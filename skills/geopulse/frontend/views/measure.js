import { api } from "../api.js";
import { executionFields } from "../execution.js";
import { h, clear, pageHead, section, dataTable, badge, metric, drawer, field, input, select, checkbox, toast, formError, confirmDialog, formatDate, label, emptyState, handleBudgetError, pct, onSubmit } from "../components.js";

const openRunHistories = new Set();
const isManualWave = (wave) => wave.protocol.measurement_target === "consumer_web";
const isBrowserWave = (wave) => wave.protocol.collection_protocol?.collection_method === "browser_assisted";
const driverName = (driver) => driver === "kimi_web" ? "Kimi Web" : "DeepSeek Web";
const browserPhaseName = (phase) => ({
  queued: "等待本机采集器", session_check: "检查登录会话", preparing: "准备新会话",
  submitting: "正在发送问题", waiting: "等待网页回答", extracting: "提取回答与证据",
  uploading: "保存原始证据", awaiting_user: "需要处理登录或验证码",
  paused_unknown: "结果不明，等待管理员核对", completed: "采集完成", failed: "采集失败",
}[phase] || phase || "等待采集");
const requiresRealConfirmation = (wave) => [
  ...(wave.protocol.engine_signature || []),
  ...(wave.protocol.judge_signature ? [wave.protocol.judge_signature] : []),
].some((engine) => !["demo", "manual_web"].includes(engine.kind));

function executionText(execution) {
  if (!execution) return "—";
  const value = (key) => execution[key] === null ? "不发送" : execution[key] ?? "继承";
  return `temperature=${value("temperature")} · max_tokens=${value("max_tokens")} · system=${execution.system_prompt === null ? "不发送" : execution.system_prompt === "" ? "空 system" : "已冻结"}`;
}

function frozenExecution(protocol) {
  return h("details", { class: "advanced" }, h("summary", {}, "查看冻结执行参数"), h("div", {},
    h("p", { class: "muted small" }, `Judge 方式：${protocol.judge_mode === "independent" ? `独立 Judge · ${protocol.judge_signature?.name || "未配置"}` : protocol.judge_mode === "disabled" ? "已关闭" : "各回答引擎兼任 Judge"}。这里只展示非秘密参数摘要。`),
    dataTable(["回答引擎", "回答请求", "Judge 请求"], (protocol.engine_signature || []).map((engine) => [
      engine.name,
      protocol.measurement_target === "consumer_web" ? `${protocol.collection_protocol?.collection_method === "browser_assisted" ? "授权浏览器" : "人工"}页面回答` : executionText(protocol.answer_execution?.[engine.id]),
      executionText(protocol.judge_execution?.[engine.id]),
    ]))));
}

