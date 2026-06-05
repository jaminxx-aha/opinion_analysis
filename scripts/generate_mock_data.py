#!/usr/bin/env python3
"""
生成舆情分析mock数据

创建10个Excel文件，每个代表一周的舆情数据，约100条记录。
各周数据分布不同，用于测试仪表盘和对比功能。

用法: python scripts/generate_mock_data.py [--output-dir DIR]
"""

import random
import argparse
import os
from datetime import date, timedelta

try:
    import pandas as pd
except ImportError:
    print("需要 pandas 和 openpyxl，请运行: pip install pandas openpyxl")
    raise

# ─── 值域定义 ───

CHANNELS = ['应用内反馈', 'App Store评论', '微博投诉', '应用市场', '黑猫投诉', '社交媒体', '官方客服']

DEVICES = [
    'iPhone 14 Pro', 'iPhone 15 Pro', 'iPhone 13', 'iPhone 14', 'iPhone 15',
    '华为P50', '华为Mate60',
    '小米12', '小米13', 'Redmi K60',
    'OPPO Find X6',
    'vivo X90', 'vivo X100',
    '一加11', '一加12',
    '三星S23',
    '荣耀Magic4', '荣耀Magic5',
]

OS_VERSIONS = [
    'Android 12', 'Android 13', 'Android 14',
    'iOS 16.5', 'iOS 17.1',
    '鸿蒙OS 3.0', '鸿蒙OS 4.0', '鸿蒙OS 4.2',
]

ISSUE_STATUSES = ['未解决', '待处理', '已解决', '已关闭']

PRIORITIES = ['高', '中', '低']

HANDLERS = ['未分配', '客服1号', '客服2号', '客服3号', '客服4号', '客服5号', '客服6号', '客服7号', '客服8号']

# ─── 问题描述模板 ───
# 每个分类对应多条自然语言描述

PROBLEM_TEMPLATES = {
    '卡顿': [
        '抖音刷视频卡顿严重',
        '滑动的时候很卡',
        '视频播放经常卡住',
        '抖音卡顿受不了了',
        '直播看一会儿就卡',
        '上下滑视频经常卡顿',
        '抖音页面转场卡顿',
        '加载视频的时候卡',
        '剪辑视频特别卡',
        '点击评论区域卡顿',
    ],
    '响应慢/延迟': [
        '打开抖音很慢',
        '消息发送有延迟',
        '加载时间太长了',
        '抖音响应很慢',
        '直播间延迟好几秒',
        '上传视频特别慢',
        '点击关注反应慢',
        '抖音搜索结果加载慢',
        '发布评论延迟',
        '打开消息列表很慢',
    ],
    '闪退/崩溃': [
        '看视频突然闪退',
        '抖音老是崩溃',
        '页面切换闪退',
        '抖音刚启动就闪退',
        '发评论时闪退',
        '看直播闪退了',
        '抖音崩溃报告',
        '打开私信就闪退',
        '拍摄时抖音崩溃',
        '抖音后台切换回来闪退',
    ],
    '启动异常': [
        '打开抖音要很久',
        '启动失败一直转圈',
        '启动卡在首页不动',
        '抖音启动显示异常',
        '冷启动特别慢',
        '抖音启动黑屏',
        '启动后页面加载不出来',
        '抖音启动白屏',
        '重启手机后抖音启动慢',
        '抖音启动卡在广告页',
    ],
    '发热': [
        '抖音刷短视频发热',
        '手机发烫厉害',
        '直播手机很热',
        '看一会儿抖音就发热',
        '抖音后台发热严重',
        '拍摄视频手机发烫',
        '抖音耗电很快手机热',
        '连续刷抖音发热',
        '抖音发热卡顿一起出现',
        '抖音发热到不敢拿',
    ],
    '内存异常': [
        '抖音占用内存太大',
        '内存不足提示',
        '手机内存被抖音吃完了',
        '抖音内存泄漏严重',
        '抖音内存占用高',
        '抖音导致手机内存不足',
        '抖音内存异常',
        '长时间用抖音内存暴涨',
        '抖音后台占用内存多',
        '抖音内存不足闪退',
    ],
    '渲染异常': [
        '视频画面花屏',
        '直播画质异常',
        '界面显示错乱',
        '抖音图片渲染异常',
        '直播画面撕裂',
        '特效渲染卡顿花屏',
        '抖音UI渲染问题',
        '视频画面有条纹',
        '抖音滤镜渲染异常',
        '弹幕渲染重叠',
    ],
    '网络异常': [
        '抖音连不上网',
        '视频加载网络错误',
        '直播间网络断开',
        '抖音网络异常',
        '上传视频网络失败',
        '抖音商城加载不出来',
        '点赞提示网络错误',
        '抖音Wi-Fi下也断网',
        '评论发送网络异常',
        '抖音4G网络频繁断开',
    ],
    '未知问题': [
        '抖音钱包提现失败',
        '直播间被封了没有说明',
        '账号被盗了',
        '抖音视频被删了没有通知',
        '抖音充值失败',
        '抖音商城退款慢',
        '抖音广告太多了',
        '抖音推送内容不喜欢',
        '抖音VIP功能用不了',
        '私信被限制发送',
        '抖音账号异常登录',
        '投诉客服没人回复',
    ],
}

# ─── 每周分布权重（10周差异化） ───
# 键名对应 PROBLEM_TEMPLATES 的键，值是该分类的权重百分比

