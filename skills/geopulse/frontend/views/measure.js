import { api } from "../api.js";
import { h, clear, pageHead, section, dataTable, badge, metric, drawer, field, input, select, checkbox, toast, formError, confirmDialog, formatDate, label, emptyState, handleBudgetError, pct } from "../components.js";

const openRunHistories = new Set();
const isManualWave = (wave) => wave.protocol.measurement_target === "consumer_web";
const requiresRealConfirmation = (wave) => [
  ...(wave.protocol.engine_signature || []),
  ...(wave.protocol.judge_signature ? [wave.protocol.judge_signature] : []),
].some((engine) => !["demo", "manual_web"].includes(engine.kind));

export async function renderMeasure(root, ctx) {
  const [waveData, setData, engineData] = await Promise.all([
    api.get(`/api/projects/${ctx.project.id}/waves`), api.get(`/api/projects/${ctx.project.id}/prompt-sets`), api.get(`/api/projects/${ctx.project.id}/engines`),
  ]);
  const waves = waveData.items;
  const actions = [["admin", "analyst"].includes(ctx.role) ? h("button", { class: `button${waves.length ? " secondary" : ""}`, onClick: () => waveWizard(ctx, setData.items, engineData.items) }, "新建测量方案") : null];
  if (!waves.length) {
    clear(root); root.append(pageHead("测量执行", "wave 冻结测量口径，run 记录每一次执行尝试。", actions),
      emptyState("还没有测量方案", "先创建 wave 并检查调用预估；只有确认创建 run 后才会进入执行队列。", null));
    return;
  }
  const wave = waves.find((item) => String(item.id) === ctx.params.get("wave")) || waves[0];
  const selectedRunId = Number(ctx.params.get("run")) || wave.runs[0]?.id;
  const run = selectedRunId ? await api.get(`/api/projects/${ctx.project.id}/runs/${selectedRunId}`) : null;
  const metrics = run ? await api.get(`/api/projects/${ctx.project.id}/runs/${run.id}/metrics`) : null;
  if (!ctx.isCurrent()) return;
  const protocol = wave.protocol;
  const manual = isManualWave(wave);
  ctx.setProtocol({ promptSet: `ID ${protocol.prompt_set_id} · ${protocol.prompt_set_hash.slice(0, 8)}`, entityVersion: protocol.entity_version,
    engines: protocol.engine_signature.map((engine) => engine.name).join(" / "), mode: protocol.mode,
    target: protocol.measurement_target, repeats: protocol.repeats, n: metrics?.quality?.valid_samples,
    demo: metrics?.is_demo, real: metrics && !metrics.is_demo });
  clear(root);
  root.append(pageHead("测量执行", "先冻结口径并查看预估，再创建 run。失败、取消和空回答不会进入有效样本分母。", actions));
  const rail = h("aside", { class: "list-rail" }, h("div", { class: "list-rail-head" }, h("strong", {}, "Wave 列表"), h("span", { class: "muted small" }, `${waves.length} 个`)),
    waves.map((item) => h("button", { class: `list-item${item.id === wave.id ? " active" : ""}`, "aria-current": item.id === wave.id ? "location" : null, "data-wave-id": item.id, onClick: () => ctx.navigate("measure", { wave: item.id }) },
      h("strong", {}, item.label), badge(item.status), h("small", { class: "cell-sub" }, `${item.runs.length} 个 run · ${formatDate(item.created_at, ctx.project.timezone)}`))));
  const detail = h("div", { class: "detail-pane" });
  const active = run && ["queued", "running"].includes(run.status);
  const canSelectOfficial = run && ["done", "partial"].includes(run.status) && ctx.role === "admin" && wave.official_run_id !== run.id;
  detail.append(h("section", { class: "inline-panel wave-summary" }, h("div", { class: "section-head" },
    h("div", {}, h("h2", {}, wave.label), h("p", {}, `Wave #${wave.id} · ${label(wave.status)}${wave.official_run_id ? ` · 正式 Run #${wave.official_run_id}` : " · 尚未指定正式 run"}`)),
    h("div", { class: "button-group" },
      ["admin", "analyst"].includes(ctx.role) ? h("button", { class: `button${active || canSelectOfficial ? " secondary" : ""}`, onClick: () => confirmRun(ctx, wave) }, manual ? "创建人工采集 Run" : wave.runs.length ? "创建重试 Run" : "确认并创建 Run") : null,
      wave.official_run_id ? h("a", { class: "button secondary", href: `#/reports?wave=${wave.id}` }, "生成报告") : null)),
    h("dl", { class: "definition-list" },
      h("div", {}, h("dt", {}, "测量目标"), h("dd", {}, `${label(protocol.mode)} · ${label(protocol.measurement_target)}`)),
      h("div", {}, h("dt", {}, "问题 / 目标 / 轮次"), h("dd", {}, `${wave.estimate.prompt_items} × ${wave.estimate.engines} × ${protocol.repeats}`)),
      manual ? h("div", {}, h("dt", {}, "待人工采集任务"), h("dd", { class: "num" }, wave.estimate.collection_tasks)) : null,
      h("div", {}, h("dt", {}, manual ? "独立 Judge 基础 / 重试上限" : "基础 / 安全重试调用"), h("dd", { class: "num" }, `${wave.estimate.total_external_calls} / ${wave.estimate.max_external_calls}`)),
      ["admin", "analyst"].includes(ctx.role) ? h("div", {}, h("dt", {}, "基础 / 含重试费用预估"), h("dd", {}, wave.estimate.cost_unknown ? "部分价格未知" : `${wave.estimate.estimated_cost} / ${wave.estimate.max_estimated_cost} ${wave.estimate.currency || ""}`)) : null),
    h("p", { class: "muted small" }, wave.estimate.note),
    manual ? h("details", { class: "advanced" }, h("summary", {}, "查看冻结采集协议"), h("div", {},
      h("p", {}, protocol.collection_protocol.product_url),
      h("p", { class: "muted small" }, `${label(protocol.collection_protocol.surface)} · ${protocol.collection_protocol.page_mode || "默认模式"} · ${protocol.collection_protocol.session_mode === "new" ? "新会话" : "连续会话"} · ${protocol.collection_protocol.language}`),
      h("p", { class: "muted small" }, `独立 Judge：${protocol.judge_signature?.name || "未启用"}。联网、深度开关、登录状态、上下文清理和追问策略均已冻结；实际提交必须逐项一致。`))) : null));
  if (run) {
    const progress = run.progress;
    detail.append(h("section", { class: "inline-panel run-focus" }, h("div", { class: "section-head" }, h("div", {}, h("h2", {}, `Run #${run.id} · 第 ${run.attempt_no} 次尝试`), h("p", { dataset: { runStatus: "" } }, `${label(run.status)} · ${manual ? run.snapshot.protocol.use_judge ? `独立 Judge：${protocol.judge_signature?.name || "未配置"}` : "规则回退，需人工仲裁" : run.snapshot.protocol.use_judge ? "全量结构化 judge" : "规则回退"}${metrics.is_demo ? " · 演示数据" : ""}`)),
      h("div", { class: "button-group" },
        active && ["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button danger small-button", onClick: () => cancelRun(ctx, wave, run) }, "取消 Run") : null,
        ["failed", "cancelled", "partial"].includes(run.status) && ctx.role === "admin" ? h("button", { class: "button secondary small-button", onClick: () => retryRun(ctx, run) }, "确认重试失败样本") : null,
        canSelectOfficial ? h("button", { class: "button small-button", onClick: () => selectOfficial(ctx, wave, run) }, "指定为正式 Run") : null,
        h("a", { class: "button secondary small-button", href: `#/review?run=${run.id}` }, manual ? "采集与复核证据" : "复核证据"))),
      h("div", { class: "progress-track", dataset: { runProgress: "" }, role: "progressbar", "aria-valuenow": progress.progress, "aria-valuemin": 0, "aria-valuemax": 100, "aria-label": "Run 完成进度" }, h("div", { class: "progress-bar", style: `width:${progress.progress}%` })),
      h("div", { class: "progress-meta" }, h("span", { dataset: { progressCount: "" } }, `${progress.finished}/${progress.total} 个样本已结束`), h("span", { class: "num", dataset: { progressPercent: "" } }, `${progress.progress}%`)),
      run.error ? h("p", { class: "form-error" }, run.error) : null));
    const results = h("section", { class: "run-results" }, h("div", { class: "section-head" }, h("div", {}, h("h2", {}, "测量结果"), h("p", {}, "先看有效样本与不确定性，再进入维度和实体诊断。"))));
    if (metrics.quality.valid_samples) {
      results.append(h("div", { class: "metric-strip" }, metric("意图覆盖", metrics.coverage), metric("稳定命中", metrics.hit_rate), metric("有效推荐", metrics.effective_recommendation_rate), metric("北极星", metrics.north_star)));
      results.append(h("p", { class: "muted small" }, metrics.coverage.limited ? "小样本仅展示原始计数与方向；不显示确定性 SoV 或百分点诊断。" : `SoV ${pct(metrics.share_of_voice.value)} · ${metrics.share_of_voice.definition}。${metrics.limitations.join("；")}`));
    } else results.append(h("div", { class: "inline-panel warning-panel" }, h("h3", {}, manual && metrics.quality.awaiting_collection ? "等待人工采集与证据提交" : "当前没有可诊断的有效样本"), h("p", {}, manual ? "进入“采集与复核证据”，逐条填写实际页面回答并上传截图。待采集、失败或上下文不符的样本不会成为零提及。" : "请检查队列、引擎错误和取消记录。这里不会显示“0% 提及”作为业务结论。")));
    results.append(h("dl", { class: "definition-list quality-ledger" },
      h("div", {}, h("dt", {}, "有效样本"), h("dd", {}, `${metrics.quality.valid_samples}/${metrics.quality.expected_samples}`)),
      h("div", {}, h("dt", {}, "失败 / 取消"), h("dd", {}, `${metrics.quality.failed_samples} / ${metrics.quality.cancelled_samples}`)),
      h("div", {}, h("dt", {}, "待复核回答"), h("dd", {}, metrics.quality.pending_review_answers)),
      h("div", {}, h("dt", {}, "Judge 降级"), h("dd", {}, `${metrics.quality.judge_fallback_rate.hits}/${metrics.quality.judge_fallback_rate.n}`)),
      manual ? h("div", {}, h("dt", {}, "待人工采集"), h("dd", {}, metrics.quality.awaiting_collection || 0)) : null,
      manual ? h("div", {}, h("dt", {}, "有效样本证据覆盖"), h("dd", {}, `${metrics.quality.evidence_coverage?.hits || 0}/${metrics.quality.evidence_coverage?.n || 0}`)) : null));
    detail.append(results);
    const diagnostics = h("div", { class: "run-diagnostics" });
    if (metrics.dimensions.length) diagnostics.append(section("四维原始计数", "小样本只展示计数与方向，不据此判定确定胜负", dataTable(["维度", "覆盖", "命中 / 有效回答", "样本"], metrics.dimensions.map((row) => [label(row.key), `${row.coverage.hits}/${row.coverage.n}${row.coverage.limited ? "" : ` · ${pct(row.coverage.value)}`}`, `${row.hit_rate.hits}/${row.hit_rate.n}`, row.samples]))));
    if (metrics.competitors.length) diagnostics.append(section("实体池表现", "SoV 与主品牌采用完全相同的意图×引擎加权口径；小样本不显示 SoV", dataTable(["实体", "角色", "确认提及", "SoV", "负面"], metrics.competitors.map((row) => [row.name, label(row.role), row.mentions, metrics.coverage.limited ? "—" : pct(row.sov), row.negative]))));
    if (diagnostics.childNodes.length) detail.append(diagnostics);
  } else detail.append(emptyState(manual ? "尚未创建人工采集 Run" : "尚未创建 run", manual ? "创建后系统只生成待采集任务，不会自动打开或操作产品网页。请在证据复核页人工提交回答与截图。" : "调用预估仅用于确认，不会自动执行。创建后即使离开页面，持久队列也会继续。", null));
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
  root.append(h("div", { class: "split-layout has-rail measure-browser" }, rail, detail));
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
      } catch { /* Keep the last confirmed progress; the next poll can retry. */ }
      finally { polling = false; }
    }, 2500);
    ctx.onCleanup(() => clearInterval(timer));
  }
}

