# GeoPulse v2 部署与运维

## 1. 部署基线

推荐单台受控主机、单 Uvicorn 进程、本地或受控磁盘上的 SQLite。生产由 HTTPS 反向代理暴露服务，数据库、secret store、备份和导出目录只允许运行账号访问。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt

export GEOPULSE_DB=/srv/geopulse/data/geopulse.db
export GEOPULSE_SECRETS=/srv/geopulse/private/secrets.json
export GEOPULSE_CONFIG=/srv/geopulse/private/legacy-config.json
export GEOPULSE_BACKUP_DIR=/srv/geopulse/backups
export GEOPULSE_EXPORT_DIR=/srv/geopulse/exports
export GEOPULSE_WORKERS=4

.venv/bin/python scripts/geopulse_ctl.py init
.venv/bin/python backend/run.py --host 127.0.0.1 --port 8700
```

首次初始化在终端显示一次性管理员密码。立即登录并更换：

```bash
.venv/bin/python scripts/geopulse_ctl.py set-admin-password admin@geopulse.local
```

不要用多个独立 Uvicorn worker 进程共享这个内置队列来扩容。当前架构是单节点；需要多节点、高可用或分布式队列时应另行设计，而不是直接增加进程数。

## 2. 文件与权限

| 内容 | 默认位置 | 建议权限 |
|---|---|---|
| SQLite | `backend/geopulse.db` | 0600，运行账号所有 |
| SQLite WAL/SHM | 同目录 | 同数据库，备份期间不要手工复制单个文件 |
| 密钥 | `backend/secrets.json` | 0600 |
| 可选旧引擎配置 | `backend/config.json` | 0600 |
| DB 备份 | `backend/backups/` | 0700 目录，0600 文件 |
| 项目导出 | `outputs/` | 按客户资料保护 |

不要在 issue、聊天、前端、日志或报告中粘贴密钥。数据库备份不保存明文 Provider key；如需灾难恢复真实引擎，secret store 必须通过独立加密备份渠道保存。项目 JSON 导出也不含密钥。

旧 `backend/config.json` 只用于导入 OpenAI-compatible 引擎配置，不导入旧回答。没有旧配置时，将 `GEOPULSE_CONFIG` 指向不存在的路径可禁用导入。

## 3. 健康检查与真实付费调用

应用存活：

```bash
curl --fail http://127.0.0.1:8700/api/health
```

响应包含程序和 schema 版本。引擎健康检查与存活检查不同：非 demo 引擎会向厂商发起真实请求，可能收费，API 必须带 `{"confirm":true}`，UI 会再次确认。

真实 smoke 执行前逐项确认：

1. 使用隔离测试项目，不混入正式客户指标；
2. 引擎 Base URL、模型 ID、密钥归属和账号额度；
3. memory/search、Provider API 测量目标；
4. prompt 数、轮次、Search/Chat/Judge 调用次数；
5. 当前价格规则和最大可能费用；
6. 超时结果不明时不自动重放。

CI、pytest、浏览器 smoke 和 2700 压力脚本均不执行真实付费调用。Kimi Search 合同 mock 通过不等于外部账号 live smoke 通过。

## 4. 队列与调度

默认应用内启动 4 个 worker 和 scheduler。每引擎独立限流，不同引擎可并行。

- 进程重启恢复 queued/running/judging。
- 已有原文的样本只恢复 Judge，不重复 Provider 请求。
- 可安全重试错误最多按 Wave 协议自动重试；超时等结果不明错误需管理员重试。
- 活跃 Run 未结束时，调度器不会为同一 Wave 重复入队。
- 正式 Run 仍由管理员人工指定，调度不会自动替换。

只运行独立 worker 时，可先以 `GEOPULSE_DISABLE_WORKER=1` 启动 Web，再运行：

```bash
.venv/bin/python scripts/geopulse_ctl.py run-worker
```

这仍是同一单节点部署方式；不要让多个独立调度器同时处理同一数据库。

## 5. 备份

在线一致性备份使用 SQLite backup API：

```bash
.venv/bin/python scripts/geopulse_ctl.py backup
```

输出包含源路径、备份路径、schema 版本、UTC 时间和 SHA-256；同目录生成 `.manifest.json`。也可在“系统管理 → 设置与数据治理”创建备份并下载 manifest。

建议：

- 内部开发基线：RPO 24h、RTO 4h，不构成客户 SLA。
- 至少每天备份，并将副本放到不同故障域。
- 对备份文件和 manifest 设置 0600。
- 备份失败应告警，不能把“命令曾执行”当作可恢复证明。
- 定期执行恢复演练并记录实际 RPO/RTO。
- 原始回答默认不自动删除；保留策略变化需按客户合同单独配置。

校验示例：

```bash
shasum -a 256 /path/to/backup.db
```

将结果与 manifest 的 `sha256` 比较。当前 restore 命令检查 schema，但不会替人工判断备份是否选错；恢复前必须核对项目、时间和 checksum。

## 6. 恢复演练与正式恢复

恢复会覆盖目标数据库。先停止 Web、worker 和 scheduler 的全部写入，再操作。不要对正在写的生产库直接试验。

### 隔离演练

```bash
export GEOPULSE_DB=/srv/geopulse/recovery-drill/geopulse.db
export GEOPULSE_SECRETS=/srv/geopulse/recovery-drill/secrets.json
export GEOPULSE_BACKUP_DIR=/srv/geopulse/recovery-drill/backups

