---
name: toutiao-news-trends
description: |
  获取今日头条(www.toutiao.com)新闻热榜/热搜榜数据 | Get Toutiao (www.toutiao.com) news hot list/trending data
  包含时政要闻、财经、社会事件、国际新闻、科技发展及娱乐八卦等多领域的热门中文资讯 | Includes politics, finance, social events, international news, tech, entertainment and more
  输出热点标题、热度值与跳转链接 | Output hot titles, heat values and jump links
---

# 今日头条新闻热榜 | Toutiao News Hot List

## 技能概述 | Skill Overview

此技能用于抓取今日头条 PC 端热榜（hot-board）数据，包括：
This skill fetches Toutiao PC hot-board data, including:

- 热点标题 / Hot topic titles
- 热度值（HotValue）/ Heat values
- 详情跳转链接（去除冗余查询参数，便于分享）/ Detail links (cleaned for sharing)
- 封面图（如有）/ Cover images (if available)
- 标签（如"热门事件"等）/ Labels (e.g., "hot event")

数据来源：今日头条 (www.toutiao.com)
Data source: Toutiao (www.toutiao.com)

---

## 获取热榜 | Get Hot List

获取热榜（默认 50 条，按榜单顺序返回）：
Get hot list (default 50 items, in list order):

```bash
node scripts/toutiao.js hot
```

获取热榜前 N 条：
Get top N items:

```bash
node scripts/toutiao.js hot 10
```

---

## 返回数据字段说明 | Return Data Fields

| 字段 / Field | 类型 / Type | 说明 / Description |
|-------------|------------|-------------------|
| rank | number | 榜单排名（从 1 开始）| List ranking (starting from 1) |
| title | string | 热点标题 | Hot topic title |
| popularity | number | 热度值（HotValue，已转为数字；解析失败时为 0）| Heat value (parsed to number; 0 if failed) |
| link | string | 热点详情链接（已清理 query/hash）| Detail link (cleaned query/hash) |
| cover | string \| null | 封面图 URL（如有）| Cover image URL (if available) |
| label | string \| null | 标签/标识（如有）| Label (if available) |
| clusterId | string | 聚合 ID（字符串化）| Cluster ID (as string) |
| categories | string[] | 兴趣分类（如有）| Interest categories (if available) |

---

## 注意事项 | Notes

- 该接口为网页端公开接口，返回结构可能变动；若字段缺失可适当容错
  This interface is a public web interface; structure may change; handle missing fields gracefully
- 访问频繁可能触发风控，脚本内置随机 User-Agent 与超时控制
  Frequent access may trigger rate limiting; script includes random User-Agent and timeout control

---

## 数据采集与持久化 | Data Collection & Persistence

新增数据库存储和可视化功能，用于调研数据收集。
New database storage and visualization features for research data collection.

### 快速开始 | Quick Start

```bash
# 1. 初始化数据库（首次使用）/ Initialize database (first time)
cd scripts
python3 init_db.py

# 2. 采集数据并保存到数据库 / Collect data and save to database
python3 save_to_db.py 50

# 3. 查询数据 / Query data
python3 query.py today

# 4. 生成 HTML 报告 / Generate HTML report
python3 generate_html.py
open ../data/index.html
```

### 新增脚本说明 | New Scripts

| 脚本 / Script | 功能 / Function |
|--------------|-----------------|
| `init_db.py` | 初始化 SQLite 数据库 / Initialize SQLite database |
| `save_to_db.py` | 采集热榜并保存到数据库 / Collect hot list and save to DB |
| `query.py` | 查询数据库内容 / Query database content |
| `generate_html.py` | 生成可视化 HTML 报告 / Generate visual HTML report |

### 使用示例 | Usage Examples

```bash
# 采集50条热榜 / Collect 50 hot items
cd scripts
python3 save_to_db.py 50

# 查看今天的热榜 / View today's hot items
python3 query.py today

# 查看统计 / View statistics
python3 query.py stats 7
```

### 数据存储位置 | Data Storage Location

```
data/
├── toutiao.db        # SQLite 数据库 / Database
└── index.html        # HTML 报告（生成后）/ HTML report (generated)
```

---

## 致谢

感谢原作者@爱海贼的无处不在 的原版技能toutiao-news-trends开源，本技能基于原版技能进行强化和更新制作而成。
