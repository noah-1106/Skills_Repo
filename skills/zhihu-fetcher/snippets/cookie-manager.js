/**
 * Cookie 管理模块
 * 
 * 三级认证策略：
 * 1. Browser Profile - 优先使用已登录的浏览器状态
 * 2. File Cookie - 从配置文件读取固化的 cookie
 * 3. Fallback Source - 无需认证的备用数据源
 */

const fs = require('fs');
const path = require('path');
const https = require('https');

const CONFIG_PATH = path.join(__dirname, '..', 'config', 'fallback-sources.json');

/**
 * 加载配置
 */
function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
  } catch (e) {
    return { cookie: {}, auth: { priority: ['browser_profile', 'file_cookie', 'fallback_source'] } };
  }
}

/**
 * 检查是否有固化的 cookie
 */
function hasFileCookie() {
  const config = loadConfig();
  const cookie = config.cookie || {};
  
  // 检查是否有有效的 cookie 值
  return !!(cookie.zhihu_session || cookie.z_c0 || cookie._xsrf);
}

/**
 * 获取固化的 cookie 字符串
 */
function getFileCookie() {
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

/**
 * 使用 cookie 直接请求知乎 API
 * 使用增强 Headers 以匹配新版 API 要求
 */
async function fetchWithCookie(url, cookie) {
  return new Promise((resolve, reject) => {
    const options = {
      headers: {
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
      }
    };
    
    const req = https.get(url, options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        if (res.statusCode === 200) {
          resolve({ status: res.statusCode, data });
        } else if (res.statusCode === 401 || res.statusCode === 403) {
          reject(new Error('Cookie 已过期或无效'));
        } else {
          reject(new Error(`HTTP ${res.statusCode}`));
        }
      });
    });
    
    req.on('error', reject);
    
    setTimeout(() => {
      req.destroy();
      reject(new Error('请求超时'));
    }, 10000);
  });
}

/**
 * 尝试使用 file cookie 获取热榜
 */
async function fetchWithFileCookie(limit = 50) {
  console.log('🍪 尝试使用固化 Cookie 获取...');
  
  if (!hasFileCookie()) {
    throw new Error('没有配置固化 Cookie');
  }
  
  const cookie = getFileCookie();
  console.log('   使用 Cookie:', cookie.slice(0, 50) + '...');
  
  try {
    // 知乎热榜 API
    const url = `https://www.zhihu.com/api/v3/feed/topstory/hot-list-web?limit=${limit}`;
    const response = await fetchWithCookie(url, cookie);
    
    const json = JSON.parse(response.data);
    
    if (!json.data) {
      throw new Error('返回数据格式异常');
    }
    
    const items = json.data.map((item, index) => ({
      rank: index + 1,
      title: item.target?.title_area?.text || item.target?.title || '无标题',
      heat: item.target?.metrics_area?.text?.match(/(\d+)/)?.[0] 
            || item.detail_text?.match(/(\d+)/)?.[0] 
            || 0,
      url: item.target?.link?.url 
           || item.target?.url 
           || `https://www.zhihu.com/question/${item.target?.id}`,
      type: 'hot'
    }));
    
    console.log(`   ✅ Cookie 有效，获取 ${items.length} 条数据`);
    
    return {
      meta: {
        source: 'zhihu-api-with-cookie',
        fetch_time: new Date().toISOString(),
        mode: 'hot',
        auth_method: 'file_cookie'
      },
      data: items
    };
  } catch (error) {
    console.log(`   ❌ Cookie 请求失败: ${error.message}`);
    throw error;
  }
}

/**
 * 获取认证策略
 */
function getAuthPriority() {
  const config = loadConfig();
  return config.auth?.priority || ['browser_profile', 'file_cookie', 'fallback_source'];
}

module.exports = {
  hasFileCookie,
  getFileCookie,
  fetchWithFileCookie,
  getAuthPriority,
  loadConfig
};
