#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书单篇下载器 (xhs-dl) — v1.2 独立版

给一个小红书链接，出一张资源卡片（+素材）。单篇、极简、完全自包含。

用法:
  python3 xhs.py <小红书链接> [更多链接...]

输出:
  out/<note_id>.md          资源卡片(核心产物)
  out/<note_id>/            图文原图(仅图文笔记)

自包含能力:
  - 内置本地 ASR: sherpa-onnx + paraformer-bilingual int8 模型(224MB)
    → 视频口播转写完全本地, 中英混合识别
  - 内置本地 OCR: ocrmac(macOS Vision 框架), 有口播也抽帧补工具名/无口播抽首帧/图文原图
  - 双路径: 视频(yt-dlp直链→ffmpeg拉音频→本地转写) / 图文(页面解析→原图)

依赖:
  - models/    ASR 模型(224MB, 跨架构通用)
  - .venv/     Python 环境(跨平台: Mac=ocrmac / Windows=winrt) — 需先运行 python3 scripts/setup.py
  - yt-dlp / ffmpeg: 系统安装(Mac: brew install / Windows: 加入 PATH 或同目录)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if BASE_DIR.name == "scripts":
    BASE_DIR = BASE_DIR.parent  # Skill 自包含: 模型/产物在 skill 根下

# ── venv 引导: 当前 python 无 sherpa_onnx 时自动用 .venv 重执行 ──
def _venv_python() -> Path:
    """跨平台 venv 解释器路径: Windows 在 Scripts/, Mac/Linux 在 bin/"""
    if sys.platform == "win32":
        return BASE_DIR / ".venv" / "Scripts" / "python.exe"
    return BASE_DIR / ".venv" / "bin" / "python"


def _ensure_venv():
    try:
        import sherpa_onnx  # noqa: F401
        return
    except ImportError:
        venv_py = _venv_python()
        if venv_py.exists():
            os.execv(str(venv_py), [str(venv_py)] + sys.argv)
        print("❌ 缺少 Python 环境 (.venv 不存在或当前 Python 无 sherpa_onnx)")
        print("   请先运行:  python3 scripts/setup.py   （跨平台安装脚本）")
        sys.exit(1)


_ensure_venv()

# ─────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────
OUT_DIR = BASE_DIR / "out"                 # 资源卡片 + 图文原图
ASR_MODEL_DIR = BASE_DIR / "models" / "paraformer-bilingual"  # Paraformer 中英双语 (213MB, 英文工具名准)

import shutil


def _find_tool(name: str, candidates: list) -> str:
    """定位工具: PATH → 常见安装位置 → 原样(让系统报错)"""
    p = shutil.which(name)
    if p:
        return p
    for c in candidates:
        if Path(c).exists():
            return c
    return name


def _venv_tool(name: str) -> str:
    """优先用 .venv 内置工具(如 yt-dlp 由 setup.py 装进 venv)"""
    if sys.platform == "win32":
        cand = BASE_DIR / ".venv" / "Scripts" / f"{name}.exe"
    else:
        cand = BASE_DIR / ".venv" / "bin" / name
    if cand.exists():
        return str(cand)
    return ""


YTDLP = (os.environ.get("YTDLP") or _venv_tool("yt-dlp")
         or _find_tool("yt-dlp", [
             os.path.expanduser("~/Library/Python/3.9/bin/yt-dlp"),
             "/opt/homebrew/bin/yt-dlp",
             "/usr/local/bin/yt-dlp",
         ]))
FFMPEG = os.environ.get("FFMPEG") or _find_tool("ffmpeg", [
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
])
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36")


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ─────────────────────────────────────────────
# 1. 链接解析
# ─────────────────────────────────────────────
def resolve_short_url(url: str) -> str:
    """解析 xhslink.cn 短链 → 最终真实 URL"""
    if "xhslink.cn" in url:
        try:
            r = subprocess.run(
                ["curl", "-sL", "-A", UA, "-o", "/dev/null", "-w", "%{url_effective}", url],
                capture_output=True, text=True, timeout=30)
            final = r.stdout.strip()
            if final and "xiaohongshu.com" in final:
                log(f"  短链解析 → {final[:70]}...")
                return final
        except Exception as e:
            log(f"  ⚠️ 短链解析失败: {e}")
    return url


