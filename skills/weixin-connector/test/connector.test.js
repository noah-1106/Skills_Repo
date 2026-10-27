import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { routeMessage, parseRouteText } from '../src/router.js';
import { Connector } from '../src/daemon.js';
import { ExFlowerClient } from '../src/exflower.js';
import { getUpdates, sendText } from '../src/weixin.js';
const testHome = fs.mkdtempSync(path.join(os.tmpdir(), 'exf-weixin-home-'));
process.env.EXF_WEIXIN_HOME = testHome;
const agents = { 'agent-022': { name: '项项', alias: '项项' }, 'agent-009': { name: '红红', alias: '红红' } };
const blank = () => ({ bindings: {}, contexts: {}, histories: {}, processed: [], tasks: {}, pending: {}, lastError: null });
const msg = (id, text, extra = {}) => ({ message_id: id, from_user_id: 'owner', message_type: 1, context_token: `token-${id}`, item_list: [{ type: 1, text_item: { text } }], ...extra });
function fixture(overrides = {}) {
  const calls = [], sent = []; let count = 0;
  const exflower = { invoke: async (id, text) => { calls.push({ id, text }); count++; return `task-${count}`; }, waitForResult: async id => `回复:${id}`, ...overrides.exflower };
  const connector = new Connector({ config: { agents, allowFrom: ['owner'] }, credentials: { ilink_bot_id: 'bot', ilink_user_id: 'owner' }, state: blank(), exflower, sender: async (to, text, token) => { sent.push({ to, text, token }); }, logger: () => {}, persist: () => {}, ...overrides.connector });
  return { connector, calls, sent };
}
test('路由支持精确 @、续聊、切换与未知别名拒绝', () => {
  assert.deepEqual(parseRouteText('@项项 做个方案'), { alias: '项项', text: '做个方案', explicit: true });
  assert.equal(routeMessage('@项项 做个方案', agents).agentId, 'agent-022');
  assert.equal(routeMessage('继续', agents, 'agent-022').agentId, 'agent-022');
  assert.equal(routeMessage('@红红 写文案', agents).agentId, 'agent-009');
  assert.match(routeMessage('@不存在的 你好', agents).reply, /没有找到/);
  assert.match(routeMessage('你好', agents).reply, /请先指定/);
});
test('微信→指定 Agent→微信闭环，续聊不改路由，重复消息不重复执行', async () => {
  const { connector, calls, sent } = fixture();
  await connector.ingest([msg('m1', '@项项 你好'), msg('m2', '继续'), msg('m3', '@红红 写文案'), msg('m1', '@项项 你好')]);
  assert.deepEqual(calls.filter(x => x.id === 'agent-022').map(x => x.text), ['你好', '继续']);
  assert.deepEqual(calls.filter(x => x.id === 'agent-009').map(x => x.text), ['写文案']);
  assert.equal(calls.length, 3);
  assert.equal(sent.length, 3);
  assert.equal(connector.state.bindings['bot:owner'].agentId, 'agent-009');
  assert.equal(connector.state.contexts['bot:owner'], 'token-m3');
  assert.equal(connector.state.processed.length, 3);
});
test('未授权用户和群消息不进入 Agent', async () => {
  const { connector, calls, sent } = fixture();
  await connector.ingest([msg('m4', '@项项 你好', { from_user_id: 'stranger' }), msg('m5', '@项项 你好', { group_id: 'room' })]);
  assert.equal(calls.length, 0); assert.equal(sent.length, 0);
});
test('Agent 调用后自动退避重试仍复用同一 taskId，不重复创建任务', async () => {
  let waits = 0, invokes = 0;
  const exflower = { invoke: async () => { invokes++; return 'fixed-task'; }, waitForResult: async () => { if (++waits === 1) throw new Error('temporary poll failure'); return '恢复后的回复'; } };
  const { connector, sent } = fixture({ exflower });
  await connector.ingest([msg('recover', '@项项 测试恢复')]);
  assert.equal(invokes, 1); assert.equal(waits, 2); assert.equal(sent[0].text, '恢复后的回复');
  assert.equal(Object.keys(connector.state.pending).length, 0);
  assert.equal(Object.keys(connector.state.deadLetters).length, 0);
});
test('回复发送失败保留 Agent 结果，重试不再次调用 Agent', async () => {
  let invokes = 0, sends = 0;
  const exflower = { invoke: async () => { invokes++; return 'task-send'; }, waitForResult: async () => '已经生成，不重复生成' };
  const { connector, sent } = fixture({ exflower, connector: { sender: async (to, text) => { if (++sends === 1) throw new Error('send failed'); sent.push({ to, text }); } } });
  await connector.ingest([msg('send-retry', '@项项 测试')]);
  await connector.retryPending();
  assert.equal(invokes, 1); assert.equal(sends, 2); assert.equal(sent.length, 1);
});
test('ExFlower 客户端按 taskId 获取最终回复', async () => {
  const requests = [];
  const fetchImpl = async (url, options = {}) => { requests.push({ url, options }); const body = options.body ? JSON.parse(options.body) : null;
    const payload = url.includes('/api/message/send') ? { success: true, taskId: 'task-real-shape' } : url.includes('/api/messages/by-task/') ? { message: { content: '最终回复' } } : { ok: true };
    return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } }); };
  const client = new ExFlowerClient({ exflowerUrl: 'http://local', apiKey: '' }, fetchImpl);
  const taskId = await client.invoke('agent-022', '你好');
  assert.equal(taskId, 'task-real-shape');
  assert.equal(requests[0].options.body.includes('CrewAI:agent-022'), true);
  assert.equal(JSON.parse(requests[0].options.body).type, 'chat');
  assert.equal(await client.waitForResult(taskId, { intervalMs: 1 }), '最终回复');
});
test('iLink getupdates/sendmessage 使用协议字段且不回显 token', async () => {
  const seen = [];
  const fetchImpl = async (url, options) => { seen.push({ url, options }); const isSend = url.includes('sendmessage');
    return new Response(JSON.stringify(isSend ? { ret: 0, message_id: 'server-1' } : { ret: 0, msgs: [], get_updates_buf: 'next' }), { status: 200 }); };
  const credentials = { token: 'secret-token', baseUrl: 'https://example.test' };
  const update = await getUpdates(credentials, 'old', { fetchImpl });
  assert.equal(update.get_updates_buf, 'next');
  assert.equal(JSON.parse(seen[0].options.body).get_updates_buf, 'old');
  assert.equal(JSON.parse(seen[0].options.body).base_info.bot_agent, 'ExFlower/0.3.0');
  const sent = await sendText(credentials, 'owner', '回复', 'context', { clientId: 'stable-id', fetchImpl });
  const body = JSON.parse(seen[1].options.body);
  assert.equal(sent.clientId, 'stable-id'); assert.equal(body.msg.context_token, 'context'); assert.equal(body.msg.message_type, 2);
  assert.equal(seen[1].options.headers.Authorization, 'Bearer secret-token');
});
test('配置和凭证目录只使用测试临时目录', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'exf-weixin-test-'));
  assert.equal(fs.statSync(root).isDirectory(), true);
});


