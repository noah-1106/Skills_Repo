# Changelog

## 2.5.0 — 2026-11-10

### 跑前配置校验

- 新增应用 v2.5.0 与 schema v7；001–006 checksum 不变，旧 Wave、Observation、报告 JSON/HTML/hash 不回写。新增服务端测量准备单，在执行前汇总 Judge 方式、冻结参数、回答/Search/Judge 调用数、费用、历史健康、历史耗时和截断风险。
- 历史耗时要求对应操作至少 3 条成功记录，按逐引擎串行和历史中位数/P90 启发式估算；样本不足、Consumer Web 和真实模型无历史时明确显示未知，不承诺固定分钟数，也不建立题型到 token 的写死映射。准备单不会自动执行付费健康检查。
- 真实 Provider Run 关闭 Judge 时，创建 Run 必须由 admin 显式 `confirm_judge_disabled=true` 并留下审计；Wave 草稿仍可保存，该确认不绕过跑后的报告质量闸门。

### Judge-only 补判与质量闸门

- 新增 `judge_batches`、`judge_batch_items` 和可空 `call_attempts.judge_batch_id`。补判关联已有 Run/Answer，支持全量或逐题选择、独立预算、取消、恢复和明确失败重试；answer/search 调用与预估均为 0，不创建新 Wave 或回答 Run。
- 只接受 raw 存在、hash 可验证、采集证据完整的有效 Answer。raw purged、hash 不符、截断、无效或未提交 Consumer Web 样本返回排除原因，不能靠补判变成有效样本或零提及。
- 补判只追加当前最大 Observation revision + 1，保留原文、Answer、旧 revision 和 Citation；`judge_meta` 记录批次、配置/实际模型和 raw hash。原 Run 的 Judge 调用不伪填 batch ID。
- 进程恢复只继续未开始项；在途项标为 `interrupted_unknown`，不自动重放可能已计费或已返回的真实请求。取消保留外部调用台账，但不把取消时的在途结果静默写成正式判定。只有 `outcome_unknown=0` 的明确失败项可重试。
- 新增派生质量摘要与 effective Judge lineage，统一呈现执行状态、补判覆盖、fallback、pending/provisional、人工 revision、配置/实际模型和交付阻断。全量同配置补判可形成一致口径；部分覆盖、配置混合或活跃批次阻断相应报告审批和严格比较。
- `rules-fallback` 与 `llm-judge-evidence-fallback` 的 recommended 必须 pending，负面推荐继续降级。报告 gate 阻止未复核推荐进入已批准客户结论；小样本仍可带限制交付，不宣称逐字证据校验能解决全部语义假阳性。

### 交付交接、报告与来源管理

- 新增只读 `GET /api/projects/{project}/runs/{run}/handoff`，提供稳定 project/wave/run/report/opportunity ID、质量摘要、readiness、唯一下一步、报告审批和工时状态。机会发现区分“未检查”和“已检查为 0”；旧报告仍有质量阻断时指向创建新版本。
- 测量页把准备单、当前质量和唯一下一步放在首层，补判参数与历史记录渐进披露；机会、报告、工时和 Wave 收尾按钮连接到真实工作流，只读角色不显示无权执行的操作。
- 新报告快照增加质量摘要、effective Judge protocol、JudgeBatch、配置/实际回答与 Judge 模型，以及版本化指标公式、分子、分母、聚合单元、权重和限制附录。客户版继续递归移除 system prompt、内部成本、原始证据和 secret reference。
- 系统管理新增 `projects.settings.source_domains` 表格编辑，支持 hostname/IDNA 规范化和八类来源；只默认影响之后写入的 Citation，不静默重分类历史来源或旧报告。工时只提醒人工登记，不自动计时、写外部业务孪生或外发报告。
- 项目导出包含 JudgeBatch 和逐项状态，沿用递归 secret scrub；嵌套 `secret_ref` 保持既有清空值合同。薄 CLI 新增 `judge-batch list/create/get/cancel/retry` 与 `run handoff`。

