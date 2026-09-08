![Skills_Repo Banner](docs/Skills_Repo.jpg)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![爱发电](https://img.shields.io/badge/爱发电-支持我-FF6B6B?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0id2hpdGUiPjx0ZXh0IHg9IjEyIiB5PSIxOCIgZm9udC1zaXplPSIxMiIgdGV4dC1hbmNob3I9Im1pZGRsZSI+5oSb5YiGPC90ZXh0Pjwvc3ZnPg==&logoColor=white)](https://ifdian.net/a/noahtan)

# Skills_Repo

Noah和他的AI助理们开发的skills仓库，全部开源，欢迎取用。如果你觉得对你有帮助，可以帮我买杯咖啡，感谢~~

A skill repository developed by Noah and his AI assistants. All open source, feel free to use. Buy me a coffee if you find it helpful :) Thanks~~

## 技能列表 / Skills

### 核心工具 / Core Tools

#### longtask_system
- **技能名称 / Name**：长程任务管理系统 / LongTask System
- **技能描述 / Description**：状态驱动的任务编排引擎，用于管理跨会话的复杂工作流，**支持可视化驾驶舱实时监控** / State-driven task orchestration engine for managing complex workflows across sessions, with **visual cockpit for real-time monitoring**
- **当前版本 / Version**：1.2.2
- **发布日期 / Date**：2026-03-24

![Task Cockpit](docs/TaskCockpit.png)

#### ec_creator
- **技能名称 / Name**：执行卡片创建工具 / EC Creator
- **技能描述 / Description**：EC校验和自动修复工具，用于创建标准化执行卡片 / Validation and auto-fix tool for creating standardized Execution Cards
- **当前版本 / Version**：1.1.0
- **发布日期 / Date**：2026-03-15

#### scribe
- **技能名称 / Name**：本地录音转写 / Local Audio Transcription
- **技能描述 / Description**：音频/视频 → 带时间戳文字稿（TXT/SRT/JSON），可选说话人标记（CAM++）。常驻本地服务，**Agent 可自动调用**（上传转写 + 下载留存全自动闭环）。自包含跨平台：代码全在 skill 内，首次 setup.py 自动装依赖 + 下载模型 / Audio/video → timestamped transcript (TXT/SRT/JSON), optional speaker diarization (CAM++). Persistent local service with **full Agent automation** (upload → transcribe → download loop). Self-contained & cross-platform: all code in skill, setup.py installs deps + downloads models on first run
- **当前版本 / Version**：1.0.0
- **发布日期 / Date**：2026-08-25
- **安装 / Install**：`python3 scripts/setup.py`（跨平台：venv + funasr/torch + SenseVoice 模型 897MB，modelscope 国内源）；启动 `python3 scripts/start.py`；Agent 调用 `python3 scripts/scribe.py <音频> [--diarize]`

#### geopulse
- **技能名称 / Name**：自托管 AI 品牌可见性监测系统 / Self-hosted AI Brand Visibility Monitor (GEO)
- **技能描述 / Description**：完整的 GEO（生成式引擎优化）监测系统，前后端自带、skill 内自包含。监测品牌在 AI 引擎回答中的可见率、声量份额、引用深度（提名/描述/推荐）、四维热力图（品牌词/场景词/对比词/选购词），一键导出可发客户的诊断报告。demo 引擎零 API Key 开箱即用，填任意 OpenAI 兼容端点（DeepSeek/智谱/通义/Kimi/OpenAI）即接入生产，数据全程留在本机 `~/.geopulse/` / Complete GEO (Generative Engine Optimization) monitoring system with bundled frontend & backend. Tracks brand visibility, share-of-voice, mention depth (named/described/recommended) and a 4-dimension heatmap, exports client-ready diagnostic reports. Works out-of-the-box with a zero-key demo engine; connect any OpenAI-compatible endpoint (DeepSeek/Zhipu/Qwen/Kimi/OpenAI) for production. All data stays local.
- **当前版本 / Version**：1.2.0
- **发布日期 / Date**：2026-09-07
- **安装 / Install**：`pip3 install --user -r skills/geopulse/requirements.txt` 后 `python3 skills/geopulse/scripts/geopulse_ctl.py start`（首次自动建库+演示数据）；日常管理 `geopulse_ctl.py status/engine/brands/prompts/run/report`
- **自检 / Self-test**：`python3 skills/geopulse/tests/test_integration.py`（36 项集成测试）
- **浏览器**：`http://127.0.0.1:8700`（仪表盘 / Prompt 库 / 品牌与引擎）

