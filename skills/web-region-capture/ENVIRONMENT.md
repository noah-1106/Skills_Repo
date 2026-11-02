# 跨平台环境契约

> M2 已提供薄 bootstrap/doctor 与同一 Python 核心；macOS 实测，Windows/客户端实测状态以 TEST-STATUS.md 为准。不预设 Chrome。

## 1. 依赖分层

| 层 | 必需性 | 说明 |
|---|---|---|
| Python 3 + pip | 必需 | 推荐受支持的 Python 3.11+；实现时锁精确版本 |
| Playwright Python | 必需 | 托管浏览器、定位和截图主路径 |
| Playwright Chromium | 必需 | `python -m playwright install chromium`；不需要系统 Chrome |
| openpyxl + Pillow | 本地 Excel 必需 | 工作簿副本、图片锚定、尺寸与图像检查 |
| OpenCLI | 可选 | 仅用户显式选择复用已登录 Chrome 时安装 |
| Node.js / npm | 可选组件需要 | 官方飞书 CLI 安装；OpenCLI 若以 npm 安装也需要 |
| 飞书官方 `lark-cli` | 飞书 Base 必需 | 仅飞书适配器使用；目录/Excel 不依赖 |

浏览器与 Python 环境不随分发包携带；每个 OS 重建。OpenCLI 不是基础安装门槛。

## 2. 当前 Noah 机器：外置盘布局

项目可放在任意可写目录；以下路径均从项目根解析。

建议当前机器派生目录（实现时由本地配置生成，不写进公开示例）：

- `.venv/`：当前 OS 的 Python 环境；
- `runtime/ms-playwright/`：Playwright 浏览器；
- `data/browser-profile/`：登录 profile，敏感且不发布；
- `data/runs/`、`outputs/`：任务证据与交付图。

设置浏览器缓存的项目内路径：

macOS/Linux shell：

```bash
export PLAYWRIGHT_BROWSERS_PATH="$PWD/runtime/ms-playwright"
python -m playwright install chromium
```

Windows PowerShell：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD "runtime/ms-playwright"
python -m playwright install chromium
```

启动器必须为每次运行设置同一变量，不能只依赖用户手工 export。若外置盘未挂载、不可写或空间不足，doctor 在启动浏览器前失败。

## 3. 安装形态

实现后提供两个薄入口，内部调用同一 Python 模块：

- macOS：`scripts/bootstrap.sh`、`scripts/doctor.sh`
- Windows：`scripts/bootstrap.ps1`、`scripts/doctor.ps1`

底层标准动作：

macOS：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
# 依赖锁定文件生成后再执行精确安装
python -m playwright install chromium
```

Windows PowerShell：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m playwright install chromium
```

Windows 执行策略或企业权限导致脚本无法运行时，直接显示等价 Python 命令，不要求用户关闭系统安全策略。代理、证书和企业网络错误单独分类，不能笼统报“浏览器坏了”。

## 4. 本地环境配置

`config/local.json` 由 bootstrap/doctor 生成并加入 `.gitignore`；只存当前机器路径与驱动选择，不存网站密码、Cookie 或飞书 secret。

优先级：显式 CLI 参数 > 任务配置 > `config/local.json` > 安全默认值。

- 项目路径和输出路径支持相对项目根目录；允许用户显式绝对路径。
- `browser.driver` 默认 `playwright`，`browser.channel` 默认 `chromium`。
- 只有用户显式选择才使用 `chrome`、`edge` 或 `opencli`。
- 默认有头浏览器，方便首次人工登录；后续是否无头由处方和 POC 决定。
- 默认串行，禁止多个进程共用可写 profile。

## 5. doctor 输出契约

```json
{
  "ok": false,
  "checks": [
    {"name": "python", "status": "pass|fail|warn", "detail": "脱敏说明"},
    {"name": "project_writable", "status": "pass", "detail": "..."},
    {"name": "disk_space", "status": "pass", "detail": "..."},
    {"name": "playwright_chromium", "status": "pass", "detail": "..."},
    {"name": "opencli", "status": "skipped", "detail": "未选择该驱动"},
    {"name": "lark_cli", "status": "skipped", "detail": "未选择 Base 输出"}
  ],
  "artifact": "data/runs/<run>/env-report.json"
}
```

必需项失败则 exit 非 0；可选项未安装但未被选择只能 skipped，不能算失败。客户端可以读取 JSON，人类用户可以读文本摘要。

## 6. 登录态与安全

- 首次打开有头浏览器，由用户本人登录和处理验证码。
- profile 是敏感资产，权限尽量限当前用户；不上传、不打包、不进入测试 fixture。
- 不把 Cookie 导出到任务配置，不要求用户提供账号密码。
- 外置盘丢失或不可信时，用户应撤销相关网站会话；公开分发不含任何现成 profile。
- 真实网站与表格测试默认关闭；环境报告不记录秘密值。

## 7. 分发验收环境

至少验证四种，不以“我的 Mac 能跑”为跨平台证据：

1. macOS，无系统 Chrome，Playwright Chromium；
2. Windows，无系统 Chrome，Playwright Chromium；
3. macOS 或 Windows，用户显式选择已有 Chrome + OpenCLI（可选）；
4. Codex、Claude Code、WorkBuddy 至少各一次从 SKILL.md 调用相同命令，产物一致。

第 3 项失败不影响默认路径交付；第 4 项未实测的客户端必须标为未验证，不写“全客户端兼容”。
