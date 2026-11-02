# web-region-capture · 项目设计 V0.2

> 状态：离线回归 8/8；Wikipedia 公共站真实 POC 功能链通过，首段区域纯净度待修；星图未测。飞书仅 dry-run，未真实写入。详见 `TEST-STATUS.md`。
> 项目可放在任意可写目录；代码与配置不得硬编码本机绝对路径。
> 用户：Windows / macOS；客户端：Codex、Claude Code、WorkBuddy 或其他能执行本地命令的 Agent。
> 核心产物：网页指定业务区域 PNG → 显式目录、Excel 单元格锚点或飞书多维表格附件单元格。

## 0. 本轮裁定

1. **默认浏览器 = Playwright 托管 Chromium**。用户不必安装 Chrome，也不得有可供 Agent 接管的浏览器。
2. **OpenCLI = 可选浏览器驱动**。只有用户明确选择复用已登录 Chrome，且环境检查通过时才启用。
3. **客户端无关**。核心是标准 Python/CLI、文本配置和文件产物；不用 Claude/Codex 专有 API，不依赖 MCP。
4. **本地表格只处理显式单元格映射**。工作簿、工作表、区域名与单元格由任务配置明确给出，不猜测目标位置。
5. **飞书多维表格使用官方 `larksuite/cli`**。目标语义为记录 + 附件字段，不是 Excel 的 A1 坐标。
6. Noah 当前项目与浏览器运行数据放外置盘；分发包不包含浏览器、登录 profile、任务数据或虚拟环境，其他用户在本机重建。

## 1. COP 与边界

### C

同一批网页对象需要重复搜索、进入详情、展开业务面板、截取相同区域，并把图放入提报材料或表格。首个 POC 是星图达人“粉丝性别比例 / 八大人群”。

### O

任务校验 → 环境检查 → 浏览器启动/连接 → 人工登录（首次）→ 搜索或直达 → 身份校验 → 面板定位 → 区域截图 → 图像验收 → 显式目标写入 → 读回/manifest。

不能凭感觉的判断：达人身份、区域唯一性、加载完成、目标单元格、覆盖权限、写入读回。

### P

每个“对象 × 区域”独立交付 PNG 和结构化结果。状态至少分 `captured`、`delivered`、`failed`、`needs_human`、`skipped`；`captured` 不等于 `delivered`。

### 不承诺

- 不承诺任意网站零配置；采用通用执行器 + 每站点处方。
- 不绕过登录、验证码、权限或平台风控。
- 不用视觉模型直接猜最终坐标，不做桌面坐标机器人。
- 不将 openpyxl 的浮动图片锚定说成微软原生“置于单元格中”。
- 未真实运行前不宣称支持星图或飞书写入。

## 2. 架构与目录

```text
任务配置 + 站点处方 + 本地环境配置
        ↓
01 validate + doctor       → env-report.json / task-errors.json
        ↓
02 browser connect         → browser-session.json（不含秘密）
        ↓
03 navigate + identity     → navigation.json
        ↓
04 resolve region          → resolved-region.json
        ↓
05 capture + verify        → PNG + capture-check.json
        ↓
06 folder / excel / base   → delivery.json + 读回证据
        ↓
07 manifest.jsonl + summary.json
```

每个节点可独立失败和重跑。PNG 验收后表格失败不丢图；定位失败不得写表格。

```text
web-region-capture/
├── README.md / DESIGN.md / ENVIRONMENT.md
├── SKILL.md                       # 客户端无关调用说明
├── config/
│   ├── project.example.json
│   ├── tasks.example.json
│   └── sites/xingtu.example.yaml
├── docs/
│   ├── LOCAL_EXCEL.md
│   └── LARK_BASE.md
├── scripts/                       # bootstrap/doctor 跨平台入口
├── src/
│   ├── browser/                   # playwright / opencli 可选
│   ├── capture/                   # 锚点、容器、截图、验收
│   ├── delivery/                  # folder / excel / lark_base
│   └── manifest.py
├── data/                          # 本地任务、状态、登录 profile；不发布
├── runtime/                       # 当前机器浏览器等重建资产；不发布
├── outputs/                       # PNG、结果工作簿、报告
└── tests/                         # 离线默认；真实网站/表格显式开启
```

不需要独立 Agent 灵魂文件。项目不是多 Agent 系统，而是可测试工具管线。

## 3. 浏览器与环境策略

### 默认：Playwright 托管 Chromium

- `browser.driver=playwright`，`browser.channel=chromium`。
- 首次以有头窗口启动，用户人工登录；后续复用项目配置的持久 profile。
- Chromium 可由 Playwright 安装，因此没有 Chrome、Edge、OpenCLI 也能执行。
- 当前 Noah 机器把浏览器下载缓存和 profile 放外置盘，防止继续挤占本地盘。

### 可选：OpenCLI

- 仅当任务显式设置 `browser.driver=opencli` 时启用。
- 先检查 `opencli`、浏览器扩展、profile/session、语义定位、截图/eval 参数。
- 若 OpenCLI 能稳定完成区域截图，则保持单一驱动；否则只负责交互，由 CDP/Playwright 负责截图。
- 本机目前没有 `opencli` 命令，不能把它作为默认依赖。

### doctor 必须检查

