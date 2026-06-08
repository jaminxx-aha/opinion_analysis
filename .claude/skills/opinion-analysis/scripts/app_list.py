#!/usr/bin/env python3
"""
舆情分析辅助脚本 - 查看当前支持的应用列表

用法: python app_list.py
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
APPS_DIR = os.path.join(SKILL_DIR, "references", "apps")


def get_supported_apps():
    """获取当前支持的应用列表（从 references/apps/ 目录扫描）"""
    return sorted(d for d in os.listdir(APPS_DIR) if os.path.isdir(os.path.join(APPS_DIR, d)))


def get_app_dir(app_name):
    """获取应用知识库目录路径，返回None表示不支持"""
    app_dir = os.path.join(APPS_DIR, app_name)
    if os.path.isdir(app_dir):
        return app_dir
    return None


if __name__ == "__main__":
    for app in get_supported_apps():
        print(app)