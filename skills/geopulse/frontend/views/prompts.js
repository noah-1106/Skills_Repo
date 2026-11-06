import { api } from "../api.js";
import { h, clear, pageHead, section, dataTable, badge, drawer, field, input, select, textarea, checkbox, toast, formError, confirmDialog, downloadJson, label } from "../components.js";

const dimensions = { brand: "品牌词", scene: "场景词", compare: "对比词", choice: "选购词" };
const refreshSet = (ctx, id) => String(ctx.params.get("set")) === String(id) ? ctx.refresh() : ctx.navigate("prompts", { set: id });

export async function renderPrompts(root, ctx) {
  const sets = (await api.get(`/api/projects/${ctx.project.id}/prompt-sets`)).items;
  if (!sets.length) {
    clear(root); root.append(pageHead("问题集工作台", "先创建草稿，再生成或导入候选题。", [h("button", { class: "button", onClick: () => newSet(ctx) }, "新建问题集")]),
      h("div", { class: "empty-state" }, h("h3", {}, "还没有问题集"), h("p", {}, "候选题必须逐条审核并满足四维配额，冻结后才能用于测量。")));
    return;
  }
  const selectedId = Number(ctx.params.get("set")) || sets.find((item) => item.status === "draft")?.id || sets[0].id;
  const current = await api.get(`/api/projects/${ctx.project.id}/prompt-sets/${selectedId}`);
  if (!ctx.isCurrent()) return;
  const activeItems = current.items.filter((item) => item.status !== "rejected");
  const pending = activeItems.filter((item) => !["reviewed", "frozen"].includes(item.status)).length;
  ctx.setProtocol({ promptSet: `${current.name} · v${current.version}`, engines: "尚未选择", n: undefined });
  const setSelector = select(sets.map((item) => ({ value: item.id, label: `v${item.version} · ${item.name} · ${label(item.status)}` })), current.id, { "aria-label": "选择问题集版本" });
  setSelector.addEventListener("change", () => ctx.navigate("prompts", { set: setSelector.value }));
  const actions = [h("button", { class: "button secondary", onClick: () => newSet(ctx) }, "新建草稿")];
  if (current.status === "draft") {
    actions.push(h("button", { class: "button secondary", onClick: () => scaffoldDialog(ctx, current) }, "生成候选题"));
    actions.push(h("button", { class: "button secondary", onClick: () => importDialog(ctx, current) }, "导入 JSON / CSV"));
    actions.push(h("button", { class: "button", onClick: () => changeStatus(ctx, current, "reviewing") }, "进入审核"));
  }
  if (current.status === "reviewing" && ctx.role === "admin") {
    const next = activeItems.find((item) => !["reviewed", "frozen"].includes(item.status));
    actions.push(next ? h("button", { class: "button", onClick: () => reviewDialog(ctx, current, next, "reviewed") }, `继续审核 · 还剩 ${pending} 条`)
      : h("button", { class: "button", onClick: () => changeStatus(ctx, current, "frozen") }, "冻结此版本"));
  }
  if (current.status === "frozen") actions.push(h("button", { class: "button", onClick: async () => { const copy = await api.post(`/api/projects/${ctx.project.id}/prompt-sets/${current.id}/copy`, {}); toast("已复制为新草稿"); refreshSet(ctx, copy.id); } }, "复制为新版本"));
  clear(root);
  root.append(pageHead("问题集工作台", "把自然问法归入同一业务意图；冻结后文本、分层与适用性不再修改。", actions));
  root.append(h("div", { class: "inline-panel emphasis" }, h("div", { class: "form-grid" }, field("当前版本", setSelector),
    h("div", {}, h("h2", {}, current.status === "frozen" ? "这是不可变测量版本" : pending ? `还有 ${pending} 条待审核` : "题目已完成逐条审核"),
      h("p", { class: "muted" }, current.status === "frozen" ? `冻结于 ${current.frozen_at || "—"} · 内容哈希 ${current.content_hash.slice(0, 12)}。如需修改，请复制新版本。`
        : current.status === "draft" ? "先添加候选题并进入审核。导入内容请避免包含客户机密；可选择自动脱敏邮箱和手机号。"
        : pending ? "管理员需要明确每条题目是否保留及其业务适用性。" : "可以冻结。冻结时会再次校验四维配额与未审核题目。"))),
    h("dl", { class: "definition-list" }, Object.entries(dimensions).map(([key, name]) => h("div", {}, h("dt", {}, name), h("dd", {}, `${activeItems.filter((item) => item.dimension === key).length} 条`))),
      h("div", {}, h("dt", {}, "发现 / 导航"), h("dd", {}, `${activeItems.filter((item) => item.query_type === "discovery").length} / ${activeItems.filter((item) => item.query_type === "navigation").length}`)))));

  const rows = current.items.map((item) => [
    h("button", { class: "table-link", onClick: () => promptDetail(ctx, current, item) }, item.text),
    dimensions[item.dimension], badge(item.status),
    ctx.role === "admin" && ["draft", "reviewing"].includes(current.status) ? h("div", { class: "button-group" },
      !["reviewed", "frozen"].includes(item.status) ? h("button", { class: "button small-button", onClick: () => reviewDialog(ctx, current, item, "reviewed") }, "通过") : null,
      item.status !== "rejected" ? h("button", { class: "button small-button secondary", onClick: () => reviewDialog(ctx, current, item, "rejected") }, "排除") : null,
      item.status === "rejected" ? h("button", { class: "button small-button secondary", onClick: () => reviewDialog(ctx, current, item, "draft") }, "恢复") : null) : h("span", { class: "muted" }, current.status === "frozen" ? "只读" : "由管理员审核"),
  ]);
  const promptTable = dataTable(["题目", "维度", "状态", "操作"], rows);
  promptTable.classList.add("prompt-table");
  root.append(section(`题目清单 · ${current.items.length} 条`, "选择题名查看技术口径；审核动作只改变当前草稿，已排除题目不进入冻结内容", promptTable));
  root.append(h("details", { class: "advanced" }, h("summary", {}, "版本 diff 与导出"), h("div", {},
    h("div", { class: "button-group" },
      h("button", { class: "button secondary", onClick: () => diffDialog(ctx, sets, current) }, "比较两个版本"),
      h("a", { class: "button secondary", href: `/api/projects/${ctx.project.id}/prompt-sets/${current.id}/export?format=csv` }, "导出 CSV"),
      h("button", { class: "button secondary", onClick: async () => downloadJson(await api.get(`/api/projects/${ctx.project.id}/prompt-sets/${current.id}/export?format=json`), `prompt-set-${current.id}.json`) }, "导出 JSON"),
      current.status === "frozen" && ctx.role === "admin" ? h("button", { class: "button danger", onClick: () => changeStatus(ctx, current, "retired", true) }, "退役版本") : null),
    h("p", { class: "muted small" }, "导出文件含完整 Prompt，请按客户资料管理；不包含引擎密钥。"))));
}

