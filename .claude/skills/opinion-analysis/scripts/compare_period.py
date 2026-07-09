#!/usr/bin/env python3
"""
舆情周期对比报告生成脚本

对比两个不同时期的舆情分类报告（如本周 vs 上周），
展示分类分布、数量和占比的变化趋势。

功能域：按 full_path(- 分隔) 的 1/2/3 级做分布对比与钻取。
业务域：按 business_classification(单层页面标签) 做分布对比。
两视图来自同一张 report 表，报告内「功能域/业务域」视图切换。

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
import json
import argparse
from datetime import datetime
from collections import Counter
from generate_report import read_report_db, render_template

# Windows 下强制 UTF-8 输出
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer') and (not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer') and (not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_TEMPLATE = os.path.join(SKILL_DIR, "assets", "compare_period_template.html")

PATH_SEP = "-"
sys.path.insert(0, SCRIPT_DIR)


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


def _levels_of(detail: dict) -> list:
    """功能域：detail.classification.full_path 按 - 切分的各级名称列表。"""
    cls = detail.get('classification') or {}
    fp = cls.get('full_path', '') if isinstance(cls, dict) else ''
    return [p for p in fp.split(PATH_SEP) if p] if fp else []


def _biz_of(detail: dict) -> str:
    """业务域：detail.classification.business_classification 页面标签。"""
    cls = detail.get('classification') or {}
    return (cls.get('business_classification', '') if isinstance(cls, dict) else '') or ''


def compute_distribution(details: list, total: int, depth: int) -> dict:
    """功能域：计算 full_path 第 depth 级(1-based) 的频次分布。

    depth=1 时，「未知问题」也算一个分类。
    返回: {分类名: count}
    """
    counter = Counter()
    for item in details:
        st = item.get('status')
        if st == 'classified':
            lv = _levels_of(item)
            if len(lv) >= depth:
                counter[lv[depth - 1]] += 1
        elif st == 'unknown_issue' and depth == 1:
            counter['未知问题'] += 1
    return dict(counter)


def compute_business_distribution(details: list) -> dict:
    """业务域：按 business_classification 单层分布。返回 {页面标签: count}。"""
    counter = Counter()
    for item in details:
        if item.get('status') == 'classified':
            b = _biz_of(item)
            if b:
                counter[b] += 1
    return dict(counter)


def compute_level2_by_level1(details: list) -> dict:
    """功能域：按 1 级分组的 2 级分布。返回 {l1: {l2: count}}。"""
    result = {}
    for item in details:
        if item.get('status') != 'classified':
            continue
        lv = _levels_of(item)
        if len(lv) >= 2:
            l1, l2 = lv[0], lv[1]
            result.setdefault(l1, Counter())[l2] += 1
    return {k: dict(v) for k, v in result.items()}


def compute_level3_by_level1_level2(details: list) -> dict:
    """功能域：按 1.2 级分组的 3 级分布。返回 {l1: {l2: {l3: count}}}。"""
    result = {}
    for item in details:
        if item.get('status') != 'classified':
            continue
        lv = _levels_of(item)
        if len(lv) >= 3:
            l1, l2, l3 = lv[0], lv[1], lv[2]
            result.setdefault(l1, {}).setdefault(l2, Counter())[l3] += 1
    return {l1: {l2: dict(v) for l2, v in sub.items()} for l1, sub in result.items()}


def build_comparison_data(dist_a: dict, dist_b: dict, total_a: int, total_b: int) -> dict:
    """构建两个分布的对比数据。返回 {分类名: {a, b, pct_a, pct_b, delta, delta_pct}}。"""
    all_keys = sorted(set(list(dist_a.keys()) + list(dist_b.keys())))
    result = {}
    for key in all_keys:
        count_a = dist_a.get(key, 0)
        count_b = dist_b.get(key, 0)
        pct_a = round(count_a / total_a * 100, 2) if total_a > 0 else 0
        pct_b = round(count_b / total_b * 100, 2) if total_b > 0 else 0
        result[key] = {
            'a': count_a, 'b': count_b,
            'pct_a': pct_a, 'pct_b': pct_b,
            'delta': count_b - count_a, 'delta_pct': round(pct_b - pct_a, 2),
        }
    return result


def build_nested_comparison(level_dist_a: dict, level_dist_b: dict,
                            total_a: int, total_b: int) -> dict:
    """构建嵌套分布对比。返回 {group_key: {sub_key: {a,b,...}}}。"""
    all_groups = sorted(set(list(level_dist_a.keys()) + list(level_dist_b.keys())))
    result = {}
    for group in all_groups:
        sub_a = level_dist_a.get(group, {})
        sub_b = level_dist_b.get(group, {})
        result[group] = build_comparison_data(sub_a, sub_b, total_a, total_b)
    return result


def extract_versions(details: list) -> list:
    """提取版本号列表（唯一值，排序，包含空版本标记）。"""
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
        result.append('')
    return result


def _build_bundle(data_a, data_b):
    """构建功能域/业务域两套对比 bundle（共享 summary/details/versions）。

    data_a/data_b 为 {summary,details}，可为 None。返回 (function_bundle, business_bundle)，
    任一在两期均无数据时对应 bundle 内 level* 为空（但仍返回，因业务域由功能域派生，总有数据）。
    """
    empty = {'summary': {'total': 0, 'classified': 0, 'unknown_issue': 0, 'infer_failed': 0}, 'details': []}
    a = data_a or empty
    b = data_b or empty

    summary_a = a['summary']
    summary_b = b['summary']
    details_a = a['details']
    details_b = b['details']
    total_a = summary_a.get('total', 0)
    total_b = summary_b.get('total', 0)

    # 1. 汇总对比
    summary_comparison = {}
    for key in ['total', 'classified', 'unknown_issue', 'infer_failed']:
        val_a = summary_a.get(key, 0)
        val_b = summary_b.get(key, 0)
        pct_a = round(val_a / total_a * 100, 2) if total_a > 0 else 0
        pct_b = round(val_b / total_b * 100, 2) if total_b > 0 else 0
        summary_comparison[key] = {
            'a': val_a, 'b': val_b, 'pct_a': pct_a, 'pct_b': pct_b,
            'delta': val_b - val_a, 'delta_pct': round(pct_b - pct_a, 2),
        }

    # 2. 功能域：full_path 1/2/3 级对比
    dist_l1_a = compute_distribution(details_a, total_a, 1)
    dist_l1_b = compute_distribution(details_b, total_b, 1)
    level1 = build_comparison_data(dist_l1_a, dist_l1_b, total_a, total_b)

    dist_l2_a = compute_level2_by_level1(details_a)
    dist_l2_b = compute_level2_by_level1(details_b)
    level2 = build_nested_comparison(dist_l2_a, dist_l2_b, total_a, total_b)

    dist_l3_a = compute_level3_by_level1_level2(details_a)
    dist_l3_b = compute_level3_by_level1_level2(details_b)
    level3 = {}
    for l1 in sorted(set(list(dist_l3_a.keys()) + list(dist_l3_b.keys()))):
        level3[l1] = build_nested_comparison(dist_l3_a.get(l1, {}), dist_l3_b.get(l1, {}), total_a, total_b)

    # 3. 业务域：business_classification 单层对比
    dist_biz_a = compute_business_distribution(details_a)
    dist_biz_b = compute_business_distribution(details_b)
    biz_level1 = build_comparison_data(dist_biz_a, dist_biz_b, total_a, total_b)

    all_versions = sorted(set(extract_versions(details_a) + extract_versions(details_b)))

    common = {
        'summary': summary_comparison,
        'detailsA': details_a,
        'detailsB': details_b,
        'versions': all_versions,
    }
    function_bundle = {**common, 'level1': level1, 'level2': level2, 'level3': level3}
    business_bundle = {**common, 'level1': biz_level1, 'level2': {}, 'level3': {}}
    return function_bundle, business_bundle


def generate_compare_report(db_path_a: str, db_path_b: str,
                            output_dir: str = None,
                            label_a: str = None, label_b: str = None,
                            template_path: str = None) -> str:
    """生成周期对比报告：同一 report 表，功能域/业务域视图切换。"""

    if not template_path:
        template_path = DEFAULT_TEMPLATE

    data_a = read_report_db(db_path_a)
    data_b = read_report_db(db_path_b)
    if data_a is None and data_b is None:
        raise SystemExit(f"错误: 两个 db 均无 report 表数据。\n  A={db_path_a}\n  B={db_path_b}")

    function_bundle, business_bundle = _build_bundle(data_a, data_b)

    # 元信息
    dir_a = os.path.dirname(os.path.abspath(db_path_a))
    dir_b = os.path.dirname(os.path.abspath(db_path_b))
    has_version = bool(function_bundle.get('versions'))
    meta = {
        'label_a': label_a or os.path.basename(dir_a),
        'label_b': label_b or os.path.basename(dir_b),
        'time_a': get_db_mtime(db_path_a),
        'time_b': get_db_mtime(db_path_b),
        'source_a': find_xlsx_in_dir(dir_a),
        'source_b': find_xlsx_in_dir(dir_b),
        'has_version': has_version,
    }

    default_domain = "function"

    variables = {
        'DOMAIN_FUNCTION_JSON': json.dumps(function_bundle, ensure_ascii=False),
        'DOMAIN_BUSINESS_JSON': json.dumps(business_bundle, ensure_ascii=False),
        'HAS_FUNCTION': True,
        'HAS_BUSINESS': True,
        'DEFAULT_DOMAIN': default_domain,
        'META_JSON': json.dumps(meta, ensure_ascii=False),
        'GENERATED_TIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'LABEL_A': meta['label_a'],
        'LABEL_B': meta['label_b'],
        'HAS_VERSION': has_version,
    }

    html = render_template(template_path, variables)

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
