#!/usr/bin/env python3
"""
舆情分析脚本

用法:
  查看Excel信息: python analyze_excel.py <Excel文件路径> --info
  生成报告模式: python analyze_excel.py <分类结果JSON或DB路径> [--output-dir <目录>]

参数:
  --info            只显示Excel字段信息和样本数据（用于判断列名）
  --output-dir      指定输出目录（默认在输入文件所在目录）

输出:
  --info: 显示列名和前10行样本数据
  JSON/DB输入: 可视化HTML报告（由generate_report.py生成）
"""

import sys
import os
import pandas as pd
import subprocess
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

from config import apps_in_folder, app_alias_map


def get_excel_info(excel_path: str) -> dict:
    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()
    sample_size = min(10, len(df))

    columns_with_index = {i+1: col for i, col in enumerate(columns)}
    column_samples = {}
    for i, col in enumerate(columns):
        samples = df[col].head(sample_size).astype(str).tolist()
        column_samples[f"{i+1}:{col}"] = samples

    return {
        'excel_source': excel_path,
        'columns': columns,
        'columns_with_index': columns_with_index,
        'column_samples': column_samples,
        'total_rows': len(df),
        'sample_size': sample_size,
        'apps_available': apps_in_folder,
        'app_aliases': app_alias_map
    }


def generate_report(input_path: str, output_dir: str = None) -> str:
    """调用generate_report.py生成可视化HTML报告"""
    if not output_dir:
        output_dir = os.path.dirname(os.path.abspath(input_path))
    else:
        os.makedirs(output_dir, exist_ok=True)

    # 确定输出HTML路径
    basename = os.path.basename(input_path)
    for ext in ['.json', '.db']:
        if basename.endswith(ext):
            basename = basename[:-len(ext)]
    for suffix in ['_classified', '_prepared']:
        if basename.endswith(suffix):
            basename = basename[:-len(suffix)]

    report_path = os.path.join(output_dir, f"{basename}_report.html")

    try:
        subprocess.run([
            sys.executable,
            os.path.join(SCRIPT_DIR, 'generate_report.py'),
            input_path,
            report_path
        ], check=True)
    except Exception as e:
        print(f"生成可视化报告失败: {e}")
        return None

    return report_path


def main():
    parser = argparse.ArgumentParser(description='舆情数据分析脚本')
    parser.add_argument('input', help='输入文件路径（Excel、JSON或DB）')
    parser.add_argument('--info', action='store_true',
                        help='只显示Excel字段信息和样本数据（用于判断列名）')
    parser.add_argument('--output-dir', help='输出目录路径')

    args = parser.parse_args()
    input_path = args.input

    if input_path.endswith('.xlsx') or input_path.endswith('.xls'):
        if args.info:
            result = get_excel_info(input_path)
            print("=== Excel 文件信息 ===")
            print(f"文件路径: {result['excel_source']}")
            print(f"总行数: {result['total_rows']}")
            print()
            print("=== 列名（带索引号）===")
            for idx, col in result['columns_with_index'].items():
                print(f"  [{idx}] {col}")
            print()
            print("=== 各列样本数据（前10行）===")
            for col, samples in result['column_samples'].items():
                print(f"\n【{col}】")
                for i, s in enumerate(samples):
                    print(f"  {i+1}. {s}")
            print()
            print("=== 已知的应用名和别名 ===")
            print(f"应用列表: {result['apps_available']}")
            print(f"别名映射: {result['app_aliases']}")
            print()
            print("请根据以上信息判断应用名列和问题描述列的索引号")
            print("然后使用 fetch_data.py 分批读取数据并分类：")
            print(f"  python scripts/fetch_data.py {input_path} --app-column <索引> --problem-column <索引> --start 1 --end 5")
        else:
            print("请指定操作模式:")
            print("  --info  查看Excel字段信息和样本数据")
            sys.exit(1)

    elif input_path.endswith('.db') or input_path.endswith('.json'):
        report_path = generate_report(input_path, args.output_dir)
        if report_path:
            print(f"\n可视化报告已生成: {report_path}")
        else:
            sys.exit(1)

    else:
        print(f"不支持的输入格式: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()