/**
 * 浏览器端反爬机制调研脚本
 * 
 * 使用方法：
 * 1. 打开 https://www.zhihu.com/hot
 * 2. F12 打开开发者工具 → Network 面板
 * 3. 复制此代码到 Console 运行
 * 4. 对比正常请求和触发限制时的差异
 */

// 获取当前页面的请求特征
function analyzeCurrentPage() {
  const result = {
    url: location.href,
    cookies: document.cookie.split(';').map(c => c.trim()).filter(c => 
      c.startsWith('_xsrf') || 
      c.startsWith('_zap') || 
      c.startsWith('d_c0') ||
      c.startsWith('SESSIONID')
    ),
    userAgent: navigator.userAgent,
    screen: {
      width: screen.width,
      height: screen.height,
      colorDepth: screen.colorDepth
    },
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    language: navigator.language,
    platform: navigator.platform,
    // 检查是否有反爬相关的 JavaScript 变量
    windowKeys: Object.keys(window).filter(k => 
      k.toLowerCase().includes('zhihu') ||
      k.toLowerCase().includes('anti') ||
      k.toLowerCase().includes('captcha')
    ).slice(0, 20)
  };
  
  console.log('📊 当前页面特征:', result);
  return result;
}

// 监听网络请求
function monitorNetwork() {
  const originalFetch = window.fetch;
  window.fetch = async (...args) => {
    const [url, options] = args;
    console.log('📡 Fetch 请求:', {
      url: url.toString().slice(0, 100),
      headers: options?.headers,
      timestamp: new Date().toISOString()
    });
    
    try {
      const response = await originalFetch(...args);
      console.log('📥 响应:', {
        status: response.status,
        headers: Object.fromEntries(response.headers.entries())
      });
      return response;
    } catch (error) {
      console.error('❌ 请求失败:', error);
      throw error;
    }
  };
  
  console.log('✅ 网络监听已启动');
}

// 运行分析
analyzeCurrentPage();
monitorNetwork();

// 获取知乎 API 请求示例
async function fetchHotAPI() {
  try {
    const response = await fetch('/api/v3/feed/topstory/hot-list-web?limit=5', {
      headers: {
        'Accept': 'application/json'
      }
    });
    
    console.log('API 响应状态:', response.status);
    
    if (response.status === 200) {
      const data = await response.json();
      console.log('✅ API 调用成功，数据条数:', data.data?.length);
      return data;
    } else {
      console.log('❌ API 调用失败:', response.statusText);
      const text = await response.text();
      console.log('响应内容:', text.slice(0, 500));
    }
  } catch (e) {
    console.error('请求异常:', e);
  }
}

// 导出供手动调用
window.analyzePage = analyzeCurrentPage;
window.fetchHotAPI = fetchHotAPI;

console.log('\n💡 可用命令:');
console.log('  analyzePage() - 分析当前页面特征');
console.log('  fetchHotAPI() - 测试 API 调用');
