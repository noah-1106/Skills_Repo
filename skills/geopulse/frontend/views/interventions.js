import { api } from "../api.js";
import { h, clear, badge, drawer, field, input, select, textarea, toast, formError, safeLink, label, formatDate, section, emptyState, onSubmit } from "../components.js";
import { toDateTimeLocal, fromDateTimeLocal } from "../datetime.js";

const roundStatus = {
  pending_measurement: "待测量", measured: "已有测量", insufficient_evidence: "证据不足",
  incomparable: "不可比", legacy_unavailable: "历史证据不可用",
};
const observedLabels = { improved: "观察到改善", not_improved: "未观察到改善", unknown: "暂无法判断", "": "尚未评估" };

export async function openIntervention(ctx, actionId, initialAction = "") {
  const modal = drawer(`Intervention #${actionId}`, h("div", { class: "muted" }, "正在读取证据链…"), {
    wide: true,
    onClose: () => {
      if (ctx.params.get("action")) {
        const status = data?.action.status;
        const tab = status === "remeasure_due" ? "remeasure"
          : ["verified", "not_effective", "stopped"].includes(status) ? "closed" : "actions";
        ctx.navigate("opportunities", { tab });
      }
    },
  });
  let data;
  let waves;
  async function reload() {
    [data, waves] = await Promise.all([
      api.get(`/api/projects/${ctx.project.id}/actions/${actionId}`),
      api.get(`/api/projects/${ctx.project.id}/waves`),
    ]);
    render();
  }
  function render() {
    clear(modal.body);
    const action = data.action;
    const summary = data.decision_summary;
    const latestObservation = summary.observations.filter((row) => row.status !== "pending_measurement").at(-1);
    modal.body.append(
      h("div", { class: "inline-panel emphasis intervention-hero" },
        h("div", { class: "section-head" }, h("div", {}, h("h2", {}, action.title),
          h("p", {}, `第 ${action.geo_step} 步 · ${action.owner || "未分配负责人"} · ${data.opportunity.prompt_text}`)), badge(action.status)),
        h("p", {}, latestObservation ? `最新 cohort 观察：D${latestObservation.offset_days} · ${roundStatus[latestObservation.status]} · ${observedLabels[latestObservation.observed_change]}` : "尚无复测观察。先完成内容资产与真实渠道登记。"),
        h("p", { class: "muted" }, data.causal_boundary),
        h("div", { class: "form-actions" }, primaryControl(ctx, data, waves, modal, reload))),
      decisionPanel(summary, ctx),
      briefPanel(ctx, data, modal, reload),
      assetPanel(ctx, data, modal, reload),
      publicationPanel(ctx, data, modal, reload),
      roundsPanel(ctx, data, waves, modal, reload),
      technicalPanel(ctx, data),
    );
    if (!modal.dialog.contains(document.activeElement)) modal.focus();
  }
  try {
    await reload();
    if (initialAction === "publish") publicationDialog(ctx, data, reload);
    if (initialAction === "rounds") roundsDialog(ctx, data, waves, reload);
  } catch (error) {
    clear(modal.body);
    modal.body.append(h("div", { class: "error-state", role: "alert" }, h("h3", {}, "无法读取 Intervention"), h("p", {}, error.message)));
  }
  return modal;
}

