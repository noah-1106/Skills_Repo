import { api } from "../api.js";
import { h, clear, pageHead, section, dataTable, badge, drawer, field, input, select, textarea, checkbox, toast, formError, confirmDialog, tabs, label, formatDate, downloadJson, emptyState } from "../components.js";

export async function renderAdmin(root, ctx) {
  const tab = ctx.params.get("tab") || "engines";
  const [engines, waves, alerts, schedules] = await Promise.all([
    api.get(`/api/projects/${ctx.project.id}/engines`).then((data) => data.items), api.get(`/api/projects/${ctx.project.id}/waves`).then((data) => data.items),
    api.get(`/api/projects/${ctx.project.id}/alerts`).then((data) => data.items), api.get(`/api/projects/${ctx.project.id}/schedules`).then((data) => data.items),
  ]);
  let users = [], members = [], operations = null, audit = [];
  if (ctx.role === "admin") {
    [users, members, audit] = await Promise.all([
      api.get("/api/users").then((data) => data.items), api.get(`/api/projects/${ctx.project.id}/memberships`).then((data) => data.items),
      api.get(`/api/projects/${ctx.project.id}/audit?limit=100`).then((data) => data.items),
    ]);
  }
  if (["admin", "analyst"].includes(ctx.role)) operations = await api.get(`/api/projects/${ctx.project.id}/operations`);
  if (!ctx.isCurrent()) return;
  clear(root);
  root.append(pageHead("系统管理", "引擎密钥、成员权限、调度、成本与数据治理由项目作用域隔离。真实健康检查需要再次确认外部调用。"));
  const availableTabs = [{ value: "engines", label: "引擎与口径" }, { value: "schedules", label: "调度与告警" }];
  if (ctx.role === "admin") availableTabs.push({ value: "members", label: "成员与角色" });
  if (operations) availableTabs.push({ value: "operations", label: "成本与运营" });
  availableTabs.push({ value: "governance", label: "设置与数据治理" });
  root.append(tabs(availableTabs, tab, (value) => ctx.navigate("admin", { tab: value })));
  if (tab === "engines") renderEngines(root, ctx, engines);
  else if (tab === "members" && ctx.role === "admin") renderMembers(root, ctx, users, members);
  else if (tab === "schedules") renderSchedules(root, ctx, waves, schedules, alerts);
  else if (tab === "operations" && operations) renderOperations(root, ctx, operations);
  else renderGovernance(root, ctx, { engines, audit });
}

function renderEngines(root, ctx, engines) {
  const add = ctx.role === "admin" ? h("button", { class: "button", onClick: () => engineDialog(ctx) }, "新增引擎") : null;
  root.append(section("引擎配置", "Provider API 结果不会被标为 Kimi App、ChatGPT 网页等消费者产品观察", dataTable(
    ["引擎", "类型 / 模型", "测量口径", "健康", "状态", "操作"], engines.map((engine) => [
      h("div", {}, h("div", { class: "cell-title" }, engine.name), h("span", { class: "cell-sub" }, `${engine.vendor} · ${engine.has_api_key ? "密钥已单独保存" : "无密钥"}`)),
      h("div", {}, `${engine.kind} · ${engine.model || "—"}`, h("span", { class: "cell-sub" }, engine.base_url || "本地演示")),
      h("div", {}, `${label(engine.mode)} · ${label(engine.measurement_target)}`, engine.kind === "kimi_search" ? h("span", { class: "cell-sub" }, "Kimi Search Basic + Chat 检索增强 API") : null),
      engine.health_status || "未检查", badge(engine.enabled ? "confirmed" : "stopped", engine.enabled ? "success" : "neutral"),
      ctx.role === "admin" ? h("div", { class: "button-group" }, h("button", { class: "button small-button secondary", onClick: () => engineDialog(ctx, engine) }, "编辑"),
        h("button", { class: "button small-button", onClick: () => healthCheck(ctx, engine) }, engine.kind === "demo" ? "检查演示引擎" : "确认并健康检查")) : h("span", { class: "muted" }, "只读"),
    ])), [add]));
  root.append(h("div", { class: "inline-panel" }, h("h3", {}, "调用边界"),
    h("p", { class: "muted" }, "普通 OpenAI-compatible 配置只用于 memory；Kimi 检索使用 POST /v1/tools/search 的 text_query，再交给 Chat 回答。Search 失败不会降级成 memory。密钥只显示“已配置”，编辑时留空表示保留。")));
}

