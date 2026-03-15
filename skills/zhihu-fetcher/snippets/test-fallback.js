#!/usr/bin/env node
/**
 * 测试 fallback 功能
 */

const { tryFallbacks } = require('./fallback');
const fs = require('fs');
const path = require('path');

async function testFallback() {
  console.log('🧪 测试备用数据源\n');
  
  const configPath = path.join(__dirname, '..', 'config', 'fallback-sources.json');
  const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
  
  try {
    const result = await tryFallbacks(config.fallbacks);
    
    console.log('\n✅ 获取成功!');
    console.log(`   来源: ${result.meta.source}`);
    console.log(`   数量: ${result.data.length} 条`);
    console.log(`   时间: ${result.meta.fetch_time}`);
    
    console.log('\n📊 前 5 条数据:');
    result.data.slice(0, 5).forEach(item => {
      console.log(`   ${item.rank}. ${item.title.slice(0, 50)}...`);
    });
    
    return result;
  } catch (error) {
    console.error('\n❌ 测试失败:', error.message);
    process.exit(1);
  }
}

// 运行测试
testFallback();
