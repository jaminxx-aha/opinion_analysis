#!/usr/bin/env python3
"""
舆情分析主脚本

用法:
  初始化输出目录: python analyze_excel.py <Excel文件路径> --init-output <输出目录>
  查看Excel信息:   python analyze_excel.py <Excel文件路径> --info
  验证分类完整性:  python analyze_excel.py <DB路径> --verify <期望行数>
  生成报告:        python analyze_excel.py <DB或JSON路径> [--output-dir <目录>]
"""

import sys
import os
import io

# Windows下强制UTF-8输出
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import shutil
import sqlite3
import pandas as pd
import subprocess
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

from config import app_alias_map, resolve_column, SUPPORTED_APPS, get_app_dir


def get_excel_info(excel_path: str) -> dict:
    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()
    sample_size = min(3, len(df))

    columns_with_index = {i+1: col for i, col in enumerate(columns)}
    column_samples = {}
    for i, col in enumerate(columns):
        samples = df[col].head(sample_size).astype(str).tolist()
        column_samples[f"{i+1}:{col}"] = samples

    return {
        'df': df,
        'excel_source': excel_path,
        'columns': columns,
        'columns_with_index': columns_with_index,
        'column_samples': column_samples,
        'total_rows': len(df),
        'sample_size': sample_size,
        'apps_available': SUPPORTED_APPS,
        'app_aliases': app_alias_map,
    }


def init_output_dir(excel_path: str, output_dir: str) -> None:
    """创建输出目录、复制Excel文件"""
    os.makedirs(output_dir, exist_ok=True)

    excel_basename = os.path.basename(excel_path)
    dest = os.path.join(output_dir, excel_basename)
    if not os.path.isfile(dest):
        shutil.copy2(excel_path, dest)
        print(f"已复制Excel文件到: {dest}")
    else:
        print(f"Excel文件已存在: {dest}")

    print(f"输出目录已初始化: {output_dir}")


def verify_db(db_path: str, expected_count: int) -> None:
    """验证数据库行数是否与期望一致"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM report")
    actual_count = cursor.fetchone()[0]
    conn.close()

    if actual_count == expected_count:
        print(f"验证通过: 数据库 {actual_count} 条，期望 {expected_count} 条")
    else:
        print(f"警告: 数据库 {actual_count} 条，期望 {expected_count} 条，有 {expected_count - actual_count} 条数据丢失")


def generate_report(input_path: str, output_dir: str = None) -> str:
    """调用generate_report.py生成可视化HTML报告"""
    if not output_dir:
        output_dir = os.path.dirname(os.path.abspath(input_path))
    else:
        os.makedirs(output_dir, exist_ok=True)

    report_path = os.path.join(output_dir, "report.html")
    template_path = os.path.join(SKILL_DIR, "assets", "report_template.html")

    try:
        subprocess.run([
            sys.executable,
            os.path.join(SCRIPT_DIR, 'generate_report.py'),
            input_path,
            report_path,
            template_path,
        ], check=True)
    except Exception as e:
        print(f"生成可视化报告失败: {e}")
        return None

    return report_path


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

    # 检查识别出的应用是否在支持列表中
    supported_check = {}
    for app_name, count in sorted_apps:
        has_kb = get_app_dir(SKILL_DIR, app_name) is not None
        supported_check[app_name] = {"count": count, "supported": has_kb}

    return {
        'distribution': sorted_apps,
        'supported_check': supported_check,
        'is_single_app': is_single,
        'single_app': single_app,
    }


def main():
    parser = argparse.ArgumentParser(description='舆情数据分析主脚本')
    parser.add_argument('input', help='输入文件路径（Excel、JSON或DB）')
    parser.add_argument('--info', action='store_true',
                        help='显示Excel字段信息和样本数据（用于判断列名）')
    parser.add_argument('--init-output', metavar='DIR',
                        help='初始化输出目录，复制Excel文件并缓存数据')
    parser.add_argument('--verify', type=int, metavar='N',
                        help='验证数据库行数是否等于N')
    parser.add_argument('--app-column', help='应用名列索引（从1开始）或列名，用于显示应用名分布')
    parser.add_argument('--output-dir', help='输出目录路径')

    args = parser.parse_args()
    input_path = args.input

    # 初始化输出目录模式
    if args.init_output:
        if not (input_path.endswith('.xlsx') or input_path.endswith('.xls')):
            print("错误: --init-output 需要Excel文件路径")
            sys.exit(1)
        init_output_dir(input_path, args.init_output)
        return

    # 验证模式
    if args.verify:
        if not input_path.endswith('.db'):
            print("错误: --verify 需要DB文件路径")
            sys.exit(1)
        verify_db(input_path, args.verify)
        return

    # Excel信息模式
    if input_path.endswith('.xlsx') or input_path.endswith('.xls'):
        if args.info:
            result = get_excel_info(input_path)
            df = result['df']

            print("=== Excel 文件信息 ===")
            print(f"文件路径: {result['excel_source']}")
            print(f"总行数: {result['total_rows']}")
            print()
            print("=== 列名（带索引号）===")
            for idx, col in result['columns_with_index'].items():
                print(f"  [{idx}] {col}")
            print()
            print("=== 各列样本数据（前3行）===")
            for col, samples in result['column_samples'].items():
                print(f"\n【{col}】")
                for i, s in enumerate(samples):
                    print(f"  {i+1}. {s}")
            print()
            print("=== 已知的应用名和别名 ===")
            print(f"支持分类的应用: {result['apps_available']}")
            print(f"别名映射: {result['app_aliases']}")
            print()

            # 应用名分布（不再重复读取Excel）
            if args.app_column:
                columns = result['columns']
                app_col_name = resolve_column(args.app_column, columns)
                if app_col_name and app_col_name in columns:
                    app_dist = get_app_distribution(df, app_col_name)
                    print("=== 应用名分布 ===")
                    for app_name, info in app_dist['supported_check'].items():
                        status = "支持分类" if info['supported'] else "不支持（将归为未知问题）"
                        print(f"  {app_name}: {info['count']}条 — {status}")
                    print()

            print("请根据以上信息判断应用名列和问题描述列的索引号")
        else:
            print("请指定操作模式:")
            print("  --info            查看Excel字段信息")
            print("  --init-output DIR 初始化输出目录")
            sys.exit(1)

    # 生成报告模式
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