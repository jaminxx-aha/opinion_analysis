#!/usr/bin/env python3
"""
将子Agent分类结果追加到 prepared.db SQLite数据库

用法:
  python save_classification.py <分类结果JSON> --output-dir <输出目录>

参数:
  分类结果JSON    子Agent输出的分类结果（包含raw_data），可以是JSON字符串或文件路径
  --output-dir    输出目录（prepared.db 所在目录）
  --excel-source  原始Excel文件路径（仅用于记录元数据）

分类结果JSON格式:
  [
    {
      "row_index": 1,
      "app": "抖音",
      "problem": "问题描述",
      "raw_data": {"序号": "1", "应用名": "抖音", ...},  // 所有列原始数据
      "classification": {"app": "抖音", "level1": "卡顿", ...}
    }
  ]

示例:
  python save_classification.py '[{"row_index":1,...,"raw_data":{...},"classification":{...}}]' --output-dir ./output/data
"""

import sys
import json
import os
import sqlite3
import argparse

DB_FILENAME = "prepared.db"


def init_db(db_path: str, excel_source: str = ""):
    """初始化数据库，创建表结构"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            row_index INTEGER,
            app TEXT,
            problem TEXT,
            status TEXT DEFAULT 'success',
            cls_app TEXT,
            level1 TEXT,
            level2 TEXT,
            level3 TEXT,
            full_path TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_rows (
            row_index INTEGER PRIMARY KEY,
            raw_data TEXT
        )
    """)

    if excel_source:
        cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('excel_source', ?)",
                        (excel_source,))

    conn.commit()
    return conn


def save_classification(json_input, output_dir, excel_source=""):
    # 解析输入：JSON字符串或文件路径
    if os.path.isfile(json_input):
        with open(json_input, 'r', encoding='utf-8') as f:
            items = json.load(f)
    else:
        items = json.loads(json_input)

    # 确保 items 是列表
    if not isinstance(items, list):
        items = [items]

    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)

    # 数据库路径
    db_path = os.path.join(output_dir, DB_FILENAME)

    # 初始化数据库（如果不存在则创建）
    conn = init_db(db_path, excel_source)
    cursor = conn.cursor()

    # 插入分类结果和原始数据
    inserted = 0
    raw_saved = 0
    for item in items:
        cls = item.get("classification", {})
        status = item.get("status", "success")
        row_index = item.get("row_index")

        # 保存原始数据到raw_rows表
        raw_data = item.get("raw_data")
        if raw_data and row_index:
            cursor.execute(
                "INSERT OR REPLACE INTO raw_rows (row_index, raw_data) VALUES (?, ?)",
                (row_index, json.dumps(raw_data, ensure_ascii=False))
            )
            raw_saved += 1

        if not cls and status in ("unrecognized", "no_description"):
            cursor.execute("""
                INSERT INTO items (row_index, app, problem, status)
                VALUES (?, ?, ?, ?)
            """, (row_index, item.get("app", ""), item.get("problem", ""), status))
        elif cls:
            cursor.execute("""
                INSERT INTO items (row_index, app, problem, status, cls_app, level1, level2, level3, full_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row_index,
                item.get("app", ""),
                item.get("problem", ""),
                status,
                cls.get("app", ""),
                cls.get("level1", ""),
                cls.get("level2", ""),
                cls.get("level3", ""),
                cls.get("full_path", ""),
            ))
        else:
            cursor.execute("""
                INSERT INTO items (row_index, app, problem, status)
                VALUES (?, ?, ?, ?)
            """, (row_index, item.get("app", ""), item.get("problem", ""), "pending"))

        inserted += 1

    conn.commit()

    # 获取总数
    cursor.execute("SELECT COUNT(*) FROM items")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM raw_rows")
    raw_total = cursor.fetchone()[0]
    conn.close()

    print(f"已追加 {inserted} 条分类结果到 {db_path}")
    if raw_saved > 0:
        print(f"已保存 {raw_saved} 条原始数据（累计 {raw_total} 条）")
    print(f"分类累计: {total} 条")


def main():
    parser = argparse.ArgumentParser(description='追加分类结果到prepared.db')
    parser.add_argument('json_input', help='分类结果JSON（字符串或文件路径）')
    parser.add_argument('--output-dir', required=True, help='输出目录路径')
    parser.add_argument('--excel-source', default='', help='原始Excel文件路径（仅用于记录元数据）')

    args = parser.parse_args()

    try:
        save_classification(args.json_input, args.output_dir, args.excel_source)
    except json.JSONDecodeError as e:
        print(f"读取文件错误：JSON解析失败 - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"读取文件错误：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()