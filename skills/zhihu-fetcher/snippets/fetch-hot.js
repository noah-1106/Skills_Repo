#!/usr/bin/env node
/**
 * 知乎热榜获取 - 完整版（含三级认证）
 * 
 * 认证优先级：
 * 1. Browser Profile - 使用已登录的浏览器
 * 2. File Cookie - 使用配置文件中的固化 cookie
 * 3. Fallback Source - 使用无需认证的备用数据源
 */

const fs = require('fs');
const path = require('path');
const { defaultRateLimiter } = require('./rate-limiter');
const { tryFallbacks } = require('./fallback');
const { fetchWithFileCookie, hasFileCookie, getAuthPriority } = require('./cookie-manager');

// 加载配置
const configPath = path.join(__dirname, '..', 'config', 'fallback-sources.json');
const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));

/**
 * 尝试使用 browser profile 抓取
 */
async function fetchWithBrowser(limit = 50) {
  console.log('🔥 尝试使用 Browser Profile 抓取...');
  
  // 检查是否有活跃的 browser session
  // 实际使用时，这部分会被调用方替换为真实的 browser 调用
  
  console.log('   请确保已通过 browser open https://www.zhihu.com 登录');
  console.log('   或提供固化的 cookie');
  
  throw new Error('Browser Profile 模式需要手动执行');
}

/**
 * 带完整降级链的热榜获取
 */
async function fetchWithFallback(options = {}) {
  const {
    limit = 50,
    rateLimitMs = config.rateLimit?.defaultMs || 2000,
    useFallback = true,
    timeout = config.timeout?.directFetchMs || 10000
  } = options;
  
  // 1. 频率限制
  await defaultRateLimiter.wait();
  
  const authPriority = getAuthPriority();
  console.log('📋 认证策略:', authPriority.join(' → '));
  
  let result = null;
  let authMethod = null;
  
  // 按优先级尝试各种认证方式
  for (const method of authPriority) {
    try {
      switch (method) {
        case 'browser_profile':
          console.log('\n🔹 尝试方式 1: Browser Profile');
          result = await fetchWithBrowser(limit);
          authMethod = 'browser_profile';
          break;
          
        case 'file_cookie':
          console.log('\n🔹 尝试方式 2: File Cookie');
          if (hasFileCookie()) {
            result = await fetchWithFileCookie(limit);
            authMethod = 'file_cookie';
          } else {
            console.log('   跳过: 没有配置固化 Cookie');
          }
          break;
          
        case 'fallback_source':
          if (useFallback && !result) {
            console.log('\n🔹 尝试方式 3: Fallback Source');
            result = await tryFallbacks(config.fallbacks || []);
            authMethod = 'fallback_source';
            
            if (result.data && limit) {
              result.data = result.data.slice(0, limit);
            }
          }
          break;
      }
      
      if (result) break;  // 成功获取数据，跳出循环
      
    } catch (error) {
      console.log(`   失败: ${error.message}`);
      continue;  // 尝试下一个方式
    }
  }
  
  // 如果所有方式都失败
  if (!result) {
    throw new Error('所有认证方式均失败，无法获取数据');
  }
  
  // 统一输出格式
  const output = {
    meta: {
      source: authMethod === 'fallback_source' ? result.meta.source : 'zhihu',
      fetch_time: new Date().toISOString(),
      mode: 'hot',
      auth_method: authMethod,
      rate_limited: true,
      count: result.data?.length || 0
    },
    data: result.data || []
  };
  
  return output;
}

/**
 * 命令行执行
 */
async function main() {
  const args = process.argv.slice(2);
  const limit = parseInt(args[0]) || 50;
  const outputPath = args[1];
  
  console.log('\n📰 知乎热榜获取（三级认证）\n');
  console.log('认证链: Browser Profile → File Cookie → Fallback Source\n');
  
  try {
    const data = await fetchWithFallback({ limit });
    
    const jsonOutput = JSON.stringify(data, null, 2);
    
    if (outputPath) {
      fs.writeFileSync(outputPath, jsonOutput, 'utf-8');
      console.log(`\n✅ 已保存到: ${outputPath}`);
      console.log(`   认证方式: ${data.meta.auth_method}`);
      console.log(`   数据条数: ${data.meta.count}`);
    } else {
      console.log('\n📊 结果:');
      console.log(jsonOutput);
    }
    
    return data;
  } catch (error) {
    console.error(`\n❌ 获取失败: ${error.message}`);
    console.log('\n💡 建议:');
    console.log('   1. 运行 browser open https://www.zhihu.com 登录');
    console.log('   2. 或在 config/fallback-sources.json 中配置固化 Cookie');
    console.log('   3. 或检查网络连接，使用备用数据源');
    process.exit(1);
  }
}

// 导出模块
module.exports = { fetchWithFallback };

// 直接运行
if (require.main === module) {
  main();
}
