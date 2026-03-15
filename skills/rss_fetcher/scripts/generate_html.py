#!/usr/bin/env python3
"""
RSS Fetcher - 生成可筛选的HTML文章列表
所有数据内联，无需服务器
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "rss_fetcher.db"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "index.html"


def generate_html():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 获取所有文章（最多500篇）
    cursor.execute('''
        SELECT a.id, a.source_id, a.category, a.title, a.url, a.author, a.published_at,
               GROUP_CONCAT(t.name) as tags
        FROM articles a
        LEFT JOIN article_tags at ON a.id = at.article_id
        LEFT JOIN tags t ON at.tag_id = t.id
        GROUP BY a.id
        ORDER BY a.published_at DESC
        LIMIT 500
    ''')
    rows = cursor.fetchall()
    
    # 获取高频标签（出现次数>=3）
    cursor.execute('''
        SELECT t.name, COUNT(*) as count 
        FROM tags t 
        JOIN article_tags at ON t.id = at.tag_id 
        GROUP BY t.id 
        HAVING count >= 3
        ORDER BY count DESC
    ''')
    all_tags = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    # 转换为JS可用的数据
    articles = []
    for row in rows:
        tags_list = row['tags'].split(',') if row['tags'] else []
        articles.append({
            'id': row['id'],
            'title': row['title'],
            'url': row['url'],
            'category': row['category'] or 'unknown',
            'source': row['source_id'],
            'date': datetime.fromtimestamp(row['published_at']).strftime('%Y-%m-%d'),
            'time': datetime.fromtimestamp(row['published_at']).strftime('%H:%M'),
            'tags': tags_list
        })
    
    # 计算日期范围
    if articles:
        dates = [a['date'] for a in articles]
        min_date = min(dates)
        max_date = max(dates)
    else:
        min_date = max_date = datetime.now().strftime('%Y-%m-%d')
    
    # 分类列表
    categories = sorted(set(a['category'] for a in articles))
    
    # 生成HTML
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RSS Reader</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f5; 
            line-height: 1.6;
        }}
        .header {{
            background: #1a73e8;
            color: white;
            padding: 20px;
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        .header h1 {{ font-size: 20px; margin-bottom: 5px; }}
        .header .meta {{ font-size: 12px; opacity: 0.9; }}
        
        .filters {{
            background: white;
            padding: 15px 20px;
            border-bottom: 1px solid #e0e0e0;
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            align-items: flex-start;
        }}
        .filter-group {{ display: flex; align-items: center; gap: 8px; }}
        .filter-group label {{ font-size: 13px; color: #666; font-weight: 500; white-space: nowrap; }}
        .filter-group input, .filter-group select {{
            padding: 6px 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 13px;
        }}
        .filter-group input[type="date"] {{ width: 130px; }}
        .filter-group select {{ min-width: 100px; }}
        
        .tag-input-wrapper {{ position: relative; }}
        .tag-suggestions {{
            display: none;
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: white;
            border: 1px solid #ddd;
            border-radius: 4px;
            max-height: 200px;
            overflow-y: auto;
            z-index: 1000;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }}
        .tag-suggestions div {{
            padding: 8px 12px;
            cursor: pointer;
            font-size: 13px;
            border-bottom: 1px solid #f0f0f0;
        }}
        .tag-suggestions div:hover {{ background: #f5f5f5; }}
        .selected-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin-top: 5px;
        }}
        .selected-tag {{
            background: #e3f2fd;
            color: #1976d2;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}
        .selected-tag .remove {{ cursor: pointer; font-weight: bold; }}
        
        .stats {{
            padding: 10px 20px;
            background: #f0f7ff;
            font-size: 13px;
            color: #666;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        .articles {{
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        .article {{
            background: white;
            border-radius: 8px;
            padding: 16px 20px;
            margin-bottom: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        
        .article-header {{
            display: flex;
            gap: 10px;
            margin-bottom: 8px;
            align-items: center;
            flex-wrap: wrap;
        }}
        
        .category-badge {{
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 12px;
            background: #e3f2fd;
            color: #1976d2;
            font-weight: 500;
            text-transform: uppercase;
        }}
        
        .tag-badge {{
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 12px;
            background: #f3e5f5;
            color: #7b1fa2;
            font-weight: 500;
        }}
        
        .date-badge {{
            font-size: 12px;
            color: #999;
        }}
        
        .article-title {{
            font-size: 15px;
            color: #202124;
            text-decoration: none;
            display: block;
            line-height: 1.5;
        }}
        
        .article-title:hover {{ color: #1a73e8; }}
        
        .article-source {{
            font-size: 12px;
            color: #666;
            margin-top: 8px;
        }}
        
        .empty {{
            text-align: center;
            padding: 60px 20px;
            color: #999;
        }}
        
        @media (max-width: 600px) {{
            .filters {{ flex-direction: column; align-items: stretch; }}
            .filter-group {{ justify-content: space-between; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📰 RSS Reader</h1>
        <div class="meta">更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 共 {len(articles)} 篇文章</div>
    </div>
    
    <div class="filters">
        <div class="filter-group">
            <label>开始日期</label>
            <input type="date" id="startDate" value="{min_date}" min="{min_date}" max="{max_date}">
        </div>
        <div class="filter-group">
            <label>结束日期</label>
            <input type="date" id="endDate" value="{max_date}" min="{min_date}" max="{max_date}">
        </div>
        <div class="filter-group">
            <label>分类</label>
            <select id="categoryFilter">
                <option value="">全部</option>
'''
    
    for cat in categories:
        html += f'                <option value="{cat}">{cat}</option>\n'
    
    html += f'''            </select>
        </div>
        <div class="filter-group">
            <label>关键词</label>
            <input type="text" id="keywordFilter" placeholder="搜索标题..." style="width: 150px;">
        </div>
        <div class="filter-group" style="flex: 1; min-width: 200px;">
            <label>标签</label>
            <div class="tag-input-wrapper">
                <input type="text" id="tagInput" placeholder="输入标签，回车添加..." style="width: 200px;" autocomplete="off">
                <div class="tag-suggestions" id="tagSuggestions"></div>
            </div>
            <div class="selected-tags" id="selectedTags"></div>
        </div>
        
        <div class="filter-group">
            <button onclick="resetFilters()" style="padding: 6px 15px; background: #f5f5f5; border: 1px solid #ddd; border-radius: 4px; cursor: pointer; font-size: 13px; margin-top: 20px;">重置</button>
        </div>
    </div>
    
    <div class="stats" id="stats">显示全部 {len(articles)} 篇文章</div>
    
    <div class="articles" id="articleList"></div>

    <script>
        // 文章数据（内联）
        const articles = {json.dumps(articles, ensure_ascii=False)};
        
        // 所有可用标签
        const allTags = {json.dumps(all_tags, ensure_ascii=False)};
        let selectedTags = [];
        
        // 默认显示最近24小时
        const now = new Date();
        const yesterday = new Date(now - 24 * 60 * 60 * 1000);
        document.getElementById('startDate').value = yesterday.toISOString().split('T')[0];
        
        // 标签输入处理
        const tagInput = document.getElementById('tagInput');
        const tagSuggestions = document.getElementById('tagSuggestions');
        const selectedTagsContainer = document.getElementById('selectedTags');
        
        function updateSelectedTags() {{
            selectedTagsContainer.innerHTML = selectedTags.map(tag => `
                <span class="selected-tag">
                    ${{tag}}
                    <span class="remove" onclick="removeTag('${{tag}}')">×</span>
                </span>
            `).join('');
            renderArticles();
        }}
        
        function removeTag(tag) {{
            selectedTags = selectedTags.filter(t => t !== tag);
            updateSelectedTags();
        }}
        
        tagInput.addEventListener('input', function() {{
            const value = this.value.toLowerCase().trim();
            if (!value) {{
                tagSuggestions.style.display = 'none';
                return;
            }}
            
            // 过滤已选和匹配的
            const matches = allTags.filter(tag => 
                tag.toLowerCase().includes(value) && !selectedTags.includes(tag)
            ).slice(0, 10);
            
            if (matches.length > 0) {{
                tagSuggestions.innerHTML = matches.map(tag => `
                    <div onclick="selectTag('${{tag}}')">${{tag}}</div>
                `).join('');
                tagSuggestions.style.display = 'block';
            }} else {{
                tagSuggestions.style.display = 'none';
            }}
        }});
        
        tagInput.addEventListener('keydown', function(e) {{
            if (e.key === 'Enter') {{
                const value = this.value.trim();
                if (value && !selectedTags.includes(value) && allTags.includes(value)) {{
                    selectedTags.push(value);
                    updateSelectedTags();
                    this.value = '';
                    tagSuggestions.style.display = 'none';
                }}
                e.preventDefault();
            }}
        }});
        
        document.addEventListener('click', function(e) {{
            if (!e.target.closest('.tag-input-wrapper')) {{
                tagSuggestions.style.display = 'none';
            }}
        }});
        
        function selectTag(tag) {{
            if (!selectedTags.includes(tag)) {{
                selectedTags.push(tag);
                updateSelectedTags();
            }}
            tagInput.value = '';
            tagSuggestions.style.display = 'none';
        }}
        
        function renderArticles() {{
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;
            const category = document.getElementById('categoryFilter').value;
            const keyword = document.getElementById('keywordFilter').value.toLowerCase().trim();
            
            // 过滤
            let filtered = articles.filter(a => {{
                if (startDate && a.date < startDate) return false;
                if (endDate && a.date > endDate) return false;
                if (category && a.category !== category) return false;
                if (keyword && !a.title.toLowerCase().includes(keyword)) return false;
                // 标签多选：文章必须包含所有选中的标签
                if (selectedTags.length > 0) {{
                    const hasAllTags = selectedTags.every(tag => a.tags.includes(tag));
                    if (!hasAllTags) return false;
                }}
                return true;
            }});
            
            // 更新统计
            document.getElementById('stats').textContent = 
                `显示 ${{filtered.length}} / ${{articles.length}} 篇文章`;
            
            // 渲染列表
            const container = document.getElementById('articleList');
            if (filtered.length === 0) {{
                container.innerHTML = '<div class="empty">没有找到文章</div>';
                return;
            }}
            
            container.innerHTML = filtered.map(a => `
                <div class="article" data-category="${{a.category}}" data-date="${{a.date}}">
                    <div class="article-header">
                        <span class="category-badge">${{a.category}}</span>
                        <span class="date-badge">${{a.date}} ${{a.time}}</span>
                        ${{a.tags.map(t => `<span class="tag-badge">${{t}}</span>`).join('')}}
                    </div>
                    <a href="${{a.url}}" class="article-title" target="_blank">${{a.title}}</a>
                    <div class="article-source">📄 ${{a.source}}</div>
                </div>
            `).join('');
        }}
        
        function resetFilters() {{
            const dates = articles.map(a => a.date);
            document.getElementById('startDate').value = Math.min(...dates);
            document.getElementById('endDate').value = Math.max(...dates);
            document.getElementById('categoryFilter').value = '';
            document.getElementById('keywordFilter').value = '';
            selectedTags = [];
            updateSelectedTags();
        }}
        
        // 监听变化
        document.getElementById('startDate').addEventListener('change', renderArticles);
        document.getElementById('endDate').addEventListener('change', renderArticles);
        document.getElementById('categoryFilter').addEventListener('change', renderArticles);
        document.getElementById('keywordFilter').addEventListener('input', renderArticles);
        
        // 初始渲染
        renderArticles();
    </script>
</body>
</html>'''
    
    OUTPUT_PATH.write_text(html, encoding='utf-8')
    print(f"✅ HTML已生成: {OUTPUT_PATH}")
    print(f"   共 {len(articles)} 篇文章")
    print(f"   日期范围: {min_date} ~ {max_date}")
    print(f"   分类: {', '.join(categories)}")
    print(f"   高频标签: {len(all_tags)} 个")


if __name__ == '__main__':
    generate_html()
