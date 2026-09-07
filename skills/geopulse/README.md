# GeoPulse 📡 自托管 AI 品牌可见性监测台

> 你的品牌在 ChatGPT/DeepSeek/Kimi 们的回答里被提及了吗？——一条命令，自己监测。

## 这是什么

GEO（生成式引擎优化）监测工具：维护一组"用户会怎么问 AI"的 prompt，定期向 LLM 提问，解析品牌/竞品在回答中的提及，产出**可见率 / 声量份额 / 趋势 / 竞品矩阵**。

对标 Profound（$250/mo）、Scrunch（$100/mo）、Otterly（$29/mo）——全部 SaaS 订阅制。**GeoPulse 自托管**：数据不出你的机器，客户环境拷贝即用，零订阅费。

## 快速上手（60 秒）

```bash
# 依赖：Python 3.9+（无 fastapi/uvicorn 则 pip3 install --user -r requirements.txt）
python3 scripts/geopulse_ctl.py start
# 浏览器打开 http://127.0.0.1:8700
```

开箱即 demo 模式（确定性引擎，零成本跑通全链路）：点「▶ 立即监测」→ 仪表盘出数。
你的数据在 `~/.geopulse/`（geopulse.db + config.json），升级/重装 skill 不丢。

## 接入生产（真实 LLM）

「品牌与引擎」页配置，OpenAI 兼容协议：

| 厂商 | Base URL | 模型示例 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | glm-4-flash |
| 通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen-plus |
| Kimi | `https://api.moonshot.cn/v1` | moonshot-v1-8k |
| OpenAI | `https://api.openai.com/v1` | gpt-4o-mini |

Key 仅存本机 `~/.geopulse/config.json`（0600 权限），API 永不回显明文。
CLI 一条命令接入：`python3 scripts/geopulse_ctl.py engine set --kind openai_compat --name deepseek --base-url https://api.deepseek.com/v1 --model deepseek-chat --api-key sk-xxx`

## 使用流程

1. **品牌页**：添加你的品牌（含别名表，如英文名/缩写/旧名）+ 竞品
2. **Prompt 库**：录入真实用户会问的问题（品类调研/选型/对比/入门各来几条）
3. **仪表盘**：点「立即监测」→ 看可见率/SoV/趋势/最新回答
4. 定期跑（建议每周），趋势线就是你的 GEO 成效曲线

## 指标定义

| 指标 | 定义 |
|---|---|
| AI 可见率 | 提及该品牌的回答数 ÷ 总回答数（该周期内） |
| 声量份额 SoV | 该品牌提及次数 ÷ 全部监测品牌提及总次数 |
| 趋势 | 按天的可见率曲线 |

## 目录结构

```
geopulse/
├── SKILL.md                   # Agent 使用说明
├── requirements.txt           # 仅 fastapi + uvicorn
├── scripts/
│   └── geopulse_ctl.py        # 管理 CLI（start/stop/engine/brands/prompts/run/report）
├── backend/
│   ├── run.py                 # 启动器（首次建库+种子）
│   └── app/
│       ├── api/routes.py      # REST API
│       ├── engine/core.py     # 监测执行+解析+指标
│       └── providers/llm.py   # 可插拔引擎（demo/openai_compat）
├── frontend/                  # 零构建单页（vanilla JS + 本地ECharts）
├── tests/test_integration.py  # 21项集成测试（自管服务器生命周期）
└── docs/                      # 萃取文档+设计文档
```

## 测试

```bash
python3 tests/test_integration.py   # 21项：种子/CRUD/监测端到端/金标准/异常路径/key安全
```

金标准示例：demo 引擎下主品牌可见率必须=100%、SoV=50%（确定性引擎的可断言性）。

## 常见失败与排查

| 症状 | 原因 | 处理 |
|---|---|---|
| 端口 8700 被占 | 残留进程 | `lsof -ti tcp:8700 \| xargs kill` |
| run 全失败 error=HTTP 401 | key 无效 | 品牌页检查引擎配置 |
| run 失败 error=network | 端点不通 | 检查 base_url / 网络（部分厂商需代理） |
| 仪表盘空 | 还没跑过监测 | 点「立即监测」 |
| 可见率虚高 | 还在 demo 模式 | 引擎页切 openai_compat 配真实 key |

## 边界（v1 不做）

- 多用户/权限（单机自用定位）
- 邮件/Slack 订阅推送（API 可编程触发，定时交给 cron：`curl -X POST :8700/api/runs -d '{"scope":"active"}'`）
- 情感分析（schema 已留位，v2 做 LLM 二次判定）
- 传统 SEO 基线

## 技术说明

- 提及解析为确定性别名匹配（可解释可审计——GEO 咨询交付场景需要"为什么判命中"说得清）
- demo 引擎：同 prompt 恒同回答（哈希选模板），用于 CI/演示/无 key 环境
- 前端零构建：改完 HTML/JS 刷新即生效，无 npm 依赖，双平台浏览器直开

License: MIT
