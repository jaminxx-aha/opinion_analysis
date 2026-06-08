#!/usr/bin/env python3
"""
fix_invalid_classifications.py - 修复DB中分类路径不属于编码→路径字典的数据

遍历DB中的数据，若分类路径不存在于编码→路径字典中，且不是未知问题(status=1)或失败(status=2)，
则将其status修改为2(失败)，并在reasoning中追加原因说明。

用法:
  python fix_invalid_classifications.py --app-name 抖音 --db-path output/douyin_100/report.db
"""

import os
import sys
import json
import sqlite3
import argparse
import logging

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

sys.path.insert(0, SCRIPT_DIR)
from app_list import get_supported_apps, get_app_dir
from classify_data import validate_classification, parse_classification_md

logger = logging.getLogger("fix_invalid")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger.addHandler(handler)


def load_classification_tree(app_name):
    """加载应用的分类编码→路径字典"""
    app_dir = get_app_dir(app_name)
    if not app_dir:
        logger.error("应用 '%s' 不在支持列表中, 无法加载分类字典", app_name)
        return None
    classification_path = os.path.join(app_dir, "classification.md")
    if not os.path.isfile(classification_path):
        logger.error("分类文件不存在: %s", classification_path)
        return None
    with open(classification_path, "r", encoding="utf-8") as f:
        md_content = f.read()
    return parse_classification_md(md_content)


def fix_invalid(db_path, app_name):
    """遍历DB，修复分类路径无效的数据"""
    tree_data = load_classification_tree(app_name)
    if tree_data is None:
        return

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 30000")

    rows = conn.execute(
        "SELECT id, level1, level2, level3, full_path, status, reasoning FROM report"
    ).fetchall()

    fixed_count = 0
    already_invalid = 0
    already_unknown = 0
    valid_count = 0

    for row in rows:
        id_, l1, l2, l3, full_path, status, reasoning = row

        # 跳过已经是失败(status=2)或未知问题(status=1)的数据
        if status == 2:
            already_invalid += 1
            continue
        if status == 1:
            already_unknown += 1
            continue

        # 构造classification列表
        classification = list(filter(None, [l1, l2, l3]))
        if not classification:
            continue

        # 校验分类路径
        if validate_classification(classification, tree_data):
            valid_count += 1
            continue

        # 分类路径无效，修改为失败(status=2)
        invalid_reason = f"分类路径无效: {full_path} 不存在于分类树"
        new_reasoning = f"{reasoning}\n{invalid_reason}" if reasoning else invalid_reason

        conn.execute(
            "UPDATE report SET status = 2, reasoning = ? WHERE id = ?",
            (new_reasoning, id_)
        )
        logger.info("行%d 分类路径无效: '%s', 已修改为失败", id_, full_path)
        fixed_count += 1

    conn.commit()
    conn.close()

    total = len(rows)
    logger.info("扫描完成: 共%d条, 有效%d条, 已是未知%d条, 已是失败%d条, 本次修复%d条",
                total, valid_count, already_unknown, already_invalid, fixed_count)
    print(f"扫描完成: 共{total}条, 有效{valid_count}条, 已是未知{already_unknown}条, 已是失败{already_invalid}条, 本次修复{fixed_count}条")


def main():
    parser = argparse.ArgumentParser(description="修复DB中分类路径不属于JSON分类树的数据")
    parser.add_argument("--app-name", required=True, help="应用名称(如: 抖音)")
    parser.add_argument("--db-path", required=True, help="SQLite数据库路径")
    args = parser.parse_args()

    if args.app_name not in get_supported_apps():
        logger.warning("应用 '%s' 不在支持列表中: %s", args.app_name, get_supported_apps())

    if not os.path.isfile(args.db_path):
        logger.error("数据库文件不存在: %s", args.db_path)
        sys.exit(1)

    fix_invalid(args.db_path, args.app_name)


if __name__ == "__main__":
    main()