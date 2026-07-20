#!/usr/bin/env python3
"""openai_agent_client.py - OpenAI SDK 后端（AgentClient 子类）

通过 openai SDK 直连 OpenAI 兼容端点做单条分类推理，流式返回文本（含
[{"classification","reason"}] JSON）。仅在 cfg.backend == 'openai' 时被
agent_client.create_agent 动态 import，故 openai 仅在选用本后端时才需要安装。

设计要点：
  - prompt 复刻删除前 classify_batch.build_batch_prompt 模板（同
    ---CLASSIFICATION--- / ---REQUIREMENTS--- 分隔符、同指令、
    同 JSON 形状 [{"classification":"编码","reason":"推理过程"}]），改为单条：
    ---PROBLEM--- / ---PROBLEM_END---，"必须返回1个元素"。openai 后端自带 prompt
    构造，与 opencode 后端的 skill-based system 注入互不共享。
  - 完整提示词 = 代码内 prompt + 文件内容：CLASSIFICATION ← classification_function.md；
    REQUIREMENTS ← classification_requirements.md（从 classifier skill 抽取的分类要求）。
    不再注入 APP(info) / EXAMPLES / ERROR_EXAMPLES 段（历史 info.md / examples_*.md /
    error_examples_*.md 已删，原本就为空）。
  - 流式：delta.reasoning_content → on_progress（仅日志，不进 extract_json）；
    delta.content → yield（answer 文本）。空闲超时由调用方经 idle_timeout 传入，
    本后端对每个 chunk 的 __anext__() 套 asyncio.wait_for，无产出超阈值即判卡死。

stream() 是异步生成器，逐块 yield 文本，由调用方消费：边收边写日志、拼接全文后
extract_json 解析；超时与日志写入由调用方负责。
"""

import asyncio
import logging
import os

import httpx
import openai

from agent_client import AgentClient

logger = logging.getLogger("classify_data")


# ========== reference 加载（按 skill_dir 缓存）==========

_REFS_CACHE = {}


def _load_refs(cfg):
    """从 cfg['skill_dir'](=app 目录) 读 classification_function.md 作 classification，
    读 classification_requirements.md 作 requirements（从 classifier skill 抽取的分类要求，
    注入 prompt 作为完整提示词的一部分；文件缺失则留空）。
    """
    app_dir = cfg.get("skill_dir") or ""
    skill_name = cfg.get("skill_name") or ""
    key = (app_dir, skill_name)
    if key in _REFS_CACHE:
        return _REFS_CACHE[key]

    def _read(fname):
        p = os.path.join(app_dir, fname)
        if p and os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.warning("读取 %s 失败: %s", p, e)
        return ""

    refs = {
        "classification": _read("classification_function.md"),
        "requirements": _read("classification_requirements.md"),
    }
    _REFS_CACHE[key] = refs
    return refs


def _build_prompt(cfg, desc, correction):
    """复刻删除前 classify_batch.build_batch_prompt 模板（单条版）。

    与历史保持一致：同分隔符、同指令、同 JSON 形状 [{"classification":"编码","reason"}]，
    仅把多问题改为单问题（---PROBLEM--- / ---PROBLEM_END---，必须返回1个元素）。
    correction 非空时末尾追加修正要求（与 opencode 后端 correction 拼接方式一致）。
    """
    app_name = cfg.get("app_name") or "应用"
    refs = _load_refs(cfg)
    prompt = f"""你是一位专业的{app_name}应用问题分类专家，请根据用户的问题描述，

结合分类编码表（以---CLASSIFICATION---、---CLASSIFICATION_END---分隔）与分类要求（以---REQUIREMENTS---、---REQUIREMENTS_END---分隔），推导出最准确的分类编码。

---PROBLEM---
{desc or ""}
---PROBLEM_END---

---CLASSIFICATION---
{refs.get('classification', '')}
---CLASSIFICATION_END---

---REQUIREMENTS---
{refs.get('requirements', '')}
---REQUIREMENTS_END---

推导规则：对照编码表逐层推导，返回分类编码；无法推导的层级截断编码（如无法推导二级则只返回一级编码如"1"，无法推导三级则只返回到二级编码如"1.1"）；不属于编码表问题的返回"0"。

必须返回1个元素，禁止多加或遗漏，必须按照以下json格式返回，json格式被三个反引号分割
```
[{{"classification": "编码", "reason": "推理过程"}}]
```

【要求】
1.推理过程需要严格按照层级推理，即先分析出第一级，然后根据一级分类分析出第二级，再根据第二级分类分析出第三第三级分类
2.忽略卓易通相关的描述，只分析原生鸿蒙相关的问题
3.要根据现有的描述分析问题，若无法进一步得到更确切的分类则返回，不要去联想猜测
4.推理过程只描述问题描述与分类的语义关联，不要在推理中提及候选编号或分类编码。
"""
    if correction:
        prompt += "\n\n===== 上次返回有误，请按以下修正要求重新返回 =====\n" + correction
    return prompt


