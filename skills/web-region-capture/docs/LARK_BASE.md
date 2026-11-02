# 飞书多维表格落位：官方 CLI 方法

> 适用：飞书多维表格（Base/Bitable）的**附件字段**。不是飞书电子表格，也不是 Excel A1 单元格。
> 状态：命令依据官方仓库文档/源码核对，尚未用 Noah 的真实 Base 执行。

## 1. 官方组件与安装

官方仓库：`https://github.com/larksuite/cli`，命令名 `lark-cli`。需要 Node.js/npm；Go 和 Python 仅源码构建需要。

```bash
npx @larksuite/cli@latest install
lark-cli config init
lark-cli auth login --recommend
lark-cli auth status
```

Agent 引导新应用可使用 `lark-cli config init --new`，按输出让用户在浏览器完成授权。凭据由官方 CLI 管理，不复制到本项目任务配置。

Base 操作优先 `--as user`。上传附件涉及权限：`base:record:update`、`base:field:read`、`docs:document.media:upload`；实际授权后仍需用户确认 Base 资源 ACL。

## 2. 先明确“指定单元格”

Base 不使用 Excel 的 `C5` 定位。用户必须显式约定：

- `base_token`：目标 Base；
- `table_id`：目标数据表；
- `record_id`：目标记录（行）；
- `field_id`：目标附件字段（列）；
- 每个截图区域与 field_id 的映射；
- 追加还是替换；默认追加且防止重跑重复，已有附件无法判断时停止。

从 URL 开始解析：

```bash
lark-cli base +url-resolve --url '<用户提供的Base链接>' --as user
lark-cli base +table-list --base-token '<base_token>' --as user
lark-cli base +field-list --base-token '<base_token>' --table-id '<table_id>' --as user
```

记录可由用户提供 record_id，或通过明确业务键搜索后由用户确认；不得用模糊昵称猜记录。

## 3. 一条命令上传并写入附件单元格

官方专用 shortcut：`base +record-upload-attachment`。官方源码定义的三步为：验证目标字段确为附件 → 上传本地文件到当前 Base → 将返回的 file_token 追加到目标记录字段。

```bash
lark-cli base +record-upload-attachment \
  --base-token '<base_token>' \
  --table-id '<table_id>' \
  --record-id '<record_id>' \
  --field-id '<attachment_field_id>' \
  --file './outputs/creator-001/gender.png' \
  --as user \
  --format json
```

多个区域默认分别调用并写入各自显式 field_id。不要仅为减少命令而把不同业务图塞进同一附件字段。

**不需要先手工执行 `drive +upload`**；上述 Base shortcut 已封装上传与写入。`drive +upload` 是普通云盘文件上传，不等于更新 Base 附件单元格。

## 4. 默认是追加，不是替换

- 命令描述及 dry-run API 均为 append attachments。
- 本项目 manifest 必须记录 task、region、record、field、返回的 file_token 和 hash，重跑先检查是否已交付。
- 已有附件且没有可靠映射时：`needs_human`，不得自动清空。
- 用户明确要求替换时，只针对确认过的旧 file_token 执行 `+record-remove-attachment`；这是高风险写命令，官方要求 `--yes`。不能让 Agent 静默执行。

## 5. 读回验收

先读目标记录，确认返回的 file_token 出现在指定附件字段：

```bash
lark-cli base +record-get \
  --base-token '<base_token>' --table-id '<table_id>' \
  --record-id '<record_id>' --field-id '<attachment_field_id>' \
  --as user --format json
```

再下载该附件并核对图像可打开及与源 PNG 的 SHA256：

```bash
lark-cli base +record-download-attachment \
  --base-token '<base_token>' --table-id '<table_id>' \
  --record-id '<record_id>' --file-token '<上传返回的file_token>' \
  --output './outputs/verify-gender.png' --overwrite --as user
```

只有“记录字段含目标 file_token + 下载文件与源图一致”才算 `delivered`。上传成功或 API 200 只是中间状态。

## 6. 项目适配器的职责

官方 CLI 是外部进程适配器，不把 Go 源码复制进项目：

1. doctor 检查 `lark-cli`、认证与 scope；未选择 Base 时跳过。
2. 从任务读取显式 Base 坐标，校验目标字段类型。
3. 只把已验收 PNG 交给官方命令；保存结构化 JSON。
4. 对未知结果先读目标状态再重试，避免重复附件。
5. 写后读回并下载对账；原始凭据、完整响应和真实业务数据不进入公开日志。

命令参数随官方版本升级可能变化，实现和升级时必须重读 `--help`/结构化 schema，并做 dry-run/测试 Base 验证。

## 7. 证据出处

本项目 `research/` 保存了公开官方材料：

- `official-README.zh.md`：安装、认证与官方 Agent Skills；
- `official-skills-lark-base-SKILL.md`：Base 实体模型、记录/附件专用命令；
- `official-shortcuts-base-record_upload_attachment.go`：`+record-upload-attachment` 的参数、权限、追加语义、上传与读回契约。

这些是公开技术资料，不含 Noah 的应用凭据或真实 Base 数据。
