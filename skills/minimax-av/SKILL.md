---
name: minimax-av
description: MiniMax 音视频理解 CLI，双子命令。transcribe：音频转文本（asr-1.0，支持 mp3/wav/m4a/aac/flac 等多格式）；understand：视频内容理解（MiniMax-M3 原生视频理解，mp4/mov/avi/mkv 等 ≤100MB，问答/摘要/JSON 结构化输出）。模型、端点、API Key 全部走 config.json 可换。用于录音转写、视频内容分析、视频问答、字幕文本提取。
---

# minimax-av — MiniMax 音视频理解

## 场景

- **transcribe**：录音/语音备忘录/访谈转文字（多格式、无 30 秒硬限制）
- **understand**：视频内容问答/摘要/画面描述/字幕文字提取（M3 原生视频理解）

## 触发条件

用户给出音频文件要求转写，或给出视频文件要求理解/描述/分析/问答时。MiniMax 生态（Token Plan key）的音视频需求。

## 输入

| 子命令 | 文件 | 限制 |
|---|---|---|
| `transcribe` | mp3/wav/m4a/aac/flac/pcm/amr/opus/ogg/webm | 官方未标注时长上限（实测 5s 正常）；格式以 magic bytes 校验 |
| `understand` | mp4/mov/avi/mkv/webm/flv/wmv/mpeg | 默认 ≤100MB（config 的 max_video_bytes 可调）；时长未标注 |

参数：`--out 文件`（落盘）、`--show-usage`（stderr 打印延迟/用量）、understand 另有 `--prompt`（默认"详细描述这段视频的内容"）、`--json`（结构化输出）、`--max-tokens`。

## 步骤

```bash
python3 scripts/minimax_av.py transcribe 录音.mp3
python3 scripts/minimax_av.py understand video.mp4 --prompt "总结内容" --out result.txt
```

## 判断标准

- understand 输出为空 → think 剥离后无正文 → 增大 --max-tokens（M3 推理占额）
- transcribe 转录为空 → 检查音频是否有有效语音

## 输出

stdout：转录文本 / 视频分析文本（已剥离 M3 的 `<think>` 推理段）。`--out` 同时落盘。错误写 stderr，退出码非 0。

## 异常处理

| 症状 | 处理 |
|---|---|
| 401 | key 无效 → 检查 config.json 或环境变量 MINIMAX_API_KEY |
| 429 | 限流 → 稍后重试 |
| "需要audio文件，实际是 video" | 视频先抽音轨：`ffmpeg -i in.mp4 -vn -b:a 64k out.mp3` |
| "需要video文件，实际是 audio" | 音频转写用 `transcribe` 子命令 |
| understand 空回答 | max_tokens 被 M3 推理吃满 → 加大 --max-tokens（默认 4096） |

## 数据回流（2026-09-08 实测）

- **正确的视频格式是 `video_url`**（`image_url` + video/mime 会被明确拒绝 2013"not supported"）
- **M3 的推理藏在 content 的 `<think>` 标签里**（不是 reasoning_content 字段）——脚本已内置剥离；reasoning_content 兜底逻辑仍保留
- **wav 识别质量优于 mp3**：同一段音频 mp3 转出"质谱"（错）、wav 转出"智谱"（对）——重要音频建议 wav
- MiniMax ASR **无热词参数**（智谱 GLM-ASR 有 hotwords）——专有名词场景识别差异靠 wav 格式补偿
- 响应带 `duration` 字段（音频时长），trace_id 可用于问题追踪
- config 换 vision_model 后其他模型调用不报错但"看不到"视频（视频理解是 M3 原生能力）——换模型需理解能力差异
- base_url 是中国站 `api.minimaxi.com`；国际站为 `api.minimax.io`（config 可换）

## 版本

v1.0 · 2026-09-08 · 项项（冒烟先行→开发→11 项功能测试→安装）