---

## 内容创作 / Content Creation

#### style_fingerprint
- **技能名称 / Name**：写作风格指纹 / Style Fingerprint
- **技能描述 / Description**：分析、校验、合并中文写作风格指纹，提取节奏、功能词习惯、句式修辞与范例句，供AI写作助手模仿与回归校验（v2 新增 compare 新稿偏差报告 / merge 多文本合并 / selftest 回归测试） / Analyze, compare and merge Chinese writing style fingerprints - rhythm, function-word habits, rhetoric patterns and exemplar sentences for AI writing agents (v2: compare deviation reports, multi-text merge, built-in regression tests)
- **当前版本 / Version**：2.0.0
- **发布日期 / Date**：2026-08-30

#### weibo-publisher
- **技能名称 / Name**：微博发布器 / Weibo Publisher
- **技能描述 / Description**：通过浏览器自动化在 m.weibo.cn 发布微博内容，支持图文发布、自动验证和防重复机制 / Publish to Weibo via browser automation on m.weibo.cn, supporting text/image posts with verification and anti-duplication measures
- **当前版本 / Version**：1.0.0
- **发布日期 / Date**：2026-03-19

#### glm-asr
- **技能名称 / Name**：智谱语音转文本 / GLM-ASR Speech-to-Text
- **技能描述 / Description**：智谱 GLM-ASR-2512 语音转文本 CLI。音频（wav/mp3，≤25MB，≤30秒）进，转录文本出，支持热词表（专有名词识别修正，实测"质朴→智谱"逐字修正）与上下文提示。模型/端点/API Key 全部 config.json 可换（Coding Plan 与普通端点双验证可用）。内置长音频 ffmpeg 切分指引、视频容器拦截（MP4 自动给抽音轨命令）、并发与大小限制指引 / Zhipu GLM-ASR-2512 speech-to-text CLI. Audio (wav/mp3, ≤25MB, ≤30s) in, transcript out, with hotwords (proper-noun correction), context prompt, config-swappable endpoint/model/key, long-audio ffmpeg splitting guide and MP4 video-container detection with audio-extraction hints
- **当前版本 / Version**：1.0.0
- **发布日期 / Date**：2026-09-08
- **安装 / Install**：填入你的智谱 API key 到 `skills/glm-asr/config.json`（或设环境变量 `GLM_ASR_API_KEY`），然后 `python3 skills/glm-asr/scripts/glm_asr.py audio.mp3 --hotwords "专有名词"`
- **限制**：wav/mp3 only、≤25MB、≤30s、并发 ≤10（超限 429/1302）；MP4/视频先抽音轨（报错自带命令）

