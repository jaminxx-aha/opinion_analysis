#!/usr/bin/env python3
"""
可视化报告生成脚本（优化界面设计）

用法: python generate_report.py <分析结果JSON路径> [输出HTML路径]
输出: HTML 可视化报告（简洁界面，适合用户查看）
"""

import sys
import json
import os
from datetime import datetime


def generate_report(json_path: str, output_path: str = None) -> str:
    """根据分析结果 JSON 生成可视化 HTML 报告"""

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    summary = data.get('summary', {})

    # 检查是否需要从prepared.json补充raw_data
    raw_details = data.get('details', [])
    need_raw_data = False
    if raw_details:
        # 检查第一条是否有raw_data
        first_item = raw_details[0]
        if not first_item.get('raw_data') or first_item.get('raw_data') == {}:
            need_raw_data = True

    # 如果需要补充raw_data，尝试读取prepared.json
    prepared_data = None
    if need_raw_data:
        json_dir = os.path.dirname(os.path.abspath(json_path))
        json_basename = os.path.basename(json_path).replace('_classified.json', '_prepared.json')
        prepared_path = os.path.join(json_dir, json_basename)
        if os.path.exists(prepared_path):
            with open(prepared_path, 'r', encoding='utf-8') as f:
                prepared_data = json.load(f)

    # 兼容多种格式：
    # 1. details + input + 嵌套classification 格式
    # 2. items + problem 格式
    # 3. details + 扁平格式（classification字段直接在顶层）
    if not raw_details:
        # 如果没有 details，尝试读取 items 格式并转换
        items = data.get('items', [])
        raw_details = []
        for item in items:
            detail = {
                'input': item.get('problem', item.get('input', '')),
                'status': item.get('status', 'pending'),
                'classification': item.get('classification'),
                'raw_data': item.get('raw_data', {})
            }
            if not detail.get('classification') and detail['status'] == 'pending':
                detail['output'] = '待分类'
            raw_details.append(detail)

    # 处理扁平格式：如果details中的项没有嵌套的classification，但有app/module等字段
    details = []
    for i, item in enumerate(raw_details):
        # 补充raw_data（如果有prepared_data）
        if prepared_data and prepared_data.get('items'):
            prepared_items = prepared_data.get('items', [])
            if i < len(prepared_items):
                item['raw_data'] = prepared_items[i].get('raw_data', {})

        if 'classification' not in item and 'app' in item:
            # 扁平格式，转换为嵌套格式
            classification = {
                'app': item.get('app', ''),
                'module': item.get('module', ''),
                'page': item.get('page', ''),
                'issue_type': item.get('issue_type', ''),
                'issue_detail': item.get('issue_detail', '')
            }
            detail = {
                'input': item.get('input', item.get('problem', '')),
                'status': item.get('status', 'success'),
                'classification': classification,
                'raw_data': item.get('raw_data', {})
            }
            details.append(detail)
        else:
            details.append(item)

    # 统计数据 - 如果 summary 不完整，重新计算
    total = summary.get('total', len(details))
    if not summary.get('classified'):
        # 重新计算统计
        classified = sum(1 for d in details if d.get('status') == 'success')
        no_description = sum(1 for d in details if d.get('status') == 'no_description')
        unrecognized = sum(1 for d in details if d.get('status') == 'unrecognized')
        summary = {
            'total': total,
            'classified': classified,
            'no_description': no_description,
            'unrecognized_app': unrecognized
        }
    else:
        classified = summary.get('classified', 0)
        no_description = summary.get('no_description', 0)
        unrecognized = summary.get('unrecognized_app', 0)

    # Excel来源文件名 - 优先从output_dir查找实际Excel文件
    excel_source = data.get('excel_source', '')

    # 尝试从prepared.json获取原始Excel路径
    if prepared_data:
        excel_source = prepared_data.get('excel_source', excel_source)

    # 尝试从output_dir直接查找Excel文件
    json_dir = os.path.dirname(os.path.abspath(json_path))
    excel_filename = ''
    for f in os.listdir(json_dir):
        if f.endswith('.xlsx') or f.endswith('.xls'):
            excel_filename = f
            break

    # 如果没找到，使用excel_source的basename
    if not excel_filename and excel_source:
        excel_filename = os.path.basename(excel_source)

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

    # 基础样式
    parts.append('* { margin: 0; padding: 0; box-sizing: border-box; overflow-anchor: none; }')  # 全局禁用滚动锚点
    parts.append('body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #1e293b; line-height: 1.5; }')

    # 容器
    parts.append('.container { max-width: 1200px; margin: 0 auto; padding: 24px; }')

    # 顶部标题区
    parts.append('.header { background: white; border-radius: 12px; padding: 24px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }')
    parts.append('.header-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }')
    parts.append('.header h1 { font-size: 20px; font-weight: 600; color: #0f172a; }')
    parts.append('.header-right { display: flex; align-items: center; gap: 16px; }')
    parts.append('.header .time { font-size: 13px; color: #64748b; }')
    # Excel文件链接样式
    parts.append('.excel-link { font-size: 13px; color: white; text-decoration: none; padding: 6px 12px; background: #3b82f6; border-radius: 6px; display: inline-flex; align-items: center; gap: 6px; transition: background 0.2s; }')
    parts.append('.excel-link:hover { background: #2563eb; }')
    parts.append('.excel-link::before { content: "⬇"; font-size: 14px; }')

    # 统计卡片（横向排列）
    parts.append('.stats-row { display: flex; gap: 12px; }')
    parts.append('.stat-card { flex: 1; background: #f1f5f9; border-radius: 8px; padding: 16px; text-align: center; }')
    parts.append('.stat-card .num { font-size: 28px; font-weight: 700; color: #0f172a; }')
    parts.append('.stat-card .label { font-size: 12px; color: #64748b; margin-top: 4px; }')
    parts.append('.stat-card.success .num { color: #16a34a; }')
    parts.append('.stat-card.warning .num { color: #ca8a04; }')
    parts.append('.stat-card.error .num { color: #dc2626; }')

    # 过滤工具栏
    parts.append('.toolbar { background: white; border-radius: 12px; padding: 16px 24px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }')

    # 下拉选择器
    parts.append('.filter-select { display: flex; align-items: center; gap: 8px; }')
    parts.append('.filter-select label { font-size: 13px; color: #64748b; font-weight: 500; }')
    parts.append('.filter-select select { padding: 8px 12px; border-radius: 6px; border: 1px solid #e2e8f0; background: white; font-size: 13px; color: #1e293b; cursor: pointer; min-width: 140px; }')
    parts.append('.filter-select select:focus { outline: none; border-color: #3b82f6; }')
    parts.append('.filter-select select:disabled { background: #f1f5f9; color: #94a3b8; cursor: not-allowed; }')

    # 搜索框
    parts.append('.search-box { display: flex; align-items: center; gap: 8px; margin-left: auto; }')
    parts.append('.search-box input { padding: 8px 12px; border-radius: 6px; border: 1px solid #e2e8f0; font-size: 13px; width: 200px; }')
    parts.append('.search-box input:focus { outline: none; border-color: #3b82f6; }')

    # 面包屑路径
    # 筛选路径样式（在标题后面显示）
    parts.append('.filter-path { font-size: 14px; color: #64748b; margin-left: 8px; }')
    parts.append('.filter-path .item { color: #3b82f6; cursor: pointer; }')
    parts.append('.filter-path .item:hover { text-decoration: underline; }')
    parts.append('.filter-path .sep { color: #94a3b8; margin: 0 4px; }')

    # 图表区（可折叠）
    parts.append('.charts-section { background: white; border-radius: 12px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }')
    parts.append('.section-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-bottom: 1px solid #e2e8f0; }')
    parts.append('.section-header h2 { font-size: 15px; font-weight: 600; color: #0f172a; }')
    parts.append('.section-header .toggle { font-size: 13px; color: #3b82f6; cursor: pointer; }')
    parts.append('.charts-content { padding: 24px; display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; }')
    parts.append('.charts-content.collapsed { display: none; }')
    # 图表盒子样式（合并到下一行）
    parts.append('.chart-box h3 { font-size: 13px; font-weight: 500; color: #475569; margin-bottom: 12px; }')
    parts.append('.chart-wrap { height: 280px; position: relative; }')

    # 数据表格
    parts.append('.table-section { background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow-anchor: none; }')  # 禁用滚动锚点
    parts.append('.table-header { padding: 16px 24px; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; }')
    parts.append('.table-header h2 { font-size: 15px; font-weight: 600; color: #0f172a; }')
    parts.append('.table-header .count { font-size: 13px; color: #64748b; }')
    parts.append('.table-container { overflow-x: auto; overflow-anchor: none; }')  # 移除固定高度，让table-section控制
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

    # 分类路径（表格内）
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

    # 问题描述可点击样式（单行显示，超出省略号，悬停显示完整）
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
    parts.append(f'<div class="stat-card success"><div class="num">{classified}</div><div class="label">已分类</div></div>')
    parts.append(f'<div class="stat-card warning"><div class="num">{no_description}</div><div class="label">无描述</div></div>')
    parts.append(f'<div class="stat-card error"><div class="num">{unrecognized}</div><div class="label">未识别</div></div>')
    parts.append('</div>')
    parts.append('</div>')

    # 过滤工具栏
    parts.append('<div class="toolbar">')
    parts.append('<div class="filter-select"><label>应用</label><select id="filter-app" onchange="onFilterChange(\'app\')"><option value="">全部</option></select></div>')
    parts.append('<div class="filter-select"><label>模块</label><select id="filter-module" onchange="onFilterChange(\'module\')" disabled><option value="">全部</option></select></div>')
    parts.append('<div class="filter-select"><label>页面</label><select id="filter-page" onchange="onFilterChange(\'page\')" disabled><option value="">全部</option></select></div>')
    parts.append('<div class="filter-select"><label>问题类型</label><select id="filter-type" onchange="onFilterChange(\'type\')" disabled><option value="">全部</option></select></div>')
    parts.append('<div class="search-box"><input type="text" id="search-input" placeholder="搜索问题描述..." onkeyup="onSearch()"></input></div>')
    parts.append('</div>')

    # 图表区
    parts.append('<div class="charts-section">')
    parts.append('<div class="section-header">')
    parts.append('<h2>数据分布 <span id="filter-path" class="filter-path"></span></h2>')
    parts.append('<span class="toggle" onclick="toggleCharts()">收起</span>')
    parts.append('</div>')
    parts.append('<div class="charts-content" id="charts-content">')
    parts.append('<div class="chart-box"><h3>应用分布</h3><div class="chart-wrap"><canvas id="appChart"></canvas></div></div>')
    parts.append('<div class="chart-box"><h3 id="pie-title">模块分布</h3><div class="chart-wrap"><canvas id="pieChart"></canvas></div></div>')
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
    parts.append('<th>分类路径（点击可筛选）</th>')
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
    parts.append('let filters = { app: "", module: "", type: "", page: "" };')
    parts.append('let searchText = "";')
    parts.append('let charts = {};')
    parts.append('let chartsVisible = true;')
    parts.append('let currentPage = 1;')
    parts.append('const pageSize = 50;')

    # 获取所有可用选项（用于初始化）
    parts.append('function getAllOptions() {')
    parts.append('const apps = {}, modules = {}, pages = {}, types = {};')
    parts.append('allData.forEach(item => {')
    parts.append('if (item.status === "success") {')
    parts.append('const cls = item.classification;')
    parts.append('apps[cls.app] = true;')
    parts.append('modules[cls.module] = true;')
    parts.append('pages[cls.page] = true;')
    parts.append('types[cls.issue_type] = true;')
    parts.append('}});')
    parts.append('return { apps: Object.keys(apps).sort(), modules: Object.keys(modules).sort(), pages: Object.keys(pages).sort(), types: Object.keys(types).sort() };')
    parts.append('}')

    # 获取当前可用的模块选项（根据已选应用）
    parts.append('function getAvailableModules(app) {')
    parts.append('const modules = {};')
    parts.append('allData.forEach(item => {')
    parts.append('if (item.status === "success") {')
    parts.append('const cls = item.classification;')
    parts.append('if (!app || cls.app === app) {')
    parts.append('modules[cls.module] = true;')
    parts.append('}}});')
    parts.append('return Object.keys(modules).sort();')
    parts.append('}')

    # 获取当前可用的页面选项（根据已选应用和模块）
    parts.append('function getAvailablePages(app, module) {')
    parts.append('const pages = {};')
    parts.append('allData.forEach(item => {')
    parts.append('if (item.status === "success") {')
    parts.append('const cls = item.classification;')
    parts.append('if (!app || cls.app === app) {')
    parts.append('if (!module || cls.module === module) {')
    parts.append('pages[cls.page] = true;')
    parts.append('}}}});')
    parts.append('return Object.keys(pages).sort();')
    parts.append('}')

    # 获取当前可用的问题类型选项（根据已选应用、模块和页面）
    parts.append('function getAvailableTypes(app, module, page) {')
    parts.append('const types = {};')
    parts.append('allData.forEach(item => {')
    parts.append('if (item.status === "success") {')
    parts.append('const cls = item.classification;')
    parts.append('if (!app || cls.app === app) {')
    parts.append('if (!module || cls.module === module) {')
    parts.append('if (!page || cls.page === page) {')
    parts.append('types[cls.issue_type] = true;')
    parts.append('}}}}});')
    parts.append('return Object.keys(types).sort();')
    parts.append('}')

    # 初始化下拉选项
    parts.append('function initSelectOptions() {')
    parts.append('const opts = getAllOptions();')
    parts.append('fillSelect("filter-app", opts.apps, "全部");')
    # 模块和问题类型初始禁用
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
    parts.append('if (item.status !== "success") return false;')
    parts.append('const cls = item.classification;')
    parts.append('if (filters.app && cls.app !== filters.app) return false;')
    parts.append('if (filters.module && cls.module !== filters.module) return false;')
    parts.append('if (filters.type && cls.issue_type !== filters.type) return false;')
    parts.append('if (filters.page && cls.page !== filters.page) return false;')
    parts.append('if (searchText) {')
    parts.append('const text = (item.input || "").toLowerCase();')
    parts.append('if (!text.includes(searchText.toLowerCase())) return false;')
    parts.append('}')
    parts.append('return true;')
    parts.append('});')
    parts.append('}')

    # 计算统计
    parts.append('function calcStats(data) {')
    parts.append('const stats = { app: {}, module: {}, page: {}, type: {} };')
    parts.append('data.forEach(item => {')
    parts.append('if (item.status !== "success") return;')
    parts.append('const cls = item.classification;')
    parts.append('stats.app[cls.app] = (stats.app[cls.app] || 0) + 1;')
    parts.append('stats.module[cls.module] = (stats.module[cls.module] || 0) + 1;')
    parts.append('stats.page[cls.page] = (stats.page[cls.page] || 0) + 1;')
    parts.append('stats.type[cls.issue_type] = (stats.type[cls.issue_type] || 0) + 1;')
    parts.append('});')
    parts.append('return stats;')
    parts.append('}')

    # 过滤变更（级联更新选项，根据是否有值启用/禁用）
    parts.append('function onFilterChange(source) {')
    parts.append('const appSel = document.getElementById("filter-app");')
    parts.append('const moduleSel = document.getElementById("filter-module");')
    parts.append('const pageSel = document.getElementById("filter-page");')
    parts.append('const typeSel = document.getElementById("filter-type");')

    # 如果是应用变更
    parts.append('if (source === "app") {')
    parts.append('filters.app = appSel.value;')
    parts.append('if (filters.app) {')
    parts.append('const availableModules = getAvailableModules(filters.app);')
    parts.append('fillSelect("filter-module", availableModules, "全部");')
    parts.append('moduleSel.disabled = false;')
    parts.append('} else {')
    parts.append('moduleSel.disabled = true;')
    parts.append('moduleSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('pageSel.disabled = true;')
    parts.append('pageSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('typeSel.disabled = true;')
    parts.append('typeSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('}')
    parts.append('filters.module = "";')
    parts.append('filters.page = "";')
    parts.append('filters.type = "";')
    parts.append('}')

    # 如果是模块变更
    parts.append('if (source === "module") {')
    parts.append('filters.module = moduleSel.value;')
    parts.append('if (filters.module) {')
    parts.append('const availablePages = getAvailablePages(filters.app, filters.module);')
    parts.append('fillSelect("filter-page", availablePages, "全部");')
    parts.append('pageSel.disabled = false;')
    parts.append('} else {')
    parts.append('pageSel.disabled = true;')
    parts.append('pageSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('typeSel.disabled = true;')
    parts.append('typeSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('}')
    parts.append('filters.page = "";')
    parts.append('filters.type = "";')
    parts.append('}')

    # 如果是页面变更
    parts.append('if (source === "page") {')
    parts.append('filters.page = pageSel.value;')
    parts.append('if (filters.page) {')
    parts.append('const availableTypes = getAvailableTypes(filters.app, filters.module, filters.page);')
    parts.append('fillSelect("filter-type", availableTypes, "全部");')
    parts.append('typeSel.disabled = false;')
    parts.append('} else {')
    parts.append('typeSel.disabled = true;')
    parts.append('typeSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('}')
    parts.append('filters.type = "";')
    parts.append('}')

    # 如果是问题类型变更
    parts.append('if (source === "type") {')
    parts.append('filters.type = typeSel.value;')
    parts.append('}')

    parts.append('currentPage = 1;')  # 筛选变化时重置到第一页
    parts.append('updateAll();')
    parts.append('}')

    # 搜索
    parts.append('function onSearch() {')
    parts.append('searchText = document.getElementById("search-input").value;')
    parts.append('currentPage = 1;')  # 搜索时重置到第一页
    parts.append('updateAll();')
    parts.append('}')

    # 清除筛选
    parts.append('function clearFilters() {')
    parts.append('filters = { app: "", module: "", page: "", type: "" };')
    parts.append('searchText = "";')
    parts.append('const opts = getAllOptions();')
    parts.append('fillSelect("filter-app", opts.apps, "全部");')
    parts.append('document.getElementById("filter-app").value = "";')  # 明确重置为"全部"
    # 禁用模块、页面和问题类型
    parts.append('const moduleSel = document.getElementById("filter-module");')
    parts.append('moduleSel.disabled = true;')
    parts.append('moduleSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('const pageSel = document.getElementById("filter-page");')
    parts.append('pageSel.disabled = true;')
    parts.append('pageSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('const typeSel = document.getElementById("filter-type");')
    parts.append('typeSel.disabled = true;')
    parts.append('typeSel.innerHTML = "<option value=\\"\\">全部</option>";')
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

    # 更新筛选路径（在"数据分布"标题后显示）
    parts.append('function updateBreadcrumb() {')
    parts.append('const pathEl = document.getElementById("filter-path");')
    # 全选时不显示
    parts.append('if (!filters.app && !filters.module && !filters.page && !filters.type && !searchText) {')
    parts.append('pathEl.innerHTML = "";')
    parts.append('return;')
    parts.append('}')
    # 构建路径：全部›应用›模块›页面›问题类型
    parts.append('const parts = ["全部"];')
    parts.append('if (filters.app) parts.push(filters.app);')
    parts.append('if (filters.module) parts.push(filters.module);')
    parts.append('if (filters.page) parts.push(filters.page);')
    parts.append('if (filters.type) parts.push(filters.type);')
    parts.append('if (searchText) parts.push("搜索:" + searchText);')
    # 渲染路径，每个部分可点击清除该项及下级
    parts.append('pathEl.innerHTML = parts.map((p, i) => {')
    parts.append('if (i === 0) return `<span class="item" onclick="clearFilters()">${p}</span>`;')  # "全部"点击清除所有
    parts.append('return `<span class="item" onclick="clearLevel(${i})">${p}</span>`;')
    parts.append('}).join("<span class=\'sep\'>›</span>");')
    parts.append('}')

    # 清除指定层级后面的层级（1=app, 2=module, 3=page, 4=type）
    # 点击某个层级时保留该层级，清除后面的层级，启用下一级下拉框
    parts.append('function clearLevel(level) {')
    # level 1=点击应用, 清除模块及后面，启用模块下拉框
    parts.append('if (level === 1) {')
    parts.append('filters.module = ""; filters.page = ""; filters.type = "";')
    parts.append('const availableModules = getAvailableModules(filters.app);')
    parts.append('fillSelect("filter-module", availableModules, "全部");')
    parts.append('document.getElementById("filter-module").disabled = false;')
    parts.append('document.getElementById("filter-module").value = "";')  # 重置为全部
    parts.append('document.getElementById("filter-page").disabled = true;')
    parts.append('document.getElementById("filter-page").innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('document.getElementById("filter-type").disabled = true;')
    parts.append('document.getElementById("filter-type").innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('} else if (level === 2) {')
    # level 2=点击模块, 清除页面及后面，启用页面下拉框
    parts.append('filters.page = ""; filters.type = "";')
    parts.append('const availablePages = getAvailablePages(filters.app, filters.module);')
    parts.append('fillSelect("filter-page", availablePages, "全部");')
    parts.append('document.getElementById("filter-page").disabled = false;')
    parts.append('document.getElementById("filter-page").value = "";')  # 重置为全部
    parts.append('document.getElementById("filter-type").disabled = true;')
    parts.append('document.getElementById("filter-type").innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('} else if (level === 3) {')
    # level 3=点击页面, 清除问题类型，启用问题类型下拉框
    parts.append('filters.type = "";')
    parts.append('const availableTypes = getAvailableTypes(filters.app, filters.module, filters.page);')
    parts.append('fillSelect("filter-type", availableTypes, "全部");')
    parts.append('document.getElementById("filter-type").disabled = false;')
    parts.append('document.getElementById("filter-type").value = "";')  # 重置为全部
    parts.append('}')
    parts.append('searchText = ""; document.getElementById("search-input").value = "";')
    parts.append('currentPage = 1;')
    parts.append('updateAll();')
    parts.append('}')

    # 更新表格（带分页）
    parts.append('function updateTable() {')
    parts.append('const tbody = document.getElementById("table-body");')
    parts.append('const empty = document.getElementById("empty-state");')
    parts.append('const countEl = document.getElementById("table-count");')
    parts.append('const paginationEl = document.getElementById("pagination");')
    parts.append('const filtered = getFilteredData();')
    parts.append('countEl.textContent = filtered.length + " 条";')
    # 计算分页
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
    # 渲染当前页数据
    parts.append('pageData.forEach((item, i) => {')
    parts.append('const cls = item.classification;')
    parts.append('const globalIndex = start + i;')  # 全局索引
    parts.append('const row = document.createElement("tr");')
    parts.append('row.dataset.index = globalIndex;')
    parts.append('row.innerHTML = `')
    parts.append('<td>${globalIndex + 1}</td>')
    parts.append('<td><span class="problem-text" title="${item.input}" onclick="showDetail(${globalIndex})">${item.input}</span></td>')
    parts.append('<td><span class="app-tag">${cls.app}</span></td>')
    parts.append('<td><span class="cls-path">')
    parts.append('<span class="item" onclick="setFilterWithPath(\'${cls.app}\',\'\',\'\',\'\',\'app\',\'${cls.app}\')">${cls.app}</span>')
    parts.append('<span class="sep">›</span>')
    parts.append('<span class="item" onclick="setFilterWithPath(\'${cls.app}\',\'${cls.module}\',\'\',\'\',\'module\',\'${cls.module}\')">${cls.module}</span>')
    parts.append('<span class="sep">›</span>')
    parts.append('<span class="item" onclick="setFilterWithPath(\'${cls.app}\',\'${cls.module}\',\'${cls.page}\',\'\',\'page\',\'${cls.page}\')">${cls.page}</span>')
    parts.append('<span class="sep">›</span>')
    parts.append('<span class="item" onclick="setFilterWithPath(\'${cls.app}\',\'${cls.module}\',\'${cls.page}\',\'${cls.issue_type}\',\'type\',\'${cls.issue_type}\')">${cls.issue_type}</span>')
    parts.append('<span class="sep">›</span>')
    parts.append('<span class="item">${cls.issue_detail}</span>')
    parts.append('</span></td>')
    parts.append('`;')
    parts.append('tbody.appendChild(row);')
    parts.append('});')
    # 渲染分页控件
    parts.append('updatePagination(filtered.length, totalPages);')
    parts.append('}')

    # 简单筛选函数（用于图表点击，不设置完整路径）
    parts.append('function setFilter(field, value) {')
    parts.append('const appSel = document.getElementById("filter-app");')
    parts.append('const moduleSel = document.getElementById("filter-module");')
    parts.append('const pageSel = document.getElementById("filter-page");')
    parts.append('const typeSel = document.getElementById("filter-type");')

    parts.append('if (field === "app") {')
    parts.append('filters.app = value;')
    parts.append('appSel.value = value;')
    parts.append('const availableModules = getAvailableModules(value);')
    parts.append('fillSelect("filter-module", availableModules, "全部");')
    parts.append('moduleSel.disabled = false;')
    parts.append('moduleSel.value = "";')
    parts.append('filters.module = "";')
    parts.append('pageSel.disabled = true;')
    parts.append('pageSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.page = "";')
    parts.append('typeSel.disabled = true;')
    parts.append('typeSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.type = "";')
    parts.append('} else if (field === "module") {')
    # 点击模块：保留上级应用，设置模块
    parts.append('filters.module = value;')
    parts.append('moduleSel.value = value;')
    parts.append('const availablePages = getAvailablePages(filters.app, value);')
    parts.append('fillSelect("filter-page", availablePages, "全部");')
    parts.append('pageSel.disabled = false;')
    parts.append('pageSel.value = "";')
    parts.append('filters.page = "";')
    parts.append('typeSel.disabled = true;')
    parts.append('typeSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.type = "";')
    parts.append('} else if (field === "page") {')
    # 点击页面：保留上级，设置页面
    parts.append('filters.page = value;')
    parts.append('pageSel.value = value;')
    parts.append('const availableTypes = getAvailableTypes(filters.app, filters.module, value);')
    parts.append('fillSelect("filter-type", availableTypes, "全部");')
    parts.append('typeSel.disabled = false;')
    parts.append('typeSel.value = "";')
    parts.append('filters.type = "";')
    parts.append('} else if (field === "type") {')
    # 点击问题类型：保留上级
    parts.append('filters.type = value;')
    parts.append('typeSel.value = value;')
    parts.append('}')
    parts.append('currentPage = 1;')
    parts.append('updateAll();')
    parts.append('}')

    # 设置筛选（点击表格路径时，按该行的完整路径设置）
    # 直接传入完整路径值，避免依赖event对象
    # 根据 targetField 决定哪些下拉框启用/禁用
    parts.append('function setFilterWithPath(app, module, page, type, targetField, targetValue) {')
    parts.append('const appSel = document.getElementById("filter-app");')
    parts.append('const moduleSel = document.getElementById("filter-module");')
    parts.append('const pageSel = document.getElementById("filter-page");')
    parts.append('const typeSel = document.getElementById("filter-type");')

    # 点击应用：只启用模块
    parts.append('if (targetField === "app") {')
    parts.append('filters.app = targetValue;')
    parts.append('appSel.value = targetValue;')
    parts.append('const availableModules = getAvailableModules(targetValue);')
    parts.append('fillSelect("filter-module", availableModules, "全部");')
    parts.append('moduleSel.disabled = false;')
    parts.append('moduleSel.value = "";')
    parts.append('filters.module = "";')
    parts.append('pageSel.disabled = true;')
    parts.append('pageSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.page = "";')
    parts.append('typeSel.disabled = true;')
    parts.append('typeSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.type = "";')

    # 点击模块：启用模块和页面，禁用类型
    parts.append('} else if (targetField === "module") {')
    parts.append('filters.app = app;')
    parts.append('appSel.value = app;')
    parts.append('const availableModules = getAvailableModules(app);')
    parts.append('fillSelect("filter-module", availableModules, "全部");')
    parts.append('moduleSel.disabled = false;')
    parts.append('filters.module = targetValue;')
    parts.append('moduleSel.value = targetValue;')
    parts.append('const availablePages = getAvailablePages(app, targetValue);')
    parts.append('fillSelect("filter-page", availablePages, "全部");')
    parts.append('pageSel.disabled = false;')
    parts.append('pageSel.value = "";')
    parts.append('filters.page = "";')
    parts.append('typeSel.disabled = true;')
    parts.append('typeSel.innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.type = "";')

    # 点击页面：启用模块、页面和类型
    parts.append('} else if (targetField === "page") {')
    parts.append('filters.app = app;')
    parts.append('appSel.value = app;')
    parts.append('const availableModules = getAvailableModules(app);')
    parts.append('fillSelect("filter-module", availableModules, "全部");')
    parts.append('moduleSel.disabled = false;')
    parts.append('filters.module = module;')
    parts.append('moduleSel.value = module;')
    parts.append('const availablePages = getAvailablePages(app, module);')
    parts.append('fillSelect("filter-page", availablePages, "全部");')
    parts.append('pageSel.disabled = false;')
    parts.append('filters.page = targetValue;')
    parts.append('pageSel.value = targetValue;')
    parts.append('const availableTypes = getAvailableTypes(app, module, targetValue);')
    parts.append('fillSelect("filter-type", availableTypes, "全部");')
    parts.append('typeSel.disabled = false;')
    parts.append('typeSel.value = "";')
    parts.append('filters.type = "";')

    # 点击问题类型：全部启用，设置完整路径
    parts.append('} else if (targetField === "type") {')
    parts.append('filters.app = app;')
    parts.append('appSel.value = app;')
    parts.append('const availableModules = getAvailableModules(app);')
    parts.append('fillSelect("filter-module", availableModules, "全部");')
    parts.append('moduleSel.disabled = false;')
    parts.append('filters.module = module;')
    parts.append('moduleSel.value = module;')
    parts.append('const availablePages = getAvailablePages(app, module);')
    parts.append('fillSelect("filter-page", availablePages, "全部");')
    parts.append('pageSel.disabled = false;')
    parts.append('filters.page = page;')
    parts.append('pageSel.value = page;')
    parts.append('const availableTypes = getAvailableTypes(app, module, page);')
    parts.append('fillSelect("filter-type", availableTypes, "全部");')
    parts.append('typeSel.disabled = false;')
    parts.append('filters.type = targetValue;')
    parts.append('typeSel.value = targetValue;')
    parts.append('}')

    parts.append('currentPage = 1;')
    parts.append('updateAll();')
    parts.append('}')

    # 更新图表
    parts.append('function updateCharts() {')
    parts.append('const filtered = getFilteredData();')
    parts.append('const stats = calcStats(filtered);')
    # 更新应用柱状图
    parts.append('charts.app.data.labels = Object.keys(stats.app);')
    parts.append('charts.app.data.datasets[0].data = Object.values(stats.app);')
    parts.append('charts.app.update();')
    # 更新动态饼图（根据筛选层级显示不同内容）
    parts.append('const pieTitle = document.getElementById("pie-title");')
    parts.append('if (filters.page) {')
    # 已选页面，显示问题类型分布
    parts.append('pieTitle.textContent = "问题类型分布";')
    parts.append('charts.pie.data.labels = Object.keys(stats.type);')
    parts.append('charts.pie.data.datasets[0].data = Object.values(stats.type);')
    parts.append('} else if (filters.module) {')
    # 已选模块，显示页面分布
    parts.append('pieTitle.textContent = "页面分布";')
    parts.append('charts.pie.data.labels = Object.keys(stats.page);')
    parts.append('charts.pie.data.datasets[0].data = Object.values(stats.page);')
    parts.append('} else if (filters.app) {')
    # 已选应用，显示模块分布
    parts.append('pieTitle.textContent = "模块分布";')
    parts.append('charts.pie.data.labels = Object.keys(stats.module);')
    parts.append('charts.pie.data.datasets[0].data = Object.values(stats.module);')
    parts.append('} else {')
    # 未选应用，显示应用分布
    parts.append('pieTitle.textContent = "应用分布";')
    parts.append('charts.pie.data.labels = Object.keys(stats.app);')
    parts.append('charts.pie.data.datasets[0].data = Object.values(stats.app);')
    parts.append('}')
    parts.append('charts.pie.update();')
    parts.append('}')

    # 初始化图表
    parts.append('function initCharts() {')
    parts.append('const stats = calcStats(allData);')
    parts.append('charts.app = new Chart(document.getElementById("appChart"), {')
    parts.append('type: "bar",')
    parts.append('data: { labels: Object.keys(stats.app), datasets: [{ data: Object.values(stats.app), backgroundColor: ["#3b82f6","#8b5cf6","#ec4899","#f43f5e","#06b6d4","#14b8a6"] }] },')
    parts.append('options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, onClick: (e,els) => { if(els.length>0) setFilter("app", charts.app.data.labels[els[0].index]); } }')
    parts.append('});')
    # 动态饼图：根据筛选层级显示应用/模块/页面/问题类型
    parts.append('charts.pie = new Chart(document.getElementById("pieChart"), {')
    parts.append('type: "doughnut",')
    parts.append('data: { labels: [], datasets: [{ data: [], backgroundColor: ["#3b82f6","#8b5cf6","#ec4899","#f43f5e","#06b6d4","#14b8a6","#16a34a","#ca8a04"] }] },')
    parts.append('options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: function(ctx) { const total = ctx.dataset.data.reduce((a,b)=>a+b,0); const pct = Math.round(ctx.raw/total*100); return ctx.label + ": " + ctx.raw + " 条 (" + pct + "%)"; } } } }, onClick: (e,els) => { if(els.length>0) onPieClick(charts.pie.data.labels[els[0].index]); } }')
    parts.append('});')
    parts.append('}')

    # 饼图点击处理（点击具体分类保留上级筛选）
    parts.append('function onPieClick(value) {')
    parts.append('if (filters.page) {')
    # 已选页面，点击问题类型
    parts.append('setFilter("type", value);')
    parts.append('} else if (filters.module) {')
    # 已选模块，点击页面
    parts.append('setFilter("page", value);')
    parts.append('} else if (filters.app) {')
    # 已选应用，点击模块
    parts.append('setFilter("module", value);')
    parts.append('} else {')
    # 未选应用，点击应用
    parts.append('setFilter("app", value);')
    parts.append('}')
    parts.append('}')

    # 清除单个筛选层级（返回上一级）
    parts.append('function clearFilter(level) {')
    parts.append('const sel = document.getElementById("filter-" + level);')
    parts.append('filters[level] = "";')
    parts.append('if (sel) sel.value = "";')
    # 禁用下级选择
    parts.append('if (level === "app") {')
    parts.append('document.getElementById("filter-module").disabled = true;')
    parts.append('document.getElementById("filter-module").innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.module = "";')
    parts.append('document.getElementById("filter-page").disabled = true;')
    parts.append('document.getElementById("filter-page").innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.page = "";')
    parts.append('document.getElementById("filter-type").disabled = true;')
    parts.append('document.getElementById("filter-type").innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.type = "";')
    parts.append('} else if (level === "module") {')
    parts.append('document.getElementById("filter-page").disabled = true;')
    parts.append('document.getElementById("filter-page").innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.page = "";')
    parts.append('document.getElementById("filter-type").disabled = true;')
    parts.append('document.getElementById("filter-type").innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.type = "";')
    parts.append('} else if (level === "page") {')
    parts.append('document.getElementById("filter-type").disabled = true;')
    parts.append('document.getElementById("filter-type").innerHTML = "<option value=\\"\\">全部</option>";')
    parts.append('filters.type = "";')
    parts.append('}')
    parts.append('updateAll();')
    parts.append('}')

    # 全量更新
    parts.append('function updateAll() {')
    parts.append('updateCharts();')
    parts.append('updateBreadcrumb();')
    parts.append('updateTable();')
    parts.append('}')

    # 更新分页控件
    parts.append('function updatePagination(total, totalPages) {')
    parts.append('const paginationEl = document.getElementById("pagination");')
    parts.append('if (totalPages <= 1) {')
    parts.append('paginationEl.innerHTML = "";')
    parts.append('return;')
    parts.append('}')
    parts.append('let html = "";')
    parts.append('html += `<button onclick="goToPage(1)" ${currentPage === 1 ? "disabled" : ""}>首页</button>`;')
    parts.append('html += `<button onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? "disabled" : ""}>上一页</button>`;')
    # 显示页码（最多显示5个）
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

    # 显示详情弹窗（显示Excel原始数据，用表格形式）
    parts.append('function showDetail(index) {')
    parts.append('const filtered = getFilteredData();')
    parts.append('const item = filtered[index];')
    parts.append('const raw = item.raw_data || {};')
    parts.append('const body = document.getElementById("modal-body");')
    # 用表格显示原始数据
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
        # 默认：在JSON文件所在目录输出
        json_dir = os.path.dirname(os.path.abspath(json_path))
        json_basename = os.path.basename(json_path).replace('.json', '')
        output_path = os.path.join(json_dir, f"{json_basename}_report.html")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return output_path


def main():
    if len(sys.argv) < 2:
        print("用法: python generate_report.py <分析结果JSON路径> [输出HTML路径]")
        print("      未指定输出路径时，结果将保存在JSON文件所在目录")
        sys.exit(1)

    json_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    result_path = generate_report(json_path, output_path)
    print(f"报告已生成: {result_path}")


if __name__ == "__main__":
    main()