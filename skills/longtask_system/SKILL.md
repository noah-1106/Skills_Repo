---
name: longtask_system
version: 1.2.0
description: |
  长程任务执行管理系统 | Long-running Task Execution Management System
  通过状态文件驱动，将长任务拆分为子任务，由守护进程按顺序触发执行，确保每步完成后再执行下一步。
  State-file driven system that breaks long tasks into subtasks, triggered sequentially by daemon to ensure each step completes before next.
  支持多 Agent 协作 | Multi-Agent collaboration supported.
  新增可视化驾驶舱 | Visual Cockpit for real-time monitoring.

重要：为了确保长程任务执行的效果，每一个子任务会强制通过/new重置对话后执行！如果你是单agent模式，可以在notify_agent.sh脚本中的消息构建删除/new命令。如果是多agent模式，请尽量确保你的任务中仅包含执行agent，不要包含监督agent。

---

# LongTask System - 长程任务执行管理

**核心原则**：保持自动化运行。任一环节断链（Agent 离线、CLI 失败等）都会打断自动化流程并标记任务失败。为此引入 Agent Inbox 作为 fallback 机制，支持原子级进度记录和崩溃后重启续做。

解决长任务执行中的"睡着"、跳步、上下文丢失问题。

## 核心机制

```
daemon.sh ──▶ task_state.json ──▶ Agent 执行 ──▶ complete_step.sh ──▶ 下一任务
   ▲                                                    │
   └────────────────── 状态更新 ────────────────────────┘
```

1. **daemon.sh** 每15秒检查任务状态
2. 发现 `pending` 子任务 → 标记为 `doing` → 通知 Agent（CLI 或 inbox）
3. **Agent** 执行任务 → 调用 `complete_step.sh` 标记完成
4. daemon 触发下一任务

## 文件结构

```
longtask_system/
├── daemon.sh          # 守护进程
├── notify_agent.sh    # 通知 Agent（CLI/inbox 双模式）
├── consume_inbox.sh   # Agent 读取并删除 inbox 任务
├── complete_step.sh   # 标记任务完成
├── cockpit_renderer.py # 可视化驾驶舱生成器 (Cockpit Visualizer) ⭐ NEW
├── agents.json        # Agent 配置
├── agent_inbox.json   # 消息收件箱（CLI 失败时备用）
├── task_template.json # 任务模板
├── tasks/             # 任务文件目录
└── longtask_log/      # 日志目录
```

## 快速开始

### 1. 配置 Agent

编辑 `agents.json`：

```json
{
  "agents": [
    {"agent_id": "bibi", "agent_name": "笔笔"},
    {"agent_id": "tutu", "agent_name": "图图"}
  ]
}
```

### 2. 创建任务

```bash
cp task_template.json tasks/my_task.json
# 编辑：定义 steps 数组，指定 agent_id
```

### 3. 启动守护进程

```bash
# 方案1: screen（推荐，跨平台，可恢复查看）
screen -d -m -S longtask bash daemon.sh my_task

# 方案2: setsid（Linux 环境）
setsid bash daemon.sh my_task > longtask_log/daemon.log 2>&1 &

# 或前台调试
./daemon.sh my_task
```

**注意**：OpenClaw 等 Agent 框架在 session 结束时会清理子进程，必须使用 `screen` 或 `setsid` 确保 daemon 不被杀掉。

### 4. Agent 消费任务

**方式1：CLI 直接通知**（正常流程）
- Agent 收到消息 → 执行任务
- **回调时必须使用任务标识（文件名）**：`./complete_step.sh 任务名 step_id success`

**方式2：Inbox 消费**（崩溃恢复/CLI 失败）

```bash
# 读取并删除自己的 pending 任务（原子操作）
TASK_JSON=$(./consume_inbox.sh bibi)

if [ -n "$TASK_JSON" ]; then
    # 解析任务信息
    TASK_NAME=$(echo "$TASK_JSON" | jq -r '.task_name')
    STEP_ID=$(echo "$TASK_JSON" | jq -r '.step_id')
    
    # 执行任务...
    
    # 标记完成
    ./complete_step.sh "$TASK_NAME" "$STEP_ID" success
fi
```

**关键**：`consume_inbox.sh` 是**读取即删除**，防止重复消费。

## 任务定义

```json
{
  "task_id": "batch_writing_20260313",
  "description": "批量写作15篇文章",
  "status": "running",
  "total_steps": 15,
  "agent_id": "bibi",
  "session_name": "main",
  "max_retry": 0,
  "steps": [
    {
      "id": 1,
      "name": "文章1：伊朗警告美国科技公司",
      "status": "pending",
      "params": {"topic": "...", "fingerprint": "..."}
    }
  ]
}
```

