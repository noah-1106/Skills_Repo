/**
 * 备用数据源解析器
 * 解析不同格式的备用数据
 */

const https = require('https');

/**
 * 获取 URL 内容
 */
function fetchUrl(url, timeout = 15000) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(data));
    });
    
    req.on('error', reject);
    
    // 手动超时处理
    setTimeout(() => {
      req.destroy();
      reject(new Error('请求超时'));
    }, timeout);
  });
}

/**
 * 解析 Markdown 格式的热榜数据
 * 针对 SnailDev/zhihu-hot-hub 格式
 */
function parseMarkdownHotList(markdown) {
  const items = [];
  const lines = markdown.split('\n');
  
  // 查找 "## 热门搜索" 部分
  let inHotSection = false;
  
  for (const line of lines) {
    // 检测热门搜索区块开始
    if (line.startsWith('## 热门搜索')) {
      inHotSection = true;
      continue;
    }
    
    // 检测区块结束（下一个 ## 标题）
    if (inHotSection && line.startsWith('## ')) {
      break;
    }
    
    // 解析列表项: "1. [标题](链接)"
    if (inHotSection && line.match(/^\d+\.\s*\[/)) {
      const match = line.match(/^(\d+)\.\s*\[(.+?)\]\((.+?)\)/);
      if (match) {
        items.push({
          rank: parseInt(match[1]),
          title: match[2],
          url: match[3],
          heat: 0,  // 备用源没有热度数据
          type: 'hot'
        });
      }
    }
  }
  
  return items;
}

/**
 * 从备用源获取数据
 */
async function fetchFromFallback(sourceConfig) {
  console.log(`🔄 尝试备用源: ${sourceConfig.name}`);
  
  try {
    const content = await fetchUrl(sourceConfig.url, 15000);
    
    let data = [];
    if (sourceConfig.type === 'markdown') {
      data = parseMarkdownHotList(content);
    }
    // 可扩展: json, xml 等其他格式
    
    console.log(`✅ 备用源获取成功: ${data.length} 条`);
    
    return {
      meta: {
        source: sourceConfig.name,
        fetch_time: new Date().toISOString(),
        url: sourceConfig.url,
        fallback_used: true
      },
      data: data
    };
  } catch (error) {
    console.error(`❌ 备用源失败: ${error.message}`);
    throw error;
  }
}

/**
 * 尝试所有备用源
 */
async function tryFallbacks(fallbacks) {
  // 按优先级排序
  const sorted = [...fallbacks].sort((a, b) => a.priority - b.priority);
  
  for (const source of sorted) {
    try {
      const result = await fetchFromFallback(source);
      return result;
    } catch (e) {
      console.log(`   跳过 ${source.name}: ${e.message}`);
      continue;
    }
  }
  
  throw new Error('所有备用源均不可用');
}

module.exports = {
  fetchFromFallback,
  tryFallbacks,
  parseMarkdownHotList,
  fetchUrl
};
