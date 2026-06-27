#!/usr/bin/env python3
"""classify_layered.py - 逐层推导分类（层级无关 + 编号驱动）

与 classify_batch.py 的"一次性整批推导"不同：本模块按 一级→二级→三级 串行推导，
但**每次给 LLM 的 prompt 不暴露当前层级**——模板统一，只给一份带编号的候选分类名单
（无树编码、不说层级），让 LLM 返回一个编号。

- 每层候选都从 1 开始编号（1..N），末行「0 未知问题」；二/三层也各自从 1 开始。
- LLM 每层返回一个编号；0 表示未知问题，任一层返回 0 即终止下钻。
- 各层编号拼接成结果编码（因分类树每层子级从 1 连续，拼接编号 == 树编码，如 1.2.3）。
- 用该编码在 classification_tree（编码→名称路径）中查名称，名称入库（与批量模式一致）。
- 入库时「未知问题」只第一层有效：L1 返回 0 → 整条记为「未知问题」(status=1)；
  L2/L3 返回 0 → 停止、保留已确定的上级名称路径，「未知问题」不写入 DB(status=0)。

每条问题最多发起 3 次 LLM 调用（每层一次），故 LLM_BATCH_SIZE 在本模式下不生效。

共享逻辑（save_item / call_llm_sdk / extract_json / 进度 / 输出目录）均在 classify_data
中实现，这里通过懒导入避免循环依赖。
"""

import os
import re
import time

from classify_data import (
    save_item,
    call_llm_sdk,
    extract_json,
    get_output_dir,
    incr_progress,
)

import logging
logger = logging.getLogger("classify_data")

OTHER_NUM = 0  # 各层候选名单中「未知问题」的固定编号


def children_codes(code_to_path, parent_code):
    """返回 parent_code 的直接子级 [(code, name), ...]，按编码排序。

    parent_code 为 "" 时返回全部一级类目（路径长度=1）。
    parent_code 自身不在结果中。
    """
    if parent_code:
        prefix = parent_code + "."
        parent_depth = len(parent_code.split("."))
        target_depth = parent_depth + 1
    else:
        prefix = ""
        target_depth = 1

    children = []
    for code, path in code_to_path.items():
        if code == "0":
            continue
        if prefix and not code.startswith(prefix):
            continue
        if len(code.split(".")) != target_depth:
            continue
        children.append((code, path[-1]))
    children.sort(key=lambda x: [int(p) for p in x[0].split(".")])
    return children


_CN_LEVEL = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def parse_layered_examples(md):
    """切分为 {level: str_or_dict}。

    - 一级段（## 一级）为单个表格文本；
    - 二级及以上段（## 二级 / ## 三级 / ## 四级 ...）按 `### 父级名` 子标题切成
      {父级名: 表格文本}，调用时只注入当前父级对应的那一段，不混入其它父级用例。
    支持任意深度（随分类树层级加深自动适配）。
    """
    result = {}  # {1: str, level>=2: {parent: str}}
    if not md:
        return result
    level = None       # 当前层级
    parent = None     # L2+ 子段父级名
    buf = []

    def flush():
        nonlocal buf
        text = "\n".join(buf).strip()
        buf = []
        if level is None or not text:
            return
        if level == 1:
            result[1] = text if not result.get(1) else result[1] + "\n" + text
        elif parent is not None:
            result.setdefault(level, {})[parent] = text

    for line in md.split("\n"):
        s = line.strip()
        m2 = re.match(r'^##\s*([一二三四五六七八九十]+)级', s)
        if m2:
            flush()
            level = _CN_LEVEL[m2.group(1)]
            parent = None
            continue
        m3 = re.match(r'^###\s*(.+?)\s*$', s)
        if m3 and level is not None and level >= 2:
            flush()
            parent = m3.group(1)
            continue
        buf.append(line)
    flush()
    return result


def _find_code_by_name(code_to_path, name):
    """在分类树中按名称反查编码（取路径末段等于 name 的第一个）。"""
    if not name:
        return None
    for code, path in code_to_path.items():
        if path and path[-1] == name:
            return code
    return None


def _to_int(raw):
    """把 LLM 返回的 classification 解析为单个整数编号。非纯整数（如"1.2.3"、"卡顿"）返回 None。"""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        m = re.match(r'^\s*(-?\d+)\s*$', raw)
        if m:
            return int(m.group(1))
    return None


def _layer_level_label(domain):
    return "业务模块" if domain == "business" else "性能问题"


