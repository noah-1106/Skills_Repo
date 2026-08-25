#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scribe 实时转录核心 —— 流式 VAD 状态机 + 在线说话人标记。

流程（服务器推模式，前后端走 WebSocket）：
  前端浏览器 MediaRecorder 每 0.5s 推一小块 webm/opus
    → 服务器把块按序写入「一个持久 ffmpeg 进程」的 stdin（连续流解码）
    → 解码出的 16k 单声道采样追加进滑动缓冲
    → 增量跑 FSMN-VAD（模型有内部流式状态，endpointer 思维）
    → VAD 报「一段说完」→ 立即送 SenseVoice 识别 → 广播句子
    → 勾选说话人时，CAM++ 对该段提声纹并在线聚类（复用 diarize.py）

关键设计（踩坑记录，全部经实测确认）：
  - 【v2 核心修复】MediaRecorder 用 timeslice 切片时，只有第一块含 EBML
    头，后续块是无头 Cluster 分片——单独喂 ffmpeg 必然报
    "Invalid data found when processing input"（1.0 版逐块起 ffmpeg 的
    死法）。但这些块拼起来是一条连续合法的 webm 流，所以改为每个会话
    常驻一个 ffmpeg 进程：块按序写 stdin，采样从 stdout 持续流出。
  - VAD 必须持久保存 cache/in_progress：每批新采样只跑一次 generate，
    模型自己跨调用记忆上文。每批重切会打断它的 FSMN 状态。
  - 批采样数若不是 chunk_stride(960) 的整数倍，缓存会被模型静默下移、
    段边界整体漂移。所以批 = 待处理缓冲向下取整到 960 的倍数。
  - FSMN-VAD 流式接口的 value 坐标系是「流全局毫秒」：实测块1输出
    [[210,-1]]（段起于全局 210ms），块37输出 [[-1,17890]]。段边界直接
    用 value 值，不要叠加任何 feed 偏移（1.0 版误加偏移导致区间越界、
    录音零结果）。
  - 停顿出字由服务器 worker 的空闲 tick 驱动（不依赖前端计时器，
    浏览器后台标签页会节流 setInterval）。tick 同时泵取 ffmpeg 已解码
    但还没进 VAD 的采样，避免 partial 滞后一个块。
  - 整段上传转写（transcribe.py）不受影响，两种模式并存。
