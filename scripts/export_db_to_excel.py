#!/usr/bin/env python3
"""
export_db_to_excel.py - 将分类DB数据导出为Excel文件，并追加推理分类及校验结果

用法:
  导出+追加: python export_db_to_excel.py <db文件路径> <输出路径>
  仅追加:    python export_db_to_excel.py <db文件路径> <excel文件路径> --append

Excel格式:
  校准分类区: 问题描述(合并2行) | 校准分类(合并3列, 二行拆为level1/level2/level3)
  推理分类区: 推理分类(合并4列, 二行拆为level1/level2/level3/result)
  result列: 公式校验推理分类与校准分类是否一致
  末尾: 正确率统计行

追加模式时，推理分类列从已有数据最后一列之后开始，列号动态计算。
"""

import sys
import os
import sqlite3
import argparse

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

DATA_START_ROW = 3  # 数据从第3行开始


def _table_for_domain(domain):
    """域 → 表名。function/business 分别 report_function/report_business。"""
    return f"report_{domain}"


def _read_db(db_path, table="report"):
    """读取DB中指定表的分类数据（默认 report 表）

    table: report_function / report_business / report(旧)。若指定表不存在，
    自动回退到 report 表（兼容旧库）。
    """
    if not os.path.isfile(db_path):
        print(f"错误: DB文件不存在: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 30000")
    if table != "report":
        has = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not has:
            print(f"提示: 表 {table} 不存在，回退到 report 表")
            table = "report"
    rows = conn.execute(
        f"SELECT problem, level1, level2, level3 FROM {table} ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def _write_headers(ws, start_col):
    """写入推理分类表头（从start_col列开始）"""
    # 第一行: 推理分类 合并4列
    ws.merge_cells(start_row=1, start_column=start_col, end_row=1, end_column=start_col + 3)
    ws.cell(row=1, column=start_col, value="推理分类").alignment = Alignment(horizontal="center", vertical="center")

    # 第二行: level1 | level2 | level3 | result
    for offset, label in enumerate(["level1", "level2", "level3", "result"]):
        ws.cell(row=2, column=start_col + offset, value=label).alignment = Alignment(horizontal="center")


def _write_data_rows(ws, rows, cal_l1_col, cal_l2_col, cal_l3_col, inf_start_col):
    """写入推理分类数据行，返回最后一行行号

    Args:
        cal_l1_col: 校准分类level1所在列号
        cal_l2_col: 校准分类level2所在列号
        cal_l3_col: 校准分类level3所在列号
        inf_start_col: 推理分类起始列号(level1)
    """
    inf_l1_col = inf_start_col
    inf_l2_col = inf_start_col + 1
    inf_l3_col = inf_start_col + 2
    inf_result_col = inf_start_col + 3

    for i, (problem, l1, l2, l3) in enumerate(rows):
        row_num = DATA_START_ROW + i
        ws.cell(row=row_num, column=inf_l1_col, value=l1 or "")
        ws.cell(row=row_num, column=inf_l2_col, value=l2 or "")
        ws.cell(row=row_num, column=inf_l3_col, value=l3 or "")

    # result列: 公式校验校准分类与推理分类是否一致
    col_cal_l1 = get_column_letter(cal_l1_col)
    col_cal_l2 = get_column_letter(cal_l2_col)
    col_cal_l3 = get_column_letter(cal_l3_col)
    col_inf_l1 = get_column_letter(inf_l1_col)
    col_inf_l2 = get_column_letter(inf_l2_col)
    col_inf_l3 = get_column_letter(inf_l3_col)
    col_result = get_column_letter(inf_result_col)

    for i in range(len(rows)):
        row_num = DATA_START_ROW + i
        formula = (
            f'=IF(AND(AND({col_cal_l1}{row_num}={col_inf_l1}{row_num},'
            f'{col_cal_l2}{row_num}={col_inf_l2}{row_num}),'
            f'{col_cal_l3}{row_num}={col_inf_l3}{row_num}), "√", "×")'
        )
        ws.cell(row=row_num, column=inf_result_col, value=formula)

    last_data_row = DATA_START_ROW + len(rows) - 1
    return last_data_row


def _write_accuracy_row(ws, last_data_row, inf_start_col):
    """写入正确率统计行

    Args:
        inf_start_col: 推理分类起始列号(level1)
    """
    inf_result_col = inf_start_col + 3
    summary_row = last_data_row + 1
    col_result = get_column_letter(inf_result_col)

    # 推理分类 area: 正确率 合并3列 (level1-level3位置)
    ws.merge_cells(start_row=summary_row, start_column=inf_start_col, end_row=summary_row, end_column=inf_start_col + 2)
    cell_label = ws.cell(row=summary_row, column=inf_start_col, value="正确率")
    cell_label.font = Font(bold=True)
    cell_label.alignment = Alignment(horizontal="center", vertical="center")

    # result列: 正确率百分比公式
    formula = f'=COUNTIF({col_result}{DATA_START_ROW}:{col_result}{last_data_row},"√")/COUNTA({col_result}{DATA_START_ROW}:{col_result}{last_data_row})'
    cell_pct = ws.cell(row=summary_row, column=inf_result_col, value=formula)
    cell_pct.font = Font(bold=True)
    cell_pct.number_format = '0.00%'

    return summary_row


def _set_column_widths(ws, cols_widths):
    """设置列宽

    Args:
        cols_widths: dict, 列号 → 宽度
    """
    for col, width in cols_widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width


# 默认列布局 (1-based): 导出模式下校准分类从B列开始
DEFAULT_CAL_L1 = 2  # B
DEFAULT_CAL_L2 = 3  # C
DEFAULT_CAL_L3 = 4  # D

DEFAULT_WIDTHS = {
    1: 40,       # 问题描述
    2: 15,       # 校准 level1
    3: 15,       # 校准 level2
    4: 15,       # 校准 level3
}

INF_WIDTHS = {
    "l1": 15,
    "l2": 15,
    "l3": 15,
    "result": 10,
}


def export_db_to_excel(db_path, output_path, domain="function"):
    """创建新Excel文件：仅校准分类（问题描述 + level1/level2/level3）"""
    rows = _read_db(db_path, _table_for_domain(domain))

    wb = Workbook()
    ws = wb.active
    ws.title = "分类结果"

    # 校准分类表头
    ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=1)
    ws.cell(row=1, column=1, value="问题描述").alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells(start_row=1, start_column=DEFAULT_CAL_L1, end_row=1, end_column=DEFAULT_CAL_L3)
    ws.cell(row=1, column=DEFAULT_CAL_L1, value="校准分类").alignment = Alignment(horizontal="center", vertical="center")

    ws.cell(row=2, column=DEFAULT_CAL_L1, value="level1").alignment = Alignment(horizontal="center")
    ws.cell(row=2, column=DEFAULT_CAL_L2, value="level2").alignment = Alignment(horizontal="center")
    ws.cell(row=2, column=DEFAULT_CAL_L3, value="level3").alignment = Alignment(horizontal="center")

    # 校准分类数据
    for i, (problem, l1, l2, l3) in enumerate(rows):
        row_num = DATA_START_ROW + i
        ws.cell(row=row_num, column=1, value=problem or "")
        ws.cell(row=row_num, column=DEFAULT_CAL_L1, value=l1 or "")
        ws.cell(row=row_num, column=DEFAULT_CAL_L2, value=l2 or "")
        ws.cell(row=row_num, column=DEFAULT_CAL_L3, value=l3 or "")

    _set_column_widths(ws, DEFAULT_WIDTHS)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    wb.save(output_path)
    print(f"导出完成: {output_path} ({len(rows)}条数据)")


