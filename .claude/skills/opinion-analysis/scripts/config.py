# 分类配置文件

import os

# apps 目录下的应用列表（有完整分类知识库的应用）
SUPPORTED_APPS = ["抖音"]

# 应用名别名映射（包含所有可能的应用名及别名）
app_alias_map = {
    # 英文别名
    "douyin": "抖音",

    # 口语化别名
    "字节": "抖音",
    "头条系": "抖音",
    "头条": "抖音",
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