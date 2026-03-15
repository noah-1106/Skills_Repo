---
name: zhihu-fetcher
description: 知乎数据获取 - 极简设计，支持三级认证降级（Browser Profile → File Cookie → Fallback），确保数据可靠获取
metadata:
  openclaw:
    emoji: "📰"
    category: "data-source"
    tags: ["zhihu", "fetch", "hot-list", "search", "fallback", "rate-limit", "cookie"]
---

# 知乎数据获取

极简设计的知乎数据抓取工具，支持**三级认证降级**，确保在各种环境下都能获取数据。

## 三级认证机制

```
优先级1: Browser Profile
    使用 OpenClaw browser 已登录的状态
    ↓ 失败/无登录态
优先级2: File Cookie  
    使用配置文件中固化的 Cookie
    ↓ 失败/无配置
优先级3: Fallback Source
    使用无需认证的备用数据源
```

## 快速开始

### 方式1: Browser Profile（推荐）

```bash
# 1. 登录知乎
browser open https://www.zhihu.com
# 完成登录

# 2. 获取数据
node snippets/fetch-hot.js
```

### 方式2: 固化 Cookie

```bash
# 1. 编辑配置文件，填入 Cookie
vim config/fallback-sources.json

# 2. 直接运行（无需 browser）
node snippets/fetch-hot.js
```

### 方式3: 仅使用备用源

```bash
# 无需任何认证
node snippets/test-simple.js
```

## Cookie 配置

编辑 `config/fallback-sources.json`：

```json
{
  "cookie": {
    "zhihu_session": "你的_session值",
    "z_c0": "你的_z_c0值",
    "_xsrf": "你的_xsrf值",
    "_zap": "...",
    "d_c0": "..."
  }
}
```

**获取 Cookie 方法：**
1. 浏览器打开 https://www.zhihu.com 并登录
2. 按 F12 打开开发者工具 → Application/Storage → Cookies
3. 复制对应字段的值

## 使用示例

```bash
# 获取30条热榜
node snippets/fetch-hot.js 30

# 保存到文件
node snippets/fetch-hot.js 50 ./zhihu-hot.json

# 自定义频率限制（5秒/次）
RATE_LIMIT=5000 node snippets/fetch-hot.js
```

## 在报告中使用

```javascript
const { fetchWithFallback } = require('./snippets/fetch-hot.js');

const data = await fetchWithFallback({
  limit: 30,
  rateLimitMs: 2000
});

// 自动选择最佳认证方式
console.log('认证方式:', data.meta.auth_method);
// browser_profile | file_cookie | fallback_source

report.zhihu = data.data;
```

## 文件结构

```
zhihu-fetcher/
├── SKILL.md                    # 本文档
├── config/
│   └── fallback-sources.json   # 配置：cookie + 备用源
└── snippets/
    ├── hot.js                  # 浏览器提取代码
    ├── search.js               # 搜索提取代码
    ├── rate-limiter.js         # 频率限制器
    ├── cookie-manager.js       # ✅ Cookie 管理
    ├── fallback.js             # 备用源获取
    ├── fetch-hot.js            # 完整热榜获取（三级认证）
    └── test-simple.js          # 测试脚本
```

## 数据输出

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

## 扩展备用源

编辑 `config/fallback-sources.json`：

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

## 认证优先级配置

如需调整认证顺序，编辑配置：

```json
{
  "auth": {
    "priority": [
      "file_cookie",        // 优先使用固化 cookie
      "browser_profile",    // 其次使用 browser
      "fallback_source"     // 最后使用备用源
    ]
  }
}
```

## 测试状态

✅ **已通过测试**
- Browser Profile: 需要手动登录
- File Cookie: 需配置后测试
- Fallback Source: ✅ 成功获取 26 条数据

```bash
# 测试备用源
node snippets/test-simple.js
```

## 注意事项

1. **Cookie 有效期** - 固化 cookie 可能过期，需定期更新
2. **频率限制** - 默认 2 秒/次，避免触发反爬
3. **备用源延迟** - GitHub 源可能有 1 小时延迟
4. **安全性** - cookie 配置文件中不要提交到 Git

## 适用场景

| 场景 | 推荐方式 | 原因 |
|------|---------|------|
| 日常开发 | Browser Profile | 最稳定、数据最全 |
| CI/CD 自动化 | File Cookie | 无需交互、可固化 |
| 应急备用 | Fallback Source | 无需任何认证 |
