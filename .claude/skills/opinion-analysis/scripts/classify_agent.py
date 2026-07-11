#!/usr/bin/env python3
"""classify_agent.py - 通过 agent 后端（抖音舆情 skill）做单条分类推理

唯一的推理路径：每条问题描述发起一次 agent 调用，skill 一次性返回完整分类编码
{result, reason}，每条问题一个任务。agent 后端由配置选择（agent_client.create_agent），
本模块只与后端基类打交道，不感知具体后端实现。

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
from agent_client import create_agent
from args import derive_business_classification

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


def _consume_agent(desc, agent_cfg, log_file, correction=None):
    """同步桥接：运行流式 agent，边收边写日志，返回拼接后的完整文本。

    超时由后端按“空闲超时”实现（idle_timeout 秒内无任何消息才判卡死，
    流式持续产出/工具往返期间不超时）。agent 报错(RuntimeError)与空闲超时都抛
    RuntimeError，由调用方按失败重试。日志边收边写，长任务可 tail 实时查看。
    correction 非空时拼入 prompt，把上一次失败上下文带给 agent 修正。
    后端实例由 agent_client.create_agent(agent_cfg) 按 cfg.backend 分派。
    """
    idle_timeout = agent_cfg.get("timeout")

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
        agent = create_agent(agent_cfg)
        agen = agent.stream(desc, correction=correction, idle_timeout=idle_timeout)
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

    return asyncio.run(_run())


def _try_repair_json(text):
    """尝试用 json_repair 修复残缺/带包裹的 JSON 文本，返回解析后的 dict 或 None。"""
    if not text:
        return None
    # 先取出代码块或花括号内的 JSON 片段，再交给 json_repair
    candidate = None
    for pat in (r'```json\s*(.*?)\s*```', r'```\s*(.*?)\s*```'):
        m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if m:
            candidate = m.group(1)
            break
    if not candidate:
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            candidate = m.group()
    if not candidate:
        return None
    try:
        import json_repair
        obj = json_repair.repair_json(candidate, return_objects=True)
        if isinstance(obj, dict):
            return obj
    except Exception as e:
        logger.debug("json_repair 修复失败: %s", e)
    return None


def classify_one(num, desc, refs, agent_cfg):
    """对单条问题描述跑 agent 分类（含重试/json_repair/correction 纠偏）。

    返回 (status, classification, reason)：0=成功, 1=未知问题, 2=失败。
    不入库、不打印进度，由调用方负责 save_item / incr_progress。
    """
    code_to_path = refs.get("classification_tree", {})
    tree_md = refs.get("classification", "")
    output_dir = get_output_dir()
    max_retries = agent_cfg.get("max_retries", 3)

    def _log_file(attempt):
        suffix = f"_retry{attempt + 1}" if attempt > 0 else ""
        base = f"response_{num}_agent{suffix}"
        return os.path.join(output_dir, "log", f"{base}.log") if output_dir else None

    reason = ""
    correction = None  # 上一次失败的原因上下文，带入下一次 agent 调用让其修正

    for attempt in range(max_retries):
        try:
            logger.info("行%d agent请求发送, 第%d/%d次", num, attempt + 1, max_retries)
            text = _consume_agent(desc, agent_cfg, _log_file(attempt), correction=correction)
            logger.info("行%d agent返回, 文本长度: %d", num, len(text) if text else 0)
        except Exception as e:
            logger.warning("行%d agent调用失败(第%d/%d次): %s", num, attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return 2, ["未知问题"], f"agent调用失败: {e}"

        parsed = extract_json(text)
        if not isinstance(parsed, dict):
            # 1) 先尝试 json_repair 修复；修复成功则直接用，不消耗重试
            repaired = _try_repair_json(text)
            if isinstance(repaired, dict):
                parsed = repaired
                logger.info("行%d json_repair 修复成功(第%d/%d次)", num, attempt + 1, max_retries)
            else:
                # 2) 修复失败：把错误信息带给 agent 重新返回，计入重试
                logger.warning("行%d JSON解析失败且修复失败(第%d/%d次), 原始: %s", num, attempt + 1, max_retries, (text or "")[:300])
                correction = (
                    '你上一次的返回不是合法 JSON，无法解析。'
                    '原始返回（截断到 800 字）：\n' + (text or '')[:800] + '\n'
                    '请严格只返回用三个反引号包裹的合法 JSON 对象，不要附加任何说明文字。'
                    '格式：```{"result": "<分类名称路径或未知问题>", "reason": "<推理过程>"}```'
                )
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                return 2, ["未知问题"], "JSON解析失败"

        # skill 用 result 字段返回名称路径(如 "动效卡顿-滑动卡顿-列表滑动卡顿-视频流上下滑动卡顿")
        # 或 "未知问题"/"0"；也可能是数字编码。统一用 match_result_to_code 校验并映射到编码树。
        result = parsed.get("result", "")
        reason = parsed.get("reason", "") or ""
        if not isinstance(result, str):
            logger.warning("行%d 分类格式错误(第%d/%d次): result应为字符串", num, attempt + 1, max_retries)
            correction = (
                '你上一次返回的 JSON 中 result 字段不是字符串。'
                '原始返回（截断到 800 字）：\n' + (text or '')[:800] + '\n'
                '请重新返回，result 必须是字符串（分类名称路径或"未知问题"）。'
            )
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return 2, ["未知问题"], "分类格式错误: result应为字符串"

        code, classification = match_result_to_code(result, code_to_path)
        if code is None:
            # 分类与编码树对应不上：把分类树带给 agent 重新返回，计入重试
            logger.warning("行%d 分类结果与编码树不一致(第%d/%d次): '%s'", num, attempt + 1, max_retries, (result or "")[:200])
            correction = (
                '你上一次返回的分类「' + (result or '') + '」不在分类树中。'
                '请严格从下列分类树中选择一条名称路径重新返回。\n'
                '分类树（classification.md）：\n' + tree_md + '\n'
                '返回格式：用三个反引号包裹的 JSON {"result": "<从分类树中选择的名称路径>", "reason": "<推理过程>"}'
            )
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return 2, ["未知问题"], f"分类结果不在编码表: {result}"

        if code == "0":
            return 1, ["未知问题"], reason or "未知问题"

        logger.info("行%d agent推理成功, 编码: %s, 分类: %s", num, code, ".".join(classification))
        return 0, classification, reason

    # 重试耗尽（理论上上面分支都已 return，兜底）
    return 2, ["未知问题"], reason or "重试耗尽"


def process_item_agent(item, app_name, problem_col, df, refs, db_path,
                       agent_cfg, total, version_col=None):
    """单条问题 → agent 分类 → 入库。返回 [(num, status)]。
    状态码：0=成功, 1=未知问题, 2=失败。
    """
    num = item["num"]
    desc = item["desc"]
    if not desc.strip():
        status, classification, reason = 2, ["未知问题"], "空描述,跳过分类"
    else:
        status, classification, reason = classify_one(num, desc, refs, agent_cfg)
    func_to_business = refs.get("func_to_business", {}) if refs else {}
    business = derive_business_classification(classification, status, func_to_business)
    save_item(num, classification, reason, app_name, problem_col, df, db_path, status, version_col, business)
    incr_progress(1, total, str(num))
    return [(num, status)]
