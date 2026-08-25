---
name: xhs-dl
description: |
  小红书笔记处理工具：把链接变成结构化资源卡片（标题/正文/标签/博主 + 口播转写 + 画面OCR + 原图）。
  ★ 触发铁律（最重要）：用户消息里出现小红书链接（xhslink.cn 短链 或 xiaohongshu.com 完整链接），无论用户要求什么（看看/讲什么/存一下/下载/保存/整理/提取/转写/有没有声音/是什么），立即使用本技能——不要只回复链接或描述，必须实际调用 xhs.py 处理。
  - 想从小红书链接提取文字、转写视频口播、抓取图文原图、提炼资源线索/干货/工具名
  - 处理小红书 AI 工具介绍/教程/GitHub 周榜类视频笔记（英文工具名密集）
  - 用户说"这个视频没有声音/没有配音"或视频是画面演示类（信息在画面里）——本技能用抽帧 OCR 提取画面文字
  - 博主拼写错误时（如标题"Fireclawl"实际是"Firecrawl"）——本技能用画面 OCR 拿到权威拼写，自动纠错
  本技能全本地运行（ASR + OCR 内置，不依赖任何外部服务），单篇处理，链接进卡片出，约 20 秒级出结果（ASR ~11s + 画面OCR ~10s）。
compatibility: "macOS（OCR 用 Vision 框架；Windows 上自动跳过 OCR 不影响主流程，替代方案为 winrt-Windows.Media.Ocr）。系统工具: yt-dlp + ffmpeg（xhs.py 自动定位）。Python 3.9+（需 python3 -m venv 可用；macOS CLT 自带 python 可能缺 ensurepip，需装完整版）。Skill 完全自包含：代码在 scripts/，模型/环境首次使用时 setup.py 自动下载+建立（模型 224MB 来自 hf-mirror）。"
---

# xhs-dl — 小红书单篇下载

给一个小红书链接，出一张资源卡片。单篇、极简、完全自包含（本地 ASR 转写 + 本地 OCR，双通道互补）。

## 快速使用（Skill 自包含，无需外部项目）

本 Skill 完全自包含：代码在 `scripts/`，模型和环境在**首次使用时**由 setup.py 自动下载+建立。不依赖任何外部硬盘/项目目录。

```bash
cd ~/.exflower/skills/xhs-dl
python3 scripts/xhs.py "<小红书链接>"       # Mac / Linux
python  scripts/xhs.py "<小红书链接>"       # Windows
python3 scripts/xhs.py <链接1> <链接2>     # 可多传几个
```

输出（在 skill 根下）：
- `out/<note_id>.md` 资源卡片（核心产物）
- `out/<note_id>/` 图文原图（仅图文笔记）

首次运行 xhs.py 会自动引导：当前 Python 无 sherpa_onnx → 用 skill 根下 .venv 重执行 → .venv 缺失时提示跑 scripts/setup.py。

## 首次环境搭建（唯一前置，必须执行一次）

> Skill 不自带模型/环境（保持轻量可分发），**新机器/新环境首次使用必须先跑**：

```bash
python3 scripts/setup.py        # Mac / Linux
python scripts/setup.py         # Windows
# 做什么: ① 建 .venv + 装依赖（2-3 分钟）
#         ② 下载 ASR 模型 paraformer-bilingual 224MB（国内走 hf-mirror，1-5 分钟）
#         ③ 验证环境就绪
```

- **一套脚本双平台**：setup.py 是 Python 写的跨平台安装脚本（替代 bash），Mac/Windows 同一套代码
- 依赖按平台自动选择：Mac 装 ocrmac（Vision 框架）/ Windows 装 winrt-Windows.Media.Ocr（系统级 OCR）
- `.venv` 绑定 CPU 架构：换机器/换架构重跑 setup.py（模型和代码通用）
- 检查系统 python3 是否支持 venv：`python3 -m venv --help`；不行就装完整版（Mac: brew install python@3.11 / Windows: python.org）
- 分发时**不带** models/ 和 .venv/（体积大），接收方跑一次 setup.py 即完整可用

## 三类内容的处理策略（自动分流）

| 内容类型 | 处理 | 信息来源 |
|---|---|---|
| 🎬 有口播视频 | 拉音频 → ASR 转写 **+ 抽帧画面 OCR**（双通道） | 口播全文（ASR）+ 画面工具名/star 数/仓库名（OCR，权威拼写） |
| 🎬 无口播演示视频 | 转写为空 → 自动抽帧 OCR | 画面文字（工具名/口号/特性） |
| 🖼️ 图文 | 页面解析 → 正文/标签/博主 → 下原图 → 原图 OCR | 图内文字（教程/技术文档也能读） |

视频全程零落盘（ffmpeg -vn 只拉音频流；抽帧图片用完即删）。

## 执行要点（为什么这么做）

