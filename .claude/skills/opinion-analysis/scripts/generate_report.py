#!/usr/bin/env python3
"""
可视化报告生成脚本（支持JSON和SQLite输入）

分类格式：一级分类.二级分类.三级分类
例如：卡顿.滑动卡顿.首页推荐视频流上下滑动卡顿

用法: python generate_report.py <分析结果JSON或DB路径> [输出HTML路径]
输出: HTML 可视化报告（简洁界面，适合用户查看）
"""

import sys
import json
import os
import sqlite3
from datetime import datetime


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

    # 兼容items格式（旧prepared.json）
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

        # 新格式
        if cls.get('level1') and cls.get('level2') and cls.get('level3'):
            detail = {
                'input': item.get('input', item.get('problem', '')),
                'status': item.get('status', 'success'),
                'classification': cls,
            }
        # 旧格式转换
        elif cls.get('module') and cls.get('issue_type'):
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
    if not summary.get('classified'):
        classified = sum(1 for d in details if d.get('status') == 'success')
        no_description = sum(1 for d in details if d.get('status') == 'no_description')
        unrecognized = sum(1 for d in details if d.get('status') == 'unrecognized')
        summary = {
            'total': total,
            'classified': classified,
            'no_description': no_description,
            'unrecognized_app': unrecognized,
        }

    return {
        'summary': summary,
        'details': details,
    }