操作系统/架构、Python、可写项目目录、剩余空间、依赖版本、Playwright Chromium、浏览器 profile 可写性、配置文件、可选 OpenCLI、可选 lark-cli、表格引擎与网络连通性。输出人读文本和 JSON；秘密只报“存在/缺失/权限有效”，不打印值。

完整契约见 `ENVIRONMENT.md`。

## 4. 区域处方与身份闸门

处方按以下优先级定位：稳定角色/元素 → 面板内唯一文本锚点 → 业务父容器 → 固定矩形。固定矩形必须锁定 viewport、DPI、缩放，布局变化后重新验收。

以下均阻断成功：

- `IDENTITY_MISMATCH`：当前达人不是任务对象；
- `REGION_NOT_FOUND`：区域不存在；
- `REGION_AMBIGUOUS`：同名区域不唯一；
- `REGION_NOT_READY`：加载、遮罩或数据未就绪；
- `AUTH_REQUIRED`：需要用户重新登录；
- `TARGET_UNSAFE`：目标不明确、非空或越权。

星图 DOM/Canvas/iframe 尚未实测。`config/sites/xingtu.example.yaml` 只有字段模板，选择器必须由 POC 证据填写。

区域纯净度采用“**样图标定 + 结构处方 + 排除/遮挡检查 + 新处方首图人工验收**”。样图定义意图，不承担像素定位；执行契约包含 `locate / boundary / exclude / occlusion`。文本浮动场景使用文本行边界，卡片/图表使用业务容器边界。详见 `docs/REGION_PURITY.md`。该能力目前仍是设计，未实现。

## 5. 显式落位契约

### 文件夹

`destination.type=folder`，路径为项目相对路径或用户显式绝对路径；文件名含安全任务键和区域名，原子写入并校验 SHA256。

### 本地 Excel/WPS

必须显式提供：工作簿路径、工作表、每个区域的单元格。例：

```json
"destination": {
  "type": "excel",
  "path": "outputs/达人提报.xlsx",
  "sheet": "达人提报",
  "cells": { "gender": "C5", "audience": "D5" },
  "overwrite": false
}
```

默认生成新结果工作簿，不改原件。`overwrite=false` 时目标已有图片/内容则停止。首版使用 openpyxl 将**浮动图片锚定到单元格**并适配尺寸；不是原生单元格值。若必须原生嵌入，另立 Windows Office 适配器验收。

### 飞书多维表格

显式提供 `base_token + table_id + record_id + 每个区域对应的附件 field_id`。使用官方 CLI 的 `base +record-upload-attachment`，该命令会验证附件字段、上传本地图片并把 file_token 追加到目标单元格。

**它是追加语义，不是替换。** manifest 记录交付证据防止重跑重复；目标已有附件且无法确认时进入待人工。替换旧附件需要单独授权并精确指定旧 file_token，禁止清空整个字段。

完整安装与命令见 `docs/LARK_BASE.md`。

## 6. 跨平台与客户端约束

- 所有项目路径默认相对项目根目录解析，支持中文、空格和 Windows/macOS 分隔符。
- 统一 Python 模块入口；shell/PowerShell 只是薄启动器，业务逻辑不写两份。
- Codex / Claude Code / WorkBuddy 读取同一份 SKILL.md 并调用同一 CLI，没有客户端专属状态。
- 浏览器二进制、Python 虚拟环境、登录 profile 不跨 OS 复制；换机器必须 bootstrap 重建。
- 默认串行网页任务，避免同一 profile 并发写入。表格写入同表串行，失败按任务隔离。
- 配置优先级：显式 CLI 参数 > 任务配置 > 本地环境配置 > 安全默认值；任何默认都不能替用户猜单元格或账号。

## 7. 纵向切片与验收

1. **环境切片**：分别在 Windows/macOS 的干净测试环境执行 bootstrap/doctor；不安装 Chrome，托管 Chromium 能启动。
2. **POC**：1 个达人 × 2 区域 × 文件夹；用户人工登录；核验身份、区域、PNG。
3. **本地表格**：测试工作簿副本，显式单元格映射；验证图片锚点、尺寸、原件不变、重复运行不重复插入。
4. **批量恢复**：正常、搜索无结果、重名、超时、区域缺失、单图失败、断点续跑。
5. **飞书可选**：测试 Base、附件字段、官方 CLI 上传、记录读回、附件下载/hash 对账。
6. **通用性与交付**：第二个站点处方；README 陌生 Agent 检验；Windows/macOS 安装与排查文档。

验收分对象域、视觉域、几何域、写入域、恢复域。文件存在或 API success 都不是单独通过条件。

## 8. 安全与分发

- 只操作获授权的网站和表格；人工处理登录/验证码。
- 发布包不包含任务数据、网页截图、工作簿、Base token、浏览器 profile、凭据或运行日志。
- 当前外置盘是 Noah 的开发位置，不是其他用户的默认路径；其他用户通过本地配置选择数据目录。
- 所有真实网站/表格测试默认关闭，需显式开关、测试副本和回滚证据。

## 9. 当前待输入

1. 一个测试达人及已获授权的星图登录方式；
2. 一份测试 Excel/WPS 工作簿，明确工作表和两个目标单元格；
3. 是否先做本地 Excel，再做可选飞书 Base。

设计完成不等于 POC 通过；下一步先在星图真实页面确认登录、搜索和两种区域的 DOM/Canvas 结构。
