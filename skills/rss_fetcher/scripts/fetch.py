#!/usr/bin/env python3
"""
RSS Fetcher - 核心抓取脚本
支持增量抓取、去重、失败重试、多线程并发
"""

import sqlite3
import hashlib
import time
import json
import re
import socket
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "rss_fetcher.db"
CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.json"
TIMEOUT = 30
RETRY_COUNT = 3
RETRY_DELAY = 2.0
UNRELIABLE_TIME = 0  # 时间不可信标记 (1970-01-01)

# 多线程配置
DEFAULT_WORKERS = 20          # 默认抓取线程数
MAX_WORKERS = 50              # 最大抓取线程数
BATCH_SIZE = 50               # 批量写入大小
WRITE_QUEUE_SIZE = 1000       # 写入队列容量

# 尝试导入 feedparser，否则用正则解析
try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False


def get_db():
    """获取数据库连接，启用WAL模式"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


# 全局写入队列
write_queue = Queue(maxsize=WRITE_QUEUE_SIZE)
write_stats = {'total': 0, 'new': 0, 'errors': 0}
stats_lock = threading.Lock()


def db_writer_thread(stop_event):
    """数据库写入线程 - 单线程批量写入保证一致性"""
    conn = get_db()
    cursor = conn.cursor()
    batch = []
    
    while not stop_event.is_set() or not write_queue.empty():
        try:
            item = write_queue.get(timeout=1)
            if item is None:  # 毒丸信号
                write_queue.task_done()
                break
            batch.append(item)
            write_queue.task_done()  # 标记任务完成
            
            # 批量写入
            if len(batch) >= BATCH_SIZE:
                _flush_batch(cursor, conn, batch)
                batch = []
        except:
            continue
    
    # 刷新剩余数据
    if batch:
        _flush_batch(cursor, conn, batch)
    
    conn.close()
    print(f"💾 Writer thread finished")


def _flush_batch(cursor, conn, batch):
    """批量写入数据库"""
    global write_stats
    
    try:
        # 批量插入文章（使用INSERT OR IGNORE自动去重）
        articles_data = [
            (item['id'], item['source_id'], item['category'], item['title'], 
             item['url'], item['author'], item['published_at'])
            for item in batch
        ]
        cursor.executemany('''
            INSERT OR IGNORE INTO articles (id, source_id, category, title, url, author, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', articles_data)
        
        # 获取实际插入数量
        inserted = cursor.rowcount
        
        # 批量处理标签
        for item in batch:
            article_id = item['id']
            for tag_name in item.get('tags', []):
                # 获取或创建标签
                cursor.execute('SELECT id FROM tags WHERE name = ?', (tag_name,))
                tag_row = cursor.fetchone()
                if tag_row:
                    tag_id = tag_row[0]
                else:
                    cursor.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)', (tag_name,))
                    tag_id = cursor.lastrowid or cursor.execute('SELECT id FROM tags WHERE name = ?', (tag_name,)).fetchone()[0]
                
                # 关联文章和标签
                cursor.execute('''
                    INSERT OR IGNORE INTO article_tags (article_id, tag_id) VALUES (?, ?)
                ''', (article_id, tag_id))
        
        conn.commit()
        
        with stats_lock:
            write_stats['new'] += inserted
            write_stats['total'] += len(batch)
            
    except Exception as e:
        print(f"   ⚠️ Batch write error: {e}")
        with stats_lock:
            write_stats['errors'] += len(batch)


def load_sources():
    """从配置文件加载RSS源"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    sources = config.get('sources', [])
    # 过滤启用的源
    return [s for s in sources if s.get('enabled', True)]


