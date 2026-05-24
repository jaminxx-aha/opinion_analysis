#!/usr/bin/env python3
"""
可视化报告生成脚本（支持JSON和SQLite输入，基于HTML模板）

分类格式：一级分类.二级分类.三级分类

用法: python generate_report.py <分析结果DB或JSON路径> <输出HTML路径> [模板HTML路径]
输出: HTML 可视化报告
"""

import sys
import json
import os
import sqlite3
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_TEMPLATE = os.path.join(SKILL_DIR, "assets", "report_template.html")


def read_data_from_db(db_path: str) -> dict:
    """从SQLite数据库读取分类结果"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM report ORDER BY id")
    rows = cursor.fetchall()
    conn.close()

    summary = {
        "total": len(rows),
        "classified": 0,
        "unrecognized_app": 0,
        "no_description": 0,
    }

    details = []
    for r in rows:
        raw_data = json.loads(r['raw_data']) if r['raw_data'] else {}
        status = r['status']
        if status == 'success' and r['level1']:
            summary["classified"] += 1
            details.append({
                'input': r['problem'],
                'status': 'success',
                'classification': {
                    'app': r['cls_app'] or r['app'],
                    'level1': r['level1'],
                    'level2': r['level2'],
                    'level3': r['level3'],
                    'full_path': r['full_path'],
                },
                'reasoning': r['reasoning'] or '',
                'raw_data': raw_data,
            })
        elif status == 'unrecognized':
            summary["unrecognized_app"] += 1
            details.append({
                'input': r['problem'],
                'status': 'unrecognized',
                'classification': {
                    'app': r['app'] or '',
                    'level1': '未知问题',
                    'level2': '',
                    'level3': '',
                    'full_path': '未知问题',
                },
                'reasoning': r['reasoning'] or '',
                'raw_data': raw_data,
            })
        elif status == 'no_description':
            summary["no_description"] += 1
            details.append({
                'input': r['problem'],
                'status': 'no_description',
                'output': f"{r['app']}没有描述",
                'raw_data': raw_data,
            })
        else:
            details.append({
                'input': r['problem'],
                'status': 'pending',
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


def generate_report(input_path: str, output_path: str = None, template_path: str = None) -> str:
    """根据分析结果生成可视化 HTML 报告"""

    if not template_path:
        template_path = DEFAULT_TEMPLATE

    # 根据输入类型选择读取方式
    if input_path.endswith('.db'):
        report_data = read_data_from_db(input_path)
    else:
        report_data = read_data_from_json(input_path)

    summary = report_data['summary']
    details = report_data['details']

    total = summary.get('total', len(details))
    classified = summary.get('classified', 0)
    unrecognized = summary.get('unrecognized_app', 0)

    # 查找Excel来源文件名
    input_dir = os.path.dirname(os.path.abspath(input_path))
    excel_filename = ''
    for f in os.listdir(input_dir):
        if f.endswith('.xlsx') or f.endswith('.xls'):
            excel_filename = f
            break

    # 模板变量
    variables = {
        'TOTAL': total,
        'CLASSIFIED': classified,
        'UNRECOGNIZED': unrecognized,
        'DETAILS_JSON': json.dumps(details, ensure_ascii=False),
        'GENERATED_TIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'EXCEL_FILENAME': excel_filename,
        'HAS_EXCEL_FILENAME': bool(excel_filename),
    }

    html = render_template(template_path, variables)

    # 确定输出路径
    if not output_path:
        input_dir = os.path.dirname(os.path.abspath(input_path))
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

    return output_path


def main():
    if len(sys.argv) < 2:
        print("用法: python generate_report.py <分析结果JSON或DB路径> [输出HTML路径] [模板HTML路径]")
        print("      未指定输出路径时，结果将保存在输入文件所在目录")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    template_path = sys.argv[3] if len(sys.argv) > 3 else None

    result_path = generate_report(input_path, output_path, template_path)
    print(f"报告已生成: {result_path}")


if __name__ == "__main__":
    main()