def generate_report(input_path: str, output_path: str = None) -> str:
    """根据分析结果生成可视化 HTML 报告"""

    # 根据输入类型选择读取方式
    if input_path.endswith('.db'):
        report_data = read_data_from_db(input_path)
    else:
        report_data = read_data_from_json(input_path)

    summary = report_data['summary']
    details = report_data['details']

    total = summary.get('total', len(details))
    classified = summary.get('classified', 0)
    no_description = summary.get('no_description', 0)
    unrecognized = summary.get('unrecognized_app', 0)

    # Excel来源文件名
    input_dir = os.path.dirname(os.path.abspath(input_path))
    excel_filename = ''
    for f in os.listdir(input_dir):
        if f.endswith('.xlsx') or f.endswith('.xls'):
            excel_filename = f
            break

    if not excel_filename:
        excel_filename = ''

    details_json = json.dumps(details, ensure_ascii=False)
    generated_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    parts = []

    # HTML头部
    parts.append('<!DOCTYPE html>')
    parts.append('<html lang="zh-CN">')
    parts.append('<head>')
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append('<title>舆情分析报告</title>')
    parts.append('<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>')
    parts.append('<style>')

    # 样式
    parts.append('* { margin: 0; padding: 0; box-sizing: border-box; overflow-anchor: none; }')
    parts.append('body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #1e293b; line-height: 1.5; }')
    parts.append('.container { max-width: 1200px; margin: 0 auto; padding: 24px; }')
    parts.append('.header { background: white; border-radius: 12px; padding: 24px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }')
    parts.append('.header-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }')
    parts.append('.header h1 { font-size: 20px; font-weight: 600; color: #0f172a; }')
    parts.append('.header-right { display: flex; align-items: center; gap: 16px; }')
    parts.append('.header .time { font-size: 13px; color: #64748b; }')
    parts.append('.excel-link { font-size: 13px; color: white; text-decoration: none; padding: 6px 12px; background: #3b82f6; border-radius: 6px; display: inline-flex; align-items: center; gap: 6px; transition: background 0.2s; }')
    parts.append('.excel-link:hover { background: #2563eb; }')
    parts.append('.excel-link::before { content: "⬇"; font-size: 14px; }')

    # 统计卡片
    parts.append('.stats-row { display: flex; gap: 12px; }')
    parts.append('.stat-card { flex: 1; background: #f1f5f9; border-radius: 8px; padding: 16px; text-align: center; }')
    parts.append('.stat-card .num { font-size: 28px; font-weight: 700; color: #0f172a; }')
    parts.append('.stat-card .label { font-size: 12px; color: #64748b; margin-top: 4px; }')
    parts.append('.stat-card.success .num { color: #16a34a; }')
    parts.append('.stat-card.warning .num { color: #ca8a04; }')
    parts.append('.stat-card.error .num { color: #dc2626; }')

    # 过滤工具栏
    parts.append('.toolbar { background: white; border-radius: 12px; padding: 16px 24px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }')
    parts.append('.filter-select { display: flex; align-items: center; gap: 8px; }')
    parts.append('.filter-select label { font-size: 13px; color: #64748b; font-weight: 500; }')
    parts.append('.filter-select select { padding: 8px 12px; border-radius: 6px; border: 1px solid #e2e8f0; background: white; font-size: 13px; color: #1e293b; cursor: pointer; min-width: 140px; }')
    parts.append('.filter-select select:focus { outline: none; border-color: #3b82f6; }')
    parts.append('.filter-select select:disabled { background: #f1f5f9; color: #94a3b8; cursor: not-allowed; }')

    # 搜索框
    parts.append('.search-box { display: flex; align-items: center; gap: 8px; margin-left: auto; }')
    parts.append('.search-box input { padding: 8px 12px; border-radius: 6px; border: 1px solid #e2e8f0; font-size: 13px; width: 200px; }')
    parts.append('.search-box input:focus { outline: none; border-color: #3b82f6; }')

    # 筛选路径
    parts.append('.filter-path { font-size: 14px; color: #64748b; margin-left: 8px; }')
    parts.append('.filter-path .item { color: #3b82f6; cursor: pointer; }')
    parts.append('.filter-path .item:hover { text-decoration: underline; }')
    parts.append('.filter-path .sep { color: #94a3b8; margin: 0 4px; }')

    # 图表区
    parts.append('.charts-section { background: white; border-radius: 12px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }')
    parts.append('.section-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-bottom: 1px solid #e2e8f0; }')
    parts.append('.section-header h2 { font-size: 15px; font-weight: 600; color: #0f172a; }')
    parts.append('.section-header .toggle { font-size: 13px; color: #3b82f6; cursor: pointer; }')
    parts.append('.charts-content { padding: 24px; display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; }')
    parts.append('.charts-content.collapsed { display: none; }')
    parts.append('.chart-box h3 { font-size: 13px; font-weight: 500; color: #475569; margin-bottom: 12px; }')
    parts.append('.chart-wrap { height: 280px; position: relative; }')

    # 数据表格
    parts.append('.table-section { background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow-anchor: none; }')
    parts.append('.table-header { padding: 16px 24px; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; }')
    parts.append('.table-header h2 { font-size: 15px; font-weight: 600; color: #0f172a; }')
    parts.append('.table-header .count { font-size: 13px; color: #64748b; }')
    parts.append('.table-container { overflow-x: auto; overflow-anchor: none; }')
    parts.append('table { width: 100%; border-collapse: collapse; font-size: 13px; }')
    parts.append('th { background: #f8fafc; padding: 12px 16px; text-align: left; font-weight: 500; color: #475569; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }')
    parts.append('td { padding: 12px 16px; border-bottom: 1px solid #f1f5f9; }')
    parts.append('tr:hover { background: #f8fafc; }')
    parts.append('.status-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }')
    parts.append('.status-badge.success { background: #dcfce7; color: #16a34a; }')
    parts.append('.status-badge.error { background: #fee2e2; color: #dc2626; }')
    parts.append('.status-badge.warning { background: #fef3c7; color: #ca8a04; }')

    # 应用标签
    parts.append('.app-tag { display: inline-block; padding: 3px 10px; border-radius: 6px; background: #3b82f6; color: white; font-size: 12px; font-weight: 500; }')

    # 分类路径
    parts.append('.cls-path { font-size: 12px; color: #64748b; }')
    parts.append('.cls-path .item { cursor: pointer; color: #3b82f6; }')
    parts.append('.cls-path .item:hover { text-decoration: underline; }')
    parts.append('.cls-path .sep { color: #94a3b8; margin: 0 2px; }')

    # 空状态
    parts.append('.empty-state { padding: 48px 24px; text-align: center; color: #64748b; }')
    parts.append('.empty-state .icon { font-size: 48px; margin-bottom: 16px; }')
    parts.append('.empty-state p { font-size: 14px; }')
    parts.append('.hidden { display: none; }')

    # 弹窗样式
    parts.append('.modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1000; }')
    parts.append('.modal-overlay.hidden { display: none; }')
    parts.append('.modal { background: white; border-radius: 12px; max-width: 800px; width: 90%; max-height: 80vh; overflow: hidden; box-shadow: 0 20px 40px rgba(0,0,0,0.2); }')
    parts.append('.modal-header { padding: 16px 24px; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; }')
    parts.append('.modal-header h3 { font-size: 16px; font-weight: 600; color: #0f172a; }')
    parts.append('.modal-close { font-size: 20px; color: #64748b; cursor: pointer; line-height: 1; }')
    parts.append('.modal-close:hover { color: #1e293b; }')
    parts.append('.modal-body { padding: 24px; overflow-x: auto; }')
    parts.append('.modal-body table { width: 100%; border-collapse: collapse; }')
    parts.append('.modal-body th { background: #f1f5f9; padding: 12px 16px; text-align: left; font-weight: 500; color: #475569; border: 1px solid #e2e8f0; white-space: nowrap; }')
    parts.append('.modal-body td { padding: 12px 16px; border: 1px solid #e2e8f0; word-break: break-all; }')

    # 分页样式
    parts.append('.pagination { display: flex; justify-content: center; align-items: center; gap: 8px; padding: 16px; border-top: 1px solid #e2e8f0; }')
    parts.append('.pagination button { padding: 8px 16px; border: 1px solid #e2e8f0; border-radius: 6px; background: white; color: #475569; cursor: pointer; font-size: 13px; }')
    parts.append('.pagination button:hover:not(:disabled) { background: #f1f5f9; }')
    parts.append('.pagination button:disabled { opacity: 0.5; cursor: not-allowed; }')
    parts.append('.pagination button.active { background: #3b82f6; color: white; border-color: #3b82f6; }')
    parts.append('.pagination .page-info { font-size: 13px; color: #64748b; }')

    # 问题描述样式
    parts.append('.problem-text { cursor: pointer; color: #3b82f6; display: block; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }')
    parts.append('.problem-text:hover { text-decoration: underline; }')

    parts.append('</style>')
    parts.append('</head>')
    parts.append('<body>')
    parts.append('<div class="container">')

    # 头部
    parts.append('<div class="header">')
    parts.append('<div class="header-top">')
    parts.append('<h1>舆情分析报告</h1>')
    parts.append('<div class="header-right">')
    if excel_filename:
        parts.append(f'<a href="{excel_filename}" class="excel-link" download title="下载原始Excel数据">下载原始数据</a>')
    parts.append(f'<span class="time">{generated_time}</span>')
    parts.append('</div>')
    parts.append('</div>')
    parts.append('<div class="stats-row">')
    parts.append(f'<div class="stat-card"><div class="num">{total}</div><div class="label">总数据</div></div>')
    parts.append(f'<div class="stat-card error"><div class="num">{unrecognized}</div><div class="label">未知问题</div></div>')
    parts.append('</div>')
    parts.append('</div>')

    # 过滤工具栏
    parts.append('<div class="toolbar">')
    parts.append('<div class="filter-select"><label>一级分类</label><select id="filter-level1" onchange="onFilterChange(\'level1\')"><option value="">全部</option></select></div>')
    parts.append('<div class="filter-select"><label>二级分类</label><select id="filter-level2" onchange="onFilterChange(\'level2\')" disabled><option value="">全部</option></select></div>')
    parts.append('<div class="filter-select"><label>三级分类</label><select id="filter-level3" onchange="onFilterChange(\'level3\')" disabled><option value="">全部</option></select></div>')
    parts.append('<div class="search-box"><input type="text" id="search-input" placeholder="搜索问题描述..." onkeyup="onSearch()"></input></div>')
    parts.append('</div>')

    # 图表区
    parts.append('<div class="charts-section">')
    parts.append('<div class="section-header">')
    parts.append('<h2>数据分布 <span id="filter-path" class="filter-path"></span></h2>')
    parts.append('<span class="toggle" onclick="toggleCharts()">收起</span>')
    parts.append('</div>')
    parts.append('<div class="charts-content" id="charts-content">')
    parts.append('<div class="chart-box"><h3 id="bar-title">一级分类分布</h3><div class="chart-wrap"><canvas id="level1Chart"></canvas></div></div>')
    parts.append('<div class="chart-box"><h3 id="pie-title">一级分类分布</h3><div class="chart-wrap"><canvas id="pieChart"></canvas></div></div>')
    parts.append('</div>')
    parts.append('</div>')

    # 数据表格
    parts.append('<div class="table-section">')
    parts.append('<div class="table-header">')
    parts.append('<h2>详细数据</h2>')
    parts.append('<span class="count" id="table-count">0 条</span>')
    parts.append('</div>')
    parts.append('<div class="table-container">')
    parts.append('<table>')
    parts.append('<thead><tr>')
    parts.append('<th style="width:60px">序号</th>')
    parts.append('<th style="width:250px">问题描述</th>')
    parts.append('<th style="width:100px">应用</th>')
    parts.append('<th>分类</th>')
    parts.append('<th style="width:300px">推理说明</th>')
    parts.append('</tr></thead>')
    parts.append('<tbody id="table-body"></tbody>')
    parts.append('</table>')
    parts.append('</div>')
    parts.append('<div class="pagination" id="pagination"></div>')
    parts.append('<div class="empty-state hidden" id="empty-state"><div class="icon">🔍</div><p>没有找到匹配的数据</p></div>')
    parts.append('</div>')

    # 弹窗
    parts.append('<div class="modal-overlay hidden" id="modal-overlay" onclick="closeModal()">')
    parts.append('<div class="modal" onclick="event.stopPropagation()">')
    parts.append('<div class="modal-header">')
    parts.append('<h3>数据详情</h3>')
    parts.append('<span class="modal-close" onclick="closeModal()">×</span>')
    parts.append('</div>')
    parts.append('<div class="modal-body" id="modal-body"></div>')
    parts.append('</div>')
    parts.append('</div>')

    parts.append('</div>')

    # JavaScript
    parts.append('<script>')
    parts.append(f'const allData = {details_json};')
    parts.append('let filters = { level1: "", level2: "", level3: "" };')
    parts.append('let searchText = "";')
    parts.append('let charts = {};')
    parts.append('let chartsVisible = true;')
    parts.append('let currentPage = 1;')
    parts.append('const pageSize = 50;')

    # 获取所有可用选项
    parts.append('function getAllOptions() {')
    parts.append('const level1s = {}, level2s = {}, level3s = {};')
    parts.append('allData.forEach(item => {')
    parts.append('if (item.status === "unrecognized") {')
    parts.append('level1s["未知问题"] = true;')
    parts.append('return;')
    parts.append('}')
    parts.append('if (item.status === "success") {')
    parts.append('const cls = item.classification;')
    parts.append('level1s[cls.level1] = true;')
    parts.append('level2s[cls.level2] = true;')
    parts.append('level3s[cls.level3] = true;')
    parts.append('}});')
    parts.append('return { level1s: Object.keys(level1s).sort(), level2s: Object.keys(level2s).sort(), level3s: Object.keys(level3s).sort() };')
    parts.append('}')

    # 获取当前可用的二级分类选项
    parts.append('function getAvailableLevel2(level1) {')
    parts.append('const level2s = {};')
    parts.append('allData.forEach(item => {')
    parts.append('if (item.status === "success") {')
    parts.append('const cls = item.classification;')
    parts.append('if (!level1 || cls.level1 === level1) {')
    parts.append('level2s[cls.level2] = true;')
    parts.append('}}});')
    parts.append('return Object.keys(level2s).sort();')
    parts.append('}')

    # 获取当前可用的三级分类选项
    parts.append('function getAvailableLevel3(level1, level2) {')
    parts.append('const level3s = {};')
    parts.append('allData.forEach(item => {')
    parts.append('if (item.status === "success") {')
    parts.append('const cls = item.classification;')
    parts.append('if (!level1 || cls.level1 === level1) {')
    parts.append('if (!level2 || cls.level2 === level2) {')
    parts.append('level3s[cls.level3] = true;')
    parts.append('}}}});')
    parts.append('return Object.keys(level3s).sort();')
    parts.append('}')

    # 初始化下拉选项
    parts.append('function initSelectOptions() {')
    parts.append('const opts = getAllOptions();')
    parts.append('fillSelect("filter-level1", opts.level1s, "全部");')
    parts.append('}')

    parts.append('function fillSelect(id, options, placeholder = "全部") {')
    parts.append('const sel = document.getElementById(id);')
    parts.append('const currentValue = sel.value;')
    parts.append('sel.innerHTML = "<option value=\\"\\">" + placeholder + "</option>";')
    parts.append('options.forEach(opt => {')
    parts.append('const optEl = document.createElement("option");')
    parts.append('optEl.value = opt;')
    parts.append('optEl.textContent = opt;')
    parts.append('sel.appendChild(optEl);')
    parts.append('});')
    parts.append('if (options.includes(currentValue)) {')
    parts.append('sel.value = currentValue;')
    parts.append('} else {')
    parts.append('sel.value = "";')
    parts.append('}')
    parts.append('}')

    # 获取过滤后的数据
    parts.append('function getFilteredData() {')
    parts.append('return allData.filter(item => {')
    parts.append('if (item.status === "unrecognized") {')
    parts.append('if (filters.level1 === "未知问题") return true;')
    parts.append('if (filters.level1 || filters.level2 || filters.level3) return false;')
    parts.append('if (searchText) {')
    parts.append('const text = (item.input || "").toLowerCase();')
    parts.append('if (!text.includes(searchText.toLowerCase())) return false;')
    parts.append('}')
    parts.append('return true;')
    parts.append('}')
    parts.append('if (item.status === "success") {')
    parts.append('const cls = item.classification;')
    parts.append('if (filters.level1 && cls.level1 !== filters.level1) return false;')
    parts.append('if (filters.level2 && cls.level2 !== filters.level2) return false;')
    parts.append('if (filters.level3 && cls.level3 !== filters.level3) return false;')
    parts.append('}')
    parts.append('if (searchText) {')
    parts.append('const text = (item.input || "").toLowerCase();')
    parts.append('if (!text.includes(searchText.toLowerCase())) return false;')
    parts.append('}')
    parts.append('return true;')
    parts.append('});')
    parts.append('}')

    # 计算统计
    parts.append('function calcStats(data) {')
    parts.append('const stats = { level1: {}, level2: {}, level3: {} };')
    parts.append('data.forEach(item => {')
    parts.append('if (item.status === "unrecognized") {')
    parts.append('stats.level1["未知问题"] = (stats.level1["未知问题"] || 0) + 1;')
    parts.append('return;')
    parts.append('}')
    parts.append('if (item.status !== "success") return;')
    parts.append('const cls = item.classification;')
    parts.append('stats.level1[cls.level1] = (stats.level1[cls.level1] || 0) + 1;')
    parts.append('stats.level2[cls.level2] = (stats.level2[cls.level2] || 0) + 1;')
    parts.append('stats.level3[cls.level3] = (stats.level3[cls.level3] || 0) + 1;')
    parts.append('});')
    parts.append('return stats;')
    parts.append('}')

    # 过滤变更（移除状态筛选）
    parts.append('function onFilterChange(source) {')
    parts.append('const level1Sel = document.getElementById("filter-level1");')
    parts.append('const level2Sel = document.getElementById("filter-level2");')
    parts.append('const level3Sel = document.getElementById("filter-level3");')

    parts.append('if (source === "level1") {')
    parts.append('filters.level1 = level1Sel.value;')
    parts.append('if (filters.level1) {')
    parts.append('const availableLevel2 = getAvailableLevel2(filters.level1);')
    parts.append('fillSelect("filter-level2", availableLevel2, "全部");')
    parts.append('level2Sel.disabled = false;')
    parts.append('} else {')
    parts.append('level2Sel.disabled = true;')
    parts.append('level2Sel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('level3Sel.disabled = true;')
    parts.append('level3Sel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('}')
    parts.append('filters.level2 = "";')
    parts.append('filters.level3 = "";')
    parts.append('}')

    parts.append('if (source === "level2") {')
    parts.append('filters.level2 = level2Sel.value;')
    parts.append('if (filters.level2) {')
    parts.append('const availableLevel3 = getAvailableLevel3(filters.level1, filters.level2);')
    parts.append('fillSelect("filter-level3", availableLevel3, "全部");')
    parts.append('level3Sel.disabled = false;')
    parts.append('} else {')
    parts.append('level3Sel.disabled = true;')
    parts.append('level3Sel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('}')
    parts.append('filters.level3 = "";')
    parts.append('}')

    parts.append('if (source === "level3") {')
    parts.append('filters.level3 = level3Sel.value;')
    parts.append('}')

    parts.append('currentPage = 1;')
    parts.append('updateAll();')
    parts.append('}')

    # 搜索
    parts.append('function onSearch() {')
    parts.append('searchText = document.getElementById("search-input").value;')
    parts.append('currentPage = 1;')
    parts.append('updateAll();')
    parts.append('}')

    # 清除筛选
    parts.append('function clearFilters() {')
    parts.append('filters = { level1: "", level2: "", level3: "" };')
    parts.append('searchText = "";')
    parts.append('const opts = getAllOptions();')
    parts.append('fillSelect("filter-level1", opts.level1s, "全部");')
    parts.append('document.getElementById("filter-level1").value = "";')
    parts.append('const level2Sel = document.getElementById("filter-level2");')
    parts.append('level2Sel.disabled = true;')
    parts.append('level2Sel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('const level3Sel = document.getElementById("filter-level3");')
    parts.append('level3Sel.disabled = true;')
    parts.append('level3Sel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('document.getElementById("search-input").value = "";')
    parts.append('currentPage = 1;')
    parts.append('updateAll();')
    parts.append('}')

    # 折叠图表
    parts.append('function toggleCharts() {')
    parts.append('chartsVisible = !chartsVisible;')
    parts.append('const content = document.getElementById("charts-content");')
    parts.append('const toggle = document.querySelector(".section-header .toggle");')
    parts.append('if (chartsVisible) {')
    parts.append('content.classList.remove("collapsed");')
    parts.append('toggle.textContent = "收起";')
    parts.append('} else {')
    parts.append('content.classList.add("collapsed");')
    parts.append('toggle.textContent = "展开";')
    parts.append('}')
    parts.append('}')

    # 更新筛选路径
    parts.append('function updateBreadcrumb() {')
    parts.append('const pathEl = document.getElementById("filter-path");')
    parts.append('if (!filters.level1 && !filters.level2 && !filters.level3 && !searchText) {')
    parts.append('pathEl.innerHTML = "";')
    parts.append('return;')
    parts.append('}')
    parts.append('const parts = ["全部"];')
    parts.append('if (filters.level1) parts.push(filters.level1);')
    parts.append('if (filters.level2) parts.push(filters.level2);')
    parts.append('if (filters.level3) parts.push(filters.level3);')
    parts.append('if (searchText) parts.push("搜索:" + searchText);')
    parts.append('pathEl.innerHTML = parts.map((p, i) => {')
    parts.append('if (i === 0) return `<span class="item" onclick="clearFilters()">${p}</span>`;')
    parts.append('return `<span class="item" onclick="clearLevel(${i})">${p}</span>`;')
    parts.append('}).join("<span class=\'sep\'>›</span>");')
    parts.append('}')

    # 清除指定层级
    parts.append('function clearLevel(level) {')
    parts.append('if (level === 1) {')
    parts.append('filters.level2 = ""; filters.level3 = "";')
    parts.append('const availableLevel2 = getAvailableLevel2(filters.level1);')
    parts.append('fillSelect("filter-level2", availableLevel2, "全部");')
    parts.append('document.getElementById("filter-level2").disabled = false;')
    parts.append('document.getElementById("filter-level2").value = "";')
    parts.append('document.getElementById("filter-level3").disabled = true;')
    parts.append('document.getElementById("filter-level3").innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('} else if (level === 2) {')
    parts.append('filters.level3 = "";')
    parts.append('const availableLevel3 = getAvailableLevel3(filters.level1, filters.level2);')
    parts.append('fillSelect("filter-level3", availableLevel3, "全部");')
    parts.append('document.getElementById("filter-level3").disabled = false;')
    parts.append('document.getElementById("filter-level3").value = "";')
    parts.append('}')
    parts.append('searchText = ""; document.getElementById("search-input").value = "";')
    parts.append('currentPage = 1;')
    parts.append('updateAll();')
    parts.append('}')

    # 更新表格
    parts.append('function updateTable() {')
    parts.append('const tbody = document.getElementById("table-body");')
    parts.append('const empty = document.getElementById("empty-state");')
    parts.append('const countEl = document.getElementById("table-count");')
    parts.append('const paginationEl = document.getElementById("pagination");')
    parts.append('const filtered = getFilteredData();')
    parts.append('countEl.textContent = filtered.length + " 条";')
    parts.append('const totalPages = Math.ceil(filtered.length / pageSize);')
    parts.append('if (currentPage > totalPages) currentPage = totalPages || 1;')
    parts.append('const start = (currentPage - 1) * pageSize;')
    parts.append('const end = start + pageSize;')
    parts.append('const pageData = filtered.slice(start, end);')
    parts.append('tbody.innerHTML = "";')
    parts.append('if (filtered.length === 0) {')
    parts.append('empty.classList.remove("hidden");')
    parts.append('paginationEl.innerHTML = "";')
    parts.append('return;')
    parts.append('}')
    parts.append('empty.classList.add("hidden");')
    parts.append('pageData.forEach((item, i) => {')
    parts.append('const globalIndex = start + i;')
    parts.append('const row = document.createElement("tr");')
    parts.append('row.dataset.index = globalIndex;')
    parts.append('const cls = item.classification || {};')
    parts.append('let clsHtml = "";')
    parts.append('if (item.status === "success") {')
    parts.append('const parts = [];')
    parts.append('if (cls.level1) parts.push(`<span class="item" onclick="setFilterWithPath(\'${cls.level1}\',\'\',\'\',\'level1\',\'${cls.level1}\')">${cls.level1}</span>`);')
    parts.append('if (cls.level2) parts.push(`<span class="sep">.</span><span class="item" onclick="setFilterWithPath(\'${cls.level1}\',\'${cls.level2}\',\'\',\'level2\',\'${cls.level2}\')">${cls.level2}</span>`);')
    parts.append('if (cls.level3) parts.push(`<span class="sep">.</span><span class="item" onclick="setFilterWithPath(\'${cls.level1}\',\'${cls.level2}\',\'${cls.level3}\',\'level3\',\'${cls.level3}\')">${cls.level3}</span>`);')
    parts.append('clsHtml = `<span class="cls-path">${parts.join("")}</span>`;')
    parts.append('} else {')
    parts.append('clsHtml = `<span class="cls-path"><span class="item" onclick="setFilterWithPath(\'未知问题\',\'\',\'\',\'level1\',\'未知问题\')" style="color:#dc2626">未知问题</span></span>`;')
    parts.append('}')
    parts.append('row.innerHTML = `')
    parts.append('<td>${globalIndex + 1}</td>')
    parts.append('<td><span class="problem-text" title="${item.input}" onclick="showDetail(${globalIndex})">${item.input}</span></td>')
    parts.append('<td><span class="app-tag">${cls.app || (item.raw_data && item.raw_data["应用名"]) || ""}</span></td>')
    parts.append('<td>${clsHtml}</td>')
    parts.append('<td>${item.reasoning || ""}</td>')
    parts.append('`;')
    parts.append('tbody.appendChild(row);')
    parts.append('});')
    parts.append('updatePagination(filtered.length, totalPages);')
    parts.append('}')

    # 简单筛选函数
    parts.append('function setFilter(field, value) {')
    parts.append('const level1Sel = document.getElementById("filter-level1");')
    parts.append('const level2Sel = document.getElementById("filter-level2");')
    parts.append('const level3Sel = document.getElementById("filter-level3");')

    parts.append('if (field === "level1") {')
    parts.append('filters.level1 = value;')
    parts.append('level1Sel.value = value;')
    parts.append('const availableLevel2 = getAvailableLevel2(value);')
    parts.append('fillSelect("filter-level2", availableLevel2, "全部");')
    parts.append('level2Sel.disabled = false;')
    parts.append('level2Sel.value = "";')
    parts.append('filters.level2 = "";')
    parts.append('level3Sel.disabled = true;')
    parts.append('level3Sel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.level3 = "";')
    parts.append('} else if (field === "level2") {')
    parts.append('filters.level2 = value;')
    parts.append('level2Sel.value = value;')
    parts.append('const availableLevel3 = getAvailableLevel3(filters.level1, value);')
    parts.append('fillSelect("filter-level3", availableLevel3, "全部");')
    parts.append('level3Sel.disabled = false;')
    parts.append('level3Sel.value = "";')
    parts.append('filters.level3 = "";')
    parts.append('} else if (field === "level3") {')
    parts.append('filters.level3 = value;')
    parts.append('level3Sel.value = value;')
    parts.append('}')
    parts.append('currentPage = 1;')
    parts.append('updateAll();')
    parts.append('}')

    # 设置筛选（点击表格路径时）
    parts.append('function setFilterWithPath(level1, level2, level3, targetField, targetValue) {')
    parts.append('const level1Sel = document.getElementById("filter-level1");')
    parts.append('const level2Sel = document.getElementById("filter-level2");')
    parts.append('const level3Sel = document.getElementById("filter-level3");')

    parts.append('if (targetField === "level1") {')
    parts.append('filters.level1 = targetValue;')
    parts.append('level1Sel.value = targetValue;')
    parts.append('const availableLevel2 = getAvailableLevel2(targetValue);')
    parts.append('fillSelect("filter-level2", availableLevel2, "全部");')
    parts.append('level2Sel.disabled = false;')
    parts.append('level2Sel.value = "";')
    parts.append('filters.level2 = "";')
    parts.append('level3Sel.disabled = true;')
    parts.append('level3Sel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.level3 = "";')
    parts.append('} else if (targetField === "level2") {')
    parts.append('filters.level1 = level1;')
    parts.append('level1Sel.value = level1;')
    parts.append('const availableLevel2 = getAvailableLevel2(level1);')
    parts.append('fillSelect("filter-level2", availableLevel2, "全部");')
    parts.append('level2Sel.disabled = false;')
    parts.append('filters.level2 = targetValue;')
    parts.append('level2Sel.value = targetValue;')
    parts.append('const availableLevel3 = getAvailableLevel3(level1, targetValue);')
    parts.append('fillSelect("filter-level3", availableLevel3, "全部");')
    parts.append('level3Sel.disabled = false;')
    parts.append('level3Sel.value = "";')
    parts.append('filters.level3 = "";')
    parts.append('} else if (targetField === "level3") {')
    parts.append('filters.level1 = level1;')
    parts.append('level1Sel.value = level1;')
    parts.append('const availableLevel2 = getAvailableLevel2(level1);')
    parts.append('fillSelect("filter-level2", availableLevel2, "全部");')
    parts.append('level2Sel.disabled = false;')
    parts.append('filters.level2 = level2;')
    parts.append('level2Sel.value = level2;')
    parts.append('const availableLevel3 = getAvailableLevel3(level1, level2);')
    parts.append('fillSelect("filter-level3", availableLevel3, "全部");')
    parts.append('level3Sel.disabled = false;')
    parts.append('filters.level3 = targetValue;')
    parts.append('level3Sel.value = targetValue;')
    parts.append('}')
    parts.append('currentPage = 1;')
    parts.append('updateAll();')
    parts.append('}')

    # 更新图表
    parts.append('function updateCharts() {')
    parts.append('const filtered = getFilteredData();')
    parts.append('const stats = calcStats(filtered);')
    parts.append('const barTitle = document.getElementById("bar-title");')
    parts.append('const pieTitle = document.getElementById("pie-title");')
    parts.append('if (filters.level2) {')
    parts.append('barTitle.textContent = "三级分类分布";')
    parts.append('pieTitle.textContent = "三级分类分布";')
    parts.append('charts.level1.data.labels = Object.keys(stats.level3);')
    parts.append('charts.level1.data.datasets[0].data = Object.values(stats.level3);')
    parts.append('charts.level1.options.plugins.legend.display = false;')
    parts.append('charts.pie.data.labels = Object.keys(stats.level3);')
    parts.append('charts.pie.data.datasets[0].data = Object.values(stats.level3);')
    parts.append('} else if (filters.level1) {')
    parts.append('barTitle.textContent = "二级分类分布";')
    parts.append('pieTitle.textContent = "二级分类分布";')
    parts.append('charts.level1.data.labels = Object.keys(stats.level2);')
    parts.append('charts.level1.data.datasets[0].data = Object.values(stats.level2);')
    parts.append('charts.level1.options.plugins.legend.display = false;')
    parts.append('charts.pie.data.labels = Object.keys(stats.level2);')
    parts.append('charts.pie.data.datasets[0].data = Object.values(stats.level2);')
    parts.append('} else {')
    parts.append('barTitle.textContent = "一级分类分布";')
    parts.append('pieTitle.textContent = "一级分类分布";')
    parts.append('charts.level1.data.labels = Object.keys(stats.level1);')
    parts.append('charts.level1.data.datasets[0].data = Object.values(stats.level1);')
    parts.append('charts.level1.options.plugins.legend.display = false;')
    parts.append('charts.pie.data.labels = Object.keys(stats.level1);')
    parts.append('charts.pie.data.datasets[0].data = Object.values(stats.level1);')
    parts.append('}')
    parts.append('charts.level1.update();')
    parts.append('charts.pie.update();')
    parts.append('}')

    # 初始化图表
    parts.append('function initCharts() {')
    parts.append('const stats = calcStats(allData);')
    parts.append('const colorPalette = ["#3b82f6","#8b5cf6","#ec4899","#f43f5e","#06b6d4","#14b8a6","#16a34a","#ca8a04","#6366f1","#d946ef","#0ea5e9","#10b981","#f97316","#ef4444","#a855f7","#84cc16","#22d3ee","#e879f9","#fb923c","#34d399"];')
    parts.append('charts.level1 = new Chart(document.getElementById("level1Chart"), {')
    parts.append('type: "bar",')
    parts.append('data: { labels: Object.keys(stats.level1), datasets: [{ data: Object.values(stats.level1), backgroundColor: colorPalette }] },')
    parts.append('options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, onClick: (e,els) => { if(els.length>0) onBarClick(charts.level1.data.labels[els[0].index]); } }')
    parts.append('});')

    parts.append('charts.pie = new Chart(document.getElementById("pieChart"), {')
    parts.append('type: "doughnut",')
    parts.append('data: { labels: Object.keys(stats.level1), datasets: [{ data: Object.values(stats.level1), backgroundColor: colorPalette }] },')
    parts.append('options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: function(ctx) { const total = ctx.dataset.data.reduce((a,b)=>a+b,0); const pct = Math.round(ctx.raw/total*100); return ctx.label + ": " + ctx.raw + " 条 (" + pct + "%)"; } } } }, onClick: (e,els) => { if(els.length>0) onPieClick(charts.pie.data.labels[els[0].index]); } }')
    parts.append('});')
    parts.append('}')

    # 柱状图点击处理
    parts.append('function onBarClick(value) {')
    parts.append('if (filters.level2) {')
    parts.append('setFilter("level3", value);')
    parts.append('} else if (filters.level1) {')
    parts.append('setFilter("level2", value);')
    parts.append('} else {')
    parts.append('setFilter("level1", value);')
    parts.append('}')
    parts.append('}')

    # 饼图点击处理
    parts.append('function onPieClick(value) {')
    parts.append('if (filters.level2) {')
    parts.append('setFilter("level3", value);')
    parts.append('} else if (filters.level1) {')
    parts.append('setFilter("level2", value);')
    parts.append('} else {')
    parts.append('setFilter("level2", value);')
    parts.append('}')
    parts.append('}')

    # 全量更新
    parts.append('function updateAll() {')
    parts.append('updateCharts();')
    parts.append('updateBreadcrumb();')
    parts.append('updateTable();')
    parts.append('}')

    # 更新分页
    parts.append('function updatePagination(total, totalPages) {')
    parts.append('const paginationEl = document.getElementById("pagination");')
    parts.append('if (totalPages <= 1) {')
    parts.append('paginationEl.innerHTML = "";')
    parts.append('return;')
    parts.append('}')
    parts.append('let html = "";')
    parts.append('html += `<button onclick="goToPage(1)" ${currentPage === 1 ? "disabled" : ""}>首页</button>`;')
    parts.append('html += `<button onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? "disabled" : ""}>上一页</button>`;')
    parts.append('const startPage = Math.max(1, currentPage - 2);')
    parts.append('const endPage = Math.min(totalPages, startPage + 4);')
    parts.append('for (let p = startPage; p <= endPage; p++) {')
    parts.append('html += `<button onclick="goToPage(${p})" class="${p === currentPage ? "active" : ""}">${p}</button>`;')
    parts.append('}')
    parts.append('html += `<button onclick="goToPage(${currentPage + 1})" ${currentPage === totalPages ? "disabled" : ""}>下一页</button>`;')
    parts.append('html += `<button onclick="goToPage(${totalPages})" ${currentPage === totalPages ? "disabled" : ""}>末页</button>`;')
    parts.append('html += `<span class="page-info">第 ${currentPage}/${totalPages} 页，共 ${total} 条</span>`;')
    parts.append('paginationEl.innerHTML = html;')
    parts.append('}')

    # 跳转页面
    parts.append('function goToPage(page) {')
    parts.append('const filtered = getFilteredData();')
    parts.append('const totalPages = Math.ceil(filtered.length / pageSize);')
    parts.append('if (page < 1) page = 1;')
    parts.append('if (page > totalPages) page = totalPages;')
    parts.append('currentPage = page;')
    parts.append('updateTable();')
    parts.append('}')

    # 显示详情弹窗（显示原始数据行）
    parts.append('function showDetail(index) {')
    parts.append('const filtered = getFilteredData();')
    parts.append('const item = filtered[index];')
    parts.append('const raw = item.raw_data || {};')
    parts.append('const body = document.getElementById("modal-body");')
    parts.append('let html = "<table><thead><tr>";')
    parts.append('for (const key in raw) {')
    parts.append('html += `<th>${key}</th>`;')
    parts.append('}')
    parts.append('html += "</tr></thead><tbody><tr>";')
    parts.append('for (const key in raw) {')
    parts.append('html += `<td>${raw[key]}</td>`;')
    parts.append('}')
    parts.append('html += "</tr></tbody></table>";')
    parts.append('body.innerHTML = html;')
    parts.append('document.getElementById("modal-overlay").classList.remove("hidden");')
    parts.append('}')

    # 关闭弹窗
    parts.append('function closeModal() {')
    parts.append('document.getElementById("modal-overlay").classList.add("hidden");')
    parts.append('}')

    # 页面初始化
    parts.append('document.addEventListener("DOMContentLoaded", () => {')
    parts.append('initSelectOptions();')
    parts.append('initCharts();')
    parts.append('updateAll();')
    parts.append('});')
    parts.append('</script>')
    parts.append('</body>')
    parts.append('</html>')

    html = '\n'.join(parts)

    # 确定输出路径
    if not output_path:
        input_dir = os.path.dirname(os.path.abspath(input_path))
        input_basename = os.path.basename(input_path)
        # 去掉扩展名
        for ext in ['.json', '.db']:
            if input_basename.endswith(ext):
                input_basename = input_basename[:-len(ext)]
        # 去掉后缀
        for suffix in ['_classified', '_prepared']:
            if input_basename.endswith(suffix):
                input_basename = input_basename[:-len(suffix)]
        output_path = os.path.join(input_dir, f"{input_basename}_report.html")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return output_path


def main():
    if len(sys.argv) < 2:
        print("用法: python generate_report.py <分析结果JSON或DB路径> [输出HTML路径]")
        print("      未指定输出路径时，结果将保存在输入文件所在目录")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    result_path = generate_report(input_path, output_path)
    print(f"报告已生成: {result_path}")


if __name__ == "__main__":
    main()