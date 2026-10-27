import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const bin = fileURLToPath(new URL('../bin/exf-weixin.js', import.meta.url));
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'exf-weixin-cli-queue-'));
const statePath = path.join(home, 'state.json');
const message = { message_id: 'cli-dead', from_user_id: 'owner', message_type: 1, item_list: [{ type: 1, text_item: { text: 'test' } }] };
const state = {
  bindings: {}, contexts: {}, histories: {}, processed: [], nextSeq: 1, lastError: null,
  tasks: { 'cli-dead': { kind: 'agent', agentId: 'agent-022', text: 'test', message, lane: 'bot:owner:agent-022', taskId: 'task', invokeState: 'accepted', reply: null, history: [], sentClientIds: [] } },
  pending: {}, deadLetters: { 'cli-dead': { message, attempts: 10, lane: 'bot:owner:agent-022', seq: 1, reason: 'max_attempts', deadAt: new Date().toISOString(), taskId: 'task', agentId: 'agent-022', invokeState: 'accepted', lastError: 'timeout' } },
};
fs.writeFileSync(statePath, JSON.stringify(state));
const run = (args, ok = true, isolatedHome = home) => {
  const result = spawnSync(process.execPath, [bin, ...args, '--json'], { env: { ...process.env, EXF_WEIXIN_HOME: isolatedHome }, encoding: 'utf8' });
  if (ok) assert.equal(result.status, 0, result.stdout + result.stderr);
  else assert.notEqual(result.status, 0, result.stdout + result.stderr);
  return JSON.parse(result.stdout);
};

test('CLI 死信重试、确认丢弃与运行中写入保护', () => {
  assert.equal(run(['pending']).deadLetters.length, 1);
  const retry = run(['pending', 'retry', '--key', 'cli-dead']);
  assert.equal(retry.status, 'requeued');
  assert.equal(JSON.parse(fs.readFileSync(statePath)).pending['cli-dead'].attempts, 0);
  assert.equal(JSON.parse(fs.readFileSync(statePath)).deadLetters['cli-dead'], undefined);
  const refused = run(['pending', 'discard', '--key', 'cli-dead'], false);
  assert.match(refused.error, /--yes/);
  const discarded = run(['pending', 'discard', '--key', 'cli-dead', '--yes']);
  assert.equal(discarded.status, 'discarded');
  const archived = JSON.parse(fs.readFileSync(statePath));
  assert.equal(archived.deadLetters['cli-dead'].discarded, true);
  assert.equal(archived.tasks['cli-dead'].message.message_id, 'cli-dead');
  fs.writeFileSync(path.join(home, 'daemon.pid'), JSON.stringify({ pid: process.pid }));
  const running = run(['pending', 'retry', '--key', 'cli-dead'], false);
  assert.match(running.error, /先 stop/);
  fs.unlinkSync(path.join(home, 'daemon.pid'));
  const policy = run(['pending', 'policy', '--max-attempts', '4', '--max-age-hours', '12']);
  assert.deepEqual(policy.policy, { maxAttempts: 4, maxAgeHours: 12, maxAgeMs: 12 * 3600000 });
  assert.equal(run(['pending', 'policy', '--max-attempts', '0'], false).success, false);
});


test('CLI 对没有 tasks[key] 的不确定死信拒绝 retry/discard，且不改写 state', () => {
  for (const invokeState of ['calling', 'uncertain', 'rejected']) {
    const isolatedHome = fs.mkdtempSync(path.join(os.tmpdir(), `exf-weixin-cli-${invokeState}-`));
    const isolatedStatePath = path.join(isolatedHome, 'state.json');
    const dead = {
      message, attempts: 10, lane: 'bot:owner:agent-022', seq: 1,
      reason: 'manual_review', deadAt: new Date().toISOString(),
      taskId: null, agentId: 'agent-022', invokeState, lastError: 'delivery uncertain',
    };
    fs.writeFileSync(isolatedStatePath, JSON.stringify({ ...state, tasks: {}, pending: {}, deadLetters: { 'cli-dead': dead } }, null, 2));
    const before = fs.readFileSync(isolatedStatePath, 'utf8');
    const retry = run(['pending', 'retry', '--key', 'cli-dead'], false, isolatedHome);
    assert.match(retry.error, /recover/);
    assert.equal(fs.readFileSync(isolatedStatePath, 'utf8'), before);
    const discard = run(['pending', 'discard', '--key', 'cli-dead', '--yes'], false, isolatedHome);
    assert.match(discard.error, /recover/);
    assert.equal(fs.readFileSync(isolatedStatePath, 'utf8'), before);
  }
});