### 验证与边界

- 完整 pytest 为 **155 passed，1 warning**，包含 16 条已有回答只补 Judge、48 条新增 Observation revision、raw/hash/Web 排除、预算/权限/取消/恢复、populated v6→v7、导出脱敏、严格比较、报告闸门和完整 handoff。
- 七套真实 Chrome 均通过：八工作流、执行治理、Intervention、人工 Consumer Web、模型执行、授权 Web Collector，以及新的准备单→补判→人工 revision→正式 Run→机会→报告审批→handoff→工时提醒→Wave 收尾。新路径覆盖 1440/768/390、键盘焦点、正确路由和零外部请求。
- Python compile、全部前端 ESM、`git diff --check` 和 ECharts vendor integrity 通过。离线黄金集 12/12，通过实体、深度、情感、来源类型和 citation 合同回归；它不是生产 LLM 准确率证明。
- 本轮自动化只使用 Demo/mock 和本地模拟页面，不执行真实付费 Provider、真实网页登录、自动报告外发或外部业务同步。未自动提交、推送、合并或同步 Skills_Repo。

## 2.4.0 — 2026-11-09

### Intervention 证据闭环

- 新增 schema v6 与应用 v2.4.0，001–005 checksum 不变。以现有 Action 作为 Intervention cohort，新增 `content_briefs`、`action_assets`、`asset_publications`、`action_remeasurement_rounds`，ExternalEvent/Schedule 可关联对应对象，不新建平行 Intervention 或 timeline 表。
- Action 创建时生成默认 Brief/Asset 草稿。Brief 主张必须为该 Opportunity 基线范围内的 Answer/Observation revision/Citation ref，否则显式 `pending`；跨项目、错误父子关系和 hash 不匹配均拒绝。pending 阻止 Brief/Asset/Action 审批，审批版本不可覆盖，修改创建新版本。
- Asset 与 Publication 分离。一个 cohort 可有多个资产，一个资产可登记多个真实渠道 URL、媒体、含时区时间、商业关系和成本；未知成本为 NULL，填写成本必须有币种。Publication 不可变，首条才兼容投影旧 `actions.published_*`；旧单发布/单轮复测 API 保留。
- D7/D14/D28 每轮使用独立 target Wave，创建时固定 baseline official Run，评估时固定 target official Run，保存完整 comparison/hash、成功标准、理由和 Answer/Observation/Citation refs。后续更换 official Run 不改写冻结评估。
- 复测状态区分待测量、已有测量、证据不足、不可比和历史不可用；`attribution_status=not_attributable`。小样本/完整度不足不能输出改善，同期多资产不计算 per-asset delta，已结束 cohort 不重开。
- Provider 调度只创建 Run；Consumer Web 只以 `remeasurement-round:{id}` 去重提醒，不创建 Schedule/Run、不触发 BrowserWorker。通用 schedule API 拒绝带 `action_id` 的复测旁路。
- populated v5→v6 保守回填 legacy Brief/Asset/Publication/Round，保留 Answer/raw hash、旧事件 anchor 和旧报告 JSON/HTML/hash，不伪造 baseline Run 或 comparison；重复迁移不重复回填。

### 工作台、报告与权限

