# 当前测试状态

## 置顶（2026-11-02 M2D）：全量离线回归 30/30 通过

```bash
cd /path/to/web-region-capture
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t . -p 'test_*.py' -v
# Ran 30 tests in ~10s ... OK（exit=0，0 跳过）
```
日志：`evidence/m2d-full-unittest-final.log`（项目正本）。构成：M2 产品 14 项 + M1 离线 POC 8 项 + M1 区域纯度 8 项。
真实 CLI 端到端（dry-run → resume --execute-local → 再 resume 幂等）通过，产物 `outputs/m2d-e2e-*`。
修复清单、根因与未验证边界见 `docs/M2D-REPORT.md`。

**仍未验证**：Windows/PowerShell（无 pwsh）、飞书 Base 真实写入（仅 dry-run）、星图真实站点、OpenCLI 驱动、各 AI 客户端实测。

## 0. M1 区域纯度修复：16/16 本地回归通过

新增 8 项区域纯度回归：两种边界、浮动元素排除、显式交集阻断、外部覆盖层阻断、DOM 不变、缺失/歧义/不支持策略阻断。完整日志：`evidence/offline-poc-unittest.log`（项目正本）（`Ran 16 tests ... OK`）；激活清单与未激活项见 `evidence/offline-poc-summary.json`（项目正本）。

实现落在 `src/web_region_capture/region_purity.py`，旧公共入口 `capture.capture_regions()` 同样经过门禁，不是只修测试产物。遮挡检查为有限采样，不声称零漏检。

## 0.1 Wikipedia 首段复测：机器门禁与视觉复核通过（仅该页）

新 run：`data/runs/public-wikipedia-alan-turing-purity-v1/`。首段 PNG 为 590×203，视觉复核未混入信息框、文字完整；信息框 PNG 为 310×1257，完整无遮挡。保留两份 `*-purity-check.json`、`report.json`、`page-context.png` 及视觉复核记录。不是任意网站通用能力声明。

## 1. 离线组件回归：原 8 项仍通过

已激活：托管 Chromium 启动、HTML 搜索/身份断言、两区域截图、身份不符阻断、区域缺失阻断、区域歧义阻断、Excel 显式 C5/D5 锚点与读回、源工作簿不变、重复写入/非空目标/错误工作表阻断。

完整日志：`evidence/offline-poc-unittest.log`（项目正本）（`Ran 8 tests ... OK`）。

## 2. Wikipedia 真实公共网站 POC：功能通过，视觉纯净度部分通过

- 无需账号、密码、Cookie、Chrome 或 OpenCLI。
- 从 Wikipedia 首页搜索 `Alan Turing`，最终 URL 为 `https://en.wikipedia.org/wiki/Alan_Turing`，`#firstHeading` 身份断言一致。
- 截取 `table.infobox` 与首个有实质文本的可见段落，PNG 均成功生成并计算 SHA256。
- 写入新 Excel 的 `Wikipedia!C5` 与 `Wikipedia!D5`，读回两个锚点正确；源工作簿 hash 不变。
- 视觉检查：信息框完整，无明显遮挡/加载态；首段文本完整，但右侧带入了信息框上半截，**区域纯净度未全过，需要调整该站点的截图处方**，不能据此宣称任意网站视觉验收通过。

产物：`data/runs/public-wikipedia-alan-turing-v2/`；机器报告为同目录 `report.json`。

## 3. 飞书 Base：仅 dry-run

使用本机官方 `lark-cli 1.0.56` 和真实测试 PNG、占位 Base 坐标完成 dry-run，输出三步请求：验证附件字段、上传媒体、追加附件到目标单元格。没有真实上传或记录写入。证据：`evidence/lark-upload-dry-run-real-image.json`（项目正本）。

## 4. 尚未激活

星图真实站点、飞书真实 Base 写入、Windows 干净环境、OpenCLI 可选驱动、Codex/Claude Code/WorkBuddy 客户端实测。公共 POC 不能替代这些环境测试。

## 5. 对 Noah 当前所需输入

公共网站 POC 不需要任何账号或业务文件。继续产品化时，只需提供一个你想支持的公共网页、目标区域和期望单元格；若以后要测星图，再由你提供获授权账号并在浏览器中本人登录，账号密码始终不需要发给我。
