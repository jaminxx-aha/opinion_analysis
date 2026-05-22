#!/usr/bin/env python3
"""
批量舆情分析脚本

用法:
  查看Excel信息: python analyze_excel.py <Excel文件路径> --info
  准备数据模式: python analyze_excel.py <Excel文件路径> --prepare-only --app-column <列名> --problem-column <列名>
  生成报告模式: python analyze_excel.py <分类结果JSON路径>

参数:
  --info            只显示Excel字段信息和样本数据（用于判断列名）
  --prepare-only    准备数据供分类使用
  --app-column      指定应用名列名（必需）
  --problem-column  指定问题描述列名（必需）
  --output-dir      指定输出目录（默认在Excel文件所在目录）

输出:
  --info: 显示列名和前10行样本数据
  --prepare-only: JSON格式的原始数据（供子Agent分类）
  JSON输入: 可视化HTML报告
"""

import sys
import json
import os
import pandas as pd
import subprocess
import argparse
import shutil  # 添加shutil用于复制文件

# 获取脚本目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 导入配置
from config import apps_in_folder, app_alias_map


def get_excel_info(excel_path: str) -> dict:
    """
    读取Excel文件，获取字段信息和样本数据
    用于判断哪个列是应用名列、哪个是问题描述列

    Args:
        excel_path: Excel文件路径

    Returns:
        包含字段信息和样本数据的字典
    """
    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()
    sample_size = min(10, len(df))

    # 获取每列的前几行样本数据，带索引号
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
        'apps_available': apps_in_folder,  # 已知的应用列表
        'app_aliases': app_alias_map  # 应用别名映射
    }


def resolve_app_name(app: str) -> str:
    """将应用别名转换为实际应用名"""
    if app in app_alias_map:
        return app_alias_map[app]
    return app


def prepare_excel_data(excel_path: str, app_column: str, problem_column: str) -> dict:
    """
    读取Excel数据，准备供子Agent分类
    支持列名或列索引（数字，从1开始）

    Args:
        excel_path: Excel文件路径
        app_column: 应用名列名或列索引（可选）
        problem_column: 问题描述列名或列索引（必需）

    Returns:
        包含原始数据的字典
    """

    # 读取Excel
    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()

    # 解析列名/列索引
    def resolve_column(col_spec, columns):
        """将列名或列索引转换为实际列名"""
        if col_spec is None:
            return None
        # 如果是数字，当作列索引处理（从1开始）
        try:
            idx = int(col_spec)
            if 1 <= idx <= len(columns):
                return columns[idx - 1]
            else:
                return None
        except ValueError:
            # 不是数字，当作列名处理
            return col_spec

    problem_col_name = resolve_column(problem_column, columns)
    app_col_name = resolve_column(app_column, columns) if app_column else None

    # 检查必要列是否存在
    if problem_col_name not in columns:
        return {
            "error": f"指定的'问题描述'列 '{problem_column}' 不存在",
            "columns": columns,
            "columns_with_index": {i+1: col for i, col in enumerate(columns)},
            "hint": "请先使用 --info 查看Excel列名，然后指定正确的列名或列索引（数字，从1开始）"
        }

    # 检查应用名列是否存在（可选）
    has_app_column = app_col_name and app_col_name in columns

    # 提取数据
    items = []
    for idx, row in df.iterrows():
        problem = str(row[problem_col_name])

        # 获取应用名（如果有）
        app = ""
        if has_app_column:
            app = str(row[app_col_name])
            app = resolve_app_name(app)

        # 保存原始数据
        raw_data = {}
        for col in columns:
            val = row[col]
            if pd.isna(val):
                raw_data[col] = ""
            else:
                raw_data[col] = str(val)

        items.append({
            "row_index": idx + 1,
            "app": app,
            "problem": problem,
            "raw_data": raw_data
        })

    return {
        "excel_source": excel_path,
        "columns_used": {
            "app_column": app_col_name or "未指定",
            "problem_column": problem_col_name
        },
        "total": len(items),
        "items": items,
        "apps_available": apps_in_folder
    }


