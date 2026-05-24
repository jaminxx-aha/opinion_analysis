import random
import pandas as pd
from datetime import datetime, timedelta

random.seed(42)

# Classification tree for generating problem descriptions
CLASSIFICATION_TREE = {
    "卡顿": {
        "滑动卡顿": ["首页推荐视频流上下滑动卡顿", "关注页视频流滑动卡顿", "同城页视频流滑动卡顿",
                    "直播广场列表滑动卡顿", "商城商品列表滑动卡顿", "消息列表滑动卡顿", "评论列表滑动卡顿"],
        "视频播放卡顿": ["首页推荐视频播放卡顿", "关注页视频播放卡顿", "同城页视频播放卡顿",
                      "搜索结果视频播放卡顿", "个人主页视频播放卡顿", "视频详情页播放卡顿", "视频预览播放卡顿"],
        "页面转场卡顿": ["首页进入直播间转场卡顿", "首页进入个人主页转场卡顿", "视频页进入评论区转场卡顿",
                      "视频页进入分享页转场卡顿", "商城首页进入商品详情转场卡顿", "商品详情进入购物车转场卡顿",
                      "消息列表进入聊天页转场卡顿", "个人主页进入设置页转场卡顿", "底部Tab切换转场卡顿", "页面返回转场卡顿"],
        "直播卡顿": ["直播观看画面卡顿", "直播弹幕滚动卡顿", "直播购物车展开卡顿",
                   "直播礼物动画卡顿", "直播连麦画面卡顿", "直播PK特效卡顿", "直播滤镜特效卡顿"],
        "拍摄/剪辑卡顿": ["视频拍摄预览卡顿", "视频拍摄滤镜切换卡顿", "视频剪辑编辑卡顿",
                     "视频剪辑特效添加卡顿", "视频剪辑预览卡顿", "视频字幕编辑卡顿", "视频音乐选择卡顿", "视频发布上传卡顿"],
        "互动操作卡顿": ["视频点赞动画卡顿", "视频评论发送卡顿", "视频分享操作卡顿",
                     "视频收藏操作卡顿", "评论点赞卡顿", "评论回复卡顿", "直播点赞卡顿"],
        "加载卡顿": ["首页刷新加载卡顿", "视频封面加载卡顿", "评论加载卡顿",
                 "直播间加载卡顿", "商品图片加载卡顿", "消息列表加载卡顿", "个人主页加载卡顿"],
    },
    "响应慢/延迟": {
        "视频播放延迟": ["视频开始播放延迟", "视频切换响应延迟", "视频暂停恢复延迟",
                      "视频进度调整延迟", "视频音画同步延迟"],
        "直播延迟": ["直播画面延迟", "直播弹幕延迟", "直播互动延迟", "直播礼物显示延迟",
                  "直播连麦延迟", "直播开播延迟"],
        "交互响应延迟": ["点击响应延迟", "滑动响应延迟", "搜索响应延迟", "评论发送延迟",
                     "消息发送延迟", "点赞响应延迟", "分享响应延迟"],
        "加载延迟": ["首页加载延迟", "视频加载延迟", "图片加载延迟", "评论加载延迟",
                 "直播加载延迟", "商品加载延迟", "消息加载延迟"],
        "上传/发布延迟": ["视频上传延迟", "视频发布延迟", "评论上传延迟", "图片上传延迟", "直播推流延迟"],
    },
    "闪退/崩溃": {
        "使用过程闪退": ["视频播放过程闪退", "滑动浏览过程闪退", "直播观看过程闪退",
                     "视频拍摄过程闪退", "视频编辑过程闪退", "评论浏览过程闪退", "商城浏览过程闪退", "消息查看过程闪退"],
        "操作触发闪退": ["视频点赞闪退", "视频评论闪退", "视频分享闪退", "直播互动闪退",
                     "搜索操作闪退", "发布视频闪退", "下单支付闪退"],
        "页面切换闪退": ["首页进入直播间闪退", "视频进入评论区闪退", "底部Tab切换闪退",
                     "商城页面切换闪退", "个人主页切换闪退"],
        "启动闪退": ["冷启动闪退", "热启动闪退", "后台切换前台闪退", "推送点击启动闪退"],
        "特定场景崩溃": ["高清视频播放崩溃", "长时间直播崩溃", "多视频连续播放崩溃",
                     "复杂特效视频崩溃", "直播连麦崩溃", "大文件上传崩溃"],
    },
    "启动异常": {
        "启动慢": ["冷启动慢", "热启动慢", "后台切换前台慢", "推送点击启动慢", "分享链接启动慢", "小程序启动慢"],
        "启动失败": ["冷启动失败", "热启动失败", "后台切换失败", "推送启动失败", "网络异常启动失败"],
        "启动卡住": ["启动加载卡住", "启动广告卡住", "启动登录卡住", "启动首页加载卡住"],
        "启动显示异常": ["启动黑屏", "启动白屏", "启动Logo停留过长", "启动广告显示异常", "启动界面闪烁"],
    },
    "发热": {
        "视频播放发热": ["短时间播放发热", "长时间播放发热", "高清视频播放发热", "连续滑动发热", "多任务播放发热"],
        "直播发热": ["直播观看发热", "直播长时间观看发热", "直播互动发热", "直播连麦发热", "直播开播发热"],
        "拍摄/剪辑发热": ["视频拍摄发热", "视频长时间拍摄发热", "视频剪辑发热", "视频特效处理发热", "视频导出发热"],
        "综合使用发热": ["多功能切换发热", "后台运行发热", "充电时使用发热", "低电量时发热", "高温环境发热"],
    },
    "内存异常": {
        "内存占用高": ["首页内存占用高", "视频播放内存占用高", "直播观看内存占用高",
                    "视频拍摄内存占用高", "视频编辑内存占用高", "后台内存占用高", "多任务内存占用高"],
        "内存泄漏": ["视频播放内存泄漏", "直播观看内存泄漏", "页面切换内存泄漏",
                  "长时间使用内存泄漏", "图片加载内存泄漏", "特效渲染内存泄漏"],
        "内存不足触发问题": ["内存不足卡顿", "内存不足闪退", "内存不足加载失败", "内存不足图片模糊", "内存不足视频异常"],
    },
    "渲染异常": {
        "视频渲染异常": ["视频画面模糊", "视频画面卡帧", "视频画面撕裂", "视频画面闪烁",
                      "视频画面黑屏", "视频画面花屏", "视频画面色差", "视频画面比例异常"],
        "直播渲染异常": ["直播画面模糊", "直播画面卡帧", "直播画面黑屏", "直播画面花屏",
                      "直播弹幕显示异常", "直播礼物特效异常", "直播连麦画面异常"],
        "界面渲染异常": ["界面元素显示异常", "界面布局错乱", "界面文字显示异常", "界面图片显示异常",
                      "界面动画异常", "界面颜色显示异常", "界面遮挡异常"],
        "特效渲染异常": ["视频滤镜异常", "视频特效异常", "直播滤镜异常", "直播美颜异常",
                      "滑动特效异常", "互动特效异常"],
        "图片渲染异常": ["视频封面模糊", "商品图片模糊", "用户头像模糊", "评论图片异常",
                      "消息图片异常", "图片加载失败"],
    },
    "网络异常": {
        "网络连接异常": ["无网络连接", "网络连接超时", "网络连接中断", "WiFi连接异常",
                     "移动网络连接异常", "网络切换异常", "弱网环境连接异常"],
        "视频网络异常": ["视频加载失败", "视频播放中断", "视频缓冲慢", "视频重新加载", "视频画质自动降低"],
        "直播网络异常": ["直播连接失败", "直播断流", "直播画面卡顿", "直播弹幕延迟",
                      "直播推流异常", "直播连麦网络异常"],
        "交互网络异常": ["点赞失败", "评论发送失败", "分享失败", "消息发送失败",
                      "搜索失败", "关注/取消关注失败"],
        "商城网络异常": ["商品加载失败", "下单失败", "支付失败", "订单查询失败", "图片加载失败"],
        "上传网络异常": ["视频上传失败", "视频上传中断", "视频上传慢", "图片上传失败", "直播开播失败"],
    },
}

