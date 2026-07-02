#!/usr/bin/env python3
"""classify_data.py - 舆情数据自动分类入口（薄编排层）

只做 4 个阶段的编排，不再被任何兄弟模块 import（公共逻辑已下沉到 args/db_utils/processor）：
  Phase 1  parse_args + load_config + load_reference      （args.py）
  Phase 2  prepare_data：初始化 + retry/续跑选型 + 过长入库（processor.py）
  Phase 3  run：分派 batch/layered/agent 并发执行          （processor.py）
  Phase 4  generate_report                                （generate_report.py）

用法:
  python classify_data.py \
    --app-name 抖音 --problem-index 5 \
    --excel-path test/douyin_100.xlsx \
    --output-dir output/douyin_100 --domain function

LLM 配置从项目根目录 .env 自动加载，详见 args.load_config。
"""

import sys
import os
import io
import pandas as pd
import logging
from args import parse_args, load_config, resolve_columns
from db_utils import _close_all_db
from processor import prepare_data, run
from generate_report import generate_report

# Windows下强制UTF-8输出
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer') and (not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer') and (not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

logger = logging.getLogger("classify_data")

def main():
    # Phase 1：参数、环境变量、配置
    args = parse_args()
    config = load_config(args)

    # Phase 2：初始化 + 数据准备 + 过长入库（含加载分类参考库、建库建表）
    df = pd.read_excel(args.excel_path)
    problem_col, version_col = resolve_columns(args, df)

    all_data, ctx, refs = prepare_data(args, config, df, problem_col, version_col)

    # Phase 3：执行任务 + 数据落盘 + 期末汇总（汇总打印在 run 内）
    run(config, all_data, args.app_name, problem_col, df, refs, ctx, version_col)

    # Phase 4：报告生成（读 output_dir 下所有域 DB 合并双标签页，摘要打印在 generate_report 内）
    report_html_path = os.path.join(args.output_dir, f"{os.path.splitext(os.path.basename(args.excel_path))[0]}_report.html")
    report = generate_report(args.output_dir, report_html_path)
    if report:
        logger.info("报告已生成: %s (包含域: %s)", report['path'], ",".join(report.get('domains', [])))
    else:
        logger.warning("报告生成失败")

    _close_all_db()


if __name__ == "__main__":
    main()
