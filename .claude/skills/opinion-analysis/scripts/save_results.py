#!/usr/bin/env python3
"""
将分类结果和原始Excel数据写入本地SQLite数据库

用法:
  python save_results.py <分类结果JSON文件路径> --output-dir <输出目录>
  python save_results.py --stdin --output-dir <输出目录>   (从标准输入读取JSON)

参数:
  分类结果JSON    子Agent输出的分类结果JSON文件路径（推荐方式，避免命令行长度限制）
  --stdin         从标准输入读取JSON数据
  --output-dir    输出目录（report.db 所在目录）

分类结果JSON格式:
  {
    "excel_path": "/path/to/file.xlsx",
    "app": "抖音",
    "problem_column": 5,
    "start": 1,
    "end": 100,
    "data": [
      {"num": 1, "classification": ["卡顿","滑动卡顿","首页推荐视频流上下滑动卡顿"], "reasoning": "..."},
      {"num": 2, "classification": ["未知问题"], "reasoning": "..."}
    ]
  }

  classification为分类数组：三级推导为[一级,二级,三级]，二级推导为[一级,二级]，一级推导为[一级]，无法归类为["未知问题"]

示例:
  # 通过文件传入（推荐）
  python save_results.py ./output/batch_1_100.json --output-dir ./output/data

  # 通过标准输入传入
  cat result.json | python save_results.py --stdin --output-dir ./output/data
"""

import sys
import json
import os
import sqlite3
import pandas as pd
from datetime import datetime

from config import resolve_column

DB_FILENAME = "report.db"


def init_db(db_path: str):
    """初始化数据库，创建单表结构，设置并发写入超时"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 30000")  # 30秒并发等待
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


def read_json_input(json_input, use_stdin=False):
    """解析JSON输入：文件路径或标准输入"""
    if use_stdin:
        return json.loads(sys.stdin.read())

    if os.path.isfile(json_input):
        with open(json_input, 'r', encoding='utf-8') as f:
            return json.load(f)

    return json.loads(json_input)


def save_results(result, output_dir):
    """将分类结果写入数据库"""
    excel_path = result.get("excel_path")
    app = result.get("app", "")
    problem_column = result.get("problem_column", "")
    start = result.get("start", 1)
    end = result.get("end", None)
    data = result.get("data", [])

    if not excel_path:
        print("错误：缺少 excel_path")
        sys.exit(1)

    # 读取Excel原始数据（如果output_dir中有缓存则优先使用）
    cache_path = os.path.join(output_dir, "_excel_cache.pkl")
    if os.path.isfile(cache_path):
        df = pd.read_pickle(cache_path)
    else:
        df = pd.read_excel(excel_path)
        # 写入缓存供后续子agent使用
        df.to_pickle(cache_path)

    columns = df.columns.tolist()
    problem_col_name = resolve_column(problem_column, columns)

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    db_path = os.path.join(output_dir, DB_FILENAME)

    # 初始化数据库
    conn = init_db(db_path)
    cursor = conn.cursor()

    inserted = 0
    for item in data:
        num = item["num"]
        cls = item.get("classification", [])
        reasoning = item.get("reasoning", "")

        # 获取原始行数据
        row_idx = num - 1
        if 0 <= row_idx < len(df):
            row = df.iloc[row_idx]
            problem = str(row[problem_col_name]) if problem_col_name and not pd.isna(row[problem_col_name]) else ""
            raw_data = {col: str(row[col]) if not pd.isna(row[col]) else "" for col in columns}
            raw_data_json = json.dumps(raw_data, ensure_ascii=False)
        else:
            problem = ""
            raw_data_json = "{}"

        # 解析分类结果并写入单表
        if not cls or cls[0] == "未知问题":
            cursor.execute("""
                INSERT OR REPLACE INTO report (id, app, problem, status, reasoning, raw_data)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (num, app, problem, "unrecognized", reasoning, raw_data_json))
        else:
            level1 = cls[0]
            level2 = cls[1] if len(cls) >= 2 else ""
            level3 = cls[2] if len(cls) >= 3 else ""
            full_path = ".".join([l for l in [level1, level2, level3] if l])

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

    # 写入日志
    log_path = os.path.join(output_dir, "report.log")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as log_f:
        log_f.write(f"{now} {start} - {end} 分类成功\n")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='将分类结果和原始数据写入数据库')
    parser.add_argument('json_input', nargs='?', default=None, help='分类结果JSON文件路径')
    parser.add_argument('--stdin', action='store_true', help='从标准输入读取JSON数据')
    parser.add_argument('--output-dir', required=True, help='输出目录路径')

    args = parser.parse_args()

    if not args.stdin and not args.json_input:
        print("错误：请指定JSON文件路径或使用 --stdin 从标准输入读取")
        sys.exit(1)

    # 在try前提取start/end，用于失败日志
    start, end = "", ""
    try:
        if args.stdin:
            raw = sys.stdin.read()
            parsed = json.loads(raw)
        elif os.path.isfile(args.json_input):
            parsed = {}
        else:
            parsed = json.loads(args.json_input)
        start = parsed.get("start", "")
        end = parsed.get("end", "")
    except Exception:
        pass

    try:
        result = read_json_input(args.json_input, args.stdin)
        save_results(result, args.output_dir)
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        log_path = os.path.join(args.output_dir, "report.log")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(args.output_dir, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as log_f:
            log_f.write(f"{now} {start} - {end} 分类失败: JSON解析失败\n")
        sys.exit(1)
    except Exception as e:
        print(f"错误: {e}")
        log_path = os.path.join(args.output_dir, "report.log")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(args.output_dir, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as log_f:
            log_f.write(f"{now} {start} - {end} 分类失败: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()