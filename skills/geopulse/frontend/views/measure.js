import { api } from "../api.js";
import { h, clear, pageHead, section, dataTable, badge, metric, drawer, field, input, select, checkbox, toast, formError, confirmDialog, formatDate, label, emptyState } from "../components.js";

export async function renderMeasure(root, ctx) {
  const [waveData, setData, engineData] = await Promise.all([
    api.get(`/api/projects/${ctx.project.id}/waves`), api.get(`/api/projects/${ctx.project.id}/prompt-sets`), api.get(`/api/projects/${ctx.project.id}/engines`),
  ]);
  const waves = waveData.items;
  const actions = [["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button", onClick: () => waveWizard(ctx, setData.items, engineData.items) }, "新建测量方案") : null];
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
  ctx.setProtocol({ promptSet: `ID ${protocol.prompt_set_id} · ${protocol.prompt_set_hash.slice(0, 8)}`, entityVersion: protocol.entity_version,
    engines: protocol.engine_signature.map((engine) => engine.name).join(" / "), mode: protocol.mode,
    target: protocol.measurement_target, repeats: protocol.repeats, n: metrics?.quality?.valid_samples,
    demo: metrics?.is_demo, real: metrics && !metrics.is_demo });
  clear(root);
  root.append(pageHead("测量执行", "先冻结口径并查看预估，再创建 run。失败、取消和空回答不会进入有效样本分母。", actions));
  const rail = h("aside", { class: "list-rail" }, h("div", { class: "list-rail-head" }, h("strong", {}, "Wave 列表"), h("span", { class: "muted small" }, `${waves.length} 个`)),
    waves.map((item) => h("button", { class: `list-item${item.id === wave.id ? " active" : ""}`, onClick: () => ctx.navigate("measure", { wave: item.id }) },
      h("strong", {}, item.label), badge(item.status), h("small", { class: "cell-sub" }, `${item.runs.length} 个 run · ${formatDate(item.created_at, ctx.project.timezone)}`))));
  const detail = h("div", { class: "detail-pane" });
  const active = run && ["queued", "running"].includes(run.status);
  detail.append(h("section", { class: "inline-panel emphasis" }, h("div", { class: "section-head" },
    h("div", {}, h("h2", {}, wave.label), h("p", {}, `Wave #${wave.id} · ${label(wave.status)}${wave.official_run_id ? ` · 正式 Run #${wave.official_run_id}` : " · 尚未指定正式 run"}`)),
    h("div", { class: "button-group" },
      ["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button", onClick: () => confirmRun(ctx, wave) }, wave.runs.length ? "创建重试 Run" : "确认并创建 Run") : null,
      wave.official_run_id ? h("a", { class: "button secondary", href: `#/reports?wave=${wave.id}` }, "生成报告") : null)),
    h("dl", { class: "definition-list" },
      h("div", {}, h("dt", {}, "测量目标"), h("dd", {}, `${label(protocol.mode)} · ${label(protocol.measurement_target)}`)),
      h("div", {}, h("dt", {}, "问题 / 引擎 / 轮次"), h("dd", {}, `${wave.estimate.prompt_items} × ${wave.estimate.engines} × ${protocol.repeats}`)),
      h("div", {}, h("dt", {}, "外部调用上限"), h("dd", { class: "num" }, wave.estimate.total_external_calls)),
      h("div", {}, h("dt", {}, "费用预估"), h("dd", {}, wave.estimate.cost_unknown ? "部分价格未知" : `${wave.estimate.estimated_cost} ${wave.estimate.by_engine[0]?.currency || "CNY"}`))),
    h("p", { class: "muted small" }, wave.estimate.note)));
  if (run) {
    const progress = run.progress;
    detail.append(h("section", { class: "inline-panel" }, h("div", { class: "section-head" }, h("div", {}, h("h2", {}, `Run #${run.id} · 第 ${run.attempt_no} 次尝试`), h("p", {}, `${label(run.status)} · ${run.snapshot.protocol.use_judge ? "全量结构化 judge" : "规则回退"}${metrics.is_demo ? " · 演示数据" : ""}`)),
      h("div", { class: "button-group" },
        active && ["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button danger small-button", onClick: () => cancelRun(ctx, wave, run) }, "取消 Run") : null,
        ["failed", "cancelled", "partial"].includes(run.status) && ctx.role === "admin" ? h("button", { class: "button secondary small-button", onClick: () => retryRun(ctx, run) }, "确认重试失败样本") : null,
        ["done", "partial"].includes(run.status) && ctx.role === "admin" && wave.official_run_id !== run.id ? h("button", { class: "button small-button", onClick: () => selectOfficial(ctx, wave, run) }, "指定为正式 Run") : null,
        h("a", { class: "button secondary small-button", href: `#/review?run=${run.id}` }, "复核证据"))),
      h("div", { class: "progress-track", role: "progressbar", "aria-valuenow": progress.progress, "aria-valuemin": 0, "aria-valuemax": 100, "aria-label": "Run 完成进度" }, h("div", { class: "progress-bar", style: `width:${progress.progress}%` })),
      h("div", { class: "progress-meta" }, h("span", {}, `${progress.finished}/${progress.total} 个样本已结束`), h("span", { class: "num" }, `${progress.progress}%`)),
      run.error ? h("p", { class: "form-error" }, run.error) : null));
    if (metrics.quality.valid_samples) {
      detail.append(h("div", { class: "metric-strip" }, metric("意图覆盖", metrics.coverage), metric("稳定命中", metrics.hit_rate), metric("有效推荐", metrics.effective_recommendation_rate), metric("北极星", metrics.north_star)));
      detail.append(h("p", { class: "muted small" }, `SoV ${metrics.share_of_voice.value}% · ${metrics.share_of_voice.definition}。${metrics.limitations.join("；")}`));
    } else detail.append(h("div", { class: "inline-panel warning-panel" }, h("h3", {}, "当前没有可诊断的有效样本"), h("p", {}, "请检查队列、引擎错误和取消记录。这里不会显示“0% 提及”作为业务结论。")));
    detail.append(h("dl", { class: "definition-list" },
      h("div", {}, h("dt", {}, "有效样本"), h("dd", {}, `${metrics.quality.valid_samples}/${metrics.quality.expected_samples}`)),
      h("div", {}, h("dt", {}, "失败 / 取消"), h("dd", {}, `${metrics.quality.failed_samples} / ${metrics.quality.cancelled_samples}`)),
      h("div", {}, h("dt", {}, "待复核回答"), h("dd", {}, metrics.quality.pending_review_answers)),
      h("div", {}, h("dt", {}, "Judge 降级"), h("dd", {}, `${metrics.quality.judge_fallback_rate.hits}/${metrics.quality.judge_fallback_rate.n}`))));
    if (metrics.dimensions.length) detail.append(section("四维原始计数", "小样本只展示计数与方向，不据此判定确定胜负", dataTable(["维度", "覆盖率", "命中", "有效回答"], metrics.dimensions.map((row) => [row.key, `${row.coverage.hits}/${row.coverage.n} · ${row.coverage.value}%`, `${row.hit_rate.hits}/${row.hit_rate.n}`, row.samples]))));
    if (metrics.competitors.length) detail.append(section("实体池表现", "SoV 与主品牌采用完全相同的意图×引擎加权口径", dataTable(["实体", "角色", "确认提及", "SoV", "负面"], metrics.competitors.map((row) => [row.name, label(row.role), row.mentions, `${row.sov}%`, row.negative]))));
  } else detail.append(emptyState("尚未创建 run", "调用预估仅用于确认，不会自动执行。创建后即使离开页面，持久队列也会继续。", null));
  root.append(h("div", { class: "split-layout" }, rail, detail));
  root.append(section("此 Wave 的执行记录", "正式 run 只能由管理员人工指定；重试不会覆盖原回答", dataTable(["Run", "状态", "开始", "结束", "操作"], wave.runs.map((item) => [
    `#${item.id} · 第 ${item.attempt_no} 次`, badge(item.status), formatDate(item.started_at, ctx.project.timezone), formatDate(item.finished_at, ctx.project.timezone),
    h("button", { class: "table-link", onClick: () => ctx.navigate("measure", { wave: wave.id, run: item.id }) }, "打开"),
  ]), "尚无执行记录。")));
  if (active) {
    const timer = setInterval(() => { if (ctx.isCurrent()) ctx.refresh(); }, 2500);
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
  const judge = checkbox("生产回答使用全量结构化 judge", true, "演示引擎始终使用明确标记的 demo-rules；生产 judge 失败会显式降级并进入复核");
  const engineChecks = enabled.map((engine) => {
    const control = checkbox(`${engine.name} · ${engine.model || engine.kind}`, enabled.length === 1, `${label(engine.mode)} · ${label(engine.measurement_target)} · ${engine.vendor}`);
    control.engine = engine; return control;
  });
  const form = h("form", {}, field("Wave 名称", labelInput), field("冻结问题集", setInput),
    h("fieldset", {}, h("legend", { class: "field-label" }, "选择同口径引擎"), engineChecks.map((item) => item.node)),
    h("div", { class: "form-grid" }, field("采样轮次", repeats), field("最大输出 tokens", maxTokens)), judge.node,
    h("p", { class: "muted small" }, "创建 wave 不会调用外部服务。统计阈值沿用项目设置，创建后冻结，不能在看到结果后放宽。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "创建方案并查看预估")));
  const modal = drawer("新建测量方案", form, { wide: true });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selected = engineChecks.filter((item) => item.control.checked).map((item) => item.engine);
    if (!selected.length) { formError(form, new Error("至少选择一个引擎")); return; }
    if (new Set(selected.map((item) => `${item.mode}/${item.measurement_target}`)).size !== 1) { formError(form, new Error("同一 wave 不能混合 memory/search 或 API/产品端口径")); return; }
    try {
      const wave = await api.post(`/api/projects/${ctx.project.id}/waves`, { label: labelInput.value, prompt_set_id: Number(setInput.value), engine_ids: selected.map((item) => item.id), repeats: Number(repeats.value), max_tokens: Number(maxTokens.value), use_judge: judge.control.checked });
      clear(modal.body);
      modal.body.append(h("h3", {}, "调用与费用预估"), h("dl", { class: "definition-list" },
        h("div", {}, h("dt", {}, "回答调用"), h("dd", {}, wave.estimate.answer_calls)), h("div", {}, h("dt", {}, "Judge 调用"), h("dd", {}, wave.estimate.judge_calls)),
        h("div", {}, h("dt", {}, "检索调用"), h("dd", {}, wave.estimate.search_calls)), h("div", {}, h("dt", {}, "预估费用"), h("dd", {}, wave.estimate.cost_unknown ? "部分价格未知，不按零成本处理" : wave.estimate.estimated_cost))),
        h("p", { class: "muted" }, wave.estimate.note), h("div", { class: "form-actions" },
          h("button", { class: "button secondary", onClick: () => { modal.close(); ctx.navigate("measure", { wave: wave.id }); } }, "仅保存方案"),
          h("button", { class: "button", onClick: async () => { try { const result = await api.post(`/api/projects/${ctx.project.id}/waves/${wave.id}/runs`, {}); modal.close(); toast("Run 已进入持久队列"); ctx.navigate("measure", { wave: wave.id, run: result.run.id }); } catch (error) { toast(error.message, true); } } }, "确认调用并创建 Run")));
    } catch (error) { formError(form, error); }
  });
}

