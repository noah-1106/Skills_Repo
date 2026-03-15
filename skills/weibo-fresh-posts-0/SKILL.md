---
name: weibo-hot-search
description: |
  微博多频道热搜数据采集与可视化 | Weibo Multi-Channel Hot Search Data Collection & Visualization
  支持热搜总榜、社会榜、文娱榜、生活榜同时抓取 | Supports hot search, social, entertainment, life channels
  数据持久化存储，提供HTML可视化报告 | Data persistence with HTML visualization reports
metadata:
  openclaw:
    emoji: "📱"
    category: "data-source"
    tags: ["weibo", "hot-search", "social-media", "trending"]
---

# Weibo Hot Search - 微博热搜数据采集 | Weibo Hot Search Data Collection

多频道微博热搜数据采集工具，支持数据持久化存储和可视化展示。
Multi-channel Weibo hot search data collection tool with persistence and visualization.

---

## 功能特性 | Features

- **多频道采集 / Multi-Channel Collection** - 同时抓取热搜总榜、社会榜、文娱榜、生活榜 | Fetch hot search, social, entertainment, life channels simultaneously
- **数据持久化 / Data Persistence** - 自动保存到SQLite数据库，支持历史查询 | Auto-save to SQLite database with historical query support
- **HTML可视化 / HTML Visualization** - 生成交互式报告，支持日期/频道/关键词筛选 | Generate interactive reports with date/channel/keyword filters
- **频道标签 / Channel Tags** - 热/新/商/官宣等标签识别 | Hot/New/Commercial/Official tag recognition

---

## 快速开始 | Quick Start

### 1. 初始化数据库 | Initialize Database

```bash
cd scripts
python3 init_db.py
```

### 2. 采集数据 | Collect Data

```bash
# 采集所有频道（每频道30条）/ Fetch all channels (30 per channel)
python3 save_to_db.py

# 指定数量 / Specify count
python3 save_to_db.py 50
```

### 3. 查询数据 | Query Data

```bash
# 查看今天的热搜 / View today's hot search
python3 query.py today

# 查看指定频道 / View specific channel
python3 query.py today hot

# 查看指定日期 / View specific date
python3 query.py date 2026-03-15

# 查看统计 / View statistics
python3 query.py stats 7
```

### 4. 生成HTML报告 | Generate HTML Report

```bash
python3 generate_html.py
open ../data/index.html
```

---

## 文件结构 | File Structure

```
weibo-fresh-posts-0/
├── SKILL.md                    # 本文档 | This document
├── data/
│   ├── weibo.db                # SQLite数据库 | SQLite database
│   └── index.html              # HTML可视化报告 | HTML visualization report
└── scripts/
    ├── init_db.py              # 数据库初始化 | DB initialization
    ├── db.py                   # 数据库操作模块 | DB operations module
    ├── fetch-hot-search.py     # 核心采集脚本 | Core collection script
    ├── save_to_db.py           # 采集并保存到数据库 | Collection & save
    ├── query.py                # 数据查询工具 | Data query tool
    └── generate_html.py        # HTML报告生成 | HTML report generation
```

---

## 数据库结构 | Database Schema

### hot_items 表 | hot_items Table
```sql
CREATE TABLE hot_items (
    id TEXT PRIMARY KEY,              -- URL+日期+频道的哈希 | Hash of URL+date+channel
    platform TEXT DEFAULT 'weibo',    -- 平台标识 | Platform identifier
    channel_id TEXT,                  -- hot/social/entertainment/life
    channel_name TEXT,                -- 频道名称 | Channel name
    rank INTEGER,                     -- 排名 | Ranking
    title TEXT NOT NULL,              -- 标题 | Title
    url TEXT NOT NULL,                -- 链接 | Link
    heat INTEGER,                     -- 热度值 | Heat value
    tag TEXT,                         -- 热/新/商/官宣等 | Hot/New/Commercial/Official
    fetched_at INTEGER,               -- 抓取时间 | Fetch time
    fetch_date TEXT                   -- 抓取日期 YYYY-MM-DD | Fetch date
);
```

### topic_posts 表 | topic_posts Table
```sql
CREATE TABLE topic_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hot_item_id TEXT,                 -- 关联的热搜条目 | Related hot item
    author TEXT,                      -- 作者 | Author
    author_type TEXT,                 -- media/user | Media or user
    content TEXT,                     -- 内容 | Content
    url TEXT,                         -- 链接 | Link
    is_media BOOLEAN                  -- 是否媒体账号 | Is media account
);
```

---

## 使用示例 | Usage Examples

### 采集数据 | Collect Data

