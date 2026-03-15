#!/usr/bin/env node
/**
 * Cookie 设置工具
 * 帮助用户配置固化 Cookie
 */

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const CONFIG_PATH = path.join(__dirname, '..', 'config', 'fallback-sources.json');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

function question(q) {
  return new Promise(resolve => rl.question(q, resolve));
}

async function main() {
  console.log('\n🍪 知乎 Cookie 配置工具\n');
  console.log('请按以下步骤获取 Cookie:\n');
  console.log('1. 浏览器打开 https://www.zhihu.com 并登录');
  console.log('2. 按 F12 打开开发者工具');
  console.log('3. 切换到 Application/Storage → Cookies → https://www.zhihu.com');
  console.log('4. 复制以下字段的值:\n');

  const config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
  
  const cookies = {};
  
  cookies.zhihu_session = await question('zhihu_session (按回车跳过): ');
  cookies.z_c0 = await question('z_c0 (关键字段，建议填写): ');
  cookies._xsrf = await question('_xsrf: ');
  cookies._zap = await question('_zap (可选): ');
  cookies.d_c0 = await question('d_c0 (可选): ');
  
  // 过滤空值
  Object.keys(cookies).forEach(key => {
    if (!cookies[key]) delete cookies[key];
  });
  
  if (Object.keys(cookies).length === 0) {
    console.log('\n❌ 没有输入任何 Cookie，退出');
    rl.close();
    return;
  }
  
  // 更新配置
  config.cookie = { ...config.cookie, ...cookies };
  
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2), 'utf-8');
  
  console.log('\n✅ Cookie 已保存到 config/fallback-sources.json');
  console.log('   现在可以运行: node snippets/fetch-hot.js');
  
  rl.close();
}

main().catch(console.error);
