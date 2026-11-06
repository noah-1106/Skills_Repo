# Changelog

## 2.0.1 — 2026-11-07

### 功能闭环

- 项目、Wave 和项目时区每日预算统一接入手工 Run、失败样本重试、调度和健康检查；在途 reservation 防止排队任务绕过额度。
- 软预算超限要求管理员逐次填写理由并审计；硬预算和未知成本在执行前拒绝，调度进入可诊断、可恢复的 `blocked`。
- 成本按业务类型、计费操作和币种汇总真实 usage，单独暴露未知成本；健康检查 Search/Chat 也进入台账。金额明确为手工价格估算，不是厂商账单。
- 调度支持单次、周期、编辑、暂停、恢复、取消、退避与告警；Action 安排复测创建真实 Schedule。
- Action 改善结论必须来自另一轮 Wave 的正式 Run 和严格同口径比较，拒绝用机会来源基线自我复测；支持 verified 和 not_effective。
- 原文保留策略支持预览、确认执行、tombstone 和审计；默认不清理，历史有效样本事实与报告快照不被重写。
- 项目导出统一 UI/CLI 合同并递归清理嵌套 secret reference；恢复校验 manifest、SHA-256、schema、integrity check 后原子替换。
- 新增 [功能对照矩阵](feature-matrix.md)，区分已闭环、人工登记、仅 CLI、外部账号未验证和不在范围内的能力。

### 前端重设计

- 按八条交付任务重建信息层级，首屏优先当前状态、待办和唯一下一步，进阶协议、内部字段和危险操作渐进披露。
- 系统管理重组为引擎与口径、调度与告警、成员与角色、成本与运营、设置与数据治理；结构化价格表单不再要求编辑 JSON。
- 预算确认、硬预算拒绝、告警历史、保留清理、手工工时和调度恢复均提供当前任务内的完整操作路径。
- 小样本以 hits/n 和 Wilson 区间为主，不再放大确定性百分比、SoV 或 pp；空值不再显示为 0%。
- 对比与报告拆分任务视图，报告创建、审批、阻塞项和导出集中；机会与行动按当前阶段组织。
- 统一中文状态、骨架加载、空/错误状态、移动表格语义、抽屉焦点/inert、tabs 键盘/ARIA 和 reduced motion。
- 移动证据采用清单与详情两个导航状态；toast、账户菜单和移动导航避免遮挡主要操作。

### 本机验证

- pytest：61 passed，1 个 Starlette TestClient 依赖弃用提醒；前端全部 ES-module 语法检查通过。
- 两套真实 Chrome 验收通过：八条工作流与只读角色，以及预算、调度、告警、保留、工时、键盘 tabs 和移动治理。
- 已逐张检查 1440、1280、390 截图；覆盖八个页面、移动证据清单/详情、硬预算对话框和 toast 不遮挡主操作。
- 黄金集 12/12 用例通过；该小型回归集各分类 accuracy=1.0，引用合同 TP=2/FP=0/FN=0，不能外推为生产 LLM 准确率。
- 2700 次 DemoProvider 调用全部成功，8100 observations，无重复样本键/revision，恢复重复 Provider 调用为 0，外部网络调用为 0。
- 本轮压力执行 37.58 秒，临时数据库 4,796,416 bytes；完整指标读 API 本机 P95 195.11 ms。
- ECharts vendor SHA-256 校验通过，`pip-audit` 未发现已知漏洞。

### 验证边界

- DeepSeek 已完成一次真实 Provider API smoke，但完整真实 Wave/Run/Judge 未验证；Kimi live 未执行，仍只有协议 mock。
- 本轮自动化和浏览器验收不执行真实付费调用；Consumer Web/App 采集、厂商账单对账、多节点高可用和自动外发报告不在范围内。

## 2.0.0 — 2026-11-06

### 数据与安全

- 使用干净 v2 SQLite schema，旧测试回答不回迁；引擎配置与独立 secret store 保留。
- 所有业务查询采用项目授权与 `client_id + project_id` 作用域。
- 新增 Cookie/Bearer 登录、PBKDF2、CSRF、项目角色、审计脱敏和 0600 密钥存储。
- reviewer/viewer 隐藏原文、内部成本与内部报告；项目导出排除密钥。

