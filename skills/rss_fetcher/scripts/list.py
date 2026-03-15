#!/usr/bin/env python3
"""
RSS Fetcher - 文章列表查看工具
支持终端友好的表格输出
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

DB_PATH = Path(__file__).parent.parent / "data" / "rss_fetcher.db"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.json"


def load_sources():
    """加载源配置"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
    sources = config.get('sources', [])
    return {s['id']: s for s in sources if s.get('enabled', True)}


def truncate(s, length=40):
    """截断字符串"""
    if not s:
        return ""
    return s[:length-3] + "..." if len(s) > length else s


def format_time(timestamp):
    """格式化时间戳"""
    if not timestamp or timestamp == 0:
        return "未知"
    try:
        dt = datetime.fromtimestamp(timestamp)
        # 今天的显示时间，其他的显示日期
        if dt.date() == datetime.now().date():
            return dt.strftime("%H:%M")
        return dt.strftime("%m-%d")
    except:
        return "错误"


def list_articles(hours=24, source=None, category=None, limit=20, json_output=False):
    """列出文章"""
    sources = load_sources()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 构建查询
    query = '''
        SELECT id, source_id, title, url, author, published_at, fetched_at, status
        FROM articles
        WHERE 1=1
    '''
    params = []
    
    if hours:
        cutoff = int(datetime.now().timestamp()) - (hours * 3600)
        query += ' AND published_at > ?'
        params.append(cutoff)
    
    if source:
        query += ' AND source_id = ?'
        params.append(source)
    elif category:
        # 获取该分类的所有源
        source_ids = [sid for sid, s in sources.items() if s.get('category') == category]
        if source_ids:
            placeholders = ','.join('?' * len(source_ids))
            query += f' AND source_id IN ({placeholders})'
            params.extend(source_ids)
    
    query += ' ORDER BY published_at DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    if json_output:
        results = []
        for row in rows:
            source_info = sources.get(row['source_id'], {})
            results.append({
                'id': row['id'],
                'title': row['title'],
                'url': row['url'],
                'source': source_info.get('name', row['source_id']),
                'category': source_info.get('category', 'unknown'),
                'published_at': format_time(row['published_at']),
                'fetched_at': format_time(row['fetched_at']),
            })
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    
    # 终端表格输出
    if not rows:
        print("📭 没有找到文章")
        return
    
    # 表头
    print(f"\n{'时间':<6} {'分类':<8} {'源':<12} {'标题':<40} {'链接':<30}")
    print("-" * 100)
    
    for row in rows:
        source_info = sources.get(row['source_id'], {})
        source_name = truncate(source_info.get('name', row['source_id']), 12)
        category = truncate(source_info.get('category', '-'), 8)
        title = truncate(row['title'], 40)
        url = truncate(row['url'], 30)
        pub_time = format_time(row['published_at'])
        
        print(f"{pub_time:<6} {category:<8} {source_name:<12} {title:<40} {url:<30}")
    
    print(f"\n📊 共 {len(rows)} 篇文章")


def show_stats():
    """显示统计信息"""
    sources = load_sources()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 总文章数
    cursor.execute('SELECT COUNT(*) FROM articles')
    total = cursor.fetchone()[0]
    
    # 今日新增
    today_start = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
    cursor.execute('SELECT COUNT(*) FROM articles WHERE fetched_at > ?', (today_start,))
    today = cursor.fetchone()[0]
    
    # 按源统计
    cursor.execute('''
        SELECT source_id, COUNT(*) as count, MAX(fetched_at) as last_fetch
        FROM articles
        GROUP BY source_id
        ORDER BY count DESC
    ''')
    source_stats = cursor.fetchall()
    conn.close()
    
    print(f"\n📈 RSS Fetcher 统计")
    print(f"总文章数: {total}")
    print(f"今日新增: {today}")
    print(f"活跃源数: {len(sources)}")
    
    if source_stats:
        print(f"\n{'源':<20} {'文章数':<10} {'最后抓取':<12}")
        print("-" * 50)
        for sid, count, last_fetch in source_stats[:10]:
            source_name = truncate(sources.get(sid, {}).get('name', sid), 18)
            last_time = format_time(last_fetch)
            print(f"{source_name:<20} {count:<10} {last_time:<12}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='List RSS articles')
    parser.add_argument('--hours', type=int, default=24, help='Hours to look back')
    parser.add_argument('--source', type=str, help='Filter by source ID')
    parser.add_argument('--category', type=str, help='Filter by category')
    parser.add_argument('--limit', type=int, default=20, help='Limit results')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    
    if args.stats:
        show_stats()
    else:
        list_articles(
            hours=args.hours,
            source=args.source,
            category=args.category,
            limit=args.limit,
            json_output=args.json
        )
