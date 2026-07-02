#!/usr/bin/env python3
"""runtime.py - 各推理策略模块共享的运行时状态与响应解析

抽出为独立叶子模块，目的是打破 processor↔策略 的循环依赖：策略模块从本模块取
get_output_dir/incr_progress/extract_json，而不再 import processor，于是 processor
可以在文件顶部直接 import 策略模块。

仅 Claude Agent SDK 路径：agent 的 LLM 调用在 claude_agent_client.py（走 SDK 的 query），
本模块不再持有 openai/anthropic 直调代码。
"""

import json
import re
import threading
import logging

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
    """返回当前输出目录（供推理模块写日志文件）。"""
    return _output_dir


def incr_progress(n, total, label):
    """累加进度并打印进度日志（推理模块共用）。"""
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
        for m in re.findall(pattern, text, re.DOTALL | re.IGNORECASE):
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
