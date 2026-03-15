#!/usr/bin/env python3
"""
Weibo Hot Search - Query Tool
微博热搜数据查询工具
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys

DB_PATH = Path(__file__).parent.parent / "data" / "weibo.db"

def query_today(channel=None, limit=50):
    """查询今天的数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    if channel:
        cursor.execute('''
            SELECT channel_name, rank, title, url, heat, tag
            FROM hot_items
            WHERE fetch_date = ? AND channel_id = ?
            ORDER BY rank ASC
            LIMIT ?
        ''', (today, channel, limit))
    else:
        cursor.execute('''
            SELECT channel_name, rank, title, url, heat, tag
            FROM hot_items
            WHERE fetch_date = ?
            ORDER BY channel_id, rank ASC
            LIMIT ?
        ''', (today, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    print(f"\n📱 微博热搜 - {today}")
    print("=" * 80)
    
    current_channel = None
    for row in rows:
        channel_name, rank, title, url, heat, tag = row
        
        if channel_name != current_channel:
            print(f"\n【{channel_name}】")
            current_channel = channel_name
        
        tag_str = f" [{tag}]" if tag else ""
        heat_str = f"🔥 {heat:,}" if heat else ""
        print(f"  {rank:2d}. {title}{tag_str}")
        if heat_str:
            print(f"      {heat_str}")
    
    print(f"\n   共 {len(rows)} 条数据")

def query_by_date(date_str, channel=None, limit=50):
    """查询指定日期的数据"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if channel:
        cursor.execute('''
            SELECT channel_name, rank, title, url, heat, tag
            FROM hot_items
            WHERE fetch_date = ? AND channel_id = ?
            ORDER BY rank ASC
            LIMIT ?
        ''', (date_str, channel, limit))
    else:
        cursor.execute('''
            SELECT channel_name, rank, title, url, heat, tag
            FROM hot_items
            WHERE fetch_date = ?
            ORDER BY channel_id, rank ASC
            LIMIT ?
        ''', (date_str, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        print(f"❌ 未找到 {date_str} 的数据")
        return
    
    print(f"\n📱 微博热搜 - {date_str}")
    print("=" * 80)
    
    current_channel = None
    for row in rows:
        channel_name, rank, title, url, heat, tag = row
        
        if channel_name != current_channel:
            print(f"\n【{channel_name}】")
            current_channel = channel_name
        
        tag_str = f" [{tag}]" if tag else ""
        heat_str = f"🔥 {heat:,}" if heat else ""
        print(f"  {rank:2d}. {title}{tag_str}")
        if heat_str:
            print(f"      {heat_str}")
    
    print(f"\n   共 {len(rows)} 条数据")

def query_stats(days=7):
    """查询最近N天的统计"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT fetch_date, channel_name, COUNT(*) as count
        FROM hot_items
        WHERE fetch_date >= date('now', '-{} days')
        GROUP BY fetch_date, channel_id
        ORDER BY fetch_date DESC, channel_id
    '''.format(days))
    
    rows = cursor.fetchall()
    conn.close()
    
    print(f"\n📊 最近{days}天采集统计")
    print("=" * 60)
    print(f"{'日期':<12} {'频道':<12} {'数量':<8}")
    print("-" * 60)
    
    current_date = None
    for row in rows:
        date_str, channel_name, count = row
        date_display = date_str if date_str != current_date else ""
        current_date = date_str
        print(f"{date_display:<12} {channel_name:<12} {count:<8}")

def query_channels():
    """查询各频道统计"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT channel_name, COUNT(*) as count, MAX(fetch_date) as last_date
        FROM hot_items
        GROUP BY channel_id
        ORDER BY count DESC
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    print(f"\n📺 各频道统计")
    print("=" * 60)
    print(f"{'频道':<15} {'总数':<10} {'最后更新':<15}")
    print("-" * 60)
    
    for row in rows:
        channel_name, count, last_date = row
        print(f"{channel_name:<15} {count:<10} {last_date or '-':<15}")

def query_logs(limit=10):
    """查询抓取日志"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT started_at, channel_id, found, new, status
        FROM fetch_logs
        ORDER BY started_at DESC
        LIMIT ?
    ''', (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    print(f"\n📝 最近{limit}次抓取日志")
    print("=" * 70)
    print(f"{'时间':<20} {'频道':<12} {'发现':<8} {'新增':<8} {'状态':<8}")
    print("-" * 70)
    
    for row in rows:
        started, channel_id, found, new, status = row
        time_str = datetime.fromtimestamp(started, tz=timezone.utc).strftime('%m-%d %H:%M:%S')
        status_str = '✅' if status == 0 else '⚠️' if status == 1 else '❌'
        print(f"{time_str:<20} {channel_id or '-':<12} {found:<8} {new:<8} {status_str:<8}")

def main():
    args = sys.argv[1:]
    
    if not args or args[0] == 'today':
        channel = args[1] if len(args) > 1 else None
        limit = int(args[2]) if len(args) > 2 else 50
        query_today(channel, limit)
    elif args[0] == 'date':
        if len(args) < 2:
            print("Usage: query.py date YYYY-MM-DD [channel] [limit]")
            return
        date_str = args[1]
        channel = args[2] if len(args) > 2 else None
        limit = int(args[3]) if len(args) > 3 else 50
        query_by_date(date_str, channel, limit)
    elif args[0] == 'stats':
        days = int(args[1]) if len(args) > 1 else 7
        query_stats(days)
    elif args[0] == 'channels':
        query_channels()
    elif args[0] == 'logs':
        limit = int(args[1]) if len(args) > 1 else 10
        query_logs(limit)
    else:
        print("Usage: query.py [command] [args]")
        print("")
        print("Commands:")
        print("  today [channel] [limit]     查询今天的数据")
        print("  date YYYY-MM-DD [channel]   查询指定日期的数据")
        print("  stats [days]                统计最近N天的数据")
        print("  channels                    查看各频道统计")
        print("  logs [limit]                查看抓取日志")
        print("")
        print("Channels: hot, social, entertainment, life")
        print("")
        print("Examples:")
        print("  python3 query.py today")
        print("  python3 query.py today hot 20")
        print("  python3 query.py date 2026-03-15")
        print("  python3 query.py stats 30")

if __name__ == '__main__':
    main()
