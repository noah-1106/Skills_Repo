#!/usr/bin/env node
/**
 * 测试修复后的固化 Cookie 抓取
 */

const { fetchWithFileCookie } = require('./cookie-manager');

async function main() {
  console.log('🧪 测试修复后的固化 Cookie 抓取\n');
  
  try {
    const result = await fetchWithFileCookie(5);
    
    console.log('\n✅ 抓取成功！');
    console.log(`认证方式: ${result.meta.auth_method}`);
    console.log(`获取条数: ${result.data.length}\n`);
    
    console.log('数据示例:');
    result.data.forEach(item => {
      console.log(`${item.rank}. ${item.title.slice(0, 50)}... [${item.heat}热度]`);
    });
    
  } catch (error) {
    console.error('❌ 测试失败:', error.message);
  }
}

main();