.venv/bin/python scripts/geopulse_ctl.py restore /path/to/backup.db --yes
.venv/bin/python backend/run.py --host 127.0.0.1 --port 8710 --no-worker
```

检查项目数、正式 Run、回答/observation 数、报告快照和权限，再停止演练服务。`--no-worker` 避免演练库继续执行队列或真实请求。

### 正式恢复

1. 停止所有写入并保留当前故障库的额外备份。
2. 核对备份 manifest、schema 和 SHA-256。
3. 用 `GEOPULSE_DB` 明确指向目标库执行 restore。
4. 如 secret store 也需恢复，从独立加密备份恢复并设置 0600。
5. 先以 `--no-worker` 启动并验证。
6. 确认没有不应重放的真实调用后，再恢复正常 worker/scheduler。
7. 记录恢复人、时间、备份 checksum、验证结果和实际 RPO/RTO。

## 7. 迁移

```bash
.venv/bin/python scripts/geopulse_ctl.py migrate
```

当前干净 v2 schema 的 `PRAGMA user_version=1`。程序拒绝静默打开未知旧版本或更新版本。未来迁移必须先备份、按顺序执行并记录 checksum；本版本不迁移旧 v1 回答数据。

## 8. 项目导出与删除

```bash
.venv/bin/python scripts/geopulse_ctl.py export 1 --out /secure/path/project-1.json
.venv/bin/python scripts/geopulse_ctl.py delete-project 1 --confirm '完整项目名'
```

导出包含 schema、项目业务表、导出时间和 SHA-256，不含 secret store。删除会级联删除该项目业务数据；已有备份不会被自动删除，需按保留策略处理。UI 删除要求输入完整项目名。

## 9. 日志、成本与告警

HTTP 结构化日志包含 request ID、方法、路径、状态和延迟。业务表保存 project/wave/run 关联，调用记录保存类型、模型、usage、延迟、成本和错误。

- 不在日志中输出 API key、密码、session token。
- reviewer/viewer 响应隐藏原始回答、内部成本和内部错误细节。
- 成本按 answer/judge/search 分列；未知价格不按零成本。
- 默认预算只提醒；显式硬限额需要管理员另行开启。
- Run partial/failed 会生成告警，缺失样本始终不能转成零提及。

## 10. 故障排查

| 症状 | 检查 | 下一步 |
|---|---|---|
| 端口已占用 | `lsof -nP -iTCP:8700 -sTCP:LISTEN` | 识别进程；不要批量杀未知进程，可改用 `--port` |
| 401 | 会话过期、密码已更换 | 重新登录 |
| 403 CSRF | 页面令牌过期 | 刷新并重新登录 |
| Run 全部失败 | 引擎错误类型、模型、Base URL、账号额度 | 修正配置后由管理员明确重试 |
| Search 失败 | Search operation 与错误前缀 | 不用 memory 补位，检查检索权限与协议 |
| Judge 降级 | `judge_fallback_rate`、JSON/证据错误 | 复核 pending 样本，黄金集通过后再升级 Judge |
| 对比被拒绝 | mismatches、pair/sample completeness | 使用同口径正式 Run，不能事后放宽冻结阈值 |
| PDF 失败 | Chrome/Chromium 是否安装 | 设置 `CHROME_PATH` 后重试 |
| 数据库锁定 | 多写入进程、长事务、磁盘状态 | 保持单节点写入，检查慢操作与磁盘 |

## 11. 安全更新

```bash
.venv/bin/pip-audit -r requirements-dev.txt
.venv/bin/python scripts/check_vendor.py
.venv/bin/python -m pytest -q
```

CI 还执行前端 ESM、真实浏览器、黄金集、模拟压力和 secret scanning。更新 ECharts 时必须同步版本、来源、许可证和 SHA-256，不要无记录替换 minified 文件。
