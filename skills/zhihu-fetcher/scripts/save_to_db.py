#!/usr/bin/env python3
"""
Zhihu Fetcher - Save to Database
将知乎热榜保存到数据库的集成脚本
"""

import subprocess
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# 添加当前目录到路径以便导入db模块
sys.path.insert(0, str(Path(__file__).parent))
from db import save_articles, log_fetch, get_db

def fetch_zhihu_hot(limit=50):
    """
    调用知乎热榜采集脚本获取数据
    优先使用浏览器方式，失败则使用其他方式
    """
    script_dir = Path(__file__).parent.parent / "snippets"
    
    # 尝试使用 fetch-hot.js (带三级认证)
    fetch_script = script_dir / "fetch-hot.js"
    
    try:
        # 运行Node.js脚本获取数据
        result = subprocess.run(
            ['node', str(fetch_script), str(limit)],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            print(f"❌ Node脚本执行失败: {result.stderr}")
            return None
        
        # 解析输出中的JSON
        output = result.stdout
        
        # 找到JSON开始的位置 (通常是第一个 { )
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
    limit = int(args[0]) if args else 50
    
    print("=" * 60)
    print(f"📰 知乎热榜采集 → 数据库")
    print(f"   采集数量: {limit}")
    print("=" * 60)
    
    # 确保数据库已初始化
    db_path = Path(__file__).parent.parent / "data" / "zhihu.db"
    if not db_path.exists():
        print("\n🔄 初始化数据库...")
        from init_db import init_db
        init_db()
    
    # 采集数据
    print("\n🔥 开始采集知乎热榜...")
    data = fetch_zhihu_hot(limit)
    
    if not data or 'data' not in data:
        print("❌ 采集失败，无数据")
        log_fetch('hot', 0, 0, 0, status=2, error='No data fetched')
        sys.exit(1)
    
    articles = data.get('data', [])
    meta = data.get('meta', {})
    auth_method = meta.get('auth_method', 'unknown')
    
    print(f"   认证方式: {auth_method}")
    print(f"   采集到 {len(articles)} 条数据")
    
    # 保存到数据库
    print("\n💾 保存到数据库...")
    result = save_articles(articles, article_type='hot', auth_method=auth_method)
    
    print(f"   发现: {result['found']} 条")
    print(f"   新增: {result['new']} 条")
    print(f"   更新: {result['updated']} 条")
    if result['errors'] > 0:
        print(f"   错误: {result['errors']} 条")
    
    # 记录日志
    status = 0 if result['errors'] == 0 else 1
    log_fetch(
        'hot', 
        result['found'], 
        result['new'], 
        result['updated'],
        status=status,
        auth_method=auth_method
    )
    
    print("\n✅ 完成!")
    print(f"   数据库: {db_path}")
    
    # 显示Top 5
    if articles:
        print("\n🔥 Top 5:")
        for item in articles[:5]:
            heat_val = item.get('heat', 0)
            try:
                heat_num = int(heat_val) if heat_val else 0
                heat_str = f"{heat_num:,}"
            except (ValueError, TypeError):
                heat_str = str(heat_val) if heat_val else "N/A"
            print(f"  {item.get('rank', 0)}. {item.get('title', '')[:40]}...")
            print(f"     热度: {heat_str}")

if __name__ == '__main__':
    main()
