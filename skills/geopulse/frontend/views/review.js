import { api, query } from "../api.js";
import { h, clear, pageHead, section, badge, drawer, field, select, textarea, checkbox, toast, formError, formatDate, label, safeLink, emptyState } from "../components.js";

export async function renderReview(root, ctx) {
  const waves = (await api.get(`/api/projects/${ctx.project.id}/waves`)).items;
  const allRuns = waves.flatMap((wave) => wave.runs.map((run) => ({ ...run, wave })));
  const selectedId = Number(ctx.params.get("run")) || allRuns.find((item) => item.wave.official_run_id === item.id)?.id || allRuns[0]?.id;
  const actions = [h("a", { class: "button secondary", href: "#/measure" }, "返回测量执行")];
  if (!selectedId) {
    clear(root); root.append(pageHead("证据复核", "原始回答与实体判定并排显示，人工修订不会覆盖原文。", actions),
      emptyState("还没有可复核的回答", "先创建并执行一个 run。回答完成写入后，即使 judge 尚未完成，也会保留原始文本。"));
    return;
  }
  const runEntry = allRuns.find((item) => item.id === selectedId) || allRuns[0];
  const runId = runEntry.id;
  const filters = { status: ctx.params.get("status") || "", review: ctx.params.has("review") ? ctx.params.get("review") : "pending", limit: 200 };
  const answerData = await api.get(`/api/projects/${ctx.project.id}/runs/${runId}/answers${query(filters)}`);
  const selectedAnswerId = Number(ctx.params.get("answer")) || answerData.items[0]?.id;
  const detail = selectedAnswerId ? await api.get(`/api/projects/${ctx.project.id}/answers/${selectedAnswerId}`) : null;
  if (!ctx.isCurrent()) return;
  const protocol = runEntry.wave.protocol;
  ctx.setProtocol({ promptSet: `ID ${protocol.prompt_set_id}`, entityVersion: protocol.entity_version,
    engines: protocol.engine_signature.map((engine) => engine.name).join(" / "), mode: protocol.mode,
    target: protocol.measurement_target, repeats: protocol.repeats, n: detail?.status === "succeeded" ? 1 : 0,
    demo: protocol.engine_signature.every((engine) => engine.kind === "demo") });
  clear(root);
  root.append(pageHead("证据复核", "只有 confirmed 实体进入有效提及与推荐指标。证据必须逐字来自原文；存疑判定进入人工复核。", actions));
  const runSelect = select(allRuns.map((item) => ({ value: item.id, label: `${item.wave.label} · Run #${item.id} · ${label(item.status)}` })), runId, { "aria-label": "选择 Run" });
  runSelect.addEventListener("change", () => ctx.navigate("review", { run: runSelect.value }));
  const statusFilter = select([{ value: "", label: "全部回答状态" }, { value: "succeeded", label: "成功" }, { value: "failed", label: "失败" }, { value: "cancelled", label: "取消" }, { value: "judging", label: "判定中" }], filters.status);
  const reviewFilter = select([{ value: "all", label: "全部复核状态" }, { value: "pending", label: "仅看待复核" }], filters.review);
  const applyFilters = () => ctx.navigate("review", { run: runId, status: statusFilter.value, review: reviewFilter.value });
  statusFilter.addEventListener("change", applyFilters); reviewFilter.addEventListener("change", applyFilters);
  root.append(h("div", { class: "filters" }, field("Run", runSelect), field("回答状态", statusFilter), field("复核状态", reviewFilter),
    h("span", { class: "muted small" }, `显示 ${answerData.items.length}/${answerData.total} 条`)));
  const rail = h("aside", { class: "list-rail" }, h("div", { class: "list-rail-head" }, h("strong", {}, "回答清单"), badge(runEntry.status)),
    answerData.items.length ? answerData.items.map((answer) => {
      const pending = answer.observations.filter((observation) => observation.review_status === "pending").length;
      return h("button", { class: `list-item${answer.id === selectedAnswerId ? " active" : ""}`, onClick: () => ctx.navigate("review", { run: runId, answer: answer.id, status: filters.status, review: filters.review }) },
        h("strong", {}, `#${answer.id} · ${answer.prompt_text}`), h("small", {}, `${answer.engine_name} · Round ${answer.round_no} · ${label(answer.status)}`),
        pending ? h("span", { class: "cell-sub" }, `${pending} 个实体待复核`) : null);
    }) : h("div", { class: "empty-state" }, h("p", {}, filters.review === "pending" ? "当前 Run 没有待复核回答。可以查看全部回答，或先处理失败样本。" : "当前筛选没有回答。请调整状态筛选。"),
      filters.review === "pending" ? h("button", { class: "button secondary", onClick: () => ctx.navigate("review", { run: runId, review: "all", status: filters.status }) }, "查看全部回答") : null));
  const pane = h("div", { class: "detail-pane" });
  pane.append(h("button", { class: "button secondary mobile-back", onClick: () => ctx.navigate("review", { run: runId, status: filters.status, review: filters.review }) }, "返回回答清单"));
  if (detail) renderAnswerDetail(pane, ctx, detail, filters);
  root.append(h("div", { class: `split-layout wide-left evidence-browser${ctx.params.has("answer") ? " has-detail" : ""}` }, rail, pane));
}

