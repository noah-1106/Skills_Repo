import { api } from "../api.js";
import { h, clear, pageHead, section, dataTable, badge, drawer, field, input, select, textarea, checkbox, toast, formError, label } from "../components.js";

export async function renderEntities(root, ctx) {
  const includeHistory = ctx.params.get("history") === "1";
  const data = await api.get(`/api/projects/${ctx.project.id}/entities?include_history=${includeHistory ? 1 : 0}`);
  if (!ctx.isCurrent()) return;
  const pending = data.items.filter((entity) => ["draft", "pending_review"].includes(entity.status));
  const primary = data.items.find((entity) => entity.role === "primary" && entity.status === "confirmed" && !entity.valid_to);
  const actions = [h("button", { class: "button secondary", onClick: () => ctx.navigate("entities", includeHistory ? {} : { history: 1 }) }, includeHistory ? "只看当前实体" : "查看历史版本")];
  if (["admin", "analyst"].includes(ctx.role)) actions.push(h("button", { class: "button", onClick: () => entityDialog(ctx) }, "新增实体"));
  clear(root);
  root.append(pageHead("品牌实体工作台", "先确认“这个名字究竟是谁”，再计算有效提及。字符串命中不等于目标实体已确认。", actions));
  root.append(h("div", { class: "inline-panel emphasis" }, h("h2", {}, pending.length ? `${pending.length} 个实体版本等待管理员审核` : "当前实体池已完成审核"),
    h("p", { class: "muted" }, primary ? `当前主品牌：${primary.name}（实体版本 v${primary.version}）。有效提及、推荐与 SoV 只使用 confirmed 实体。`
      : "尚未确认主品牌。创建主品牌草稿后，由管理员填写消歧依据并确认，才能创建 wave。"),
    pending.length && ctx.role === "admin" ? h("button", { class: "button", onClick: () => reviewDialog(ctx, pending[0]) }, `审核 ${pending[0].name}`) : null));
  if (data.conflicts.length) root.append(h("div", { class: "inline-panel warning-panel" }, h("h2", {}, `发现 ${data.conflicts.length} 组别名重叠`),
    h("p", {}, "以下冲突不会被自动合并。请补全实体卡、排除语境，或由管理员明确保留。生产 judge 会先消歧。"),
    dataTable(["实体 A / 别名", "实体 B / 别名"], data.conflicts.map((conflict) => [`${conflict.brand_a} / ${conflict.alias_a}`, `${conflict.brand_b} / ${conflict.alias_b}`]))));
  const rows = data.items.map((entity) => {
    const card = entity.entity_card || {};
    return [h("div", {}, h("div", { class: "cell-title" }, entity.name), h("span", { class: "cell-sub" }, (card.aliases || []).join("、") || "无别名")),
      h("div", {}, label(entity.role), entity.valid_to ? h("span", { class: "cell-sub" }, "历史版本") : null),
      h("div", {}, card.category || "—", h("span", { class: "cell-sub" }, card.domain || "未配置官网")),
      h("div", {}, badge(entity.status), h("span", { class: "cell-sub" }, `v${entity.version}${entity.review_reason ? ` · ${entity.review_reason}` : ""}`)),
      h("div", { class: "button-group" },
        ["draft", "pending_review"].includes(entity.status) && ctx.role === "admin" ? h("button", { class: "button small-button", onClick: () => reviewDialog(ctx, entity) }, "审核") : null,
        !["draft", "pending_review"].includes(entity.status) && ["admin", "analyst"].includes(ctx.role) ? h("button", { class: "button small-button secondary", onClick: () => entityDialog(ctx, entity) }, "新版本") : null,
        h("button", { class: "button small-button ghost", onClick: () => entityDetail(entity) }, "实体卡")
      )
    ];
  });
  root.append(section(includeHistory ? "全部实体版本" : "当前实体池", "开放候选必须经管理员分配角色并确认后才进入竞品池", dataTable(
    ["实体 / 别名", "角色", "品类 / 官网", "状态 / 版本", "操作"], rows), [h("button", { class: "button secondary small-button", onClick: () => poolDiff(ctx, data.items) }, "竞品池 diff")]));
}

function entityForm(entity) {
  const card = entity?.entity_card || {};
  return {
    name: input(entity?.name || "", { required: true }),
    role: select([{ value: "competitor", label: "竞品" }, { value: "primary", label: "主品牌" }, { value: "candidate", label: "开放候选" }], entity?.role || "competitor"),
    aliases: input((card.aliases || []).join(", "), { placeholder: "英文别名, 缩写, 旧名" }),
    category: input(card.category || "", { placeholder: "具体产品品类" }),
    company: input(card.company || ""),
    domain: input(card.domain || "", { placeholder: "example.com，不带 https://" }),
    excludes: textarea((card.exclude_contexts || []).join("\n"), { placeholder: "每行一个需要排除的同名语境" }),
    allow: checkbox("我已核对并保留别名冲突", false, "仅在确认同名实体或包含关系后勾选"),
  };
}

