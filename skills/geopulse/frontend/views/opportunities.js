import { api } from "../api.js";
import { h, clear, pageHead, dataTable, badge, drawer, field, input, select, textarea, toast, tabs, tabPanel, label, emptyState, formatDate, onSubmit } from "../components.js";
import { openIntervention } from "./interventions.js";

const stepNames = { 1: "事实与定位", 2: "纠偏与负面", 3: "事实内容", 4: "渠道分发", 5: "来源建设", 6: "深度证据", 7: "实体消歧" };

export async function renderOpportunities(root, ctx) {
  const [opportunityData, actionData, waveData] = await Promise.all([
    api.get(`/api/projects/${ctx.project.id}/opportunities`), api.get(`/api/projects/${ctx.project.id}/actions`), api.get(`/api/projects/${ctx.project.id}/waves`),
  ]);
  const requestedTab = ctx.params.get("tab") || "review";
  const currentTab = ["review", "confirmed", "actions", "remeasure", "closed"].includes(requestedTab) ? requestedTab : "review";
  const officialWaves = waveData.items.filter((wave) => wave.official_run_id);
  const actions = [["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button secondary", disabled: !officialWaves.length, title: officialWaves.length ? "从正式 run 生成候选" : "需要先指定正式 run", onClick: () => generateDialog(ctx, officialWaves) }, "从正式 Run 发现候选") : null];
  clear(root);
  root.append(pageHead("机会与行动", "自动发现只产生候选。管理员确认适用性后才评分、创建七步 Action，并进入客户报告。", actions));
  const pending = opportunityData.items.filter((item) => ["candidate", "eligibility_pending"].includes(item.status));
  const confirmed = opportunityData.items.filter((item) => ["confirmed", "actioned", "remeasured"].includes(item.status));
  root.append(h("div", { class: "inline-panel emphasis" }, h("h2", {}, pending.length ? `${pending.length} 个候选需要适用性判断` : confirmed.length ? `${confirmed.length} 个机会已进入交付流程` : "当前没有待处理候选"),
    h("p", { class: "muted" }, "优先级评分不是自动结论。先核查原文中的竞品推荐理由、场景和不适用边界，再决定是否投入。"),
    h("dl", { class: "definition-list" }, h("div", {}, h("dt", {}, "待确认机会"), h("dd", {}, pending.length)), h("div", {}, h("dt", {}, "已确认机会"), h("dd", {}, confirmed.length)),
      h("div", {}, h("dt", {}, "已登记发布"), h("dd", {}, actionData.items.filter((item) => item.publication_count > 0).length)))));
  const actionGroups = {
    actions: actionData.items.filter((item) => ["draft", "review", "approved", "published"].includes(item.status)),
    remeasure: actionData.items.filter((item) => item.status === "remeasure_due"),
    closed: actionData.items.filter((item) => ["verified", "not_effective", "stopped"].includes(item.status)),
  };
  const tablist = tabs([{ value: "review", label: `候选审核 (${pending.length})` }, { value: "confirmed", label: `已确认机会 (${confirmed.length})` },
    { value: "actions", label: `执行中 (${actionGroups.actions.length})` }, { value: "remeasure", label: `待复测 (${actionGroups.remeasure.length})` }, { value: "closed", label: `已结束 (${actionGroups.closed.length})` }], currentTab,
    (tab) => ctx.navigate("opportunities", { tab }));
  root.append(tablist);
  const panel = h("div", {});
  if (actionGroups[currentTab]) renderActions(panel, ctx, actionGroups[currentTab], waveData.items, currentTab);
  else {
    const items = currentTab === "confirmed" ? confirmed : pending;
    panel.append(items.length ? dataTable(["缺口 / Prompt", "Wave", "状态", "评分", "下一步"], items.map((item) => [
      h("div", {}, h("button", { class: "table-link", onClick: () => opportunityDetail(ctx, item, waveData.items) }, item.gap_type), h("span", { class: "cell-sub" }, item.prompt_text)),
      item.wave_label, badge(item.status), item.score ?? h("span", { class: "muted" }, "确认后计算"),
      h("div", { class: "button-group" },
        ["candidate", "eligibility_pending"].includes(item.status) && ctx.role === "admin" ? h("button", { class: "button small-button", onClick: () => reviewDialog(ctx, item) }, "审核适用性") : null,
        item.status === "confirmed" && ["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button small-button", onClick: () => actionDialog(ctx, item, waveData.items) }, "创建 Action") : null,
        h("button", { class: "button small-button ghost", onClick: () => opportunityDetail(ctx, item, waveData.items) }, "查看证据")),
    ])) : emptyState(currentTab === "confirmed" ? "还没有已确认机会" : "候选队列已清空", currentTab === "confirmed" ? "候选只有经管理员确认适用后才会出现在这里。" : "可以从已指定正式 run 的 wave 生成候选；没有候选也可能表示当前规则未检出竞争缺口。"));
  }
  root.append(tabPanel(tablist, panel));
  const deepLinkedAction = ctx.params.get("action");
  if (deepLinkedAction) openIntervention(ctx, Number(deepLinkedAction), ctx.params.get("intent") || "");
}

