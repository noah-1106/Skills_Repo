#!/usr/bin/env python3
"""geopulse_ctl: GeoPulse 自托管 GEO 监测系统的管理 CLI（分发版）。

本 skill 自包含完整 GeoPulse 系统（backend/frontend/docs/tests）。
首次 start 自动建库+种子（demo 引擎，零 key 可跑通）；接入生产用 engine set。

用法：
  geopulse_ctl.py status                     服务健康 + 数据概况
  geopulse_ctl.py start | stop               启动/停止服务（幂等，数据在 ~/.geopulse/）
  geopulse_ctl.py engine show                当前引擎配置（key 脱敏）
  geopulse_ctl.py engine set --kind openai_compat --base-url URL --model M --api-key K
  geopulse_ctl.py brands [list|add|remove]   品牌管理
  geopulse_ctl.py prompts [list|add|remove]  prompt 管理（--dimension 四维）
  geopulse_ctl.py run [--max N]              触发监测
  geopulse_ctl.py insights [--days N]        指标概览
  geopulse_ctl.py report [--days N] [--out]  导出诊断报告
"""
from __future__ import annotations
import argparse
import json
import os
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
BACKEND = SKILL_DIR / "backend"
PORT = int(os.environ.get("GEOPULSE_PORT", "8700"))
BASE = os.environ.get("GEOPULSE_URL", f"http://127.0.0.1:{PORT}")
DATA_DIR = Path(os.environ.get("GEOPULSE_HOME", str(Path.home() / ".geopulse")))
DB_PATH = DATA_DIR / "geopulse.db"
CFG_PATH = DATA_DIR / "config.json"


def api(method: str, path: str, body=None, timeout=30):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except (urllib.error.URLError, TimeoutError) as e:
        raise SystemExit(f"[geopulse] 服务不可达（{BASE}）：先执行 start。({e})")


IS_WIN = sys.platform.startswith("win")


def pids_on_port(port: int) -> list:
    """跨平台找出监听端口的进程 pid。"""
    if IS_WIN:
        r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True)
        pids = set()
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
                try:
                    pids.add(int(parts[4]))
                except ValueError:
                    pass
        return sorted(pids)
    r = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True)
    out = []
    for pid in r.stdout.split():
        try:
            out.append(int(pid))
        except ValueError:
            pass
    return out


def kill_pids(pids: list):
    for pid in pids:
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        except (ProcessLookupError, ValueError):
            pass


def service_alive() -> bool:
    try:
        with urllib.request.urlopen(BASE + "/api/brands", timeout=3):
            return True
    except Exception:
        return False


def cmd_status(_):
    if not service_alive():
        print("服务：❌ 未运行（用 start 启动）")
        print(f"本体：{'✓' if BACKEND.is_dir() else '❌'} {SKILL_DIR}")
        print(f"数据：{DATA_DIR}")
        return
    print(f"服务：✅ {BASE}")
    _, brands = api("GET", "/api/brands")
    _, prompts = api("GET", "/api/prompts")
    _, ins = api("GET", "/api/insights/overview?days=7")
    _, settings = api("GET", "/api/settings")
    engines = settings.get("engines") or ([settings["provider"]] if settings.get("provider") else [])
    enames = [e.get("name", e.get("kind", "?")) for e in engines]
    print(f"品牌：{len(brands['items'])} 个（主品牌：{next((b['name'] for b in brands['items'] if b['is_primary']), '无')}）")
    print(f"Prompts：{len(prompts['items'])} 条 | 引擎：{enames}")
    print(f"近7天：可见率 {ins['visibility']}% | SoV {ins['share_of_voice']}% | 样本 {ins['total_prompts']} | 数据目录: {DATA_DIR}")


def check_deps():
    r = subprocess.run([sys.executable, "-c", "import fastapi, uvicorn"],
                       capture_output=True)
    if r.returncode != 0:
        raise SystemExit(
            "[geopulse] 缺少依赖：fastapi / uvicorn\n"
            "  安装：pip3 install --user fastapi 'uvicorn[standard]'\n"
            "  （GeoPulse 后端仅此两个依赖，SQLite/前端均为零依赖）")


