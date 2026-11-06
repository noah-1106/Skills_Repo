import { api } from "../api.js";
import { h, clear, pageHead, section, dataTable, badge, metric, formatDate, label, emptyState } from "../components.js";

const todoRoutes = { entities: "entities", opportunities: "opportunities", reports: "reports" };

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
  let action = { route: "measure", label: "开始一次测量", params: {} };
  if (nextTodo) action = { route: todoRoutes[nextTodo.kind] || "overview", label: nextTodo.label, params: {} };
  else if (officialWave) action = { route: "reports", label: "查看对比与报告", params: { wave: officialWave.id } };
  const runningWave = waves.find((wave) => ["running", "planned"].includes(wave.status));
  if (!nextTodo && runningWave) action = { route: "measure", label: runningWave.status === "running" ? "查看测量进度" : "继续测量方案", params: { wave: runningWave.id } };

  clear(root);
  root.append(pageHead("项目总览", `${ctx.project.client_name} · ${ctx.project.category || "未设置品类"} · ${ctx.project.market}，所有时间以 ${ctx.project.timezone} 展示。`,
    [h("a", { class: "button secondary", href: "#/measure" }, "测量工作台")]));
  root.append(h("section", { class: "stage-panel" }, h("div", {}, h("div", { class: "stage-kicker" }, `当前阶段 · ${overview.stage}`),
    h("h2", {}, nextTodo ? `有 ${overview.todos.reduce((sum, item) => sum + item.count, 0)} 项工作需要处理` : officialWave ? "最新正式测量已就绪" : "先建立可复现的测量基线"),
    h("p", {}, nextTodo ? "先完成审核与口径确认，再解读结果。系统不会把候选机会自动写成客户结论。"
      : officialWave ? "正式 run 已由管理员指定。下一步可复核证据、确认机会或创建不可变报告快照。"
      : "确认实体和问题集版本后创建 wave；创建方案不会调用外部引擎，确认 run 前可查看调用预估。")),
    h("a", { class: "button", href: `#/${action.route}` }, action.label)));

  if (metrics) {
    root.append(h("div", { class: "metric-strip", "aria-label": "最新正式测量摘要" },
      metric("意图覆盖", metrics.coverage), metric("稳定命中", metrics.hit_rate),
      metric("有效推荐", metrics.effective_recommendation_rate), metric("北极星指标", metrics.north_star)));
    root.append(h("p", { class: "muted small" }, metrics.quality.valid_samples
      ? `最新正式 run：${metrics.quality.valid_samples}/${metrics.quality.expected_samples} 条有效样本。${metrics.is_demo ? "当前为演示引擎，不代表真实 AI 表现。" : "比率同时展示原始计数与 Wilson 区间。"}`
      : "正式 run 没有有效样本，不能形成零提及或下降结论。"));
  } else {
    root.append(h("div", { class: "inline-panel" }, h("h2", {}, "尚无可解读的正式数据"),
      h("p", { class: "muted" }, "完成 run 后，管理员需要在测量页人工指定正式 run。未完成、失败或重试中的 run 不会自动成为报告基线。")));
  }

  const todoBody = overview.todos.length ? h("div", { class: "todo-list" }, overview.todos.map((todo) => h("div", { class: "todo-row" },
    h("a", { href: `#/${todoRoutes[todo.kind] || "overview"}` }, todo.label), h("strong", { class: "todo-count num" }, todo.count),
    h("small", {}, todo.kind === "reports" ? "自动闸门通过后仍需管理员审批" : todo.kind === "entities" ? "消歧依据和别名版本会留痕" : "确认适用性后才能评分与进入报告"))))
    : h("div", { class: "section-note" }, "当前没有待处理审批。可检查下一次复测安排或补充外部事件。");
  root.append(section("需要处理", "按交付顺序排列，不以颜色代替任务说明", todoBody));

  root.append(section("最近 wave", "wave 是业务测量，run 是其下的执行尝试", dataTable(
    ["Wave", "状态", "正式 Run", "创建时间", "下一步"], waves.slice(0, 8).map((wave) => [
      h("a", { class: "table-link", href: `#/measure?wave=${wave.id}` }, wave.label), badge(wave.status),
      wave.official_run_id ? `#${wave.official_run_id}` : h("span", { class: "muted" }, "未指定"), formatDate(wave.created_at, ctx.project.timezone),
      h("a", { href: `#/measure?wave=${wave.id}` }, wave.status === "running" ? "查看进度" : "打开"),
    ]), "还没有 wave。进入测量工作台创建第一个方案。")));

  const side = h("div", { class: "inline-panel" }, h("h2", {}, "运行与交付记录"),
    h("dl", { class: "definition-list" },
      h("div", {}, h("dt", {}, "下次复测"), h("dd", {}, overview.next_schedule ? formatDate(overview.next_schedule.scheduled_at, ctx.project.timezone) : "未安排")),
      h("div", {}, h("dt", {}, "失败样本"), h("dd", { class: "num" }, overview.failed_samples)),
      h("div", {}, h("dt", {}, "外部调用"), h("dd", { class: "num" }, overview.operations.external_calls)),
      ctx.role !== "reviewer" && ctx.role !== "viewer" ? h("div", {}, h("dt", {}, "交付工时"), h("dd", {}, `${overview.work_hours} 小时`)) : null),
    h("a", { href: "#/admin" }, "查看调度、成本与运营记录"));
  root.append(h("div", { class: "split-layout" }, h("div", {}, section("开放告警", "业务波动只作人工核查提醒，不自动归因为 GEO 策略效果",
    overview.alerts.length ? dataTable(["级别", "内容", "时间"], overview.alerts.map((alert) => [badge(alert.severity, alert.severity === "warning" ? "warning" : "danger"), alert.message, formatDate(alert.created_at, ctx.project.timezone)])) : h("div", { class: "section-note" }, "没有开放告警。"))), side));
}