#### minimax-av
- **技能名称 / Name**：MiniMax 全模态理解 / MiniMax Multimodal Understanding (Audio + Vision)
- **技能描述 / Description**：MiniMax 全模态理解 CLI，双子命令合一。`transcribe`：音频转文本（asr-1.0，支持 wav/aiff/flac/m4a/mp3/aac/opus/ogg，≤50MB/≤500 秒，**支持 SRT/VTT 字幕与 verbose_json 说话人分离时间戳**）；`understand`：视觉理解（MiniMax-M3 原生，**视频 mp4/mov 等 + 图片 png/jpg/webp/gif 可混合多文件**，≤100MB，问答/摘要/JSON 结构化输出，自动剥离推理段）。模型/端点/API Key 全部 config.json 可换 / MiniMax multimodal understanding CLI with two subcommands. `transcribe`: audio-to-text (asr-1.0, 8 formats ≤50MB/≤500s, SRT/VTT subtitles & verbose_json speaker-diarization timestamps). `understand`: vision (MiniMax-M3 native, videos + images mixed multi-file ≤100MB, Q&A/summary/JSON, auto strips reasoning). Config-swappable endpoint/model/key
- **当前版本 / Version**：1.2.0
- **发布日期 / Date**：2026-09-08
- **安装 / Install**：填入你的 MiniMax API key 到 `skills/minimax-av/config.json`（或设环境变量 `MINIMAX_API_KEY`），然后 `python3 skills/minimax-av/scripts/minimax_av.py transcribe audio.mp3 --format srt` 或 `python3 skills/minimax-av/scripts/minimax_av.py understand video.mp4 cover.png --prompt "总结内容"`
- **限制**：ASR ≤50MB/≤500 秒（超长直接拒）；视频理解需 MiniMax-M3（其他模型收到视频"看不到"）；M3 推理占 max_tokens（默认 4096，空回答时调大）；图片 >2MB 建议先缩放

---

## 技能管理 / Skill Management

#### skills-hub
- **技能名称 / Name**：技能市场管理器 / Skills Hub
- **技能描述 / Description**：从 ClawHub 技能市场实时搜索、安装、更新技能——零依赖纯 HTTP，无需账号。每次搜索都是最新数据（无缓存架构），匿名下载安装，含来源溯源标记 / Live search, install, and update skills from the ClawHub marketplace. Zero dependencies, no account needed. Always-fresh results (no cache), anonymous download & install, origin tracking included.
- **当前版本 / Version**：1.2.0
- **发布日期 / Date**：2026-08-30

---

## 数据采集 / Data Collection

📊 **所有数据采集技能均包含可视化 HTML 报告功能**
📊 **All data collection skills include visual HTML reports**

#### rss_fetcher
- **技能名称 / Name**：RSS采集器 / RSS Fetcher
- **技能描述 / Description**：统一的RSS采集与管理系统，支持增量抓取、自动去重、自动标签，**生成可视化HTML报告** / Unified RSS feed fetcher with incremental fetching, auto-dedup, auto-tagging, and **visual HTML reports**
- **当前版本 / Version**：1.1.0
- **发布日期 / Date**：2026-03-16

#### zhihu-fetcher
- **技能名称 / Name**：知乎数据获取 / Zhihu Fetcher
- **技能描述 / Description**：知乎数据抓取工具，支持三级认证降级机制，**生成可视化HTML报告** / Zhihu data fetching tool with three-level authentication fallback, and **visual HTML reports**
- **当前版本 / Version**：1.0.0
- **发布日期 / Date**：2026-03-15

#### baidu-hot-cn-1
- **技能名称 / Name**：百度热榜监控 / Baidu Hot Monitor
- **技能描述 / Description**：百度热搜榜实时监控，支持数据库存储，**生成可视化HTML报告** / Real-time Baidu hot search monitoring with database persistence, and **visual HTML reports**
- **当前版本 / Version**：1.0.0
- **发布日期 / Date**：2026-03-16

#### weibo-fresh-posts-0
- **技能名称 / Name**：微博热搜采集 / Weibo Hot Search
- **技能描述 / Description**：多频道微博热搜数据采集，支持热搜总榜/社会榜/文娱榜/生活榜，**生成可视化HTML报告** / Multi-channel Weibo hot search collector, and **visual HTML reports**
- **当前版本 / Version**：1.0.0
- **发布日期 / Date**：2026-03-16

#### toutiao-news-trends-0
- **技能名称 / Name**：今日头条热榜 / Toutiao Hot News
- **技能描述 / Description**：今日头条热榜数据获取，支持持久化存储，**生成可视化HTML报告** / Toutiao hot news fetcher with persistence, and **visual HTML reports**
- **当前版本 / Version**：1.0.0
- **发布日期 / Date**：2026-03-16

