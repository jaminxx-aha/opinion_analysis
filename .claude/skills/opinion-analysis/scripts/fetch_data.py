#!/usr/bin/env python3
"""
从Excel中提取数据，供子Agent分类使用

用法:
  python fetch_data.py <Excel文件路径> --app-column <列> --problem-column <列> [--start <行号>] [--end <行号>] [--json]

参数:
  --app-column      应用名列索引（从1开始）或列名
  --problem-column  问题描述列索引（从1开始）或列名
  --start           起始数据行号（从1开始，不含表头），默认1
  --end             结束数据行号（含），默认全部
  --json            输出JSON格式（包含所有列数据，用于保存到数据库）

示例:
  python fetch_data.py data.xlsx --app-column 2 --problem-column 5
  python fetch_data.py data.xlsx --app-column 2 --problem-column 5 --start 1 --end 5
  python fetch_data.py data.xlsx --app-column 2 --problem-column 5 --start 1 --end 5 --json
"""

import sys
import json
import os
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
from config import app_alias_map


def resolve_app_name(app: str) -> str:
    """将应用别名转换为实际应用名"""
    if app in app_alias_map:
        return app_alias_map[app]
    return app


def resolve_column(col_spec, columns):
    """将列索引或列名转换为实际列名"""
    if col_spec is None:
        return None
    try:
        idx = int(col_spec)
        if 1 <= idx <= len(columns):
            return columns[idx - 1]
        return None
    except ValueError:
        return col_spec


def fetch_data(excel_path, app_column, problem_column, start_row=1, end_row=None, json_output=False, app_filter=None):
    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()

    app_col_name = resolve_column(app_column, columns)
    problem_col_name = resolve_column(problem_column, columns)

    # 检查列是否存在
    if problem_col_name not in columns:
        print(f"读取文件错误：问题描述列 '{problem_column}' 不存在")
        sys.exit(1)
    if app_col_name and app_col_name not in columns:
        print(f"读取文件错误：应用名列 '{app_column}' 不存在")
        sys.exit(1)

    # 行范围
    total_rows = len(df)
    if end_row is None:
        end_row = total_rows
    if start_row < 1:
        print(f"读取文件错误：起始行号不能小于1")
        sys.exit(1)
    if start_row > total_rows:
        print(f"读取文件错误：起始行号 {start_row} 超出范围（共 {total_rows} 行数据）")
        sys.exit(1)
    if end_row > total_rows:
        end_row = total_rows
    if start_row > end_row:
        print(f"读取文件错误：起始行号 {start_row} 大于结束行号 {end_row}")
        sys.exit(1)

    # 提取指定行范围的数据
    sliced = df.iloc[start_row - 1:end_row]

    # 如果指定了app_filter，只保留该应用的数据行
    if app_filter and app_col_name:
        sliced = sliced[
            sliced[app_col_name].apply(lambda x: resolve_app_name(str(x).strip()) if not pd.isna(x) else "")
            == app_filter
        ]
        if len(sliced) == 0:
            print(f"读取文件错误：应用名 '{app_filter}' 在指定行范围内无数据")
            sys.exit(1)

    if json_output:
        # JSON输出格式：包含所有列数据
        result = []
        for i, (pandas_idx, row) in enumerate(sliced.iterrows()):
            data_row = start_row + i
            app_val = ""
            if app_col_name:
                raw_app = str(row[app_col_name]) if not pd.isna(row[app_col_name]) else ""
                app_val = resolve_app_name(raw_app)

            problem_val = str(row[problem_col_name]) if not pd.isna(row[problem_col_name]) else ""

            # 所有列数据作为raw_data
            raw_data = {col: str(row[col]) if not pd.isna(row[col]) else "" for col in df.columns}

            result.append({
                "row_index": data_row,
                "app": app_val,
                "problem": problem_val,
                "raw_data": raw_data,
            })

        print(json.dumps(result, ensure_ascii=False))
    else:
        # 文本输出格式（用于分类参考）
        app_col_label = f"[{app_column}]" if app_col_name else ""
        problem_col_label = f"[{problem_column}]"

        print(f"文件: {excel_path}")
        print(f"行范围: {start_row}-{end_row} (共 {total_rows} 行数据)")
        print(f"应用名列: {app_col_label} {app_col_name}")
        print(f"问题描述列: {problem_col_label} {problem_col_name}")
        print()

        for i, (pandas_idx, row) in enumerate(sliced.iterrows()):
            data_row = start_row + i
            app_val = ""
            if app_col_name:
                raw_app = str(row[app_col_name]) if not pd.isna(row[app_col_name]) else ""
                app_val = resolve_app_name(raw_app)

            problem_val = str(row[problem_col_name]) if not pd.isna(row[problem_col_name]) else ""

            print(f"行{data_row} | 应用: {app_val} | 问题: {problem_val}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='从Excel提取应用名和问题描述列数据')
    parser.add_argument('input', help='Excel文件路径')
    parser.add_argument('--app-column', required=False, help='应用名列索引（从1开始）或列名')
    parser.add_argument('--problem-column', required=True, help='问题描述列索引（从1开始）或列名')
    parser.add_argument('--start', type=int, default=1, help='起始数据行号（从1开始，不含表头）')
    parser.add_argument('--end', type=int, default=None, help='结束数据行号（含）')
    parser.add_argument('--json', action='store_true', help='输出JSON格式（包含所有列数据）')
    parser.add_argument('--app-filter', default=None, help='只输出指定应用名的数据行（标准应用名，如"抖音"）')

    args = parser.parse_args()

    try:
        fetch_data(args.input, args.app_column, args.problem_column, args.start, args.end, args.json, args.app_filter)
    except FileNotFoundError:
        print(f"读取文件错误：文件不存在 '{args.input}'")
        sys.exit(1)
    except Exception as e:
        print(f"读取文件错误：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()