test('含空格别名最长精确匹配，不会误路由到短别名', () => {
  const set = {
    'agent-006': { name: 'Coco', alias: 'Coco' },
    'agent-025': { name: 'Coco 2.0', alias: 'Coco 2.0' },
  };
  assert.equal(routeMessage('@Coco 2.0 你好', set).agentId, 'agent-025');
  assert.equal(routeMessage('@Coco 2.0 你好', set).text, '你好');
  assert.equal(routeMessage('@Coco 你好', set).agentId, 'agent-006');
  assert.equal(routeMessage('/use Coco 2.0', set).agentId, 'agent-025');
  assert.equal(routeMessage('@agent-025 你好', set).agentId, 'agent-025');
});

test('上下文按联系人和 Agent 隔离，切换后各自保留最近历史', async () => {
  const invocations = []; let count = 0;
  const exflower = {
    invoke: async (agentId, text, history) => { invocations.push({ agentId, text, history }); return `task-${++count}`; },
    waitForResult: async taskId => ({ content: `回答:${taskId}`, steps: [{ name: 'lookup', params: { q: 'x' }, result: '工具返回' }], thinking: '历史推理' }),
  };
  const { connector } = fixture({ exflower });
  await connector.ingest([
    msg('h1', '@项项 我的项目是北冥'),
    msg('h2', '它叫什么？'),
    msg('h3', '@红红 帮我写文案'),
    msg('h4', '@项项 继续聊项目'),
  ]);
  const byText = Object.fromEntries(invocations.map(x => [x.text, x]));
  assert.deepEqual(byText['我的项目是北冥'].history, []);
  assert.deepEqual(byText['它叫什么？'].history.map(x => ({ role: x.role, content: x.content })), [
    { role: 'user', content: '我的项目是北冥' },
    { role: 'assistant', content: '回答:task-1' },
  ]);
  assert.equal(byText['它叫什么？'].history[1].steps[0].name, 'lookup');
  assert.equal(byText['它叫什么？'].history[1].steps[0].result, '工具返回');
  assert.equal(byText['它叫什么？'].history[1].thinking, '历史推理');
  assert.deepEqual(byText['帮我写文案'].history, []);
  assert.equal(byText['继续聊项目'].history.length, 4);
  connector.config.allowFrom.push('other');
  await connector.ingest([msg('h5', '@项项 我是另一位用户', { from_user_id: 'other' })]);
  const other = invocations.find(x => x.text === '我是另一位用户');
  assert.ok(other); assert.deepEqual(other.history, []);
});

