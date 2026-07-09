#!/usr/bin/env python3
"""
报告管理中心仪表盘生成脚本

扫描 output/ 目录下所有报告数据，汇总趋势和对比信息，
生成交互式仪表盘 HTML 页面。

功能域：full_path(- 分隔) 1/2/3 级趋势与对比。
业务域：business_classification 单层页面标签趋势与对比。
两视图来自同一张 report 表，仪表盘内「功能域/业务域」视图切换。

用法: python generate_dashboard.py [--output-dir DIR]
"""

import sys
import os
import io
import json
import argparse
import sqlite3
from datetime import datetime
from generate_report import read_report_db, render_template, table_exists, REPORT_TABLE
from compare_period import (compute_distribution, compute_level2_by_level1,
                            compute_level3_by_level1_level2, compute_business_distribution,
                            find_xlsx_in_dir, get_db_mtime, extract_versions)

if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer') and (not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer') and (not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))
DEFAULT_TEMPLATE = os.path.join(SKILL_DIR, "assets", "dashboard_template.html")

sys.path.insert(0, SCRIPT_DIR)


def _resolve_db_path(entry_path: str) -> str:
    """返回报告目录下含 report 表的 DB 路径（空串表示无数据）。"""
    report_db = os.path.join(entry_path, "report.db")
    if os.path.isfile(report_db):
        conn = sqlite3.connect(report_db)
        has = table_exists(conn, REPORT_TABLE)
        conn.close()
        if has:
            return report_db
    return ""


def scan_reports(output_dir: str) -> list:
    """扫描 output/ 目录，收集每个报告的元数据与功能域 1 级分布。"""
    reports = []
    if not os.path.isdir(output_dir):
        return reports

    for entry in sorted(os.listdir(output_dir)):
        entry_path = os.path.join(output_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        db_path = _resolve_db_path(entry_path)
        if not db_path:
            continue

        data = read_report_db(db_path)
        summary = data['summary']
        details = data['details']
        total = summary.get('total', len(details))

        level1_dist = compute_distribution(details, total, 1)
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

    reports.sort(key=lambda r: r['name'])
    return reports


def build_comparison_data(output_dir: str, reports: list) -> dict:
    """构建客户端对比/趋势所需的分布数据（功能域 1/2/3 级 + 业务域单层 + 版本）。"""
    comparison_data = {}
    for r in reports:
        db_path = _resolve_db_path(os.path.join(output_dir, r['name']))
        if not db_path:
            continue
        data = read_report_db(db_path)
        details = data['details']
        total = data['summary']['total']
        comparison_data[r['name']] = {
            'summary': data['summary'],
            'level1_dist': compute_distribution(details, total, 1),
            'level2_dist': compute_level2_by_level1(details),
            'level3_dist': compute_level3_by_level1_level2(details),
            'business_dist': compute_business_distribution(details),
            'details': details,
            'versions': extract_versions(details),
        }
    return comparison_data


def _build_bundle(output_dir: str, domain: str):
    """构建某视图的仪表盘数据。domain: function(功能域 1 级) / business(业务域单层)。
    返回 None 表示无任何报告。
    """
    reports = scan_reports(output_dir)
    if not reports:
        return None

    trend_labels = [r['name'] for r in reports]
    trend_total = [r['total'] for r in reports]
    trend_classified = [r['classified'] for r in reports]
    trend_unknown = [r['unknown_issue'] for r in reports]
    trend_failed = [r['infer_failed'] for r in reports]

    comparison_data = build_comparison_data(output_dir, reports)

    # 1 级 keys：功能域取 level1_dist 的键，业务域取 business_dist 的键
    dist_key = 'level1_dist' if domain == 'function' else 'business_dist'
    all_keys = sorted(set(k for r in reports for k in comparison_data[r['name']][dist_key]))
    level1_trend = {}
    for key in all_keys:
        level1_trend[key] = [comparison_data[r['name']][dist_key].get(key, 0) for r in reports]

    # scan_reports 的 level1_dist 仅含功能域 1 级；业务域需重算
    if domain == 'business':
        for r in reports:
            r['level1_dist'] = comparison_data[r['name']]['business_dist']

    return {
        'reports': reports,
        'trend_labels': trend_labels,
        'trend_total': trend_total,
        'trend_classified': trend_classified,
        'trend_unknown': trend_unknown,
        'trend_failed': trend_failed,
        'level1_keys': all_keys,
        'level1_trend': level1_trend,
        'comparison_data': comparison_data,
    }


def generate_dashboard(output_dir: str = None, template_path: str = None) -> str:
    """生成报告管理中心仪表盘：功能域/业务域同页双视图切换"""

    if not template_path:
        template_path = DEFAULT_TEMPLATE

    if not output_dir:
        output_dir = os.path.join(PROJECT_DIR, 'output')

    bundles = {}
    for domain in ("function", "business"):
        b = _build_bundle(output_dir, domain)
        if b is not None:
            bundles[domain] = b

    has_reports = len(bundles) > 0
    default_domain = "function" if "function" in bundles else (next(iter(bundles)) if bundles else "function")

    variables = {
        'DOMAIN_FUNCTION_JSON': json.dumps(bundles.get("function"), ensure_ascii=False),
        'DOMAIN_BUSINESS_JSON': json.dumps(bundles.get("business"), ensure_ascii=False),
        'HAS_FUNCTION': "function" in bundles,
        'HAS_BUSINESS': "business" in bundles,
        'DEFAULT_DOMAIN': default_domain,
        'GENERATED_TIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'HAS_REPORTS': has_reports,
        'HAS_NO_REPORTS': not has_reports,
    }

    html = render_template(template_path, variables)

    # 内联 Chart.js 到 HTML，避免浏览器 file:// 安全策略阻止加载外部脚本
    chart_js_src = os.path.join(SKILL_DIR, 'assets', 'chart.js')
    if os.path.isfile(chart_js_src):
        with open(chart_js_src, 'r', encoding='utf-8') as f:
            chart_js_content = f.read()
        html = html.replace('<script src="chart.js"></script>',
                            '<script>\n' + chart_js_content + '\n</script>')

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
