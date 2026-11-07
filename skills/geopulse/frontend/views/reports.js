import { api, query } from "../api.js";
import { h, clear, pageHead, section, dataTable, badge, drawer, field, select, textarea, toast, formError, confirmDialog, formatDate, label, nextFrame, emptyState, tabs, tabPanel, pct } from "../components.js";

const metricNames = { coverage: "覆盖率", hit_rate: "稳定命中率", recommendation_coverage: "推荐覆盖率", effective_recommendation_rate: "有效推荐率", north_star: "北极星指标" };

export async function renderReports(root, ctx) {
  const [waveData, reportData, eventData] = await Promise.all([
    api.get(`/api/projects/${ctx.project.id}/waves`), api.get(`/api/projects/${ctx.project.id}/reports`), api.get(`/api/projects/${ctx.project.id}/events`),
  ]);
  const official = waveData.items.filter((wave) => wave.official_run_id);
  const selectedReportId = Number(ctx.params.get("report"));
  const report = selectedReportId ? await api.get(`/api/projects/${ctx.project.id}/reports/${selectedReportId}`) : null;
  const current = official.find((wave) => String(wave.id) === (ctx.params.get("current") || ctx.params.get("wave"))) || official[0];
  if (current) ctx.setProtocol({ promptSet: `ID ${current.protocol.prompt_set_id}`, entityVersion: current.protocol.entity_version,
    engines: current.protocol.engine_signature.map((engine) => engine.name).join(" / "), mode: current.protocol.mode,
    target: current.protocol.measurement_target, repeats: current.protocol.repeats, demo: current.protocol.engine_signature.every((engine) => engine.kind === "demo") });
  clear(root);
  root.append(pageHead("对比与报告", "先确认两次测量能否严格比较，再阅读变化。报告快照不可变，自动检查通过后仍需管理员逐步审批。"));
  const currentTab = ctx.params.get("tab") || (selectedReportId || ctx.params.has("wave") ? "delivery" : "compare");
  const tablist = tabs([{ value: "compare", label: "变化对比" }, { value: "delivery", label: `报告交付 (${reportData.items.length})` }], currentTab,
    (tab) => ctx.navigate("reports", { tab, ...(tab === "delivery" && ctx.params.get("wave") ? { wave: ctx.params.get("wave") } : {}) }));
  root.append(tablist);
  const panel = h("div", {});
  if (currentTab === "compare") {
    renderComparison(panel, ctx, official, eventData.items);
  } else {
    panel.append(section("报告版本", "选择当前版本处理审批与导出；每次创建都会生成新的数据快照和 SHA-256", dataTable(
      ["版本", "Wave", "当前审批节点", "创建时间", "操作"], reportData.items.map((item) => [
        `v${item.version} · #${item.id}`, item.wave_ids.join(" → "), badge(item.approval_status), formatDate(item.created_at, ctx.project.timezone),
        h("button", { class: "table-link", "data-report-id": item.id, onClick: () => ctx.navigate("reports", { tab: "delivery", report: item.id }) }, "打开报告"),
      ]), "还没有报告。选择单个诊断 Wave 或基线 + 复测两个 Wave 创建快照。"),
      [["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button", "data-testid": "create-report", disabled: !waveData.items.length, onClick: () => createReportDialog(ctx, waveData.items) }, "创建报告快照") : null]));
    if (report) renderReportDetail(panel, ctx, report);
    else if (!reportData.items.length) panel.append(emptyState("从正式测量创建交付快照", "报告会固定当时的数据、证据和口径。后续审批不会改写数据快照。", null));
  }
  root.append(tabPanel(tablist, panel));
}