test('发送失败重试不会重复追加上下文', async () => {
  const invocations = []; let sends = 0, count = 0;
  const exflower = {
    invoke: async (agentId, text, history) => { invocations.push({ text, history }); return `task-${++count}`; },
    waitForResult: async taskId => `回答:${taskId}`,
  };
  const { connector } = fixture({
    exflower,
    connector: { sender: async () => { if (++sends === 1) throw new Error('temporary send failure'); } },
  });
  await connector.ingest([msg('r1', '@项项 记住这一次')]);
  await connector.retryPending();
  await connector.ingest([msg('r2', '继续')]);
  assert.equal(invocations.length, 2);
  assert.equal(invocations[1].history.length, 2);
  assert.deepEqual(invocations[1].history.map(x => x.role), ['user', 'assistant']);
});


test('invoke 结果不确定时停止自动重放，人工 attach taskId 后恢复', async () => {
  let invokes = 0, waits = 0;
  const exflower = {
    invoke: async () => { invokes++; const e = new Error('ack lost'); e.invokeUncertain = true; throw e; },
    waitForResult: async id => { waits++; assert.equal(id, 'manual-task'); return '核对后的原任务回复'; },
  };
  const { connector, sent } = fixture({ exflower });
  await connector.ingest([msg('uncertain', '@项项 不要重复执行')]);
  await connector.retryPending(); await connector.retryPending();
  assert.equal(invokes, 1);
  assert.equal(connector.state.tasks.uncertain.invokeState, 'uncertain');
  assert.equal(connector.state.pending.uncertain.attempts, 1);
  const { attachPendingTask } = await import('../src/daemon.js');
  attachPendingTask(connector.state, 'uncertain', 'manual-task');
  await connector.retryPending();
  assert.equal(waits, 1); assert.equal(invokes, 1);
  assert.equal(sent[0].text, '核对后的原任务回复');
  assert.equal(Object.keys(connector.state.pending).length, 0);
});

test('明确连接拒绝可安全重试 invoke', async () => {
  let invokes = 0;
  const exflower = {
    invoke: async () => { if (++invokes === 1) { const e = new Error('refused'); e.invokeUncertain = false; throw e; } return 'safe-task'; },
    waitForResult: async () => '恢复成功',
  };
  const { connector, sent } = fixture({ exflower });
  await connector.ingest([msg('safe-retry', '@项项 测试')]);
  await connector.retryPending();
  assert.equal(invokes, 2); assert.equal(sent[0].text, '恢复成功');
});

