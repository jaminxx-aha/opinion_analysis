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
import json
import argparse
import sqlite3
from datetime import datetime
from generate_report import read_data_from_db, render_template, domain_table, table_exists
from compare_period import compute_distribution, compute_level2_by_level1, compute_level3_by_level1_level2, find_xlsx_in_dir, get_db_mtime, extract_versions

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

def _resolve_db_path(entry_path: str, domain: str) -> str:
    """返回某报告目录下包含该域数据的 DB 文件路径（空串表示无数据）。

    解析顺序：report.db（新，单库双表）→ <domain>_report.db（旧，按域分库）→ function 回退 report.db 的 report 表。
    """
    report_db = os.path.join(entry_path, "report.db")
    if os.path.isfile(report_db):
        conn = sqlite3.connect(report_db)
        has_table = table_exists(conn, domain_table(domain))
        # function 域：兼容最早的 report 表
        if not has_table and domain == "function":
            has_table = table_exists(conn, "report")
        conn.close()
        if has_table:
            return report_db
    per_domain = os.path.join(entry_path, f"{domain}_report.db")
    if os.path.isfile(per_domain):
        return per_domain
    return ""


def _read_domain_db(db_path: str, domain: str):
    """从 db 读取某域数据（单库双表 / 按域分库 / 最早 report 表）。"""
    conn = sqlite3.connect(db_path)
    has_new = table_exists(conn, domain_table(domain))
    has_legacy_report = domain == "function" and table_exists(conn, "report")
    conn.close()
    if has_new:
        return read_data_from_db(db_path, domain_table(domain))
    if has_legacy_report:
        return read_data_from_db(db_path, "report")
    # 按域分库（旧）
    return read_data_from_db(db_path, "report")


def scan_reports(output_dir: str, domain: str = "function") -> list:
    """扫描 output/ 目录，收集每个报告的元数据和分布数据（按指定域）"""
    reports = []
    if not os.path.isdir(output_dir):
        return reports

    for entry in sorted(os.listdir(output_dir)):
        entry_path = os.path.join(output_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        db_path = _resolve_db_path(entry_path, domain)
        if not db_path:
            continue

        data = _read_domain_db(db_path, domain)
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

    reports.sort(key=lambda r: r['name'])
    return reports


def build_comparison_data(output_dir: str, reports: list, domain: str = "function") -> dict:
    """构建客户端对比所需的分布数据（含三级钻取和版本筛选）"""
    comparison_data = {}
    for r in reports:
        db_path = _resolve_db_path(os.path.join(output_dir, r['name']), domain)
        if not db_path:
            continue
        data = _read_domain_db(db_path, domain)
        details = data['details']
        total = data['summary']['total']

        comparison_data[r['name']] = {
            'summary': data['summary'],
            'level1_dist': compute_distribution(details, total, 'level1'),
            'level2_dist': compute_level2_by_level1(details),
            'level3_dist': compute_level3_by_level1_level2(details),
            'details': details,
            'versions': extract_versions(details),
        }
    return comparison_data


def _build_domain_bundle(output_dir: str, domain: str):
    """为单个域构建仪表盘所需的全部数据。返回 None 表示该域无任何数据。"""
    reports = scan_reports(output_dir, domain)
    if not reports:
        return None

    trend_labels = [r['name'] for r in reports]
    trend_total = [r['total'] for r in reports]
    trend_classified = [r['classified'] for r in reports]
    trend_unknown = [r['unknown_issue'] for r in reports]
    trend_failed = [r['infer_failed'] for r in reports]

    all_level1_keys = sorted(set(k for r in reports for k in r['level1_dist']))
    level1_trend = {}
    for key in all_level1_keys:
        level1_trend[key] = [r['level1_dist'].get(key, 0) for r in reports]

    comparison_data = build_comparison_data(output_dir, reports, domain)

    return {
        'reports': reports,
        'trend_labels': trend_labels,
        'trend_total': trend_total,
        'trend_classified': trend_classified,
        'trend_unknown': trend_unknown,
        'trend_failed': trend_failed,
        'level1_keys': all_level1_keys,
        'level1_trend': level1_trend,
        'comparison_data': comparison_data,
    }


def generate_dashboard(output_dir: str = None, template_path: str = None) -> str:
    """生成报告管理中心仪表盘：功能域与业务域同页双标签页切换"""

    if not template_path:
        template_path = DEFAULT_TEMPLATE

    if not output_dir:
        output_dir = os.path.join(PROJECT_DIR, 'output')

    bundles = {}
    for domain in ("function", "business"):
        b = _build_domain_bundle(output_dir, domain)
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