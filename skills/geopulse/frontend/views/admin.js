import { api } from "../api.js";
import { executionFields } from "../execution.js";
import { h, clear, pageHead, section, dataTable, badge, drawer, field, input, select, textarea, checkbox, toast, formError, confirmDialog, tabs, tabPanel, label, formatDate, downloadJson, handleBudgetError } from "../components.js";

export async function renderAdmin(root, ctx) {
  const requested = ctx.params.get("tab") || "engines";
  const [engines, waves, alerts, schedules] = await Promise.all([
    api.get(`/api/projects/${ctx.project.id}/engines`).then((data) => data.items),
    api.get(`/api/projects/${ctx.project.id}/waves`).then((data) => data.items),
    api.get(`/api/projects/${ctx.project.id}/alerts`).then((data) => data.items),
    api.get(`/api/projects/${ctx.project.id}/schedules`).then((data) => data.items),
  ]);
  let users = [], members = [], operations = null, audit = [], retention = null;
  if (ctx.role === "admin") {
    [members, audit] = await Promise.all([
      api.get(`/api/projects/${ctx.project.id}/memberships`).then((data) => data.items),
      api.get(`/api/projects/${ctx.project.id}/audit?limit=100`).then((data) => data.items),
    ]);
    if (ctx.user.global_role === "admin") users = await api.get("/api/users").then((data) => data.items);
  }
  if (["admin", "analyst"].includes(ctx.role)) {
    [operations, retention] = await Promise.all([
      api.get(`/api/projects/${ctx.project.id}/operations`),
      api.get(`/api/projects/${ctx.project.id}/retention/preview`),
    ]);
  }
  if (!ctx.isCurrent()) return;
  const availableTabs = [{ value: "engines", label: "引擎与口径" }, { value: "schedules", label: `调度与告警${alerts.length ? ` (${alerts.length})` : ""}` }];
  if (ctx.role === "admin") availableTabs.push({ value: "members", label: "成员与角色" });
  if (operations) availableTabs.push({ value: "operations", label: "成本与运营" });
  availableTabs.push({ value: "governance", label: "设置与数据治理" });
  const tab = availableTabs.some((item) => item.value === requested) ? requested : "engines";
  clear(root);
  root.append(pageHead("系统管理", "管理测量连接、执行安排和项目数据。真实外部调用会在执行前再次显示预估并请求确认。"));
  const tablist = tabs(availableTabs, tab, (value) => ctx.navigate("admin", { tab: value }));
  root.append(tablist);
  const panel = h("div", {});
  if (tab === "engines") renderEngines(panel, ctx, engines);
  else if (tab === "members") renderMembers(panel, ctx, users, members);
  else if (tab === "schedules") renderSchedules(panel, ctx, waves, schedules, alerts);
  else if (tab === "operations") renderOperations(panel, ctx, operations);
  else renderGovernance(panel, ctx, { engines, audit, retention });
  root.append(tabPanel(tablist, panel));
}

function healthText(value) {
  if (!value) return "未检查";
  const [status, ...detail] = String(value).split(":");
  return `${label(status)}${detail.length ? ` · ${detail.join(":")}` : ""}`;
}

