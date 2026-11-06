"""Versioned prompt-set design, review, import and scaffolding."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from typing import Iterable

from fastapi import HTTPException

from ..db import all_rows, dumps, loads, one, utc_now
from ..security import audit
from .state import logical_id, transition

ITEM_FIELDS = ("text", "canonical_intent_id", "dimension", "funnel_stage", "query_type", "persona",
               "scenario", "market", "language", "price_band", "source", "priority", "eligibility", "fields")
DIMENSIONS = {"brand", "scene", "compare", "choice"}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def redact_private(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱]", text)
    return re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号]", text)


def create_set(conn, project: dict, actor: int, name: str, weights: dict | None = None) -> dict:
    version = (one(conn, "SELECT MAX(version) AS value FROM prompt_sets WHERE project_id=?", (project["id"],))["value"] or 0) + 1
    set_id = conn.execute("INSERT INTO prompt_sets(client_id,project_id,name,version,weights_json,created_at) VALUES(?,?,?,?,?,?)",
                          (project["client_id"], project["id"], name.strip(), version,
                           dumps(weights or {}), utc_now())).lastrowid
    row = one(conn, "SELECT * FROM prompt_sets WHERE id=?", (set_id,))
    audit(conn, actor, project, "prompt_set", set_id, "create", None, row)
    return row


def add_items(conn, prompt_set: dict, actor: int, items: Iterable[dict], redact: bool = False) -> list[dict]:
    if prompt_set["status"] != "draft":
        raise HTTPException(409, "只有草稿问题集可以编辑；请复制新版本")
    inserted = []
    duplicates = []
    seen = {row["text"].casefold() for row in conn.execute("SELECT text FROM prompt_items WHERE prompt_set_id=?", (prompt_set["id"],))}
    for item in items:
        text = normalize_text(item.get("text") or "")
        if redact:
            text = redact_private(text)
        if text.casefold() in seen:
            duplicates.append(text)
            continue
        seen.add(text.casefold())
        if not text:
            raise HTTPException(400, "Prompt 文本不能为空")
        if item.get("dimension") not in DIMENSIONS:
            raise HTTPException(400, "每条 Prompt 必须选择四维分类")
        query_type = item.get("query_type") or "discovery"
        if query_type not in ("discovery", "navigation"):
            raise HTTPException(400, "query_type 必须为 discovery 或 navigation")
        priority = int(item.get("priority", 3))
        if not 1 <= priority <= 5:
            raise HTTPException(400, "优先级必须为 1–5")
        canonical = normalize_text(item.get("canonical_intent_id") or "") or logical_id("intent")
        values = {field: item.get(field) for field in ITEM_FIELDS}
        item_id = conn.execute(
            "INSERT INTO prompt_items(client_id,project_id,prompt_set_id,logical_id,canonical_intent_id,text,dimension,funnel_stage,query_type,persona,scenario,market,language,price_band,source,priority,eligibility,fields_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (prompt_set["client_id"], prompt_set["project_id"], prompt_set["id"], logical_id("item"), canonical,
             text, item["dimension"], item.get("funnel_stage") or "考虑", query_type,
             item.get("persona") or "", item.get("scenario") or "", item.get("market") or "",
             item.get("language") or "zh-CN", item.get("price_band") or "", item.get("source") or "专家设计",
             priority, item.get("eligibility") or "unknown", dumps(item.get("fields") or {}), utc_now())).lastrowid
        inserted.append(one(conn, "SELECT * FROM prompt_items WHERE id=?", (item_id,)))
    audit(conn, actor, prompt_set, "prompt_set", prompt_set["id"], "add_items", None,
          {"count": len(inserted), "duplicates": len(duplicates)})
    return {"items": inserted, "duplicates": duplicates}


def review_item(conn, prompt_set: dict, item_id: int, actor: int, status: str, eligibility: str | None) -> dict:
    if prompt_set["status"] not in ("draft", "reviewing"):
        raise HTTPException(409, "冻结后不能修改题目审核状态")
    if status not in ("reviewed", "rejected", "draft"):
        raise HTTPException(400, "无效审核状态")
    item = one(conn, "SELECT * FROM prompt_items WHERE id=? AND prompt_set_id=?", (item_id, prompt_set["id"]))
    if not item:
        raise HTTPException(404, "题目不存在")
    conn.execute("UPDATE prompt_items SET status=?,eligibility=COALESCE(?,eligibility) WHERE id=?",
                 (status, eligibility, item_id))
    after = one(conn, "SELECT * FROM prompt_items WHERE id=?", (item_id,))
    audit(conn, actor, prompt_set, "prompt_item", item_id, "review", item, after)
    return after


def content_hash(items: list[dict]) -> str:
    keys = ("logical_id", "canonical_intent_id", "text", "dimension", "funnel_stage", "query_type",
            "persona", "scenario", "market", "language", "price_band", "priority", "eligibility", "fields_json")
    normalized = [{key: item.get(key) for key in keys} for item in sorted(items, key=lambda row: row["logical_id"])]
    return hashlib.sha256(dumps(normalized).encode()).hexdigest()


def freeze_set(conn, prompt_set: dict, actor: int, project: dict) -> dict:
    if prompt_set["status"] != "reviewing":
        raise HTTPException(409, "请先进入审核状态")
    items = all_rows(conn, "SELECT * FROM prompt_items WHERE prompt_set_id=? AND status!='rejected'", (prompt_set["id"],))
    if not items:
        raise HTTPException(409, "没有可冻结的有效题目")
    unreviewed = [item["id"] for item in items if item["status"] != "reviewed"]
    if unreviewed:
        raise HTTPException(409, f"仍有 {len(unreviewed)} 条题目未逐条审核")
    counts = {dimension: sum(item["dimension"] == dimension for item in items) for dimension in DIMENSIONS}
    settings = loads(project["settings_json"], {})
    quotas = settings.get("prompt_quotas") or {dimension: 1 for dimension in DIMENSIONS}
    missing = {dimension: {"required": quotas.get(dimension, 0), "actual": counts[dimension]}
               for dimension in DIMENSIONS if counts[dimension] < int(quotas.get(dimension, 0))}
    if missing:
        raise HTTPException(409, {"message": "问题集分层配额不足", "quotas": missing})
    now = utc_now()
    conn.execute("UPDATE prompt_items SET status='frozen' WHERE prompt_set_id=? AND status='reviewed'", (prompt_set["id"],))
    items = all_rows(conn, "SELECT * FROM prompt_items WHERE prompt_set_id=? AND status='frozen'", (prompt_set["id"],))
    return transition(conn, "prompt_sets", prompt_set, "frozen", actor,
                      extra={"frozen_at": now, "content_hash": content_hash(items)})


def copy_set(conn, prompt_set: dict, actor: int, name: str | None = None) -> dict:
    new_set = create_set(conn, {"id": prompt_set["project_id"], "client_id": prompt_set["client_id"]}, actor,
                         name or f"{prompt_set['name']}（新版本）", loads(prompt_set["weights_json"], {}))
    items = all_rows(conn, "SELECT * FROM prompt_items WHERE prompt_set_id=?", (prompt_set["id"],))
    for item in items:
        conn.execute("INSERT INTO prompt_items(client_id,project_id,prompt_set_id,logical_id,canonical_intent_id,text,dimension,funnel_stage,query_type,persona,scenario,market,language,price_band,source,priority,eligibility,status,version,fields_json,created_at) SELECT client_id,project_id,?,logical_id,canonical_intent_id,text,dimension,funnel_stage,query_type,persona,scenario,market,language,price_band,source,priority,eligibility,'draft',version+1,fields_json,? FROM prompt_items WHERE id=?",
                     (new_set["id"], utc_now(), item["id"]))
    return one(conn, "SELECT * FROM prompt_sets WHERE id=?", (new_set["id"],))


def diff_sets(before: list[dict], after: list[dict]) -> dict:
    left, right = {item["logical_id"]: item for item in before}, {item["logical_id"]: item for item in after}
    changed = []
    for logical in set(left) & set(right):
        fields = [field for field in ITEM_FIELDS if field != "fields" and left[logical].get(field) != right[logical].get(field)]
        if fields:
            changed.append({"logical_id": logical, "fields": fields, "before": left[logical], "after": right[logical]})
    return {"added": [right[key] for key in set(right) - set(left)],
            "removed": [left[key] for key in set(left) - set(right)], "changed": changed}


def scaffold(brand: str, category: str, competitors: list[str], market: str = "CN") -> list[dict]:
    competitor = competitors[0] if competitors else "其他方案"
    specs = [
        ("brand-overview", "brand", f"{brand} 是什么？主要解决什么问题？", "navigation"),
        ("brand-overview", "brand", f"请介绍 {brand} 的产品定位和用途。", "navigation"),
        ("brand-fit", "brand", f"{brand} 适合哪些团队和场景？", "navigation"),
        ("brand-fit", "brand", f"哪些用户应该考虑 {brand}，哪些不适合？", "navigation"),
        ("scene-monitor", "scene", f"市场团队如何监测 AI 回答中的{category}表现？", "discovery"),
        ("scene-monitor", "scene", f"企业怎么持续追踪{category}效果？", "discovery"),
        ("scene-budget", "scene", f"预算有限的团队怎么做{category}效果追踪？", "discovery"),
        ("scene-budget", "scene", f"小团队第一次做{category}诊断，应该先做什么？", "discovery"),
        ("compare-private", "compare", f"{brand} 和 {competitor} 哪个更适合私有化部署？", "navigation"),
        ("compare-private", "compare", f"需要自托管时，{brand}与{competitor}怎么选？", "navigation"),
        ("compare-evidence", "compare", f"{brand} 与 {competitor} 在证据审计方面有什么区别？", "navigation"),
        ("compare-evidence", "compare", f"比较 {brand} 和 {competitor} 的证据复核能力。", "navigation"),
        ("choice-list", "choice", f"有哪些值得评估的{category}工具？", "discovery"),
        ("choice-list", "choice", f"请推荐几类{category}方案并说明差异。", "discovery"),
        ("choice-eval", "choice", f"选择{category}工具时应该看哪些指标？", "discovery"),
        ("choice-eval", "choice", f"如何比较不同{category}产品的真实能力？", "discovery"),
    ]
    return [{"text": text, "dimension": dimension, "query_type": query_type,
             "canonical_intent_id": canonical, "source": "AI扩展", "priority": 4,
             "scenario": category, "market": market, "eligibility": "unknown"}
            for canonical, dimension, text, query_type in specs]


def export_csv(items: list[dict]) -> str:
    output = io.StringIO()
    fields = ["text", "canonical_intent_id", "dimension", "funnel_stage", "query_type", "persona", "scenario",
              "market", "language", "price_band", "source", "priority", "eligibility"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(items)
    return output.getvalue()
