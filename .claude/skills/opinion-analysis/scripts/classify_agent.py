#!/usr/bin/env python3
"""classify_agent.py - 通过 Claude Agent SDK（抖音舆情 skill）做单条分类推理

唯一的推理路径：每条问题描述发起一次 agent 调用，skill 一次性返回完整分类编码
{result, reason}，每条问题一个任务。

共享逻辑（save_item 在 db_utils；extract_json/get_output_dir/incr_progress 在 runtime）
通过顶层 import 引入。
"""

import os
import re
import time
import asyncio
import logging
from db_utils import save_item
from runtime import extract_json, get_output_dir, incr_progress
from claude_agent_client import call_agent_sdk

logger = logging.getLogger("classify_data")

def match_result_to_code(result, code_to_path):
    """校验 skill 返回的 result 是否与编码树一致，并映射到数字编码。

    skill 的 result 可能是：
      - 名称路径 "动效卡顿-滑动卡顿-页面滑动卡顿-视频流上下滑动卡顿"
      - "未知问题" / "0"（非性能/非鸿蒙/无法分类）
      - 数字编码 "1.1.1.1"（兼容）
      - 兜底一级类 "卡顿"（不在 classification_*.md 中展示，由 parse_classification_md 追加）
    只有当整条名称路径在编码树中精确命中某节点时才视为一致，返回 (code, path)；
    否则一律返回 (None, None)，由调用方按「分类结果与编码树不一致」失败重试
    （不做事前前缀回退，避免静默降级到上级、丢失深层语义）。

    匹配策略：
      1) 未知问题/0 → ("0", ["未知问题"])
      2) 数字编码直接命中 → (code, path)
      3) 整条名称路径精确命中 → (code, path)
      4) 都不中 → (None, None)
    """
    if not isinstance(result, str):
        return (None, None)
    result = result.strip()
    if not result:
        return (None, None)

    # 1) 未知问题
    if result in ("0", "未知问题", "其他问题"):
        return ("0", ["未知问题"])

    # 2) 数字编码直接命中
    if re.match(r'^\d+(\.\d+)*$', result) and result in code_to_path:
        return (result, code_to_path[result])

    # 反向索引：名称路径元组 -> 编码（名称内含 "/" 故只用 - — → > 作分隔符）
    path_to_code = {tuple(v): k for k, v in code_to_path.items() if v}

    # 3) 整条名称路径精确命中
    parts = tuple(p.strip() for p in re.split(r'[-—→>]+', result) if p.strip())
    if parts and parts in path_to_code:
        return (path_to_code[parts], code_to_path[path_to_code[parts]])

    # 4) 不一致：不做前缀回退，交由调用方重试
    return (None, None)


def _consume_agent(desc, agent_cfg, log_file):
    """同步桥接：运行流式 agent，边收边写日志，返回拼接后的完整文本。

    用 asyncio.wait_for 包裹消费协程实现超时；agent 报错(RuntimeError)与超时
    都抛 RuntimeError，由调用方按失败重试。日志边收边写，长任务可 tail 实时查看。
    """
    timeout = agent_cfg.get("timeout")

    async def _run():
        chunks = []
        fh = None
        if log_file:
            try:
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
                fh = open(log_file, "w", encoding="utf-8")
                fh.write("===== Agent 流式返回 =====\n")
            except Exception as e:
                logger.warning("写 agent 日志失败 %s: %s", log_file, e)
        agen = call_agent_sdk(
            desc,
            skill_dir=agent_cfg["skill_dir"],
            skill_name=agent_cfg["skill_name"],
            model=agent_cfg.get("model"),
            api_key=agent_cfg.get("api_key"),
            base_url=agent_cfg.get("base_url"),
            max_turns=agent_cfg.get("max_turns"),
        )
        try:
            async for chunk in agen:
                chunks.append(chunk)
                if fh:
                    try:
                        fh.write(chunk)
                        fh.flush()
                    except Exception:
                        pass
        finally:
            # 显式关闭流式生成器，避免 asyncio 收尾时报 "error during closing of async generator"
            try:
                await agen.aclose()
            except Exception:
                pass
            if fh:
                try:
                    fh.close()
                except Exception:
                    pass
        return "".join(chunks)

    try:
        if timeout:
            return asyncio.run(asyncio.wait_for(_run(), timeout))
        return asyncio.run(_run())
    except asyncio.TimeoutError:
        raise RuntimeError("agent 调用超时(%ds)" % timeout)


