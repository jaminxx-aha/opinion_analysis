#!/usr/bin/env python3
"""processor.py - Phase 2 数据准备 + Phase 3 执行分派

依赖图（无循环）：
  processor → classify_batch / classify_layered / classify_agent（顶部直接 import）
  各策略 → db_utils / runtime / args / claude_agent_client（叶子，不反向 import processor）
运行时状态与 LLM 调用已抽到 runtime.py，故 processor 可在顶部直接 import 策略模块。
"""

import sqlite3
import concurrent.futures
import logging

import pandas as pd

from args import setup_logging, MAX_DESC_LENGTH
from db_utils import save_item, clean_desc, init_db, set_table, init_output_dir
from runtime import set_output_dir
from classify_batch import process_batch
from classify_layered import process_item_layered
from classify_agent import process_item_agent

logger = logging.getLogger("classify_data")


# ========== Phase 2：数据准备 ==========

def prepare_data(args, config, refs, df, problem_col, version_col, db_path, table):
    """初始化输出目录/日志/DB，按 retry/续跑 选型构建待处理列表，过长项直接入库。

    返回 (all_data, ctx)：
      all_data: [{num, desc}] 待送 LLM 的条目（过长已分离入库）
      ctx: dict，含 total_all / max_id / too_long / mode_label，供 main 期末汇总
    """
    app_name = args.app_name
    output_dir = args.output_dir

    init_output_dir(args.excel_path, output_dir)
    setup_logging(output_dir)
    init_db(db_path, args.domain)
    set_table(table)
    set_output_dir(output_dir)

    filtered = list(range(len(df)))
    logger.info("总行数: %d (无应用名列筛选)", len(df))

    conn = sqlite3.connect(db_path)
    if args.retry:
        # 重试模式: 找出指定状态及缺失的行
        existing = dict(conn.execute(f"SELECT id, status FROM {table}").fetchall())
        retry_ids = set()
        missing_count = 0
        failed_count = 0
        unknown_count = 0
        for i in filtered:
            row_id = i + 1
            if row_id not in existing:
                retry_ids.add(row_id)
                missing_count += 1
            elif args.retry == "failed" and existing[row_id] == 2:
                retry_ids.add(row_id)
                failed_count += 1
            elif args.retry == "unknown" and existing[row_id] == 1:
                retry_ids.add(row_id)
                unknown_count += 1
        conn.close()

        all_data = [{"num": i + 1, "desc": clean_desc(str(df.iloc[i][problem_col])) if not pd.isna(df.iloc[i][problem_col]) else ""}
                    for i in filtered if (i + 1) in retry_ids]

        logger.info("重试模式(%s): 失败%d条, 未知%d条, 缺失%d条, 共需重试%d条, 并发 %d (keys=%d, 每key=%d), 推理模式 %s, provider=%s, model=%s, temperature=%.1f",
                    args.retry, failed_count, unknown_count, missing_count, len(all_data), config.total_concurrent, len(config.api_keys), config.max_concurrent, config.reason_mode, config.provider, config.model, config.temperature)

        max_id = 0
        mode_label = f"重试-{args.retry}"
    else:
        # 续跑模式: 从最大id之后继续
        max_id = conn.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]
        conn.close()
        if max_id is None:
            max_id = 0

        all_data = [{"num": i + 1, "desc": clean_desc(str(df.iloc[i][problem_col])) if not pd.isna(df.iloc[i][problem_col]) else ""}
                    for i in filtered if (i + 1) > max_id]

        logger.info("共 %d条, 已完成 %d条, 待处理 %d条, 并发 %d (keys=%d, 每key=%d), 推理模式 %s, provider=%s, model=%s, temperature=%.1f",
                    len(filtered), max_id, len(all_data), config.total_concurrent, len(config.api_keys), config.max_concurrent, config.reason_mode, config.provider, config.model, config.temperature)

        mode_label = "续跑"

    total_all = len(filtered)

    # 描述过长(超过 MAX_DESC_LENGTH 字)的项直接入库status=3, 不送LLM
    too_long = 0
    too_long_items = [item for item in all_data if len(item["desc"]) > MAX_DESC_LENGTH]
    all_data = [item for item in all_data if len(item["desc"]) <= MAX_DESC_LENGTH]
    for item in too_long_items:
        desc_len = len(item["desc"])
        save_item(item["num"], ["描述过长"], f"清洗后描述长度{desc_len}超过{MAX_DESC_LENGTH}字限制, 跳过分类", app_name, problem_col, df, db_path, 3, version_col)
        too_long += 1
    if too_long_items:
        logger.info("描述过长跳过分类: %d条", len(too_long_items))

    if config.is_agent:
        logger.info("Agent provider: skill=%s, key数%d, 每key并发%d, 总并发%d",
                    config.agent_cfg["skill_name"], len(config.api_keys), config.max_concurrent, config.total_concurrent)
    else:
        logger.info("API key配置: %d个key, 每key最大并发%d, 总并发%d", len(config.api_keys), config.max_concurrent, config.total_concurrent)
    if len(config.api_keys) > 1:
        logger.info("key列表(前缀): %s", ", ".join(k[:8] + "..." for k in config.api_keys))

    ctx = {
        "total_all": total_all,
        "max_id": max_id,
        "too_long": too_long,
        "mode_label": mode_label,
    }
    return all_data, ctx


# ========== Phase 3：执行分派 ==========

def run(config, all_data, app_name, problem_col, df, refs, db_path, version_col, domain):
    """按 provider/reason_mode 分派单次推理调用，并发执行，返回 (success, unknown, failed)。"""
    if config.is_agent:
        run_fn = process_item_agent
        # agent skill 单条→单个JSON，一次性给出完整编码，每条问题一个任务
        tasks = all_data
    elif config.reason_mode == "layered":
        run_fn = process_item_layered
        # 逐层模式: 每条问题一个独立任务，忽略 batch_size
        tasks = all_data
    else:
        run_fn = process_batch
        # 批量模式: 按 batch_size 切批
        tasks = [all_data[i:i + config.batch_size] for i in range(0, len(all_data), config.batch_size)]

    def _invoke(task, idx):
        """按 provider 分派单次推理调用，返回 [(num, status)]。"""
        if config.is_agent:
            # 多 key 轮询：每个 task 用独立 cfg 副本注入对应 key，避免线程间共享可变状态
            if config.api_keys:
                cfg = dict(config.agent_cfg)
                cfg["api_key"] = config.api_keys[idx % len(config.api_keys)]
            else:
                cfg = config.agent_cfg
            return run_fn(task, app_name, problem_col, df, refs, db_path,
                          cfg, len(all_data), version_col, domain)
        assigned_key = config.api_keys[idx % len(config.api_keys)]
        return run_fn(task, app_name, problem_col, df, refs, db_path,
                      config.provider, assigned_key, config.base_url, config.model,
                      config.max_tokens, config.max_retries, config.timeout,
                      config.verify_ssl, config.disable_proxy, config.temperature,
                      len(all_data), version_col, domain)

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

    # 失败计数的单任务条数：batch 模式按 batch_size 计；agent/layered 每任务1条
    fail_unit = config.batch_size if (not config.is_agent and config.reason_mode == "batch") else 1

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
                    failed += fail_unit

    return success, unknown, failed