function promptDetail(ctx, current, item) {
  const canReview = ctx.role === "admin" && ["draft", "reviewing"].includes(current.status);
  const openReview = (status) => { modal.close(); reviewDialog(ctx, current, item, status); };
  const content = h("div", {},
    h("div", { class: "inline-panel emphasis" }, h("h3", {}, item.text), h("p", {}, badge(item.status)),
      h("p", { class: "muted" }, item.scenario || "未设置场景")),
    h("dl", { class: "definition-list" },
      h("div", {}, h("dt", {}, "Canonical intent"), h("dd", {}, item.canonical_intent_id)),
      h("div", {}, h("dt", {}, "维度"), h("dd", {}, dimensions[item.dimension])),
      h("div", {}, h("dt", {}, "查询类型"), h("dd", {}, item.query_type === "discovery" ? "发现型" : "导航型")),
      h("div", {}, h("dt", {}, "优先级"), h("dd", {}, `P${item.priority}`)),
      h("div", {}, h("dt", {}, "业务适用性"), h("dd", {}, label(item.eligibility)))),
    canReview ? h("div", { class: "form-actions" },
      !["reviewed", "frozen"].includes(item.status) ? h("button", { class: "button", onClick: () => openReview("reviewed") }, "审核此题") : null,
      item.status === "rejected" ? h("button", { class: "button", onClick: () => openReview("draft") }, "恢复为草稿") : null,
      item.status !== "rejected" ? h("button", { class: "button secondary", onClick: () => openReview("rejected") }, "排除此题") : null) : null);
  const modal = drawer("题目详情与审核", content);
}

