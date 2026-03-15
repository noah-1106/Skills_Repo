#!/bin/bash
#
# consume_inbox.sh - Agent 消费 inbox 中的任务
# 
# 功能：
#   1. 读取当前 Agent 的 pending 任务
#   2. 从 inbox 中删除该条目（防止重复消费）
#   3. 输出任务内容供 Agent 处理
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INBOX_FILE="${SCRIPT_DIR}/agent_inbox.json"

# Agent 身份（从环境变量或参数获取）
AGENT_ID="${1:-${AGENT_ID:-bibi}}"

# 检查 inbox 文件
if [ ! -f "$INBOX_FILE" ]; then
    echo "无 inbox 文件"
    exit 1
fi

# 查找当前 Agent 的第一个 pending 任务
TASK_ENTRY=$(jq -c ".[] | select(.agent_id == \"$AGENT_ID\" and .status == \"pending\")" "$INBOX_FILE" | head -1)

if [ -z "$TASK_ENTRY" ] || [ "$TASK_ENTRY" = "null" ]; then
    echo "无待处理任务"
    exit 1
fi

# 获取任务标识（用于删除）
TASK_TIMESTAMP=$(echo "$TASK_ENTRY" | jq -r '.timestamp')
TASK_STEP_ID=$(echo "$TASK_ENTRY" | jq -r '.step_id')

# 原子删除该条目（通过反向选择过滤掉已消费的任务）
tmp_file="${INBOX_FILE}.tmp.$$"
jq --arg ts "$TASK_TIMESTAMP" \
   --arg aid "$AGENT_ID" \
   --argjson sid "$TASK_STEP_ID" \
   'map(select(.timestamp == $ts and .agent_id == $aid and .step_id == $sid | not))' \
   "$INBOX_FILE" > "$tmp_file" && mv "$tmp_file" "$INBOX_FILE"

# 输出任务内容给 Agent
echo "$TASK_ENTRY"
