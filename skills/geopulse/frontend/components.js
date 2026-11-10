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
    else node.setAttribute(key, value === true && !key.startsWith("aria-") ? "" : String(value));
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
export const pct = (value) => value === undefined || value === null || value === "" || !Number.isFinite(Number(value))
  ? "—" : `${Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 1)}%`;

export const labels = {
  draft: "草稿", reviewing: "审核中", frozen: "已冻结", retired: "已退役",
  planned: "待执行", queued: "排队中", running: "执行中", judging: "判定中", awaiting_collection: "待人工采集",
  collecting: "采集中", review_pending: "待提交复核", recollect_required: "需要重采", completed: "已完成",
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
  active: "启用", inactive: "停用", open: "待处理", acknowledged: "已知悉", resolved: "已恢复",
  blocked: "已阻塞", paused: "已暂停", healthy: "正常", unhealthy: "异常", unknown_health: "未检查",
  info: "提示", warning: "警告", critical: "严重", error: "错误", demo: "演示", answer: "回答", judge: "Judge",
  health: "健康检查", operation: "调用", daily: "每日", once: "单次", recurring: "周期", enabled: "已启用", disabled: "已停用",
  brand: "品牌词", scene: "场景词", compare: "对比词", choice: "选购词", discovery: "发现型", navigation: "导航型",
  client_confirmed: "客户已确认适用", eligible: "内部确认适用", not_eligible: "不适用",
  "human-arbitrated": "管理员仲裁", "human-review": "人工修订", "demo-rules": "演示规则",
  evidence_linked: "已链接证据", pending_measurement: "待测量", measured: "已有测量",
  insufficient_evidence: "证据不足", incomparable: "不可比", legacy_unavailable: "历史证据不可用",
  legacy: "历史记录", superseded: "已被新版本替代", not_attributable: "暂无法归因", improved: "观察到改善", not_improved: "未观察到改善",
  owned_site: "客户官网", owned: "自有渠道", partner: "合作渠道", paid: "付费渠道", earned: "自然获得", unknown: "未知",
  fact_page: "事实页", faq: "FAQ", comparison: "对比内容", documentation: "文档",
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
    h("tbody", {}, rows.map((cells) => h("tr", {}, cells.map((cell, index) => h("td", {
      class: index === 0 ? "wrap-cell" : "", "data-label": typeof headers[index] === "string" ? headers[index] : `第 ${index + 1} 列`,
    }, cell)))))));
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
  const hasRatio = metricData && metricData.value !== null && metricData.value !== undefined;
  const rawValues = [metricData?.value, metricData?.ci_low, metricData?.ci_high];
  const values = rawValues.map(Number);
  const hasInterval = Boolean(metricData && Number(metricData.n) > 0
    && rawValues.every((value) => value !== null && value !== undefined && value !== "") && values.every(Number.isFinite)
    && values[1] >= 0 && values[2] <= 100 && values[1] <= values[2] && values[0] >= 0 && values[0] <= 100);
  const track = hasInterval ? h("div", {
    class: "wilson-track", "aria-hidden": "true",
    style: `--interval-start:${values[1]}%;--interval-width:${Math.max(values[2] - values[1], .35)}%;--point:${values[0]}%`,
  }, h("span", { class: "wilson-interval" }), h("span", { class: "wilson-point" })) : null;
  const count = metricData ? `${metricData.hits ?? "—"}/${metricData.n ?? "—"}` : "";
  return h("div", { class: `metric-block${limited ? " limited" : ""}` },
    h("span", { class: "metric-label" }, labelText),
    h("strong", { class: "metric-value num" }, limited ? count : hasRatio ? pct(metricData.value) : "—"),
    track,
    metricData ? h("small", { class: "metric-evidence" },
      h("span", { class: "num" }, limited ? `点估计 ${pct(metricData.value)}` : `${count} 个有效样本`),
      h("span", { class: "metric-range-text num" }, `Wilson ${pct(metricData.ci_low)}–${pct(metricData.ci_high)}`),
      limited ? h("span", { class: "limited-note" }, "小样本仅看方向") : null)
      : h("small", { class: "metric-evidence" }, options.empty || "尚无有效样本"));
}

