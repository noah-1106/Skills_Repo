import { api, setCsrf } from "./api.js";
import { h, clear, pageHead, field, input, select, toast, formError, label } from "./components.js";
import { renderOverview } from "./views/overview.js";
import { renderPrompts } from "./views/prompts.js";
import { renderEntities } from "./views/entities.js";
import { renderMeasure } from "./views/measure.js";
import { renderReview } from "./views/review.js";
import { renderOpportunities } from "./views/opportunities.js";
import { renderReports } from "./views/reports.js";
import { renderAdmin } from "./views/admin.js";

const routes = [
  ["overview", "项目总览", renderOverview], ["prompts", "问题集", renderPrompts],
  ["entities", "品牌实体", renderEntities], ["measure", "测量执行", renderMeasure],
  ["review", "证据复核", renderReview], ["opportunities", "机会与行动", renderOpportunities],
  ["reports", "对比与报告", renderReports], ["admin", "系统管理", renderAdmin],
];
const state = { user: null, projects: [], project: null, role: "viewer", renderId: 0, cleanups: [] };
const workspace = document.getElementById("workspace");

function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, "") || "overview";
  const [name, search = ""] = raw.split("?");
  return { name: routes.some(([route]) => route === name) ? name : "overview", params: new URLSearchParams(search) };
}

export function navigate(name, params = {}) {
  const search = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ""));
  location.hash = `#/${name}${search.toString() ? `?${search}` : ""}`;
}

function renderNav(active) {
  const nav = document.getElementById("main-nav");
  clear(nav);
  routes.forEach(([name, title]) => nav.append(h("a", { href: `#/${name}`, class: name === active ? "active" : "", "aria-current": name === active ? "page" : null }, title)));
}

function setProtocol(data = {}) {
  const band = document.getElementById("protocol-band");
  clear(band);
  band.append(h("strong", {}, "当前口径"));
  const items = [
    ["项目", state.project?.name], ["问题集", data.promptSet], ["实体版本", data.entityVersion ? String(data.entityVersion).slice(0, 10) : ""],
    ["引擎", data.engines], ["模式", data.mode ? label(data.mode) : ""], ["目标", data.target ? label(data.target) : ""],
    ["轮次", data.repeats ? `${data.repeats} 轮` : ""], ["有效样本", data.n !== undefined ? `n=${data.n}` : ""],
    ["数据", data.demo ? "演示数据" : data.real ? "真实 API 数据" : ""],
  ].filter(([, value]) => value);
  if (items.length <= 1) band.append(h("span", { class: "protocol-empty" }, "选择 wave 后显示冻结口径；不同 wave 不会混合计算"));
  items.slice(1).forEach(([name, value]) => band.append(h("span", { class: "protocol-item" }, `${name} ${value}`)));
}

function cleanup() {
  state.cleanups.forEach((fn) => { try { fn(); } catch { /* view already gone */ } });
  state.cleanups = [];
}

async function renderRoute() {
  if (!state.project) return;
  cleanup();
  const { name, params } = parseRoute();
  const route = routes.find(([routeName]) => routeName === name);
  renderNav(name);
  document.title = `${route[1]} · ${state.project.name} · GeoPulse`;
  const renderId = ++state.renderId;
  clear(workspace);
  workspace.append(h("div", { class: "page-loading", role: "status" }, "正在读取项目数据…"));
  setProtocol();
  try {
    await route[2](workspace, {
      project: state.project, role: state.role, user: state.user, params, navigate, setProtocol,
      onCleanup: (fn) => state.cleanups.push(fn),
      refresh: () => { if (renderId === state.renderId) renderRoute(); },
      isCurrent: () => renderId === state.renderId,
    });
    if (renderId === state.renderId) workspace.focus({ preventScroll: true });
  } catch (error) {
    if (renderId !== state.renderId) return;
    clear(workspace);
    workspace.append(pageHead(route[1], "当前页面没有完成加载。"), h("div", { class: "error-state", role: "alert" },
      h("h2", {}, error.status === 403 ? "没有访问权限" : "页面读取失败"), h("p", {}, error.message),
      h("button", { class: "button secondary", onClick: renderRoute }, "重试")));
  }
}

function renderProjectSwitcher() {
  const root = document.getElementById("project-switcher");
  clear(root);
  const control = select(state.projects.map((project) => ({ value: project.id, label: `${project.client_name} / ${project.name}` })), state.project?.id, { "aria-label": "切换客户项目" });
  control.addEventListener("change", () => {
    localStorage.setItem("geopulse-project", control.value);
    state.project = state.projects.find((project) => String(project.id) === control.value);
    state.role = state.project.member_role;
    renderProjectSwitcher();
    document.getElementById("role-label").textContent = label(state.role);
    renderRoute();
  });
  root.append(h("label", {}, "客户项目"), control);
  if (state.user?.global_role === "admin") root.append(h("button", { class: "text-button", onClick: createProjectDialog }, "新建项目"));
  document.getElementById("role-label").textContent = label(state.role);
}

