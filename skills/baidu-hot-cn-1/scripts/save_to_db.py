#!/usr/bin/env python3
"""
Baidu Hot - Save to Database
将百度热搜保存到数据库
"""

import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from db import save_hot_items, log_fetch

def fetch_and_save(limit=50):
    """采集百度热搜并保存到数据库"""
    script_path = Path(__file__).parent / "baidu_hot.py"
    
    print("🔍 采集百度热搜...")
    
    try:
        # 调用原有脚本获取数据
        result = subprocess.run(
            [sys.executable, str(script_path), str(limit), '--json'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"❌ 脚本执行失败: {result.stderr}")
            log_fetch(0, 0, status=2, error=result.stderr)
            return None
        
        # 解析JSON
        data = json.loads(result.stdout)
        
        if data.get('status') != 'success':
            print(f"❌ 获取失败: {data.get('error', '未知错误')}")
            log_fetch(0, 0, status=2, error=data.get('error'))
            return None
        
        items = data.get('data', [])
        print(f"   获取到 {len(items)} 条热搜")
        
        # 保存到数据库
        result = save_hot_items(items)
        
        # 记录日志
        status = 0 if result['errors'] == 0 else 1
        log_fetch(result['found'], result['new'], status=status)
        
        return result
        
    except subprocess.TimeoutExpired:
        print("❌ 采集超时")
        log_fetch(0, 0, status=2, error='Timeout')
        return None
    except Exception as e:
        print(f"❌ 异常: {e}")
        log_fetch(0, 0, status=2, error=str(e))
        return None

def main():
    """主函数"""
    args = sys.argv[1:]
    limit = int(args[0]) if args else 50
    
    print("=" * 60)
    print(f"🔍 百度热搜采集 → 数据库")
    print(f"   数量: {limit}")
    print("=" * 60)
    
    # 确保数据库已初始化
    db_path = Path(__file__).parent.parent / "data" / "baidu.db"
    if not db_path.exists():
        print("\n🔄 初始化数据库...")
        from init_db import init_db
        init_db()
    
    # 采集数据
    result = fetch_and_save(limit)
    
    if result:
        print("\n" + "=" * 60)
        print("✅ 完成!")
        print(f"   数据库: {db_path}")
        print(f"   发现: {result['found']} 条")
        print(f"   新增: {result['new']} 条")
        if result['errors'] > 0:
            print(f"   错误: {result['errors']} 条")
        
        # 显示Top 5
        print("\n🔥 Top 5:")
        # 重新查询今天数据
        from db import get_items_by_date
        items = get_items_by_date(limit=5)
        for item in items:
            label_str = f" [{item['category']}]" if item['category'] else ""
            print(f"  {item['rank']}. {item['title'][:40]}...{label_str}")
    else:
        print("\n❌ 采集失败")
        sys.exit(1)

if __name__ == '__main__':
    main()
