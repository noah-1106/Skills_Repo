#!/usr/bin/env python3
"""
Baidu Hot - Database Operations
百度热搜数据库操作模块
"""

import sqlite3
import json
import hashlib
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "baidu.db"

def get_db():
    """获取数据库连接"""
    return sqlite3.connect(DB_PATH)

def generate_id(title, date_str):
    """生成条目ID"""
    return hashlib.sha256((title + date_str).encode()).hexdigest()[:16]

def get_today_str():
    """获取今天的日期字符串"""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')

def save_hot_items(items):
    """
    保存热搜条目到数据库
    
    Args:
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
            title = item.get('title', '')
            if not title:
                continue
            
            # 生成唯一ID
            item_id = generate_id(title, today)
            rank = item.get('rank', 0)
            category = item.get('category', '综合')
            hot_tag = item.get('hot_tag', '0')
            label = item.get('label', '')
            
            # 检查是否已存在
            cursor.execute('SELECT id FROM hot_items WHERE id = ?', (item_id,))
            if cursor.fetchone():
                continue  # 已存在，跳过
            
            # 插入新记录
            url = f"https://www.baidu.com/s?wd={urllib.parse.quote(title)}"
            cursor.execute('''
                INSERT INTO hot_items 
                (id, platform, rank, title, category, hot_tag, label, url, fetched_at, fetch_date, raw_data)
                VALUES (?, 'baidu', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (item_id, rank, title, category, hot_tag, label, url, now, today, json.dumps(item, ensure_ascii=False)))
            
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

def log_fetch(found, new, status=0, error=None):
    """记录抓取日志"""
    conn = get_db()
    cursor = conn.cursor()
    
    now = int(datetime.now(timezone.utc).timestamp())
    
    cursor.execute('''
        INSERT INTO fetch_logs 
        (started_at, ended_at, found, new, status, error)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (now, now, found, new, status, error))
    
    conn.commit()
    conn.close()

def get_items_by_date(date_str=None, category=None, limit=100):
    """获取指定日期的热搜条目"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = get_db()
    cursor = conn.cursor()
    
    if category:
        cursor.execute('''
            SELECT rank, title, category, label, fetched_at
            FROM hot_items
            WHERE fetch_date = ? AND category = ?
            ORDER BY rank ASC
            LIMIT ?
        ''', (date_str, category, limit))
    else:
        cursor.execute('''
            SELECT rank, title, category, label, fetched_at
            FROM hot_items
            WHERE fetch_date = ?
            ORDER BY rank ASC
            LIMIT ?
        ''', (date_str, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        'rank': row[0],
        'title': row[1],
        'category': row[2],
        'label': row[3],
        'fetched_at': row[4]
    } for row in rows]

def get_stats(days=7):
    """获取最近N天的统计信息"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT fetch_date, COUNT(*) as count, 
               COUNT(DISTINCT category) as categories
        FROM hot_items
        WHERE fetch_date >= date('now', '-{} days')
        GROUP BY fetch_date
        ORDER BY fetch_date DESC
    '''.format(days))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        'date': row[0],
        'count': row[1],
        'categories': row[2]
    } for row in rows]

def get_category_stats(date_str=None):
    """获取分类统计"""
    if date_str is None:
        date_str = get_today_str()
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT category, COUNT(*) as count
        FROM hot_items
        WHERE fetch_date = ?
        GROUP BY category
        ORDER BY count DESC
    ''', (date_str,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{
        'category': row[0],
        'count': row[1]
    } for row in rows]

if __name__ == '__main__':
    print(f"Database path: {DB_PATH}")