function primaryControl(ctx, data, waves, modal, reload) {
  const action = data.action;
  const admin = ctx.role === "admin";
  const analyst = admin || ctx.role === "analyst";
  if (action.status === "draft" && analyst) return h("button", { class: "button", onClick: () => changeStatus(ctx, action, "review", reload) }, "提交审核");
  if (action.status === "review" && admin) return h("button", { class: "button", onClick: () => changeStatus(ctx, action, "approved", reload) }, "批准行动");
  if (["approved", "published", "remeasure_due"].includes(action.status) && admin && !data.publications.length)
    return h("button", { class: "button", onClick: () => publicationDialog(ctx, data, reload) }, "登记真实发布");
  if (["published", "remeasure_due"].includes(action.status) && analyst) {
    const pending = data.rounds.find((row) => row.status === "pending_measurement");
    if (pending) {
      const wave = waves.items.find((item) => item.id === pending.target_wave_id);
      if (pending.surface === "consumer_web" && !wave?.official_run_id)
        return h("a", { class: "button", href: `#/measure?wave=${pending.target_wave_id}`, onClick: () => modal.close() }, "前往显式复测");
      if (admin && wave?.official_run_id) return h("button", { class: "button", onClick: () => assessDialog(ctx, pending, reload) }, "评估当前复测");
      return h("span", { class: "muted" }, wave?.official_run_id ? "等待管理员评估" : "等待目标 Wave 指定正式 Run");
    }
    const remainingDays = [7, 14, 28].filter((days) => !data.rounds.some((row) => row.offset_days === days && row.status !== "legacy_unavailable"));
    if (remainingDays.length) return h("button", { class: "button", onClick: () => roundsDialog(ctx, data, waves, reload) }, `安排 ${remainingDays.map((days) => `D${days}`).join("/")} 复测`);
    return h("span", { class: "muted" }, data.next_recommendation);
  }
  return h("span", { class: "muted" }, data.next_recommendation);
}

async function changeStatus(ctx, action, status, reload) {
  try { await api.post(`/api/projects/${ctx.project.id}/actions/${action.id}/status`, { status }); toast(`Action 已更新为${label(status)}`); await reload(); }
  catch (error) { toast(error.message, true); }
}

function decisionPanel(summary, ctx) {
  return section("客户决策摘要", "只呈现 cohort 事实与证据强度，不把同期变化写成单篇内容效果。", h("div", { class: "decision-grid" },
    h("article", {}, h("h3", {}, "哪些关键问题不推荐我们"), summary.key_questions.length ? h("ul", {}, summary.key_questions.map((row) => h("li", {}, `${row.prompt_text} · ${row.gap_type}`))) : h("p", { class: "muted" }, "尚未关联关键问题")),
    h("article", {}, h("h3", {}, "改了什么、发到哪里"), summary.changes.assets.length || summary.changes.publications.length ? h("ul", {},
      summary.changes.assets.map((row) => h("li", {}, `${row.title} · v${row.version}`)),
      summary.changes.publications.map((row) => h("li", {}, `${label(row.channel)}${row.outlet ? ` / ${row.outlet}` : ""} · ${formatDate(row.published_at, ctx.project.timezone)}`))) : h("p", { class: "muted" }, "尚未登记真实发布")),
    h("article", {}, h("h3", {}, "之后观察到什么"), summary.observations.length ? h("ul", {}, summary.observations.map((row) => h("li", {}, `D${row.offset_days} · ${roundStatus[row.status]} · ${row.evidence_strength}`))) : h("p", { class: "muted" }, "尚无复测评估")),
    h("p", { class: "next-recommendation" }, h("strong", {}, "唯一下一轮建议："), summary.next_recommendation)));
}