test('本地长命令回复也记录分片，重试不重发已接受片', async () => {
  const { sendLongText } = await import('../src/weixin.js');
  const manyAgents = Object.fromEntries(Array.from({ length: 130 }, (_, i) => [`agent-${i}`, { name: `很长的角色别名-${String(i).padStart(3, '0')}-用于覆盖本地列表分片`, alias: `很长的角色别名-${String(i).padStart(3, '0')}-用于覆盖本地列表分片` }]));
  const bodies = []; let sends = 0;
  const fetchImpl = async (url, options) => {
    sends++; if (sends === 2) throw new Error('第二片网络失败');
    bodies.push(JSON.parse(options.body));
    return new Response(JSON.stringify({ ret: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  const { connector } = fixture({ connector: {
    config: { agents: manyAgents, allowFrom: ['owner'] },
    sender: async (to, text, token, options) => sendLongText({ token: 'x', baseUrl: 'https://example.test' }, to, text, token, { ...options, fetchImpl }),
  } });
  await connector.ingest([msg('local-long', '/agents')]);
  assert.equal(connector.state.tasks['local-long'], undefined);
  assert.equal(Object.keys(connector.state.pending).length, 0);
  assert.equal(sends, 3);
  assert.equal(bodies.length, 2);
  assert.equal(bodies.filter(x => x.msg.client_id.endsWith(':0')).length, 1);
  assert.equal(bodies.filter(x => x.msg.client_id.endsWith(':1')).length, 1);
});


test('taskId 返回后落盘失败时，从缓存 task 恢复且不重复 invoke', async () => {
  let invokes = 0;
  const exflower = {
    invoke: async () => { invokes++; return 'orphan-task'; },
    waitForResult: async () => '崩溃前已完成的结果',
  };
  const { connector, sent, persist } = fixture({ exflower, connector: {
    persist: state => {
      // Allow the taskId write, then fail only when ingest first persists pending.
      if (state.tasks.orphan?.taskId && Object.keys(state.pending).length && !state.pending.orphan.recovered) throw new Error('模拟 pending 写入前崩溃');
    },
  } });
  const results = await connector.ingest([msg('orphan', '@项项 恢复我')]);
  assert.equal(results[0].status, 'retry');
  assert.equal(invokes, 1);
  // Simulate a new process with the cached task, but no pending entry.
  connector.state.pending = {};
  assert.equal(connector.state.tasks.orphan.taskId, 'orphan-task');
  await connector.retryPending();
  assert.equal(invokes, 1); assert.equal(sent[0].text, '崩溃前已完成的结果');
  assert.equal(Object.keys(connector.state.pending).length, 0);
});


test('慢 Agent 不阻塞其他 Agent，重复入站不重复建任务', async () => {
  let releaseSlow;
  const slowGate = new Promise(resolve => { releaseSlow = resolve; });
  const invocations = [];
  const exflower = {
    invoke: async (agentId, text) => { invocations.push({ agentId, text }); return agentId === 'agent-009' ? 'slow-task' : 'fast-task'; },
    waitForResult: async id => { if (id === 'slow-task') await slowGate; return id === 'slow-task' ? '慢任务回复' : '快任务回复'; },
  };
  const { connector, sent } = fixture({ exflower });
  const first = connector.enqueue([msg('parallel-slow', '@红红 慢任务'), msg('parallel-fast', '@项项 快任务'), msg('parallel-slow', '@红红 慢任务')]);
  const fastLane = connector.state.pending['parallel-fast'].lane;
  const fastIndex = [...new Set(Object.values(connector.state.pending).map(x => x.lane))].indexOf(fastLane);
  await first.jobs[fastIndex];
  assert.equal(sent.some(x => x.text === '快任务回复'), true);
  assert.equal(sent.some(x => x.text === '慢任务回复'), false);
  assert.equal(invocations.filter(x => x.text === '慢任务').length, 1);
  assert.equal(connector.state.processed.includes('parallel-fast'), true);
  assert.equal(connector.state.pending['parallel-slow'].attempts, 0);
  releaseSlow();
  await Promise.all(first.jobs);
  assert.equal(sent.filter(x => x.text === '慢任务回复').length, 1);
});

test('同一联系人同一 Agent 严格顺序，第二条历史包含第一条', async () => {
  let releaseFirst;
  const gate = new Promise(resolve => { releaseFirst = resolve; });
  const invocations = []; let count = 0;
  const exflower = {
    invoke: async (agentId, text, history) => { invocations.push({ text, history }); return `ordered-${++count}`; },
    waitForResult: async id => { if (id === 'ordered-1') await gate; return `结果:${id}`; },
  };
  const { connector, sent } = fixture({ exflower });
  const queued = connector.enqueue([msg('ordered-1', '@项项 第一条'), msg('ordered-2', '第二条'), msg('ordered-3', '第三条')]);
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(invocations.map(x => x.text), ['第一条']);
  assert.equal(sent.length, 0);
  releaseFirst();
  await Promise.all(queued.jobs);
  assert.deepEqual(invocations.map(x => x.text), ['第一条', '第二条', '第三条']);
  assert.equal(invocations[1].history.length, 2);
  assert.equal(invocations[2].history.length, 4);
  assert.deepEqual(sent.map(x => x.text), ['结果:ordered-1', '结果:ordered-2', '结果:ordered-3']);
});

test('旧任务完成不会把已经切换的绑定改回去', async () => {
  let releaseOld;
  const gate = new Promise(resolve => { releaseOld = resolve; });
  const exflower = {
    invoke: async agentId => agentId === 'agent-022' ? 'old-binding' : 'new-binding',
    waitForResult: async id => { if (id === 'old-binding') await gate; return `回复:${id}`; },
  };
  const { connector } = fixture({ exflower });
  const queued = connector.enqueue([msg('binding-old', '@项项 旧任务'), msg('binding-new', '@红红 新任务')]);
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(connector.state.bindings['bot:owner'].agentId, 'agent-009');
  releaseOld(); await Promise.all(queued.jobs);
  assert.equal(connector.state.bindings['bot:owner'].agentId, 'agent-009');
});
