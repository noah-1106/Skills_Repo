# Changelog

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

- 未执行真实 DeepSeek/Kimi 外部账号 smoke；目前通过的是协议 mock，不是 live 厂商验收。
- 黄金集是人工编写的小型离线回归集，不能据此宣称生产 LLM Judge 准确率。
- 单节点 SQLite 不提供多节点高可用；RPO 24h/RTO 4h 是内部开发基线，不是客户 SLA。
- 浏览器 smoke 是关键路径，不穷尽所有筛选组合、异常状态和全部管理交互。
