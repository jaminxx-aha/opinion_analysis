#!/usr/bin/env python3
"""
可视化报告生成脚本（支持JSON和SQLite输入，基于HTML模板）

分类格式：一级分类.二级分类.三级分类

用法: python generate_report.py <分析结果DB或JSON路径> <输出HTML路径> [模板HTML路径]
输出: HTML 可视化报告
"""

import sys
import os
import io

# Windows下强制UTF-8输出
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer') and (not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer') and (not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import json
import sqlite3
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_TEMPLATE = os.path.join(SKILL_DIR, "assets", "report_template.html")


def domain_table(domain: str) -> str:
    """域 → 表名。功能域/业务域分别 report_function / report_business（同一 report.db）。"""
    return f"report_{domain}"


def table_exists(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def read_data_from_db(db_path: str, table: str = "report") -> dict:
    """从SQLite数据库读取指定表的分类结果

    table: report_function / report_business / report(旧)
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 兼容旧DB：检查 version 列是否存在
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    has_version = 'version' in cols
    has_level4 = 'level4' in cols
    has_level5 = 'level5' in cols

    cursor.execute(f"SELECT * FROM {table} ORDER BY id")
    rows = cursor.fetchall()
    conn.close()

    summary = {
        "total": len(rows),
        "classified": 0,
        "unknown_issue": 0,
        "infer_failed": 0,
        "too_long": 0,
    }

    details = []
    for r in rows:
        raw_data = json.loads(r['raw_data']) if r['raw_data'] else {}
        status = r['status']  # 0=成功, 1=未知问题, 2=失败
        version = r['version'] if has_version else ''
        if status == 0 and r['level1'] and r['level1'] != '未知问题':
            summary["classified"] += 1
            details.append({
                'row_id': r['id'],
                'input': r['problem'],
                'status': 'classified',
                'version': version or '',
                'classification': {
                    'app': r['cls_app'] or r['app'],
                    'level1': r['level1'],
                    'level2': r['level2'],
                    'level3': r['level3'],
                    'level4': r['level4'] if has_level4 else '',
                    'level5': r['level5'] if has_level5 else '',
                    'full_path': r['full_path'],
                },
                'reasoning': r['reasoning'] or '',
                'raw_data': raw_data,
            })
        elif status == 1:
            summary["unknown_issue"] += 1
            details.append({
                'row_id': r['id'],
                'input': r['problem'],
                'status': 'unknown_issue',
                'version': version or '',
                'classification': {
                    'app': r['app'] or '',
                    'level1': '未知问题',
                    'level2': '',
                    'level3': '',
                    'level4': '',
                    'level5': '',
                    'full_path': '未知问题',
                },
                'reasoning': r['reasoning'] or '',
                'raw_data': raw_data,
            })
        elif status == 2:
            summary["infer_failed"] += 1
            details.append({
                'row_id': r['id'],
                'input': r['problem'],
                'status': 'infer_failed',
                'version': version or '',
                'reasoning': r['reasoning'] or '',
                'raw_data': raw_data,
            })
        elif status == 3:
            summary["too_long"] += 1
            details.append({
                'row_id': r['id'],
                'input': r['problem'],
                'status': 'too_long',
                'version': version or '',
                'classification': {
                    'app': r['cls_app'] or r['app'],
                    'level1': '描述过长',
                    'level2': '',
                    'level3': '',
                    'level4': '',
                    'level5': '',
                    'full_path': '描述过长',
                },
                'reasoning': r['reasoning'] or '',
                'raw_data': raw_data,
            })
        else:
            details.append({
                'row_id': r['id'],
                'input': r['problem'],
                'status': 'pending',
                'version': version or '',
                'output': '待分类',
                'raw_data': raw_data,
            })

    return {
        'summary': summary,
        'details': details,
    }


def read_data_from_json(json_path: str) -> dict:
    """从JSON文件读取分类结果"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    summary = data.get('summary', {})
    raw_details = data.get('details', [])

    # 兼容旧格式
    if not raw_details:
        items = data.get('items', [])
        raw_details = []
        for item in items:
            detail = {
                'input': item.get('problem', item.get('input', '')),
                'status': item.get('status', 'pending'),
                'classification': item.get('classification'),
            }
            if not detail.get('classification') and detail['status'] == 'pending':
                detail['output'] = '待分类'
            raw_details.append(detail)

    # 处理数据，支持新旧两种分类格式
    details = []
    for item in raw_details:
        cls = item.get('classification', {})

        if isinstance(cls, dict) and cls.get('level1'):
            detail = {
                'input': item.get('input', item.get('problem', '')),
                'status': item.get('status', 'success'),
                'classification': cls,
            }
        elif isinstance(cls, dict) and cls.get('module') and cls.get('issue_type'):
            level1 = cls.get('issue_type', '')
            level2 = cls.get('module', '')
            level3 = cls.get('issue_detail', '')
            if level1 == '性能问题':
                level1 = '卡顿'
            detail = {
                'input': item.get('input', item.get('problem', '')),
                'status': item.get('status', 'success'),
                'classification': {
                    'app': cls.get('app', ''),
                    'level1': level1,
                    'level2': level2,
                    'level3': level3,
                    'level4': '',
                    'level5': '',
                    'full_path': f'{level1}.{level2}.{level3}',
                },
            }
        else:
            detail = item

        details.append(detail)

    total = summary.get('total', len(details))
    classified = summary.get('classified', sum(1 for d in details if d.get('status') == 'success'))
    unrecognized = summary.get('unrecognized_app', sum(1 for d in details if d.get('status') == 'unrecognized'))

    return {
        'summary': {
            'total': total,
            'classified': classified,
            'unrecognized_app': unrecognized,
        },
        'details': details,
    }


def read_domain(output_dir: str, domain: str):
    """读取某个分类域的数据。

    解析顺序：
      1. <output_dir>/report.db 的 report_<domain> 表（新布局，单库双表）
      2. <output_dir>/<domain>_report.db 的 report 表（旧布局，按域分库）
      3. function 域回退 <output_dir>/report.db 的 report 表（更早的单域库）
    返回 {summary, details} 或 None（该域数据不存在时）。
    """
    output_dir = os.path.abspath(output_dir)

    # 1. 单库 report.db 的 report_<domain> 表
    report_db = os.path.join(output_dir, "report.db")
    if os.path.isfile(report_db):
        conn = sqlite3.connect(report_db)
        t = domain_table(domain)
        if table_exists(conn, t):
            conn.close()
            return read_data_from_db(report_db, t)
        conn.close()

    # 2. 按域分库（旧布局）
    per_domain_db = os.path.join(output_dir, f"{domain}_report.db")
    if os.path.isfile(per_domain_db):
        return read_data_from_db(per_domain_db, "report")

    # 3. function 域回退到最早的单域 report.db（表 report）
    if domain == "function" and os.path.isfile(report_db):
        conn = sqlite3.connect(report_db)
        legacy = table_exists(conn, "report")
        conn.close()
        if legacy:
            return read_data_from_db(report_db, "report")

    return None


def read_domain_from_db(db_path: str, domain: str):
    """从指定 DB 文件读取某域数据（report_<domain> 表，回退 report 表）。"""
    conn = sqlite3.connect(db_path)
    has_new = table_exists(conn, domain_table(domain))
    has_legacy = table_exists(conn, "report") if domain == "function" else False
    conn.close()
    if has_new:
        return read_data_from_db(db_path, domain_table(domain))
    if has_legacy:
        return read_data_from_db(db_path, "report")
    return None


def render_template(template_path: str, variables: dict) -> str:
    """读取HTML模板并替换变量占位符，处理条件块"""
    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()

    # 处理条件块 {{IF_X}}...{{ENDIF_X}}
    for key, value in variables.items():
        if key.startswith("HAS_"):
            if value:
                html = re.sub(r'{{IF_' + key[4:] + '}}(.*?){{ENDIF_' + key[4:] + '}}', r'\1', html, flags=re.DOTALL)
            else:
                html = re.sub(r'{{IF_' + key[4:] + '}}.*?{{ENDIF_' + key[4:] + '}}', '', html, flags=re.DOTALL)

    # 替换简单变量 {{VAR}}
    for key, value in variables.items():
        if not key.startswith("HAS_"):
            html = html.replace('{{' + key + '}}', str(value))

    return html


def generate_report(input_path: str, output_path: str = None, template_path: str = None) -> dict:
    """根据分析结果生成可视化 HTML 报告。

    input_path 可以是:
      - 目录：读取该目录下存在的 function / business 两个域 DB，合并成双标签页报告
      - .db 文件：单库，按文件名推断域（旧 report.db 视作 function）
      - .json 文件：旧 JSON 格式（按 function 域处理）
    """
    if not template_path:
        template_path = DEFAULT_TEMPLATE

    # 判定输入类型并按域收集数据
    domains_data = {}  # domain -> {summary, details}
    if os.path.isdir(input_path):
        input_dir = os.path.abspath(input_path)
        for domain in ("function", "business"):
            data = read_domain(input_dir, domain)
            if data is not None:
                domains_data[domain] = data
    elif input_path.endswith('.db'):
        input_dir = os.path.dirname(os.path.abspath(input_path))
        # 单库 report.db 可能含两域表；按域分库 db 取其域
        for domain in ("function", "business"):
            data = read_domain_from_db(input_path, domain)
            if data is not None:
                domains_data[domain] = data
    else:
        input_dir = os.path.dirname(os.path.abspath(input_path))
        domains_data["function"] = read_data_from_json(input_path)

    if not domains_data:
        return None

    # 默认展示首个可用域
    default_domain = "function" if "function" in domains_data else next(iter(domains_data))

    # 查找 Excel 来源文件名（目录内的 .xlsx/.xls）
    excel_filename = ''
    if os.path.isdir(input_dir) and os.path.exists(input_dir):
        for f in os.listdir(input_dir):
            if f.endswith('.xlsx') or f.endswith('.xls'):
                excel_filename = f
                break

    # 域摘要，供模板里的 summary 数字使用（默认域）
    def_data = domains_data[default_domain]
    def_summary = def_data['summary']
    def_details = def_data['details']
    total = def_summary.get('total', len(def_details))
    classified = def_summary.get('classified', 0)
    unknown_issue = def_summary.get('unknown_issue', 0)
    infer_failed = def_summary.get('infer_failed', 0)
    too_long = def_summary.get('too_long', 0)

    variables = {
        'TOTAL': total,
        'CLASSIFIED': classified,
        'UNKNOWN_ISSUE': unknown_issue,
        'INFER_FAILED': infer_failed,
        'TOO_LONG': too_long,
        # 双域数据，每域 {summary, details}；模板里按 domain 取用
        'DOMAIN_FUNCTION_JSON': json.dumps(domains_data.get("function"), ensure_ascii=False),
        'DOMAIN_BUSINESS_JSON': json.dumps(domains_data.get("business"), ensure_ascii=False),
        'HAS_FUNCTION': "function" in domains_data,
        'HAS_BUSINESS': "business" in domains_data,
        'DEFAULT_DOMAIN': default_domain,
        # 兼容旧模板：DETAILS_JSON 指向默认域
        'DETAILS_JSON': json.dumps(def_details, ensure_ascii=False),
        'GENERATED_TIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'EXCEL_FILENAME': excel_filename,
        'HAS_EXCEL_FILENAME': bool(excel_filename),
    }

    html = render_template(template_path, variables)

    # 确定输出路径
    if not output_path:
        if os.path.isdir(input_path):
            # 传入的是目录：用目录名作报告名
            output_path = os.path.join(input_dir, f"{os.path.basename(input_dir)}_report.html")
        else:
            input_basename = os.path.basename(input_path)
            for ext in ['.json', '.db']:
                if input_basename.endswith(ext):
                    input_basename = input_basename[:-len(ext)]
            for suffix in ['_classified', '_prepared']:
                if input_basename.endswith(suffix):
                    input_basename = input_basename[:-len(suffix)]
            output_path = os.path.join(input_dir, f"{input_basename}_report.html")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return {
        'path': output_path,
        'domains': list(domains_data.keys()),
        'total': total,
        'classified': classified,
        'unknown_issue': unknown_issue,
        'infer_failed': infer_failed,
    }


def main():
    if len(sys.argv) < 2:
        print("用法: python generate_report.py <输出目录或分析结果JSON/DB路径> [输出HTML路径] [模板HTML路径]")
        print("      传目录时读取该目录下 function/business 两域 DB 合并双标签页报告")
        print("      未指定输出路径时，结果将保存在输入文件所在目录")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    template_path = sys.argv[3] if len(sys.argv) > 3 else None

    result = generate_report(input_path, output_path, template_path)
    print(f"报告已生成: {result['path']}")


if __name__ == "__main__":
    main()