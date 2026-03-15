#!/usr/bin/env python3
"""
百度热搜榜获取脚本
Baidu Hot Topics Fetcher - 使用真实API
"""

import json
import sys
import urllib.request
from datetime import datetime

def get_baidu_hot(limit=50):
    """获取百度热搜榜 - 使用真实API"""
    try:
        # 百度热搜实时API
        url = 'https://top.baidu.com/api/board?platform=wise&tab=realtime'
        
        # 设置请求头
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://top.baidu.com/'
        }
        
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            # 解析数据结构: data.cards[0].content[0].content
            if not data.get('success') or 'data' not in data:
                raise Exception('API返回数据格式异常')
            
            cards = data['data'].get('cards', [])
            if not cards:
                raise Exception('无法获取热搜卡片数据')
            
            # 提取内容列表 - 需要嵌套解析
            hot_items = []
            for card in cards:
                if 'content' in card and isinstance(card['content'], list):
                    for content_item in card['content']:
                        if 'content' in content_item and isinstance(content_item['content'], list):
                            hot_items.extend(content_item['content'])
            
            if not hot_items:
                raise Exception('热搜内容为空')
            
            # 解析热搜条目
            hot_list = []
            for item in hot_items[:limit]:
                rank = item.get('index', 0)
                title = item.get('word', '').strip()
                hot_tag = item.get('hotTag', '0')  # 0=普通, 1=新, 3=热
                
                # 获取标签
                label = ''
                if item.get('labelTag'):
                    label = item['labelTag'].get('day', {}).get('text', '')
                
                # 热度标记转换
                if label:
                    category = label  # 优先使用标签（热议、辟谣等）
                elif hot_tag == '1':
                    category = '新'
                elif hot_tag == '3':
                    category = '热'
                else:
                    category = '综合'
                
                if title:  # 只添加有标题的条目
                    hot_list.append({
                        'rank': rank,
                        'title': title,
                        'category': category,
                        'search_count': '',
                        'hot_tag': hot_tag,
                        'label': label
                    })
            
            return {
                'status': 'success',
                'data': hot_list,
                'count': len(hot_list),
                'timestamp': datetime.now().isoformat(),
                'source': 'baidu_realtime_api'
            }
        
    except Exception as e:
        return {
            'status': 'error',
            'error': f'获取失败: {str(e)}',
            'data': [],
            'count': 0
        }


def format_output(data):
    """格式化输出"""
    if not data:
        return "❌ 未获取到数据"
    
    output = "🔍 百度热搜榜\n\n"
    for item in data:
        rank = item['rank']
        title = item['title']
        category = item['category']
        
        output += f"{rank}. [{category}] {title}\n"
    
    return output


def main():
    limit = 50
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except:
            pass
    
    result = get_baidu_hot(limit)
    
    if '--json' in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result['status'] == 'success':
            print(format_output(result["data"]))
        else:
            print(f"❌ 获取失败: {result.get('error', '未知错误')}")
            sys.exit(1)


if __name__ == "__main__":
    main()
