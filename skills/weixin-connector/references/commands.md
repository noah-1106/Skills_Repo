# exf-weixin 命令契约

所有命令支持 `--json`。凭证、token、完整登录响应不得输出。

## 连接与状态
- `exf-weixin doctor --json`：Node、ExFlower、登录和 daemon 检查。
- `exf-weixin login --no-wait --json`：生成二维码；返回 `qrPngPath`。
- `exf-weixin login-status --json`：查询扫码；需要验证码时加 `--code 数字`。
- `exf-weixin start --json` / `stop --json`：启停后台连接器。
- `exf-weixin status --json`：状态、绑定、pending 及诊断信息。
- `exf-weixin logs --json`：最近日志；不包含消息正文。

## Agent 与权限
- `exf-weixin agents sync --json`：同步 ExFlower Agent。
- `exf-weixin agents list --json`
- `exf-weixin agents bind --agent agent-id --alias 别名`
- `exf-weixin agents unbind agent-id`
- `exf-weixin allow list` / `allow add 微信用户ID`：授权前必须获得所有者明确许可。

## 恢复
- `exf-weixin pending --json`：只输出待恢复项的诊断元数据，不输出消息正文。
- `invokeState=uncertain/calling`：ExFlower 是否已创建任务不确定，禁止自动重新 invoke。
- 在 ExFlower 核对真实 taskId 后，先 `exf-weixin stop`，再执行 `exf-weixin recover --key 消息键 --task-id 真实taskId --json`，最后 `exf-weixin start`。recover 在 daemon 运行时会拒绝写入，防止旧内存覆盖。
- attach 只绑定已有任务，不会重新创建任务；connector 随后获取原结果并发送。

## 回复已有会话
`exf-weixin send --to 微信用户ID --text 内容 --json`
仅当该联系人已有入站 `context_token` 时可用。输出 accepted 不代表已读。

## 测试
- `npm test` / `npm run test:offline`：只跑模拟与单元测试。
- `EXF_WEIXIN_TEST_AGENT=实际AgentID npm run test:real`：真实调用指定 ExFlower Agent，必须获得明确许可；未设置 ID 时拒绝执行。