def extract_note_id(url: str):
    m = re.search(r"/(?:explore|discovery/item)/([0-9a-f]{20,})", url)
    return m.group(1) if m else None


# ─────────────────────────────────────────────
# 2a. 视频笔记: yt-dlp 元数据
# ─────────────────────────────────────────────
def fetch_video_meta(url: str, note_id: str) -> dict:
    target = url if "xsec_token" in url else f"https://www.xiaohongshu.com/discovery/item/{note_id}"
    cmd = [YTDLP, "--skip-download", "--dump-json", "--no-warnings",
           f"--add-header=User-Agent:{UA}", target]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:])
    return json.loads(r.stdout.strip().splitlines()[-1])


# ─────────────────────────────────────────────
# 2b. 图文笔记: 页面 __INITIAL_STATE__ 解析
# ─────────────────────────────────────────────
def _fetch_page(url: str) -> str:
    r = subprocess.run(
        ["curl", "-sL", "-A", UA, "-H", "Referer: https://www.xiaohongshu.com/", url],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or len(r.stdout) < 1000:
        raise RuntimeError("页面抓取失败(可能被风控)")
    return r.stdout


def _extract_initial_state(html: str) -> str:
    """括号配对精确截取 __INITIAL_STATE__ 对象(贪婪正则会把后续 JS 吞进来)"""
    idx = html.find("__INITIAL_STATE__=")
    if idx < 0:
        raise RuntimeError("页面无 __INITIAL_STATE__")
    start = idx + len("__INITIAL_STATE__=")
    depth, in_str, esc = 0, False, False
    for i in range(start, min(start + 500000, len(html))):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
    raise RuntimeError("INITIAL_STATE 对象未闭合")


def _js_to_json(raw: str) -> dict:
    """yt-dlp 的 js_to_json 处理非标准 JS 字面量(undefined 等)"""
    try:
        from yt_dlp.utils import js_to_json
    except ImportError:
        # venv 里没有 yt_dlp 时, 用简版: 把 undefined/null 替换为合法 JSON
        raw = re.sub(r":\s*undefined", ":null", raw)
        return json.loads(raw)
    return json.loads(js_to_json(raw))


def fetch_image_note(url: str, note_id: str) -> dict:
    html = _fetch_page(url)
    state = _js_to_json(_extract_initial_state(html))
    ndm = state.get("note", {}).get("noteDetailMap", {})
    note = None
    for v in ndm.values():
        note = v.get("note", {})
        break
    if not note:
        raise RuntimeError("页面无 noteDetailMap")
    user = note.get("user", {}) or {}
    images = [img.get("urlDefault", "") for img in (note.get("imageList", []) or []) if img.get("urlDefault")]
    return {
        "id": note.get("noteId", note_id),
        "title": note.get("title", ""),
        "desc": note.get("desc", ""),
        "tags": [t.get("name", "") for t in (note.get("tagList", []) or [])],
        "uploader": user.get("nickname", ""),
        "uploader_id": user.get("userId", ""),
        "note_type": "image",
        "images": images,
        "duration": None,
        "webpage_url": url,
    }


# ─────────────────────────────────────────────
# 3. 视频 → 音频 → 本地 ASR 转写(内置 sherpa-onnx)
# ─────────────────────────────────────────────
_recognizer = None


def get_recognizer():
    """懒加载内置 ASR 模型(24MB)"""
    global _recognizer
    if _recognizer is None:
        import sherpa_onnx
        t0 = time.time()
        _recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=f"{ASR_MODEL_DIR}/model.int8.onnx",
            tokens=f"{ASR_MODEL_DIR}/tokens.txt",
            num_threads=2, provider="cpu",
            decoding_method="greedy_search",
        )
        log(f"  🧠 ASR 模型加载: {time.time()-t0:.1f}s (paraformer-bilingual 224MB)")
    return _recognizer


