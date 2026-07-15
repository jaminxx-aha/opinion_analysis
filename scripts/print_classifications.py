#!/usr/bin/env python3
"""print_classifications.py - 打印 DB 中每条数据的「问题描述 + 分类」

输出为 TSV（制表符分隔），可直接复制粘贴进 Excel：
  - 默认：id<TAB>分类<TAB>问题描述，每行一条，含表头。
  - --only-classification：只输出分类列，每行一个，无表头；复制整段粘进 Excel 即一列。

当前 DB 表结构：单 report 表，功能域分类存 full_path（- 分隔），业务域分类存
business_classification（单层页面标签）。本脚本按 --domain 选择打印哪一域。
status 非 0 的行（未知问题/推理失败/描述过长）分类可能为空，用状态标签兜底。

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

# 旧库（level1-5 无 full_path）兼容：按顺序拼回 full_path
_LEVEL_COLS = ("level1", "level2", "level3", "level4", "level5")


def _resolve_table(conn):
    """返回 (table, cols)。优先 report 表；旧库回退首个 report_* 表。"""
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )]
    for t in ["report"] + [n for n in names if n.startswith("report_")]:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
        if cols:
            return t, cols
    return None, []


def _row_classification(row, cols):
    """从一行数据抽出 (full_path, business_classification)。
    旧库无 full_path 时按 level1-5 拼回。"""
    fp = row["full_path"] if "full_path" in cols and row["full_path"] else ""
    biz = row["business_classification"] if "business_classification" in cols and row["business_classification"] else ""
    if not fp:
        parts = [row[c] for c in _LEVEL_COLS if c in cols and row[c]]
        fp = "-".join(parts)
    return fp or "", biz or ""


def _fallback_label(status):
    """分类为空时用状态标签兜底。"""
    return f"[{STATUS_LABEL.get(status, status)}]"


def main():
    ap = argparse.ArgumentParser(description="打印 DB 中问题描述与分类(TSV, 可直接粘进 Excel)")
    ap.add_argument("db_path", help="report.db 路径")
    ap.add_argument("--domain", default="all", choices=["function", "business", "all"],
                    help="功能域(full_path) / 业务域(business_classification) / 全部，默认 all")
    ap.add_argument("--only-classification", action="store_true",
                    help="只输出分类列(每行一个, 无表头)，复制整段可直接粘成 Excel 一列")
    args = ap.parse_args()

    if not os.path.isfile(args.db_path):
        sys.stderr.write(f"数据库文件不存在: {args.db_path}\n")
        sys.exit(1)

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    try:
        table, cols = _resolve_table(conn)
        if not table:
            sys.stderr.write("未找到 report 表（或旧 report_* 表）\n")
            sys.exit(1)

        # 只 SELECT 存在的列
        wanted = ["id", "problem", "status"] + [c for c in ("full_path", "business_classification") + _LEVEL_COLS if c in cols]
        select_cols = list(dict.fromkeys(wanted))  # 去重保序
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM {table} ORDER BY id"
        ).fetchall()
        if not rows:
            sys.stderr.write(f"表 {table} 无数据\n")
            sys.exit(1)

        out = sys.stdout
        show_func = args.domain in ("function", "all")
        show_biz = args.domain in ("business", "all")
        only = args.only_classification

        if not only:
            if show_func and show_biz:
                out.write("id\t功能域分类\t业务域分类\t问题描述\n")
            else:
                out.write("id\t分类\t问题描述\n")

        for r in rows:
            fp, biz = _row_classification(r, cols)
            status = r["status"]
            func_cls = fp or _fallback_label(status)
            biz_cls = biz or _fallback_label(status)
            problem = r["problem"] or ""
            if only:
                if show_func and show_biz:
                    out.write(f"{func_cls}\t{biz_cls}\n")
                elif show_func:
                    out.write(f"{func_cls}\n")
                else:
                    out.write(f"{biz_cls}\n")
            else:
                if show_func and show_biz:
                    out.write(f"{r['id']}\t{func_cls}\t{biz_cls}\t{problem}\n")
                else:
                    cls = func_cls if show_func else biz_cls
                    out.write(f"{r['id']}\t{cls}\t{problem}\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