- 新增独立“常见概念”页，按业务、测量证据、优化交付和技术参数提供中英文对照与项目内解释；所有角色可读，不批量改写既有工作流、API 字段或历史报告。
- 新增 Intervention drawer 和 `#/opportunities?tab=actions&action=<id>` 深链。首层呈现当前状态、最新 cohort 观察、非因果边界和一个主操作；Brief、资产、发布、复测和技术时间线分层展开，支持 1440/768/390、焦点闭环、Escape 和当前阶段恢复。
- 报告快照升级为 schema v2，使用独立 `report_v2.html`，首屏回答“哪些关键问题不推荐我们、改了什么/发到哪里、之后观察到什么及证据强度”，并给唯一下一轮建议。旧 v1 快照仍走原模板，JSON/HTML/hash 不变。
- 客户版、reviewer/viewer 不读取内部成本、Publication 备注、原始回答、Brief/Round 内部 evidence refs 或 Opportunity 原始 evidence/score JSON。Intervention 列表、详情、Brief/Asset/Publication/Round、导出和 HTTP 薄 CLI 已接通。
- retention 后冻结 refs/comparison/hash 不变，Answer ref 标 `raw_purged`；新表进入项目导出并沿用递归 secret scrub/checksum。

### 健康检查配置修正

- 空 `health_defaults` 不再注入 `temperature=0/max_tokens=8`，而是省略这两个请求字段并使用厂商默认值，避免截断推理模型或向只允许特定温度的模型发送不兼容参数。answer/Judge/health 继续独立解析，显式 health 配置优先。
- 健康检查省略输出上限时，预估复用引擎的“预估输出 tokens”，不再按 8 tokens 低估；管理界面明确展示不发送语义和参数隔离边界。
- 移除 answer/Judge/Wave override 的 8000 tokens 应用硬上限；新回答默认调整为 65536，Judge 保持 1800，管理员和 Agent 可按模型修改，声明的模型输出上限仍逐引擎校验。旧协议兼容回退和历史 Wave 不变。
- Kimi Chat 使用厂商当前 `max_completion_tokens` 字段，DeepSeek/普通 OpenAI-compatible 保持 `max_tokens`；调用台账继续以统一的 `max_tokens` 名称记录有效预算。

### 验证与边界

- 完整 pytest 为 137 项通过；新增 populated migration、多个资产/渠道、固定 Run/comparison、Consumer Web 提醒、跨项目证据隔离、小样本/不可比、retention、只读角色和大输出预算专项。
- 独立真实 Chrome Intervention 验收通过：pending 阻断、2 个资产、2 条发布、D7/D14/D28、冻结评估、三问报告、HTML/PDF、深链刷新、焦点/Escape、viewer/reviewer、1440/768/390，外部请求为 0。
- 六套真实 Chrome 均通过：八工作流、执行治理、人工 Consumer Web、模型执行/独立 Judge、两个授权 Web Driver，以及 Intervention 证据链。前端 ESM 与 Python compile 通过。
- 离线黄金集 12/12、2700 次 DemoProvider 压力、ECharts vendor 完整性和 `pip-audit` 通过；压力无重复样本/revision、恢复重复 Provider 调用或外部网络调用。新增变更的凭据模式扫描无发现；本机未安装 gitleaks，CI 保留完整仓库扫描。
- 开发库先创建带 manifest 的 v5 一致性备份，再迁移至 v6；两次迁移前备份的 SHA-256 一致，`integrity_check=ok`，外键检查无违规。v2.4 预览已恢复，worker/BrowserWorker 禁用以避免自动外部调用。
- 本轮只使用 Demo/离线夹具，不执行真实付费 Provider 或真实网页调用；DeepSeek Web/Kimi Web 真实平台 live 边界不变。未自动提交、推送或同步 Skills_Repo。

## 2.3.0 — 2026-11-08

### 授权 Consumer Web Collector

