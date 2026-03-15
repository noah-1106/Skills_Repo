#!/usr/bin/env python3
"""
今日头条热榜抓取脚本
调用 toutiao-news-trends-0 技能获取热榜数据
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

def fetch_toutiao_hot(limit=50):
    """抓取今日头条热榜"""
    print(f"🔥 抓取今日头条热榜 (Top {limit})...")
    
    skill_path = Path.home() / '.openclaw/workspace-tanluzhe/skills/toutiao-news-trends-0'
    script_path = skill_path / 'scripts/toutiao.js'
    
    cmd = ['node', str(script_path), 'hot', str(limit)]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            print(f"   ✅ 抓取到 {len(data)} 条热榜")
            return data
        else:
            print(f"   ❌ 错误: {result.stderr}")
            return []
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return []

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 fetch-toutiao.py <date_str> <reports_dir>")
        sys.exit(1)
    
    date_str = sys.argv[1]
    reports_dir = sys.argv[2]
    
    print("=" * 60)
    print(f"📰 今日头条热榜抓取 - {date_str}")
    print("=" * 60)
    
    # 抓取数据
    hot_items = fetch_toutiao_hot(50)
    
    if not hot_items:
        print("❌ 抓取失败")
        sys.exit(1)
    
    # 格式化输出
    output = {
        "source": "toutiao-hot",
        "fetch_time": datetime.now(timezone.utc).isoformat(),
        "channel": "hot",
        "total_items": len(hot_items),
        "items": hot_items,
        "metadata": {
            "data_type": "hot_news_ranking",
            "value_for_research": "high"
        }
    }
    
    # 保存文件
    output_file = Path(reports_dir) / f'toutiao-hot-{date_str}.json'
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ 已保存: {output_file}")
    print(f"📊 共 {len(hot_items)} 条热榜")
    
    # 显示前5条
    print("\n🔥 Top 5:")
    for item in hot_items[:5]:
        label = f"[{item.get('label')}] " if item.get('label') else ""
        print(f"  {item['rank']}. {label}{item['title']}")
        print(f"     热度: {item.get('popularity', 0):,}")
    
    print()

if __name__ == '__main__':
    main()
