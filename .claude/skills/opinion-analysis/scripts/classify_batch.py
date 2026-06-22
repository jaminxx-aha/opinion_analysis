#!/usr/bin/env python3
"""classify_batch.py - 批量（一次性）推导分类

把完整三级分类树 + 正常/错误示例一次性注入 prompt，LLM 一次返回整批所有层级的编码。
与 classify_layered.py 的逐层推导互为两种独立推理策略，由 classify_data.main() 按
LLM_REASON_MODE 分派调用。

共享逻辑（save_item / call_llm_sdk / extract_json / code_to_classification / 进度 /
输出目录）均在 classify_data 中实现，这里通过懒导入避免循环依赖。
"""

import os
import re
import time
import json

from classify_data import (
    save_item,
    call_llm_sdk,
    extract_json,
    code_to_classification,
    get_output_dir,
    incr_progress,
)

import logging
logger = logging.getLogger("classify_data")


def build_batch_prompt(app_name, items, refs, domain="function"):
    """构建批量分类prompt，items为[{num, desc}]列表

    domain: 分类域，function=功能域/性能问题，business=业务域
    """
    problems_text = "\n" + "\n".join([
        f"---PROBLEM_{i+1}---\n\n{item['desc']}\n\n---PROBLEM_{i+1}_END---\n"
        for i, item in enumerate(items)
    ])
    return f"""你是一位专业的{app_name}应用问题分类专家，请根据用户的问题描述（以---PROBLEMS---、---PROBLEMS_END---分隔，内部有{len(items)}个问题，每个问题以---PROBLEM_N---，---PROBLEM_N_END---分隔，每个问题可能属于多个分类，只要给出最相关即可），

结合应用描述（---APP---、---APP_END---分隔）、分类编码表（以---CLASSIFICATION---、---CLASSIFICATION_END---分隔）和分类推理示例（以---EXAMPLES---、---EXAMPLES_END---分隔），推导出最准确的分类编码。

---PROBLEMS---
{problems_text}
---PROBLEMS_END---

---APP---
{refs.get('info', '')}
---APP_END---

---CLASSIFICATION---
{refs.get('classification', '')}
---CLASSIFICATION_END---

---EXAMPLES---
{refs.get('examples', '')}
---EXAMPLES_END---

以下是一些错误的推理示例（以---ERROR_EXAMPLES---、---ERROR_EXAMPLES_END---分隔）
---ERROR_EXAMPLES---
{refs.get('error_examples', '')}
---ERROR_EXAMPLES_END---

推导规则：参照示例的推理方式，对照编码表逐层推导，返回分类编码；无法推导的层级截断编码（如无法推导二级则只返回一级编码如"1"，无法推导三级则只返回到二级编码如"1.1"）；不属于编码表问题的返回"0"。

必须返回{len(items)}个元素，禁止多加或遗漏，必须按照以下json格式返回，json格式被三个反引号分割
```
[{{"classification": "编码", "reason": "推理过程"}}]
```

【要求】
1.推理过程需要严格按照层级推理，即先分析出第一级，然后根据一级分类分析出第二级，再根据第二级分类分析出第三第三级分类
2.忽略卓易通相关的描述，只分析原生鸿蒙相关的问题
3.要根据现有的描述分析问题，若无法进一步得到更确切的分类则返回，不要去联想猜测
"""