- 新增 schema v5 与应用 v2.3.0。保留 `manual_web` 作为 Consumer Web 内部兼容类型，在冻结协议中区分 `collection_method=manual|browser_assisted`、`manual-web-v1|browser-web-v1` 和 `browser_driver`。历史 collection 默认 manual；新增 `browser_page` 引用 origin。
- 首批实现独立的 DeepSeek Web 与 Kimi Web Driver，覆盖登录/验证码识别、新聊天、联网/深度开关核验、发送、流式稳定等待、正文/引用提取、回答区域截图和 outerHTML。ChatGPT、豆包、Gemini 不写空壳 Driver。
- 新增 admin 本机会话 create/list/verify/revoke。持久 Playwright profile 位于受控 0700 目录，Cookie/localStorage/密码/storage state 不进入 SQLite；用户本人在可见浏览器登录和处理验证码，不做绕过或反检测伪装。
- 新增独立 BrowserWorker 串行 lane、数据库 lease/heartbeat 和本机 profile 文件锁。队列认领使用 `BEGIN IMMEDIATE`、未过期 lease 排除和比较并交换更新，认领即进入 `preparing`，防止重复 Worker 覆盖 owner 或重复增加 attempt。自动 Run 必须 `confirm_browser=true` 且存在对应 active session；Provider API、Consumer Web 和后续 Consumer App 口径继续严格分开，scheduler 不自动操作网页。
- 建立发送前后恢复边界：发送前过期任务可重排，发送中/发送后崩溃进入 `paused_unknown`，已发送任务只恢复原 conversation URL，不自动重发；无 URL 只能由管理员登记失败。登录失效和验证码暂停同 session，支持 expired 重新验证后恢复。
- 自动正文、raw hash、截图、HTML、引用和实际上下文在一个事务内提交，再复用独立 Judge、Observation revision、Run、报告和 CLI。修复提交后 Judge retry 清证据/覆盖原文的边界；自动任务禁止人工 draft/upload/submit 改录。
- Run 进度、证据页和测量向导显示当前 prompt、browser phase、心跳、action-required、外部发送确认和恢复操作。薄 CLI 新增 browser-session 与 collection resume，路径参数使用 `--browser-session`。
- 严格比较增加 product URL、platform、collection method 和 Driver；报告分别标注人工/授权浏览器证据。项目导出排除 session/profile/lease，retention 清理 conversation URL 和阶段详情。

### 验证与边界

- 122 项 pytest 通过，覆盖 populated v4→v5 migration、两平台自动提交、双 Worker 排他认领、profile 锁竞争重排、发送后恢复不重复提问、expired 重验、验证码暂停、取消、证据事务回滚、10MB 上限和 post-submit retry 不可变性。
- 五套真实 Chrome 验收通过：八工作流、治理、人工 Web、模型执行，以及新增授权 Collector。新增离线 Collector 同时验证两个独立 Driver、登录、模式、流式回答、引用、截图/HTML、异常、原会话恢复、失败、正式 Run、报告、撤销、四角色和 1440/768/390，无 pageerror 或外部请求。
- **DeepSeek Web 与 Kimi Web 尚未进行真实平台 live 验收**。当前 selectors 和页面流程只通过本地模拟页面合同，不能据此宣称真实平台已接入；每个平台仍需授权账号、可见浏览器、用户登录/验证码和隔离单题的即时确认验收。
- 本轮未执行真实外部网页登录或提问，未自动提交、推送或合并代码。

## 2.2.0 — 2026-11-07

### 模型能力、执行参数与独立 Judge

- 新增 schema v4：引擎可声明上下文/输出能力、temperature 支持/允许值、JSON mode 和推理预算特性，并分别配置 answer/Judge/health 默认参数。重复引擎名称的创建和更新统一返回结构化 409。
- Wave 按回答引擎冻结有效 `answer_execution` / `judge_execution`。省略字段继承引擎或内建默认，显式 null 从请求省略；引擎后续编辑不改写历史 Wave。健康检查不再固定 0/8，严格比较先归一化旧新协议。
- 普通 Provider 支持同引擎或指定独立 Judge。独立 Judge 不能同时是回答引擎，Demo/真实不混用；回答、Judge、Search 的 engine_config_id、usage、成本和预估分别归属。多回答引擎只生成一份独立 Judge 调用序列，Search 不计入 Judge。
- OpenAI-compatible 请求支持显式 null 和 JSON mode 能力。完整起始 `<think>…</think>` 只分离可见回答，推理正文不保存；未闭合、空可见后缀、reasoning-only 和 length 截断继续排除有效样本。

