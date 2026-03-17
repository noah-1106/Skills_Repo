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
- **当前版本 / Version**：1.2.0
- **发布日期 / Date**：2026-03-17

![Task Cockpit](docs/TaskCockpit.png)

#### ec_creator
- **技能名称 / Name**：执行卡片创建工具 / EC Creator
- **技能描述 / Description**：EC校验和自动修复工具，用于创建标准化执行卡片 / Validation and auto-fix tool for creating standardized Execution Cards
- **当前版本 / Version**：1.1.0
- **发布日期 / Date**：2026-03-15

### 数据采集 / Data Collection

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
