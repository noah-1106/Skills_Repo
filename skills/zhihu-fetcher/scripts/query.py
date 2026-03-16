#!/usr/bin/env python3
"""
Zhihu Fetcher - Query Tool
知乎热榜数据查询工具
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

DB_PATH = Path(__file__).parent.parent / "data" / "zhihu.db"

def query_today(limit=50):
    """查询今天的数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT rank, title, url, heat, fetched_at
        FROM articles
        WHERE fetch_date = ? AND article_type = 'hot'
        ORDER BY rank ASC
        LIMIT ?
    ''', (today, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    print(f"\n📰 知乎热榜 - {today}")
    print("=" * 80)
    
    for row in rows:
        rank, title, url, heat, fetched_at = row
        heat_str = f"{heat:,}" if heat else "N/A"
        print(f"\n{rank}. {title}")
        print(f"   🔥 热度: {heat_str}")
        print(f"   🔗 {url}")
    
    print(f"\n   共 {len(rows)} 条数据")

def query_by_date(date_str, limit=50):
    """查询指定日期的数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT rank, title, url, heat, fetched_at
        FROM articles
        WHERE fetch_date = ? AND article_type = 'hot'
        ORDER BY rank ASC
        LIMIT ?
    ''', (date_str, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        print(f"❌ 未找到 {date_str} 的数据")
        return
    
    print(f"\n📰 知乎热榜 - {date_str}")
    print("=" * 80)
    
    for row in rows:
        rank, title, url, heat, fetched_at = row
        heat_str = f"{heat:,}" if heat else "N/A"
        print(f"\n{rank}. {title}")
        print(f"   🔥 热度: {heat_str}")
    
    print(f"\n   共 {len(rows)} 条数据")

def query_stats(days=7):
    """查询最近N天的统计"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT fetch_date, COUNT(*) as count, 
               MIN(fetched_at) as first_fetch,
               MAX(fetched_at) as last_fetch
        FROM articles
        WHERE fetch_date >= date('now', '-{} days')
        GROUP BY fetch_date
        ORDER BY fetch_date DESC
    '''.format(days))
    
    rows = cursor.fetchall()
    conn.close()
    
    print(f"\n📊 最近{days}天采集统计")
    print("=" * 60)
    print(f"{'日期':<12} {'文章数':<10} {'首次采集':<20} {'最后采集':<20}")
    print("-" * 60)
    
    total = 0
    for row in rows:
        date_str, count, first, last = row
        total += count
        first_time = datetime.fromtimestamp(first, tz=timezone.utc).strftime('%H:%M:%S') if first else '-'
        last_time = datetime.fromtimestamp(last, tz=timezone.utc).strftime('%H:%M:%S') if last else '-'
        print(f"{date_str:<12} {count:<10} {first_time:<20} {last_time:<20}")
    
    print("-" * 60)
    print(f"{'总计':<12} {total:<10}")

def query_logs(limit=10):
    """查询抓取日志"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT started_at, article_type, found, new, updated, status, auth_method
        FROM fetch_logs
        ORDER BY started_at DESC
        LIMIT ?
    ''', (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    print(f"\n📝 最近{limit}次抓取日志")
    print("=" * 80)
    print(f"{'时间':<20} {'类型':<10} {'发现':<8} {'新增':<8} {'更新':<8} {'状态':<8} {'认证':<15}")
    print("-" * 80)
    
    for row in rows:
        started, atype, found, new, updated, status, auth = row
        time_str = datetime.fromtimestamp(started, tz=timezone.utc).strftime('%m-%d %H:%M:%S')
        status_str = '✅' if status == 0 else '⚠️' if status == 1 else '❌'
        print(f"{time_str:<20} {atype:<10} {found:<8} {new:<8} {updated:<8} {status_str:<8} {auth or '-':<15}")

def main():
    args = sys.argv[1:]
    
    if not args or args[0] == 'today':
        limit = int(args[1]) if len(args) > 1 else 50
        query_today(limit)
    elif args[0] == 'date':
        if len(args) < 2:
            print("Usage: query.py date YYYY-MM-DD [limit]")
            return
        date_str = args[1]
        limit = int(args[2]) if len(args) > 2 else 50
        query_by_date(date_str, limit)
    elif args[0] == 'stats':
        days = int(args[1]) if len(args) > 1 else 7
        query_stats(days)
    elif args[0] == 'logs':
        limit = int(args[1]) if len(args) > 1 else 10
        query_logs(limit)
    else:
        print("Usage: query.py [command] [args]")
        print("")
        print("Commands:")
        print("  today [limit]        查询今天的数据 (默认50条)")
        print("  date YYYY-MM-DD      查询指定日期的数据")
        print("  stats [days]         统计最近N天的数据 (默认7天)")
        print("  logs [limit]         查看抓取日志 (默认10条)")
        print("")
        print("Examples:")
        print("  python3 query.py today 20")
        print("  python3 query.py date 2026-03-15")
        print("  python3 query.py stats 30")

if __name__ == '__main__':
    main()