# 标签规则（关键词 -> 标签）
TAG_RULES = [
    # 技术
    (['ai', 'artificial intelligence', '机器学习', '深度学习', '神经网络', '大模型', 'llm', 'gpt', 'openai'], 'AI'),
    (['blockchain', '区块链', 'crypto', 'cryptocurrency', '比特币', 'ethereum', 'defi', 'nft'], '区块链'),
    (['cloud', '云计算', 'aws', 'azure', 'gcp', 'serverless'], '云计算'),
    (['security', '安全', 'hacking', '漏洞', 'cybersecurity', 'privacy'], '安全'),
    (['programming', '编程', 'developer', 'code', 'software', '开源', 'github'], '编程'),
    
    # 金融
    (['stock', '股票', 'equity', 'market', '股市', 'a股', '港股'], '股票'),
    (['fund', '基金', 'etf', 'mutual fund', '理财'], '基金'),
    (['bank', '银行', 'fintech', '支付', 'digital currency'], '银行'),
    
    # 医疗
    (['vaccine', '疫苗', 'drug', '药物', 'treatment', 'therapy'], '药物'),
    (['disease', '疾病', 'cancer', 'diabetes', 'epidemic', 'pandemic'], '疾病'),
    (['clinical', '临床', 'trial', '试验', 'fda', 'approval'], '临床试验'),
    
    # 游戏
    (['game', '游戏', 'gaming', 'gamer', 'esports', '电竞'], '游戏'),
    (['console', '主机', 'playstation', 'xbox', 'nintendo', 'switch'], '主机游戏'),
    (['mobile game', '手游', 'app store', 'google play'], '手游'),
    
    # 电商
    (['ecommerce', '电商', 'retail', 'shopping', 'amazon', 'taobao', 'jd'], '电商'),
    (['delivery', '配送', 'logistics', '供应链', 'warehouse'], '物流'),
    
    # 国内
    (['policy', '政策', 'regulation', '政府', '国务院', '发改委'], '政策'),
    (['economy', '经济', 'gdp', 'growth', 'recession', 'inflation'], '经济'),
    (['society', '社会', '民生', 'education', 'healthcare'], '社会'),
]


def auto_tag_article(title, rss_categories=None):
    """自动打标签 - 优先使用RSS自带category，没有则关键词提取"""
    tags = set()
    
    # 方案1: 使用RSS自带的categories
    if rss_categories and len(rss_categories) > 0:
        for cat in rss_categories:
            # 清理category，提取有效标签
            cat_clean = cat.strip()
            if len(cat_clean) > 1 and len(cat_clean) < 30:
                tags.add(cat_clean)
    
    # 如果没有RSS category，使用方案3: 关键词提取
    if not tags:
        tags = extract_tags_from_title(title)
    
    return list(tags)


def extract_tags_from_title(title):
    """从标题提取关键词标签"""
    import re
    
    # 常见停用词
    stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 
                  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 
                  'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare', 
                  'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 
                  'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above', 
                  'below', 'between', 'under', 'again', 'further', 'then', 'once', 'here', 
                  'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more',
                  'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own',
                  'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if', 'or',
                  'because', 'until', 'while', 'what', 'which', 'who', 'whom', 'this',
                  'that', 'these', 'those', 'am', 'it', 'its', 'they', 'them', 'their',
                  'we', 'our', 'ours', 'you', 'your', 'yours', 'he', 'him', 'his', 'she',
                  'her', 'hers', 'me', 'my', 'mine', '关于', '的', '了', '在', '是', 
                  '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', 
                  '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', 
                  '自己', '这'}
    
    title_lower = title.lower()
    extracted_tags = set()
    
    # 先检查规则匹配的标签（优先级高）
    for keywords, tag in TAG_RULES:
        for keyword in keywords:
            if keyword.lower() in title_lower:
                extracted_tags.add(tag)
                break
    
    # 如果规则没匹配到，提取标题中的名词作为标签
    if not extracted_tags:
        # 提取英文单词（大写的可能是专有名词）
        words = re.findall(r'[A-Z][a-z]+', title)
        for word in words:
            if word.lower() not in stop_words and len(word) > 2:
                extracted_tags.add(word)
        
        # 提取中文词组（2-4个字）
        chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,4}', title)
        for word in chinese_words:
            if word not in stop_words:
                extracted_tags.add(word)
    
    return list(extracted_tags)[:5]  # 最多5个标签


