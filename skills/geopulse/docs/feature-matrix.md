# GeoPulse v2 功能对照矩阵

更新时间：2026-11-07。此矩阵按实际代码和验收记录描述能力，不把“能保存配置”写成“已自动执行”，也不把 mock 写成真实厂商验证。

状态说明：

- **已闭环**：界面、API、持久化和实际执行/状态机连通，并有自动化验收。
- **部分验证**：本地闭环完成，但真实外部账号或完整生产路径尚未验证。
- **仅 CLI**：刻意只提供受控运维入口，没有网页等价操作。
- **不在范围**：当前版本明确不实现。

## 1. 八条工作流

| 界面能力 | API / 服务 | 持久化与执行 | 权限 | 验收 | 状态 |
|---|---|---|---|---|---|
| 项目总览、待办和下一步 | `GET /overview` | 从正式 Run、审批、告警和调度实时聚合 | 全项目角色；成本字段裁剪 | `test_workflow.py`、桌面/移动浏览器 | 已闭环 |
| 问题集创建、生成、导入、审核、冻结 | `/prompt-sets*` | Prompt 版本、内容 hash、冻结快照、diff | 写入 analyst；审核/冻结 admin | `test_workflow.py`、浏览器 scaffold | 已闭环 |
| 实体卡、冲突、消歧和版本 | `/entities*` | 不可变实体版本、审核理由、竞品池 | 新建 analyst；审核 admin | `test_workflow.py`、浏览器 XSS/审核 | 已闭环 |
| Wave 创建与冻结预估 | `POST /waves`、`services.costs` | 公开协议签名 + 按回答引擎有效参数 + 内部执行快照 | analyst；成本仅 admin/analyst | `test_execution_governance.py`、`test_model_execution_v22.py` | 已闭环 |
| Run 创建、取消、重试、正式指定 | `/waves/{id}/runs`、`/runs/{id}/*` | SQLite 队列、worker、取消与 revision 保留 | 创建/取消 analyst；重试/正式 admin | worker、预算和浏览器测试 | 已闭环 |
| 人工 Web 目标与冻结协议 | `manual_web + consumer_web`、`collection_protocol` | 单一 Web 目标、实际页面/会话协议、独立 Judge 快照 | 目标写入 admin；Wave 创建 analyst | `test_manual_web.py`、真实 Chrome | 已闭环；不包含自动 Collector |
| 人工草稿、截图与不可变提交 | `/answers/{id}/collection*`、`/attachments*` | 草稿、raw hash、SQLite 证据 BLOB、人工引用、失败/重采 | 编辑 admin/analyst；只读角色无内部附件 | API、权限、hash、迁移与真实 Chrome | 已闭环；人工辅助采集 |
| 证据清单、原文和实体判定 | `/runs/{id}/answers`、`/answers/{id}` | 原始回答、citation、operation、observation revision | 修订 analyst；仲裁 admin；原文 admin/analyst | `test_roles.py`、真实浏览器 | 已闭环 |
| 候选发现与适用性审核 | `/opportunities*` | 证据 JSON、冻结权重评分、审核事件 | 发现 analyst；适用性 admin | `test_workflow.py`、浏览器 | 已闭环 |
| 七步 Action 与发布 | `/actions*` | 状态机、实际发布 URL/时间、共时事件 | analyst/admin 分节点 | 浏览器、`test_action_verification.py` | 已闭环 |
| Action 复测与改善结论 | `transition_action`、scheduler、compare | 创建真实 Schedule；要求另一 Wave 的正式 Run 和严格比较 | 安排 analyst；结论 admin | 改善/未改善/同基线拒绝专项测试 | 已闭环 |
| 同口径变化比较 | `GET /compare` | pair-key、有效样本完整度、冻结协议 | 全项目角色 | `test_workflow.py`、浏览器小样本 | 已闭环 |
| API/Web 跨 surface 摘要 | `GET /compare` | `cross_surface`、各自摘要、无严格 delta/迁移 | 全项目角色 | `test_manual_web.py` | 已闭环；不输出跨口径 pp |
| 报告快照、审批和预览 | `/reports*` | 不可变数据快照、保存 HTML、审批事件 | 创建 analyst；审批 admin | `test_report_gates.py`、浏览器/PDF | 已闭环 |
| 报告发送 | `POST /reports/{id}/status` | 只登记接收人/方式说明与审计 | admin | 状态机测试 | **人工登记**；不自动外发 |

## 2. 执行治理与系统管理

