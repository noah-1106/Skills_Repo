---
name: zhihu-fetcher
description: |
  知乎数据获取 - 极简设计，支持三级认证降级（Browser Profile → File Cookie → Fallback），确保数据可靠获取
  Zhihu Data Fetcher - Minimalist design with three-level auth fallback (Browser Profile → File Cookie → Fallback), ensuring reliable data retrieval
metadata:
  openclaw:
    emoji: "📰"
    category: "data-source"
    tags: ["zhihu", "fetch", "hot-list", "search", "fallback", "rate-limit", "cookie"]
---

# 知乎数据获取 | Zhihu Data Fetcher

极简设计的知乎数据抓取工具，支持**三级认证降级**，确保在各种环境下都能获取数据。
A minimalist Zhihu data fetching tool with **three-level authentication fallback**, ensuring reliable data retrieval in any environment.

---

## 三级认证机制 | Three-Level Auth Mechanism

```
优先级1: Browser Profile / 浏览器配置
    使用 OpenClaw browser 已登录的状态 / Use OpenClaw browser logged-in state
    ↓ 失败/无登录态 / Fail or no login state
优先级2: File Cookie / 文件 Cookie
    使用配置文件中固化的 Cookie / Use cookie固化 in config file
    ↓ 失败/无配置 / Fail or no config
优先级3: Fallback Source / 备用源
    使用无需认证的备用数据源 / Use unauthenticated fallback data source
```

---

## 快速开始 | Quick Start

### 方式1: Browser Profile（推荐）| Method 1: Browser Profile (Recommended)

```bash
# 1. 登录知乎 / Login to Zhihu
browser open https://www.zhihu.com
# 完成登录 / Complete login

# 2. 获取数据并保存到数据库 / Fetch data and save to database
cd scripts
python3 save_to_db.py 50
```

### 方式2: 固化 Cookie | Method 2: File Cookie

```bash
# 1. 编辑配置文件，填入 Cookie / Edit config file and fill in cookies
vim config/fallback-sources.json

# 2. 直接运行（无需 browser）/ Run directly (no browser needed)
python3 scripts/save_to_db.py 50
```

### 方式3: 仅使用备用源 | Method 3: Fallback Source Only

```bash
# 无需任何认证 / No authentication required
python3 scripts/save_to_db.py
# 会自动降级到 fallback source / Auto-downgrade to fallback source
```

---

## 数据库使用 | Database Usage

### 初始化数据库 | Initialize Database

```bash
python3 scripts/init_db.py
```

### 采集并保存 | Collect and Save

```bash
# 采集50条热榜并保存到数据库 / Collect 50 hot items and save to database
python3 scripts/save_to_db.py 50

# 显示结果 / Display results:
# ✅ 完成! / Complete!
#    发现 / Found: 50 条
#    新增 / New: 50 条
#    更新 / Updated: 0 条
```

### 查询数据 | Query Data

```bash
# 查看今天的热榜 / View today's hot list
python3 scripts/query.py today

# 查看指定日期 / View specific date
python3 scripts/query.py date 2026-03-15

# 查看最近7天统计 / View last 7 days stats
python3 scripts/query.py stats 7

# 查看抓取日志 / View fetch logs
python3 scripts/query.py logs
```

### 数据库结构 | Database Schema

```sql
-- 文章表 / Articles table
CREATE TABLE articles (
    id TEXT PRIMARY KEY,              -- 文章ID (URL的SHA256) / Article ID (URL SHA256)
    platform TEXT DEFAULT 'zhihu',    -- 平台标识 / Platform identifier
    article_type TEXT DEFAULT 'hot',  -- 类型: hot/search / Type: hot/search
    rank INTEGER,                     -- 排名 / Ranking
    title TEXT NOT NULL,              -- 标题 / Title
    url TEXT NOT NULL,                -- 链接 / Link
    heat INTEGER,                     -- 热度值 / Heat value
    author TEXT,                      -- 作者 / Author
    summary TEXT,                     -- 摘要 / Summary
    published_at INTEGER,             -- 发布时间 / Published time
    fetched_at INTEGER,               -- 抓取时间 / Fetched time
    fetch_date TEXT,                  -- 抓取日期 (YYYY-MM-DD) / Fetch date
    raw_data TEXT,                    -- 原始JSON / Raw JSON
    UNIQUE(url, fetch_date)           -- 同一天同一URL只存一次 / Unique per URL per day
);

-- 抓取日志表 / Fetch logs table
CREATE TABLE fetch_logs (...);
```

