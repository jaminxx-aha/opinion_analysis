#!/usr/bin/env python3
"""processor.py - Phase 2 数据准备 + Phase 3 执行分派（仅 Claude Agent SDK 路径）

依赖图（无循环）：
  processor → classify_agent → db_utils / runtime / claude_agent_client（叶子，不反向 import processor）
运行时状态（输出目录/进度）与响应解析在 runtime.py。
"""

import sys
import os
import sqlite3
import concurrent.futures
import logging

import pandas as pd

from args import setup_logging, MAX_DESC_LENGTH, load_reference
from db_utils import save_item, clean_desc, init_db, set_table, init_output_dir, report_table, count_rows
from runtime import set_output_dir
from classify_agent import process_item_agent

logger = logging.getLogger("classify_data")


# ========== Phase 2：数据准备 ==========

def prepare_data(args, config, df, problem_col, version_col):
    """加载分类参考库，初始化输出目录/日志/DB，按续跑模式构建待处理列表，过长项直接入库。

    续跑：从该表最大 id 之后继续处理新行（断点续跑，非重试）。
    重试失败数据(status=2)请用 scripts/retry_failed.py。

    返回 (all_data, ctx, refs)：
      all_data: [{num, desc}] 待送 agent 的条目（过长已分离入库）
      ctx: dict，含 total_all / max_id / too_long / mode_label / db_path / table，供 main 期末汇总与 run
      refs: 分类参考库（classification_tree 用于结果校验）
    """
    app_name = args.app_name
    output_dir = args.output_dir

    # 加载分类树（agent 返回结果校验用）+ 功能→业务映射（派生 business_classification 用）
    refs = load_reference(app_name)
    if not refs:
        logger.error("无法加载 '%s' 的知识库", app_name); sys.exit(1)
    if not refs.get("classification"):
        logger.error("无法加载 '%s' 的分类知识库(classification文件缺失)", app_name); sys.exit(1)

    db_path = os.path.join(output_dir, "report.db")
    table = report_table()
    init_output_dir(args.excel_path, output_dir)
    setup_logging(output_dir)
    init_db(db_path)
    set_table(table)
    set_output_dir(output_dir)

    filtered = list(range(len(df)))
    logger.info("总行数: %d (无应用名列筛选)", len(df))

    # 续跑模式: 从最大id之后继续
    conn = sqlite3.connect(db_path)
    max_id = conn.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]
    conn.close()
    if max_id is None:
        max_id = 0

    all_data = [{"num": i + 1, "desc": clean_desc(str(df.iloc[i][problem_col])) if not pd.isna(df.iloc[i][problem_col]) else ""}
                for i in filtered if (i + 1) > max_id]

    logger.info("共 %d条, 已完成 %d条, 待处理 %d条, 并发 %d (keys=%d, 每key=%d), skill=%s, model=%s",
                len(filtered), max_id, len(all_data), config.total_concurrent, len(config.api_keys), config.max_concurrent, config.agent_cfg["skill_name"], config.agent_cfg.get("model") or "default")

    mode_label = "续跑"

    total_all = len(filtered)

    # 描述过长(超过 MAX_DESC_LENGTH 字)的项直接入库status=3, 不送 agent
    too_long = 0
    too_long_items = [item for item in all_data if len(item["desc"]) > MAX_DESC_LENGTH]
    all_data = [item for item in all_data if len(item["desc"]) <= MAX_DESC_LENGTH]
    for item in too_long_items:
        desc_len = len(item["desc"])
        save_item(item["num"], ["描述过长"], f"清洗后描述长度{desc_len}超过{MAX_DESC_LENGTH}字限制, 跳过分类", app_name, problem_col, df, db_path, 3, version_col)
        too_long += 1
    if too_long_items:
        logger.info("描述过长跳过分类: %d条", len(too_long_items))

    logger.info("Agent: skill=%s, key数%d, 每key并发%d, 总并发%d",
                config.agent_cfg["skill_name"], len(config.api_keys), config.max_concurrent, config.total_concurrent)
    if len(config.api_keys) > 1:
        logger.info("key列表(前缀): %s", ", ".join(k[:8] + "..." for k in config.api_keys))

    ctx = {
        "total_all": total_all,
        "max_id": max_id,
        "too_long": too_long,
        "mode_label": mode_label,
        "db_path": db_path,
        "table": table,
    }
    return all_data, ctx, refs


# ========== Phase 3：执行分派 ==========

def run(config, all_data, app_name, problem_col, df, refs, ctx, version_col):
    """并发执行 agent 分类，每条问题一次 agent 调用，结束后打印期末汇总。

    ctx 须含 db_path / table / total_all / max_id / too_long / mode_label。
    """
    db_path = ctx["db_path"]
    run_fn = process_item_agent
    # agent skill 单条→单个JSON，一次性给出完整编码，每条问题一个任务
    tasks = all_data

    def _invoke(task, idx):
        """分派单次 agent 调用，返回 [(num, status)]。"""
        # 多 key 轮询：每个 task 用独立 cfg 副本注入对应 key，避免线程间共享可变状态
        if config.api_keys:
            cfg = dict(config.agent_cfg)
            cfg["api_key"] = config.api_keys[idx % len(config.api_keys)]
        else:
            cfg = config.agent_cfg
        return run_fn(task, app_name, problem_col, df, refs, db_path,
                      cfg, len(all_data), version_col)

    success = 0
    unknown = 0
    failed = 0

    def _accumulate(st):
        nonlocal success, unknown, failed
        if st == 0:
            success += 1
        elif st == 1:
            unknown += 1
        else:
            failed += 1

    if config.total_concurrent == 1:
        for i, task in enumerate(tasks):
            task_results = _invoke(task, i)
            for _, st in task_results:
                _accumulate(st)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.total_concurrent) as executor:
            futures = {}
            for i, task in enumerate(tasks):
                futures[executor.submit(_invoke, task, i)] = i
            for f in concurrent.futures.as_completed(futures):
                try:
                    task_results = f.result()
                    for _, st in task_results:
                        _accumulate(st)
                except Exception:
                    failed += 1

    # 期末汇总
    cnt = count_rows(ctx["db_path"], ctx["table"])
    total_all = ctx["total_all"]
    db_status = "验证通过" if cnt == total_all else f"警告: DB {cnt}条, 期望 {total_all}条"
    processed = (ctx["max_id"] if ctx["mode_label"] == "续跑" else 0) + success + unknown + failed + ctx["too_long"]
    logger.info("分类完成(%s): %d/%d条 (成功%d, 未知%d, 失败%d, 过长%d) | %s",
                ctx["mode_label"], processed, total_all, success, unknown, failed, ctx["too_long"], db_status)
    print(f"分类完成({ctx['mode_label']}): {processed}/{total_all}条 (成功{success}, 未知{unknown}, 失败{failed}, 过长{ctx['too_long']}) | {db_status}")
