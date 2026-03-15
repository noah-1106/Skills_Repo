#!/usr/bin/env python3
"""
Baidu Hot - Generate HTML Report
百度热搜HTML可视化报告
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "baidu.db"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "index.html"

# 分类颜色
CATEGORY_COLORS = {
    '热': '#ff6b6b',
    '新': '#4ecdc4',
    '热议': '#ffa94d',
    '辟谣': '#a55eea',
    '综合': '#868e96',
}

def generate_html():
    """生成HTML报告"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 获取所有数据
    cursor.execute('''
        SELECT rank, title, category, label, url, fetch_date
        FROM hot_items
        ORDER BY fetch_date DESC, rank ASC
        LIMIT 1000
    ''')
    rows = cursor.fetchall()
    
    # 获取所有日期
    cursor.execute('SELECT DISTINCT fetch_date FROM hot_items ORDER BY fetch_date DESC')
    all_dates = [row[0] for row in cursor.fetchall()]
    
    # 获取所有分类
    cursor.execute('SELECT DISTINCT category FROM hot_items WHERE category IS NOT NULL')
    categories = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    if not rows:
        print("❌ 数据库中没有数据")
        return
    
    # 转换数据
    items = []
    for row in rows:
        items.append({
            'rank': row['rank'],
            'title': row['title'],
            'category': row['category'] or '综合',
            'label': row['label'] or '',
            'url': row['url'] or '',
            'date': row['fetch_date']
        })
    
    max_date = all_dates[0] if all_dates else datetime.now().strftime('%Y-%m-%d')
    min_date = all_dates[-1] if all_dates else max_date
    
    # 生成HTML
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>百度热搜 - 数据可视化</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", sans-serif;
            background: #f5f5f5;
            line-height: 1.6;
        }}
        
        .header {{
            background: linear-gradient(135deg, #2932e1 0%, #1a1f9c 100%);
            color: white;
            padding: 25px 20px;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .header h1 {{ font-size: 24px; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }}
        .header h1::before {{ content: "🔍"; }}
        .header .meta {{ font-size: 13px; opacity: 0.9; }}
        
        .filters {{
            background: white;
            padding: 20px;
            border-bottom: 1px solid #e8e8e8;
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            align-items: flex-end;
        }}
        
        .filter-group {{ display: flex; flex-direction: column; gap: 6px; }}
        .filter-group label {{ font-size: 12px; color: #666; font-weight: 500; }}
        .filter-group select, .filter-group input {{
            padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px;
            font-size: 14px; background: white; min-width: 120px;
        }}
        
        .btn {{ padding: 8px 16px; border: none; border-radius: 6px;
            cursor: pointer; font-size: 14px; background: #f0f0f0; color: #666; }}
        .btn:hover {{ background: #e0e0e0; }}
        
        .stats {{
            background: #f0f2ff;
            padding: 12px 20px;
            font-size: 13px;
            color: #666;
            border-bottom: 1px solid #e8e8e8;
            display: flex;
            justify-content: space-between;
        }}
        .stats .highlight {{ color: #2932e1; font-weight: 600; }}
        
        .content {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
        
        .hot-list {{ display: flex; flex-direction: column; gap: 10px; }}
        
        .hot-item {{
            display: flex;
            align-items: center;
            padding: 14px 18px;
            background: white;
            border-radius: 10px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.05);
            transition: transform 0.1s, box-shadow 0.1s;
        }}
        
        .hot-item:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        
        .rank {{
            width: 32px;
            height: 32px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 15px;
            margin-right: 14px;
            flex-shrink: 0;
        }}
        
        .rank.top1 {{ background: linear-gradient(135deg, #ff6b6b, #ee5a5a); color: white; }}
        .rank.top2 {{ background: linear-gradient(135deg, #ffa94d, #ff8c42); color: white; }}
        .rank.top3 {{ background: linear-gradient(135deg, #ffd43b, #fcc419); color: #333; }}
        .rank.normal {{ background: #f0f0f0; color: #666; }}
        
        .item-content {{ flex: 1; min-width: 0; }}
        
        .item-title {{
            font-size: 15px;
            color: #1a1a1a;
            margin-bottom: 4px;
            line-height: 1.5;
            word-break: break-word;
        }}
        
        .item-meta {{ display: flex; align-items: center; gap: 10px; font-size: 12px; }}
        
        .category-badge {{
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            color: white;
        }}
        
        .empty {{ text-align: center; padding: 80px 20px; color: #999; }}
        .empty-icon {{ font-size: 48px; margin-bottom: 16px; }}
        
        @media (max-width: 640px) {{
            .content {{ padding: 12px; }}
            .hot-item {{ padding: 12px 14px; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>百度热搜数据可视化</h1>
        <div class="meta">
            更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 
            共 {len(items)} 条记录
        </div>
    </div>
    
    <div class="filters">
        <div class="filter-group">
            <label>日期</label>
            <select id="dateSelect">
                <option value="">全部</option>
'''
    
    for date in all_dates[:30]:
        html += f'                <option value="{date}">{date}</option>\n'
    
    html += f'''            </select>
        </div>
        
        <div class="filter-group">
            <label>分类</label>
            <select id="categorySelect">
                <option value="">全部</option>
'''
    
    for cat in categories:
        html += f'                <option value="{cat}">{cat}</option>\n'
    
    html += f'''            </select>
        </div>
        
        <div class="filter-group">
            <label>搜索</label>
            <input type="text" id="searchInput" placeholder="输入关键词...">
        </div>
        
        <button class="btn" onclick="resetFilters()">重置</button>
    </div>
    
    <div class="stats">
        <span>显示 <span class="highlight" id="showCount">{len(items)}</span> / {len(items)} 条</span>
    </div>
    
    <div class="content">
        <div class="hot-list" id="hotList"></div>
    </div>

    <script>
        const items = {json.dumps(items, ensure_ascii=False)};
        const categoryColors = {json.dumps(CATEGORY_COLORS, ensure_ascii=False)};
        
        function getRankClass(rank) {{
            if (rank === 1) return 'top1';
            if (rank === 2) return 'top2';
            if (rank === 3) return 'top3';
            return 'normal';
        }}
        
        function renderItems() {{
            const dateSelect = document.getElementById('dateSelect').value;
            const categorySelect = document.getElementById('categorySelect').value;
            const search = document.getElementById('searchInput').value.toLowerCase().trim();
            
            let filtered = items.filter(item => {{
                if (dateSelect && item.date !== dateSelect) return false;
                if (categorySelect && item.category !== categorySelect) return false;
                if (search && !item.title.toLowerCase().includes(search)) return false;
                return true;
            }});
            
            document.getElementById('showCount').textContent = filtered.length;
            
            const container = document.getElementById('hotList');
            if (filtered.length === 0) {{
                container.innerHTML = `
                    <div class="empty" style="grid-column: 1/-1;">
                        <div class="empty-icon">🔍</div>
                        <div>没有找到记录</div>
                    </div>
                `;
                return;
            }}
            
            // 按日期分组
            const grouped = {{}};
            filtered.forEach(item => {{
                if (!grouped[item.date]) grouped[item.date] = [];
                grouped[item.date].push(item);
            }});
            
            let html = '';
            Object.keys(grouped).sort().reverse().forEach(date => {{
                html += grouped[date].map(item => {{
                    const bgColor = categoryColors[item.category] || '#868e96';
                    return `
                        <a href="${{item.url}}" class="hot-item" target="_blank" style="text-decoration: none; color: inherit;">
                            <div class="rank ${{getRankClass(item.rank)}}">${{item.rank}}</div>
                            <div class="item-content">
                                <div class="item-title">${{item.title}}</div>
                                <div class="item-meta">
                                    <span class="category-badge" style="background: ${{bgColor}}">${{item.category}}</span>
                                    <span style="color: #999;">${{item.date}}</span>
                                </div>
                            </div>
                        </a>
                    `;
                }}).join('');
            }});
            
            container.innerHTML = html;
        }}
        
        function resetFilters() {{
            document.getElementById('dateSelect').value = '';
            document.getElementById('categorySelect').value = '';
            document.getElementById('searchInput').value = '';
            renderItems();
        }}
        
        document.getElementById('dateSelect').addEventListener('change', renderItems);
        document.getElementById('categorySelect').addEventListener('change', renderItems);
        document.getElementById('searchInput').addEventListener('input', renderItems);
        
        renderItems();
    </script>
</body>
</html>'''
    
    OUTPUT_PATH.write_text(html, encoding='utf-8')
    print(f"✅ HTML报告已生成: {OUTPUT_PATH}")
    print(f"   共 {len(items)} 条记录")
    print(f"   日期: {min_date} ~ {max_date}")

if __name__ == '__main__':
    generate_html()
