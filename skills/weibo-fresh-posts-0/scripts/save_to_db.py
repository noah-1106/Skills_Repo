#!/usr/bin/env python3
"""
Weibo Hot Search - Save to Database
将微博热搜保存到数据库的集成脚本
"""

import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# 添加当前目录到路径以便导入db模块
sys.path.insert(0, str(Path(__file__).parent))
from db import save_hot_items, log_fetch

def fetch_weibo_hot(limit=30):
    """
    调用微博热搜采集脚本获取数据
    """
    script_path = Path(__file__).parent / "fetch-hot-search.py"
    
    try:
        # 运行Python脚本获取数据
        result = subprocess.run(
            [sys.executable, str(script_path), 
             '--limit', str(limit),
             '--output', '-'],  # 输出到stdout
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode != 0:
            print(f"❌ 脚本执行失败: {result.stderr}")
            return None
        
        # 解析输出中的JSON
        output = result.stdout
        
        # 找到JSON开始的位置
        json_start = output.find('{')
        if json_start == -1:
            print("❌ 未找到JSON数据")
            return None
        
        json_str = output[json_start:]
        data = json.loads(json_str)
        
        return data
        
    except subprocess.TimeoutExpired:
        print("❌ 采集超时")
        return None
    except Exception as e:
        print(f"❌ 采集异常: {e}")
        return None

def main():
    """主函数"""
    args = sys.argv[1:]
    limit = int(args[0]) if args else 30
    
    print("=" * 60)
    print(f"📱 微博热搜采集 → 数据库")
    print(f"   每频道采集数量: {limit}")
    print("=" * 60)
    
    # 确保数据库已初始化
    db_path = Path(__file__).parent.parent / "data" / "weibo.db"
    if not db_path.exists():
        print("\n🔄 初始化数据库...")
        from init_db import init_db
        init_db()
    
    # 采集数据
    print("\n🔥 开始采集微博热搜...")
    data = fetch_weibo_hot(limit)
    
    if not data or 'channels' not in data:
        print("❌ 采集失败，无数据")
        sys.exit(1)
    
    channels = data.get('channels', {})
    
    # 统计总数
    total_found = 0
    total_new = 0
    total_errors = 0
    
    # 保存每个频道的数据
    for channel_id, channel_data in channels.items():
        channel_name = channel_data.get('name', channel_id)
        items = channel_data.get('items', [])
        
        print(f"\n📡 [{channel_name}]")
        print(f"   采集到 {len(items)} 条数据")
        
        if items:
            result = save_hot_items(channel_id, channel_name, items)
            print(f"   新增: {result['new']} 条")
            if result['errors'] > 0:
                print(f"   错误: {result['errors']} 条")
            
            total_found += result['found']
            total_new += result['new']
            total_errors += result['errors']
            
            # 记录日志
            status = 0 if result['errors'] == 0 else 1
            log_fetch(channel_id, result['found'], result['new'], status=status)
    
    print("\n" + "=" * 60)
    print("✅ 完成!")
    print(f"   数据库: {db_path}")
    print(f"   总计发现: {total_found} 条")
    print(f"   总计新增: {total_new} 条")
    if total_errors > 0:
        print(f"   总计错误: {total_errors} 条")
    
    # 显示各频道Top 3
    print("\n🔥 各频道 Top 3:")
    for channel_id, channel_data in channels.items():
        channel_name = channel_data.get('name', channel_id)
        items = channel_data.get('items', [])[:3]
        print(f"\n  【{channel_name}】")
        for item in items:
            heat_str = f"{item.get('heat', 0):,}" if item.get('heat') else "N/A"
            tag_str = f" [{item.get('tag', '')}]" if item.get('tag') else ""
            print(f"    {item.get('rank', 0)}. {item.get('title', '')[:35]}...{tag_str}")

if __name__ == '__main__':
    main()