### DeepSeek Search 与 CLI

- 新增 `deepseek_search + provider_api + search`，使用官方 `POST /v1/tools/search` 的 `{query,count,need_content:false}` 与 `results[]`，Search 后单独调用 Chat。长查询确定性截断并保留完整原始 Prompt；本轮不实现 Fetch。
- Search HTTP 失败、空结果和无有效资料不调用 Chat、不降级 memory；失败/空结果显式零计费，成功 Search 后 Chat 失败仍保留 Search 成本。Kimi 空结果同步明确 `search_calls=0,billable=false`。
- CLI 新增 `schema engine|wave|collection-draft` 和 `example engine|wave|manual-web-wave|collection-draft`；schema 直接读取服务 OpenAPI，示例不含秘密且无业务写副作用。人工正式提交响应和文档明确 `collection submit → judging → run-worker` 的下一步。

### 前端与验证

- 管理页以渐进披露配置模型能力和三组默认参数；测量向导支持普通 Provider 独立 Judge、按回答引擎覆盖、Judge 参数、分引擎费用和冻结参数摘要。证据详情显示 allowlisted 请求参数与非敏感响应元数据。
- 110 项 pytest 通过，覆盖参数优先级、能力校验、重复名称 409、独立 Judge worker/成本、DeepSeek 协议与失败语义、think 处理、旧新协议比较、CLI schema/example 和 populated v3→v4 migration。
- 四套真实 Chrome 验收通过：八工作流、治理、人工 Web，以及模型参数/DeepSeek 离线配置/普通 Provider 独立 Judge。新增路径覆盖 1440/768/390，无外部请求。
- 自动化未执行真实付费调用；另行确认的两组隔离单题 live 已通过。DeepSeek Search+Chat 各 1 次、10 条引用，实际返回模型 `deepseek-flash`；Kimi Search+Chat 各 1 次，`kimi-k3.1-pro` 使用 `temperature=1,max_tokens=2048` 返回 5 条引用，随后 DeepSeek 独立 Judge 使用 `temperature=0,max_tokens=1800` 和 JSON mode 返回 `llm-judge`，回答/Judge 引擎归属分开。两组 Run 均为 done、回答均为有效样本，未自动重试；价格未配置故成本未知，单题 live 不覆盖失败路径或账单对账。未实现 Fetch、自动 Collector、持久登录、DOM 自动提取、验证码处理/绕过或多平台爬虫。

## 2.1.0 — 2026-11-07

### 报告与浏览器合同

- 报告创建在无显式深链时默认选择最新具有正式 Run 的 Wave，不再误选更新的同名未执行 Wave；显式选择未执行 Wave 仍可保存受阻草稿。报告选项和详情显示 Wave/Run 身份。
- Measure、Review、Report 增加稳定业务定位器和轻量 `ReportsPage`；同名 Wave 回归同时断言 UI、真实 POST/GET 和 SQLite 快照绑定。
- 修复 ARIA 布尔值序列化，以及隐藏人工协议中的必填控件阻断普通 Provider Wave 创建的问题；隐藏协议现在同时禁用，人工选择后恢复。

### 完整薄业务 CLI

- 新增标准库 HTTP-only CLI，保留九个本机运维命令；业务命令通过 FastAPI，不直接写业务 SQLite，不复制权限、预算、状态机或审批。
- 注册表覆盖全部业务 OpenAPI 路由，提供 Bearer-only 0600 会话、秘密 FD、JSON/table、结构化错误、`capabilities` 和组合测量命令。
- 真实 Run/健康检查需要独立确认；写请求和超时不自动重试，禁止自动重定向。下载使用 0600 原子替换并校验大小、SHA-256、PDF magic 和项目导出内部 hash。
- 新增 collection/evidence 命令、原始 bytes 上传和不可变提交/失败确认；人工 Web 目标不接收 API Key。详见 [cli.md](cli.md)。

