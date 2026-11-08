---
name: geopulse
description: 自托管的多客户 GEO 交付工作台。冻结问题与实体口径，执行可恢复的 Wave/Run 测量，复核不可变原始证据，完成同口径比较、机会与七步 Action、客户/内部报告审批，以及角色、调度、成本和备份管理。支持 Demo、OpenAI-compatible、Kimi/DeepSeek Search + Chat、人工 Consumer Web 与授权 DeepSeek/Kimi 网页采集。
---

# GeoPulse v2 — 多客户 GEO 交付工作台

## 何时使用

- 用户提到 GEO、AI 品牌可见性、声量份额、品牌提及、竞品推荐或客户诊断报告。
- 需要为客户建立可复核的测量基线、复测、证据审阅、行动和报告交付流程。
- 需要在本机自托管完整 FastAPI + SQLite + 原生前端系统。

GeoPulse 不承诺排名，不把 Provider API 结果冒充 Kimi App、ChatGPT 网页等消费者产品观察，也不从指标变化自动推断 GEO 策略因果。

## 安装与启动

要求 Python 3.11+；当前锁文件在 Python 3.14 验证。PDF 和浏览器验收需要 Chrome/Chromium。

```bash
cd skills/geopulse
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/python backend/run.py
```

打开 `http://127.0.0.1:8700`。首次启动创建演示项目、冻结问题集、Demo 引擎和管理员，并在终端显示一次性密码。登录后尽快更换：

```bash
.venv/bin/python scripts/geopulse_ctl.py set-admin-password admin@geopulse.local
```

默认数据位于 skill 内的 `backend/` 和 `outputs/`，这些路径已被 `.gitignore` 排除。正式使用或升级 skill 前，建议把数据放到独立持久目录：

```bash
export GEOPULSE_DB="$HOME/.geopulse/v2/geopulse.db"
export GEOPULSE_SECRETS="$HOME/.geopulse/v2/secrets.json"
export GEOPULSE_BACKUP_DIR="$HOME/.geopulse/v2/backups"
export GEOPULSE_EXPORT_DIR="$HOME/.geopulse/v2/exports"
export GEOPULSE_BROWSER_PROFILES="$HOME/.geopulse/v2/browser_profiles"
```

不要把数据库、secret store、浏览器 profile、旧 `backend/config.json`、客户原文或测试输出提交到仓库。

## 八条工作流

1. **项目总览**：当前阶段、待办、正式指标、告警和下一次复测。
2. **问题集**：草稿、候选 scaffold、JSON/CSV、去重、审核、冻结、复制和版本 diff。
3. **品牌实体**：实体卡、别名冲突、管理员消歧、不可变版本和竞品池。
4. **测量执行**：Wave 冻结协议，Run 执行/重试，调用与成本预估，持久队列和正式 Run 指定。
5. **证据复核**：原文与 observation、Judge 元数据、引用和追加式人工 revision。
6. **机会与行动**：管理员确认适用性、冻结权重评分、七步 Action、真实发布和复测。
7. **对比与报告**：协议与有效样本完整度、配对迁移、ECharts、不可变快照、三级审批、HTML/PDF。
8. **系统管理**：引擎、成员角色、单次/周期调度、告警确认与恢复、成本、手工工时、软/硬预算、原文保留、审计、备份、导出和删除。

逐项“界面 → API → 持久化 → 执行器 → 权限 → 测试”见 `docs/feature-matrix.md`。

## 真实引擎与费用

在“系统管理 → 引擎与口径”配置：

- **OpenAI-compatible memory**：普通 Chat Completions 记忆态测量。
- **Kimi Search + Chat**：先调用 `POST /v1/tools/search`，再单独调用 Chat；Search/Chat usage 分开记录。
- **DeepSeek Search + Chat**：使用官方 Search 协议，再单独调用 Chat；Search/Chat usage 分开记录。
- **人工 Consumer Web**：人工复制实际网页回答并上传截图、HTML 和页面引用。
- **DeepSeek Web / Kimi Web 授权浏览器**：通过独立 Driver、本机持久会话和可见浏览器发送冻结问题，采集正文、引用、截图与回答区域 HTML；用户本人登录和处理验证码。
- **Demo**：本地确定性数据，只用于演示和测试，不能与真实引擎混算。