#### douyin-hot-trend-1
- **技能名称 / Name**：抖音热榜 / Douyin Hot List
- **技能描述 / Description**：抖音热榜/热搜榜数据获取，包含热门视频/挑战赛/音乐，**生成可视化HTML报告** / Douyin hot list fetcher with videos/challenges/music, and **visual HTML reports**
- **当前版本 / Version**：1.0.0
- **发布日期 / Date**：2026-03-16
- **致谢 / Credits**：基于 [douyin-hot-trend](https://github.com/franklu0819-lang/douyin-hot-trend) 修改，感谢 [@franklu0819-lang](https://github.com/franklu0819-lang)

#### xhs-dl
- **技能名称 / Name**：小红书单篇下载器 / Xiaohongshu (XHS) Single-Note Downloader
- **技能描述 / Description**：把小红书笔记链接（视频/图文）变成结构化资源卡片——标题/正文/标签/博主 + **本地ASR口播转写**（中英混合）+ **画面OCR**（工具名/仓库名权威拼写，能纠正标题拼写错误）+ 图文原图下载。全本地运行，**一套 Python 脚本双平台（Mac/Windows）**，零外部服务依赖 / Turn XHS note links into structured resource cards — title/body/tags/author + **local ASR transcription** (Chinese-English) + **screen OCR** (authoritative tool/repo name spelling, auto-corrects typos) + image download. Fully local, **one Python codebase for both Mac & Windows**, zero external services
- **当前版本 / Version**：1.0.0
- **发布日期 / Date**：2026-08-25
- **安装 / Install**：`python3 scripts/setup.py`（跨平台：建 venv + 装依赖（**内置 yt-dlp**）+ 下载 ASR 模型 224MB，走 hf-mirror）；仅剩 ffmpeg 需系统安装

### Coze 集成 / Coze Integration

#### coze-workflow
- **技能名称 / Name**：Coze 工作流执行 / Coze Workflow
- **技能描述 / Description**：Coze 工作流执行技能，纯净的调用层，不处理业务逻辑 / Coze workflow executor, pure invocation layer with no business logic
- **当前版本 / Version**：1.1.3
- **发布日期 / Date**：2026-03-15

#### image-gen-coze
- **技能名称 / Name**：图像生成 / Image Generation
- **技能描述 / Description**：基于 Coze 的图像生成技能，使用 Seedream 4.5 模型，负责参数构建和结果解析 / Image generation via Coze using Seedream 4.5 model
- **当前版本 / Version**：1.1.3
- **发布日期 / Date**：2026-03-15

---

## 目录结构 / Directory Structure

```
Skills_Repo/
├── skills/                 # 技能目录 / Skills directory
│   └── [skill_name]/       # 各技能文件夹 / Individual skill folders
├── docs/                   # 文档 / Documentation
└── README.md               # 本文件
```

👉 所有技能请查看 [`skills/`](skills/) 目录
👉 View all skills in the [`skills/`](skills/) directory

---

## 使用方式 / Usage

每个技能文件夹内包含详细的 `SKILL.md` 文档，说明安装和使用方法。
Each skill folder contains detailed `SKILL.md` documentation for installation and usage.

### 安装技能 / Install Skill

```bash
# 复制到 OpenClaw skills 目录
cp -r skills/[skill_name] ~/.openclaw/skills/

# 或使用 clawhub（如果已发布）
clawhub install [skill_name]
```

---

## 贡献指南 / Contributing

欢迎提交 PR 和 Issue！
PRs and Issues are welcome!

---

## 许可证 / License

[MIT](LICENSE)

---

## 支持我 / Support Me

如果这个项目对你有帮助，可以请我喝杯咖啡 ☕️
If this project helps you, buy me a coffee ☕️

[![爱发电](https://img.shields.io/badge/爱发电-支持我-FF6B6B?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0id2hpdGUiPjx0ZXh0IHg9IjEyIiB5PSIxOCIgZm9udC1zaXplPSIxMiIgdGV4dC1hbmNob3I9Im1pZGRsZSI+5oSb5YiGPC90ZXh0Pjwvc3ZnPg==&logoColor=white)](https://ifdian.net/a/noahtan)