def process_item_agent(item, app_name, problem_col, df, refs, db_path,
                       agent_cfg, total, version_col=None, domain="function"):
    """单条问题 → 一次 agent(skill) 调用 → 解析 JSON → 入库。

    agent_cfg: dict，含 skill_dir/skill_name/model/api_key/base_url/
               max_turns/timeout/max_retries。
    返回 [(num, status)]，状态码与 batch/layered 一致：0=成功,1=未知问题,2=失败。
    """
    results = []
    num = item["num"]
    desc = item["desc"]

    if not desc.strip():
        save_item(num, ["未知问题"], "空描述,跳过分类", app_name, problem_col, df, db_path, 2, version_col)
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
            text = _consume_agent(desc, agent_cfg, _log_file(attempt))
            logger.info("行%d agent返回, 文本长度: %d", num, len(text) if text else 0)
        except Exception as e:
            logger.warning("行%d agent调用失败(第%d/%d次): %s", num, attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            save_item(num, ["未知问题"], f"agent调用失败: {e}", app_name, problem_col, df, db_path, 2, version_col)
            incr_progress(1, total, str(num))
            return [(num, 2)]

        parsed = extract_json(text)
        if not isinstance(parsed, dict):
            logger.warning("行%d JSON解析失败(第%d/%d次), 原始: %s", num, attempt + 1, max_retries, (text or "")[:300])
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            save_item(num, ["未知问题"], "JSON解析失败", app_name, problem_col, df, db_path, 2, version_col)
            incr_progress(1, total, str(num))
            return [(num, 2)]

        # skill 用 result 字段返回名称路径(如 "动效卡顿-滑动卡顿-列表滑动卡顿-视频流上下滑动卡顿")
        # 或 "未知问题"/"0"；也可能是数字编码。统一用 match_result_to_code 校验并映射到编码树。
        result = parsed.get("result", "")
        reason = parsed.get("reason", "") or ""
        if not isinstance(result, str):
            logger.warning("行%d 分类格式错误(第%d/%d次): result应为字符串", num, attempt + 1, max_retries)
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            save_item(num, ["未知问题"], "分类格式错误: result应为字符串", app_name, problem_col, df, db_path, 2, version_col)
            incr_progress(1, total, str(num))
            return [(num, 2)]

        code, classification = match_result_to_code(result, code_to_path)
        if code is None:
            logger.warning("行%d 分类结果与编码树不一致(第%d/%d次): '%s'", num, attempt + 1, max_retries, (result or "")[:200])
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            save_item(num, ["未知问题"], f"分类结果不在编码表: {result}", app_name, problem_col, df, db_path, 2, version_col)
            incr_progress(1, total, str(num))
            return [(num, 2)]

        if code == "0":
            save_item(num, ["未知问题"], reason or "未知问题", app_name, problem_col, df, db_path, 1, version_col)
            incr_progress(1, total, str(num))
            return [(num, 1)]

        # 校验通过：classification 为编码树内名称路径
        save_item(num, classification, reason, app_name, problem_col, df, db_path, 0, version_col)
        status = 0
        logger.info("行%d agent推理成功, 编码: %s, 分类: %s", num, code, ".".join(classification))
        incr_progress(1, total, str(num))
        return [(num, status)]

    # 重试耗尽（理论上上面分支都已 return，兜底）
    save_item(num, ["未知问题"], reason or "重试耗尽", app_name, problem_col, df, db_path, 2, version_col)
    incr_progress(1, total, str(num))
    return [(num, 2)]