```bash
# 基础采集 / Basic collection
python3 scripts/save_to_db.py

# 显示输出 / Sample output:
# ============================================================
# 📱 微博热搜采集 → 数据库 / Weibo Hot Search → Database
#    每频道采集数量 / Per channel count: 30
# # ============================================================
# 🔥 开始采集微博热搜 / Starting Weibo hot search collection...
# 
# 📡 [热搜总榜 / Hot Search]
#    ✅ 30 条热搜 / 30 hot items
#    新增 / New: 30 条
# 
# 📡 [社会榜 / Social]
#    ✅ 30 条热搜 / 30 hot items
#    新增 / New: 30 条
# ...
```

### 查询数据 | Query Data

```bash
# 今天的热搜 / Today's hot search
$ python3 query.py today

📱 微博热搜 - 2026-03-16 / Weibo Hot Search
================================================================================

【热搜总榜 / Hot Search】
  1. 315晚会曝光... [热] / 315 Gala exposure... [Hot]
      🔥 5,000,000
  2. 明星离婚... [爆] / Celebrity divorce... [Viral]
      🔥 3,200,000
...

【社会榜 / Social】
  1. 交通事故... / Traffic accident...
  2. 天气预报... / Weather forecast...
```

### 生成报告 | Generate Report

```bash
$ python3 generate_html.py

✅ HTML报告已生成 / HTML report generated: data/index.html
   共 / Total: 120 条记录
   日期范围 / Date range: 2026-03-15 ~ 2026-03-16
   频道 / Channels: 热搜总榜, 社会榜, 文娱榜, 生活榜

   打开方式 / Open methods:
   - Mac: open data/index.html
```

---

## HTML报告功能 | HTML Report Features

- 📅 **日期筛选 / Date Filter** - 选择具体日期 | Select specific date
- 📺 **频道筛选 / Channel Filter** - 点击频道标签过滤 | Click channel tags to filter
- 🔍 **关键词搜索 / Keyword Search** - 实时搜索标题 | Real-time title search
- 🔥 **热度显示 / Heat Display** - 显示热度值 | Show heat values
- 🏷️ **标签展示 / Tag Display** - 热/新/商/官宣等标签 | Hot/New/Commercial/Official tags
- 🏆 **排名标识 / Ranking Display** - Top 3 特殊颜色标识 | Top 3 special color marking

---

## 支持频道 | Supported Channels

| 频道ID / Channel ID | 频道名称 / Channel Name | 说明 / Description |
|--------------------|------------------------|-------------------|
| hot | 热搜总榜 / Hot Search | 综合热搜 / Comprehensive hot |
| social | 社会榜 / Social | 社会新闻 / Social news |
| entertainment | 文娱榜 / Entertainment | 娱乐文化 / Entertainment & culture |
| life | 生活榜 / Life | 生活方式 / Lifestyle |

---

## 原始采集脚本 | Original Collection Script

如需直接获取JSON数据：
For direct JSON output:

```bash
# 输出到文件 / Output to file
python3 fetch-hot-search.py -o weibo-hot.json

# 输出到stdout（静默模式）/ Output to stdout (quiet mode)
python3 fetch-hot-search.py -q

# 抓取详细内容（前10个话题的帖子）/ Fetch detailed content (posts for top 10 topics)
python3 fetch-hot-search.py -c --content-limit 2 -o weibo-hot.json
```

---

## 数据查询SQL示例 | SQL Query Examples

```bash
# 进入数据库 / Enter database
sqlite3 data/weibo.db

# 今天的热搜总榜 / Today's hot search
SELECT rank, title, heat, tag FROM hot_items 
WHERE fetch_date = date('now') AND channel_id = 'hot'
ORDER BY rank LIMIT 10;

# 最近7天每天各频道数量 / Daily channel counts for last 7 days
SELECT fetch_date, channel_name, COUNT(*) 
FROM hot_items 
WHERE fetch_date >= date('now', '-7 days')
GROUP BY fetch_date, channel_id;

# 包含"315"的热搜 / Hot search containing "315"
SELECT * FROM hot_items 
WHERE title LIKE '%315%' 
ORDER BY fetch_date DESC, heat DESC;
```

---

## 注意事项 | Notes

1. **需要登录 / Login Required** - 使用 browser open https://weibo.com 登录 | Use browser open https://weibo.com to login
2. **频率限制 / Rate Limiting** - 每次抓取有短暂延迟，避免触发反爬 | Brief delay between fetches to avoid anti-crawl
3. **数据去重 / Deduplication** - 同一天同一URL同一频道只保存一次 | Same URL on same day/channel saved once only
4. **热度更新 / Heat Update** - 重新抓取会更新热度值 | Refetching updates heat values

---

## 更新记录 | Changelog

- 2026-03-16: 添加数据库持久化和HTML可视化功能 / Added database persistence and HTML visualization