def cmd_start(_):
    if not BACKEND.is_dir():
        raise SystemExit(f"[geopulse] 本体缺失: {BACKEND}（skill 安装不完整）")
    check_deps()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if service_alive():
        print("服务已在运行 ✅")
        cmd_status(None)
        return
    kill_pids(pids_on_port(PORT))
    env = dict(os.environ,
               GEOPULSE_DB=str(DB_PATH),
               GEOPULSE_CONFIG=str(CFG_PATH),
               GEOPULSE_PORT=str(PORT))
    popen_kw = {"cwd": str(BACKEND), "env": env,
                "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if not IS_WIN:
        popen_kw["preexec_fn"] = os.setsid  # 进程组（Windows 无此概念，也无需）
    subprocess.Popen([sys.executable, "run.py"], **popen_kw)
    for _ in range(20):
        time.sleep(0.5)
        if service_alive():
            print("服务已启动 ✅（数据目录: " + str(DATA_DIR) + "）")
            cmd_status(None)
            return
    raise SystemExit("[geopulse] 启动 20s 未就绪——手动前台跑看报错：cd "
                     f"{BACKEND} && GEOPULSE_DB={DB_PATH} GEOPULSE_CONFIG={CFG_PATH} python3 run.py")


def cmd_stop(_):
    pids = pids_on_port(PORT)
    kill_pids(pids)
    print(f"已停止（{len(pids)} 个进程）" if pids else "服务本就没在跑")


def cmd_engine(args):
    if args.action == "show":
        cfg = json.loads(CFG_PATH.read_text(encoding="utf-8")) if CFG_PATH.is_file() else {}
        engines = cfg.get("engines") or ([cfg["provider"]] if cfg.get("provider") else [])
        if not engines:
            print("当前：demo 引擎（默认，零 key 可跑通）")
            print("接入生产：engine set --kind openai_compat --base-url https://api.deepseek.com/v1 --model deepseek-chat --api-key sk-xxx")
            return
        for e in engines:
            k = e.get("api_key") or ""
            masked = (k[:6] + "..." + k[-4:]) if len(k) > 12 else ("***" if k else "(demo 无需 key)")
            print(f"  {e.get('name', e.get('kind'))}: {e.get('kind')} | {e.get('model', '-')} | key: {masked}")
        return
    if args.action == "remove":
        if not args.engine_name:
            raise SystemExit("用法：engine remove <引擎名>")
        cfg = json.loads(CFG_PATH.read_text(encoding="utf-8")) if CFG_PATH.is_file() else {}
        engines = cfg.get("engines") or []
        rest = [e for e in engines if e.get("name") != args.engine_name]
        if len(rest) == len(engines):
            raise SystemExit(f"找不到引擎: {args.engine_name}（现有: {[e.get('name') for e in engines]}）")
        cfg["engines"] = rest
        CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        CFG_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
        print(f"已删除引擎: {args.engine_name}（重启服务生效）")
        return
    # set
    if args.action == "set" and not args.kind:
        raise SystemExit("[geopulse] engine set 必须指定 --kind demo 或 --kind openai_compat"
                         "（漏掉会静默建成 demo、丢弃你的 key）")
    if args.kind == "openai_compat" and not (args.api_key or "").strip():
        raise SystemExit("[geopulse] openai_compat 需要 --api-key")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8")) if CFG_PATH.is_file() else {}
    name = args.name or args.model or args.kind
    engines = [e for e in (cfg.get("engines") or []) if e.get("name") != name]
    if args.kind == "openai_compat":
        engines.append({"name": name, "kind": "openai_compat",
                        "base_url": args.base_url or "https://api.deepseek.com/v1",
                        "model": args.model or "deepseek-chat",
                        "api_key": args.api_key})
    else:
        engines.append({"name": name, "kind": "demo"})
    cfg["engines"] = engines
    CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    CFG_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"引擎已保存: {name}（{args.kind}）→ {CFG_PATH}")
    print("重启服务生效：geopulse_ctl.py stop && geopulse_ctl.py start")


def cmd_brands(args):
    if args.action in (None, "list"):
        _, d = api("GET", "/api/brands")
        for b in d["items"]:
            role = "★主" if b["is_primary"] else " 竞"
            print(f"  [{role}] {b['name']:<16} 别名: {', '.join(b['aliases'] or []) or '-'}")
        return
    if args.action == "add":
        if not args.name:
            raise SystemExit("用法：brands add <品牌名> [--aliases \"a,b\"] [--primary]")
        aliases = [a.strip() for a in (args.aliases or "").split(",") if a.strip()]
        code, d = api("POST", "/api/brands",
                      {"name": args.name, "aliases": aliases, "is_primary": bool(args.primary)})
        if code == 200:
            print(f"已添加: {d['name']} (id={d['id']}){' ★主品牌' if args.primary else ''}")
        else:
            raise SystemExit(f"添加失败 HTTP {code}: {d.get('detail')}")
        return
    if args.action == "remove":
        if not args.name:
            raise SystemExit("用法：brands remove <品牌名或id>")
        _, d = api("GET", "/api/brands")
        target = next((b for b in d["items"]
                       if b["name"] == args.name or str(b["id"]) == args.name), None)
        if not target:
            raise SystemExit(f"找不到品牌: {args.name}")
        api("DELETE", f"/api/brands/{target['id']}")
        print(f"已删除: {target['name']}")