function generateDialog(ctx, waves) {
  const wave = select(waves.map((item) => ({ value: item.id, label: `${item.label} · 正式 Run #${item.official_run_id}` })));
  const form = h("form", {}, field("正式测量", wave), h("p", { class: "muted" }, "只读取正式 run 的当前 observation revision。候选生成不会自动评分或写入客户报告。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "生成候选")));
  const modal = drawer("从正式 Run 发现候选", form);
  onSubmit(form, async () => {
    const result = await api.post(`/api/projects/${ctx.project.id}/waves/${wave.value}/opportunities/generate`, {});
    modal.close(); toast(`生成 ${result.count} 个候选`); ctx.refresh();
  });
}

function opportunityDetail(ctx, item, waves) {
  const evidence = item.evidence || {};
  const content = h("div", {}, h("div", { class: "inline-panel emphasis" }, h("h3", {}, `${item.gap_type} · ${item.prompt_text}`),
    h("p", {}, `${item.wave_label} · ${label(item.status)} · ${label(item.eligibility)}`), item.score_detail ? h("p", { class: "code-block" }, JSON.stringify(item.score_detail, null, 2)) : h("p", { class: "muted" }, "尚未评分；管理员确认适用性后才计算。")),
    h("h3", {}, "竞品推荐与原文证据"), evidence.evidence?.length ? evidence.evidence.map((row) => h("article", { class: "observation" },
      h("h3", {}, `${row.brand} · ${label(row.depth)}`), h("blockquote", { class: "observation-evidence" }, row.evidence),
      h("a", { href: `#/review?answer=${row.answer_id}` }, "打开回答上下文"))) : h("p", { class: "muted" }, "此候选主要来自主品牌负面或实体歧义，请查看关联回答。"),
    h("p", { class: "muted small" }, `关联回答 ID：${(evidence.answer_ids || []).join("、") || "—"}`),
    h("div", { class: "form-actions" },
      ["candidate", "eligibility_pending"].includes(item.status) && ctx.role === "admin" ? h("button", { class: "button", onClick: () => { modal.close(); reviewDialog(ctx, item); } }, "审核适用性") : null,
      item.status === "confirmed" && ["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button", onClick: () => { modal.close(); actionDialog(ctx, item, waves); } }, "创建七步 Action") : null,
      ["actioned", "remeasured"].includes(item.status) && ctx.role === "admin" ? h("button", { class: "button danger", onClick: () => { modal.close(); closeDialog(ctx, item); } }, "关闭机会") : null));
  const modal = drawer(`机会 #${item.id} · 证据与下一步`, content, { wide: true });
}

function reviewDialog(ctx, item) {
  const decision = select([{ value: "confirmed", label: "确认适用并评分" }, { value: "eligibility_pending", label: "暂存，继续核查" }, { value: "rejected", label: "不适用并排除" }], item.status === "eligibility_pending" ? "eligibility_pending" : "confirmed");
  const eligibility = select([{ value: "client_confirmed", label: "客户已确认适用" }, { value: "eligible", label: "内部确认适用" }], "client_confirmed");
  const business = select([1, 2, 3, 4, 5].map((value) => ({ value, label: `${value} / 5` })), 3);
  const executability = select([1, 2, 3, 4, 5].map((value) => ({ value, label: `${value} / 5` })), 3);
  const reason = textarea("", { placeholder: "记录适用边界、客户确认或排除原因" });
  const scoreFields = h("div", { class: "form-grid" }, field("适用性依据", eligibility), field("商业价值", business), field("可执行性", executability));
  const scoreHelp = h("p", { class: "muted small" }, "评分采用冻结权重的几何聚合；证据可靠性和竞争缺口由原始样本自动计算。");
  const syncDecision = () => {
    const confirmed = decision.value === "confirmed";
    scoreFields.hidden = !confirmed;
    scoreHelp.hidden = !confirmed;
    [eligibility, business, executability].forEach((control) => { control.disabled = !confirmed; });
  };
  decision.addEventListener("change", syncDecision);
  syncDecision();
  const form = h("form", {}, h("p", {}, `${item.gap_type} · ${item.prompt_text}`), field("审核决定", decision),
    scoreFields, field("审核说明", reason), scoreHelp,
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "保存管理员决定")));
  const modal = drawer("确认机会适用性", form);
  onSubmit(form, async () => {
    const confirmed = decision.value === "confirmed";
    await api.post(`/api/projects/${ctx.project.id}/opportunities/${item.id}/review`, { decision: decision.value,
      ...(confirmed ? { eligibility: eligibility.value, business_value: Number(business.value), executability: Number(executability.value) } : {}), reason: reason.value });
    modal.close(); toast("适用性审核已保存"); ctx.refresh();
  });
}

