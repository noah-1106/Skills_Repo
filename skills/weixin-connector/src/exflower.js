export function bareAgentId(id) { return String(id || '').replace(/^CrewAI:/i, ''); }

export class ExFlowerClient {
  constructor(config, fetchImpl = globalThis.fetch) {
    this.base = config.exflowerUrl.replace(/\/$/, '');
    this.apiKey = config.apiKey || '';
    this.fetch = fetchImpl;
  }
  headers(json = false) { return { ...(json ? { 'Content-Type': 'application/json' } : {}), ...(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {}) }; }
  async request(url, options = {}) {
    let res;
    try {
      res = await this.fetch(this.base + url, { ...options, headers: { ...this.headers(Boolean(options.body)), ...(options.headers || {}) } });
    } catch (cause) {
      const code = cause?.cause?.code || cause?.code || null;
      // A refused/unresolved connection cannot have reached this ExFlower process.
      const definitelyNotAccepted = ['ECONNREFUSED', 'ENOTFOUND', 'EAI_AGAIN'].includes(code);
      const error = new Error(`ExFlower transport: ${cause.message}${code ? ` (${code})` : ''}`);
      error.code = code; error.invokeUncertain = !definitelyNotAccepted;
      throw error;
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) {
      const error = new Error(data.error || data.message || `ExFlower HTTP ${res.status}`);
      error.httpStatus = res.status;
      error.permanent = [400, 404, 422].includes(res.status);
      // A 5xx or success:false response does not prove that no task was created.
      error.invokeUncertain = !error.permanent;
      throw error;
    }
    return data;
  }
  async health() { return this.request('/health'); }
  async agents() {
    const data = await this.request('/api/agents');
    return (data.agents || data.data || []).map(a => ({ id: bareAgentId(a.id), name: a.name || bareAgentId(a.id), connected: a.connected !== false }));
  }
  async invoke(agentId, content, history = [], options = {}) {
    const controller = new AbortController();
    const signal = options.signal ? AbortSignal.any([controller.signal, options.signal]) : controller.signal;
    const timer = setTimeout(() => controller.abort(new Error('ExFlower invoke acknowledgement timeout')), options.timeoutMs || 30_000);
    try {
      const data = await this.request('/api/message/send', {
        method: 'POST', signal,
        body: JSON.stringify({ agentId: `CrewAI:${bareAgentId(agentId)}`, content, type: 'chat', history }),
      });
      if (!data.taskId) {
        const error = new Error('ExFlower acknowledged without taskId; invocation outcome is uncertain');
        error.invokeUncertain = true; throw error;
      }
      return data.taskId;
    } finally { clearTimeout(timer); }
  }
  async waitForResult(taskId, options = {}) {
    const timeoutMs = options.timeoutMs || 300_000;
    const intervalMs = options.intervalMs || 1_000;
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (options.signal?.aborted) throw new Error('Result wait aborted');
      const data = await this.request(`/api/messages/by-task/${encodeURIComponent(taskId)}`, { signal: options.signal });
      const message = data.message;
      if (message) {
        const content = String(message.content || '').trim();
        if (!content) throw new Error(`Agent task ${taskId} ended without text`);
        if (!options.detailed) return content;
        let steps = [];
        try { steps = Array.isArray(message.steps) ? message.steps : JSON.parse(message.steps_json || '[]'); } catch { steps = []; }
        return { content, steps, thinking: typeof message.thinking === 'string' ? message.thinking : '' };
      }
      await new Promise((resolve, reject) => {
        const onAbort = () => { clearTimeout(timer); reject(new Error('Result wait aborted')); };
        const timer = setTimeout(() => { options.signal?.removeEventListener('abort', onAbort); resolve(); }, intervalMs);
        options.signal?.addEventListener('abort', onAbort, { once: true });
      });
    }
    throw new Error(`Agent result timeout after ${timeoutMs}ms (taskId=${taskId})`);
  }
}