export function field(labelText, control, help = "", full = false) {
  const id = control.id || `field-${Math.random().toString(36).slice(2, 9)}`;
  control.id = id;
  const helpId = help ? `${id}-help` : "";
  if (helpId) control.setAttribute("aria-describedby", [control.getAttribute("aria-describedby"), helpId].filter(Boolean).join(" "));
  return h("div", { class: `field${full ? " full" : ""}` }, h("label", { for: id }, labelText), control,
    help ? h("small", { id: helpId }, help) : null);
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
  const helpId = help ? `${control.id}-help` : "";
  if (helpId) control.setAttribute("aria-describedby", [control.getAttribute("aria-describedby"), helpId].filter(Boolean).join(" "));
  return { control, node: h("div", { class: "check-field" }, control, h("label", { for: control.id }, labelText, help ? h("small", { id: helpId }, help) : null)) };
}

let toastTimer;
export function dismissToast() {
  const node = document.getElementById("toast");
  clearTimeout(toastTimer);
  node.className = "toast";
  node.replaceChildren();
}
export function toast(message, isError = false) {
  const node = document.getElementById("toast");
  dismissToast();
  const close = h("button", { class: "toast-close", type: "button", "aria-label": "关闭提示", onClick: dismissToast }, "×");
  node.append(h("span", { class: "toast-message" }, message));
  if (isError) node.append(close);
  node.className = `toast show${isError ? " error" : ""}`;
  node.setAttribute("role", isError ? "alert" : "status");
  node.setAttribute("aria-live", isError ? "assertive" : "polite");
  const pause = () => clearTimeout(toastTimer);
  const resume = () => {
    clearTimeout(toastTimer);
    toastTimer = setTimeout(dismissToast, isError ? 6500 : 3500);
  };
  node.onpointerenter = pause;
  node.onpointerleave = resume;
  node.onfocusin = pause;
  node.onfocusout = resume;
  resume();
}

export function loadingSkeleton() {
  return h("div", { class: "page-skeleton", role: "status", "aria-label": "正在读取项目数据" },
    h("div", { class: "skeleton-heading" }, h("span"), h("span")),
    h("div", { class: "skeleton-summary" }),
    h("div", { class: "skeleton-grid" }, h("span"), h("span"), h("span"), h("span")),
    h("div", { class: "skeleton-table" }, h("span"), h("span"), h("span")),
    h("span", { class: "sr-only" }, "正在读取项目数据…"));
}

