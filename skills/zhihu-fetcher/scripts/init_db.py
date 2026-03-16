#!/usr/bin/env python3
"""
Zhihu Fetcher - Database Initialization
知乎热榜数据库初始化
"""

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "zhihu.db")
DB_PATH = os.path.normpath(DB_PATH)

def init_db():
    """初始化数据库"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 知乎热榜文章表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,              -- 文章ID: URL的SHA256
            platform TEXT DEFAULT 'zhihu',    -- 平台标识
            article_type TEXT DEFAULT 'hot',  -- 文章类型: hot(热榜)/search(搜索)/etc
            rank INTEGER,                     -- 排名
            title TEXT NOT NULL,              -- 标题
            url TEXT NOT NULL,                -- 链接
            heat INTEGER,                     -- 热度值
            author TEXT,                      -- 作者(如果有)
            summary TEXT,                     -- 摘要(如果有)
            published_at INTEGER,             -- 发布时间(Unix时间戳,知乎可能没有)
            fetched_at INTEGER DEFAULT (strftime('%s', 'now')), -- 抓取时间
            fetch_date TEXT,                  -- 抓取日期(YYYY-MM-DD),用于分区
            raw_data TEXT,                    -- 原始JSON数据
            UNIQUE(url, fetch_date)           -- 同一天同一URL只存一次
        )
    ''')
    
    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(fetch_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_type ON articles(article_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_fetched ON articles(fetched_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_rank ON articles(rank)')
    
    # 抓取日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fetch_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_type TEXT DEFAULT 'hot',
            started_at INTEGER DEFAULT (strftime('%s', 'now')),
            ended_at INTEGER,
            found INTEGER DEFAULT 0,
            new INTEGER DEFAULT 0,
            updated INTEGER DEFAULT 0,
            status INTEGER DEFAULT 0,         -- 0成功 1部分 2失败
            auth_method TEXT,                 -- 认证方式
            error TEXT
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_fetch_logs_date ON fetch_logs(started_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_fetch_logs_type ON fetch_logs(article_type)')
    
    conn.commit()
    conn.close()
    
    print(f"✅ Zhihu database initialized: {DB_PATH}")
    return DB_PATH

if __name__ == '__main__':
    init_db()