def build_layer_prompt(app_name, desc, refs, domain, level, parent_name):
    """构建层级无关的单层推导 prompt（不出现"一级/二级/三级"字样，候选给编号+名称）。

    level: 当前层级（1,2,3,...），仅用于取对应层用例段；prompt 文本不提及层级。
    parent_name: 上一层选中的名称（level=1 时为 None）。
    """
    code_to_path = refs.get("classification_tree", {})
    layered_examples = parse_layered_examples(refs.get("examples_layered", ""))
    layered_error_examples = parse_layered_examples(refs.get("error_examples_layered", ""))

    # 当前层候选类目（父级的直接子级），按编码顺序从 1 编号
    if level == 1:
        children = children_codes(code_to_path, "")
        parent_ctx = ""
    else:
        parent_code = _find_code_by_name(code_to_path, parent_name)
        children = children_codes(code_to_path, parent_code) if parent_code else []
        parent_ctx = f"\n已确定该问题属于「{parent_name}」。请从下列候选分类中选择最匹配的一个。\n"

    # 候选名单：首行「0 未知问题」，随后每行「编号 名称」按编码从 1 编号。编号每层从 1 开始。
    cat_lines = "\n".join([f"{OTHER_NUM} 未知问题"] + [f"{i + 1} {name}" for i, (_, name) in enumerate(children)])

    examples = layered_examples.get(level, "")
    err_examples = layered_error_examples.get(level, "")
    # level>=2：layered_examples[level] 是 {父级名: 表格文本}，只取当前父级对应的那段；
    # level==1：layered_examples[1] 是单个表格文本，直接用。深层无对应段时返回空串。
    if level >= 2:
        examples = examples.get(parent_name, "") if isinstance(examples, dict) else ""
        err_examples = err_examples.get(parent_name, "") if isinstance(err_examples, dict) else ""
    domain_label = _layer_level_label(domain)

    return f"""你是一位专业的{app_name}应用{domain_label}分类专家，请根据用户的问题描述（以---PROBLEM---、---PROBLEM_END---分隔，问题可能属于多个分类，只要给出最相关即可），

结合应用描述（---APP---、---APP_END---分隔）、候选分类（以---CATEGORIES---、---CATEGORIES_END---分隔）和分类推理示例（以---EXAMPLES---、---EXAMPLES_END---分隔），从候选分类中选择最匹配的一个。

---PROBLEM---
{desc}
---PROBLEM_END---
{parent_ctx}
---APP---
{refs.get('info', '')}
---APP_END---

---CATEGORIES---
{cat_lines}
---CATEGORIES_END---

---EXAMPLES---
{examples}
---EXAMPLES_END---

以下是一些错误的推理示例（以---ERROR_EXAMPLES---、---ERROR_EXAMPLES_END---分隔）
---ERROR_EXAMPLES---
{err_examples}
---ERROR_EXAMPLES_END---

推导规则：
1. 只能从上方候选分类的编号中选择一个。
2. 忽略卓易通相关的描述，只分析原生鸿蒙相关的问题。
3. 要根据现有描述分析，不要联想猜测。
4. 推理过程只描述问题描述与分类的语义关联，不要在推理中提及候选编号或分类编码。

必须按照以下json格式返回单个对象（不要返回数组），json格式被三个反引号分割
```
{{"classification": "编号", "reason": "本层推理过程"}}
```
"""


