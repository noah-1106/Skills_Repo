# GeoPulse 薄业务 CLI

`scripts/geopulse_ctl.py` 同时保留本机运维命令和 HTTP 业务命令。业务命令只调用 FastAPI，不直接写业务 SQLite，不复制权限、预算、审批或状态机；真实 Provider 调用仍需独立确认。

## 1. 认证与通用参数

交互登录会隐藏密码输入，并把 Bearer token 保存在 0600 本机会话中；不会保存 Cookie，也不会输出 access token 或 CSRF token。

```bash
.venv/bin/python scripts/geopulse_ctl.py auth login \
  --base-url http://127.0.0.1:8700 --email admin@geopulse.local

.venv/bin/python scripts/geopulse_ctl.py capabilities
.venv/bin/python scripts/geopulse_ctl.py auth me
```

自动化可通过 `--secret-fd` 从受保护的文件描述符读取密码，例如 `3< /secure/path/password.txt`。不要把密码写进 `--spec`、命令行明文参数或聊天记录。也可使用 `GEOPULSE_ACCESS_TOKEN`；`GEOPULSE_SESSION`、`GEOPULSE_BASE_URL` 分别覆盖会话路径和服务地址。

通用参数：

- `--project ID`：项目作用域，业务命令应显式提供。
- `--spec FILE`：JSON 请求对象；`-` 表示 stdin。保留 omitted 与 explicit null 的区别。
- `--format json|table`：默认机器可读 JSON；`--json` 是默认格式别名。
- `--timeout SECONDS`：请求超时，默认 30。
- `--out FILE`、`--overwrite`：输出路径及显式覆盖。
- `--session FILE`：使用隔离的 0600 会话文件。

错误输出保留 API 的结构化 `detail`、HTTP 状态、request ID 和 estimate。CLI 禁止自动重定向，不自动重试 POST/PUT/DELETE、下载或超时请求。

## 2. 本机运维命令

以下九个命令保留原有本机语义，不经过远程 API：

```text
init
migrate
backup
restore
set-admin-password
run-worker
golden-eval
export
delete-project
```

`admin backup` 是另一个 HTTP 命令：它只在服务器备份目录创建数据库和 manifest，不声称已下载或本地校验数据库。`project export` 是 HTTP 项目导出；本机 `export` 仍直接读取本机数据库。

## 3. 业务命令域

```text
auth             login / me / logout / password
project          list / create / get / settings / overview / export / delete
prompt-set       list / create / get / import / scaffold / review / status /
                 copy / diff / export
entity           list / create / review / version / pool-diff
engine           list / create / update / health
wave             list / create / get / run / official / status
run              get / handoff / answers / metrics / wait / cancel / retry
judge-batch      list / create / get / cancel / retry
answer           get / revise
collection       get / save / submit / fail / resume
browser-session  list / create / verify / revoke
evidence         upload / download / delete
compare          同口径或跨 surface 摘要
opportunity      generate / list / review / status / action
action           list / get / status
brief            create / update / approve
asset            create / update / approve
publication      create
remeasurement    create / assess
event            list / create
report           list / create / get / status / export
schedule         list / create / update
alert            list / ack
retention        preview / execute
work-log         add
operations       成本与运营摘要
member           list / assign
user             list / create
audit            list
admin            backup
health           服务健康状态
```

使用 `--help` 查看叶子命令的准确参数：

```bash
.venv/bin/python scripts/geopulse_ctl.py wave create --help
.venv/bin/python scripts/geopulse_ctl.py evidence upload --help
.venv/bin/python scripts/geopulse_ctl.py browser-session create --help
.venv/bin/python scripts/geopulse_ctl.py collection resume --help
```

`capabilities` 返回服务健康、当前身份和完整注册表。`live_provider_verified=false` 是有意的：命令覆盖不等于真实 Provider、真实消费者平台或 Collector 已验收。

## 4. OpenAPI schema 与可填写示例

```bash
CTL='.venv/bin/python scripts/geopulse_ctl.py'

$CTL schema engine
$CTL schema wave
$CTL schema collection-draft

$CTL example engine
$CTL example wave
$CTL example manual-web-wave
$CTL example collection-draft
```

`schema` 只读取服务的 `/openapi.json` 并展开对应 Pydantic component，不让远程 CLI 导入后端或复制 schema。`example` 返回 `spec`、`usage` 和 `notes`；把 `spec` 保存为 JSON 后替换实际 ID、模型、入口和观察事实。示例不包含 API Key，引擎秘密仍通过 `--secret-fd` 提供。两条命令都不会创建引擎、Wave、Run 或采集任务。

## 5. 典型调用

```bash
CTL='.venv/bin/python scripts/geopulse_ctl.py'

$CTL wave list --project 1
$CTL run get --project 1 --run 12
$CTL run wait --project 1 --run 12 --wait-timeout 600
$CTL run metrics --project 1 --run 12
$CTL report create --project 1 --wave-id 4
$CTL report export --project 1 --report 7 \
  --variant internal --file-format pdf --out /secure/path/report.pdf
```

Shell 变量只缩短示例；也可以重复写完整解释器路径。`run wait` 只轮询 GET，等待超时不等于 Run 失败。

`measure run --project 1 --spec wave.json` 是少量组合命令之一，按 `wave create → run create → 可选 wait/metrics` 编排。遇到真实调用确认或预算节点会立即停止并输出 `waiting_for_decision`，不会越过人工决定继续创建 Run。

### Judge 补判与交付交接

