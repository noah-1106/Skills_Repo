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
| Wave 创建与冻结预估 | `POST /waves`、`services.costs` | 公开协议签名 + 内部引擎执行快照 | analyst；成本仅 admin/analyst | `test_execution_governance.py` | 已闭环 |
| Run 创建、取消、重试、正式指定 | `/waves/{id}/runs`、`/runs/{id}/*` | SQLite 队列、worker、取消与 revision 保留 | 创建/取消 analyst；重试/正式 admin | worker、预算和浏览器测试 | 已闭环 |
| 证据清单、原文和实体判定 | `/runs/{id}/answers`、`/answers/{id}` | 原始回答、citation、operation、observation revision | 修订 analyst；仲裁 admin；原文 admin/analyst | `test_roles.py`、真实浏览器 | 已闭环 |
| 候选发现与适用性审核 | `/opportunities*` | 证据 JSON、冻结权重评分、审核事件 | 发现 analyst；适用性 admin | `test_workflow.py`、浏览器 | 已闭环 |
| 七步 Action 与发布 | `/actions*` | 状态机、实际发布 URL/时间、共时事件 | analyst/admin 分节点 | 浏览器、`test_action_verification.py` | 已闭环 |
| Action 复测与改善结论 | `transition_action`、scheduler、compare | 创建真实 Schedule；要求另一 Wave 的正式 Run 和严格比较 | 安排 analyst；结论 admin | 改善/未改善/同基线拒绝专项测试 | 已闭环 |
| 同口径变化比较 | `GET /compare` | pair-key、有效样本完整度、冻结协议 | 全项目角色 | `test_workflow.py`、浏览器小样本 | 已闭环 |
| 报告快照、审批和预览 | `/reports*` | 不可变数据快照、保存 HTML、审批事件 | 创建 analyst；审批 admin | `test_report_gates.py`、浏览器/PDF | 已闭环 |
| 报告发送 | `POST /reports/{id}/status` | 只登记接收人/方式说明与审计 | admin | 状态机测试 | **人工登记**；不自动外发 |

## 2. 执行治理与系统管理

| 界面能力 | API / 服务 | 持久化与执行 | 权限 | 验收 | 状态 |
|---|---|---|---|---|---|
| 引擎连接和结构化价格 | `/engines*` | secret reference、独立 0600 secret store；旧 Wave 快照不变 | 全角色可读公开配置；价格/写入 admin | 角色脱敏、冻结快照、浏览器表单 | 已闭环 |
| 健康检查 | `POST /engines/{id}/health` | Search/Chat 进入统一调用台账；预算预留后释放 | admin；真实调用逐次确认 | 成功/失败/预算测试 | 本地已闭环；真实账号另见第 4 节 |
| 项目/Wave/每日预算 | `services.budgets`、项目设置 | 已发生成本 + active reservation；按项目时区每日边界 | admin 配置 | 边界、并发预留、币种和浏览器 | 已闭环 |
| 软预算超限 | Run/retry/health/schedule 统一入口 | 管理员逐次理由、预留和审计；调度无法自行确认 | admin 确认 | 服务测试与真实浏览器理由流程 | 已闭环 |
| 硬预算和未知成本 | 同上 | 执行前拒绝，不创建调用；缺价/混合币种不当作 0 | admin 调整额度/价格 | 服务与浏览器拒绝、补价入口 | 已闭环；不保证在途调用绝不超额 |
| 成本与运营 | `GET /operations` | 按 kind/operation/currency 汇总真实 usage；健康检查不遗漏 | admin/analyst | `test_roles.py`、浏览器 | 已闭环；是手工价格估算，非厂商账单 |
| 单次/周期调度 | `/schedules*`、scheduler | 事务认领、周期推进、退避、暂停/恢复/取消、blocked | 读取项目角色；写入 admin | `test_scheduler_governance.py`、浏览器 | 已闭环 |
| 告警确认与历史 | `/alerts*` | 去重、确认、恢复、预算/备份/保留/引擎告警 | 读取项目角色；确认 admin | 调度测试、浏览器历史 | 已闭环 |
| 原文保留预览与清理 | `/retention/*`、后台维护 | tombstone；保留 valid sample、判定、usage 和聚合元数据 | 预览 admin/analyst；执行 admin | `test_retention.py`、报告闸门、浏览器 | 已闭环；默认不清理 |
| 手工工时 | `POST /work-logs` | 业务日期、人员、类型、工时、说明和审计 | admin/analyst | `test_scheduler_governance.py`、浏览器 | 已闭环；不是自动计时 |
| 在线数据库备份 | `POST /backup`、`migrations.backup` | SQLite backup、相邻 manifest、SHA-256、失败告警/审计 | admin | `test_scheduler_governance.py`、浏览器下载 | 已闭环 |
| 项目导出 | `GET /export`、`services.exports` | UI/CLI 同合同；递归清理 JSON 字符串内 secret reference；checksum | admin | `test_exports.py`、浏览器 | 已闭环 |
| 数据库恢复 | `scripts/geopulse_ctl.py restore` | 校验 manifest/hash/schema/integrity；临时文件验证后原子替换 | 停写后的运维人员 | 篡改拒绝且目标文件不变 | **仅 CLI**，无网页覆盖入口 |
| 成员与全局用户 | `/memberships`、`/users` | 项目角色和全局用户分开 | 项目 admin / 全局 admin | 四角色 API 与浏览器 | 已闭环 |
| 审计 | `GET /audit` | 设置、预算、调度、告警、导出、报告等事件 | 项目 admin | 各服务专项测试 | 已闭环 |

