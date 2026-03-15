#!/usr/bin/env node
/**
 * 测试 ZhihuVAPI 风格的固化 Cookie 请求
 * 参考: https://github.com/cheezone/ZhihuVAPI
 * 
 * 关键逻辑:
 * 1. 访问 https://api.zhihu.com/people/self 获取 hash (id字段)
 * 2. 使用完整的 headers 配置
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

const CONFIG_PATH = path.join(__dirname, '..', 'config', 'fallback-sources.json');

function loadConfig() {
  return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
}

function getCookieString() {
  const config = loadConfig();
  const cookie = config.cookie || {};
  
  const parts = [];
  if (cookie.zhihu_session) parts.push(`zhihu_session=${cookie.zhihu_session}`);
  if (cookie.z_c0) parts.push(`z_c0=${cookie.z_c0}`);
  if (cookie._xsrf) parts.push(`_xsrf=${cookie._xsrf}`);
  if (cookie._zap) parts.push(`_zap=${cookie._zap}`);
  if (cookie.d_c0) parts.push(`d_c0=${cookie.d_c0}`);
  
  return parts.join('; ');
}

function request(url, options = {}) {
  return new Promise((resolve, reject) => {
    const parsedUrl = new URL(url);
    const reqOptions = {
      hostname: parsedUrl.hostname,
      path: parsedUrl.pathname + parsedUrl.search,
      method: options.method || 'GET',
      headers: options.headers || {}
    };

    const req = https.request(reqOptions, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        resolve({
          status: res.statusCode,
          headers: res.headers,
          data: data
        });
      });
    });

    req.on('error', reject);
    
    setTimeout(() => {
      req.destroy();
      reject(new Error('请求超时'));
    }, options.timeout || 10000);

    req.end();
  });
}

async function testPeopleSelf() {
  console.log('🧪 测试 1: 访问 api.zhihu.com/people/self 获取用户信息\n');
  
  const cookie = getCookieString();
  const config = loadConfig();
  const z_c0 = config.cookie?.z_c0 || '';
  
  console.log('当前 Cookie 字段:');
  console.log('  - zhihu_session:', config.cookie?.zhihu_session ? '✅ 有' : '❌ 无');
  console.log('  - z_c0:', z_c0 ? '✅ 有' : '❌ 无 (关键字段缺失！)');
  console.log('  - _xsrf:', config.cookie?._xsrf ? '✅ 有' : '❌ 无');
  console.log('  - _zap:', config.cookie?._zap ? '✅ 有' : '❌ 无');
  console.log('  - d_c0:', config.cookie?.d_c0 ? '✅ 有' : '❌ 无');
  console.log('');
  
  // 构建请求头 - 参考 ZhihuVAPI 的方式
  const headers = {
    'Cookie': cookie,
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://www.zhihu.com/',
    'Origin': 'https://www.zhihu.com',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site'
  };
  
  // 如果 z_c0 存在，添加 authorization header
  if (z_c0) {
    headers['Authorization'] = `Bearer ${z_c0}`;
    console.log('📝 添加了 Authorization: Bearer {z_c0}');
  }
  
  console.log('\n📡 请求 api.zhihu.com/people/self...\n');
  
  try {
    const response = await request('https://api.zhihu.com/people/self', { headers });
    
    console.log(`响应状态: ${response.status}`);
    console.log(`响应头:`, JSON.stringify(response.headers, null, 2).slice(0, 500));
    console.log('\n响应体:');
    
    if (response.status === 200) {
      const json = JSON.parse(response.data);
      console.log(JSON.stringify(json, null, 2).slice(0, 2000));
      
      if (json.id) {
        console.log(`\n✅ 成功获取 hash (id): ${json.id}`);
        return json.id;
      }
    } else if (response.status === 401) {
      console.log('❌ 401 Unauthorized - Cookie 无效或过期');
      console.log('\n响应体:', response.data.slice(0, 500));
    } else {
      console.log('响应:', response.data.slice(0, 1000));
    }
  } catch (error) {
    console.error('❌ 请求失败:', error.message);
  }
  
  return null;
}

async function testHotListWithAuth() {
  console.log('\n\n🧪 测试 2: 使用增强 Headers 请求热榜 API\n');
  
  const cookie = getCookieString();
  const config = loadConfig();
  const z_c0 = config.cookie?.z_c0 || '';
  
  const headers = {
    'Cookie': cookie,
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://www.zhihu.com/hot',
    'Origin': 'https://www.zhihu.com',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'x-requested-with': 'fetch'
  };
  
  if (z_c0) {
    headers['Authorization'] = `Bearer ${z_c0}`;
  }
  
  // 尝试新版热榜 API
  const apis = [
    'https://www.zhihu.com/api/v3/feed/topstory/hot-list-web?limit=10',
    'https://api.zhihu.com/topstory/hot-list?limit=10'
  ];
  
  for (const api of apis) {
    console.log(`\n📡 测试 API: ${api}`);
    try {
      const response = await request(api, { headers });
      console.log(`  状态: ${response.status}`);
      
      if (response.status === 200) {
        const json = JSON.parse(response.data);
        const count = json.data?.length || 0;
        console.log(`  ✅ 成功！获取 ${count} 条数据`);
        if (count > 0) {
          console.log(`  示例: ${json.data[0]?.target?.title || '无标题'}`);
          return true;
        }
      } else {
        console.log(`  响应: ${response.data.slice(0, 200)}`);
      }
    } catch (error) {
      console.log(`  ❌ 失败: ${error.message}`);
    }
  }
  
  return false;
}

async function main() {
  console.log('═══════════════════════════════════════════════════');
  console.log('  ZhihuVAPI 风格固化 Cookie 测试');
  console.log('═══════════════════════════════════════════════════\n');
  
  // 测试 1: 获取用户信息
  const hash = await testPeopleSelf();
  
  // 测试 2: 请求热榜
  const hotSuccess = await testHotListWithAuth();
  
  console.log('\n\n═══════════════════════════════════════════════════');
  console.log('  测试结果总结');
  console.log('═══════════════════════════════════════════════════');
  console.log(`获取用户信息 (hash): ${hash ? '✅ 成功' : '❌ 失败'}`);
  console.log(`获取热榜数据: ${hotSuccess ? '✅ 成功' : '❌ 失败'}`);
  
  if (!hash && !hotSuccess) {
    console.log('\n💡 建议:');
    console.log('1. z_c0 字段为空，这是关键认证字段');
    console.log('2. 需要从浏览器获取完整的 z_c0 值');
    console.log('3. 或使用 Browser Profile 方式获取数据');
  }
}

main().catch(console.error);