function renderComparison(root, ctx, waves, events) {
  const baseline = select(waves.map((wave) => ({ value: wave.id, label: `${wave.label} · Run #${wave.official_run_id}` })), ctx.params.get("baseline") || waves[1]?.id);
  const current = select(waves.map((wave) => ({ value: wave.id, label: `${wave.label} · Run #${wave.official_run_id}` })), ctx.params.get("current") || waves[0]?.id);
  const output = h("div", {});
  const form = h("form", { class: "filters" }, field("基线 Wave", baseline), field("复测 Wave", current),
    h("button", { class: "button secondary", type: "submit", disabled: waves.length < 2 }, "检查口径并比较"));
  root.append(section("同口径配对比较", "校验问题集、实体池、引擎、轮次、Judge、统计口径与至少 90% 有效配对", h("div", { class: "section-body" }, form, output)));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (baseline.value === current.value) { clear(output); output.append(h("p", { class: "form-error" }, "基线和复测必须是不同 wave")); return; }
    clear(output); output.append(h("p", { class: "muted" }, "正在校验协议与有效样本…"));
    try {
      const result = await api.get(`/api/projects/${ctx.project.id}/compare${query({ baseline_wave: baseline.value, current_wave: current.value })}`);
      clear(output);
      if (!result.comparable) {
        output.append(h("div", { class: "inline-panel warning-panel" }, h("h3", {}, "不能输出严格前后变化"), h("p", {}, result.reason),
          result.mismatches?.length ? h("p", { class: "code-block" }, result.mismatches.join("\n")) : null)); return;
      }
      output.append(h("div", { class: `inline-panel${result.exploratory ? " warning-panel" : " emphasis"}` },
        h("h3", {}, result.exploratory ? "协议一致，但模型版本变化：仅作探索性比较" : "协议与样本完整度通过"),
        h("p", {}, `配对完整度 ${result.pair_completeness}% · 有效样本完整度 ${result.sample_completeness}%`), h("p", { class: "muted" }, result.interpretation)));
      output.append(h("div", { class: "transition-grid" }, [
        ["持续提及", "持续缺席", "新增提及", "失去提及"].map((key) => h("div", { class: `transition-cell${key === "新增提及" ? " gain" : key === "失去提及" ? " loss" : ""}` },
          h("span", {}, key), h("strong", { class: "num" }, result.transition_counts[key]))),
      ]));
      const limited = Object.values(result.delta).some((row) => row.baseline.limited || row.current.limited);
      if (limited) output.append(h("div", { class: "inline-panel warning-panel" }, h("h3", {}, "小样本仅观察方向"), h("p", {}, "以下以原始命中数 / 有效样本数为主，不输出确定性百分点或相对变化诊断。")));
      const chartNode = limited ? null : h("div", { class: "chart", role: "img", "aria-label": "基线与复测指标百分比对比图" });
      if (chartNode) output.append(chartNode);
      output.append(h("h3", {}, limited ? "指标原始计数" : "指标变化（百分点）"), dataTable(limited ? ["指标", "基线", "复测", "变化"] : ["指标", "基线", "复测", "变化", "相对变化"], Object.entries(result.delta).map(([key, row]) => {
        const rowLimited = limited || row.baseline.limited || row.current.limited;
        const cells = [metricNames[key] || key,
          rowLimited ? `${row.baseline.hits}/${row.baseline.n}` : `${pct(row.baseline.value)} (${row.baseline.hits}/${row.baseline.n})`,
          rowLimited ? `${row.current.hits}/${row.current.n}` : `${pct(row.current.value)} (${row.current.hits}/${row.current.n})`,
          rowLimited ? "仅观察方向" : `${row.pp > 0 ? "+" : ""}${row.pp} pp`];
        if (!limited) cells.push(row.relative === null ? "基线为 0，不计算" : pct(row.relative));
        return cells;
      })));
      output.append(h("h3", {}, "逐意图迁移"), dataTable(["Prompt", "维度", "迁移"], result.transitions.map((row) => [row.prompt_text, label(row.dimension), row.change])));
      await nextFrame();
      if (chartNode && window.echarts && ctx.isCurrent()) {
        const chart = window.echarts.init(chartNode);
        const rows = Object.values(result.delta);
        const names = Object.keys(result.delta).map((key) => metricNames[key] || key);
        chart.setOption({ color: ["#89999F", "#00747B"], aria: { enabled: true },
          tooltip: { trigger: "item", formatter: (params) => `${params.seriesName}<br>${params.name}：${pct(params.value[0])}` },
          legend: { data: ["基线", "复测"] }, grid: { left: 100, right: 30, top: 45, bottom: 50 },
          xAxis: { type: "value", max: 100, name: "%", splitLine: { lineStyle: { color: "#D4DEE1" } } },
          yAxis: { type: "category", data: names, inverse: true, axisTick: { show: false }, axisLine: { show: false } },
          series: ["baseline", "current"].map((key, index) => ({ name: index ? "复测" : "基线", type: "scatter", symbolSize: index ? 13 : 11,
            data: rows.map((row, rowIndex) => ({ name: names[rowIndex], value: [row[key].value, rowIndex] })) })) });
        const resize = () => chart.resize(); window.addEventListener("resize", resize);
        ctx.onCleanup(() => { window.removeEventListener("resize", resize); chart.dispose(); });
      }
    } catch (error) { clear(output); output.append(h("div", { class: "error-state" }, h("p", {}, error.message))); }
  });
  if (events.length) root.append(section("共时外部事件", "只记录同时发生的事实，不据此自动归因", dataTable(["时间", "类型", "事件", "来源"], events.map((event) => [event.event_at, event.kind, event.description, event.source || "—"]))));
}