function waveWizard(ctx, sets, engines) {
  const frozen = sets.filter((item) => item.status === "frozen");
  if (!frozen.length) { toast("请先在问题集工作台审核并冻结一个版本", true); return; }
  const enabled = engines.filter((item) => item.enabled);
  if (!enabled.length) { toast("请先配置并启用引擎", true); return; }
  const labelInput = input(`GEO 测量 ${new Date().toISOString().slice(0, 10)}`, { required: true });
  const setInput = select(frozen.map((item) => ({ value: item.id, label: `v${item.version} · ${item.name}` })));
  const repeats = select([1, 2, 3, 4, 5].map((value) => ({ value, label: `${value} 轮${value === 3 ? "（默认）" : ""}` })), 3);
  const maxTokens = input("700", { type: "number", min: 100, max: 8000 });
  const maxTokensField = field("最大输出 tokens", maxTokens);
  const judge = checkbox("生产回答使用全量结构化 judge", true, "演示引擎始终使用明确标记的 demo-rules；生产 judge 失败会显式降级并进入复核");
  const judgeEngines = enabled.filter((engine) => engine.kind !== "manual_web");
  const judgeEngine = select(judgeEngines.map((engine) => ({ value: engine.id, label: `${engine.name} · ${engine.kind} · ${engine.model || "未标模型"}` })), judgeEngines[0]?.id);
  const judgeEngineField = field("独立 Judge 引擎", judgeEngine, "只用于判定人工原文；不是被观察的消费者产品");
  const productUrl = input("", { readonly: true });
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
  const collectionPanel = h("div", { class: "inline-panel emphasis", hidden: true },
    h("h3", {}, "冻结人工 Consumer Web 采集协议"),
    h("p", { class: "muted small" }, "本轮只生成人工采集任务。系统不会自动打开网页、保存登录会话或提取 DOM；正式提交时实际页面和以下上下文必须一致。"),
    h("div", { class: "form-grid" }, field("产品入口", productUrl), field("平台", platform), field("页面形态", surface), field("页面模型 / 模式", pageMode),
      field("会话策略", sessionMode), field("登录状态", loginState), field("账号类型", accountType), field("地区", region), field("语言", language),
      field("上下文清理", contextClearing), field("追问策略", followUpPolicy)),
    networking.node, deepThinking.node, deepResearch.node);
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
  const syncEngines = () => {
    const manualTarget = engineChecks.find((item) => item.control.checked && item.engine.kind === "manual_web")?.engine;
    collectionPanel.hidden = !manualTarget;
    collectionPanel.querySelectorAll("input,select,textarea").forEach((control) => { control.disabled = !manualTarget; });
    judgeEngineField.hidden = !manualTarget || !judge.control.checked;
    judge.node.querySelector("label").childNodes[0].textContent = manualTarget ? "使用独立 Judge 判定人工回答" : "生产回答使用全量结构化 judge";
    maxTokensField.querySelector("label").textContent = manualTarget ? "Judge 最大输出 tokens" : "最大输出 tokens";
    if (manualTarget) {
      productUrl.value = manualTarget.base_url;
      platform.value = platform.value || manualTarget.vendor || manualTarget.name;
      networking.control.checked = manualTarget.mode === "search";
      networking.control.disabled = true;
    } else networking.control.disabled = false;
  };
  judge.control.addEventListener("change", syncEngines);
  const form = h("form", {}, field("Wave 名称", labelInput), field("冻结问题集", setInput),
    h("fieldset", {}, h("legend", { class: "field-label" }, "选择一个 Provider 组合或一个人工 Web 目标"), engineChecks.map((item) => item.node)),
    collectionPanel, h("div", { class: "form-grid" }, field("采样轮次", repeats), maxTokensField), judge.node, judgeEngineField,
    h("p", { class: "muted small" }, "创建 wave 不会调用外部服务。统计阈值沿用项目设置，创建后冻结，不能在看到结果后放宽。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "创建方案并查看预估")));
  const modal = drawer("新建测量方案", form, { wide: true });
  syncEngines();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selected = engineChecks.filter((item) => item.control.checked).map((item) => item.engine);
    if (!selected.length) { formError(form, new Error("至少选择一个测量目标")); return; }
    if (new Set(selected.map((item) => `${item.mode}/${item.measurement_target}`)).size !== 1) { formError(form, new Error("同一 wave 不能混合 memory/search 或 API/产品端口径")); return; }
    const manual = selected.length === 1 && selected[0].kind === "manual_web";
    if (selected.some((item) => item.kind === "manual_web") && !manual) { formError(form, new Error("人工 Web Wave 只能选择一个目标，不能与 Provider 混合")); return; }
    if (manual && judge.control.checked && !judgeEngine.value) { formError(form, new Error("请选择独立 Judge，或显式关闭 Judge 并完成后续人工仲裁")); return; }
    try {
      const wave = await api.post(`/api/projects/${ctx.project.id}/waves`, {
        label: labelInput.value, prompt_set_id: Number(setInput.value), engine_ids: selected.map((item) => item.id),
        repeats: Number(repeats.value), max_tokens: Number(maxTokens.value), use_judge: judge.control.checked,
        judge_engine_id: manual && judge.control.checked ? Number(judgeEngine.value) : undefined,
        collection_protocol: manual ? {
          product_url: productUrl.value, platform: platform.value, surface: surface.value, page_mode: pageMode.value,
          networking: networking.control.checked, deep_thinking: deepThinking.control.checked,
          deep_research: deepResearch.control.checked, session_mode: sessionMode.value, login_state: loginState.value,
          account_type: accountType.value, region: region.value, language: language.value,
          context_clearing: contextClearing.value, follow_up_policy: followUpPolicy.value, protocol_version: "manual-web-v1",
        } : undefined,
      });
      clear(modal.body);
      modal.body.append(h("h3", {}, manual ? "人工采集与独立 Judge 预估" : "调用与费用预估"), h("dl", { class: "definition-list" },
        manual ? h("div", {}, h("dt", {}, "人工采集任务"), h("dd", {}, wave.estimate.collection_tasks)) : null,
        h("div", {}, h("dt", {}, "Provider 回答调用"), h("dd", {}, wave.estimate.answer_calls)), h("div", {}, h("dt", {}, "Judge 调用"), h("dd", {}, wave.estimate.judge_calls)),
        h("div", {}, h("dt", {}, "检索调用"), h("dd", {}, wave.estimate.search_calls)), h("div", {}, h("dt", {}, "预估费用"), h("dd", {}, wave.estimate.cost_unknown ? "部分价格未知，不按零成本处理" : wave.estimate.estimated_cost))),
        h("p", { class: "muted" }, wave.estimate.note), h("div", { class: "form-actions" },
          h("button", { class: "button secondary", onClick: () => { modal.close(); ctx.navigate("measure", { wave: wave.id }); } }, "仅保存方案"),
          h("button", { class: "button", onClick: async () => { try { await startRun(ctx, wave); modal.close(); } catch (error) { if (!handleBudgetError(error, async (reason) => { await startRun(ctx, wave, reason); modal.close(); })) toast(error.message, true); } } }, manual ? "创建人工采集 Run" : "确认调用并创建 Run")));
    } catch (error) { formError(form, error); }
  });
}