"""
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
FFMPEG = BASE / "bin" / "ffmpeg"

SR = 16000
CHUNK_STRIDE = 960            # FSMN-VAD 内部 stride（60ms），批必须对齐
MAX_BATCH = SR * 5            # 单次最多喂 5s（speech 突增时限速，防抖动）
PARTIAL_MIN_GAP_S = 4.0       # 同一驻留段两次暂显的最小间隔
PARTIAL_MIN_NEW_S = 0.6       # 自上次暂显以来至少新增这么多音频才重识别


class StreamDecoder:
    """一个会话一个持久 ffmpeg 进程：webm/opus 连续流 → 16k f32le 采样。

    MediaRecorder 的 timeslice 块拼起来是连续 webm 流（仅首块有 EBML 头），
    所以绝不能逐块起进程解码，必须让 ffmpeg 进程跨块存活。块写 stdin，
    后台线程从 stdout 持续收 PCM 字节进缓冲，主线程按需取走。
    """

    def __init__(self):
        exe = str(FFMPEG) if FFMPEG.exists() else (shutil.which("ffmpeg") or "ffmpeg")
        self.p = subprocess.Popen(
            [exe, "-v", "error", "-i", "pipe:0",
             "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.err = bytearray()
        self.dead = False
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    def _pump_stdout(self):
        try:
            while True:
                chunk = self.p.stdout.read(65536)
                if not chunk:
                    break
                with self.lock:
                    self.buf += chunk
        except Exception:
            pass
        self.dead = True

    def _pump_stderr(self):
        try:
            while True:
                chunk = self.p.stderr.read(4096)
                if not chunk:
                    break
                self.err += chunk
        except Exception:
            pass

    def write(self, data: bytes):
        if self.p.poll() is not None:
            raise RuntimeError("ffmpeg 解码进程已退出: "
                               + bytes(self.err).decode(errors="ignore")[:160])
        try:
            self.p.stdin.write(data)
            self.p.stdin.flush()
        except BrokenPipeError:
            raise RuntimeError("ffmpeg 解码失败（管道断开）: "
                               + bytes(self.err).decode(errors="ignore")[:160])

    def read_samples(self) -> np.ndarray:
        """取走当前已解码的全部采样（按 float32 对齐）。"""
        with self.lock:
            n = len(self.buf) // 4 * 4
            if n == 0:
                return np.zeros(0, dtype=np.float32)
            out = bytes(self.buf[:n])
            del self.buf[:n]
        return np.frombuffer(out, dtype=np.float32)

    def close(self):
        """关闭输入，等 ffmpeg 冲完尾部采样后收割残余缓冲。"""
        try:
            self.p.stdin.close()
        except Exception:
            pass
        try:
            self.p.wait(timeout=10)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass
        # 给 stdout 泵线程一个节拍把最后字节搬进缓冲
        for _ in range(20):
            if self.dead:
                break
            time.sleep(0.05)


class VadStream:
    """FSMN-VAD 流式包装：维护 cache，逐批喂采样，吐出闭合段 + 驻留段。

    注意：模型输出的段边界是流全局毫秒（实测确认），这里只做单位换算，
    不做任何偏移叠加。
    """

    def __init__(self, vad_model):
        self.vad = vad_model
        self.cache = {}
        self.in_progress = None      # 当前未闭合段起点（全局 ms）
        self.offset_ms = 0           # 已消费采样总量（全局 ms），仅用于驻留段右端点
        self.pending = np.zeros(0, dtype=np.float32)  # 不足一批的余量

    def _run(self, chunk: np.ndarray, is_final: bool):
        try:
            res = self.vad.generate(
                input=chunk, cache=self.cache, is_final=is_final,
                chunk_size=int(os.environ.get("FUNASR_VAD_CHUNK", "60")),
                disable_pbar=True)
            return res[0]["value"] if res and res[0].get("value") else []
        except Exception:
            return []

    def feed(self, samples: np.ndarray):
        """喂一批解码后的采样，返回 [{start,end}] 闭合段（全局秒）。"""
        self.pending = np.concatenate([self.pending, samples]) \
            if self.pending.size else samples.copy()
        closed = []
        while self.pending.size >= CHUNK_STRIDE:
            n = min(MAX_BATCH, (self.pending.size // CHUNK_STRIDE) * CHUNK_STRIDE)
            chunk, self.pending = self.pending[:n], self.pending[n:]
            segs = self._run(chunk, False)
            self.offset_ms += int(round(n / SR * 1000))
            closed.extend(self._absorb(segs))
        return closed

    def _absorb(self, segs):
        """把 VAD 的段输出（流全局 ms）折算成秒，并维护驻留段状态。"""
        out = []
        for s in segs:
            st_ms, en_ms = s
            if en_ms == -1:                     # 新段开始，驻留（全局坐标）
                self.in_progress = st_ms
            elif st_ms == -1:                   # 段闭合（全局坐标）
                start_ms = self.in_progress if self.in_progress is not None else 0
                if en_ms > start_ms:
                    out.append({"start": start_ms / 1000.0,
                                "end": en_ms / 1000.0})
                self.in_progress = None
            else:                               # 一次性给出完整段（全局坐标）
                if en_ms > st_ms:
                    out.append({"start": st_ms / 1000.0,
                                "end": en_ms / 1000.0})
                self.in_progress = None
        return out

    def flush_partial(self):
        """把驻留段按「当前位置」暂闭合，供 partial 识别。"""
        if self.in_progress is None:
            return None
        return {"start": self.in_progress / 1000.0, "end": self.offset_ms / 1000.0}

    def finish(self):
        """录音结束：冲掉余量，返回剩余闭合段 + 驻留段。"""
        closed = []
        if self.pending.size:
            pad = (CHUNK_STRIDE - self.pending.size % CHUNK_STRIDE) % CHUNK_STRIDE
            chunk = np.concatenate([self.pending, np.zeros(pad, dtype=np.float32)])
            closed.extend(self._absorb(self._run(chunk, True)))
            self.offset_ms += int(round(self.pending.size / SR * 1000))
            self.pending = np.zeros(0, dtype=np.float32)
        else:
            closed.extend(self._absorb(self._run(np.zeros(CHUNK_STRIDE, dtype=np.float32), True)))
        if self.in_progress is not None:
            end_ms = max(self.offset_ms, self.in_progress)
            if end_ms > self.in_progress:
                closed.append({"start": self.in_progress / 1000.0,
                               "end": end_ms / 1000.0})
            self.in_progress = None
        return closed


class LiveSession:
    """一次录音会话：持久解码器 + 音频缓冲 + VAD 流 + ASR + 可选说话人。"""

    def __init__(self, asr, vad, diarize: bool, sv_loader):
        self.asr = asr
        self.vadstream = VadStream(vad)
        self.diarize = diarize
        self.sv = sv_loader() if diarize else None
        self.decoder = StreamDecoder()           # 每会话一个持久 ffmpeg
        self.wav = np.zeros(0, dtype=np.float32)   # 已解码全部采样
        self.sentences = []                        # 已定稿句子
        self.speakers = []                         # 在线说话人质心
        self.last_idx = None
        self.next_block = 0
        self.block_queue = {}                      # seq -> bytes（乱序重排）
        self.t_start = time.time()
        # partial 节流状态
        self.last_partial_at = 0.0
        self.last_partial_end_s = 0.0
        self.decoder_closed = False

    # ---- 音频入口 ----
    def push_block(self, seq: int, data: bytes):
        self.block_queue[seq] = data

    def _ingest(self, samples: np.ndarray):
        """采样进缓冲 + 喂 VAD，返回闭合段。"""
        if samples.size == 0:
            return []
        self.wav = np.concatenate([self.wav, samples]) if self.wav.size else samples
        return self.vadstream.feed(samples)

    def pump(self):
        """把 ffmpeg 已解码但还没进 VAD 的采样泵进来（不碰块队列）。

        服务器空闲 tick 也会调它——解码比块到达略滞后时，partial 不至于
        永远慢一个块。
        """
        return self._ingest(self.decoder.read_samples())

    def drain(self):
        """把按序到齐的块写入持久解码器，再泵采样进 VAD，返回新闭合段。"""
        while self.next_block in self.block_queue:
            data = self.block_queue.pop(self.next_block)
            self.next_block += 1
            self.decoder.write(data)
        return self.pump()

    def finish_decoder(self):
        """stop 时调用：关闭解码器，收割尾部采样，返回闭合段。"""
        if self.decoder_closed:
            return []
        self.decoder_closed = True
        self.decoder.close()
        return self._ingest(self.decoder.read_samples())

    def maybe_partial(self):
        """服务器计时器调用：驻留段满足节流条件才暂识别。

        条件：距上次暂显 >PARTIAL_MIN_GAP_S，且自上次暂显以来新增音频
        ≥PARTIAL_MIN_NEW_S——避免无音频时反复重识别同一段烧 CPU。
        """
        p = self.vadstream.flush_partial()
        if not p:
            return None
        now = time.time()
        if now - self.last_partial_at < PARTIAL_MIN_GAP_S:
            return None
        if p["end"] - self.last_partial_end_s < PARTIAL_MIN_NEW_S:
            return None
        sent = self.recognize(p["start"], p["end"], partial=True)
        if sent:
            self.last_partial_at = now
            self.last_partial_end_s = p["end"]
        return sent

    # ---- 识别 ----
    def _clip(self, st_s: float, en_s: float) -> np.ndarray:
        a = max(0, int(st_s * SR))
        b = min(int(en_s * SR), self.wav.size)
        return self.wav[a:b] if b > a else np.zeros(0, dtype=np.float32)

    def recognize(self, st_s: float, en_s: float, partial: bool = False):
        """识别 [st,en) 区间，返回句子 dict；空音频返回 None。

        partial=True 时跳过说话人聚类——驻留段会被反复暂识别，
        每次都提声纹会把同一人拆成多个质心。
        """
        clip = self._clip(st_s, en_s)
        if clip.size < SR * 0.3:
            return None
        r = self.asr.generate(input=clip, cache={}, language="auto",
                              use_itn=True, batch_size_s=60)[0]
        from transcribe import clean
        text = clean(r.get("text", ""))
        if not text:
            return None
        sent = {"start": round(st_s, 2), "end": round(en_s, 2), "text": text}
        if self.diarize and not partial:
            sent["speaker"] = self._label(st_s, en_s)
        return sent

    def _label(self, st_s: float, en_s: float) -> str:
        """在线说话人聚类（与 diarize.py 同策略，逐段调用版）。"""
        from diarize import THRESHOLD, EMA_ALPHA, MIN_SEG_S, _embedding
        if en_s - st_s < MIN_SEG_S and self.last_idx is not None:
            return "说话人 {}".format(self.last_idx + 1)
        clip = self._clip(st_s, en_s)
        if clip.size == 0:
            return "说话人 {}".format((self.last_idx or 0) + 1)
        emb = _embedding(self.sv, clip)
        best, best_sim = None, -1.0
        for i, (cent, _) in enumerate(self.speakers):
            sim = float(np.dot(emb, cent))
            if sim > best_sim:
                best, best_sim = i, sim
        if best is not None and best_sim >= THRESHOLD:
            cent, n = self.speakers[best]
            cent = cent * EMA_ALPHA + emb * (1 - EMA_ALPHA)
            cent /= (np.linalg.norm(cent) + 1e-9)
            self.speakers[best] = (cent, n + 1)
            self.last_idx = best
        else:
            self.speakers.append((emb.copy(), 1))
            self.last_idx = len(self.speakers) - 1
        return "说话人 {}".format(self.last_idx + 1)