function renderEngines(root, ctx, engines) {
  const add = ctx.role === "admin" ? h("button", { class: "button", onClick: () => engineDialog(ctx) }, "新增引擎") : null;
  const unhealthy = engines.filter((engine) => engine.health_status?.startsWith("unhealthy")).length;
  const providers = engines.filter((engine) => engine.kind !== "manual_web" && engine.enabled).length;
  const webTargets = engines.filter((engine) => engine.kind === "manual_web" && engine.enabled).length;
  root.append(h("div", { class: `inline-panel${unhealthy ? " warning-panel" : " emphasis"}` },
    h("h2", {}, unhealthy ? `${unhealthy} 个 Provider 健康检查异常` : `${providers} 个 Provider · ${webTargets} 个人工 Web 目标可用于新测量`),
    h("p", { class: "muted" }, "Provider API 与人工 Consumer Web 是两种独立测量口径。人工目标只保存 HTTPS 产品入口，不保存账号、Cookie、密码或 Token，也不执行网页自动化。冻结 Wave 后，编辑配置不会改写历史协议。")));
  root.append(section("测量目标配置", "Provider 密钥单独保存在 0600 secret store；人工 Web 目标不配置密钥、价格或健康检查", dataTable(
    ["目标", "模型或产品入口", "测量口径", "连接状态", "状态", "操作"], engines.map((engine) => {
      const manual = engine.kind === "manual_web";
      return [
        h("div", {}, h("div", { class: "cell-title" }, engine.name), h("span", { class: "cell-sub" }, `${engine.vendor} · ${manual ? "人工采集" : engine.has_api_key ? "密钥已配置" : engine.kind === "demo" ? "本地演示" : "缺少密钥"}`)),
        h("div", {}, manual ? engine.base_url : engine.model || "—", h("span", { class: "cell-sub" }, `${engine.kind} · ${manual ? "HTTPS 产品入口" : engine.base_url || "本地"}`)),
        h("div", {}, `${label(engine.mode)} · ${label(engine.measurement_target)}`, engine.kind === "kimi_search" || engine.kind === "deepseek_search" ? h("span", { class: "cell-sub" }, "Search + Chat；Search 失败不降级") : manual ? h("span", { class: "cell-sub" }, "由人工在页面观察并提交证据") : null),
        manual ? h("div", {}, "不适用", h("span", { class: "cell-sub" }, "无 Provider 健康检查")) : h("div", {}, healthText(engine.health_status), engine.health_status ? h("span", { class: "cell-sub" }, "结果保存在当前配置，不改变历史 Run") : null),
        badge(engine.enabled ? "enabled" : "disabled", engine.enabled ? "success" : "neutral"),
        ctx.role === "admin" ? h("div", { class: "button-group" },
          h("button", { class: "button small-button secondary", onClick: () => engineDialog(ctx, engine) }, "编辑"),
          manual ? null : h("button", { class: "button small-button", onClick: () => healthCheck(ctx, engine) }, engine.kind === "demo" ? "检查演示引擎" : "预估并健康检查")) : h("span", { class: "muted" }, "只读"),
      ];
    })), [add]));
  root.append(h("details", { class: "advanced" }, h("summary", {}, "连接与测量边界"), h("div", {},
    h("p", { class: "muted" }, "普通 OpenAI-compatible 配置只用于 memory。Kimi 与 DeepSeek 分别使用各自的 Search 协议，再交给 Chat 回答；Search 失败不会降级为记忆态。人工 Web 仅支持人工辅助采集；授权浏览器 Collector、持久登录、DOM 自动提取、验证码处理和多平台爬虫不在当前范围内。"))));
}

