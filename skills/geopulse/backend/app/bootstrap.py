"""First-run demo workspace and optional legacy engine import.

No legacy answers are imported. The previous workspace was explicitly disposable test data.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets

from . import config
from .db import connect, dumps, one, utc_now
from .security import SecretStore, hash_password
from .services.state import logical_id


def seed_demo() -> None:
    with connect() as conn:
        project = one(conn, "SELECT * FROM projects ORDER BY id LIMIT 1")
        if project is None:
            now = utc_now()
            client_id = conn.execute("INSERT INTO clients(name,created_at) VALUES(?,?)",
                                     ("演示客户", now)).lastrowid
            project_id = conn.execute(
                "INSERT INTO projects(client_id,name,category,market,language,settings_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (client_id, "GEO 演示项目", "AI 品牌可见性监测", "CN", "zh-CN",
                 dumps(config.DEFAULT_PROJECT_SETTINGS), now)).lastrowid
            project = one(conn, "SELECT * FROM projects WHERE id=?", (project_id,))
            conn.execute("INSERT INTO engine_configs(client_id,project_id,name,vendor,kind,mode,created_at) VALUES(?,?,?,?,?,?,?)",
                         (client_id, project_id, "demo", "GeoPulse", "demo", "memory", now))
            _seed_entities(conn, project)
            _seed_prompts(conn, project)
            conn.commit()
        if not one(conn, "SELECT id FROM users LIMIT 1"):
            email = os.environ.get("GEOPULSE_ADMIN_EMAIL", "admin@geopulse.local")
            password = os.environ.get("GEOPULSE_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
            user_id = conn.execute("INSERT INTO users(email,password_hash,global_role,created_at) VALUES(?,?,?,?)",
                                   (email, hash_password(password), "admin", utc_now())).lastrowid
            conn.execute("INSERT INTO memberships(client_id,project_id,user_id,role,created_at) VALUES(?,?,?,?,?)",
                         (project["client_id"], project["id"], user_id, "admin", utc_now()))
            conn.commit()
            print(f"[GeoPulse] 初始管理员：{email}\n[GeoPulse] 一次性密码：{password}\n请登录后立即更换。", flush=True)
    _import_legacy_engines()


def _seed_entities(conn, project: dict) -> None:
    now = utc_now()
    rows = [
        ("primary", "GeoPulse", {"aliases": ["Geo Pulse"], "category": "GEO 品牌可见性监测软件",
                                  "company": "GeoPulse", "domain": "", "region": "CN",
                                  "exclude_contexts": ["地质", "地球物理", "地震监测"]}),
        ("competitor", "Profound", {"aliases": ["profound.io"], "category": "GEO 监测软件"}),
        ("competitor", "Otterly", {"aliases": ["otterly.ai"], "category": "GEO 监测软件"}),
    ]
    for role, name, card in rows:
        conn.execute("INSERT INTO brand_entities(client_id,project_id,logical_id,role,name,entity_card_json,version,valid_from,status,created_at) VALUES(?,?,?,?,?,?,1,?,'confirmed',?)",
                     (project["client_id"], project["id"], logical_id("brand"), role, name, dumps(card), now, now))


def _seed_prompts(conn, project: dict) -> None:
    now = utc_now()
    set_id = conn.execute("INSERT INTO prompt_sets(client_id,project_id,name,version,status,frozen_at,created_at) VALUES(?,?,?,1,'frozen',?,?)",
                          (project["client_id"], project["id"], "GEO 工具发现题基线", now, now)).lastrowid
    prompts = [
        ("intent-brand", "GeoPulse 是什么类型的工具？", "brand", "navigation"),
        ("intent-brand-2", "GeoPulse 适合哪些团队？", "brand", "navigation"),
        ("intent-scene", "小团队想监测 AI 回答里的品牌表现，应该用什么工具？", "scene", "discovery"),
        ("intent-scene-2", "企业做 GEO 诊断前，如何先摸清品牌可见性？", "scene", "discovery"),
        ("intent-compare", "GeoPulse 和 Profound 的功能定位有什么不同？", "compare", "navigation"),
        ("intent-compare-2", "自托管 GEO 工具和 SaaS 监测平台怎么比较？", "compare", "discovery"),
        ("intent-choice", "有哪些可自托管的 AI 品牌可见性监测工具？", "choice", "discovery"),
        ("intent-choice-2", "预算有限的团队如何选择 GEO 监测工具？", "choice", "discovery"),
    ]
    for index, (intent, text, dimension, query_type) in enumerate(prompts, 1):
        conn.execute("INSERT INTO prompt_items(client_id,project_id,prompt_set_id,logical_id,canonical_intent_id,text,dimension,funnel_stage,query_type,scenario,market,language,source,priority,eligibility,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (project["client_id"], project["id"], set_id, logical_id("item"), intent, text,
                      dimension, "考虑", query_type, "GEO 诊断", "CN", "zh-CN", "专家设计",
                      4 if query_type == "discovery" else 2, "eligible", "frozen", now))
    rows = conn.execute("SELECT id,logical_id,canonical_intent_id,text,dimension,query_type FROM prompt_items WHERE prompt_set_id=? ORDER BY id", (set_id,)).fetchall()
    content = dumps([dict(row) for row in rows])
    conn.execute("UPDATE prompt_sets SET content_hash=? WHERE id=?", (hashlib.sha256(content.encode()).hexdigest(), set_id))


def _import_legacy_engines() -> None:
    path = config.legacy_config_path()
    if not path.is_file():
        return
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    path.chmod(0o600)
    store = SecretStore()
    with connect() as conn:
        project = one(conn, "SELECT * FROM projects ORDER BY id LIMIT 1")
        if not project:
            return
        for engine in settings.get("engines") or []:
            if engine.get("kind") != "openai_compat":
                continue
            name = engine.get("name") or engine.get("model") or "openai"
            if one(conn, "SELECT id FROM engine_configs WHERE project_id=? AND name=?", (project["id"], name)):
                continue
            ref = store.put(engine.get("api_key") or "")
            vendor = "DeepSeek" if "deepseek" in (engine.get("base_url") or "") else "OpenAI-compatible"
            conn.execute("INSERT INTO engine_configs(client_id,project_id,name,vendor,kind,model,base_url,secret_ref,mode,created_at) VALUES(?,?,?,?,?,?,?,?, 'memory',?)",
                         (project["client_id"], project["id"], name, vendor, "openai_compat",
                          engine.get("model") or "", engine.get("base_url") or "", ref, utc_now()))
        conn.commit()
