#!/usr/bin/env node
/**
 * 知乎 API 反爬机制调研工具
 * 
 * 使用方法:
 *   node research-anti-crawl.js
 * 
 * 功能:
 *   1. 测试不同请求头组合
 *   2. 检测频率限制阈值
 *   3. 分析响应特征
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

// 加载保存的 cookie
const CONFIG_PATH = path.join(__dirname, '..', 'config', 'fallback-sources.json');
const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
const cookie = config.cookie;

// 测试用例配置
const TEST_CASES = [
  {
    name: '最小请求头（仅 Cookie）',
    headers: {
      'Cookie': buildCookieString()
    }
  },
  {
    name: '标准浏览器请求头',
    headers: {
      'Cookie': buildCookieString(),
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': 'application/json, text/plain, */*',
      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
      'Referer': 'https://www.zhihu.com/',
      'Origin': 'https://www.zhihu.com'
    }
  },
  {
    name: '完整请求头（含 X-Requested-With）',
    headers: {
      'Cookie': buildCookieString(),
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': 'application/json',
      'Accept-Language': 'zh-CN,zh;q=0.9',
      'Referer': 'https://www.zhihu.com/',
      'Origin': 'https://www.zhihu.com',
      'X-Requested-With': 'fetch',
      'Sec-Fetch-Dest': 'empty',
      'Sec-Fetch-Mode': 'cors',
      'Sec-Fetch-Site': 'same-origin'
    }
  }
];

function buildCookieString() {
  const parts = [];
  if (cookie._xsrf) parts.push(`_xsrf=${cookie._xsrf}`);
  if (cookie._zap) parts.push(`_zap=${cookie._zap}`);
  if (cookie.d_c0) parts.push(`d_c0=${cookie.d_c0}`);
  if (cookie.zhihu_session) parts.push(`SESSIONID=${cookie.zhihu_session}`);
  return parts.join('; ');
}

/**
 * 发送测试请求
 */
function testRequest(testCase) {
  return new Promise((resolve) => {
    const options = {
      hostname: 'www.zhihu.com',
      path: '/api/v3/feed/topstory/hot-list-web?limit=5',
      headers: testCase.headers,
      timeout: 10000
    };

    const startTime = Date.now();
    
    const req = https.get(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        const duration = Date.now() - startTime;
        resolve({
          name: testCase.name,
          status: res.statusCode,
          headers: res.headers,
          dataLength: data.length,
          duration,
          success: res.statusCode === 200,
          responsePreview: data.slice(0, 200)
        });
      });
    });

    req.on('error', (err) => {
      resolve({
        name: testCase.name,
        error: err.message,
        success: false
      });
    });

    req.on('timeout', () => {
      req.destroy();
      resolve({
        name: testCase.name,
        error: 'Timeout',
        success: false
      });
    });
  });
}

/**
 * 频率限制测试
 */
async function testRateLimit() {
  console.log('\n📊 频率限制测试\n');
  console.log('连续发送 10 个请求，观察响应...\n');
  
  const results = [];
  const headers = {
    'Cookie': buildCookieString(),
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
  };

  for (let i = 0; i < 10; i++) {
    const result = await testRequest({ name: `Request ${i+1}`, headers });
    results.push(result);
    console.log(`  请求 ${i+1}: ${result.success ? '✅' : '❌'} ${result.status || result.error}`);
    
    // 每5个请求暂停一下
    if (i === 4) {
      console.log('  ⏸️  暂停 3 秒...');
      await new Promise(r => setTimeout(r, 3000));
    }
  }

  const successCount = results.filter(r => r.success).length;
  console.log(`\n结果: ${successCount}/10 成功`);
  
  if (successCount < 10) {
    console.log('⚠️  检测到频率限制或反爬机制');
  }
}

/**
 * 主测试
 */
async function main() {
  console.log('🔍 知乎 API 反爬机制调研\n');
  console.log('=' .repeat(50));
  
  // 1. 测试不同请求头
  console.log('\n📋 测试不同请求头组合\n');
  
  for (const testCase of TEST_CASES) {
    console.log(`\n测试: ${testCase.name}`);
    console.log('-'.repeat(40));
    
    const result = await testRequest(testCase);
    
    if (result.success) {
      console.log(`  状态: ✅ ${result.status}`);
      console.log(`  耗时: ${result.duration}ms`);
      console.log(`  数据: ${result.dataLength} bytes`);
    } else {
      console.log(`  状态: ❌ ${result.error || result.status}`);
      if (result.responsePreview) {
        console.log(`  响应: ${result.responsePreview}`);
      }
    }
    
    // 间隔1秒避免触发限制
    await new Promise(r => setTimeout(r, 1000));
  }
  
  // 2. 频率限制测试
  await testRateLimit();
  
  // 3. 输出建议
  console.log('\n\n💡 调研建议\n');
  console.log('1. 在浏览器开发者工具中对比 Network 面板的请求头');
  console.log('2. 检查是否有 x-zse-96, x-ab-pb 等签名参数');
  console.log('3. 观察响应中的 Set-Cookie 和验证码挑战');
  console.log('4. 测试不同 IP 和 User-Agent 的效果');
  console.log('5. 检查是否存在 JavaScript 挑战（如 _cf_bm, __cfduid）');
}

// 运行
main().catch(console.error);
