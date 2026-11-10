import { api, query, download } from "../api.js";
import { h, clear, pageHead, section, dataTable, badge, drawer, field, input, select, textarea, checkbox, toast, formError, confirmDialog, formatDate, label, safeLink, emptyState, onSubmit } from "../components.js";

const browserPhaseName = (phase) => ({
  queued: "等待本机采集器", session_check: "检查登录会话", preparing: "准备新会话",
  submitting: "正在发送问题", waiting: "等待网页回答", extracting: "提取回答与证据",
  uploading: "保存原始证据", awaiting_user: "需要处理登录或验证码",
  paused_unknown: "结果不明，等待管理员核对", completed: "采集完成", failed: "采集失败",
}[phase] || phase || "等待采集");

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
  const manual = runEntry.wave.protocol.measurement_target === "consumer_web";
  const browser = runEntry.wave.protocol.collection_protocol?.collection_method === "browser_assisted";
  const filters = { status: ctx.params.get("status") || "", review: ctx.params.has("review") ? ctx.params.get("review") : manual ? "all" : "pending", limit: 200 };
  const answerData = await api.get(`/api/projects/${ctx.project.id}/runs/${runId}/answers${query(filters)}`);
  const selectedAnswerId = Number(ctx.params.get("answer")) || answerData.items[0]?.id;
  const detail = selectedAnswerId ? await api.get(`/api/projects/${ctx.project.id}/answers/${selectedAnswerId}`) : null;
  const collection = detail && manual ? await api.get(`/api/projects/${ctx.project.id}/answers/${detail.id}/collection`) : null;
  if (!ctx.isCurrent()) return;
  const protocol = runEntry.wave.protocol;
  ctx.setProtocol({ promptSet: `ID ${protocol.prompt_set_id}`, entityVersion: protocol.entity_version,
    engines: protocol.engine_signature.map((engine) => engine.name).join(" / "), mode: protocol.mode,
    target: protocol.measurement_target, repeats: protocol.repeats, n: detail?.status === "succeeded" ? 1 : 0,
    demo: protocol.engine_signature.every((engine) => engine.kind === "demo") });
  clear(root);
  root.append(pageHead(browser ? "授权浏览器采集与证据" : manual ? "人工采集与证据复核" : "证据复核", browser ? "查看本机采集阶段与原始证据。登录和验证码由用户处理；结果不明只能恢复原会话或登记失败，不能自动重发。" : manual ? "先完成实际页面回答、截图和采集事实，再复核实体判定。正式提交不可覆盖；失败样本不会成为零提及。" : "只有 confirmed 实体进入有效提及与推荐指标。证据必须逐字来自原文；存疑判定进入人工复核。", actions));
  const runSelect = select(allRuns.map((item) => ({ value: item.id, label: `${item.wave.label} · Run #${item.id} · ${label(item.status)}` })), runId, { "aria-label": "选择 Run" });
  runSelect.addEventListener("change", () => ctx.navigate("review", { run: runSelect.value }));
  const statusFilter = select([{ value: "", label: "全部回答状态" }, { value: "awaiting_collection", label: browser ? "待网页采集" : "待人工采集" }, { value: "succeeded", label: "成功" }, { value: "failed", label: "失败" }, { value: "cancelled", label: "取消" }, { value: "judging", label: "判定中" }], filters.status);
  const reviewFilter = select([{ value: "all", label: "全部复核状态" }, { value: "pending", label: "仅看待复核" }], filters.review);
  const applyFilters = () => ctx.navigate("review", { run: runId, status: statusFilter.value, review: reviewFilter.value });
  statusFilter.addEventListener("change", applyFilters); reviewFilter.addEventListener("change", applyFilters);
  root.append(h("div", { class: "filters" }, field("Run", runSelect), field("回答状态", statusFilter), field("复核状态", reviewFilter),
    h("span", { class: "muted small" }, `显示 ${answerData.items.length}/${answerData.total} 条`)));
  const rail = h("aside", { class: "list-rail" }, h("div", { class: "list-rail-head" }, h("strong", {}, "回答清单"), badge(runEntry.status)),
    answerData.items.length ? answerData.items.map((answer) => {
      const pending = answer.observations.filter((observation) => observation.review_status === "pending").length;
      return h("button", { class: `list-item${answer.id === selectedAnswerId ? " active" : ""}`, "aria-current": answer.id === selectedAnswerId ? "location" : null, "data-answer-id": answer.id, onClick: () => ctx.navigate("review", { run: runId, answer: answer.id, status: filters.status, review: filters.review }) },
        h("strong", {}, `#${answer.id} · ${answer.prompt_text}`), h("small", {}, `${answer.engine_name} · Round ${answer.round_no} · ${label(answer.collection_status || answer.status)}`),
        answer.collection_failure_type ? h("span", { class: "cell-sub" }, `采集失败：${answer.collection_failure_type}`) : pending ? h("span", { class: "cell-sub" }, `${pending} 个实体待复核`) : null);
    }) : h("div", { class: "empty-state" }, h("p", {}, filters.review === "pending" ? "当前 Run 没有待复核回答。可以查看全部回答，或先处理失败样本。" : browser ? "当前筛选没有授权浏览器任务。" : manual ? "当前筛选没有人工采集任务。" : "当前筛选没有回答。请调整状态筛选。"),
      filters.review === "pending" ? h("button", { class: "button secondary", onClick: () => ctx.navigate("review", { run: runId, review: "all", status: filters.status }) }, "查看全部回答") : null));
  const pane = h("div", { class: "detail-pane" });
  pane.append(h("button", { class: "button secondary mobile-back", onClick: () => ctx.navigate("review", { run: runId, status: filters.status, review: filters.review }) }, "返回回答清单"));
  if (detail) renderAnswerDetail(pane, ctx, detail, filters, collection);
  root.append(h("div", { class: `split-layout has-rail wide-left evidence-browser${ctx.params.has("answer") ? " has-detail" : ""}` }, rail, pane));
  if (browser && detail?.status === "awaiting_collection" && !["awaiting_user", "paused_unknown"].includes(collection.browser_phase)) {
    let refreshing = false;
    const timer = setInterval(async () => {
      if (!ctx.isCurrent() || refreshing) return;
      refreshing = true;
      try { await ctx.refresh(); } finally { refreshing = false; }
    }, 3000);
    ctx.onCleanup(() => clearInterval(timer));
  }
}

