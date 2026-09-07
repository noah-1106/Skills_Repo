"""GeoPulse LLM Provider 层：可插拔引擎接入。

生产：openai_compat（DeepSeek/智谱/通义/Kimi/OpenAI 等一切 OpenAI 兼容端点）
测试/演示：demo（确定性 mock，零成本零网络）
"""
from __future__ import annotations
import json
import time
import urllib.request
import urllib.error
from abc import ABC, abstractmethod


class ProviderError(Exception):
    pass


class BaseProvider(ABC):
    name = "base"

    @abstractmethod
    def ask(self, prompt: str) -> tuple:
        """返回 (answer_text, meta_dict)。meta 至少含 model。"""
        raise NotImplementedError


class DemoProvider(BaseProvider):
    """确定性演示引擎：基于品牌词种子的伪回答生成器。

    用途：CI 测试、销售演示、无 key 环境跑通全链路。
    特性：同一 prompt+brands 永远得到同一回答（可断言）。
    注入品牌词需要调用方在 prompt 前设置 self._seed_brands。
    """

    name = "demo"

    def __init__(self):
        self._seed_brands = []

    def set_seed_brands(self, brands):
        self._seed_brands = [b.lower() for b in brands]

    def ask(self, prompt: str) -> tuple:
        h = sum(ord(c) for c in prompt)
        templates = [
            "根据行业资料，{main} 在这个领域口碑不错，{alt} 也有一定用户基础。具体选择建议结合预算与场景评估。",
            "目前比较主流的选择包括 {main} 和 {alt}。{main} 的优势在于生态完整，{alt} 价格更有竞争力。",
            "不少团队反馈 {main} 的中文场景支持较好；如果预算有限，{alt} 是常见的替代方案之一。",
            "综合公开讨论，{main} 和 {alt} 都值得列入候选清单，建议先小规模试点再决策。",
        ]
        main = self._seed_brands[0].title() if self._seed_brands else "某品牌"
        alt = self._seed_brands[1].title() if len(self._seed_brands) > 1 else "另一品牌"
        text = templates[h % len(templates)].format(main=main, alt=alt)
        meta = {"model": "geopulse-demo-1", "latency_ms": 50, "chars": len(text)}
        time.sleep(0.05)
        return text, meta


class OpenAICompatProvider(BaseProvider):
    """OpenAI 兼容协议：base_url + api_key + model 可指向任何厂商。

    已验证兼容：DeepSeek(api.deepseek.com) 智谱(open.bigmodel.cn)
    通义(dashscope.aliyuncs.com/compatible-mode) Kimi(api.moonshot.cn) OpenAI
    """

    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def ask(self, prompt: str) -> tuple:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一位客观的行业顾问，基于公开信息回答。"
                                              "如实地在回答中提及你知道的真实品牌名。"
                                              "不要因为问题里提到某品牌就回避或偏向它。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 500,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "geopulse/1.0",
            },
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            raise ProviderError(f"HTTP {e.code}: {body}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise ProviderError(f"network: {e}") from e
        latency = int((time.time() - t0) * 1000)
        try:
            msg = data["choices"][0]["message"]
            raw = msg.get("content")
            text = (raw or "").strip()
            reasoning = (msg.get("reasoning_content") or "").strip()
            usage = data.get("usage") or {}
            finish = data["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"malformed response: {e}") from e
        if not text and reasoning:
            # 推理模型（deepseek-reasoner 等）：正文在 reasoning_content
            text = reasoning
        if not text:
            raise ProviderError(
                f"empty answer (finish={finish}, model={self.model}) - "
                f"换模型或检查 max_tokens（当前 {self.model} 返回 content=null）")
        meta = {
            "model": data.get("model", self.model),
            "latency_ms": latency,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }
        return text, meta


def build_engines(settings: dict, seed_brands=None):
    """多引擎工厂：settings.engines = [{name, kind, ...}]。
    兼容旧版单引擎 settings.provider（自动迁移语义）。"""
    from pathlib import Path
    engines = []
    eng_list = settings.get("engines") if isinstance(settings, dict) else None
    if not eng_list:
        # 旧版单引擎配置 → 视作单引擎列表
        prov = settings.get("provider") if isinstance(settings, dict) else None
        if prov and prov.get("kind") == "openai_compat":
            eng_list = [{"name": "engine-1", **prov}]
        else:
            eng_list = [{"name": "demo", "kind": "demo"}]
    result = []
    for e in eng_list:
        name = e.get("name") or (e.get("model") or "demo")
        kind = e.get("kind") or "demo"
        if kind == "openai_compat":
            key = e.get("api_key") or ""
            if not key:
                raise ProviderError(f"engine [{name}] missing api_key")
            result.append((name, OpenAICompatProvider(
                base_url=e.get("base_url", "https://api.deepseek.com/v1"),
                api_key=key, model=e.get("model", "deepseek-chat"),
                timeout=int(e.get("timeout", 60)))))
        else:
            d = DemoProvider()
            if seed_brands:
                d.set_seed_brands(seed_brands)
            result.append((name, d))
    return result


def build_provider(settings: dict, seed_brands=None):
    """工厂：settings 来自 config.json 的 provider 段。"""
    kind = (settings or {}).get("kind") or "demo"
    if kind == "openai_compat":
        cfg = settings or {}
        key = cfg.get("api_key") or ""
        if not key:
            raise ProviderError("openai_compat 需要 api_key（settings 里配置）")
        p = OpenAICompatProvider(
            base_url=cfg.get("base_url", "https://api.deepseek.com/v1"),
            api_key=key,
            model=cfg.get("model", "deepseek-chat"),
            timeout=int(cfg.get("timeout", 60)),
        )
        return p
    d = DemoProvider()
    if seed_brands:
        d.set_seed_brands(seed_brands)
    return d
