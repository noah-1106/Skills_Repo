# GeoPulse v2 部署与运维

## 1. 部署基线

推荐单台受控主机、单 Uvicorn 进程、本地或受控磁盘上的 SQLite。生产由 HTTPS 反向代理暴露服务，数据库、secret store、备份和导出目录只允许运行账号访问。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt

export GEOPULSE_DB=/srv/geopulse/data/geopulse.db
export GEOPULSE_SECRETS=/srv/geopulse/private/secrets.json
export GEOPULSE_CONFIG=/srv/geopulse/private/legacy-config.json
export GEOPULSE_BACKUP_DIR=/srv/geopulse/backups
export GEOPULSE_EXPORT_DIR=/srv/geopulse/exports
export GEOPULSE_BROWSER_PROFILES=/srv/geopulse/private/browser-profiles
export GEOPULSE_WORKERS=4

.venv/bin/python scripts/geopulse_ctl.py init
.venv/bin/python backend/run.py --host 127.0.0.1 --port 8700
```

首次初始化在终端显示一次性管理员密码。立即登录并更换：

```bash
.venv/bin/python scripts/geopulse_ctl.py set-admin-password admin@geopulse.local
```

不要用多个独立 Uvicorn worker 进程共享这个内置队列来扩容。当前架构是单节点；需要多节点、高可用或分布式队列时应另行设计，而不是直接增加进程数。

## 2. 文件与权限

| 内容 | 默认位置 | 建议权限 |
|---|---|---|
| SQLite | `backend/geopulse.db` | 0600，运行账号所有 |
| SQLite WAL/SHM | 同目录 | 同数据库，备份期间不要手工复制单个文件 |
| 密钥 | `backend/secrets.json` | 0600 |
| 可选旧引擎配置 | `backend/config.json` | 0600 |
| DB 备份 | `backend/backups/` | 0700 目录，0600 文件 |
| 项目导出 | `outputs/` | 按客户资料保护 |
| 浏览器 profiles | `backend/browser_profiles/` | 0700 目录；锁文件 0600；运行账号所有 |

浏览器 profile 含 Cookie/localStorage 等敏感登录状态，只是受文件权限保护的本机目录，不声称加密。不要把该目录同步到 Skills_Repo、项目导出、普通数据库备份或客户报告。Cookie、密码和 storage state 不进入 SQLite。需要保留登录会话以支持灾难恢复时，应使用单独授权的加密备份流程；撤销会话后由 BrowserWorker 清理对应目录。

不要在 issue、聊天、前端、日志或报告中粘贴密钥。数据库备份不保存明文 Provider key；如需灾难恢复真实引擎，secret store 必须通过独立加密备份渠道保存。项目 JSON 导出也不含密钥。

旧 `backend/config.json` 只用于导入 OpenAI-compatible 引擎配置，不导入旧回答。没有旧配置时，将 `GEOPULSE_CONFIG` 指向不存在的路径可禁用导入。

## 3. 健康检查与真实付费调用

应用存活：

```bash
curl --fail http://127.0.0.1:8700/api/health
```

响应包含程序和 schema 版本。引擎健康检查与存活检查不同：非 demo 引擎会向厂商发起真实请求，可能收费，API 必须带 `{"confirm":true}`，UI 会再次确认。健康检查使用引擎自己的 health 有效参数，不再固定 temperature=0/max_tokens=8。Search 和 Chat 健康调用会进入统一调用台账，同时保留业务分组 `kind=health` 与实际计费操作 `operation=search/answer`，因此运营成本和用量汇总不会漏掉健康检查。

真实 smoke 执行前逐项确认：

1. 使用隔离测试项目，不混入正式客户指标；
2. 引擎 Base URL、模型 ID、密钥归属和账号额度；
3. memory/search、Provider API 测量目标；
4. prompt 数、轮次、Search/Chat/Judge 调用次数；
5. 当前价格规则和最大可能费用；
6. 超时结果不明时不自动重放。

CI、pytest、浏览器 smoke/governance/manual-web/model-execution/web-collector 和 2700 压力脚本均不执行真实付费调用，也不会登录真实消费者网站。Kimi 与 DeepSeek Search 合同 mock 通过不等于外部账号 live smoke 通过。本轮经单独确认完成了两组隔离单题 live：DeepSeek Search+Chat 各 1 次、10 条引用，实际返回模型 `deepseek-flash`；Kimi Search+Chat 各 1 次，`kimi-k3.1-pro` 使用 `temperature=1,max_tokens=2048` 返回 5 条引用，随后 DeepSeek 独立 Judge 使用 `temperature=0,max_tokens=1800` 和 JSON mode 返回 `llm-judge`，回答/Judge 引擎归属分开。两组 Run 均为 done、回答均为有效样本，未自动重试。未配置价格规则，成本保持未知；单题 live 不覆盖失败路径、账单对账或生产准确率。Geo agent 的既有报告另记录 DeepSeek Flash 单题真实链与 MiniMax 真实结构化 Judge 补验，不是本轮自动化执行结果。人工 Consumer Web 的测试入口和 Demo Judge 只验证离线产品闭环，不代表真实消费者平台 live 验收。DeepSeek Web 与 Kimi Web 的独立 Driver 已通过本地模拟页面的真实 Chrome 验收，但尚未完成真实平台 selectors、登录和联网模式校准，仍不得标为 live 已接入。每个平台的真实验收都要另行即时确认：使用授权账号、可见浏览器、隔离项目，先由用户登录/处理验证码并验证会话，再只发 1 条冻结问题；不自动重试，产物仅放 ignored `test-results/`。后续真实 smoke 仍需独立预估和即时确认，既有确认不自动延伸到新调用。

## 4. 队列与调度

默认应用内启动 4 个 worker 和 scheduler。每引擎独立限流，不同引擎可并行。

- 进程重启恢复 queued/running/judging。
- 已有原文的样本只恢复 Judge，不重复 Provider 请求。
- 可安全重试错误最多按 Wave 协议自动重试；超时等结果不明错误需管理员重试。
- 活跃 Run 未结束时，调度器不会为同一 Wave 重复入队。
- Consumer Web 不能创建自动调度；人工与授权浏览器 Run 都只能由内部成员在测量页显式创建。授权浏览器还需要 `confirm_browser=true` 和对应目标/Driver 的 active 本机会话。
- BrowserWorker 与 Provider worker 使用独立队列 lane，首版浏览器任务全局串行；数据库 lease/heartbeat 与本机 `fcntl.flock` 共同防止同一 profile 被两个采集器使用。队列认领在同一写事务内排除未过期 lease，并用条件更新原子设置 owner、attempt 和 `preparing`，避免误启动的第二个 Worker 覆盖任务。
- 发送前持久化 `submitting`，发送后记录 conversation URL。只有确认未进入发送阶段的过期 lease 才自动重排；发送中/发送后崩溃进入 `paused_unknown`，只能恢复原会话或由管理员登记失败，绝不自动重发。
- 登录失效或验证码进入 `awaiting_user` 并暂停同 session 后续任务。用户在可见浏览器中处理后，管理员重新验证 `expired` 会话，再恢复当前采集。
- 正式 Run 仍由管理员人工指定，调度不会自动替换。
- 调度支持单次、每 7/14/28 天和自定义周期；可在 UI 编辑、暂停、恢复或取消。
- 周期任务每次只执行一次到期测量，再推进到未来，不在停机后突发补跑全部过期周期。
- 调度认领、Run 创建、预算预留和下次时间推进位于同一可回滚事务内；失败保留诊断状态并生成告警。
- 调度遇到软预算确认、硬预算或未知成本时进入 `blocked`，不会代替管理员确认超限。处理价格/额度后使用“处理后再试”。
- Action 的“安排复测”会创建真实 Schedule；“确认改善”要求另一轮 Wave 的正式 Run 和严格同口径比较，不能用来源基线自我复测。

### 预算执行语义

项目累计、Wave 冻结额度和项目时区每日额度统一适用于手工 Run、失败样本重试、调度和健康检查。排队时使用 `budget_reservations` 记录在途预估，完成、取消或失败后按真实 usage 对账并释放，避免多个排队 Run 同时绕过额度。

- 默认只展示预估，不启用预算阻断。
- 启用检查后，软预算超限需要管理员针对本次执行填写理由；理由和确认进入预留与审计，不修改额度。
- 硬预算在执行前拒绝；缺失价格、缺失必要 usage 或混合币种不会按零成本放行。
- 基础调用数与含安全重试的调用次数上限分开显示；token 和金额仍是启发式预估。
- 硬限额是执行前保护，不承诺已经发出的在途厂商调用绝不超额。

只运行独立 worker 时，可先以 `GEOPULSE_DISABLE_WORKER=1` 启动 Web，再运行：

```bash
.venv/bin/python scripts/geopulse_ctl.py run-worker
```

这仍是同一单节点部署方式；`run-worker` 同时启动 Provider/Judge worker 和 BrowserWorker。不要让多个独立调度器同时处理同一数据库，也不要让多个采集器共用同一浏览器 profile。真实登录必须使用可见浏览器；`GEOPULSE_BROWSER_HEADLESS=1` 只用于离线测试。无图形环境设置 `GEOPULSE_DISABLE_BROWSER_WORKER=1`，不要尝试伪造网页结果；可另建人工 Wave/Run。

## 5. 备份

在线一致性备份使用 SQLite backup API：

```bash
.venv/bin/python scripts/geopulse_ctl.py backup
```

输出包含源路径、备份路径、schema 版本、UTC 时间和 SHA-256；同目录生成 `.manifest.json`。也可在“系统管理 → 设置与数据治理”创建备份并下载 manifest。Consumer Web 截图/raw evidence 以 SQLite BLOB 保存在同一数据库，因此一致性备份会同时包含正文、采集事实和证据字节；不要只导出 JSON 后把它当作数据库备份。浏览器 profile 位于数据库外部，**不包含在此备份中**；恢复数据库不会恢复网页登录会话，应重新授权验证，或按独立加密备份流程处理。

建议：

- 内部开发基线：RPO 24h、RTO 4h，不构成客户 SLA。
- 至少每天备份，并将副本放到不同故障域。
- 对备份文件和 manifest 设置 0600。
- 备份失败应告警，不能把“命令曾执行”当作可恢复证明。
- 定期执行恢复演练并记录实际 RPO/RTO。
- 原始回答默认不自动删除；保留策略变化需按客户合同单独配置。

校验示例：

```bash
shasum -a 256 /path/to/backup.db
```

将结果与 manifest 的 `sha256` 比较。restore 会要求备份旁的相邻 manifest，并校验 SHA-256、schema 版本和 SQLite `integrity_check`；先在同目录临时文件上恢复和验证，再原子替换目标。任何校验失败都不会修改现有数据库。命令仍不能替人工判断备份是否选错，恢复前必须核对项目、时间和 checksum。

## 6. 恢复演练与正式恢复

恢复会覆盖目标数据库。先停止 Web、worker 和 scheduler 的全部写入，再操作。不要对正在写的生产库直接试验。

### 隔离演练

```bash
export GEOPULSE_DB=/srv/geopulse/recovery-drill/geopulse.db
export GEOPULSE_SECRETS=/srv/geopulse/recovery-drill/secrets.json
export GEOPULSE_BACKUP_DIR=/srv/geopulse/recovery-drill/backups

