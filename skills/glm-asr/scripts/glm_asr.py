#!/usr/bin/env python3
"""glm-asr: 智谱 GLM-ASR-2512 语音转文本 CLI。

用法：
  python3 glm_asr.py <音频文件>                    # 转录，文本到 stdout
  python3 glm_asr.py meeting.mp3 --hotwords "智谱,AutoGLM"
  python3 glm_asr.py audio.wav --prompt "这是一段医学讲座"
  python3 glm_asr.py a.mp3 --out transcript.txt

配置：config.json（与脚本同目录的上级）—— base_url / model / api_key 可改。
     api_key 读取顺序：环境变量 GLM_ASR_API_KEY > config.json 的 api_key 字段。
限制（API 侧）：wav/mp3，≤25MB，≤30 秒。超长音频请先用 ffmpeg 切分：
     ffmpeg -i in.mp3 -f segment -segment_time 28 -c copy out_%03d.mp3
输出：转录文本到 stdout；错误到 stderr，退出码非 0。
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"
AUDIO_EXTS = {".wav": "audio/wav", ".mp3": "audio/mpeg"}
MAX_BYTES = 25 * 1024 * 1024


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        sys.exit(f"[glm-asr] config 不存在: {CONFIG_PATH}")
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    key = os.environ.get(cfg.get("api_key_env") or "GLM_ASR_API_KEY", "").strip() \
        or (cfg.get("api_key") or "").strip()
    if not key:
        sys.exit("[glm-asr] 未配置 api_key：设置环境变量 GLM_ASR_API_KEY 或填入 config.json")
    cfg["api_key"] = key
    return cfg


def check_audio(path: Path) -> str:
    """存在性/格式/大小校验，返回 mime。magic bytes 自证，不信扩展名。"""
    if not path.is_file():
        raise SystemExit(f"[glm-asr] 音频不存在: {path}")
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise SystemExit(f"[glm-asr] 文件过大（{size/1048576:.1f}MB > 25MB）。"
                         "超 30 秒的长音频请先切分：ffmpeg -i in.mp3 -f segment -segment_time 28 -c copy out_%03d.mp3")
    head = path.read_bytes()[:12]
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[4:8] == b"ftyp":
        raise SystemExit(
            f"[glm-asr] 检测到视频容器（MP4/MOV/m4a）——ASR API 不收视频，先抽音轨："
            f"ffmpeg -i {path.name} -vn -b:a 64k {path.stem}.mp3")
    raise SystemExit(
        f"[glm-asr] 不是 wav/mp3 音频（magic={head[:4].hex()}）。"
        f"API 仅支持 wav/mp3（实测伪装后缀也会被服务端拒绝）；"
        f"其他格式先转：ffmpeg -i {path.name} {path.stem}.mp3")


def build_multipart(cfg: dict, audio_path: Path, mime: str,
                    hotwords: list, prompt: str) -> tuple:
    """multipart/form-data（file 二进制方式，服务端解析最稳）。"""
    boundary = "----glmasr9d2c"
    parts = []
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
                 f'{cfg["model"]}\r\n'.encode())
    if hotwords:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="hotwords"\r\n\r\n'
                     f'{json.dumps(hotwords, ensure_ascii=False)}\r\n'.encode())
    if prompt:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="prompt"\r\n\r\n'
                     f'{prompt}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                 f'filename="{audio_path.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
    parts.append(audio_path.read_bytes())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    ctype = f"multipart/form-data; boundary={boundary}"
    return body, ctype


def call(cfg: dict, body: bytes, ctype: str) -> dict:
    url = cfg["base_url"].rstrip("/") + "/audio/transcriptions"
    timeout = cfg.get("timeout_ms", 120000) / 1000
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": ctype,
                 "Authorization": f"Bearer {cfg['api_key']}"})
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
            raise SystemExit("[glm-asr] 401: API Key 无效或过期（检查 config.json / GLM_ASR_API_KEY）")
        if e.code == 429:
            raise SystemExit("[glm-asr] 429（code 1302）: 并发/频率超限——并发勿超 10，退避 1-2s 重试；高峰期 14:00-18:00 更严")
        raise SystemExit(f"[glm-asr] HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"[glm-asr] 网络失败: {e.reason}")


def main():
    ap = argparse.ArgumentParser(prog="glm-asr", description="智谱 GLM-ASR-2512 语音转文本")
    ap.add_argument("audio", help="音频文件（wav/mp3，≤25MB，≤30秒）")
    ap.add_argument("--hotwords", default="", help="逗号分隔热词（专有名词/项目代号，提升识别率）")
    ap.add_argument("--prompt", default="", help="上下文提示（长文本场景的前文转录）")
    ap.add_argument("--out", help="保存到文件（不传则打印到 stdout）")
    ap.add_argument("--show-usage", action="store_true", help="stderr 打印延迟信息")
    args = ap.parse_args()

    cfg = load_config()
    audio_path = Path(args.audio).expanduser()
    mime = check_audio(audio_path)
    hotwords = [h.strip() for h in args.hotwords.split(",") if h.strip()][:100]
    body, ctype = build_multipart(cfg, audio_path, mime, hotwords, args.prompt)

    t0 = time.time()
    resp = call(cfg, body, ctype)
    text = (resp.get("text") or "").strip()
    if not text:
        raise SystemExit(f"[glm-asr] 转录结果为空 | 响应keys={sorted(resp.keys())}")

    if args.out:
        out = Path(args.out).expanduser()
        out.write_text(text + "\n", encoding="utf-8")
        print(f"转录完成 → {out}", file=sys.stderr)
    print(text)
    if args.show_usage:
        print(f"[glm-asr] model={resp.get('model','?')} "
              f"latency={int((time.time()-t0)*1000)}ms bytes={audio_path.stat().st_size}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
