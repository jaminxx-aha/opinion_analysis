#!/usr/bin/env python3
"""
舆情周期对比报告生成脚本

对比两个不同时期的舆情分类报告（如本周 vs 上周），
展示分类分布、数量和占比的变化趋势。

用法: python compare_period.py <db_path_a> <db_path_b> [--output-dir DIR] [--label-a LABEL] [--label-b LABEL]

参数:
  db_path_a    基准期 db 文件路径（如上周）
  db_path_b    对比期 db 文件路径（如本周）
  --output-dir 输出目录（默认取 db_b 所在目录）
  --label-a    报告A标签（默认 "报告A"）
  --label-b    报告B标签（默认 "报告B"）
"""

import sys
import os
import io

# Windows 下强制 UTF-8 输出
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer') and (not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer') and (not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import json
import argparse
from datetime import datetime
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_TEMPLATE = os.path.join(SKILL_DIR, "assets", "compare_period_template.html")

# 导入 generate_report 的 DB 读取和模板渲染函数
sys.path.insert(0, SCRIPT_DIR)
from generate_report import read_data_from_db, render_template


def find_xlsx_in_dir(dir_path: str) -> str:
    """查找目录中的 xlsx 文件名"""
    for f in os.listdir(dir_path):
        if f.endswith('.xlsx') or f.endswith('.xls'):
            return f
    return ''


def get_db_mtime(db_path: str) -> str:
    """获取 db 文件的修改时间"""
    mtime = os.path.getmtime(db_path)
    return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')


def compute_distribution(details: list, total: int, level: str) -> dict:
    """
    计算某一层级分类的频次分布

    level: 'level1', 'level2', 'level3'
    返回: {分类名: count}
    """
    counter = Counter()
    for item in details:
        cls = item.get('classification', {})
        if not cls:
            continue
        val = cls.get(level, '')
        if val and val != '其他问题' or (level == 'level1' and val == '其他问题'):
            # 对于 level1，其他问题也算一个分类
            if level == 'level1':
                counter[val] += 1
            elif val:
                counter[val] += 1
    return dict(counter)


def compute_level2_by_level1(details: list) -> dict:
    """
    计算按 level1 分组的 level2 分布

    返回: {level1名: {level2名: count}}
    """
    result = {}
    for item in details:
        cls = item.get('classification', {})
        if not cls:
            continue
        l1 = cls.get('level1', '')
        l2 = cls.get('level2', '')
        if l1 and l2:
            if l1 not in result:
                result[l1] = Counter()
            result[l1][l2] += 1
    # 将 Counter 转为 dict
    return {k: dict(v) for k, v in result.items()}


def compute_level3_by_level1_level2(details: list) -> dict:
    """
    计算按 level1.level2 分组的 level3 分布

    返回: {level1名: {level2名: {level3名: count}}}
    """
    result = {}
    for item in details:
        cls = item.get('classification', {})
        if not cls:
            continue
        l1 = cls.get('level1', '')
        l2 = cls.get('level2', '')
        l3 = cls.get('level3', '')
        if l1 and l2 and l3:
            if l1 not in result:
                result[l1] = {}
            if l2 not in result[l1]:
                result[l1][l2] = Counter()
            result[l1][l2][l3] += 1
    # 将 Counter 转为 dict
    return {l1: {l2: dict(v) for l2, v in sub.items()} for l1, sub in result.items()}


def build_comparison_data(dist_a: dict, dist_b: dict, total_a: int, total_b: int) -> dict:
    """
    构建两个分布的对比数据

    返回: {分类名: {a, b, pct_a, pct_b, delta, delta_pct}}
    """
    all_keys = sorted(set(list(dist_a.keys()) + list(dist_b.keys())))
    result = {}
    for key in all_keys:
        count_a = dist_a.get(key, 0)
        count_b = dist_b.get(key, 0)
        pct_a = round(count_a / total_a * 100, 2) if total_a > 0 else 0
        pct_b = round(count_b / total_b * 100, 2) if total_b > 0 else 0
        delta = count_b - count_a
        delta_pct = round(pct_b - pct_a, 2)
        result[key] = {
            'a': count_a,
            'b': count_b,
            'pct_a': pct_a,
            'pct_b': pct_b,
            'delta': delta,
            'delta_pct': delta_pct,
        }
    return result


def build_nested_comparison(level_dist_a: dict, level_dist_b: dict,
                             total_a: int, total_b: int) -> dict:
    """
    构建嵌套分布对比（level2 按 level1 分组，或 level3 按 level1.level2 分组）

    level_dist_a/b: {group_key: {sub_key: count}}
    返回: {group_key: {sub_key: {a, b, pct_a, pct_b, delta, delta_pct}}}
    """
    all_groups = sorted(set(list(level_dist_a.keys()) + list(level_dist_b.keys())))
    result = {}
    for group in all_groups:
        sub_a = level_dist_a.get(group, {})
        sub_b = level_dist_b.get(group, {})
        # 计算该 group 下的 total 用于 pct
        group_total_a = sum(sub_a.values()) if sub_a else 0
        group_total_b = sum(sub_b.values()) if sub_b else 0
        result[group] = build_comparison_data(sub_a, sub_b, total_a, total_b)
    return result


def extract_versions(details: list) -> list:
    """提取版本号列表（唯一值，排序，包含空版本标记）"""
    versions = set()
    has_empty = False
    for item in details:
        ver = item.get('version', '')
        if ver:
            versions.add(ver)
        else:
            has_empty = True
    result = sorted(versions)
    if has_empty:
        result.append('')  # 空版本号作为可选项
    return result


def generate_compare_report(db_path_a: str, db_path_b: str,
                             output_dir: str = None,
                             label_a: str = None, label_b: str = None,
                             template_path: str = None) -> str:
    """生成周期对比报告"""

    if not template_path:
        template_path = DEFAULT_TEMPLATE

    # 读取两个 db 的数据
    data_a = read_data_from_db(db_path_a)
    data_b = read_data_from_db(db_path_b)

    summary_a = data_a['summary']
    summary_b = data_b['summary']
    details_a = data_a['details']
    details_b = data_b['details']

    total_a = summary_a['total']
    total_b = summary_b['total']

    # ─── 1. 汇总对比 ───
    summary_comparison = {}
    for key in ['total', 'classified', 'unknown_issue', 'infer_failed']:
        val_a = summary_a.get(key, 0)
        val_b = summary_b.get(key, 0)
        pct_a = round(val_a / total_a * 100, 2) if total_a > 0 else 0
        pct_b = round(val_b / total_b * 100, 2) if total_b > 0 else 0
        delta = val_b - val_a
        delta_pct = round(pct_b - pct_a, 2)
        summary_comparison[key] = {
            'a': val_a, 'b': val_b,
            'pct_a': pct_a, 'pct_b': pct_b,
            'delta': delta, 'delta_pct': delta_pct,
        }

    # ─── 2. Level1 分布对比 ───
    dist_l1_a = compute_distribution(details_a, total_a, 'level1')
    dist_l1_b = compute_distribution(details_b, total_b, 'level1')
    level1_comparison = build_comparison_data(dist_l1_a, dist_l1_b, total_a, total_b)

    # ─── 3. Level2 分布对比 ───
    dist_l2_a = compute_level2_by_level1(details_a)
    dist_l2_b = compute_level2_by_level1(details_b)
    level2_comparison = build_nested_comparison(dist_l2_a, dist_l2_b, total_a, total_b)

    # ─── 4. Level3 分布对比 ───
    dist_l3_a = compute_level3_by_level1_level2(details_a)
    dist_l3_b = compute_level3_by_level1_level2(details_b)
    level3_comparison = {}
    all_l1_for_l3 = sorted(set(list(dist_l3_a.keys()) + list(dist_l3_b.keys())))
    for l1 in all_l1_for_l3:
        sub_a = dist_l3_a.get(l1, {})
        sub_b = dist_l3_b.get(l1, {})
        level3_comparison[l1] = build_nested_comparison(sub_a, sub_b, total_a, total_b)

    # ─── 5. 版本号数据 ───
    versions_a = extract_versions(details_a)
    versions_b = extract_versions(details_b)
    all_versions = sorted(set(versions_a + versions_b))

    # ─── 6. 元信息 ───
    dir_a = os.path.dirname(os.path.abspath(db_path_a))
    dir_b = os.path.dirname(os.path.abspath(db_path_b))
    meta = {
        'label_a': label_a or os.path.basename(dir_a),
        'label_b': label_b or os.path.basename(dir_b),
        'time_a': get_db_mtime(db_path_a),
        'time_b': get_db_mtime(db_path_b),
        'source_a': find_xlsx_in_dir(dir_a),
        'source_b': find_xlsx_in_dir(dir_b),
        'has_version': len(all_versions) > 0,
    }

    # ─── 模板变量 ───
    variables = {
        'SUMMARY_JSON': json.dumps(summary_comparison, ensure_ascii=False),
        'LEVEL1_JSON': json.dumps(level1_comparison, ensure_ascii=False),
        'LEVEL2_JSON': json.dumps(level2_comparison, ensure_ascii=False),
        'LEVEL3_JSON': json.dumps(level3_comparison, ensure_ascii=False),
        'DETAILS_A_JSON': json.dumps(details_a, ensure_ascii=False),
        'DETAILS_B_JSON': json.dumps(details_b, ensure_ascii=False),
        'ALL_VERSIONS_JSON': json.dumps(all_versions, ensure_ascii=False),
        'META_JSON': json.dumps(meta, ensure_ascii=False),
        'GENERATED_TIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'LABEL_A': meta['label_a'],
        'LABEL_B': meta['label_b'],
        'HAS_VERSION': meta['has_version'],
    }

    # ─── 渲染模板 ───
    html = render_template(template_path, variables)

    # ─── 确定输出路径 ───
    if not output_dir:
        output_dir = dir_b
    output_path = os.path.join(output_dir, 'compare_period_report.html')
    os.makedirs(output_dir, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description='生成舆情周期对比报告',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='示例: python compare_period.py output/week1/report.db output/week2/report.db --label-a 上周 --label-b 本周'
    )
    parser.add_argument('db_path_a', help='基准期 db 文件路径（如上周）')
    parser.add_argument('db_path_b', help='对比期 db 文件路径（如本周）')
    parser.add_argument('--output-dir', help='输出目录（默认取 db_b 所在目录）')
    parser.add_argument('--label-a', help='报告A标签（默认取目录名）')
    parser.add_argument('--label-b', help='报告B标签（默认取目录名）')
    parser.add_argument('--template', help='自定义模板路径')

    args = parser.parse_args()

    # 验证 db 文件存在
    for db_path in [args.db_path_a, args.db_path_b]:
        if not os.path.isfile(db_path):
            print(f"错误: db 文件不存在: {db_path}")
            sys.exit(1)

    result_path = generate_compare_report(
        db_path_a=args.db_path_a,
        db_path_b=args.db_path_b,
        output_dir=args.output_dir,
        label_a=args.label_a,
        label_b=args.label_b,
        template_path=args.template,
    )
    print(f"对比报告已生成: {result_path}")


if __name__ == "__main__":
    main()