# Time prefix patterns
TIME_PREFIXES = ["今天", "昨天", "最近", "刚才", "这几天", "从昨天开始", "今天早上",
                "今天下午", "今天晚上", "昨天晚上", "最近一周", "这段时间", "一直以来"]

# Channel sources
CHANNELS = ["App Store评论", "官方客服", "应用市场", "应用内反馈", "社交媒体", "黑猫投诉", "微博投诉"]

# Device types
DEVICES = ["华为P50", "华为Mate60", "iPhone 15", "iPhone 14", "iPhone 13",
          "小米12", "小米13", "OPPO Find X6", "OPPO Find X5", "vivo X90", "vivo X100",
          "荣耀Magic4", "荣耀Magic5", "一加11", "一加12", "三星S23", "三星S24",
          "Redmi K60", "Redmi Note 12", "iPhone 15 Pro", "iPhone 14 Pro"]

# OS versions
OS_VERSIONS = ["Android 14", "Android 13", "Android 12", "iOS 17.1", "iOS 16.5",
              "鸿蒙OS 3.0", "鸿蒙OS 4.0", "鸿蒙OS 4.2"]

# Problem statuses
STATUSES = ["待处理", "已解决", "未解决", "已关闭"]

# Priorities
PRIORITIES = ["高", "中", "低"]

# Handlers
HANDLERS = ["客服1号", "客服2号", "客服3号", "客服4号", "客服5号",
           "客服6号", "客服7号", "客服8号", "未分配"]

# Priority weights for categories (more common issues get higher weight)
CATEGORY_WEIGHTS = {
    "卡顿": 25,
    "响应慢/延迟": 15,
    "闪退/崩溃": 15,
    "启动异常": 10,
    "发热": 12,
    "内存异常": 8,
    "渲染异常": 10,
    "网络异常": 15,
}


