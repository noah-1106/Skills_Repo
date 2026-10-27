import { extractText } from './router.js';
const readHistory = (state, contextKey, agentId) => {
  const entries = state.histories?.[`${contextKey}:${agentId}`];
  return Array.isArray(entries) ? entries.map(x => ({ ...x })) : [];
};

export const DEFAULT_PENDING_MAX_ATTEMPTS = 10;
export const DEFAULT_PENDING_MAX_AGE_HOURS = 24;

export function retryPolicy(config = {}) {
  const attempts = Number(config.pendingMaxAttempts);
  const ageHours = Number(config.pendingMaxAgeHours);
  const maxAttempts = Number.isSafeInteger(attempts) && attempts > 0 ? attempts : DEFAULT_PENDING_MAX_ATTEMPTS;
  const maxAgeHours = Number.isFinite(ageHours) && ageHours > 0 ? ageHours : DEFAULT_PENDING_MAX_AGE_HOURS;
  return { maxAttempts, maxAgeHours, maxAgeMs: maxAgeHours * 60 * 60 * 1000 };
}

export function retryDelayMs(attempts) {
  return Math.min(60_000, 1000 * 2 ** Math.min(Math.max(0, attempts - 1), 6));
}

export function deadLetterSummary(state) {
  return Object.entries(state.deadLetters || {}).map(([key, dead]) => ({
    key, reason: dead.reason, deadAt: dead.deadAt, attempts: dead.attempts || 0,
    lastError: dead.lastError || null, lane: dead.lane || null,
    taskId: dead.taskId || null, agentId: dead.agentId || null,
    invokeState: dead.invokeState || null, discarded: Boolean(dead.discarded),
    discardedAt: dead.discardedAt || null,
  }));
}

export function quarantineReason(state, key, config, now = new Date()) {
  const pending = state.pending?.[key];
  // Uncertain invocation requires a human taskId decision, never an age/attempt shortcut.
  const task = state.tasks?.[key];
  if (!pending || pending.blocked || (task && !task.taskId && ['calling', 'uncertain', 'rejected'].includes(task.invokeState))) return null;
  const policy = retryPolicy(config);
  if ((pending.attempts || 0) >= policy.maxAttempts) return 'max_attempts';
  const queuedAt = Date.parse(pending.queuedAt || '');
  if (Number.isFinite(queuedAt) && now.getTime() - queuedAt >= policy.maxAgeMs) return 'max_age';
  return null;
}

export function quarantineMessage(state, key, reason, now = new Date()) {
  state.deadLetters ||= {};
  if (state.deadLetters[key]) { delete state.pending[key]; return state.deadLetters[key]; }
  const pending = state.pending?.[key] || {};
  const task = state.tasks?.[key] || {};
  const deadAt = now.toISOString();
  const record = {
    message: pending.message || task.message || null,
    attempts: pending.attempts || 0,
    queuedAt: pending.queuedAt || task.queuedAt || null,
    lastError: pending.lastError || task.invokeError || reason,
    lane: pending.lane || task.lane || null,
    seq: pending.seq || task.seq || null,
    blocked: Boolean(pending.blocked),
    reason, deadAt,
    taskId: task.taskId || null, agentId: task.agentId || null,
    invokeState: task.invokeState || null,
    discarded: reason === 'manual_discard',
    discardedAt: reason === 'manual_discard' ? deadAt : null,
  };
  state.deadLetters[key] = record;
  delete state.pending[key];
  return record;
}

export function restoreAgentTaskFromDeadLetter(state, key, options = {}) {
  const dead = state.deadLetters?.[key];
  if (!dead) throw new Error(`No dead-letter message for key ${key}`);
  if (!dead.agentId || !dead.message) throw new Error(`Dead-letter key ${key} lacks Agent or raw-message metadata; refusing to guess a recovery task`);
  if (!dead.lane || !dead.seq || !dead.invokeState || dead.taskId === undefined) {
    throw new Error(`Dead-letter key ${key} lacks recovery metadata (lane/seq/invokeState/taskId)`);
  }
  const history = dead.message && typeof options.readHistory === 'function' ? options.readHistory(dead) : [];
  const task = {
    kind: 'agent', agentId: dead.agentId, text: extractText(dead.message || {}),
    message: dead.message, lane: dead.lane, history, taskId: dead.taskId,
    invokeState: dead.invokeState, reply: null, sentClientIds: [],
    historyCommitted: false, restoredFromDeadLetter: true,
  };
  state.tasks ||= {}; state.tasks[key] = task;
  return task;
}

