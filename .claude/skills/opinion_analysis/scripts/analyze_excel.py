#!/usr/bin/env python3
"""
批量舆情分析脚本

用法:
  准备数据模式: python analyze_excel.py <Excel文件路径> --prepare-only
  生成报告模式: python analyze_excel.py <分类结果JSON路径>

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


def resolve_app_name(app: str) -> str:
    """将应用别名转换为实际应用名"""
    if app in app_alias_map:
        return app_alias_map[app]
    return app


def prepare_excel_data(excel_path: str) -> dict:
    """
    读取Excel数据，准备供子Agent分类

    Args:
        excel_path: Excel文件路径

    Returns:
        包含原始数据的字典
    """

    # 读取Excel
    df = pd.read_excel(excel_path)

    # 检查必要列
    if "问题描述" not in df.columns:
        return {
            "error": "Excel 文件缺少'问题描述'列",
            "columns": df.columns.tolist()
        }

    # 检查是否有应用名列
    has_app_column = "应用名" in df.columns

    # 提取数据
    items = []
    for idx, row in df.iterrows():
        problem = str(row["问题描述"])

        # 获取应用名（如果有）
        app = ""
        if has_app_column:
            app = str(row["应用名"])
            app = resolve_app_name(app)

        # 保存原始数据
        raw_data = {}
        for col in df.columns:
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
        "total": len(items),
        "items": items,
        "apps_available": apps_in_folder  # 可用的应用描述列表
    }


def generate_report_from_result(result_path: str) -> dict:
    """
    从分类结果JSON生成可视化报告

    Args:
        result_path: 分类结果JSON路径

    Returns:
        报告生成信息
    """

    # 读取分类结果
    with open(result_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

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

    # 保存完整结果
    output_path = result_path.replace('.json', '_classified.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 生成可视化报告
    report_path = output_path.replace('.json', '_report.html')
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
    parser.add_argument('--output', help='输出文件路径')

    args = parser.parse_args()

    input_path = args.input

    # 判断输入类型
    if input_path.endswith('.xlsx') or input_path.endswith('.xls'):
        # Excel输入
        if args.prepare_only:
            # 只准备数据
            result = prepare_excel_data(input_path)

            # 确定输出路径
            if args.output:
                output_path = args.output
            else:
                excel_basename = os.path.basename(input_path).replace('.xlsx', '').replace('.xls', '')
                result_dir = os.path.join(os.getcwd(), excel_basename)
                os.makedirs(result_dir, exist_ok=True)
                output_path = os.path.join(result_dir, f"{excel_basename}_prepared.json")

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            print(f"数据已准备: {output_path}")
            print(f"总条数: {result['total']}")
            print("请使用子Agent对每条数据进行分类，分类完成后运行：")
            print(f"  python analyze_excel.py {output_path}")
        else:
            # 直接处理Excel（需要配合分类）
            print("请先使用 --prepare-only 准备数据，然后由子Agent分类后再生成报告")
            result = prepare_excel_data(input_path)
            print(json.dumps(result, ensure_ascii=False, indent=2))

    elif input_path.endswith('.json'):
        # JSON输入（已分类的数据）
        result = generate_report_from_result(input_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        if result.get("report_path"):
            print(f"\n可视化报告已生成: {result['report_path']}")

    else:
        print(f"不支持的输入格式: {input_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()