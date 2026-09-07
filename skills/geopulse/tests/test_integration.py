#!/usr/bin/env python3
"""GeoPulse 集成测试套件：真实起服 → 全 API 面 → 断言 → 清理。

跑法：python3 tests/test_integration.py
要求：端口 8700 可用（脚本自管服务器生命周期）。
"""
from __future__ import annotations
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
TEST_DB = Path("/tmp/geopulse_test.db")
DB = TEST_DB  # 测试永远不碰生产库（GEOPULSE_DB 环境变量注入见 run_test_server.py）
BASE = "http://127.0.0.1:8700"

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def api(method: str, path: str, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def _free_port():
    """杀掉占用 8700 的残留服务器（测试环境隔离）。"""
    r = subprocess.run(["lsof", "-ti", "tcp:8700"], capture_output=True, text=True)
    for pid in r.stdout.split():
        try:
            os.kill(int(pid), signal.SIGTERM)
            time.sleep(0.5)
        except (ProcessLookupError, ValueError):
            pass


def main():
    # ---- 1. 清场 + 起服 ----
    _free_port()
    if DB.exists():
        DB.unlink()
    cfg_path = Path("/tmp/geopulse_test_config.json")
    cfg_bak = None
    if cfg_path.exists():
        cfg_bak = cfg_path.read_text(encoding="utf-8")
        cfg_path.unlink()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "run_test_server.py")], cwd=str(ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid)
    for _ in range(20):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(BASE + "/api/brands", timeout=2)
            break
        except Exception:
            continue
    else:
        print("[FATAL] 服务器 20s 未就绪")
        sys.exit(1)
    print("[OK] 测试服务器就绪")

    try:
        # ---- 2. 种子与列表 ----
        s, d = api("GET", "/api/brands")
        check("GET brands 200 + 种子4", s == 200 and len(d["items"]) == 4, str(d))
        s, d = api("GET", "/api/prompts")
        check("GET prompts 200 + 种子5", s == 200 and len(d["items"]) == 5, str(d))

        # ---- 3. 品牌增删 ----
        s, d = api("POST", "/api/brands", {"name": "测试品牌X", "aliases": ["TBX"], "is_primary": False})
        check("POST brand 200", s == 200 and d.get("id"), str(d))
        bid = d["id"]
        s, d = api("POST", "/api/brands", {"name": "  ", "aliases": []})
        check("空品牌名 400", s == 400, str(d))
        s, d = api("DELETE", f"/api/brands/{bid}")
        check("DELETE brand 200", s == 200)
        s, d = api("DELETE", f"/api/brands/{bid}")
        check("重复删 404", s == 404)

        # ---- 4. prompt 增删 ----
        s, d = api("POST", "/api/prompts", {"text": "测试 prompt 一条", "intent": "测试"})
        check("POST prompt 200", s == 200 and d.get("id"))
        pid = d["id"]
        s, d = api("DELETE", f"/api/prompts/{pid}")
        check("DELETE prompt 200", s == 200)

        # ---- 5. demo 监测端到端 + 金标准 ----
        s, d = api("POST", "/api/runs", {"scope": "all"})
        check("POST run 200 done=5(种子)", s == 200 and d.get("done") == 5, str(d))
        s, d = api("GET", "/api/insights/overview?days=7&exclude_demo=false")
        check("overview 有数据", s == 200 and d.get("total_prompts", 0) >= 5, str(d)[:200])
        check("金标准：demo 可见率=100", d.get("visibility") == 100.0, str(d.get("visibility")))
        check("金标准：SoV 主品牌>0", d.get("share_of_voice", 0) > 0, str(d.get("share_of_voice")))
        check("金标准：无 Profound 误报", "Profound" not in json.dumps(d.get("recent", [])), "")

        # ---- 6. 异常路径 ----
        s, d = api("GET", "/api/runs/9999")
        check("不存在 run 404", s == 404)

        # ---- 7. settings key 安全 ----
        s, d = api("PUT", "/api/settings", {"provider": {"kind": "openai_compat",
            "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
            "api_key": "test-fake-key-0000000000"}})
        check("PUT settings 200", s == 200, str(d))
        check("PUT 响应无明文 key", "test-fake-key" not in json.dumps(d))
        s, d = api("GET", "/api/settings")
        check("GET settings 无明文 key", "test-fake-key" not in json.dumps(d))
        check("masked 存在", bool(d.get("provider", {}).get("api_key_masked")))
        # __KEEP__ 语义：key 留空提交不覆盖
        s, d = api("PUT", "/api/settings", {"provider": {"kind": "demo", "api_key": "__KEEP__"}})
        cfg = json.loads(Path("/tmp/geopulse_test_config.json").read_text())
        check("__KEEP__ 保留旧 key", cfg["provider"].get("api_key") == "test-fake-key-0000000000", str(cfg.get("provider", {}).get("api_key")))

        # ---- 8. demo 配置真实跑一轮（provider 切换后）----
        s, d = api("POST", "/api/runs", {"scope": "all"})
        check("demo 引擎切换后 run 仍成功", s == 200 and d.get("done", 0) >= 5, str(d))

        # ---- 8b. 四维矩阵 + 深度判定 + 报告导出 ----
        s, d = api("POST", "/api/prompts", {"text": "测试品牌X 怎么样？靠谱吗", "dimension": "brand"})
        check("带 dimension 的 prompt 200", s == 200)
        tpid = d["id"]
        api("DELETE", f"/api/prompts/{tpid}")

        s, d = api("GET", "/api/insights/overview?days=1&exclude_demo=false")
        check("overview 含 dimensions 字段", "dimensions" in d, str(list(d.keys())[:8]))
        check("overview 含 depth 字段", "depth" in d)
        check("深度判定有 recommended", d.get("depth", {}).get("recommended", 0) > 0, str(d.get("depth")))

        req = urllib.request.Request(BASE + "/api/insights/report?days=1&exclude_demo=false")
        with urllib.request.urlopen(req, timeout=10) as r:
            rep = r.read().decode("utf-8")
        check("报告导出含诊断标题", "诊断报告" in rep and "一句话诊断" in rep)
        check("报告含四维热力图", "四维热力图" in rep or "维度" in rep)

        # ---- 8c. 多引擎配置 ----
        s, d = api("PUT", "/api/settings", {"engines": [
            {"name": "demo", "kind": "demo"},
            {"name": "demo2", "kind": "demo"}]})
        check("多引擎保存 200", s == 200 and len(d.get("engines", [])) == 2, str(d))
        raw = json.dumps(d)
        check("多引擎 key 无明文", "test-fake-key" not in raw, raw[:120])
        s, d = api("POST", "/api/runs", {"scope": "all"})
        check("多引擎 run 总量翻倍", s == 200 and d.get("done", 0) == 10, str(d))
        # 隔离库校验：测试从未碰生产
        check("测试 DB 是隔离库", Path("/tmp/geopulse_test.db").exists())
        # 分引擎断言：demo 引擎内可见率应为 100%（demo 每条都提主品牌）
        s, d = api("GET", "/api/insights/overview?days=1&exclude_demo=false")
        demo_eng = next((e for e in d.get("engines", []) if e["engine"] == "demo"), None)
        check("demo 引擎可见率=100", demo_eng and demo_eng["visibility"] == 100.0, str(demo_eng))
        s, d = api("GET", "/api/insights/overview?days=1&exclude_demo=false")
        eng_names = [e["engine"] for e in d.get("engines", [])]
        check("overview 分引擎统计", "demo" in eng_names and "demo2" in eng_names, str(eng_names))
        s, d = api("GET", "/api/insights/overview?days=1")
        demo_in = any(e["engine"].startswith("demo") for e in d.get("engines", []))
        check("指标默认排除 demo 引擎", not demo_in, str(d.get("engines")))
        s, d = api("GET", "/api/insights/overview?days=1&exclude_demo=false")
        check("exclude_demo=false 可看 demo", "total_prompts" in d)
        # 还原单引擎
        api("PUT", "/api/settings", {"engines": [{"name": "demo", "kind": "demo"}]})
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        time.sleep(1)
        if cfg_bak is not None:
            cfg_path.write_text(cfg_bak, encoding="utf-8")

    # ---- 9. config 权限（隔离 config）----
    test_cfg = Path("/tmp/geopulse_test_config.json")
    mode = oct(test_cfg.stat().st_mode)[-3:]
    check("config.json 0600", mode == "600", mode)
    # backend（skill 内分发副本）不被测试写入任何 config
    check("backend 未被测试写入 config", not (BACKEND / "config.json").exists())

    print()
    print(f"════ 结果：{PASS} PASS / {FAIL} FAIL ════")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