function confirmRun(ctx, wave) {
  const real = wave.protocol.engine_signature.some((engine) => engine.kind !== "demo");
  confirmDialog("确认创建 Run", `将执行 ${wave.estimate.total_external_calls} 次外部调用。${wave.estimate.cost_unknown ? "部分价格未知。" : `预估费用 ${wave.estimate.estimated_cost}。`}${real ? "真实厂商可能产生费用；超时等结果不明样本不会自动重放。" : "当前为演示引擎。"}`, "确认并进入队列", async () => {
    const result = await api.post(`/api/projects/${ctx.project.id}/waves/${wave.id}/runs`, {}); toast("Run 已创建"); ctx.navigate("measure", { wave: wave.id, run: result.run.id });
  });
}

function cancelRun(ctx, wave, run) {
  confirmDialog("取消当前 Run", "排队样本会标记为取消；正在执行的外部请求无法撤回，返回后保留原文但不进入有效指标。缺失样本不等于零提及。", "确认取消", async () => { await api.post(`/api/projects/${ctx.project.id}/runs/${run.id}/cancel`, {}); toast("已请求取消"); ctx.refresh(); }, true);
}

function retryRun(ctx, run) {
  confirmDialog("确认重试失败样本", "失败与取消样本会重新排队。超时等结果不明的外部调用可能已被厂商计费，本次重试由管理员明确确认。", "确认重试", async () => { const result = await api.post(`/api/projects/${ctx.project.id}/runs/${run.id}/retry`, {}); toast(`已重新排队 ${result.queued} 个样本`); ctx.refresh(); });
}

function selectOfficial(ctx, wave, run) {
  confirmDialog("指定正式 Run", `Run #${run.id} 的状态为 ${label(run.status)}。报告与同口径对比将固定使用这次尝试，不再自动切换到更新 run。${run.status === "partial" ? "部分完成数据会在对比时检查 90% 完整度。" : ""}`, "指定为正式 Run", async () => { await api.post(`/api/projects/${ctx.project.id}/waves/${wave.id}/official`, { run_id: run.id }); toast("正式 Run 已指定"); ctx.refresh(); });
}
