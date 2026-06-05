#!/usr/bin/env python3
"""
报告管理中心仪表盘生成脚本

扫描 output/ 目录下所有报告数据，汇总趋势和对比信息，
生成交互式仪表盘 HTML 页面。

用法: python generate_dashboard.py [--output-dir DIR]
"""

import sys
import os
import io

if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer') and (not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer') and (not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import json
import argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))
DEFAULT_TEMPLATE = os.path.join(SKILL_DIR, "assets", "dashboard_template.html")

sys.path.insert(0, SCRIPT_DIR)
from generate_report import read_data_from_db, render_template
from compare_period import compute_distribution, compute_level2_by_level1, find_xlsx_in_dir, get_db_mtime


def scan_reports(output_dir: str) -> list:
    """扫描 output/ 目录，收集每个报告的元数据和分布数据"""
    reports = []
    if not os.path.isdir(output_dir):
        return reports

    for entry in sorted(os.listdir(output_dir)):
        entry_path = os.path.join(output_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        db_path = os.path.join(entry_path, "report.db")
        if not os.path.isfile(db_path):
            continue

        data = read_data_from_db(db_path)
        summary = data['summary']
        details = data['details']
        total = summary.get('total', len(details))

        level1_dist = compute_distribution(details, total, 'level1')
        xlsx_name = find_xlsx_in_dir(entry_path)
        mtime = get_db_mtime(db_path)

        html_path = os.path.join(entry_path, "report.html")
        has_html = os.path.isfile(html_path)

        reports.append({
            'name': entry,
            'mtime': mtime,
            'total': total,
            'classified': summary.get('classified', 0),
            'unknown_issue': summary.get('unknown_issue', 0),
            'infer_failed': summary.get('infer_failed', 0),
            'level1_dist': level1_dist,
            'xlsx_name': xlsx_name,
            'has_html': has_html,
        })

    reports.sort(key=lambda r: r['mtime'])
    return reports


def build_comparison_data(output_dir: str, reports: list) -> dict:
    """构建客户端对比所需的分布数据"""
    comparison_data = {}
    for r in reports:
        db_path = os.path.join(output_dir, r['name'], 'report.db')
        data = read_data_from_db(db_path)
        details = data['details']
        total = data['summary']['total']

        comparison_data[r['name']] = {
            'summary': data['summary'],
            'level1_dist': compute_distribution(details, total, 'level1'),
            'level2_dist': compute_level2_by_level1(details),
        }
    return comparison_data


def generate_dashboard(output_dir: str = None, template_path: str = None) -> str:
    """生成报告管理中心仪表盘"""

    if not template_path:
        template_path = DEFAULT_TEMPLATE

    if not output_dir:
        output_dir = os.path.join(PROJECT_DIR, 'output')

    reports = scan_reports(output_dir)

    trend_labels = [r['name'] for r in reports]
    trend_total = [r['total'] for r in reports]
    trend_classified = [r['classified'] for r in reports]
    trend_unknown = [r['unknown_issue'] for r in reports]
    trend_failed = [r['infer_failed'] for r in reports]

    all_level1_keys = sorted(set(k for r in reports for k in r['level1_dist']))
    level1_trend = {}
    for key in all_level1_keys:
        level1_trend[key] = [r['level1_dist'].get(key, 0) for r in reports]

    comparison_data = build_comparison_data(output_dir, reports) if reports else {}

    variables = {
        'REPORTS_JSON': json.dumps(reports, ensure_ascii=False),
        'TREND_LABELS_JSON': json.dumps(trend_labels, ensure_ascii=False),
        'TREND_TOTAL_JSON': json.dumps(trend_total, ensure_ascii=False),
        'TREND_CLASSIFIED_JSON': json.dumps(trend_classified, ensure_ascii=False),
        'TREND_UNKNOWN_JSON': json.dumps(trend_unknown, ensure_ascii=False),
        'TREND_FAILED_JSON': json.dumps(trend_failed, ensure_ascii=False),
        'LEVEL1_KEYS_JSON': json.dumps(all_level1_keys, ensure_ascii=False),
        'LEVEL1_TREND_JSON': json.dumps(level1_trend, ensure_ascii=False),
        'COMPARISON_DATA_JSON': json.dumps(comparison_data, ensure_ascii=False),
        'GENERATED_TIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'HAS_REPORTS': len(reports) > 0,
        'HAS_NO_REPORTS': len(reports) == 0,
    }

    html = render_template(template_path, variables)

    dashboard_path = os.path.join(output_dir, 'dashboard.html')
    os.makedirs(output_dir, exist_ok=True)

    with open(dashboard_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return dashboard_path


def main():
    parser = argparse.ArgumentParser(description='生成报告管理中心仪表盘')
    parser.add_argument('--output-dir', default=None, help='输出目录（默认为项目根目录下的 output/）')
    parser.add_argument('--template', default=None, help='自定义模板路径')
    args = parser.parse_args()

    result_path = generate_dashboard(
        output_dir=args.output_dir,
        template_path=args.template,
    )
    print(f"仪表盘已生成: {result_path}")


if __name__ == "__main__":
    main()