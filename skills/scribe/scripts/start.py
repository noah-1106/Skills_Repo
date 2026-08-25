#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scribe Skill 跨平台启动脚本（替代 start.sh）

用法:
  python3 scripts/start.py          # 前台启动（终端挂着）
  python3 scripts/start.py --wait   # 启动并等待 /api/health 就绪后退出
  python3 scripts/start.py --detach # 后台启动（nohup 风格, 日志写 data/server.log）

注意:
  - 优先用 skill 根 .venv 的 python（setup.py 建好）
  - 无 .venv 时提示先跑 setup.py
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
if BASE.name == "scripts":
    BASE = BASE.parent

PORT = int(os.environ.get("SCRIBE_PORT", "8399"))
SERVER = BASE / "scripts" / "server.py"


def venv_python() -> Path:
    if sys.platform == "win32":
        return BASE / ".venv" / "Scripts" / "python.exe"
    return BASE / ".venv" / "bin" / "python"


def health_ok(timeout: float = 180.0) -> bool:
    """轮询 /api/health 直到 ok=True（模型常驻加载完成）或超时。"""
    url = f"http://localhost:{PORT}/api/health"
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                import json
                data = json.loads(r.read().decode())
                if data.get("ok"):
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def main():
    py = venv_python()
    if not py.exists():
        print("❌ 未找到 .venv, 请先运行: python3 scripts/setup.py")
        sys.exit(1)

    # 已在运行?
    try:
        import json
        with urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2) as r:
            data = json.loads(r.read().decode())
            if data.get("ok"):
                print(f"✅ scribe 已在运行 http://localhost:{PORT} (模型就绪)")
                return
    except Exception:
        pass  # 未运行, 继续启动

    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    cmd = [str(py), str(SERVER)]
    if mode == "--detach":
        log_dir = BASE / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        logf = open(log_dir / "server.log", "a")
        subprocess.Popen(cmd, stdout=logf, stderr=logf, start_new_session=True)
        print(f"🚀 scribe 后台启动中 (日志: {log_dir / 'server.log'})")
    else:
        print(f"🚀 scribe 启动中 → http://localhost:{PORT} (首次加载模型约 15s)")
        if mode == "--wait":
            # spawn 后等待就绪
            log_dir = BASE / "data"
            log_dir.mkdir(parents=True, exist_ok=True)
            logf = open(log_dir / "server.log", "a")
            subprocess.Popen(cmd, stdout=logf, stderr=logf, start_new_session=True)
            if health_ok():
                print(f"✅ scribe 就绪 http://localhost:{PORT}")
            else:
                print("⚠️ 等待超时, 查看 data/server.log")
            return
        # 前台运行
        os.execv(str(py), [str(py), str(SERVER)])


if __name__ == "__main__":
    main()
