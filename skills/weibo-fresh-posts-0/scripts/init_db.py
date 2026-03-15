#!/usr/bin/env python3
"""
Weibo Hot Search - Database Initialization
微博热搜数据库初始化
"""

import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "weibo.db"

def init_db():
    """初始化数据库"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 微博热搜文章表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hot_items (
            id TEXT PRIMARY KEY,              -- 文章ID: URL的SHA256
            platform TEXT DEFAULT 'weibo',    -- 平台标识
            channel_id TEXT,                  -- 频道ID: hot/social/entertainment/life
            channel_name TEXT,                -- 频道名称
            rank INTEGER,                     -- 排名
            title TEXT NOT NULL,              -- 标题
            url TEXT NOT NULL,                -- 链接
            heat INTEGER,                     -- 热度值
            tag TEXT,                         -- 标签: 热/新/商/官宣等
            fetched_at INTEGER DEFAULT (strftime('%s', 'now')), -- 抓取时间
            fetch_date TEXT,                  -- 抓取日期(YYYY-MM-DD)
            UNIQUE(url, fetch_date, channel_id)  -- 同一天同频道同URL只存一次
        )
    ''')
    
    # 话题内容表（可选，存储每个话题的帖子）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS topic_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hot_item_id TEXT,                 -- 关联的热搜条目ID
            author TEXT,                      -- 作者
            author_type TEXT,                 -- 类型: media/user
            content TEXT,                     -- 内容
            url TEXT,                         -- 帖子链接
            is_media BOOLEAN,                 -- 是否媒体账号
            fetched_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (hot_item_id) REFERENCES hot_items(id) ON DELETE CASCADE
        )
    ''')
    
    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hot_items_date ON hot_items(fetch_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hot_items_channel ON hot_items(channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hot_items_fetched ON hot_items(fetched_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_hot_items_rank ON hot_items(rank)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_topic_posts_hot ON topic_posts(hot_item_id)')
    
    # 抓取日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fetch_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            started_at INTEGER DEFAULT (strftime('%s', 'now')),
            ended_at INTEGER,
            found INTEGER DEFAULT 0,
            new INTEGER DEFAULT 0,
            status INTEGER DEFAULT 0,
            error TEXT
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_fetch_logs_date ON fetch_logs(started_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_fetch_logs_channel ON fetch_logs(channel_id)')
    
    conn.commit()
    conn.close()
    
    print(f"✅ Weibo database initialized: {DB_PATH}")
    return DB_PATH

if __name__ == '__main__':
    init_db()
