#!/usr/bin/env python3
"""
RSS Fetcher - 查询文章数据
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "rss_fetcher.db"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.json"


def load_sources():
    """从配置文件加载RSS源信息"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    sources = config.get('sources', [])
    # 构建 source_id -> source_info 映射
    return {s['id']: s for s in sources if s.get('enabled', True)}


def query_recent(hours=24, limit=50):
    """查询最近文章"""
    sources = load_sources()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cutoff = int(datetime.now().timestamp()) - (hours * 3600)
    
    cursor.execute('''
        SELECT * FROM articles
        WHERE published_at > ?
        ORDER BY published_at DESC
        LIMIT ?
    ''', (cutoff, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        source_info = sources.get(row['source_id'], {})
        results.append({
            'title': row['title'],
            'url': row['url'],
            'source': source_info.get('name', row['source_id']),
            'category': source_info.get('category', 'unknown'),
            'published_at': datetime.fromtimestamp(row['published_at']).isoformat() if row['published_at'] else 'unknown',
        })
    
    return results


def query_by_category(category, hours=24, limit=50):
    """按分类查询"""
    sources = load_sources()
    # 获取该分类下的 source_ids
    source_ids = [sid for sid, s in sources.items() if s.get('category') == category]
    
    if not source_ids:
        return []
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cutoff = int(datetime.now().timestamp()) - (hours * 3600)
    placeholders = ','.join('?' * len(source_ids))
    
    cursor.execute(f'''
        SELECT * FROM articles
        WHERE source_id IN ({placeholders}) AND published_at > ?
        ORDER BY published_at DESC
        LIMIT ?
    ''', (*source_ids, cutoff, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        source_info = sources.get(row['source_id'], {})
        results.append({
            'title': row['title'],
            'url': row['url'],
            'source': source_info.get('name', row['source_id']),
            'category': source_info.get('category', 'unknown'),
            'published_at': datetime.fromtimestamp(row['published_at']).isoformat() if row['published_at'] else 'unknown',
        })
    
    return results


def query_by_source(source_id, limit=20):
    """按源查询"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM articles
        WHERE source_id = ?
        ORDER BY published_at DESC
        LIMIT ?
    ''', (source_id, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_stats():
    """获取统计信息"""
    sources = load_sources()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 文章总数
    cursor.execute('SELECT COUNT(*) FROM articles')
    total_articles = cursor.fetchone()[0]
    
    # 今日新增
    today_start = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
    cursor.execute('SELECT COUNT(*) FROM articles WHERE fetched_at > ?', (today_start,))
    today_articles = cursor.fetchone()[0]
    
    # 源数量 (从JSON读取)
    active_sources = len(sources)
    
    # 按分类统计文章
    cursor.execute('SELECT source_id, COUNT(*) FROM articles GROUP BY source_id')
    source_counts = {row[0]: row[1] for row in cursor.fetchall()}
    
    conn.close()
    
    return {
        'total_articles': total_articles,
        'today_articles': today_articles,
        'active_sources': active_sources,
        'sources_by_category': {
            cat: len([s for s in sources.values() if s.get('category') == cat])
            for cat in set(s.get('category', 'unknown') for s in sources.values())
        },
        'top_sources': sorted(
            [{'id': sid, 'name': s.get('name', sid), 'count': source_counts.get(sid, 0)} 
             for sid, s in sources.items()],
            key=lambda x: x['count'],
            reverse=True
        )[:10]
    }


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Query RSS articles')
    parser.add_argument('--recent', action='store_true', help='Query recent articles')
    parser.add_argument('--category', type=str, help='Query by category')
    parser.add_argument('--source', type=str, help='Query by source ID')
    parser.add_argument('--hours', type=int, default=24, help='Hours to look back')
    parser.add_argument('--limit', type=int, default=20, help='Limit results')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    
    if args.stats:
        stats = get_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    elif args.category:
        results = query_by_category(args.category, args.hours, args.limit)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    elif args.source:
        results = query_by_source(args.source, args.limit)
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        results = query_recent(args.hours, args.limit)
        print(json.dumps(results, indent=2, ensure_ascii=False))
