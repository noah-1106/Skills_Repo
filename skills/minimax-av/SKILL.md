---
name: minimax-av
description: MiniMax 全模态理解 CLI，双子命令。transcribe：音频转文本（asr-1.0，8 种格式 ≤50MB/≤500s，支持 SRT/VTT 字幕与说话人分离时间戳）；understand：视觉理解（MiniMax-M3 原生，视频 mp4/mov 等 + 图片 png/jpg/webp/gif，≤100MB 可混合多文件，问答/摘要/JSON 输出）。模型、端点、API Key 全部走 config.json 可换。用于录音转写、字幕生产、视频分析、图片理解、会议纪要。
---

# minimax-av — MiniMax 全模态理解（音频转写 + 视觉理解）

## 场景

- **transcribe**：录音/语音备忘录/访谈转文字（多格式、≤500 秒、可出 SRT/VTT 字幕与说话人分离时间戳）
- **understand**：视频内容问答/摘要（M3 原生视频理解）+ 图片理解/对比/文字提取（可混合多文件）

## 触发条件

用户给出音频文件要求转写/出字幕，或给出视频/图片文件要求理解、描述、分析、问答时。

## 输入（硬限制）

| 子命令 | 文件 | 限制 |
|---|---|---|
| `transcribe` | wav/aiff/flac/m4a/mp3/aac/opus/ogg | ≤**50MB**（413）、≤**500 秒**（400，超长不截断直接拒）；裸 PCM 不支持 |
| `understand` | 视频 mp4/mov/avi/mkv/webm/flv/wmv/mpeg；**图片 png/jpg/webp/gif** | 单文件 ≤100MB（config 可调）；**图片 >2MB 建议先缩放**（脚本会提示）；时长未标注 |

参数：`--out 文件`（落盘）、`--show-usage`（stderr 打印延迟/用量）；transcribe 另有 **`--format`**；understand 另有 `--prompt`、`--json`、`--max-tokens`。

### 时间戳/字幕（transcribe 的 --format）

| format | 输出 | 适合 |
|---|---|---|
| `json`（默认） | 纯文本 + duration | 快速转写 |
| `verbose_json` | **句级时间戳 + 说话人分离**（[S1] 0.02s-5.32s 文本，含 n_speakers） | 会议纪要、访谈 |
| `srt` / `vtt` | **标准字幕格式**（00:00:00,020 --> 00:00:05,320） | 视频配字幕 |

注意：这三种格式启用时间戳对齐与说话人分离，不能与流式同用（本 skill 非流式，无此限制）。

## 步骤

```bash
python3 scripts/minimax_av.py transcribe 录音.mp3
python3 scripts/minimax_av.py transcribe meeting.mp3 --format srt --out 字幕.srt
python3 scripts/minimax_av.py transcribe interview.wav --format verbose_json   # 说话人+时间戳
python3 scripts/minimax_av.py understand video.mp4 --prompt "总结内容" --out result.txt
python3 scripts/minimax_av.py understand cover.png --prompt "提取图中所有文字"
python3 scripts/minimax_av.py understand img1.png img2.jpg video.mp4 --prompt "对比分析"
```

超 500 秒的长音频先切分（ffmpeg，每段留余量）：

```bash
ffmpeg -i long.mp3 -f segment -segment_time 480 -c copy part_%03d.mp3
```

## 判断标准

- transcribe 空输出 → 检查音频是否有有效语音
- understand 空回答 → think 剥离后无正文 → 增大 --max-tokens（M3 推理占额）
- 专有名词识别错 → 换 wav 无损格式重试（有损压缩会降低识别质量），或转录后人工校对

## 输出

stdout：转录文本 / 字幕 / 视觉分析文本（已剥离 `<think>` 推理段）。`--out` 同时落盘。错误写 stderr，退出码非 0。

## 异常处理

| 症状 | 处理 |
|---|---|
| 401 | key 无效 → 检查 config.json 或环境变量 MINIMAX_API_KEY |
| 429 | 限流（并发勿超 10；M3 官方 RPM：免费 20 / 充值 200）→ 退避重试 |
| 400 超长 | 音频超 500 秒 → 切分（命令见上） |
| 413 超大 | 超 50MB → `ffmpeg -i in -b:a 64k out.mp3` 压缩 |
| "需要media文件，实际是 audio" | 音频转写用 `transcribe` 子命令 |
| understand 空回答 | max_tokens 被 M3 推理吃满 → 加大 --max-tokens |

## 数据回流（2026-09-08 实测）

- **正确的视频格式是 `video_url`**（`image_url` + video/mime 会被明确拒绝 2013）；图片走 `image_url` + data URL，多文件可混合
- **M3 的推理藏在 content 的 `<think>` 标签里**（不是 reasoning_content 字段）——脚本已内置剥离
- **wav 识别质量优于有损压缩格式**；同一文件多次请求结果存在波动（ASR 非确定性）——重要场景建议 wav + 人工抽查
- MiniMax ASR **无热词参数**——专有名词识别建议 wav 无损格式补偿，或转录后人工校对
- 响应自带 `duration`；图片 >2MB 建议先缩放（脚本会 stderr 提示）
- config 换 vision_model 后其他模型调用不报错但"看不到"视频（视频理解是 M3 原生能力）
- base_url 中国站 `api.minimaxi.com`；国际站 `api.minimax.io`（config 可换）

## 版本

v1.2.1 · 2026-09-08 · 清理内部引用（纯对外文档）+ 根 README 同步 v1.2
v1.2 · 2026-09-08 · understand 泛化：图片识别（png/jpg/webp/gif）+ 多文件混合输入 + >2MB 缩放提示；修 WEBP 误判 AVI
v1.1 · 2026-09-08 · 时间戳/字幕支持（--format srt/vtt/verbose_json+说话人分离）+ 官方规格修正（50MB/500s/8 格式）
v1.0 · 2026-09-08 · 首发（冒烟先行→开发→11 项功能测试→安装）
