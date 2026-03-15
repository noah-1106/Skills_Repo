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

# 知乎数据获取 / Zhihu Data Fetcher

极简设计的知乎数据抓取工具，支持**三级认证降级**，确保在各种环境下都能获取数据。

A minimalist Zhihu data fetching tool with **three-level authentication fallback**, ensuring reliable data retrieval in any environment.

---

## 三级认证机制 / Three-Level Auth Mechanism

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

## 快速开始 / Quick Start

### 方式1: Browser Profile（推荐）/ Method 1: Browser Profile (Recommended)

```bash
# 1. 登录知乎 / Login to Zhihu
browser open https://www.zhihu.com
# 完成登录 / Complete login

# 2. 获取数据 / Fetch data
node snippets/fetch-hot.js
```

### 方式2: 固化 Cookie / Method 2: File Cookie

```bash
# 1. 编辑配置文件，填入 Cookie / Edit config file and fill in cookies
vim config/fallback-sources.json

# 2. 直接运行（无需 browser）/ Run directly (no browser needed)
node snippets/fetch-hot.js
```

### 方式3: 仅使用备用源 / Method 3: Fallback Source Only

```bash
# 无需任何认证 / No authentication required
node snippets/test-simple.js
```

---

## Cookie 配置 / Cookie Configuration

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

## 使用示例 / Usage Examples

```bash
# 获取30条热榜 / Get 30 hot items
node snippets/fetch-hot.js 30

# 保存到文件 / Save to file
node snippets/fetch-hot.js 50 ./zhihu-hot.json

# 自定义频率限制（5秒/次）/ Custom rate limit (5 seconds per request)
RATE_LIMIT=5000 node snippets/fetch-hot.js
```

---

## 在报告中使用 / Use in Reports

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

## 文件结构 / File Structure

```
zhihu-fetcher/
├── SKILL.md                    # 本文档 / This document
├── config/
│   └── fallback-sources.json   # 配置：cookie + 备用源 / Config: cookie + fallback
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

## 数据输出 / Data Output

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

## 扩展备用源 / Extend Fallback Sources

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

## 认证优先级配置 / Auth Priority Configuration

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

## 测试状态 / Test Status

✅ **已通过测试 / Tested**
- Browser Profile: 需要手动登录 / Requires manual login
- File Cookie: 需配置后测试 / Requires configuration
- Fallback Source: ✅ 成功获取 26 条数据 / Successfully fetched 26 items

```bash
# 测试备用源 / Test fallback
node snippets/test-simple.js
```

---

## 注意事项 / Notes

1. **Cookie 有效期 / Cookie Expiration** - 固化 cookie 可能过期，需定期更新 / File cookies may expire, update regularly
2. **频率限制 / Rate Limit** - 默认 2 秒/次，避免触发反爬 / Default 2 sec/request, avoid anti-crawl
3. **备用源延迟 / Fallback Delay** - GitHub 源可能有 1 小时延迟 / GitHub source may have 1-hour delay
4. **安全性 / Security** - cookie 配置文件中不要提交到 Git / Don't commit cookie config to Git

---

## 适用场景 / Use Cases

| 场景 / Scenario | 推荐方式 / Recommended | 原因 / Reason |
|----------------|---------------------|--------------|
| 日常开发 / Daily dev | Browser Profile | 最稳定、数据最全 / Most stable, complete data |
| CI/CD 自动化 / Automation | File Cookie | 无需交互、可固化 / No interaction, reproducible |
| 应急备用 / Emergency | Fallback Source | 无需任何认证 / No auth required |
