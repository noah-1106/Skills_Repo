"""GeoPulse API：brands / prompts / runs / insights / settings。"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..engine import core
from ..engine.core import analyze_mentions

app = FastAPI(title="GeoPulse", version="1.0.0",
              description="自托管 AI 品牌可见性监测台（GEO）")

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent.parent / "frontend"


# ---------- models ----------

class BrandIn(BaseModel):
    name: str
    aliases: list = []
    is_primary: bool = False


class PromptIn(BaseModel):
    text: str
    intent: str = ""
    dimension: str = ""   # brand | scene | compare | choice（引引四维）
    is_active: bool = True


class RunIn(BaseModel):
    scope: str = "all"          # all | active | custom
    prompt_ids: Optional[list] = None
    max_prompts: Optional[int] = None


class SettingsIn(BaseModel):
    provider: Optional[dict] = None
    engines: Optional[list] = None


# ---------- brands ----------

@app.get("/api/brands")
def list_brands():
    with core.db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM brands ORDER BY is_primary DESC, name")]
    for r in rows:
        r["aliases"] = json.loads(r["aliases"] or "[]")
    return {"items": rows}


@app.post("/api/brands")
def add_brand(b: BrandIn):
    if not b.name.strip():
        raise HTTPException(400, "品牌名不能为空")
    with core.db() as conn:
        if b.is_primary:
            conn.execute("UPDATE brands SET is_primary=0")
        cur = conn.execute(
            "INSERT INTO brands (name, aliases, is_primary) VALUES (?,?,?)",
            (b.name.strip(), json.dumps(b.aliases, ensure_ascii=False), int(b.is_primary)))
        new_id = cur.lastrowid
        conn.commit()
    return {"id": new_id, "name": b.name.strip()}


@app.delete("/api/brands/{brand_id}")
def del_brand(brand_id: int):
    with core.db() as conn:
        cur = conn.execute("DELETE FROM brands WHERE id=?", (brand_id,))
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "brand not found")
    return {"deleted": brand_id}


# ---------- prompts ----------

@app.get("/api/prompts")
def list_prompts():
    with core.db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM prompts ORDER BY id DESC")]
    return {"items": rows}


@app.post("/api/prompts")
def add_prompt(p: PromptIn):
    if not p.text.strip():
        raise HTTPException(400, "prompt 不能为空")
    with core.db() as conn:
        cur = conn.execute(
            "INSERT INTO prompts (text, intent, dimension, is_active) VALUES (?,?,?,?)",
            (p.text.strip(), p.intent, p.dimension, int(p.is_active)))
        new_id = cur.lastrowid
        conn.commit()
    return {"id": new_id}


@app.delete("/api/prompts/{pid}")
def del_prompt(pid: int):
    with core.db() as conn:
        cur = conn.execute("DELETE FROM prompts WHERE id=?", (pid,))
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "prompt not found")
    return {"deleted": pid}


# ---------- runs ----------

@app.post("/api/runs")
def create_run(r: RunIn):
    run_id = core.start_run(scope=r.scope if r.scope != "custom" else "custom")
    if r.scope == "custom":
        with core.db() as conn:
            conn.execute("UPDATE runs SET prompt_ids=? WHERE id=?",
                         (json.dumps(r.prompt_ids or []), run_id))
            conn.commit()
    try:
        result = core.execute_run(run_id, max_prompts=r.max_prompts)
    except core.ProviderError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@app.get("/api/runs")
def list_runs(limit: int = 30):
    with core.db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]
    return {"items": rows}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int):
    with core.db() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise HTTPException(404, "run not found")
        answers = [dict(a) for a in conn.execute(
            "SELECT a.*, p.text AS prompt_text FROM answers a "
            "JOIN prompts p ON a.prompt_id=p.id WHERE a.run_id=? ORDER BY a.id", (run_id,))]
    return {"run": dict(run), "answers": answers}


# ---------- insights ----------

@app.get("/api/insights/overview")
def insights_overview(brand_id: Optional[int] = None, days: int = 30,
                      exclude_demo: bool = True):
    result = core.overview(brand_id=brand_id, days=days, exclude_demo=exclude_demo)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


# ---------- settings ----------

def _mask(settings: dict) -> dict:
    """API 永不回显 key 明文（provider 与 engines 都处理）。"""
    masked = json.loads(json.dumps(settings))
    prov = masked.get("provider") or {}
    if prov.get("api_key"):
        k = prov["api_key"]
        prov["api_key_masked"] = k[:6] + "..." + k[-4:] if len(k) > 12 else "***"
        del prov["api_key"]
    for e in masked.get("engines") or []:
        if e.get("api_key"):
            k = e["api_key"]
            e["api_key_masked"] = k[:6] + "..." + k[-4:] if len(k) > 12 else "***"
            del e["api_key"]
    return masked


@app.get("/api/settings")
def get_settings():
    return _mask(core.load_settings())


@app.put("/api/settings")
def put_settings(s: SettingsIn):
    current = core.load_settings()
    if s.provider is not None:
        incoming = s.provider
        if incoming.get("api_key") == "__KEEP__" or not incoming.get("api_key"):
            incoming["api_key"] = (current.get("provider") or {}).get("api_key", "")
        current["provider"] = incoming
    if s.engines is not None:
        old_engines = {e.get("name"): e for e in (current.get("engines") or [])}
        for e in s.engines:
            if e.get("kind") == "openai_compat" and e.get("api_key") in (None, "", "__KEEP__"):
                prev = old_engines.get(e.get("name")) or {}
                e["api_key"] = prev.get("api_key") or (current.get("provider") or {}).get("api_key", "")
        current["engines"] = s.engines
    core.save_settings(current)
    return _mask(current)


@app.get("/api/insights/report")
def insights_report(brand_id: Optional[int] = None, days: int = 30,
                    exclude_demo: bool = True):
    """生成引引格式的 GEO 引用现状诊断报告（Markdown，可直接发客户）。"""
    d = core.overview(brand_id=brand_id, days=days, exclude_demo=exclude_demo)
    if "error" in d:
        raise HTTPException(404, d["error"])
    dim_icon = {"brand": "品牌词", "scene": "场景词", "compare": "对比词", "choice": "选购词"}
    dep_cn = {"mentioned": "仅提名", "described": "有描述", "recommended": "有推荐"}
    L = []
    L.append(f"# {d['brand']} · GEO 引用现状诊断报告")
    L.append("")
    L.append(f"日期：{d['trend'][-1]['day'] if d['trend'] else '-'} | 数据来源：GeoPulse 自托管监测 | 周期：近 {d['days']} 天")
    L.append("")
    L.append("## 一、搜索概览")
    L.append("")
    L.append(f"- 监测样本：{d['total_prompts']} 条 AI 回答")
    L.append(f"- **AI 可见率：{d['visibility']}%**（被提及回答占比）")
    L.append(f"- 声量份额 SoV：{d['share_of_voice']}%")
    L.append("")
    if d.get("engines"):
        L.append("| 引擎 | 可见率 | 样本 |")
        L.append("|---|---|---|")
        for e in d["engines"]:
            L.append(f"| {e['engine']} | {e['visibility']}% | {e['samples']} |")
        L.append("")
    if d.get("dimensions"):
        L.append("## 二、四维热力图（品牌 × 问题维度）")
        L.append("")
        L.append("| 维度 | 可见率 | 样本 | 状态 |")
        L.append("|---|---|---|---|")
        for x in d["dimensions"]:
            st = "🔴 缺席" if x["visibility"] == 0 else ("🟡 偏弱" if x["visibility"] < 50 else "🟢 在场")
            L.append(f"| {dim_icon.get(x['key'], x['key'])} | {x['visibility']}% | {x['samples']} | {st} |")
        L.append("")
    if d.get("depth"):
        L.append("## 三、引用深度分布")
        L.append("")
        for k, v in d["depth"].items():
            L.append(f"- {dep_cn.get(k, k)}：{v} 次")
        L.append("")
    if d.get("competitors"):
        L.append("## 四、竞品对标")
        L.append("")
        L.append("| 品牌 | 提及 | SoV |")
        L.append("|---|---|---|")
        for c in d["competitors"][:8]:
            L.append(f"| {c['name']} | {c['mentions']} | {c['sov']}% |")
        L.append("")
    # 机会标注：主品牌全缺席的维度
    miss = [x for x in d.get("dimensions", []) if x["visibility"] == 0]
    if miss:
        L.append("## 五、机会标注（零引用维度）")
        L.append("")
        for x in miss:
            L.append(f"- **{dim_icon.get(x['key'], x['key'])}**：{x['samples']} 个问题全部缺席——AI 在这类问题中不认为你是候选")
        L.append("")
    L.append("## 六、一句话诊断")
    L.append("")
    if miss:
        worst = dim_icon.get(miss[0]["key"], miss[0]["key"])
        L.append(f"{d['brand']} 的 AI 引用现状：可见率 {d['visibility']}%。最大缺口在「{worst}」维度——建议优先补该维度的场景化内容。")
    else:
        L.append(f"{d['brand']} 的 AI 引用现状：可见率 {d['visibility']}%，四维均有出现。下一优先级：提升引用深度（从提名到推荐）。")
    L.append("")
    L.append("> 报告由 GeoPulse 自动生成 · 深度判定为规则版（v1）· 可解释可审计")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(L), media_type="text/markdown; charset=utf-8")


# ---------- frontend（目录缺失时降级为 API-only，不崩） ----------

if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))
else:
    print(f"[WARN] frontend dir not found: {FRONTEND_DIR} - running API-only mode")

    @app.get("/")
    def index():
        return {"service": "GeoPulse", "mode": "api-only",
                "hint": "frontend directory missing; REST API still available at /api/*"}