def local_transcribe(wav_path: Path) -> str:
    """本地转写 wav(16k 单声道) → 文本"""
    import numpy as np
    import wave
    rec = get_recognizer()
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    t0 = time.time()
    s = rec.create_stream()
    s.accept_waveform(sr, samples)
    try:
        if hasattr(rec, "is_ready"):      # 流式
            while rec.is_ready(s):
                rec.decode_stream(s)
            text = rec.get_result(s)
        else:                              # 离线
            rec.decode_stream(s)
            text = s.result.text
    except Exception as e:
        log(f"  ⚠️ 解码异常(无语音?): {str(e)[:80]}，走 OCR 兜底")
        text = ""
    dur = len(samples) / sr
    log(f"  ✍️ 转写 {dur:.1f}s 音频, 耗时 {time.time()-t0:.1f}s")
    return text


def get_video_url(meta: dict):
    fmts = meta.get("formats") or []
    for f in sorted(fmts, key=lambda x: x.get("height") or 0, reverse=True):
        if f.get("url") and f.get("vcodec") != "none":
            return f["url"]
    return None


def extract_audio(video_url: str, out_wav: Path) -> bool:
    """从直链拉音频流(视频零落盘)"""
    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-headers", f"User-Agent: {UA}\r\nReferer: https://www.xiaohongshu.com/\r\n",
           "-i", video_url, "-vn", "-ar", "16000", "-ac", "1", "-f", "wav", str(out_wav)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not out_wav.exists():
        log(f"  ⚠️ 音频提取失败: {r.stderr[-200:]}")
        return False
    return True


# ─────────────────────────────────────────────
# 4. 图文原图下载
# ─────────────────────────────────────────────
def download_images(image_urls: list, note_id: str) -> list:
    if not image_urls:
        return []
    out_dir = OUT_DIR / note_id
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, url in enumerate(image_urls[:9]):
        ext = ".png" if ".png" in url else (".webp" if ".webp" in url else ".jpg")
        out = out_dir / f"{i+1:02d}{ext}"
        if out.exists():
            saved.append(out.name)
            continue
        try:
            r = subprocess.run(
                ["curl", "-sL", "-o", str(out), "-A", UA,
                 "-H", "Referer: https://www.xiaohongshu.com/", url],
                capture_output=True, timeout=60)
            if r.returncode == 0 and out.exists() and out.stat().st_size > 1000:
                saved.append(out.name)
            else:
                out.unlink(missing_ok=True)
        except Exception:
            out.unlink(missing_ok=True)
    if saved:
        log(f"  🖼️ 原图 {len(saved)} 张 → out/{note_id}/")
    return saved


# ─────────────────────────────────────────────
# 4.5 画面 OCR (macOS Vision 框架, ocrmac)
# ─────────────────────────────────────────────
def ocr_image(image_path: Path) -> str:
    """跨平台 OCR: Mac→ocrmac(Vision 框架) / Windows→winrt-Windows.Media.Ocr。

    Windows 分支代码完整, 但需 Windows 真机验证后才算"可用"。
    """
    if sys.platform == "darwin":
        try:
            from ocrmac import ocrmac
            ann = ocrmac.OCR(str(image_path), language_preference=['zh-Hans', 'en-US']).recognize()
            texts = [t for t, c, b in ann if c > 0.3]
            return " ".join(texts).strip()
        except Exception:
            return ""
    elif sys.platform == "win32":
        try:
            import asyncio
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.graphics.imaging import BitmapDecoder
            from winrt.windows.storage import StorageFile
            from winrt.windows.storage.streams import FileAccessMode

            async def _ocr():
                file = await StorageFile.get_file_from_path_async(str(image_path))
                stream = await file.open_async(FileAccessMode.READ)
                decoder = await BitmapDecoder.create_async(stream)
                bitmap = await decoder.get_software_bitmap_async()
                lang = None
                for l in OcrEngine.available_recognizer_languages:
                    if l.language_tag.lower().startswith("zh"):
                        lang = l
                        break
                if lang is None and OcrEngine.available_recognizer_languages:
                    lang = OcrEngine.available_recognizer_languages[0]
                if lang is None:
                    return ""
                engine = OcrEngine.try_create_from_language(lang)
                if engine is None:
                    engine = OcrEngine.try_create_from_user_profile_languages()
                result = await engine.recognize_async(bitmap)
                return " ".join(line.text for line in result.lines)

            return asyncio.run(_ocr()).strip()
        except Exception:
            return ""
    return ""


