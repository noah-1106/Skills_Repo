import test from 'node:test';
import assert from 'node:assert/strict';
import { Connector, attachPendingTask } from '../src/daemon.js';
import { retryMessage, discardMessage, quarantineMessage, retryPolicy } from '../src/delivery.js';

const lane = 'bot:owner:agent-022';
const agents = { 'agent-022': { name: '项项', alias: '项项' } };
const message = id => ({ message_id: id, from_user_id: 'owner', message_type: 1, context_token: `token-${id}`, item_list: [{ type: 1, text_item: { text: id } }] });
const task = id => ({ kind: 'agent', agentId: 'agent-022', text: id, message: message(id), lane, history: [], taskId: `${id}-task`, invokeState: 'accepted', reply: null, sentClientIds: [], historyCommitted: false });
const pending = (id, extra = {}) => ({ message: message(id), attempts: 0, lastError: null, blocked: false, lane, seq: 1, queuedAt: new Date().toISOString(), ...extra });
const state = () => ({ bindings: {}, contexts: {}, histories: {}, processed: [], tasks: {}, pending: {}, deadLetters: {}, nextSeq: 0, lastError: null });
function connector(s, waitForResult, sent) {
  return new Connector({ config: { agents, allowFrom: ['owner'], pendingMaxAttempts: 2, pendingMaxAgeHours: 1 }, credentials: { ilink_bot_id: 'bot', ilink_user_id: 'owner' }, state: s,
    exflower: { invoke: async () => { throw new Error('must not invoke an already accepted task'); }, waitForResult },
    sender: async (to, text) => { sent.push({ to, text }); }, logger: () => {}, persist: () => {} });
}

test('失败达到次数后进入死信并放行同 lane 后续消息，原始任务不删除', async () => {
  const s = state(), sent = [];
  s.tasks.old = task('old'); s.tasks.next = task('next');
  s.pending.old = pending('old', { attempts: 1, seq: 1 }); s.pending.next = pending('next', { seq: 2 }); s.nextSeq = 2;
  const c = connector(s, async id => { if (id === 'old-task') throw new Error('persistent failure'); return { content: 'next ok' }; }, sent);
  await c.retryPending();
  assert.equal(s.pending.old, undefined);
  assert.equal(s.deadLetters.old.attempts, 2);
  assert.equal(s.deadLetters.old.reason, 'max_attempts');
  assert.equal(s.deadLetters.old.taskId, 'old-task');
  assert.equal(s.tasks.old.message.message_id, 'old');
  assert.equal(s.pending.next, undefined);
  assert.deepEqual(sent, [{ to: 'owner', text: 'next ok' }]);
  assert.deepEqual(s.processed, ['next']);
});

test('排队超时在执行前隔离，恢复扫描不会把死信重新入队', async () => {
  const s = state(), sent = [];
  s.tasks.old = task('old'); s.tasks.next = task('next');
  s.pending.old = pending('old', { queuedAt: new Date(Date.now() - 2 * 3600_000).toISOString(), seq: 1 });
  s.pending.next = pending('next', { seq: 2 }); s.nextSeq = 2;
  const c = connector(s, async id => { assert.equal(id, 'next-task'); return 'after timeout'; }, sent);
  await c.retryPending();
  assert.equal(s.deadLetters.old.reason, 'max_age');
  assert.equal(s.deadLetters.old.attempts, 0);
  c.recoverPending();
  assert.equal(s.pending.old, undefined);
  assert.equal(s.deadLetters.old.message.message_id, 'old');
  assert.deepEqual(s.processed, ['next']);
});

test('不确定 invoke 不按次数或年龄自动隔离，必须核对 taskId 后 recover', async () => {
  const s = state();
  s.tasks.u = { ...task('u'), taskId: null, invokeState: 'uncertain' };
  s.pending.u = pending('u', { attempts: 99, blocked: true, queuedAt: new Date(Date.now() - 3600_000).toISOString() });
  const c = connector(s, async () => { throw new Error('must not poll uncertain task'); }, []);
  await c.retryPending();
  assert.ok(s.pending.u);
  assert.equal(s.deadLetters.u, undefined);
  quarantineMessage(s, 'u', 'max_attempts');
  assert.throws(() => retryMessage(s, 'u'), /recover/);
  attachPendingTask(s, 'u', 'verified-task');
  assert.equal(s.tasks.u.taskId, 'verified-task');
  assert.equal(s.tasks.u.invokeState, 'accepted');
  assert.equal(s.deadLetters.u, undefined);
  assert.equal(s.pending.u.attempts, 0);
  assert.equal(s.pending.u.blocked, false);
});

test('手动重试重置计数；确认丢弃只归档，重复投递不复活', async () => {
  const s = state();
  s.tasks.d = task('d'); s.pending.d = pending('d', { attempts: 4 });
  assert.throws(() => discardMessage(s, 'd'), /--yes/);
  discardMessage(s, 'd', true);
  assert.equal(s.pending.d, undefined);
  assert.equal(s.deadLetters.d.discarded, true);
  assert.equal(s.tasks.d.message.message_id, 'd');
  const c = connector(s, async () => { throw new Error('must not execute discarded task'); }, []);
  const redelivered = c.enqueue([message('d')]);
  assert.equal(redelivered.immediate[0].status, 'dead_letter');
  assert.equal(redelivered.jobs.length, 0);
  assert.equal(s.pending.d, undefined);
  assert.throws(() => retryMessage(s, 'd'), /discarded.*terminal/);
  assert.equal(s.pending.d, undefined);
  assert.equal(s.deadLetters.d.discarded, true);
  assert.equal(s.tasks.d.message.message_id, 'd');
  assert.equal(retryPolicy({ pendingMaxAttempts: 3, pendingMaxAgeHours: 2 }).maxAttempts, 3);
});