function briefPanel(ctx, data, modal, reload) {
  const analyst = ["admin", "analyst"].includes(ctx.role);
  const brief = data.briefs[0];
  const body = brief ? h("div", {},
    h("p", {}, `Brief v${brief.version} · ${label(brief.status)}`),
    h("dl", { class: "definition-list" }, h("div", {}, h("dt", {}, "信息增量"), h("dd", {}, brief.information_gain)),
      h("div", {}, h("dt", {}, "成功标准"), h("dd", {}, brief.success_criteria))),
    h("div", { class: "claim-list" }, brief.claims.map((claim) => h("article", { class: "claim-row" },
      h("p", {}, claim.text), badge(claim.status, claim.status === "pending" ? "warning" : "success"),
      claim.status === "pending" ? h("span", { class: "muted" }, "待确认，不能作为事实发布") : null,
      (claim.evidence_refs || []).map((ref) => h("a", { class: `evidence-ref${ref.available_now === false ? " unavailable" : ""}`,
        href: `#/review?answer=${ref.answer_id}` }, ref.available_now === false ? `Answer #${ref.answer_id} · 原文已清理` : `Answer #${ref.answer_id}${ref.observation_id ? ` / Observation #${ref.observation_id} r${ref.revision}` : ""}`)),
      claim.evidence_count !== undefined ? h("span", { class: "muted small" }, `${claim.evidence_count} 条证据引用`) : null))),
    brief.hypothesis ? h("details", {}, h("summary", {}, "假设与预期观察"), h("p", {}, brief.hypothesis), h("p", {}, brief.expected_observation)) : null)
    : emptyState("还没有结构化 Brief", "legacy 记录需要新建 Brief 版本，不能补造历史证据。");
  const actions = [];
  if (brief && analyst) actions.push(h("button", { class: "button small-button secondary", onClick: () => briefDialog(ctx, data, brief, reload) }, brief.status === "draft" ? "编辑 Brief" : "创建新 Brief 版本"));
  if (brief?.status === "draft" && ctx.role === "admin") actions.push(h("button", { class: "button small-button", onClick: async () => {
    try { await api.post(`/api/projects/${ctx.project.id}/briefs/${brief.id}/approve`, {}); toast("Brief 已审批并冻结"); await reload(); } catch (error) { toast(error.message, true); }
  } }, "审批 Brief"));
  return section("Brief 与事实主张", "每条事实主张必须链接基线证据；没有证据的内容明确标为待确认。", body, actions);
}

function baselineAnswerIds(data) {
  try { return JSON.parse(data.opportunity.evidence_json || "{}").answer_ids || []; }
  catch { return []; }
}

function briefDialog(ctx, data, brief, reload) {
  const informationGain = textarea(brief.information_gain, { required: true, rows: 3 });
  const hypothesis = textarea(brief.hypothesis, { required: true, rows: 3 });
  const expected = textarea(brief.expected_observation, { required: true, rows: 3 });
  const criteria = textarea(brief.success_criteria, { required: true, rows: 3 });
  const channels = input((brief.channels || []).join("、"), { placeholder: "官网、合作媒体；登记发布时仍逐渠道记录" });
  const answerIds = baselineAnswerIds(data);
  const claims = h("div", { class: "claim-editor" });
  function addClaim(claim = { text: "", status: "pending", evidence_refs: [] }) {
    const text = textarea(claim.text, { required: true, rows: 2, placeholder: "写一条可核验的事实主张" });
    const status = select([{ value: "pending", label: "待确认" }, { value: "evidence_linked", label: "已链接基线证据" }], claim.status);
    const refsByAnswer = new Map((claim.evidence_refs || []).map((ref) => [Number(ref.answer_id), ref]));
    const evidence = select(answerIds.map((id) => ({ value: id, label: `Answer #${id}` })), "", {
      multiple: true, size: Math.min(Math.max(answerIds.length, 2), 5), disabled: !answerIds.length,
    });
    [...evidence.options].forEach((option) => { option.selected = refsByAnswer.has(Number(option.value)); });
    const row = h("div", { class: "inline-panel" }, field("事实主张", text), field("证据状态", status),
      field("基线 Answer 证据（可多选）", evidence, answerIds.length
        ? "只选择该 Opportunity 基线范围内的证据；保留的 Observation / Citation 引用不会被移除"
        : "此历史 Opportunity 没有可用 Answer ID，只能保存待确认主张"),
      h("button", { class: "button small-button ghost", type: "button", onClick: () => row.remove() }, "移除主张"));
    row._claim = { text, status, evidence, refsByAnswer };
    claims.append(row);
  }
  brief.claims.forEach(addClaim);
  const creatingVersion = brief.status !== "draft";
  const form = h("form", {}, field("信息增量", informationGain), field("假设", hypothesis), field("预期观察", expected),
    field("成功标准", criteria), field("计划渠道", channels), h("h3", {}, "事实主张"), claims,
    h("button", { class: "button small-button secondary", type: "button", onClick: () => addClaim() }, "添加事实主张"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, creatingVersion ? "创建 Brief 新版本" : "保存 Brief")));
  const modal = drawer(`Brief v${brief.version}${brief.status === "legacy" ? " · 新建结构化版本" : ""}`, form, { wide: true });
  onSubmit(form, async () => {
    const payload = { information_gain: informationGain.value, hypothesis: hypothesis.value,
      expected_observation: expected.value, success_criteria: criteria.value,
      channels: channels.value.split(/[、,，]/).map((value) => value.trim()).filter(Boolean),
      claims: [...claims.children].map((row) => {
        const selected = [...row._claim.evidence.selectedOptions].map((option) => Number(option.value));
        return { text: row._claim.text.value, status: row._claim.status.value,
          evidence_refs: row._claim.status.value === "evidence_linked"
            ? selected.map((id) => row._claim.refsByAnswer.get(id) || { answer_id: id }) : [] };
      }) };
    if (!payload.claims.length) throw new Error("至少保留一条事实主张");
    if (payload.claims.some((claim) => claim.status === "evidence_linked" && !claim.evidence_refs.length)) throw new Error("标为已链接证据的主张必须至少选择一个基线 Answer");
    if (creatingVersion) await api.post(`/api/projects/${ctx.project.id}/actions/${data.action.id}/briefs`, payload);
    else await api.put(`/api/projects/${ctx.project.id}/briefs/${brief.id}`, payload);
    modal.close(); toast("Brief 已保存"); await reload();
  });
}

function assetPanel(ctx, data, modal, reload) {
  const analyst = ["admin", "analyst"].includes(ctx.role);
  const structuredBriefs = data.briefs.filter((brief) => brief.status !== "legacy" && brief.claims.length);
  const body = data.assets.length ? h("div", { class: "record-list" }, data.assets.map((asset) => h("article", { class: "record-row" },
    h("div", {}, h("h3", {}, `${asset.title} · v${asset.version}`), h("p", { class: "muted" }, `${label(asset.asset_type)} · ${label(asset.status)}`),
      asset.applicability ? h("p", {}, `适用：${asset.applicability}`) : null, asset.exclusions ? h("p", {}, "不适用：" + asset.exclusions) : null,
      asset.facts.some((fact) => fact.status === "pending") ? h("p", { class: "form-error" }, "仍有待确认事实，不能发布") : null),
    h("div", { class: "button-group" },
      analyst && asset.status !== "legacy" ? h("button", { class: "button small-button secondary", onClick: () => assetDialog(ctx, data, reload, asset) }, asset.status === "draft" ? "编辑 Asset" : "创建 Asset 新版本") : null,
      asset.status === "draft" && ctx.role === "admin" ? h("button", { class: "button small-button", onClick: async () => {
        try { await api.post(`/api/projects/${ctx.project.id}/assets/${asset.id}/approve`, {}); toast("Asset 已审批"); await reload(); } catch (error) { toast(error.message, true); }
      } }, "审批 Asset") : null)))) : emptyState("还没有内容资产", "Asset 管内容身份与版本，不包含渠道费用或单篇效果。");
  return section("Content Assets", "同一 Action 下的所有资产属于一个干预 cohort。", body,
    analyst && structuredBriefs.length ? [h("button", { class: "button small-button secondary", onClick: () => assetDialog(ctx, data, reload) }, "新增内容资产")] : []);
}

function assetDialog(ctx, data, reload, existing = null) {
  const brief = existing ? data.briefs.find((row) => row.id === existing.brief_id)
    : data.briefs.find((row) => row.status === "approved" && row.claims.length) || data.briefs.find((row) => row.status === "draft" && row.claims.length);
  if (!brief) { toast("请先创建包含事实主张的结构化 Brief", true); return; }
  const content = existing?.content || {};
  const creatingVersion = Boolean(existing && existing.status !== "draft");
  const title = input(existing?.title || data.action.title, { required: true });
  const type = select([{ value: "fact_page", label: "事实页" }, { value: "faq", label: "FAQ" }, { value: "comparison", label: "对比内容" }, { value: "documentation", label: "文档" }], existing?.asset_type || "fact_page");
  const summary = textarea(content.summary || "", { rows: 3, placeholder: "内容摘要；不要复制原始回答" });
  const targetUrl = input(content.target_url || data.action.target_url || "", { type: "url" });
  const applicability = textarea(existing?.applicability || "", { rows: 2 });
  const exclusions = textarea(existing?.exclusions || "", { rows: 2 });
  const facts = existing?.facts?.length ? existing.facts : brief.claims;
  const form = h("form", {}, field("资产标题", title), field("资产类型", type), field("内容摘要", summary),
    field("计划目标 URL", targetUrl), field("适用边界", applicability), field("不适用边界", exclusions),
    h("p", { class: "muted" }, `事实主张继承 Brief v${brief.version}；审批前会再次校验 evidence_ref。`),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" },
      existing && !creatingVersion ? "保存 Asset 草稿" : creatingVersion ? "创建 Asset 新版本" : "创建 Asset 草稿")));
  const modal = drawer(existing ? `${existing.title} · v${existing.version}` : "新增内容资产", form);
  onSubmit(form, async () => {
    const payload = { brief_id: brief.id, title: title.value, asset_type: type.value, facts,
      content: { ...content, summary: summary.value, target_url: targetUrl.value }, applicability: applicability.value, exclusions: exclusions.value,
      ...(creatingVersion ? { supersedes_asset_id: existing.id } : {}) };
    if (existing && !creatingVersion) await api.put(`/api/projects/${ctx.project.id}/assets/${existing.id}`, payload);
    else await api.post(`/api/projects/${ctx.project.id}/actions/${data.action.id}/assets`, payload);
    modal.close(); toast("Asset 已保存"); await reload();
  });
}