async function startRun(ctx, wave, budgetReason = "") {
  const result = await api.post(`/api/projects/${ctx.project.id}/waves/${wave.id}/runs`, { budget_confirmation_reason: budgetReason });
  const manual = isManualWave(wave);
  toast(manual ? "人工采集 Run 已创建，请逐条提交回答与截图" : "Run 已进入持久队列");
  ctx.navigate(manual ? "review" : "measure", manual ? { run: result.run.id } : { wave: wave.id, run: result.run.id });
  return result;
}

function confirmRun(ctx, wave) {
  const real = requiresRealConfirmation(wave);
  const manual = isManualWave(wave);
  const estimate = wave.estimate.cost_unknown ? "部分价格未知，不会按零成本处理。" : `基础预估 ${wave.estimate.estimated_cost}，含安全重试预估 ${wave.estimate.max_estimated_cost} ${wave.estimate.currency || ""}。`;
  const description = manual
    ? `将创建 ${wave.estimate.collection_tasks} 条人工采集任务；Provider 回答和 Search 调用均为 0，独立 Judge 基础调用 ${wave.estimate.judge_calls} 次。${estimate}${real ? "真实 Judge 可能产生费用。" : "当前 Judge 为离线演示夹具，不代表 live 验收。"}系统不会自动操作网页。`
    : `基础调用 ${wave.estimate.total_external_calls} 次，含安全重试最多 ${wave.estimate.max_external_calls} 次。${estimate}${real ? "真实厂商可能产生费用；超时等结果不明样本不会自动重放。" : "当前为演示引擎。"}`;
  confirmDialog(manual ? "确认创建人工采集 Run" : "确认创建 Run", description, manual ? "创建并前往人工采集" : "确认并进入队列", async () => {
    try { await startRun(ctx, wave); }
    catch (error) { if (!handleBudgetError(error, (reason) => startRun(ctx, wave, reason))) throw error; }
  });
}