function renderAnswerDetail(root, ctx, answer, filters, collection = null) {
  if (collection && answer.status === "awaiting_collection") {
    root.append(collection.collection_method === "browser_assisted"
      ? browserCollectionWorkspace(ctx, answer, collection)
      : collectionWorkspace(ctx, answer, collection));
    return;
  }
  if (collection) root.append(collectionFacts(ctx, collection));
  const latest = new Map();
  answer.observations.forEach((observation) => {
    const group = latest.get(observation.brand_entity_id) || [];
    group.push(observation); latest.set(observation.brand_entity_id, group);
  });
  const rawPanel = h("section", { class: "raw-panel" }, h("div", { class: "section-head" }, h("div", {}, h("h2", {}, `#${answer.id} · 原始回答`), h("p", {}, `${answer.engine_name || answer.model} · Round ${answer.round_no} · ${formatDate(answer.completed_at, ctx.project.timezone)}`)), badge(answer.status)),
    h("p", { class: "muted" }, answer.prompt_text),
    answer.raw_text ? h("div", { class: "raw-answer", tabindex: 0, role: "region", "aria-label": "原始回答全文" }, answer.raw_text) : h("div", { class: "inline-panel warning-panel" },
      h("h3", {}, answer.content_retained === 0 ? "原文已按保留策略清理" : answer.status === "failed" ? "没有有效回答原文" : "原文不可见"),
      h("p", {}, answer.content_retained === 0 ? "判定、有效样本事实和聚合指标仍保留；不能再新增依赖原文的 revision，新报告也无法通过原文证据闸门。" : answer.status === "failed" ? `${answer.error_type || "执行失败"}。失败样本不能解释为零提及；请由管理员确认是否重试。` : "当前角色可查看实体证据与状态，但不能读取内部原始回答。")),
    answer.citations.length ? h("div", { class: "inline-panel" }, h("h3", {}, answer.citations.every((citation) => citation.origin === "browser_page") ? "授权浏览器提取的页面引用" : answer.citations.every((citation) => citation.origin === "manual_page") ? "人工记录的页面引用" : "Provider 实际返回的来源"), answer.citations.map((citation) => h("p", {}, safeLink(citation.final_url || citation.raw_url, citation.title || citation.domain), h("span", { class: "cell-sub" }, `${citation.source_type} · ${citation.domain}`)))) : h("p", { class: "muted small" }, collection ? "未记录页面引用；不会把无来源回答判为无效，也不会补造 URL。" : "未暴露可核验来源；不会补造 URL。"));
  const observations = h("section", { class: "observations-panel" }, h("div", { class: "section-head" }, h("div", {}, h("h2", {}, "实体判定"),
    h("p", {}, latest.size ? `${latest.size} 个冻结实体 · 原文不会因修订改变` : "尚无实体判定 · 原文不会因修订改变"))));
  if (!latest.size) observations.append(emptyState("还没有实体判定", answer.status === "judging"
    ? "Judge 尚未写入判定。可稍后刷新，并检查下方调用元数据。"
    : ["failed", "cancelled"].includes(answer.status) ? "当前回答未形成有效判定；失败或取消不会被解释为零提及。"
      : "当前回答没有实体判定记录。请检查 Judge 调用状态，不要补造零提及。"));
  latest.forEach((versions) => {
    const current = versions[0];
    const panel = h("article", { class: `observation ${current.review_status === "confirmed" ? "confirmed" : current.review_status === "pending" ? "pending" : ""}` },
      h("div", { class: "observation-head" }, h("div", {}, h("h3", {}, current.name), h("span", { class: "cell-sub" }, `${label(current.role)} · ${label(current.judge_status)}`)),
        h("span", { class: "badge-context" }, h("span", { class: "quiet-label" }, "实体身份"), badge(current.entity_status))),
      h("div", { class: "button-group" }, badge(current.depth), badge(current.sentiment), current.top_choice ? badge("Top Choice", "info") : null,
        h("span", { class: "badge-context" }, h("span", { class: "quiet-label" }, "人工复核"), badge(current.review_status))),
      current.evidence ? h("blockquote", { class: "observation-evidence" }, current.evidence) : h("p", { class: "muted small" }, "无有效证据句"),
      current.citation_urls.length ? h("p", {}, current.citation_urls.map((url) => safeLink(url))) : null,
      h("div", { class: "button-group" },
        ["admin", "analyst"].includes(ctx.role) && answer.raw_text ? h("button", { class: "button small-button secondary", onClick: () => revisionDialog(ctx, answer, current, filters) }, "新增人工修订") : null,
        versions.length > 1 ? h("details", {}, h("summary", { class: "revision-note" }, `${versions.length} 个 revision`), versions.map((version) => h("p", { class: "revision-note" }, `r${version.revision} · ${version.judge_status} · ${version.review_reason || "机器判定"} · ${formatDate(version.created_at, ctx.project.timezone)}`))) : null));
    observations.append(panel);
  });
  root.append(h("div", { class: "evidence-layout" }, rawPanel, observations));
  root.append(h("details", { class: "advanced" }, h("summary", {}, "调用、模型与 Judge 元数据"), h("div", {},
    h("p", { class: "muted metadata-value" }, `返回模型：${answer.model || "—"}。usage：${JSON.stringify(answer.usage || {})}`),
    answer.call_attempts.length ? dataTable(["类型", "状态", "模型", "延迟", "Usage", "实际请求参数", "响应元数据", ...(ctx.role === "reviewer" || ctx.role === "viewer" ? [] : ["成本"])],
      answer.call_attempts.map((attempt) => [attempt.kind, label(attempt.status), attempt.model || "—", `${attempt.latency_ms || 0} ms`,
        h("span", { class: "metadata-value" }, JSON.stringify(attempt.usage || {})), h("span", { class: "metadata-value" }, JSON.stringify(attempt.request_params || {})),
        h("span", { class: "metadata-value" }, JSON.stringify(attempt.response_meta || {})), ...(ctx.role === "reviewer" || ctx.role === "viewer" ? [] : [attempt.cost ?? "未知"])])) : h("p", {}, "暂无调用记录"))));
}

