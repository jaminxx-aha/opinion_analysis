#!/usr/bin/env python3
"""retry_failed.py - 对某输出目录 DB 中 status=2(推理失败) 的数据重跑 agent 分类

用法:
  python retry_failed.py <output_dir> [--domain function|business] [--app-name 抖音]

- 只需给一个输出目录，自行读取其中的 report.db（不需要 Excel）
- 只重试 status=2 的失败行（不含未知问题 status=1、不含缺失行）
- app_name 未指定时从 DB 的 app 列推断
- 重试走与 classify_data 相同的 agent 路径（含 json_repair 修复 + 分类树纠偏 + 重试）
- 完成后重新生成报告
"""

import sys
import os
import io
import argparse
import sqlite3
import logging
import concurrent.futures

from args import load_config, load_reference, setup_logging, derive_business_classification
from db_utils import report_table, set_table, init_db, count_rows, update_item, _close_all_db
from runtime import set_output_dir, incr_progress
from classify_agent import classify_one
from generate_report import generate_report

# Windows 下强制 UTF-8 输出
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "buffer") and (
            not isinstance(stream, io.TextIOWrapper) or stream.encoding.lower() != "utf-8"
        ):
            stream.reconfigure(encoding="utf-8") if hasattr(stream, "reconfigure") else None

logger = logging.getLogger("classify_data")
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger.addHandler(_handler)


def main():
    ap = argparse.ArgumentParser(description="重试 DB 中推理失败(status=2)的数据")
    ap.add_argument("output_dir", help="输出目录（含 report.db）")
    ap.add_argument("--app-name", default=None, help="应用名（不指定则从 DB 推断）")
    args = ap.parse_args()

    output_dir = os.path.abspath(args.output_dir)
    db_path = os.path.join(output_dir, "report.db")
    if not os.path.isfile(db_path):
        print(f"错误: 未找到 {db_path}")
        sys.exit(1)
    table = report_table()

    # 输出目录/日志/DB/表 初始化（与 classify_data 的 prepare_data 对齐）
    os.makedirs(os.path.join(output_dir, "log"), exist_ok=True)
    setup_logging(output_dir)
    set_output_dir(output_dir)
    set_table(table)
    init_db(db_path)  # 幂等，确保 full_path/business_classification/version 列存在

    # app_name：未指定则从 DB 推断
    app_name = args.app_name
    if not app_name:
        conn = sqlite3.connect(db_path)
        row = conn.execute(f"SELECT app FROM {table} WHERE app IS NOT NULL AND app != '' LIMIT 1").fetchone()
        conn.close()
        if not row:
            print(f"错误: {table} 表无 app 数据，无法推断应用名，请用 --app-name 指定")
            sys.exit(1)
        app_name = row[0]
    args.app_name = app_name  # 供 load_config 校验

    # 加载 LLM 配置 + 分类参考库
    config = load_config(args)
    refs = load_reference(app_name)
    if not refs or not refs.get("classification"):
        logger.error("无法加载 '%s' 的分类知识库", app_name); sys.exit(1)
    func_to_business = refs.get("func_to_business", {})

    # 读 status=2 的失败行（不含未知问题、不含缺失）
    conn = sqlite3.connect(db_path)
    failed = conn.execute(f"SELECT id, problem FROM {table} WHERE status = 2 ORDER BY id").fetchall()
    conn.close()
    total = len(failed)
    logger.info("重试开始: 应用=%s, 失败%d条, 并发%d (keys=%d, 每key=%d), skill=%s, model=%s",
                app_name, total, config.total_concurrent, len(config.api_keys), config.max_concurrent,
                config.agent_cfg["skill_name"], config.agent_cfg.get("model") or "default")

    if total == 0:
        print(f"无失败数据(status=2)，无需重试。DB 共 {count_rows(db_path, table)} 条。")
        _close_all_db()
        return

    def _retry_one(task_idx, num, problem):
        """重试单条：classify_one 跑 agent，update_item 更新已有行（保留 problem/raw_data/version）。"""
        desc = problem or ""
        if not desc.strip():
            st, cls, reason = 2, ["未知问题"], "空描述,跳过分类"
        else:
            # 多 key 轮询：每个 task 用独立 cfg 副本注入对应 key
            if config.api_keys:
                cfg = dict(config.agent_cfg)
                cfg["api_key"] = config.api_keys[task_idx % len(config.api_keys)]
            else:
                cfg = config.agent_cfg
            st, cls, reason = classify_one(num, desc, refs, cfg)
        business = derive_business_classification(cls, st, func_to_business)
        update_item(num, cls, reason, app_name, db_path, st, business)
        return st

    success = 0
    unknown = 0
    still_failed = 0

    def _accumulate(st):
        nonlocal success, unknown, still_failed
        if st == 0:
            success += 1
        elif st == 1:
            unknown += 1
        else:
            still_failed += 1

    if config.total_concurrent == 1:
        for i, (num, problem) in enumerate(failed):
            _accumulate(_retry_one(i, num, problem))
            incr_progress(1, total, str(num))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.total_concurrent) as executor:
            futures = {}
            for i, (num, problem) in enumerate(failed):
                futures[executor.submit(_retry_one, i, num, problem)] = num
            for f in concurrent.futures.as_completed(futures):
                try:
                    _accumulate(f.result())
                except Exception as e:
                    logger.error("重试任务异常: %s", e)
                    still_failed += 1
                incr_progress(1, total, str(futures[f]))

    cnt = count_rows(db_path, table)
    logger.info("重试完成: %d条 (成功%d, 未知%d, 仍失败%d) | DB共%d条", total, success, unknown, still_failed, cnt)
    print(f"重试完成: {total}条 (成功{success}, 未知{unknown}, 仍失败{still_failed}) | DB共{cnt}条")

    # 重新生成报告（output_path 留空，generate_report 用目录名派生文件名）
    report = generate_report(output_dir)
    if not report:
        logger.warning("报告生成失败")

    _close_all_db()


if __name__ == "__main__":
    main()