test('CLI 从 taskless 死信恢复原 taskId/人工核对 taskId，并恢复持久历史', () => {
  for (const scenario of [
    { key: 'accepted', invokeState: 'accepted', originalTaskId: 'accepted-original', command: ['pending', 'retry', '--key', 'accepted'], expectedTaskId: 'accepted-original' },
    { key: 'verified', invokeState: 'uncertain', originalTaskId: null, command: ['recover', '--key', 'verified', '--task-id', 'human-verified'], expectedTaskId: 'human-verified' },
  ]) {
    const isolatedHome = fs.mkdtempSync(path.join(os.tmpdir(), `exf-weixin-cli-restore-${scenario.key}-`));
    const isolatedStatePath = path.join(isolatedHome, 'state.json');
    const raw = { ...message, message_id: scenario.key };
    const restoredState = {
      ...state, tasks: {}, pending: {},
      histories: { 'bot:owner:agent-022': [{ role: 'user', content: '上一轮' }, { role: 'assistant', content: '上一答' }] },
      deadLetters: { [scenario.key]: {
        message: raw, attempts: 10, lane: 'bot:owner:agent-022', seq: 1,
        reason: 'max_attempts', deadAt: new Date().toISOString(),
        taskId: scenario.originalTaskId, agentId: 'agent-022', invokeState: scenario.invokeState,
      } },
    };
    fs.writeFileSync(isolatedStatePath, JSON.stringify(restoredState, null, 2));
    fs.writeFileSync(path.join(isolatedHome, 'credentials.json'), JSON.stringify({ token: 'test-only', ilink_bot_id: 'bot', ilink_user_id: 'owner' }));
    const result = run(scenario.command, true, isolatedHome);
    const after = JSON.parse(fs.readFileSync(isolatedStatePath));
    assert.ok(['requeued', 'attached'].includes(result.status));
    assert.equal(after.tasks[scenario.key].taskId, scenario.expectedTaskId);
    assert.equal(after.tasks[scenario.key].invokeState, 'accepted');
    assert.equal(after.tasks[scenario.key].history.length, 2);
    assert.equal(after.pending[scenario.key].message.message_id, scenario.key);
    assert.equal(after.deadLetters[scenario.key], undefined);
  }
});


test('CLI 对 discarded 与缺 Agent 元数据死信拒绝 retry/recover，且不改写 state', () => {
  for (const scenario of ['discarded', 'missing-agent']) for (const mode of ['retry', 'recover']) {
    const key = `${scenario}-${mode}`;
    const isolatedHome = fs.mkdtempSync(path.join(os.tmpdir(), `exf-weixin-cli-${key}-`));
    const isolatedStatePath = path.join(isolatedHome, 'state.json');
    const dead = {
      message: { ...message, message_id: key }, attempts: 10,
      lane: 'bot:owner:agent-022', seq: 1, reason: 'manual_discard',
      deadAt: new Date().toISOString(), taskId: 'accepted-original', invokeState: 'accepted',
    };
    if (scenario === 'discarded') Object.assign(dead, { agentId: 'agent-022', discarded: true, discardedAt: new Date().toISOString() });
    const isolatedState = { ...state, tasks: {}, pending: {}, deadLetters: { [key]: dead } };
    fs.writeFileSync(isolatedStatePath, JSON.stringify(isolatedState, null, 2));
    fs.writeFileSync(path.join(isolatedHome, 'credentials.json'), JSON.stringify({ token: 'test-only', ilink_bot_id: 'bot', ilink_user_id: 'owner' }));
    const before = fs.readFileSync(isolatedStatePath, 'utf8');
    const command = mode === 'retry' ? ['pending', 'retry', '--key', key] : ['recover', '--key', key, '--task-id', 'verified'];
    const result = run(command, false, isolatedHome);
    assert.match(result.error, scenario === 'discarded' ? /discarded.*terminal/ : /Agent.*metadata/);
    assert.equal(fs.readFileSync(isolatedStatePath, 'utf8'), before);
  }
});