---

## Cookie 配置 | Cookie Configuration

编辑 `config/fallback-sources.json` / Edit `config/fallback-sources.json`：

```json
{
  "cookie": {
    "zhihu_session": "你的_session值 / your_session_value",
    "z_c0": "你的_z_c0值 / your_z_c0_value",
    "_xsrf": "你的_xsrf值 / your_xsrf_value",
    "_zap": "...",
    "d_c0": "..."
  }
}
```

**获取 Cookie 方法 / How to get cookies：**
1. 浏览器打开 https://www.zhihu.com 并登录 / Open browser and login
2. 按 F12 打开开发者工具 → Application/Storage → Cookies / Press F12 → Application/Storage → Cookies
3. 复制对应字段的值 / Copy the corresponding field values

---

## 使用示例 | Usage Examples

```bash
# 获取30条热榜 / Get 30 hot items
node snippets/fetch-hot.js 30

# 保存到文件 / Save to file
node snippets/fetch-hot.js 50 ./zhihu-hot.json

# 自定义频率限制（5秒/次）/ Custom rate limit (5 seconds per request)
RATE_LIMIT=5000 node snippets/fetch-hot.js
```

---

## 在报告中使用 | Use in Reports

```javascript
const { fetchWithFallback } = require('./snippets/fetch-hot.js');

const data = await fetchWithFallback({
  limit: 30,
  rateLimitMs: 2000
});

// 自动选择最佳认证方式 / Auto-select best auth method
console.log('认证方式 / Auth method:', data.meta.auth_method);
// browser_profile | file_cookie | fallback_source

report.zhihu = data.data;
```

---

## 文件结构 | File Structure

```
zhihu-fetcher/
├── SKILL.md                    # 本文档 / This document
├── config/
│   └── fallback-sources.json   # 配置：cookie + 备用源 / Config: cookie + fallback
├── data/
│   ├── zhihu.db                # SQLite数据库 (自动创建) / SQLite DB (auto-created)
│   └── index.html              # HTML可视化报告 (自动生成) / HTML report (auto-generated)
├── scripts/
│   ├── init_db.py              # 数据库初始化 / DB initialization
│   ├── db.py                   # 数据库操作模块 / DB operations module
│   ├── save_to_db.py           # 采集并保存到数据库 / Collection & save
│   ├── query.py                # 数据查询工具 / Data query tool
│   └── generate_html.py        # HTML可视化报告生成 / HTML report generation
└── snippets/
    ├── hot.js                  # 浏览器提取代码 / Browser extraction
    ├── search.js               # 搜索提取代码 / Search extraction
    ├── rate-limiter.js         # 频率限制器 / Rate limiter
    ├── cookie-manager.js       # Cookie 管理 / Cookie manager
    ├── fallback.js             # 备用源获取 / Fallback source
    ├── fetch-hot.js            # 完整热榜获取（三级认证）/ Full hot list (3-level auth)
    └── test-simple.js          # 测试脚本 / Test script
```

---

## 数据输出 | Data Output

```json
{
  "meta": {
    "source": "zhihu",
    "fetch_time": "2026-03-15T08:30:00.000Z",
    "mode": "hot",
    "auth_method": "file_cookie",
    "rate_limited": true,
    "count": 30
  },
  "data": [
    {
      "rank": 1,
      "title": "...",
      "heat": 4030000,
      "url": "..."
    }
  ]
}
```

---

## 生成HTML可视化报告 | Generate HTML Visualization Report

```bash
# 生成可视化HTML报告 / Generate visual HTML report
python3 scripts/generate_html.py

# 打开查看 / Open to view
open data/index.html
```