export async function renderMeasure(root, ctx) {
  const [waveData, setData, engineData] = await Promise.all([
    api.get(`/api/projects/${ctx.project.id}/waves`), api.get(`/api/projects/${ctx.project.id}/prompt-sets`), api.get(`/api/projects/${ctx.project.id}/engines`),
  ]);
  const waves = waveData.items;
  const browserSessions = {};
  if (ctx.role === "admin") {
    await Promise.all(engineData.items.filter((engine) => engine.kind === "manual_web").map(async (engine) => {
      browserSessions[engine.id] = (await api.get(`/api/projects/${ctx.project.id}/engines/${engine.id}/browser-sessions`)).items;
    }));
  }
  if (!ctx.isCurrent()) return;
  const actions = [["admin", "analyst"].includes(ctx.role) ? h("button", { class: `button${waves.length ? " secondary" : ""}`, onClick: () => waveWizard(ctx, setData.items, engineData.items, browserSessions) }, "新建测量方案") : null];
  if (!waves.length) {
    clear(root); root.append(pageHead("测量执行", "wave 冻结测量口径，run 记录每一次执行尝试。", actions),
      emptyState("还没有测量方案", "先创建 wave 并检查调用预估；只有确认创建 run 后才会进入执行队列。", null));
    return;
  }
  const wave = waves.find((item) => String(item.id) === ctx.params.get("wave")) || waves[0];
  const selectedRunId = Number(ctx.params.get("run")) || wave.runs[0]?.id;
  const run = selectedRunId ? await api.get(`/api/projects/${ctx.project.id}/runs/${selectedRunId}`) : null;
  const [metrics, handoff] = run ? await Promise.all([
    api.get(`/api/projects/${ctx.project.id}/runs/${run.id}/metrics`),
    api.get(`/api/projects/${ctx.project.id}/runs/${run.id}/handoff`),
  ]) : [null, null];
  if (!ctx.isCurrent()) return;
  const protocol = wave.protocol;
  const manual = isManualWave(wave);
  const browser = isBrowserWave(wave);
  ctx.setProtocol({ promptSet: `ID ${protocol.prompt_set_id} · ${protocol.prompt_set_hash.slice(0, 8)}`, entityVersion: protocol.entity_version,
    engines: protocol.engine_signature.map((engine) => engine.name).join(" / "), mode: protocol.mode,
    target: protocol.measurement_target, repeats: protocol.repeats, n: metrics?.quality?.valid_samples,
    demo: metrics?.is_demo, real: metrics && !metrics.is_demo });
  clear(root);
  root.append(pageHead("测量执行", "先冻结口径并查看预估，再创建 run。失败、取消和空回答不会进入有效样本分母。", actions));
  const rail = h("aside", { class: "list-rail" }, h("div", { class: "list-rail-head" }, h("strong", {}, "Wave 列表"), h("span", { class: "muted small" }, `${waves.length} 个`)),
    waves.map((item) => h("button", { class: `list-item${item.id === wave.id ? " active" : ""}`, "aria-current": item.id === wave.id ? "location" : null, "data-wave-id": item.id, onClick: () => ctx.navigate("measure", { wave: item.id }) },
      h("strong", {}, item.label), badge(item.status), h("small", { class: "cell-sub" }, `${item.runs.length} 个 run · ${formatDate(item.created_at, ctx.project.timezone)}`))));
  const narrowRail = window.matchMedia("(max-width: 1100px)");
  const railDetails = h("details", { class: "wave-rail", open: !narrowRail.matches },
    h("summary", {}, h("span", {}, `当前 Wave：${wave.label}`), h("small", {}, `${waves.length} 个方案`)), rail);
  const syncRail = () => { railDetails.open = !narrowRail.matches; };
  narrowRail.addEventListener("change", syncRail);
  ctx.onCleanup(() => narrowRail.removeEventListener("change", syncRail));
  const detail = h("div", { class: "detail-pane" });
  const active = run && ["queued", "running"].includes(run.status);
  const canSelectOfficial = run && ["done", "partial"].includes(run.status) && ctx.role === "admin" && wave.official_run_id !== run.id;
  detail.append(h("section", { class: "inline-panel wave-summary" }, h("div", { class: "section-head" },
    h("div", {}, h("h2", {}, wave.label), h("p", {}, `Wave #${wave.id} · ${label(wave.status)}${wave.official_run_id ? ` · 正式 Run #${wave.official_run_id}` : " · 尚未指定正式 run"}`)),
    h("div", { class: "button-group" },
      ["admin", "analyst"].includes(ctx.role) ? h("button", { class: `button${active || canSelectOfficial ? " secondary" : ""}`, disabled: wave.readiness?.requires_judge_disabled_confirmation && ctx.role !== "admin", title: wave.readiness?.requires_judge_disabled_confirmation && ctx.role !== "admin" ? "关闭 Judge 的真实 Run 必须由管理员确认" : "", onClick: () => confirmRun(ctx, wave) }, browser ? "创建授权采集 Run" : manual ? "创建人工采集 Run" : wave.readiness?.requires_judge_disabled_confirmation && ctx.role !== "admin" ? "需管理员确认关闭 Judge" : wave.runs.length ? "创建重试 Run" : "确认并创建 Run") : null,
      wave.official_run_id ? h("a", { class: "button secondary", href: `#/reports?wave=${wave.id}` }, "生成报告") : null)),
    readinessSummary(wave.readiness),
    h("dl", { class: "definition-list" },
      h("div", {}, h("dt", {}, "测量目标"), h("dd", {}, `${label(protocol.mode)} · ${label(protocol.measurement_target)}`)),
      h("div", {}, h("dt", {}, "采集方法"), h("dd", {}, browser ? `授权浏览器 · ${driverName(protocol.collection_protocol.browser_driver)}` : manual ? "人工网页采集" : "Provider API")),
      h("div", {}, h("dt", {}, "问题 / 目标 / 轮次"), h("dd", {}, `${wave.estimate.prompt_items} × ${wave.estimate.engines} × ${protocol.repeats}`)),
      manual ? h("div", {}, h("dt", {}, browser ? "串行浏览器任务" : "待人工采集任务"), h("dd", { class: "num" }, wave.estimate.collection_tasks)) : null,
      h("div", {}, h("dt", {}, manual ? "独立 Judge 基础 / 重试上限" : "基础 / 安全重试调用"), h("dd", { class: "num" }, `${wave.estimate.total_external_calls} / ${wave.estimate.max_external_calls}`)),
      ["admin", "analyst"].includes(ctx.role) ? h("div", {}, h("dt", {}, "基础 / 含重试费用预估"), h("dd", {}, wave.estimate.cost_unknown ? "部分价格未知" : `${wave.estimate.estimated_cost} / ${wave.estimate.max_estimated_cost} ${wave.estimate.currency || ""}`)) : null),
    h("p", { class: "muted small" }, wave.estimate.note),
    manual ? h("details", { class: "advanced" }, h("summary", {}, "查看冻结采集协议"), h("div", {},
      h("p", {}, protocol.collection_protocol.product_url),
      h("p", { class: "muted small" }, `${browser ? `授权浏览器 · ${driverName(protocol.collection_protocol.browser_driver)}` : "人工采集"} · ${label(protocol.collection_protocol.surface)} · ${protocol.collection_protocol.page_mode || "默认模式"} · ${protocol.collection_protocol.session_mode === "new" ? "新会话" : "连续会话"} · ${protocol.collection_protocol.language}`),
      h("p", { class: "muted small" }, `独立 Judge：${protocol.judge_signature?.name || "未启用"}。联网、深度开关、登录状态、上下文清理和追问策略均已冻结；实际提交必须逐项一致。${browser ? "采集器只访问对应产品，不自动打开页面引用。" : ""}`))) : null,
    frozenExecution(protocol)));
  if (run) {
    const progress = run.progress;
    const completedBatch = run.quality?.judge_lineage === "consistent" ? run.quality.judge_batches?.at(-1) : null;
    const judgeText = completedBatch ? `补判完成：${completedBatch.judge_engine.name}`
      : manual ? run.snapshot.protocol.use_judge ? `独立 Judge：${protocol.judge_signature?.name || "未配置"}` : "规则回退，需人工仲裁"
        : run.snapshot.protocol.use_judge ? protocol.judge_mode === "independent" ? `独立 Judge：${protocol.judge_signature?.name || "未配置"}` : "各回答引擎兼任结构化 Judge" : "规则回退";
    detail.append(deliveryPanel(ctx, wave, run, handoff, engineData.items));
    detail.append(h("section", { class: "inline-panel run-focus" }, h("div", { class: "section-head" }, h("div", {}, h("h2", {}, `Run #${run.id} · 第 ${run.attempt_no} 次尝试`), h("p", { dataset: { runStatus: "" } }, `${label(run.status)} · ${judgeText}${metrics.is_demo ? " · 演示数据" : ""}`)),
      h("div", { class: "button-group" },
        active && ["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button danger small-button", onClick: () => cancelRun(ctx, wave, run) }, "取消 Run") : null,
        ["failed", "cancelled", "partial"].includes(run.status) && ctx.role === "admin" ? h("button", { class: "button secondary small-button", onClick: () => retryRun(ctx, run) }, "确认重试失败样本") : null,
        canSelectOfficial ? h("button", { class: "button secondary small-button", onClick: () => selectOfficial(ctx, wave, run) }, "指定为正式 Run") : null,
        h("a", { class: "button secondary small-button", href: `#/review?run=${run.id}` }, browser ? "查看采集与证据" : manual ? "采集与复核证据" : "复核证据"))),
      browser ? browserRunProgress(progress.browser, ctx, run.id) : null,
      h("div", { class: "progress-track", dataset: { runProgress: "" }, role: "progressbar", "aria-valuenow": progress.progress, "aria-valuemin": 0, "aria-valuemax": 100, "aria-label": "Run 完成进度" }, h("div", { class: "progress-bar", style: `width:${progress.progress}%` })),
      h("div", { class: "progress-meta" }, h("span", { dataset: { progressCount: "" } }, `${progress.finished}/${progress.total} 个样本已结束`), h("span", { class: "num", dataset: { progressPercent: "" } }, `${progress.progress}%`)),
      run.error ? h("p", { class: "form-error" }, run.error) : null));
    const results = h("section", { class: "run-results" }, h("div", { class: "section-head" }, h("div", {}, h("h2", {}, "测量结果"), h("p", {}, "先看有效样本与不确定性，再进入维度和实体诊断。"))));
    if (metrics.quality.valid_samples) {
      results.append(h("div", { class: "metric-strip" }, metric("意图覆盖", metrics.coverage), metric("稳定命中", metrics.hit_rate), metric("有效推荐", metrics.effective_recommendation_rate), metric("北极星", metrics.north_star)));
      results.append(h("p", { class: "muted small" }, metrics.coverage.limited ? "小样本仅展示原始计数与方向；不显示确定性 SoV 或百分点诊断。" : `SoV ${pct(metrics.share_of_voice.value)} · ${metrics.share_of_voice.definition}。${metrics.limitations.join("；")}`));
    } else results.append(h("div", { class: "inline-panel warning-panel" }, h("h3", {}, manual && metrics.quality.awaiting_collection ? browser ? "等待授权浏览器采集与证据提交" : "等待人工采集与证据提交" : "当前没有可诊断的有效样本"), h("p", {}, browser ? "采集器会逐条发送冻结问题并保存回答区域截图和 HTML。登录、验证码或结果不明时需要管理员处理；失败样本不会成为零提及。" : manual ? "进入“采集与复核证据”，逐条填写实际页面回答并上传截图。待采集、失败或上下文不符的样本不会成为零提及。" : "请检查队列、引擎错误和取消记录。这里不会显示“0% 提及”作为业务结论。")));
    results.append(h("dl", { class: "definition-list quality-ledger" },
      h("div", {}, h("dt", {}, "有效样本"), h("dd", {}, `${metrics.quality.valid_samples}/${metrics.quality.expected_samples}`)),
      h("div", {}, h("dt", {}, "失败 / 取消"), h("dd", {}, `${metrics.quality.failed_samples} / ${metrics.quality.cancelled_samples}`)),
      h("div", {}, h("dt", {}, "待复核回答"), h("dd", {}, metrics.quality.pending_review_answers)),
      h("div", {}, h("dt", {}, "Judge 降级"), h("dd", {}, `${metrics.quality.judge_fallback_rate.hits}/${metrics.quality.judge_fallback_rate.n}`)),
      manual ? h("div", {}, h("dt", {}, browser ? "待网页采集" : "待人工采集"), h("dd", {}, metrics.quality.awaiting_collection || 0)) : null,
      manual ? h("div", {}, h("dt", {}, "有效样本证据覆盖"), h("dd", {}, `${metrics.quality.evidence_coverage?.hits || 0}/${metrics.quality.evidence_coverage?.n || 0}`)) : null));
    results.append(qualityDetails(run.quality, ctx, wave, run));
    detail.append(results);
    const diagnostics = h("div", { class: "run-diagnostics" });
    if (metrics.dimensions.length) diagnostics.append(section("四维原始计数", "小样本只展示计数与方向，不据此判定确定胜负", dataTable(["维度", "覆盖", "命中 / 有效回答", "样本"], metrics.dimensions.map((row) => [label(row.key), `${row.coverage.hits}/${row.coverage.n}${row.coverage.limited ? "" : ` · ${pct(row.coverage.value)}`}`, `${row.hit_rate.hits}/${row.hit_rate.n}`, row.samples]))));
    if (metrics.competitors.length) diagnostics.append(section("实体池表现", "SoV 与主品牌采用完全相同的意图×引擎加权口径；小样本不显示 SoV", dataTable(["实体", "角色", "确认提及", "SoV", "负面"], metrics.competitors.map((row) => [row.name, label(row.role), row.mentions, metrics.coverage.limited ? "—" : pct(row.sov), row.negative]))));
    if (diagnostics.childNodes.length) detail.append(diagnostics);
  } else detail.append(emptyState(browser ? "尚未创建授权浏览器 Run" : manual ? "尚未创建人工采集 Run" : "尚未创建 run", browser ? "创建前会确认第三方产品、问题数和独立 Judge。只有已验证的本机会话才能执行；创建后任务全局串行，结果不明不会自动重发。" : manual ? "创建后系统只生成待采集任务，不会自动打开或操作产品网页。请在证据复核页人工提交回答与截图。" : "调用预估仅用于确认，不会自动执行。创建后即使离开页面，持久队列也会继续。", null));
  const historyKey = `${ctx.project.id}:${wave.id}`;
  const history = h("details", { class: "advanced run-history", open: openRunHistories.has(historyKey) },
    h("summary", {}, h("span", {}, "此 Wave 的执行记录"), h("small", {}, `${run ? `选中 Run #${run.id} · ` : ""}${wave.runs.length} 次尝试`)),
    h("div", {}, h("p", { class: "muted small" }, "正式 run 只能由管理员人工指定；重试不会覆盖原回答"), dataTable(["Run", "状态", "开始", "结束", "操作"], wave.runs.map((item) => [
      `#${item.id} · 第 ${item.attempt_no} 次`, badge(item.status), formatDate(item.started_at, ctx.project.timezone), formatDate(item.finished_at, ctx.project.timezone),
      h("button", { class: "table-link", "data-run-id": item.id, onClick: () => ctx.navigate("measure", { wave: wave.id, run: item.id }) }, "打开"),
    ]), "尚无执行记录。")));
  history.addEventListener("toggle", () => {
    if (history.open) openRunHistories.add(historyKey); else openRunHistories.delete(historyKey);
  });
  detail.append(history);
  root.append(h("div", { class: "split-layout has-rail measure-browser" }, railDetails, detail));
  if (active) {
    let polling = false;
    const timer = setInterval(async () => {
      if (!ctx.isCurrent() || polling) return;
      polling = true;
      try {
        const fresh = await api.get(`/api/projects/${ctx.project.id}/runs/${run.id}`);
        if (!ctx.isCurrent()) return;
        if (!["queued", "running"].includes(fresh.status)) { ctx.refresh(); return; }
        const track = detail.querySelector("[data-run-progress]");
        if (!track) return;
        track.setAttribute("aria-valuenow", fresh.progress.progress);
        track.querySelector(".progress-bar").style.width = `${fresh.progress.progress}%`;
        detail.querySelector("[data-progress-count]").textContent = `${fresh.progress.finished}/${fresh.progress.total} 个样本已结束`;
        detail.querySelector("[data-progress-percent]").textContent = `${fresh.progress.progress}%`;
        updateBrowserRunProgress(detail.querySelector("[data-browser-progress]"), fresh.progress.browser, ctx, run.id);
      } catch { /* Keep the last confirmed progress; the next poll can retry. */ }
      finally { polling = false; }
    }, 2500);
    ctx.onCleanup(() => clearInterval(timer));
  }
}

function readinessSummary(readiness, showTitle = true) {
  if (!readiness) return null;
  const duration = readiness.duration?.status === "estimated"
    ? `历史估算 ${readiness.duration.min_seconds}–${readiness.duration.max_seconds} 秒（${readiness.duration.samples} 条调用样本）`
    : readiness.duration?.status === "not_applicable" ? "离线 Demo 不估算真实模型时长" : "历史耗时未知";
  return h("div", { class: `inline-panel${readiness.status === "blocked" ? " warning-panel" : " emphasis"}` },
    showTitle ? h("h3", {}, "测量准备单") : null,
    h("p", {}, `${readiness.status === "blocked" ? "存在阻断项" : readiness.status === "ready_with_warnings" ? "可准备，但有风险需确认" : "配置检查通过"} · ${duration}`),
    readiness.requires_judge_disabled_confirmation ? h("p", { class: "form-error" }, "真实 Provider 已关闭 Judge：创建 Run 时管理员必须显式确认；草稿 Wave 可以保留。") : null,
    readiness.warnings?.length ? h("ul", { class: "muted small" }, readiness.warnings.map((warning) => h("li", {}, warning))) : null,
    readiness.blocking_reasons?.map((reason) => h("p", { class: "form-error" }, reason)),
    h("p", { class: "muted small" }, readiness.duration?.reason || readiness.duration?.note || readiness.note));
}

const nextActionLabels = {
  wait_for_execution: "等待执行与补判结束", retry_failed_samples: "重试失败样本",
  create_judge_batch: "创建补判批次", complete_judge_coverage: "补齐 Judge 覆盖",
  review_evidence: "复核待确认证据", select_official_run: "指定正式 Run",
  review_quality_limits: "检查质量限制", generate_opportunities: "发现候选机会",
  review_opportunities: "确认机会适用性", create_report: "创建平台报告",
  approve_report: "完成报告审批", record_work_log_reminder: "人工登记工时",
  close_or_analyze_wave: "标记 Wave 已分析", ready: "进入交付下一步", complete: "本轮交接已完成",
};

function deliveryPanel(ctx, wave, run, handoff, engines) {
  const quality = run.quality;
  const next = handoff?.next_action || quality.next_action;
  let action = null;
  if (["create_judge_batch", "complete_judge_coverage"].includes(next.kind) && ctx.role === "admin") {
    action = h("button", { class: "button", onClick: () => judgeBatchDialog(ctx, run, engines) }, nextActionLabels[next.kind]);
  } else if (next.kind === "retry_failed_samples" && ctx.role === "admin") {
    action = h("button", { class: "button", onClick: () => retryRun(ctx, run) }, nextActionLabels[next.kind]);
  } else if (next.kind === "select_official_run" && ctx.role === "admin") {
    action = h("button", { class: "button", onClick: () => selectOfficial(ctx, wave, run) }, nextActionLabels[next.kind]);
  } else if (next.kind === "review_evidence") {
    action = h("a", { class: "button", href: `#/review?run=${run.id}&review=pending` }, nextActionLabels[next.kind]);
  } else if (next.kind === "generate_opportunities" && ["admin", "analyst"].includes(ctx.role)) {
    action = h("a", { class: "button", href: `#/opportunities?wave=${wave.id}` }, nextActionLabels[next.kind]);
  } else if (next.kind === "review_opportunities" && ctx.role === "admin") {
    action = h("a", { class: "button", href: `#/opportunities?wave=${wave.id}` }, nextActionLabels[next.kind]);
  } else if (next.kind === "create_report" && ["admin", "analyst"].includes(ctx.role)) {
    action = h("a", { class: "button", href: `#/reports?wave=${wave.id}` }, nextActionLabels[next.kind]);
  } else if (next.kind === "approve_report" && ctx.role === "admin") {
    action = h("a", { class: "button", href: `#/reports?wave=${wave.id}` }, nextActionLabels[next.kind]);
  } else if (next.kind === "record_work_log_reminder" && ["admin", "analyst"].includes(ctx.role)) {
    action = h("a", { class: "button secondary", href: "#/admin?tab=operations" }, nextActionLabels[next.kind]);
  } else if (next.kind === "close_or_analyze_wave" && ctx.role === "admin") {
    action = h("button", { class: "button", onClick: () => confirmDialog(
      "标记 Wave 已分析", "报告已批准且工时已提醒。确认本轮分析收尾？此操作只更新 Wave 状态，不改写 Run、证据或报告。", "确认标记", async () => {
        await api.post(`/api/projects/${ctx.project.id}/waves/${wave.id}/status`, { status: "analyzed", reason: "交付交接完成，人工确认收尾" });
        toast("Wave 已标记为已分析"); ctx.refresh();
      }) }, nextActionLabels[next.kind]);
  }
  return h("section", { class: `inline-panel${quality.delivery_readiness === "not_ready" ? " warning-panel" : " emphasis"}` },
    h("div", { class: "section-head" }, h("div", {},
      h("h2", {}, quality.delivery_readiness === "ready" ? "可以交付" : quality.delivery_readiness === "ready_with_limitations" ? "可带限制交付" : "尚未达到交付条件"),
      h("p", {}, `唯一下一步：${nextActionLabels[next.kind] || next.kind}`)), action),
    quality.blocking_reasons?.length ? h("ul", { class: "muted" }, quality.blocking_reasons.map((reason) => h("li", {}, reason))) : h("p", { class: "muted" }, "执行与判定质量检查已通过；仍须遵守小样本和因果边界。"),
    handoff?.opportunities?.status === "checked_empty" ? h("p", { class: "muted small" }, "机会发现已执行，结果为 0；不是“尚未检查”。") : null,
    handoff?.work_log?.missing && handoff?.report ? h("p", { class: "muted small" }, "项目尚未登记工时；这里只提醒，不会自动把 Run 时长记为咨询工时。") : null);
}

function qualityDetails(quality, ctx, wave, run) {
  const modelRows = [
    ...(quality.models?.answers || []).map((row) => ["回答", row.name, row.configured_model, row.actual_models.join("、") || "未返回", row.provider_routing_observed ? "观察到厂商路由差异" : "—"]),
    ...(quality.models?.judges || []).map((row) => [`Judge${row.judge_batch_id ? ` #${row.judge_batch_id}` : ""}`, row.name, row.configured_model, row.actual_models.join("、") || "未返回", row.provider_routing_observed ? "观察到厂商路由差异，不判失败" : "—"]),
  ];
  return h("details", { class: "advanced" }, h("summary", {}, "判定质量、实际模型与补判记录"), h("div", {},
    h("p", { class: "muted small" }, `有效 Judge 口径：${quality.judge_lineage} · 补判覆盖 ${quality.judge_coverage.hits}/${quality.judge_coverage.n} · provisional 推荐 ${quality.provisional_recommendations} · 人工 revision ${quality.human_revisions}`),
    dataTable(["角色", "引擎", "配置模型", "实际返回模型", "路由说明"], modelRows),
    dataTable(["Batch", "状态", "覆盖", "Judge", "操作"], (quality.judge_batches || []).map((batch) => [
      `#${batch.id}`, badge(batch.status), `${batch.done}/${batch.total} · 失败 ${batch.failed}`,
      `${batch.judge_engine.name} / ${batch.judge_engine.model}`,
      h("div", { class: "button-group" },
        ["queued", "running"].includes(batch.status) && ctx.role === "admin" ? h("button", { class: "button small-button secondary", onClick: () => cancelJudgeBatch(ctx, batch) }, "取消补判") : null,
        ["failed", "partial"].includes(batch.status) && ctx.role === "admin" ? h("button", { class: "button small-button secondary", onClick: () => retryJudgeBatch(ctx, batch) }, "重试明确失败项") : null),
    ]), "尚无补判批次。")));
}

async function judgeBatchDialog(ctx, run, engines) {
  const realRun = (run.snapshot.protocol.engine_signature || []).some((engine) => engine.kind !== "demo");
  const eligibleEngines = engines.filter((engine) => engine.enabled && engine.kind !== "manual_web" && (realRun ? engine.kind !== "demo" : engine.kind === "demo"));
  if (!eligibleEngines.length) { toast(realRun ? "请先配置真实 Judge 引擎" : "没有可用的 Demo Judge", true); return; }
  const answerData = await api.get(`/api/projects/${ctx.project.id}/runs/${run.id}/answers?limit=200`);
  const scope = select([{ value: "all", label: "全部可补判回答" }, { value: "selected", label: "逐题选择" }], "all");
  const judge = select(eligibleEngines.map((engine) => ({ value: engine.id, label: `${engine.name} · ${engine.model || engine.kind}` })), eligibleEngines[0].id);
  const overrides = executionFields({}, "judge", "Judge 参数（可选，继承引擎配置）");
  const checks = answerData.items.map((answer) => {
    const control = checkbox(`#${answer.id} · ${answer.prompt_text}`, answer.status === "succeeded" && answer.content_retained !== 0,
      answer.status !== "succeeded" ? "无效样本不能补判" : answer.content_retained === 0 ? "原文已清理，不能补判" : `已有 ${answer.observations.length} 条当前实体判定`,
      { disabled: answer.status !== "succeeded" || answer.content_retained === 0 });
    control.answerId = answer.id;
    return control;
  });
  const answerPanel = h("div", { hidden: true }, checks.map((control) => control.node));
  scope.addEventListener("change", () => { answerPanel.hidden = scope.value !== "selected"; });
  const estimate = h("div", {});
  const form = h("form", {},
    h("p", { class: "muted" }, "只读取已有有效原文并追加 Observation revision。Answer、raw hash、原 Run、Citation 不变；不会重新请求回答或 Search。"),
    field("补判范围", scope), answerPanel, field("Judge 引擎", judge), overrides.node, estimate,
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "检查预估并创建补判批次")));
  const modal = drawer(`Judge-only 补判 · Run #${run.id}`, form, { wide: true });
  let confirmed = false;
  onSubmit(form, async () => {
    const answerIds = scope.value === "selected" ? checks.filter((control) => control.control.checked).map((control) => control.answerId) : undefined;
    if (answerIds && !answerIds.length) throw new Error("至少选择一条可补判回答");
    const execute = async (reason = "") => {
      const result = await api.post(`/api/projects/${ctx.project.id}/runs/${run.id}/judge-batches`, {
        answer_ids: answerIds, judge_engine_id: Number(judge.value), judge_overrides: overrides.read(),
        confirm: confirmed, budget_confirmation_reason: reason,
      });
      modal.close(); toast(`补判批次 #${result.id} 已进入队列；不会重采回答`); ctx.refresh();
    };
    try { await execute(); }
    catch (error) {
      if (error.detail?.code === "judge_batch_confirmation_required") {
        confirmed = true;
        const value = error.detail.estimate;
        clear(estimate);
        estimate.append(h("div", { class: "inline-panel warning-panel" }, h("h3", {}, "真实 Judge 独立预估"),
          h("p", {}, `Judge ${value.judge_calls} 次，含安全重试最多 ${value.max_external_calls} 次；Answer / Search 均为 0。`),
          h("p", {}, value.cost_unknown ? "价格未知，不按零成本处理" : `基础 ${value.estimated_cost} / 含重试 ${value.max_estimated_cost} ${value.currency}`),
          h("p", {}, "再次点击按钮即确认本次真实调用。")));
        form.querySelector("button[type=submit]").textContent = "确认真实 Judge 调用并创建";
        return;
      }
      if (!handleBudgetError(error, execute)) throw error;
    }
  });
}

function cancelJudgeBatch(ctx, batch) {
  confirmDialog("取消补判批次", `Batch #${batch.id} 的排队项会取消；在途真实调用无法撤回，取消时已返回的结果不会静默追加为正式判定。`, "确认取消", async () => {
    await api.post(`/api/projects/${ctx.project.id}/judge-batches/${batch.id}/cancel`, {}); toast("已请求取消补判"); ctx.refresh();
  }, true);
}

function retryJudgeBatch(ctx, batch) {
  const execute = async (reason = "", confirm = false) => api.post(`/api/projects/${ctx.project.id}/judge-batches/${batch.id}/retry`, {
    confirm, budget_confirmation_reason: reason,
  });
  confirmDialog("重试失败补判项", "只重试结果明确的失败项；已完成的 Answer 不重复 revision，结果不明的项不会自动重放。", "检查并重试", async () => {
    try {
      const result = await execute(); toast(`Batch #${batch.id} 已重新排队`); ctx.refresh(); return result;
    } catch (error) {
      if (error.detail?.code === "judge_batch_confirmation_required") {
        const estimate = error.detail.estimate;
        confirmDialog("确认真实 Judge 重试", `重试 ${estimate.judge_calls} 次，Answer / Search 为 0。${estimate.cost_unknown ? "价格未知。" : `含重试预估 ${estimate.max_estimated_cost} ${estimate.currency}`}`, "确认并重试", async () => {
          try { await execute("", true); toast("失败补判项已重试"); ctx.refresh(); }
          catch (retryError) { if (!handleBudgetError(retryError, (reason) => execute(reason, true))) throw retryError; }
        });
        return;
      }
      if (!handleBudgetError(error, (reason) => execute(reason, true))) throw error;
    }
  });
}

function browserRunProgress(browser, ctx, runId) {
  const node = h("div", { class: "browser-run-progress", dataset: { browserProgress: "" }, role: "status", "aria-live": "polite" });
  updateBrowserRunProgress(node, browser, ctx, runId);
  return node;
}

function updateBrowserRunProgress(node, browser, ctx, runId) {
  if (!node) return;
  clear(node);
  if (!browser) {
    node.append(h("strong", {}, "网页采集阶段已结束"), h("p", {}, "原始回答与证据已提交，正在等待独立 Judge 或执行收尾。"));
    return;
  }
  const needsAction = ["awaiting_user", "paused_unknown"].includes(browser.phase);
  node.append(h("div", { class: "section-head" }, h("div", {}, h("h3", {}, browserPhaseName(browser.phase)),
    h("p", {}, browser.detail || (browser.prompt_submitted ? "问题已发送；采集器只会核对原会话，不会自动重发。" : "任务在本机浏览器队列中串行执行。"))),
    needsAction ? h("a", { class: "button small-button", href: `#/review?run=${runId}&answer=${browser.answer_id}&review=all` }, "处理当前采集") : null),
    h("p", { class: "browser-current-prompt" }, browser.prompt),
    h("div", { class: "progress-meta" },
      h("span", {}, browser.prompt_submitted ? "问题已发送" : "尚未确认发送"),
      h("span", {}, `心跳 ${formatDate(browser.heartbeat_at, ctx.project.timezone)}`),
      browser.action_required ? h("span", {}, `${browser.action_required} 条需要管理员处理`) : null));
}

function waveWizard(ctx, sets, engines, browserSessions = {}) {
  const frozen = sets.filter((item) => item.status === "frozen");
  if (!frozen.length) { toast("请先在问题集工作台审核并冻结一个版本", true); return; }
  const enabled = engines.filter((item) => item.enabled);
  if (!enabled.length) { toast("请先配置并启用引擎", true); return; }
  const labelInput = input(`GEO 测量 ${new Date().toISOString().slice(0, 10)}`, { required: true });
  const setInput = select(frozen.map((item) => ({ value: item.id, label: `v${item.version} · ${item.name}` })));
  const repeats = select([1, 2, 3, 4, 5].map((value) => ({ value, label: `${value} 轮${value === 3 ? "（默认）" : ""}` })), 3);
  const answerParams = executionFields({}, "answer", "回答参数（可选，默认继承引擎配置）");
  const judgeParams = executionFields({}, "judge", "Judge 参数（可选，默认继承 Judge 引擎配置）");
  const judge = checkbox("生产回答使用全量结构化 judge", true, "演示引擎始终使用明确标记的 demo-rules；生产 judge 失败会显式降级并进入复核");
  const judgeEngines = enabled.filter((engine) => engine.kind !== "manual_web");
  const judgeMode = select([{ value: "answer_engine", label: "各回答引擎兼任 Judge" }, { value: "independent", label: "指定独立 Judge" }], "answer_engine");
  const judgeModeField = field("Judge 方式", judgeMode, "同引擎保留兼容口径；独立 Judge 分开发送判定请求并记录成本");
  const judgeEngine = select(judgeEngines.map((engine) => ({ value: engine.id, label: `${engine.name} · ${engine.kind} · ${engine.model || "未标模型"}` })), judgeEngines[0]?.id);
  const judgeEngineField = field("独立 Judge 引擎", judgeEngine, "只用于结构化判定；Search 型 Judge 也只调用 Chat，不执行 Search");
  const answerOverridePanel = h("div", {});
  const answerOverrides = new Map();
  const productUrl = input("", { readonly: true });
  const collectionMethod = select([{ value: "manual", label: "人工复制回答并上传证据" }, { value: "browser_assisted", label: "授权浏览器自动采集" }], "manual");
  const browserDriver = select([{ value: "deepseek_web", label: "DeepSeek 网页版" }, { value: "kimi_web", label: "Kimi 网页版" }], "deepseek_web");
  const browserDriverField = field("浏览器 Driver", browserDriver, "两个平台使用各自独立 Driver，不通用套用选择器");
  const browserConnection = h("p", { class: "muted small" });
  const platform = input("", { required: true, placeholder: "产品或平台名称，不填写账号别名" });
  const surface = select([{ value: "desktop_web", label: "桌面 Web" }, { value: "mobile_web", label: "移动 Web" }], "desktop_web");
  const pageMode = input("default", { required: true, placeholder: "实际页面模型或模式" });
  const networking = checkbox("声明页面已联网", false, "必须与人工目标的 memory/search 口径一致");
  const deepThinking = checkbox("开启深度思考", false);
  const deepResearch = checkbox("开启深度研究", false);
  const sessionMode = select([{ value: "new", label: "新会话" }, { value: "continuous", label: "连续会话" }], "new");
  const loginState = select([{ value: "anonymous", label: "匿名访问" }, { value: "logged_in", label: "已登录" }], "anonymous");
  const accountType = input("", { placeholder: "如 free / pro；不要填写账号名" });
  const region = input(ctx.project.market || "CN", { required: true });
  const language = input(ctx.project.language || "zh-CN", { required: true });
  const contextClearing = input("new_session", { required: true, placeholder: "如 new_session / clear_context" });
  const followUpPolicy = input("none", { required: true, placeholder: "如 none / one_follow_up" });
  const collectionHeading = h("h3", {}, "冻结 Consumer Web 采集协议");
  const collectionDescription = h("p", { class: "muted small" });
  const collectionPanel = h("div", { class: "inline-panel emphasis", hidden: true },
    collectionHeading, collectionDescription,
    h("div", { class: "form-grid" }, field("采集方法", collectionMethod), browserDriverField, field("产品入口", productUrl), field("平台", platform), field("页面形态", surface), field("页面模型 / 模式", pageMode),
      field("会话策略", sessionMode), field("登录状态", loginState), field("账号类型", accountType), field("地区", region), field("语言", language),
      field("上下文清理", contextClearing), field("追问策略", followUpPolicy)),
    browserConnection, networking.node, deepThinking.node, deepResearch.node);
  const engineChecks = enabled.map((engine) => {
    const control = checkbox(`${engine.name} · ${engine.model || engine.kind}`, enabled.length === 1, `${label(engine.mode)} · ${label(engine.measurement_target)} · ${engine.vendor}`);
    control.engine = engine;
    control.control.addEventListener("change", () => {
      if (control.control.checked) engineChecks.forEach((item) => {
        if (item !== control && (engine.kind === "manual_web" || item.engine.kind === "manual_web")) item.control.checked = false;
      });
      syncEngines();
    });
    return control;
  });
  let consumerTarget = null;
  let collectionTargetId = null;
  const syncCollection = () => {
    const automatic = Boolean(consumerTarget) && collectionMethod.value === "browser_assisted";
    collectionHeading.textContent = automatic ? "冻结授权浏览器 Consumer Web 采集协议" : "冻结人工 Consumer Web 采集协议";
    collectionDescription.textContent = automatic
      ? "本机采集器将在可见浏览器中新建会话、发送冻结问题并提取回答区域证据。你本人负责登录和验证码；系统不绕过验证，不自动重发结果不明的问题。"
      : "本轮只生成人工采集任务。系统不会自动打开网页、保存登录会话或提取 DOM；正式提交时实际页面和以下上下文必须一致。";
    collectionMethod.disabled = !consumerTarget;
    browserDriver.disabled = !automatic;
    browserDriverField.hidden = !automatic;
    browserConnection.hidden = !automatic;
    if (automatic) {
      surface.value = "desktop_web"; sessionMode.value = "new"; loginState.value = "logged_in";
      contextClearing.value = "new_session"; followUpPolicy.value = "none"; deepResearch.control.checked = false;
      const sessions = browserSessions[consumerTarget.id] || [];
      const current = sessions.find((item) => item.driver === browserDriver.value && item.status === "active");
      browserConnection.textContent = ctx.role === "admin"
        ? current ? `已验证 ${driverName(browserDriver.value)} 本机会话 · 最近验证 ${formatDate(current.last_verified_at, ctx.project.timezone)}。创建 Run 时还会再次检查。`
          : `当前目标没有已验证的 ${driverName(browserDriver.value)} 会话。可以先保存 Wave；创建 Run 前请到系统管理完成连接。`
        : "创建 Run 时服务端会检查管理员已验证的本机会话；分析师不能查看或修改浏览器连接。";
    } else browserConnection.textContent = "";
    [surface, sessionMode, loginState, contextClearing, followUpPolicy].forEach((control) => { control.disabled = !consumerTarget || automatic; });
    deepResearch.control.disabled = !consumerTarget || automatic;
  };
  const syncEngines = () => {
    const selected = engineChecks.filter((item) => item.control.checked).map((item) => item.engine);
    consumerTarget = selected.find((engine) => engine.kind === "manual_web") || null;
    const manualTarget = consumerTarget;
    if (manualTarget && collectionTargetId !== manualTarget.id) {
      collectionTargetId = manualTarget.id;
      browserDriver.value = manualTarget.vendor.toLowerCase().includes("kimi") ? "kimi_web" : "deepseek_web";
      const active = (browserSessions[manualTarget.id] || []).find((item) => item.status === "active");
      if (active) browserDriver.value = active.driver;
    } else if (!manualTarget) collectionTargetId = null;
    const providerIds = new Set(selected.filter((engine) => engine.kind !== "manual_web").map((engine) => Number(engine.id)));
    collectionPanel.hidden = !manualTarget;
    collectionPanel.querySelectorAll("input,select,textarea").forEach((control) => { control.disabled = !manualTarget; });
    answerParams.node.hidden = Boolean(manualTarget);
    answerOverridePanel.hidden = Boolean(manualTarget);
    clear(answerOverridePanel);
    if (!manualTarget && selected.length) {
      answerOverridePanel.append(h("h3", {}, "按回答引擎覆盖（可选）"), h("p", { class: "muted small" }, "未展开的引擎继承上方回答参数与各自引擎默认值。"));
      selected.forEach((engine) => {
        if (!answerOverrides.has(engine.id)) answerOverrides.set(engine.id, executionFields({}, "answer", `${engine.name} · 回答覆盖`));
        answerOverridePanel.append(answerOverrides.get(engine.id).node);
      });
    }
    judgeMode.disabled = Boolean(manualTarget);
    if (manualTarget) judgeMode.value = "independent";
    const independent = judgeMode.value === "independent";
    judgeModeField.hidden = Boolean(manualTarget) || !judge.control.checked;
    judgeEngineField.hidden = !judge.control.checked || !independent;
    judgeParams.node.hidden = !judge.control.checked;
    judge.node.querySelector("label").childNodes[0].textContent = manualTarget ? `使用独立 Judge 判定${collectionMethod.value === "browser_assisted" ? "网页" : "人工"}回答` : "生产回答使用全量结构化 judge";
    judgeEngineField.querySelector("label").textContent = manualTarget ? "独立 Judge 引擎" : "独立 Judge 引擎（不能同时是回答引擎）";
    [...judgeEngine.options].forEach((option) => { option.disabled = !manualTarget && providerIds.has(Number(option.value)); });
    if (judgeEngine.selectedOptions[0]?.disabled) judgeEngine.value = [...judgeEngine.options].find((option) => !option.disabled)?.value || "";
    if (manualTarget) {
      productUrl.value = manualTarget.base_url;
      platform.value = platform.value || manualTarget.vendor || manualTarget.name;
      networking.control.checked = manualTarget.mode === "search";
      networking.control.disabled = true;
    } else networking.control.disabled = false;
    syncCollection();
  };
  judge.control.addEventListener("change", syncEngines);
  judgeMode.addEventListener("change", syncEngines);
  collectionMethod.addEventListener("change", syncEngines);
  browserDriver.addEventListener("change", syncCollection);
  const form = h("form", {}, field("Wave 名称", labelInput), field("冻结问题集", setInput),
    h("fieldset", {}, h("legend", { class: "field-label" }, "选择一个 Provider 组合或一个 Consumer Web 目标"), engineChecks.map((item) => item.node)),
    collectionPanel, h("div", { class: "form-grid" }, field("采样轮次", repeats)), answerParams.node, answerOverridePanel,
    judge.node, judgeModeField, judgeEngineField, judgeParams.node,
    h("p", { class: "muted small" }, "创建 wave 不会调用外部服务。统计阈值沿用项目设置，创建后冻结，不能在看到结果后放宽。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "创建方案并查看预估")));
  const modal = drawer("新建测量方案", form, { wide: true });
  syncEngines();
  onSubmit(form, async () => {
    const selected = engineChecks.filter((item) => item.control.checked).map((item) => item.engine);
    if (!selected.length) throw new Error("至少选择一个测量目标");
    if (new Set(selected.map((item) => `${item.mode}/${item.measurement_target}`)).size !== 1) throw new Error("同一 wave 不能混合 memory/search 或 API/产品端口径");
    const manual = selected.length === 1 && selected[0].kind === "manual_web";
    const browser = manual && collectionMethod.value === "browser_assisted";
    if (selected.some((item) => item.kind === "manual_web") && !manual) throw new Error("Consumer Web Wave 只能选择一个目标，不能与 Provider 混合");
    if (judge.control.checked && judgeMode.value === "independent" && !judgeEngine.value) throw new Error("请选择独立 Judge，或改用同引擎判定");
    const overrides = {};
    if (!manual) selected.forEach((engine) => {
      const values = answerOverrides.get(engine.id)?.read() || {};
      if (Object.keys(values).length) overrides[engine.id] = values;
    });
    const wave = await api.post(`/api/projects/${ctx.project.id}/waves`, {
      label: labelInput.value, prompt_set_id: Number(setInput.value), engine_ids: selected.map((item) => item.id),
      repeats: Number(repeats.value), ...(manual ? {} : answerParams.read()), use_judge: judge.control.checked,
      answer_overrides: manual ? undefined : overrides, judge_overrides: judge.control.checked ? judgeParams.read() : undefined,
      judge_engine_id: judge.control.checked && judgeMode.value === "independent" ? Number(judgeEngine.value) : undefined,
      collection_protocol: manual ? {
        product_url: productUrl.value, platform: platform.value, surface: surface.value, page_mode: pageMode.value,
        networking: networking.control.checked, deep_thinking: deepThinking.control.checked,
        deep_research: deepResearch.control.checked, session_mode: sessionMode.value, login_state: loginState.value,
        account_type: accountType.value, region: region.value, language: language.value,
        context_clearing: contextClearing.value, follow_up_policy: followUpPolicy.value,
        collection_method: browser ? "browser_assisted" : "manual",
        browser_driver: browser ? browserDriver.value : null,
        protocol_version: browser ? "browser-web-v1" : "manual-web-v1",
      } : undefined,
    });
    const estimateForm = h("form", {}, h("h3", {}, browser ? "授权浏览器采集与独立 Judge 准备单" : manual ? "人工采集与独立 Judge 准备单" : "测量准备单"), readinessSummary(wave.readiness, false), h("h4", {}, "调用与费用预估"), h("dl", { class: "definition-list" },
      manual ? h("div", {}, h("dt", {}, browser ? "串行浏览器任务" : "人工采集任务"), h("dd", {}, wave.estimate.collection_tasks)) : null,
      h("div", {}, h("dt", {}, "Provider 回答调用"), h("dd", {}, wave.estimate.answer_calls)), h("div", {}, h("dt", {}, "Judge 调用"), h("dd", {}, wave.estimate.judge_calls)),
      h("div", {}, h("dt", {}, "检索调用"), h("dd", {}, wave.estimate.search_calls)), h("div", {}, h("dt", {}, "预估费用"), h("dd", {}, wave.estimate.cost_unknown ? "部分价格未知，不按零成本处理" : wave.estimate.estimated_cost))),
      dataTable(["引擎", "角色", "基础预估", "含安全重试"], (wave.estimate.by_engine || []).map((entry) => [entry.engine, entry.role === "judge" ? "独立 Judge" : "回答 / 同引擎 Judge", entry.estimated_cost ?? "未知", entry.max_estimated_cost ?? "未知"])),
      h("p", { class: "muted" }, wave.estimate.note),
      browser ? h("p", { class: "muted" }, `点击下方确认后，将把 ${wave.estimate.collection_tasks} 条冻结问题串行发送到 ${platform.value || driverName(browserDriver.value)}（${driverName(browserDriver.value)}），再使用独立 Judge 判定。网页订阅费用不按 API 调用估算；结果不明不会自动重发。`) : null,
      h("div", { class: "form-actions" },
        h("button", { class: "button secondary", type: "button", onClick: () => { modal.close(); ctx.navigate("measure", { wave: wave.id }); } }, "仅保存方案"),
        h("button", { class: "button", type: "submit" }, browser ? "确认发送并创建 Run" : manual ? "创建人工采集 Run" : "确认调用并创建 Run")));
    clear(modal.body);
    modal.body.append(estimateForm);
    modal.focus();
    onSubmit(estimateForm, async () => {
      try { await startRun(ctx, wave); modal.close(); }
      catch (error) {
        if (!handleBudgetError(error, async (reason) => { await startRun(ctx, wave, reason); modal.close(); })) throw error;
      }
    });
  });
}

async function startRun(ctx, wave, budgetReason = "") {
  const result = await api.post(`/api/projects/${ctx.project.id}/waves/${wave.id}/runs`, {
    budget_confirmation_reason: budgetReason, confirm_browser: isBrowserWave(wave),
    confirm_judge_disabled: Boolean(wave.readiness?.requires_judge_disabled_confirmation),
  });
  const manual = isManualWave(wave);
  toast(isBrowserWave(wave) ? "授权浏览器 Run 已创建，问题将在本机串行采集" : manual ? "人工采集 Run 已创建，请逐条提交回答与截图" : "Run 已进入持久队列");
  ctx.navigate(manual ? "review" : "measure", manual ? { run: result.run.id } : { wave: wave.id, run: result.run.id });
  return result;
}

function confirmRun(ctx, wave) {
  const real = requiresRealConfirmation(wave);
  const manual = isManualWave(wave);
  const browser = isBrowserWave(wave);
  const estimate = wave.estimate.cost_unknown ? "部分价格未知，不会按零成本处理。" : `基础预估 ${wave.estimate.estimated_cost}，含安全重试预估 ${wave.estimate.max_estimated_cost} ${wave.estimate.currency || ""}。`;
  const collection = wave.protocol.collection_protocol || {};
  const description = browser
    ? `将把 ${wave.estimate.collection_tasks} 条冻结问题串行发送到 ${collection.platform || driverName(collection.browser_driver)}（${driverName(collection.browser_driver)}），使用本机已验证会话，并保存回答、引用、截图和 HTML。Provider 回答和 Search 调用均为 0，独立 Judge 基础调用 ${wave.estimate.judge_calls} 次。${estimate}${real ? "真实 Judge 可能产生费用。" : "当前 Judge 为离线演示夹具，不代表 live 验收。"}登录和验证码由你本人处理；结果不明不会自动重发。`
    : manual
      ? `将创建 ${wave.estimate.collection_tasks} 条人工采集任务；Provider 回答和 Search 调用均为 0，独立 Judge 基础调用 ${wave.estimate.judge_calls} 次。${estimate}${real ? "真实 Judge 可能产生费用。" : "当前 Judge 为离线演示夹具，不代表 live 验收。"}系统不会自动操作网页。`
      : `基础调用 ${wave.estimate.total_external_calls} 次，含安全重试最多 ${wave.estimate.max_external_calls} 次。${estimate}${real ? "真实厂商可能产生费用；超时等结果不明样本不会自动重放。" : "当前为演示引擎。"}${wave.readiness?.requires_judge_disabled_confirmation ? "本次已关闭 Judge。管理员确认只代表允许执行，不代表报告质量闸门已通过；执行后需补判或人工质检。" : ""}`;
  confirmDialog(browser ? "确认发送问题并创建 Run" : manual ? "确认创建人工采集 Run" : "确认创建 Run", description, browser ? "确认发送并开始采集" : manual ? "创建并前往人工采集" : "确认并进入队列", async () => {
    try { await startRun(ctx, wave); }
    catch (error) { if (!handleBudgetError(error, (reason) => startRun(ctx, wave, reason))) throw error; }
  });
}

function cancelRun(ctx, wave, run) {
  confirmDialog("取消当前 Run", "排队样本会标记为取消；正在执行的外部请求无法撤回，返回后保留原文但不进入有效指标。缺失样本不等于零提及。", "确认取消", async () => { await api.post(`/api/projects/${ctx.project.id}/runs/${run.id}/cancel`, {}); toast("已请求取消"); ctx.refresh(); }, true);
}

function retryRun(ctx, run) {
  const browser = run.snapshot.protocol.collection_protocol?.collection_method === "browser_assisted";
  const execute = async (reason = "") => {
    const result = await api.post(`/api/projects/${ctx.project.id}/runs/${run.id}/retry`, { budget_confirmation_reason: reason, confirm_browser: browser });
    toast(`${result.queued} 个样本已${run.snapshot.protocol.measurement_target === "consumer_web" ? "转入重采或 Judge 重试" : "重新排队"}`); ctx.refresh();
  };
  const description = browser
    ? "已有原始回答的失败样本只重跑独立 Judge，原文与证据保持不变；没有原文的失败样本会再次向第三方产品发送对应冻结问题。结果不明的原会话不会被自动重发，网页采集重试由管理员明确确认。"
    : "失败与取消样本会重新排队。超时等结果不明的外部调用可能已被厂商计费，本次重试由管理员明确确认；系统会按失败样本比例重新检查预算。";
  confirmDialog("确认重试失败样本", description, browser ? "确认重试" : "确认重试", async () => {
    try { await execute(); } catch (error) { if (!handleBudgetError(error, execute)) throw error; }
  });
}

function selectOfficial(ctx, wave, run) {
  confirmDialog("指定正式 Run", `Run #${run.id} 的状态为 ${label(run.status)}。报告与同口径对比将固定使用这次尝试，不再自动切换到更新 run。${run.status === "partial" ? "部分完成数据会在对比时检查 90% 完整度。" : ""}`, "指定为正式 Run", async () => { await api.post(`/api/projects/${ctx.project.id}/waves/${wave.id}/official`, { run_id: run.id }); toast("正式 Run 已指定"); ctx.refresh(); });
}
