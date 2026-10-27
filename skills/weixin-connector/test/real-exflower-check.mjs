import { ExFlowerClient } from '../src/exflower.js';
import { loadConfig } from '../src/store.js';
const client = new ExFlowerClient(loadConfig());
const agentId = String(process.env.EXF_WEIXIN_TEST_AGENT || '').trim();
if (!agentId) throw new Error('Set EXF_WEIXIN_TEST_AGENT to an existing Agent ID before this explicitly authorized real test.');
const taskId = await client.invoke(agentId, '这是 ExFlower 微信连接器的集成自检。不要调用任何工具，不要追问，只回复：EXF_WEIXIN_OK');
const result = await client.waitForResult(taskId, { timeoutMs: 180_000, intervalMs: 500 });
console.log(JSON.stringify({ agentId, taskId, matched: result.includes('EXF_WEIXIN_OK'), reply: result.slice(0, 300) }, null, 2));
if (!result.includes('EXF_WEIXIN_OK')) process.exitCode = 1;
