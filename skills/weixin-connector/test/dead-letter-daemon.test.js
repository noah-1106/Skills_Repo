import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'exf-weixin-dead-daemon-'));
process.env.EXF_WEIXIN_HOME = home;
const { runDaemon } = await import('../src/daemon.js');
const { paths, writeJson, readJson } = await import('../src/store.js');
const response = data => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
const waitUntil = async (predicate, timeoutMs = 2500) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) { if (predicate()) return; await new Promise(r => setTimeout(r, 10)); }
  throw new Error('condition timeout');
};

test('旧任务死信后 daemon 继续接收同联系人新消息并推进游标', async () => {
  const p = paths();
  writeJson(p.config, { exflowerUrl: 'http://exflower.test', agents: { 'agent-028': { name: '小小', alias: '小小' } }, allowFrom: ['owner'], pendingMaxAttempts: 1, pendingMaxAgeHours: 24 });
  writeJson(p.credentials, { token: 'test-only', ilink_bot_id: 'bot', ilink_user_id: 'owner', baseUrl: 'http://weixin.test' }, true);
  const oldMessage = { message_id: 'old', from_user_id: 'owner', message_type: 1, context_token: 'old-token', item_list: [{ type: 1, text_item: { text: '@小小 旧任务' } }] };
  writeJson(p.state, { syncBuf: 'old-cursor', bindings: {}, contexts: { 'bot:owner': 'old-token' }, histories: {}, processed: [], tasks: { old: { kind: 'agent', agentId: 'agent-028', text: '旧任务', message: oldMessage, lane: 'bot:owner:agent-028', history: [], taskId: 'old-task', invokeState: 'accepted', reply: null, sentClientIds: [], historyCommitted: false } }, pending: { old: { message: oldMessage, attempts: 0, lastError: null, blocked: false, lane: 'bot:owner:agent-028', seq: 1 } }, nextSeq: 1, lastError: null }, true);
  let polls = 0, invokes = 0, sends = 0, pendingDuringPoll = null;
  const controller = new AbortController();
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url);
    if (target.includes('/api/message/send')) {
      pendingDuringPoll = Object.keys(readJson(p.state).pending || {});
      invokes++; return response({ success: true, taskId: 'new-task' });
    }
    if (target.includes('/api/messages/by-task/old-task')) throw new Error('old result permanently unavailable');
    if (target.includes('/api/messages/by-task/new-task')) return response({ message: { content: '新消息回复', steps_json: '[]', thinking: '' } });
    if (target.includes('/getupdates')) {
      polls++;
      if (polls === 1) return response({ ret: 0, get_updates_buf: 'new-cursor', msgs: [{ message_id: 'new', from_user_id: 'owner', message_type: 1, context_token: 'new-token', item_list: [{ type: 1, text_item: { text: '@小小 新消息' } }] }] });
      await new Promise((resolve, reject) => { const t = setTimeout(resolve, 2000); options.signal?.addEventListener('abort', () => { clearTimeout(t); reject(new Error('aborted')); }, { once: true }); });
    }
    if (target.includes('/sendmessage')) { sends++; return response({ ret: 0, message_id: 'server-new' }); }
    throw new Error(`unexpected URL ${target}`);
  };
  const running = runDaemon({ signal: controller.signal });
  try {
    await waitUntil(() => sends === 1 && readJson(p.state).deadLetters?.old);
    const state = readJson(p.state);
    assert.equal(state.deadLetters.old.attempts, 1);
    assert.equal(state.deadLetters.old.taskId, 'old-task');
    assert.equal(state.pending.old, undefined);
    assert.equal(state.pending.new, undefined);
    assert.ok(pendingDuringPoll, 'new raw message must be durable before batch completion');
    assert.equal(state.processed.includes('new'), true);
    assert.equal(state.syncBuf, 'new-cursor');
    assert.equal(invokes, 1);
    assert.equal(state.tasks.old.message.message_id, 'old');
  } finally {
    controller.abort(); await running;
  }
  assert.equal(fs.existsSync(p.pid), false);
});
