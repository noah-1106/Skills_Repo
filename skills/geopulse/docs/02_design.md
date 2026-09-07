# GeoPulse 设计文档

## 架构
```
frontend (vanilla JS + ECharts, 零构建)
    │  REST/JSON
backend (FastAPI + SQLite)
    ├── api/       brands | prompts | runs | insights
    ├── engine/    runner（执行监测） analyzer（提及解析）
    └── providers/ base → openai_compat（DeepSeek/智谱/通义/Kimi/OpenAI）| demo（确定性mock）
```

## 数据模型（SQLite 三表）
brands:   id, name, aliases(JSON), is_primary, created_at
prompts:  id, text, intent, is_active, created_at
runs:     id, status, provider, model, started_at, finished_at, error
answers:  id, run_id, prompt_id, brand_id(nullable), answer_text, mentioned_brands(JSON),
          sentiment, created_at

## 核心指标
可见率(visibility) = 提及该品牌的 prompt 数 / 总 prompt 数
份额(share_of_voice) = 该品牌提及次数 / 所有监测品牌提及总次数
情感(sentiment) = LLM 判定 positive/neutral/negative（analyzer 二次调用，可关）

## Provider 协议
class BaseProvider: def ask(prompt) -> (answer_text, meta)
openai_compat: POST {base_url}/chat/completions（用户配 key/model）
demo: 基于品牌词哈希的确定性回答生成（测试/演示，零成本）

## API 面（v1）
GET  /api/brands | POST /api/brands | DELETE /api/brands/{id}
GET  /api/prompts | POST /api/prompts | DELETE /api/prompts/{id}
POST /api/runs（触发监测，body: scope） | GET /api/runs | GET /api/runs/{id}
GET  /api/insights/overview?brand_id=&days=（趋势+份额+明细）
GET  /api/settings | PUT /api/settings（provider 配置，key 不回显）

## 关键决策
1. SQLite 而非 PG：单机自托管零配置，客户环境拷贝即用
2. 前端零构建：vanilla JS + 本地 ECharts 文件，离线可用，双平台浏览器直开
3. demo Provider 内置：销售演示/CI 测试不烧钱不依赖网络
4. key 存本地 config.json（0600），API 永不回显明文