function engineDialog(ctx, engine) {
  const name = input(engine?.name || "", { required: true });
  const vendor = input(engine?.vendor || "", { required: true, placeholder: "DeepSeek / Moonshot / GeoPulse" });
  const kind = select([{ value: "openai_compat", label: "OpenAI-compatible（记忆态）" }, { value: "kimi_search", label: "Kimi Search + Chat（检索态）" }, { value: "demo", label: "本地演示引擎" }], engine?.kind || "openai_compat");
  const mode = select([{ value: "memory", label: "memory · 记忆态" }, { value: "search", label: "search · 检索态" }], engine?.mode || "memory");
  const model = input(engine?.model || "", { placeholder: "按厂商账号可用模型填写" });
  const baseUrl = input(engine?.base_url || "", { placeholder: "https://platform.example.com/v1" });
  const apiKey = input("", { type: "password", autocomplete: "new-password", placeholder: engine?.has_api_key ? "留空保留现有密钥" : "仅在保存时传输，不回显" });
  const timeout = input(String(engine?.timeout || 60), { type: "number", min: 1, max: 300 });
  const rate = input(String(engine?.rate_limit || 12), { type: "number", min: 0.1, max: 600, step: "0.1" });
  const enabled = checkbox("启用此引擎", engine?.enabled ?? true);
  const costRule = textarea(JSON.stringify(engine?.cost_rule || {}, null, 2), { rows: 7, placeholder: '{"input_per_million":2,"output_per_million":8,"currency":"CNY"}' });
  const form = h("form", {}, h("div", { class: "form-grid" }, field("配置名称", name), field("厂商", vendor), field("Provider 类型", kind), field("测量模式", mode),
    field("模型 ID", model), field("Base URL", baseUrl, "生产环境强制 HTTPS"), field("API Key", apiKey), field("超时（秒）", timeout), field("每引擎速率（请求/秒）", rate)),
    enabled.node, h("details", { class: "advanced" }, h("summary", {}, "成本与 token 估算规则"), h("div", {}, field("JSON 成本规则", costRule, "可含 input/output_per_million、judge_*、search_per_call、estimated_*_tokens、currency"))),
    h("p", { class: "muted small" }, "当前仅允许 provider_api 合法采集。API 密钥保存在 0600 secret store，数据库和导出只保留引用。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "保存引擎配置")));
  const modal = drawer(engine ? `编辑引擎 · ${engine.name}` : "新增引擎", form, { wide: true });
  kind.addEventListener("change", () => { mode.value = kind.value === "kimi_search" ? "search" : "memory"; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const payload = { name: name.value, vendor: vendor.value, kind: kind.value, mode: mode.value, model: model.value, base_url: baseUrl.value,
        api_key: apiKey.value || (engine ? "__KEEP__" : ""), measurement_target: "provider_api", timeout: Number(timeout.value), rate_limit: Number(rate.value), enabled: enabled.control.checked,
        cost_rule: costRule.value.trim() ? JSON.parse(costRule.value) : {} };
      await (engine ? api.put(`/api/projects/${ctx.project.id}/engines/${engine.id}`, payload) : api.post(`/api/projects/${ctx.project.id}/engines`, payload));
      modal.close(); toast("引擎配置已保存，密钥未回显"); ctx.refresh();
    } catch (error) { formError(form, error); }
  });
}

function healthCheck(ctx, engine) {
  const calls = engine.kind === "kimi_search" ? 2 : 1;
  confirmDialog(engine.kind === "demo" ? "检查演示引擎" : "确认真实外部调用", engine.kind === "demo" ? "演示健康检查只生成本地确定性回答。" : `将调用 ${engine.name}：预计 ${calls} 次外部请求（${engine.kind === "kimi_search" ? "Search + Chat" : "Chat"}），可能产生厂商费用。请确认模型和当前账号额度。`, "确认并检查", async () => {
    const result = await api.post(`/api/projects/${ctx.project.id}/engines/${engine.id}/health`, { confirm: engine.kind !== "demo" });
    toast(`${label(result.status)} · ${result.detail}`, result.status !== "healthy"); ctx.refresh();
  });
}

function renderMembers(root, ctx, users, members) {
  root.append(section("项目成员", "管理员负责实体、适用性、报告审批与发送；客户审核者不能替代内部审批", dataTable(
    ["成员", "项目角色", "分配时间"], members.map((member) => [member.email, badge(member.role), formatDate(member.created_at, ctx.project.timezone)])),
    [h("button", { class: "button", onClick: () => membershipDialog(ctx, users) }, "分配 / 调整角色"), h("button", { class: "button secondary", onClick: () => userDialog(ctx) }, "新建用户")]));
  root.append(section("全部用户", "全局用户列表仅管理员可见", dataTable(["邮箱", "全局角色", "状态"], users.map((user) => [user.email, label(user.global_role), label(user.status)]))));
}

function userDialog(ctx) {
  const email = input("", { type: "email", required: true });
  const password = input("", { type: "password", minlength: 10, required: true, autocomplete: "new-password" });
  const form = h("form", {}, field("邮箱", email), field("初始密码", password, "至少 10 个字符，请通过安全渠道交付并要求尽快更换"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "创建用户")));
  const modal = drawer("新建用户", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api.post("/api/users", { email: email.value, password: password.value }); modal.close(); toast("用户已创建，请继续分配项目角色"); ctx.refresh(); }
    catch (error) { formError(form, error); }
  });
}

