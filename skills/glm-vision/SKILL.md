---
name: glm-vision
description: 智谱 GLM-5.3-flash 视觉理解 CLI。输入图片（本地路径 / URL / 多图）+ 提问，输出文字或 JSON 分析。模型、端点、API Key 全部走 config.json 可换。用于截图理解、图表解读、图片问答、OCR 式提取。
---

# glm-vision 视觉理解

## 场景

- 截图/界面理解（UI 描述、元素识别、转代码前置分析）
- 图表/数据图解读
- 图片内容问答、信息提取（--json 结构化输出）
- 多图对比（≤5 张）

## 触发条件

用户给出图片（路径或 URL）并要求理解、描述、分析或提取信息时。

## 输入

- 图片：本地路径（自动转 Base64）或 URL（智谱服务端拉取）；jpg/png/webp/gif，单张 ≤10MB
- **视频**：本地文件（mp4/mov/avi/mkv/webm，≤50MB，自动转 Base64）或 URL 直传
- 提问：`--prompt`（默认"详细描述这张图片的内容"）
- `--json`：要求模型只输出合法 JSON
- `--max-tokens N`：覆盖 config（reasoning 也占此预算，复杂问题适当调大）
- `--download`：图片 URL 强制本地下载转 Base64（智谱服务端拉取国外源失败时用）

## 步骤

1. 确认图片路径/URL 有效
2. `python3 scripts/glm_vision.py <图片...> [--prompt "..."] [--json]`
3. stdout 取结果；stderr 看诊断（--show-usage 可打印 token 用量与延迟）

## 判断标准

- 输出为空 → stderr 会有明确错误（401 key / 429 限流 / 空回答提示加大 max_tokens）
- 多图 >5 张会提示质量风险

## 输出

stdout：模型回答文本（或 JSON 字符串）。错误写 stderr 且退出码非 0。

## 异常处理

| 症状 | 处理 |
|---|---|
| 401 | key 无效 → 检查 config.json 或环境变量 GLM_VISION_API_KEY |
| 429 | 限流（实测上限约 5 QPS）→ 间隔 1-2s 重试 |
| 1210 图片解析错误 | 图片文件损坏或非图片（先 magic bytes 验证）；或 URL 是国外源智谱拉不动 → 加 --download |
| URL 图报"type 参数非法" | 智谱服务端拉取该 URL 失败的误导性报错（多为国外源）→ 加 --download 本地下载 |
| 空回答 | max_tokens 被 reasoning 吃满 → 加大 max_tokens |

## 实测边界（2026-09-02）

- URL 直传依赖**智谱服务端能访问目标 URL**：国内源（bigmodel.cn CDN 等）稳定通过；国外源（httpbin.org/wikimedia）拉取失败（报 1210 或误导性的"type 参数非法"）——此时加 `--download` 自动绕过
- 视频：`video_url` 块，Base64 Data URL 和 URL 直传均可用（Base64 实测通过）

## 数据回流

2026-09-02 实测：`content` 多为 null，正文在 `reasoning_content`（thinking 默认 enabled）——脚本已内置兼容（content 非空时优先）。若智谱未来修复，无需改代码。

## 版本

v1.2 · 2026-09-02 · 视频支持（video_url）+ URL 策略修正（国外源自动降级）
v1.0/v1.1 · 2026-09-02 · 项项（skill-creator-exflower 流程）