function engineDialog(ctx, engine) {
  const rule = engine?.cost_rule || {};
  const name = input(engine?.name || "", { required: true });
  const vendor = input(engine?.vendor || "", { required: true, placeholder: "DeepSeek / Moonshot / GeoPulse" });
  const kind = select([{ value: "openai_compat", label: "OpenAI-compatible（记忆态）" }, { value: "kimi_search", label: "Kimi Search + Chat（检索态）" }, { value: "deepseek_search", label: "DeepSeek Search + Chat（检索态）" }, { value: "demo", label: "本地演示引擎" }, { value: "manual_web", label: "人工 Consumer Web（网页观察）" }], engine?.kind || "openai_compat");
  const mode = select([{ value: "memory", label: "memory · 记忆态" }, { value: "search", label: "search · 检索态" }], engine?.mode || "memory");
  const model = input(engine?.model || "", { placeholder: "按厂商账号可用模型填写" });
  const baseUrl = input(engine?.base_url || "", { placeholder: "https://platform.example.com/v1" });
  const apiKey = input("", { type: "password", autocomplete: "new-password", placeholder: engine?.has_api_key ? "留空保留现有密钥" : "仅在保存时传输，不回显" });
  const timeout = input(String(engine?.timeout || 60), { type: "number", min: 1, max: 300 });
  const rate = input(String(engine?.rate_limit || 12), { type: "number", min: 0.1, max: 600, step: "0.1" });
  const enabled = checkbox("启用此引擎", engine?.enabled ?? true, "停用后，新 Run 会拒绝使用；已冻结历史数据不变");
  const currency = select(["CNY", "USD", "EUR"].map((value) => ({ value, label: value })), rule.currency || "CNY");
  const inputPrice = input(rule.input_per_million ?? "", { type: "number", min: 0, step: "0.000001", placeholder: "未设置" });
  const outputPrice = input(rule.output_per_million ?? "", { type: "number", min: 0, step: "0.000001", placeholder: "未设置" });
  const searchPrice = input(rule.search_per_call ?? "", { type: "number", min: 0, step: "0.000001", placeholder: "未设置" });
  const judgeInput = input(rule.judge_input_per_million ?? "", { type: "number", min: 0, step: "0.000001", placeholder: "沿用回答输入价" });
  const judgeOutput = input(rule.judge_output_per_million ?? "", { type: "number", min: 0, step: "0.000001", placeholder: "沿用回答输出价" });
  const estimatedInput = input(rule.estimated_input_tokens ?? 1200, { type: "number", min: 1, step: 1 });
  const estimatedOutput = input(rule.estimated_output_tokens ?? 700, { type: "number", min: 1, step: 1 });
  const capabilities = engine?.capabilities || {};
  const contextWindow = input(capabilities.context_window ?? "", { type: "number", min: 1, step: 1, placeholder: "未知" });
  const maxOutput = input(capabilities.max_output_tokens ?? "", { type: "number", min: 1, step: 1, placeholder: "未知，不猜测" });
  const allowedTemperatures = input((capabilities.allowed_temperatures || []).join(","), { placeholder: "如 1；留空表示未声明枚举限制" });
  const capabilitySelect = (key) => select([{ value: "", label: "未知 / 未声明" }, { value: "true", label: "支持 / 是" }, { value: "false", label: "不支持 / 否" }],
    capabilities[key] === true ? "true" : capabilities[key] === false ? "false" : "");
  const supportsTemperature = capabilitySelect("supports_temperature");
  const supportsJson = capabilitySelect("supports_json_mode");
  const sharedReasoning = capabilitySelect("reasoning_tokens_share_output_budget");
  const answerDefaults = executionFields(engine?.answer_defaults, "answer", "回答默认参数");
  const judgeDefaults = executionFields(engine?.judge_defaults, "judge", "Judge 默认参数");
  const healthDefaults = executionFields(engine?.health_defaults, "health", "健康检查默认参数");
  const modelSettings = h("div", {},
    h("details", { class: "advanced" }, h("summary", {}, "模型能力声明"), h("div", {},
      h("p", { class: "muted small" }, "只填写厂商明确声明的能力。未知保持空白，不根据模型名或上下文窗口猜输出上限。"),
      h("div", { class: "form-grid" }, field("上下文窗口", contextWindow), field("最大输出 tokens", maxOutput),
        field("Temperature 支持", supportsTemperature), field("允许的 temperatures", allowedTemperatures),
        field("JSON response_format", supportsJson), field("推理共享输出预算", sharedReasoning)))),
    answerDefaults.node, judgeDefaults.node, healthDefaults.node);
  const searchField = field("Search 单次调用价", searchPrice, "Search Driver 需要；未填写时成本明确标为未知");
  const modelField = field("模型 ID", model);
  const baseUrlField = field("Base URL", baseUrl, "生产环境强制 HTTPS");
  const apiKeyField = field("API Key", apiKey);
  const timeoutField = field("超时（秒）", timeout);
  const rateField = field("每引擎速率（请求/秒）", rate);
  const pricing = h("details", { class: "advanced", open: Boolean(engine && Object.keys(rule).length) }, h("summary", {}, "价格与调用预估"), h("div", {},
    h("p", { class: "muted small" }, "金额按厂商真实 usage 与以下手工价格估算，不是厂商账单。留空表示未知，不会按零成本处理。"),
    h("div", { class: "form-grid" }, field("币种", currency), searchField,
      field("回答输入价 / 百万 tokens", inputPrice), field("回答输出价 / 百万 tokens", outputPrice),
      field("Judge 输入价 / 百万 tokens", judgeInput), field("Judge 输出价 / 百万 tokens", judgeOutput),
      field("预估输入 tokens / 次", estimatedInput), field("预估输出 tokens / 次", estimatedOutput))));
  const boundaryNote = h("p", { class: "muted small" });
  const syncKind = () => {
    const manual = kind.value === "manual_web";
    const searchDriver = ["kimi_search", "deepseek_search"].includes(kind.value);
    mode.value = manual ? (engine?.mode || "memory") : searchDriver ? "search" : "memory";
    mode.disabled = !manual;
    searchField.hidden = !searchDriver;
    [modelField, apiKeyField, timeoutField, rateField, pricing, modelSettings].forEach((node) => { node.hidden = manual; });
    baseUrlField.querySelector("label").textContent = manual ? "HTTPS 产品入口" : "Base URL";
    baseUrl.placeholder = manual ? "https://consumer.example.com/chat" : "https://platform.example.com/v1";
    boundaryNote.textContent = manual
      ? "人工 Web 只保存产品入口和启用状态，不保存 API Key、Cookie、密码或 Token，不提供 Provider 价格、限流或健康检查。Provider 与人工目标不能互相改型。"
      : "当前 Provider 配置仅用于 provider_api。编辑价格不会改变已冻结 Wave 的预估与历史成本。";
  };
  const form = h("form", {}, h("div", { class: "form-grid" }, field("配置名称", name), field("厂商 / 产品", vendor), field("目标类型", kind), field("测量模式", mode),
    modelField, baseUrlField, apiKeyField, timeoutField, rateField), enabled.node, modelSettings, pricing, boundaryNote,
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "保存测量目标")));
  if (engine?.kind === "manual_web") kind.disabled = true;
  else if (engine) kind.querySelector("option[value='manual_web']").disabled = true;
  const modal = drawer(engine ? `编辑引擎 · ${engine.name}` : "新增引擎", form, { wide: true });
  kind.addEventListener("change", syncKind); syncKind();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const numberOrNull = (control) => control.value === "" ? null : Number(control.value);
    const costRule = { currency: currency.value, estimated_input_tokens: Number(estimatedInput.value), estimated_output_tokens: Number(estimatedOutput.value) };
    [["input_per_million", inputPrice], ["output_per_million", outputPrice], ["search_per_call", searchPrice],
      ["judge_input_per_million", judgeInput], ["judge_output_per_million", judgeOutput]].forEach(([key, control]) => {
      if (control.value !== "") costRule[key] = numberOrNull(control);
    });
    try {
      const manual = kind.value === "manual_web";
      const optionalNumber = (control) => control.value === "" ? null : Number(control.value);
      const boolValue = (control) => control.value === "" ? null : control.value === "true";
      const allowed = allowedTemperatures.value.trim();
      const capabilityValues = {
        context_window: optionalNumber(contextWindow), max_output_tokens: optionalNumber(maxOutput),
        supports_temperature: boolValue(supportsTemperature),
        allowed_temperatures: allowed ? allowed.split(",").map((value) => Number(value.trim())) : null,
        supports_json_mode: boolValue(supportsJson), reasoning_tokens_share_output_budget: boolValue(sharedReasoning),
      };
      if (capabilityValues.allowed_temperatures?.some((value) => !Number.isFinite(value))) throw new Error("允许的 temperatures 必须是逗号分隔的数值");
      const payload = { name: name.value, vendor: vendor.value, kind: kind.value, mode: mode.value, model: manual ? "" : model.value, base_url: baseUrl.value,
        api_key: manual ? "" : apiKey.value || (engine ? "__KEEP__" : ""), measurement_target: manual ? "consumer_web" : "provider_api",
        timeout: Number(timeout.value), rate_limit: Number(rate.value), enabled: enabled.control.checked, cost_rule: manual ? {} : costRule,
        capabilities: manual ? {} : capabilityValues, answer_defaults: manual ? {} : answerDefaults.read(),
        judge_defaults: manual ? {} : judgeDefaults.read(), health_defaults: manual ? {} : healthDefaults.read() };
      await (engine ? api.put(`/api/projects/${ctx.project.id}/engines/${engine.id}`, payload) : api.post(`/api/projects/${ctx.project.id}/engines`, payload));
      modal.close(); toast("引擎配置已保存，密钥未回显"); ctx.refresh();
    } catch (error) { formError(form, error); }
  });
}