function membershipDialog(ctx, users) {
  const user = select(users.map((item) => ({ value: item.id, label: item.email })));
  const role = select(["admin", "analyst", "reviewer", "viewer"].map((value) => ({ value, label: label(value) })), "viewer");
  const form = h("form", {}, field("用户", user), field("项目角色", role),
    h("p", { class: "muted" }, "reviewer / viewer 不查看内部成本和原始回答；所有审批仍以管理员权限为准。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "保存项目角色")));
  const modal = drawer("分配项目成员", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api.post(`/api/projects/${ctx.project.id}/memberships`, { user_id: Number(user.value), role: role.value }); modal.close(); toast("成员角色已保存"); ctx.refresh(); }
    catch (error) { formError(form, error); }
  });
}

function renderSchedules(root, ctx, waves, schedules, alerts) {
  root.append(section("Wave 调度", "调度只负责幂等创建 run；正式 run 仍由管理员在数据完成后人工指定", dataTable(
    ["Wave", "计划时间", "状态", "最近 Run"], schedules.map((schedule) => [schedule.wave_label, formatDate(schedule.scheduled_at, ctx.project.timezone), badge(schedule.status === "pending" ? "planned" : schedule.status), schedule.last_run_id ? `#${schedule.last_run_id}` : "—"])),
    ctx.role === "admin" ? [h("button", { class: "button", disabled: !waves.length, onClick: () => scheduleDialog(ctx, waves) }, "安排复测")] : []));
  root.append(section("开放告警", "样本、Judge 和连续 wave 波动都需要人工核查", dataTable(["级别", "内容", "时间", "操作"], alerts.map((alert) => [
    badge(alert.severity, alert.status === "open" ? "warning" : "neutral"), h("div", {}, alert.message, h("span", { class: "cell-sub" }, `${alert.kind} · ${label(alert.status)}`)), formatDate(alert.created_at, ctx.project.timezone),
    alert.status === "open" && ctx.role === "admin" ? h("button", { class: "button small-button secondary", onClick: async () => { await api.post(`/api/projects/${ctx.project.id}/alerts/${alert.id}/ack`, {}); toast("告警已确认"); ctx.refresh(); } }, "确认已知悉") : "—",
  ]), "暂无告警。")));
}

