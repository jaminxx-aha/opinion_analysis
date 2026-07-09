#!/usr/bin/env python3
"""
可视化报告生成脚本（基于HTML模板）

分类格式：full_path（- 分隔的完整路径，如 动效卡顿-滑动卡顿-页面滑动卡顿-视频流上下滑动卡顿）
业务域分类：business_classification（由功能域→业务页面标签映射派生，单层，如 视频页）
同一报告内用「功能域/业务域」视图切换呈现，均来自单张 report 表。

用法: python generate_report.py <分析结果DB或JSON路径> <输出HTML路径> [模板HTML路径]
输出: HTML 可视化报告
"""

import sys
import os
import io
import json
import sqlite3
import re
from datetime import datetime

# Windows下强制UTF-8输出
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer') and (not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer') and (not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_TEMPLATE = os.path.join(SKILL_DIR, "assets", "report_template.html")

REPORT_TABLE = "report"
PATH_SEP = "-"


def table_exists(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def read_data_from_db(db_path: str, table: str = REPORT_TABLE) -> dict:
    """从SQLite数据库读取 report 表的分类结果。

    每条 classified detail 的 classification 携带 {app, full_path, business_classification}。
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 兼容旧DB：检查新列是否存在
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    has_full_path = 'full_path' in cols
    has_business = 'business_classification' in cols
    has_version = 'version' in cols

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
        status = r['status']  # 0=成功, 1=未知问题, 2=失败, 3=描述过长
        version = r['version'] if has_version else ''
        # 旧库(level1-5)兼容：full_path 缺失时按 level1..5 拼回（- 分隔）
        fp = r['full_path'] if has_full_path else ''
        biz = r['business_classification'] if has_business else ''
        if not fp and has_version is False and 'level1' in cols:
            # 极旧库只有 level1-5：拼 full_path
            parts = [r[c] for c in ('level1', 'level2', 'level3', 'level4', 'level5') if c in cols and r[c]]
            fp = PATH_SEP.join(parts) if parts else ''
        if status == 0 and fp and fp != '未知问题':
            summary["classified"] += 1
            details.append({
                'row_id': r['id'],
                'input': r['problem'],
                'status': 'classified',
                'version': version or '',
                'classification': {
                    'app': r['cls_app'] or r['app'],
                    'full_path': fp,
                    'business_classification': biz or '',
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
                    'full_path': '未知问题',
                    'business_classification': biz or '',
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
                    'full_path': '描述过长',
                    'business_classification': '',
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
    """从JSON文件读取分类结果（旧格式兼容）。"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    summary = data.get('summary', {})
    raw_details = data.get('details', [])

    details = []
    for item in raw_details:
        cls = item.get('classification', {})
        full_path = ''
        if isinstance(cls, dict):
            full_path = cls.get('full_path', '')
            if not full_path:
                # 旧 level1-5 格式：拼 full_path
                parts = [cls.get(k, '') for k in ('level1', 'level2', 'level3', 'level4', 'level5')]
                full_path = PATH_SEP.join(p for p in parts if p)
            cls = {**cls, 'full_path': full_path, 'business_classification': cls.get('business_classification', '')}
        detail = {
            'input': item.get('input', item.get('problem', '')),
            'status': item.get('status', 'pending'),
            'classification': cls or {},
        }
        if not detail.get('classification') and detail['status'] == 'pending':
            detail['output'] = '待分类'
        details.append(detail)

    total = summary.get('total', len(details))
    classified = summary.get('classified', sum(1 for d in details if d.get('status') == 'classified'))

    return {
        'summary': {
            'total': total,
            'classified': classified,
            'unknown_issue': summary.get('unknown_issue', 0),
            'infer_failed': summary.get('infer_failed', 0),
            'too_long': summary.get('too_long', 0),
        },
        'details': details,
    }


def read_report_db(db_path: str) -> dict:
    """从指定 DB 读取 report 表数据。report 表不存在时返回 None。"""
    conn = sqlite3.connect(db_path)
    has = table_exists(conn, REPORT_TABLE)
    conn.close()
    if has:
        return read_data_from_db(db_path, REPORT_TABLE)
    return None


def read_report(output_dir: str) -> dict:
    """读取输出目录下的 report.db（report 表）。返回 {summary, details} 或 None。"""
    output_dir = os.path.abspath(output_dir)
    report_db = os.path.join(output_dir, "report.db")
    if os.path.isfile(report_db):
        return read_report_db(report_db)
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
      - 目录：读取该目录下 report.db 的 report 表
      - .db 文件：读取其 report 表
      - .json 文件：旧 JSON 格式
    """
    if not template_path:
        template_path = DEFAULT_TEMPLATE

    # 判定输入类型并读取单表数据
    if os.path.isdir(input_path):
        input_dir = os.path.abspath(input_path)
        data = read_report(input_dir)
    elif input_path.endswith('.db'):
        input_dir = os.path.dirname(os.path.abspath(input_path))
        data = read_report_db(input_path)
    else:
        input_dir = os.path.dirname(os.path.abspath(input_path))
        data = read_data_from_json(input_path)

    if not data:
        return None

    summary = data['summary']
    details = data['details']
    total = summary.get('total', len(details))
    classified = summary.get('classified', 0)
    unknown_issue = summary.get('unknown_issue', 0)
    infer_failed = summary.get('infer_failed', 0)
    too_long = summary.get('too_long', 0)

    # 查找 Excel 来源文件名（目录内的 .xlsx/.xls）
    excel_filename = ''
    if os.path.isdir(input_dir) and os.path.exists(input_dir):
        for f in os.listdir(input_dir):
            if f.endswith('.xlsx') or f.endswith('.xls'):
                excel_filename = f
                break

    variables = {
        'TOTAL': total,
        'CLASSIFIED': classified,
        'UNKNOWN_ISSUE': unknown_issue,
        'INFER_FAILED': infer_failed,
        'TOO_LONG': too_long,
        # 单表数据：功能域用 full_path 多级、业务域用 business_classification 单层，模板内视图切换
        'DATA_JSON': json.dumps(data, ensure_ascii=False),
        'GENERATED_TIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'EXCEL_FILENAME': excel_filename,
        'HAS_EXCEL_FILENAME': bool(excel_filename),
    }

    html = render_template(template_path, variables)

    # 内联 Chart.js 到 HTML，避免浏览器 file:// 打开报告时 CDN 脚本加载失败导致图表不渲染
    chart_js_src = os.path.join(SKILL_DIR, 'assets', 'chart.js')
    if os.path.isfile(chart_js_src):
        with open(chart_js_src, 'r', encoding='utf-8') as f:
            chart_js_content = f.read()
        html = html.replace('<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>',
                            '<script>\n' + chart_js_content + '\n</script>')

    # 确定输出路径
    if not output_path:
        if os.path.isdir(input_path):
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

    # 打印报告摘要（供调用方与命令行直接运行复用）
    print(f"\n报告已生成: {output_path}")
    print("| 属性 | 值 |")
    print("|------|-----|")
    print(f"| 总数据 | {total} |")
    print(f"| 已分类 | {classified} |")
    print(f"| 未知问题 | {unknown_issue} |")
    print(f"| 推理失败 | {infer_failed} |")

    return {
        'path': output_path,
        'total': total,
        'classified': classified,
        'unknown_issue': unknown_issue,
        'infer_failed': infer_failed,
    }


def main():
    if len(sys.argv) < 2:
        print("用法: python generate_report.py <输出目录或分析结果JSON/DB路径> [输出HTML路径] [模板HTML路径]")
        print("      读 report.db 的 report 表生成报告（功能域/业务域视图切换）")
        print("      未指定输出路径时，结果将保存在输入文件所在目录")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    template_path = sys.argv[3] if len(sys.argv) > 3 else None

    result = generate_report(input_path, output_path, template_path)
    if not result:
        print("报告生成失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