function healthCheck(ctx, engine) {
  const calls = ["kimi_search", "deepseek_search"].includes(engine.kind) ? 2 : 1;
  const execute = async (reason = "") => {
    const result = await api.post(`/api/projects/${ctx.project.id}/engines/${engine.id}/health`, { confirm: engine.kind !== "demo", budget_confirmation_reason: reason });
    toast(`${label(result.status)} · ${result.detail}`, result.status !== "healthy"); ctx.refresh();
  };
  confirmDialog(engine.kind === "demo" ? "检查演示引擎" : "确认真实外部调用", engine.kind === "demo" ? "演示健康检查只生成本地确定性回答，并写入统一调用台账。" : `将调用 ${engine.name}：预计 ${calls} 次外部请求（${["kimi_search", "deepseek_search"].includes(engine.kind) ? "Search + Chat" : "Chat"}），可能产生厂商费用。预算检查会在调用前执行。`, "确认并检查", async () => {
    try { await execute(); } catch (error) { if (!handleBudgetError(error, execute)) throw error; }
  });
}

function renderMembers(root, ctx, users, members) {
  const globalAdmin = ctx.user.global_role === "admin";
  const assignable = globalAdmin ? users : members.map((member) => ({ id: member.user_id, email: member.email }));
  const actions = [h("button", { class: "button", onClick: () => membershipDialog(ctx, assignable) }, globalAdmin ? "分配 / 调整角色" : "调整现有成员角色")];
  if (globalAdmin) actions.push(h("button", { class: "button secondary", onClick: () => userDialog(ctx) }, "新建用户"));
  root.append(section("项目成员", "管理员负责实体、机会适用性、正式 Run 与报告审批；客户审核者不能替代内部审批", dataTable(
    ["成员", "项目角色", "分配时间"], members.map((member) => [member.email, badge(member.role), formatDate(member.created_at, ctx.project.timezone)])), actions));
  if (globalAdmin) root.append(section("全部用户", "全局用户列表仅全局管理员可见", dataTable(["邮箱", "全局角色", "状态"], users.map((user) => [user.email, label(user.global_role), label(user.status)]))));
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
  const schedulableWaves = waves.filter((wave) => wave.protocol.measurement_target !== "consumer_web");
  const blocked = schedules.filter((schedule) => schedule.status === "blocked").length;
  root.append(h("div", { class: `inline-panel${blocked || alerts.length ? " warning-panel" : " emphasis"}` },
    h("h2", {}, blocked ? `${blocked} 个调度等待管理员处理` : alerts.length ? `${alerts.length} 条开放告警需要核查` : "当前没有阻塞的调度"),
    h("p", { class: "muted" }, "到期调度只创建执行 Run，不会自动指定正式 Run。预算软超限会停在 blocked，不会替管理员确认。")));
  root.append(section("Wave 调度", "单次或周期执行；活跃 Run 未完成时不会重复入队", dataTable(
    ["Wave", "下次执行", "频率", "状态", "最近结果", "操作"], schedules.map((schedule) => [
      h("div", {}, h("div", { class: "cell-title" }, schedule.wave_label), schedule.last_error ? h("span", { class: "cell-sub" }, schedule.last_error) : null),
      formatDate(schedule.next_run_at || schedule.scheduled_at, ctx.project.timezone),
      schedule.recurrence_days ? `每 ${schedule.recurrence_days} 天` : "单次",
      badge(schedule.status === "pending" ? "planned" : schedule.status),
      schedule.last_run_id ? `Run #${schedule.last_run_id}` : h("span", { class: "muted" }, "尚未执行"),
      ctx.role === "admin" ? scheduleControls(ctx, schedule, schedulableWaves) : h("span", { class: "muted" }, "只读"),
    ]), "还没有复测安排。"), ctx.role === "admin" ? [h("button", { class: "button", disabled: !schedulableWaves.length, onClick: () => scheduleDialog(ctx, schedulableWaves) }, "安排复测")] : []));
  root.append(section("开放告警", "告警只提示人工核查，不自动归因为 GEO 策略效果", dataTable(["级别", "内容", "时间", "操作"], alerts.map((alert) => [
    badge(alert.severity, alert.severity === "critical" ? "danger" : "warning"),
    h("div", {}, alert.message, h("span", { class: "cell-sub" }, `${label(alert.kind)} · ${label(alert.status)}`)), formatDate(alert.created_at, ctx.project.timezone),
    alert.status === "open" && ctx.role === "admin" ? h("button", { class: "button small-button secondary", onClick: async () => { try { await api.post(`/api/projects/${ctx.project.id}/alerts/${alert.id}/ack`, {}); toast("告警已确认"); ctx.refresh(); } catch (error) { toast(error.message, true); } } }, "确认已知悉") : "—",
  ]), "暂无开放告警。"), [h("button", { class: "button secondary", onClick: () => alertHistory(ctx) }, "查看告警历史")]));
}

