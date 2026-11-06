export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || (value === false && !key.startsWith("aria-"))) return;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "for") node.htmlFor = value;
    else if (key === "value") node.value = value;
    else if (key === "checked" || key === "selected" || key === "disabled" || key === "hidden" || key === "required" || key === "multiple" || key === "readonly") node[key] = Boolean(value);
    else if (key === "colspan") node.colSpan = value;
    else node.setAttribute(key, value === true ? "" : String(value));
  });
  const append = (child) => {
    if (child === undefined || child === null || child === false) return;
    if (Array.isArray(child)) return child.forEach(append);
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  };
  children.forEach(append);
  return node;
}

export const clear = (node) => node.replaceChildren();
export const text = (value, fallback = "—") => value === undefined || value === null || value === "" ? fallback : String(value);
export const pct = (value) => `${Number(value || 0).toFixed(Number.isInteger(Number(value)) ? 0 : 1)}%`;

export const labels = {
  draft: "草稿", reviewing: "审核中", frozen: "已冻结", retired: "已退役",
  planned: "待执行", queued: "排队中", running: "执行中", judging: "判定中",
  done: "已完成", partial: "部分完成", failed: "失败", cancelled: "已取消", succeeded: "成功",
  data_ready: "数据就绪", data_ready_with_warnings: "数据有警告", analyzed: "已分析", closed: "已关闭",
  candidate: "待确认候选", eligibility_pending: "适用性审核中", confirmed: "已确认", rejected: "已排除",
  actioned: "已生成行动", remeasured: "已复测", review: "待审核", approved: "已批准",
  published: "已发布", remeasure_due: "待复测", verified: "已验证", not_effective: "未见改善", stopped: "已停止",
  data_checked: "数据已核验", strategy_reviewed: "策略已复核", client_approved: "客户版已批准", sent: "已登记发送",
  pending_review: "待审核", machine: "机器判定", pending: "待复核", unknown: "未知", ambiguous: "实体歧义",
  wrong_entity: "非目标实体", absent: "未提及", mentioned: "仅提及", described: "有描述", recommended: "有推荐",
  positive: "正向", neutral: "中性", negative: "负向", primary: "主品牌", competitor: "竞品",
  admin: "管理员", analyst: "分析师", reviewer: "客户审核者", viewer: "只读查看者",
  memory: "记忆态", search: "检索态", provider_api: "Provider API", consumer_web: "消费网页端", consumer_app: "消费 App",
};
export const label = (value) => labels[value] || text(value);
export function badge(value, tone) {
  const inferred = tone || (["done", "succeeded", "confirmed", "frozen", "published", "client_approved", "verified"].includes(value) ? "success"
    : ["failed", "rejected", "negative", "wrong_entity"].includes(value) ? "danger"
    : ["partial", "pending", "pending_review", "candidate", "eligibility_pending", "reviewing", "running", "queued", "data_ready_with_warnings", "remeasure_due"].includes(value) ? "warning"
    : ["search", "recommended", "data_checked", "strategy_reviewed"].includes(value) ? "info" : "neutral");
  return h("span", { class: `badge ${inferred}` }, label(value));
}

export function pageHead(title, description, actions = []) {
  return h("div", { class: "page-head" }, h("div", {}, h("h1", {}, title), h("p", {}, description)),
    h("div", { class: "page-actions" }, actions));
}

export function section(title, description, body, actions = []) {
  return h("section", { class: "work-section" }, h("div", { class: "section-head" },
    h("div", {}, h("h2", {}, title), description ? h("p", {}, description) : null),
    h("div", { class: "button-group" }, actions)), h("div", { class: "section-body flush" }, body));
}

export function dataTable(headers, rows, empty = "当前没有记录") {
  if (!rows.length) return h("div", { class: "empty-state" }, h("p", {}, empty));
  return h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, headers.map((head) => h("th", { scope: "col" }, head)))),
    h("tbody", {}, rows.map((cells) => h("tr", {}, cells.map((cell, index) => h("td", { class: index === 0 ? "wrap-cell" : "" }, cell)))))));
}

export function emptyState(title, description, action) {
  return h("div", { class: "empty-state" }, h("h3", {}, title), h("p", {}, description), action || null);
}

export function errorState(error, retry) {
  return h("div", { class: "error-state", role: "alert" }, h("h2", {}, error.status === 403 ? "当前角色没有此权限" : "暂时无法读取"),
    h("p", {}, error.message || String(error)), retry ? h("button", { class: "button secondary", onClick: retry }, "重新读取") : null);
}

