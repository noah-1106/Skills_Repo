"""Manual Consumer Web drafts, evidence and immutable submission."""
from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from ..db import all_rows, dumps, loads, one, utc_now
from ..security import audit
from .measurement import _finalize_run

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS = 12
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
ATTACHMENT_TYPES = {
    "screenshot": IMAGE_TYPES,
    "raw_html": {"text/html"},
    "raw_text": {"text/plain"},
}
ACTUAL_CONTEXT_KEYS = {
    "surface", "page_mode", "networking", "deep_thinking", "deep_research", "session_mode",
    "login_state", "account_type", "region", "language", "context_clearing", "follow_up_policy",
}


def _manual_answer(conn, project: dict, answer_id: int) -> tuple[dict, dict, dict]:
    answer = one(conn, "SELECT a.*,r.wave_id,r.snapshot_json,w.protocol_json FROM answers a JOIN runs r ON r.id=a.run_id JOIN waves w ON w.id=r.wave_id WHERE a.id=? AND a.project_id=? AND a.client_id=?",
                 (answer_id, project["id"], project["client_id"]))
    if not answer:
        raise HTTPException(404, "人工采集回答不存在或不属于当前项目")
    protocol = loads(answer["protocol_json"], {})
    if protocol.get("measurement_target") != "consumer_web":
        raise HTTPException(409, "该回答不是人工 Consumer Web 采集任务")
    collection = one(conn, "SELECT * FROM web_collections WHERE answer_id=? AND project_id=?", (answer_id, project["id"]))
    if not collection:
        raise HTTPException(409, "该回答缺少人工采集记录")
    return answer, collection, protocol


def _mutable(answer: dict, collection: dict) -> None:
    if answer["status"] != "awaiting_collection" or collection["status"] == "completed":
        raise HTTPException(409, "该采集已提交或已结束，不能覆盖；失败样本请由管理员重试")


def attachment_public(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "content"} | {
        "available": row.get("content") is not None and not row.get("purged_at")
    }


def collection_public(conn, answer: dict, collection: dict, protocol: dict, *, internal: bool = True) -> dict:
    result = dict(collection)
    result["session_context"] = loads(result.pop("session_context_json"), {})
    citations = loads(result.pop("citations_json"), [])
    if not internal:
        result["draft_text"] = None
        result["notes"] = ""
        result["failure_detail"] = ""
        citations = [{key: item.get(key, "") for key in ("url", "title")} for item in citations]
    result["citations"] = citations
    result["answer_status"] = answer["status"]
    result["raw_text_sha256"] = answer.get("raw_text_sha256") or ""
    result["collection_protocol"] = protocol.get("collection_protocol")
    result["attachments"] = [attachment_public(row) for row in all_rows(
        conn, "SELECT * FROM answer_attachments WHERE answer_id=? ORDER BY id", (answer["id"],))]
    return result


def get_collection(conn, project: dict, answer_id: int, *, internal: bool = True) -> dict:
    answer, collection, protocol = _manual_answer(conn, project, answer_id)
    return collection_public(conn, answer, collection, protocol, internal=internal)


def _validate_context(session_context: dict) -> dict:
    if not isinstance(session_context, dict) or set(session_context) - ACTUAL_CONTEXT_KEYS:
        raise HTTPException(400, "采集上下文包含不支持的字段；不得保存 Cookie、密码、Token 或账号别名")
    if any(isinstance(value, (dict, list)) for value in session_context.values()):
        raise HTTPException(400, "采集上下文只能包含标量事实")
    return session_context


def _draft_values(payload: dict) -> dict:
    return {
        "draft_text": payload.get("draft_text") or "",
        "actual_url": (payload.get("actual_url") or "").strip(),
        "observed_mode": (payload.get("observed_mode") or "").strip(),
        "observed_at": (payload.get("observed_at") or "").strip(),
        "timezone": (payload.get("timezone") or "").strip(),
        "session_context": _validate_context(payload.get("session_context") or {}),
        "retrieval_status": payload.get("retrieval_status") or "unknown",
        "notes": payload.get("notes") or "",
        "citations": [dict(item) for item in payload.get("citations") or []],
    }


def save_draft(conn, project: dict, answer_id: int, payload: dict, actor: int) -> dict:
    answer, collection, protocol = _manual_answer(conn, project, answer_id)
    _mutable(answer, collection)
    values = _draft_values(payload)
    now = utc_now()
    conn.execute("""UPDATE web_collections SET status=?,draft_text=?,actual_url=?,observed_mode=?,observed_at=?,timezone=?,
                    session_context_json=?,retrieval_status=?,notes=?,citations_json=?,collector_id=?,updated_at=? WHERE id=?""",
                 (payload.get("status") or "collecting", values["draft_text"], values["actual_url"], values["observed_mode"],
                  values["observed_at"], values["timezone"], dumps(values["session_context"]), values["retrieval_status"],
                  values["notes"], dumps(values["citations"]), actor, now, collection["id"]))
    audit(conn, actor, project, "web_collection", collection["id"], "draft", None,
          {"answer_id": answer_id, "status": payload.get("status") or "collecting", "characters": len(values["draft_text"])})
    updated = one(conn, "SELECT * FROM web_collections WHERE id=?", (collection["id"],))
    return collection_public(conn, answer, updated, protocol)


