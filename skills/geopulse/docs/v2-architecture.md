# GeoPulse v2.5 架构

## 1. 目标与边界

GeoPulse v2.5 是单节点、多客户项目的 GEO 交付系统，重点是可复现测量、证据审计、严格比较和人工审批，而不是自动承诺优化效果。Provider API、人工 Consumer Web 与授权浏览器 Consumer Web 是独立采集口径。v2.4 以 Action 作为 Intervention cohort，将版本化 Brief、Content Asset、Channel Publication、多轮复测和客户决策串成一条证据链；v2.5 在此基础上增加跑前准备单、只追加判定的 JudgeBatch、统一交付质量与只读业务 handoff。同期变化仍不作单资产或策略因果归因。首批授权浏览器 Driver 为 DeepSeek Web 和 Kimi Web；两者已通过本地模拟页面的真实 Chrome 合同验收，但真实平台 live 尚未校准。ChatGPT、豆包、Gemini、Consumer App、验证码绕过、反检测伪装和大规模爬取不在本轮范围。

保留以下部署约束：

- FastAPI + SQLite + 有界后台 worker + 调度器。
- 原生零构建 ES-module 前端，本地 ECharts。
- Playwright 用于 PDF 渲染、浏览器验收和授权 Consumer Web 采集；sync API 只运行在 BrowserWorker 专用线程，不进入 FastAPI event loop。
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
  ├─ Kimi Search Basic + Chat（search）
  └─ DeepSeek Search + Chat（search）

Manual Web Run → awaiting_collection → 人工草稿 + SQLite 证据 BLOB
               → 不可变提交 → 独立 Judge → 同一 Observation / Report 链

Browser Web Run → awaiting_collection / web_collections.browser_phase
                → BrowserWorker（单任务串行，lease + heartbeat + profile lock）
                → DeepSeekWebDriver 或 KimiWebDriver（独立 selectors）
                → 正文 + browser_page 引用 + 回答区域截图/HTML
                → 同事务不可变提交 → 独立 Judge → 同一 Observation / Report 链

Scheduler → 到期 Provider Wave → 幂等创建 Run → 同一个 SQLite 队列
           Consumer Web Wave 禁止自动调度

Existing Run / Answer → JudgeBatch → judge_batch_items → 仅 Judge Provider 调用
                     → 追加 Observation revision；answer/search 调用为 0