export function metric(labelText, metricData, options = {}) {
  const limited = metricData?.limited;
  return h("div", { class: `metric-block${limited ? " limited" : ""}` },
    h("span", { class: "metric-label" }, labelText),
    h("strong", { class: "metric-value num" }, metricData ? pct(metricData.value) : "—"),
    h("small", {}, metricData ? `${metricData.hits}/${metricData.n} · Wilson ${metricData.ci_low}–${metricData.ci_high}%${limited ? " · 小样本" : ""}` : options.empty || "尚无有效样本"));
}

export function field(labelText, control, help = "", full = false) {
  const id = control.id || `field-${Math.random().toString(36).slice(2, 9)}`;
  control.id = id;
  return h("div", { class: `field${full ? " full" : ""}` }, h("label", { for: id }, labelText), control,
    help ? h("small", {}, help) : null);
}

export function select(options, value = "", attrs = {}) {
  const control = h("select", attrs);
  options.forEach((item) => {
    const option = typeof item === "object" ? item : { value: item, label };
    control.append(h("option", { value: option.value, selected: String(option.value) === String(value), disabled: option.disabled }, option.label));
  });
  return control;
}

export function input(value = "", attrs = {}) { return h("input", { value, ...attrs }); }
export function textarea(value = "", attrs = {}) { return h("textarea", attrs, value); }
export function checkbox(labelText, checked = false, help = "", attrs = {}) {
  const control = h("input", { type: "checkbox", checked, ...attrs });
  control.id = control.id || `field-${Math.random().toString(36).slice(2, 9)}`;
  return { control, node: h("div", { class: "check-field" }, control, h("label", { for: control.id }, labelText, help ? h("small", {}, help) : null)) };
}

let toastTimer;
export function toast(message, isError = false) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.className = "toast"; }, isError ? 6500 : 3500);
}

export function drawer(title, content, options = {}) {
  const root = document.getElementById("drawer-root");
  const previousFocus = document.activeElement;
  const close = () => {
    backdrop.remove();
    document.body.style.overflow = "";
    document.removeEventListener("keydown", onKeydown);
    if (previousFocus?.isConnected) previousFocus.focus();
    options.onClose?.();
  };
  const body = h("div", { class: "drawer-body" }, content);
  const dialog = h("section", { class: `drawer${options.wide ? " wide-drawer" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "drawer-head" }, h("h2", {}, title), h("button", { class: "drawer-close", "aria-label": "关闭", onClick: close }, "×")), body);
  const backdrop = h("div", { class: "drawer-backdrop", onClick: (event) => { if (event.target === backdrop && options.dismissible !== false) close(); } }, dialog);
  const onKeydown = (event) => {
    if (event.key === "Escape" && options.dismissible !== false) close();
    if (event.key === "Tab") {
      const focusable = [...dialog.querySelectorAll("button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex='0']")];
      if (!focusable.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  };
  document.addEventListener("keydown", onKeydown);
  document.body.style.overflow = "hidden";
  root.append(backdrop);
  requestAnimationFrame(() => dialog.querySelector("input,select,textarea,button")?.focus());
  return { body, close, dialog };
}

export function confirmDialog(title, description, confirmLabel, onConfirm, dangerous = false) {
  const error = h("div", { class: "form-error", hidden: true });
  const modal = drawer(title, h("form", {}, h("p", {}, description), error,
    h("div", { class: "form-actions" }, h("button", { type: "button", class: "button secondary", onClick: () => modal.close() }, "取消"),
      h("button", { type: "submit", class: `button${dangerous ? " danger" : ""}` }, confirmLabel))));
  modal.body.querySelector("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = event.target.querySelector("button[type=submit]");
    submit.disabled = true;
    error.hidden = true;
    try { await onConfirm(); modal.close(); }
    catch (caught) { error.textContent = caught.message; error.hidden = false; submit.disabled = false; }
  });
  return modal;
}

export function formError(form, error) {
  let node = form.querySelector(".form-error");
  if (!node) { node = h("div", { class: "form-error", role: "alert" }); form.prepend(node); }
  node.textContent = error?.detail?.errors?.join?.("\n") || error.message || String(error);
  node.hidden = false;
}

export function formatDate(value, timezone = "Asia/Shanghai") {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

export function safeLink(url, title) {
  try {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol)) return document.createTextNode(title || url);
    return h("a", { href: parsed.href, target: "_blank", rel: "noopener noreferrer" }, title || parsed.hostname);
  } catch { return document.createTextNode(title || url || "—"); }
}

export function tabs(items, current, onChange) {
  return h("div", { class: "tabs", role: "tablist" }, items.map((item) => h("button", {
    role: "tab", "aria-selected": item.value === current, onClick: () => onChange(item.value),
  }, item.label)));
}

export function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = h("a", { href: url, download: filename });
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function nextFrame() { return new Promise((resolve) => requestAnimationFrame(resolve)); }
