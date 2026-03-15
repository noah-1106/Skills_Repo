#!/usr/bin/env python3
"""
RSS Fetcher - 源维护工具
支持源健康检查、状态管理
"""

import sqlite3
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

DB_PATH = Path(__file__).parent.parent / "data" / "rss_fetcher.db"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.json"
TIMEOUT = 30


def load_sources():
    """加载源配置"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config.get('sources', [])


def save_sources(sources):
    """保存源配置"""
    config = {
        "_description": "RSS源配置文件",
        "_updated": datetime.now().strftime("%Y-%m-%d"),
        "_total_sources": len(sources),
        "sources": sources
    }
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"✅ 配置已保存 ({len(sources)} 个源)")


def check_source_health(source_id, url):
    """检查单个源的健康状态 - 实际解析RSS"""
    import re
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        start_time = time.time()
        with urlopen(req, timeout=TIMEOUT) as response:
            data = response.read().decode('utf-8', errors='ignore')
            elapsed = time.time() - start_time
            
            # 检查是否是有效的RSS/Atom
            is_rss = '<rss' in data.lower() or '<feed' in data.lower() or '<channel' in data.lower()
            
            if not is_rss:
                return {
                    'status': 'error',
                    'response_time': round(elapsed * 1000, 1),
                    'error': '不是有效的RSS/Atom feed'
                }
            
            # 尝试提取文章
            # 简单的item/entry检测
            has_items = '<item>' in data.lower() or '<entry>' in data.lower()
            item_count = len(re.findall(r'<item[\s>]', data, re.IGNORECASE))
            item_count += len(re.findall(r'<entry[\s>]', data, re.IGNORECASE))
            
            if item_count == 0:
                return {
                    'status': 'warning',
                    'response_time': round(elapsed * 1000, 1),
                    'error': 'RSS有效但没有文章',
                    'items': 0
                }
            
            return {
                'status': 'ok',
                'response_time': round(elapsed * 1000, 1),
                'error': None,
                'items': item_count
            }
    except HTTPError as e:
        return {'status': 'error', 'response_time': None, 'error': f'HTTP {e.code}'}
    except URLError as e:
        return {'status': 'error', 'response_time': None, 'error': str(e.reason)}
    except Exception as e:
        return {'status': 'error', 'response_time': None, 'error': str(e)}


def check_all_sources():
    """检查所有源的健康状态"""
    sources = load_sources()
    print(f"🔍 开始检查 {len(sources)} 个RSS源...\n")
    
    ok_count = 0
    error_count = 0
    disabled_count = 0
    
    results = []
    for source in sources:
        sid = source['id']
        name = source.get('name', sid)
        url = source['url']
        enabled = source.get('enabled', True)
        
        if not enabled:
            print(f"⏸️  {name} (已禁用)")
            disabled_count += 1
            continue
        
        result = check_source_health(sid, url)
        results.append({**result, 'id': sid, 'name': name})
        
        if result['status'] == 'ok':
            items_info = f"[{result.get('items', '?')}篇]" if 'items' in result else ""
            print(f"✅ {name} ({result['response_time']}ms) {items_info}")
            ok_count += 1
        elif result['status'] == 'warning':
            print(f"⚠️  {name} - {result['error']}")
            ok_count += 1  # 警告也算可用
        else:
            print(f"❌ {name} - {result['error']}")
            error_count += 1
        
        time.sleep(0.3)  # 礼貌间隔
    
    print(f"\n📊 检查结果:")
    print(f"  正常: {ok_count}  错误: {error_count}  禁用: {disabled_count}")
    
    # 显示错误的源
    errors = [r for r in results if r['status'] == 'error']
    if errors:
        print(f"\n⚠️  需要关注的源:")
        for e in errors:
            print(f"  - {e['name']}: {e['error']}")


def source_stats():
    """显示源的抓取统计"""
    sources = load_sources()
    source_map = {s['id']: s for s in sources}
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 按源统计文章数
    cursor.execute('''
        SELECT source_id, COUNT(*) as count, 
               MIN(published_at) as oldest,
               MAX(published_at) as newest
        FROM articles
        GROUP BY source_id
    ''')
    stats = cursor.fetchall()
    conn.close()
    
    print(f"\n📈 源抓取统计\n")
    print(f"{'源ID':<20} {'名称':<20} {'文章数':<8} {'最早':<10} {'最新':<10}")
    print("-" * 80)
    
    for sid, count, oldest, newest in sorted(stats, key=lambda x: -x[1]):
        source = source_map.get(sid, {})
        name = source.get('name', sid)[:18]
        oldest_str = datetime.fromtimestamp(oldest).strftime("%m-%d") if oldest else "-"
        newest_str = datetime.fromtimestamp(newest).strftime("%m-%d") if newest else "-"
        print(f"{sid:<20} {name:<20} {count:<8} {oldest_str:<10} {newest_str:<10}")


def add_source(source_id, name, url, category):
    """添加新源"""
    sources = load_sources()
    
    # 检查ID是否已存在
    if any(s['id'] == source_id for s in sources):
        print(f"❌ 源ID '{source_id}' 已存在")
        return
    
    # 检查URL是否已存在
    if any(s['url'] == url for s in sources):
        print(f"❌ URL 已存在")
        return
    
    new_source = {
        "id": source_id,
        "name": name,
        "url": url,
        "category": category,
        "enabled": True
    }
    
    sources.append(new_source)
    save_sources(sources)
    print(f"✅ 已添加源: {name}")


def disable_source(source_id):
    """禁用源"""
    sources = load_sources()
    for s in sources:
        if s['id'] == source_id:
            s['enabled'] = False
            save_sources(sources)
            print(f"✅ 已禁用源: {s.get('name', source_id)}")
            return
    print(f"❌ 未找到源: {source_id}")


def enable_source(source_id):
    """启用源"""
    sources = load_sources()
    for s in sources:
        if s['id'] == source_id:
            s['enabled'] = True
            save_sources(sources)
            print(f"✅ 已启用源: {s.get('name', source_id)}")
            return
    print(f"❌ 未找到源: {source_id}")


def remove_source(source_id):
    """删除源"""
    sources = load_sources()
    original_len = len(sources)
    sources = [s for s in sources if s['id'] != source_id]
    
    if len(sources) == original_len:
        print(f"❌ 未找到源: {source_id}")
        return
    
    save_sources(sources)
    print(f"✅ 已删除源: {source_id}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='RSS Source Manager')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # check 命令
    check_parser = subparsers.add_parser('check', help='Check all sources health')
    
    # stats 命令
    stats_parser = subparsers.add_parser('stats', help='Show source statistics')
    
    # add 命令
    add_parser = subparsers.add_parser('add', help='Add new source')
    add_parser.add_argument('id', help='Source ID')
    add_parser.add_argument('name', help='Source name')
    add_parser.add_argument('url', help='RSS URL')
    add_parser.add_argument('category', help='Category (tech/finance/health/etc)')
    
    # disable 命令
    disable_parser = subparsers.add_parser('disable', help='Disable a source')
    disable_parser.add_argument('id', help='Source ID')
    
    # enable 命令
    enable_parser = subparsers.add_parser('enable', help='Enable a source')
    enable_parser.add_argument('id', help='Source ID')
    
    # remove 命令
    remove_parser = subparsers.add_parser('remove', help='Remove a source')
    remove_parser.add_argument('id', help='Source ID')
    
    args = parser.parse_args()
    
    if args.command == 'check':
        check_all_sources()
    elif args.command == 'stats':
        source_stats()
    elif args.command == 'add':
        add_source(args.id, args.name, args.url, args.category)
    elif args.command == 'disable':
        disable_source(args.id)
    elif args.command == 'enable':
        enable_source(args.id)
    elif args.command == 'remove':
            remove_source(args.id)
    else:
        parser.print_help()
