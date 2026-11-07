# GeoPulse v2.1

GeoPulse 是一个自托管的 GEO 客户交付工作台：冻结问题与实体口径，执行可恢复的 Provider API 或人工 Consumer Web 测量，复核原始证据，再进行同口径比较、机会行动和报告审批。

它不是“排名承诺”工具。Provider API 与人工网页观察始终分开记账和比较，API 结果不会冒充 Kimi App、ChatGPT 网页等消费者产品的实际观察。

## 已实现的工作流

1. **项目总览**：当前交付阶段、待办、唯一下一步、正式指标、告警和运营摘要。
2. **问题集**：草稿、16 条候选 scaffold、JSON/CSV 导入去重、逐条审核、冻结、复制、版本 diff 和导出。
3. **品牌实体**：实体卡、别名冲突、管理员消歧、不可变版本、开放候选审核和竞品池 diff。
4. **测量执行**：Wave 与 Run 分离、调用/成本预估、持久队列、取消、管理员重试和正式 Run 指定；人工 Web Wave 冻结实际页面、会话和独立 Judge 协议。
5. **证据复核**：Provider 原文与 observation 并排；人工 Web 支持可编辑草稿、截图/raw evidence、人工页面引用、不可变提交和失败登记。
6. **机会与行动**：候选适用性审核、冻结权重评分、七步 Action、真实发布证据、复测和关闭。
7. **对比与报告**：协议与样本完整度检查、配对迁移、ECharts、不可变快照、三级审批、HTML/PDF。
8. **系统管理**：引擎、显式付费健康检查、成员角色、单次/周期调度、告警确认与恢复、成本、手工工时、软/硬预算、原文保留、备份、导出和审计。

逐项的“界面 → API → 持久化 → 执行器 → 权限 → 测试”对照，以及仅 CLI 和未覆盖能力，见 [docs/feature-matrix.md](docs/feature-matrix.md)。

## 快速开始

要求 Python 3.11+；当前开发环境使用 Python 3.14。PDF 和浏览器验收需要 Chrome/Chromium。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/python backend/run.py
```

打开 `http://127.0.0.1:8700`。首次启动会创建演示项目、冻结问题集、demo 引擎和管理员，并在终端显示一次性管理员密码。请登录后尽快通过 CLI 更换密码：

```bash
.venv/bin/python scripts/geopulse_ctl.py set-admin-password admin@geopulse.local
```

Demo 使用本地确定性回答，不访问外部模型，不代表真实 AI 表现。

## 真实引擎与费用边界

在“系统管理 → 引擎与口径”中配置：

- **OpenAI-compatible memory**：普通 Chat Completions 记忆态测量。
- **Kimi Search + Chat**：`POST /v1/tools/search` 的 `text_query` 检索，再交给 Chat 回答；Search 与 Chat usage 分开记录。
- **Demo**：本地演示，不与真实数据混算。
- **人工 Consumer Web**：只保存 HTTPS 产品入口，由内部成员在页面人工观察并提交回答、截图和实际采集事实；不保存 Cookie、密码或 Token，不执行网页自动化。

Search 失败、无结果或协议异常不会降级成 memory。模型 ID 和 Base URL 以管理员账号实际可用配置为准。密钥保存在独立 `backend/secrets.json`（0600），数据库只保存引用，项目导出会清空该引用且不包含密钥，API 不回显明文。

真实健康检查必须再次确认；创建真实 Run 前展示基础调用和含安全重试的调用/费用预估。默认不启用硬预算阻断；启用后，软预算超限需要管理员逐次填写理由，硬预算在执行前拒绝，调度遇到需人工确认的预算状态会阻塞并告警。未知价格不按零成本处理，金额是按实际 usage 和管理员价格规则计算的估算，不是厂商账单。真实厂商 smoke 不在测试或 CI 中自动执行。

## 测量口径

- Wave 是业务测量；Run 是其下的一次执行/重试尝试。
- 正式 Run 只能由管理员人工指定，报告不会自动切换到较新的尝试。
- 只有 `succeeded` 且原文非空的 Provider 回答进入有效指标；人工 Web 还必须完成不可变提交并保留有效截图证据。
- 失败、取消、空、截断或结果不明回答都不是“零提及”。
- 原始回答不可变；人工复核和 Judge 升级只追加 observation revision。
- 只有 confirmed 实体进入有效提及、推荐和 SoV。
- 默认 Wilson 95%、小样本阈值 `n=30`、最低配对完整度 `90%`、3 轮采样（可配置 1–5）。
- 阈值在 Wave 创建时冻结，不能看到结果后放宽。
- 人工 Web 只创建一个目标，不与 Provider 或其他 Web 目标混合；回答/Search 调用为 0，独立 Judge 单独预估和记录。调度器不会自动操作网页。
- API/Web 或不同 surface/session 上下文只返回各自摘要，不生成严格 pp、delta 或迁移结论。

完整公式见 [docs/metrics.md](docs/metrics.md)。

## 权限与数据隔离

角色为 `admin / analyst / reviewer / viewer`。所有业务接口按项目校验成员关系并带 `client_id + project_id` 查询作用域；全局管理员可跨项目管理。