def generate_report_from_result(result_path: str, output_dir: str = None) -> dict:
    """
    从分类结果JSON生成可视化报告

    Args:
        result_path: 分类结果JSON路径
        output_dir: 输出目录（可选，默认在JSON文件所在目录）

    Returns:
        报告生成信息
    """

    # 读取分类结果
    with open(result_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 确定输出目录
    if not output_dir:
        output_dir = os.path.dirname(os.path.abspath(result_path))
    else:
        os.makedirs(output_dir, exist_ok=True)

    # 计算统计
    summary = {
        "total": len(data.get("items", [])),
        "classified": 0,
        "unrecognized_app": 0,
        "no_description": 0,
        "by_app": {},
        "by_module": {},
        "by_issue_type": {}
    }

    details = []
    for item in data.get("items", []):
        classification = item.get("classification")

        if classification:
            summary["classified"] += 1
            cls = classification
            summary["by_app"][cls["app"]] = summary["by_app"].get(cls["app"], 0) + 1
            summary["by_module"][cls["module"]] = summary["by_module"].get(cls["module"], 0) + 1
            summary["by_issue_type"][cls["issue_type"]] = summary["by_issue_type"].get(cls["issue_type"], 0) + 1
            details.append({
                "input": item["problem"],
                "status": "success",
                "classification": classification,
                "raw_data": item.get("raw_data", {})
            })
        elif item.get("status") == "unrecognized":
            summary["unrecognized_app"] += 1
            details.append({
                "input": item["problem"],
                "status": "unrecognized",
                "output": "无法识别应用"
            })
        elif item.get("status") == "no_description":
            summary["no_description"] += 1
            details.append({
                "input": item["problem"],
                "status": "no_description",
                "output": f"{item.get('app', '未知')}没有描述"
            })
        else:
            details.append({
                "input": item["problem"],
                "status": "pending",
                "output": "待分类"
            })

    # 构建完整输出
    output = {
        "summary": summary,
        "details": details,
        "excel_source": data.get("excel_source", "")
    }

    # 确定输出文件名
    json_basename = os.path.basename(result_path).replace('.json', '').replace('_prepared', '')
    output_path = os.path.join(output_dir, f"{json_basename}_classified.json")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 生成可视化报告
    report_path = os.path.join(output_dir, f"{json_basename}_report.html")
    try:
        subprocess.run([
            sys.executable,
            os.path.join(SCRIPT_DIR, 'generate_report.py'),
            output_path,
            report_path
        ], check=True)
    except Exception as e:
        print(f"生成可视化报告失败: {e}")
        report_path = None

    return {
        "summary": summary,
        "json_path": output_path,
        "report_path": report_path
    }


def main():
    parser = argparse.ArgumentParser(description='舆情数据分析脚本')
    parser.add_argument('input', help='输入文件路径（Excel或JSON）')
    parser.add_argument('--info', action='store_true',
                        help='只显示Excel字段信息和样本数据（用于判断列名）')
    parser.add_argument('--prepare-only', action='store_true',
                        help='准备数据供分类使用（需配合 --app-column 和 --problem-column）')
    parser.add_argument('--app-column', help='应用名列名')
    parser.add_argument('--problem-column', help='问题描述列名')
    parser.add_argument('--output-dir', help='输出目录路径')

    args = parser.parse_args()

    input_path = args.input

    # 判断输入类型
    if input_path.endswith('.xlsx') or input_path.endswith('.xls'):
        # Excel输入

        if args.info:
            # 只显示Excel信息
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
            print("请根据以上信息判断哪个列是应用名列、哪个是问题描述列")
            print("然后使用以下命令准备数据（可用列索引号代替列名）：")
            print(f"  python analyze_excel.py {input_path} --prepare-only --app-column <列索引或列名> --problem-column <列索引或列名>")
            print("示例（用索引号）：")
            print(f"  python analyze_excel.py {input_path} --prepare-only --app-column 1 --problem-column 2")

        elif args.prepare_only:
            # 准备数据 - 必须手动指定参数（支持列索引号）
            if not args.problem_column:
                print("错误: 必须指定 --problem-column 参数")
                print("请先使用 --info 查看Excel列名和索引号，然后指定问题描述列")
                sys.exit(1)

            app_column = args.app_column
            problem_column = args.problem_column

            result = prepare_excel_data(input_path, app_column, problem_column)

            # 检查是否有错误
            if "error" in result:
                print(f"错误: {result['error']}")
                print(f"现有列名: {result['columns']}")
                print(f"提示: {result.get('hint', '')}")
                sys.exit(1)

            # 确定输出目录（按SKILL.md步骤0的逻辑）
            # 获取Excel文件基础名（用于创建子目录）
            excel_basename = os.path.basename(input_path).replace('.xlsx', '').replace('.xls', '')

            if args.output_dir:
                # 用户指定了输出路径
                user_output = args.output_dir
                if os.path.exists(user_output):
                    if os.path.isdir(user_output):
                        # 存在且是文件夹
                        output_base = user_output
                    else:
                        # 存在但不是文件夹，报错
                        print(f"错误: 输出路径 '{user_output}' 不是文件夹")
                        sys.exit(1)
                else:
                    # 不存在，创建该文件夹
                    os.makedirs(user_output, exist_ok=True)
                    output_base = user_output
            else:
                # 用户未指定输出路径，使用 ./output
                output_base = os.path.join(os.getcwd(), 'output')
                if not os.path.exists(output_base):
                    os.makedirs(output_base, exist_ok=True)

            # 在output_base下创建以Excel文件名命名的子目录
            output_dir = os.path.join(output_base, excel_basename)
            os.makedirs(output_dir, exist_ok=True)

            # 复制原始Excel文件到output_dir（用于HTML报告下载）
            excel_copy_path = os.path.join(output_dir, os.path.basename(input_path))
            if os.path.abspath(input_path) != os.path.abspath(excel_copy_path):
                shutil.copy2(input_path, excel_copy_path)

            # 确定输出文件名
            output_path = os.path.join(output_dir, f"{excel_basename}_prepared.json")

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            print(f"数据已准备: {output_path}")
            print(f"使用的列: 应用名={result['columns_used']['app_column']}, 问题描述={result['columns_used']['problem_column']}")
            print(f"总条数: {result['total']}")
            print("请使用子Agent对每条数据进行分类，分类完成后运行：")
            print(f"  python analyze_excel.py {output_path}")

        else:
            # 未指定模式
            print("请指定操作模式:")
            print("  --info          查看Excel字段信息和样本数据")
            print("  --prepare-only  准备数据供分类使用")
            sys.exit(1)

    elif input_path.endswith('.json'):
        # JSON输入（已分类的数据）
        result = generate_report_from_result(input_path, args.output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if result.get("report_path"):
            print(f"\n可视化报告已生成: {result['report_path']}")

    else:
        print(f"不支持的输入格式: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()