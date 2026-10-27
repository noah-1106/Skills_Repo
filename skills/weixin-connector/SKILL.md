---
name: weixin-connector
description: 连接微信与 ExFlower 多 Agent。用户说“连接微信/微信扫码/微信接入/微信里找某个 Agent/@项项/@红红/查看微信连接状态/把结果回复到微信/微信机器人”时使用。通过 exf-weixin CLI 管理扫码、后台接收、Agent 精确路由和文字回复；不用于视频号下载或群控。
---
# ExFlower 微信连接器
用自然语言帮助用户操作，不要求用户自己敲命令。CLI 是 Agent 的执行工具，已随 Skill 内置。

## 首次安装与命令入口
- 先确认 `bin/exf-weixin.js`、`src/`、`package-lock.json` 与本 SKILL.md 同级完整存在；缺文件说明解压不完整。
- 在 `SKILL.md` 所在目录执行 `npm ci --ignore-scripts`，再执行 `node bin/exf-weixin.js doctor --json`。
- 本文的 `exf-weixin ...` 是 CLI 简写；未全局安装时，在 Skill 根目录替换为 `node bin/exf-weixin.js ...`。只有用户明确需要全局命令时才执行 `npm link --ignore-scripts`。
- 不把开发机路径写进命令，不要求用户另找源码，不改装 OpenClaw。

## 边界
- 当前版本：个人微信私聊文字、扫码登录、`@Agent别名` 精确路由、同一联系人与同一 Agent 的最近 12 轮上下文、后台接收。
- 不支持图片、文件、语音、视频、群聊、主动加人、群发、朋友圈、任意新会话。
- Skill 不是监听器。持续接收必须运行 `exf-weixin start` 启动 daemon。
- 首次只允许扫码者使用。添加其他微信用户前必须得到所有者明确授权。
- 不输出 token、credentials.json、完整 login.json；日志和状态也不得泄露它们。state.json 含消息历史，也只能本地使用。
## 连接微信
1. 完成上述依赖安装后，执行 `exf-weixin doctor --json`。若 CLI 文件缺失或依赖安装失败，报告具体错误，不要改为安装 OpenClaw。
2. ExFlower 不可达时先让用户启动 ExFlower；不要擅自改端口或 API Key。
3. 执行 `exf-weixin agents sync --json`，向用户说明可用 Agent 别名。含空格别名支持最长精确匹配，例如 `@Coco 2.0`。
4. 执行 `exf-weixin login --no-wait --json`，展示返回的 `qrPngPath` 二维码图片，并给出本地路径。二维码是临时敏感信息，不上传第三方。
5. 用户扫码后执行 `exf-weixin login-status --json`。`wait/scaned` 继续轮询；`need_verifycode` 时询问微信显示的数字，再执行 `exf-weixin login-status --code 数字 --json`；`expired` 重新生成；`binded_redirect` 表示已绑定其他实例，不绕过。
6. `confirmed` 后执行 `exf-weixin start --json` 和 `exf-weixin status --json`，确认 daemon 有 PID、pending 数量和 lastError。
## 教用户在微信里使用
- `@项项 帮我梳理这个项目`：只发给项项，并绑定后续会话。
- 随后直接说 `继续`：仍发给项项，并带该联系人与项项最近的上下文。
- `@红红 写成小红书`：切换给红红；红红有独立历史，不自动复制项项上下文。
- `/agents`：查看可用 Agent；`/use Coco 2.0`：只切换，不执行任务。
## 回复已有微信会话
用户明确要求把结果发回微信时，先 `exf-weixin status --json` 找目标用户与绑定关系，再执行 `exf-weixin send --to 微信用户ID --text 内容 --json`。没有入站 context_token 就不能发送，不能伪造“已送达”；accepted 只表示微信服务接受。
## 异常处理
先运行 `exf-weixin status --json`、`exf-weixin logs --json`、`exf-weixin doctor --json`。pending 不为 0 表示仍在重试，不要重复启动多个 daemon，不要手工清除 state.json。默认失败 10 次或排队 24 小时后进入 deadLetters，保留原消息并放行同 lane 后续消息。用 `pending --json` 查看；人工重试/确认丢弃前先 stop，再执行 `pending retry --key ID` 或 `pending discard --key ID --yes`，完成后 start。凭证失效时重新扫码。
- `npm test` 只运行离线测试；`npm run test:real` 会真实调用 ExFlower Agent，必须得到用户明确许可后单独运行。
- 修改 connector 后，先备份状态并检查 pending 明细，再 `stop`、`start`；pending 会按 lane 恢复，不要求清零，绝不删除凭证、状态或历史文件。
不确定的 invoke 不按次数或年龄自动隔离，必须核对 taskId 后 recover。死信只隔离、不自动删除；没有 --yes 不得执行 discard。已 discarded 的死信是终态，禁止 retry/recover；缺 Agent 或原始消息等恢复元数据时必须拒绝并保持原状。详细命令见 references/commands.md。
