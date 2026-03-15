-- RSS Fetcher 数据库结构参考
-- 用于手动创建或理解表结构

-- 1. 文章表
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,              -- 文章ID (URL的SHA256)
    source_id TEXT NOT NULL,          -- RSS源ID
    category TEXT,                    -- 文章分类 (继承自sources.json)
    title TEXT NOT NULL,              -- 文章标题
    url TEXT UNIQUE NOT NULL,         -- 文章链接
    author TEXT,                      -- 作者
    published_at INTEGER NOT NULL,    -- 发布时间 (Unix时间戳, 0表示不可信)
    fetched_at INTEGER DEFAULT (strftime('%s', 'now')), -- 抓取时间
    content TEXT,                     -- 正文内容
    status INTEGER DEFAULT 0          -- 0新 1已处理 2已归档
);

-- 2. 标签表
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,        -- 标签名: ai, llm, finance...
    type INTEGER DEFAULT 0,           -- 0自动 1人工 2系统
    article_count INTEGER DEFAULT 0   -- 关联文章数（冗余统计）
);

-- 3. 文章-标签关联表
CREATE TABLE IF NOT EXISTS article_tags (
    article_id TEXT NOT NULL,
    tag_id INTEGER NOT NULL,
    confidence REAL DEFAULT 1.0,      -- 标签置信度 0.0-1.0
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    PRIMARY KEY (article_id, tag_id),
    FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

-- 4. 抓取日志表
CREATE TABLE IF NOT EXISTS fetch_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT,                   -- RSS源ID
    started_at INTEGER DEFAULT (strftime('%s', 'now')),
    ended_at INTEGER,
    found INTEGER DEFAULT 0,          -- 发现文章数
    new INTEGER DEFAULT 0,            -- 新增文章数
    status INTEGER,                   -- 0成功 1部分 2失败
    error TEXT                        -- 错误详情
);

-- 索引优化
CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_fetch ON articles(fetched_at);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_article_tags_tag ON article_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_fetch_logs_time ON fetch_logs(started_at);

-- 常用查询示例

-- 查看今天所有文章
SELECT a.title, a.url, a.source_id
FROM articles a
WHERE date(a.fetched_at, 'unixepoch', 'localtime') = date('now', 'localtime')
ORDER BY a.published_at DESC;

-- 查看时间不可靠的文章
SELECT title, url FROM articles WHERE published_at = 0;

-- 查看抓取统计
SELECT 
    source_id,
    COUNT(*) as article_count,
    MAX(fetched_at) as last_fetch
FROM articles
GROUP BY source_id;