def _call_layer(item, level, children, parent_name, app_name, refs, domain,
                provider, api_key, base_url, model, max_tokens, max_retries,
                timeout, verify_ssl, disable_proxy, temperature):
    """发起某一层的 LLM 调用（含重试），编号驱动。

    返回 (num, reason, ok):
      ok=True  → num 为 0（未知问题）或 1..N（某候选编号）
      ok=False → 重试耗尽仍无法得到有效编号
    """
    desc = item["desc"]
    num_row = item["num"]
    output_dir = get_output_dir()
    log_base = f"response_{num_row}_L{level}"

    n_candidates = len(children)
    # 合法编号：0(未知问题) .. n_candidates
    valid_nums = set(range(0, n_candidates + 1))

    prompt = build_layer_prompt(app_name, desc, refs, domain, level, parent_name)

    for attempt in range(max_retries):
        suffix = f"_retry{attempt + 1}" if attempt > 0 else ""
        log_file = os.path.join(output_dir, "log", f"{log_base}{suffix}.log") if output_dir else None
        try:
            logger.info("行%d 第%d层LLM请求, 第%d/%d次", num_row, level, attempt + 1, max_retries)
            text = call_llm_sdk(prompt, provider, api_key, base_url, model, max_tokens, timeout, verify_ssl, disable_proxy, temperature=temperature, log_file=log_file)
        except Exception as e:
            logger.warning("行%d 第%d层LLM调用失败(第%d/%d次): %s", num_row, level, attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return None, f"API调用失败: {e}", False

        parsed = extract_json(text)
        if not isinstance(parsed, dict):
            logger.warning("行%d 第%d层JSON解析失败(第%d/%d次), 原始: %s", num_row, level, attempt + 1, max_retries, (text or "")[:300])
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return None, "JSON解析失败", False

        raw = parsed.get("classification", "")
        reason = parsed.get("reason", "") or ""
        num = _to_int(raw)
        if num is None or num not in valid_nums:
            logger.warning("行%d 第%d层编号无效(第%d/%d次): '%s' 不在候选编号范围(0..%d)", num_row, level, attempt + 1, max_retries, raw, n_candidates)
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return None, f"分类编号无效: {raw}", False

        return num, reason, True

    return None, "重试耗尽", False


def process_item_layered(item, app_name, problem_col, df, refs, db_path,
                          provider, api_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, temperature, total, version_col=None, domain="function"):
    """逐层串行推导单条问题，循环下钻至无子级或选「未知问题」为止，支持任意深度。

    每层 LLM 返回编号；编号拼接成树编码，用 classification_tree 查名称路径入库。
    - L1 选 0(未知问题) → 整条记为未知问题(status=1)；
    - 任意更深层选 0 或推导失败 → 止于上级、「未知问题」不写入(status=0)；
    - 选到无子级的叶节点 → 到末级(status=0)。
    """
    num = item["num"]
    code_to_path = refs.get("classification_tree", {})

    if not item["desc"].strip():
        save_item(num, ["未知问题"], "空描述,跳过分类", app_name, problem_col, df, db_path, 2, version_col)
        incr_progress(1, total, str(num))
        return [(num, 2)]

    code = None            # 已确定的当前编码（None = 尚未过 L1）
    parent_name = None     # code 对应的名称（下一层候选的父级）
    children = children_codes(code_to_path, "")  # L1 候选
    reasons = []
    level = 1

    while True:
        n, reason, ok = _call_layer(item, level, children, parent_name, app_name, refs, domain,
                                    provider, api_key, base_url, model, max_tokens, max_retries,
                                    timeout, verify_ssl, disable_proxy, temperature)
        if not ok:
            # 本层推导失败
            reasons.append(f"第{level}级推导失败: {reason}")
            if code is None:
                # L1 失败 → 无任何分类
                save_item(num, ["未知问题"], reasons[-1], app_name, problem_col, df, db_path, 2, version_col)
                logger.info("行%d 一级推导失败 → 失败(status=2)", num)
            else:
                # 更深层失败 → 止于上级
                save_item(num, code_to_path.get(code, []), " | ".join(reasons), app_name, problem_col, df, db_path, 0, version_col)
                logger.info("行%d 逐层推导完成, 编码: %s (第%d级推导失败, 止于上级)", num, code, level)
            incr_progress(1, total, str(num))
            return [(num, 2 if code is None else 0)]

        if n == OTHER_NUM:
            # 本层选「未知问题」
            reasons.append(reason)
            if code is None:
                # 仅 L1 有效 → 整条未知问题
                save_item(num, ["未知问题"], " | ".join(reasons), app_name, problem_col, df, db_path, 1, version_col)
                logger.info("行%d 逐层推导完成, 一层判未知问题(0) → 未知问题", num)
                incr_progress(1, total, str(num))
                return [(num, 1)]
            # 更深层未知问题 → 止于上级，「未知问题」不写入
            save_item(num, code_to_path.get(code, []), " | ".join(reasons), app_name, problem_col, df, db_path, 0, version_col)
            logger.info("行%d 逐层推导完成, 编码: %s (第%d级判未知问题, 止于上级)", num, code, level)
            incr_progress(1, total, str(num))
            return [(num, 0)]

        # 本层选中一个候选，下钻
        reasons.append(reason)
        code = children[n - 1][0]
        parent_name = children[n - 1][1]
        children = children_codes(code_to_path, code)
        if not children:
            # 已到叶节点
            save_item(num, code_to_path.get(code, []), " | ".join(reasons), app_name, problem_col, df, db_path, 0, version_col)
            logger.info("行%d 逐层推导完成, 编码: %s (到末级, 第%d级)", num, code, level)
            incr_progress(1, total, str(num))
            return [(num, 0)]
        level += 1

