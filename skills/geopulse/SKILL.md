---
name: geopulse
description: 自托管的 AI 品牌可见性监测系统（完整前后端，skill 内自带）。监测品牌在 AI 引擎（DeepSeek/智谱/通义/Kimi 等）回答中的可见率、声量份额、引用深度（提名/描述/推荐）、四维热力图（品牌词/场景词/对比词/选购词），并导出可发客户的 GEO 诊断报告。demo 引擎零 key 开箱即用，填任意 OpenAI 兼容端点的 key 即接入生产。
---

# geopulse — 自托管 AI 品牌可见性监测系统

## 场景

- 用户问"我的品牌在 AI（ChatGPT/DeepSeek）里被提及吗 / AI 可见性怎么测"
- 内容营销/GEO 工作流：跑一轮品牌监测、看可见率趋势、导出诊断报告给客户
- Agent 需要品牌在 AI 回答中的提及数据时

## 触发条件

出现"GEO / AI 可见性 / 品牌监测 / AI 提及 / 声量份额 / 诊断报告"等意图，或用户要求操作 GeoPulse 系统。

## 前置

本 skill **自包含完整 GeoPulse 系统**（backend + frontend + docs + tests），无外部依赖路径。
- 依赖：Python 3.9+ 与 fastapi/uvicorn（`pip3 install --user fastapi 'uvicorn[standard]'`；start 会自动检测并提示）
- 数据目录：`~/.geopulse/`（geopulse.db + config.json，与应用分离，升级 skill 不丢数据）
- 开箱即 demo 引擎（零 key 跑通全链路）；接入生产：`engine set` 填你的 key（支持 DeepSeek/智谱/通义/Kimi/OpenAI 等一切 OpenAI 兼容端点）

## 步骤（标准工作流——新用户 60 秒跑通）

```bash
CTL=python3 scripts/geopulse_ctl.py
$CTL start                       # 0. 首次自动建库+种子（demo 引擎，零 key）
$CTL brands add 你的品牌 --aliases "英文名,缩写" --primary   # 1. 换成你的品牌
$CTL brands remove GeoPulse      #    （删掉种子演示品牌）
$CTL prompts list                # 2. 换成你的客户会问的问题（四维标注）
$CTL run                         # 3. 触发监测（demo 引擎立即出数）
$CTL insights --days 7           # 4. 看指标
$CTL report --out ~/报告.md      # 5. 导出诊断报告（Markdown，可直接发客户）
```

### 接入生产（真实 LLM）

```bash
$CTL engine set --kind openai_compat --name deepseek \
     --base-url https://api.deepseek.com/v1 --model deepseek-chat --api-key sk-xxx
$CTL stop && $CTL start
$CTL run                # 现在是真实 AI 回答的真实监测
```

支持：DeepSeek / 智谱 / 通义 / Kimi / OpenAI 等一切 OpenAI 兼容端点（base_url/model 随填）。

## 判断标准

- run 后 done=0 且 failed>0 → 看 `run` 输出的失败详情（常见：key 失效 401 / 国外引擎网络 / prompt 全停用）
- insights 可见率 0% 且样本 0 → 最近没跑过监测，先 run
- 换了监测品牌后数字诡异 → 旧 run 的历史数据还在（demo 引擎数据已自动排除；要干净基线可换 prompt 库后跑新 run）

## 输出

- status/insights：人读概览
- report：引引六段格式 Markdown（搜索概览/四维热力图/引用深度/竞品对标/机会标注/一句话诊断）
- 所有错误写 stderr，退出码非 0

## 异常处理

| 症状 | 处理 |
|---|---|
| 服务不可达 | `geopulse_ctl.py start` |
| 缺依赖报错 | `pip3 install --user -r requirements.txt`（仅 fastapi/uvicorn） |
| 端口 8700 被占 | start 自动清同端口残留进程；自定义端口：`GEOPULSE_PORT=8800 start` |
| run 全失败 | `engine show` 检查引擎配置（key/模型/base_url），`engine remove <名>` 删坏引擎 |
| 401/429 | 引擎侧 key 失效或限流 → 等 1-2 分钟或换引擎 |

## 边界

- 单机单实例（端口 8700）；多用户/权限未做
- 情感分析/定时调度未做（GeoPulse v1.3 路线图：基线追踪/引用来源解析/未识别品牌发现）

## 版本

v1.2 · 2026-09-07 · 分发审查版：跨平台（Win/macOS/Linux）+ engine set 校验 + 测试套件随包
v1.1 · 2026-09-07 · 自包含完整系统 + 数据外置 ~/.geopulse + engine 子命令
v1.0 · 2026-09-07 · 首发（9 个子命令真实测试通过）
