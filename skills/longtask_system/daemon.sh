#!/bin/bash

# LongTask System Daemon
# 每15秒检查任务状态，触发下一个待执行的子任务

set -euo pipefail

# 配置
INTERVAL=${INTERVAL:-15}           # 检查间隔（秒）
TIMEOUT_MINUTES=${TIMEOUT:-5}      # 子任务超时时间（分钟），默认5分钟
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 日志目录（约定：所有日志文件放在 longtask_log/ 子目录）
LOGS_DIR="${SCRIPT_DIR}/longtask_log"
mkdir -p "$LOGS_DIR"

# 任务目录（约定：所有任务文件放在 tasks/ 子目录）
TASKS_DIR="${SCRIPT_DIR}/tasks"
mkdir -p "$TASKS_DIR"

# 检查参数
if [ $# -lt 1 ]; then
    echo "Usage: $0 <task_name>"
    echo "Example: $0 batch_writing"
    echo ""
    echo "Note: Task files should be placed in: ${TASKS_DIR}/"
    exit 1
fi

TASK_NAME="$1"
TASK_FILE="${TASKS_DIR}/${TASK_NAME}.json"

# 检查文件存在
if [ ! -f "$TASK_FILE" ]; then
    echo "Error: Task file not found: $TASK_FILE"
    echo ""
    echo "Available tasks:"
    ls -1 "${TASKS_DIR}"/*.json 2>/dev/null | xargs -n1 basename -s .json | sed 's/^/  - /' || echo "  (none)"
    exit 1
fi

# 每个任务独立的日志文件 + 全局 daemon 日志
TASK_LOG="${LOGS_DIR}/task_${TASK_NAME}.log"
LOG_FILE="${LOGS_DIR}/daemon.log"

# 日志函数（同时写入全局 daemon.log 和独立 task 日志）
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg" >> "$LOG_FILE"
    echo "$msg" >> "$TASK_LOG"
}

# 原子性更新状态文件
update_state() {
    local file="$1"
    local jq_expr="$2"
    local tmp_file="${file}.tmp.$$"
    
    # 执行 jq 表达式，输出到临时文件
    if jq "$jq_expr" "$file" > "$tmp_file" 2>/dev/null; then
        # 原子性替换
        mv "$tmp_file" "$file"
        # 触发驾驶舱渲染
        render_cockpit "$file"
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

# 检查任务是否超时
check_timeout() {
    local start_time="$1"
    local timeout_minutes="$2"
    
    # 将 ISO 时间转换为 Unix 时间戳
    local start_epoch
    start_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$start_time" +%s 2>/dev/null || \
                  date -d "$start_time" +%s 2>/dev/null || \
                  echo "0")
    
    if [ "$start_epoch" = "0" ]; then
        return 1  # 解析失败，不认为超时
    fi
    
    local timeout_epoch=$((start_epoch + timeout_minutes * 60))
    local now_epoch=$(date +%s)
    
    if [ "$now_epoch" -gt "$timeout_epoch" ]; then
        return 0  # 超时
    else
        return 1  # 未超时
    fi
}

# 触发 Agent 执行子任务
trigger_agent() {
    local task_file="$1"
    local step_id="$2"
    
    # 读取任务信息
    local task_id step_name params agent_id session_name
    task_id=$(jq -r '.task_id' "$task_file")
    step_name=$(jq -r ".steps[] | select(.id == $step_id) | .name" "$task_file")
    params=$(jq -r ".steps[] | select(.id == $step_id) | .params // {}" "$task_file")
    agent_id=$(jq -r ".steps[] | select(.id == $step_id) | .agent_id // .agent_id // \"bibi\"" "$task_file")
    session_name=$(jq -r ".steps[] | select(.id == $step_id) | .session_name // .session_name // \"main\"" "$task_file")
    
    log "Triggering step $step_id: $step_name (agent: $agent_id, session: $session_name)"
    
    # 调用通知脚本（传递 task_name 而非完整路径）
    local task_name
    task_name=$(basename "$task_file" .json)
    
    if [ -x "${SCRIPT_DIR}/notify_agent.sh" ]; then
        "${SCRIPT_DIR}/notify_agent.sh" "$task_name" "$step_id" 2>&1 || {
            log "ERROR: Failed to notify agent for step $step_id"
            return 1
        }
    else
        log "ERROR: notify_agent.sh not found or not executable"
        return 1
    fi
    
    return 0
}

# 主检查循环
check_and_trigger() {
    local task_file="$1"
    
    # 读取当前任务状态
    local task_status updated_at
    task_status=$(jq -r '.status' "$task_file" 2>/dev/null || echo "error")
    updated_at=$(jq -r '.updated_at // ""' "$task_file" 2>/dev/null || echo "")
    
    # 检查状态文件是否可读
    if [ "$task_status" = "error" ]; then
        log "Error: Cannot read task file"
        exit 1
    fi
    
    # 检查状态文件是否超过20分钟未更新（防止僵尸daemon）
    if [ -n "$updated_at" ]; then
        local last_update_epoch now_epoch staleness
        last_update_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${updated_at%%+*}" +%s 2>/dev/null || date -d "$updated_at" +%s 2>/dev/null || echo "0")
        now_epoch=$(date +%s)
        if [ "$last_update_epoch" != "0" ]; then
            staleness=$((now_epoch - last_update_epoch))
            if [ "$staleness" -gt 1200 ]; then  # 20分钟 = 1200秒
                log "Error: Task state not updated for ${staleness}s (超过20分钟)，daemon 可能已僵死，退出"
                exit 1
            fi
        fi
    fi
    
    if [ "$task_status" != "running" ]; then
        log "Task status is '$task_status', not running. Exiting."
        exit 0
    fi
    
    # 检查是否有进行中的任务
    local doing_step doing_start
    doing_step=$(jq -r '.steps[] | select(.status == "doing") | .id' "$task_file" | head -1)
    
    if [ -n "$doing_step" ]; then
        # 检查是否超时
        doing_start=$(jq -r ".steps[] | select(.id == $doing_step) | .started_at" "$task_file")
        
        if check_timeout "$doing_start" "$TIMEOUT_MINUTES"; then
            log "Step $doing_step timeout! Marking as failed."
            update_state "$task_file" ".steps[$((doing_step-1))].status = \"failed\" | .steps[$((doing_step-1))].error = \"timeout\""
            
            # 检查重试次数（读取任务配置，默认0）
            local retry_count max_retry
            retry_count=$(jq -r ".steps[$((doing_step-1))].retry_count // 0" "$task_file")
            max_retry=$(jq -r '.max_retry // 0' "$task_file")
            
            if [ "$retry_count" -lt "$max_retry" ]; then
                log "Will retry step $doing_step (attempt $((retry_count+1))/$max_retry)"
                update_state "$task_file" ".steps[$((doing_step-1))].status = \"pending\" | .steps[$((doing_step-1))].retry_count = $((retry_count+1))"
            else
                # 重试次数用尽，标记任务失败并退出
                log "Step $doing_step failed after $max_retry retries. Task failed."
                update_state "$task_file" ".status = \"failed\" | .error = \"Step $doing_step timeout\" | .failed_at = \"$(date -Iseconds)\""
                exit 1
            fi
        else
            log "Step $doing_step still running..."
        fi
        return 0
    fi
    
    # 找到下一个 pending 或 failed（可重试）的任务
    local next_step max_retry
    next_step=$(jq -r '.steps[] | select(.status == "pending") | .id' "$task_file" | head -1)
    max_retry=$(jq -r '.max_retry // 0' "$task_file")
    
    # 如果没有 pending，找 failed 且重试次数未达到上限的
    if [ -z "$next_step" ]; then
        next_step=$(jq -r --arg max_retry "$max_retry" '.steps[] | select(.status == "failed" and (.retry_count // 0) < ($max_retry | tonumber)) | .id' "$task_file" | head -1)
        if [ -n "$next_step" ]; then
            log "Retrying failed step $next_step (retry count reset to 0)"
            # 将 failed 改回 pending，重置 retry_count 为 0（重新启动任务给予全新机会）
            update_state "$task_file" ".steps[$((next_step-1))].status = \"pending\" | .steps[$((next_step-1))].retry_count = 0"
        fi
    fi
    
    if [ -z "$next_step" ]; then
        # 没有可执行的步骤，检查是否有 failed 步骤（重试用尽）
        local failed_count done_count
        failed_count=$(jq -r '[.steps[] | select(.status == "failed")] | length' "$task_file")
        done_count=$(jq -r '[.steps[] | select(.status == "done")] | length' "$task_file")
        
        if [ "$failed_count" -gt 0 ]; then
            log "Task failed: $failed_count step(s) failed, $done_count step(s) done"
            update_state "$task_file" ".status = \"failed\" | .error = \"$failed_count step(s) failed\" | .failed_at = \"$(date -Iseconds)\""
            exit 1
        else
            # 所有步骤完成
            log "All steps completed! ($done_count steps)"
            update_state "$task_file" ".status = \"completed\" | .completed_at = \"$(date -Iseconds)\""
            exit 0
        fi
    fi
    
    # 获取步骤信息
    local step_name
    step_name=$(jq -r ".steps[] | select(.id == $next_step) | .name" "$task_file")
    
    log "Next step: $next_step - $step_name"
    
    # 更新状态为 doing
    update_state "$task_file" ".steps[$((next_step-1))].status = \"doing\" | .steps[$((next_step-1))].started_at = \"$(date -Iseconds)\" | .current_step = $next_step | .updated_at = \"$(date -Iseconds)\""
    
    # 触发 Agent
    if trigger_agent "$task_file" "$next_step"; then
        log "Step $next_step triggered successfully"
    else
        log "ERROR: Failed to trigger step $next_step, marking task as failed"
        # 标记步骤和任务为失败，并退出 daemon
        update_state "$task_file" ".steps[$((next_step-1))].status = \"failed\" | .steps[$((next_step-1))].error = \"trigger_failed\""
        update_state "$task_file" ".status = \"failed\" | .error = \"Failed to trigger step $next_step\" | .failed_at = \"$(date -Iseconds)\""
        exit 1
    fi
}

# 主循环
main() {
    log "=== Daemon started ==="
    log "Task file: $TASK_FILE"
    log "Check interval: ${INTERVAL}s"
    log "Timeout: ${TIMEOUT_MINUTES}min"
    
    # 设置任务为 running 状态
    if ! update_state "$TASK_FILE" ".status = \"running\" | .started_at = \"$(date -Iseconds)\"" 2>/dev/null; then
        log "Warning: Failed to update task status to running"
    fi
    
    # 主循环
    while true; do
        check_and_trigger "$TASK_FILE"
        sleep "$INTERVAL"
    done
}

# 信号处理
trap 'log "Daemon terminated"; exit 0' SIGTERM SIGINT

main "$@"
