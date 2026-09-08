---
name: minimax-av
description: MiniMax 全模态理解 CLI，双子命令。transcribe：音频转文本（asr-1.0，8 种格式 ≤50MB/≤500s，支持 SRT/VTT 字幕与说话人分离时间戳）；understand：视觉理解（MiniMax-M3 原生，视频 mp4/mov 等 + 图片 png/jpg/webp/gif，≤100MB 可混合多文件，问答/摘要/JSON 输出）。模型、端点、API Key 全部走 config.json 可换。用于录音转写、字幕生产、视频分析、图片理解、会议纪要。
---

# minimax-av — MiniMax 全模态理解（音频转写 + 视觉理解）

## 场景

- **transcribe**：录音/语音备忘录/访谈转文字（多格式、≤500 秒、可出 SRT/VTT 字幕与说话人分离时间戳）
- **understand**：视频内容问答/摘要（M3 原生视频理解）+ **图片理解/对比/文字提取**（可混合多文件）

## 触发条件

用户给出音频文件要求转写，或给出视频文件要求理解/描述/分析/问答时。MiniMax 生态（Token Plan key）的音视频需求。

## 输入

| 子命令 | 文件 | 限制（官方/实测） |
|---|---|---|
| `transcribe` | wav/aiff/flac/m4a/mp3/aac/opus/ogg | ≤**50MB**（413）、≤**500 秒**（400，超长不截断直接拒）；裸 PCM 不支持 |
| `understand` | 视频 mp4/mov/avi/mkv/webm/flv/wmv/mpeg；**图片 png/jpg/webp/gif** | 单文件 ≤100MB（config 可调）；**图片 >2MB 建议先缩放**（脚本会提示）；时长未标注 |

参数：`--out 文件`（落盘）、`--show-usage`（stderr 打印延迟/用量）；transcribe 另有 **`--format`**（输出格式，见下）；understand 另有 `--prompt`、`--json`、`--max-tokens`。

### 时间戳/字幕（transcribe 的 --format）

| format | 输出 | 适合 |
|---|---|---|
| `json`（默认） | 纯文本 + duration | 快速转写 |
| `verbose_json` | **句级时间戳 + 说话人分离**（[S1] 0.02s-5.32s 文本，含 n_speakers） | 会议纪要、访谈 |
| `srt` / `vtt` | **标准字幕格式**（00:00:00,020 --> 00:00:05,320） | 视频配字幕 |

注意：srt/vtt/verbose_json 启用说话人分离与时间戳对齐，**不能与流式同用**（本 skill 非流式，无此限制）。

## 步骤

```bash
python3 scripts/minimax_av.py transcribe 录音.mp3
python3 scripts/minimax_av.py transcribe meeting.mp3 --format srt --out 字幕.srt
python3 scripts/minimax_av.py understand video.mp4 --prompt "总结内容" --out result.txt
python3 scripts/minimax_av.py understand cover.png --prompt "提取图中所有文字"
python3 scripts/minimax_av.py understand img1.png img2.jpg --prompt "对比这两张图"
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
| 429 | 限流（并发勿超 10；M3 官方 RPM：免费 20 / 充值 200）→ 退避重试 |
| "需要audio文件，实际是 video" | 视频先抽音轨：`ffmpeg -i in.mp4 -vn -b:a 64k out.mp3` |
| "需要video文件，实际是 audio" | 音频转写用 `transcribe` 子命令 |
| understand 空回答 | max_tokens 被 M3 推理吃满 → 加大 --max-tokens（默认 4096） |

## 数据回流（2026-09-08 实测）

- **正确的视频格式是 `video_url`**（`image_url` + video/mime 会被明确拒绝 2013"not supported"）；图片走 `image_url` + data URL（ec-xhs-cover-prompt-reverse 卡片 2026-07-31 实测的同款方案）
- **图片 >2MB 建议先缩放**（卡片实测经验，脚本会 stderr 提示）
- **M3 的推理藏在 content 的 `<think>` 标签里**（不是 reasoning_content 字段）——脚本已内置剥离；reasoning_content 兜底逻辑仍保留
- **wav 识别质量优于 mp3**：同一段音频 mp3 转出"质谱"（错）、wav 转出"智谱"（对）；但同一文件多次请求结果也有波动（ASR 非确定性）——重要场景建议 wav + 人工抽查
- MiniMax ASR **无热词参数**（智谱 GLM-ASR 有 hotwords）——专有名词场景识别差异靠 wav 格式补偿
- 响应带 `duration`；srt/vtt/verbose_json 启用时间戳对齐与说话人分离（**不能与 stream=true 同用**，本 skill 非流式无此限制）
- config 换 vision_model 后其他模型调用不报错但"看不到"视频（视频理解是 M3 原生能力）——换模型需理解能力差异
- base_url 是中国站 `api.minimaxi.com`；国际站为 `api.minimax.io`（config 可换）

## 与 glm-asr（智谱）选型对照

| 维度 | glm-asr | minimax-av transcribe |
|---|---|---|
| 时长 | ≤30s | **≤500s** |
| 格式 | wav/mp3 | 8 种（wav/aiff/flac/m4a/mp3/aac/opus/ogg） |
| 时间戳/字幕 | ❌ 无 | **✅ srt/vtt/verbose_json + 说话人分离** |
| 热词 | ✅ hotwords | ❌（wav 补偿） |
| 短语音+专有名词 | 首选 | 可用 |
| 长音频/字幕/会议纪要 | 不适用 | **首选** |
| 图片理解 | glm-vision（GLM 视觉） | ✅ M3 也能看（可混合视频） |

## 版本

v1.2 · 2026-09-08 · understand 泛化为视觉理解：图片识别（png/jpg/webp/gif）+ 多文件混合输入 + >2MB 缩放提示；修 WEBP 误判 AVI
v1.1 · 2026-09-08 · 时间戳/字幕支持（--format srt/vtt/verbose_json+说话人分离）+ 官方规格修正（50MB/500s/8 格式）
v1.0 · 2026-09-08 · 项项（冒烟先行→开发→11 项功能测试→安装）
