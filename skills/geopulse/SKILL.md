---
name: geopulse
description: 自托管的多客户 GEO 交付工作台。冻结问题与实体口径，执行可恢复的 Wave/Run 测量，复核不可变原始证据，完成同口径比较、机会与七步 Action、客户/内部报告审批，以及角色、调度、成本和备份管理。支持 Demo、OpenAI-compatible memory 和 Kimi Search + Chat 检索增强 API。
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
```

不要把数据库、secret store、旧 `backend/config.json`、客户原文或测试输出提交到仓库。

## 八条工作流

1. **项目总览**：当前阶段、待办、正式指标、告警和下一次复测。
2. **问题集**：草稿、候选 scaffold、JSON/CSV、去重、审核、冻结、复制和版本 diff。
3. **品牌实体**：实体卡、别名冲突、管理员消歧、不可变版本和竞品池。
4. **测量执行**：Wave 冻结协议，Run 执行/重试，调用与成本预估，持久队列和正式 Run 指定。
5. **证据复核**：原文与 observation、Judge 元数据、引用和追加式人工 revision。
6. **机会与行动**：管理员确认适用性、冻结权重评分、七步 Action、真实发布和复测。
7. **对比与报告**：协议与有效样本完整度、配对迁移、ECharts、不可变快照、三级审批、HTML/PDF。
8. **系统管理**：引擎、成员角色、调度、告警、成本、工时、预算、审计、备份、导出和删除。

## 真实引擎与费用

在“系统管理 → 引擎与口径”配置：

- **OpenAI-compatible memory**：普通 Chat Completions 记忆态测量。
- **Kimi Search + Chat**：先调用 `POST /v1/tools/search`，再单独调用 Chat；Search/Chat usage 分开记录。
- **Demo**：本地确定性数据，只用于演示和测试，不能与真实引擎混算。

Search 失败、无结果或协议异常不会静默降级 memory。真实健康检查和真实 Run 可能产生厂商费用，执行前必须核对账号、模型、Base URL、调用次数和预估费用；不要替用户自动确认付费调用。API key 只保存在 0600 secret store，数据库仅存引用，项目导出清空引用。

当前通过的是 Kimi/OpenAI-compatible 协议 mock，尚未完成真实 DeepSeek/Kimi 外部账号 smoke。

## 测量与权限边界

- Wave 是业务测量，Run 是其下的一次尝试；正式 Run 只能由管理员指定。
- 失败、取消、空、截断或结果不明回答不能成为“零提及”。
- 原始回答不可变；人工复核和 Judge 升级只追加 observation revision。
- 只有 confirmed 实体进入有效提及、推荐和 SoV。
- 默认 Wilson 95%、小样本阈值 `n=30`、最低配对完整度 `90%`、3 轮采样（可配置 1–5）；Wave 冻结后不能看结果放宽。
- 实体审核、机会适用性、正式 Run、报告审批/发送登记和项目删除仅管理员可执行。
- reviewer/viewer 不读取原始回答、内部成本或内部版报告。
- 报告发送只是人工登记，不自动向外部服务发送。

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

单节点 SQLite 不提供多节点高可用。RPO 24h/RTO 4h 只是内部开发基线，不是客户 SLA；secret store 需要独立加密备份。完整部署与恢复步骤见 `docs/operations.md`。

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
```

浏览器与压力脚本使用临时数据库和动态端口，不读取真实旧配置，不终止未知服务进程，不调用真实付费 Provider。离线黄金集只是小型回归集，不代表生产 LLM Judge 准确率；2700 次压力调用全部来自 DemoProvider。

## 版本

v2.0.0 · 2026-11-06 · 多客户隔离、八条交付工作流、Kimi Search + Chat、证据 revision、严格比较、机会行动、不可变报告和完整离线验收。