function scheduleControls(ctx, schedule, waves) {
  const update = async (payload, message) => {
    try { await api.put(`/api/projects/${ctx.project.id}/schedules/${schedule.id}`, payload); toast(message); ctx.refresh(); }
    catch (error) { toast(error.message, true); }
  };
  const controls = [h("button", { class: "button small-button secondary", onClick: () => scheduleDialog(ctx, waves, schedule) }, "编辑")];
  if (["pending", "blocked"].includes(schedule.status)) controls.push(h("button", { class: "button small-button secondary", onClick: () => update({ status: "paused" }, "调度已暂停") }, "暂停"));
  if (["paused", "blocked"].includes(schedule.status)) controls.push(h("button", { class: "button small-button", onClick: () => update({ status: "pending" }, "调度已恢复，将重新检查预算") }, schedule.status === "blocked" ? "处理后再试" : "恢复"));
  if (!["cancelled", "done"].includes(schedule.status)) controls.push(h("button", { class: "button small-button ghost", onClick: () => confirmDialog("取消调度", "只取消未来执行，不影响已经创建的 Run 和测量证据。", "取消未来调度", () => update({ status: "cancelled" }, "调度已取消"), true) }, "取消"));
  return h("div", { class: "button-group" }, controls);
}

function scheduleDialog(ctx, waves, schedule = null) {
  const wave = select(waves.map((item) => ({ value: item.id, label: item.label })), schedule?.wave_id || waves[0]?.id);
  wave.disabled = Boolean(schedule);
  const frequency = select([{ value: "", label: "单次执行" }, { value: 7, label: "每 7 天" }, { value: 14, label: "每 14 天" }, { value: 28, label: "每 28 天" }, { value: "custom", label: "自定义周期" }], schedule?.recurrence_days && ![7, 14, 28].includes(schedule.recurrence_days) ? "custom" : schedule?.recurrence_days || "");
  const customDays = input(schedule?.recurrence_days || 14, { type: "number", min: 1, max: 365 });
  const daysField = field("自定义周期（天）", customDays);
  const dateValue = schedule?.next_run_at || schedule?.scheduled_at;
  const local = dateValue ? new Date(new Date(dateValue).getTime() - new Date(dateValue).getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "";
  const scheduledAt = input(local, { type: "datetime-local", required: true });
  const sync = () => { daysField.hidden = frequency.value !== "custom"; customDays.required = frequency.value === "custom"; };
  frequency.addEventListener("change", sync); sync();
  const form = h("form", {}, field("Wave", wave), field("执行频率", frequency), daysField, field("下次执行时间", scheduledAt, `按 ${ctx.project.timezone} 显示；服务端以 UTC 存储`),
    h("p", { class: "muted" }, schedule?.action_id ? "此调度由 Action 实际发布时间锚定。修改周期不会改写发布事件。" : "周期从计划时间推进，停机恢复后不会突发补跑所有过期测量。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, schedule ? "保存调度修改" : "保存调度")));
  const modal = drawer(schedule ? `编辑调度 · ${schedule.wave_label}` : "安排 Wave 复测", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const date = new Date(scheduledAt.value);
    if (Number.isNaN(date.getTime())) { formError(form, new Error("请选择有效执行时间")); return; }
    const recurrence = frequency.value === "custom" ? Number(customDays.value) : frequency.value ? Number(frequency.value) : null;
    try {
      if (schedule) await api.put(`/api/projects/${ctx.project.id}/schedules/${schedule.id}`, { scheduled_at: date.toISOString(), recurrence_days: recurrence, status: schedule.status === "blocked" ? "pending" : undefined });
      else await api.post(`/api/projects/${ctx.project.id}/schedules`, { wave_id: Number(wave.value), scheduled_at: date.toISOString(), recurrence_days: recurrence });
      modal.close(); toast("复测调度已保存"); ctx.refresh();
    } catch (error) { formError(form, error); }
  });
}

function alertHistory(ctx) {
  const output = h("div", { class: "page-loading" }, "正在读取历史…");
  drawer("告警历史", output, { wide: true });
  api.get(`/api/projects/${ctx.project.id}/alerts?history=true`).then((data) => {
    clear(output); output.className = "";
    output.append(dataTable(["级别", "内容", "状态", "确认 / 恢复时间"], data.items.map((alert) => [badge(alert.severity), alert.message, badge(alert.status), formatDate(alert.acknowledged_at || alert.resolved_at, ctx.project.timezone)]), "还没有告警历史。"));
  }).catch((error) => { clear(output); output.append(h("div", { class: "error-state" }, error.message)); });
}

function renderOperations(root, ctx, operations) {
  const summary = operations.cost_summary;
  const known = Object.entries(summary.by_currency);
  root.append(h("div", { class: "inline-panel emphasis" }, h("h2", {}, "调用台账与交付记录"),
    h("p", { class: "muted" }, summary.estimate_note), h("p", { class: "small" }, `${summary.unknown ? "存在未知成本，未按零元计入。" : "当前调用均已有价格结果。"} ${operations.db_scope}。`)));
  root.append(h("div", { class: "metric-strip" },
    h("div", { class: "metric-block" }, h("span", { class: "metric-label" }, "手工登记工时"), h("strong", { class: "metric-value" }, `${operations.work_hours} h`), h("small", {}, "由项目成员登记，不是系统自动计时")),
    h("div", { class: "metric-block" }, h("span", { class: "metric-label" }, "全库文件大小"), h("strong", { class: "metric-value" }, `${(operations.db_bytes / 1024 / 1024).toFixed(2)} MB`), h("small", {}, "包含所有项目，不是单项目占用")),
    known.length ? known.map(([currency, row]) => h("div", { class: "metric-block" }, h("span", { class: "metric-label" }, `已知估算成本 · ${currency}`), h("strong", { class: "metric-value num" }, row.known_cost), h("small", {}, `${row.calls} 次调用 · ${row.unknown} 次成本未知`))) : h("div", { class: "metric-block" }, h("span", { class: "metric-label" }, "已知估算成本"), h("strong", { class: "metric-value" }, "—"), h("small", {}, "尚无调用台账"))));
  root.append(section("调用类型与币种", "回答、Judge、Search、健康检查与重试分别记录；不同币种不合并求和", dataTable(
    ["业务类型", "计费操作", "币种", "调用 / 重试", "已知估算成本", "未知成本调用"], operations.costs.map((row) => [label(row.kind), label(row.operation), row.currency || "历史未标币种", `${row.calls} / ${row.retry_calls}`, row.known_cost ?? "—", row.unknown])), "尚无调用记录。"));
  root.append(section("有效 usage", "仅汇总厂商实际返回或演示引擎明确记录的 token", dataTable(["类型", "输入 tokens", "输出 tokens"], Object.entries(summary.tokens).map(([kind, row]) => [label(kind), row.prompt_tokens, row.completion_tokens])), "尚无 token usage。"));
  root.append(h("div", { class: "split-layout" }, section("队列状态", "进程重启会从 SQLite 恢复", dataTable(["状态", "样本数"], Object.entries(operations.queue).map(([status, count]) => [label(status), count]))),
    section("交付工时", "内部手工记录，不进入客户版报告", dataTable(["业务日期", "人员", "类型", "工时"], operations.work_logs.map((log) => [log.work_date || formatDate(log.created_at, ctx.project.timezone), log.email, log.kind, log.hours])), [h("button", { class: "button secondary", onClick: () => workLogDialog(ctx) }, "记录工时")])));
}

function workLogDialog(ctx) {
  const hours = input("", { type: "number", min: 0.25, max: 24, step: "0.25", required: true });
  const kind = select(["测量执行", "证据复核", "内容交付", "报告审核", "客户沟通"].map((value) => ({ value, label: value })));
  const workDate = input(new Date().toISOString().slice(0, 10), { type: "date", required: true });
  const note = textarea("");
  const form = h("form", {}, h("p", { class: "muted" }, "这是手工交付登记，不是系统自动计时。"), field("业务日期", workDate), field("工时", hours), field("工作类型", kind), field("说明", note), h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "保存工时")));
  const modal = drawer("记录交付工时", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api.post(`/api/projects/${ctx.project.id}/work-logs`, { hours: Number(hours.value), kind: kind.value, note: note.value, work_date: workDate.value }); modal.close(); toast("工时已记录"); ctx.refresh(); }
    catch (error) { formError(form, error); }
  });
}

