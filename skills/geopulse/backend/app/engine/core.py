"""GeoPulse 监测引擎：runner（执行）+ analyzer（解析）。

节点纪律：文件/数据库进，文件/数据库出，独立失败。
"""
from __future__ import annotations
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from ..providers.llm import build_provider, build_engines, ProviderError

import os
DB_PATH = Path(os.environ.get("GEOPULSE_DB") or (Path(__file__).resolve().parent.parent.parent / "geopulse.db"))
CONFIG_PATH = Path(os.environ.get("GEOPULSE_CONFIG") or (Path(__file__).resolve().parent.parent.parent / "config.json"))


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_settings() -> dict:
    if CONFIG_PATH.is_file():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_settings(s: dict):
    CONFIG_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    CONFIG_PATH.chmod(0o600)


# ---------------- analyzer ----------------

REC_WORDS = ["推荐", "建议", "首选", "值得考虑", "可以考虑", "优选", "优先选择", "可以看看",
             "不错的选择", "推荐使用", "选择", "不妨", "试试"]
DESC_WORDS = ["是", "提供", "支持", "拥有", "适合", "主打", "特点", "优势", "定位", "核心",
              "功能", "平台", "工具", "产品"]


def _depth_for(text_lower: str, name_lower: str) -> str:
    """引用深度三级（引引方法论：仅提名/有描述/有推荐）。规则版 v1。"""
    import re
    positions = [m.start() for m in re.finditer(re.escape(name_lower), text_lower)]
    if not positions:
        return ""
    for p in positions:
        window = text_lower[max(0, p - 30):p + 50]
        if any(w in window for w in REC_WORDS):
            return "recommended"
    for p in positions:
        window = text_lower[max(0, p - 20):p + 60]
        if any(w in window for w in DESC_WORDS):
            return "described"
    return "mentioned"


def analyze_mentions(answer_text: str, brands):
    """确定性提及解析：别名表匹配 + 深度判定。brands: [{name, aliases:[...]}]
    返回 {品牌名: depth}（mentioned/described/recommended）。"""
    text = answer_text.lower()
    result = {}
    for b in brands:
        names = [b["name"]] + list(b.get("aliases") or [])
        for alias in names:
            a = alias.lower().strip()
            if a and a in text:
                result[b["name"]] = _depth_for(text, b["name"].lower())
                break
    return result


# ---------------- runner ----------------

def start_run(scope="all", prompt_ids=None) -> int:
    """创建 run 记录。scope: all | active | custom(prompt_ids)"""
    conn = db()
    cur = conn.execute(
        "INSERT INTO runs (status, scope, started_at) VALUES ('pending', ?, ?)",
        (scope, datetime.now().isoformat(timespec="seconds")))
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def execute_run(run_id: int, max_prompts=None):
    """同步执行一次监测（v1 不做后台队列——数据量小，同步即生产可用）。"""
    conn = db()
    run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        conn.close()
        raise ValueError(f"run {run_id} not found")

    settings = load_settings()
    brands = []
    for r in conn.execute("SELECT name, aliases FROM brands ORDER BY is_primary DESC, name"):
        b = dict(r)
        raw = b.get("aliases") or "[]"
        b["aliases"] = json.loads(raw) if isinstance(raw, str) else (raw or [])
        brands.append(b)
    if not brands:
        conn.execute("UPDATE runs SET status='failed', error='无监测品牌' WHERE id=?", (run_id,))
        conn.commit()
        conn.close()
        raise ProviderError("无监测品牌：先在品牌页添加至少一个品牌")

    if run["scope"] == "active":
        prompts = conn.execute("SELECT * FROM prompts WHERE is_active=1").fetchall()
    elif run["scope"] == "custom" and run.get("prompt_ids"):
        ids = json.loads(run["prompt_ids"])
        marks = ",".join("?" * len(ids))
        prompts = conn.execute(f"SELECT * FROM prompts WHERE id IN ({marks})", ids).fetchall()
    else:
        prompts = conn.execute("SELECT * FROM prompts").fetchall()

    prompts = [dict(p) for p in prompts]
    if max_prompts:
        prompts = prompts[:max_prompts]
    if not prompts:
        conn.execute("UPDATE runs SET status='failed', error='无 prompt' WHERE id=?", (run_id,))
        conn.commit()
        conn.close()
        raise ProviderError("无 prompt：先在 prompt 页添加至少一条")

    try:
        engines = build_engines(settings, seed_brands=[b["name"] for b in brands])
    except ProviderError as e:
        conn.execute("UPDATE runs SET status='failed', error=? WHERE id=?", (str(e), run_id))
        conn.commit()
        conn.close()
        raise

    total = len(prompts) * len(engines)
    conn.execute("UPDATE runs SET status='running', provider=?, model=?, total=? WHERE id=?",
                 ("multi" if len(engines) > 1 else engines[0][0],
                  ",".join(getattr(p, "model", name) for name, p in engines), total, run_id))
    conn.commit()

    done, failed = 0, 0
    errors = []
    for engine_label, provider in engines:
        for p in prompts:
            try:
                answer, meta = provider.ask(p["text"])
                mentioned = analyze_mentions(answer, brands)  # {name: depth}
                conn.execute(
                    "INSERT INTO answers (run_id, prompt_id, answer_text, mentioned_brands, "
                    "depth, engine, provider, model, latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (run_id, p["id"], answer,
                     json.dumps(list(mentioned.keys()), ensure_ascii=False),
                     json.dumps(mentioned, ensure_ascii=False),
                     engine_label, provider.name, meta.get("model"), meta.get("latency_ms"),
                     datetime.now().isoformat(timespec="seconds")))
                done += 1
            except ProviderError as e:
                failed += 1
                errors.append(f"{engine_label}/p{p['id']}: {e}")
            except Exception as e:  # 单条失败不拖垮整跑
                failed += 1
                errors.append(f"{engine_label}/p{p['id']}: {type(e).__name__} {e}")
            conn.execute("UPDATE runs SET done=? WHERE id=?", (done, run_id))
            conn.commit()

    status = "done" if failed == 0 else ("partial" if done > 0 else "failed")
    err_note = "; ".join(errors[:5]) if errors else None
    conn.execute("UPDATE runs SET status=?, finished_at=?, error=? WHERE id=?",
                 (status, datetime.now().isoformat(timespec="seconds"), err_note, run_id))
    conn.commit()
    conn.close()
    return {"run_id": run_id, "done": done, "failed": failed}


