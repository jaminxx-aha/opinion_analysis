#!/usr/bin/env python3
"""processor.py - Phase 2 数据准备 + Phase 3 执行分派（agent 后端路径）

依赖图（无循环）：
  processor → classify_agent → db_utils / runtime / agent_client（叶子，不反向 import processor）
运行时状态（输出目录/进度）与响应解析在 runtime.py。
"""

import sys
import os
import concurrent.futures
import logging

import pandas as pd

from args import setup_logging, load_reference
from db_utils import init_db, set_table, init_output_dir, report_table, count_rows
from runtime import set_output_dir
from classify_agent import process_item_agent

logger = logging.getLogger("classify_data")


# ========== Phase 2：数据准备 ==========

def prepare_data(args, config, df, problem_col):
    """加载分类参考库，初始化输出目录/日志/DB，构建待处理列表。

    续跑/重试改用「逐条查 DB 判断存在性」（在 process_item_agent 内做），不再取 MAX(id)
    批量过滤——避免并发中断产生的 id 空洞被永久跳过。
      - 续跑(默认)：DB 已存在的行跳过，缺失的行分析。
      - 重试(--retry-failed)：DB 中 status=2(失败)及缺失的行重新分析，其余跳过。
    不在此预清洗/预判过长：取原始描述，清洗与过长判定下沉到 process_item_agent
    按处理顺序逐条做（过长行在其前面行处理完后才判定，不再一开始统一入库）。

    返回 (all_data, ctx, refs)：
      all_data: [{num, desc(原始)}] 全量待处理条目（跳过与否由 process_item_agent 按条判断）
      ctx: dict，含 total_all / done / retry_failed / mode_label / db_path / table
      refs: 分类参考库（classification_tree 用于结果校验）
    """
    app_name = args.app_name
    output_dir = args.output_dir
    retry_failed = bool(getattr(args, "retry_failed", False))

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
    total_all = len(filtered)
    done = count_rows(db_path, table)  # DB 当前已落库行数（= 已完成，含成功/未知/失败/过长）
    logger.info("总行数: %d, DB 已完成 %d条 (无应用名列筛选)", total_all, done)

    # 全量条目（原始描述），不在本阶段预清洗/预判过长/预过滤；跳过与否由 process_item_agent 按条查 DB 判断
    all_data = [{"num": i + 1, "desc": str(df.iloc[i][problem_col]) if not pd.isna(df.iloc[i][problem_col]) else ""}
                for i in filtered]

    mode_label = "重试失败" if retry_failed else "续跑"
    logger.info("模式: %s, 共 %d条, 并发 %d (keys=%d, 每key=%d), skill=%s, model=%s",
                mode_label, total_all, config.total_concurrent, len(config.api_keys), config.max_concurrent,
                config.agent_cfg["skill_name"], config.agent_cfg.get("model") or "default")
    logger.info("Agent: skill=%s, key数%d, 每key并发%d, 总并发%d",
                config.agent_cfg["skill_name"], len(config.api_keys), config.max_concurrent, config.total_concurrent)
    if len(config.api_keys) > 1:
        logger.info("key列表(前缀): %s", ", ".join(k[:8] + "..." for k in config.api_keys))

    ctx = {
        "total_all": total_all,
        "done": done,
        "retry_failed": retry_failed,
        "mode_label": mode_label,
        "db_path": db_path,
        "table": table,
    }
    return all_data, ctx, refs


# ========== Phase 3：执行分派 ==========

def run(config, all_data, app_name, problem_col, df, refs, ctx, version_col):
    """并发执行 agent 分类，每条问题一次 agent 调用，结束后打印期末汇总。

    ctx 须含 db_path / table / total_all / retry_failed / mode_label。
    每条处理前由 process_item_agent 查 DB 判断是否跳过（续跑跳过已存在；重试只重做 status=2 及缺失）。
    """
    db_path = ctx["db_path"]
    retry_failed = ctx.get("retry_failed", False)
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
                      cfg, len(all_data), version_col, retry_failed)

    success = 0
    unknown = 0
    failed = 0
    too_long = 0
    skipped_cnt = 0

    def _accumulate(st, skipped):
        nonlocal success, unknown, failed, too_long, skipped_cnt
        if st == 0:
            success += 1
        elif st == 1:
            unknown += 1
        elif st == 3:
            too_long += 1
        else:
            failed += 1
        if skipped:
            skipped_cnt += 1

    if config.total_concurrent == 1:
        for i, task in enumerate(tasks):
            task_results = _invoke(task, i)
            for _, st, sk in task_results:
                _accumulate(st, sk)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.total_concurrent) as executor:
            futures = {}
            for i, task in enumerate(tasks):
                futures[executor.submit(_invoke, task, i)] = i
            for f in concurrent.futures.as_completed(futures):
                try:
                    task_results = f.result()
                    for _, st, sk in task_results:
                        _accumulate(st, sk)
                except Exception:
                    failed += 1

    # 期末汇总
    cnt = count_rows(ctx["db_path"], ctx["table"])
    total_all = ctx["total_all"]
    db_status = "验证通过" if cnt == total_all else f"警告: DB {cnt}条, 期望 {total_all}条"
    analyzed = success + unknown + failed + too_long - skipped_cnt
    logger.info("分类完成(%s): DB %d/%d条 (成功%d, 未知%d, 失败%d, 过长%d) | 跳过%d 实跑%d | %s",
                ctx["mode_label"], cnt, total_all, success, unknown, failed, too_long, skipped_cnt, analyzed, db_status)
    print(f"分类完成({ctx['mode_label']}): DB {cnt}/{total_all}条 (成功{success}, 未知{unknown}, 失败{failed}, 过长{too_long}) | 跳过{skipped_cnt} 实跑{analyzed} | {db_status}")