const drawerStack = [];
export function closeAllDrawers() {
  [...drawerStack].reverse().forEach((entry) => entry.close({ restoreFocus: false, notify: false }));
}
export function drawer(title, content, options = {}) {
  dismissToast();
  const root = document.getElementById("drawer-root");
  const previousFocus = document.activeElement;
  const background = document.getElementById("app-shell")?.hidden ? document.getElementById("login-view") : document.getElementById("app-shell");
  const previousBackdrop = drawerStack.at(-1)?.backdrop;
  if (previousBackdrop) previousBackdrop.inert = true;
  let closed = false;
  const close = ({ restoreFocus = true, notify = true } = {}) => {
    if (closed) return;
    closed = true;
    const index = drawerStack.findIndex((entry) => entry.backdrop === backdrop);
    if (index >= 0) drawerStack.splice(index, 1);
    backdrop.remove();
    if (previousBackdrop) previousBackdrop.inert = false;
    if (!drawerStack.length) {
      document.body.style.overflow = "";
      if (background) background.inert = false;
    }
    document.removeEventListener("keydown", onKeydown);
    if (restoreFocus && previousFocus?.isConnected) previousFocus.focus();
    if (notify) options.onClose?.();
  };
  const body = h("div", { class: "drawer-body" }, content);
  const titleId = `drawer-title-${Math.random().toString(36).slice(2, 9)}`;
  const dialog = h("section", { class: `drawer${options.wide ? " wide-drawer" : ""}`, role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, tabindex: -1 },
    h("div", { class: "drawer-head" }, h("h2", { id: titleId }, title), h("button", { class: "drawer-close", "aria-label": "关闭对话框", onClick: () => close() }, "×")), body);
  const backdrop = h("div", { class: "drawer-backdrop", onClick: (event) => { if (event.target === backdrop && options.dismissible !== false) close(); } }, dialog);
  const focus = () => {
    const control = [...body.querySelectorAll("input:not([type=hidden]):not(:disabled),select:not(:disabled),textarea:not(:disabled)")]
      .find((node) => !node.closest("[hidden],[inert]") && node.getClientRects().length);
    (control || dialog.querySelector(".drawer-close") || dialog).focus({ preventScroll: true });
  };
  const onKeydown = (event) => {
    if (drawerStack.at(-1)?.backdrop !== backdrop) return;
    if (event.key === "Escape" && options.dismissible !== false) { event.preventDefault(); close(); return; }
    if (event.key === "Tab") {
      const focusable = [...dialog.querySelectorAll("button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex='0']")]
        .filter((node) => !node.closest("[hidden],[inert]"));
      if (!focusable.length) { event.preventDefault(); dialog.focus(); return; }
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    }
  };
  drawerStack.push({ backdrop, close });
  document.addEventListener("keydown", onKeydown);
  document.body.style.overflow = "hidden";
  if (background) background.inert = true;
  root.append(backdrop);
  requestAnimationFrame(() => {
    if (!closed && drawerStack.at(-1)?.backdrop === backdrop && !dialog.contains(document.activeElement)) focus();
  });
  return { body, close, dialog, focus };
}

export function onSubmit(form, handler) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (form.getAttribute("aria-busy") === "true") return;
    const submit = event.submitter || form.querySelector("button[type=submit],button:not([type])");
    form.setAttribute("aria-busy", "true");
    if (submit) submit.disabled = true;
    try {
      await handler(event);
    } catch (error) {
      if (form.isConnected) formError(form, error);
    } finally {
      if (form.isConnected) {
        form.setAttribute("aria-busy", "false");
        if (submit) submit.disabled = false;
      }
    }
  });
}

export function confirmDialog(title, description, confirmLabel, onConfirm, dangerous = false) {
  const error = h("div", { class: "form-error", hidden: true });
  const modal = drawer(title, h("form", {}, h("p", {}, description), error,
    h("div", { class: "form-actions" }, h("button", { type: "button", class: "button secondary", onClick: () => modal.close() }, "取消"),
      h("button", { type: "submit", class: `button${dangerous ? " danger" : ""}` }, confirmLabel))));
  onSubmit(modal.body.querySelector("form"), async () => {
    error.hidden = true;
    await onConfirm();
    modal.close();
  });
  return modal;
}

