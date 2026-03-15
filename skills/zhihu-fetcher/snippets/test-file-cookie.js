// 测试 File Cookie 获取
const https = require('https');
const fs = require('fs');
const path = require('path');

const CONFIG_PATH = path.join(__dirname, '..', 'config', 'fallback-sources.json');
const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
const cookie = config.cookie;

console.log('🍪 测试 File Cookie 获取\n');

// 构建 cookie 字符串
const cookieStr = [
  cookie._xsrf ? `_xsrf=${cookie._xsrf}` : '',
  cookie._zap ? `_zap=${cookie._zap}` : '',
  cookie.d_c0 ? `d_c0=${cookie.d_c0}` : '',
  cookie.zhihu_session ? `SESSIONID=${cookie.zhihu_session}` : ''
].filter(Boolean).join('; ');

console.log('使用的 Cookie:', cookieStr.slice(0, 80) + '...\n');

// 请求知乎 API
const options = {
  hostname: 'www.zhihu.com',
  path: '/api/v3/feed/topstory/hot-list-web?limit=10',
  headers: {
    'Cookie': cookieStr,
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Referer': 'https://www.zhihu.com/',
    'x-requested-with': 'fetch'
  }
};

console.log('请求 API...');

const req = https.get(options, (res) => {
  console.log('状态码:', res.statusCode);
  
  let data = '';
  res.on('data', chunk => data += chunk);
  res.on('end', () => {
    if (res.statusCode === 200) {
      try {
        const json = JSON.parse(data);
        const items = json.data?.map((item, i) => ({
          rank: i + 1,
          title: item.target?.title || item.target?.question?.title || '无标题',
          heat: item.detail_text?.match(/(\d+)/)?.[0] || 0,
          url: item.target?.url || `https://www.zhihu.com/question/${item.target?.id}`
        })) || [];
        
        console.log('\n✅ File Cookie 测试成功！');
        console.log('获取数据:', items.length, '条\n');
        console.log('前5条预览:');
        items.slice(0, 5).forEach(item => {
          console.log(`  ${item.rank}. ${item.title.slice(0, 45)}... (${item.heat}万热度)`);
        });
      } catch (e) {
        console.error('解析失败:', e.message);
      }
    } else {
      console.error('请求失败，状态码:', res.statusCode);
      console.log('可能需要更新 Cookie');
    }
  });
});

req.on('error', (e) => {
  console.error('请求错误:', e.message);
});

setTimeout(() => {
  req.destroy();
  console.error('\n请求超时');
}, 10000);
