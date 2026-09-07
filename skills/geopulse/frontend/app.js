/* GeoPulse 前端逻辑：vanilla JS，零构建。 */
"use strict";
const $ = (s) => document.querySelector(s);
const api = {
  async get(url) { const r = await fetch(url); if (!r.ok) throw new Error((await r.json()).detail || r.status); return r.json(); },
  async send(url, method, body) {
    const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    if (!r.ok) throw new Error((await r.json()).detail || r.status);
    return r.json();
  },
};

/* ---------- tabs ---------- */
document.querySelectorAll("nav button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("nav button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    ["dash", "prompts", "brands"].forEach((t) => {
      $(`#tab-${t}`).style.display = t === b.dataset.tab ? "" : "none";
    });
    if (b.dataset.tab === "prompts") loadPrompts();
    if (b.dataset.tab === "brands") loadBrands();
  };
});

/* ---------- charts ---------- */
const trendChart = echarts.init(document.getElementById("trend"));
const sovChart = echarts.init(document.getElementById("sov"));
window.addEventListener("resize", () => { trendChart.resize(); sovChart.resize(); });

function renderTrend(trend) {
  trendChart.setOption({
    backgroundColor: "transparent",
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: trend.map((t) => t.day), axisLabel: { color: "#8b92a5" }, axisLine: { lineStyle: { color: "#262b38" } } },
    yAxis: { type: "value", max: 100, axisLabel: { color: "#8b92a5" }, splitLine: { lineStyle: { color: "#1c2029" } } },
    series: [{ type: "line", data: trend.map((t) => t.visibility), smooth: true,
      areaStyle: { color: "rgba(91,140,255,.15)" }, lineStyle: { color: "#5b8cff" },
      itemStyle: { color: "#5b8cff" }, symbolSize: 6 }],
  });
}

function renderSov(comps) {
  const top = comps.slice(0, 8);
  sovChart.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "item", formatter: "{b}: {c} 次提及 ({d}%)" },
    series: [{ type: "pie", radius: ["45%", "70%"], center: ["50%", "50%"],
      label: { color: "#c9cede", fontSize: 11 },
      itemStyle: { borderColor: "#171a23", borderWidth: 2 },
      data: top.map((c) => ({ name: c.name, value: c.mentions })) }],
  });
}

/* ---------- dashboard ---------- */
async function loadDash() {
  try {
    const brands = await api.get("/api/brands");
    const sel = $("#sel-brand");
    sel.innerHTML = brands.items.map((b) => `<option value="${b.id}">${b.name}${b.is_primary ? " ★" : ""}</option>`).join("");
    const saved = localStorage.getItem("gp-brand");
    if (saved) sel.value = saved;
    sel.onchange = () => { localStorage.setItem("gp-brand", sel.value); loadInsights(); };
  } catch (e) { console.error(e); }

  try {
    const st = await api.get("/api/settings");
    const prov = st.provider || { kind: "demo" };
    const badge = $("#provider-badge");
    const engs = st.engines || [];
    if (engs.length > 1) {
      badge.textContent = engs.length + " 引擎";
      badge.className = "pill hit";
    } else {
      const prov0 = engs[0] || prov;
      badge.textContent = (prov0 && prov0.kind === "openai_compat") ? (prov0.model || "openai_compat") : "demo";
      badge.className = "pill " + ((prov0 && prov0.kind === "openai_compat") ? "hit" : "demo");
    }
  } catch (e) { /* keep default badge */ }
  loadInsights();
}

async function loadInsights() {
  const brandId = $("#sel-brand").value;
  const days = $("#sel-days").value;
  $("#sel-days").onchange = loadInsights;
  try {
    const d = await api.get(`/api/insights/overview?brand_id=${brandId}&days=${days}`);
    $("#kpis").innerHTML = `
      <div class="kpi"><div class="label">AI 可见率</div><div class="value">${d.visibility}%</div><div class="sub">${d.days} 天内被提及的回答占比</div></div>
      <div class="kpi"><div class="label">声量份额 SoV</div><div class="value">${d.share_of_voice}%</div><div class="sub">在全部品牌提及中的占比</div></div>
      <div class="kpi"><div class="label">监测 Prompt 数</div><div class="value">${d.total_prompts}</div><div class="sub">有效回答样本</div></div>
      <div class="kpi"><div class="label">品牌被提及</div><div class="value">${d.brand_mentions}</div><div class="sub">次</div></div>`;
    renderTrend(d.trend);
    renderSov(d.competitors);
    renderDims(d.dimensions || []);
    renderEngines(d.engines || []);
    renderDepth(d.depth || {});
    renderRecent(d.recent);
  } catch (e) {
    $("#kpis").innerHTML = `<div class="empty">${e.message} —— 先去 Prompt 库加几条，再点「立即监测」</div>`;
    trendChart.clear(); sovChart.clear(); $("#recent").innerHTML = "";
  }
}

