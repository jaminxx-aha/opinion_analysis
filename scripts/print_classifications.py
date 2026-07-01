#!/usr/bin/env python3
"""print_classifications.py - 打印 DB 中每条数据的「问题描述 + 分类」

输出为 TSV（制表符分隔），可直接复制粘贴进 Excel：
  - 默认：id<TAB>分类<TAB>问题描述，每行一条，含表头。
  - --only-classification：只输出分类列，每行一个，无表头；复制整段粘进 Excel 即一列。

分类格式：level1-level2-level3-level4-level5（空层级自动跳过）。
status 非 0 的行（未知问题/推理失败/描述过长）level 可能为空，用状态标签兜底。

用法:
  python print_classifications.py <db_path> [--domain function|business|all] [--only-classification]
"""

import sys
import os
import io
import sqlite3
import argparse

# Windows 控制台默认 GBK，打印中文/emoji 会崩，强制 stdout/stderr 走 UTF-8
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "buffer") and (
            not isinstance(stream, io.TextIOWrapper) or stream.encoding.lower() != "utf-8"
        ):
            stream.reconfigure(encoding="utf-8") if hasattr(stream, "reconfigure") else None

STATUS_LABEL = {0: "成功", 1: "未知问题", 2: "推理失败", 3: "描述过长"}


def format_classification(levels):
    """levels: [level1..level5]，去空后用 - 连接。"""
    return "-".join(l for l in levels if l)


def list_tables(conn, domain):
    if domain == "all":
        return [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'report_%'"
            )
        ]
    return [f"report_{domain}"]


def main():
    ap = argparse.ArgumentParser(description="打印 DB 中问题描述与分类(TSV, 可直接粘进 Excel)")
    ap.add_argument("db_path", help="report.db 路径")
    ap.add_argument("--domain", default="all", choices=["function", "business", "all"],
                    help="只打印指定域的表，默认 all 扫描所有 report_* 表")
    ap.add_argument("--only-classification", action="store_true",
                    help="只输出分类列(每行一个, 无表头)，复制整段可直接粘成 Excel 一列")
    args = ap.parse_args()

    if not os.path.isfile(args.db_path):
        sys.stderr.write(f"数据库文件不存在: {args.db_path}\n")
        sys.exit(1)

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = list_tables(conn, args.domain)
        if not tables:
            sys.stderr.write("未找到任何 report_* 表\n")
            sys.exit(1)

        out = sys.stdout
        first_table = True
        for table in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if not cols:
                continue
            level_cols = [f"level{i}" for i in range(1, 6)]
            select_levels = ", ".join(level_cols)
            rows = conn.execute(
                f"SELECT id, problem, status, {select_levels} FROM {table} ORDER BY id"
            ).fetchall()
            if not rows:
                continue

            if not args.only_classification:
                # 多表之间空一行分隔（Excel 粘贴时为一个空行，不影响列对齐）
                if not first_table:
                    out.write("\n")
                out.write("id\t分类\t问题描述\n")
            for r in rows:
                levels = [r[c] for c in level_cols]
                cls = format_classification(levels)
                if not cls:
                    cls = f"[{STATUS_LABEL.get(r['status'], r['status'])}]"
                if args.only_classification:
                    out.write(f"{cls}\n")
                else:
                    out.write(f"{r['id']}\t{cls}\t{r['problem'] or ''}\n")
            first_table = False
    finally:
        conn.close()


if __name__ == "__main__":
    main()
