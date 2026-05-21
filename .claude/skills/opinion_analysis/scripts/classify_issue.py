#!/usr/bin/env python3
"""
单条舆情分类脚本

5用法: python classify_issue.py <应用名> <问题描述>
输出: JSON 格式的分类结果
"""

import sys
import json
import os

# 获取脚本目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 导入配置
from config import apps_in_folder, classification_rules, issue_type_map, app_alias_map


def resolve_app_name(app: str) -> str:
    """
    将应用别名转换为实际应用名

    Args:
        app: 输入的应用名或别名

    Returns:
        实际应用名（如wechat -> 微信）
    """
    # 如果在别名映射中找到，返回实际应用名
    if app in app_alias_map:
        return app_alias_map[app]
    # 否则返回原应用名
    return app


def classify_issue(app: str, problem_desc: str) -> dict:
    """
    对单条舆情问题进行分类

    Args:
        app: 应用名称（可以是别名，如wechat）
        problem_desc: 问题描述

    Returns:
        分类结果字典
    """

    # 将别名转换为实际应用名
    original_app = app
    resolved_app = resolve_app_name(app)

    # 检查是否为未知应用
    if resolved_app == "未知":
        return {
            "input": problem_desc,
            "status": "unrecognized",
            "output": "无法识别应用"
        }

    # 检查应用是否在 apps 目录中
    if resolved_app not in apps_in_folder:
        return {
            "input": problem_desc,
            "status": "no_description",
            "output": f"{resolved_app}没有描述"
        }

    # 使用实际应用名进行分类
    app = resolved_app

    # 尝试匹配分类规则
    rules = classification_rules.get(app, {})
    classification = None

    for module, module_info in rules.items():
        # 检查是否匹配模块关键词
        keywords = module_info.get("keywords", [])
        if any(kw in problem_desc for kw in keywords):
            # 检查页面匹配
            for page_key, page_info in module_info.get("pages", {}).items():
                if page_key in problem_desc:
                    # 检查问题匹配
                    for issue_key, issue_detail in page_info.get("issues", {}).items():
                        if issue_key in problem_desc:
                            issue_type = issue_type_map.get(issue_key, "功能问题")
                            classification = {
                                "app": app,
                                "module": module,
                                "page": page_info["page"],
                                "issue_type": issue_type,
                                "issue_detail": issue_detail,
                                "full_path": f"{app} > {module} > {page_info['page']} > {issue_type} > {issue_detail}"
                            }
                            break
                    if classification:
                        break
            if classification:
                break

    # 如果没有精确匹配，进行通用分类
    if not classification:
        if "卡顿" in problem_desc:
            classification = {
                "app": app,
                "module": "通用模块",
                "page": "通用页面",
                "issue_type": "性能问题",
                "issue_detail": "卡顿",
                "full_path": f"{app} > 通用模块 > 通用页面 > 性能问题 > 卡顿"
            }
        elif "加载" in problem_desc and ("不出" in problem_desc or "失败" in problem_desc or "慢" in problem_desc):
            classification = {
                "app": app,
                "module": "通用模块",
                "page": "通用页面",
                "issue_type": "性能问题",
                "issue_detail": "加载失败",
                "full_path": f"{app} > 通用模块 > 通用页面 > 性能问题 > 加载失败"
            }
        elif "模糊" in problem_desc or "显示" in problem_desc:
            classification = {
                "app": app,
                "module": "通用模块",
                "page": "通用页面",
                "issue_type": "显示问题",
                "issue_detail": "显示异常",
                "full_path": f"{app} > 通用模块 > 通用页面 > 显示问题 > 显示异常"
            }
        else:
            classification = {
                "app": app,
                "module": "通用模块",
                "page": "通用页面",
                "issue_type": "功能问题",
                "issue_detail": "功能异常",
                "full_path": f"{app} > 通用模块 > 通用页面 > 功能问题 > 功能异常"
            }

    return {
        "input": problem_desc,
        "status": "success",
        "original_app": original_app,
        "resolved_app": resolved_app,
        "classification": classification,
        "reasoning": f"根据问题描述'{problem_desc}'，推断为{classification['full_path']}"
    }


def main():
    if len(sys.argv) < 3:
        print("用法: python classify_issue.py <应用名或别名> <问题描述>")
        print("示例: python classify_issue.py 抖音 '刷抖音视频卡顿严重'")
        print("示例: python classify_issue.py wechat '小程序打开失败'")
        sys.exit(1)

    app = sys.argv[1]
    problem = sys.argv[2]

    result = classify_issue(app, problem)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()