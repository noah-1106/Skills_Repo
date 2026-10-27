import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createLogin, pollLoginOnce, sendLongText, getUpdates, chunkText } from '../src/weixin.js';

test('长文分片不拆 Emoji 代理对，且每片不超过长度上限', () => {
  const source = `${'汉'.repeat(2999)}😀尾${'🙂'.repeat(3001)}`;
  const chunks = chunkText(source);
  assert.equal(chunks.join(''), source);
  assert.ok(chunks.length >= 3);
  for (const chunk of chunks) {
    assert.ok(chunk.length <= 3000);
    assert.equal(/[\uD800-\uDBFF]$/.test(chunk), false);
    assert.equal(/^[\uDC00-\uDFFF]/.test(chunk), false);
  }
});
import { loadConfig, loadCredentials, paths } from '../src/store.js';
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'exf-weixin-login-'));
process.env.EXF_WEIXIN_HOME = home;
function response(data) { return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } }); }
test('模拟扫码确认：只公开账号信息，token 0600，扫码者成为默认可用用户', async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes('get_bot_qrcode')) return response({ qrcode: 'qr-ticket', qrcode_img_content: 'https://example.test/scan' });
    if (url.includes('get_qrcode_status')) return response({ status: 'confirmed', bot_token: 'never-print-this-token', ilink_bot_id: 'bot@im.bot', ilink_user_id: 'owner@im.wechat', baseurl: 'https://example.test' });
    throw new Error(`unexpected ${url}`);
  };
  const created = await createLogin({ noWait: true, fetchImpl });
  assert.equal(created.status, 'waiting');
  assert.equal(fs.existsSync(created.qrPngPath), true);
  assert.equal(fs.statSync(created.qrPngPath).size > 100, true);
  assert.equal(JSON.stringify(created).includes('never-print-this-token'), false);
  const confirmed = await pollLoginOnce(undefined, fetchImpl);
  assert.equal(confirmed.status, 'confirmed');
  assert.equal(confirmed.owner, 'owner@im.wechat');
  const credentials = loadCredentials();
  assert.equal(credentials.token, 'never-print-this-token');
  assert.equal(fs.statSync(paths().credentials).mode & 0o777, 0o600);
  assert.deepEqual(loadConfig().allowFrom, ['owner@im.wechat']);
  assert.equal(fs.existsSync(paths().login), false);
  assert.equal(calls.length, 2);
  assert.match(calls[0].url, /get_bot_qrcode\?bot_type=3$/);
  assert.deepEqual(JSON.parse(calls[0].options.body), { local_token_list: [] });
});
test('长回复分片：第一片已接受后失败，重试从第二片继续', async () => {
  const bodies = []; let sends = 0;
  const fetchImpl = async (url, options) => {
    sends++;
    if (sends === 2) throw new Error('simulated network loss');
    bodies.push(JSON.parse(options.body));
    return response({ ret: 0, message_id: `server-${sends}` });
  };
  const credentials = { token: 'x', baseUrl: 'https://example.test' };
  const sentIds = [];
  const options = { clientIdPrefix: 'stable-message', sentClientIds: sentIds, fetchImpl, onSent: result => sentIds.push(result.clientId) };
  await assert.rejects(sendLongText(credentials, 'owner', 'A'.repeat(3100), 'context', options), /network loss/);
  assert.deepEqual(sentIds, ['stable-message:0']);
  await sendLongText(credentials, 'owner', 'A'.repeat(3100), 'context', options);
  assert.deepEqual(sentIds, ['stable-message:0', 'stable-message:1']);
  assert.equal(bodies.length, 2);
  assert.equal(bodies[0].msg.client_id, 'stable-message:0');
  assert.equal(bodies[1].msg.client_id, 'stable-message:1');
  assert.equal(bodies[0].msg.item_list[0].text_item.text.length, 3000);
  assert.equal(bodies[1].msg.item_list[0].text_item.text.length, 100);
});
test('iLink 非零 ret/errcode 不当作发送成功', async () => {
  await assert.rejects(sendLongText({ token: 'x', baseUrl: 'https://example.test' }, 'owner', 'hello', 'context', { fetchImpl: async () => response({ ret: 1, errmsg: 'rejected' }) }), /Weixin API 1: rejected/);
});