function renderAnswerDetail(root, ctx, answer, filters) {
  const latest = new Map();
  answer.observations.forEach((observation) => {
    const group = latest.get(observation.brand_entity_id) || [];
    group.push(observation); latest.set(observation.brand_entity_id, group);
  });
  const rawPanel = h("section", {}, h("div", { class: "section-head" }, h("div", {}, h("h2", {}, `#${answer.id} · 原始回答`), h("p", {}, `${answer.engine_name || answer.model} · Round ${answer.round_no} · ${formatDate(answer.completed_at, ctx.project.timezone)}`)), badge(answer.status)),
    h("p", { class: "muted" }, answer.prompt_text),
    answer.raw_text ? h("div", { class: "raw-answer" }, answer.raw_text) : h("div", { class: "inline-panel warning-panel" },
      h("h3", {}, answer.content_retained === 0 ? "原文已按保留策略清理" : answer.status === "failed" ? "没有有效回答原文" : "原文不可见"),
      h("p", {}, answer.content_retained === 0 ? "判定、有效样本事实和聚合指标仍保留；不能再新增依赖原文的 revision，新报告也无法通过原文证据闸门。" : answer.status === "failed" ? `${answer.error_type || "执行失败"}。失败样本不能解释为零提及；请由管理员确认是否重试。` : "当前角色可查看实体证据与状态，但不能读取内部原始回答。")),
    answer.citations.length ? h("div", { class: "inline-panel" }, h("h3", {}, "Provider 实际返回的来源"), answer.citations.map((citation) => h("p", {}, safeLink(citation.final_url || citation.raw_url, citation.title || citation.domain), h("span", { class: "cell-sub" }, `${citation.source_type} · ${citation.domain}`)))) : h("p", { class: "muted small" }, "未暴露可核验来源；不会补造 URL。"));
  const observations = h("section", {}, h("div", { class: "section-head" }, h("div", {}, h("h2", {}, "实体判定"), h("p", {}, `${latest.size} 个冻结实体 · 原文不会因修订改变`))));
  latest.forEach((versions) => {
    const current = versions[0];
    const panel = h("article", { class: `observation ${current.entity_status === "confirmed" ? "confirmed" : current.review_status === "pending" ? "pending" : ""}` },
      h("div", { class: "observation-head" }, h("div", {}, h("h3", {}, current.name), h("span", { class: "cell-sub" }, `${label(current.role)} · ${label(current.judge_status)}`)), badge(current.entity_status)),
      h("div", { class: "button-group" }, badge(current.depth), badge(current.sentiment), current.top_choice ? badge("Top Choice", "info") : null, badge(current.review_status)),
      current.evidence ? h("blockquote", { class: "observation-evidence" }, current.evidence) : h("p", { class: "muted small" }, "无有效证据句"),
      current.citation_urls.length ? h("p", {}, current.citation_urls.map((url) => safeLink(url))) : null,
      h("div", { class: "button-group" },
        ["admin", "analyst"].includes(ctx.role) && answer.raw_text ? h("button", { class: "button small-button secondary", onClick: () => revisionDialog(ctx, answer, current, filters) }, "新增人工修订") : null,
        versions.length > 1 ? h("details", {}, h("summary", { class: "revision-note" }, `${versions.length} 个 revision`), versions.map((version) => h("p", { class: "revision-note" }, `r${version.revision} · ${version.judge_status} · ${version.review_reason || "机器判定"} · ${formatDate(version.created_at, ctx.project.timezone)}`))) : null));
    observations.append(panel);
  });
  root.append(h("div", { class: "evidence-layout" }, rawPanel, observations));
  root.append(h("details", { class: "advanced" }, h("summary", {}, "调用、模型与 Judge 元数据"), h("div", {},
    h("p", { class: "muted" }, `返回模型：${answer.model || "—"}。usage：${JSON.stringify(answer.usage || {})}`),
    answer.call_attempts.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["类型", "状态", "模型", "延迟", "Usage", ...(ctx.role === "reviewer" || ctx.role === "viewer" ? [] : ["成本"])].map((title) => h("th", {}, title)))),
      h("tbody", {}, answer.call_attempts.map((attempt) => h("tr", {}, [attempt.kind, label(attempt.status), attempt.model || "—", `${attempt.latency_ms || 0} ms`, JSON.stringify(attempt.usage || {}), ...(ctx.role === "reviewer" || ctx.role === "viewer" ? [] : [attempt.cost ?? "未知"])].map((value) => h("td", {}, value))))))) : h("p", {}, "暂无调用记录"))));
}