def _find_cal_columns(ws):
    """从已有Excel中检测校准分类的level1/level2/level3列号

    在第二行中查找"level1"关键字，返回其列号及后续列号。
    """
    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=2, column=col).value
        if val and str(val).strip() == "level1":
            return col, col + 1, col + 2
    print("错误: 未在Excel第二行找到校准分类的'level1'列")
    sys.exit(1)


def append_to_excel(db_path, excel_path, domain="function"):
    """向已有Excel文件追加推理分类4列，列号动态计算"""
    if not os.path.isfile(excel_path):
        print(f"错误: Excel文件不存在: {excel_path}")
        sys.exit(1)

    rows = _read_db(db_path, _table_for_domain(domain))
    wb = load_workbook(excel_path)
    ws = wb.active

    # 动态检测校准分类列位置
    cal_l1, cal_l2, cal_l3 = _find_cal_columns(ws)

    # 推理分类从已有最大列之后开始
    # max_column可能包含合并单元格的空列，取实际有数据的最大列+1
    inf_start_col = ws.max_column + 1
    # 安全检查: 确保inf_start_col在cal_l3之后
    if inf_start_col <= cal_l3:
        inf_start_col = cal_l3 + 1

    # 检查已有数据行数是否与DB匹配
    existing_count = 0
    for row in range(DATA_START_ROW, ws.max_row + 1):
        if ws.cell(row=row, column=cal_l1).value is not None:
            existing_count += 1

    if existing_count != len(rows):
        print(f"警告: Excel数据行数({existing_count})与DB行数({len(rows)})不一致")

    _write_headers(ws, inf_start_col)
    last_data_row = _write_data_rows(ws, rows, cal_l1, cal_l2, cal_l3, inf_start_col)
    _write_accuracy_row(ws, last_data_row, inf_start_col)

    # 列宽: 只设置推理分类新增的列
    widths = {}
    for offset, key in enumerate(["l1", "l2", "l3", "result"]):
        widths[inf_start_col + offset] = INF_WIDTHS[key]
    _set_column_widths(ws, widths)

    wb.save(excel_path)
    print(f"追加完成: {excel_path} ({len(rows)}条数据, 推理分类从{get_column_letter(inf_start_col)}列开始)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将分类DB数据导出为Excel文件")
    parser.add_argument("db_path", help="DB文件路径")
    parser.add_argument("output_path", help="输出Excel文件路径")
    parser.add_argument("--append", action="store_true",
                        help="追加模式: 向已有Excel文件添加推理分类列（而非创建新文件）")
    parser.add_argument("--domain", choices=["function", "business"], default="function",
                        help="导出的分类域（默认 function）。单库 report.db 读 report_<domain> 表，缺失时回退 report 表")
    args = parser.parse_args()

    if args.append:
        append_to_excel(args.db_path, args.output_path, args.domain)
    else:
        export_db_to_excel(args.db_path, args.output_path, args.domain)