function newSet(ctx) {
  const name = input("", { required: true, placeholder: "例如：2026 Q4 GEO 基线" });
  const form = h("form", {}, field("问题集名称", name), h("p", { class: "muted" }, "创建后为草稿，不会自动用于测量。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "创建草稿")));
  const modal = drawer("新建问题集", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { const created = await api.post(`/api/projects/${ctx.project.id}/prompt-sets`, { name: name.value }); modal.close(); refreshSet(ctx, created.id); }
    catch (error) { formError(form, error); }
  });
}

function reviewDialog(ctx, current, item, status) {
  const eligibility = select([{ value: "eligible", label: "适用于客户业务" }, { value: "client_confirmed", label: "客户已确认适用" }, { value: "unknown", label: "尚不确定" }, { value: "not_eligible", label: "不适用" }], item.eligibility === "not_eligible" ? "not_eligible" : "eligible");
  const form = h("form", {}, h("p", {}, item.text), status !== "rejected" ? field("业务适用性", eligibility, "北极星只纳入高优先级且已确认适用的发现型意图") : h("p", { class: "muted" }, "排除后不会进入冻结版本。"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, status === "reviewed" ? "确认通过" : status === "rejected" ? "确认排除" : "恢复为草稿")));
  const modal = drawer("审核 Prompt", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api.post(`/api/projects/${ctx.project.id}/prompt-sets/${current.id}/items/${item.id}/review`, { status, eligibility: status === "rejected" ? null : eligibility.value }); modal.close(); toast("审核状态已保存"); ctx.refresh(); }
    catch (error) { formError(form, error); }
  });
}

async function changeStatus(ctx, current, status, dangerous = false) {
  const action = async () => {
    try { await api.post(`/api/projects/${ctx.project.id}/prompt-sets/${current.id}/status`, { status, reason: status === "retired" ? "管理员退役旧版本" : "" }); toast(status === "frozen" ? "问题集已冻结" : "状态已更新"); ctx.refresh(); }
    catch (error) { toast(error.detail?.quotas ? `${error.message}：${JSON.stringify(error.detail.quotas)}` : error.message, true); }
  };
  if (status === "frozen") confirmDialog("冻结问题集", "冻结后不能修改文本、意图、分层或适用性。后续测量会引用这个内容哈希。", "冻结版本", action);
  else if (dangerous) confirmDialog("退役问题集", "已有 wave 快照不受影响，但新测量不应继续使用此版本。", "确认退役", action, true);
  else await action();
}

