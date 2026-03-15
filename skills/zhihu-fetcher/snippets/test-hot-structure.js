#!/usr/bin/env node
/**
 * 详细查看热榜 API 返回结构
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

async function main() {
  const cookie = getCookieString();
  
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
  
  console.log('📡 请求热榜 API...\n');
  
  try {
    const response = await request('https://www.zhihu.com/api/v3/feed/topstory/hot-list-web?limit=3', { headers });
    
    console.log(`状态码: ${response.status}`);
    console.log('\n响应数据 (前3000字符):');
    console.log(response.data.slice(0, 3000));
    
    const json = JSON.parse(response.data);
    console.log('\n\n数据结构分析:');
    console.log('顶层字段:', Object.keys(json));
    
    if (json.data && json.data.length > 0) {
      console.log('\n第一条数据字段:', Object.keys(json.data[0]));
      console.log('\n第一条 target 字段:', Object.keys(json.data[0].target || {}));
      console.log('\n第一条完整数据:', JSON.stringify(json.data[0], null, 2).slice(0, 2000));
    }
    
  } catch (error) {
    console.error('❌ 错误:', error.message);
  }
}

main();