# ---------------- insights ----------------

def overview(brand_id=None, days=30, exclude_demo=True):
    """可见率/份额/趋势。brand_id=None 时对主品牌。
    exclude_demo: demo 引擎的回答是确定性模板（必提主品牌），默认排除统计。"""
    conn = db()
    if brand_id:
        brand = conn.execute("SELECT * FROM brands WHERE id=?", (brand_id,)).fetchone()
    else:
        brand = conn.execute("SELECT * FROM brands WHERE is_primary=1 ORDER BY id LIMIT 1").fetchone()
    if brand is None:
        conn.close()
        return {"error": "no brand"}
    brand_name = brand["name"]

    rows = conn.execute(
        "SELECT a.run_id, a.mentioned_brands, a.depth, a.engine, a.created_at, r.status, "
        "p.dimension, p.text AS prompt_text "
        "FROM answers a JOIN runs r ON a.run_id=r.id JOIN prompts p ON a.prompt_id=p.id "
        "WHERE a.created_at >= datetime('now', ?) AND r.status IN ('done','partial') "
        + ("AND a.provider != 'demo' " if exclude_demo else "")
        + "ORDER BY a.id", (f'-{int(days)} days',)).fetchall()

    total_prompts = len(rows)
    brand_rows = [r for r in rows if brand_name in json.loads(r["mentioned_brands"] or "[]")]

    # 四维分组（引引：品牌词/场景词/对比词/选购词）
    dim_names = {"brand": "品牌词", "scene": "场景词", "compare": "对比词", "choice": "选购词"}
    by_dimension = {}
    for r in rows:
        dim = r["dimension"] or "other"
        d = by_dimension.setdefault(dim, {"total": 0, "hit": 0})
        d["total"] += 1
        if brand_name in json.loads(r["mentioned_brands"] or "[]"):
            d["hit"] += 1
    dimensions = [{"key": k, "name": dim_names.get(k, k),
                   "visibility": round(v["hit"] / v["total"] * 100, 1) if v["total"] else 0,
                   "samples": v["total"]} for k, v in by_dimension.items()]

    # 引擎分组
    by_engine = {}
    for r in rows:
        eng = r["engine"] or (r["provider"] or "unknown")
        e = by_engine.setdefault(eng, {"total": 0, "hit": 0})
        e["total"] += 1
        if brand_name in json.loads(r["mentioned_brands"] or "[]"):
            e["hit"] += 1
    engines_stat = [{"engine": k,
                     "visibility": round(v["hit"] / v["total"] * 100, 1) if v["total"] else 0,
                     "samples": v["total"]} for k, v in by_engine.items()]

    # 深度分布（主品牌）
    depth_counter = {}
    for r in brand_rows:
        dep = json.loads(r["depth"] or "{}").get(brand_name) or "mentioned"
        depth_counter[dep] = depth_counter.get(dep, 0) + 1
    visibility = round(len(brand_rows) / total_prompts * 100, 1) if total_prompts else 0.0

    mention_counter = {}
    for r in rows:
        for m in json.loads(r["mentioned_brands"] or "[]"):
            mention_counter[m] = mention_counter.get(m, 0) + 1
    total_mentions = sum(mention_counter.values())
    sov = round(mention_counter.get(brand_name, 0) / total_mentions * 100, 1) if total_mentions else 0.0

    # 按天趋势
    by_day = {}
    for r in rows:
        day = (r["created_at"] or "")[:10]
        d = by_day.setdefault(day, {"total": 0, "hit": 0})
        d["total"] += 1
        if brand_name in json.loads(r["mentioned_brands"] or "[]"):
            d["hit"] += 1
    trend = [{"day": k, "visibility": round(v["hit"] / v["total"] * 100, 1) if v["total"] else 0,
              "prompts": v["total"]} for k, v in sorted(by_day.items())]

    competitors = [{"name": k, "mentions": v,
                    "sov": round(v / total_mentions * 100, 1) if total_mentions else 0}
                   for k, v in sorted(mention_counter.items(), key=lambda x: -x[1])]

    recent = conn.execute(
        "SELECT a.id, a.prompt_id, p.text AS prompt_text, p.dimension, a.mentioned_brands, "
        "a.depth, a.engine, a.answer_text, a.created_at, a.provider, a.model "
        "FROM answers a JOIN prompts p ON a.prompt_id=p.id "
        + ("WHERE a.provider != 'demo' " if exclude_demo else "")
        + "ORDER BY a.id DESC LIMIT 20").fetchall()

    conn.close()
    return {
        "brand": brand_name, "days": days,
        "visibility": visibility, "share_of_voice": sov,
        "total_prompts": total_prompts, "brand_mentions": mention_counter.get(brand_name, 0),
        "trend": trend, "competitors": competitors,
        "dimensions": dimensions, "engines": engines_stat, "depth": depth_counter,
        "recent": [dict(r) for r in recent],
    }