function evidenceList(ctx, collection, onDelete = null) {
  if (!collection.attachments.length) return h("div", { class: "empty-state" }, h("p", {}, collection.collection_method === "browser_assisted" ? "授权浏览器尚未提交截图与回答区域 HTML；等待采集完成，不能在此人工补传。" : "尚未上传证据。正式提交至少需要一张 PNG、JPEG 或 WebP 截图。"));
  return h("div", { class: "evidence-files" }, collection.attachments.map((attachment) => h("div", { class: "evidence-file" },
    h("div", {}, h("strong", {}, attachment.filename), h("small", { class: "cell-sub" }, `${attachment.kind} · ${attachment.media_type} · ${attachment.byte_size} bytes`)),
    h("code", { class: "evidence-hash", title: attachment.sha256 }, `SHA-256 ${attachment.sha256}`),
    attachment.available ? h("div", { class: "button-group" },
      ["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button small-button secondary", onClick: () => download(`/api/projects/${ctx.project.id}/attachments/${attachment.id}`, attachment.filename).catch((error) => toast(error.message, true)) }, "下载") : null,
      onDelete ? h("button", { class: "button small-button ghost", onClick: () => onDelete(attachment) }, "删除") : null)
      : h("span", { class: "badge neutral" }, "字节已清理"))));
}

