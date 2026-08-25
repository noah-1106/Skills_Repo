#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scribe Skill — Agent 客户端：确保服务运行 → 上传转写 → 下载留存

用法:
  python3 scribe.py <音频/视频文件> [--diarize] [--format txt|srt|json|all] [--out DIR]
  python3 scribe.py --status          # 查看服务状态
  python3 scribe.py --start           # 启动服务并等待就绪

示例:
  python3 scribe.py 会议录音.m4a
  python3 scribe.py 采访.wav --diarize --format json --out ~/Desktop
  python3 scribe.py --status

流程（全自动）:
  1. ensure_server(): 检查 http://localhost:8399/api/health
     - 没起 → spawn scripts/start.py --detach → 轮询 health 直到就绪(≤180s)
  2. POST /api/transcribe 上传音频 → 转写（可 diarize 说话人标记）
  3. GET /api/download 拉产物（txt/srt/json）→ 存到 --out（默认当前目录）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
if BASE.name == "scripts":
    BASE = BASE.parent

DEFAULT_PORT = int(os.environ.get("SCRIBE_PORT", "8399"))
HEALTH_TIMEOUT = 180  # 首次加载模型最多等 180s


# ---------- 服务管理 ----------

def _health(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def ensure_server(port: int = DEFAULT_PORT, timeout: float = HEALTH_TIMEOUT) -> dict:
    """确保服务运行且模型就绪, 返回 health 信息。"""
    h = _health(port)
    if h and h.get("ok"):
        print(f"✅ scribe 服务已在运行 (模型就绪, {h.get('model_load_seconds')}s 加载)")
        return h

    # 未运行 → 启动
    print(f"🚀 scribe 服务未运行, 启动中 (首次加载模型约 15s)...")
    start_py = BASE / "scripts" / "start.py"
    if not start_py.exists():
        sys.exit("❌ 找不到 scripts/start.py")
    venv_py = (BASE / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python"))
    launcher = str(venv_py) if venv_py.exists() else sys.executable
    subprocess.Popen([launcher, str(start_py), "--detach"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)

    # 轮询等待
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = _health(port)
        if h and h.get("ok"):
            print(f"✅ scribe 就绪 (耗时 {time.time() - t0:.0f}s)")
            return h
        time.sleep(2)
    sys.exit(f"❌ 等待服务就绪超时 ({timeout}s)。查看 {BASE / 'data' / 'server.log'}")


# ---------- 转写 ----------

def transcribe(file_path: Path, diarize: bool, port: int = DEFAULT_PORT) -> dict:
    """上传音频 → 转写 → 返回完整结果 JSON。"""
    # multipart/form-data 手工构造（避免依赖 requests）；diarize 走 query 参数
    boundary = "----scribeSkillBoundary" + str(int(time.time() * 1000))
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    fields = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{urllib.parse.quote(file_path.name)}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n"]
    body = "".join(fields).encode() + file_bytes + f"\r\n--{boundary}--\r\n".encode()

    qs = "?diarize=true" if diarize else ""
    req = urllib.request.Request(
        f"http://localhost:{port}/api/transcribe{qs}", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode())


# ---------- 下载留存 ----------

def download(url: str, out_dir: Path, port: int = DEFAULT_PORT) -> Path:
    """下载单个产物到指定目录, 返回本地路径。URL 相对路径自动补全 host。"""
    if url.startswith("/"):
        url = f"http://localhost:{port}{url}"
    name = Path(urllib.parse.urlparse(url).path).name
    dest = out_dir / name
    with urllib.request.urlopen(url, timeout=60) as r:
        dest.write_bytes(r.read())
    return dest


def save_outputs(result: dict, out_dir: Path, fmt: str = "all", port: int = DEFAULT_PORT) -> list[Path]:
    """把转写结果的所有产物下载到 out_dir, 返回本地文件列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    dl = result.get("downloads", {})
    fmts = {"txt": ["txt"], "srt": ["srt"], "json": ["json"], "all": ["txt", "srt", "json"]}
    for key in fmts.get(fmt, ["txt"]):
        url = dl.get(key)
        if url:
            p = download(url, out_dir, port)
            saved.append(p)
            print(f"  💾 {p}")
    return saved


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="scribe Skill — Agent 客户端")
    ap.add_argument("file", nargs="?", help="音频/视频文件路径")
    ap.add_argument("--diarize", action="store_true", help="标记说话人 (CAM++ 懒加载)")
    ap.add_argument("--format", default="all", choices=["txt", "srt", "json", "all"],
                    help="下载格式 (默认 all)")
    ap.add_argument("--out", default=".", help="产物保存目录 (默认当前目录)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--status", action="store_true", help="查看服务状态")
    ap.add_argument("--start", action="store_true", help="只启动服务并等待就绪")
    args = ap.parse_args()

    if args.status:
        h = _health(args.port)
        if h:
            print(json.dumps(h, ensure_ascii=False, indent=2))
        else:
            print("❌ scribe 服务未运行")
        return

    if args.start:
        ensure_server(args.port)
        return

    if not args.file:
        ap.print_help()
        sys.exit(1)

    file_path = Path(args.file)
    if not file_path.exists():
        sys.exit(f"❌ 文件不存在: {file_path}")

    # ① 确保服务
    ensure_server(args.port)

    # ② 转写
    print(f"🎙️ 上传 {file_path.name} 转写中... (diarize={'是' if args.diarize else '否'})")
    result = transcribe(file_path, args.diarize, args.port)
    print(f"   ✅ 转写完成: {result.get('duration_s', 0)}s 音频, 推理 {result.get('infer_s', 0)}s, "
          f"RTF {result.get('rtf', 0)}"
          + (f", {result.get('n_speakers', 0)} 位说话人" if args.diarize else ""))

    # ③ 下载留存
    print(f"💾 保存产物到 {Path(args.out).resolve()} ...")
    saved = save_outputs(result, Path(args.out), args.format, args.port)

    # ④ 摘要
    print()
    print(f"📄 转写摘要 ({result.get('project', '未命名')}):")
    for s in result.get("sentences", [])[:10]:
        sp = f"{s['speaker']}: " if args.diarize and s.get("speaker") else ""
        print(f"   [{s['start']:.1f}s-{s['end']:.1f}s] {sp}{s['text']}")
    if len(result.get("sentences", [])) > 10:
        print(f"   ... 共 {len(result['sentences'])} 句")
    print()
    print(f"✅ 完成。产物: {', '.join(str(p) for p in saved)}")


if __name__ == "__main__":
    main()
