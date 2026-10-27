# ExFlower 微信连接器 V0.3
把个人微信私聊文字路由给指定 ExFlower Agent，并把最终回复送回微信。Skill 与 CLI 一同分发，不需要另找项目源码。

## 安装
要求：Node.js >=22.13、npm、正在运行的 ExFlower、可用的微信 iLink 登录环境。安装依赖和扫码需要网络。

`.skill` 是 ZIP 格式。解压到 ExFlower 用户技能目录，最终路径应为：

```text
~/.exflower/skills/weixin-connector/SKILL.md
~/.exflower/skills/weixin-connector/bin/exf-weixin.js
```

然后安装锁定的依赖并自检：

```bash
cd ~/.exflower/skills/weixin-connector
npm ci --ignore-scripts
node bin/exf-weixin.js doctor --json
```

让 Agent 重新读取技能列表，然后说“连接微信”。Agent 会按 `SKILL.md` 引导同步 Agent、展示二维码、扫码和启动 daemon。首次使用不需要手工编辑 config。

如果明确需要全局 `exf-weixin` 命令，可在上述目录执行 `npm link --ignore-scripts`；这不是必需步骤。没有全局命令时，所有文档中的 `exf-weixin ...` 都可替换为在 Skill 根目录执行 `node bin/exf-weixin.js ...`。

## 微信侧用法
- `@项项 你好`：指定 Agent，并绑定该联系人的后续会话。
- `继续`：发给当前绑定 Agent。
- `@Coco 2.0 你好`：支持含空格别名，最长精确匹配。
- `/agents`：查看 Agent；`/use Coco 2.0`：只切换，不执行任务。

## 调度与上下文
- 每个“联系人 + Agent”保留最近 12 轮历史，单条历史最多 6000 字；不同联系人和 Agent 相互隔离。
- 同一联系人同一 Agent 严格顺序执行；不同 Agent lane 可并行，一个长任务不阻塞其他 Agent 或新消息接收。
- 入站原始消息先落盘，再推进同步游标；重启从 pending 与任务缓存恢复，已有 taskId 不重复 invoke。
- Agent 绑定按消息到达时更新，旧任务完成不会把绑定改回去。

## 失败与死信
- 默认同一消息失败 10 次或排队超过 24 小时后进入 `deadLetters`；可用 `pending policy --max-attempts N --max-age-hours H` 调整。旧队列升级时从首次运行新版开始计龄。
- 死信保留原消息、taskId、错误与次数，不自动删除，也不再阻塞同 lane 后续消息。重复入站不会复活死信。
- `invokeState=calling/uncertain/rejected` 仍需人工核对 taskId，不能靠年龄、次数、retry 或 discard 自动跳过。
- 修改队列前先 `stop`：`pending retry --key ID` 重置重试并保留原顺序；`pending discard --key ID --yes` 只确认归档，不抹除原始记录；`recover --key ID --task-id 已核对ID` 可恢复 pending 或非 discarded 死信。已 discarded 是终态，retry/recover 均拒绝；缺 Agent/原始消息等元数据也拒绝且不改状态。完成后 `start`。
- 完成消息 ID 作为持久去重记录保留，不按最近 2000 条窗口淘汰；清理前应先停止 daemon 并备份 state。
- `pending --json` 和 `status --json` 同时列出活动队列与死信摘要，不输出消息正文。

## 数据与安全
凭证、配置和运行状态保存在 `~/.exflower/connectors/weixin/`，不在 Skill 包内。凭证与状态权限为 0600。默认只允许扫码者；添加其他微信用户必须得到所有者明确授权。

消息正文会保存在本机状态与最近历史中，并传给所选 Agent 和模型。不要转发无权分享的聊天内容；敏感信息先脱敏。日志不得包含 token 或消息正文。

## 当前边界
仅支持个人微信私聊文字。不支持图片、语音、视频、文件、群聊、原生合并转发聊天记录、全量历史读取、主动加人、任意新会话或已读回执。复制粘贴的其他聊天文字可按普通私聊文字处理。`sent` 只表示微信服务接受，不等于对方已读。

ExFlower 调用接口没有幂等键。连接明确拒绝可自动重试；调用结果不确定时会阻断该 lane 的自动重放，需核对真实 taskId 后人工恢复。不宣称端到端 exactly-once。

## 验证
```bash
npm test                 # 40 项离线测试，不调用真实 Agent 或微信
EXF_WEIXIN_TEST_AGENT=agent-id npm run test:real
```

真实自检会调用指定 Agent，必须先获得明确许可，并把 `agent-id` 换成接收方 ExFlower 中实际存在的 ID。接收方仍需自行完成扫码、真实收发和长回复验收；原开发环境的验收不随包转移。

## 文件说明
`SKILL.md` 是 Agent 操作入口；`bin/` 为 CLI；`src/` 为协议、路由、存储和 daemon；`references/commands.md` 为命令契约；`test/` 为离线与显式真实自检。依赖版本见 `package-lock.json`；第三方许可见 `UPSTREAM-LICENSE` 与 `THIRD_PARTY_NOTICES.md`。