export function formError(form, error) {
  let node = form.querySelector(".form-error");
  if (!node) { node = h("div", { class: "form-error", role: "alert" }); form.prepend(node); }
  node.setAttribute("role", "alert");
  node.tabIndex = -1;
  node.textContent = error?.detail?.errors?.join?.("\n") || error.message || String(error);
  node.hidden = false;
  requestAnimationFrame(() => {
    if (!node.isConnected) return;
    node.focus({ preventScroll: true });
    node.scrollIntoView({ block: "nearest" });
  });
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

let pendingTabFocus = "";
export function tabs(items, current, onChange) {
  const group = `tabs-${`${location.hash.split("?")[0]}-${items.map((item) => item.value).join("-")}`.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const selected = items.some((item) => item.value === current) ? current : items[0]?.value;
  const list = h("div", { class: "tabs", role: "tablist", "aria-label": "当前页面任务" }, items.map((item, index) => {
    const active = item.value === selected;
    const button = h("button", {
      id: `${group}-${index}`, role: "tab", type: "button", "aria-selected": active,
      "aria-controls": `${group}-panel`, tabindex: active ? 0 : -1,
      onClick: () => { pendingTabFocus = `${group}-${index}`; onChange(item.value); },
      onKeydown: (event) => {
        const keys = { ArrowRight: 1, ArrowLeft: -1 };
        let next;
        if (event.key in keys) next = (index + keys[event.key] + items.length) % items.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = items.length - 1;
        else return;
        event.preventDefault();
        pendingTabFocus = `${group}-${next}`;
        onChange(items[next].value);
      },
    }, item.label);
    return button;
  }));
  list.dataset.panelId = `${group}-panel`;
  list.dataset.tabPrefix = group;
  if (pendingTabFocus.startsWith(`${group}-`)) {
    const target = pendingTabFocus;
    pendingTabFocus = "";
    requestAnimationFrame(() => document.getElementById(target)?.focus());
  }
  return list;
}

export function tabPanel(tablist, content) {
  const active = tablist.querySelector("[aria-selected=true]");
  return h("div", {
    id: tablist.dataset.panelId, class: "tab-panel", role: "tabpanel", tabindex: 0,
    "aria-labelledby": active?.id,
  }, content);
}

export function budgetConfirmationDialog(error, retry) {
  const detail = error.detail || {};
  const reason = textarea("", { required: true, minlength: 4, rows: 4, placeholder: "说明本次超限仍需执行的业务原因" });
  const form = h("form", {},
    h("div", { class: "inline-panel warning-panel" }, h("h3", {}, "本次执行需要管理员确认"),
      h("p", {}, detail.message || error.message),
      detail.estimate?.max_estimated_cost !== undefined ? h("p", {}, `含安全重试的费用预估：${detail.estimate.max_estimated_cost} ${detail.estimate.currency || ""}`) : null),
    field("超限执行理由", reason, "理由会与本次预算预留一起写入审计，不会修改预算额度"),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "确认超限并继续")));
  const modal = drawer("预算超限确认", form);
  onSubmit(form, async () => { await retry(reason.value); modal.close(); });
  return modal;
}

function budgetBlockedDialog(error) {
  const detail = error.detail || {};
  const content = h("div", {},
    h("div", { class: "inline-panel danger-panel" }, h("h3", {}, "本次执行未创建"),
      h("p", {}, detail.message || error.message),
      (detail.unknown_reasons || []).length ? h("ul", {}, detail.unknown_reasons.map((reason) => h("li", {}, reason))) : null),
    (detail.limits || []).length ? dataTable(["范围", "额度", "已用 + 在途", "本次后预估"], detail.limits.map((limit) => [limit.label, `${limit.limit} ${detail.currency}`, `${limit.used} ${detail.currency}`, limit.projected === null ? "成本未知" : `${limit.projected} ${detail.currency}`])) : null,
    h("p", { class: "muted" }, detail.code === "budget_cost_unknown" ? "请先补齐实际使用的价格与币种；未知成本不会按零元放行。也可由管理员调整硬限额策略。" : "请由管理员提高额度或调整执行范围。硬限额只在执行前保护，不承诺在途调用绝不超额。"),
    h("div", { class: "form-actions" },
      h("button", { class: "button secondary", onClick: () => { modal.close(); location.hash = "#/admin?tab=engines"; } }, "检查引擎价格"),
      h("button", { class: "button", onClick: () => { modal.close(); location.hash = "#/admin?tab=governance"; } }, "前往预算设置")));
  const modal = drawer("预算阻止了本次执行", content, { wide: true });
}

export function handleBudgetError(error, retry) {
  if (error?.detail?.code === "budget_confirmation_required") {
    setTimeout(() => budgetConfirmationDialog(error, retry), 0);
    return true;
  }
  if (["budget_exceeded", "budget_cost_unknown"].includes(error?.detail?.code)) {
    setTimeout(() => budgetBlockedDialog(error), 0);
    return true;
  }
  return false;
}

export function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = h("a", { href: url, download: filename });
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function nextFrame() { return new Promise((resolve) => requestAnimationFrame(resolve)); }
