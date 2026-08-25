#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scribe · 本地录音转写工具 — 一体化服务（FastAPI 后端 + 内置前端）。

架构：
  启动时 lifespan 常驻加载 SenseVoice-Small + FSMN-VAD（一次性，首次 ~15s），
  之后每次转写只付推理时间（实测 RTF ≈ 0.04，25 倍实时）。
  CAM++ 声纹模型（28MB）按需懒加载——只有勾选「标记说话人」时才加载。

  GET  /                内置单页前端（frontend/index.html）
  GET  /api/health      模型 / 解码器状态
  POST /api/transcribe  上传任意音频/视频 → 归一化 16k wav → VAD+ASR → 句级时间戳
                        ?diarize=true 追加说话人标记（说话人 1/2/3…）
  WS   /ws/live         实时转录：浏览器 MediaRecorder 推流 → 流式 VAD 切段
                        → 段闭合即识别广播 → 停顿出 partial → 可选说话人

音频解码优先级：项目内置 bin/ffmpeg → 系统 ffmpeg → macOS 原生 afconvert 兜底。

运行位置说明（外部硬盘部署）：
  项目位于本项目文件夹（路径任意，可整体拷贝移动），启动时把 TMPDIR / MODELSCOPE_CACHE / HF_HOME /
  XDG_CACHE_HOME 全部钉到项目内 data/tmp 与 data/cache——上传临时文件、模型缓存、
  torch hub 产物一律写外置盘，不碰系统盘。这些环境变量必须在 import fastapi /
  funasr 之前设置（它们在建临时文件/选缓存根时就读取环境），所以放在文件顶部。
转写核心逻辑复用 transcribe.py（单一事实源，CLI 与服务共用）。

时长上限说明：
  无 VAD 时 SenseVoice 单段动态 batch 默认 300s（官方建议短语音 ≤30s）；
  本工具始终走 VAD 切片路线，单段通常 <30s，整体音频时长只受内存限制，
  小时级播客/访谈可直接拖入；实时模式则天然无限时长（边录边出）。

