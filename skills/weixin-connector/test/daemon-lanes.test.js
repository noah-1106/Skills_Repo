import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'exf-weixin-daemon-lanes-'));
process.env.EXF_WEIXIN_HOME = home;
const { runDaemon } = await import('../src/daemon.js');
const { paths, writeJson, readJson, loadState } = await import('../src/store.js');

const response = data => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
const waitUntil = async (predicate, timeoutMs = 2000) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error('condition timeout');
};

test('daemon 轮询不被旧任务队头阻塞：新消息落库、执行并推进游标', async () => {
  const p = paths();
  writeJson(p.config, { exflowerUrl: 'http://exflower.test', agents: { 'agent-022': { name: '项项', alias: '项项' }, 'agent-028': { name: '小小', alias: '小小' } }, allowFrom: ['owner'] });
  writeJson(p.credentials, { token: 'test-only', ilink_bot_id: 'bot', ilink_user_id: 'owner', baseUrl: 'http://weixin.test' }, true);
  const oldMessage = { message_id: 'old-small', from_user_id: 'owner', message_type: 1, context_token: 'old-token', item_list: [{ type: 1, text_item: { text: 'WX-OLD' } }] };
  writeJson(p.state, {
    syncBuf: 'cursor-old', bindings: {}, contexts: { 'bot:owner': 'old-token' }, histories: {}, processed: [],
    tasks: { 'old-small': { kind: 'agent', agentId: 'agent-028', text: 'WX-OLD', message: oldMessage, history: [], taskId: 'old-task', invokeState: 'accepted', reply: null, sentClientIds: [], historyCommitted: false } },
    pending: { 'old-small': { message: oldMessage, attempts: 2, lastError: 'old timeout' } }, lastError: null,
  }, true);
  let getUpdatesCalls = 0, newInvokes = 0, oldInvokes = 0, sends = 0;
  const controller = new AbortController();
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url);
    if (target.includes('/api/message/send')) {
      const body = JSON.parse(options.body);
      if (body.agentId.endsWith('agent-028')) oldInvokes++;
      if (body.agentId.endsWith('agent-022')) { newInvokes++; assert.equal(body.content, '新消息'); }
      return response({ success: true, taskId: 'new-task' });
    }
    if (target.includes('/api/messages/by-task/old-task')) {
      // Hold the HTTP request itself, not just the polling sleep, to verify abort propagation.
      await new Promise((resolve, reject) => {
        if (options.signal?.aborted) { reject(new Error('aborted before old result')); return; }
        options.signal?.addEventListener('abort', () => reject(new Error('old result aborted')), { once: true });
      });
      return response({ message: null });
    }
    if (target.includes('/api/messages/by-task/new-task')) return response({ message: { content: '项项新回复', steps_json: '[]', thinking: '' } });
    if (target.includes('/getupdates')) {
      getUpdatesCalls++;
      if (getUpdatesCalls === 1) return response({ ret: 0, get_updates_buf: 'cursor-new', msgs: [{ message_id: 'new-xiang', from_user_id: 'owner', message_type: 1, context_token: 'new-token', item_list: [{ type: 1, text_item: { text: '@项项 新消息' } }] }] });
      await new Promise((resolve, reject) => {
        const timer = setTimeout(resolve, 2000);
        options.signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new Error('aborted')); }, { once: true });
      });
      return response({ ret: 0, get_updates_buf: 'cursor-new', msgs: [] });
    }
    if (target.includes('/sendmessage')) { sends++; return response({ ret: 0, message_id: 'server-new' }); }
    throw new Error(`unexpected URL ${target}`);
  };
  const running = runDaemon({ signal: controller.signal });
  await waitUntil(() => sends === 1 && readJson(p.state).processed.includes('new-xiang'));
  const state = readJson(p.state);
  assert.equal(state.syncBuf, 'cursor-new');
  assert.equal(state.pending['new-xiang'], undefined);
  assert.equal(state.pending['old-small'].message.message_id, 'old-small');
  assert.equal(state.tasks['old-small'].taskId, 'old-task');
  assert.equal(newInvokes, 1);
  assert.equal(oldInvokes, 0);
  assert.equal(state.nextSeq >= 2, true);
  assert.equal(loadState().nextSeq, state.nextSeq);
  assert.equal(state.bindings['bot:owner'].agentId, 'agent-022');
  controller.abort();
  await running;
  assert.equal(fs.existsSync(p.pid), false);
});
