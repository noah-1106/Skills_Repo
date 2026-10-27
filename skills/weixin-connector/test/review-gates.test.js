import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Connector, pendingSummary } from '../src/daemon.js';
import { discardMessage } from '../src/delivery.js';
import { saveState, loadState, paths } from '../src/store.js';

const msg = (id, extra = {}) => ({ message_id: id, from_user_id: 'owner', message_type: 1, context_token: `token-${id}`, item_list: [{ type: 1, text_item: { text: id } }], ...extra });
const blank = () => ({ bindings: {}, contexts: {}, histories: {}, processed: [], tasks: {}, pending: {}, deadLetters: {}, nextSeq: 0, lastError: null });
function fixture(config = { agents: { 'agent-022': { name: '项项', alias: '项项' } }, allowFrom: ['owner'] }) {
  const calls = [], sent = [];
  const exflower = { invoke: async (id, text) => { calls.push({ id, text }); return `task-${calls.length}`; }, waitForResult: async id => `回复:${id}` };
  const state = blank();
  const connector = new Connector({ config, credentials: { ilink_bot_id: 'bot', ilink_user_id: 'owner' }, state, exflower, sender: async (to, text) => sent.push({ to, text }), logger: () => {}, persist: () => {} });
  return { connector, calls, sent, state };
}

test('完成 ID 超过 2000 条仍持久保留，重载与重投都不会重复执行', async () => {
  const previousHome = process.env.EXF_WEIXIN_HOME;
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'exf-weixin-dedupe-retention-'));
  process.env.EXF_WEIXIN_HOME = home;
  try {
    const persisted = blank();
    persisted.processed = ['ancient', ...Array.from({ length: 2500 }, (_, i) => `recent-${i}`)];
    saveState(persisted);
    const reloaded = loadState();
    assert.equal(reloaded.processed.length, 2501);
    assert.ok(reloaded.processed.includes('ancient'));
    assert.equal(fs.statSync(paths().state).mode & 0o777, 0o600);

    const { connector, calls, state } = fixture();
    state.processed = reloaded.processed;
    const results = await connector.ingest([msg('ancient')]);
    assert.equal(results[0].status, 'duplicate');
    assert.equal(calls.length, 0);
    assert.deepEqual(pendingSummary(state), []);
    state.pending.ancient = { message: msg('ancient'), attempts: 0, lane: 'bot:owner:local', seq: 1 };
    connector.recoverPending();
    assert.equal(state.pending.ancient, undefined);
  } finally {
    if (previousHome === undefined) delete process.env.EXF_WEIXIN_HOME;
    else process.env.EXF_WEIXIN_HOME = previousHome;
  }
});

test('allowFrom 缺失或为空时仅扫码者可用，其他私聊拒绝', async () => {
  for (const allowFrom of [undefined, []]) {
    const { connector, calls, sent } = fixture({ agents: { 'agent-022': { name: '项项', alias: '项项' } }, allowFrom });
    const denied = await connector.ingest([msg(`denied-${String(allowFrom)}`, { from_user_id: 'stranger' })]);
    assert.equal(denied[0].status, 'unauthorized');
    assert.equal(calls.length, 0); assert.equal(sent.length, 0);
    const ownerMessage = msg(`owner-${String(allowFrom)}`);
    ownerMessage.item_list[0].text_item.text = '@项项 owner message';
    const accepted = await connector.ingest([ownerMessage]);
    assert.equal(accepted[0].status, 'sent');
    assert.equal(calls.length, 1);
  }
  const { connector, calls } = fixture();
  const allowedMessage = msg('allowed');
  allowedMessage.item_list[0].text_item.text = '@项项 allowed message';
  await connector.ingest([allowedMessage]);
  assert.equal(calls.length, 1);
});

test('calling/uncertain/rejected 不能用 discard 绕过人工 taskId 核对', () => {
  for (const invokeState of ['calling', 'uncertain', 'rejected']) {
    for (const location of ['pending', 'deadLetters']) {
      const state = blank();
      state.tasks.u = { kind: 'agent', agentId: 'agent-022', taskId: null, invokeState, message: msg('u'), lane: 'bot:owner:agent-022' };
      const record = { message: msg('u'), attempts: 10, blocked: true, lane: 'bot:owner:agent-022', seq: 1, taskId: null, agentId: 'agent-022', invokeState };
      if (location === 'pending') state.pending.u = record;
      else state.deadLetters.u = record;
      assert.throws(() => discardMessage(state, 'u', true), /recover/);
      assert.ok(state[location].u);
      assert.equal(location === 'pending' ? state.deadLetters.u : state.pending.u, undefined);
    }
  }
});