function collectionFacts(ctx, collection) {
  const actual = collection.session_context || {};
  const browser = collection.collection_method === "browser_assisted";
  return section(browser ? "授权浏览器 Consumer Web 采集事实" : "人工 Consumer Web 采集事实", `状态：${label(collection.status)} · ${browser ? "由独立网页 Driver 提取，提交后原文与证据不可覆盖" : "提交后正文、引用和采集事实不可覆盖"}`, h("div", {},
    h("dl", { class: "definition-list" },
      browser ? h("div", {}, h("dt", {}, "平台 Driver"), h("dd", {}, `${collection.browser_driver === "kimi_web" ? "Kimi Web" : "DeepSeek Web"} · ${collection.browser_driver_version || "版本未记录"}`)) : null,
      h("div", {}, h("dt", {}, "实际页面"), h("dd", {}, collection.actual_url || collection.conversation_url ? safeLink(collection.actual_url || collection.conversation_url) : "—")),
      h("div", {}, h("dt", {}, "观察时间"), h("dd", {}, collection.observed_at ? `${formatDate(collection.observed_at, collection.timezone || ctx.project.timezone)} · ${collection.timezone}` : "—")),
      h("div", {}, h("dt", {}, "页面 / 会话"), h("dd", {}, `${actual.surface || "—"} · ${collection.observed_mode || "—"} · ${actual.session_mode === "new" ? "新会话" : actual.session_mode || "—"}`)),
      h("div", {}, h("dt", {}, "检索状态"), h("dd", {}, collection.retrieval_status || "unknown")),
      h("div", {}, h("dt", {}, "提交时间"), h("dd", {}, formatDate(collection.submitted_at, ctx.project.timezone))),
      h("div", {}, h("dt", {}, "原文 SHA-256"), h("dd", { class: "evidence-hash" }, collection.raw_text_sha256 || "—"))),
    collection.failure_type ? h("div", { class: "inline-panel warning-panel" }, h("h3", {}, `采集失败：${collection.failure_type}`), h("p", {}, collection.failure_detail || "失败样本不计入有效提及；请由管理员在测量页确认重采。")) : null,
    collection.notes ? h("p", { class: "muted" }, collection.notes) : null,
    h("h3", {}, "截图与原始证据"), evidenceList(ctx, collection)));
}