WEEKLY_PROFILES = [
    # 第1周: 卡顿为主
    {'卡顿': 28, '响应慢/延迟': 10, '闪退/崩溃': 8, '启动异常': 6, '发热': 8, '内存异常': 5, '渲染异常': 10, '网络异常': 10, '未知问题': 13},
    # 第2周: 发热突出
    {'卡顿': 12, '响应慢/延迟': 8, '闪退/崩溃': 10, '启动异常': 8, '发热': 25, '内存异常': 6, '渲染异常': 8, '网络异常': 12, '未知问题': 19},
    # 第3周: 网络问题多
    {'卡顿': 10, '响应慢/延迟': 12, '闪退/崩溃': 8, '启动异常': 5, '发热': 10, '内存异常': 5, '渲染异常': 8, '网络异常': 30, '未知问题': 12},
    # 第4周: 闪退严重
    {'卡顿': 10, '响应慢/延迟': 8, '闪退/崩溃': 25, '启动异常': 10, '发热': 8, '内存异常': 8, '渲染异常': 10, '网络异常': 8, '未知问题': 16},
    # 第5周: 启动异常集中
    {'卡顿': 8, '响应慢/延迟': 10, '闪退/崩溃': 8, '启动异常': 22, '发热': 12, '内存异常': 8, '渲染异常': 10, '网络异常': 8, '未知问题': 14},
    # 第6周: 响应慢为主
    {'卡顿': 10, '响应慢/延迟': 28, '闪退/崩溃': 8, '启动异常': 5, '发热': 10, '内存异常': 6, '渲染异常': 10, '网络异常': 12, '未知问题': 15},
    # 第7周: 渲染异常多
    {'卡顿': 10, '响应慢/延迟': 8, '闪退/崩溃': 10, '启动异常': 6, '发热': 8, '内存异常': 5, '渲染异常': 25, '网络异常': 12, '未知问题': 16},
    # 第8周: 内存问题突出
    {'卡顿': 12, '响应慢/延迟': 8, '闪退/崩溃': 8, '启动异常': 5, '发热': 10, '内存异常': 22, '渲染异常': 10, '网络异常': 8, '未知问题': 17},
    # 第9周: 均衡分布
    {'卡顿': 14, '响应慢/延迟': 14, '闪退/崩溃': 12, '启动异常': 8, '发热': 12, '内存异常': 6, '渲染异常': 10, '网络异常': 10, '未知问题': 14},
    # 第10周: 卡顿+发热双高
    {'卡顿': 22, '响应慢/延迟': 8, '闪退/崩溃': 8, '启动异常': 5, '发热': 20, '内存异常': 5, '渲染异常': 8, '网络异常': 10, '未知问题': 12},
]


def generate_week_data(week_start: date, profile: dict, count: int) -> pd.DataFrame:
    """根据周起始日期、分布权重和总条数生成一周数据"""

    # 按权重分配每类的条数
    categories = list(profile.keys())
    weights = list(profile.values())
    total_weight = sum(weights)

    # 计算每类条数，确保总数等于 count
    counts = {}
    remaining = count
    for i, (cat, w) in enumerate(zip(categories, weights)):
        if i == len(categories) - 1:
            counts[cat] = remaining
        else:
            n = round(w / total_weight * count)
            counts[cat] = n
            remaining -= n

    rows = []
    row_idx = 1

    for cat, n in counts.items():
        templates = PROBLEM_TEMPLATES[cat]
        for _ in range(n):
            # 日期: 在当周内随机
            day_offset = random.randint(0, 6)
            row_date = week_start + timedelta(days=day_offset)

            # 时间: 随机 HH:MM
            hour = random.randint(0, 23)
            minute = random.randint(0, 59)
            row_time = f"{hour:02d}:{minute:02d}"

            # 问题描述: 随机选择模板
            problem = random.choice(templates)

            # 随机选择各字段值
            rows.append({
                '序号': row_idx,
                '应用名': '抖音',
                '日期': row_date.strftime('%Y-%m-%d'),
                '时间': row_time,
                '问题描述': problem,
                '用户ID': f"U{random.randint(100000, 999999)}",
                '渠道来源': random.choice(CHANNELS),
                '设备类型': random.choice(DEVICES),
                '系统版本': random.choice(OS_VERSIONS),
                '问题状态': random.choice(ISSUE_STATUSES),
                '优先级': random.choice(PRIORITIES),
                '处理人员': random.choice(HANDLERS),
            })
            row_idx += 1

    df = pd.DataFrame(rows)
    return df


def main():
    parser = argparse.ArgumentParser(description='生成舆情分析mock数据')
    parser.add_argument('--output-dir', default='test', help='输出目录（默认 test/）')
    parser.add_argument('--start-date', default='2025-05-05', help='起始周日期（默认 2025-05-05）')
    args = parser.parse_args()

    output_dir = args.output_dir
    start_date = date.fromisoformat(args.start_date)

    os.makedirs(output_dir, exist_ok=True)

    for week_num, profile in enumerate(WEEKLY_PROFILES):
        week_start = start_date + timedelta(weeks=week_num)
        # 每周条数: 90~110 随机浮动
        count = random.randint(90, 110)

        df = generate_week_data(week_start, profile, count)

        filename = f"{week_start.isoformat()}.xlsx"
        filepath = os.path.join(output_dir, filename)

        df.to_excel(filepath, index=False, engine='openpyxl')
        print(f"已生成: {filepath} ({count} 条)")

    print(f"\n共生成 {len(WEEKLY_PROFILES)} 个文件到 {output_dir}/ 目录")


if __name__ == '__main__':
    main()