### 人工 Consumer Web 闭环

- 新增 `manual_web + consumer_web` 目标及 schema v3。Web Wave 只选择一个目标，冻结实际产品入口、surface、会话/登录、联网/深度、上下文清理、追问策略和独立 Judge；不与 Provider 混合，不创建自动调度。
- 人工 Run 从 `awaiting_collection` 开始；支持不完整草稿、PNG/JPEG/WebP 截图、raw HTML/text、人工页面引用、实际观察时间/上下文、不可变提交、失败登记和管理员重采。截图/raw evidence 与正文同存 SQLite。
- 提交后复用独立 Judge、Observation revision、指标、正式 Run 和报告链。人工回答/Search 调用为 0；Demo Judge 明确标为离线测试，不代表真实消费者平台或 Provider live 验收。
- 新增证据覆盖与采集质量指标、跨 surface 无 delta 比较、人工 Web 报告证据闸门、客户版脱敏、`geopulse-project-v2` base64 附件导出和 retention tombstone。
- 修复多 worker 重复领取已提交人工回答、附件删除审计序列化 BLOB、独立 Demo Judge 归属和 Answer API 的 Judge engine ID 合同。

### 验证

- 90 项 pytest 通过，含 CLI 全路由与完整业务链、人工提交/失败/权限/12 附件上限/图片签名、v2→v3 populated migration、备份恢复、报告、导出和保留。
- 三套真实 Chrome 验收通过：既有八工作流、治理与可访问性，以及人工 Web 目标→草稿→证据→提交→离线 Judge→仲裁→正式 Run→报告 HTML/PDF→失败登记→viewer/reviewer。
- 人工 Web 在 1440/768/390 检查布局与横向溢出，证据下载 bytes/hash 和客户 PDF hash 通过；浏览器外部请求为 0，无 pageerror。
- 本轮不执行真实付费调用，不实现授权 Collector、持久登录、DOM 自动提取、验证码处理/绕过、多平台爬虫或 Consumer App 自动化。

## 2.0.2 — 2026-11-07

### Unslop 组件级精修

