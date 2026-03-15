/**
 * 频率限制器
 * 简单的令牌桶算法实现
 */

class RateLimiter {
  constructor(minIntervalMs = 2000) {
    this.minInterval = minIntervalMs;
    this.lastRequestTime = 0;
  }

  /**
   * 等待直到可以发送下一个请求
   */
  async wait() {
    const now = Date.now();
    const elapsed = now - this.lastRequestTime;
    
    if (elapsed < this.minInterval) {
      const waitTime = this.minInterval - elapsed;
      console.log(`⏳ 频率限制: 等待 ${waitTime}ms...`);
      await new Promise(resolve => setTimeout(resolve, waitTime));
    }
    
    this.lastRequestTime = Date.now();
  }

  /**
   * 执行带频率限制的函数
   */
  async execute(fn) {
    await this.wait();
    return await fn();
  }
}

/**
 * 全局频率限制器实例
 */
const defaultRateLimiter = new RateLimiter(
  parseInt(process.env.RATE_LIMIT) || 2000
);

module.exports = {
  RateLimiter,
  defaultRateLimiter
};