def grab_frame(video_url: str, t: float, out_jpg: Path) -> bool:
    """从直链抽第 t 秒的一帧 (CDN 支持 range, 无需下载整片)"""
    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-headers", f"User-Agent: {UA}\r\nReferer: https://www.xiaohongshu.com/\r\n",
           "-ss", str(t), "-i", video_url, "-frames:v", "1", "-q:v", "2", str(out_jpg)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and out_jpg.exists() and out_jpg.stat().st_size > 1000
    except Exception:
        return False


def ocr_video_frames(video_url: str, duration: float, interval: int = 15) -> list:
    """有口播视频也抽帧 OCR: 首帧 + 每 interval 秒一帧, 专治生僻工具名 ASR 音译错乱。

    画面上的项目名/仓库名是白纸黑字, 比任何 ASR 都权威 (GitHub 周榜类视频尤甚)。
    返回每帧 OCR 文本列表(有文字的), 帧图片用完即删。
    """
    out_dir = OUT_DIR / "_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    texts = []
    ts = [1] + list(range(0, int(duration) + 1, interval))
    seen = set()
    for t in ts:
        if t in seen:
            continue
        seen.add(t)
        out = out_dir / f"t{t:03d}.jpg"
        try:
            if grab_frame(video_url, t, out):
                txt = ocr_image(out)
                if txt:
                    texts.append(f"[t={t}s] {txt}")
        finally:
            out.unlink(missing_ok=True)
    return texts


