#!/usr/bin/env python3
"""
Zhihu Fetcher - 生成热榜HTML可视化报告
支持按日期筛选、排名排序、热度筛选
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "zhihu.db"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "index.html"


def generate_html():
    """生成HTML报告"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 获取所有文章（最多1000篇）
    cursor.execute('''
        SELECT rank, title, url, heat, fetch_date, fetched_at, raw_data
        FROM articles
        WHERE article_type = 'hot'
        ORDER BY fetch_date DESC, rank ASC
        LIMIT 1000
    ''')
    rows = cursor.fetchall()
    
    # 获取所有日期
    cursor.execute('''
        SELECT DISTINCT fetch_date 
        FROM articles 
        WHERE article_type = 'hot'
        ORDER BY fetch_date DESC
    ''')
    all_dates = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    if not rows:
        print("❌ 数据库中没有数据")
        return
    
    # 转换为JS可用数据
    articles = []
    for row in rows:
        articles.append({
            'rank': row['rank'],
            'title': row['title'],
            'url': row['url'],
            'heat': row['heat'] or 0,
            'date': row['fetch_date'],
            'fetched_at': datetime.fromtimestamp(row['fetched_at'], tz=timezone.utc).strftime('%H:%M:%S') if row['fetched_at'] else '-'
        })
    
    # 日期范围
    min_date = all_dates[-1] if all_dates else datetime.now().strftime('%Y-%m-%d')
    max_date = all_dates[0] if all_dates else datetime.now().strftime('%Y-%m-%d')
    
    # 生成HTML
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>知乎热榜 - 数据可视化</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #f6f6f6;
            line-height: 1.6;
        }}
        
        .header {{
            background: linear-gradient(135deg, #0084ff 0%, #0066cc 100%);
            color: white;
            padding: 25px 20px;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            font-size: 24px;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .header h1::before {{
            content: "📰";
        }}
        .header .meta {{
            font-size: 13px;
            opacity: 0.9;
        }}
        
        .filters {{
            background: white;
            padding: 20px;
            border-bottom: 1px solid #e8e8e8;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            align-items: flex-end;
        }}
        
        .filter-group {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        
        .filter-group label {{
            font-size: 12px;
            color: #666;
            font-weight: 500;
        }}
        
        .filter-group input,
        .filter-group select {{
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
            background: white;
            min-width: 120px;
        }}
        
        .filter-group input:focus,
        .filter-group select:focus {{
            outline: none;
            border-color: #0084ff;
            box-shadow: 0 0 0 3px rgba(0,132,255,0.1);
        }}
        
        .filter-group input[type="date"] {{
            width: 140px;
        }}
        
        .btn {{
            padding: 8px 16px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }}
        
        .btn-secondary {{
            background: #f0f0f0;
            color: #666;
        }}
        
        .btn-secondary:hover {{
            background: #e0e0e0;
        }}
        
        .stats {{
            background: #f0f7ff;
            padding: 12px 20px;
            font-size: 13px;
            color: #666;
            border-bottom: 1px solid #e8e8e8;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .stats .highlight {{
            color: #0084ff;
            font-weight: 600;
        }}
        
        .content {{
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        .hot-list {{
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        
        .hot-item {{
            display: flex;
            align-items: flex-start;
            padding: 16px 20px;
            border-bottom: 1px solid #f0f0f0;
            transition: background 0.2s;
            text-decoration: none;
            color: inherit;
        }}
        
        .hot-item:hover {{
            background: #fafafa;
        }}
        
        .hot-item:last-child {{
            border-bottom: none;
        }}
        
        .rank {{
            width: 36px;
            height: 36px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 16px;
            margin-right: 16px;
            flex-shrink: 0;
        }}
        
        .rank.top1 {{ background: linear-gradient(135deg, #ff6b6b, #ee5a5a); color: white; }}
        .rank.top2 {{ background: linear-gradient(135deg, #ffa94d, #ff8c42); color: white; }}
        .rank.top3 {{ background: linear-gradient(135deg, #ffd43b, #fcc419); color: #333; }}
        .rank.normal {{ background: #f0f0f0; color: #666; }}
        
        .item-content {{
            flex: 1;
            min-width: 0;
        }}
        
        .item-title {{
            font-size: 15px;
            color: #1a1a1a;
            margin-bottom: 6px;
            line-height: 1.5;
            word-break: break-word;
        }}
        
        .item-meta {{
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 12px;
            color: #999;
        }}
        
        .heat-badge {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            color: #ff6b6b;
            font-weight: 500;
        }}
        
        .heat-badge::before {{
            content: "🔥";
        }}
        
        .empty {{
            text-align: center;
            padding: 80px 20px;
            color: #999;
        }}
        
        .empty-icon {{
            font-size: 48px;
            margin-bottom: 16px;
        }}
        
        @media (max-width: 640px) {{
            .filters {{ padding: 15px; gap: 12px; }}
            .filter-group {{ flex: 1; min-width: 100px; }}
            .filter-group input,
            .filter-group select {{ width: 100%; }}
            .content {{ padding: 12px; }}
            .hot-item {{ padding: 12px 15px; }}
            .rank {{ width: 32px; height: 32px; font-size: 14px; margin-right: 12px; }}
            .item-title {{ font-size: 14px; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>知乎热榜数据可视化</h1>
        <div class="meta">
            更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 
            数据范围: {min_date} ~ {max_date} | 
            共 {len(articles)} 条记录
        </div>
    </div>
    
    <div class="filters">
        <div class="filter-group">
            <label>选择日期</label>
            <select id="dateSelect">
                <option value="">全部日期</option>
'''
    
    for date in all_dates[:30]:  # 只显示最近30天
        html += f'                <option value="{date}">{date}</option>\n'
    
    html += f'''            </select>
        </div>
        
        <div class="filter-group">
            <label>开始日期</label>
            <input type="date" id="startDate" value="{max_date}" min="{min_date}" max="{max_date}">
        </div>
        
        <div class="filter-group">
            <label>结束日期</label>
            <input type="date" id="endDate" value="{max_date}" min="{min_date}" max="{max_date}">
        </div>
        
        <div class="filter-group">
            <label>关键词搜索</label>
            <input type="text" id="keywordFilter" placeholder="输入关键词...">
        </div>
        
        <div class="filter-group">
            <label>最小热度</label>
            <input type="number" id="minHeat" placeholder="0" min="0">
        </div>
        
        <button class="btn btn-secondary" onclick="resetFilters()">重置筛选</button>
    </div>
    
    <div class="stats">
        <span>显示 <span class="highlight" id="showCount">{len(articles)}</span> / {len(articles)} 条记录</span>
        <span id="dateRange">日期范围: {min_date} ~ {max_date}</span>
    </div>
    
    <div class="content">
        <div class="hot-list" id="hotList"></div>
    </div>

    <script>
        // 数据
        const articles = {json.dumps(articles, ensure_ascii=False)};
        const allDates = {json.dumps(all_dates, ensure_ascii=False)};
        
        // 获取排名样式类
        function getRankClass(rank) {{
            if (rank === 1) return 'top1';
            if (rank === 2) return 'top2';
            if (rank === 3) return 'top3';
            return 'normal';
        }}
        
        // 格式化热度
        function formatHeat(heat) {{
            if (heat >= 10000) {{
                return (heat / 10000).toFixed(1) + '万';
            }}
            return heat.toLocaleString();
        }}
        
        // 渲染列表
        function renderArticles() {{
            const dateSelect = document.getElementById('dateSelect').value;
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;
            const keyword = document.getElementById('keywordFilter').value.toLowerCase().trim();
            const minHeat = parseInt(document.getElementById('minHeat').value) || 0;
            
            // 过滤
            let filtered = articles.filter(a => {{
                // 日期选择
                if (dateSelect && a.date !== dateSelect) return false;
                
                // 日期范围
                if (!dateSelect) {{
                    if (startDate && a.date < startDate) return false;
                    if (endDate && a.date > endDate) return false;
                }}
                
                // 关键词
                if (keyword && !a.title.toLowerCase().includes(keyword)) return false;
                
                // 热度
                if (minHeat && a.heat < minHeat) return false;
                
                return true;
            }});
            
            // 更新统计
            document.getElementById('showCount').textContent = filtered.length;
            
            // 按日期分组显示
            const container = document.getElementById('hotList');
            
            if (filtered.length === 0) {{
                container.innerHTML = `
                    <div class="empty">
                        <div class="empty-icon">🔍</div>
                        <div>没有找到匹配的记录</div>
                    </div>
                `;
                return;
            }}
            
            // 按日期分组
            const grouped = {{}};
            filtered.forEach(a => {{
                if (!grouped[a.date]) grouped[a.date] = [];
                grouped[a.date].push(a);
            }});
            
            // 渲染
            let html = '';
            Object.keys(grouped).sort().reverse().forEach(date => {{
                const items = grouped[date];
                html += items.map(a => `
                    <a href="${{a.url}}" class="hot-item" target="_blank">
                        <div class="rank ${{getRankClass(a.rank)}}">${{a.rank}}</div>
                        <div class="item-content">
                            <div class="item-title">${{a.title}}</div>
                            <div class="item-meta">
                                <span class="heat-badge">${{formatHeat(a.heat)}}</span>
                                <span>${{a.date}}</span>
                                <span>采集时间: ${{a.fetched_at}}</span>
                            </div>
                        </div>
                    </a>
                `).join('');
            }});
            
            container.innerHTML = html;
        }}
        
        // 重置筛选
        function resetFilters() {{
            document.getElementById('dateSelect').value = '';
            document.getElementById('startDate').value = allDates[0] || '';
            document.getElementById('endDate').value = allDates[0] || '';
            document.getElementById('keywordFilter').value = '';
            document.getElementById('minHeat').value = '';
            renderArticles();
        }}
        
        // 监听变化
        document.getElementById('dateSelect').addEventListener('change', renderArticles);
        document.getElementById('startDate').addEventListener('change', renderArticles);
        document.getElementById('endDate').addEventListener('change', renderArticles);
        document.getElementById('keywordFilter').addEventListener('input', renderArticles);
        document.getElementById('minHeat').addEventListener('input', renderArticles);
        
        // 初始渲染
        renderArticles();
    </script>
</body>
</html>'''
    
    OUTPUT_PATH.write_text(html, encoding='utf-8')
    print(f"✅ HTML报告已生成: {OUTPUT_PATH}")
    print(f"   共 {len(articles)} 条记录")
    print(f"   日期范围: {min_date} ~ {max_date}")
    print(f"   可用日期: {len(all_dates)} 天")
    print(f"\n   打开方式:")
    print(f"   - Mac: open {OUTPUT_PATH}")
    print(f"   - 浏览器: file://{OUTPUT_PATH}")


if __name__ == '__main__':
    generate_html()
