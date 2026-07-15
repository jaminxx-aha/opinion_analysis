#!/usr/bin/env python3
"""
fix_invalid_classifications.py - 修复DB中分类路径不属于分类树/合法标签集的数据

当前 DB 表结构：单 report 表，功能域分类 = full_path（- 分隔），业务域分类 =
business_classification（单层页面标签）。本脚本按 --domain 校验对应列：
  - function: full_path 切分后是否存在于功能域分类树（classification_function.md）
  - business: business_classification 是否属于功能→业务映射的合法标签集
status 非 0 的行（未知问题=1 / 推理失败=2 / 描述过长=3）跳过，只校验 status=0。
无效者改 status=2（失败）并在 reasoning 追加原因。

用法:
  python fix_invalid_classifications.py --app-name 抖音 --domain function --db-path output/xxx/report.db
"""

import os
import sys
import sqlite3
import argparse
import logging

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
SKILL_SCRIPTS_DIR = os.path.join(PROJECT_DIR, ".claude", "skills", "opinion-analysis", "scripts")

sys.path.insert(0, SKILL_SCRIPTS_DIR)
from app_list import get_supported_apps  # noqa: E402
from args import load_reference, validate_classification  # noqa: E402

logger = logging.getLogger("fix_invalid")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger.addHandler(handler)

# 旧库（无 full_path）兼容：按顺序拼回 full_path
_LEVEL_COLS = ("level1", "level2", "level3", "level4", "level5")


def _resolve_table(conn, domain):
    """优先 report 表；旧库回退 report_<domain>。"""
    names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    if "report" in names:
        return "report"
    if f"report_{domain}" in names:
        return f"report_{domain}"
    return "report"


def _extract_full_path(row, cols):
    """从行数据取 full_path；旧库无 full_path 时按 level1-5 拼回。"""
    fp = row["full_path"] if "full_path" in cols and row["full_path"] else ""
    if not fp:
        parts = [row[c] for c in _LEVEL_COLS if c in cols and row[c]]
        fp = "-".join(parts)
    return fp or ""


def fix_invalid(db_path, app_name, domain="function"):
    """遍历DB，修复分类路径无效的数据"""
    ref = load_reference(app_name)
    if ref is None:
        logger.error("应用 '%s' 无分类参考库, 无法加载分类字典", app_name)
        return
    tree = ref["classification_tree"]
    func_to_business = ref["func_to_business"]
    if domain == "business":
        valid_labels = set(func_to_business.values()) | {"其它", "未知问题"}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    table = _resolve_table(conn, domain)
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

    wanted = ["id", "status", "reasoning"] + [
        c for c in ("full_path", "business_classification") + _LEVEL_COLS if c in cols
    ]
    select_cols = list(dict.fromkeys(wanted))  # 去重保序
    rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM {table}").fetchall()

    fixed_count = 0
    already_invalid = 0
    already_unknown = 0
    already_too_long = 0
    valid_count = 0
    empty_count = 0

    for row in rows:
        id_ = row["id"]
        status = row["status"]
        reasoning = row["reasoning"]

        # 只校验 status=0 的成功行；未知(1)/失败(2)/描述过长(3) 跳过
        if status == 2:
            already_invalid += 1
            continue
        if status == 1:
            already_unknown += 1
            continue
        if status == 3:
            already_too_long += 1
            continue

        if domain == "function":
            fp = _extract_full_path(row, cols)
            classification = [p for p in fp.split("-") if p]
            if not classification:
                empty_count += 1
                continue
            ok = validate_classification(classification, tree)
            invalid_desc = f"分类路径无效: {fp} 不存在于分类树"
        else:  # business
            label = row["business_classification"] if "business_classification" in cols and row["business_classification"] else ""
            if not label:
                empty_count += 1
                continue
            ok = label in valid_labels
            invalid_desc = f"业务标签无效: {label} 不在合法标签集"

        if ok:
            valid_count += 1
            continue

        new_reasoning = f"{reasoning}\n{invalid_desc}" if reasoning else invalid_desc
        conn.execute(
            f"UPDATE {table} SET status = 2, reasoning = ? WHERE id = ?",
            (new_reasoning, id_)
        )
        logger.info("行%d %s, 已改为失败", id_, invalid_desc)
        fixed_count += 1

    conn.commit()
    conn.close()

    total = len(rows)
    logger.info("扫描完成: 共%d条, 有效%d条, 已是未知%d条, 已是失败%d条, 描述过长%d条, 空分类%d条, 本次修复%d条",
                total, valid_count, already_unknown, already_invalid, already_too_long, empty_count, fixed_count)
    print(f"扫描完成: 共{total}条, 有效{valid_count}条, 已是未知{already_unknown}条, 已是失败{already_invalid}条, "
          f"描述过长{already_too_long}条, 空分类{empty_count}条, 本次修复{fixed_count}条")


def _detect_domain(db_path):
    """从 DB 文件名推断域：function_report.db→function, business_report.db→business, 旧 report.db→function"""
    base = os.path.basename(db_path)
    for d in ("function", "business"):
        if base == f"{d}_report.db":
            return d
    return "function"


def main():
    parser = argparse.ArgumentParser(description="修复DB中分类路径不属于分类树/合法标签集的数据")
    parser.add_argument("--app-name", required=True, help="应用名称(如: 抖音)")
    parser.add_argument("--db-path", required=True, help="SQLite数据库路径(如 report.db)")
    parser.add_argument("--domain", choices=["function", "business"], default=None,
                        help="分类域（默认按 DB 文件名推断，旧 report.db 视作 function）")
    args = parser.parse_args()

    domain = args.domain or _detect_domain(args.db_path)

    if args.app_name not in get_supported_apps():
        logger.warning("应用 '%s' 不在支持列表中: %s", args.app_name, get_supported_apps())

    if not os.path.isfile(args.db_path):
        logger.error("数据库文件不存在: %s", args.db_path)
        sys.exit(1)

    fix_invalid(args.db_path, args.app_name, domain)


if __name__ == "__main__":
    main()
