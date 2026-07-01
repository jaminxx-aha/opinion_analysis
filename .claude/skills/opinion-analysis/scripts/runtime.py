#!/usr/bin/env python3
"""runtime.py - 各推理策略模块共享的运行时状态与 LLM 调用

抽出为独立叶子模块，目的是打破 processor↔策略 的循环依赖：策略模块从本模块取
get_output_dir/incr_progress/call_llm_sdk/extract_json，而不再 import processor，
于是 processor 可以在文件顶部直接 import 三个策略。

依赖（顶部硬依赖）：anthropic、openai、httpx。三者均在 requirements.txt 中。
"""

import json
import re
import threading
import logging

from anthropic import Anthropic
from openai import OpenAI
import httpx

logger = logging.getLogger("classify_data")


# ========== 运行时状态（Phase 2 设置，Phase 3 各策略共享）==========
_output_dir = ""
_progress_lock = threading.Lock()
_progress_done = 0


def set_output_dir(output_dir):
    """设置当前输出目录（prepare_data 阶段调用）。"""
    global _output_dir
    _output_dir = output_dir


def get_output_dir():
    """返回当前输出目录（供批量/逐层推理模块写日志文件）。"""
    return _output_dir


def incr_progress(n, total, label):
    """累加进度并打印进度日志（批量/逐层推理模块共用）。"""
    global _progress_done
    with _progress_lock:
        _progress_done += n
        pct = _progress_done * 100 // total if total else 0
        logger.info("[%3d%%] 已完成第%s条 (%d/%d)", pct, label, _progress_done, total)


# ========== 响应解析 ==========

def extract_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in [r'```json\s*(.*?)\s*```', r'```\s*(.*?)\s*```']:
        for m in re.findall(pattern, text, re.DOTALL):
            try:
                return json.loads(m)
            except json.JSONDecodeError:
                continue
    brace = re.search(r'\[[\s\S]*\]' if '[' in text else r'\{[\s\S]*\}', text)
    if brace:
        try:
            return json.loads(brace.group())
        except json.JSONDecodeError:
            pass
    return None


# ========== LLM 调用 ==========

def call_llm_sdk(prompt, provider, api_key, base_url, model, max_tokens, timeout, verify_ssl, disable_proxy=False, temperature=0.7, log_file=None):
    base_url = base_url.rstrip("/") if base_url else None
    trust_env = not disable_proxy
    if provider == "anthropic":
        if not verify_ssl or disable_proxy:
            http_client = httpx.Client(verify=verify_ssl, trust_env=trust_env)
            client = Anthropic(api_key=api_key, base_url=base_url, http_client=http_client) if base_url else Anthropic(api_key=api_key, http_client=http_client)
        else:
            client = Anthropic(api_key=api_key, base_url=base_url) if base_url else Anthropic(api_key=api_key)
        resp = client.messages.create(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}], temperature=temperature, timeout=timeout, stream=True)
        log_fh = open(log_file, "w", encoding="utf-8") if log_file else None
        _wrote_reasoning_header = False
        _wrote_content_header = False
        full_text = ""
        for event in resp:
            if event.type == "content_block_start":
                if log_fh:
                    block_type = event.content_block.type
                    if block_type == "thinking" and not _wrote_reasoning_header:
                        log_fh.write("===== 思考过程 =====\n")
                        log_fh.flush()
                        _wrote_reasoning_header = True
                    elif block_type == "text" and not _wrote_content_header:
                        log_fh.write("\n===== 返回内容 =====\n")
                        log_fh.flush()
                        _wrote_content_header = True
            elif event.type == "content_block_delta":
                delta_type = event.delta.type
                if delta_type == "thinking_delta":
                    if log_fh:
                        if not _wrote_reasoning_header:
                            log_fh.write("===== 思考过程 =====\n")
                            _wrote_reasoning_header = True
                        log_fh.write(event.delta.thinking)
                        log_fh.flush()
                else:
                    full_text += event.delta.text
                    if log_fh:
                        if not _wrote_content_header:
                            log_fh.write("\n===== 返回内容 =====\n")
                            _wrote_content_header = True
                        log_fh.write(event.delta.text)
                        log_fh.flush()
        if log_fh:
            log_fh.close()
        logger.info("LLM响应接收完成(Anthropic SDK, key=%s..., 长度%d)", api_key[:8], len(full_text))
        return full_text
    else:
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        if not verify_ssl or disable_proxy:
            kwargs["http_client"] = httpx.Client(verify=verify_ssl, trust_env=trust_env)
        client = OpenAI(**kwargs)
        stream = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=temperature, timeout=timeout, stream=True, extra_body={"enable_thinking": True})
        log_fh = open(log_file, "w", encoding="utf-8") if log_file else None
        _wrote_reasoning_header = False
        _wrote_content_header = False
        full_text = ""
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta:
                reasoning = getattr(delta, 'reasoning_content', None) or ""
                content = delta.content or ""
                if reasoning:
                    if log_fh:
                        if not _wrote_reasoning_header:
                            log_fh.write("===== 思考过程 =====\n")
                            _wrote_reasoning_header = True
                        log_fh.write(reasoning)
                        log_fh.flush()
                if content:
                    full_text += content
                    if log_fh:
                        if not _wrote_content_header:
                            log_fh.write("\n===== 返回内容 =====\n")
                            _wrote_content_header = True
                        log_fh.write(content)
                        log_fh.flush()
        if log_fh:
            log_fh.close()
        logger.info("LLM响应接收完成(OpenAI SDK, key=%s..., 长度%d)", api_key[:8], len(full_text))
        return full_text