const dimCN2 = { brand: "品牌词", scene: "场景词", compare: "对比词", choice: "选购词" };
const depCN = { mentioned: "仅提名", described: "有描述", recommended: "有推荐" };

function renderDims(dims) {
  const el = document.getElementById("dims");
  if (!dims.length) { el.innerHTML = '<div class="empty">暂无维度数据（跑一轮监测）</div>'; return; }
  el.innerHTML = `<table><thead><tr><th>维度</th><th>可见率</th><th>样本</th><th>状态</th></tr></thead><tbody>
    ${dims.map((x) => `<tr><td>${dimCN2[x.key] || x.key}</td><td><b>${x.visibility}%</b></td><td>${x.samples}</td>
    <td>${x.visibility === 0 ? '<span class="pill failed">缺席</span>' : x.visibility < 50 ? '<span class="pill partial">偏弱</span>' : '<span class="pill hit">在场</span>'}</td></tr>`).join("")}
  </tbody></table>`;
}

function renderEngines(engs) {
  const el = document.getElementById("engines");
  if (!engs.length) { el.innerHTML = '<div class="empty">暂无引擎数据</div>'; return; }
  el.innerHTML = `<table><thead><tr><th>引擎</th><th>可见率</th><th>样本</th></tr></thead><tbody>
    ${engs.map((e) => `<tr><td>${e.engine}</td><td><b>${e.visibility}%</b></td><td>${e.samples}</td></tr>`).join("")}
  </tbody></table>`;
}

function renderDepth(dep) {
  const kpis = document.getElementById("kpis");
  if (Object.keys(dep).length) {
    const parts = Object.entries(dep).map(([k, v]) => `${depCN[k] || k} ${v}`).join(" · ");
    const div = document.createElement("div");
    div.className = "kpi";
    div.innerHTML = `<div class="label">引用深度</div><div class="value" style="font-size:16px;line-height:1.8;margin-top:6px">${parts}</div><div class="sub">提名&lt;描述&lt;推荐</div>`;
    kpis.appendChild(div);
  }
}

function renderRecent(rows) {
  if (!rows.length) { $("#recent").innerHTML = '<div class="empty">暂无回答，点「立即监测」跑一轮</div>'; return; }
  $("#recent").innerHTML = rows.map((r) => {
    const mentioned = JSON.parse(r.mentioned_brands || "[]");
    const depMap = JSON.parse(r.depth || "{}");
    const hits = mentioned.map((m) => {
      const dep = depMap[m] || "mentioned";
      const cls = dep === "recommended" ? "hit" : dep === "described" ? "partial" : "demo";
      return `<span class="pill ${cls}">${m}·${depCN[dep] || dep}</span>`;
    }).join(" ");
    return `<table style="margin-bottom:10px"><tr>
      <td style="width:60%" class="muted">${String(r.prompt_text || "").slice(0, 80)}</td>
      <td>${hits || '<span class="pill miss">未提及</span>'}</td>
      <td class="muted" style="width:120px">${(r.created_at || "").slice(5, 16)}</td>
    </tr></table>
    <details><summary>展开回答全文</summary><div class="answer">${(r.answer_text || "").replace(/</g, "&lt;")}</div></details>`;
  }).join("");
}

$("#btn-report").onclick = (e) => {
  e.preventDefault();
  const brandId = $("#sel-brand").value || "";
  const days = $("#sel-days").value || 30;
  window.open(`/api/insights/report?brand_id=${brandId}&days=${days}`, "_blank");
};

/* ---------- run ---------- */
$("#btn-run").onclick = async () => {
  const status = $("#run-status");
  status.textContent = "监测执行中…";
  try {
    const r = await api.send("/api/runs", "POST", { scope: "active" });
    status.textContent = `完成：${r.done} 条成功${r.failed ? `, ${r.failed} 条失败` : ""}`;
    loadInsights();
  } catch (e) {
    status.textContent = `失败: ${e.message}`;
  }
};

/* ---------- prompts ---------- */
async function loadPrompts() {
  const d = await api.get("/api/prompts");
  const dimCN = { brand: "品牌词", scene: "场景词", compare: "对比词", choice: "选购词" };
  $("#tbl-prompts tbody").innerHTML = d.items.map((p) => `
    <tr><td>${p.id}</td><td>${p.text.replace(/</g, "&lt;")}</td>
    <td>${p.dimension ? `<span class="pill ${p.dimension === "brand" ? "hit" : "demo"}">${dimCN[p.dimension] || p.dimension}</span>` : "-"}</td>
    <td class="muted">${p.intent}</td>
    <td>${p.is_active ? '<span class="pill done">启用</span>' : '<span class="pill demo">停用</span>'}</td>
    <td><button class="btn danger" data-del="${p.id}">删除</button></td></tr>`).join("");
  $("#tbl-prompts tbody").querySelectorAll("[data-del]").forEach((b) => {
    b.onclick = async () => { await api.send(`/api/prompts/${b.dataset.del}`, "DELETE"); loadPrompts(); };
  });
}
$("#form-prompt").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("#p-text").value.trim();
  if (!text) return;
  await api.send("/api/prompts", "POST", { text, intent: $("#p-intent").value.trim(), dimension: $("#p-dimension").value });
  $("#p-text").value = ""; $("#p-intent").value = "";
  loadPrompts();
};

