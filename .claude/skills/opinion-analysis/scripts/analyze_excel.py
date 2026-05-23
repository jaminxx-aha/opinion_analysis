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

    report_path = os.path.join(output_dir, "report.html")

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


def resolve_column(col_spec, columns):
    """将列索引或列名转换为实际列名"""
    if col_spec is None:
        return None
    try:
        idx = int(col_spec)
        if 1 <= idx <= len(columns):
            return columns[idx - 1]
        return None
    except ValueError:
        return col_spec


def get_app_distribution(df, app_col_name):
    """获取应用名列的分布信息"""
    if not app_col_name:
        return None

    raw_values = df[app_col_name].dropna().astype(str).tolist()
    resolved = {}
    for v in raw_values:
        app = v.strip()
        if app in app_alias_map:
            app = app_alias_map[app]
        resolved[app] = resolved.get(app, 0) + 1

    sorted_apps = sorted(resolved.items(), key=lambda x: -x[1])
    is_single = len(sorted_apps) == 1
    single_app = sorted_apps[0][0] if is_single else None

    return {
        'distribution': sorted_apps,
        'is_single_app': is_single,
        'single_app': single_app,
    }


def main():
    parser = argparse.ArgumentParser(description='舆情数据分析脚本')
    parser.add_argument('input', help='输入文件路径（Excel、JSON或DB）')
    parser.add_argument('--info', action='store_true',
                        help='只显示Excel字段信息和样本数据（用于判断列名）')
    parser.add_argument('--app-column', help='应用名列索引（从1开始）或列名，用于显示应用名分布')
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

            # 如果指定了应用名列，显示应用名分布
            if args.app_column:
                df = pd.read_excel(input_path)
                columns = df.columns.tolist()
                app_col_name = resolve_column(args.app_column, columns)
                if app_col_name and app_col_name in columns:
                    app_dist = get_app_distribution(df, app_col_name)
                    print("=== 应用名分布 ===")
                    dist_str = ", ".join(f"{app}({cnt})" for app, cnt in app_dist['distribution'])
                    print(f"{dist_str} — 单一应用")
                    if app_dist['single_app']:
                        print(f"所有数据均属于【{app_dist['single_app']}】，子Agent无需读取应用描述，只需在提示词中嵌入该应用描述即可")
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