function renderGovernance(root, ctx, data) {
  const settings = ctx.project.settings;
  const budget = settings.budget || {};
  const smallN = input(String(settings.small_sample_n ?? 30), { type: "number", min: 1 });
  const completeness = input(String(settings.min_pair_completeness ?? 0.9), { type: "number", min: 0.5, max: 1, step: "0.01" });
  const repeats = select([1, 2, 3, 4, 5].map((value) => ({ value, label: `${value} 轮` })), settings.repeats ?? 3);
  const budgetEnabled = checkbox("启用预算检查", budget.enabled ?? false, "软超限需要管理员逐次填写理由；硬限额在执行前拒绝");
  const hardLimit = checkbox("启用硬限额", budget.hard_limit ?? false, "只提供执行前保护，不承诺在途厂商调用绝不超额");
  const currency = select(["CNY", "USD", "EUR"].map((value) => ({ value, label: value })), budget.currency || "CNY");
  const amount = input(budget.amount ?? "", { type: "number", min: 0, step: "0.01", placeholder: "不设置" });
  const waveAmount = input(budget.wave_amount ?? "", { type: "number", min: 0, step: "0.01", placeholder: "不设置" });
  const dailyAmount = input(budget.daily_amount ?? "", { type: "number", min: 0, step: "0.01", placeholder: "不设置" });
  const retentionDays = input(settings.retention_days ?? "", { type: "number", min: 1, step: 1, placeholder: "不自动清理" });
  const form = h("form", { class: "inline-panel emphasis" }, h("h2", {}, "后续测量与执行默认值"),
    h("p", { class: "muted" }, "修改只影响之后创建的 Wave；已冻结统计阈值不会随结果放宽。预算额度由管理员维护。"),
    h("div", { class: "form-grid" }, field("小样本阈值 n", smallN), field("最低配对完整度", completeness), field("默认采样轮次", repeats), field("预算币种", currency),
      field("项目累计额度", amount), field("单 Wave 额度", waveAmount), field("每日额度", dailyAmount, `按 ${ctx.project.timezone} 的自然日检查`), field("原文保留天数", retentionDays, "留空表示永不自动清理；后台最多每日执行一次")),
    budgetEnabled.node, hardLimit.node, h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit", disabled: ctx.role !== "admin" }, "保存项目设置")));
  if (ctx.role !== "admin") form.querySelectorAll("input,select").forEach((control) => { control.disabled = true; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const amountValue = (control) => control.value === "" ? null : Number(control.value);
    try {
      const result = await api.put(`/api/projects/${ctx.project.id}/settings`, { settings: { small_sample_n: Number(smallN.value), min_pair_completeness: Number(completeness.value), repeats: Number(repeats.value), retention_days: retentionDays.value === "" ? null : Number(retentionDays.value), budget: { ...budget, enabled: budgetEnabled.control.checked, hard_limit: hardLimit.control.checked, currency: currency.value, amount: amountValue(amount), wave_amount: amountValue(waveAmount), daily_amount: amountValue(dailyAmount) } } });
      ctx.project.settings = result.settings;
      toast("项目设置已保存，已有 Wave 未改变"); ctx.refresh();
    } catch (error) { formError(form, error); }
  });
  root.append(form);
  if (data.retention) renderRetention(root, ctx, data.retention);
  if (ctx.role === "admin") {
    root.append(section("备份与项目导出", "项目导出不含密钥；数据库恢复仍通过停写后的运维 CLI 执行", h("div", { class: "section-note" },
      h("div", { class: "button-group" },
        h("button", { class: "button secondary", onClick: async () => { try { const manifest = await api.post(`/api/projects/${ctx.project.id}/backup`, {}); downloadJson(manifest, "geopulse-backup-manifest.json"); toast("备份完成，manifest 已下载"); } catch (error) { toast(error.message, true); } } }, "立即备份数据库"),
        h("button", { class: "button secondary", onClick: async () => { try { downloadJson(await api.get(`/api/projects/${ctx.project.id}/export`), `geopulse-project-${ctx.project.id}.json`); toast("项目导出已生成，不含密钥"); } catch (error) { toast(error.message, true); } } }, "导出当前项目")),
      h("p", { class: "muted small" }, "单机 SQLite 需要定期离线备份和恢复演练。内部开发基线 RPO 24h / RTO 4h，不构成客户 SLA。"))));
    root.append(h("details", { class: "advanced" }, h("summary", {}, "最近审计事件"), h("div", {}, dataTable(["时间", "操作者", "对象", "动作"], data.audit.map((event) => [formatDate(event.created_at, ctx.project.timezone), event.actor_email || "系统", `${event.object_type} #${event.object_id}`, event.action])))));
    root.append(h("details", { class: "advanced" }, h("summary", {}, "危险操作：删除当前项目"), h("div", {}, h("p", { class: "muted" }, "删除前请先完成备份与项目导出。"), h("button", { class: "button danger", onClick: () => deleteProject(ctx) }, "永久删除当前项目"))));
  }
}

function renderRetention(root, ctx, preview) {
  const output = h("div", { class: "section-note" }, h("p", {}, preview.message),
    preview.enabled ? h("p", {}, `截止时间：${formatDate(preview.cutoff, ctx.project.timezone)}；当前有 ${preview.candidate_count} 条到期原文。`) : null,
    ctx.role === "admin" ? h("button", { class: "button secondary", disabled: !preview.enabled || !preview.candidate_count, onClick: () => purgeDialog(ctx, preview) }, "预览并清理到期原文") : null);
  root.append(section("原始回答保留策略", "只清理到期正文；判定、有效样本事实、usage 和历史指标保留。已清理原文不能新增 revision，新报告不能通过原文证据闸门。", output));
}

function purgeDialog(ctx, preview) {
  confirmDialog("清理到期原始回答", `将清理 ${preview.candidate_count} 条原始回答正文，截止 ${formatDate(preview.cutoff, ctx.project.timezone)}。此操作不可恢复；历史有效样本和聚合指标保留，但新报告无法回查这些原文。`, "确认清理原文", async () => {
    const result = await api.post(`/api/projects/${ctx.project.id}/retention/execute`, { confirm: true });
    toast(`已清理 ${result.purged_count} 条原文`); ctx.refresh();
  }, true);
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