export function assertRecoveryAllowed(state, key) {
  const dead = state.deadLetters?.[key];
  if (dead?.discarded) throw new Error(`Dead-letter ${key} was explicitly discarded and is terminal; retry/recover are forbidden`);
}

export function retryMessage(state, key, options = {}) {
  const pending = state.pending?.[key];
  const dead = state.deadLetters?.[key];
  let task = state.tasks?.[key];
  if (!pending && !dead) throw new Error(`No pending or dead-letter message for key ${key}`);
  assertRecoveryAllowed(state, key);
  if (state.processed?.includes(key)) throw new Error(`Message ${key} is already processed; refusing to replay`);
  const taskId = task?.taskId || dead?.taskId || null;
  const invokeState = task?.invokeState || dead?.invokeState || null;
  const isAgentTask = task ? (task.kind || 'agent') === 'agent' : Boolean(dead?.agentId);
  if (isAgentTask && !taskId && ['calling', 'uncertain', 'rejected'].includes(invokeState)) {
    throw new Error(`Message ${key} has uncertain/rejected invocation; use recover --key ${key} --task-id VERIFIED_ID instead of retry`);
  }
  if (!task && dead) task = restoreAgentTaskFromDeadLetter(state, key, {
    readHistory: dead => {
      const route = typeof options.route === 'function' ? options.route(dead.message) : null;
      const contextKey = route?.contextKey || `${options.botId}:${dead.message.from_user_id}`;
      return readHistory(state, contextKey, dead.agentId);
    },
  });
  if (!task && dead) throw new Error(`Message ${key} has no recoverable task metadata; state was not changed`);
  const previousAttempts = pending?.attempts ?? dead?.attempts ?? 0;
  const seq = pending?.seq || dead?.seq || task?.seq || (state.nextSeq = (state.nextSeq || 0) + 1);
  state.pending[key] = {
    message: pending?.message || dead?.message || task?.message,
    attempts: 0, lastError: null, erroredAt: null, blocked: false,
    lane: pending?.lane || dead?.lane || task?.lane,
    seq, queuedAt: new Date().toISOString(), nextRetryAt: null, manuallyRetried: true,
  };
  if (task) task.seq ||= seq;
  delete state.deadLetters[key];
  return { key, status: 'requeued', previousAttempts, source: pending ? 'pending' : 'deadLetters' };
}

export function discardMessage(state, key, confirmed = false) {
  if (!confirmed) throw new Error('Discard requires --yes; the message is archived as a dead letter, not erased');
  const task = state.tasks?.[key];
  const dead = state.deadLetters?.[key];
  const taskId = task?.taskId || dead?.taskId || null;
  const invokeState = task?.invokeState || dead?.invokeState || null;
  const isAgentTask = task ? (task.kind || 'agent') === 'agent' : Boolean(dead?.agentId);
  if (isAgentTask && !taskId && ['calling', 'uncertain', 'rejected'].includes(invokeState)) {
    throw new Error(`Message ${key} has uncertain/rejected invocation; recover --key ${key} --task-id VERIFIED_ID before deciding whether to discard`);
  }
  if (dead) {
    dead.discarded = true; dead.discardedAt ||= new Date().toISOString();
    return { key, status: 'discarded', source: 'deadLetters', preserved: true };
  }
  if (!state.pending?.[key]) throw new Error(`No pending or dead-letter message for key ${key}`);
  quarantineMessage(state, key, 'manual_discard');
  return { key, status: 'discarded', source: 'pending', preserved: true };
}