function revisionDialog(ctx, answer, observation, filters) {
  const entityStatus = select(["confirmed", "ambiguous", "wrong_entity", "unknown"].map((value) => ({ value, label: label(value) })), observation.entity_status);
  const mentioned = checkbox("目标实体在回答中出现", Boolean(observation.mentioned));
  const depth = select(["absent", "mentioned", "described", "recommended"].map((value) => ({ value, label: label(value) })), observation.depth);
  const sentiment = select(["positive", "neutral", "negative", "unknown"].map((value) => ({ value, label: label(value) })), observation.sentiment);
  const topChoice = checkbox("这是当前问题下的首选推荐", Boolean(observation.top_choice));
  const evidence = textarea(observation.evidence || "", { rows: 5, placeholder: "逐字粘贴原文中的证据句；未提及时留空" });
  const reason = textarea("", { required: true, placeholder: "说明修订依据和争议点" });
  const arbitrate = checkbox("以管理员仲裁结论提交", false, "仲裁后 review_status=confirmed；普通分析师修订仍待复核");
  if (ctx.role !== "admin") arbitrate.node.hidden = true;
  const form = h("form", {}, h("p", {}, `${observation.name} · 基于 revision ${observation.revision} 新增版本`),
    h("div", { class: "form-grid" }, field("实体状态", entityStatus), field("提及深度", depth), field("情感", sentiment)),
    mentioned.node, topChoice.node, field("原文证据", evidence), field("修订理由", reason), arbitrate.node,
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "保存新 Revision")));
  const modal = drawer("人工修订实体判定", form, { wide: true });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api.post(`/api/projects/${ctx.project.id}/answers/${answer.id}/observations/${observation.id}/revisions`, {
        entity_status: entityStatus.value, mentioned: mentioned.control.checked, depth: depth.value, sentiment: sentiment.value,
        top_choice: topChoice.control.checked, evidence: evidence.value, reason: reason.value,
        arbitrate: ctx.role === "admin" && arbitrate.control.checked,
      });
      modal.close(); toast("新 revision 已保存，原始回答未改变"); ctx.refresh();
    } catch (error) { formError(form, error); }
  });
}
