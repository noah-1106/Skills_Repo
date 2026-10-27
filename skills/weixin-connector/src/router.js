function mentionCandidates(agents) {
  const candidates = new Map();
  for (const [id, agent] of Object.entries(agents || {})) {
    for (const value of [id, agent.alias || agent.name]) {
      if (value) candidates.set(String(value).toLowerCase(), String(value));
    }
  }
  return [...candidates.values()].sort((a, b) => b.length - a.length);
}

export function parseRouteText(raw, agents = {}) {
  const text = String(raw || '').trim();
  if (text === '/agents') return { command: 'agents' };
  const use = text.match(/^\/use\s+(.+?)\s*$/);
  if (use) return { command: 'use', alias: use[1] };
  if (text.startsWith('@')) {
    // Longest exact alias wins: "Coco 2.0" must beat the shorter "Coco".
    for (const candidate of mentionCandidates(agents)) {
      const prefix = `@${candidate}`;
      if (text.slice(0, prefix.length).toLowerCase() !== prefix.toLowerCase()) continue;
      if (text.length > prefix.length && !/\s/.test(text[prefix.length])) continue;
      return { alias: text.slice(1, prefix.length), text: text.slice(prefix.length).trim(), explicit: true };
    }
    const mention = text.match(/^@([^\s@]+)(?:\s+|$)([\s\S]*)$/);
    if (mention) return { alias: mention[1], text: mention[2].trim(), explicit: true };
  }
  return { text, explicit: false };
}
export function findAgent(agents, alias) {
  const needle = String(alias || '').toLowerCase();
  return Object.entries(agents || {}).find(([id, a]) => id.toLowerCase() === needle || String(a.alias || '').toLowerCase() === needle);
}
export function agentChoices(agents) {
  const list = Object.entries(agents || {}).map(([, a]) => `@${a.alias || a.name}`);
  return list.length ? list.join('、') : '尚未绑定 Agent，请先在 ExFlower 中配置。';
}
export function routeMessage(raw, agents, binding) {
  const parsed = parseRouteText(raw, agents);
  if (parsed.command === 'agents') return { reply: `可用 Agent：${agentChoices(agents)}\n用 @别名 切换，例如：@${Object.values(agents)[0]?.alias || '项项'} 你好` };
  if (parsed.command === 'use') {
    const found = findAgent(agents, parsed.alias);
    return found ? { agentId: found[0], text: '', bind: true, reply: `已切换到 ${found[1].name}。后续消息将发给该 Agent。` } : { reply: `没有找到 ${parsed.alias}。可用：${agentChoices(agents)}` };
  }
  if (parsed.alias) {
    const found = findAgent(agents, parsed.alias);
    if (!found) return { reply: `没有找到 ${parsed.alias}。可用：${agentChoices(agents)}` };
    if (!parsed.text) return { agentId: found[0], bind: true, reply: `已切换到 ${found[1].name}。请继续发送消息。` };
    return { agentId: found[0], text: parsed.text, bind: true };
  }
  if (binding && agents[binding]) return { agentId: binding, text: parsed.text };
  return { reply: `请先指定 Agent，例如：@项项 你好\n可用：${agentChoices(agents)}\n之后不带 @ 的消息会继续发给当前 Agent。` };
}
export function extractText(message) {
  const items = Array.isArray(message.item_list) ? message.item_list : [];
  return items.filter(i => i.type === 1).map(i => i.text_item?.text || '').filter(Boolean).join('\n').trim();
}
export function messageKey(message) { return String(message.message_id || message.client_id || `${message.from_user_id}:${message.create_time_ms}:${message.seq || ''}`); }