def ocr_first_frame(video_url: str, out_jpg: Path) -> str:
    """抽视频首帧并 OCR(用于无口播演示类视频)。失败返回空串。"""
    cmd = [FFMPEG, "-y", "-loglevel", "error",
           "-headers", f"User-Agent: {UA}\r\nReferer: https://www.xiaohongshu.com/\r\n",
           "-ss", "1", "-i", video_url, "-frames:v", "1", "-q:v", "2", str(out_jpg)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and out_jpg.exists() and out_jpg.stat().st_size > 1000:
            return ocr_image(out_jpg)
    except Exception:
        pass
    return ""


# ─────────────────────────────────────────────
# 5. 资源卡片
# ─────────────────────────────────────────────
def build_card(note_id: str, url: str, meta: dict, transcript_text, images: list) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = meta.get("title") or "(无标题)"
    desc = meta.get("desc") or ""
    tags = meta.get("tags") or []
    note_type = meta.get("note_type", "video")
    duration = meta.get("duration")
    uploader = meta.get("uploader") or "未知"
    uploader_id = meta.get("uploader_id") or ""
    icon = "🎬 视频" if note_type == "video" else "🖼️ 图文"

    L = [f"# 📌 {title}", "",
         f"- **类型**: {icon}",
         f"- **来源**: 小红书 ({url.split('?')[0]})",
         f"- **note_id**: `{note_id}`",
         f"- **博主**: {uploader} (`{uploader_id}`)"]
    if duration:
        L.append(f"- **时长**: {duration}s")
    L += [f"- **收录**: {ts}", ""]

    if note_type == "image" and len(desc.strip()) < 100:
        L += ["> ⚠️ **正文较短**，核心信息可能在图片中，建议人工查看", ""]
    if desc:
        L += ["## 📝 正文", "", desc, ""]
    if tags:
        L += ["## 🏷️ 标签", "", " ".join(f"`#{t}`" for t in tags), ""]
    if transcript_text:
        L += ["## 🎙️ 口播转写", "", "> " + transcript_text.replace("\n", " "), ""]
    elif note_type == "video":
        L += ["## 🎙️ 口播转写", "",
              "_（该视频无口播或语音微弱，转写为空——可能是纯音乐/画面演示类视频）_",
              "",
              "> ⚠️ **无配音演示类视频**：核心信息可能在画面中（界面演示/文字教程），建议人工查看画面获取细节", ""]
    ocr_t = meta.get("ocr_text") or ""
    if ocr_t:
        L += ["## 📺 画面OCR", "", "> " + ocr_t, ""]
    if images:
        L += ["## 🖼️ 图片", ""]
        for img in images:
            L.append(f"- `out/{note_id}/{img}`")
        L.append("")
    repos = sorted(set(re.findall(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", ocr_t))) if ocr_t else []
    L += ["## 💡 资源线索", "",
          "- 标签中的疑似项目/工具: " + ("、".join(t for t in tags if re.match(r"^[A-Za-z][A-Za-z0-9_-]{2,}$", t)) or "(无明显英文标签)"),
          "- 正文/口播中的疑似资源: (由 AI 提炼)",
          "- 画面OCR中的项目/仓库: " + ("、".join(repos) if repos else "(无)"),
          "", "---", ""]
    return "\n".join(L)


# ─────────────────────────────────────────────
# 6. 主流程(单篇)
# ─────────────────────────────────────────────
def process_link(url: str) -> bool:
    full_url = resolve_short_url(url)
    note_id = extract_note_id(full_url)
    if not note_id:
        log(f"❌ 无法提取 note_id: {url}")
        return False
    log(f"▶️ {note_id}")

    meta = None
    transcript_text = None
    images = []
    try:
        meta = fetch_video_meta(full_url, note_id)
        meta["note_type"] = "video"
        log(f"  🎬 视频 | {(meta.get('title') or note_id)[:40]}")
    except RuntimeError as e:
        if "No video formats" in str(e) or "formats" in str(e).lower():
            log("  🖼️ 图文(yt-dlp无视频流, 走页面解析)")
            try:
                meta = fetch_image_note(full_url, note_id)
            except RuntimeError as e2:
                log(f"  ❌ 图文解析失败: {e2}")
                return False
        else:
            log(f"  ❌ 视频元数据失败: {e}")
            return False

    if meta["note_type"] == "video":
        vurl = get_video_url(meta)
        if vurl:
            OUT_DIR.mkdir(parents=True, exist_ok=True)  # 全新安装 out/ 可能不存在
            wav = OUT_DIR / f"{note_id}.wav"
            if extract_audio(vurl, wav):
                log(f"  🎵 音频就绪 ({wav.stat().st_size//1024}KB), 本地转写...")
                transcript_text = local_transcribe(wav)
            wav.unlink(missing_ok=True)   # 音频用完即删
            # 画面 OCR 补工具名(无论有无口播): 生僻工具名 ASR 易错乱, 画面白纸黑字最准
            frame_texts = ocr_video_frames(vurl, meta.get("duration") or 0)
            if frame_texts:
                meta["ocr_text"] = " || ".join(frame_texts)
                log(f"  📺 画面OCR(补工具名): {len(frame_texts)} 帧有文字")
            # 无口播 → 抽首帧 OCR 补画面信息(演示类视频, 兜底)
            if not (transcript_text or "").strip() and not frame_texts:
                log("  📺 无口播, 抽首帧 OCR 补画面信息...")
                frame = OUT_DIR / f"{note_id}_frame.jpg"
                ocr_text = ocr_first_frame(vurl, frame)
                frame.unlink(missing_ok=True)
                if ocr_text:
                    meta["ocr_text"] = ocr_text
                    log(f"  📺 画面OCR: {ocr_text[:40]}...")
        else:
            log("  ⚠️ 无视频直链, 仅元数据")
    else:
        images = download_images(meta.get("images", []), note_id)
        # 图文: 原图 OCR 补图内文字
        ocr_parts = []
        for img in images:
            t = ocr_image(OUT_DIR / note_id / img)
            if t:
                ocr_parts.append(t)
        if ocr_parts:
            meta["ocr_text"] = " | ".join(ocr_parts)
            log(f"  📺 图文OCR: {len(ocr_parts)} 张图有文字")

    card = build_card(note_id, full_url, meta, transcript_text, images)
    out_md = OUT_DIR / f"{note_id}.md"
    out_md.write_text(card)
    log(f"  ✅ 卡片 → out/{note_id}.md")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    links = sys.argv[1:]
    ok = fail = 0
    for i, link in enumerate(links):
        log(f"── [{i+1}/{len(links)}] ──")
        if process_link(link):
            ok += 1
        else:
            fail += 1
    log(f"══ 完成: 成功 {ok}, 失败 {fail} ══")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