def parse_date(s):
    """解析日期字符串为Unix时间戳"""
    if not s:
        return UNRELIABLE_TIME
    
    s = s.strip()
    # 清理多余空格（如 "2026-03-15 11:53:57  +0800" -> "2026-03-15 11:53:57 +0800"）
    s = re.sub(r'\s+', ' ', s)
    
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S %Z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    
    return UNRELIABLE_TIME


def parse_feed_regex(url):
    """用正则解析RSS（fallback模式）"""
    items = []
    # 保存当前全局超时设置
    old_timeout = socket.getdefaulttimeout()
    
    try:
        # 设置SSL握手15秒超时（必须在创建socket之前）
        socket.setdefaulttimeout(15)
        
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        # 使用更短的超时，避免覆盖socket超时
        with urlopen(req, timeout=15) as response:
            data = response.read().decode('utf-8', errors='ignore')
    except socket.timeout:
        return [], "SSL handshake timeout (15s)"
    except Exception as e:
        return [], str(e)
    finally:
        # 恢复原来的超时设置
        socket.setdefaulttimeout(old_timeout)
    
    # 提取item
    item_pattern = r'<item[^>]*>(.*?)</item>'
    title_pattern = r'<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>'
    link_pattern = r'<link[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>'
    pubdate_pattern = r'<(?:pubDate|published|updated)[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:pubDate|published|updated)>'
    author_pattern = r'<(?:author|creator)[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:author|creator)>'
    category_pattern = r'<category[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</category>'
    
    for item_match in re.finditer(item_pattern, data, re.DOTALL | re.IGNORECASE):
        item_text = item_match.group(1)
        
        title = re.search(title_pattern, item_text, re.DOTALL | re.IGNORECASE)
        link = re.search(link_pattern, item_text, re.DOTALL | re.IGNORECASE)
        pubdate = re.search(pubdate_pattern, item_text, re.DOTALL | re.IGNORECASE)
        author = re.search(author_pattern, item_text, re.DOTALL | re.IGNORECASE)
        
        # 提取所有category
        categories = re.findall(category_pattern, item_text, re.DOTALL | re.IGNORECASE)
        
        if title and link:
            items.append({
                'title': (title.group(1) or '').strip(),
                'url': (link.group(1) or '').strip(),
                'published_at': parse_date(pubdate.group(1)) if pubdate else UNRELIABLE_TIME,
                'author': (author.group(1) or '').strip() if author else None,
                'categories': [c.strip() for c in categories if c.strip()],
            })
    
    return items, None


def parse_feed_feedparser(url):
    """用feedparser解析RSS"""
    items = []
    # 保存当前全局超时设置
    old_timeout = socket.getdefaulttimeout()
    
    try:
        # 设置SSL握手15秒超时
        socket.setdefaulttimeout(15)
        
        feed = feedparser.parse(url, request_headers={'User-Agent': 'Mozilla/5.0'})
        
        for entry in feed.entries:
            # 获取发布时间
            pub_date = None
            if hasattr(entry, 'published'):
                pub_date = entry.published
            elif hasattr(entry, 'updated'):
                pub_date = entry.updated
            elif hasattr(entry, 'pubDate'):
                pub_date = entry.pubDate
            
            # 获取作者
            author = None
            if hasattr(entry, 'author'):
                author = entry.author
            elif hasattr(entry, 'creator'):
                author = entry.creator
            
            # 获取categories
            categories = []
            if hasattr(entry, 'tags'):
                categories = [tag.term for tag in entry.tags if hasattr(tag, 'term')]
            elif hasattr(entry, 'category'):
                categories = [entry.category] if entry.category else []
            
            items.append({
                'title': entry.get('title', ''),
                'url': entry.get('link', ''),
                'published_at': parse_date(pub_date),
                'author': author,
                'categories': categories,
            })
        
        return items, None
    except socket.timeout:
        return [], "SSL handshake timeout (15s)"
    except Exception as e:
        return [], str(e)
    finally:
        # 恢复原来的超时设置
        socket.setdefaulttimeout(old_timeout)