```

`run_test_server.py` 必须显式接收临时 DB 和 secret store。浏览器 smoke 使用动态空闲端口，只终止自己创建的子进程。

## 3. 核心领域对象

| 对象 | 责任 | 不变量 |
|---|---|---|
| Client / Project | 客户与项目边界 | 业务行保存 `client_id + project_id` |
| User / Membership | 登录与项目角色 | 非全局管理员必须有项目 membership |
| EngineConfig | Provider 或 Consumer Web 目标、口径、能力、执行默认值、限流、成本规则 | DB 不保存明文 key；网页目标不保存账号或秘密 |
| BrowserSession | 本机授权会话的非秘密元数据与 pending/active/expired/revoked 生命周期 | 随机 profile reference 不公开；Cookie/localStorage/密码/storage state 不入库 |
| BrandEntity | 主品牌、竞品、候选与消歧卡 | 版本不可变，confirmed 才进有效指标 |
| PromptSet / PromptItem | 自然问法、canonical intent、分层与适用性 | 冻结后只能复制新版本 |
| Wave | 一次业务测量及完整冻结协议 | 正式 Run 由管理员指定 |
| Run | Wave 下的执行尝试 | `(wave_id, attempt_no)` 唯一 |
| Answer | 一次 prompt×engine×round 原始回答 | 原文不覆盖；样本键唯一 |
| CallAttempt | answer/judge/search 调用、allowlisted 请求参数、响应元数据、usage、成本与错误 | 每次 attempt 独立追加；不记录 API Key 或推理正文 |
| Observation | 某实体在某回答中的当前/历史判定 | revision 追加，不改原文 |
| JudgeBatch / JudgeBatchItem | 对已有 Run 的全部可补判或选中 Answer 只执行 Judge | 不是新 Wave/Run；answer/search=0；保存冻结 Judge 配置、预算和逐项状态；只追加 Observation revision |
| Citation | Provider 返回、人工记录或浏览器提取的页面 URL | `provider_returned/manual_page/browser_page` 分离；不伪造 URL；按 answer+URL+hash 去重 |
| WebCollection | 采集方法、草稿/自动事实、浏览器 phase、实际页面、上下文、观察时间和提交事实 | 正式提交不可覆盖；自动任务禁止人工改录；失败不成为零提及 |
| AnswerAttachment | 截图/raw HTML/text 的 SQLite BLOB、hash、大小与 tombstone | 单文件 10MB、每 Answer 12 个；HTML 不内联执行 |
| Opportunity / Action | 候选缺口与七步 Intervention cohort | 适用性审批后才评分/创建 Action；已结束 cohort 不重开 |
| ContentBrief | 目标问题、信息增量、假设、预期观察、渠道、成功标准和事实主张 | `(action_id,version)` 唯一；审批版本不可覆盖；无证据主张显式 pending |
| ActionAsset | 内容身份、类型、版本、事实 refs 和适用/不适用边界 | 与 Brief 关联；批准后通过 `supersedes_asset_id` 创建新版本 |
| AssetPublication | 某 Asset 的真实渠道、媒体、URL、含时区时间、成本/币种和商业关系 | 不可变渠道事实；成本未知为 NULL；首条才投影旧 Action 发布字段 |
| ActionRemeasurementRound | D7/D14/D28 节点、固定 baseline/target Run、完整 comparison/hash 和证据 refs | 每轮独立目标 Wave；评估不可覆盖；只有 cohort 观察，没有 per-asset delta |
| ExternalEvent / Schedule | 共时事件与 Provider 执行调度 | 可关联 Action/Asset/Publication/Round；Consumer Web round 只提醒，不创建 schedule |
| Report / ReportEvent | 不可变数据快照与审批记录 | 展示状态与数据快照分离；v2 快照含客户决策摘要 |
| AuditEvent | 管理操作留痕 | 写入前递归脱敏 |

原始回答、observation、report data snapshot 都是审计资产，默认不自动删除。

## 4. 协议冻结与比较

创建 Wave 时保存：

- prompt set ID/hash、prompt item IDs 和 canonical intent 分层权重；
- 实体 IDs、实体版本 hash、竞品池 hash；
- 引擎 ID/name/kind/model、memory/search、provider_api 或 consumer_web；
- repeats，以及按回答引擎 ID 冻结的 `answer_execution` / `judge_execution` 有效参数；显式 null 与 omitted 在创建时解析完成；
- language、market、judge version、有效样本定义；
- Consumer Web 的 `collection_protocol`：`collection_method=manual|browser_assisted`、`protocol_version`、可选 `browser_driver`、产品入口、平台、surface、页面模式、联网/深度开关、会话、登录/账号类型、地区/语言、上下文清理和追问策略；自动首版仅支持 `browser-web-v1 + desktop_web + logged_in + new + none`；
- 同引擎 Judge 或独立 Judge 的 `judge_mode`、公开 `judge_signature` 与内部执行快照；独立 Judge 可服务普通 Provider 或人工 Web，人工回答/Search 调用为 0；
- 统计阈值、安全重试上限和是否启用全量 Judge。

参数优先级为：Wave 按引擎 answer/Judge 覆盖 → 旧 Wave 全局兼容输入 → 引擎 answer/Judge/health 默认值 → 内建兼容默认值。显式 null 是不发送，不等于继承。新回答测量的内建 max_tokens 为 65536，Judge 为 1800，均可由管理员或 Agent 通过引擎配置/Wave override 修改；应用不设统一最高值，已声明的 `max_output_tokens` 继续逐引擎校验。旧协议缺失参数时仍按原 700/1800 回退，不重写历史口径。健康检查不继承 answer/Judge；其内建 temperature/max_tokens 均为 null，即未显式配置时使用厂商默认值。已知 `max_output_tokens`、temperature 支持和允许枚举在冻结/健康检查前校验；未知能力保持 unknown，不按模型名猜测。Kimi Chat 将有效 max_tokens 映射为厂商当前 `max_completion_tokens` 字段，台账仍保存统一参数名；DeepSeek 和普通 OpenAI-compatible 保持 `max_tokens`。编辑引擎不会改写旧 Wave。

严格比较先把旧 top-level 参数和新 per-engine map 归一化为有效执行协议，再校验完整协议，并同时检查：

1. 两次正式 Run 的 intent×engine pair-key 完整度；
2. 两次测量的有效样本率；
3. 当前 Wave 冻结的最低完整度阈值（默认 90%）；
4. 补判后的 effective Judge signature、覆盖率和活跃 JudgeBatch。只补一边、覆盖不完整、配置不一致或批次仍在执行时，不输出严格 delta。

供应商返回模型版本变化时，即使协议兼容，也只标为探索性比较。API/Web 或不同 surface/session 上下文标为 `cross_surface`，只返回各自摘要，`delta=null`、`transitions=[]`，不生成严格 pp 或迁移；product URL、platform、collection method 和 browser Driver 也纳入跨口径判断。变化只描述共时样本，不自动归因为 GEO Action。

## 5. 队列、恢复与重试

Answer 行本身就是持久队列，Provider 状态为 `queued / running / judging / succeeded / failed / cancelled`；Consumer Web 以 `awaiting_collection` 等待人工或浏览器提交。Provider worker 只领取 Provider 任务和已提交的 Consumer Web Judge 任务，不领取空白采集任务。浏览器任务由独立 BrowserWorker 领取，采集期间 Answer 不进入 Provider `running`，避免恢复器误判。

- `_claim_answer()` 在 `BEGIN IMMEDIATE` 中原子领取一个样本。
- 不同引擎可并行；同一引擎通过锁串行，并执行 requests/second 限流。
- 原文成功写入后，恢复只重跑判定，不重复 Provider 请求。
- 没有剩余活动样本的 Run 在恢复时正确收尾。
- 仅 `retryable=True` 且 `outcome_unknown=False` 的错误自动安全重试。
- JudgeBatch 由同一 Worker 在没有 Answer 工作时原子领取 item。完成、取消和失败使用独立的 `judge-batch:{id}` 预算预留，不绑定原 Run 的预留。
- 进程恢复时，未开始的补判 item 可继续；`running` item 可能已到达厂商，标为 `failed + interrupted_unknown + outcome_unknown=1`，绝不自动重放。重试 API 只接受结果明确的失败项。
- 补判取消保留已经发生的调用台账；取消时在途返回不会静默追加为正式 Observation。已完成的 revision 不回滚。
- 超时等结果不明错误保持 failed，必须管理员明确重试。
- Provider 返回后若已请求取消，保留原文但样本标 cancelled，不进入有效指标。
- 无法保证厂商侧绝不重复计费，因此 UI 和文档要求人工确认结果不明重试。

BrowserWorker 首版全局串行，使用数据库 lease/heartbeat 和本机 `fcntl.flock` profile 锁。`_claim()` 在 `BEGIN IMMEDIATE` 事务中排除未过期 lease，并以带原阶段和 lease 条件的比较并交换更新原子认领，同时进入 `preparing`；第二个 Worker 不能覆盖 owner 或重复增加 attempt。`browser_phase` 为 `queued / session_check / preparing / submitting / waiting / extracting / uploading / awaiting_user / paused_unknown / completed / failed`。点击发送前保存 `submitting + browser_send_started_at`；发送后保存 `prompt_submitted_at + conversation_url`。只有确认未进入发送阶段的过期 lease 才自动重排；发送中或发送后崩溃进入 `paused_unknown`，恢复只能打开原 conversation URL，不得再次调用 `submit_prompt`。已发送但无可核对 URL 时只能由管理员登记失败。

登录失效或验证码进入 `awaiting_user`，session 转为 expired 并暂停后续任务；用户在可见浏览器中处理后，admin 重新验证再恢复。Run cancel 在下一浏览器动作前生效。提交前失败才允许明确重采；已有 raw_text 的提交后 Judge 失败只回到 judging，保留原文、raw hash 和全部证据。

浏览器 profile 默认在 `backend/browser_profiles/`，目录 0700、锁文件 0600，不声称加密。项目导出排除 session 表、profile reference、lease owner 和内部 session ID；数据库备份不包含外部 profile，撤销后由 worker 清理目录。

SQLite 单写者决定了这是有界单节点队列。不要把多个独立 Uvicorn 进程当作无协调的分布式 worker 扩展方案。

## 6. Judge 与证据

生产回答默认全量结构化 Judge。Judge 必须返回每个输入实体的：

- `entity_status`：confirmed / ambiguous / wrong_entity / unknown；
- `mentioned`、`depth`、`sentiment`、`top_choice`；
- 原文逐字 `evidence`；
- 只能来自 Provider 返回白名单的 `citation_urls`；
- 开放候选实体及其证据。

证据不在原文时，系统尝试确定性回查并标为待复核；缺失实体不会伪装成 confirmed absence。负面推荐被降级，Judge 失败显式记录 rules fallback。所有非 Demo 的 rules-fallback 或 llm-judge-evidence-fallback 推荐都必须 `review_status=pending` 并写明 `review_reason`，推荐计数标为 provisional；逐字证据仍不自动证明语义支持推荐，必要时应由人工 revision 修正。Demo 始终使用明确标记的 demo-rules。

**JudgeBatch 只补判定，不重新采集。** admin 可对已有 Run 的全部可补判 Answer 或选中 Answer 创建批次，冻结独立 Judge 引擎、有效执行参数、版本和调用/费用预估。真实 Judge 创建和明确失败重试都要求在各自执行前单独确认；预估 answer/search 永远为 0。只有 raw 存在、SHA-256 可验证且采集证据完整的有效 Answer 才能补判；raw purged、hash 不符、截断/无效样本和未提交 Consumer Web 样本返回逐题排除原因。

Worker 复用 engine slot、限流和调用台账，实际模型、usage、batch/item ID 与 Answer raw hash 写入判定元数据。每个实体按当前最大 revision+1 追加，不改 Answer、原 Observation、Citation 或 Run。全部有效 Answer 由同一 Judge 配置成功补判后形成 `consistent` effective lineage；只补部分或使用不同配置为 `mixed`。活跃或 mixed 批次阻断相应报告审批和严格比较。补判不自动改写旧报告，也不证明语义假阳性已被字符串校验全部解决。

人工 Web 默认选择同项目、已启用的独立 Judge。普通 Provider 也可显式选择独立 Judge；未选择时保留各回答引擎兼任 Judge。Provider 独立 Judge 不能同时是本次回答引擎，真实回答与 Demo Judge 不混用。Judge 使用自己的冻结参数和 engine_config_id；Search 型 Judge 只调用结构化 Chat，不执行 Search。Demo Judge 只用于明确标记的离线测试；真实 Judge 的调用、usage、成本和 secret reference 与回答目标分离。显式关闭 Judge 时使用 rules fallback；真实 Provider Run 创建必须由 admin 显式 `confirm_judge_disabled=true` 并审计，Wave 草稿仍可保存。该确认只允许执行，不能绕过补判、人工复核和报告质量闸门。

Consumer Web 提交要求非空正文、相同 origin、与冻结协议一致的实际上下文、带 offset 且与 IANA 时区一致的时间，以及至少一张通过 bytes/hash/size/magic 校验的截图。人工引用只记录用户实际看到的 URL、标题和卡片文本；浏览器引用只从当前回答区域提取实际 HTTP(S) URL。两者都不自动访问引用或宣称正文支持关系已核验。自动采集在一个显式事务内上传截图/HTML并提交正文、raw hash、引用和上下文，任一步失败全部回滚。附件下载仅 admin/analyst，reviewer/viewer 与跨项目 ID 均拒绝。

### 跑前准备单、交付质量与只读 handoff

`wave_readiness()` 复用冻结协议和费用预估，汇总引擎启用状态、Judge 配置/有效参数、历史健康、截断风险和启发式耗时。打开准备单不会发起健康检查或其他外部调用。耗时要求对应 operation 至少 3 条成功历史记录，按逐引擎串行和中位数/P90 估算；不足、Consumer Web 均为未知，Demo 不用于推算真实模型时长。上下文风险只来自声明能力和历史截断，不建立题型到 token 的固定映射。

`run_quality()` 从 Run、最新 Observation、JudgeBatch 和正式 Run 事实派生执行状态、fallback/pending/provisional/human revision、配置模型/实际返回模型、补判 lineage、`delivery_readiness` 和唯一下一步，不另建手工项目状态机。现有指标公式不因 pending 而静默改写；未复核推荐会阻断批准。小样本可 `ready_with_limitations`，不一律判失败。

`GET /api/projects/{project}/runs/{run}/handoff` 是面向内部成员及执行 agent 的只读投影，返回稳定 project/wave/run/report/opportunity ID、质量摘要、readiness、next_action、报告审批和手工工时状态。机会发现通过 audit 区分未检查与已检查为 0；旧报告仍有质量 gates 时下一步是创建新报告版本，不是批准旧快照。GeoPulse 不写外部业务孪生、不自动外发报告、不自动记录工时；外部同步方须自行记录 synced_at。

## 7. Provider 口径

### OpenAI-compatible memory

普通 Chat Completions。`finish_reason=length` 即使已有部分文本也标为截断失败；reasoning-only 内容不作为正式回答。起始完整 `<think>…</think>` 只分离可见回答，未闭合或空可见后缀仍失败，推理文本不进入原文或调用台账。请求按有效配置发送或省略 temperature/max_tokens/system message；不支持 JSON response_format 时仍要求 Judge 输出 JSON，但不发送该能力字段。

### Kimi Search + Chat

明确命名的 Provider API 检索增强管线：

1. `POST /v1/tools/search`，请求 `{"text_query": prompt}`；
2. 读取 `search_results[{title,url,text}]` 并去重 URL；
3. 单独调用 Chat completion；
4. 分开记录 Search/Chat operation 和 usage。

Search 失败保留错误前缀；Chat 失败仍保留已成功的 Search operation。Search 无结果、无 URL 或失败时绝不回退 memory。

这些结果不得标为 Kimi App、ChatGPT web 或其他消费端观察。

### DeepSeek Search + Chat

使用官方 [Search 协议](https://api-docs.deepseek.com/guides/search/)：`POST {base_url}/tools/search`，base URL 按现有约定包含 `/v1`，请求 `{query,count:10,need_content:false}`。解析 `results[]` 的 title/url/snippet/summary/site_name/date，校验 HTTP(S) URL 并去重，再单独调用 Chat。query 超过 128 个 Unicode 字符时确定性截断并记录 `query_truncated`；完整原始 Prompt 仍进入 Chat。本轮不实现 Fetch。

Search HTTP 失败、空结果或没有可用资料不会调用 Chat 或降级 memory；失败/空结果操作记录 `search_calls=0,billable=false`。已成功 Search 后 Chat 失败仍保留 Search usage 和成本。Search/Chat 的 operation、usage、成本、延迟、request ID 和实际参数分别记录，价格仍由管理员规则提供，不硬编码厂商价格。

这些结果不得标为 DeepSeek Web/App 或其他消费端观察。

### Consumer Web

`manual_web + consumer_web` 是内部兼容目标类型，不是 Provider adapter，`build_provider` 会明确拒绝。UI 不把该内部 kind 当作用户术语。Web Wave 只能选择一个目标，不能和 Provider 或其他 Web 目标混合，也不能创建自动调度。每个 Wave 通过冻结 `collection_method` 明确人工或授权浏览器，两者不能静默互换。

**人工采集**：Run 创建待采集任务，不自动打开网页。草稿可暂不完整；正式提交原子写入不可变原文、raw-text SHA-256、`manual_page` 引用和采集事实，再进入独立 Judge。验证码、登录失效、空正文、截断、错误页和流式中断必须登记失败，管理员确认后才能重采。

**授权浏览器采集**：`deepseek_web.py` 与 `kimi_web.py` 分别维护版本化 selectors、登录/验证码识别、新聊天、联网/深度开关、发送、流式完成和回答提取，不用一套通用选择器伪装兼容。无法确认冻结模式时在发送前失败，不降级 memory。自动 Run 必须带 `confirm_browser=true` 并找到同目标/Driver 的 active session。采集器只访问对应 HTTPS origin allowlist，不自动打开提取到的引用 URL；正文保持页面可见文本，不总结或改写。

自动任务返回 `BrowserCapture(payload, screenshot, html)`，不实现 `BaseProvider`，不产生 Provider answer/search usage，网页订阅费不进入 API token 台账。截图和 HTML 只截取当前回答区域，单文件非空且不超过 10MB，与 `browser_page` 引用一起提交。真实 selectors 尚需各平台授权账号 live 校准，离线 mock 通过不能写成真实平台已接入。

截图与原始证据保存在同一个 SQLite 数据库，备份/恢复与项目导出保持一致；普通 Answer JSON 只返回元数据，不返回 BLOB。项目导出合同为 `geopulse-project-v2`，附件 bytes 使用 base64 编码，浏览器 profile 和 session 秘密不进入导出。

## 8. Intervention 证据链与多轮复测

```text
Opportunity baseline Answer / Observation / Citation refs
  → Action（Intervention cohort）
  → versioned Brief + Content Assets
  → immutable Channel Publications + ExternalEvents
  → D7 / D14 / D28 target Waves
  → frozen cohort assessment + evidence timeline
  → schema-v2 decision summary + one next recommendation
