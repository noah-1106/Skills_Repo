#!/usr/bin/env python3
"""minimax-av: MiniMax 音视频理解 CLI（ASR 转写 + M3 视频理解）。

用法：
  # 音频转文本（asr-1.0）
  python3 minimax_av.py transcribe meeting.mp3
  python3 minimax_av.py transcribe voice.m4a --out transcript.txt

  # 视频理解（MiniMax-M3，video_url + data URL）
  python3 minimax_av.py understand video.mp4 --prompt "总结这段视频的内容"
  python3 minimax_av.py screen.mp4 --prompt "提取画面中的所有文字" --out result.txt

配置：config.json（与脚本同目录的上级）—— base_url / 模型 / api_key 可改。
     api_key 读取顺序：环境变量 MINIMAX_API_KEY > config.json 的 api_key 字段。
输出：结果文本到 stdout；错误到 stderr，退出码非 0。
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"

AUDIO_EXTS = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
              ".aac": "audio/aac", ".pcm": "audio/pcm", ".flac": "audio/flac",
              ".ogg": "audio/ogg", ".opus": "audio/opus", ".amr": "audio/amr",
              ".webm": "audio/webm"}
VIDEO_EXTS = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
              ".mkv": "video/x-matroska", ".webm": "video/webm", ".flv": "video/x-flv",
              ".wmv": "video/x-ms-wmv", ".mpeg": "video/mpeg", ".mpg": "video/mpeg"}


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        sys.exit(f"[minimax-av] config 不存在: {CONFIG_PATH}")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    key = os.environ.get(cfg.get("api_key_env") or "MINIMAX_API_KEY", "").strip() \
        or (cfg.get("api_key") or "").strip()
    if not key:
        sys.exit("[minimax-av] 未配置 api_key：设置环境变量 MINIMAX_API_KEY 或填入 config.json")
    cfg["api_key"] = key
    return cfg


def sniff(path: Path) -> tuple:
    """magic bytes 判断音频/视频/其他。返回 (kind, mime)。"""
    head = path.read_bytes()[:16]
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio", "audio/mpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if head[:4] == b"fLaC":
        return "audio", "audio/flac"
    if head[:4] == b"OggS":
        return "audio", "audio/ogg"
    if head[:4] == b"#!AMR":
        return "audio", "audio/amr"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        return "video", "video/mp4"
    if head[:4] == b"RIFF":  # AVI
        return "video", "video/x-msvideo"
    if head[:4] in (b"\x1aE\xdf\xa3",):  # EBML (mkv/webm)
        return "video", "video/webm"
    if head[:3] == b"FLV":
        return "video", "video/x-flv"
    return "unknown", ""


def check_file(path: Path, want: str, max_bytes: int) -> str:
    if not path.is_file():
        raise SystemExit(f"[minimax-av] 文件不存在: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise SystemExit(f"[minimax-av] 文件过大（{size/1048576:.1f}MB），超出上限")
    kind, mime = sniff(path)
    if kind != want:
        hint = ""
        if want == "audio" and kind == "video":
            hint = "。视频文件先抽音轨：ffmpeg -i in.mp4 -vn -b:a 64k out.mp3"
        if want == "video" and kind == "audio":
            hint = "。这是音频文件——转写请用 transcribe 子命令"
        raise SystemExit(f"[minimax-av] 需要{want}文件，实际是 {kind or '未知类型'}（magic={path.read_bytes()[:4].hex()}）{hint}")
    return mime


def http_post(url: str, body: bytes, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if e.code == 401:
            raise SystemExit("[minimax-av] 401: API Key 无效或过期（检查 config.json / MINIMAX_API_KEY）")
        if e.code == 429:
            raise SystemExit("[minimax-av] 429: 限流，稍后重试")
        raise SystemExit(f"[minimax-av] HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[minimax-av] 网络失败: {e.reason}")


def strip_think(text: str) -> str:
    """M3 推理内容混在 content 的 <think> 标签里——剥离，只留正文。"""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


# ─────────────────── ASR ───────────────────

def do_transcribe(cfg: dict, args) -> str:
    audio_path = Path(args.media).expanduser()
    mime = check_file(audio_path, "audio", 500 * 1024 * 1024)

    boundary = "----mmasr" + uuid.uuid4().hex[:8]
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
             f'{cfg["asr_model"]}\r\n'.encode()]
    parts.append(b'--' + boundary.encode() + b'\r\nContent-Disposition: form-data; name="response_format"\r\n\r\njson\r\n')
    parts.append(b'--' + boundary.encode() + b'\r\nContent-Disposition: form-data; name="stream"\r\n\r\nfalse\r\n')
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                 f'filename="{audio_path.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
    parts.append(audio_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    url = cfg["base_url"].rstrip("/") + "/speech_to_text"
    resp = http_post(url, b"".join(parts),
                     {"Content-Type": f"multipart/form-data; boundary={boundary}",
                      "Authorization": f"Bearer {cfg['api_key']}"},
                     cfg.get("timeout_asr_ms", 90000) // 1000)

    text = (resp.get("text") or "").strip()
    if not text:
        raise SystemExit(f"[minimax-av] 转录为空 | 响应keys={sorted(resp.keys())}")
    info = f'duration={resp.get("duration", "?")}s'
    if args.out:
        Path(args.out).expanduser().write_text(text + "\n", encoding="utf-8")
        print(f"转录完成 → {args.out}", file=sys.stderr)
    print(text)
    if args.show_usage:
        print(f"[minimax-av] asr_model={resp.get('model', cfg['asr_model'])} "
              f"latency={int((time.time()-t0)*1000)}ms {info} bytes={audio_path.stat().st_size}",
              file=sys.stderr)
    return text


# ─────────────────── 视频理解 ───────────────────

def do_understand(cfg: dict, args) -> str:
    video_path = Path(args.media).expanduser()
    mime = check_file(video_path, "video", cfg.get("max_video_bytes", 100 * 1024 * 1024))

    b64 = base64.b64encode(video_path.read_bytes()).decode()
    content = [
        {"type": "video_url", "video_url": {"url": f"data:{mime};base64,{b64}"}},
        {"type": "text", "text": args.prompt},
    ]
    payload = {"model": cfg["vision_model"],
               "messages": [{"role": "user", "content": content}],
               "max_tokens": args.max_tokens or 4096}
    if args.json:
        payload["messages"][0]["content"][-1]["text"] += (
            "\n\n要求：只输出合法 JSON，不要输出其他文字或 markdown 代码块。")

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    resp = http_post(url, json.dumps(payload).encode("utf-8"),
                     {"Content-Type": "application/json",
                      "Authorization": f"Bearer {cfg['api_key']}"},
                     cfg.get("timeout_vision_ms", 300000) // 1000)

    try:
        msg = resp["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        raise SystemExit(f"[minimax-av] 响应结构异常: {e} | keys={sorted(resp.keys())}")
    raw = (msg.get("content") or "").strip()
    text = strip_think(raw) or (msg.get("reasoning_content") or "").strip()
    if not text:
        raise SystemExit("[minimax-av] 空回答（think 剥离后无正文且 reasoning_content 为空），尝试增大 --max-tokens")
    if args.out:
        Path(args.out).expanduser().write_text(text + "\n", encoding="utf-8")
        print(f"分析完成 → {args.out}", file=sys.stderr)
    print(text)
    if args.show_usage:
        print(f"[minimax-av] model={resp.get('model', cfg['vision_model'])} "
              f"latency={int((time.time()-t0)*1000)}ms "
              f"usage={json.dumps(resp.get('usage') or {}, ensure_ascii=False)}",
              file=sys.stderr)
    return text


def main():
    ap = argparse.ArgumentParser(prog="minimax-av", description="MiniMax 音视频理解（ASR 转写 + M3 视频理解）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_t = sub.add_parser("transcribe", help="音频转文本（asr-1.0）")
    ap_t.add_argument("media", help="音频文件")
    ap_t.add_argument("--out", help="保存到文件")
    ap_t.add_argument("--show-usage", action="store_true")

    ap_u = sub.add_parser("understand", help="视频理解（MiniMax-M3）")
    ap_u.add_argument("media", help="视频文件（mp4/mov/avi/mkv/webm…）")
    ap_u.add_argument("-p", "--prompt", default="详细描述这段视频的内容。")
    ap_u.add_argument("--json", action="store_true", help="要求模型输出 JSON")
    ap_u.add_argument("--max-tokens", type=int, default=None)
    ap_u.add_argument("--out", help="保存到文件")
    ap_u.add_argument("--show-usage", action="store_true")

    args = ap.parse_args()
    cfg = load_config()
    global t0
    t0 = time.time()
    if args.cmd == "transcribe":
        do_transcribe(cfg, args)
    elif args.cmd == "understand":
        do_understand(cfg, args)


t0 = time.time()
if __name__ == "__main__":
    main()
