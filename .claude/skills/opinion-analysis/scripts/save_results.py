#!/usr/bin/env python3
"""
将分类结果和原始Excel数据写入本地SQLite数据库

用法:
  python save_results.py '<分类结果JSON>' --output-dir <输出目录>

参数:
  分类结果JSON    子Agent输出的分类结果JSON字符串或文件路径
  --output-dir    输出目录（report.db 所在目录）

分类结果JSON格式:
  {
    "excel_path": "/path/to/file.xlsx",
    "app": "抖音",
    "problem_column": 5,
    "start": 1,
    "end": 100,
    "data": [
      {"num": 1, "desc": "卡顿.滑动卡顿.首页推荐视频流上下滑动卡顿"},
      {"num": 2, "desc": "unrecognized"},
      {"num": 3, "desc": "闪退/崩溃.使用过程闪退.视频播放过程闪退"}
    ]
  }

  desc为三层分类路径（成功分类）或"unrecognized"（不属于8类性能问题）

示例:
  python save_results.py '{"excel_path":"data.xlsx","app":"抖音","problem_column":5,"start":1,"end":5,"data":[{"num":1,"desc":"卡顿.滑动卡顿.首页推荐视频流上下滑动卡顿"}]}' --output-dir ./output/data
"""

import sys
import json
import os
import sqlite3
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DB_FILENAME = "report.db"


def resolve_column(col_spec, columns):
    """将列索引或列名转换为实际列名"""
    try:
        idx = int(col_spec)
        if 1 <= idx <= len(columns):
            return columns[idx - 1]
        return None
    except ValueError:
        return col_spec


def init_db(db_path: str, app: str = ""):
    """初始化数据库，创建单表结构"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS report (
            id INTEGER PRIMARY KEY,
            app TEXT,
            problem TEXT,
            status TEXT DEFAULT 'success',
            cls_app TEXT,
            level1 TEXT,
            level2 TEXT,
            level3 TEXT,
            full_path TEXT,
            reasoning TEXT,
            raw_data TEXT
        )
    """)

    conn.commit()
    return conn


def save_results(json_input, output_dir):
    # 解析输入：JSON字符串或文件路径
    if os.path.isfile(json_input):
        with open(json_input, 'r', encoding='utf-8') as f:
            result = json.load(f)
    else:
        result = json.loads(json_input)

    excel_path = result.get("excel_path")
    app = result.get("app", "")
    problem_column = result.get("problem_column", "")
    start = result.get("start", 1)
    end = result.get("end", None)
    data = result.get("data", [])

    if not excel_path:
        print("错误：缺少 excel_path")
        sys.exit(1)

    # 读取Excel原始数据
    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()
    problem_col_name = resolve_column(problem_column, columns)

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    db_path = os.path.join(output_dir, DB_FILENAME)

    # 初始化数据库
    conn = init_db(db_path, app)
    cursor = conn.cursor()

    inserted = 0
    for item in data:
        num = item["num"]
        desc = item["desc"]
        reasoning = item.get("reasoning", "")

        # 获取原始行数据
        row_idx = num - 1  # pandas行索引从0开始
        if 0 <= row_idx < len(df):
            row = df.iloc[row_idx]
            problem = str(row[problem_col_name]) if problem_col_name and not pd.isna(row[problem_col_name]) else ""
            raw_data = {col: str(row[col]) if not pd.isna(row[col]) else "" for col in columns}
            raw_data_json = json.dumps(raw_data, ensure_ascii=False)
        else:
            problem = ""
            raw_data_json = "{}"

        # 解析分类结果并写入单表
        if desc == "unrecognized":
            cursor.execute("""
                INSERT OR REPLACE INTO report (id, app, problem, status, reasoning, raw_data)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (num, app, problem, "unrecognized", reasoning, raw_data_json))
        else:
            parts = desc
            level1 = parts[0] if len(parts) >= 1 else ""
            level2 = parts[1] if len(parts) >= 2 else ""
            level3 = parts[2] if len(parts) >= 3 else ""
            full_path = ".".join(parts)

            cursor.execute("""
                INSERT OR REPLACE INTO report (id, app, problem, status, cls_app, level1, level2, level3, full_path, reasoning, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (num, app, problem, "success", app, level1, level2, level3, full_path, reasoning, raw_data_json))

        inserted += 1

    conn.commit()

    # 获取总数
    cursor.execute("SELECT COUNT(*) FROM report")
    total = cursor.fetchone()[0]
    conn.close()

    print(f"已写入 {inserted} 条分类结果到 {db_path}")
    print(f"累计: {total} 条")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='将分类结果和原始数据写入数据库')
    parser.add_argument('json_input', help='分类结果JSON（字符串或文件路径）')
    parser.add_argument('--output-dir', required=True, help='输出目录路径')

    args = parser.parse_args()

    try:
        save_results(args.json_input, args.output_dir)
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()