def generate_problem_description():
    """Generate a realistic problem description based on the classification tree."""
    # Select category by weight
    categories = list(CATEGORY_WEIGHTS.keys())
    weights = list(CATEGORY_WEIGHTS.values())
    category = random.choices(categories, weights=weights, k=1)[0]

    # Select sub-category
    sub_categories = list(CLASSIFICATION_TREE[category].keys())
    sub_category = random.choice(sub_categories)

    # Select specific problem
    specific_problem = random.choice(CLASSIFICATION_TREE[category][sub_category])

    # Remove "卡顿"/"延迟" suffix from the specific problem for natural language
    # and construct a sentence
    time_prefix = random.choice(TIME_PREFIXES)

    # Generate natural language description
    # Some descriptions directly use the problem, others combine with context
    patterns = [
        f"{time_prefix}抖音{specific_problem}",
        f"抖音{specific_problem}，很烦",
        f"{time_prefix}发现抖音{specific_problem}",
        f"抖音{specific_problem}严重影响体验",
        f"{time_prefix}开始抖音{specific_problem}",
        f"抖音{specific_problem}，希望尽快修复",
        f"用抖音时{specific_problem}",
        f"{time_prefix}抖音又{specific_problem}",
    ]

    return random.choice(patterns)


def generate_date():
    """Generate a random date in 2024."""
    start = datetime(2024, 1, 1)
    end = datetime(2024, 12, 31)
    delta = (end - start).days
    random_date = start + timedelta(days=random.randint(0, delta))
    return random_date.strftime("%Y-%m-%d")


def generate_time():
    """Generate a random time."""
    hour = random.randint(0, 23)
    minute = random.randint(0, 59)
    return f"{hour:02d}:{minute:02d}"


def generate_user_id():
    """Generate a random user ID."""
    return f"U{random.randint(1, 999999)}"


def generate_priority_for_category(category):
    """Assign priority based on category severity."""
    high_priority_cats = ["闪退/崩溃", "启动异常", "网络异常"]
    if category in high_priority_cats:
        return random.choices(["高", "中", "低"], weights=[50, 35, 15], k=1)[0]
    else:
        return random.choices(["高", "中", "低"], weights=[25, 45, 30], k=1)[0]


def generate_data(n_rows=100000):
    """Generate n_rows of simulated sentiment data."""
    rows = []
    for i in range(1, n_rows + 1):
        # Generate problem description and extract category for priority assignment
        problem_desc = generate_problem_description()

        # Determine category from description for priority weighting
        category = None
        for cat in CLASSIFICATION_TREE:
            if cat in problem_desc or any(
                keyword in problem_desc for keyword in
                ["卡顿", "延迟", "慢", "闪退", "崩溃", "发热", "内存", "模糊", "异常", "失败", "中断"]
            ):
                # Simple keyword matching
                for cat_name in CLASSIFICATION_TREE:
                    cat_keywords = {
                        "卡顿": ["卡顿"],
                        "响应慢/延迟": ["延迟", "响应慢", "慢"],
                        "闪退/崩溃": ["闪退", "崩溃"],
                        "启动异常": ["启动", "黑屏", "白屏"],
                        "发热": ["发热"],
                        "内存异常": ["内存"],
                        "渲染异常": ["模糊", "花屏", "撕裂", "闪烁", "渲染"],
                        "网络异常": ["失败", "中断", "断流", "无网络", "超时"],
                    }
                    if any(kw in problem_desc for kw in cat_keywords[cat_name]):
                        category = cat_name
                        break
                break
        if category is None:
            category = "卡顿"

        priority = generate_priority_for_category(category)

        # Status: higher priority more likely to be unresolved
        if priority == "高":
            status = random.choices(STATUSES, weights=[40, 25, 25, 10], k=1)[0]
        elif priority == "中":
            status = random.choices(STATUSES, weights=[30, 35, 20, 15], k=1)[0]
        else:
            status = random.choices(STATUSES, weights=[20, 40, 15, 25], k=1)[0]

        # Handler: unresolved more likely unassigned
        if status in ["待处理", "未解决"]:
            handler = random.choices(HANDLERS, weights=[5, 5, 5, 5, 5, 5, 5, 5, 60], k=1)[0]
        else:
            handler = random.choices(HANDLERS[:-1], k=1)[0]

        row = {
            "序号": i,
            "应用名": "抖音",
            "日期": generate_date(),
            "时间": generate_time(),
            "问题描述": problem_desc,
            "用户ID": generate_user_id(),
            "渠道来源": random.choice(CHANNELS),
            "设备类型": random.choice(DEVICES),
            "系统版本": random.choice(OS_VERSIONS),
            "问题状态": status,
            "优先级": priority,
            "处理人员": handler,
        }
        rows.append(row)

    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100000
    output_path = sys.argv[2] if len(sys.argv) > 2 else f"test/抖音舆情数据_{n}.xlsx"

    print(f"生成 {n} 条抖音舆情数据...")
    df = generate_data(n)
    df.to_excel(output_path, index=False, engine="openpyxl")
    print(f"数据已保存到 {output_path}")
    print(f"列名: {list(df.columns)}")
    print(f"行数: {len(df)}")
    print(f"前5行示例:")
    print(df.head().to_string())