1. **链接解析**：短链 `xhslink.cn` 用 curl -sL 跟跳转拿真实 URL；note_id 从 `/(?:explore|discovery/item)/([0-9a-f]{20,})` 提取
2. **视频路径**：yt-dlp `--skip-download --dump-json` 拿元数据+CDN 直链（xsec_token 有则带，无也能跑）。**直链有时效性（几小时），拿到立刻拉音频**
3. **图文路径**：yt-dlp 对图文会报 "No video formats found"（stdout 空）——**这是正常的**，自动切页面解析：抓 HTML → 括号配对截取 `__INITIAL_STATE__` → yt-dlp 的 `js_to_json` 处理（页面含 undefined 等非标准 JS）→ 提取 title/desc/tagList/imageList/user
4. **转写**：sherpa_onnx `OfflineRecognizer.from_paraformer`，音频要 16k 单声道 wav、采样 float32 归一化（int16 会乱码）；短音频/纯音乐偶发 ONNX 报错——正常，自动走 OCR 兜底
5. **画面 OCR（重要，双通道核心）**：**有口播的视频也抽帧 OCR**（首帧 + 每 15s 一帧），因为**生僻工具名/项目名 ASR 必错**（"Tapestry"→"tap scturb o"、"OpenViking"→"open working"），而画面里的 GitHub 仓库页是**白纸黑字的权威拼写**，还能白捡 star 数/本周增长/作者/语言/项目描述等元数据。实测 183s 周榜视频 14 帧全命中，工具名 100% 正确
6. **OCR 纠错**：ocrmac（macOS Vision 框架）还能**纠正标题拼写错误**（实测 "Fireclawl"→"Firecrawl"）

## 已知坑（真实实测，详见 references/已知坑.md）

- 图文笔记走页面解析而不是 yt-dlp（yt-dlp 对图文报错是正常的）
- `__INITIAL_STATE__` 必须括号配对截取（贪婪正则吞后续 JS）
- 原图下载必须带 Referer
- ocrmac 必须装进 .venv（xhs.py 在 .venv 里跑，装系统 Python 会静默返回空）
- **生僻工具名 ASR 必错，别指望换模型解决——用画面 OCR 兜底（见 references/模型选型.md 的最终结论）**
- 模型选型结论：paraformer-bilingual 是唯一主模型（详见 references/模型选型.md）

## 输出卡片格式

固定模板（ALWAYS）：
```markdown
# 📌 <标题>
- **类型**: 🎬 视频 / 🖼️ 图文
- **来源**: 小红书 (<链接>)
- **note_id**: `...`
- **博主**: <昵称> (`<ID>`)
- **时长**: <s>（视频）
- **收录**: <时间>

## 📝 正文        （图文）
## 🏷️ 标签
## 🎙️ 口播转写     （视频，> 引用）
## 📺 画面OCR      （有口播视频/无口播视频/图文有文字时均会有）
## 🖼️ 图片        （图文原图列表）
## 💡 资源线索     （英文标签识别 + 画面OCR中的项目/仓库自动提炼）
```

## 增值步骤（Agent 接手卡片后）

「资源线索」段自动识别英文标签 + 画面 OCR 里的 GitHub 仓库名（`owner/repo` 模式，实测可提炼 15 个）。真正价值在 AI 提炼：从正文/口播转写/OCR 里识别项目名/工具名，结合标题和标签做**拼写纠错**（ASR 音译错乱 → 用 OCR 权威拼写校正），输出结构化资源条目。

**输出模板（ALWAYS 遵循）**：
```markdown
📌 资源：<正确名称>（<一句话说明>）
   类型：开源项目 / 工具 / Agent / 框架
   亮点：<从转写/OCR 提炼的 1-3 条关键信息，如 star 数、特性>
   来源：小红书 <博主>《<标题>》 → <链接>
```

**示例（来自 GitHub 周榜实测卡片）**：
```markdown
📌 资源：MoneyPrinterTurbo（一句话生成短视频）
   类型：开源项目 · AI 视频
   亮点：一句话给主题自动写文案/配素材/剪成片；11.5 万 star；支持 9 种主流大模型；TikTok 一键发布
   来源：小红书 @某博主《GitHub 本周热门…》 → https://xhslink.cn/o/9EcARTChLhJ

📌 资源：OpenViking（面向 AI Agent 的上下文数据库）
   类型：开源项目 · Agent 基础设施（字节跳动/火山引擎开源）
   亮点：记忆/资源/技能挂到虚拟文件系统，agent 用 ls/tree/find 找上下文；3.2 万 star
   来源：同上
```

**拼写纠错规则**：
- ASR 转写里的音译错乱（"tap scturb o"）→ 用画面 OCR 的权威拼写（MoneyPrinterTurbo）校正
- 标题里的拼写错误（Fireclawl）→ 用 OCR/常识校正（Firecrawl）

## 合规边界

处理**自己收藏**的内容做个人学习，OK。不要高频请求（防风控）、不要批量分发他人笔记。