function scheduleDialog(ctx, waves) {
  const wave = select(waves.map((item) => ({ value: item.id, label: item.label })));
  const preset = select([{ value: 7, label: "D7 · 7 天后" }, { value: 14, label: "D14 · 14 天后" }, { value: 28, label: "D28 · 28 天后" }, { value: "custom", label: "自定义时间" }], 14);
  const custom = input("", { type: "datetime-local" });
  const customField = field("自定义时间", custom); customField.hidden = true;
  preset.addEventListener("change", () => { customField.hidden = preset.value !== "custom"; custom.required = preset.value === "custom"; });
  const form = h("form", {}, field("Wave", wave), field("复测锚点", preset), customField,
    h("p", { class: "muted" }, `时间按 ${ctx.project.timezone} 展示，服务端以 UTC 存储。活跃 run 未完成时不会重复入队。`),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "保存调度")));
  const modal = drawer("安排 Wave 复测", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const date = preset.value === "custom" ? new Date(custom.value) : new Date(Date.now() + Number(preset.value) * 86400000);
    if (Number.isNaN(date.getTime())) { formError(form, new Error("请选择有效时间")); return; }
    try { await api.post(`/api/projects/${ctx.project.id}/schedules`, { wave_id: Number(wave.value), scheduled_at: date.toISOString() }); modal.close(); toast("复测调度已保存"); ctx.refresh(); }
    catch (error) { formError(form, error); }
  });
}

function renderOperations(root, ctx, operations) {
  root.append(h("div", { class: "metric-strip" },
    h("div", { class: "metric-block" }, h("span", { class: "metric-label" }, "交付工时"), h("strong", { class: "metric-value" }, `${operations.work_hours} h`)),
    h("div", { class: "metric-block" }, h("span", { class: "metric-label" }, "数据库大小"), h("strong", { class: "metric-value" }, `${(operations.db_bytes / 1024 / 1024).toFixed(2)} MB`)),
    h("div", { class: "metric-block" }, h("span", { class: "metric-label" }, "有效样本成本"), h("strong", { class: "metric-value" }, operations.queue.succeeded ? `${(operations.costs.reduce((sum, row) => sum + (row.cost || 0), 0) / operations.queue.succeeded).toFixed(4)}` : "—"), h("small", {}, "未知价格不按零成本"))));
  root.append(section("分调用类型成本", "回答、Judge、Search 和重试分别记录", dataTable(["类型", "调用数", "成本", "未知价格调用"], operations.costs.map((row) => [row.kind, row.calls, row.cost ?? "—", row.unknown]))));
  root.append(section("队列状态", "进程重启会从 SQLite 恢复，已成功原文不重复请求", dataTable(["状态", "样本数"], Object.entries(operations.queue).map(([status, count]) => [label(status), count]))));
  root.append(section("交付工时记录", "内部运营数据不会进入客户版报告", dataTable(["时间", "人员", "类型", "工时", "说明"], operations.work_logs.map((log) => [formatDate(log.created_at, ctx.project.timezone), log.email, log.kind, log.hours, log.note])),
    [h("button", { class: "button secondary", onClick: () => workLogDialog(ctx) }, "记录工时")]));
}

function workLogDialog(ctx) {
  const hours = input("", { type: "number", min: 0, max: 24, step: "0.25", required: true });
  const kind = select(["测量执行", "证据复核", "内容交付", "报告审核", "客户沟通"].map((value) => ({ value, label: value })));
  const note = textarea("");
  const form = h("form", {}, field("工时", hours), field("工作类型", kind), field("说明", note), h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "保存工时")));
  const modal = drawer("记录交付工时", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api.post(`/api/projects/${ctx.project.id}/work-logs`, { hours: Number(hours.value), kind: kind.value, note: note.value }); modal.close(); toast("工时已记录"); ctx.refresh(); }
    catch (error) { formError(form, error); }
  });
}

