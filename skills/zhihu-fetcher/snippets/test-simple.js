// 极简测试 - 只测试基本功能
const https = require('https');

console.log('开始测试...\n');

// 1. 测试网络连接
console.log('1. 测试网络连接...');
https.get('https://raw.githubusercontent.com/SnailDev/zhihu-hot-hub/master/README.md', (res) => {
  console.log('   ✓ 连接成功，状态码:', res.statusCode);
  
  let data = '';
  res.on('data', chunk => data += chunk);
  res.on('end', () => {
    console.log('   ✓ 数据接收完成，长度:', data.length);
    
    // 2. 测试解析
    console.log('\n2. 测试数据解析...');
    const items = [];
    const lines = data.split('\n');
    let inHotSection = false;
    
    for (const line of lines) {
      if (line.startsWith('## 热门搜索')) {
        inHotSection = true;
        continue;
      }
      if (inHotSection && line.startsWith('## ')) break;
      
      if (inHotSection && line.match(/^\d+\.\s*\[/)) {
        const match = line.match(/^(\d+)\.\s*\[(.+?)\]\((.+?)\)/);
        if (match) {
          items.push({
            rank: parseInt(match[1]),
            title: match[2],
            url: match[3]
          });
        }
      }
    }
    
    console.log('   ✓ 解析完成，获取', items.length, '条数据');
    console.log('\n3. 前5条数据预览:');
    items.slice(0, 5).forEach(item => {
      console.log(`   ${item.rank}. ${item.title.slice(0, 40)}...`);
    });
    
    console.log('\n✅ 测试成功！');
  });
}).on('error', (err) => {
  console.error('   ✗ 错误:', err.message);
});

// 5秒超时保护
setTimeout(() => {
  console.error('\n✗ 测试超时');
  process.exit(1);
}, 5000);
