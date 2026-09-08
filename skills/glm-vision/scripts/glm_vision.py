#!/usr/bin/env python3
"""glm-vision: 智谱 GLM-5.3-flash 视觉理解 CLI。

用法：
  python3 glm_vision.py <图片路径或URL> [--prompt "问题"] [--json] [--max-tokens N]
  python3 glm_vision.py img1.jpg img2.png --prompt "对比这两张图"
  python3 glm_vision.py screenshot.png --json --prompt "提取页面所有文字"

配置：config.json（与脚本同目录的上级）—— base_url / model / api_key 可改。
     api_key 读取顺序：环境变量 GLM_VISION_API_KEY > config.json 的 api_key 字段。
输出：正文到 stdout；错误到 stderr，退出码非 0。
"""
from __future__ import annotations
import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"
DEFAULT_PROMPT = "详细描述这张图片的内容。"


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        sys.exit(f"[glm-vision] config 不存在: {CONFIG_PATH}")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    key = os.environ.get(cfg.get("api_key_env") or "GLM_VISION_API_KEY", "").strip() \
        or (cfg.get("api_key") or "").strip()
    if not key:
        sys.exit("[glm-vision] 未配置 api_key：设置环境变量 GLM_VISION_API_KEY 或填入 config.json")
    cfg["api_key"] = key
    return cfg


def to_data_url(path: str) -> str:
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"图片不存在: {path}")
    size = p.stat().st_size
    if size > 10 * 1024 * 1024:
        raise ValueError(f"图片过大（{size/1048576:.1f}MB > 10MB），请压缩后重试")
    mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
    if not mime.startswith("image/"):
        raise ValueError(f"不是图片文件: {path} ({mime})")
    data = base64.b64encode(p.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


def download_as_data_url(url: str) -> str:
    """下载 URL 图片转 Base64 Data URL。
    Coding Plan 端点实测不支持 URL 直传（报 1210/类型非法，且错误信息误导），
    因此 URL 一律本地下载转 Base64——顺带获得 UA/大小控制/失败明确报错。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (glm-vision skill)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            ct = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[glm-vision] 图片下载失败 HTTP {e.code}: {url}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise SystemExit(f"[glm-vision] 图片下载失败: {url} ({e})")
    if len(data) > 10 * 1024 * 1024:
        raise SystemExit(f"[glm-vision] 图片过大（{len(data)/1048576:.1f}MB > 10MB）: {url}")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        mime = "image/gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        # Content-Type 兜底（magic 不认识时）
        mime = ct if ct.startswith("image/") else ""
        if not mime:
            raise SystemExit(f"[glm-vision] URL 不是图片（magic 未知, content-type={ct or '无'}）: {url}")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


VIDEO_EXTS = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
              ".mkv": "video/x-matroska", ".webm": "video/webm"}


def is_video(src: str) -> bool:
    if src.lower().endswith(tuple(VIDEO_EXTS)):
        return True
    return False


def media_block(src: str, force_download: bool = False) -> dict:
    """构造 image_url / video_url 内容块。
    图片：URL 直传（默认）；--download 或拉取失败时降级本地下载转 Base64。
    视频：本地文件转 Base64 Data URL；URL 视频直传。"""
    if src.startswith(("http://", "https://")):
        if is_video(src):
            return {"type": "video_url", "video_url": {"url": src}}
        if force_download:
            return {"type": "image_url", "image_url": {"url": download_as_data_url(src)}}
        return {"type": "image_url", "image_url": {"url": src}}
    if is_video(src):
        p = Path(src).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"视频不存在: {src}")
        size = p.stat().st_size
        if size > 50 * 1024 * 1024:
            raise ValueError(f"视频过大（{size/1048576:.1f}MB > 50MB），请压缩或截短")
        mime = VIDEO_EXTS.get(p.suffix.lower(), "video/mp4")
        data = base64.b64encode(p.read_bytes()).decode()
        return {"type": "video_url", "video_url": {"url": f"data:{mime};base64,{data}"}}
    if force_download:
        if src.startswith(("http://", "https://")):
            return {"type": "image_url", "image_url": {"url": download_as_data_url(src)}}
    return {"type": "image_url", "image_url": {"url": to_data_url(src)}}


def build_payload(cfg: dict, images: list, prompt: str, as_json: bool, max_tokens: int,
                  force_download: bool = False) -> dict:
    if as_json:
        prompt = prompt + "\n\n要求：只输出合法 JSON，不要输出其他文字或 markdown 代码块。"
    content = [media_block(s, force_download) for s in images]
    content.append({"type": "text", "text": prompt})
    return {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": cfg.get("temperature", 1.0),
        "top_p": cfg.get("top_p", 0.95),
    }


def call(cfg: dict, payload: dict) -> dict:
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    timeout = cfg.get("timeout_ms", 120000) / 1000
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg['api_key']}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if e.code == 401:
            raise SystemExit("[glm-vision] 401: API Key 无效或过期（检查 config.json / GLM_VISION_API_KEY）")
        if e.code == 429:
            raise SystemExit("[glm-vision] 429: 限流（Coding Plan 上限约 5 QPS，稍后重试）")
        raise SystemExit(f"[glm-vision] HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[glm-vision] 网络失败: {e.reason}")


def extract_text(resp: dict) -> tuple:
    """智谱 GLM-5.3-flash 是推理模型：content 常为 null，正文在 reasoning_content。
    两个都取，content 优先。返回 (text, usage, model, raw_content_empty)。"""
    try:
        msg = resp["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        raise SystemExit(f"[glm-vision] 响应结构异常: {e} | keys={list(resp.keys())}")
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    text = content or reasoning
    if not text:
        raise SystemExit(
            f"[glm-vision] 空回答（content=null 且 reasoning_content 为空）| "
            f"finish={resp['choices'][0].get('finish_reason')} | "
            f"考虑增大 max_tokens 或检查图片有效性")
    usage = resp.get("usage") or {}
    model = resp.get("model", "?")
    return text, usage, model, not content.strip()


def main():
    ap = argparse.ArgumentParser(prog="glm-vision", description="智谱 GLM-5.3-flash 视觉理解")
    ap.add_argument("images", nargs="+", help="图片路径或 URL（可多张）")
    ap.add_argument("-p", "--prompt", default=DEFAULT_PROMPT, help="提问/指令")
    ap.add_argument("--json", action="store_true", help="要求模型输出 JSON")
    ap.add_argument("--max-tokens", type=int, default=None, help="覆盖 config 的 max_tokens")
    ap.add_argument("--download", action="store_true",
                    help="图片 URL 强制本地下载转 Base64（对国外源等智谱拉取困难的 URL 有用）")
    ap.add_argument("--show-usage", action="store_true", help="stderr 打印 token 用量")
    args = ap.parse_args()

    cfg = load_config()
    if len(args.images) > 5:
        print("[glm-vision] 提示：一次超过 5 张图可能影响质量与限流", file=sys.stderr)

    max_tokens = args.max_tokens or cfg.get("max_tokens", 4096)
    payload = build_payload(cfg, args.images, args.prompt, args.json, max_tokens,
                            force_download=args.download)

    t0 = time.time()
    resp = call(cfg, payload)
    text, usage, model, used_reasoning = extract_text(resp)

    print(text)
    if args.show_usage:
        latency = int((time.time() - t0) * 1000)
        print(f"\n[usage] model={model} latency={latency}ms "
              f"prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} "
              f"reasoning_mode={'yes' if used_reasoning else 'no'}", file=sys.stderr)


if __name__ == "__main__":
    main()
