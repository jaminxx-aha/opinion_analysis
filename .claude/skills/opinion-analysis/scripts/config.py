# 分类配置文件

import os

# apps 目录下的应用列表（有完整分类知识库的应用）
SUPPORTED_APPS = ["抖音", "微信", "淘宝", "快手", "小红书"]

# 应用名别名映射（包含所有可能的应用名及别名）
app_alias_map = {
    # 英文别名
    "wechat": "微信",
    "douyin": "抖音",
    "taobao": "淘宝",
    "kuaishou": "快手",
    "xiaohongshu": "小红书",
    "red": "小红书",
    "bilibili": "哔哩哔哩",
    "jd": "京东",
    "meituan": "美团",
    "pinduoduo": "拼多多",

    # 口语化别名
    "狗东": "京东",
    "东哥": "京东",
    "拼夕夕": "拼多多",
    "B站": "哔哩哔哩",
    "小破站": "哔哩哔哩",
    "阿里爸爸": "淘宝",
    "阿里": "淘宝",
    "鹅厂": "微信",
    "腾讯": "微信",
    "字节": "抖音",
    "头条系": "抖音",
    "头条": "抖音",
    "红书": "小红书",
}

# 兼容旧变量名
apps_in_folder = SUPPORTED_APPS


def resolve_column(col_spec, columns):
    """将列索引或列名转换为实际列名"""
    if col_spec is None:
        return None
    try:
        idx = int(col_spec)
        if 1 <= idx <= len(columns):
            return columns[idx - 1]
        return None
    except ValueError:
        return col_spec


def get_app_dir(skill_path, app_name):
    """获取应用知识库目录路径，返回None表示不支持"""
    app_dir = os.path.join(skill_path, "references", "apps", app_name)
    if os.path.isdir(app_dir):
        return app_dir
    return None