---
name: glm-asr
description: 智谱 GLM-ASR-2512 语音转文本 CLI。输入音频文件（wav/mp3，≤25MB，≤30秒），输出转录文本，支持热词表（专有名词/项目代号提升识别率）与上下文提示。模型、端点、API Key 全部走 config.json 可换。用于录音转写、会议纪要、语音输入、字幕文本提取。
---

# glm-asr — 语音转文本（GLM-ASR-2512）

## 场景

- 录音/语音备忘录转文字
- 会议片段、访谈片段的快速转写
- 语音输入（说一段话 → 文本给下游 Agent 处理）
- 带专有名词的音频（--hotwords 提升识别率）

## 触发条件

用户给出音频文件并要求转文字/转录/提取内容时。

## 输入（硬限制，超了会被 API 直接拒绝）

- **格式**：仅 wav / mp3（其他格式先用 ffmpeg 转：`ffmpeg -i in.xxx out.mp3`）
- **单文件**：≤25MB 且 ≤30 秒
- **并发**：勿超过 **10**（20 并发实测触发 429/1302；高峰期 14:00-18:00 更严）
- **视频（mp4/mov/m4a）不收**：先抽音轨 `ffmpeg -i in.mp4 -vn -b:a 64k out.mp3`（伪装后缀也会被服务端识破）
- `--hotwords "词1,词2"`：热词表（≤100 个），专有名词识别更准（实测：给"智谱"可把"质朴"修回"智谱"）
- `--prompt "上下文"`：长文本场景的前文提示
- `--out 文件`：保存到文件

## 步骤

```bash
python3 scripts/glm_asr.py 录音.mp3
python3 scripts/glm_asr.py meeting.mp3 --hotwords "智谱,AutoGLM" --out transcript.txt
```

视频先抽音轨，超 30 秒的长音频先切分（ffmpeg）：

```bash
# 视频抽音轨（mp4/mov/m4a 都不收，必须先转）
ffmpeg -i video.mp4 -vn -b:a 64k audio.mp3

# 超长音频切分（每段 28 秒，留 2 秒余量）
ffmpeg -i audio.mp3 -f segment -segment_time 28 -c copy part_%03d.mp3
python3 scripts/glm_asr.py part_001.mp3 --prompt "（上一段的转录文本作为上下文）"
```

## 判断标准

- 输出空文本 → stderr 有明确错误（401 key / 429 限流 / 格式问题）
- 专有名词错 → 加 --hotwords 重试

## 输出

stdout：转录文本。`--out` 时同时落盘。错误写 stderr，退出码非 0。

## 异常处理

| 症状 | 处理 |
|---|---|
| 401 | key 无效 → 检查 config.json 或环境变量 GLM_ASR_API_KEY |
| 429（code 1302） | 并发/频率超限（实测安全水位 ≤10 并发）→ 退避 1-2s 重试；高峰期 14:00-18:00 更严 |
| 不是 wav/mp3 | 用 ffmpeg 转：`ffmpeg -i in.aiff out.mp3` |
| 超 25MB / 超 30 秒 | 切分（命令见上）或压缩：`ffmpeg -i in.wav -b:a 64k out.mp3` |

## 数据回流（2026-09-08 实测）

- **端点**：coding plan（`/api/coding/paas/v4/audio/transcriptions`）与普通端点（`/api/paas/v4/...`）**均可用**（同 key），config 默认前者
- 响应 `text` 直接在顶层（无 reasoning 坑）
- 中文 TTS 测试 24 字逐字准确；专有名词（GLM ASR→GLM ATP）加 hotwords 后修正
- 端点/模型/key 变化只改 config.json，脚本零改动

## 版本

v1.0 · 2026-09-08 · 项项（skill-creator-exflower 流程：冒烟先行→开发→10 项功能测试→安装）