function entityDialog(ctx, entity) {
  const controls = entityForm(entity);
  const form = h("form", {}, h("div", { class: "form-grid" }, field("实体名称", controls.name), field("角色", controls.role),
    field("别名", controls.aliases), field("品类", controls.category), field("公司 / 集团", controls.company), field("官网域名", controls.domain),
    field("排除语境", controls.excludes, "例如 GeoPulse 软件需要排除地质、地球物理语境", true)), controls.allow.node,
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, entity ? "创建不可变新版本" : "保存为待审核草稿")));
  const modal = drawer(entity ? `新版本 · ${entity.name}` : "新增品牌实体", form, { wide: true });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = { name: controls.name.value, role: controls.role.value, allow_conflicts: controls.allow.control.checked,
      entity_card: { aliases: controls.aliases.value.split(/[,，]/).map((value) => value.trim()).filter(Boolean),
        category: controls.category.value, company: controls.company.value, domain: controls.domain.value.replace(/^https?:\/\//, "").replace(/\/$/, ""),
        exclude_contexts: controls.excludes.value.split("\n").map((value) => value.trim()).filter(Boolean) } };
    try {
      await api.post(entity ? `/api/projects/${ctx.project.id}/entities/${entity.id}/versions` : `/api/projects/${ctx.project.id}/entities`, payload);
      modal.close(); toast("实体草稿已保存，等待管理员审核"); ctx.refresh();
    } catch (error) { formError(form, error); }
  });
}

function reviewDialog(ctx, entity) {
  const reason = textarea("", { required: true, placeholder: "记录官网、公司、品类或排除语境依据" });
  const role = select([{ value: "competitor", label: "确认为竞品" }, { value: "primary", label: "确认为主品牌" }], entity.role === "primary" ? "primary" : "competitor");
  const decision = select([{ value: "confirmed", label: "确认实体与角色" }, { value: "rejected", label: "排除此版本" }], "confirmed");
  const form = h("form", {}, h("p", {}, `${entity.name} · 当前角色 ${label(entity.role)} · v${entity.version}`),
    field("审核决定", decision), field("确认后的角色", role, "候选实体不能直接计入正式竞品指标"), field("消歧依据", reason),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "保存审核决定")));
  const modal = drawer("管理员实体审核", form);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api.post(`/api/projects/${ctx.project.id}/entities/${entity.id}/review`, { decision: decision.value, role: decision.value === "confirmed" ? role.value : null, reason: reason.value }); modal.close(); toast("实体审核已留痕"); ctx.refresh(); }
    catch (error) { formError(form, error); }
  });
}

function entityDetail(entity) {
  const card = entity.entity_card || {};
  drawer(`实体卡 · ${entity.name}`, h("div", {}, h("dl", { class: "definition-list" },
    h("div", {}, h("dt", {}, "角色"), h("dd", {}, label(entity.role))), h("div", {}, h("dt", {}, "版本"), h("dd", {}, `v${entity.version}`)),
    h("div", {}, h("dt", {}, "公司"), h("dd", {}, card.company || "—")), h("div", {}, h("dt", {}, "官网"), h("dd", {}, card.domain || "—"))),
    h("h3", {}, "别名"), h("p", {}, (card.aliases || []).join("、") || "无"),
    h("h3", {}, "排除语境"), h("p", {}, (card.exclude_contexts || []).join("、") || "未配置"),
    h("h3", {}, "审核记录"), h("p", {}, entity.review_reason || "尚未审核"),
    entity.status === "candidate" || entity.role === "candidate" ? h("div", { class: "inline-panel warning-panel" }, h("h3", {}, "开放候选不会自动计入指标"), h("p", {}, card.evidence || "无证据")) : null));
}

function poolDiff(ctx, items) {
  const options = items.map((entity) => ({ value: entity.id, label: `${entity.name} · v${entity.version}` }));
  const before = h("select", { multiple: true, size: 6 }, options.map((item) => h("option", { value: item.value }, item.label)));
  const after = h("select", { multiple: true, size: 6 }, options.map((item) => h("option", { value: item.value }, item.label)));
  const output = h("div", {});
  const ids = (control) => [...control.selectedOptions].map((option) => option.value).join(",");
  const form = h("form", {}, h("p", { class: "muted" }, "按住 Command / Ctrl 可多选。通常从两个 wave 的冻结 entity_ids 选择。"),
    h("div", { class: "form-grid" }, field("基线实体池", before), field("当前实体池", after)),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "比较实体池")), output);
  drawer("竞品池版本 diff", form, { wide: true });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { const diff = await api.get(`/api/projects/${ctx.project.id}/entities/pool-diff?before=${ids(before)}&after=${ids(after)}`);
      clear(output); output.append(h("h3", {}, `新增 ${diff.added.length} · 移除 ${diff.removed.length}`), dataTable(["变化", "实体"], [...diff.added.map((item) => ["新增", item.name]), ...diff.removed.map((item) => ["移除", item.name])]));
    } catch (error) { formError(form, error); }
  });
}
