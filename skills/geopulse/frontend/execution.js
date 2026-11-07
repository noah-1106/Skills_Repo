import { h, field, input, select, textarea } from "./components.js";

const has = (value, key) => Object.prototype.hasOwnProperty.call(value || {}, key);

function parameterMode(saved, key) {
  if (!has(saved, key)) return "inherit";
  return saved[key] === null ? "null" : "value";
}

function modeOptions(kind) {
  return [
    { value: "inherit", label: "继承引擎或内建默认" },
    { value: "value", label: kind === "system" ? "本次自定义" : "本次指定数值" },
    { value: "null", label: kind === "system" ? "不发送 system message" : `不发送 ${kind}` },
  ];
}

export function executionFields(saved = {}, role = "answer", title = "执行参数") {
  const temperature = input(has(saved, "temperature") && saved.temperature !== null ? saved.temperature : 0.2,
    { type: "number", min: 0, max: 2, step: "0.01" });
  const maxTokens = input(has(saved, "max_tokens") && saved.max_tokens !== null ? saved.max_tokens : role === "judge" ? 1800 : role === "health" ? 8 : 700,
    { type: "number", min: 1, max: 8000, step: 1 });
  const systemPrompt = textarea(has(saved, "system_prompt") && saved.system_prompt !== null ? saved.system_prompt : "", { rows: 2 });
  const temperatureMode = select(modeOptions("temperature"), parameterMode(saved, "temperature"));
  const maxTokensMode = select(modeOptions("max_tokens"), parameterMode(saved, "max_tokens"));
  const systemMode = select(modeOptions("system"), parameterMode(saved, "system_prompt"));
  const rows = [
    [temperatureMode, temperature], [maxTokensMode, maxTokens], [systemMode, systemPrompt],
  ];
  const sync = () => rows.forEach(([mode, control]) => { control.disabled = mode.value !== "value"; });
  rows.forEach(([mode]) => mode.addEventListener("change", sync));
  sync();
  const node = h("details", { class: "advanced execution-fields" }, h("summary", {}, title), h("div", {},
    h("p", { class: "muted small" }, "留用继承会采用引擎默认值；显式“不发送”会从请求体省略该参数。回答与 Judge 的输出上限至少为 100 tokens。"),
    h("div", { class: "form-grid" },
      field("Temperature", temperatureMode), field("Temperature 数值", temperature),
      field("最大输出 tokens", maxTokensMode), field("最大输出 tokens 数值", maxTokens),
      field("System prompt", systemMode), field("System prompt 内容", systemPrompt))));
  const read = () => {
    const result = {};
    if (temperatureMode.value !== "inherit") result.temperature = temperatureMode.value === "null" ? null : Number(temperature.value);
    if (maxTokensMode.value !== "inherit") result.max_tokens = maxTokensMode.value === "null" ? null : Number(maxTokens.value);
    if (systemMode.value !== "inherit") result.system_prompt = systemMode.value === "null" ? null : systemPrompt.value;
    return result;
  };
  return { node, read };
}