def process_batch(batch, app_name, problem_col, df, refs, db_path,
                  provider, api_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, temperature, total, version_col=None, domain="function"):
    """处理一批问题，batch为[{num, desc}]列表"""
    results = []

    valid_items = [item for item in batch if item["desc"].strip()]

    nums = [it["num"] for it in batch]
    if len(nums) == 1:
        batch_label = str(nums[0])
        log_base = f"response_{nums[0]}"
    else:
        batch_label = ",".join(str(n) for n in nums)
        log_base = f"response_{'_'.join(str(n) for n in nums)}"

    output_dir = get_output_dir()

    def _log_file(attempt):
        suffix = f"_retry{attempt + 1}" if attempt > 0 else ""
        return os.path.join(output_dir, "log", f"{log_base}{suffix}.log") if output_dir else None

    if not valid_items:
        for item in batch:
            save_item(item["num"], ["其他问题"], "空描述,跳过分类", app_name, problem_col, df, db_path, 2, version_col)
            results.append((item["num"], False))
        incr_progress(len(batch), total, batch_label)
        return results

    try:
        prompt = build_batch_prompt(app_name, valid_items, refs, domain)
        row_nums = ",".join(str(it["num"]) for it in valid_items)
        logger.debug("批量开始LLM推理, 行号[%s], 有效问题数: %d", row_nums, len(valid_items))

        for attempt in range(max_retries):
            try:
                logger.info("LLM请求发送, 第%d/%d次", attempt + 1, max_retries)
                text = call_llm_sdk(prompt, provider, api_key, base_url, model, max_tokens, timeout, verify_ssl, disable_proxy, temperature=temperature, log_file=_log_file(attempt))
                logger.info("批量LLM推理返回, 文本长度: %d", len(text) if text else 0)
            except Exception as e:
                logger.warning("LLM调用失败(第%d/%d次): %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for item in valid_items:
                        save_item(item["num"], ["其他问题"], f"API调用失败: {e}", app_name, problem_col, df, db_path, 2, version_col)
                        results.append((item["num"], 2))
                    break

            parsed = extract_json(text)
            if not parsed or not isinstance(parsed, list):
                logger.warning("JSON解析失败(第%d/%d次), 原始返回: %s", attempt + 1, max_retries, text[:300] if text else "空")
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for item in valid_items:
                        save_item(item["num"], ["其他问题"], "JSON解析失败", app_name, problem_col, df, db_path, 2, version_col)
                        results.append((item["num"], 2))
                    break

            if len(parsed) != len(valid_items):
                logger.warning("结果数量不一致(第%d/%d次): 期望%d条, 返回%d条", attempt + 1, max_retries, len(valid_items), len(parsed))
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for item in valid_items:
                        save_item(item["num"], ["其他问题"], f"结果数量不一致: 期望{len(valid_items)}条, 返回{len(parsed)}条", app_name, problem_col, df, db_path, 2, version_col)
                        results.append((item["num"], 2))
                    break

            # 格式检查: classification应为字符串编码
            code_to_path = refs.get("classification_tree", {})
            format_errors = False
            for p in parsed:
                if not isinstance(p, dict):
                    continue
                cls = p.get("classification", "0")
                if not isinstance(cls, str):
                    format_errors = True
                    break

            if format_errors:
                logger.warning("分类格式错误(第%d/%d次): classification应为字符串编码", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for i, item in enumerate(valid_items):
                        num = item["num"]
                        p = parsed[i]
                        code = p.get("classification", "0") if isinstance(p, dict) else "0"
                        reason = p.get("reason", "") if isinstance(p, dict) else ""
                        classification = code_to_classification(code, code_to_path)
                        if not isinstance(code, str):
                            save_item(num, ["其他问题"], "分类格式错误: classification应为字符串编码", app_name, problem_col, df, db_path, 2, version_col)
                            results.append((num, 2))
                        elif code == "0":
                            save_item(num, classification, reason, app_name, problem_col, df, db_path, 1, version_col)
                            results.append((num, 1))
                        else:
                            save_item(num, classification, reason, app_name, problem_col, df, db_path, 0, version_col)
                            results.append((num, 0))
                        logger.info("行%d 批量推理成功, 编码: %s, 分类: %s", num, code, ".".join(classification))
                    break

            # 分类编码校验: 检查每个编码是否存在于编码→路径字典中
            invalid_codes = []
            for i, p in enumerate(parsed):
                if not isinstance(p, dict):
                    invalid_codes.append((i, "not a dict"))
                    continue
                code = p.get("classification", "0")
                if not isinstance(code, str):
                    continue  # 已在format_errors中处理
                # 容错: 提取编码部分(如"1.1 滑动卡顿" → "1.1")
                code_clean = re.match(r'^(\d+(?:\.\d+)*)', str(code).strip())
                code_str = code_clean.group(1) if code_clean else str(code).strip()
                if code_str != "0" and code_str not in code_to_path:
                    invalid_codes.append((i, code_str))

            if invalid_codes:
                for idx, invalid_code in invalid_codes:
                    logger.warning("分类编码无效(第%d/%d次), 项目%d: '%s' 不存在于编码表", attempt + 1, max_retries, idx + 1, invalid_code)
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue  # 重试整个批次
                else:
                    # 最后一次重试仍无效, 按条保存
                    for i, item in enumerate(valid_items):
                        num = item["num"]
                        p = parsed[i]
                        code = p.get("classification", "0") if isinstance(p, dict) else "0"
                        reason = p.get("reason", "") if isinstance(p, dict) else ""
                        classification = code_to_classification(code, code_to_path)
                        if not isinstance(code, str):
                            save_item(num, ["其他问题"], "分类格式错误", app_name, problem_col, df, db_path, 2, version_col)
                            results.append((num, 2))
                        elif code == "0":
                            save_item(num, classification, reason, app_name, problem_col, df, db_path, 1, version_col)
                            results.append((num, 1))
                        elif classification[0] == "其他问题":
                            # 编码不在字典中, 转换后为其他问题
                            invalid_reason = f"分类编码无效: {code} 不存在于编码表"
                            save_item(num, ["其他问题"], invalid_reason, app_name, problem_col, df, db_path, 2, version_col)
                            results.append((num, 2))
                        else:
                            save_item(num, classification, reason, app_name, problem_col, df, db_path, 0, version_col)
                            results.append((num, 0))
                    break

            for i, item in enumerate(valid_items):
                num = item["num"]
                p = parsed[i]
                code = p.get("classification", "0")
                reason = p.get("reason", "")
                classification = code_to_classification(code, code_to_path)
                if code == "0":
                    save_item(num, classification, reason, app_name, problem_col, df, db_path, 1, version_col)
                    results.append((num, 1))
                else:
                    save_item(num, classification, reason, app_name, problem_col, df, db_path, 0, version_col)
                    results.append((num, 0))
                logger.info("行%d 批量推理成功, 编码: %s, 分类: %s", num, code, ".".join(classification))
            break

    except Exception as e:
        logger.error("批量LLM推理失败: %s", e)
        for item in valid_items:
            save_item(item["num"], ["其他问题"], f"API调用失败: {e}", app_name, problem_col, df, db_path, 2, version_col)
            results.append((item["num"], 2))

    for item in batch:
        if not item["desc"].strip():
            save_item(item["num"], ["其他问题"], "空描述,跳过分类", app_name, problem_col, df, db_path, 2, version_col)
            results.append((item["num"], 2))

    incr_progress(len(batch), total, batch_label)
    return results
