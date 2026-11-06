"""Immutable brand entity cards and review workflows."""
from __future__ import annotations

from fastapi import HTTPException

from ..db import all_rows, dumps, one, utc_now
from ..engine.analyzer import alias_conflicts
from ..security import audit
from .measurement import entity_public
from .state import logical_id


def create_entity(conn, project: dict, actor: int, payload: dict, allow_conflicts: bool = False) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "品牌名不能为空")
    role = payload.get("role") or "competitor"
    if role not in ("primary", "competitor", "candidate"):
        raise HTTPException(400, "无效实体角色")
    card = payload.get("entity_card") or {}
    candidate = {"id": 0, "name": name, "entity_card": card}
    existing = [entity_public(row) for row in all_rows(conn,
        "SELECT * FROM brand_entities WHERE project_id=? AND valid_to IS NULL AND status!='rejected'", (project["id"],))]
    conflicts = alias_conflicts([*existing, candidate])
    if conflicts and not allow_conflicts:
        raise HTTPException(409, {"message": "别名存在冲突，需要管理员确认", "conflicts": conflicts})
    logical = payload.get("logical_id") or logical_id("brand")
    previous = one(conn, "SELECT MAX(version) AS value FROM brand_entities WHERE project_id=? AND logical_id=?",
                   (project["id"], logical))
    version = int(previous["value"] or 0) + 1
    entity_id = conn.execute("INSERT INTO brand_entities(client_id,project_id,logical_id,role,name,entity_card_json,version,valid_from,status,review_reason,created_at) VALUES(?,?,?,?,?,?,?,?, 'draft',?,?)",
                             (project["client_id"], project["id"], logical, role, name, dumps(card), version,
                              utc_now(), payload.get("review_reason") or "", utc_now())).lastrowid
    row = one(conn, "SELECT * FROM brand_entities WHERE id=?", (entity_id,))
    audit(conn, actor, project, "brand_entity", entity_id, "create", None, row)
    return row


def review_entity(conn, entity: dict, actor: int, decision: str, reason: str, role: str | None = None) -> dict:
    if entity["status"] not in ("draft", "pending_review"):
        raise HTTPException(409, "该实体版本已经审核；请创建新版本")
    if decision not in ("confirmed", "rejected"):
        raise HTTPException(400, "审核结果必须为 confirmed 或 rejected")
    if not reason.strip():
        raise HTTPException(400, "实体审核必须填写消歧依据")
    new_role = role or ("competitor" if entity["role"] == "candidate" and decision == "confirmed" else entity["role"])
    now = utc_now()
    if decision == "confirmed":
        conn.execute("UPDATE brand_entities SET valid_to=? WHERE project_id=? AND logical_id=? AND id!=? AND valid_to IS NULL",
                     (now, entity["project_id"], entity["logical_id"], entity["id"]))
        if new_role == "primary":
            conn.execute("UPDATE brand_entities SET valid_to=? WHERE project_id=? AND role='primary' AND id!=? AND valid_to IS NULL",
                         (now, entity["project_id"], entity["id"]))
    conn.execute("UPDATE brand_entities SET status=?,role=?,reviewed_by=?,review_reason=? WHERE id=?",
                 (decision, new_role, actor, reason.strip(), entity["id"]))
    after = one(conn, "SELECT * FROM brand_entities WHERE id=?", (entity["id"],))
    audit(conn, actor, entity, "brand_entity", entity["id"], "review", entity, after)
    return after


def new_version(conn, entity: dict, actor: int, payload: dict) -> dict:
    project = {"id": entity["project_id"], "client_id": entity["client_id"]}
    return create_entity(conn, project, actor, {
        "logical_id": entity["logical_id"], "name": payload.get("name") or entity["name"],
        "role": payload.get("role") or entity["role"],
        "entity_card": payload.get("entity_card") or loads_card(entity),
        "review_reason": payload.get("review_reason") or "创建实体新版本",
    }, allow_conflicts=bool(payload.get("allow_conflicts")))


def loads_card(entity: dict) -> dict:
    from ..db import loads
    return loads(entity.get("entity_card_json"), {})


def pool_diff(conn, before_ids: list[int], after_ids: list[int], project_id: int) -> dict:
    before = {row["id"]: entity_public(row) for row in all_rows(conn,
        f"SELECT * FROM brand_entities WHERE project_id=? AND id IN ({','.join('?' * len(before_ids))})", [project_id, *before_ids])} if before_ids else {}
    after = {row["id"]: entity_public(row) for row in all_rows(conn,
        f"SELECT * FROM brand_entities WHERE project_id=? AND id IN ({','.join('?' * len(after_ids))})", [project_id, *after_ids])} if after_ids else {}
    return {"added": [after[key] for key in set(after) - set(before)],
            "removed": [before[key] for key in set(before) - set(after)],
            "changed": [{"before": before[key], "after": after[key]} for key in set(before) & set(after)
                        if before[key]["entity_card"] != after[key]["entity_card"]]}
