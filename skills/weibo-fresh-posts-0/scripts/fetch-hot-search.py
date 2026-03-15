#!/usr/bin/env python3
"""
Weibo Hot Search Fetcher - 多频道版本
同时抓取：热搜总榜、社会榜、文娱榜、生活榜
"""

import json
import subprocess
import time
import sys
import re
import argparse
from datetime import datetime, timezone
from pathlib import Path

def run_command(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def fetch_channel(channel_id, channel_name, limit=30, quiet=False):
    """抓取单个频道的热搜榜单"""
    if not quiet:
        print(f"\n📡 [{channel_name}]")
    
    # 构建URL
    if channel_id == 'hot':
        url = 'https://weibo.com/hot/search'
    else:
        url = f'https://weibo.com/hot/{channel_id}'
    
    # 打开页面
    success, _, _ = run_command(
        f"openclaw browser open --profile openclaw '{url}'",
        timeout=15
    )
    if not success:
        if not quiet:
            print(f"   ❌ 打开失败")
        return None
    
    time.sleep(3)
    success, stdout, _ = run_command("openclaw browser snapshot --compact 2>&1", 15)
    if not success:
        if not quiet:
            print(f"   ❌ 获取失败")
        return None
    
    items = parse_hot_search(stdout, limit)
    if not quiet:
        print(f"   ✅ {len(items)} 条热搜")
    return items

def parse_hot_search(text, limit):
    """解析热搜列表 - 只解析 main: 部分"""
    items = []
    lines = text.split('\n')
    
    in_main = False
    
    for i, line in enumerate(lines):
        if line.strip() == '- main:':
            in_main = True
            continue
        
        if not in_main:
            continue
        
        if line.startswith('  - ') and 'main' not in line:
            break
        
        if 'link "' in line and '[ref=e' in line:
            try:
                start = line.find('link "') + 6
                end = line.find('"', start)
                title = line[start:end]
                
                url = ""
                for j in range(i+1, min(i+5, len(lines))):
                    if '/url:' in lines[j] and 's.weibo.com' in lines[j]:
                        match = re.search(r'/url:\s*(\S+)', lines[j])
                        if match:
                            url = match.group(1)
                        break
                
                heat = 0
                tag = ""
                for j in range(i+1, min(i+4, len(lines))):
                    if lines[j].strip().startswith('- text:'):
                        text_content = lines[j][7:].strip()
                        parts = text_content.split()
                        for p in parts:
                            if p.isdigit():
                                num = int(p)
                                if num > 1000:
                                    heat = num
                            elif p in ['热', '新', '商', '官宣', '焕新']:
                                tag = p
                        break
                
                if title in ['首页', '推荐', '视频', '消息', '热门推荐', '热门榜单']:
                    continue
                
                if url and 's.weibo.com' in url:
                    items.append({
                        "rank": len(items)+1,
                        "title": title,
                        "heat": heat,
                        "tag": tag,
                        "url": url,
                        "posts": []
                    })
                    
                    if len(items) >= limit:
                        break
            except:
                pass
    
    return items

def fetch_topic_content(title, url, max_posts=2, quiet=False):
    """抓取话题内容"""
    if not url:
        return []
    
    if url.startswith('//'):
        url = 'https:' + url
    
    success, _, _ = run_command(
        f"openclaw browser open --profile openclaw '{url}'",
        timeout=15
    )
    if not success:
        return []
    
    time.sleep(2)
    success, stdout, _ = run_command("openclaw browser snapshot --compact 2>&1", 15)
    if not success:
        return []
    
    return parse_posts(stdout, max_posts)

def parse_posts(text, max_posts):
    """解析帖子"""
    posts = []
    lines = text.split('\n')
    
    media_keywords = [
        '中国新闻网', '央视新闻', '人民日报', '新华社', '澎湃新闻',
        '新京报', '头条新闻', '时间视频', '环球网', '极目新闻',
        '羊城晚报', '央视网', '香港文匯網'
    ]
    
    i = 0
    while i < len(lines) and len(posts) < max_posts:
        line = lines[i]
        
        if 'link "' in line and '[ref=e' in line:
            try:
                start = line.find('link "') + 6
                end = line.find('"', start)
                author = line[start:end]
                
                if author in ['首页', '推荐', '视频', '消息', 'Weibo', 'c', '展开']:
                    i += 1
                    continue
                
                post_url = ""
                for j in range(i+1, min(i+5, len(lines))):
                    url_match = re.search(r'/url:\s*(//weibo\.com/\d+/[A-Za-z0-9]+)', lines[j])
                    if url_match:
                        post_url = 'https:' + url_match.group(1)
                        break
                
                if not post_url:
                    i += 1
                    continue
                
                content = ""
                for j in range(i+1, min(i+15, len(lines))):
                    if lines[j].strip() == '- paragraph:':
                        for k in range(j+1, min(j+10, len(lines))):
                            if lines[k].strip().startswith('- text:'):
                                text_content = lines[k].strip()[7:].strip()
                                if len(text_content) > 15:
                                    content = text_content
                                    break
                            if lines[k].strip().startswith('- ') and 'text' not in lines[k]:
                                break
                        break
                
                if content and author:
                    is_media = any(kw in author for kw in media_keywords)
                    posts.append({
                        "author": author,
                        "author_type": "media" if is_media else "user",
                        "content": content[:300] + "..." if len(content) > 300 else content,
                        "url": post_url,
                        "is_media": is_media
                    })
            except:
                pass
        
        i += 1
    
    media_posts = [p for p in posts if p['is_media']]
    user_posts = [p for p in posts if not p['is_media']]
    result = media_posts[:max_posts]
    if len(result) < max_posts:
        result.extend(user_posts[:max_posts - len(result)])
    
    return result[:max_posts]

def main():
    parser = argparse.ArgumentParser(description='Weibo Multi-Channel Hot Search Fetcher')
    parser.add_argument('--limit', '-l', type=int, default=30, help='每频道抓取数量')
    parser.add_argument('--with-content', '-c', action='store_true', help='抓取详细内容')
    parser.add_argument('--content-limit', type=int, default=2, help='每个话题帖子数')
    parser.add_argument('--output', '-o', default='-', help='输出JSON文件 (默认为stdout)')
    parser.add_argument('--quiet', '-q', action='store_true', help='静默模式 (不输出进度)')
    
    args = parser.parse_args()
    
    # 定义要抓取的频道
    channels = {
        'hot': '热搜总榜',
        'social': '社会榜',
        'entertainment': '文娱榜',
        'life': '生活榜'
    }
    
    if not args.quiet:
        print(f"🔥 微博多频道热搜抓取", file=sys.stderr)
        print(f"   频道: {', '.join(channels.values())}", file=sys.stderr)
        print(f"   每频道: Top {args.limit}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
    
    all_data = {
        'source': 'weibo-hot-search-multi',
        'fetch_time': datetime.now(timezone.utc).isoformat(),
        'channels': {}
    }
    
    # 抓取每个频道
    for channel_id, channel_name in channels.items():
        items = fetch_channel(channel_id, channel_name, args.limit, quiet=args.quiet)
        
        if items:
            # 抓取内容
            if args.with_content:
                if not args.quiet:
                    print(f"   📰 抓取详细内容...", file=sys.stderr)
                for i, item in enumerate(items[:10], 1):  # 前10个话题
                    posts = fetch_topic_content(item['title'], item['url'], args.content_limit, quiet=args.quiet)
                    item['posts'] = posts
                    time.sleep(0.5)
            
            all_data['channels'][channel_id] = {
                'name': channel_name,
                'total_items': len(items),
                'items': items
            }
    
    # 输出JSON
    json_output = json.dumps(all_data, indent=2, ensure_ascii=False)
    
    if args.output == '-':
        # 输出到stdout
        print(json_output)
    else:
        # 保存到文件
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(json_output)
    
    # 统计
    if not args.quiet:
        total_items = sum(ch['total_items'] for ch in all_data['channels'].values())
        total_posts = sum(
            len(post) 
            for ch in all_data['channels'].values() 
            for item in ch['items'] 
            for post in item.get('posts', [])
        )
        
        print("\n" + "=" * 60, file=sys.stderr)
        if args.output != '-':
            print(f"✅ 已保存: {args.output}", file=sys.stderr)
        print(f"📊 共 {len(all_data['channels'])} 个频道, {total_items} 条热搜", file=sys.stderr)
        if args.with_content:
            print(f"📝 {total_posts} 条帖子内容", file=sys.stderr)

if __name__ == '__main__':
    main()
