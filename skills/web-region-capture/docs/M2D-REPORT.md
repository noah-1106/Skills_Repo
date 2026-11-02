# M2D 验收报告（2026-11-02）

范围：把 M2A-C 期间已改动但未激活的代码拉回可验证状态；修 resume/dry-run 复用缺陷；真实 CLI 端到端验收。
验证日志保留在项目正本的 `evidence/`（本机运行证据，不随仓库分发）。

## 结果

| 项 | 结果 | 实证 |
|---|---|---|
| 全量离线回归 | **30/30 通过，0 失败 0 跳过，exit=0** | `evidence/m2d-full-unittest-final.log`（项目正本）（`Ran 30 tests ... OK`，37 行） |
| M2 产品套件 | 14/14（含 test_09/11 子测试） | `evidence/m2d-product-r21.log`（项目正本） → final |
| M1 基线（不得回退） | 16/16 仍通过 | final 日志中 test_offline_poc 8 + test_region_purity 8 |
| 真实 CLI：dry-run | 通过，未落位任何产物 | `data/runs/m2d-e2e/` |
| 真实 CLI：resume + execute-local | 通过，folder 2 PNG + Excel 落位 | `outputs/m2d-e2e-folder/`、`outputs/m2d-e2e-结果表.xlsx` |
| Excel 读回 | C5/D5 两锚点，2 张图 | 见下「读回实证」 |
| 源表不变 | manifest hash == 实际 hash `392cad044784c968…` | 同上 |
| 重复 resume 幂等 | 两任务均 `resumed: true`，产物 mtime 未变（1793603510） | `evidence/m2d-e2e-resume-reuse.json`（项目正本） |

## 本轮修复（全部落在 product.py / 测试，不改 M1 区域纯度模块）

1. **dry-run 条目可被 `--resume --execute-local` 复用导致未落位**（resume 文件头号待修）
   根因：`deliver_local()` 的 receipt 没带 `dry_run` 字段，`verify_delivery()` 的 `dry_run is not False` 判定对缺省值失效。
   修复：run() 交付后显式写 `state['delivery']['dry_run']`。回归锚：test_08（dry-run→resume 真实落位→再 resume 复用）。
2. **folder 交付 receipt 记录暂存目录路径**，`os.replace` 后全部成死指针 → resume 永远误判不可复用。
   修复：replace 后按最终路径重新 `verify_png` 生成 evidence。回归锚：test_11。
3. **`reusable()` 把 files 的证据 dict 当路径字符串**（TypeError 被吞成 False）。
   修复：按 evidence dict 读 `path` 并 `verify_png`，保留旧格式兼容分支。
4. **证据 hash 校验错误码** 由底层 `EVIDENCE_HASH_MISMATCH` 冒泡，统一为 `RESUME_MISMATCH`；manifest 增补 `root`、`frozen_config`、`frozen_site`（真实落盘文件 + hash）。
5. **frozen 指纹含绝对路径** → 同一项目经 `/var` 与 `/private/var` 打开无法 resume。
   修复：frozen 只留内容 hash；site 文件引用改 root 相对；路径比较统一 `.resolve()`。
6. **`navigate_and_capture` 污染进程级 `TMPDIR`** → 同进程后续 Playwright 启动 ENOENT / asyncio loop 冲突。
   修复：`run()` 包 try/finally 恢复环境。这是「30 项合跑全挂、单跑全过」的根因。
7. **`file://` 起始 URL 被当相对路径再拼 root** → `ERR_FILE_NOT_FOUND`。
   修复：按 RFC scheme 判定，绝对 URL 原样使用。
8. **lark-cli 拒绝绝对 `--file` 路径** → 默认 runner 绑定 cwd 到截图目录，`--file ./<region>.png`；注入的 mock runner 签名不变。
9. **测试基础设施**：补 `tests/__init__.py`（无包发现会遮蔽 stdlib `unittest`）；`import unittest.mock`；4 处断言改 `.resolve()` 比较；test_06 用符号链接复用已装 Chromium，不放宽 `project_path` 安全约束。

## 读回实证

```
图片锚点: ['C5', 'D5']   图片数: 2
源表 hash: manifest 392cad044784c968 == 实际 392cad044784c968 → True
gender (960, 285)  audience (960, 286)
resumed: true ×2；产物 mtime 前后一致 → PASS: 复用未重写
```

## 明确未验证（不得写成通过）

- Windows / PowerShell：本机无 pwsh，仅静态审阅。
- 飞书 Base 真实写入：仅 dry-run；`--execute-local` 对 base 仍拒绝，需独立授权门 + M2C 读回契约。
- 星图等真实业务站点、OpenCLI 可选驱动、各 AI 客户端实测：均未激活。
- 遮挡检测为有限采样，不声称零漏检。

## 复跑命令

```bash
cd /path/to/web-region-capture
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t . -p 'test_*.py' -v
PYTHONPATH=src .venv/bin/python -m web_region_capture run --config config/tasks.m2d-e2e.json --run-id m2d-e2e --resume --execute-local
```
