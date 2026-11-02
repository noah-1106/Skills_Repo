# web-region-capture

把网页的显式区域做成可复核、可续跑的 PNG 证据，再安全送到目录或本地 `.xlsx` 副本。飞书 Base 只通过官方 `lark-cli`，默认 dry-run。

## 快速上手（macOS 已实测）

```sh
sh scripts/bootstrap.sh
sh scripts/doctor.sh
python -m web_region_capture --root "$PWD" run --config config/tasks.m2-example.json --run-id "我的 运行"
```

若未安装包，先设置 `PYTHONPATH="$PWD/src"`。默认 dry-run：只保留截图/纯净度/manifest，不写最终目录或 Excel。确认计划后同一运行续跑（dry-run 产物不会被误当已交付，必须显式 `--execute-local` 才落位）：

```sh
python -m web_region_capture --root "$PWD" run --config config/tasks.m2-example.json --run-id "我的 运行" --resume --execute-local
```

Windows 用 `powershell -ExecutionPolicy RemoteSigned -File scripts/bootstrap.ps1`（如企业策略禁止，按脚本内等价 Python 命令手工执行，不要求关闭安全策略）和 `scripts/doctor.ps1`。**Windows 脚本本轮未在 Windows 激活。**

## 环境与锁定依赖

Python 3.11+；直接依赖在 `requirements.txt` / `pyproject.toml` 精确锁定：Playwright 1.64.1、openpyxl 3.1.5、Pillow 13.0.0。默认 Playwright 托管 Chromium，缓存为项目内 `runtime/ms-playwright`，无需 Chrome、Node 或 OpenCLI。OpenCLI 不是默认运行依赖且 M2 未实现其 runner。飞书输出才需要用户自行安装/登录官方 `lark-cli`，凭据不进配置。

`config/local.json` 从 `config/local.example.json` 复制；只含本机路径和默认驱动，不含账号密码/Cookie。目录、工作簿和本地 HTML 的相对路径均从 `--root` 解析；支持中文和空格。

## 配置与落位

从 `config/tasks.m2-example.json` 复制：内联 `site` 或 `site_file`，任务提供安全唯一 `task_id`、`regions`。目录用 `destination.path`；Excel 必须给 `source_path`、新 `path`、精确 `sheet` 和每区域 `cells` A1 映射。原表不原地修改，非空目标/已有图片/缺失工作表阻断。只支持 `.xlsx`，浮动图片锚定，不声称 Microsoft 365 Place-in-Cell 或 xlsm/VBA 保真。

Base 需要 `base_token`、`table_id`、`record_id`、每区域附件 `fields`。详见 `docs/LARK_BASE.md`。真实写入同时要求任务 `allow_live_write=true`、`allow_replace=false` 和命令 `--authorize-lark-write`，默认只追加；上传后状态为 `needs_readback`，须官方读回与下载 hash 对账才可称 delivered，未授权不得真实写入。

## 节点、文件与失败

1. 配置校验 → `data/runs/<run>/manifest.json`；错映射在打开网页前失败。
2. 页面动作/身份断言 → manifest `navigation`；导航动作仅白名单 fill/click/wait_for_selector。
3. 区域截图与 M1 纯净度门禁 → `captures/<task>/<region>.png` 与 `*-purity-check.json`；缺失、歧义、遮挡、非法边界独立失败。
4. 目录/Excel/官方 CLI 适配器 → 本地新产物或 run-local dry-run 响应；无客户端专有 API。
5. manifest 记录任务指纹、PNG 与检查 hash、源/结果工作簿 hash；`--resume` 只跳过已验证的同指纹产物，冲突/改变需诊断或新 run，绝不静默覆盖。

## 测试与边界

```sh
PYTHONPATH="$PWD/src" PLAYWRIGHT_BROWSERS_PATH="$PWD/runtime/ms-playwright" python -m unittest discover -s tests -t . -p 'test_*.py' -v
```

`-t .` 不可省：`tests/` 是包，从项目根做顶层发现才能正确导入。当前 30/30 通过（日志 `evidence/m2d-full-unittest-final.log`，明细 `docs/M2D-REPORT.md`）。

### 路径写法

- `/./xxx` = 显式项目根相对，如 `/./outputs/结果.xlsx`。
- 普通相对路径与绝对路径也会解析，但最终目标必须仍在 `--root` 内，否则 `OUTPUT_UNSAFE`。
- `destination` 可写平铺映射，也可写 `{"mapping": {...}}` 嵌套形式（`mapping` 必须是唯一属性），两者等价。
- 同一项目经符号链接路径（如 macOS `/var` vs `/private/var`）打开，`--resume` 仍按内容 hash 识别，不会因路径拼写不同而失败。

当前机器激活范围见 `TEST-STATUS.md` 与 `evidence/m2-verification.json`。公共站验收属于后续 M3；不得用离线 fixture 替代。Windows、OpenCLI、外部客户端、星图及真实 Base 均未实测。

## 目录

`src/web_region_capture/` 核心与 CLI；`scripts/` 两平台薄入口；`config/` 示例；`data/runs/` 中间证据与 manifest；`outputs/` 最终本地交付；`tests/` 离线回归；`docs/` Excel/Base/纯净度契约；`evidence/` 测试全量日志。无 `agents/`：本版本无需客户端灵魂文件。

## 验证与来源

本仓库副本不含本机运行日志。`docs/M2D-REPORT.md` 与 `TEST-STATUS.md` 引用的 `evidence/` 日志保留在项目正本；本文所述 30/30 回归结果可用上面的复跑命令自行验证。