运行：python3 server.py    或    ./start.sh
"""
import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import queue as queue_mod
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

# —— 环境钉桩：所有临时/缓存目录强制落到项目内（外置盘），防系统盘被写满。
#    必须在任何会读这些变量的 import（fastapi/funasr/torch…）之前设置。
BASE = Path(__file__).resolve().parent
if BASE.name == "scripts":
    BASE = BASE.parent  # Skill 自包含: 项目根 = scripts/ 上一级
_TMP = BASE / "data" / "tmp"
_TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMPDIR"] = str(_TMP)  # 强制覆盖：系统 TMPDIR 指向系统盘
os.environ.setdefault("MODELSCOPE_CACHE", str(BASE / "data" / "cache" / "modelscope"))
os.environ.setdefault("HF_HOME", str(BASE / "data" / "cache" / "huggingface"))
os.environ.setdefault("XDG_CACHE_HOME", str(BASE / "data" / "cache"))

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from transcribe import transcribe as transcribe_core, fmt_s as fmt_hms, fmt_srt
from realtime import LiveSession

ASR_DIR = str(BASE / "models" / "SenseVoiceSmall")
VAD_DIR = str(BASE / "models" / "speech_fsmn_vad")
SV_DIR = str(BASE / "models" / "campplus_sv")
FFMPEG_LOCAL = BASE / "bin" / "ffmpeg"
FRONTEND_DIR = BASE / "frontend"
OUT_DIR = BASE / "data" / "outputs"  # 仅兼容旧文件下载；新产物按项目落 outputs/<项目名>/
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _safe_name(name: str) -> str:
    """项目名 → 安全目录名：去除路径分隔与特殊字符，空则兜底。保留中文。"""
    import re as _re
    name = _re.sub(r'[\\/:*?"<>|]', "", (name or "")).strip().strip(".")[:80]
    return name or "未命名"


def _job_basename(project: str) -> str:
    """同一项目内产物命名：毫秒时间戳保证多次录音各自独立、按时间排序。"""
    return str(int(time.time() * 1000))
PORT = int(os.environ.get("SCRIBE_PORT", "8399"))

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("scribe")


# ---------- 音频解码：内置 ffmpeg → 系统 ffmpeg → afconvert 兜底 ----------

def _resolve_decoder():
    if FFMPEG_LOCAL.exists() and os.access(FFMPEG_LOCAL, os.X_OK):
        return "ffmpeg", str(FFMPEG_LOCAL)
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return "ffmpeg", sys_ff
    if shutil.which("afconvert"):
        return "afconvert", shutil.which("afconvert")
    return None, None


def to_wav(src_path: str, dst_path: str) -> float:
    """任意音视频 → 16kHz 单声道 wav。返回源时长（秒）。

    注意：ffmpeg 对「无扩展名的输出路径」不会自动推断 wav 格式，
    会误判成「输出=输入」而拒绝执行 —— 所以显式加 -f wav。
    """
    kind, exe = _resolve_decoder()
    if kind is None:
        raise HTTPException(500, "没有可用的音频解码器（缺 bin/ffmpeg 与 afconvert）")
    if kind == "ffmpeg":
        subprocess.run([exe, "-y", "-v", "error", "-i", src_path,
                        "-ac", "1", "-ar", "16000", "-f", "wav", dst_path],
                       check=True, capture_output=True)
        probe = str(Path(exe).with_name("ffprobe"))
        if not Path(probe).exists():
            probe = shutil.which("ffprobe") or ""
        if probe:
            try:
                out = subprocess.run(
                    [probe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=nw=1:nk=1", src_path],
                    capture_output=True, text=True)
                return float(out.stdout.strip() or 0)
            except Exception:
                return 0.0
        return 0.0
    else:  # afconvert：macOS 原生兜底，不支持视频容器
        subprocess.run([exe, "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                        src_path, dst_path], check=True, capture_output=True)
        return 0.0


# ---------- 应用状态：常驻模型 ----------

class State:
    asr = None
    vad = None
    sv = None               # CAM++ 声纹模型（懒加载，仅说话人模式用）
    lock = threading.Lock()      # 推理串行化（CPU 单模型实例）
    load_seconds = 0.0


def _load_models():
    from funasr import AutoModel
    t0 = time.time()
    State.asr = AutoModel(model=ASR_DIR, trust_remote_code=True,
                          device="cpu", disable_update=True)
    State.vad = AutoModel(model=VAD_DIR, trust_remote_code=True,
                          device="cpu", disable_update=True)
    State.load_seconds = time.time() - t0
    log.info("模型常驻完成，耗时 %.1fs", State.load_seconds)


def _load_sv():
    """CAM++ 懒加载：第一次勾选说话人标记时才占内存。"""
    if State.sv is None:
        from funasr import AutoModel
        t0 = time.time()
        State.sv = AutoModel(model=SV_DIR, trust_remote_code=True,
                             device="cpu", disable_update=True)
        log.info("CAM++ 声纹模型加载完成，耗时 %.1fs", time.time() - t0)
    return State.sv


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("正在加载 SenseVoice-Small + FSMN-VAD（一次性，首次约 15s）…")
    await asyncio.to_thread(_load_models)
    log.info("scribe 就绪 → http://localhost:%d", PORT)
    yield


app = FastAPI(title="scribe · 本地录音转写", lifespan=lifespan)


# ---------- API ----------

@app.get("/api/health")
def health():
    kind, exe = _resolve_decoder()
    free_gb = shutil.disk_usage(str(BASE)).free / (1024 ** 3)
    return {
        "ok": State.asr is not None,
        "base_dir": str(BASE),
        "tmpdir": os.environ.get("TMPDIR"),
        "disk_free_gb": round(free_gb, 1),
        "model_load_seconds": round(State.load_seconds, 1),
        "decoder": kind,
        "decoder_path": exe,
        "asr_model": "SenseVoice-Small (pt, 897MB)",
        "vad_model": "FSMN-VAD",
        "sv_model": "CAM++ (28MB, 按需加载)" if State.sv is not None else "CAM++ (28MB, 未加载)",
    }


def _render_sent(s: dict, diarize: bool) -> str:
    t = f"[{fmt_hms(s['start'])}] "
    if diarize and s.get("speaker"):
        t += f"{s['speaker']}: "
    return t + s["text"]


@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...),
                          diarize: str = Query("false", description="说话人标记: true/false")):
    # 宽松解析: 兼容 "true"/"1"/"yes"/"on" 各种客户端传法
    diarize = str(diarize).lower() in ("1", "true", "yes", "on")
    if State.asr is None:
        raise HTTPException(503, "模型仍在加载，稍后重试")
    suffix = Path(file.filename or "audio").suffix or ".bin"
    tmpdir = tempfile.mkdtemp(prefix="scribe_", dir=str(_TMP))
    src = os.path.join(tmpdir, "input" + suffix)
    wav = os.path.join(tmpdir, "converted.wav")
    try:
        # 流式落盘：长视频可能数百 MB，避免一次性读入内存，也方便定位磁盘空间问题
        try:
            with open(src, "wb") as f:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
        except OSError as e:
            if getattr(e, "errno", None) == 28:
                raise HTTPException(507, "磁盘空间不足，无法写入上传文件")
            raise HTTPException(400, f"保存上传文件失败：{e}")
        if not Path(src).exists() or Path(src).stat().st_size == 0:
            raise HTTPException(400, "空文件")

        t0 = time.time()
        try:
            src_duration = await asyncio.to_thread(to_wav, src, wav)
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode()[:200] if e.stderr else str(e)
            raise HTTPException(400, f"解码失败（不支持的格式？）：{err}")

        def _infer():
            with State.lock:
                sents = transcribe_core(State.asr, State.vad, wav)
                if diarize:
                    import soundfile as sf
                    from diarize import label_speakers
                    w, sr = sf.read(wav)
                    if w.ndim > 1:
                        w = w.mean(axis=1)
                    label_speakers(sents, w, sr, _load_sv())
                return sents

        sentences: List[dict] = await asyncio.to_thread(_infer)
        infer_s = time.time() - t0

        duration = src_duration or (sentences[-1]["end"] if sentences else 0)
        project = Path(file.filename or "audio").stem  # 上传模式：文件名即项目名
        base_name = _job_basename(project)
        _save_outputs(base_name, file.filename or "audio", duration, sentences, diarize, project)

        n_speakers = len({s.get("speaker") for s in sentences if s.get("speaker")}) if diarize else 0
        return {
            "job_id": base_name,
            "project": _safe_name(project),
            "source": file.filename,
            "duration_s": round(duration, 1),
            "infer_s": round(infer_s, 1),
            "rtf": round(infer_s / max(duration, 1), 3),
            "diarize": diarize,
            "n_speakers": n_speakers,
            "sentences": sentences,
            "downloads": {
                "txt": f"/api/download/{_safe_name(project)}/{base_name}.txt",
                "srt": f"/api/download/{_safe_name(project)}/{base_name}.srt",
                "json": f"/api/download/{_safe_name(project)}/{base_name}.json",
            },
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _save_outputs(base_name, source, duration, sentences, diarize, project="未命名"):
    """按项目落盘：outputs/<项目名>/<毫秒时间戳>.{txt,srt,json}，meta.json 存项目元信息。"""
    pdir = OUT_DIR / _safe_name(project)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "meta.json").write_text(json.dumps(
        {"project": _safe_name(project), "updated": int(time.time())},
        ensure_ascii=False, indent=2), encoding="utf-8")
    (pdir / f"{base_name}.txt").write_text(
        "\n".join(_render_sent(s, diarize) for s in sentences) + "\n", encoding="utf-8")
    (pdir / f"{base_name}.srt").write_text(
        "\n".join(
            f"{i}\n{fmt_srt(s['start'])} --> {fmt_srt(s['end'])}\n"
            f"{(s['speaker'] + ': ') if diarize and s.get('speaker') else ''}{s['text']}\n"
            for i, s in enumerate(sentences, 1)), encoding="utf-8")
    (pdir / f"{base_name}.json").write_text(json.dumps({
        "project": _safe_name(project),
        "source": source, "duration_s": round(duration, 1),
        "diarize": diarize, "sentences": sentences,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return _safe_name(project)


@app.get("/api/download/{name:path}")
def download(name: str):
    """支持 <项目名>/<文件> 两层路径；旧平铺文件仍可直接按文件名下载。"""
    p = (OUT_DIR / name).resolve()
    if not str(p).startswith(str(OUT_DIR.resolve())) or not p.exists() or p.is_dir():
        raise HTTPException(404, "文件不存在")
    from fastapi.responses import FileResponse
    return FileResponse(p, filename=p.name)


# ---------- 实时转录（WebSocket） ----------
#
# 协议（JSON 文本帧）：
#   → {"type":"start","diarize":bool,"project":str}  开始会话（重复发 = 重置）
#   → {"type":"block","seq":N,"data":"<b64>"}  一块 webm/opus（前端每 0.5s 推）
#   → {"type":"flush"}                         停顿，吐 partial（驻留段暂识别）
#   → {"type":"stop"}                          结束录音，收口剩余段落
#   ← {"type":"ready"} / {"type":"sentence"} / {"type":"partial"}
#     {"type":"final","job_id","downloads"}    / {"type":"error","message"}
#
# 处理在 worker 线程：drain 解码 + VAD，闭合段立即识别广播。
# 停顿检测由前端触发（>=1.6s 无新块 → flush），因为「没有音频」这件事
# 本身不会通过网络到达。

@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    sess: LiveSession = None
    loop = asyncio.get_event_loop()
    msg_q: queue_mod.Queue = queue_mod.Queue()
    stop_flag = threading.Event()

    async def send(obj):
        try:
            await ws.send_text(json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass

    def worker():
        nonlocal sess
        while not stop_flag.is_set():
            try:
                msg = msg_q.get(timeout=0.3)
            except queue_mod.Empty:
                # 空闲 tick：服务器驱动的 partial——录音中驻留段定期暂识别，
                # 实现「边录边出字」。不依赖前端 flush（浏览器计时器在后台
                # 标签页会被节流，且「没有音频」不会自己通过网络到来）。
                if sess:
                    try:
                        with State.lock:
                            for seg in sess.pump():
                                _emit(seg)
                            sent = sess.maybe_partial()
                        if sent:
                            asyncio.run_coroutine_threadsafe(
                                send({"type": "partial", **sent}), loop)
                    except Exception:
                        log.exception("live partial error")
                continue
            except Exception:
                log.exception("live queue error")
                break
            t = msg.get("type")
            try:
                if t == "start":
                    sess = LiveSession(State.asr, State.vad,
                                       bool(msg.get("diarize")), _load_sv)
                    sess.project = (msg.get("project") or "").strip() or (
                        "录音 " + time.strftime("%m-%d %H:%M"))
                    asyncio.run_coroutine_threadsafe(send({"type": "ready"}), loop)
                elif t == "block" and sess:
                    with State.lock:
                        sess.push_block(int(msg["seq"]), base64.b64decode(msg["data"]))
                        for seg in sess.drain():
                            _emit(seg)
                elif t == "flush" and sess:
                    # 兼容前端显式 flush：立即暂识别（绕过节流的最小间隔）
                    with State.lock:
                        for seg in sess.drain():
                            _emit(seg)
                        p = sess.vadstream.flush_partial()
                    if p:
                        with State.lock:
                            sent = sess.recognize(p["start"], p["end"], partial=True)
                        if sent:
                            sess.last_partial_at = time.time()
                            sess.last_partial_end_s = p["end"]
                            asyncio.run_coroutine_threadsafe(
                                send({"type": "partial", **sent}), loop)
                elif t == "force_flush" and sess:
                    # 前端超时兜底：用户停顿了但 VAD 因短促停顿迟迟不报闭合，
                    # 直接冲掉驻留段当定稿句（给用户「停顿就断句」的体验）。
                    for seg in sess.drain():
                        _emit(seg)
                    p = sess.vadstream.flush_partial()
                    if p and p["end"] - p["start"] > 0.3:
                        with State.lock:
                            sent = sess.recognize(p["start"], p["end"])
                        if sent:
                            sess.sentences.append(sent)
                            asyncio.run_coroutine_threadsafe(
                                send({"type": "sentence", **sent}), loop)
                    sess.vadstream.in_progress = None
                    sess.last_partial_at = 0.0
                    sess.last_partial_end_s = 0.0
                elif t == "stop" and sess:
                    with State.lock:
                        for seg in sess.drain():
                            _emit(seg)
                        for seg in sess.finish_decoder():
                            _emit(seg)
                        for seg in sess.vadstream.finish():
                            _emit(seg)
                    _finish()
                    break
            except Exception as e:
                log.exception("live worker error")
                asyncio.run_coroutine_threadsafe(
                    send({"type": "error", "message": str(e)[:200]}), loop)

    def _emit(seg):
        sent = sess.recognize(seg["start"], seg["end"])
        if sent:
            sess.sentences.append(sent)
            asyncio.run_coroutine_threadsafe(
                send({"type": "sentence", **sent}), loop)

    def _finish():
        duration = sess.wav.size / 16000.0 if sess.wav.size else 0.0
        project = getattr(sess, "project", None) or "未命名"
        base_name = _job_basename(project)
        _save_outputs(base_name, "live-recording", duration,
                      sess.sentences, sess.diarize, project)
        n_spk = len({s.get("speaker") for s in sess.sentences if s.get("speaker")})
        safe = _safe_name(project)
        asyncio.run_coroutine_threadsafe(send({
            "type": "final", "job_id": base_name, "project": safe,
            "duration_s": round(duration, 1),
            "n_sentences": len(sess.sentences),
            "n_speakers": n_spk if sess.diarize else 0,
            "downloads": {
                "txt": f"/api/download/{safe}/{base_name}.txt",
                "srt": f"/api/download/{safe}/{base_name}.srt",
                "json": f"/api/download/{safe}/{base_name}.json",
            }}), loop)

    threading.Thread(target=worker, daemon=True).start()
    try:
        while True:
            raw = await ws.receive_text()
            msg_q.put_nowait(json.loads(raw))
    except WebSocketDisconnect:
        pass
    finally:
        stop_flag.set()
        if sess is not None:
            try:
                sess.decoder.close()
            except Exception:
                pass


# ---------- 项目管理：列表 / 重命名 ----------

@app.get("/api/projects")
def list_projects():
    """扫描 outputs/<项目名>/ 返回各项目及产物，供前端项目栏展示。"""
    out = []
    for pdir in sorted(OUT_DIR.iterdir() if OUT_DIR.exists() else []):
        if not pdir.is_dir():
            continue
        txts = sorted(pdir.glob("*.txt"))
        total = sum(t.stat().st_size for t in pdir.glob("*"))
        out.append({
            "name": pdir.name,
            "n_files": len(txts),
            "updated": max((t.stat().st_mtime for t in pdir.glob("*")), default=0),
            "bytes": total,
        })
    out.sort(key=lambda x: -x["updated"])
    return {"projects": out}


@app.post("/api/projects/rename")
async def rename_project(payload: dict):
    """重命名项目 = 目录改名。重名自动加 (2)(3) 后缀，绝不覆盖。"""
    old = _safe_name(payload.get("old", ""))
    new = _safe_name(payload.get("new", ""))
    src = OUT_DIR / old
    if not src.exists() or not src.is_dir():
        raise HTTPException(404, "项目不存在")
    dst = OUT_DIR / new
    n = 2
    while dst.exists():
        dst = OUT_DIR / f"{new}({n})"
        n += 1
    src.rename(dst)
    return {"ok": True, "name": dst.name}


# ---------- 前端：静态挂载（含 SPA 入口） ----------

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
