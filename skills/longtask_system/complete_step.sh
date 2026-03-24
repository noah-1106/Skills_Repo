#!/bin/bash

# complete_step.sh - 标记子任务完成

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TASKS_DIR="${SCRIPT_DIR}/tasks"

# 日志目录（约定）
LOGS_DIR="${SCRIPT_DIR}/longtask_log"
mkdir -p "$LOGS_DIR"

# 检查参数
if [ $# -lt 3 ]; then
    echo "Usage: $0 <task_name> <step_id> <success|failed> [output_path] [error_message]"
    echo "Example: $0 batch_writing 1 success articles/2026-03-13/article1.md"
    exit 1
fi

TASK_NAME="$1"
STEP_ID="$2"
RESULT="$3"
OUTPUT_PATH="${4:-}"
ERROR_MSG="${5:-}"

# 查找任务文件
TASK_FILE="${TASKS_DIR}/${TASK_NAME}.json"

if [ ! -f "$TASK_FILE" ]; then
    echo "Error: Task file not found: $TASK_FILE"
    exit 1
fi

# 读取当前全局重试次数和状态
GLOBAL_RETRY=$(jq -r '.global_retry // 0' "$TASK_FILE")
CURRENT_STATUS=$(jq -r '.status' "$TASK_FILE")

# 原子性更新函数
update_step() {
    local file="$1"
    local jq_expr="$2"
    local tmp_file="${file}.tmp.$$"

    if jq "$jq_expr" "$file" > "$tmp_file" 2>/dev/null; then
        mv "$tmp_file" "$file"
        return 0
    else
        rm -f "$tmp_file"
        return 1
    fi
}

# 渲染驾驶舱 UI
render_cockpit() {
    local task_file="$1"
    local renderer="${SCRIPT_DIR}/cockpit_renderer.py"

    # 如果渲染器存在，则调用
    if [ -f "$renderer" ] && command -v python3 >/dev/null 2>&1; then
        python3 "$renderer" "$task_file" >/dev/null 2>&1 &
    fi
}

# 构建更新表达式（使用 select(.id == $STEP_ID) 定位，而非数组索引）
JQ_EXPR="(.steps[] | select(.id == $STEP_ID)).status = \"done\""
JQ_EXPR="$JQ_EXPR | (.steps[] | select(.id == $STEP_ID)).result = \"$RESULT\""
JQ_EXPR="$JQ_EXPR | (.steps[] | select(.id == $STEP_ID)).completed_at = \"$(date -Iseconds)\""
JQ_EXPR="$JQ_EXPR | (.steps[] | select(.id == $STEP_ID)).processed_by = \"agent_fallback\""
JQ_EXPR="$JQ_EXPR | .updated_at = \"$(date -Iseconds)\""

if [ -n "$OUTPUT_PATH" ]; then
    JQ_EXPR="$JQ_EXPR | (.steps[] | select(.id == $STEP_ID)).output_path = \"$OUTPUT_PATH\""
fi

if [ -n "$ERROR_MSG" ]; then
    JQ_EXPR="$JQ_EXPR | (.steps[] | select(.id == $STEP_ID)).error = \"$ERROR_MSG\""
fi

# 补丁 A 增强版：自动复苏逻辑（带重试上限保护）
if [ "$RESULT" == "success" ] && [ "$CURRENT_STATUS" == "failed" ]; then
    if [ "$GLOBAL_RETRY" -lt 3 ]; then
        # 在阈值内，自动复苏
        JQ_EXPR="$JQ_EXPR | .status = \"pending\" | .error = null | .global_retry = $((GLOBAL_RETRY + 1))"
        echo "检测到任务复苏（第 $((GLOBAL_RETRY + 1))/3 次），已重置全局状态为 pending。"
    else
        # 超过阈值，保持 failed，提醒手动检查
        echo "警告：任务已失败超过 3 次，不再自动复苏。请手动检查任务状态。"
    fi
fi

# 执行更新
if update_step "$TASK_FILE" "$JQ_EXPR"; then
    echo "Success"

    # 触发驾驶舱渲染（步骤完成后更新UI）
    render_cockpit "$TASK_FILE"

    # 记录独立任务日志
    TASK_LOG="${LOGS_DIR}/task_${TASK_NAME}.log"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Step $STEP_ID: $RESULT (global_retry: ${GLOBAL_RETRY})" >> "$TASK_LOG"

    exit 0
else
    echo "Failed, refer to the logs"
    exit 1
fi
