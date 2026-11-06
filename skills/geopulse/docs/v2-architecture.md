# GeoPulse v2 架构

## 1. 目标与边界

GeoPulse v2 是单节点、多客户项目的 GEO 交付系统，重点是可复现测量、证据审计、严格比较和人工审批，而不是抓取消费者产品界面或自动承诺优化效果。

保留以下部署约束：

- FastAPI + SQLite + 有界后台 worker + 调度器。
- 原生零构建 ES-module 前端，本地 ECharts。
- Playwright 只用于 PDF 渲染和浏览器验收。
- 不依赖 Redis、Celery、前端框架或微服务。
- 单节点不是高可用集群；跨项目隔离由应用层授权、作用域查询和数据库约束共同保证。

## 2. 请求与执行结构

```text
Browser / API client
        │ HTTPS（生产由反向代理终止）
        ▼
FastAPI ──────────────── 静态 frontend/
  │ auth + CSRF + project_context
  │ project-scoped REST
  ├───────────────┐
  ▼               ▼
SQLite           reporting → 自包含 HTML → Chrome PDF
  │ WAL / FK / busy timeout
  │ persistent answer queue
  ▼
Worker threads（默认 4）
  │ per-engine slot + rate limit
  ▼
Provider API
  ├─ Demo（本地，无网络）
  ├─ OpenAI-compatible Chat（memory）
  └─ Kimi Search Basic + Chat（search）

Scheduler → 到期 Wave → 幂等创建 Run → 同一个 SQLite 队列
```

`run_test_server.py` 必须显式接收临时 DB 和 secret store。浏览器 smoke 使用动态空闲端口，只终止自己创建的子进程。

## 3. 核心领域对象

| 对象 | 责任 | 不变量 |
|---|---|---|
| Client / Project | 客户与项目边界 | 业务行保存 `client_id + project_id` |
| User / Membership | 登录与项目角色 | 非全局管理员必须有项目 membership |
| EngineConfig | Provider、模型、口径、限流、成本规则 | DB 不保存明文 key |
| BrandEntity | 主品牌、竞品、候选与消歧卡 | 版本不可变，confirmed 才进有效指标 |
| PromptSet / PromptItem | 自然问法、canonical intent、分层与适用性 | 冻结后只能复制新版本 |
| Wave | 一次业务测量及完整冻结协议 | 正式 Run 由管理员指定 |
| Run | Wave 下的执行尝试 | `(wave_id, attempt_no)` 唯一 |
| Answer | 一次 prompt×engine×round 原始回答 | 原文不覆盖；样本键唯一 |
| CallAttempt | answer/judge/search 调用、usage、成本与错误 | 每次 attempt 独立追加 |
| Observation | 某实体在某回答中的当前/历史判定 | revision 追加，不改原文 |
| Citation | Provider 实际返回 URL 与实体关联 | 不伪造 URL；按 answer+URL+hash 去重 |
| Opportunity / Action | 候选缺口与七步交付 | 适用性审批后才评分/创建 Action |
| Report / ReportEvent | 不可变数据快照与审批记录 | 展示状态与数据快照分离 |
| AuditEvent | 管理操作留痕 | 写入前递归脱敏 |

原始回答、observation、report data snapshot 都是审计资产，默认不自动删除。

## 4. 协议冻结与比较

创建 Wave 时保存：

- prompt set ID/hash、prompt item IDs 和 canonical intent 分层权重；
- 实体 IDs、实体版本 hash、竞品池 hash；
- 引擎 ID/name/kind/model、memory/search、provider_api；
- repeats、temperature、中性 system prompt、max tokens；
- language、market、judge version、有效样本定义；
- 统计阈值、安全重试上限和是否启用全量 Judge。

严格比较校验完整协议，并同时检查：

1. 两次正式 Run 的 intent×engine pair-key 完整度；
2. 两次测量的有效样本率；
3. 当前 Wave 冻结的最低完整度阈值（默认 90%）。