## 3. 报告与数据口径

| 能力 | 实际行为 | 验收与边界 |
|---|---|---|
| 有效样本 | `answers.valid_sample` 持久化；正文清理后历史分母不变 | 失败、取消、空、截断和结果不明均不成为零提及 |
| 小样本 | 主数字为 hits/n，展示 Wilson 区间；隐藏确定性 SoV/pp 诊断 | 报告、测量、比较和浏览器均覆盖；小样本不一律禁止交付 |
| 发布闸门 | 对报告内每个 Wave 检查正式 Run、完整度、复核、Judge、证据、保留状态和机会适用性 | 基线不合格也会阻塞；自动检查不替代人工事实核验 |
| 报告导出 | 直接使用创建/审批时保存的 HTML，不用未来模板重排旧快照 | HTML/PDF 返回内容与数据快照 SHA-256，并写导出审计 |
| 客户版隔离 | 不包含内部成本、内部证据、其他项目或 secret reference | 四角色 API 和 reviewer/viewer 浏览器验证 |
| 原文清理后的报告 | 旧报告快照不变；包含已清理证据的新报告被闸门阻止 | `test_report_gates.py` |

## 4. 外部 Provider 与明确未覆盖范围

| 能力 | 当前状态 |
|---|---|
| DemoProvider | 完整离线闭环；健康检查也进入台账；不与真实指标混算 |
| OpenAI-compatible 协议 | mock 覆盖空正文、截断、错误 usage 保留。**DeepSeek 已完成一次真实 Provider API smoke；完整真实 Wave/Run/Judge 未验证。** |
| Kimi Search + Chat | Search Basic `text_query`、Search/Chat 分离和失败不降级均有 mock；**本轮未执行 Kimi live，外部账号验证未完成。** |
| Consumer Web/App 对话采集 | **不在范围**。API 观察不能描述为 Kimi App、DeepSeek 网页等终端用户实际回答；不绕过验证码或反爬，也不静默回退 API。 |
| 厂商账单导入与对账 | **不在范围**。当前金额是实际 usage + 管理员价格规则的估算。 |
| 多节点队列、高可用 | **不在范围**。当前为单节点 FastAPI + SQLite。 |
| 自动向客户发送报告 | **不在范围**。仅人工登记发送记录。 |
| 旧 v1 测试数据回迁 | **不在范围**。当前使用干净 v2 schema；旧测试数据已获准删除。 |

## 5. 主要验收入口

- `pytest`：后端服务、状态机、权限、预算、调度、保留、导出、报告和 Action 专项。
- `tests/browser_smoke.py`：八条工作流、报告 PDF、viewer/reviewer、移动导航和证据详情。
- `tests/browser_governance.py`：结构化价格、软/硬预算、调度 blocked/恢复、告警历史、保留执行、手工工时、键盘 tabs 和移动溢出。
- `tests/stress_simulated.py`：仅 DemoProvider 的 2700 次模拟压力验收，不访问外部网络。
- `scripts/geopulse_ctl.py golden-eval`：小型离线回归集，不代表生产 LLM 准确率。
