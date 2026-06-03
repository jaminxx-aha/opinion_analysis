#!/usr/bin/env python3
"""
convert_classification.py - 将markdown分类树转换为JSON格式

一次性转换脚本，读取各应用的 classification.md 文件，
解析Unicode树形图，生成对应的 classification.json 文件。
"""

import os
import json
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
APPS_DIR = os.path.join(SKILL_DIR, "references", "apps")


def parse_classification_md(md_content):
    """解析markdown分类树，返回 { level1: { level2: [level3, ...] } } 结构"""

    tree = {}

    # 按 fenced code block 分割，每个 code block 是一个 level1 分类树
    code_blocks = re.findall(r'```\n(.*?)```', md_content, re.DOTALL)

    for block in code_blocks:
        lines = [l.rstrip() for l in block.strip().split('\n') if l.strip()]

        if not lines:
            continue

        # 第一行是 level1 根名
        level1 = lines[0].strip()
        current_level2 = None
        level2_dict = {}

        for line in lines[1:]:
            # 跳过纯 │ 分隔线
            if re.match(r'^│\s*$', line):
                continue

            # 去除box-drawing前缀，提取分类名
            # level2: ├── xxx 或 └── xxx (直接跟在根名下)
            l2_match = re.match(r'^[├└]──\s+(.+)$', line)
            if l2_match:
                current_level2 = l2_match.group(1).strip()
                level2_dict[current_level2] = []
                continue

            # level3: │   ├── xxx 或 │       ├── xxx 或     ├── xxx (在 └── 的level2下)
            l3_match = re.match(r'^[│\s]{0,4}[├└]──\s+(.+)$', line)
            if l3_match and current_level2:
                level3_name = l3_match.group(1).strip()
                level2_dict[current_level2].append(level3_name)
                continue

        if level1 and level2_dict:
            tree[level1] = level2_dict

    return tree


def classification_tree_to_text(tree):
    """将JSON分类树转为与原markdown格式相同的树形图文本"""

    # level1名称到section标题的映射
    heading_map = {
        "卡顿": "卡顿类问题",
        "响应慢/延迟": "响应慢/延迟类问题",
        "闪退/崩溃": "闪退/崩溃类问题",
        "启动异常": "启动异常类问题",
        "发热": "发热类问题",
        "内存异常": "内存异常类问题",
        "渲染异常": "渲染异常类问题",
        "网络异常": "网络异常类问题",
    }

    sections = []
    for level1, level2_dict in tree.items():
        heading = heading_map.get(level1, f"{level1}类问题")
        section_lines = [f"# {heading}", "", "```", level1]

        level2_keys = list(level2_dict.keys())
        for i, level2 in enumerate(level2_keys):
            level3_list = level2_dict[level2]
            is_last_l2 = (i == len(level2_keys) - 1)
            prefix_l2 = "└── " if is_last_l2 else "├── "
            section_lines.append(f"{prefix_l2}{level2}")

            cont_prefix = "    " if is_last_l2 else "│   "
            for j, level3 in enumerate(level3_list):
                is_last_l3 = (j == len(level3_list) - 1)
                prefix_l3 = "└── " if is_last_l3 else "├── "
                section_lines.append(f"{cont_prefix}{prefix_l3}{level3}")

            # 在非最后一个level2组之间加 │ 分隔线
            if not is_last_l2:
                section_lines.append("│")

        section_lines.append("```")
        section_lines.append("")
        sections.append("\n".join(section_lines))

    return "\n".join(sections)


def convert_all_apps():
    """转换所有应用的classification.md为classification.json"""

    app_names = [d for d in os.listdir(APPS_DIR)
                 if os.path.isdir(os.path.join(APPS_DIR, d))]

    print(f"发现 {len(app_names)} 个应用目录: {app_names}")

    for app_name in app_names:
        md_path = os.path.join(APPS_DIR, app_name, "classification.md")
        json_path = os.path.join(APPS_DIR, app_name, "classification.json")

        if not os.path.isfile(md_path):
            print(f"  [{app_name}] classification.md 不存在, 跳过")
            continue

        md_content = open(md_path, "r", encoding="utf-8").read()
        tree = parse_classification_md(md_content)

        # 统计信息
        l1_count = len(tree)
        l2_count = sum(len(v) for v in tree.values())
        l3_count = sum(sum(len(items) for items in v.values()) for v in tree.values())
        print(f"  [{app_name}] 解析完成: {l1_count}个一级, {l2_count}个二级, {l3_count}个三级分类")

        # 验证: 重新生成文本并对比
        regenerated = classification_tree_to_text(tree)
        # 只做结构验证，不逐字对比（格式可能有微小差异）
        reg_blocks = re.findall(r'```\n(.*?)```', regenerated, re.DOTALL)
        if len(reg_blocks) != l1_count:
            print(f"  [{app_name}] ⚠️ 警告: 重新生成code block数({len(reg_blocks)})与原始({l1_count})不一致!")

        # 写入JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2)
        print(f"  [{app_name}] 已写入: {json_path}")

        # 详细对比: 从JSON重新生成文本，检查分类名称是否完整
        print(f"  [{app_name}] 分类列表:")
        for l1, l2_dict in tree.items():
            print(f"    - {l1}: {len(l2_dict)}个子分类")
            for l2, l3_list in l2_dict.items():
                print(f"      - {l2}: {len(l3_list)}个叶子")


if __name__ == "__main__":
    convert_all_apps()
    print("\n转换完成!")