test('taskless 死信恢复：已有 taskId 只轮询原结果，不重新 invoke，并恢复历史', async () => {
  const s = state(), sent = [];
  const raw = message('restored');
  const historyKey = lane;
  s.histories[historyKey] = [{ role: 'user', content: '上一轮' }, { role: 'assistant', content: '上一答' }];
  s.deadLetters.restored = {
    message: raw, attempts: 10, lane, seq: 1, reason: 'max_attempts',
    deadAt: new Date().toISOString(), taskId: 'accepted-original', agentId: 'agent-022',
    invokeState: 'accepted', lastError: 'wait timeout', discarded: false,
  };
  let invokes = 0;
  const c = new Connector({ config: { agents, allowFrom: ['owner'] }, credentials: { ilink_bot_id: 'bot', ilink_user_id: 'owner' }, state: s,
    exflower: { invoke: async () => { invokes++; throw new Error('must not invoke restored accepted task'); }, waitForResult: async id => ({ content: `原任务结果:${id}` }) },
    sender: async (to, text) => sent.push({ to, text }), logger: () => {}, persist: () => {} });
  const result = retryMessage(s, 'restored', { botId: 'bot' });
  assert.equal(result.status, 'requeued');
  assert.equal(s.tasks.restored.taskId, 'accepted-original');
  assert.equal(s.tasks.restored.invokeState, 'accepted');
  assert.equal(s.tasks.restored.history.length, 2);
  await c.retryPending();
  assert.equal(invokes, 0);
  assert.deepEqual(sent, [{ to: 'owner', text: '原任务结果:accepted-original' }]);
  assert.ok(s.processed.includes('restored'));
});

test('taskless 不确定死信可用已核对 taskId recover，随后只轮询不重新 invoke', async () => {
  const s = state(), sent = [];
  const raw = message('verified');
  s.deadLetters.verified = {
    message: raw, attempts: 1, lane, seq: 1, reason: 'manual_review',
    deadAt: new Date().toISOString(), taskId: null, agentId: 'agent-022',
    invokeState: 'uncertain', lastError: 'transport uncertain',
  };
  let invokes = 0;
  attachPendingTask(s, 'verified', 'human-verified', () => {}, { botId: 'bot' });
  assert.equal(s.tasks.verified.invokeState, 'accepted');
  const c = new Connector({ config: { agents, allowFrom: ['owner'] }, credentials: { ilink_bot_id: 'bot', ilink_user_id: 'owner' }, state: s,
    exflower: { invoke: async () => { invokes++; throw new Error('must not invoke human-verified task'); }, waitForResult: async id => `核对后:${id}` },
    sender: async (to, text) => sent.push({ to, text }), logger: () => {}, persist: () => {} });
  await c.retryPending();
  assert.equal(invokes, 0);
  assert.deepEqual(sent, [{ to: 'owner', text: '核对后:human-verified' }]);
  assert.ok(s.processed.includes('verified'));
});


test('discarded 死信是终态：retry/recover 在有无 task 缓存时都拒绝且不改状态', () => {
  for (const cached of [false, true]) for (const mode of ['retry', 'recover']) {
    const s = state();
    const key = `discarded-${cached}-${mode}`;
    const raw = message(key);
    if (cached) s.tasks[key] = task(key);
    s.deadLetters[key] = {
      message: raw, attempts: 10, lane, seq: 1, reason: 'manual_discard',
      deadAt: new Date().toISOString(), taskId: cached ? `${key}-task` : 'accepted-original',
      agentId: 'agent-022', invokeState: 'accepted', discarded: true,
      discardedAt: new Date().toISOString(),
    };
    const before = structuredClone(s);
    if (mode === 'retry') {
      assert.throws(() => retryMessage(s, key, { botId: 'bot' }), /discarded.*terminal/);
    } else {
      assert.throws(() => attachPendingTask(s, key, 'verified', () => {}, { botId: 'bot' }), /discarded.*terminal/);
    }
    assert.deepEqual(s, before);
  }
});

test('taskless 死信缺 Agent 元数据时 retry/recover 均拒绝且不改状态', () => {
  for (const mode of ['retry', 'recover']) {
    const s = state();
    const key = `missing-agent-${mode}`;
    s.deadLetters[key] = {
      message: message(key), attempts: 1, lane, seq: 1, reason: 'max_attempts',
      deadAt: new Date().toISOString(), taskId: 'accepted-original', invokeState: 'accepted',
    };
    const before = structuredClone(s);
    if (mode === 'retry') {
      assert.throws(() => retryMessage(s, key, { botId: 'bot' }), /Agent.*metadata/);
    } else {
      assert.throws(() => attachPendingTask(s, key, 'verified', () => {}, { botId: 'bot' }), /Agent.*metadata/);
    }
    assert.deepEqual(s, before);
  }
});