def cmd_prompts(args):
    if args.action in (None, "list"):
        _, d = api("GET", "/api/prompts")
        for p in d["items"]:
            dim = p.get("dimension") or "-"
            st = "启用" if p.get("is_active") else "停用"
            print(f"  P{p['id']:>3} [{st}] ({dim:<7}) {p['text'][:50]}")
        return
    if args.action == "add":
        if not args.name:
            raise SystemExit("用法：prompts add <文本> [--dimension brand|scene|compare|choice]")
        code, d = api("POST", "/api/prompts",
                      {"text": args.name, "dimension": args.dimension or "", "intent": ""})
        if code == 200:
            print(f"已添加 prompt id={d['id']}（维度: {args.dimension or '未标注'}）")
        else:
            raise SystemExit(f"添加失败 HTTP {code}: {d.get('detail')}")
        return
    if args.action == "remove":
        if not args.name:
            raise SystemExit("用法：prompts remove <id>")
        code, _d = api("DELETE", f"/api/prompts/{args.name}")
        print("已删除" if code == 200 else f"删除失败 HTTP {code}")


def cmd_run(args):
    body = {"scope": "active"}
    if args.max:
        body["max_prompts"] = args.max
    print(f"触发监测（最多 {args.max or '全部'} 条 prompt × 全部引擎），等待完成…")
    t0 = time.time()
    code, d = api("POST", "/api/runs", body, timeout=600)
    if code != 200:
        raise SystemExit(f"监测失败 HTTP {code}: {d.get('detail')}")
    print(f"完成：{d['done']} 成功 / {d['failed']} 失败（run_id={d['run_id']}，{time.time()-t0:.0f}s）")
    if d["failed"]:
        _, detail = api("GET", f"/api/runs/{d['run_id']}")
        err = (detail["run"].get("error") or "")[:200]
        print(f"失败详情: {err}")


def cmd_insights(args):
    _, d = api("GET", f"/api/insights/overview?days={args.days or 7}")
    print(f"主品牌：{d['brand']}（近 {d['days']} 天，样本 {d['total_prompts']}）")
    print(f"可见率：{d['visibility']}% | SoV：{d['share_of_voice']}%")
    if d.get("depth"):
        dep = {"mentioned": "仅提名", "described": "有描述", "recommended": "有推荐"}
        print("深度：", ", ".join(f"{dep.get(k, k)}×{v}" for k, v in d["depth"].items()))
    if d.get("dimensions"):
        print("四维：", " | ".join(f"{x['name']} {x['visibility']}%" for x in d["dimensions"]))
    if d.get("competitors"):
        print("竞品：", " | ".join(f"{c['name']} {c['mentions']}次" for c in d["competitors"][:6]))


def cmd_report(args):
    req = urllib.request.Request(BASE + f"/api/insights/report?days={args.days or 7}")
    with urllib.request.urlopen(req, timeout=30) as r:
        md = r.read().decode("utf-8")
    if args.out:
        out = Path(args.out).expanduser()
        out.write_text(md, encoding="utf-8")
        print(f"报告已保存: {out}（{len(md)} 字符）")
    else:
        print(md)


def main():
    ap = argparse.ArgumentParser(prog="geopulse", description="GeoPulse 自托管 GEO 监测（分发版）")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    sub.add_parser("start")
    sub.add_parser("stop")
    e = sub.add_parser("engine")
    e.add_argument("action", choices=["show", "set", "remove"])
    e.add_argument("engine_name", nargs="?")
    e.add_argument("--kind", choices=["demo", "openai_compat"])
    e.add_argument("--name", help="引擎名（结果分列显示用）")
    e.add_argument("--base-url")
    e.add_argument("--model")
    e.add_argument("--api-key")
    b = sub.add_parser("brands")
    b.add_argument("action", nargs="?", default="list", choices=["list", "add", "remove"])
    b.add_argument("name", nargs="?")
    b.add_argument("--aliases")
    b.add_argument("--primary", action="store_true")
    p = sub.add_parser("prompts")
    p.add_argument("action", nargs="?", default="list", choices=["list", "add", "remove"])
    p.add_argument("name", nargs="?")
    p.add_argument("--dimension", choices=["brand", "scene", "compare", "choice"])
    r = sub.add_parser("run")
    r.add_argument("--max", type=int, default=None)
    i = sub.add_parser("insights")
    i.add_argument("--days", type=int, default=7)
    rep = sub.add_parser("report")
    rep.add_argument("--days", type=int, default=7)
    rep.add_argument("--out")
    args = ap.parse_args()

    if not args.cmd:
        ap.print_help()
        return
    {"status": cmd_status, "start": cmd_start, "stop": cmd_stop,
     "engine": cmd_engine, "brands": cmd_brands, "prompts": cmd_prompts,
     "run": cmd_run, "insights": cmd_insights, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
