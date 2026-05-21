#!/usr/bin/env python3
"""
批量舆情分析脚本

用法: python analyze_excel.py <Excel文件路径> [输出文件路径]
输出: JSON 格式的分类结果和统计汇总，并自动生成可视化 HTML 报告
"""

import sys
import json
import os
import pandas as pd
import subprocess

# 获取脚本目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 导入配置和分类函数
from config import apps_in_folder
from classify_issue import classify_issue


def analyze_excel(excel_path: str, output_path: str = None, generate_report: bool = True) -> dict:
    """
    批量分析 Excel 文件中的舆情数据

    Args:
        excel_path: Excel 文件路径
        output_path: 输出文件路径（可选）
        generate_report: 是否生成可视化报告（默认 True）

    Returns:
        包含汇总和详细分类结果的字典
    """

    # 读取 Excel
    df = pd.read_excel(excel_path)

    # 检查必要列
    if "问题描述" not in df.columns:
        return {
            "error": "Excel 文件缺少'问题描述'列",
            "columns": df.columns.tolist()
        }

    # 检查是否有应用名列
    has_app_column = "应用名" in df.columns

    # 执行分类
    results = []
    summary = {
        "total": len(df),
        "classified": 0,
        "unrecognized_app": 0,
        "no_description": 0,
        "by_app": {},
        "by_module": {},
        "by_issue_type": {}
    }

    for idx, row in df.iterrows():
        problem = str(row["问题描述"])

        # 获取应用名
        if has_app_column:
            app = str(row["应用名"])
        else:
            # 从问题描述中推断应用名
            app = extract_app_from_problem(problem)

        # 执行分类
        result = classify_issue(app, problem)
        result["row_index"] = idx + 1

        # 保存原始数据（Excel中该行的所有列）
        raw_data = {}
        for col in df.columns:
            val = row[col]
            # 处理NaN和空值
            if pd.isna(val):
                raw_data[col] = ""
            else:
                raw_data[col] = str(val)
        result["raw_data"] = raw_data

        results.append(result)

        # 更新汇总统计
        if result["status"] == "success":
            summary["classified"] += 1
            cls = result["classification"]
            summary["by_app"][cls["app"]] = summary["by_app"].get(cls["app"], 0) + 1
            summary["by_module"][cls["module"]] = summary["by_module"].get(cls["module"], 0) + 1
            summary["by_issue_type"][cls["issue_type"]] = summary["by_issue_type"].get(cls["issue_type"], 0) + 1
        elif result["status"] == "unrecognized":
            summary["unrecognized_app"] += 1
        elif result["status"] == "no_description":
            summary["no_description"] += 1

    # 构建输出
    output = {
        "summary": summary,
        "details": results,
        "excel_source": excel_path
    }

    # 确定输出路径
    excel_basename = os.path.basename(excel_path).replace('.xlsx', '').replace('.xls', '')

    if not output_path:
        # 默认：在当前工作目录下以Excel文件名创建文件夹
        result_dir = os.path.join(os.getcwd(), excel_basename)
        os.makedirs(result_dir, exist_ok=True)
        output_path = os.path.join(result_dir, f"{excel_basename}_result.json")
    else:
        # 用户指定了路径，在该路径下以Excel文件名创建文件夹
        base_dir = os.path.abspath(output_path)
        result_dir = os.path.join(base_dir, excel_basename)
        os.makedirs(result_dir, exist_ok=True)
        output_path = os.path.join(result_dir, f"{excel_basename}_result.json")

    # 保存 JSON 结果
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 复制Excel文件到结果文件夹（用于下载）
    excel_copy_path = None
    if result_dir:
        excel_basename = os.path.basename(excel_path)
        excel_copy_path = os.path.join(result_dir, excel_basename)
        import shutil
        shutil.copy2(excel_path, excel_copy_path)

    # 生成可视化报告
    report_path = None
    if generate_report:
        # 报告路径与JSON在同一目录
        report_path = output_path.replace('.json', '_report.html')
        try:
            # 调用 generate_report.py
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
        "details_count": len(results),
        "json_path": output_path,
        "report_path": report_path
    }


def extract_app_from_problem(problem: str) -> str:
    """
    从问题描述中推断应用名

    Args:
        problem: 问题描述

    Returns:
        推断的应用名
    """

    # 直接匹配
    for app in apps_in_folder:
        if app in problem:
            return app

    # 间接推断
    if "刷短视频" in problem or "短视频" in problem:
        return "抖音"  # 默认推断为抖音
    if "朋友圈" in problem:
        return "微信"
    if "直播" in problem and "购物" in problem:
        return "抖音"
    if "笔记" in problem:
        return "小红书"

    # 无法识别
    return "未知"


def main():
    if len(sys.argv) < 2:
        print("用法: python analyze_excel.py <Excel文件路径> [输出文件路径]")
        print("示例: python analyze_excel.py 舆情数据.xlsx")
        print("      python analyze_excel.py 舆情数据.xlsx /path/to/result.json")
        print("")
        print("输出文件:")
        print("  未指定路径时，结果保存在Excel所在目录的'舆情分析结果'文件夹中")
        print("  - JSON 结果: 分类数据和统计汇总")
        print("  - HTML 报告: 可视化图表和详情表格")
        sys.exit(1)

    excel_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    result = analyze_excel(excel_path, output_path)

    # 输出汇总信息
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("report_path"):
        print(f"\n可视化报告已生成: {result['report_path']}")
        print("请用浏览器打开查看")


if __name__ == "__main__":
    main()