import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'exf-weixin-startup-hol-'));
process.env.EXF_WEIXIN_HOME = home;
const { runDaemon } = await import('../src/daemon.js');
const { paths, writeJson, readJson } = await import('../src/store.js');
const response = data => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
const until = async (fn, ms = 2500) => { const end = Date.now() + ms; while (Date.now() < end) { if (fn()) return; await new Promise(r => setTimeout(r, 10)); } throw new Error('timeout'); };

test('启动时旧 Agent 永不返回，也不阻塞不同 Agent lane 的新消息接收与执行', async () => {
  const p = paths();
  writeJson(p.config, { exflowerUrl: 'http://exflower.test', agents: { 'agent-022': { name: '项项', alias: '项项' }, 'agent-028': { name: '小小', alias: '小小' } }, allowFrom: ['owner'], pendingMaxAttempts: 10, pendingMaxAgeHours: 24 });
  writeJson(p.credentials, { token: 'test-only', ilink_bot_id: 'bot', ilink_user_id: 'owner', baseUrl: 'http://weixin.test' }, true);
  const old = msgFor('old');
  writeJson(p.state, { syncBuf: 'cursor-old', bindings: {}, contexts: { 'bot:owner': 'old-token' }, histories: {}, processed: [], processedIndex: {}, tasks: { old: { kind: 'agent', agentId: 'agent-022', text: 'old', message: old, lane: 'bot:owner:agent-022', history: [], taskId: 'old-task', invokeState: 'accepted', reply: null, sentClientIds: [], historyCommitted: false } }, pending: { old: { message: old, attempts: 0, lastError: 'old timeout', blocked: false, lane: 'bot:owner:agent-022', seq: 1, queuedAt: new Date().toISOString(), nextRetryAt: null } }, nextSeq: 1, lastError: null }, true);
  let polls = 0, sends = 0, invokes = 0;
  const controller = new AbortController();
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url);
    if (target.includes('/api/message/send')) { invokes++; return response({ success: true, taskId: 'new-task' }); }
    if (target.includes('/api/messages/by-task/old-task')) return new Promise((resolve, reject) => { options.signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true }); });
    if (target.includes('/api/messages/by-task/new-task')) return response({ message: { content: 'new reply', steps_json: '[]' } });
    if (target.includes('/getupdates')) {
      polls++;
      if (polls === 1) return response({ ret: 0, get_updates_buf: 'cursor-new', msgs: [msgFor('new', '@小小 hello')] });
      return new Promise((resolve, reject) => { const timer = setTimeout(() => resolve(response({ ret: 0, msgs: [] })), 4000); options.signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new Error('aborted')); }, { once: true }); });
    }
    if (target.includes('/sendmessage')) { sends++; return response({ ret: 0, message_id: 'server-new' }); }
    throw new Error(`unexpected ${target}`);
  };
  const running = runDaemon({ signal: controller.signal });
  try {
    await until(() => sends === 1);
    const state = readJson(p.state);
    assert.equal(state.pending.old.message.message_id, 'old');
    assert.equal(state.processed.includes('new'), true);
    assert.equal(state.pending.new, undefined);
    assert.equal(state.syncBuf, 'cursor-new');
    assert.equal(invokes, 1);
  } finally {
    controller.abort(); await running;
  }
});
function msgFor(id, text = '@项项 hello') { return { message_id: id, from_user_id: 'owner', message_type: 1, context_token: `${id}-token`, item_list: [{ type: 1, text_item: { text } }] }; }