/* ---------- brands & settings ---------- */
async function loadBrands() {
  const d = await api.get("/api/brands");
  $("#tbl-brands tbody").innerHTML = d.items.map((b) => `
    <tr><td><b>${b.name}</b></td><td class="muted">${(b.aliases || []).join(", ")}</td>
    <td>${b.is_primary ? '<span class="pill hit">主品牌</span>' : '<span class="pill demo">竞品</span>'}</td>
    <td><button class="btn danger" data-del="${b.id}">删除</button></td></tr>`).join("");
  $("#tbl-brands tbody").querySelectorAll("[data-del]").forEach((btn) => {
    btn.onclick = async () => { await api.send(`/api/brands/${btn.dataset.del}`, "DELETE"); loadBrands(); };
  });
  const st = await api.get("/api/settings");
  renderEnginesForm(st.engines || (st.provider ? [{ name: "engine-1", ...st.provider }] : []));
}
$("#form-brand").onsubmit = async (e) => {
  e.preventDefault();
  const name = $("#b-name").value.trim();
  if (!name) return;
  const aliases = $("#b-aliases").value.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
  await api.send("/api/brands", "POST", { name, aliases, is_primary: $("#b-primary").checked });
  $("#b-name").value = ""; $("#b-aliases").value = ""; $("#b-primary").checked = false;
  loadBrands();
};
function renderEnginesForm(engines) {
  const box = document.getElementById("engines-box");
  if (!engines.length) engines = [{ name: "demo", kind: "demo", base_url: "", model: "" }];
  box.innerHTML = engines.map((e, i) => `
    <div class="panel" style="padding:12px;margin-bottom:10px" data-eng="${i}">
      <div class="formrow">
        <div class="field"><label>引擎名（结果将按此分列）</label><input class="e-name" value="${e.name || ""}" placeholder="deepseek"></div>
        <div class="field"><label>类型</label>
          <select class="e-kind">
            <option value="demo" ${e.kind !== "openai_compat" ? "selected" : ""}>demo（零成本）</option>
            <option value="openai_compat" ${e.kind === "openai_compat" ? "selected" : ""}>openai_compat（真实 LLM）</option>
          </select></div>
        <div class="field"><label>Base URL</label><input class="e-url" value="${e.base_url || ""}" placeholder="https://api.deepseek.com/v1"></div>
      </div>
      <div class="formrow">
        <div class="field"><label>模型</label><input class="e-model" value="${e.model || ""}" placeholder="deepseek-chat"></div>
        <div class="field"><label>API Key（${e.api_key_masked ? "当前 " + e.api_key_masked + "，" : ""}留空=保留）</label><input class="e-key" type="password" placeholder="sk-..."></div>
        <div class="field" style="display:flex;align-items:flex-end"><button type="button" class="btn danger" data-rm="${i}">移除</button></div>
      </div>
    </div>`).join("");
  box.querySelectorAll("[data-rm]").forEach((b) => {
    b.onclick = () => { b.closest("[data-eng]").remove(); };
  });
}

document.getElementById("btn-add-engine").onclick = () => {
  renderEnginesForm([...document.querySelectorAll("#engines-box [data-eng]")].map((row) => ({
    name: row.querySelector(".e-name").value,
    kind: row.querySelector(".e-kind").value,
    base_url: row.querySelector(".e-url").value,
    model: row.querySelector(".e-model").value,
    api_key: row.querySelector(".e-key").value || "__KEEP__",
  })).concat([{ name: "", kind: "openai_compat", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" }]));
};

$("#form-settings").onsubmit = async (e) => {
  e.preventDefault();
  const engines = [...document.querySelectorAll("#engines-box [data-eng]")].map((row) => ({
    name: row.querySelector(".e-name").value.trim() || "engine",
    kind: row.querySelector(".e-kind").value,
    base_url: row.querySelector(".e-url").value.trim(),
    model: row.querySelector(".e-model").value.trim(),
    api_key: row.querySelector(".e-key").value.trim() || "__KEEP__",
  }));
  try {
    await api.send("/api/settings", "PUT", { engines });
    loadBrands();
    $("#settings-hint").textContent = "已保存 ✓（" + engines.length + " 个引擎）";
    loadDash();
  } catch (err) { $("#settings-hint").textContent = `保存失败: ${err.message}`; }
};

/* ---------- boot ---------- */
loadDash();