function createProjectDialog() {
  const client = input("", { required: true, placeholder: "客户或公司名" });
  const name = input("", { required: true, placeholder: "例如：2026 品牌 GEO 监测" });
  const category = input("", { placeholder: "例如：企业软件" });
  const form = h("form", {}, field("客户名称", client), field("项目名称", name), field("业务品类", category),
    h("div", { class: "form-actions" }, h("button", { class: "button", type: "submit" }, "创建项目")));
  import("./components.js").then(({ drawer }) => {
    const modal = drawer("新建客户项目", form);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const project = await api.post("/api/projects", { client_name: client.value, name: name.value, category: category.value });
        modal.close(); toast("项目已创建"); await loadProjects(project.id); renderProjectSwitcher(); navigate("entities");
      } catch (error) { formError(form, error); }
    });
  });
}

async function loadProjects(preferredId) {
  state.projects = (await api.get("/api/projects")).items;
  const saved = preferredId || localStorage.getItem("geopulse-project");
  state.project = state.projects.find((project) => String(project.id) === String(saved)) || state.projects[0] || null;
  state.role = state.project?.member_role || "viewer";
}

function renderLogin(message = "") {
  cleanup();
  closeNavigation();
  document.getElementById("app-shell").hidden = true;
  const view = document.getElementById("login-view");
  view.hidden = false; clear(view);
  const email = input("", { type: "email", autocomplete: "username", required: true, placeholder: "name@company.com" });
  const password = input("", { type: "password", autocomplete: "current-password", required: true });
  const form = h("form", { class: "login-form" }, h("h2", {}, "登录交付工作台"), h("p", { class: "muted" }, "使用当前部署环境中的账号继续。"),
    message ? h("div", { class: "form-error" }, message) : null,
    field("邮箱", email), field("密码", password), h("button", { class: "button", type: "submit" }, "登录"));
  view.append(h("div", { class: "login-intro" }, h("div", {}, h("div", { class: "brand-mark" }, h("span", { class: "brand-symbol" }, "G"), h("strong", {}, "GeoPulse")),
    h("h1", {}, "让每一次 GEO 结论，都能回到证据。"), h("p", {}, "面向客户交付的测量、复核、行动与报告工作流。")),
    h("div", { class: "login-principles" }, h("span", {}, "冻结口径，再比较变化"), h("span", {}, "失败样本不等于零提及"), h("span", {}, "自动发现必须经管理员确认"))),
    h("div", { class: "login-form-wrap" }, form));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("button[type=submit]"); submit.disabled = true;
    try {
      const result = await api.post("/api/auth/login", { email: email.value, password: password.value });
      setCsrf(result.csrf_token); state.user = result.user;
      await startApp();
    } catch (error) { formError(form, error); submit.disabled = false; }
  });
}

async function startApp() {
  await loadProjects();
  if (!state.project) { renderLogin("当前账号尚未分配项目，请联系管理员。"); return; }
  document.getElementById("login-view").hidden = true;
  document.getElementById("app-shell").hidden = false;
  renderProjectSwitcher();
  if (!location.hash) navigate("overview"); else await renderRoute();
}

document.getElementById("logout-button").addEventListener("click", async () => {
  try { await api.post("/api/auth/logout", {}); } finally { setCsrf(""); state.user = null; location.hash = ""; renderLogin(); }
});
const mobileNavigation = window.matchMedia("(max-width: 760px)");

function closeNavigation(restoreFocus = false) {
  const sidebar = document.getElementById("sidebar");
  sidebar.classList.remove("open");
  document.getElementById("nav-backdrop").hidden = true;
  document.getElementById("menu-button").setAttribute("aria-expanded", "false");
  document.querySelector(".shell-main").inert = false;
  if (restoreFocus && mobileNavigation.matches) document.getElementById("menu-button").focus();
}

document.getElementById("menu-button").addEventListener("click", () => {
  const sidebar = document.getElementById("sidebar");
  if (sidebar.classList.contains("open")) { closeNavigation(true); return; }
  sidebar.classList.add("open");
  document.getElementById("nav-backdrop").hidden = false;
  document.getElementById("menu-button").setAttribute("aria-expanded", "true");
  document.querySelector(".shell-main").inert = true;
  document.querySelector("#main-nav a")?.focus();
});
document.getElementById("nav-backdrop").addEventListener("click", () => closeNavigation(true));
document.getElementById("main-nav").addEventListener("click", () => closeNavigation());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.getElementById("sidebar").classList.contains("open")) closeNavigation(true);
});
mobileNavigation.addEventListener("change", () => closeNavigation());
window.addEventListener("hashchange", renderRoute);
window.addEventListener("geopulse:unauthorized", () => { if (state.user) { state.user = null; setCsrf(""); renderLogin("登录已过期，请重新登录。"); } });

(async function bootstrap() {
  try {
    const me = await api.get("/api/auth/me");
    state.user = me.user; setCsrf(me.csrf_token); await startApp();
  } catch (error) {
    if (error.status !== 401) renderLogin("无法连接服务，请确认后端已启动。登录服务恢复后再试。");
    else renderLogin();
  }
})();
