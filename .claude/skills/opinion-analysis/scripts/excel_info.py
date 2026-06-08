#!/usr/bin/env python3
"""
舆情分析辅助脚本 - 查看Excel列名和前3行数据（MD表格格式）

用法: python excel_info.py <Excel文件路径>
"""

import sys
import io

# Windows下强制UTF-8输出
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer') and (not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer') and (not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import pandas as pd

input_path = sys.argv[1]

if not (input_path.endswith('.xlsx') or input_path.endswith('.xls')):
    print(f"错误: 需要 Excel 文件路径（.xlsx 或 .xls），当前输入: {input_path}")
    sys.exit(1)

df = pd.read_excel(input_path)
columns = df.columns.tolist()

header = "| " + " | ".join(columns) + " |"
sep = "| " + " | ".join(["------" for _ in columns]) + " |"
print(header)
print(sep)
for _, row in df.head(min(3, len(df))).iterrows():
    vals = row.astype(str).tolist()
    print("| " + " | ".join(vals) + " |")