function createReportDialog(ctx, waves) {
  const waveOptions = waves.map((wave) => ({
    value: wave.id,
    label: `#${wave.id} · ${wave.label} · ${formatDate(wave.created_at, ctx.project.timezone)} · ${wave.official_run_id ? `正式 Run #${wave.official_run_id}` : "未执行 · 仅可创建受阻草稿"}`,
  }));
  const latestOfficial = waves.find((wave) => wave.official_run_id);
  const current = select(waveOptions, ctx.params.get("wave") || latestOfficial?.id || waves[0]?.id, { "data-testid": "report-current-wave" });
  const baseline = select([{ value: "", label: "不对比，仅诊断当前 Wave" }, ...waveOptions], "", { "data-testid": "report-baseline-wave" });
  const form = h("form", {}, field("当前 Wave", current), field("可选基线 Wave", baseline),
    h("p", { class: "muted" }, "未指定正式 run 或没有有效样本时，可以保存待处理草稿，但发布闸门会阻止审批。不同口径不会生成严格对比结论。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "创建不可变快照")));
  const modal = drawer("创建报告快照", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (baseline.value && baseline.value === current.value) { formError(form, new Error("基线和当前 Wave 不能相同")); return; }
    const ids = baseline.value ? [Number(baseline.value), Number(current.value)] : [Number(current.value)];
    try { const report = await api.post(`/api/projects/${ctx.project.id}/reports`, { wave_ids: ids }); modal.close(); toast(`报告 v${report.version} 已创建`); ctx.navigate("reports", { tab: "delivery", report: report.id }); }
    catch (error) { formError(form, error); }
  });
}

function renderReportDetail(root, ctx, report) {
  const snapshot = report.snapshot;
  const latest = snapshot.waves[snapshot.waves.length - 1];
  const next = { draft: "data_checked", data_checked: "strategy_reviewed", strategy_reviewed: "client_approved", client_approved: "sent" }[report.approval_status];
  const panel = h("section", { class: "work-section report-document" }, h("article", { class: "inline-panel report-sheet" },
    h("div", { class: "section-head" }, h("div", {}, h("h2", {}, `报告 v${report.version} · ${label(report.approval_status)}`), h("p", {}, `Wave #${latest.wave.id} · ${latest.run ? `正式 Run #${latest.run.id}` : "未指定正式 Run"} · 快照 ${report.data_snapshot_hash.slice(0, 16)}… · ${snapshot.generated_at}`)),
      h("div", { class: "button-group" },
        h("button", { class: "button secondary", onClick: () => previewReport(ctx, report, "client") }, "预览客户版"),
        ["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button secondary", onClick: () => previewReport(ctx, report, "internal") }, "预览内部版") : null,
        next && ctx.role === "admin" ? h("button", { class: "button", disabled: next === "data_checked" && report.gates.length > 0, onClick: () => advanceReport(ctx, report, next) }, next === "sent" ? "登记发送记录" : `推进到${label(next)}`) : null)),
    h("h3", {}, "执行摘要"), h("p", {}, snapshot.diagnosis), h("p", { class: "muted" }, snapshot.causal_boundary),
    h("dl", { class: "definition-list" }, h("div", {}, h("dt", {}, "有效样本"), h("dd", {}, `${latest.metrics.quality.valid_samples}/${latest.metrics.quality.expected_samples}`)),
      h("div", {}, h("dt", {}, "待复核"), h("dd", {}, latest.metrics.quality.pending_review_answers)), h("div", {}, h("dt", {}, "测量模式"), h("dd", {}, latest.metrics.measurement_modes.map(label).join(" / "))),
      h("div", {}, h("dt", {}, "机会"), h("dd", {}, `${snapshot.opportunities.length} 个已确认`))),
    report.gates.length ? h("div", { class: "inline-panel warning-panel" }, h("h3", {}, "发布闸门尚未通过"), h("ul", {}, report.gates.map((gate) => h("li", {}, gate)))) : h("p", { class: "badge success" }, "自动发布闸门已通过；仍需管理员逐步审批"),
    h("div", { class: "button-group" },
      h("a", { class: "button secondary", href: `/api/projects/${ctx.project.id}/reports/${report.id}/export?variant=client&format=html`, target: "_blank", rel: "noopener" }, "打开客户版 HTML"),
      ["client_approved", "sent"].includes(report.approval_status) ? h("a", { class: "button secondary", href: `/api/projects/${ctx.project.id}/reports/${report.id}/export?variant=client&format=pdf` }, "下载客户版 PDF") : h("span", { class: "muted small" }, "客户版 PDF 需先完成客户批准"),
      ["admin", "analyst"].includes(ctx.role) ? h("a", { class: "button secondary", href: `/api/projects/${ctx.project.id}/reports/${report.id}/export?variant=internal&format=pdf` }, "下载内部版 PDF") : null)));
  panel.append(h("details", { class: "advanced" }, h("summary", {}, "审批事件与不可变快照元数据"), h("div", {},
    dataTable(["时间", "状态变化", "原因", "操作者"], report.events.map((event) => [event.created_at, `${event.from_status || "创建"} → ${event.to_status}`, event.reason || "—", event.actor || "系统"])),
    h("p", { class: "code-block" }, JSON.stringify({ schema_version: snapshot.schema_version, hash: report.data_snapshot_hash, wave_ids: report.wave_ids, generated_at: snapshot.generated_at }, null, 2)))));
  root.append(panel);
}

function previewReport(ctx, report, variant) {
  const iframe = h("iframe", { src: `/api/projects/${ctx.project.id}/reports/${report.id}/export?variant=${variant}&format=html`, title: `${variant === "client" ? "客户" : "内部"}版报告预览`, sandbox: "", style: "width:100%;height:75vh;border:1px solid #D4DEE1;border-radius:8px;background:white" });
  drawer(`${variant === "client" ? "客户" : "内部"}版 · v${report.version}`, iframe, { wide: true });
}

function advanceReport(ctx, report, status) {
  if (status === "sent") {
    const reason = textarea("", { required: true, placeholder: "登记接收人、发送方式和时间；系统不会自动向外部服务发送" });
    const form = h("form", {}, field("发送记录", reason), h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "登记为已发送")));
    const modal = drawer("登记报告发送", form);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try { await api.post(`/api/projects/${ctx.project.id}/reports/${report.id}/status`, { status, reason: reason.value }); modal.close(); toast("发送记录已登记"); ctx.refresh(); }
      catch (error) { formError(form, error); }
    });
    return;
  }
  confirmDialog(`推进到${label(status)}`, "此操作由管理员完成并写入审批事件。数据快照本身不会改变；如需修改内容，必须创建新报告版本。", "确认推进", async () => { await api.post(`/api/projects/${ctx.project.id}/reports/${report.id}/status`, { status }); toast("审批状态已更新"); ctx.refresh(); });
}