Search 失败、无结果或协议异常不会静默降级 memory。真实健康检查和真实 Run 可能产生厂商费用，执行前必须核对账号、模型、Base URL、调用次数和预估费用；不要替用户自动确认付费调用。API key 只保存在 0600 secret store，数据库仅存引用，项目导出清空引用。

预算覆盖项目累计、Wave 冻结额度和项目时区每日额度，并记录排队任务的在途预留。默认不启用阻断；软预算超限需要管理员逐次填写理由，硬预算和未知成本在执行前拒绝，调度不能自动确认超限而会进入 `blocked`。成本金额是实际 usage + 管理员价格规则的估算，不是厂商账单。

DeepSeek Search+Chat、Kimi Search+Chat 和 DeepSeek 独立 Judge 已完成隔离单题 live；未覆盖 live 失败路径或账单对账。DeepSeek Web 与 Kimi Web 目前只通过本地模拟页面的真实 Chrome 合同验收，真实 selectors、登录和页面流程尚未 live 校准，不能标为真实平台已接入。任何新的真实 Provider 或网页调用仍需单独预估和即时确认。

## 测量与权限边界

- Wave 是业务测量，Run 是其下的一次尝试；正式 Run 只能由管理员指定。
- 失败、取消、空、截断或结果不明回答不能成为“零提及”。
- 原始回答不可变；人工复核和 Judge 升级只追加 observation revision。
- 只有 confirmed 实体进入有效提及、推荐和 SoV。
- 默认 Wilson 95%、小样本阈值 `n=30`、最低配对完整度 `90%`、3 轮采样（可配置 1–5）；Wave 冻结后不能看结果放宽。
- 实体审核、机会适用性、正式 Run、报告审批/发送登记和项目删除仅管理员可执行。
- reviewer/viewer 不读取原始回答、内部成本或内部版报告。
- 报告发送只是人工登记，不自动向外部服务发送。
- 原文默认不自动清理；显式配置保留天数后，只清理到期正文并保留有效样本、判定、usage 和聚合元数据。
- Action 改善/未改善结论要求另一轮 Wave 的正式 Run 和严格同口径比较，来源基线不能作为自己的复测目标。

公式见 `docs/metrics.md`，架构见 `docs/v2-architecture.md`。

## 运维

```bash
# 初始化、迁移检查、在线一致性备份
.venv/bin/python scripts/geopulse_ctl.py init
.venv/bin/python scripts/geopulse_ctl.py migrate
.venv/bin/python scripts/geopulse_ctl.py backup

# 停写后恢复；会覆盖目标数据库
.venv/bin/python scripts/geopulse_ctl.py restore /path/to/backup.db --yes

# 项目导出与删除
.venv/bin/python scripts/geopulse_ctl.py export 1
.venv/bin/python scripts/geopulse_ctl.py delete-project 1 --confirm '完整项目名'
```

单节点 SQLite 不提供多节点高可用。RPO 24h/RTO 4h 只是内部开发基线，不是客户 SLA；secret store 需要独立加密备份。恢复要求相邻 manifest、SHA-256、schema 和 SQLite integrity check，先验证临时文件再原子替换。完整部署与恢复步骤见 `docs/operations.md`。

## 验证

```bash
.venv/bin/python -m pytest -q

for file in frontend/*.js frontend/views/*.js; do
  node --input-type=module --check < "$file" || exit 1
done

.venv/bin/python scripts/check_vendor.py
.venv/bin/pip-audit -r requirements-lock.txt
.venv/bin/python scripts/geopulse_ctl.py golden-eval --out test-results/golden-eval.json
.venv/bin/python tests/stress_simulated.py
.venv/bin/python tests/browser_smoke.py
.venv/bin/python tests/browser_governance.py
.venv/bin/python tests/browser_manual_web.py
.venv/bin/python tests/browser_model_execution.py
.venv/bin/python tests/browser_web_collector.py
```

浏览器与压力脚本使用临时数据库和动态端口，不读取真实旧配置，不终止未知服务进程，不调用真实付费 Provider。离线黄金集只是小型回归集，不代表生产 LLM Judge 准确率；2700 次压力调用全部来自 DemoProvider。

## 版本

v2.3.0 · 2026-11-08 · 新增 DeepSeek Search、模型执行参数、独立 Judge、人工 Consumer Web，以及 DeepSeek Web/Kimi Web 授权浏览器离线闭环；真实网页平台仍待逐平台 live 校准。