function browserCollectionWorkspace(ctx, answer, collection) {
  const phase = collection.browser_phase || "queued";
  const needsAction = ["awaiting_user", "paused_unknown"].includes(phase);
  const sent = Boolean(collection.browser_send_started_at || collection.prompt_submitted_at);
  const canResume = needsAction && (!sent || Boolean(collection.conversation_url));
  const frozen = collection.collection_protocol || {};
  const driver = collection.browser_driver === "kimi_web" ? "Kimi Web" : "DeepSeek Web";
  const recover = () => confirmDialog("恢复授权浏览器采集", sent
    ? "采集器只会打开已记录的原会话，继续等待和提取回答，不会再次发送问题。恢复前必须已完成本机会话验证。"
    : "采集器将恢复原任务；如问题尚未发送，会在本机可见浏览器中执行本次冻结采集。请确认登录和验证码已处理，并已重新验证会话。",
  sent ? "恢复原会话，不重发" : "恢复当前采集", async () => {
    await api.post(`/api/projects/${ctx.project.id}/answers/${answer.id}/collection/resume`, { action: "resume" });
    toast("采集已恢复排队；不会自动重发已发送问题"); ctx.refresh();
  });
  const fail = () => confirmDialog("登记网页采集无法恢复", "该样本将标记为失败且不计入有效提及。原始结果不明的任务不会被重发；如需重采，请在测量页单独确认。", "登记失败", async () => {
    await api.post(`/api/projects/${ctx.project.id}/answers/${answer.id}/collection/resume`, { action: "fail", detail: "管理员确认当前网页结果无法可靠恢复，未形成有效样本" });
    toast("已登记采集失败；未计入有效样本"); ctx.refresh();
  }, true);
  const primary = ctx.role === "admin" && needsAction
    ? canResume ? h("button", { class: "button", onClick: recover }, sent ? "恢复原会话，不重发" : "已验证会话，恢复采集")
      : h("button", { class: "button danger", onClick: fail }, "登记无法恢复")
    : null;
  return h("div", { class: "browser-collection-workspace" },
    h("div", { class: `inline-panel${needsAction ? " warning-panel" : " emphasis"}` },
      h("h2", {}, `#${answer.id} · ${browserPhaseName(phase)}`),
      h("p", {}, answer.prompt_text),
      h("p", { class: "muted" }, collection.browser_phase_detail || (needsAction
        ? ctx.role === "admin" ? "请核对本机浏览器和原会话，再选择唯一合适的恢复操作。" : "等待管理员核对本机浏览器和原会话。"
        : "采集器正在本机串行处理；此页面不提供人工改录入。")),
      h("dl", { class: "definition-list" },
        h("div", {}, h("dt", {}, "采集平台"), h("dd", {}, driver)),
        h("div", {}, h("dt", {}, "问题发送"), h("dd", {}, collection.prompt_submitted_at ? `已发送 · ${formatDate(collection.prompt_submitted_at, ctx.project.timezone)}` : sent ? "发送结果待核对" : "尚未确认发送")),
        h("div", {}, h("dt", {}, "采集器心跳"), h("dd", {}, formatDate(collection.browser_heartbeat_at, ctx.project.timezone))),
        h("div", {}, h("dt", {}, "执行次数"), h("dd", {}, collection.browser_attempt_count || 0))),
      collection.conversation_url ? h("p", {}, safeLink(collection.conversation_url, "打开已记录的原会话")) : null,
      primary,
      ctx.role === "admin" && phase === "awaiting_user" ? h("p", { class: "muted small" }, "如会话已失效，请先到系统管理重新登录并验证，再点击恢复。") : null,
      ctx.role === "admin" && phase === "awaiting_user" ? h("a", { class: "button secondary", href: "#/admin?tab=engines" }, "管理本机浏览器连接") : null,
      ctx.role === "admin" && needsAction && canResume ? h("details", { class: "advanced danger-zone" }, h("summary", {}, "无法可靠恢复？登记失败"), h("div", {},
        h("p", { class: "muted" }, "只有确认无法核对原会话时才登记失败；不会把缺失回答算作零提及。"),
        h("button", { class: "button danger", onClick: fail }, "登记采集失败"))) : null),
    section("自动采集证据", "回答区域截图与 HTML 由 Collector 一并提交；自动任务不能通过人工上传接口补造证据", evidenceList(ctx, collection)),
    h("details", { class: "advanced" }, h("summary", {}, "查看冻结采集上下文"), h("div", {},
      h("dl", { class: "definition-list" },
        h("div", {}, h("dt", {}, "产品入口"), h("dd", {}, frozen.product_url || "—")),
        h("div", {}, h("dt", {}, "Driver 版本"), h("dd", {}, collection.browser_driver_version || "—")),
        h("div", {}, h("dt", {}, "页面 / 模式"), h("dd", {}, `${frozen.surface || "—"} · ${frozen.page_mode || "default"}`)),
        h("div", {}, h("dt", {}, "会话 / 追问"), h("dd", {}, `${frozen.session_mode || "—"} · ${frozen.follow_up_policy || "—"}`))),
      h("p", { class: "muted small" }, "网页引用只记录页面实际展示的 URL，不会自动访问，也不代表已核验正文支持关系。"))));
}

