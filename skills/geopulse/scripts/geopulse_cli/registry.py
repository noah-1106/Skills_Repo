"""Declarative HTTP operations. Business rules stay in the FastAPI service."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Operation:
    command: tuple[str, ...]
    method: str
    path: str
    query: tuple[str, ...] = ()
    confirmation: str = ""
    download: str = ""
    description: str = ""
    path_params: dict[str, str] = field(default_factory=dict)


def operation(command, method, path, **kwargs):
    return Operation(tuple(command.split()), method, path, **kwargs)


OPERATIONS = [
    operation("auth login", "POST", "/api/auth/login", description="登录并保存 Bearer 会话"),
    operation("auth me", "GET", "/api/auth/me", description="查看当前账号"),
    operation("auth logout", "POST", "/api/auth/logout", description="注销并删除本机会话"),
    operation("auth password", "POST", "/api/auth/password", description="修改当前账号密码"),
    operation("project list", "GET", "/api/projects", description="列出可访问项目"),
    operation("project create", "POST", "/api/projects", description="创建客户项目"),
    operation("project get", "GET", "/api/projects/{project_id}", description="读取项目"),
    operation("project delete", "DELETE", "/api/projects/{project_id}", query=("confirm",), confirmation="delete", description="删除项目"),
    operation("project settings", "PUT", "/api/projects/{project_id}/settings", description="更新项目设置"),
    operation("project overview", "GET", "/api/projects/{project_id}/overview", description="读取项目总览"),
    operation("project export", "GET", "/api/projects/{project_id}/export", download="project", description="导出完整项目"),
    operation("prompt-set list", "GET", "/api/projects/{project_id}/prompt-sets", description="列出问题集版本"),
    operation("prompt-set create", "POST", "/api/projects/{project_id}/prompt-sets", description="创建问题集草稿"),
    operation("prompt-set get", "GET", "/api/projects/{project_id}/prompt-sets/{set_id}", description="读取问题集及条目"),
    operation("prompt-set import", "POST", "/api/projects/{project_id}/prompt-sets/{set_id}/items", description="导入 JSON 或 CSV 条目"),
    operation("prompt-set scaffold", "POST", "/api/projects/{project_id}/prompt-sets/scaffold/preview", description="预览候选问题，不自动入基线"),
    operation("prompt-set review", "POST", "/api/projects/{project_id}/prompt-sets/{set_id}/items/{item_id}/review", confirmation="review", description="审核问题条目"),
    operation("prompt-set status", "POST", "/api/projects/{project_id}/prompt-sets/{set_id}/status", description="变更问题集状态"),
    operation("prompt-set copy", "POST", "/api/projects/{project_id}/prompt-sets/{set_id}/copy", description="复制冻结版本为草稿"),
    operation("prompt-set diff", "GET", "/api/projects/{project_id}/prompt-sets/{set_id}/diff/{other_id}", description="比较两个问题集版本"),
    operation("prompt-set export", "GET", "/api/projects/{project_id}/prompt-sets/{set_id}/export", query=("format",), download="prompt", description="导出问题集 JSON/CSV"),
    operation("entity list", "GET", "/api/projects/{project_id}/entities", query=("include_history",), description="列出品牌实体"),
    operation("entity create", "POST", "/api/projects/{project_id}/entities", description="创建实体草稿"),
    operation("entity review", "POST", "/api/projects/{project_id}/entities/{entity_id}/review", confirmation="review", description="审核品牌实体"),
    operation("entity version", "POST", "/api/projects/{project_id}/entities/{entity_id}/versions", description="创建实体新版本"),
    operation("entity pool-diff", "GET", "/api/projects/{project_id}/entities/pool-diff", query=("before", "after"), description="比较实体池版本"),
    operation("wave list", "GET", "/api/projects/{project_id}/waves", description="列出 Wave 与 Run"),
    operation("wave create", "POST", "/api/projects/{project_id}/waves", description="冻结测量协议"),
    operation("wave get", "GET", "/api/projects/{project_id}/waves/{wave_id}", description="读取 Wave"),
    operation("wave run", "POST", "/api/projects/{project_id}/waves/{wave_id}/runs", confirmation="run", description="确认并创建 Run"),
    operation("wave official", "POST", "/api/projects/{project_id}/waves/{wave_id}/official", confirmation="approval", description="指定正式 Run"),
    operation("wave status", "POST", "/api/projects/{project_id}/waves/{wave_id}/status", description="标记 Wave 已分析或关闭"),
    operation("run get", "GET", "/api/projects/{project_id}/runs/{run_id}", description="读取 Run 与进度"),
    operation("run cancel", "POST", "/api/projects/{project_id}/runs/{run_id}/cancel", description="请求取消 Run"),
    operation("run retry", "POST", "/api/projects/{project_id}/runs/{run_id}/retry", confirmation="run", description="确认重试失败样本"),
    operation("run metrics", "GET", "/api/projects/{project_id}/runs/{run_id}/metrics", description="读取 Run 指标"),
    operation("run answers", "GET", "/api/projects/{project_id}/runs/{run_id}/answers", query=("status", "review", "limit", "offset"), description="列出回答"),
    operation("run wait", "GET", "/api/projects/{project_id}/runs/{run_id}", description="只轮询等待 Run 结束"),
    operation("answer get", "GET", "/api/projects/{project_id}/answers/{answer_id}", description="读取回答证据"),
    operation("answer revise", "POST", "/api/projects/{project_id}/answers/{answer_id}/observations/{observation_id}/revisions", confirmation="review", description="追加人工复核 revision"),
    operation("collection get", "GET", "/api/projects/{project_id}/answers/{answer_id}/collection", description="读取人工 Web 采集事实与证据元数据"),
    operation("collection save", "PUT", "/api/projects/{project_id}/answers/{answer_id}/collection/draft", description="保存可编辑人工采集草稿"),
    operation("collection submit", "POST", "/api/projects/{project_id}/answers/{answer_id}/collection/submit", confirmation="collection", description="确认并不可变提交人工采集"),
    operation("collection fail", "POST", "/api/projects/{project_id}/answers/{answer_id}/collection/fail", confirmation="collection", description="确认登记采集失败，样本不计零提及"),
    operation("collection resume", "POST", "/api/projects/{project_id}/answers/{answer_id}/collection/resume", confirmation="collection", description="恢复原网页会话或确认失败，不自动重发"),
    operation("browser-session list", "GET", "/api/projects/{project_id}/engines/{engine_id}/browser-sessions", description="列出目标的本机浏览器会话状态"),
    operation("browser-session create", "POST", "/api/projects/{project_id}/engines/{engine_id}/browser-sessions", description="创建授权浏览器会话并等待本机登录"),
    operation("browser-session verify", "POST", "/api/projects/{project_id}/browser-sessions/{session_id}/verify", description="请求验证用户已完成的网页登录"),
    operation("browser-session revoke", "POST", "/api/projects/{project_id}/browser-sessions/{session_id}/revoke", confirmation="collection", description="撤销会话并清理本机浏览器 profile"),
    operation("evidence upload", "POST", "/api/projects/{project_id}/answers/{answer_id}/attachments", query=("kind", "filename", "media_type"), description="上传原始截图或 HTML/文本证据"),
    operation("evidence download", "GET", "/api/projects/{project_id}/attachments/{attachment_id}", download="evidence", description="下载并校验证据字节"),
    operation("evidence delete", "DELETE", "/api/projects/{project_id}/attachments/{attachment_id}", confirmation="collection", description="确认删除尚未提交的草稿附件"),
    operation("compare", "GET", "/api/projects/{project_id}/compare", query=("baseline_wave", "current_wave"), description="检查同口径并比较 Wave"),
    operation("opportunity generate", "POST", "/api/projects/{project_id}/waves/{wave_id}/opportunities/generate", description="生成候选机会"),
    operation("opportunity list", "GET", "/api/projects/{project_id}/opportunities", query=("status",), description="列出机会"),
    operation("opportunity review", "POST", "/api/projects/{project_id}/opportunities/{opportunity_id}/review", confirmation="review", description="审核机会适用性"),
    operation("opportunity status", "POST", "/api/projects/{project_id}/opportunities/{opportunity_id}/status", confirmation="review", description="关闭机会并记录理由"),
    operation("opportunity action", "POST", "/api/projects/{project_id}/opportunities/{opportunity_id}/actions", description="创建 Action 草稿"),
    operation("action list", "GET", "/api/projects/{project_id}/actions", description="列出 Action"),
    operation("action status", "POST", "/api/projects/{project_id}/actions/{action_id}/status", confirmation="action", description="推进 Action 状态"),
    operation("event list", "GET", "/api/projects/{project_id}/events", description="列出外部事件"),
    operation("event create", "POST", "/api/projects/{project_id}/events", description="登记共时外部事件"),
    operation("report list", "GET", "/api/projects/{project_id}/reports", description="列出报告版本"),
    operation("report create", "POST", "/api/projects/{project_id}/reports", description="创建不可变报告快照"),
    operation("report get", "GET", "/api/projects/{project_id}/reports/{report_id}", description="读取报告与发布闸门"),
    operation("report status", "POST", "/api/projects/{project_id}/reports/{report_id}/status", confirmation="approval", description="推进报告审批或登记发送"),
    operation("report export", "GET", "/api/projects/{project_id}/reports/{report_id}/export", query=("variant", "format"), download="report", description="导出 HTML/PDF"),
    operation("engine list", "GET", "/api/projects/{project_id}/engines", description="列出引擎配置"),
    operation("engine create", "POST", "/api/projects/{project_id}/engines", description="创建引擎配置"),
    operation("engine update", "PUT", "/api/projects/{project_id}/engines/{engine_id}", description="更新引擎配置"),
    operation("engine health", "POST", "/api/projects/{project_id}/engines/{engine_id}/health", confirmation="health", description="预估并确认健康检查"),
    operation("user list", "GET", "/api/users", description="列出用户"),
    operation("user create", "POST", "/api/users", description="创建用户"),
    operation("member assign", "POST", "/api/projects/{project_id}/memberships", description="分配项目成员角色"),
    operation("member list", "GET", "/api/projects/{project_id}/memberships", description="列出项目成员"),
    operation("schedule list", "GET", "/api/projects/{project_id}/schedules", description="列出调度"),
    operation("schedule create", "POST", "/api/projects/{project_id}/schedules", description="创建调度"),
    operation("schedule update", "PUT", "/api/projects/{project_id}/schedules/{schedule_id}", description="更新调度"),
    operation("alert list", "GET", "/api/projects/{project_id}/alerts", query=("history",), description="列出告警"),
    operation("alert ack", "POST", "/api/projects/{project_id}/alerts/{alert_id}/ack", description="确认已知悉告警"),
    operation("audit list", "GET", "/api/projects/{project_id}/audit", query=("limit",), description="读取审计记录"),
    operation("work-log add", "POST", "/api/projects/{project_id}/work-logs", description="记录人工工时"),
    operation("operations", "GET", "/api/projects/{project_id}/operations", description="读取成本与运营摘要"),
    operation("retention preview", "GET", "/api/projects/{project_id}/retention/preview", description="预览原文保留清理"),
    operation("retention execute", "POST", "/api/projects/{project_id}/retention/execute", confirmation="retention", description="确认清理到期原文"),
    operation("admin backup", "POST", "/api/projects/{project_id}/backup", description="在服务器创建数据库备份"),
    operation("health", "GET", "/api/health", description="读取服务健康状态"),
]

REGISTRY = {item.command: item for item in OPERATIONS}
assert len(REGISTRY) == len(OPERATIONS), "duplicate CLI command"

PATH_ARGUMENTS = {
    "set_id": "set",
    "other_id": "other",
    "item_id": "item",
    "entity_id": "entity",
    "wave_id": "wave",
    "run_id": "run",
    "answer_id": "answer",
    "observation_id": "observation",
    "opportunity_id": "opportunity",
    "action_id": "action",
    "report_id": "report",
    "engine_id": "engine",
    "session_id": "browser_session",
    "schedule_id": "schedule",
    "alert_id": "alert",
    "attachment_id": "attachment",
    "collection_id": "collection",
}
