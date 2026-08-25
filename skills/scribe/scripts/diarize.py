#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""说话人分离（diarization）模块 —— CAM++ 声纹嵌入 + 余弦门限聚类。

架构：
  每个语音段 → 裁出对应波形 → CAM++ 提取 192 维声纹
             → 与已有说话人质心比余弦相似度
             → ≥ 门限(0.45) 归并，否则开新说话人（在线聚类）
             → 质心指数滑动平均（EMA 0.75）自适应漂移

设计说明（与 Noah 拍板）：
  - 用在线余弦聚类而非 sklearn Agglomerative——不依赖新库，且「边转边标」可流式
  - 门限 0.45 来自 spike 实测：同人≈1.0，不同人 0.03~0.30，安全裕度大
  - 单段 SV 提取 CPU 上 <0.15s，对 RTF 影响可忽略
  - 输入波形必须是 16kHz：CAM++ 前端写死 16k 采样率，喂 48k 波形会产生错乱嵌入
    （同人相似度掉到 0.05 的假阴性）。scribe 管线天然免疫——音频在进 VAD 前
    已由内置 ffmpeg 归一化到 16k。

接口：
  label_speakers(segments, wav, sr, sv_model)
    输入  [{{start, end, ...}}, ...]（全局秒）+ 整段 16k 波形 + 采样率 + CAM++ AutoModel
    输出  原列表就地加 "speaker": "说话人 1" 字段，按首次出现顺序编号
"""
import numpy as np

THRESHOLD = 0.45     # 同人判定门限（spike 实测：异人 <=0.30）
EMA_ALPHA = 0.75     # 质心滑动平均权重
MIN_SEG_S = 0.5      # 短于 0.5s 的碎片不提取声纹，继承上一位说话人


def _embedding(sv_model, clip: np.ndarray) -> np.ndarray:
    r = sv_model.generate(input=clip)
    emb = np.array(r[0]["spk_embedding"], dtype=np.float32).ravel()
    return emb / (np.linalg.norm(emb) + 1e-9)


def label_speakers(segments, wav, sr: int, sv_model, threshold: float = THRESHOLD):
    speakers = []  # [(质心, 命中次数)]
    last_idx = None

    for s in segments:
        st, en = s["start"], s["end"]
        if en - st < MIN_SEG_S:
            # 碎片句：声纹不可信，跟随上一位
            if last_idx is not None:
                s["speaker"] = "说话人 {}".format(last_idx + 1)
                continue
        clip = wav[int(st * sr):int(en * sr)]
        if len(clip) == 0:
            if last_idx is not None:
                s["speaker"] = "说话人 {}".format(last_idx + 1)
            continue
        emb = _embedding(sv_model, clip)

        best, best_sim = None, -1.0
        for i, (cent, _) in enumerate(speakers):
            sim = float(np.dot(emb, cent))
            if sim > best_sim:
                best, best_sim = i, sim

        if best is not None and best_sim >= threshold:
            cent, n = speakers[best]
            cent = cent * EMA_ALPHA + emb * (1 - EMA_ALPHA)
            cent /= (np.linalg.norm(cent) + 1e-9)
            speakers[best] = (cent, n + 1)
            last_idx = best
        else:
            speakers.append((emb.copy(), 1))
            last_idx = len(speakers) - 1
        s["speaker"] = "说话人 {}".format(last_idx + 1)

    return segments
