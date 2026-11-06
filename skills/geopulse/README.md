# GeoPulse v2

GeoPulse 是一个自托管的 GEO 客户交付工作台：冻结问题与实体口径，执行可恢复的测量，复核原始证据，再进行同口径比较、机会行动和报告审批。

它不是“排名承诺”工具，也不会把 API 结果冒充 Kimi App、ChatGPT 网页等消费者产品的实际观察。

## 已实现的工作流

1. **项目总览**：当前交付阶段、待办、唯一下一步、正式指标、告警和运营摘要。
2. **问题集**：草稿、16 条候选 scaffold、JSON/CSV 导入去重、逐条审核、冻结、复制、版本 diff 和导出。
3. **品牌实体**：实体卡、别名冲突、管理员消歧、不可变版本、开放候选审核和竞品池 diff。
4. **测量执行**：Wave 与 Run 分离、调用/成本预估、持久队列、取消、管理员重试和正式 Run 指定。
5. **证据复核**：原文与当前 observation 并排、来源、Judge 元数据、revision 历史与人工修订。
6. **机会与行动**：候选适用性审核、冻结权重评分、七步 Action、真实发布证据、复测和关闭。
7. **对比与报告**：协议与样本完整度检查、配对迁移、ECharts、不可变快照、三级审批、HTML/PDF。
8. **系统管理**：引擎、显式付费健康检查、成员角色、调度、告警、成本、工时、预算、备份、导出和审计。

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

Search 失败、无结果或协议异常不会降级成 memory。模型 ID 和 Base URL 以管理员账号实际可用配置为准。密钥保存在独立 `backend/secrets.json`（0600），数据库只保存引用，项目导出会清空该引用且不包含密钥，API 不回显明文。

真实健康检查必须再次确认；创建真实 Run 前展示调用与成本预估。默认不做硬预算阻断，未知价格不按零成本处理。真实厂商 smoke 不在测试或 CI 中自动执行。

## 测量口径

- Wave 是业务测量；Run 是其下的一次执行/重试尝试。
- 正式 Run 只能由管理员人工指定，报告不会自动切换到较新的尝试。
- 只有 `succeeded` 且原文非空的回答进入有效指标。
- 失败、取消、空、截断或结果不明回答都不是“零提及”。
- 原始回答不可变；人工复核和 Judge 升级只追加 observation revision。
- 只有 confirmed 实体进入有效提及、推荐和 SoV。
- 默认 Wilson 95%、小样本阈值 `n=30`、最低配对完整度 `90%`、3 轮采样（可配置 1–5）。
- 阈值在 Wave 创建时冻结，不能看到结果后放宽。

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

详见 [docs/operations.md](docs/operations.md)。内部开发基线为 RPO 24h / RTO 4h，不构成客户 SLA；需要定期做恢复演练。

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

**当前验证边界**：Kimi Search 协议、错误处理和 OpenAI-compatible 截断处理使用 mock 验证；尚未执行真实 DeepSeek/Kimi 外部账号 smoke。离线黄金集是小型回归集，不是生产 LLM 准确率声明。真实 smoke 需要另行确认账号、模型、调用次数和费用。

## 目录

```text
backend/app/
  api/          项目作用域 REST API 与输入合同
  engine/       analyzer、judge、metrics、compare
  providers/    demo、OpenAI-compatible、Kimi Search + Chat
  services/     measurement、scheduler、reporting、workflow、evaluation
  migrations/   干净 v2 SQLite schema
frontend/       原生 ES modules、八个工作流、本地 ECharts
scripts/        初始化、备份恢复、导出、黄金集和 vendor 检查
tests/          pytest、真实 Chrome smoke、2700 次模拟压力验收
evaluation/     人工编写的离线黄金集
docs/           v2 架构、指标、运维和变更记录
```

许可证：MIT。本地 ECharts 使用 Apache-2.0，完整来源与 SHA-256 见 `frontend/vendor/manifest.json`。
