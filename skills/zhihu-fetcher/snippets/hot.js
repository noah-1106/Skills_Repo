// 知乎热榜数据提取
// 使用方法：在 https://www.zhihu.com/hot 页面控制台运行

[...document.querySelectorAll('.HotItem')].map((item, i) => ({
  rank: i + 1,
  title: item.querySelector('.HotItem-title')?.textContent?.trim(),
  heat: item.querySelector('.HotItem-metrics')?.textContent?.match(/(\d+(?:\.\d+)?)/)?.[0],
  url: item.querySelector('a')?.href,
  type: 'hot'
})).slice(0, 50);
