#!/usr/bin/env python3
"""
从Excel中读取指定行范围的问题描述，返回JSON格式数据供子Agent分类使用

用法:
  python get_rows.py <Excel文件路径> --problem-column <列> [--start <行号>] [--end <行号>]

参数:
  --problem-column  问题描述列索引（从1开始）或列名
  --start           起始数据行号（从1开始，不含表头），默认1
  --end             结束数据行号（含），默认全部

示例:
  python get_rows.py data.xlsx --problem-column 5
  python get_rows.py data.xlsx --problem-column 5 --start 1 --end 100
"""

import sys
import json
import os
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
from config import apps_in_folder, app_alias_map


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


def get_rows(excel_path, problem_column, app_name="", start_row=1, end_row=None):
    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()

    problem_col_name = resolve_column(problem_column, columns)
    if problem_col_name not in columns:
        print(json.dumps({"error": f"问题描述列 '{problem_column}' 不存在"}, ensure_ascii=False))
        sys.exit(1)

    # 行范围
    total_rows = len(df)
    if end_row is None:
        end_row = total_rows
    if start_row < 1 or start_row > total_rows:
        print(json.dumps({"error": f"起始行号 {start_row} 超出范围（共 {total_rows} 行）"}, ensure_ascii=False))
        sys.exit(1)
    if end_row > total_rows:
        end_row = total_rows

    # 提取指定行范围的数据
    sliced = df.iloc[start_row - 1:end_row]

    data = []
    for i, (_, row) in enumerate(sliced.iterrows()):
        num = start_row + i
        desc = str(row[problem_col_name]) if not pd.isna(row[problem_col_name]) else ""
        data.append({"num": num, "desc": desc})

    result = {
        "excel_path": excel_path,
        "total_rows": total_rows,
        "start": start_row,
        "end": end_row,
        "app": app_name,
        "problem_column": int(problem_column) if problem_column.isdigit() else problem_column,
        "data": data,
    }

    print(json.dumps(result, ensure_ascii=False))


def main():
    import argparse

    parser = argparse.ArgumentParser(description='从Excel读取指定行的问题描述')
    parser.add_argument('input', help='Excel文件路径')
    parser.add_argument('--problem-column', required=True, help='问题描述列索引（从1开始）或列名')
    parser.add_argument('--app-name', default='', help='应用名（传入JSON输出的app字段）')
    parser.add_argument('--start', type=int, default=1, help='起始数据行号（从1开始，不含表头）')
    parser.add_argument('--end', type=int, default=None, help='结束数据行号（含）')

    args = parser.parse_args()

    try:
        get_rows(args.input, args.problem_column, args.app_name, args.start, args.end)
    except FileNotFoundError:
        print(json.dumps({"error": f"文件不存在 '{args.input}'"}, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()