#!/usr/bin/env python3
"""
Weibo Hot Search - Generate HTML Report
微博热搜HTML可视化报告生成
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "weibo.db"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "index.html"

# 频道颜色映射
CHANNEL_COLORS = {
    'hot': '#ff6b6b',           # 热搜总榜 - 红色
    'social': '#4ecdc4',        # 社会榜 - 青色
    'entertainment': '#a55eea', # 文娱榜 - 紫色
    'life': '#26de81',          # 生活榜 - 绿色
}

CHANNEL_NAMES = {
    'hot': '热搜总榜',
    'social': '社会榜',
    'entertainment': '文娱榜',
    'life': '生活榜',
}

def generate_html():
    """生成HTML报告"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 获取所有数据
    cursor.execute('''
        SELECT channel_id, channel_name, rank, title, url, heat, tag, fetch_date
        FROM hot_items
        ORDER BY fetch_date DESC, channel_id, rank ASC
        LIMIT 2000
    ''')
    rows = cursor.fetchall()
    
    # 获取所有日期
    cursor.execute('''
        SELECT DISTINCT fetch_date 
        FROM hot_items 
        ORDER BY fetch_date DESC
    ''')
    all_dates = [row[0] for row in cursor.fetchall()]
    
    # 获取所有频道
    cursor.execute('''
        SELECT DISTINCT channel_id, channel_name
        FROM hot_items
        ORDER BY channel_id
    ''')
    channels = {row[0]: row[1] for row in cursor.fetchall()}
    
    conn.close()
    
    if not rows:
        print("❌ 数据库中没有数据")
        return
    
    # 转换为JS可用数据
    items = []
    for row in rows:
        items.append({
            'channel_id': row['channel_id'],
            'channel_name': row['channel_name'],
            'rank': row['rank'],
            'title': row['title'],
            'url': row['url'],
            'heat': row['heat'] or 0,
            'tag': row['tag'] or '',
            'date': row['fetch_date']
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
    <title>微博热搜 - 数据可视化</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #f5f5f5;
            line-height: 1.6;
        }}
        
        .header {{
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a5a 100%);
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
        .header h1::before {{ content: "📱"; }}
        .header .meta {{
            font-size: 13px;
            opacity: 0.9;
        }}
        
        .filters {{
            background: white;
            padding: 20px;
            border-bottom: 1px solid #e8e8e8;
            display: flex;
            gap: 15px;
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
        
        .filter-group select,
        .filter-group input {{
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 14px;
            background: white;
            min-width: 120px;
        }}
        
        .channel-tabs {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        
        .channel-tab {{
            padding: 6px 14px;
            border: 2px solid #ddd;
            border-radius: 20px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            transition: all 0.2s;
            background: white;
        }}
        
        .channel-tab:hover {{ border-color: #999; }}
        
        .channel-tab.active {{
            border-color: transparent;
            color: white;
        }}
        
        .channel-tab.all.active {{ background: #333; }}
        .channel-tab.hot.active {{ background: {CHANNEL_COLORS['hot']}; }}
        .channel-tab.social.active {{ background: {CHANNEL_COLORS['social']}; }}
        .channel-tab.entertainment.active {{ background: {CHANNEL_COLORS['entertainment']}; }}
        .channel-tab.life.active {{ background: {CHANNEL_COLORS['life']}; }}
        
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
        
        .btn-secondary:hover {{ background: #e0e0e0; }}
        
        .stats {{
            background: #fff5f5;
            padding: 12px 20px;
            font-size: 13px;
            color: #666;
            border-bottom: 1px solid #e8e8e8;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .stats .highlight {{ color: #ff6b6b; font-weight: 600; }}
        
        .content {{
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        .hot-list {{
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        
        .hot-item {{
            display: flex;
            align-items: flex-start;
            padding: 16px 20px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            text-decoration: none;
            color: inherit;
            transition: transform 0.1s, box-shadow 0.1s;
        }}
        
        .hot-item:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
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
        
        .item-content {{ flex: 1; min-width: 0; }}
        
        .item-title {{
            font-size: 15px;
            color: #1a1a1a;
            margin-bottom: 8px;
            line-height: 1.5;
            word-break: break-word;
        }}
        
        .item-meta {{
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 12px;
            flex-wrap: wrap;
        }}
        
        .channel-badge {{
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            color: white;
        }}
        
        .heat-badge {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            color: #ff6b6b;
            font-weight: 500;
        }}
        
        .tag-badge {{
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            background: #fff3cd;
            color: #856404;
            border: 1px solid #ffeaa7;
        }}
        
        .empty {{
            text-align: center;
            padding: 80px 20px;
            color: #999;
        }}
        
        .empty-icon {{ font-size: 48px; margin-bottom: 16px; }}
        
        @media (max-width: 640px) {{
            .filters {{ padding: 15px; gap: 12px; }}
            .content {{ padding: 12px; }}
            .hot-item {{ padding: 12px 15px; }}
            .rank {{ width: 32px; height: 32px; font-size: 14px; margin-right: 12px; }}
            .item-title {{ font-size: 14px; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>微博热搜数据可视化</h1>
        <div class="meta">
            更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 
            数据范围: {min_date} ~ {max_date} | 
            共 {len(items)} 条记录
        </div>
    </div>
    
    <div class="filters">
        <div class="filter-group">
            <label>选择日期</label>
            <select id="dateSelect">
                <option value="">全部日期</option>
'''
    
    for date in all_dates[:30]:
        html += f'                <option value="{date}">{date}</option>\n'
    
    html += f'''            </select>
        </div>
        
        <div class="filter-group">
            <label>频道筛选</label>
            <div class="channel-tabs" id="channelTabs">
                <span class="channel-tab all active" data-channel="">全部</span>
'''
    
    for ch_id, ch_name in channels.items():
        color = CHANNEL_COLORS.get(ch_id, '#666')
        html += f'                <span class="channel-tab {ch_id}" data-channel="{ch_id}" style="border-color: {color}; color: {color};">{ch_name}</span>\n'
    
    html += f'''            </div>
        </div>
        
        <div class="filter-group">
            <label>关键词搜索</label>
            <input type="text" id="keywordFilter" placeholder="输入关键词...">
        </div>
        
        <button class="btn btn-secondary" onclick="resetFilters()">重置</button>
    </div>
    
    <div class="stats">
        <span>显示 <span class="highlight" id="showCount">{len(items)}</span> / {len(items)} 条记录</span>
    </div>
    
    <div class="content">
        <div class="hot-list" id="hotList"></div>
    </div>

    <script>
        const items = {json.dumps(items, ensure_ascii=False)};
        const channelColors = {json.dumps(CHANNEL_COLORS, ensure_ascii=False)};
        let selectedChannel = '';
        
        function getRankClass(rank) {{
            if (rank === 1) return 'top1';
            if (rank === 2) return 'top2';
            if (rank === 3) return 'top3';
            return 'normal';
        }}
        
        function formatHeat(heat) {{
            if (heat >= 10000) return (heat / 10000).toFixed(1) + '万';
            return heat.toLocaleString();
        }}
        
        function fixUrl(url) {{
            // 修复协议相对URL (//example.com -> https://example.com)
            if (url && url.startsWith('//')) {{
                return 'https:' + url;
            }}
            return url;
        }}
        
        function renderItems() {{
            const dateSelect = document.getElementById('dateSelect').value;
            const keyword = document.getElementById('keywordFilter').value.toLowerCase().trim();
            
            let filtered = items.filter(item => {{
                if (dateSelect && item.date !== dateSelect) return false;
                if (selectedChannel && item.channel_id !== selectedChannel) return false;
                if (keyword && !item.title.toLowerCase().includes(keyword)) return false;
                return true;
            }});
            
            document.getElementById('showCount').textContent = filtered.length;
            
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
            
            // 按日期和频道分组
            const grouped = {{}};
            filtered.forEach(item => {{
                const key = item.date + '_' + item.channel_id;
                if (!grouped[key]) grouped[key] = {{ date: item.date, channel: item.channel_name, channel_id: item.channel_id, items: [] }};
                grouped[key].items.push(item);
            }});
            
            let html = '';
            Object.values(grouped).sort((a, b) => b.date.localeCompare(a.date) || a.channel_id.localeCompare(b.channel_id))
                .forEach(group => {{
                    const bgColor = channelColors[group.channel_id] || '#666';
                    html += group.items.map(item => `
                        <a href="${{fixUrl(item.url)}}" class="hot-item" target="_blank">
                            <div class="rank ${{getRankClass(item.rank)}}">${{item.rank}}</div>
                            <div class="item-content">
                                <div class="item-title">${{item.title}}</div>
                                <div class="item-meta">
                                    <span class="channel-badge" style="background: ${{bgColor}}">${{group.channel}}</span>
                                    ${{item.heat ? `<span class="heat-badge">🔥 ${{formatHeat(item.heat)}}</span>` : ''}}
                                    ${{item.tag ? `<span class="tag-badge">${{item.tag}}</span>` : ''}}
                                    <span style="color: #999;">${{item.date}}</span>
                                </div>
                            </div>
                        </a>
                    `).join('');
                }});
            
            container.innerHTML = html;
        }}
        
        // 频道标签点击
        document.getElementById('channelTabs').addEventListener('click', function(e) {{
            if (e.target.classList.contains('channel-tab')) {{
                document.querySelectorAll('.channel-tab').forEach(tab => tab.classList.remove('active'));
                e.target.classList.add('active');
                selectedChannel = e.target.dataset.channel;
                renderItems();
            }}
        }});
        
        function resetFilters() {{
            document.getElementById('dateSelect').value = '';
            document.getElementById('keywordFilter').value = '';
            document.querySelectorAll('.channel-tab').forEach(tab => tab.classList.remove('active'));
            document.querySelector('.channel-tab.all').classList.add('active');
            selectedChannel = '';
            renderItems();
        }}
        
        document.getElementById('dateSelect').addEventListener('change', renderItems);
        document.getElementById('keywordFilter').addEventListener('input', renderItems);
        
        renderItems();
    </script>
</body>
</html>'''
    
    OUTPUT_PATH.write_text(html, encoding='utf-8')
    print(f"✅ HTML报告已生成: {OUTPUT_PATH}")
    print(f"   共 {len(items)} 条记录")
    print(f"   日期范围: {min_date} ~ {max_date}")
    print(f"   频道: {', '.join(channels.values())}")
    print(f"\n   打开方式:")
    print(f"   - Mac: open {OUTPUT_PATH}")

if __name__ == '__main__':
    generate_html()