### 问题、实体与测量

- 问题集支持 scaffold、JSON/CSV、去重、逐条审核、冻结、复制、diff 和导出。
- 实体支持消歧卡、别名冲突、不可变版本、候选审核与竞品池 diff。
- Wave 冻结完整协议；Run 为独立尝试；正式 Run 由管理员指定。
- SQLite 持久队列、有界 worker、每引擎限流、取消、恢复和安全重试。
- 原始回答不可变，observation revision 追加；无效样本不进入零提及分母。

### 判定、指标与比较

- 生产默认全量结构化 Judge，支持实体消歧、证据逐字回查、引用白名单和开放候选。
- 实现 Coverage、Hit Rate、推荐覆盖、有效推荐、Top Choice、北极星、SoV、引用率与质量指标。
- 修复主竞品 SoV 分母/权重不一致，统一按 intent×engine 和冻结权重聚合。
- 严格比较同时检查协议、pair-key 完整度与有效样本率；模型换版只作探索性比较。
- 机会适用性由管理员确认，评分使用 Wave 冻结权重；Action 需要真实发布时间与 HTTP(S) URL。

### Provider

- Demo 与真实 API 始终分离。
- OpenAI-compatible 截断和 reasoning-only 响应不会被当成有效回答。
- Kimi Search Basic `POST /v1/tools/search` 使用 `text_query`，随后单独调用 Chat。
- Search/Chat operation 与 usage 分开保存；Search 失败绝不降级 memory。
- 非 demo 健康检查必须显式确认真实外部调用。

### 报告与前端

- 八个中文工作流全部重建，持续显示冻结口径带。
- 报告快照不可变，发布闸门与三级审批分离；客户版/内部版 HTML/PDF。
- 报告空样本不诊断，全维度 100% 时不再生成“低覆盖维度”的错误摘要。
- 原生安全 DOM、焦点管理、移动导航遮罩/inert、响应式表格和 reduced motion。
- 双 Wave ECharts、配对迁移、桌面/移动与 viewer/reviewer 浏览器路径。
- 浏览器覆盖人工 revision、候选审核、Action 审批/发布/复测、D14 调度、备份导出、成员 UI 和项目删除确认。

### 工程与文档

- 新增架构、指标、运维、依赖 lock 和 ECharts 来源/许可证/SHA-256 manifest。
- 新增 CI、前端 ESM 检查、依赖审计、vendor 完整性和 secret scanning。
- 新增离线黄金集评估：实体、深度、情感、来源分类与引用合同。
- 新增固定 100 意图 × 3 表述 × 3 引擎 × 3 轮的 2700 次纯模拟压力验收。

### 本机验证

- pytest：36 passed；仅保留 Starlette TestClient 关于 httpx 的依赖弃用提醒。
- 真实 Chrome 八工作流、双 Wave 对比、人工 revision、Action 闭环、D14 调度、备份导出、项目删除、移动导航、viewer/reviewer 与中文 PDF 通过。
- 黄金集 12 个回答用例通过；该小样本各分类 accuracy=1.0，引用合同 TP=2/FP=0/FN=0。
- 2700 次 DemoProvider 调用：2700 成功、8100 observations、无重复样本键/revision、恢复重复调用 0。
- 压力执行 37.57 秒，DB 3,784,704 bytes；完整指标读 API 本机 P95 184.50 ms。
- `pip-audit` 未发现已知漏洞。

### 尚未完成或明确边界

- 外部账号验证边界以 2.0.1 与功能矩阵为准；协议 mock 不等于 live 厂商验收。
- 黄金集是人工编写的小型离线回归集，不能据此宣称生产 LLM Judge 准确率。
- 单节点 SQLite 不提供多节点高可用；RPO 24h/RTO 4h 是内部开发基线，不是客户 SLA。
- 浏览器 smoke 是关键路径，不穷尽所有筛选组合、异常状态和全部管理交互。
