#!/usr/bin/env python3
"""
读取Excel表格数据并打印指定行范围

用法:
  python read_excel.py <Excel文件路径> [起始行号] [结束行号]

参数:
  Excel文件路径    必需
  起始行号         可选，从1开始（含表头），默认1
  结束行号         可选，默认为文件最后一行

示例:
  python read_excel.py data.xlsx                  # 打印全部数据
  python read_excel.py data.xlsx 1 10             # 打印第1到10行（含表头）
  python read_excel.py data.xlsx 5 20             # 打印第5到20行
"""

import sys
import pandas as pd


def read_excel_range(excel_path: str, start_row: int = 1, end_row: int = None):
    df = pd.read_excel(excel_path)

    # pandas行索引从0开始，用户输入从1开始（1=表头）
    # 表头占第1行，数据从第2行开始
    total_rows = len(df) + 1  # 含表头

    if end_row is None:
        end_row = total_rows

    # 输入验证
    if start_row < 1:
        print(f"读取文件错误：起始行号不能小于1")
        sys.exit(1)
    if start_row > total_rows:
        print(f"读取文件错误：起始行号 {start_row} 超出范围（总行数含表头: {total_rows}）")
        sys.exit(1)
    if end_row > total_rows:
        print(f"提示: 结束行号 {end_row} 超出范围，调整为 {total_rows}")
        end_row = total_rows
    if start_row > end_row:
        print(f"读取文件错误：起始行号 {start_row} 大于结束行号 {end_row}")
        sys.exit(1)

    # 构建输出：表头 + 数据行
    if start_row == 1:
        # 包含表头
        sliced = df.iloc[0:end_row - 1]  # 数据行：0到end_row-2
    else:
        # 不含表头，纯数据行
        # start_row=2 对应 df行0，start_row=N 对应 df行N-2
        sliced = df.iloc[start_row - 2:end_row - 1]

    # 打印表头（始终显示）
    print(f"文件: {excel_path}")
    print(f"总行数: {len(df)} 行数据 + 1 行表头 = {total_rows} 行")
    print(f"显示范围: 第 {start_row} 行 到 第 {end_row} 行")
    print()

    # 用 pandas 的 to_string 打印，对齐列宽
    if start_row == 1:
        print(sliced.to_string(index=True))
    else:
        # 补上表头信息，让用户知道列名
        columns = df.columns.tolist()
        header_line = " | ".join(columns)
        print(f"表头: {header_line}")
        print()
        # 重新标注行号
        display = sliced.copy()
        display.index = range(start_row, end_row + 1)[:len(display)]
        print(display.to_string(index=True))


def main():
    if len(sys.argv) < 2:
        print("用法: python read_excel.py <Excel文件路径> [起始行号] [结束行号]")
        print("  起始行号和结束行号从1开始（第1行为表头）")
        print("  默认: 起始行=1, 结束行=文件末尾")
        sys.exit(1)

    excel_path = sys.argv[1]
    start_row = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    end_row = int(sys.argv[3]) if len(sys.argv) > 3 else None

    try:
        read_excel_range(excel_path, start_row, end_row)
    except FileNotFoundError:
        print(f"读取文件错误：文件不存在 '{excel_path}'")
        sys.exit(1)
    except Exception as e:
        print(f"读取文件错误：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()