- 按 [heydamir/unslop](https://github.com/heydamir/unslop) 的 polish-mode 审计方法检查卡片、字体和表单控件；保留现有产品方向与页面顺序，未引入运行时或复制示例页面。方法来源：Damir Sokolovsky（@heydamir），CC BY 4.0。
- 收敛标题、导航、表格和元数据的字重，移除普通摘要面板的装饰性顶部高亮；控件、容器与浮层使用明确的圆角和表面 token，焦点环统一为品牌青色。
- 输入框、下拉框和文本域统一桌面 14px 字体、42px 高度及默认、悬停、焦点、禁用、只读和错误状态；修正 hover 覆盖 focus/invalid 的选择器优先级，移动控件继续使用 16px 字体和至少 44px 高度。
- 单选 select 使用本地 SVG 指示并保留原生弹出、键盘、表单和移动选择器；多选保持原生外观，forced-colors 模式恢复系统控件。当前步骤、Wave 和回答增加可编程的 `aria-current` 状态。
- 问题集版本摘要改为无卡片的数据头，冻结时间、哈希与维度计数保持完整；空项目步骤区移除外框，仅当前步骤保留轨迹线。平板页首提前纵向排列，避免操作按钮压缩中文标题。

### 「冷流工作台」UI 重构

- 分别调研 diagram-design、redesign-skill、ai-design-skills 与 OpenUI，只吸收信息层级、语义 token、图表路径和局部更新原则；未引入第三方运行时、外部字体或前端框架。
- 以 208px 深墨导航、完整中文标签和细线 SVG 图标替代单字导航轨；全站标题与控件改用现代中文无衬线，宋体只保留在原始回答、证据引文和报告阅读场景。
- 顶栏、口径带和工作区共享居中对齐的内容边界；总览、测量、证据分别设置合理宽度上限，超宽屏不再拉散，1024/768 提前转为单栏。
- 总览按当前任务、正式测量、待办与历史重组；空项目只保留一条真实准备路径。测量按 Wave 摘要、当前 Run、结果、诊断和执行记录组织，活跃 Run 原位更新进度。证据页以回答索引、原文和实体判定形成共享选择流。
- 移动导航增加 inert、焦点闭环与 Escape 恢复；原文区域支持键盘滚动和可访问名称，移动小控件保持 44px 触控高度，全部短动效支持 reduced motion。

### 「研究档案室」整体视觉

- 将宽深绿侧栏改为浅色纤细导航轨，使用冷白画布、深墨蓝正文、钴蓝主操作，以及中文宋体标题和证据引文。
- 总览以“定义 → 测量 → 复核 → 交付”和可点击的“问题 → 原文 → 判定 → 机会 → 报告”证据链替代 KPI 卡片墙；阶段只表示当前位置，不虚构完成状态。
- Wilson 区间增加可扫描轨道，保留 hits/n、点估计和上下界文本；空样本与缺失区间不绘制轨道，小样本继续只观察方向。
- 测量、证据复核、机会、报告和系统管理统一为协议单、原文文档、判定批注、交付文档和章节目录；严格比较在非小样本时使用配对点图。
- 保留八条路由、全部业务 API、权限裁剪、移动清单/详情、键盘 tabs、抽屉焦点管理和零构建 ES-module 技术栈。

### Taste Skill v2.5 排版精修

- 工作区改为统一 gutter 的流式布局，不再以 1360px 居中；顶栏、口径带和正文左右边缘一致，超宽空间用于数据表、测量明细和证据栏。
- 正文、表格、表单与控件统一提高可读性，收敛章节间距和粗分隔线；按钮增加安静的 hover/press 反馈，移动 tabs 自动换行，避免最后一项被截断。
- 空项目以真实实体、问题集和 Wave 状态生成三项基线准备清单；不再连续展示空指标、空待办、空 Wave 和零值运营区，主操作会指向当前第一项准备工作。
- 没有测量上下文时完全收起口径带，问题集不再显示“引擎：尚未选择”；移除路由切换后整个工作区的装饰性焦点边框，交互控件焦点环保持不变。

### 验证

- pytest：61 passed，1 个既有 Starlette TestClient 依赖弃用提醒；全部前端 ES-module 与两套浏览器脚本语法检查通过。
- 完整浏览器 smoke 通过：八条工作流、严格比较、viewer/reviewer、HTML/PDF、Action、调度、备份、导出和项目删除；governance 通过结构化价格、软/硬预算、阻塞调度恢复、告警历史、原文保留、工时、键盘 tabs、移动溢出、导航焦点闭环和 reduced motion。
- 八条路由在 2560、1440、1280、1024、768、390 六档宽度执行截图与横向溢出断言，并逐张复核关键页面；覆盖空项目、移动清单/详情、统一内容边缘、平板 tabs 换行和表格次级操作。
- Measure 的 Wave/Run 深链刷新、Review 的 Run/Answer/Status/Review 筛选与返回状态、移动导航 inert/Escape/焦点恢复均通过浏览器断言；登录页桌面/移动和 Wilson 数值边界检查通过。
- Unslop 组件回归通过：输入框与 select 的字体、42px 高度、圆角、原生选择行为及 hover/focus/disabled/invalid 状态均有计算样式断言；冻结版本、移动空项目、当前轨迹和 768px 页首标题宽度均有专门覆盖。控件边界对白色/画布背景对比度为 3.38:1 / 3.11:1。
- 核心正文与导航颜色对比度为 5.53:1–12.93:1，达到正常文本 4.5:1 目标。本轮仅修改前端、对应浏览器验收和文档，不执行真实付费外部调用。

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