function renderGovernance(root, ctx, data) {
  const settings = ctx.project.settings;
  const smallN = input(String(settings.small_sample_n ?? 30), { type: "number", min: 1 });
  const completeness = input(String(settings.min_pair_completeness ?? 0.9), { type: "number", min: 0.5, max: 1, step: "0.01" });
  const repeats = select([1, 2, 3, 4, 5].map((value) => ({ value, label: `${value} 轮` })), settings.repeats ?? 3);
  const budgetEnabled = checkbox("启用预算提醒", settings.budget?.enabled ?? false);
  const hardLimit = checkbox("启用显式硬限额", settings.budget?.hard_limit ?? false, "默认关闭；开启前请确认项目成本策略");
  const amount = input(settings.budget?.amount ?? "", { type: "number", min: 0, step: "0.01", placeholder: "不设置金额" });
  const form = h("form", { class: "inline-panel" }, h("h2", {}, "后续 Wave 的统计与预算默认值"),
    h("p", { class: "muted" }, "修改只影响之后创建的 wave。已冻结 wave 的阈值不会因看到结果而放宽。原始数据默认不自动删除。"),
    h("div", { class: "form-grid" }, field("小样本阈值 n", smallN), field("最低配对完整度", completeness), field("默认采样轮次", repeats), field("预算金额（CNY）", amount)),
    budgetEnabled.node, hardLimit.node, h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit", disabled: ctx.role !== "admin" }, "保存后续默认值")));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api.put(`/api/projects/${ctx.project.id}/settings`, { settings: { small_sample_n: Number(smallN.value), min_pair_completeness: Number(completeness.value), repeats: Number(repeats.value), budget: { ...settings.budget, enabled: budgetEnabled.control.checked, hard_limit: hardLimit.control.checked, amount: amount.value === "" ? null : Number(amount.value) } } }); toast("项目默认值已保存，已有 wave 未改变"); ctx.refresh(); }
    catch (error) { formError(form, error); }
  });
  root.append(form);
  if (ctx.role === "admin") {
    root.append(section("备份与项目导出", "导出包含业务快照和 checksum，不包含 API 密钥；恢复操作通过运维 CLI 在停写后执行", h("div", { class: "section-note" },
      h("div", { class: "button-group" }, h("button", { class: "button secondary", onClick: async () => { try { const manifest = await api.post(`/api/projects/${ctx.project.id}/backup`, {}); downloadJson(manifest, "geopulse-backup-manifest.json"); toast("备份完成，manifest 已下载"); } catch (error) { toast(error.message, true); } } }, "立即备份数据库"),
        h("button", { class: "button secondary", onClick: async () => { try { downloadJson(await api.get(`/api/projects/${ctx.project.id}/export`), `geopulse-project-${ctx.project.id}.json`); toast("项目导出已生成，不含密钥"); } catch (error) { toast(error.message, true); } } }, "导出当前项目"),
        h("button", { class: "button danger", onClick: () => deleteProject(ctx) }, "删除当前项目")),
      h("p", { class: "muted small" }, "单机 SQLite 需要定期离线备份和恢复演练。内部开发基线 RPO 24h / RTO 4h，不构成客户 SLA。"))));
    root.append(section("最近审计事件", "密钥、密码和 token 在写入审计前脱敏", dataTable(["时间", "操作者", "对象", "动作"], data.audit.map((event) => [
      formatDate(event.created_at, ctx.project.timezone), event.actor_email || "系统", `${event.object_type} #${event.object_id}`, event.action,
    ]))));
  }
}

function deleteProject(ctx) {
  const confirmation = input("", { required: true, placeholder: ctx.project.name });
  const form = h("form", {}, h("div", { class: "inline-panel danger-panel" }, h("h3", {}, "此操作会永久删除当前项目的测量、证据、报告和行动"),
    h("p", {}, "不会删除其他客户项目或独立 secret store。请先完成备份与项目导出。")),
    field("输入完整项目名确认", confirmation), h("div", { class: "form-actions" }, h("button", { class: "button danger", type: "submit" }, "永久删除项目")));
  const modal = drawer("删除项目", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (confirmation.value !== ctx.project.name) { formError(form, new Error("项目名不完全一致")); return; }
    try { await api.delete(`/api/projects/${ctx.project.id}?confirm=${encodeURIComponent(confirmation.value)}`); modal.close(); toast("项目已删除"); localStorage.removeItem("geopulse-project"); location.reload(); }
    catch (error) { formError(form, error); }
  });
}