| 界面能力 | API / 服务 | 持久化与执行 | 权限 | 验收 | 状态 |
|---|---|---|---|---|---|
| 引擎连接和结构化价格 | `/engines*` | secret reference、独立 0600 secret store；项目内重名 create/update 返回结构化 409；旧 Wave 快照不变 | 全角色可读公开配置；价格/写入 admin | 重名、角色脱敏、冻结快照、浏览器表单 | 已闭环 |
| 模型能力与执行参数 | `capabilities`、`answer/judge/health_defaults`、Wave overrides | omitted/null 解析、能力校验、per-engine 不可变有效快照、请求参数/响应元数据台账 | 配置 admin；Wave analyst | 参数优先级、温度/输出上限、JSON mode、旧新比较与 Chrome | 已闭环 |
| 普通 Provider 独立 Judge | `judge_engine_id`、`judge_mode` | 回答/Judge 分开发送，engine_config_id、usage、成本和报告分别归属 | Wave analyst；Demo/真实不混用 | 多引擎预估、worker 归属、同引擎兼容、Chrome，以及 Kimi 回答→DeepSeek Judge 单题 live | 已闭环；交叉模型单题 live 通过 |
| 健康检查 | `POST /engines/{id}/health` | Search/Chat 进入统一调用台账；预算预留后释放 | admin；真实调用逐次确认 | 成功/失败/预算测试 | 本地已闭环；真实账号另见第 4 节 |
| 项目/Wave/每日预算 | `services.budgets`、项目设置 | 已发生成本 + active reservation；按项目时区每日边界 | admin 配置 | 边界、并发预留、币种和浏览器 | 已闭环 |
| 软预算超限 | Run/retry/health/schedule 统一入口 | 管理员逐次理由、预留和审计；调度无法自行确认 | admin 确认 | 服务测试与真实浏览器理由流程 | 已闭环 |
| 硬预算和未知成本 | 同上 | 执行前拒绝，不创建调用；缺价/混合币种不当作 0 | admin 调整额度/价格 | 服务与浏览器拒绝、补价入口 | 已闭环；不保证在途调用绝不超额 |
| 成本与运营 | `GET /operations` | 按 kind/operation/currency 汇总真实 usage；健康检查不遗漏 | admin/analyst | `test_roles.py`、浏览器 | 已闭环；是手工价格估算，非厂商账单 |
| 单次/周期调度 | `/schedules*`、scheduler | 事务认领、周期推进、退避、暂停/恢复/取消、blocked；人工 Web 创建即拒绝 | 读取项目角色；写入 admin | `test_scheduler_governance.py`、浏览器 | 已闭环 |
| 告警确认与历史 | `/alerts*` | 去重、确认、恢复、预算/备份/保留/引擎告警 | 读取项目角色；确认 admin | 调度测试、浏览器历史 | 已闭环 |
| 原文保留预览与清理 | `/retention/*`、后台维护 | tombstone；保留 valid sample、判定、usage 和聚合元数据；同步清理 Web 草稿/引用文本/附件 BLOB | 预览 admin/analyst；执行 admin | `test_retention.py`、`test_manual_web.py`、报告闸门、浏览器 | 已闭环；默认不清理 |
| 手工工时 | `POST /work-logs` | 业务日期、人员、类型、工时、说明和审计 | admin/analyst | `test_scheduler_governance.py`、浏览器 | 已闭环；不是自动计时 |
| 在线数据库备份 | `POST /backup`、`migrations.backup` | SQLite backup、相邻 manifest、SHA-256、失败告警/审计 | admin | `test_scheduler_governance.py`、浏览器下载 | 已闭环 |
| 项目导出 | `GET /export`、`services.exports` | `geopulse-project-v2`；递归清理 secret reference；附件 base64/hash；checksum | admin | `test_exports.py`、`test_manual_web.py`、浏览器 | 已闭环 |
| 数据库恢复 | `scripts/geopulse_ctl.py restore` | 校验 manifest/hash/schema/integrity；临时文件验证后原子替换 | 停写后的运维人员 | 篡改拒绝且目标文件不变 | **仅 CLI**，无网页覆盖入口 |
| 成员与全局用户 | `/memberships`、`/users` | 项目角色和全局用户分开 | 项目 admin / 全局 admin | 四角色 API 与浏览器 | 已闭环 |
| 审计 | `GET /audit` | 设置、预算、调度、告警、导出、报告等事件 | 项目 admin | 各服务专项测试 | 已闭环 |

## 3. 报告与数据口径

| 能力 | 实际行为 | 验收与边界 |
|---|---|---|
| 有效样本 | `answers.valid_sample` 持久化；正文清理后历史分母不变 | 失败、取消、空、截断和结果不明均不成为零提及 |
| 小样本 | 主数字为 hits/n，展示 Wilson 区间；隐藏确定性 SoV/pp 诊断 | 报告、测量、比较和浏览器均覆盖；小样本不一律禁止交付 |
| 发布闸门 | 对报告内每个 Wave 检查正式 Run、完整度、复核、Judge、证据、保留状态和机会适用性 | 基线不合格也会阻塞；人工 Web 重新校验正文 hash、截图 bytes/hash/size/magic 和冻结上下文 |
| 人工 Web 报告 | 快照保存采集协议、独立 Judge、证据覆盖和附件 metadata/hash，不嵌入 BLOB | 客户版不含账号别名、内部截图或内部原文；引用标为人工记录 |
| 报告导出 | 直接使用创建/审批时保存的 HTML，不用未来模板重排旧快照 | HTML/PDF 返回内容与数据快照 SHA-256，并写导出审计 |
| 客户版隔离 | 不包含内部成本、内部证据、其他项目或 secret reference | 四角色 API 和 reviewer/viewer 浏览器验证 |
| 原文清理后的报告 | 旧报告快照不变；包含已清理证据的新报告被闸门阻止 | `test_report_gates.py` |

