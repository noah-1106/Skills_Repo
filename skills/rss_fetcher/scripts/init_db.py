#!/usr/bin/env python3
"""
RSS Fetcher - Database Initialization
创建SQLite数据库和表结构
"""

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "rss_fetcher.db")
DB_PATH = os.path.normpath(DB_PATH)

def init_db():
    """初始化数据库"""
    # 确保目录存在
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 文章表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            category TEXT,
            title TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            author TEXT,
            published_at INTEGER NOT NULL,
            fetched_at INTEGER DEFAULT (strftime('%s', 'now')),
            content TEXT,
            status INTEGER DEFAULT 0
        )
    ''')
    
    # 添加category索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category)')
    
    # 3. 标签表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            type INTEGER DEFAULT 0,
            article_count INTEGER DEFAULT 0
        )
    ''')
    
    # 4. 文章-标签关联表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS article_tags (
            article_id TEXT NOT NULL,
            tag_id INTEGER NOT NULL,
            confidence REAL DEFAULT 1.0,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            PRIMARY KEY (article_id, tag_id),
            FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
    ''')
    
    # 5. 抓取日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fetch_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT,
            started_at INTEGER DEFAULT (strftime('%s', 'now')),
            ended_at INTEGER,
            found INTEGER DEFAULT 0,
            new INTEGER DEFAULT 0,
            status INTEGER,
            error TEXT
        )
    ''')
    
    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_fetch ON articles(fetched_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_article_tags_tag ON article_tags(tag_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_fetch_logs_time ON fetch_logs(started_at)')
    
    conn.commit()
    conn.close()
    
    print(f"✅ Database initialized: {DB_PATH}")

if __name__ == '__main__':
    init_db()