实体审核、机会适用性、正式 Run、报告审批/发送登记和项目删除仅管理员可执行。reviewer/viewer 不能读取原始回答、内部成本或内部版报告。Cookie 写操作要求 CSRF token；也支持 Bearer token。报告发送只是人工登记，不会自动向外部服务发送。

## 配置

| 环境变量 | 默认值 | 用途 |
|---|---|---|
| `GEOPULSE_DB` | `backend/geopulse.db` | SQLite 数据库 |
| `GEOPULSE_SECRETS` | `backend/secrets.json` | 0600 密钥文件 |
| `GEOPULSE_CONFIG` | `backend/config.json` | 可选旧引擎配置导入，不导入旧回答 |
| `GEOPULSE_BACKUP_DIR` | `backend/backups` | 备份与 manifest |
| `GEOPULSE_EXPORT_DIR` | `outputs/` | 项目导出 |
| `GEOPULSE_WORKERS` | `4` | 有界 worker 数，限制 1–16 |
| `GEOPULSE_SESSION_HOURS` | `12` | 会话时长 |
| `GEOPULSE_DISABLE_WORKER` | 未设置 | `1` 时禁用应用内 worker/scheduler |
| `CHROME_PATH` | 自动探测 | PDF/浏览器测试所用 Chrome |

生产部署应使用 HTTPS 反向代理、独立持久目录和受限文件权限。当前是单节点 SQLite 架构，不提供多节点高可用。

## 运维命令

```bash
# 初始化/迁移检查/在线一致性备份
.venv/bin/python scripts/geopulse_ctl.py init
.venv/bin/python scripts/geopulse_ctl.py migrate
.venv/bin/python scripts/geopulse_ctl.py backup

# 停写后恢复；会覆盖目标数据库
.venv/bin/python scripts/geopulse_ctl.py restore /path/to/backup.db --yes

# 项目导出（不含密钥）与删除
.venv/bin/python scripts/geopulse_ctl.py export 1
.venv/bin/python scripts/geopulse_ctl.py delete-project 1 --confirm '完整项目名'
```

详见 [docs/operations.md](docs/operations.md)。HTTP 薄业务 CLI 的认证、命令、确认、文件校验和退出码见 [docs/cli.md](docs/cli.md)。内部开发基线为 RPO 24h / RTO 4h，不构成客户 SLA；需要定期做恢复演练。

## 测试与验收

```bash
# 后端单元、合同、权限、状态机、worker 和黄金集测试
.venv/bin/python -m pytest -q

# 零构建前端 ESM 语法
for file in frontend/*.js frontend/views/*.js; do
  node --input-type=module --check < "$file" || exit 1
done

# 隔离数据库、动态端口、真实 Chrome 八工作流与只读角色
.venv/bin/python tests/browser_smoke.py

# 真实 Chrome 预算、调度、告警、保留、工时、键盘和移动治理验收
.venv/bin/python tests/browser_governance.py

# 真实 Chrome 人工 Web：草稿、证据、离线 Judge、报告、失败与只读角色
.venv/bin/python tests/browser_manual_web.py

# 离线黄金集：准确率、召回率、F1、混淆矩阵与引用合同
.venv/bin/python scripts/geopulse_ctl.py golden-eval \
  --out test-results/golden-eval.json

# 100 意图 × 3 表述 × 3 引擎 × 3 轮，纯 DemoProvider
.venv/bin/python tests/stress_simulated.py

# 依赖和 vendor 完整性
.venv/bin/pip-audit -r requirements-dev.txt
.venv/bin/python scripts/check_vendor.py
```

浏览器和 stress 脚本使用临时数据库，不读取真实旧配置，不终止未知服务进程。测试截图和报告位于被忽略的 `test-results/`。

**当前验证边界**：Kimi Search 协议、错误处理和 OpenAI-compatible 截断处理使用 mock 验证。DeepSeek 已完成一次真实 Provider API smoke，但完整真实 Wave/Run/Judge 尚未验证；Kimi live 未执行。人工 Consumer Web 已用测试入口和离线 Demo Judge 验证产品闭环，这不等于真实消费者平台 live 验收，也不包含授权浏览器 Collector、持久登录、DOM 自动提取、验证码处理或多平台爬虫。离线黄金集是小型回归集，不是生产 LLM 准确率声明。真实 smoke 需要另行确认账号、模型、调用次数和费用，本轮功能验收不会自动产生付费调用。

## 目录

```text
backend/app/
  api/          项目作用域 REST API 与输入合同
  engine/       analyzer、judge、metrics、compare
  providers/    demo、OpenAI-compatible、Kimi Search + Chat
  services/     measurement、人工采集、scheduler、reporting、workflow、evaluation
  migrations/   顺序迁移 SQLite schema，当前 v3
frontend/       原生 ES modules、八个工作流、本地 ECharts
scripts/        本机运维、HTTP 薄 CLI、备份恢复、导出、黄金集和 vendor 检查
tests/          pytest、真实 Chrome smoke、2700 次模拟压力验收
evaluation/     人工编写的离线黄金集
docs/           v2 架构、指标、运维和变更记录
```

许可证：MIT。本地 ECharts 使用 Apache-2.0，完整来源与 SHA-256 见 `frontend/vendor/manifest.json`。