供应商返回模型版本变化时，即使协议兼容，也只标为探索性比较。变化只描述共时样本，不自动归因为 GEO Action。

## 5. 队列、恢复与重试

Answer 行本身就是持久队列，状态为 `queued / running / judging / succeeded / failed / cancelled`。

- `_claim_answer()` 在 `BEGIN IMMEDIATE` 中原子领取一个样本。
- 不同引擎可并行；同一引擎通过锁串行，并执行 requests/second 限流。
- 原文成功写入后，恢复只重跑判定，不重复 Provider 请求。
- 没有剩余活动样本的 Run 在恢复时正确收尾。
- 仅 `retryable=True` 且 `outcome_unknown=False` 的错误自动安全重试。
- 超时等结果不明错误保持 failed，必须管理员明确重试。
- Provider 返回后若已请求取消，保留原文但样本标 cancelled，不进入有效指标。
- 无法保证厂商侧绝不重复计费，因此 UI 和文档要求人工确认结果不明重试。

SQLite 单写者决定了这是有界单节点队列。不要把多个独立 Uvicorn 进程当作无协调的分布式 worker 扩展方案。

## 6. Judge 与证据

生产回答默认全量结构化 Judge。Judge 必须返回每个输入实体的：

- `entity_status`：confirmed / ambiguous / wrong_entity / unknown；
- `mentioned`、`depth`、`sentiment`、`top_choice`；
- 原文逐字 `evidence`；
- 只能来自 Provider 返回白名单的 `citation_urls`；
- 开放候选实体及其证据。

证据不在原文时，系统尝试确定性回查并标为待复核；缺失实体不会伪装成 confirmed absence。负面推荐被降级，Judge 失败显式记录 rules fallback。Demo 始终使用明确标记的 demo-rules。

## 7. Provider 口径

### OpenAI-compatible memory

普通 Chat Completions。`finish_reason=length` 即使已有部分文本也标为截断失败；reasoning-only 内容不作为正式回答。

### Kimi Search + Chat

明确命名的 Provider API 检索增强管线：

1. `POST /v1/tools/search`，请求 `{"text_query": prompt}`；
2. 读取 `search_results[{title,url,text}]` 并去重 URL；
3. 单独调用 Chat completion；
4. 分开记录 Search/Chat operation 和 usage。

Search 失败保留错误前缀；Chat 失败仍保留已成功的 Search operation。Search 无结果、无 URL 或失败时绝不回退 memory。

这些结果不得标为 Kimi App、ChatGPT web 或其他消费端观察。

## 8. 报告与导出

客户版和内部版来自同一个不可变 data snapshot。创建时保存版本、内容 SHA-256 和 draft 状态；审批事件单独追加。导出时用当前审批状态渲染展示外壳，不重写数据快照。

- 客户版隐藏成本、内部原始样本和内部错误细节。
- 内部版包含原文、Judge、失败、成本和 revision。
- 无正式 Run/无有效样本可保存待处理草稿，但发布闸门阻止审批。
- 审批顺序：draft → data_checked → strategy_reviewed → client_approved → sent。
- “sent”只登记接收人/方式/时间，不自动外发。
- 客户 PDF 必须完成 client_approved。

## 9. 前端安全与可访问性

- 动态文本使用 `document.createTextNode`，不拼接不可信 HTML。
- 外链只允许 HTTP(S)，新窗口带 `noopener noreferrer`。
- API 401 统一回到登录，Cookie 写操作携带 CSRF。
- drawer 有焦点陷阱、Escape 关闭和焦点恢复。
- 移动导航有遮罩、关闭状态同步、背景 inert 和 Escape。
- 可见 focus、reduced motion、ARIA progress/tab/dialog/live toast。
- 表格自身可滚动，页面不能横向溢出；空、错误、加载和无权限都有下一步。

## 10. 相关文档

- [指标定义](metrics.md)
- [部署、备份与恢复](operations.md)
- [变更与验证记录](changelog.md)
