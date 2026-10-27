import crypto from 'node:crypto';
import fs from 'node:fs';
import QRCode from 'qrcode';
import QRTerminal from 'qrcode-terminal';
import { paths, readJson, writeJson, loadCredentials, saveCredentials, loadConfig, saveConfig } from './store.js';

export const FIXED_BASE_URL = 'https://ilinkai.weixin.qq.com';
const CHANNEL_VERSION = '2.4.10';
const CONNECTOR_VERSION = '0.3.0';
const APP_VERSION = ((2 & 255) << 16) | ((4 & 255) << 8) | (10 & 255);
const sleep = ms => new Promise(r => setTimeout(r, ms));

function headers(token, json = true) {
  const uin = crypto.randomBytes(4).readUInt32BE(0).toString();
  return {
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    AuthorizationType: 'ilink_bot_token',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    'X-WECHAT-UIN': Buffer.from(uin).toString('base64'),
    'iLink-App-Id': 'bot',
    'iLink-App-ClientVersion': String(APP_VERSION),
  };
}
function baseInfo() { return { channel_version: CHANNEL_VERSION, bot_agent: `ExFlower/${CONNECTOR_VERSION}` }; }
function endpoint(base, path) { return `${String(base || FIXED_BASE_URL).replace(/\/$/, '')}/ilink/bot/${path}`; }
async function request(path, { baseUrl, token, body, method = 'POST', timeoutMs = 40_000, signal, fetchImpl = globalThis.fetch } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error(`Weixin request timeout: ${path}`)), timeoutMs);
  const abort = () => controller.abort(signal?.reason || new Error('Weixin request aborted'));
  signal?.addEventListener('abort', abort, { once: true });
  try {
    const response = await fetchImpl(endpoint(baseUrl, path), { method, headers: headers(token, method === 'POST'), ...(body !== undefined ? { body: JSON.stringify(body) } : {}), signal: controller.signal });
    const text = await response.text();
    let data; try { data = JSON.parse(text); } catch { throw new Error(`Weixin HTTP ${response.status}: non-JSON response`); }
    if (!response.ok) throw new Error(`Weixin HTTP ${response.status}: ${data.errmsg || data.message || 'request failed'}`);
    return data;
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}
function checkResponse(data) {
  const code = data.errcode ?? data.ret ?? 0;
  if (code !== 0) { const e = new Error(`Weixin API ${code}: ${data.errmsg || 'request failed'}`); e.code = code; throw e; }
  return data;
}
export async function createLogin({ noWait = false, fetchImpl } = {}) {
  const data = checkResponse(await request('get_bot_qrcode?bot_type=3', { baseUrl: FIXED_BASE_URL, body: { local_token_list: [] }, fetchImpl }));
  if (!data.qrcode || !data.qrcode_img_content) throw new Error('Weixin QR response is incomplete');
  const login = { qrcode: data.qrcode, qrcodeUrl: data.qrcode_img_content, startedAt: Date.now(), baseUrl: FIXED_BASE_URL };
  writeJson(paths().login, login, true);
  fs.writeFileSync(paths().root + '/login-qr.txt', await new Promise(resolve => QRTerminal.generate(login.qrcodeUrl, { small: true }, resolve)), { mode: 0o600 });
  await QRCode.toFile(paths().root + '/login-qr.png', login.qrcodeUrl, { width: 512, margin: 2 });
  if (noWait) return { status: 'waiting', qrPngPath: paths().root + '/login-qr.png', qrTextPath: paths().root + '/login-qr.txt' };
  return pollLoginLoop();
}
export async function pollLoginOnce(code, fetchImpl) {
  const p = paths(); const login = readJson(p.login);
  if (!login) return { status: 'not_started' };
  if (Date.now() - login.startedAt > 5 * 60_000) return { status: 'expired', message: '二维码已过期，请重新 login' };
  if (code) login.pendingVerifyCode = String(code).trim();
  const query = `?qrcode=${encodeURIComponent(login.qrcode)}${login.pendingVerifyCode ? `&verify_code=${encodeURIComponent(login.pendingVerifyCode)}` : ''}`;
  const data = await request(`get_qrcode_status${query}`, { baseUrl: login.baseUrl, method: 'GET', timeoutMs: 40_000, fetchImpl });
  login.status = data.status;
  if (data.status === 'scaned_but_redirect' && data.redirect_host) login.baseUrl = `https://${data.redirect_host}`;
  if (data.status === 'scaned' && login.pendingVerifyCode) delete login.pendingVerifyCode;
  if (data.status === 'confirmed') {
    if (!data.bot_token || !data.ilink_bot_id) throw new Error('Login confirmed but credentials are incomplete');
    const credentials = { token: data.bot_token, ilink_bot_id: data.ilink_bot_id, ilink_user_id: data.ilink_user_id || '', baseUrl: data.baseurl || login.baseUrl || FIXED_BASE_URL, connectedAt: new Date().toISOString() };
    saveCredentials(credentials);
    const config = loadConfig();
    if (credentials.ilink_user_id && config.allowFrom.length === 0) config.allowFrom = [credentials.ilink_user_id];
    saveConfig(config);
    try { fs.unlinkSync(p.login); } catch (e) { if (e.code !== 'ENOENT') throw e; }
    return { status: 'confirmed', account: credentials.ilink_bot_id, owner: credentials.ilink_user_id, allowFrom: config.allowFrom };
  }
  if (['expired', 'verify_code_blocked', 'binded_redirect'].includes(data.status)) {
    try { fs.unlinkSync(p.login); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  }
  writeJson(p.login, login, true);
  return { status: data.status, needsCode: data.status === 'need_verifycode', alreadyConnected: data.status === 'binded_redirect', baseUrl: login.baseUrl };
}
export async function pollLoginLoop({ timeoutMs = 480_000, signal } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (signal?.aborted) throw new Error('Login aborted');
    const result = await pollLoginOnce();
    if (['confirmed', 'expired', 'verify_code_blocked', 'binded_redirect', 'not_started'].includes(result.status)) return result;
    if (result.needsCode) return result;
    await sleep(1000);
  }
  return { status: 'timeout' };
}
export async function getUpdates(credentials, syncBuf, { timeoutMs = 40_000, signal, fetchImpl } = {}) {
  const data = await request('getupdates', { baseUrl: credentials.baseUrl, token: credentials.token, body: { sync_buf: syncBuf || '', get_updates_buf: syncBuf || '', base_info: baseInfo() }, timeoutMs, signal, fetchImpl });
  return checkResponse(data);
}
export async function sendText(credentials, to, text, contextToken, { clientId, fetchImpl, signal } = {}) {
  const id = clientId || `exf-weixin:${Date.now()}:${crypto.randomUUID()}`;
  const data = await request('sendmessage', { baseUrl: credentials.baseUrl, token: credentials.token, signal, body: { msg: { from_user_id: '', to_user_id: to, client_id: id, message_type: 2, message_state: 2, item_list: [{ type: 1, text_item: { text: String(text) } }], context_token: contextToken || undefined }, base_info: baseInfo() }, fetchImpl });
  checkResponse(data);
  return { clientId: id, serverMessageId: data.message_id || null };
}
export function chunkText(value, max = 3000) {
  const text = String(value || '').trim();
  if (!Number.isInteger(max) || max < 2) throw new Error('chunk size must be an integer >= 2');
  if (!text) return [];
  const chunks = [];
  let chunk = '', size = 0;
  for (const char of text) {
    if (chunk && size + char.length > max) { chunks.push(chunk); chunk = ''; size = 0; }
    chunk += char; size += char.length;
  }
  if (chunk) chunks.push(chunk);
  return chunks;
}
export async function sendLongText(credentials, to, text, contextToken, options = {}) {
  const chunks = chunkText(text);
  if (!chunks.length) chunks.push('（空回复）');
  const results = []; const sent = new Set(options.sentClientIds || []);
  for (let index = 0; index < chunks.length; index++) {
    const clientId = `${options.clientIdPrefix || `exf-weixin:${Date.now()}`}:${index}`;
    if (sent.has(clientId)) continue;
    const result = await sendText(credentials, to, chunks[index], contextToken, { clientId, fetchImpl: options.fetchImpl, signal: options.signal });
    results.push(result); options.onSent?.(result);
  }
  return results;
}
export function publicLoginStatus() { const c = loadCredentials(); return c ? { connected: true, account: c.ilink_bot_id, owner: c.ilink_user_id, baseUrl: c.baseUrl, connectedAt: c.connectedAt } : { connected: false }; }
