# GeoPulse v2.3

GeoPulse 是一个自托管的 GEO 客户交付工作台：冻结问题与实体口径，执行可恢复的 Provider API、人工 Consumer Web 或授权浏览器 Consumer Web 测量，复核原始证据，再进行同口径比较、机会行动和报告审批。

它不是“排名承诺”工具。Provider API、人工网页和授权浏览器观察始终分开记账和比较，API 结果不会冒充 Kimi App、DeepSeek Web、ChatGPT 网页等消费者产品的实际观察。

## 已实现的工作流

1. **项目总览**：当前交付阶段、待办、唯一下一步、正式指标、告警和运营摘要。
2. **问题集**：草稿、16 条候选 scaffold、JSON/CSV 导入去重、逐条审核、冻结、复制、版本 diff 和导出。
3. **品牌实体**：实体卡、别名冲突、管理员消歧、不可变版本、开放候选审核和竞品池 diff。
4. **测量执行**：Wave 与 Run 分离、按回答引擎冻结有效参数、同引擎或独立 Judge、调用/成本预估、持久队列、取消、管理员重试和正式 Run 指定；Consumer Web Wave 另冻结人工或授权浏览器采集协议。
5. **证据复核**：Provider 原文与 observation 并排；人工 Web 支持可编辑草稿、截图/raw evidence、人工页面引用、不可变提交和失败登记；授权浏览器任务显示当前问题、采集阶段、心跳及恢复原会话/登记失败操作，不提供人工改录入。
6. **机会与行动**：候选适用性审核、冻结权重评分、七步 Action、真实发布证据、复测和关闭。
7. **对比与报告**：协议与样本完整度检查、配对迁移、ECharts、不可变快照、三级审批、HTML/PDF。
8. **系统管理**：引擎、显式付费健康检查、DeepSeek Web/Kimi Web 本机浏览器连接、成员角色、单次/周期调度、告警确认与恢复、成本、手工工时、软/硬预算、原文保留、备份、导出和审计。

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
- **DeepSeek Search + Chat**：官方 `POST /v1/tools/search` 使用 `{query,count,need_content:false}`，读取 `results[]` 后交给 Chat；长查询确定性截断到 128 个 Unicode 字符，完整原始问题仍交给 Chat。协议来源：[DeepSeek Search & Fetch](https://api-docs.deepseek.com/guides/search/)，本轮不实现 Fetch。
- **Demo**：本地演示，不与真实数据混算。
- **人工 Consumer Web**：只保存 HTTPS 产品入口，由内部成员在页面人工观察并提交回答、截图和实际采集事实；不保存 Cookie、密码或 Token，不执行网页自动化。
- **授权浏览器 Consumer Web**：首批实现独立的 DeepSeek Web 与 Kimi Web Driver。管理员创建持久本机会话，用户在可见浏览器中自行登录和处理验证码，再验证会话；自动 Run 必须单独确认将冻结问题发送到第三方产品。采集器串行执行新会话、单轮无追问任务，保存正文、页面引用、回答区域截图和 HTML。结果不明只恢复原 conversation URL，不自动重发；人工降级必须另建人工 Wave/Run。当前两条 Driver 已通过本地模拟页面的真实 Chrome 合同验收，**尚未通过真实平台 live 校准，不能标为 live 已接入**。ChatGPT、豆包、Gemini 和 Consumer App 尚未实现。

Search 失败、无结果或协议异常不会降级成 memory。模型 ID 和 Base URL 以管理员账号实际可用配置为准。每个引擎可声明模型能力和 answer/Judge/health 默认参数，Wave 再按回答引擎覆盖；有效配置在创建时冻结。省略字段表示继承，显式 `null` 表示请求体不发送对应参数；不支持的 temperature 或已知输出上限超限会在调用前拒绝。普通 Provider 可选择同引擎 Judge 或同项目独立 Judge，回答、判定、Search、usage 与成本分别归属。密钥保存在独立 `backend/secrets.json`（0600），数据库只保存引用，项目导出会清空该引用且不包含密钥，API 不回显明文。

真实健康检查必须再次确认；创建真实 Run 前展示基础调用和含安全重试的调用/费用预估。授权浏览器即使没有 Provider 回答费用，也必须确认外部发送；独立 Judge 仍单独预估。默认不启用硬预算阻断；启用后，软预算超限需要管理员逐次填写理由，硬预算在执行前拒绝，调度遇到需人工确认的预算状态会阻塞并告警。未知价格不按零成本处理，金额是按实际 usage 和管理员价格规则计算的估算，不是厂商账单。网页订阅费不伪造成 0 元或按次 API 成本。真实厂商 smoke 不在测试或 CI 中自动执行。

浏览器 profile 默认位于 `backend/browser_profiles/`，目录权限 0700，锁文件 0600。它包含敏感本机登录状态，但不声称加密；Cookie、localStorage、密码和 storage state 不进入 SQLite、日志或项目导出。数据库备份不包含该外部目录，撤销会话后由 BrowserWorker 关闭浏览器并清理对应 profile。

## 测量口径

- Wave 是业务测量；Run 是其下的一次执行/重试尝试。
- 正式 Run 只能由管理员人工指定，报告不会自动切换到较新的尝试。
- 只有 `succeeded` 且原文非空的 Provider 回答进入有效指标；Consumer Web 还必须完成不可变提交并保留有效截图证据。
- 失败、取消、空、截断、推理耗尽或结果不明回答都不是“零提及”。起始完整 `<think>…</think>` 块只分离推理包装，不保存推理文本；未闭合或分离后无正文仍判失败。
- 原始回答不可变；人工复核和 Judge 升级只追加 observation revision。
- 只有 confirmed 实体进入有效提及、推荐和 SoV。
- 默认 Wilson 95%、小样本阈值 `n=30`、最低配对完整度 `90%`、3 轮采样（可配置 1–5）。
- 阈值在 Wave 创建时冻结，不能看到结果后放宽。
- Consumer Web 只创建一个目标，不与 Provider 或其他 Web 目标混合；回答/Search 调用为 0，独立 Judge 单独预估和记录。调度器不会自动操作网页；授权浏览器 Run 仍需 `confirm_browser=true` 和对应目标/Driver 的 active 本机会话。
- 人工与授权浏览器是不同冻结采集方法；严格比较还检查 product URL、platform、collection method 和 Driver。API/Web 或不同 surface/session 上下文只返回各自摘要，不生成严格 pp、delta 或迁移结论。

完整公式见 [docs/metrics.md](docs/metrics.md)。

## 权限与数据隔离

角色为 `admin / analyst / reviewer / viewer`。所有业务接口按项目校验成员关系并带 `client_id + project_id` 查询作用域；全局管理员可跨项目管理。

实体审核、机会适用性、正式 Run、报告审批/发送登记、浏览器会话创建/验证/撤销、结果不明采集恢复和项目删除仅管理员可执行。分析师可在已有 active 会话的目标上显式派发授权浏览器 Run，但不能查看或管理连接。reviewer/viewer 不能读取原始回答、内部成本、内部附件或内部版报告。Cookie 写操作要求 CSRF token；也支持 Bearer token。报告发送只是人工登记，不会自动向外部服务发送。

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
| `GEOPULSE_BROWSER_PROFILES` | `backend/browser_profiles/` | 持久本机浏览器 profile 根目录，0700 |
| `GEOPULSE_DISABLE_BROWSER_WORKER` | 未设置 | `1` 时只禁用 BrowserWorker；无图形环境应禁用并使用独立人工流程 |
| `GEOPULSE_BROWSER_HEADLESS` | 未设置 | 仅离线测试设为 `1`；真实登录使用可见浏览器 |
| `CHROME_PATH` | 自动探测 | PDF/浏览器测试及 Collector 所用 Chrome |

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

# 真实 Chrome 模型参数、DeepSeek 离线配置与普通 Provider 独立 Judge
.venv/bin/python tests/browser_model_execution.py

# 两套独立 Web Driver、本机会话、自动采集、恢复、撤销、报告和四角色（全部离线）
.venv/bin/python tests/browser_web_collector.py

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

**当前验证边界**：模型参数、错误处理和 OpenAI-compatible 截断/推理包装使用 mock 与离线浏览器验证。除合同 mock 外，本轮经单独确认完成了两组隔离单题 live：DeepSeek Search+Chat 各 1 次、10 条引用，实际返回模型 `deepseek-flash`；Kimi Search+Chat 各 1 次，`kimi-k3.1-pro` 以 `temperature=1,max_tokens=2048` 成功返回 5 条引用，随后 DeepSeek 独立 Judge 以 `temperature=0,max_tokens=1800` 和 JSON mode 成功返回 `llm-judge`，回答/Judge 引擎归属分开。两组 Run 均为 done、回答均为有效样本，未自动重试。价格规则为空，因此成本保持未知，不记为 0 元；这些单题结果不代表 live 失败路径、厂商账单对账或生产准确率已验证。Geo agent 的既有验收报告另记录了 DeepSeek Flash 单题真实链和 MiniMax 真实结构化 Judge 补验，这不是本轮自动化测试的执行结果。人工 Consumer Web 已用测试入口和离线 Demo Judge 验证产品闭环。v2.3 的 DeepSeek Web 与 Kimi Web Driver 另通过本地模拟页面的真实 Chrome 验收，覆盖持久会话验证、模式核验、流式回答、引用、截图/HTML、取消、验证码、selector 失效、原会话恢复和撤销；**这不是两个真实消费者平台的 live 验收，真实 selectors 和页面流程仍需授权账号逐平台校准**。未实现 ChatGPT、豆包、Gemini、Consumer App、验证码绕过、反检测伪装或大规模爬取。离线黄金集是小型回归集，不是生产 LLM 准确率声明。真实 smoke 需要另行确认账号、模型、调用次数和费用；pytest、Chrome 和 CI 不会自动产生付费调用。

## 目录

```text
backend/app/
  api/          项目作用域 REST API 与输入合同
  engine/       analyzer、judge、metrics、compare
  collectors/   独立的 DeepSeek Web、Kimi Web Driver 与共享采集合同
  providers/    demo、OpenAI-compatible、Kimi/DeepSeek Search + Chat
  services/     measurement、人工/浏览器采集、scheduler、reporting、workflow、evaluation
  migrations/   顺序迁移 SQLite schema，当前 v5
frontend/       原生 ES modules、八个工作流、本地 ECharts
scripts/        本机运维、HTTP 薄 CLI、备份恢复、导出、黄金集和 vendor 检查
tests/          pytest、真实 Chrome smoke、2700 次模拟压力验收
evaluation/     人工编写的离线黄金集
docs/           v2 架构、指标、运维和变更记录
```

许可证：MIT。本地 ECharts 使用 Apache-2.0，完整来源与 SHA-256 见 `frontend/vendor/manifest.json`。