async function evidenceSha256(file) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function collectionWorkspace(ctx, answer, collection) {
  if (!["admin", "analyst"].includes(ctx.role)) return h("div", {},
    h("div", { class: "inline-panel emphasis" }, h("h2", {}, "等待内部成员完成人工采集"), h("p", {}, "当前角色可查看采集状态和实体证据，但不能编辑草稿、上传证据或下载内部附件。")),
    collectionFacts(ctx, collection));
  const frozen = collection.collection_protocol;
  const actual = collection.session_context || {};
  const draftText = textarea(collection.draft_text || "", { rows: 12, placeholder: "粘贴实际页面中的完整回答；空回答请登记失败，不要提交为零提及" });
  const actualUrl = input(collection.actual_url || frozen.product_url, { type: "url", required: true });
  const observedMode = input(collection.observed_mode || actual.page_mode || frozen.page_mode, { required: true });
  const observedAt = input(collection.observed_at || new Date().toISOString(), { required: true, placeholder: "2026-11-07T10:00:00+08:00" });
  const timezone = input(collection.timezone || "UTC", { required: true, placeholder: "UTC 或 Asia/Shanghai" });
  const retrieval = select(["unknown", "on", "off", "unavailable"].map((value) => ({ value, label: value })), collection.retrieval_status || "unknown");
  const status = select([{ value: "collecting", label: "采集中" }, { value: "review_pending", label: "待提交复核" }], ["collecting", "review_pending"].includes(collection.status) ? collection.status : "collecting");
  const notes = textarea(collection.notes || "", { rows: 3, placeholder: "记录观察限制；不要填写 Cookie、密码、Token 或账号别名" });
  const surface = select([{ value: "desktop_web", label: "桌面 Web" }, { value: "mobile_web", label: "移动 Web" }], actual.surface || frozen.surface);
  const sessionMode = select([{ value: "new", label: "新会话" }, { value: "continuous", label: "连续会话" }], actual.session_mode || frozen.session_mode);
  const loginState = select([{ value: "anonymous", label: "匿名访问" }, { value: "logged_in", label: "已登录" }], actual.login_state || frozen.login_state);
  const accountType = input(actual.account_type ?? frozen.account_type ?? "");
  const region = input(actual.region ?? frozen.region ?? "");
  const language = input(actual.language || frozen.language);
  const contextClearing = input(actual.context_clearing || frozen.context_clearing);
  const followUpPolicy = input(actual.follow_up_policy || frozen.follow_up_policy);
  const networking = checkbox("实际页面已联网", actual.networking ?? frozen.networking);
  const deepThinking = checkbox("实际开启深度思考", actual.deep_thinking ?? frozen.deep_thinking);
  const deepResearch = checkbox("实际开启深度研究", actual.deep_research ?? frozen.deep_research);
  const citationRows = [];
  const citationList = h("div", { class: "citation-list" });
  const addCitation = (item = {}) => {
    const url = input(item.url || "", { type: "url", placeholder: "https://实际看到的来源" });
    const title = input(item.title || "", { placeholder: "引用卡片标题" });
    const text = textarea(item.text || "", { rows: 2, placeholder: "实际看到的卡片文本，不要在后台抓取" });
    const row = { url, title, text, node: null };
    row.node = h("fieldset", { class: "citation-row" }, h("div", { class: "section-head" }, h("h4", {}, `页面引用 ${citationRows.length + 1}`),
      h("button", { class: "button small-button ghost", type: "button", onClick: () => { row.node.remove(); citationRows.splice(citationRows.indexOf(row), 1); } }, "移除")),
      field("URL", url), field("标题", title), field("卡片文本", text));
    citationRows.push(row); citationList.append(row.node);
  };
  (collection.citations || []).forEach(addCitation);
  const attachmentKind = select([{ value: "screenshot", label: "页面截图" }, { value: "raw_html", label: "原始 HTML（仅下载）" }, { value: "raw_text", label: "原始文本" }], "screenshot");
  const file = input("", { type: "file" });
  const syncFileAccept = () => {
    file.accept = attachmentKind.value === "screenshot" ? ".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" : attachmentKind.value === "raw_html" ? ".html,.htm,text/html" : ".txt,text/plain";
  };
  attachmentKind.addEventListener("change", syncFileAccept); syncFileAccept();
  const failureType = select(["captcha", "login_expired", "empty", "truncated", "error_page", "stream_interrupted", "other"].map((value) => ({ value, label: value })), "captcha");
  const failureDetail = textarea("", { rows: 3, placeholder: "说明无法形成有效样本的原因" });
  const payload = () => ({
    draft_text: draftText.value, actual_url: actualUrl.value, observed_mode: observedMode.value,
    observed_at: observedAt.value, timezone: timezone.value, retrieval_status: retrieval.value,
    notes: notes.value, status: status.value,
    session_context: {
      surface: surface.value, page_mode: observedMode.value, networking: networking.control.checked,
      deep_thinking: deepThinking.control.checked, deep_research: deepResearch.control.checked,
      session_mode: sessionMode.value, login_state: loginState.value, account_type: accountType.value,
      region: region.value, language: language.value, context_clearing: contextClearing.value,
      follow_up_policy: followUpPolicy.value,
    },
    citations: citationRows.filter((row) => row.url.value || row.title.value || row.text.value).map((row) => ({ url: row.url.value, title: row.title.value, text: row.text.value })),
  });
  const saveDraft = async (refresh = true) => {
    const saved = await api.put(`/api/projects/${ctx.project.id}/answers/${answer.id}/collection/draft`, payload());
    if (refresh) { toast("人工采集草稿已保存"); ctx.refresh(); }
    return saved;
  };
  const uploadEvidence = async (button) => {
    const selected = file.files?.[0];
    if (!selected) { formError(form, new Error("请先选择一份证据文件")); return; }
    if (!selected.size || selected.size > 10 * 1024 * 1024) { formError(form, new Error("证据文件必须非空且不超过 10MB")); return; }
    if (form.getAttribute("aria-busy") === "true") return;
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    try {
      await saveDraft(false);
    } catch (error) {
      formError(form, new Error(`草稿保存失败，尚未上传证据：${error.message}`));
      button.disabled = false;
      form.setAttribute("aria-busy", "false");
      return;
    }
    try {
      const extension = selected.name.split(".").pop()?.toLowerCase();
      const mediaType = attachmentKind.value === "raw_html" ? "text/html" : attachmentKind.value === "raw_text" ? "text/plain" : selected.type || ({ png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp" }[extension] || "");
      const digest = await evidenceSha256(selected);
      await api.upload(`/api/projects/${ctx.project.id}/answers/${answer.id}/attachments${query({ kind: attachmentKind.value, filename: selected.name, media_type: mediaType })}`, selected, digest);
      toast("草稿与证据已保存"); ctx.refresh();
    } catch (error) {
      formError(form, new Error(`当前草稿已保存；证据上传未完成：${error.message}`));
    } finally {
      if (form.isConnected) {
        button.disabled = false;
        form.setAttribute("aria-busy", "false");
      }
    }
  };
  const deleteEvidence = (attachment) => confirmDialog("删除草稿证据", `将删除 ${attachment.filename}。当前表单会先保存为草稿；正式提交后不能删除证据。`, "删除附件", async () => {
    await saveDraft(false);
    await api.delete(`/api/projects/${ctx.project.id}/attachments/${attachment.id}`);
    toast("草稿附件已删除"); ctx.refresh();
  }, true);
  const form = h("form", { class: "collection-form" },
    h("div", { class: "inline-panel emphasis" }, h("h2", {}, `#${answer.id} · 完成人工页面采集`),
      h("p", {}, answer.prompt_text), h("p", { class: "muted small" }, `冻结入口：${frozen.product_url}。请人工在页面中观察；系统不会自动打开产品、保存 Cookie 或绕过验证码。`),
      safeLink(frozen.product_url, "打开冻结产品入口")),
    section("1. 回答与观察事实", "草稿可以暂不完整；正式提交时正文、origin、时间和上下文必须有效", h("div", {},
      field("实际回答全文", draftText, "提交后不可覆盖；修正需要新尝试", true),
      h("div", { class: "form-grid" }, field("实际页面 URL", actualUrl), field("实际页面模型 / 模式", observedMode),
        field("观察时间（含 offset）", observedAt), field("IANA 时区", timezone, "默认 UTC；改为项目时区时必须同步调整时间 offset"),
        field("检索状态", retrieval), field("草稿状态", status)),
      field("采集备注", notes))),
    section("2. 核对实际采集上下文", "以下值必须与冻结协议逐项一致；如有变化，请新建 Wave，不要改写本次测量", h("div", {},
      h("div", { class: "form-grid" }, field("页面形态", surface), field("会话策略", sessionMode), field("登录状态", loginState),
        field("账号类型", accountType, "仅 free/pro 等类型，不填账号别名"), field("地区", region), field("语言", language),
        field("上下文清理", contextClearing), field("追问策略", followUpPolicy)),
      networking.node, deepThinking.node, deepResearch.node)),
    section("3. 截图与原始证据", "单个文件最大 10MB，每个回答最多 12 个；HTML/文本只作为附件下载，不在页面中执行", h("div", {},
      evidenceList(ctx, collection, deleteEvidence),
      h("div", { class: "form-grid evidence-upload" }, field("证据类型", attachmentKind), field("选择文件", file)),
      h("button", { class: "button secondary", type: "button", onClick: (event) => uploadEvidence(event.currentTarget) }, "保存草稿并上传证据"))),
    section("4. 人工记录的页面引用", "只记录你实际看到的 URL、标题和卡片文本；系统不会抓取目标页面。无来源回答可以留空", h("div", {}, citationList,
      h("button", { class: "button secondary", type: "button", onClick: () => addCitation() }, "添加页面引用"))),
    h("div", { class: "form-actions sticky-actions" },
      h("button", { class: "button secondary", type: "submit" }, "保存草稿"),
      h("button", { class: "button", type: "button", onClick: () => {
        if (!collection.attachments.some((item) => item.kind === "screenshot" && item.available)) { formError(form, new Error("请先上传至少一张有效截图")); return; }
        confirmDialog("正式提交人工采集", "提交将一次性冻结回答正文、页面引用和采集事实，并进入独立 Judge。之后不能覆盖原文或删除证据。", "正式提交并进入判定", async () => {
          await api.post(`/api/projects/${ctx.project.id}/answers/${answer.id}/collection/submit`, payload());
          toast("人工回答已提交，正在判定"); ctx.refresh();
        });
      } }, "核对并正式提交")),
    h("details", { class: "advanced danger-zone" }, h("summary", {}, "无法完成采集？登记失败"), h("div", {},
      h("p", { class: "muted" }, "验证码、登录失效、空正文、截断、错误页和流式中断都必须登记为失败，valid_sample=0，不会成为零提及。重采由管理员在测量页确认。"),
      h("div", { class: "form-grid" }, field("失败类型", failureType), field("失败说明", failureDetail)),
      h("button", { class: "button danger", type: "button", onClick: () => {
        if (!failureDetail.value.trim()) { formError(form, new Error("请填写失败说明")); return; }
        confirmDialog("登记人工采集失败", "当前表单会先保存为草稿，再将该样本标记为失败。失败样本需要管理员确认后才能重采。", "登记失败", async () => {
          await saveDraft(false);
          await api.post(`/api/projects/${ctx.project.id}/answers/${answer.id}/collection/fail`, { failure_type: failureType.value, failure_detail: failureDetail.value, notes: notes.value });
          toast("已登记采集失败；未计入有效样本"); ctx.refresh();
        }, true);
      } }, "保存草稿并登记失败"))));
  onSubmit(form, async () => { await saveDraft(); });
  return form;
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
  onSubmit(form, async () => {
    await api.post(`/api/projects/${ctx.project.id}/answers/${answer.id}/observations/${observation.id}/revisions`, {
      entity_status: entityStatus.value, mentioned: mentioned.control.checked, depth: depth.value, sentiment: sentiment.value,
      top_choice: topChoice.control.checked, evidence: evidence.value, reason: reason.value,
      arbitrate: ctx.role === "admin" && arbitrate.control.checked,
    });
    modal.close(); toast("新 revision 已保存，原始回答未改变"); ctx.refresh();
  });
}
