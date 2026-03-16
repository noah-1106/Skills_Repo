#!/bin/bash

# notify_agent.sh - 通知 Agent 执行子任务

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASKS_DIR="${SCRIPT_DIR}/tasks"

# 日志目录（约定）
LOGS_DIR="${SCRIPT_DIR}/longtask_log"
mkdir -p "$LOGS_DIR"

# 检查参数
if [ $# -lt 2 ]; then
    echo "Usage: $0 <task_name> <step_id>"
    echo "Example: $0 batch_writing 1"
    exit 1
fi

TASK_NAME="$1"
STEP_ID="$2"
TASK_FILE="${TASKS_DIR}/${TASK_NAME}.json"

# 检查任务文件
if [ ! -f "$TASK_FILE" ]; then
    echo "Error: Task file not found: $TASK_FILE"
    exit 1
fi

# 读取任务信息
TASK_ID=$(jq -r '.task_id' "$TASK_FILE")
STEP_NAME=$(jq -r ".steps[] | select(.id == $STEP_ID) | .name" "$TASK_FILE")
PARAMS=$(jq -r ".steps[] | select(.id == $STEP_ID) | .params // {}" "$TASK_FILE")

# 读取 Agent 配置
AGENTS_CONFIG="${SCRIPT_DIR}/agents.json"
if [ ! -f "$AGENTS_CONFIG" ]; then
    echo "Error: Agents config not found: $AGENTS_CONFIG"
    exit 1
fi

# 从 task 文件的当前 step 获取 agent_id
AGENT_ID=$(jq -r ".steps[] | select(.id == $STEP_ID) | .agent_id // \"bibi\"" "$TASK_FILE")
SESSION_NAME=$(jq -r ".steps[] | select(.id == $STEP_ID) | .session_name // \"main\"" "$TASK_FILE")

# 从 agents.json 数组中查找 agent_name
AGENT_NAME=$(jq -r ".agents[] | select(.agent_id == \"$AGENT_ID\") | .agent_name // \"$AGENT_ID\"" "$AGENTS_CONFIG")

# 如果找不到，使用 agent_id 作为默认值
if [ -z "$AGENT_NAME" ] || [ "$AGENT_NAME" = "null" ]; then
    AGENT_NAME="$AGENT_ID"
fi

# 构建完整的 session ID（格式：agent:{agent_id}:{session_name}）
FULL_SESSION="agent:${AGENT_ID}:${SESSION_NAME}"

# 构建 complete_step.sh 的完整路径（使用脚本所在目录）
COMPLETE_STEP_CMD="${SCRIPT_DIR}/complete_step.sh"

# 读取任务描述
TASK_DESCRIPTION=$(jq -r '.description // ""' "$TASK_FILE")
TOTAL_STEPS=$(jq -r '.total_steps' "$TASK_FILE")

# 构建消息
MESSAGE=$(cat <<EOF
/new
【长程任务子任务】

重要提示：回调时必须使用 "任务标识"（即文件名）作为第一个参数！

任务标识: $TASK_NAME
步骤: $STEP_ID/$TOTAL_STEPS
任务描述: $TASK_DESCRIPTION
执行内容: $STEP_NAME

完成后必须执行:
$COMPLETE_STEP_CMD $TASK_NAME $STEP_ID success [output_path]

失败时执行:
$COMPLETE_STEP_CMD $TASK_NAME $STEP_ID failed

参数:
$PARAMS
EOF
)

# 缓冲5秒，防止重复触发
sleep 5

# 发送消息给 Agent
# 方式1: 通过 OpenClaw CLI 直接发送（优先）
CLI_SUCCESS=false
if command -v openclaw >/dev/null 2>&1; then
    # 使用 openclaw CLI 发送消息到指定 Agent 的指定 Session
    if openclaw agent --agent "$AGENT_ID" --session-id "$FULL_SESSION" --message "$MESSAGE" 2>/dev/null; then
        CLI_SUCCESS=true
    else
        echo "Failed to send via openclaw CLI, falling back to inbox"
    fi
fi

# 方式2: 写入 inbox 文件（CLI 失败或不可用时回退）
if [ "$CLI_SUCCESS" != "true" ]; then
    # inbox 文件路径（共享，所有 Agent 重启后读取恢复）
    INBOX_FILE="${SCRIPT_DIR}/agent_inbox.json"
    
    # 补丁 B：检查是否已存在相同任务（幂等性校验 + 格式校验）
    if [ -f "$INBOX_FILE" ]; then
        # 增加格式校验，防止 jq 报错崩溃
        if ! jq empty "$INBOX_FILE" 2>/dev/null; then
            echo "警告：Inbox 格式损坏，尝试备份并重建..."
            mv "$INBOX_FILE" "${INBOX_FILE}.bak.$(date +%s)"
        else
            # 增加幂等检查（带空值保护）
            EXISTING=$(jq -r "map(select(.task_id == \"$TASK_ID\" and .step_id == $STEP_ID and .status == \"pending\")) | length" "$INBOX_FILE" 2>/dev/null || echo 0)
            if [ "${EXISTING:-0}" -gt 0 ]; then
                echo "任务 $TASK_ID Step $STEP_ID 已在收件箱中。跳过投递。"
                exit 1 # 依然返回 1，让 Daemon 停机，等待 Agent 处理已有的任务
            fi
        fi
    fi
    
    # 原子性追加消息（包含 agent_id 用于过滤）
    ENTRY=$(jq -n \
        --arg timestamp "$(date -Iseconds)" \
        --arg agent_id "$AGENT_ID" \
        --arg session_name "$SESSION_NAME" \
        --arg full_session "$FULL_SESSION" \
        --arg task_id "$TASK_ID" \
        --argjson step_id "$STEP_ID" \
        --arg step_name "$STEP_NAME" \
        --arg params "$PARAMS" \
        --arg task_name "$TASK_NAME" \
        --arg message "$MESSAGE" \
        '{
            timestamp: $timestamp,
            agent_id: $agent_id,
            session_name: $session_name,
            full_session: $full_session,
            type: "execute_step",
            task_id: $task_id,
            task_name: $task_name,
            step_id: $step_id,
            step_name: $step_name,
            params: $params,
            message: $message,
            status: "pending"
        }')
    
    # 追加到 inbox（如果不存在则创建）
    if [ -f "$INBOX_FILE" ]; then
        jq ". + [$ENTRY]" "$INBOX_FILE" > "${INBOX_FILE}.tmp" && mv "${INBOX_FILE}.tmp" "$INBOX_FILE"
    else
        echo "[$ENTRY]" > "$INBOX_FILE"
    fi
    
    echo "Message written to inbox: $INBOX_FILE (agent_id: $AGENT_ID, session: $FULL_SESSION)"
    
    # CLI 失败时返回失败，触发重试机制
    exit 1
fi

# CLI 成功时继续执行
# 同时写入日志
LOG_FILE="${LOGS_DIR}/trigger.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Triggered step $STEP_ID: $STEP_NAME" >> "$LOG_FILE"

echo "Notification sent for step $STEP_ID"
