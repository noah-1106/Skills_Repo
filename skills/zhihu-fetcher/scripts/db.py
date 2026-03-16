#!/usr/bin/env python3
"""
Zhihu Fetcher - Database Operations
知乎热榜数据库操作模块
"""

import sqlite3
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "zhihu.db"

def get_db():
    """获取数据库连接"""
    return sqlite3.connect(DB_PATH)

def generate_id(url):
    """生成文章ID (URL的SHA256前16位)"""
    return hashlib.sha256(url.encode()).hexdigest()[:16]

def get_today_str():
    """获取今天的日期字符串"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')

def save_articles(articles, article_type='hot', auth_method=None):
    """
    保存文章到数据库
    
    Args:
        articles: 文章列表,每项包含 rank, title, heat, url
        article_type: 文章类型 (hot/search/...)
        auth_method: 认证方式 (browser_profile/file_cookie/fallback_source)
    
    Returns:
        dict: {found, new, updated, errors}
    """
    if not articles:
        return {'found': 0, 'new': 0, 'updated': 0, 'errors': 0}
    
    conn = get_db()
    cursor = conn.cursor()
    
    today = get_today_str()
    now = int(datetime.now(timezone.utc).timestamp())
    
    found = len(articles)
    new_count = 0
    updated_count = 0
    errors = 0
    
    for article in articles:
        try:
            url = article.get('url', '')
            if not url:
                continue
                
            article_id = generate_id(url)
            rank = article.get('rank', 0)
            title = article.get('title', '')
            heat = article.get('heat', 0)
            
            # 检查是否已存在 (同一天同一URL)
            cursor.execute(
                'SELECT id FROM articles WHERE url = ? AND fetch_date = ?',
                (url, today)
            )
            existing = cursor.fetchone()
            
            if existing:
                # 更新现有记录 (热度可能变化)
                cursor.execute('''
                    UPDATE articles 
                    SET rank = ?, heat = ?, fetched_at = ?, raw_data = ?
                    WHERE id = ?
                ''', (rank, heat, now, json.dumps(article, ensure_ascii=False), article_id))
                updated_count += 1
            else:
                # 插入新记录
                cursor.execute('''
                    INSERT INTO articles 
                    (id, platform, article_type, rank, title, url, heat, 
                     fetched_at, fetch_date, raw_data)
                    VALUES (?, 'zhihu', ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (article_id, article_type, rank, title, url, heat, 
                      now, today, json.dumps(article, ensure_ascii=False)))
                new_count += 1
                
        except Exception as e:
            print(f"   ⚠️ 保存失败: {e}")
            errors += 1
            continue
    
    conn.commit()
    conn.close()
    
    return {
        'found': found,
        'new': new_count,
        'updated': updated_count,
        'errors': errors
    }

def log_fetch(article_type, found, new, updated, status=0, auth_method=None, error=None):
    """记录抓取日志"""
    conn = get_db()
    cursor = conn.cursor()
    
    now = int(datetime.now(timezone.utc).timestamp())
    
    cursor.execute('''
        INSERT INTO fetch_logs 
        (article_type, started_at, ended_at, found, new, updated, status, auth_method, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (article_type, now, now, found, new, updated, status, auth_method, error))
    
    conn.commit()
    conn.close()

def get_articles_by_date(date_str=None, article_type='hot', limit=100):
    """获取指定日期的文章"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT rank, title, url, heat, fetched_at, raw_data
        FROM articles
        WHERE fetch_date = ? AND article_type = ?
        ORDER BY rank ASC
        LIMIT ?
    ''', (date_str, article_type, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        'rank': row[0],
        'title': row[1],
        'url': row[2],
        'heat': row[3],
        'fetched_at': row[4],
        'raw_data': json.loads(row[5]) if row[5] else {}
    } for row in rows]

def get_stats(days=7):
    """获取最近N天的统计信息"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT fetch_date, COUNT(*) as count, MAX(fetched_at) as last_fetch
        FROM articles
        WHERE fetch_date >= date('now', '-{} days')
        GROUP BY fetch_date
        ORDER BY fetch_date DESC
    '''.format(days))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        'date': row[0],
        'count': row[1],
        'last_fetch': row[2]
    } for row in rows]

if __name__ == '__main__':
    # 测试
    print(f"Database path: {DB_PATH}")
    
    # 测试保存
    test_articles = [
        {'rank': 1, 'title': '测试文章1', 'heat': 1000000, 'url': 'https://zhihu.com/question/1'},
        {'rank': 2, 'title': '测试文章2', 'heat': 800000, 'url': 'https://zhihu.com/question/2'},
    ]
    
    result = save_articles(test_articles)
    print(f"Saved: {result}")
    
    # 测试查询
    articles = get_articles_by_date(limit=10)
    print(f"Found {len(articles)} articles")
    
    # 清理测试数据
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM articles WHERE title LIKE '测试文章%'")
    conn.commit()
    conn.close()
    print("Test data cleaned")
