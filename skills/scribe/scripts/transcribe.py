#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SenseVoice-Small 本地转写工具 — VAD 切片 + 词级时间戳断句。

架构（两模型常驻，各司其职）:
  FSMN-VAD   → 按静音切出语音段（得到全局偏移 offset）
  SenseVoice → 每段识别 + output_timestamp=True 输出词级时间戳
  合并层     → 按标点（。！？；，）把词聚合成句子，句时间戳 = 段偏移 + 词时间戳

用法:
  python3 transcribe.py <音频文件>                 # 带时间戳文本
  python3 transcribe.py <音频文件> --srt           # SRT 字幕
  python3 transcribe.py <音频文件> --json          # JSON（含起止秒）
  python3 transcribe.py <音频文件> -o out.txt      # 写入文件
  python3 transcribe.py <音频文件> --max-seg 20    # VAD 段超过 N 秒时按词级时间戳二次切分
  python3 transcribe.py <音频文件> --diarize       # 说话人标记（CAM++ 按需加载，输出加「说话人 N:」前缀）
"""
import sys, time, json, re
from pathlib import Path

BASE = Path(__file__).parent
if BASE.name == "scripts":
    BASE = BASE.parent  # Skill 自包含: 项目根 = scripts/ 上一级
ASR_DIR = str(BASE / "models" / "SenseVoiceSmall")
VAD_DIR = str(BASE / "models" / "speech_fsmn_vad")

TAG_RE = re.compile(r"<\|[^|]*\|>")
# 断句标点：遇到这些就闭合当前句（保留标点本身在句尾）
SENT_END = set("。！？；!?;…")
# 段内二次切分时，长句超过该词数也在逗号处断（防止一口气 20 秒一句话）
CLAUSE_END = set("，,")
MAX_WORDS_PER_SENT = 30

def clean(t: str) -> str:
    return TAG_RE.sub("", t).strip()

def fmt_s(sec: float) -> str:
    sec = max(0, sec)
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def fmt_srt(sec: float) -> str:
    sec = max(0.0, sec)
    ms_total = int(round(sec * 1000))
    h, rem = divmod(ms_total, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def words_to_sentences(words, offset_s: float):
    """把 SenseVoice 的词级结果（词文本 + [起,止]ms，段内相对）聚合成带全局时间戳的句子。"""
    sentences, buf, wcount = [], [], 0
    for w, (wst, wen) in words:
        buf.append((w, wst, wen))
        wcount += 1
        last_char = w[-1] if w else ""
        hit_hard = last_char in SENT_END
        hit_soft = last_char in CLAUSE_END and wcount >= MAX_WORDS_PER_SENT
        if hit_hard or hit_soft:
            sentences.append(_flush(buf, offset_s))
            buf, wcount = [], 0
    if buf:
        sentences.append(_flush(buf, offset_s))
    return [s for s in sentences if s["text"]]

def _flush(buf, offset_s):
    text = "".join(w for w, _, _ in buf).strip()
    start = offset_s + buf[0][1] / 1000.0
    end = offset_s + buf[-1][2] / 1000.0
    return {"start": round(start, 2), "end": round(end, 2), "text": text}

def transcribe(asr, vad, audio_path: str, max_seg: float = 30.0):
    """返回句子列表 [{start, end, text}]，时间戳为全局秒。"""
    import soundfile as sf

    wav, sr = sf.read(audio_path)
    if wav.ndim > 1:  # 双声道混成单声道
        wav = wav.mean(axis=1)

    vad_segs = vad.generate(input=audio_path)[0]["value"]

    sentences = []
    for st_ms, en_ms in vad_segs:
        st_s, en_s = st_ms / 1000.0, en_ms / 1000.0
        clip = wav[int(st_s * sr):int(en_s * sr)]
        if len(clip) < sr * 0.3:  # 跳过 <0.3s 的碎片
            continue
        r = asr.generate(input=clip, cache={}, language="auto",
                         use_itn=True, batch_size_s=60,
                         output_timestamp=True)[0]
        words_raw = r.get("words") or []
        # words 与 timestamp 对齐；words 里可能带元标签，清洗后过滤空词
        ts = r.get("timestamp") or []
        words = []
        for w, t in zip(words_raw, ts):
            cw = clean(w)
            if cw:
                words.append((cw, t))
        if words:
            sentences.extend(words_to_sentences(words, st_s))
        else:
            # 兜底：没有词级时间戳时整段一句
            txt = clean(r.get("text", ""))
            if txt:
                sentences.append({"start": round(st_s, 2), "end": round(en_s, 2), "text": txt})
    sentences.sort(key=lambda s: s["start"])
    return sentences

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a.split("=")[0] for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        sys.exit(1)
    audio = args[0]
    out_path = args[args.index("-o") + 1] if "-o" in args else None

    t0 = time.time()
    from funasr import AutoModel
    asr = AutoModel(model=ASR_DIR, trust_remote_code=True, device="cpu", disable_update=True)
    vad = AutoModel(model=VAD_DIR, trust_remote_code=True, device="cpu", disable_update=True)
    t_load = time.time() - t0

    t1 = time.time()
    segs = transcribe(asr, vad, audio)
    if "--diarize" in flags:
        import soundfile as sf
        from diarize import label_speakers
        sv = AutoModel(model=str(BASE / "models" / "campplus_sv"),
                       trust_remote_code=True, device="cpu", disable_update=True)
        w, sr = sf.read(audio)
        if w.ndim > 1:
            w = w.mean(axis=1)
        label_speakers(segs, w, sr, sv)
    t_infer = time.time() - t1

    if "--json" in flags:
        out = json.dumps(segs, ensure_ascii=False, indent=2)
    elif "--srt" in flags:
        out = "\n".join(
            f"{i}\n{fmt_srt(s['start'])} --> {fmt_srt(s['end'])}\n{s['text']}\n"
            for i, s in enumerate(segs, 1))
    else:
        out = "\n".join(
            f"[{fmt_s(s['start'])}] " + (f"{s['speaker']}: " if s.get('speaker') else "") + s['text']
            for s in segs)

    if out_path:
        Path(out_path).write_text(out + "\n", encoding="utf-8")
        print(f"[已写入 {out_path}]", file=sys.stderr)
    else:
        print(out)

    total = segs[-1]["end"] if segs else 0
    n_spk = len({s.get("speaker") for s in segs if s.get("speaker")})
    spk_info = f" | {n_spk} 位说话人" if n_spk else ""
    print(f"[模型加载 {t_load:.1f}s | 推理 {t_infer:.1f}s | 音频 {total:.0f}s | "
          f"{len(segs)} 句{spk_info} | RTF {t_infer/max(total,1):.2f}]", file=sys.stderr)

if __name__ == "__main__":
    main()