function scaffoldDialog(ctx, current) {
  const brand = input(ctx.project.name, { required: true });
  const category = input(ctx.project.category, { required: true });
  const competitors = input("", { placeholder: "竞品 A, 竞品 B" });
  const form = h("form", {}, field("主品牌", brand), field("业务品类", category), field("竞品（逗号分隔）", competitors),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "预览 16 条候选题")));
  const modal = drawer("生成候选题", form, { wide: true });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await api.post(`/api/projects/${ctx.project.id}/prompt-sets/scaffold/preview`, { brand: brand.value, category: category.value, competitors: competitors.value.split(/[,，]/).map((value) => value.trim()).filter(Boolean) });
      clear(modal.body);
      const redact = checkbox("导入前脱敏", true, "替换邮箱与中国大陆手机号");
      const importForm = h("form", {}, h("p", { class: "muted" }, result.note), dataTable(["Intent", "候选题", "类型"], result.items.map((item) => [item.canonical_intent_id, item.text, `${dimensions[item.dimension]} · ${item.query_type}`])),
        redact.node, h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "加入当前草稿")));
      modal.body.append(importForm);
      importForm.addEventListener("submit", async (submitEvent) => {
        submitEvent.preventDefault();
        try { const added = await api.post(`/api/projects/${ctx.project.id}/prompt-sets/${current.id}/items`, { items: result.items, redact: redact.control.checked }); modal.close(); toast(`已加入 ${added.count} 条，跳过 ${added.duplicates.length} 条重复`); ctx.refresh(); }
        catch (error) { formError(importForm, error); }
      });
    } catch (error) { formError(form, error); }
  });
}

function parseCsv(source) {
  const rows = []; let row = [], value = "", quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (char === '"' && quoted && source[index + 1] === '"') { value += '"'; index += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === "," && !quoted) { row.push(value); value = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && source[index + 1] === "\n") index += 1;
      row.push(value); if (row.some((cell) => cell !== "")) rows.push(row); row = []; value = "";
    } else value += char;
  }
  row.push(value); if (row.some((cell) => cell !== "")) rows.push(row);
  if (rows.length < 2) throw new Error("CSV 需要表头和至少一行数据");
  const headers = rows[0].map((header) => header.trim());
  if (!headers.includes("text") || !headers.includes("dimension")) throw new Error("CSV 至少包含 text、dimension 两列");
  return rows.slice(1).map((cells) => Object.fromEntries(headers.map((header, index) => [header, cells[index] || ""])));
}

function importDialog(ctx, current) {
  const source = textarea("", { required: true, rows: 14, placeholder: '[{"text":"有哪些 GEO 工具？","dimension":"choice","query_type":"discovery","priority":4}]' });
  const redact = checkbox("导入前脱敏", true, "建议不要粘贴客户机密或未授权个人信息");
  const form = h("form", {}, field("JSON 数组或带表头 CSV", source, "必填 text、dimension；可含 canonical_intent_id、query_type、priority、eligibility 等字段", true), redact.node,
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "校验并导入")));
  const modal = drawer("导入候选题", form, { wide: true });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const items = source.value.trim().startsWith("[") ? JSON.parse(source.value) : parseCsv(source.value);
      if (!Array.isArray(items)) throw new Error("JSON 顶层必须是数组");
      const result = await api.post(`/api/projects/${ctx.project.id}/prompt-sets/${current.id}/items`, { items, redact: redact.control.checked });
      modal.close(); toast(`导入 ${result.count} 条，去重 ${result.duplicates.length} 条`); ctx.refresh();
    } catch (error) { formError(form, error); }
  });
}

function diffDialog(ctx, sets, current) {
  const other = select(sets.filter((item) => item.id !== current.id).map((item) => ({ value: item.id, label: `v${item.version} · ${item.name}` })));
  const output = h("div", {});
  const form = h("form", {}, field("与当前版本比较", other), h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "生成 diff")), output);
  const modal = drawer("问题集版本 diff", form, { wide: true });
  if (!other.options.length) { clear(form); form.append(h("p", {}, "需要至少两个问题集版本才能比较。")); return; }
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const diff = await api.get(`/api/projects/${ctx.project.id}/prompt-sets/${current.id}/diff/${other.value}`);
      clear(output); output.append(h("h3", {}, `新增 ${diff.added.length} · 删除 ${diff.removed.length} · 修改 ${diff.changed.length}`),
        dataTable(["变更", "Logical ID", "字段"], [
          ...diff.added.map((item) => ["新增", item.logical_id, item.text]), ...diff.removed.map((item) => ["删除", item.logical_id, item.text]),
          ...diff.changed.map((item) => ["修改", item.logical_id, item.fields.join("、")]),
        ]));
    } catch (error) { formError(form, error); }
  });
}