```

Brief/Asset 的 evidence ref 只保存 Answer、Observation revision、Citation ID 与规范 hash，不复制原始回答。服务端验证同 client/project、Opportunity baseline `answer_ids`、父子关系和 hash；客户端传回的 `available_now` 不作为事实，读取时重新标注。原文按 retention 清理后，冻结 ref 不改写，只标为 `raw_purged`。Citation URL 只证明来源出现，不证明正文支持主张。

Action 审批冻结最新 Brief 和草稿 Assets。后续变更创建新版本；已结束的 `verified/not_effective/stopped` cohort 不重开，后续投入另建 Action。Publication 与 Asset 分离，首条发布仅兼容更新旧 `actions.published_*`，后续发布不覆盖首条摘要。旧字段不再是新代码的事实来源。

创建复测轮次时固定 Opportunity baseline official Run；评估时固定 target 当时的 official Run，并保存完整 comparison、comparison hash、成功标准、理由及两个 Run 的证据 refs。之后更换 official Run 不改写已冻结评估。状态区分 `pending_measurement / measured / insufficient_evidence / incomparable / legacy_unavailable`，`attribution_status` 始终为 `not_attributable`。小样本或完整度不足不能输出改善；协议不匹配为不可比。

Provider round 复用 Scheduler，只创建 Run，不自动指定 official Run 或评估。Consumer Web round 使用 `remeasurement-round:{id}` 去重提醒，不创建 Schedule/Run、不调用 BrowserWorker；仍需显式 Run、`confirm_browser` 和 active session。通用 schedule API 拒绝携带 `action_id` 的旁路，复测必须从 rounds API 创建。

Timeline 由 Brief/Asset 审批、Publication、ExternalEvent 和 Round 实时构建，不另建重复 timeline 表。报告创建时只纳入与所选 Wave 或其 rounds 相关的 Interventions。

## 9. 报告与导出

客户版和内部版来自同一个不可变 data snapshot。创建时保存版本、内容 SHA-256 和 draft 状态；审批事件单独追加。导出时用当前审批状态渲染展示外壳，不重写数据快照。新快照使用 `schema_version=2` 和独立 `report_v2.html`，首屏回答“哪些关键问题不推荐我们、改了什么/发到哪里、之后观察到什么及证据强度”，并给唯一下一轮建议；旧 v1 快照继续使用未修改的 `report.html`，JSON/HTML/hash 不变。

- 客户版和 reviewer/viewer 快照隐藏成本、内部原始样本、内部 Intervention evidence refs、Opportunity 原始 evidence/score JSON 和内部错误细节，并递归移除 per-engine execution map 中的 system prompt。
- 内部版包含原文、Judge、失败、成本和 revision。
- 新快照同时冻结交付质量、JudgeBatch 覆盖、配置模型/实际返回模型，以及版本化 `metric_appendix`。附录给出公式、分子、分母、聚合单元、冻结权重和限制；配置模型与厂商实际返回模型不同只表示观察到路由，不自动判失败。
- 活跃/混合补判、disabled Judge 未形成完整补判、fallback 推荐和 provisional 推荐均进入发布闸门。旧报告快照不被补判回写；质量恢复后应创建新版本。
- 无正式 Run/无有效样本可保存待处理草稿，但发布闸门阻止审批。
- 审批顺序：draft → data_checked → strategy_reviewed → client_approved → sent。
- “sent”只登记接收人/方式/时间，不自动外发。
- 客户 PDF 必须完成 client_approved。
- Consumer Web 报告快照记录冻结采集方法/Driver、协议、独立 Judge、证据覆盖和内部附件 metadata/hash，不嵌入 BLOB；发布闸门重新校验正文 hash、截图字节和实际上下文。
- 来源分类继续使用项目 `settings.source_domains`。系统管理提供域名→类别表格，hostname 去空白、转小写、去末尾点并做 IDNA/格式校验；类别为官网、百科、UGC、新闻、行业、研报、投诉或其他。保存只影响新写入 Citation 的默认分类，不静默改写历史 Citation 或旧报告。
- 客户报告分别标注“人工 Consumer Web”或“授权浏览器 Consumer Web”，引用统一说明为未自动核验正文支持关系的 Consumer Web 页面引用，不包含账号别名、profile/session 元数据、内部截图、内部原文或内部成本。

## 10. 前端安全与可访问性

- 动态文本使用 `document.createTextNode`，不拼接不可信 HTML。
- 外链只允许 HTTP(S)，新窗口带 `noopener noreferrer`。
- API 401 统一回到登录，Cookie 写操作携带 CSRF。
- drawer 有焦点陷阱、Escape 关闭和焦点恢复。
- 移动导航有遮罩、关闭状态同步、背景 inert 和 Escape。
- 可见 focus、reduced motion、ARIA progress/tab/dialog/live toast。
- 表格自身可滚动，页面不能横向溢出；空、错误、加载和无权限都有下一步。

## 11. 相关文档

- [指标定义](metrics.md)
- [部署、备份与恢复](operations.md)
- [薄业务 CLI](cli.md)
- [变更与验证记录](changelog.md)
