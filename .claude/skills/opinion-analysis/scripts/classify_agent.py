#!/usr/bin/env python3
"""classify_agent.py - 通过 Claude Agent SDK（抖音舆情 skill）做单条分类推理

LLM_PROVIDER=claude-agent-sdk 时由 classify_data.main 分派调用。每条问题描述
发起一次 agent 调用，skill 一次性返回完整分类编码 {classification, reason}，
因此 batch/layered 两种 reason mode 在本 provider 下退化为"每条一次 agent 调用"。

共享逻辑（save_item / extract_json / code_to_classification / 进度 / 输出目录）
均在 classify_data 中实现，这里通过懒导入避免循环依赖，与 classify_batch/layered 同级。
"""

import os
import re
import time

from classify_data import (
    save_item,
    extract_json,
    code_to_classification,
    get_output_dir,
    incr_progress,
)
from claude_agent_client import call_agent_sdk

import logging
logger = logging.getLogger("classify_data")


def process_item_agent(item, app_name, problem_col, df, refs, db_path,
                       agent_cfg, total, version_col=None, domain="function"):
    """单条问题 → 一次 agent(skill) 调用 → 解析 JSON → 入库。

    agent_cfg: dict，含 skill_dir/skill_name/model/api_key/base_url/
               max_turns/timeout/max_retries。
    返回 [(num, status)]，状态码与 batch/layered 一致：0=成功,1=其他问题,2=失败。
    """
    results = []
    num = item["num"]
    desc = item["desc"]

    if not desc.strip():
        save_item(num, ["其他问题"], "空描述,跳过分类", app_name, problem_col, df, db_path, 2, version_col)
        incr_progress(1, total, str(num))
        return [(num, 2)]

    code_to_path = refs.get("classification_tree", {})
    output_dir = get_output_dir()
    max_retries = agent_cfg.get("max_retries", 3)

    def _log_file(attempt):
        suffix = f"_retry{attempt + 1}" if attempt > 0 else ""
        base = f"response_{num}_agent{suffix}"
        return os.path.join(output_dir, "log", f"{base}.log") if output_dir else None

    reason = ""
    code = "0"
    status = 2

    for attempt in range(max_retries):
        try:
            logger.info("行%d agent请求发送, 第%d/%d次", num, attempt + 1, max_retries)
            text = call_agent_sdk(
                desc,
                skill_dir=agent_cfg["skill_dir"],
                skill_name=agent_cfg["skill_name"],
                model=agent_cfg.get("model"),
                api_key=agent_cfg.get("api_key"),
                base_url=agent_cfg.get("base_url"),
                max_turns=agent_cfg.get("max_turns"),
                timeout=agent_cfg.get("timeout"),
                log_file=_log_file(attempt),
            )
            logger.info("行%d agent返回, 文本长度: %d", num, len(text) if text else 0)
        except Exception as e:
            logger.warning("行%d agent调用失败(第%d/%d次): %s", num, attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            save_item(num, ["其他问题"], f"agent调用失败: {e}", app_name, problem_col, df, db_path, 2, version_col)
            incr_progress(1, total, str(num))
            return [(num, 2)]

        parsed = extract_json(text)
        if not isinstance(parsed, dict):
            logger.warning("行%d JSON解析失败(第%d/%d次), 原始: %s", num, attempt + 1, max_retries, (text or "")[:300])
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            save_item(num, ["其他问题"], "JSON解析失败", app_name, problem_col, df, db_path, 2, version_col)
            incr_progress(1, total, str(num))
            return [(num, 2)]

        code = parsed.get("classification", "0")
        reason = parsed.get("reason", "") or ""
        if not isinstance(code, str):
            logger.warning("行%d 分类格式错误(第%d/%d次): classification应为字符串编码", num, attempt + 1, max_retries)
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            save_item(num, ["其他问题"], "分类格式错误: classification应为字符串编码", app_name, problem_col, df, db_path, 2, version_col)
            incr_progress(1, total, str(num))
            return [(num, 2)]

        # 容错: 提取编码部分(如"1.1 滑动卡顿" → "1.1")
        code_match = re.match(r'^(\d+(?:\.\d+)*)', code.strip())
        code_str = code_match.group(1) if code_match else code.strip()

        if code_str != "0" and code_str not in code_to_path:
            logger.warning("行%d 分类编码无效(第%d/%d次): '%s' 不存在于编码表", num, attempt + 1, max_retries, code_str)
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            save_item(num, ["其他问题"], f"分类编码无效: {code} 不存在于编码表", app_name, problem_col, df, db_path, 2, version_col)
            incr_progress(1, total, str(num))
            return [(num, 2)]

        # 校验通过
        classification = code_to_classification(code_str, code_to_path)
        if code_str == "0":
            save_item(num, classification, reason, app_name, problem_col, df, db_path, 1, version_col)
            status = 1
        else:
            save_item(num, classification, reason, app_name, problem_col, df, db_path, 0, version_col)
            status = 0
        logger.info("行%d agent推理成功, 编码: %s, 分类: %s", num, code_str, ".".join(classification))
        incr_progress(1, total, str(num))
        return [(num, status)]

    # 重试耗尽（理论上上面分支都已 return，兜底）
    save_item(num, ["其他问题"], reason or "重试耗尽", app_name, problem_col, df, db_path, 2, version_col)
    incr_progress(1, total, str(num))
    return [(num, 2)]