**HTML报告功能 / HTML Report Features：**
- 📅 **日期筛选 / Date Filter** - 选择具体日期或日期范围 | Select specific date or range
- 🔍 **关键词搜索 / Keyword Search** - 实时搜索标题 | Real-time title search
- 🔥 **热度筛选 / Heat Filter** - 按最小热度值筛选 | Filter by minimum heat value
- 🏆 **排名标识 / Ranking Display** - Top 3 特殊颜色标识 | Top 3 special color marking
- 📊 **数据统计 / Data Stats** - 实时显示筛选结果数量 | Real-time filtered results count

---

## 直接查询数据库 | Direct Database Query

```bash
# 进入数据库 / Enter database
sqlite3 data/zhihu.db

# 查看今天的数据 / View today's data
SELECT rank, title, heat FROM articles 
WHERE fetch_date = date('now') 
ORDER BY rank LIMIT 10;

# 查看最近7天每天采集多少条 / View daily count for last 7 days
SELECT fetch_date, COUNT(*) FROM articles 
WHERE fetch_date >= date('now', '-7 days') 
GROUP BY fetch_date ORDER BY fetch_date DESC;

# 查看抓取日志 / View fetch logs
SELECT * FROM fetch_logs ORDER BY started_at DESC LIMIT 5;
```

---

## 扩展备用源 | Extend Fallback Sources

编辑 `config/fallback-sources.json` / Edit `config/fallback-sources.json`：

```json
{
  "fallbacks": [
    {
      "name": "zhihu-hot-hub",
      "url": "...",
      "type": "markdown",
      "priority": 1
    },
    {
      "name": "another-api",
      "url": "https://api.example.com/zhihu-hot.json",
      "type": "json",
      "priority": 2
    }
  ]
}
```

---

## 认证优先级配置 | Auth Priority Configuration

如需调整认证顺序，编辑配置 / To adjust auth priority, edit config：

```json
{
  "auth": {
    "priority": [
      "file_cookie",        // 优先使用固化 cookie / Prefer file cookie
      "browser_profile",    // 其次使用 browser / Then browser
      "fallback_source"     // 最后使用备用源 / Finally fallback
    ]
  }
}
```

---

## 测试状态 | Test Status

✅ **已通过测试 / Tested**
- Browser Profile: 需要手动登录 / Requires manual login
- File Cookie: 需配置后测试 / Requires configuration
- Fallback Source: ✅ 成功获取 26 条数据 / Successfully fetched 26 items

```bash
# 测试备用源 / Test fallback
node snippets/test-simple.js
```

---

## 注意事项 | Notes

1. **Cookie 有效期 / Cookie Expiration** - 固化 cookie 可能过期，需定期更新 / File cookies may expire, update regularly
2. **频率限制 / Rate Limiting** - 默认 2 秒/次，避免触发反爬 / Default 2 sec/request, avoid anti-crawl
3. **备用源延迟 / Fallback Delay** - GitHub 源可能有 1 小时延迟 / GitHub source may have 1-hour delay
4. **安全性 / Security** - cookie 配置文件中不要提交到 Git / Don't commit cookie config to Git

---

## 适用场景 | Use Cases

| 场景 / Scenario | 推荐方式 / Recommended | 原因 / Reason |
|----------------|---------------------|--------------|
| 日常开发 / Daily dev | Browser Profile | 最稳定、数据最全 / Most stable, complete data |
| CI/CD 自动化 / Automation | File Cookie | 无需交互、可固化 / No interaction, reproducible |
| 应急备用 / Emergency | Fallback Source | 无需任何认证 / No auth required |

---

## 设计对比 | Design Comparison

| 方案 / Solution | 复杂度 / Complexity | 可靠性 / Reliability | 适用场景 / Use Case |
|----------------|---------------------|---------------------|---------------------|
| **本方案 / This solution** | 低 / Low | 高（三级降级）/ High (3-level) | 调研数据获取 / Research data |
| 小红书式 / XHS-style | 高 / High | 高 / High | 运营自动化 / Ops automation |
| 纯 API / Pure API | 中 / Medium | 中 / Medium | 生产环境 / Production |