function actionDialog(ctx, item, waves) {
  const title = input("", { required: true, placeholder: "例如：补充自托管部署与证据审计事实页" });
  const step = select(Object.entries(stepNames).map(([value, name]) => ({ value, label: `第 ${value} 步 · ${name}` })), { "实体歧义": 7, "缺席": 3, "深度落后": 6, "被贬": 2 }[item.gap_type] || 3);
  const owner = input(""), reviewer = input("");
  const targetUrl = input("", { type: "url", placeholder: "https://example.com/planned-page" });
  const targetWave = select([{ value: "", label: "稍后选择复测 Wave" }, ...waves.filter((wave) => wave.id !== item.wave_id).map((wave) => ({ value: wave.id, label: wave.label }))]);
  const form = h("form", {}, field("Action 标题", title), h("div", { class: "form-grid" }, field("GEO 七步", step), field("负责人", owner), field("审核人", reviewer), field("目标 URL / 平台", targetUrl), field("目标复测 Wave", targetWave)),
    h("p", { class: "muted" }, "创建后仍为草稿。只有填写真实发布时间与 URL 并经管理员发布，才会成为复测共时事件。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "创建 Action 草稿")));
  const modal = drawer("从已确认机会创建 Action", form);
  onSubmit(form, async () => {
    const action = await api.post(`/api/projects/${ctx.project.id}/opportunities/${item.id}/actions`, { title: title.value, geo_step: Number(step.value), owner: owner.value, reviewer: reviewer.value, target_url: targetUrl.value, target_wave_id: targetWave.value ? Number(targetWave.value) : null });
    modal.close(); toast("Action 与 Brief/Asset 草稿已创建"); ctx.navigate("opportunities", { tab: "actions", action: action.id });
  });
}

function renderActions(root, ctx, actions, waves, group) {
  const emptyCopy = {
    actions: ["还没有执行中的 Intervention", "先从已确认机会创建草稿，再完成 Brief、资产审批和真实渠道发布。"],
    remeasure: ["当前没有待复测的 Intervention", "完成发布后，可安排 D7/D14/D28 cohort 节点；到期或已有节点会在这里汇总。"],
    closed: ["还没有已结束的 Intervention", "完成复测评估或由管理员停止后，历史证据链会保留在这里。"],
  }[group];
  root.append(actions.length ? dataTable(["Intervention", "状态", "负责人", "最新 cohort 节点", "下一步"], actions.map((action) => [
    h("div", {}, h("button", { class: "table-link", onClick: () => openAction(ctx, action) }, action.title),
      h("span", { class: "cell-sub" }, `${action.gap_type} · ${action.asset_count || 0} 个资产 · ${action.publication_count || 0} 条发布`)),
    badge(action.status), action.owner || "未分配",
    action.latest_round_due_at ? h("div", {}, label(action.latest_round_status), h("span", { class: "cell-sub" }, formatDate(action.latest_round_due_at, ctx.project.timezone))) : h("span", { class: "muted" }, "尚未安排"),
    nextActionControl(ctx, action, waves),
  ])) : emptyState(...emptyCopy));
}

function openAction(ctx, action, intent = "") {
  const tab = action.status === "remeasure_due" ? "remeasure"
    : ["verified", "not_effective", "stopped"].includes(action.status) ? "closed" : "actions";
  ctx.navigate("opportunities", { tab, action: action.id, ...(intent ? { intent } : {}) });
}

function nextActionControl(ctx, action) {
  const admin = ctx.role === "admin", analyst = admin || ctx.role === "analyst";
  const direct = (status, title) => h("button", { class: "button small-button", onClick: () => transitionDirect(ctx, action, status, title) }, title);
  if (action.status === "draft" && analyst) return direct("review", "提交审核");
  if (action.status === "review" && admin) return direct("approved", "批准行动");
  if (action.status === "approved" && admin) return h("button", { class: "button small-button", onClick: () => openAction(ctx, action, "publish") }, "登记真实发布");
  if (action.status === "published" && analyst) return h("button", { class: "button small-button", onClick: () => openAction(ctx, action, "rounds") }, "安排复测");
  return h("button", { class: "button small-button secondary", onClick: () => openAction(ctx, action) }, "打开工作台");
}

async function transitionDirect(ctx, action, status, reason) {
  try { await api.post(`/api/projects/${ctx.project.id}/actions/${action.id}/status`, { status, reason }); toast(`Action 已更新为${label(status)}`); ctx.refresh(); }
  catch (error) { toast(error.message, true); }
}

function closeDialog(ctx, item) {
  const reason = textarea("", { required: true, placeholder: "复测改善证据或不再投入的管理员理由" });
  const form = h("form", {}, field("关闭理由", reason), h("div", { class: "form-actions" }, h("button", { class: "button danger", type: "submit" }, "关闭机会")));
  const modal = drawer("关闭机会", form);
  onSubmit(form, async () => {
    await api.post(`/api/projects/${ctx.project.id}/opportunities/${item.id}/status`, { status: "closed", reason: reason.value });
    modal.close(); toast("机会已关闭"); ctx.refresh();
  });
}