def safe_filename(value: str) -> str:
    name = Path(value or "evidence.bin").name.replace("\x00", "")
    name = re.sub(r"[\r\n/\\]", "_", name).strip()[:180]
    if not name or name in (".", ".."):
        raise HTTPException(400, "证据文件名无效")
    return name


def _validate_image(content: bytes, media_type: str) -> None:
    valid = ((media_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or
             (media_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff")) or
             (media_type == "image/webp" and len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"))
    if not valid:
        raise HTTPException(400, "截图真实文件签名与 media type 不匹配")


def upload_attachment(conn, project: dict, answer_id: int, kind: str, filename: str,
                      media_type: str, content: bytes, expected_sha256: str, actor: int) -> dict:
    answer, collection, _ = _manual_answer(conn, project, answer_id)
    _mutable(answer, collection)
    if kind not in ATTACHMENT_TYPES or media_type not in ATTACHMENT_TYPES[kind]:
        raise HTTPException(400, "附件类型仅支持 PNG/JPEG/WebP 截图、text/html 或 text/plain")
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(400, "单个附件必须非空且不超过 10MB")
    count = one(conn, "SELECT COUNT(*) AS count FROM answer_attachments WHERE answer_id=?", (answer_id,))["count"]
    if count >= MAX_ATTACHMENTS:
        raise HTTPException(409, f"每个回答最多保留 {MAX_ATTACHMENTS} 个附件")
    if kind == "screenshot":
        _validate_image(content, media_type)
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 and expected_sha256.lower() != digest:
        raise HTTPException(400, "上传内容的 X-Content-SHA256 不匹配")
    now = utc_now()
    attachment_id = conn.execute("""INSERT INTO answer_attachments(client_id,project_id,answer_id,kind,filename,media_type,
                                    byte_size,sha256,content,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                                 (project["client_id"], project["id"], answer_id, kind, safe_filename(filename), media_type,
                                  len(content), digest, content, actor, now)).lastrowid
    audit(conn, actor, project, "answer_attachment", attachment_id, "upload", None,
          {"answer_id": answer_id, "kind": kind, "bytes": len(content), "sha256": digest})
    return attachment_public(one(conn, "SELECT * FROM answer_attachments WHERE id=?", (attachment_id,)))


def delete_attachment(conn, project: dict, attachment_id: int, actor: int) -> dict:
    row = one(conn, "SELECT * FROM answer_attachments WHERE id=? AND project_id=? AND client_id=?",
              (attachment_id, project["id"], project["client_id"]))
    if not row:
        raise HTTPException(404, "附件不存在或不属于当前项目")
    answer, collection, _ = _manual_answer(conn, project, row["answer_id"])
    _mutable(answer, collection)
    conn.execute("DELETE FROM answer_attachments WHERE id=?", (attachment_id,))
    audit(conn, actor, project, "answer_attachment", attachment_id, "delete_draft", attachment_public(row), None)
    return {"deleted": attachment_id}


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


def _validate_submission(conn, answer: dict, collection: dict, protocol: dict, values: dict) -> None:
    if not values["draft_text"].strip():
        raise HTTPException(422, "回答正文不能为空；空回答请登记采集失败")
    frozen = protocol.get("collection_protocol") or {}
    if _origin(values["actual_url"]) != _origin(frozen.get("product_url", "")) or _origin(values["actual_url"])[0] not in ("http", "https"):
        raise HTTPException(422, "实际页面 origin 与冻结产品入口不一致")
    actual = values["session_context"]
    for key in ACTUAL_CONTEXT_KEYS:
        if key in frozen and actual.get(key) != frozen.get(key):
            raise HTTPException(422, f"实际采集上下文与冻结协议不一致：{key}")
    if frozen.get("page_mode") and values["observed_mode"] != frozen["page_mode"]:
        raise HTTPException(422, "实际页面模型/模式与冻结协议不一致")
    try:
        observed = datetime.fromisoformat(values["observed_at"].replace("Z", "+00:00"))
        zone = ZoneInfo(values["timezone"])
        if observed.tzinfo is None or observed.utcoffset() != observed.astimezone(zone).utcoffset():
            raise ValueError
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise HTTPException(422, "采集时间必须带时区，且 UTC offset 与填写的 IANA 时区一致") from None
    citations = []
    for item in values["citations"]:
        parsed = urllib.parse.urlparse(item.get("url") or "")
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HTTPException(422, "人工页面引用必须使用有效 HTTP(S) URL")
        citations.append(item)
    values["citations"] = citations
    screenshots = all_rows(conn, "SELECT * FROM answer_attachments WHERE answer_id=? AND kind='screenshot' AND content IS NOT NULL AND purged_at IS NULL",
                           (answer["id"],))
    if not screenshots:
        raise HTTPException(422, "正式提交至少需要一张有效截图；无法采集时请登记失败")
    for screenshot in screenshots:
        content = screenshot["content"]
        if len(content) != screenshot["byte_size"] or hashlib.sha256(content).hexdigest() != screenshot["sha256"]:
            raise HTTPException(409, "截图字节、大小或 SHA-256 校验失败")
        _validate_image(content, screenshot["media_type"])


def submit_collection(conn, project: dict, answer_id: int, payload: dict, actor: int) -> dict:
    answer, collection, protocol = _manual_answer(conn, project, answer_id)
    _mutable(answer, collection)
    values = _draft_values(payload)
    _validate_submission(conn, answer, collection, protocol, values)
    now = utc_now()
    digest = hashlib.sha256(values["draft_text"].encode("utf-8")).hexdigest()
    conn.execute("""UPDATE answers SET raw_text=?,raw_text_sha256=?,status='judging',error_type=NULL,error_detail=NULL,
                    completed_at=NULL,valid_sample=NULL,content_retained=1,content_purged_at=NULL,usage_json='{}',model=? WHERE id=?""",
                 (values["draft_text"], digest, values["observed_mode"] or answer.get("model"), answer_id))
    conn.execute("""UPDATE web_collections SET status='completed',draft_text=?,actual_url=?,observed_mode=?,observed_at=?,timezone=?,
                    session_context_json=?,retrieval_status=?,notes=?,citations_json=?,collector_id=?,submitted_at=?,updated_at=?,
                    failure_type='',failure_detail='' WHERE id=?""",
                 (values["draft_text"], values["actual_url"], values["observed_mode"], values["observed_at"], values["timezone"],
                  dumps(values["session_context"]), values["retrieval_status"], values["notes"], dumps(values["citations"]),
                  actor, now, now, collection["id"]))
    conn.execute("DELETE FROM citations WHERE answer_id=?", (answer_id,))
    for item in values["citations"]:
        parsed = urllib.parse.urlparse(item["url"])
        citation_hash = hashlib.sha256(((item.get("title") or "") + (item.get("text") or "")).encode()).hexdigest()
        conn.execute("""INSERT INTO citations(client_id,project_id,answer_id,raw_url,final_url,title,domain,source_type,
                        content_hash,returned_at,origin) VALUES(?,?,?,?,?,?,?,?,?,?, 'manual_page')""",
                     (project["client_id"], project["id"], answer_id, item["url"], item["url"], item.get("title") or "",
                      parsed.hostname, "人工记录的页面引用", citation_hash, values["observed_at"]))
    audit(conn, actor, project, "web_collection", collection["id"], "submit", None,
          {"answer_id": answer_id, "raw_text_sha256": digest, "citations": len(values["citations"]),
           "screenshots": one(conn, "SELECT COUNT(*) AS count FROM answer_attachments WHERE answer_id=? AND kind='screenshot'", (answer_id,))["count"]})
    updated_answer = one(conn, "SELECT * FROM answers WHERE id=?", (answer_id,))
    updated = one(conn, "SELECT * FROM web_collections WHERE id=?", (collection["id"],))
    return collection_public(conn, updated_answer, updated, protocol)


def fail_collection(conn, project: dict, answer_id: int, payload: dict, actor: int) -> dict:
    answer, collection, protocol = _manual_answer(conn, project, answer_id)
    _mutable(answer, collection)
    now = utc_now()
    conn.execute("UPDATE answers SET status='failed',valid_sample=0,error_type=?,error_detail=?,completed_at=? WHERE id=?",
                 (payload["failure_type"], payload["failure_detail"], now, answer_id))
    conn.execute("""UPDATE web_collections SET status='failed',failure_type=?,failure_detail=?,notes=?,collector_id=?,updated_at=? WHERE id=?""",
                 (payload["failure_type"], payload["failure_detail"], payload.get("notes") or collection["notes"],
                  actor, now, collection["id"]))
    audit(conn, actor, project, "web_collection", collection["id"], "fail", None,
          {"answer_id": answer_id, "failure_type": payload["failure_type"], "valid_sample": 0})
    _finalize_run(conn, answer["run_id"])
    updated = one(conn, "SELECT * FROM web_collections WHERE id=?", (collection["id"],))
    return collection_public(conn, one(conn, "SELECT * FROM answers WHERE id=?", (answer_id,)), updated, protocol)


def get_attachment(conn, project: dict, attachment_id: int) -> dict:
    row = one(conn, "SELECT * FROM answer_attachments WHERE id=? AND project_id=? AND client_id=?",
              (attachment_id, project["id"], project["client_id"]))
    if not row:
        raise HTTPException(404, "附件不存在或不属于当前项目")
    if row["content"] is None or row["purged_at"]:
        raise HTTPException(410, "附件字节已按保留策略清理，仅保留 hash 与大小 tombstone")
    content = row["content"]
    if len(content) != row["byte_size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
        raise HTTPException(409, "附件校验失败，拒绝下载")
    return row
