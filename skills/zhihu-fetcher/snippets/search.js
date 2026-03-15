// 知乎搜索结果提取
// 使用方法：在搜索页面控制台运行，或替换 "关键词" 后粘贴到 browser evaluate

(() => {
  const keyword = new URLSearchParams(location.search).get('q') || '';
  
  return {
    meta: {
      source: 'zhihu',
      keyword: decodeURIComponent(keyword),
      fetch_time: new Date().toISOString(),
      url: location.href
    },
    data: [...document.querySelectorAll('.SearchResult-Card, .ContentItem')].map((item, i) => ({
      rank: i + 1,
      title: item.querySelector('.ContentItem-title a, .SearchResult-Title a')?.textContent?.trim(),
      url: item.querySelector('.ContentItem-title a, .SearchResult-Title a')?.href,
      excerpt: item.querySelector('.RichContent-inner, .SearchResult-Abstract')?.textContent?.trim()?.slice(0, 150),
      author: item.querySelector('.AuthorInfo-name')?.textContent?.trim(),
      type: item.querySelector('a')?.href?.includes('/question/') ? 'question' : 'article'
    })).slice(0, 30)
  };
})();
