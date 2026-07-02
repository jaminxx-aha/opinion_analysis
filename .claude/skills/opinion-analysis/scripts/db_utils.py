#!/usr/bin/env python3
"""db_utils.py - DB 初始化、线程局部连接复用、入库、文本清洗、输出目录初始化

save_item 在多线程批量入库中被高频调用，故每个线程复用一个 sqlite 连接。
本模块不依赖 processor，可被 processor 与各策略模块直接 import。
"""

import os
import re
import json
import shutil
import sqlite3
import threading
import atexit
import logging
import pandas as pd

logger = logging.getLogger("classify_data")


def report_table(domain):
    """域 → 表名。功能域/业务域分别落 report_function / report_business 表（同一 report.db）。"""
    return f"report_{domain}"


# 建表 SQL 模板（按域生成表名：report_function / report_business）
_DB_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    id INTEGER PRIMARY KEY,
    app TEXT,
    problem TEXT,
    status INTEGER DEFAULT 1,
    cls_app TEXT,
    level1 TEXT,
    level2 TEXT,
    level3 TEXT,
    level4 TEXT,
    level5 TEXT,
    full_path TEXT,
    reasoning TEXT,
    raw_data TEXT,
    version TEXT DEFAULT ''
)
"""


def init_db(db_path, domain):
    """初始化单库 report.db，为指定域创建 report_<domain> 表。"""
    table = report_table(domain)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute(_DB_TABLE_SQL.format(table=table))
    # 兼容旧DB：自动添加缺失的 version 列
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if 'version' not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN version TEXT DEFAULT ''")
    # 兼容旧DB：自动添加缺失的 level4/level5 列（分类树最深 5 级）
    if 'level4' not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN level4 TEXT")
    if 'level5' not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN level5 TEXT")
    conn.commit()
    conn.close()


# ========== 线程局部 DB 连接复用 ==========
# save_item 在多线程批量入库中被高频调用，原先每次新建+关闭连接开销大。
# 改为每个线程复用一个连接：连接仅在所属线程使用，满足 sqlite3 默认
# check_same_thread=True；多连接并发写仍由 busy_timeout 兜底 SQLITE_BUSY。
_thread_local = threading.local()
_db_conns = []  # 登记所有线程的连接，便于统一回收
_db_conns_lock = threading.Lock()


def _get_db_conn(db_path):
    """返回当前线程复用的 SQLite 连接，首次调用时创建并登记。"""
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA busy_timeout = 30000")
        _thread_local.conn = conn
        with _db_conns_lock:
            _db_conns.append(conn)
    return conn


def _close_all_db():
    """关闭所有线程登记的连接并清空（程序退出时调用）。"""
    with _db_conns_lock:
        for conn in _db_conns:
            try:
                conn.close()
            except Exception:
                pass
        _db_conns.clear()


atexit.register(_close_all_db)


def init_output_dir(excel_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "log"), exist_ok=True)
    # 复制原始 Excel（多域续跑时可能已存在，避免覆盖报错）
    dst = os.path.join(output_dir, os.path.basename(excel_path))
    if not os.path.exists(dst):
        shutil.copy2(excel_path, dst)


def clean_desc(text):
    """清洗问题描述文本，移除HTML/CSS标签残留和卡片消息等无效内容。
    客服对话数据常见: br(换行残留)、span/p(标签名残留)、
    style/color/text-*(CSS属性残留)、答：卡片消息(小艺卡片无数据)
    """
    if not text or not text.strip():
        return text

    # br → 换行符（HTML换行标记残留）
    text = re.sub(r'\bbr\b', '\n', text)

    # CSS属性残留: 属性名 + 值 + 分号（如 style text-warp-mode wrap;、color rgb 192 0 0;）
    css_props = r'\b(?:style|color|text-\w+(?:-\w+)?|font-\w+|background(?:-\w+)?|margin(?:-\w+)?|padding(?:-\w+)?|border(?:-\w+)?|width|height|display|position|overflow(?:-\w+)?|white-space|word-\w+|line-height|vertical-align|text-align|text-decoration|letter-spacing|rgb)\b[^;]*?;'
    text = re.sub(css_props, '', text)

    # HTML标签名残留: 独立英文单词形式的标签名（如 p、span、div）
    html_tags = r'\b(?:p|span|div|b|i|strong|em|a|font|center|li|ul|ol|table|tr|td|th|img|hr|pre|code|sub|sup|small|big|h[1-6]|section|article|header|footer|nav|main|label|input|button|form|select|option|textarea|script|style)\b'
    text = re.sub(html_tags, '', text)

    # 移除"答：卡片消息"回答段（小艺卡片消息无原始数据，直接删除）
    text = re.sub(r'答[:：]\s*卡片消息', '', text)

    # 移除清理后变空的"答："标记
    text = re.sub(r'\n\s*答[:：]\s*\n', '\n', text)
    text = re.sub(r'^答[:：]\s*$', '', text, flags=re.MULTILINE)

    # 规范化空白: 压缩空格、合并多余换行、清理换行前后空格
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n[ \t]+', '\n', text)
    text = text.strip()

    return text


# 当前域对应的表名（report_function / report_business），由 prepare_data 设置，供 save_item 使用
_TABLE = "report_function"


def set_table(table):
    """设置当前域表名（prepare_data 阶段调用，供 save_item 读取）。"""
    global _TABLE
    _TABLE = table


def count_rows(db_path, table):
    """统计指定表的行数（期末汇总用，独立连接，不走线程局部池）。"""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _levels(classification):
    """由分类名称列表算出 level1~5 与 full_path（供 save_item / update_item 复用）。"""
    l1 = classification[0]
    l2 = classification[1] if len(classification) >= 2 else ""
    l3 = classification[2] if len(classification) >= 3 else ""
    l4 = classification[3] if len(classification) >= 4 else ""
    l5 = classification[4] if len(classification) >= 5 else ""
    return l1, l2, l3, l4, l5, ".".join(classification)


def update_item(num, classification, reason, app_name, db_path, status):
    """UPDATE 已有行的分类字段（status/cls_app/level1-5/full_path/reasoning），
    保留 problem/raw_data/version 不变。用于重试场景：行已存在，只需改分类结果。
    status: 0=成功, 1=未知问题, 2=失败, 3=描述过长
    """
    try:
        conn = _get_db_conn(db_path)
        cursor = conn.cursor()
        t = _TABLE
        if status == 0 and classification and classification[0] != "未知问题":
            l1, l2, l3, l4, l5, fp = _levels(classification)
            cursor.execute(f"UPDATE {t} SET status=?, cls_app=?, level1=?, level2=?, level3=?, level4=?, level5=?, full_path=?, reasoning=? WHERE id=?",
                           (status, app_name, l1, l2, l3, l4, l5, fp, reason, num))
        elif status == 1:
            cursor.execute(f"UPDATE {t} SET status=?, cls_app=?, level1=?, level2=?, level3=?, level4=?, level5=?, full_path=?, reasoning=? WHERE id=?",
                           (status, app_name, "未知问题", "", "", "", "", "未知问题", reason, num))
        elif status == 3:
            cursor.execute(f"UPDATE {t} SET status=?, cls_app=?, level1=?, level2=?, level3=?, level4=?, level5=?, full_path=?, reasoning=? WHERE id=?",
                           (status, app_name, "描述过长", "", "", "", "", "描述过长", reason, num))
        else:
            cursor.execute(f"UPDATE {t} SET status=?, reasoning=? WHERE id=?",
                           (status, reason, num))
        conn.commit()
        status_label = {0: "成功", 1: "未知问题", 2: "失败", 3: "描述过长"}
        logger.info("行%d 更新成功, 分类: %s, 推理: %s, 状态: %s", num, ".".join(classification) if classification else "无", reason, status_label.get(status, str(status)))
    except Exception as e:
        logger.error("行%d 更新失败: %s", num, e)


def save_item(num, classification, reason, app_name, problem_col, df, db_path, status, version_col=None):
    """status: 0=成功, 1=未知问题, 2=失败, 3=描述过长"""
    try:
        conn = _get_db_conn(db_path)
        cursor = conn.cursor()
        row = df.iloc[num - 1]
        problem = clean_desc(str(row[problem_col])) if not pd.isna(row[problem_col]) else ""
        raw_json = json.dumps({c: str(row[c]) if not pd.isna(row[c]) else "" for c in df.columns}, ensure_ascii=False)
        version = str(row[version_col]) if version_col and not pd.isna(row[version_col]) else ""
        t = _TABLE
        if status == 0 and classification and classification[0] != "未知问题":
            l1 = classification[0]
            l2 = classification[1] if len(classification) >= 2 else ""
            l3 = classification[2] if len(classification) >= 3 else ""
            l4 = classification[3] if len(classification) >= 4 else ""
            l5 = classification[4] if len(classification) >= 5 else ""
            # full_path 保留完整深层路径（分类树最深 5 级）；level1~5 列拆分存储各级分类名
            fp = ".".join(classification)
            cursor.execute(f"INSERT OR REPLACE INTO {t} (id,app,problem,status,cls_app,level1,level2,level3,level4,level5,full_path,reasoning,raw_data,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (num, app_name, problem, status, app_name, l1, l2, l3, l4, l5, fp, reason, raw_json, version))
        elif status == 1:
            cursor.execute(f"INSERT OR REPLACE INTO {t} (id,app,problem,status,cls_app,level1,level2,level3,level4,level5,full_path,reasoning,raw_data,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (num, app_name, problem, status, app_name, "未知问题", "", "", "", "", "未知问题", reason, raw_json, version))
        elif status == 3:
            cursor.execute(f"INSERT OR REPLACE INTO {t} (id,app,problem,status,cls_app,level1,level2,level3,level4,level5,full_path,reasoning,raw_data,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (num, app_name, problem, status, app_name, "描述过长", "", "", "", "", "描述过长", reason, raw_json, version))
        else:
            cursor.execute(f"INSERT OR REPLACE INTO {t} (id,app,problem,status,reasoning,raw_data,version) VALUES (?,?,?,?,?,?,?)",
                           (num, app_name, problem, status, reason, raw_json, version))
        conn.commit()
        status_label = {0: "成功", 1: "未知问题", 2: "失败", 3: "描述过长"}
        logger.info("行%d 入库成功, 分类: %s, 推理: %s, 状态: %s", num, ".".join(classification) if classification else "无", reason, status_label.get(status, str(status)))
    except Exception as e:
        logger.error("行%d 入库失败: %s", num, e)
