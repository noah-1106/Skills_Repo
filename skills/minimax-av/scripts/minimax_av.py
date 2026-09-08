#!/usr/bin/env python3
"""minimax-av: MiniMax 全模态理解 CLI（ASR 转写 + M3 视觉理解[视频+图片]）。

用法：
  # 音频转文本（asr-1.0）
  python3 minimax_av.py transcribe meeting.mp3
  python3 minimax_av.py transcribe voice.m4a --out transcript.txt
  python3 minimax_av.py transcribe meeting.mp3 --format srt --out 字幕.srt
  python3 minimax_av.py transcribe interview.wav --format verbose_json

  # 视觉理解（MiniMax-M3：视频走 video_url，图片走 image_url，可混合多文件）
  python3 minimax_av.py understand video.mp4 --prompt "总结这段视频的内容"
  python3 minimax_av.py understand cover.png --prompt "提取图中所有文字"
  python3 minimax_av.py understand img1.png img2.jpg --prompt "对比两张图"

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

# ASR 官方格式：wav/aiff/flac/alac(m4a)/mp3/aac/opus/ogg（裸 PCM 与 amr 不支持）
AUDIO_EXTS = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
              ".aac": "audio/aac", ".flac": "audio/flac",
              ".ogg": "audio/ogg", ".opus": "audio/opus",
              ".aiff": "audio/aiff", ".aif": "audio/aiff"}
# 视觉理解：视频容器 + 图片格式
VIDEO_EXTS = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
              ".mkv": "video/x-matroska", ".webm": "video/webm", ".flv": "video/x-flv",
              ".wmv": "video/x-ms-wmv", ".mpeg": "video/mpeg", ".mpg": "video/mpeg"}
IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}

MAX_AUDIO_BYTES = 50 * 1024 * 1024   # 官方：≤50MB（超出 413）
MAX_AUDIO_SECONDS = 500              # 官方：≤500 秒（超出 400，直接拒不截断）
MAX_MEDIA_BYTES = 100 * 1024 * 1024  # 视觉理解单文件（config 可调）


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
    """magic bytes 判断 image/audio/video/unknown。返回 (kind, mime)。"""
    head = path.read_bytes()[:16]
    # ── 图片 ──
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image", "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image", "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "image/webp"
    if head[:2] == b"BM":
        return "image", "image/bmp"
    # ── 音频 ──
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio", "audio/mpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if head[:4] == b"fLaC":
        return "audio", "audio/flac"
    if head[:4] == b"OggS":
        return "audio", "audio/ogg"
    if head[:4] == b"FORM" and head[8:12] == b"AIFF":
        return "audio", "audio/aiff"
    if head[4:8] == b"ftyp":
        # MP4 容器：.m4a = 音频（alac/aac），.mp4/.mov 等 = 视频
        if path.suffix.lower() in (".m4a", ".m4b"):
            return "audio", "audio/mp4"
        return "video", "video/mp4"
    # ── 视频 ──
    if head[:4] == b"RIFF":  # AVI（WEBP 已在前面分流）
        return "video", "video/x-msvideo"
    if head[:4] == b"\x1aE\xdf\xa3":  # EBML
        return "video", "video/webm"
    if head[:3] == b"FLV":
        return "video", "video/x-flv"
    return "unknown", ""


def check_file(path: Path, want: str, max_bytes: int) -> str:
    """存在性/格式/大小校验，返回 mime。magic bytes 自证，不信扩展名。
    want: "audio" / "media"（image 或 video）。"""
    if not path.is_file():
        raise SystemExit(f"[minimax-av] 文件不存在: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise SystemExit(f"[minimax-av] 文件过大（{size/1048576:.1f}MB），超出上限")
    kind, mime = sniff(path)
    ok = (kind == want) or (want == "media" and kind in ("image", "video"))
    if not ok:
        hint = ""
        if want == "audio" and kind == "video":
            hint = "。视频文件先抽音轨：ffmpeg -i in.mp4 -vn -b:a 64k out.mp3"
        if want == "audio" and kind == "image":
            hint = "。这是图片文件"
        if want == "media" and kind == "audio":
            hint = "。这是音频文件——转写请用 transcribe 子命令"
        raise SystemExit(f"[minimax-av] 需要{want}文件，实际是 {kind or '未知类型'}（magic={head_hex(path)}）{hint}")
    return mime


def head_hex(path: Path) -> str:
    return path.read_bytes()[:4].hex()


def http_post(url: str, body: bytes, headers: dict, timeout: int) -> tuple:
    """返回 (content_type, raw_bytes)。HTTP 错误统一分诊。"""
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if e.code == 401:
            raise SystemExit("[minimax-av] 401: API Key 无效或过期（检查 config.json / MINIMAX_API_KEY）")
        if e.code == 413:
            raise SystemExit("[minimax-av] 413: 文件超 50MB——压缩或转码：ffmpeg -i in -b:a 64k out.mp3")
        if e.code == 400:
            raise SystemExit(f"[minimax-av] 400: {detail}（常见原因：音频超 500 秒——官方不截断直接拒绝 / 格式不支持）")
        if e.code == 429:
            raise SystemExit("[minimax-av] 429: 限流（并发勿超 10）——退避 1-2s 重试")
        raise SystemExit(f"[minimax-av] HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[minimax-av] 网络失败: {e.reason}")


def strip_think(text: str) -> str:
    """M3 推理内容混在 content 的 <think> 标签里——剥离，只留正文。"""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


# ─────────────────── ASR（transcribe）───────────────────

def do_transcribe(cfg: dict, args, t0: float) -> None:
    audio_path = Path(args.media).expanduser()
    mime = check_file(audio_path, "audio", cfg.get("max_audio_bytes", MAX_AUDIO_BYTES))

    boundary = "----mmasr" + uuid.uuid4().hex[:8]
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
             f'{cfg["asr_model"]}\r\n'.encode()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="response_format"\r\n\r\n'
                 f'{args.format}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                 f'filename="{audio_path.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
    parts.append(audio_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    url = cfg["base_url"].rstrip("/") + "/speech_to_text"
    ctype, raw = http_post(
        url, b"".join(parts),
        {"Content-Type": f"multipart/form-data; boundary={boundary}",
         "Authorization": f"Bearer {cfg['api_key']}"},
        cfg.get("timeout_asr_ms", 90000) // 1000)

    if args.format in ("srt", "vtt"):
        # 字幕格式：响应体就是 text/plain
        text = raw.decode("utf-8").strip()
        if not text:
            raise SystemExit("[minimax-av] 转录为空")
        _emit(text, args, t0)
        return

    resp = json.loads(raw)
    if args.format == "verbose_json":
        segs = resp.get("segments") or []
        lines = [f"说话人数: {resp.get('n_speakers', '?')} | 时长: {resp.get('duration', '?')}s"]
        for s in segs:
            lines.append(f"[{s.get('speaker', '?')}] {s.get('start', 0):.2f}s-{s.get('end', 0):.2f}s  {s.get('text', '')}")
        text = "\n".join(lines)
        if not segs:
            text = (resp.get("text") or "").strip() or text
        _emit(text, args, t0)
        return

    # 默认 json
    text = (resp.get("text") or "").strip()
    if not text:
        raise SystemExit(f"[minimax-av] 转录为空 | 响应keys={sorted(resp.keys())}")
    _emit(text, args, t0, extra=f'duration={resp.get("duration", "?")}s')


# ─────────────────── 视觉理解（understand）───────────────────

def do_understand(cfg: dict, args, t0: float) -> None:
    """视觉理解：视频走 video_url，图片走 image_url，可混合多文件。"""
    max_bytes = cfg.get("max_video_bytes", MAX_MEDIA_BYTES)
    content = []
    for f in args.media:
        p = Path(f).expanduser()
        mime = check_file(p, "media", max_bytes)
        b64 = base64.b64encode(p.read_bytes()).decode()
        if mime.startswith("image/"):
            if p.stat().st_size > 2 * 1024 * 1024:
                print(f"[minimax-av] 提示：{p.name} 超过 2MB，建议先缩放"
                      f"（ffmpeg -i {p.name} -vf scale=1280:-1 small.png）", file=sys.stderr)
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        else:
            content.append({"type": "video_url", "video_url": {"url": f"data:{mime};base64,{b64}"}})
    content.append({"type": "text", "text": args.prompt})

    payload = {"model": cfg["vision_model"],
               "messages": [{"role": "user", "content": content}],
               "max_tokens": args.max_tokens or 4096}
    if args.json:
        payload["messages"][0]["content"][-1]["text"] += (
            "\n\n要求：只输出合法 JSON，不要输出其他文字或 markdown 代码块。")

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    _, raw = http_post(url, json.dumps(payload).encode("utf-8"),
                       {"Content-Type": "application/json",
                        "Authorization": f"Bearer {cfg['api_key']}"},
                       cfg.get("timeout_vision_ms", 300000) // 1000)
    resp = json.loads(raw)

    try:
        msg = resp["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        raise SystemExit(f"[minimax-av] 响应结构异常: {e} | keys={sorted(resp.keys())}")
    raw_text = (msg.get("content") or "").strip()
    text = strip_think(raw_text) or (msg.get("reasoning_content") or "").strip()
    if not text:
        raise SystemExit("[minimax-av] 空回答（think 剥离后无正文且 reasoning_content 为空），尝试增大 --max-tokens")
    _emit(text, args, t0, extra=f"model={resp.get('model', cfg['vision_model'])}")


def _emit(text: str, args, t0: float, extra: str = "") -> None:
    if args.out:
        Path(args.out).expanduser().write_text(text + "\n", encoding="utf-8")
        print(f"完成 → {args.out}", file=sys.stderr)
    print(text)
    if getattr(args, "show_usage", False):
        ms = int((time.time() - t0) * 1000)
        print(f"[minimax-av] latency={ms}ms {extra}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(prog="minimax-av", description="MiniMax 全模态理解（ASR 转写 + M3 视觉理解）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_t = sub.add_parser("transcribe", help="音频转文本（asr-1.0）")
    ap_t.add_argument("media", help="音频文件（wav/aiff/flac/m4a/mp3/aac/opus/ogg，≤50MB，≤500秒）")
    ap_t.add_argument("--format", choices=["json", "verbose_json", "srt", "vtt"], default="json",
                      help="输出格式：json=纯文本；verbose_json=带说话人与句级时间戳；srt/vtt=字幕")
    ap_t.add_argument("--out", help="保存到文件")
    ap_t.add_argument("--show-usage", action="store_true")

    ap_u = sub.add_parser("understand", help="视觉理解：视频+图片（MiniMax-M3）")
    ap_u.add_argument("media", nargs="+", help="视频/图片文件（mp4/mov… 或 png/jpg/webp/gif，可混合多个）")
    ap_u.add_argument("-p", "--prompt", default="详细描述这段视频的内容。")
    ap_u.add_argument("--json", action="store_true", help="要求模型输出 JSON")
    ap_u.add_argument("--max-tokens", type=int, default=None)
    ap_u.add_argument("--out", help="保存到文件")
    ap_u.add_argument("--show-usage", action="store_true")

    args = ap.parse_args()
    cfg = load_config()
    t0 = time.time()
    if args.cmd == "transcribe":
        do_transcribe(cfg, args, t0)
    elif args.cmd == "understand":
        do_understand(cfg, args, t0)


if __name__ == "__main__":
    main()