### 关键字段

| 字段 | 说明 | 默认 |
|------|------|------|
| `agent_id` | 执行 Agent | - |
| `session_name` | Session 名称 | `main` |
| `max_retry` | 单步骤失败重试次数 | `0`（不重试）|
| `global_retry` | 全局自动复苏次数（离线恢复用）| `0`（最多3次）|
| `steps[].status` | `pending`/`doing`/`done`/`failed` | - |

### 状态流转

```
子任务: pending ──▶ doing ──▶ done
                    │
                    ▼ (超时或失败)
                  failed ──▶ pending (重试，若 retry < max_retry)
                    │
                    ▼ (重试用尽)
                  任务标记 failed，daemon 退出
```

**超时**：`doing` 状态默认 **5分钟** 超时（环境变量 `TIMEOUT` 可调）。

**断点续传**：重启任务时（`status` 改回 `running`）：
- `done` → 跳过
- `failed` → 重置 retry_count 为 0，重新尝试
- `pending` → 执行

## 多 Agent 协作

Session ID 格式：`agent:{agent_id}:{session_name}`

示例：`agent:bibi:main`、`agent:tutu:main`

在任务中指定 `agent_id` 即可分配给不同 Agent。

## 关键设计

### 1. 原子写入

```bash
jq '...' state.json > tmp.json && mv tmp.json state.json
```

### 2. 防重复消费

- CLI 成功：直接送达 Agent
- CLI 失败：写入 inbox，Agent 用 `consume_inbox.sh` **读取即删除**

### 3. Fail-Stop 闭环（任务复苏）

CLI 投递失败时的处理流程：

```
1. CLI 失败 → 写入 Inbox → daemon 标记 failed → daemon 自杀
2. Agent 重启 → consume_inbox.sh → 执行任务 → complete_step.sh
3. 自动复苏：子任务成功时，若全局状态为 failed，自动重置为 pending
4. 重启 daemon → 继续执行
```

**防重保护**：`notify_agent.sh` 写入 Inbox 前检查是否已存在相同任务，避免重复投递。

**全局重试上限**：`global_retry` 字段记录自动复苏次数，超过 3 次不再自动重置，需手动检查。

## 调试

```bash
tail -f longtask_log/daemon.log              # 全局守护进程日志
tail -f longtask_log/task_任务名.log         # 单个任务的独立日志
tail -f longtask_log/trigger.log             # 任务触发日志
cat agent_inbox.json | jq                    # 检查 inbox
cat tasks/任务名.json | jq                   # 检查任务状态
```

---

## 🎨 Cockpit 可视化驾驶舱 / Visual Cockpit ⭐ NEW

实时监控任务执行状态的可视化界面。

### 功能特性 | Features

- 🐕 **萌宠主题** - Pet Workshop 可爱风格，缓解等待焦虑
- 🔄 **实时刷新** - 每 3 秒自动更新状态
- 📊 **进度可视化** - 果酱流动效果进度条
- 🎭 **状态动画** - 不同状态对应不同小动物动画:
  - 🐱 `done` - 猫咪满意
  - 🐕 `doing` - 小狗挖土（摇摆动画）
  - 💤 `pending` - 小猫睡觉（呼吸动画）
  - 👻 `failed` - 小鬼出现

### 自动生成

Cockpit 会在以下情况自动生成/更新：
- 任务状态变更时（daemon 自动触发）
- 手动运行: `python3 cockpit_renderer.py tasks/任务名.json`

### 查看驾驶舱

```bash
# 生成后打开浏览器查看
open tasks/cockpit.html
```

### 截图预览 / Screenshot

See preview in [GitHub README](https://github.com/noah-1106/Skills_Repo#longtask_system)

---

## 注意事项


1. **不要手动修改** `doing` 状态的任务
2. **默认不重试**：`max_retry` 默认为 0，失败即停
3. **超时时间**：默认 5分钟，可通过环境变量 `TIMEOUT` 调整
4. **daemon 自动退出**：状态文件超过 20 分钟未更新时退出

## 更新日志

- **v1.2** (2026-03-17)
  - 新增 `cockpit_renderer.py` 可视化驾驶舱，萌宠主题设计
  - 修复 daemon 在 OpenClaw 环境下被 session 杀掉的问题（使用 screen/setsid）
  - 优化 agent_id 读取逻辑，支持 step 级别覆盖
  - 优化驾驶舱 Agent 显示，正确显示 step 级 agent_id

- **v1.1** (2026-03-13)
  - 新增 `consume_inbox.sh`，实现读取即删除
  - 新增多 Agent 支持
  - 新增 agents.json 配置

- **v1.0** (2026-03-12)
  - 初始版本