function publicationPanel(ctx, data, modal, reload) {
  const body = data.publications.length ? h("div", { class: "record-list" }, data.publications.map((row) => h("article", { class: "record-row" },
    h("div", {}, h("h3", {}, `${label(row.channel)}${row.outlet ? ` · ${row.outlet}` : ""}`),
      h("p", {}, safeLink(row.url), h("span", { class: "cell-sub" }, formatDate(row.published_at, ctx.project.timezone))),
      h("p", { class: "muted" }, `商业关系：${label(row.relationship)}${Object.hasOwn(row, "cost") ? ` · 成本：${row.cost ?? "未知"}${row.currency ? ` ${row.currency}` : ""}` : ""}`)),
    h("span", { class: "muted small" }, `Asset #${row.asset_id}`)))) : emptyState("尚未登记渠道发布", "草稿完成不等于已发布；必须登记真实 URL 与含时区时间。");
  return section("Channel Publications", "Publication 是不可变渠道事实；后续发布不会覆盖首条兼容摘要。", body,
    ctx.role === "admin" && ["approved", "published", "remeasure_due"].includes(data.action.status) ?
      [h("button", { class: "button small-button secondary", onClick: () => publicationDialog(ctx, data, reload) }, "登记渠道发布")] : []);
}

function publicationDialog(ctx, data, reload) {
  const assets = data.assets.filter((row) => row.status === "approved");
  const asset = select(assets.map((row) => ({ value: row.id, label: `${row.title} · v${row.version}` })), assets[0]?.id);
  const channel = input("owned_site", { required: true });
  const outlet = input("");
  const url = input(data.action.target_url || "", { type: "url", required: true });
  const publishedAt = input(toDateTimeLocal(new Date(), ctx.project.timezone), { type: "datetime-local", required: true });
  const relationship = select(["owned", "partner", "paid", "earned", "unknown"].map((value) => ({ value, label: label(value) })));
  const cost = input("", { type: "number", min: 0, step: "0.01", placeholder: "未知则留空" });
  const currency = input("", { placeholder: "CNY" });
  const notes = textarea("", { rows: 2, placeholder: "内部备注，不进入客户版" });
  const form = h("form", {}, field("内容资产", asset), h("div", { class: "form-grid" }, field("渠道", channel), field("媒体 / 站点", outlet)),
    field("实际发布 URL", url), field("实际发布时间（项目时区）", publishedAt, `按 ${ctx.project.timezone} 填写；服务端保存对应 UTC 时刻`), field("商业关系", relationship),
    h("div", { class: "form-grid" }, field("实际成本", cost, "未知成本留空，不能记为 0"), field("币种", currency)), field("内部备注", notes),
    !assets.length ? h("p", { class: "form-error" }, "请先审批至少一个结构化 Asset") : null,
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit", disabled: !assets.length }, "确认已发布并登记事件")));
  const modal = drawer("登记真实发布", form, { wide: true });
  onSubmit(form, async () => {
    await api.post(`/api/projects/${ctx.project.id}/actions/${data.action.id}/publications`, {
      asset_id: Number(asset.value), channel: channel.value, outlet: outlet.value, url: url.value,
      published_at: fromDateTimeLocal(publishedAt.value, ctx.project.timezone),
      relationship: relationship.value, cost: cost.value === "" ? null : Number(cost.value), currency: currency.value, notes: notes.value,
    });
    modal.close(); toast("发布与共时事件已登记"); await reload();
  });
}

function roundsPanel(ctx, data, waves, modal, reload) {
  const analyst = ["admin", "analyst"].includes(ctx.role);
  const body = data.rounds.length ? h("div", { class: "round-timeline" }, data.rounds.map((row) => {
    const wave = waves.items.find((item) => item.id === row.target_wave_id);
    return h("article", { class: "round-node" }, h("div", { class: "round-marker" }, `D${row.offset_days}`),
      h("div", { class: "round-content" }, h("div", { class: "section-head" }, h("h3", {}, `${wave?.label || `Wave #${row.target_wave_id}`} · ${label(row.surface)}`), badge(row.status)),
        h("p", { class: "muted" }, `计划 ${formatDate(row.due_at, ctx.project.timezone)} · ${observedLabels[row.observed_change]} · ${row.attribution_status === "not_attributable" ? "暂无法归因" : row.attribution_status}`),
        row.surface === "consumer_web" ? h("p", { class: "small" }, "Consumer Web 只提醒，不自动创建 Run 或发送网页问题") : h("p", { class: "small" }, row.schedule ? `Provider 调度：${label(row.schedule.status)}${row.schedule.last_run_id ? ` · Run #${row.schedule.last_run_id}` : ""}` : "Provider 调度：未关联"),
        row.conclusion_reason ? h("p", {}, row.conclusion_reason) : null,
        row.status === "pending_measurement" && ctx.role === "admin" ? h("button", { class: "button small-button", disabled: !wave?.official_run_id,
          title: wave?.official_run_id ? "固定当前正式 Run 并冻结评估" : "目标 Wave 尚未指定正式 Run", onClick: () => assessDialog(ctx, row, reload) }, "评估本轮") : null));
  })) : emptyState("尚未安排复测", "可一次创建 D7/D14/D28，每轮使用独立目标 Wave 和同一固定基线 Run。");
  const usedDays = new Set(data.rounds.filter((row) => row.status !== "legacy_unavailable").map((row) => row.offset_days));
  const canSchedule = analyst && ["published", "remeasure_due"].includes(data.action.status) && [7, 14, 28].some((days) => !usedDays.has(days));
  return section("Cohort remeasurement", "只评估整个 cohort 的同期变化；不返回单资产 delta。", body,
    canSchedule ? [h("button", { class: "button small-button secondary", onClick: () => roundsDialog(ctx, data, waves, reload) }, "安排复测节点")] : []);
}

function roundsDialog(ctx, data, waves, reload) {
  const used = new Set(data.rounds.map((row) => row.target_wave_id));
  const usedDays = new Set(data.rounds.filter((row) => row.status !== "legacy_unavailable").map((row) => row.offset_days));
  const remainingDays = [7, 14, 28].filter((days) => !usedDays.has(days));
  const targets = waves.items.filter((row) => row.id !== data.opportunity.wave_id && !used.has(row.id));
  const controls = remainingDays.map((days, index) => ({ days, control: select(targets.map((row) => ({ value: row.id,
    label: `${row.label} · ${label(row.protocol?.measurement_target || "provider_api")}${row.official_run_id ? ` · 正式 Run #${row.official_run_id}` : ""}` })), targets[index]?.id) }));
  const enoughTargets = remainingDays.length > 0 && targets.length >= remainingDays.length;
  const form = h("form", {}, h("p", { class: "muted" }, "每个节点需要独立目标 Wave。Provider 只自动创建 Run；Consumer Web 仅到期提醒。"),
    controls.map(({ days, control }) => field(`D${days} 目标 Wave`, control)),
    !enoughTargets ? h("p", { class: "form-error" }, `还需要 ${remainingDays.length} 个尚未使用的非基线 Wave；请先复制同口径 Wave。`) : null,
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit", disabled: !enoughTargets }, `创建 ${remainingDays.map((days) => `D${days}`).join("/") || "复测"} 节点`)));
  const modal = drawer("安排 cohort 复测", form, { wide: true });
  onSubmit(form, async () => {
    const ids = controls.map(({ control }) => Number(control.value));
    if (new Set(ids).size !== ids.length) throw new Error("每轮必须选择不同的目标 Wave");
    await api.post(`/api/projects/${ctx.project.id}/actions/${data.action.id}/remeasurements`, {
      rounds: controls.map(({ days, control }) => ({ offset_days: days, target_wave_id: Number(control.value) })) });
    modal.close(); toast("D7/D14/D28 复测节点已创建"); await reload();
  });
}

function assessDialog(ctx, round, reload) {
  const reason = textarea("", { required: true, rows: 4, placeholder: "记录正式 Run、证据限制与 cohort 观察理由" });
  const form = h("form", {}, h("p", {}, `D${round.offset_days} · 固定 baseline Run #${round.baseline_run_id} 与目标 Wave 当前正式 Run。`),
    field("评估依据", reason), h("p", { class: "muted" }, "评估后不可覆盖。小样本、完整度不足和不可比不会输出改善结论。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "冻结本轮评估")));
  const modal = drawer("评估 cohort 复测", form);
  onSubmit(form, async () => {
    await api.post(`/api/projects/${ctx.project.id}/remeasurements/${round.id}/assess`, { reason: reason.value });
    modal.close(); toast("本轮评估已冻结"); await reload();
  });
}

function technicalPanel(ctx, data) {
  return h("details", { class: "technical-details" }, h("summary", {}, "证据时间线与技术详情"),
    h("div", { class: "timeline-list" }, data.timeline.map((event) => h("div", { class: "timeline-event" },
      h("time", {}, formatDate(event.event_at, ctx.project.timezone)), h("span", {}, event.description), event.source ? safeLink(event.source) : null))),
    h("p", { class: "muted small" }, `Action #${data.action.id} · Opportunity #${data.opportunity.id} · 只保存证据引用，不在时间线复制原始回答。`));
}
