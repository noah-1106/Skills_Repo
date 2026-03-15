#!/usr/bin/env python3
"""
Weibo Hot Search - Database Operations
微博热搜数据库操作模块
"""

import sqlite3
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "weibo.db"

def get_db():
    """获取数据库连接"""
    return sqlite3.connect(DB_PATH)

def generate_id(url):
    """生成文章ID (URL的SHA256前16位)"""
    return hashlib.sha256(url.encode()).hexdigest()[:16]

def get_today_str():
    """获取今天的日期字符串"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')

def save_hot_items(channel_id, channel_name, items):
    """
    保存热搜条目到数据库
    
    Args:
        channel_id: 频道ID (hot/social/entertainment/life)
        channel_name: 频道名称
        items: 条目列表
    
    Returns:
        dict: {found, new, errors}
    """
    if not items:
        return {'found': 0, 'new': 0, 'errors': 0}
    
    conn = get_db()
    cursor = conn.cursor()
    
    today = get_today_str()
    now = int(datetime.now(timezone.utc).timestamp())
    
    found = len(items)
    new_count = 0
    errors = 0
    
    for item in items:
        try:
            url = item.get('url', '')
            if not url:
                continue
            
            # 生成唯一ID: URL + 日期 + 频道
            item_id = generate_id(url + today + channel_id)
            rank = item.get('rank', 0)
            title = item.get('title', '')
            heat = item.get('heat', 0) or 0
            tag = item.get('tag', '')
            
            # 检查是否已存在
            cursor.execute(
                'SELECT id FROM hot_items WHERE id = ?',
                (item_id,)
            )
            existing = cursor.fetchone()
            
            if not existing:
                # 插入新记录
                cursor.execute('''
                    INSERT INTO hot_items 
                    (id, platform, channel_id, channel_name, rank, title, url, heat, tag, fetched_at, fetch_date)
                    VALUES (?, 'weibo', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (item_id, channel_id, channel_name, rank, title, url, heat, tag, now, today))
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
        'errors': errors
    }

def log_fetch(channel_id, found, new, status=0, error=None):
    """记录抓取日志"""
    conn = get_db()
    cursor = conn.cursor()
    
    now = int(datetime.now(timezone.utc).timestamp())
    
    cursor.execute('''
        INSERT INTO fetch_logs 
        (channel_id, started_at, ended_at, found, new, status, error)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (channel_id, now, now, found, new, status, error))
    
    conn.commit()
    conn.close()

def get_items_by_date(date_str=None, channel_id=None, limit=100):
    """获取指定日期的热搜条目"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = get_db()
    cursor = conn.cursor()
    
    if channel_id:
        cursor.execute('''
            SELECT channel_name, rank, title, url, heat, tag, fetched_at
            FROM hot_items
            WHERE fetch_date = ? AND channel_id = ?
            ORDER BY rank ASC
            LIMIT ?
        ''', (date_str, channel_id, limit))
    else:
        cursor.execute('''
            SELECT channel_name, rank, title, url, heat, tag, fetched_at
            FROM hot_items
            WHERE fetch_date = ?
            ORDER BY channel_id, rank ASC
            LIMIT ?
        ''', (date_str, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        'channel': row[0],
        'rank': row[1],
        'title': row[2],
        'url': row[3],
        'heat': row[4],
        'tag': row[5],
        'fetched_at': row[6]
    } for row in rows]

def get_stats(days=7):
    """获取最近N天的统计信息"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT fetch_date, channel_id, COUNT(*) as count
        FROM hot_items
        WHERE fetch_date >= date('now', '-{} days')
        GROUP BY fetch_date, channel_id
        ORDER BY fetch_date DESC, channel_id
    '''.format(days))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        'date': row[0],
        'channel': row[1],
        'count': row[2]
    } for row in rows]

def get_channel_stats():
    """获取各频道的数据统计"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT channel_name, COUNT(*) as count, MAX(fetch_date) as last_date
        FROM hot_items
        GROUP BY channel_id
        ORDER BY count DESC
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        'channel': row[0],
        'count': row[1],
        'last_date': row[2]
    } for row in rows]

if __name__ == '__main__':
    # 测试
    print(f"Database path: {DB_PATH}")
    
    # 测试保存
    test_items = [
        {'rank': 1, 'title': '测试热搜1', 'heat': 5000000, 'url': 'https://s.weibo.com/1', 'tag': '热'},
        {'rank': 2, 'title': '测试热搜2', 'heat': 3000000, 'url': 'https://s.weibo.com/2', 'tag': '新'},
    ]
    
    result = save_hot_items('hot', '热搜总榜', test_items)
    print(f"Saved: {result}")
    
    # 测试查询
    items = get_items_by_date(channel_id='hot', limit=10)
    print(f"Found {len(items)} items")
    
    # 清理测试数据
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM hot_items WHERE title LIKE '测试热搜%'")
    conn.commit()
    conn.close()
    print("Test data cleaned")