function cancelRun(ctx, wave, run) {
  confirmDialog("取消当前 Run", "排队样本会标记为取消；正在执行的外部请求无法撤回，返回后保留原文但不进入有效指标。缺失样本不等于零提及。", "确认取消", async () => { await api.post(`/api/projects/${ctx.project.id}/runs/${run.id}/cancel`, {}); toast("已请求取消"); ctx.refresh(); }, true);
}

function retryRun(ctx, run) {
  const execute = async (reason = "") => {
    const result = await api.post(`/api/projects/${ctx.project.id}/runs/${run.id}/retry`, { budget_confirmation_reason: reason });
    toast(`${result.queued} 个样本已${run.snapshot.protocol.measurement_target === "consumer_web" ? "转为待重采" : "重新排队"}`); ctx.refresh();
  };
  confirmDialog("确认重试失败样本", "失败与取消样本会重新排队。超时等结果不明的外部调用可能已被厂商计费，本次重试由管理员明确确认；系统会按失败样本比例重新检查预算。", "确认重试", async () => {
    try { await execute(); } catch (error) { if (!handleBudgetError(error, execute)) throw error; }
  });
}

function selectOfficial(ctx, wave, run) {
  confirmDialog("指定正式 Run", `Run #${run.id} 的状态为 ${label(run.status)}。报告与同口径对比将固定使用这次尝试，不再自动切换到更新 run。${run.status === "partial" ? "部分完成数据会在对比时检查 90% 完整度。" : ""}`, "指定为正式 Run", async () => { await api.post(`/api/projects/${ctx.project.id}/waves/${wave.id}/official`, { run_id: run.id }); toast("正式 Run 已指定"); ctx.refresh(); });
}
