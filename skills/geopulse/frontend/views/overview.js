import { api } from "../api.js";
import { h, clear, pageHead, section, dataTable, badge, metric, formatDate } from "../components.js";

const todoRoutes = { entities: "entities", opportunities: "opportunities", reports: "reports" };
const deliverySteps = [
  ["define", "定义", "问题与实体"], ["measure", "测量", "冻结并执行"],
  ["review", "复核", "原文与判定"], ["deliver", "交付", "机会与报告"],
];

export async function renderOverview(root, ctx) {
  const [overview, wavesData] = await Promise.all([
    api.get(`/api/projects/${ctx.project.id}/overview`), api.get(`/api/projects/${ctx.project.id}/waves`),
  ]);
  if (!ctx.isCurrent()) return;
  const waves = wavesData.items;
  const officialWave = waves.find((wave) => wave.official_run_id);
  const metrics = overview.latest_metrics;
  if (officialWave) {
    const protocol = officialWave.protocol;
    ctx.setProtocol({ promptSet: `v${officialWave.prompt_set_id}`, entityVersion: protocol.entity_version,
      engines: protocol.engine_signature.map((engine) => engine.name).join(" / "), mode: protocol.mode,
      target: protocol.measurement_target, repeats: protocol.repeats, n: metrics?.quality?.valid_samples,
      demo: metrics?.is_demo, real: metrics && !metrics.is_demo });
  }
  const nextTodo = overview.todos[0];
  const hasConfirmedEntity = Boolean(overview.counts.brand_entities.confirmed);
  const hasFrozenPromptSet = Boolean(overview.counts.prompt_sets.frozen);
  let action = { route: "measure", label: "开始一次测量", params: {} };
  if (nextTodo) action = { route: todoRoutes[nextTodo.kind] || "overview", label: nextTodo.label, params: {} };
  else if (!waves.length && !hasConfirmedEntity) action = { route: "entities", label: "检查品牌实体", params: {} };
  else if (!waves.length && !hasFrozenPromptSet) action = { route: "prompts", label: "审核并冻结问题集", params: {} };
  else if (officialWave) action = { route: "reports", label: "查看对比与报告", params: { wave: officialWave.id } };
  const runningWave = waves.find((wave) => ["running", "planned"].includes(wave.status));
  if (!nextTodo && runningWave) action = { route: "measure", label: runningWave.status === "running" ? "查看测量进度" : "继续测量方案", params: { wave: runningWave.id } };
  const actionQuery = new URLSearchParams(action.params).toString();

  let currentStep = overview.counts.prompt_sets.frozen ? "measure" : "define";
  if (officialWave) currentStep = metrics?.quality?.pending_review_answers ? "review" : "deliver";
  if (nextTodo?.kind === "entities") currentStep = "define";
  if (["opportunities", "reports"].includes(nextTodo?.kind)) currentStep = "deliver";

  clear(root);
  root.append(pageHead("项目总览", `${ctx.project.client_name} · ${ctx.project.category || "未设置品类"} · ${ctx.project.market}，所有时间以 ${ctx.project.timezone} 展示。`,
    waves.length && action.route !== "measure" ? [h("a", { class: "button secondary", href: "#/measure" }, "测量工作台")] : []));

  const promptCount = Object.values(overview.counts.prompt_sets).reduce((sum, count) => sum + count, 0);
  const current = h("div", { class: "stage-current" },
    h("div", { class: "stage-kicker" }, `当前阶段 · ${overview.stage}`),
    h("h2", {}, nextTodo ? `有 ${overview.todos.reduce((sum, item) => sum + item.count, 0)} 项工作需要处理` : officialWave ? "最新正式测量已就绪" : "先建立可复现的测量基线"),
    h("p", {}, nextTodo ? "先完成审核与口径确认，再解读结果。系统不会把候选机会自动写成客户结论。"
      : officialWave ? "正式 run 已由管理员指定。下一步可复核证据、确认机会或创建不可变报告快照。"
      : "确认实体和问题集版本后创建 wave；创建方案不会调用外部引擎，确认 run 前可查看调用预估。"),
    waves.length ? h("a", { class: "button", href: `#/${action.route}${actionQuery ? `?${actionQuery}` : ""}` }, action.label) : null);

  if (!waves.length) {
    const entityCount = Object.values(overview.counts.brand_entities).reduce((sum, count) => sum + count, 0);
    const confirmedEntities = overview.counts.brand_entities.confirmed || 0;
    const frozenPrompts = overview.counts.prompt_sets.frozen || 0;
    const baselineSteps = [
      ["检查品牌实体", "添加主品牌与竞品，补充别名和消歧依据。", confirmedEntities ? `${confirmedEntities}/${entityCount} 个已确认` : entityCount ? `${entityCount} 个待确认` : "尚未添加", "#/entities", !confirmedEntities],
      ["审核并冻结问题集", "冻结后的版本才会进入测量协议。", frozenPrompts ? `${frozenPrompts} 个版本已冻结` : promptCount ? `${promptCount} 个版本待整理` : "尚未创建", "#/prompts", Boolean(confirmedEntities && !frozenPrompts)],
      ["查看预估并创建 Run", "先确认问题、引擎、轮次和调用预估，再开始测量。", "尚未创建 Wave", "#/measure", Boolean(confirmedEntities && frozenPrompts)],
    ];
    root.append(h("section", { class: "stage-panel overview-flow empty-flow" }, current,
      h("ol", { class: "baseline-checklist", "aria-label": "建立第一条测量基线" }, baselineSteps.map(([title, description, status, href, isNext], index) =>
        h("li", { class: isNext ? "next" : "", "aria-current": isNext ? "step" : null }, h("a", { href, "aria-label": title }, h("span", { class: "baseline-index num", "aria-hidden": "true" }, String(index + 1).padStart(2, "0")),
          h("div", {}, h("h3", {}, title), h("p", {}, description)), h("small", { class: "baseline-state" }, status)))))));
  } else {
    root.append(h("section", { class: "stage-panel overview-flow" }, current,
      h("ol", { class: "delivery-path", "aria-label": "交付路径" }, deliverySteps.map(([key, title, description]) =>
        h("li", { class: key === currentStep ? "current" : "", "aria-current": key === currentStep ? "step" : null },
          h("strong", {}, title), h("small", {}, description))))));
  }

  const todoSection = overview.todos.length ? section("需要处理", "按交付顺序排列，不以颜色代替任务说明", h("div", { class: "todo-list" }, overview.todos.map((todo) => h("div", { class: "todo-row" },
    h("a", { href: `#/${todoRoutes[todo.kind] || "overview"}` }, todo.label), h("strong", { class: "todo-count num" }, todo.count),
    h("small", {}, todo.kind === "reports" ? "自动闸门通过后仍需管理员审批" : todo.kind === "entities" ? "消歧依据和别名版本会留痕" : "确认适用性后才能评分与进入报告"))))) : null;
  const alertSection = overview.alerts.length ? section("开放告警", "业务波动只作人工核查提醒，不自动归因为 GEO 策略效果",
    h("div", { class: "alert-list" }, overview.alerts.map((alert) => h("article", { class: "alert-row" },
      h("div", {}, badge(alert.severity, alert.severity === "warning" ? "warning" : "danger"), h("time", { class: "muted small" }, formatDate(alert.created_at, ctx.project.timezone))),
      h("p", {}, alert.message))))) : null;

  if (!waves.length) {
    if (todoSection) root.append(todoSection);
    if (alertSection) root.append(alertSection);
    return;
  }

  const main = h("div", { class: "overview-main" });
  if (metrics) {
    const measurement = section("最新正式测量", "区间表示不确定性；精确计数与估计值始终同时保留", h("div", { class: "metric-strip measurement-ledger", "aria-label": "最新正式测量摘要" },
      metric("意图覆盖", metrics.coverage), metric("稳定命中", metrics.hit_rate),
      metric("有效推荐", metrics.effective_recommendation_rate), metric("北极星指标", metrics.north_star)));
    measurement.classList.add("measurement-section");
    main.append(measurement);
    main.append(h("p", { class: "muted small measurement-note" }, metrics.quality.valid_samples
      ? `最新正式 run：${metrics.quality.valid_samples}/${metrics.quality.expected_samples} 条有效样本。${metrics.is_demo ? "当前为演示引擎，不代表真实 AI 表现。" : "比率同时展示原始计数与 Wilson 区间。"}`
      : "正式 run 没有有效样本，不能形成零提及或下降结论。"));
  } else {
    main.append(h("div", { class: "inline-panel overview-empty" }, h("h2", {}, "尚无可解读的正式数据"),
      h("p", { class: "muted" }, "完成 run 后，管理员需要在测量页人工指定正式 run。未完成、失败或重试中的 run 不会自动成为报告基线。")));
  }

  const reviewHref = officialWave ? `#/review?run=${officialWave.official_run_id}` : "#/review";
  const reportCount = Object.values(overview.counts.reports).reduce((sum, count) => sum + count, 0);
  const pendingOpportunities = (overview.counts.opportunities.candidate || 0) + (overview.counts.opportunities.eligibility_pending || 0);
  const evidenceItems = [
    ["问题", overview.counts.prompt_sets.frozen ? `${overview.counts.prompt_sets.frozen} 个冻结版本` : promptCount ? `${promptCount} 个版本待整理` : "创建并冻结问题集", "#/prompts"],
    ["原文", officialWave ? `正式 Run #${officialWave.official_run_id}` : "等待正式测量", reviewHref],
    ["判定", metrics ? `${metrics.quality.pending_review_answers} 条待复核` : officialWave ? "等待判定数据" : "测量后复核实体", reviewHref],
    ["机会", overview.counts.opportunities.confirmed ? `${overview.counts.opportunities.confirmed} 个已确认` : pendingOpportunities ? `${pendingOpportunities} 个待确认` : "正式测量后发现", "#/opportunities"],
    ["报告", reportCount ? `${reportCount} 个快照版本` : "完成测量后创建", "#/reports"],
  ];
  main.append(h("nav", { class: "evidence-chain", "aria-label": "从问题到报告的证据链" },
    h("div", { class: "chain-links" }, evidenceItems.map(([title, detail, href]) =>
      h("a", { href }, h("strong", {}, title), h("small", {}, detail))))));

  const canViewWorkHours = ctx.role !== "reviewer" && ctx.role !== "viewer";
  const hasOperations = Boolean(overview.next_schedule || overview.failed_samples || overview.operations.external_calls || (canViewWorkHours && overview.work_hours));
  const operations = hasOperations ? h("details", { class: "advanced operations-ledger" }, h("summary", {}, "运行与交付记录"),
    h("div", {}, h("dl", { class: "definition-list" },
      h("div", {}, h("dt", {}, "下次复测"), h("dd", {}, overview.next_schedule ? formatDate(overview.next_schedule.scheduled_at, ctx.project.timezone) : "未安排")),
      h("div", {}, h("dt", {}, "失败样本"), h("dd", { class: "num" }, overview.failed_samples)),
      h("div", {}, h("dt", {}, "外部调用"), h("dd", { class: "num" }, overview.operations.external_calls)),
      canViewWorkHours ? h("div", {}, h("dt", {}, "交付工时"), h("dd", {}, `${overview.work_hours} 小时`)) : null),
    h("a", { href: "#/admin" }, "查看调度、成本与运营记录"))) : null;
  const aside = todoSection || alertSection || operations ? h("aside", { class: "overview-aside", "aria-label": "待办与运行上下文" }, todoSection, alertSection, operations) : null;
  root.append(h("div", { class: `overview-workgrid${aside ? "" : " no-aside"}` }, main, aside));

  root.append(section("最近 wave", "wave 是业务测量，run 是其下的执行尝试", dataTable(
    ["Wave", "状态", "正式 Run", "创建时间", "下一步"], waves.slice(0, 8).map((wave) => [
      h("a", { class: "table-link", href: `#/measure?wave=${wave.id}` }, wave.label), badge(wave.status),
      wave.official_run_id ? `#${wave.official_run_id}` : h("span", { class: "muted" }, "未指定"), formatDate(wave.created_at, ctx.project.timezone),
      h("a", { href: `#/measure?wave=${wave.id}` }, wave.status === "running" ? "查看进度" : "打开"),
    ]), "还没有 wave。进入测量工作台创建第一个方案。")));
}
