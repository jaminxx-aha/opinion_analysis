#!/usr/bin/env python3
"""
批量舆情分析脚本

用法:
  准备数据模式: python analyze_excel.py <Excel文件路径> --prepare-only
  生成报告模式: python analyze_excel.py <分类结果JSON路径>

新增参数:
  --app-column      指定应用名列名（默认自动识别）
  --problem-column  指定问题描述列名（默认自动识别）
  --output-dir      指定输出目录（默认在Excel文件所在目录）

输出:
  准备模式: JSON格式的原始数据（供子Agent分类）
  报告模式: 可视化HTML报告
"""

import sys
import json
import os
import pandas as pd
import subprocess
import argparse

# 获取脚本目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 导入配置
from config import apps_in_folder, app_alias_map


# 应用名列的关键词（用于自动识别）
APP_COLUMN_KEYWORDS = ['应用', 'app', '应用名', 'app名', '软件', '平台', '产品']

# 问题描述列的关键词（用于自动识别）
PROBLEM_COLUMN_KEYWORDS = ['问题', '描述', '问题描述', '反馈', '内容', '投诉', '问题描述']


def identify_column(columns: list, keywords: list, column_type: str) -> str:
    """
    自动识别列名

    Args:
        columns: Excel列名列表
        keywords: 匹配关键词列表
        column_type: 列类型描述（用于错误提示）

    Returns:
        匹配的列名，如果未找到则返回空字符串
    """
    # 优先精确匹配
    for col in columns:
        col_lower = col.lower().strip()
        for keyword in keywords:
            if col_lower == keyword.lower():
                return col

    # 其次包含匹配
    for col in columns:
        col_lower = col.lower().strip()
        for keyword in keywords:
            if keyword.lower() in col_lower:
                return col

    return ""


def resolve_app_name(app: str) -> str:
    """将应用别名转换为实际应用名"""
    if app in app_alias_map:
        return app_alias_map[app]
    return app


def prepare_excel_data(excel_path: str, app_column: str = None, problem_column: str = None) -> dict:
    """
    读取Excel数据，准备供子Agent分类

    Args:
        excel_path: Excel文件路径
        app_column: 应用名列名（可选，默认自动识别）
        problem_column: 问题描述列名（可选，默认自动识别）

    Returns:
        包含原始数据的字典
    """

    # 读取Excel
    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()

    # 自动识别或使用指定的列名
    if not app_column:
        app_column = identify_column(columns, APP_COLUMN_KEYWORDS, "应用名")

    if not problem_column:
        problem_column = identify_column(columns, PROBLEM_COLUMN_KEYWORDS, "问题描述")

    # 检查必要列是否存在
    if not problem_column:
        return {
            "error": f"Excel 文件无法识别'问题描述'列",
            "columns": columns,
            "hint": "请使用 --problem-column 参数指定列名，或在Excel中添加包含'问题'或'描述'关键词的列"
        }

    # 检查是否有应用名列（可选）
    has_app_column = bool(app_column) and app_column in columns

    # 提取数据
    items = []
    for idx, row in df.iterrows():
        problem = str(row[problem_column])

        # 获取应用名（如果有）
        app = ""
        if has_app_column:
            app = str(row[app_column])
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
        "columns_detected": {
            "app_column": app_column or "未识别",
            "problem_column": problem_column
        },
        "total": len(items),
        "items": items,
        "apps_available": apps_in_folder  # 可用的应用描述列表
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
    parser.add_argument('--prepare-only', action='store_true',
                        help='只准备数据，不进行分类（用于Excel输入）')
    parser.add_argument('--output-dir', help='输出目录路径')
    parser.add_argument('--app-column', help='应用名列名（默认自动识别）')
    parser.add_argument('--problem-column', help='问题描述列名（默认自动识别）')

    args = parser.parse_args()

    input_path = args.input

    # 判断输入类型
    if input_path.endswith('.xlsx') or input_path.endswith('.xls'):
        # Excel输入
        if args.prepare_only:
            # 只准备数据
            result = prepare_excel_data(input_path, args.app_column, args.problem_column)

            # 检查是否有错误
            if "error" in result:
                print(f"错误: {result['error']}")
                print(f"现有列名: {result['columns']}")
                print(f"提示: {result.get('hint', '')}")
                sys.exit(1)

            # 确定输出目录
            if args.output_dir:
                output_dir = args.output_dir
                os.makedirs(output_dir, exist_ok=True)
            else:
                # 默认在Excel文件所在目录
                output_dir = os.path.dirname(os.path.abspath(input_path))
                if not output_dir:
                    output_dir = os.getcwd()

            # 确定输出文件名
            excel_basename = os.path.basename(input_path).replace('.xlsx', '').replace('.xls', '')
            output_path = os.path.join(output_dir, f"{excel_basename}_prepared.json")

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            print(f"数据已准备: {output_path}")
            print(f"识别的列: 应用名={result['columns_detected']['app_column']}, 问题描述={result['columns_detected']['problem_column']}")
            print(f"总条数: {result['total']}")
            print("请使用子Agent对每条数据进行分类，分类完成后运行：")
            print(f"  python analyze_excel.py {output_path}")
        else:
            # 直接处理Excel（需要配合分类）
            print("请先使用 --prepare-only 准备数据，然后由子Agent分类后再生成报告")
            result = prepare_excel_data(input_path, args.app_column, args.problem_column)

            if "error" in result:
                print(f"错误: {result['error']}")
                print(f"现有列名: {result['columns']}")
                sys.exit(1)

            print(json.dumps(result, ensure_ascii=False, indent=2))

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