.venv/bin/python scripts/geopulse_ctl.py restore /path/to/backup.db --yes
.venv/bin/python backend/run.py --host 127.0.0.1 --port 8710 --no-worker
```

检查项目数、正式 Run、回答/observation 数、报告快照和权限，再停止演练服务。`--no-worker` 避免演练库继续执行队列或真实请求。

### 正式恢复

1. 停止所有写入并保留当前故障库的额外备份。
2. 核对备份 manifest、schema 和 SHA-256。
3. 用 `GEOPULSE_DB` 明确指向目标库执行 restore。
4. 如 secret store 也需恢复，从独立加密备份恢复并设置 0600。
5. 先以 `--no-worker` 启动并验证。
6. 确认没有不应重放的真实调用后，再恢复正常 worker/scheduler。
7. 记录恢复人、时间、备份 checksum、验证结果和实际 RPO/RTO。

## 7. 迁移

```bash
.venv/bin/python scripts/geopulse_ctl.py migrate
```

当前 schema 为 v5，`PRAGMA user_version=5`。迁移按 `001_v2.sql`、`002_execution_governance.sql`、`003_manual_consumer_web.sql`、`004_model_execution_search.sql`、`005_authorized_browser_collector.sql` 顺序执行并记录 checksum。v5 新增本机浏览器会话元数据、自动采集阶段/lease/恢复字段和 `browser_page` 引用；不保存 Cookie、密码或 profile 内容。populated v4→v5 测试保留 answer 原文、collection/citation ID、origin/title、证据 BLOB、外键和完整性，历史 collection 默认 `manual`。程序拒绝静默打开未知旧版本或更新版本。迁移前会自动创建带 manifest 的一致性备份；本版本不迁移旧 v1 回答数据。

## 8. 项目导出与删除

```bash
.venv/bin/python scripts/geopulse_ctl.py export 1 --out /secure/path/project-1.json
.venv/bin/python scripts/geopulse_ctl.py delete-project 1 --confirm '完整项目名'
```

导出包含 schema、项目业务表、导出时间和 SHA-256，不含 secret store、`browser_sessions`、profile reference、lease owner 或浏览器 session 内部 ID。导出合同为 `geopulse-project-v2`；Consumer Web 附件 content 以 `{"encoding":"base64","data":"…"}` 表示，恢复或离线校验时必须按编码还原，不能把 base64 文本当作截图 bytes。删除会级联删除该项目业务数据；已有备份不会被自动删除，需按保留策略处理。UI 删除要求输入完整项目名。

## 9. 原文保留与清理

`retention_days` 留空或为 0 时不自动清理。管理员显式配置后，维护任务按项目隔离处理到期原文；UI 可先预览 cutoff 和候选数，再确认执行并记录审计。

清理只移除原始回答正文与敏感载荷，保留 `valid_sample`、observation、usage、状态和聚合所需元数据，并留下原文 tombstone。Consumer Web 同时清理草稿、页面引用卡片文本和附件 BLOB，授权浏览器还清理 conversation URL 与阶段详情，保留 raw hash、附件 hash/size 与 tombstone，并返回 `attachment_purged_count`。历史指标不会因正文为空而被改成零提及；清理后禁止新增依赖原文的 revision。旧报告快照保持不变，但包含已清理证据的新报告不能通过原文或人工证据发布闸门。

## 10. 日志、成本与告警

HTTP 结构化日志包含 request ID、方法、路径、状态和延迟。业务表保存 project/wave/run 关联，调用记录保存类型、模型、usage、延迟、成本和错误。

- 不在日志中输出 API key、密码、session token、Cookie、浏览器页面正文或 profile 路径；BrowserWorker 异常只持久化安全的阶段错误。
- reviewer/viewer 响应隐藏原始回答、内部成本和内部错误细节。
- 成本按 answer/judge/search 和业务类型分列，并按币种分别汇总；未知价格和未知 usage 单独计数，不按零成本。
- 金额使用真实 usage 与管理员价格规则估算，不是厂商账单；SQLite 文件大小是全库大小，不是单项目占用，工时为手工登记。
- 默认预算只提醒；软超限逐次确认，显式硬限额在执行前拒绝。
- Run partial/failed、样本不足、Judge 降级、预算、调度、备份和维护失败会生成告警。开放告警默认只列未确认项，历史单独查看，确认和恢复分别记录。

## 11. 故障排查

| 症状 | 检查 | 下一步 |
|---|---|---|
| 端口已占用 | `lsof -nP -iTCP:8700 -sTCP:LISTEN` | 识别进程；不要批量杀未知进程，可改用 `--port` |
| 401 | 会话过期、密码已更换 | 重新登录 |
| 403 CSRF | 页面令牌过期 | 刷新并重新登录 |
| Run 全部失败 | 引擎错误类型、模型、Base URL、账号额度 | 修正配置后由管理员明确重试 |
| Search 失败 | Search operation 与错误前缀 | 不用 memory 补位，检查检索权限与协议 |
| Judge 降级 | `judge_fallback_rate`、JSON/证据错误 | 复核 pending 样本，黄金集通过后再升级 Judge |
| 调度 blocked | 告警详情中的预算或执行错误 | 软预算不能自动确认；补齐价格/调整额度后“处理后再试” |
| 浏览器会话 pending/expired | 本机 BrowserWorker、可见浏览器、登录/验证码、`last_error` | 用户本人完成登录和验证码，再点击验证；不要提交 Cookie 或密码 |
| 自动采集 awaiting_user | 当前 prompt、session 状态和心跳 | 先重新验证会话，再恢复当前任务；同 session 后续任务保持暂停 |
| 自动采集 paused_unknown | `browser_send_started_at`、conversation URL、原页面结果 | 有 URL 只恢复原会话；无 URL 只能登记失败，不能自动重发 |
| Driver 不兼容/空证据 | 平台改版、冻结模式、选择器、截图/HTML 大小 | 标为未验证并校准 Driver；不降级 memory、不人工覆盖自动原文 |
| Run 被硬预算拒绝 | 项目/Wave/每日额度、active reservation、未知价格 | 管理员调整额度或执行范围；未知成本先补价，不能按 0 元绕过 |
| 对比被拒绝 | mismatches、pair/sample completeness | 使用同口径正式 Run，不能事后放宽冻结阈值 |
| PDF 失败 | Chrome/Chromium 是否安装 | 设置 `CHROME_PATH` 后重试 |
| 数据库锁定 | 多写入进程、长事务、磁盘状态 | 保持单节点写入，检查慢操作与磁盘 |

## 12. 安全更新

```bash
.venv/bin/pip-audit -r requirements-dev.txt
.venv/bin/python scripts/check_vendor.py
.venv/bin/python -m pytest -q
```

CI 还执行前端 ESM、五套真实浏览器、黄金集、模拟压力和 secret scanning。HTTP 薄业务 CLI 的认证、确认和文件校验见 [cli.md](cli.md)。更新 ECharts 时必须同步版本、来源、许可证和 SHA-256，不要无记录替换 minified 文件。
