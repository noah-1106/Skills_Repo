import fs from 'node:fs';
import crypto from 'node:crypto';
import { ExFlowerClient } from './exflower.js';
import { routeMessage, extractText, messageKey } from './router.js';
import { getUpdates, sendLongText } from './weixin.js';
import { paths, loadConfig, loadCredentials, loadState, saveState, writeJson, readJson } from './store.js';
import { quarantineReason, quarantineMessage, retryDelayMs, restoreAgentTaskFromDeadLetter, assertRecoveryAllowed } from './delivery.js';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const log = message => console.log(`${new Date().toISOString()} ${message}`);
export const HISTORY_TURNS = 12;
export const HISTORY_MESSAGE_CHARS = 6000;
const TERMINAL = new Set(['sent', 'duplicate', 'ignored', 'unsupported', 'unauthorized']);
export function historyKey(contextKey, agentId) { return `${contextKey}:${agentId}`; }
function clipHistoryText(value) {
  const text = String(value || '').trim();
  if (text.length <= HISTORY_MESSAGE_CHARS) return text;
  let clipped = text.slice(0, HISTORY_MESSAGE_CHARS);
  if (/[\uD800-\uDBFF]$/.test(clipped)) clipped = clipped.slice(0, -1);
  return `${clipped}\n…（历史消息已截断）`;
}
function normalizeResult(result) {
  return typeof result === 'string' ? { content: result, steps: [], thinking: '' } : result;
}
function historySteps(steps) {
  return (Array.isArray(steps) ? steps : []).filter(step => step && step.name).map(step => {
    const text = typeof step.result === 'string' ? step.result : JSON.stringify(step.result ?? '');
    return { ...step, result: text.length > 3000 ? `${text.slice(0, 3000)}\n…（历史工具结果已截断）` : text };
  });
}
export function readHistory(state, contextKey, agentId) {
  const entries = state.histories?.[historyKey(contextKey, agentId)];
  return Array.isArray(entries) ? entries.map(x => ({
    role: x.role, content: x.content,
    ...(Array.isArray(x.steps) && x.steps.length ? { steps: x.steps } : {}),
    ...(x.thinking ? { thinking: x.thinking } : {}),
  })) : [];
}
export function appendHistory(state, contextKey, agentId, userText, result) {
  state.histories ||= {};
  const key = historyKey(contextKey, agentId);
  const normalized = normalizeResult(result);
  const previous = readHistory(state, contextKey, agentId);
  const turn = [
    { role: 'user', content: clipHistoryText(userText), steps: [], thinking: '' },
    { role: 'assistant', content: clipHistoryText(normalized.content), steps: historySteps(normalized.steps), thinking: normalized.thinking || '' },
  ].filter(x => x.content);
  // Always append a complete turn, then retain complete recent turns.
  state.histories[key] = [...previous, ...turn].slice(-HISTORY_TURNS * 2);
}
export function processedSet(state) { return new Set(state.processed || []); }
export function pendingSummary(state) {
  const done = processedSet(state);
  const keys = new Set(Object.keys(state.pending || {}).filter(key => !done.has(key)));
  for (const [key, task] of Object.entries(state.tasks || {})) {
    if (task.message && !done.has(key) && !state.deadLetters?.[key]) keys.add(key);
  }
  return [...keys].map(key => {
    const pending = state.pending?.[key] || { attempts: 0, recovered: true };
    if (!state.pending?.[key]) pending.lastError ||= task.invokeError || null;
    const task = state.tasks?.[key] || {};
    return {
      key, attempts: pending.attempts, lastError: pending.lastError || task.invokeError || null,
      kind: task.kind || (task.agentId ? 'agent' : null), agentId: task.agentId || null,
      invokeState: task.invokeState || null, taskId: task.taskId || null,
      lane: pending.lane || task.lane || null, blocked: Boolean(pending.blocked),
      queuedAt: pending.queuedAt || null, nextRetryAt: pending.nextRetryAt || null,
      sentChunks: Array.isArray(task.sentClientIds) ? task.sentClientIds.length : 0,
    };
  });
}
export function attachPendingTask(state, key, taskId, persist = () => {}, options = {}) {
  let task = state.tasks?.[key];
  const pending = state.pending?.[key];
  const dead = state.deadLetters?.[key];
  if (!pending && !dead && !task?.message) throw new Error(`No recoverable message for key ${key}`);
  assertRecoveryAllowed(state, key);
  if (!task) task = restoreAgentTaskFromDeadLetter(state, key, {
    readHistory: dead => {
      const route = typeof options.route === 'function' ? options.route(dead.message) : null;
      const contextKey = route?.contextKey || `${options.botId}:${dead.message.from_user_id}`;
      return readHistory(state, contextKey, dead.agentId);
    },
  });
  if (!task || (task.kind || 'agent') !== 'agent') throw new Error(`Pending key ${key} is not an Agent task`);
  if (task.taskId && task.taskId !== taskId) throw new Error(`Pending key ${key} already has a different taskId`);
  if (!String(taskId || '').trim()) throw new Error('taskId is required');
  task.taskId = String(taskId).trim(); task.invokeState = 'accepted'; task.invokeError = null;
  const source = pending || dead || {};
  const seq = source.seq || task.seq || (state.nextSeq = (state.nextSeq || 0) + 1);
  task.seq = seq;
  state.pending[key] = {
    message: source.message || task.message, attempts: 0, lastError: null, erroredAt: null,
    blocked: false, lane: source.lane || task.lane, seq,
    queuedAt: new Date().toISOString(), nextRetryAt: null,
  };
  delete state.deadLetters[key];
  persist(state);
  return { key, taskId: task.taskId, agentId: task.agentId, status: 'attached', source: pending ? 'pending' : dead ? 'deadLetters' : 'tasks' };
}
export class Connector {
  constructor({ config, credentials, state, exflower, sender, logger = log, persist = saveState, signal = null }) {
    this.config = config; this.credentials = credentials; this.state = state;
    this.state.histories ||= {}; this.state.tasks ||= {}; this.state.pending ||= {}; this.state.deadLetters ||= {}; this.state.processed ||= [];
    this.exflower = exflower || new ExFlowerClient(config);
    this.sender = sender || ((to, text, token, options) => sendLongText(credentials, to, text, token, options));
    this.logger = logger; this.persist = persist; this.signal = signal;
    // One worker per contact+Agent lane. Workers never block the iLink polling loop.
    this.lanes = new Map();
  }
  contextKey(from) { return `${this.credentials.ilink_bot_id}:${from}`; }
  allowed(from) {
    if (from === this.credentials.ilink_user_id) return true;
    return Array.isArray(this.config.allowFrom) && this.config.allowFrom.length > 0 && this.config.allowFrom.includes(from);
  }
  laneFor(message, task = null) {
    const contextKey = this.contextKey(String(message.from_user_id || ''));
    if (task?.lane) return task.lane;
    return `${contextKey}:${task?.agentId || 'local'}`;
  }
  prepare(message, { deferHistory = false } = {}) {
    const key = messageKey(message);
    if (!key) throw new Error('Recovered task has no durable message key');
    if (this.state.processed.includes(key)) return { status: 'duplicate', key };
    if (this.state.deadLetters[key]) return { status: 'dead_letter', key, reason: this.state.deadLetters[key].reason };
    if (message.message_type === 2 || message.group_id) return { status: 'ignored', key };
    const from = String(message.from_user_id || '');
    if (!from || !this.allowed(from)) return { status: 'unauthorized', key };
    if (!extractText(message)) return { status: 'unsupported', key };
    const contextKey = this.contextKey(from);
    let task = this.state.tasks[key] || null;
    // A retry must not replace a newer context token with its older message token.
    if (message.context_token && (!task || !this.state.contexts[contextKey])) this.state.contexts[contextKey] = message.context_token;
    const token = this.state.contexts[contextKey] || message.context_token;
    if (task) task.kind ||= task.agentId ? 'agent' : 'local';
    // Cached deliveries retain their original route/reply even if bindings or Agent lists change.
    const route = task
      ? (task.kind === 'local' ? { reply: task.reply } : { agentId: task.agentId, text: task.text })
      : routeMessage(extractText(message), this.config.agents, this.state.bindings[contextKey]?.agentId);
    // Binding is updated once at arrival/prepare time, never again when an old task finishes.
    if (!task && route.agentId && route.bind) this.state.bindings[contextKey] = { agentId: route.agentId, updatedAt: new Date().toISOString() };
    if (!task && route.agentId && route.text) {
      task = this.state.tasks[key] = {
        kind: 'agent', agentId: route.agentId, text: route.text, message,
        lane: `${contextKey}:${route.agentId}`,
        history: deferHistory ? null : readHistory(this.state, contextKey, route.agentId),
        taskId: null, invokeState: 'new', reply: null, sentClientIds: [], historyCommitted: false,
      };
    } else if (!task && route.reply) {
      task = this.state.tasks[key] = {
        kind: 'local', agentId: null, text: extractText(message), message, reply: route.reply,
        lane: `${contextKey}:local`, sentClientIds: [], historyCommitted: false,
      };
    }
    if (!task) return { status: 'ignored', key };
    task.sentClientIds ||= [];
    task.lane ||= `${contextKey}:${task.agentId || 'local'}`;
    return { key, from, contextKey, token, task };
  }
  async process(message) {
    const prepared = this.prepare(message);
    if (prepared.status) return prepared;
    const { key, from, contextKey, token, task } = prepared;
    // History is snapshot when this lane reaches the message, not when it was queued.
    if (task.kind === 'agent' && task.history == null) task.history = readHistory(this.state, contextKey, task.agentId);
    task.history ||= [];
    this.persist(this.state);
    if (task.kind === 'agent') {
      if (!task.taskId) {
        // "calling" without a taskId may mean a crash after the server accepted the task.
        if (['calling', 'uncertain', 'rejected'].includes(task.invokeState)) {
          return { status: 'blocked', reason: task.invokeState === 'calling' ? 'invoke_uncertain' : `invoke_${task.invokeState}`, agentId: task.agentId };
        }
        task.invokeState = 'calling'; this.persist(this.state);
        try {
          task.taskId = await this.exflower.invoke(task.agentId, task.text, task.history, { signal: this.signal });
          task.invokeState = 'accepted'; task.invokeError = null; this.persist(this.state);
        } catch (error) {
          task.invokeState = error.permanent ? 'rejected' : (error.invokeUncertain ? 'uncertain' : 'failed');
          task.invokeError = error.message; this.persist(this.state);
          throw error;
        }
      }
      if (task.reply == null) {
        const result = normalizeResult(await this.exflower.waitForResult(task.taskId, { detailed: true, signal: this.signal }));
        task.reply = result.content;
        task.resultSteps = historySteps(result.steps);
        task.resultThinking = result.thinking || '';
        this.persist(this.state);
      }
    }
    const prefix = `exf-weixin:${crypto.createHash('sha256').update(key).digest('hex').slice(0, 24)}`;
    await this.sender(from, task.reply, token, {
      clientIdPrefix: prefix,
      sentClientIds: task.sentClientIds,
      signal: this.signal,
      onSent: result => { task.sentClientIds.push(result.clientId); this.persist(this.state); },
    });
    if (task.kind === 'agent' && !task.historyCommitted) {
      appendHistory(this.state, contextKey, task.agentId, task.text, {
        content: task.reply, steps: task.resultSteps || [], thinking: task.resultThinking || '',
      });
      task.historyCommitted = true;
    }
    this.state.processed.push(key);
    delete this.state.tasks[key];
    return { status: 'sent', agentId: task.agentId || null, taskType: task.kind };
  }
  enqueue(messages) {
    const immediate = [], lanes = new Set();
    for (const message of messages) {
      const key = messageKey(message);
      if (this.state.deadLetters[key]) {
        immediate.push({ status: 'dead_letter', key, reason: this.state.deadLetters[key].reason });
        continue;
      }
      if (this.state.pending[key]) {
        lanes.add(this.state.pending[key].lane || this.laneFor(message, this.state.tasks[key]));
        continue;
      }
      const prepared = this.prepare(message, { deferHistory: true });
      if (prepared.status) { immediate.push(prepared); continue; }
      const { task } = prepared;
      const seq = (this.state.nextSeq || 0) + 1; this.state.nextSeq = seq; task.seq = seq;
      this.state.pending[key] = { message, attempts: 0, lastError: null, blocked: false, lane: task.lane, seq, queuedAt: new Date().toISOString(), nextRetryAt: null };
      lanes.add(task.lane);
    }
    // Durable queue (including raw messages) is committed before workers or sync cursor advance.
    this.persist(this.state);
    const jobs = [...lanes].map(lane => this.startLane(lane));
    return { immediate, jobs };
  }
  async ingest(messages) {
    const { immediate, jobs } = this.enqueue(messages);
    const results = await Promise.all(jobs);
    return [...immediate, ...results.flat()];
  }
  recoverPending() {
    let changed = false;
    for (const key of Object.keys(this.state.pending)) {
      if (processedSet(this.state).has(key)) {
        delete this.state.pending[key];
        changed = true;
      }
    }
    for (const [key, task] of Object.entries(this.state.tasks)) {
      if (this.state.pending[key] || this.state.deadLetters[key] || !task.message || this.state.processed.includes(key)) continue;
      const seq = task.seq || (this.state.nextSeq = (this.state.nextSeq || 0) + 1);
      task.seq = seq;
      this.state.pending[key] = {
        message: task.message, attempts: 0, recovered: true,
        lastError: task.invokeError || 'Recovered cached delivery after restart',
        blocked: ['calling', 'uncertain', 'rejected'].includes(task.invokeState),
        lane: this.laneFor(task.message, task), seq, queuedAt: new Date().toISOString(), nextRetryAt: null,
      };
      changed = true;
    }
    for (const [key, pending] of Object.entries(this.state.pending)) {
      const task = this.state.tasks[key];
      if (!pending.lane) { pending.lane = this.laneFor(pending.message, task); changed = true; }
      if (!pending.seq) { pending.seq = (this.state.nextSeq = (this.state.nextSeq || 0) + 1); changed = true; }
      if (!Number.isSafeInteger(pending.attempts) || pending.attempts < 0) { pending.attempts = 0; changed = true; }
      if (!pending.queuedAt) { pending.queuedAt = new Date().toISOString(); changed = true; }
      if (pending.nextRetryAt === undefined) { pending.nextRetryAt = null; changed = true; }
      if (task && !task.taskId && ['calling', 'uncertain', 'rejected'].includes(task.invokeState) && !pending.blocked) { pending.blocked = true; changed = true; }
    }
    if (changed) this.persist(this.state);
  }
  kick() {
    this.recoverPending();
    const lanes = new Set(Object.values(this.state.pending).filter(x => !x.blocked).map(x => x.lane));
    return [...lanes].map(lane => this.startLane(lane));
  }
  async retryPending() {
    const results = await Promise.all(this.kick());
    return results.flat();
  }
  startLane(lane) {
    if (this.lanes.has(lane)) return this.lanes.get(lane);
    const promise = this.pumpLane(lane).catch(error => {
      this.state.lastError = { lane, message: error.message, at: new Date().toISOString() };
      try { this.persist(this.state); } catch {}
      this.logger(`lane error ${lane}: ${error.message}`);
      return [{ lane, status: 'retry', error: error.message }];
    });
    this.lanes.set(lane, promise);
    promise.finally(() => { if (this.lanes.get(lane) === promise) this.lanes.delete(lane); }).catch(() => {});
    return promise;
  }
  syncLastError() {
    const errors = Object.entries(this.state.pending).filter(([, x]) => x.lastError);
    if (errors.length) {
      const [key, pending] = errors[errors.length - 1];
      this.state.lastError = { key, message: pending.lastError, at: pending.erroredAt || new Date().toISOString() };
      return;
    }
    const dead = Object.entries(this.state.deadLetters).filter(([, x]) => x.lastError).sort((a, b) => String(a[1].deadAt).localeCompare(String(b[1].deadAt)));
    if (!dead.length) { this.state.lastError = null; return; }
    const [key, record] = dead[dead.length - 1];
    this.state.lastError = { key, message: record.lastError, at: record.deadAt, deadLetter: true, reason: record.reason };
  }
  async waitRetry(ms) {
    const deadline = Date.now() + ms;
    while (Date.now() < deadline) {
      if (this.signal?.aborted) return false;
      await sleep(Math.min(250, deadline - Date.now()));
    }
    return !this.signal?.aborted;
  }
  async pumpLane(lane) {
    const results = [];
    while (true) {
      const entry = Object.entries(this.state.pending)
        .filter(([, x]) => x.lane === lane)
        .sort((a, b) => (a[1].seq || 0) - (b[1].seq || 0))[0];
      if (!entry) break;
      const [key, pending] = entry;
      if (pending.blocked) break;
      const earlyReason = quarantineReason(this.state, key, this.config);
      if (earlyReason) {
        const dead = quarantineMessage(this.state, key, earlyReason);
        this.syncLastError(); this.persist(this.state);
        this.logger(`message dead_letter key=${key} reason=${earlyReason} attempts=${dead.attempts}`);
        results.push({ key, lane, status: 'dead_letter', reason: earlyReason, attempts: dead.attempts });
        continue;
      }
      const retryAt = Date.parse(pending.nextRetryAt || '');
      if (Number.isFinite(retryAt) && retryAt > Date.now()) {
        if (!await this.waitRetry(retryAt - Date.now())) break;
        continue;
      }
      try {
        const result = await this.process(pending.message);
        results.push({ key, lane, ...result });
        if (TERMINAL.has(result.status)) delete this.state.pending[key];
        if (result.status === 'blocked') {
          pending.blocked = true; pending.lastError = result.reason; pending.erroredAt = new Date().toISOString();
        }
        this.syncLastError(); this.persist(this.state);
        this.logger(`message ${JSON.stringify({ key, lane, ...result })}`);
        if (result.status === 'blocked') break;
      } catch (error) {
        pending.attempts = (pending.attempts || 0) + 1;
        pending.lastError = error.message; pending.erroredAt = new Date().toISOString();
        const task = this.state.tasks[key];
        pending.blocked = error.message.startsWith('invoke_uncertain') || Boolean(task && !task.taskId && ['calling', 'uncertain', 'rejected'].includes(task.invokeState));
        this.syncLastError(); this.persist(this.state);
        this.logger(`message retry key=${key} error=${error.message}`);
        const reason = quarantineReason(this.state, key, this.config);
        if (reason) {
          const dead = quarantineMessage(this.state, key, reason);
          this.syncLastError(); this.persist(this.state);
          this.logger(`message dead_letter key=${key} reason=${reason} attempts=${dead.attempts}`);
          results.push({ key, lane, status: 'dead_letter', reason, error: error.message, attempts: dead.attempts });
          continue;
        }
        const delay = pending.blocked ? 0 : retryDelayMs(pending.attempts);
        pending.nextRetryAt = pending.blocked ? null : new Date(Date.now() + delay).toISOString();
        this.persist(this.state);
        results.push({ key, lane, status: 'retry', error: error.message, attempts: pending.attempts, blocked: pending.blocked, nextRetryAt: pending.nextRetryAt });
        if (pending.blocked || !await this.waitRetry(delay)) break;
      }
    }
    return results;
  }
}
export async function runDaemon({ signal, once = false }) {
  const config = loadConfig(); const credentials = loadCredentials(); const state = loadState();
  if (!credentials?.token) throw new Error('Missing credentials; run login first');
  const connector = new Connector({ config, credentials, state, signal });
  writeJson(paths().pid, { pid: process.pid, startedAt: new Date().toISOString() }, 0o600);
  log(`daemon started account=${credentials.ilink_bot_id} agents=${Object.keys(config.agents).length}`);
  try {
    connector.kick(); // Recovery runs in lanes; never await a slow Agent before polling iLink.
    while (!signal?.aborted) {
      try {
        connector.config = loadConfig();
        const update = await getUpdates(credentials, state.syncBuf, { timeoutMs: 35_000, signal });
        const messages = update.msgs || [];
        if (messages.length) {
          const { immediate } = connector.enqueue(messages);
          for (const result of immediate) log(`message ${JSON.stringify(result)}`);
          // enqueue() has already persisted every raw message/task; only now advance the cursor.
          state.syncBuf = update.get_updates_buf || state.syncBuf; saveState(state);
        }
        connector.kick();
        if (once) return await connector.retryPending();
        await sleep(250);
      } catch (error) {
        if (signal?.aborted) log('daemon abort requested');
        else { state.lastError = { message: error.message, at: new Date().toISOString() }; saveState(state); log(`getupdates: ${error.message}`); await sleep(1000); }
      }
    }
  } finally {
    // All production waits carry the abort signal; let lane cleanup finish before exiting.
    await Promise.allSettled([...connector.lanes.values()]);
    // Never remove a replacement daemon's PID during an old process's delayed shutdown.
    try { if (readJson(paths().pid)?.pid === process.pid) fs.unlinkSync(paths().pid); } catch {}
    log('daemon stopped');
  }
}