## 4. 薄业务 CLI

| 能力 | 实际行为 | 状态 |
|---|---|---|
| 业务路由覆盖 | 注册表与 FastAPI OpenAPI 业务路由逐条对照；HTTP-only，不写业务 SQLite | `test_cli.py` 全覆盖 |
| 本机运维 | 保留 init/migrate/backup/restore/set-admin-password/run-worker/golden-eval/export/delete-project 九命令 | 原合同保留 |
| 认证与错误 | Bearer-only 0600 会话、秘密 FD、结构化 401/403/409/422/detail/request ID/estimate | 已闭环 |
| 写操作与真实调用 | 不自动重试；真实 Run/健康检查、审批、采集提交/失败、证据删除等显式确认 | 已闭环；未执行真实付费调用 |
| 文件 | 临时文件、0600 原子替换、大小/hash/PDF magic、项目导出内部 hash | 已闭环 |
| 人工 Web | collection save/get/submit/fail 与 evidence upload/download/delete | 隔离 CLI 全链通过 |
| 能力声明 | `capabilities` 返回注册表和 `live_provider_verified=false` | 不把命令覆盖写成 live 验收 |
| Schema 与示例 | `schema` 读取 `/openapi.json` 并展开 EngineIn/WaveIn/CollectionDraftIn；`example` 提供无秘密请求示例 | 只读或纯本地，无业务写副作用；提交响应明确 Worker 下一步 |

详细命令见 [cli.md](cli.md)。

## 5. 外部 Provider 与明确未覆盖范围

| 能力 | 当前状态 |
|---|---|
| DemoProvider | 完整离线闭环；健康检查也进入台账；不与真实指标混算 |
| OpenAI-compatible 协议 | mock 覆盖空正文、截断、显式 null、JSON mode、think 分离和错误 usage 保留。Geo agent 的既有报告另记录 DeepSeek Flash 单题真实链与 MiniMax 真实结构化 Judge 补验；不是本轮自动化执行结果。 |
| Kimi Search + Chat | Search Basic `text_query`、Search/Chat 分离、空结果零计费和失败不降级均有 mock；另经确认完成一次隔离单题 live，`kimi-k3.1-pro` 使用 `temperature=1,max_tokens=2048`，Search/Chat 各 1 次、5 条引用、Run done、有效样本 1；未做 live 失败路径或金额对账。 |
| DeepSeek Search + Chat | 官方 query/count/need_content 协议、长查询、引用、Search/Chat 台账、空结果无 Chat 和计费语义均有 mock；另经确认完成一次隔离单题 live，Search/Chat 各 1 次、10 条引用、Run done、有效样本 1，实际返回模型 `deepseek-flash`；未做 live 失败路径、交叉 Judge 或金额对账。 |
| 人工 Consumer Web 对话采集 | **已闭环（人工辅助）**。测试入口、草稿、截图、不可变提交、独立 Judge、报告和 CLI 已验证；不等于真实消费者平台 live 验收。 |
| 自动 Consumer Web/App Collector | **不在范围**。不实现持久登录、DOM 自动提取、验证码处理/绕过、多平台爬虫或 App 自动化；API 观察不能描述为终端产品实际回答。 |
| 厂商账单导入与对账 | **不在范围**。当前金额是实际 usage + 管理员价格规则的估算。 |
| 多节点队列、高可用 | **不在范围**。当前为单节点 FastAPI + SQLite。 |
| 自动向客户发送报告 | **不在范围**。仅人工登记发送记录。 |
| 旧 v1 测试数据回迁 | **不在范围**。当前 schema 为 v4；旧测试数据已获准删除。 |

## 6. 主要验收入口

- `pytest`：后端服务、状态机、权限、预算、调度、保留、导出、报告和 Action 专项。
- `tests/browser_smoke.py`：八条工作流、报告 PDF、viewer/reviewer、移动导航和证据详情。
- `tests/browser_governance.py`：结构化价格、软/硬预算、调度 blocked/恢复、告警历史、保留执行、手工工时、键盘 tabs 和移动溢出。
- `tests/browser_manual_web.py`：真实 Chrome 人工目标/Wave/Run、草稿、PNG、不可变提交、离线 Judge、复核、正式 Run、报告 PDF、失败登记、只读角色和 1440/768/390。
- `tests/browser_model_execution.py`：模型能力与默认参数、DeepSeek 离线配置、普通 Provider 独立 Judge、冻结协议、worker 归属及 1440/768/390。
- `tests/test_cli.py`：全路由注册、确认、错误、文件、Demo 业务链和人工 Web 证据链。
- `tests/stress_simulated.py`：仅 DemoProvider 的 2700 次模拟压力验收，不访问外部网络。
- `scripts/geopulse_ctl.py golden-eval`：小型离线回归集，不代表生产 LLM 准确率。
