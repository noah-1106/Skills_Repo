#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { ExFlowerClient, bareAgentId } from '../src/exflower.js';
import { createLogin, pollLoginOnce, pollLoginLoop, publicLoginStatus, sendLongText } from '../src/weixin.js';
import { runDaemon, pendingSummary, attachPendingTask } from '../src/daemon.js';
import { deadLetterSummary, retryMessage, discardMessage, retryPolicy } from '../src/delivery.js';
import { paths, loadConfig, saveConfig, loadCredentials, loadState, saveState, readJson, publicConfig } from '../src/store.js';
const argv = process.argv.slice(2);
const json = argv.includes('--json');
const args = argv.filter(a => a !== '--json');
const command = args[0] || 'help';
const option = (name, fallback) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : fallback; };
const has = name => args.includes(name);
const output = (data, text) => { if (json) console.log(JSON.stringify(data, null, 2)); else if (text) console.log(text); else console.log(typeof data === 'string' ? data : JSON.stringify(data, null, 2)); };
const running = () => { const p = readJson(paths().pid); if (!p?.pid) return null; try { process.kill(p.pid, 0); return p; } catch { return null; } };
async function main() {
  if (has('--help') || command === 'help') return output(`exf-weixin 0.3.0 — ExFlower 微信文字连接器\n\n连接：doctor | login [--no-wait] | login-status [--code N] | status\nAgent：agents sync | agents list | agents bind --agent ID --alias 别名 | agents unbind ID\n后台：start | stop | daemon run [--once]\n回复：send --to 微信用户ID --text 文字\n权限：allow list | allow add 微信用户ID\n队列：pending | pending retry --key ID | pending discard --key ID --yes | pending policy [--max-attempts N --max-age-hours H]\n诊断：logs\n\n所有命令支持 --json。凭证不会出现在输出中。`);
  if (command === 'doctor') {
    const config = loadConfig(); let health = null, error = null;
    try { health = await new ExFlowerClient(config).health(); } catch (e) { error = e.message; }
    const result = { node: process.version, exflowerUrl: config.exflowerUrl, exflowerReachable: Boolean(health), weixin: publicLoginStatus(), daemon: running(), error };
    if (!health) throw new Error(`ExFlower 不可达：${config.exflowerUrl}；${error}`);
    return output(result, `Node ${process.version}\nExFlower OK: ${config.exflowerUrl}\n微信：${result.weixin.connected ? '已连接' : '未连接'}\nDaemon：${result.daemon ? `运行中 PID ${result.daemon.pid}` : '未运行'}`);
  }
  if (command === 'login') {
    if (loadCredentials()?.token && !has('--relogin')) return output(publicLoginStatus(), '已连接微信；如需换账号请明确使用 --relogin');
    const result = await createLogin({ noWait: has('--no-wait') });
    if (result.status === 'waiting') return output(result, `二维码已生成：${result.qrPngPath}\n请用微信扫码，然后执行 login-status（Agent 会代为轮询）。`);
    return output(result);
  }
  if (command === 'login-status') return output(await pollLoginOnce(option('--code')));
  if (command === 'login-wait') return output(await pollLoginLoop({ timeoutMs: Number(option('--timeout', '480000')) }));
  if (command === 'agents') {
    const sub = args[1]; const config = loadConfig(); const client = new ExFlowerClient(config);
    if (sub === 'sync') {
      const remote = await client.agents(); const used = new Set();
      for (const agent of remote.filter(a => a.connected)) {
        const old = config.agents[agent.id] || {}; let alias = old.alias || agent.name || agent.id;
        if ([...used].some(x => x.toLowerCase() === alias.toLowerCase())) alias = agent.id;
        used.add(alias); config.agents[agent.id] = { name: agent.name, alias };
      }
      saveConfig(config); return output({ count: Object.keys(config.agents).length, agents: config.agents }, `已同步 ${Object.keys(config.agents).length} 个 Agent；微信消息仍只会发给被 @ 或已绑定的一个 Agent。`);
    }
    if (sub === 'bind') {
      const id = bareAgentId(option('--agent')); const alias = option('--alias');
      if (!id || !alias) throw new Error('agents bind 需要 --agent ID --alias 别名');
      const remote = await client.agents(); const agent = remote.find(a => a.id === id);
      if (!agent) throw new Error(`ExFlower 中不存在 ${id}`);
      if (Object.entries(config.agents).some(([otherId, a]) => otherId !== id && String(a.alias).toLowerCase() === alias.toLowerCase())) throw new Error(`别名已被占用：${alias}`);
      config.agents[id] = { name: agent.name, alias }; saveConfig(config);
      return output({ agent: config.agents[id], id }, `已绑定 @${alias} → ${id}`);
    }
    if (sub === 'unbind') { const id = args[2]; if (!config.agents[id]) throw new Error(`未绑定 ${id}`); delete config.agents[id]; saveConfig(config); return output({ removed: id }); }
    return output(config.agents);
  }
  if (command === 'allow') {
    const config = loadConfig(); const sub = args[1];
    if (sub === 'add') { const id = args[2]; if (!id) throw new Error('allow add 需要微信用户 ID'); config.allowFrom = [...new Set([...config.allowFrom, id])]; saveConfig(config); }
    return output({ allowFrom: config.allowFrom, default: config.allowFrom.length ? null : '仅扫码者' });
  }
  if (command === 'start') {
    if (running()) return output({ status: 'already_running', daemon: running() });
    if (!loadCredentials()?.token) throw new Error('请先 login 扫码连接微信');
    const config = loadConfig(); await new ExFlowerClient(config).health();
    if (!Object.keys(config.agents).length) throw new Error('请先 agents sync');
    fs.mkdirSync(paths().root, { recursive: true, mode: 0o700 });
    const logFd = fs.openSync(paths().log, 'a');
    const child = spawn(process.execPath, [fileURLToPath(import.meta.url), 'daemon', 'run'], { detached: true, stdio: ['ignore', logFd, logFd], env: process.env });
    child.unref(); fs.closeSync(logFd);
    const deadline = Date.now() + 8000;
    while (Date.now() < deadline) { await new Promise(r => setTimeout(r, 200)); if (running()?.pid === child.pid) return output({ status: 'started', pid: child.pid, log: paths().log }, `已启动，PID ${child.pid}`); if (child.exitCode !== null) break; }
    throw new Error(`daemon 未正常启动，请查看 ${paths().log}`);
  }
  if (command === 'stop') {
    const p = running(); if (!p) return output({ status: 'stopped' });
    process.kill(p.pid, 'SIGTERM');
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 100));
      try { process.kill(p.pid, 0); } catch { return output({ status: 'stopped', pid: p.pid }); }
    }
    throw new Error(`daemon ${p.pid} did not stop within 10s; refusing to start a replacement`);
  }
  if (command === 'daemon') {
    if (args[1] !== 'run') throw new Error('用法：daemon run [--once]');
    const controller = new AbortController(); process.on('SIGTERM', () => controller.abort()); process.on('SIGINT', () => controller.abort());
    await runDaemon({ signal: controller.signal, once: has('--once') }); return;
  }
  if (command === 'status') {
    const state = loadState(); return output({ weixin: publicLoginStatus(), daemon: running(), config: publicConfig(loadConfig()), processed: state.processed.length, pending: pendingSummary(state).length, pendingDetails: pendingSummary(state), deadLetters: deadLetterSummary(state), retryPolicy: retryPolicy(loadConfig()), bindings: state.bindings, lastError: state.lastError, log: paths().log });
  }
  if (command === 'pending') {
    const sub = args[1];
    if (!sub || sub === 'list') {
      const state = loadState();
      return output({ pending: pendingSummary(state), deadLetters: deadLetterSummary(state), policy: retryPolicy(loadConfig()) });
    }
    if (sub === 'dead') return output({ deadLetters: deadLetterSummary(loadState()) });
    if (sub === 'policy') {
      const config = loadConfig();
      const attempts = option('--max-attempts'), age = option('--max-age-hours');
      if (attempts !== undefined) {
        const value = Number(attempts);
        if (!Number.isSafeInteger(value) || value < 1) throw new Error('--max-attempts 必须是正整数');
        config.pendingMaxAttempts = value;
      }
      if (age !== undefined) {
        const value = Number(age);
        if (!Number.isFinite(value) || value <= 0) throw new Error('--max-age-hours 必须是正数');
        config.pendingMaxAgeHours = value;
      }
      if (attempts !== undefined || age !== undefined) saveConfig(config);
      return output({ policy: retryPolicy(config) });
    }
    if (sub === 'retry' || sub === 'discard') {
      if (running()) throw new Error('请先 stop，再修改队列；完成后 start。禁止运行中改写 state');
      const key = option('--key');
      if (!key) throw new Error(`${sub} 需要 --key 消息键`);
      const state = loadState(); const credentials = loadCredentials();
      const recoveryOptions = {
        botId: credentials?.ilink_bot_id,
        route: message => ({ contextKey: `${credentials?.ilink_bot_id}:${message.from_user_id}` }),
      };
      const result = sub === 'retry' ? retryMessage(state, key, recoveryOptions) : discardMessage(state, key, has('--yes'));
      saveState(state);
      return output(result);
    }
    throw new Error(`未知 pending 子命令: ${sub}`);
  }
  if (command === 'recover') {
    if (running()) throw new Error('recover 写入状态前必须先 stop daemon，避免旧内存覆盖人工恢复');
    const key = option('--key'); const taskId = option('--task-id');
    if (!key || !taskId) throw new Error('recover 需要 --key 消息键 --task-id 人工核对后的真实任务ID');
    const state = loadState(); const credentials = loadCredentials();
    return output(attachPendingTask(state, key, taskId, saveState, {
      botId: credentials?.ilink_bot_id,
      route: message => ({ contextKey: `${credentials?.ilink_bot_id}:${message.from_user_id}` }),
    }));
  }
  if (command === 'logs') { const text = fs.existsSync(paths().log) ? fs.readFileSync(paths().log, 'utf8') : ''; return output(text.split('\n').slice(-100).join('\n')); }
  if (command === 'send') {
    const to = option('--to'); const text = option('--text');
    if (!to || !text) throw new Error('send 需要 --to 微信用户ID --text 文字；只允许回复已有会话');
    const credentials = loadCredentials(); if (!credentials?.token) throw new Error('未连接微信');
    const state = loadState(); const contextKey = `${credentials.ilink_bot_id}:${to}`; const token = state.contexts[contextKey];
    if (!token) throw new Error('该用户还没有入站会话/context_token，不能主动发起');
    const results = await sendLongText(credentials, to, text, token);
    return output({ accepted: true, results }, `微信服务已接受 ${results.length} 条消息（不等于对方已读）`);
  }
  throw new Error(`未知命令：${command}；使用 --help`);
}
main().catch(error => { if (json) console.log(JSON.stringify({ success: false, error: error.message })); else console.error(`错误：${error.message}`); process.exitCode = 1; });