```bash
$CTL judge-batch list --project 1 --run 12
$CTL judge-batch create --project 1 --run 12 --spec judge-batch.json --confirm
$CTL judge-batch get --project 1 --judge-batch 3
$CTL judge-batch retry --project 1 --judge-batch 3 --confirm
$CTL run handoff --project 1 --run 12
```

补判 spec 对应 `judge_engine_id`、可选 `answer_ids/judge_overrides` 和确认字段。它只追加 Observation revision，不重新请求 answer/search。真实补判创建与明确失败重试分别确认；`interrupted_unknown` 或其他 `outcome_unknown=1` 的项不能自动重试。handoff 只读，不写外部业务孪生或工时。

### Intervention 证据链

```bash
$CTL action get --project 1 --action 3
$CTL brief update --project 1 --brief 8 --spec brief.json
$CTL brief approve --project 1 --brief 8 --confirm
$CTL asset create --project 1 --action 3 --spec asset.json
$CTL asset approve --project 1 --asset 5 --confirm
$CTL publication create --project 1 --action 3 --spec publication.json --confirm
$CTL remeasurement create --project 1 --action 3 --spec rounds.json
$CTL remeasurement assess --project 1 --round 2 --spec assessment.json --confirm
```

CLI 只透传 HTTP 合同，不在本地复制 evidence ref、审批、固定 Run 或比较规则。`--action`、`--brief`、`--asset`、`--round` 分别映射路径 ID。Brief/Asset 审批和 Publication/评估需要显式确认；Provider 调度只创建 Run，Consumer Web 仍须走显式采集命令。旧 `action status` 单发布/单复测合同保留兼容，但新交付应使用上述分离命令。

## 6. 真实调用与写操作确认

- 真实 `wave run` 未 `--confirm` 时只读取 Wave/estimate，不发送创建 Run 的 POST。
- `collection_method=browser_assisted` 的 `wave run` 和含网页重采的 `run retry` 即使 Provider 回答调用为 0，也视为真实外部发送；只有 `--confirm` 才设置 `confirm_browser=true`，服务端还会检查对应 active 本机会话。
- 非 demo 健康检查第一次返回 409 estimate；第二次必须同时带 `--confirm --estimate previous-estimate.json`。
- `collection submit/fail`、`evidence delete`、复核仲裁、报告审批、保留清理和项目删除有各自显式确认要求。
- 软预算仍需针对本次执行填写 `--budget-reason`；没有 `--force` 可绕过权限或硬预算。
- `manual_web + Demo Judge` 不被当作真实付费调用；独立真实 Judge 仍需确认。

## 7. 人工 Consumer Web 与证据

```bash
$CTL collection save --project 1 --answer 31 --spec collection-draft.json

$CTL evidence upload --project 1 --answer 31 \
  --kind screenshot --filename page.png --media-type image/png \
  --file /secure/path/page.png

$CTL collection submit --project 1 --answer 31 \
  --spec collection-draft.json --confirm

$CTL collection get --project 1 --answer 31
$CTL evidence download --project 1 --attachment 8 --out /secure/path/page.png
```

上传发送原始 bytes 和 SHA-256，不接受秘密字段。截图仅 PNG/JPEG/WebP，单附件最大 10MB，每个回答最多 12 个；raw HTML/text 只作为附件，不会内联执行。正式提交不可覆盖，失败样本不计为零提及。`collection submit --confirm` 返回 `answer_status=judging` 和 `worker_required=true`：必须启动 `run-worker`（或使用已启用应用内 worker 的服务）才会完成 Judge 和 Run，然后再执行 `run wait`。这些**人工采集命令**不会自动打开网页、保存登录会话或提取 DOM；自动任务也不能通过 save/submit/upload 改录。

## 8. 授权浏览器会话与恢复

```bash
$CTL browser-session list --project 1 --engine 4
$CTL browser-session create --project 1 --engine 4 \
  --spec '{"driver":"deepseek_web"}'
$CTL browser-session verify --project 1 --browser-session 2
$CTL collection resume --project 1 --answer 31 \
  --spec '{"action":"resume"}' --confirm
$CTL browser-session revoke --project 1 --browser-session 2 --confirm
```

`browser-session *` 仅 admin 可用。create 让本机 BrowserWorker 打开可见浏览器，用户本人登录并处理验证码，再执行 verify；CLI 不接收密码、Cookie、账号别名或 storage state。路径参数使用 `--browser-session`，与认证会话文件的全局 `--session` 不同。

`collection resume` 只用于 `awaiting_user/paused_unknown`：已发送且有 conversation URL 时只恢复原会话，不重发；已发送但无 URL 时服务端拒绝 resume，只能提交 `{"action":"fail","detail":"无法确认是否发送"}` 登记失败。需要人工降级时另建 `collection_method=manual` 的 Wave/Run，不把自动任务改成人工原文。`run-worker` 同时运行 Provider/Judge 与 BrowserWorker。

## 9. 文件与退出码

下载先写临时文件，校验非空、大小、响应 `X-Content-SHA256` 和 PDF magic；项目导出还重新计算内部 payload SHA-256。成功后以 0600 原子替换目标，默认不覆盖已有文件。

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 参数、输入、确认材料或本地文件合同错误 |
| 3 | 未认证、401 或 403 权限拒绝 |
| 4 | 业务冲突、预算/真实调用确认、等待超时及 400/409/422 |
| 5 | 网络、服务、下载或响应校验错误 |
| 130 | 用户中断；不会自动重试写请求 |

完整运维与恢复流程见 [operations.md](operations.md)，人工 Web 的数据与指标口径见 [v2-architecture.md](v2-architecture.md) 和 [metrics.md](metrics.md)。
