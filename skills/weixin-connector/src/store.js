import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

export function defaultExflowerUrl() {
  try { const port = fs.readFileSync(path.join(os.homedir(), '.exflower', '.server-port'), 'utf8').trim(); if (/^\d+$/.test(port)) return `http://127.0.0.1:${port}`; } catch {}
  return process.env.EXFLOWER_URL || 'http://127.0.0.1:4000';
}
export function dataDir() {
  return path.resolve(process.env.EXF_WEIXIN_HOME || path.join(os.homedir(), '.exflower', 'connectors', 'weixin'));
}
export function paths() {
  const root = dataDir();
  return { root, config: path.join(root, 'config.json'), credentials: path.join(root, 'credentials.json'), login: path.join(root, 'login.json'), state: path.join(root, 'state.json'), pid: path.join(root, 'daemon.pid'), log: path.join(root, 'daemon.log') };
}
function ensure() { fs.mkdirSync(dataDir(), { recursive: true, mode: 0o700 }); }
export function readJson(file, fallback = null) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (e) { if (e.code === 'ENOENT') return fallback; throw new Error(`Invalid JSON: ${file}`); }
}
export function writeJson(file, value, secret = false) {
  ensure();
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2) + '\n', { mode: secret ? 0o600 : 0o644 });
  fs.renameSync(tmp, file);
  if (secret) fs.chmodSync(file, 0o600);
}
export function loadConfig() {
  const p = paths();
  const config = readJson(p.config, {});
  return {
    exflowerUrl: config.exflowerUrl || process.env.EXFLOWER_URL || defaultExflowerUrl(),
    apiKey: process.env.OPENEXTEAM_API_KEY || '',
    agents: config.agents && typeof config.agents === 'object' ? config.agents : {},
    allowFrom: Array.isArray(config.allowFrom) ? config.allowFrom.map(String) : [],
  };
}
export function saveConfig(config) {
  const copy = { ...config }; delete copy.apiKey;
  writeJson(paths().config, copy);
}
export function loadCredentials() { return readJson(paths().credentials); }
export function saveCredentials(credentials) { writeJson(paths().credentials, credentials, true); }
export function loadState() {
  const state = readJson(paths().state, {});
  return {
    syncBuf: state.syncBuf || '',
    bindings: state.bindings || {},
    contexts: state.contexts || {},
    histories: state.histories && typeof state.histories === 'object' && !Array.isArray(state.histories) ? state.histories : {},
    processed: Array.isArray(state.processed) ? state.processed : [],
    tasks: state.tasks || {},
    pending: state.pending || {},
    nextSeq: Number.isSafeInteger(state.nextSeq) ? state.nextSeq : 0,
    lastError: state.lastError || null,
  };
}
export function saveState(state) {
  state.processed = [...new Set(state.processed)].slice(-2000);
  writeJson(paths().state, state, true);
}
export function accountId(credentials) { return String(credentials.ilink_bot_id || 'default').replace(/[^A-Za-z0-9_.-]/g, '_'); }
export function publicConfig(config) { return { exflowerUrl: config.exflowerUrl, agents: config.agents, allowFrom: config.allowFrom }; }