def parse_feed(url):
    """解析RSS feed"""
    if HAS_FEEDPARSER:
        return parse_feed_feedparser(url)
    else:
        return parse_feed_regex(url)


def fetch_source(source_id, url, category=None, hours=24):
    """抓取单个RSS源 - 线程安全版本，结果推入队列"""
    try:
        # 抓取数据
        items, error = parse_feed(url)
        
        if error:
            print(f"   ❌ {source_id}: {error}")
            return 0, 0
        
        # 计算时间窗口
        cutoff_time = int(time.time()) - (hours * 3600)
        found_count = 0
        new_count = 0
        
        for item in items:
            # 跳过太旧的文章
            if item['published_at'] < cutoff_time and item['published_at'] != UNRELIABLE_TIME:
                continue
            
            found_count += 1
            
            # 生成文章ID (URL的SHA256)
            article_id = hashlib.sha256(item['url'].encode()).hexdigest()[:32]
            
            # 自动打标签
            tags = auto_tag_article(item['title'], item.get('categories'))
            
            # 推入写入队列
            write_queue.put({
                'id': article_id,
                'source_id': source_id,
                'category': category,
                'title': item['title'],
                'url': item['url'],
                'author': item['author'],
                'published_at': item['published_at'],
                'tags': tags
            })
            new_count += 1
        
        print(f"   ✅ {source_id}: Found {found_count}, Queued {new_count}")
        return found_count, new_count
        
    except Exception as e:
        print(f"   ❌ {source_id}: {e}")
        return 0, 0


def fetch_all(hours=24, source_filter=None, max_workers=None):
    """抓取所有启用的RSS源 - 多线程版本"""
    sources = load_sources()
    
    # 过滤指定源
    if source_filter:
        sources = [s for s in sources if s['id'] in source_filter]
    
    # 确定线程数
    workers = min(max_workers or DEFAULT_WORKERS, MAX_WORKERS)
    workers = min(workers, len(sources))  # 不超过源数量
    
    print(f"🚀 Starting fetch for {len(sources)} sources (last {hours}h)")
    print(f"⚡ Using {workers} workers + 1 writer thread\n")
    
    # 重置统计
    global write_stats
    write_stats = {'total': 0, 'new': 0, 'errors': 0}
    
    # 启动写入线程
    stop_event = threading.Event()
    writer = threading.Thread(target=db_writer_thread, args=(stop_event,))
    writer.start()
    
    total_found = 0
    total_queued = 0
    
    # 多线程抓取
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # 提交所有任务
        future_to_source = {
            executor.submit(fetch_source, s['id'], s['url'], s.get('category'), hours): s 
            for s in sources
        }
        
        # 收集结果
        for future in as_completed(future_to_source):
            found, queued = future.result()
            total_found += found
            total_queued += queued
    
    # 等待队列排空
    print("\n⏳ Waiting for write queue to drain...")
    write_queue.join()
    
    # 停止写入线程
    stop_event.set()
    write_queue.put(None)  # 毒丸
    writer.join()
    
    print(f"\n📊 Summary:")
    print(f"   Found: {total_found}")
    print(f"   Queued: {total_queued}")
    print(f"   Written: {write_stats['new']} new articles")
    if write_stats['errors'] > 0:
        print(f"   Errors: {write_stats['errors']}")
    
    return total_found, write_stats['new']


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='RSS Fetcher - Multi-threaded')
    parser.add_argument('--hours', type=int, default=24, help='Hours to look back')
    parser.add_argument('--sources', nargs='+', help='Specific source IDs to fetch')
    parser.add_argument('--workers', type=int, default=DEFAULT_WORKERS, 
                        help=f'Number of fetch threads (default: {DEFAULT_WORKERS}, max: {MAX_WORKERS})')
    
    args = parser.parse_args()
    
    # 限制线程数
    workers = min(args.workers, MAX_WORKERS)
    if args.workers > MAX_WORKERS:
        print(f"⚠️ Workers capped to {MAX_WORKERS} (requested: {args.workers})")
    
    fetch_all(hours=args.hours, source_filter=args.sources, max_workers=workers)
