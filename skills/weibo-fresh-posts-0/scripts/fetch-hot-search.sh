#!/bin/bash
# Weibo Hot Search Fetcher for Daily Research
# 使用 OpenClaw browser 工具抓取微博热搜

set -e

LIMIT="${1:-30}"
OUTPUT_FILE="${2:-weibo-hot-$(date +%Y%m%d).json}"

echo "🔥 Fetching Weibo hot search (top $LIMIT)..."
echo "📄 Output: $OUTPUT_FILE"
echo ""

# 检查 openclaw 是否可用
if ! command -v openclaw &> /dev/null; then
    echo "❌ Error: openclaw command not found"
    exit 1
fi

# 检查 browser 状态
echo "🔍 Checking browser status..."
if ! openclaw browser status &> /dev/null; then
    echo "🚀 Starting browser..."
    openclaw browser start --profile openclaw || true
    sleep 3
fi

# 打开微博热搜页面
echo "🌐 Opening Weibo hot search page..."
openclaw browser open --profile openclaw --url "https://weibo.com/hot/search" &> /dev/null

# 等待页面加载
sleep 2

echo "📸 Page opened. Manual extraction needed."
echo ""
echo "⚠️  Note: Full automation requires parsing browser snapshot."
echo "   Current workflow:"
echo "   1. Browser opens weibo.com/hot/search"
echo "   2. User can manually extract data using:"
echo "      openclaw browser snapshot"
echo ""

# 创建占位符数据
cat > "$OUTPUT_FILE" << EOF
{
  "source": "weibo-hot-search",
  "fetch_time": "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)",
  "channel": "hot",
  "total_items": 0,
  "items": [],
  "note": "Browser opened successfully. Full data extraction requires manual snapshot parsing or integration with OpenClaw Python API.",
  "manual_extraction_guide": [
    "1. Run: openclaw browser snapshot",
    "2. Extract hot search items from output",
    "3. Save to this file"
  ]
}
EOF

echo "✅ Placeholder data saved to $OUTPUT_FILE"
echo "📊 To get actual data, use: openclaw browser snapshot"