def _env_bool(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("true", "1", "yes")


class OpenAIAgentClient(AgentClient):
    """openai SDK 后端实现。"""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.model = cfg.get("model")
        self.api_key = cfg.get("api_key")
        self.base_url = cfg.get("base_url") or None
        # 后端专用配置（与 opencode 后端读 LLM_AGENT_PROVIDER 同模式，自取 env）
        self.max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "1024"))
        self.temperature = float(os.environ.get("LLM_TEMPERATURE", "0.7"))
        self.verify_ssl = _env_bool("LLM_VERIFY_SSL", True)
        self.disable_proxy = _env_bool("LLM_DISABLE_PROXY", False)
        self.enable_thinking = _env_bool("LLM_ENABLE_THINKING", True)
        if not self.model:
            raise RuntimeError("openai 后端需配置 LLM_MODEL")
        if not self.api_key:
            raise RuntimeError("openai 后端需配置 LLM_API_KEY")
        # 仅在需关 SSL / 禁代理时构造自定义 http_client，否则用 SDK 默认
        self._http_client = None
        if not self.verify_ssl or self.disable_proxy:
            self._http_client = httpx.AsyncClient(verify=self.verify_ssl, trust_env=not self.disable_proxy)
        self._client = None

    def _get_client(self):
        if self._client is None:
            kwargs = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            if self._http_client is not None:
                kwargs["http_client"] = self._http_client
            self._client = openai.AsyncOpenAI(**kwargs)
        return self._client

    async def stream(self, desc, *, correction=None, idle_timeout=None, on_progress=None):
        """异步生成器：逐块 yield answer 文本（content 增量）。

        - delta.reasoning_content → on_progress（仅日志，不进 extract_json，避免思考草稿
          里的 ```json / { 污染解析）；delta.content → yield。
        - idle_timeout：对每个 chunk 的 __anext__() 套 asyncio.wait_for，idle_timeout 秒内
          无任何产出即判卡死，抛 RuntimeError，由调用方按失败重试（持续产出期间不超时）。
        """
        prompt = _build_prompt(self.cfg, desc, correction)
        client = self._get_client()
        extra_body = {"enable_thinking": True} if self.enable_thinking else None
        stream = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stream=True,
            extra_body=extra_body,
        )
        try:
            while True:
                try:
                    if idle_timeout:
                        chunk = await asyncio.wait_for(stream.__anext__(), idle_timeout)
                    else:
                        chunk = await stream.__anext__()
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise RuntimeError("agent 空闲超时(%ds 无消息)" % idle_timeout)

                # 兼容空 choices（部分心跳 chunk）
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                # reasoning 增量（reasoning 模型）：只写日志看进度，不进提取 text
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning and on_progress:
                    try:
                        on_progress(reasoning)
                    except Exception:
                        pass
                content = getattr(delta, "content", None)
                if content:
                    yield content
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    async def aclose(self):
        try:
            if self._client is not None:
                await self._client.close()
        except Exception:
            pass
        try:
            if self._http_client is not None:
                await self._http_client.aclose()
        except Exception:
            pass


def create(cfg):
    """工厂：供 agent_client.create_agent 按 backend=='openai' 动态调用。"""
    return OpenAIAgentClient(cfg)
