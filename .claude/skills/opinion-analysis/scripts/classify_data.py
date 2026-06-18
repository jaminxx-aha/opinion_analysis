#!/usr/bin/env python3
"""
classify_data.py - 使用LLM API自动分类舆情数据

用法:
  python classify_data.py \
    --app-name 抖音 --problem-index 5 \
    --excel-path test/douyin_100.xlsx \
    --output-dir output/douyin_100

LLM配置从项目根目录.env自动加载:
  LLM_PROVIDER      API格式 (openai/anthropic)
  LLM_MODEL         模型名称
  LLM_API_KEY       API密钥(多个key用逗号分隔)
  LLM_BASE_URL      API基础URL
  LLM_MAX_CONCURRENT 每个key的最大并发数(总并发=key数×此值, 默认1)
  LLM_MAX_TOKENS    最大生成token(默认1024)
  LLM_BATCH_SIZE    每次LLM调用处理的问题数(默认1)
  LLM_MAX_RETRIES   最大重试次数
  LLM_TIMEOUT      请求超时时间(秒, 默认30)
  LLM_TEMPERATURE  生成温度(默认0.7)
  LLM_VERIFY_SSL  SDK模式SSL校验(true/false, 默认true)
  LLM_LOG_LEVEL  日志等级(DEBUG/INFO/WARNING/ERROR, 默认DEBUG)
  LLM_DISABLE_PROXY  SDK模式禁用代理(true/false, 默认false)
"""

import sys
import os
import io

if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer') and (not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer') and (not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import json
import re
import argparse
import time
import shutil
import sqlite3

import threading
import atexit
import logging
import concurrent.futures


import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger("classify_data")
logger.setLevel(logging.INFO)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))

_ENV_LOADED = False


def _load_env():
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    for p in [os.path.join(PROJECT_DIR, ".env"), os.path.join(PROJECT_DIR, ".env.local")]:
        if os.path.isfile(p):
            load_dotenv(p, override=False)
    _ENV_LOADED = True


sys.path.insert(0, SCRIPT_DIR)
from app_list import get_supported_apps, get_app_dir


# 建表 SQL 模板（按域生成表名：report_function / report_business）
_DB_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    id INTEGER PRIMARY KEY,
    app TEXT,
    problem TEXT,
    status INTEGER DEFAULT 1,
    cls_app TEXT,
    level1 TEXT,
    level2 TEXT,
    level3 TEXT,
    full_path TEXT,
    reasoning TEXT,
    raw_data TEXT,
    version TEXT DEFAULT ''
)
"""


def report_table(domain):
    """域 → 表名。功能域/业务域分别落 report_function / report_business 表（同一 report.db）。"""
    return f"report_{domain}"


def init_db(db_path, domain):
    """初始化单库 report.db，为指定域创建 report_<domain> 表。"""
    table = report_table(domain)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute(_DB_TABLE_SQL.format(table=table))
    # 兼容旧DB：自动添加缺失的 version 列
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if 'version' not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN version TEXT DEFAULT ''")
    conn.commit()
    conn.close()


# ========== 线程局部 DB 连接复用 ==========
# save_item 在多线程批量入库中被高频调用，原先每次新建+关闭连接开销大。
# 改为每个线程复用一个连接：连接仅在所属线程使用，满足 sqlite3 默认
# check_same_thread=True；多连接并发写仍由 busy_timeout 兜底 SQLITE_BUSY。
_thread_local = threading.local()
_db_conns = []  # 登记所有线程的连接，便于统一回收
_db_conns_lock = threading.Lock()


def _get_db_conn(db_path):
    """返回当前线程复用的 SQLite 连接，首次调用时创建并登记。"""
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA busy_timeout = 30000")
        _thread_local.conn = conn
        with _db_conns_lock:
            _db_conns.append(conn)
    return conn


def _close_all_db():
    """关闭所有线程登记的连接并清空（程序退出时调用）。"""
    with _db_conns_lock:
        for conn in _db_conns:
            try:
                conn.close()
            except Exception:
                pass
        _db_conns.clear()


atexit.register(_close_all_db)


def init_output_dir(excel_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "log"), exist_ok=True)
    # 复制原始 Excel（多域续跑时可能已存在，避免覆盖报错）
    dst = os.path.join(output_dir, os.path.basename(excel_path))
    if not os.path.exists(dst):
        shutil.copy2(excel_path, dst)


def setup_logging(output_dir):
    log_dir = os.path.join(output_dir, "log")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "report.log")
    handler = logging.FileHandler(log_path, encoding="utf-8", mode="a")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.info("日志初始化完成, 日志文件: %s", log_path)


def parse_classification_md(md_content):
    """解析编号大纲格式的classification.md，生成编码→路径字典。

    Returns:
        dict: 编码字符串到名称路径列表的映射，
        如 {"0": ["其他问题"], "1": ["卡顿"], "1.1": ["卡顿","滑动卡顿"], "1.1.1": ["卡顿","滑动卡顿","首页推荐视频流上下滑动卡顿"]}
    """
    code_to_path = {"0": ["其他问题"]}

    lines = md_content.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 二级/三级: "1.1 滑动卡顿" 或 "1.1.1 首页推荐视频流上下滑动卡顿"
        # 编码含至少两个数字段(1.1或1.1.1)，后面是空格+标签
        match = re.match(r'^(\d+\.\d+(?:\.\d+)*?)\s+(.+)$', line)
        if match:
            code, label = match.group(1), match.group(2).strip()
            parts = code.split('.')
            parent_code = '.'.join(parts[:-1])
            parent_path = code_to_path.get(parent_code, [])
            code_to_path[code] = parent_path + [label]
            continue

        # 一级: "1 卡顿" (单数字+空格+标签)
        match = re.match(r'^(\d+)\s+(.+)$', line)
        if match:
            code, label = match.group(1), match.group(2).strip()
            code_to_path[code] = [label]
            continue

    return code_to_path


def code_to_classification(code, code_to_path):
    """将分类编码转换为名称路径列表，用于存库。

    Args:
        code: 分类编码字符串，如 "1.1.1" 或 "0"
        code_to_path: 编码→路径字典

    Returns:
        名称路径列表，如 ["卡顿", "滑动卡顿", "首页推荐视频流上下滑动卡顿"]
        编码"0"返回["其他问题"]
    """
    if not code or code == "0":
        return ["其他问题"]
    # 容错: 若LLM返回"1.1 滑动卡顿"格式，提取编码部分
    code_match = re.match(r'^(\d+(?:\.\d+)*)', str(code).strip())
    if code_match:
        code = code_match.group(1)
    return code_to_path.get(code, ["其他问题"])


# 各域对应的知识库文件名（除共享的 info.md 外）。
# function/business 域分别使用 *_function.md / *_business.md。
DOMAIN_FILES = {
    "function": {
        "info": "info.md",
        "examples": "examples_function.md",
        "error_examples": "error_examples_function.md",
        "classification": "classification_function.md",
    },
    "business": {
        "info": "info.md",
        "examples": "examples_business.md",
        "error_examples": "error_examples_business.md",
        "classification": "classification_business.md",
    },
}


def load_reference(app_name, domain="function"):
    app_dir = get_app_dir(app_name)
    if not app_dir:
        return None
    files = DOMAIN_FILES.get(domain, DOMAIN_FILES["function"])
    refs = {}
    # info.md 与 examples_business.md / error_examples_business.md 保持 markdown 原文
    for key in ("info", "examples", "error_examples"):
        fpath = os.path.join(app_dir, files[key])
        refs[key] = open(fpath, "r", encoding="utf-8").read() if os.path.isfile(fpath) else ""

    # 分类文件: 解析编号大纲生成编码→路径字典
    classification_path = os.path.join(app_dir, files["classification"])
    if os.path.isfile(classification_path):
        with open(classification_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        refs["classification_tree"] = parse_classification_md(md_content)  # 编码→路径字典(用于校验和转换)
        refs["classification"] = md_content  # md原文(用于prompt注入)
    else:
        refs["classification_tree"] = {"0": ["其他问题"]}
        refs["classification"] = ""

    return refs


def validate_classification(classification, code_to_path):
    """校验分类路径是否存在于编码→路径字典中

    Args:
        classification: 分类名称列表, 如 ["卡顿", "滑动卡顿", "首页推荐视频流上下滑动卡顿"]
        code_to_path: 编码→路径字典 (来自 parse_classification_md)

    Returns:
        True if path is valid (or classification is ["其他问题"])
        False if any path doesn't match any registered code path
    """
    # 特殊情况: "其他问题"是Prompt规则允许的, 不在字典中但直接放行
    if not classification or classification[0] == "其他问题":
        return True

    # 检查名称路径是否与字典中某个编码对应的路径完全匹配
    valid_paths = set(tuple(v) for v in code_to_path.values())
    return tuple(classification) in valid_paths


def build_batch_prompt(app_name, items, refs, domain="function"):
    """构建批量分类prompt，items为[{num, desc}]列表

    domain: 分类域，function=功能域/性能问题，business=业务域
    """
    domain_label = "业务模块" if domain == "business" else "性能问题"
    problems_text = "\n" + "\n".join([
        f"---PROBLEM_{i+1}---\n\n{item['desc']}\n\n---PROBLEM_{i+1}_END---\n"
        for i, item in enumerate(items)
    ])
    return f"""你是一位专业的{app_name}应用问题分类专家，请根据用户的问题描述（以---PROBLEMS---、---PROBLEMS_END---分隔，内部有{len(items)}个问题，每个问题以---PROBLEM_N---，---PROBLEM_N_END---分隔，每个问题可能属于多个分类，只要给出最相关即可），

结合应用描述（---APP---、---APP_END---分隔）、{domain_label}分类编码表（以---CLASSIFICATION---、---CLASSIFICATION_END---分隔）和分类推理示例（以---EXAMPLES---、---EXAMPLES_END---分隔），推导出最准确的分类编码。本次分析的是【{domain_label}】维度，请围绕该维度的分类树进行归类。

---PROBLEMS---
{problems_text}
---PROBLEMS_END---

---APP---
{refs.get('info', '')}
---APP_END---

---CLASSIFICATION---
{refs.get('classification', '')}
---CLASSIFICATION_END---

---EXAMPLES---
{refs.get('examples', '')}
---EXAMPLES_END---

以下是一些错误的推理示例（以---ERROR_EXAMPLES---、---ERROR_EXAMPLES_END---分隔）
---ERROR_EXAMPLES---
{refs.get('error_examples', '')}
---ERROR_EXAMPLES_END---

推导规则：参照示例的推理方式，对照编码表逐层推导，返回分类编码；无法推导的层级截断编码（如无法推导二级则只返回一级编码如"1"，无法推导三级则只返回到二级编码如"1.1"）；不属于编码表问题的返回"0"。

必须返回{len(items)}个元素，禁止多加或遗漏，必须按照以下json格式返回，json格式被三个反引号分割
```
[{{"classification": "编码", "reason": "推理过程"}}]
```

【要求】
1.推理过程需要严格按照层级推理，即先分析出第一级，然后根据一级分类分析出第二级，再根据第二级分类分析出第三第三级分类
2.忽略卓易通相关的描述，只分析原生鸿蒙相关的问题
3.要根据现有的描述分析问题，若无法进一步得到更确切的分类则返回，不要去联想猜测
"""

def extract_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in [r'```json\s*(.*?)\s*```', r'```\s*(.*?)\s*```']:
        for m in re.findall(pattern, text, re.DOTALL):
            try:
                return json.loads(m)
            except json.JSONDecodeError:
                continue
    brace = re.search(r'\[[\s\S]*\]' if '[' in text else r'\{[\s\S]*\}', text)
    if brace:
        try:
            return json.loads(brace.group())
        except json.JSONDecodeError:
            pass
    return None


# ========== Python SDK客户端 ==========

def call_llm_sdk(prompt, provider, api_key, base_url, model, max_tokens, timeout, verify_ssl, disable_proxy=False, temperature=0.7, log_file=None):
    base_url = base_url.rstrip("/") if base_url else None
    trust_env = not disable_proxy
    if provider == "anthropic":
        from anthropic import Anthropic, APITimeoutError
        if not verify_ssl or disable_proxy:
            import httpx
            http_client = httpx.Client(verify=verify_ssl, trust_env=trust_env)
            client = Anthropic(api_key=api_key, base_url=base_url, http_client=http_client) if base_url else Anthropic(api_key=api_key, http_client=http_client)
        else:
            client = Anthropic(api_key=api_key, base_url=base_url) if base_url else Anthropic(api_key=api_key)
        resp = client.messages.create(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}], temperature=temperature, timeout=timeout, stream=True)
        log_fh = open(log_file, "w", encoding="utf-8") if log_file else None
        _wrote_reasoning_header = False
        _wrote_content_header = False
        full_text = ""
        for event in resp:
            if event.type == "content_block_start":
                if log_fh:
                    block_type = event.content_block.type
                    if block_type == "thinking" and not _wrote_reasoning_header:
                        log_fh.write("===== 思考过程 =====\n")
                        log_fh.flush()
                        _wrote_reasoning_header = True
                    elif block_type == "text" and not _wrote_content_header:
                        log_fh.write("\n===== 返回内容 =====\n")
                        log_fh.flush()
                        _wrote_content_header = True
            elif event.type == "content_block_delta":
                delta_type = event.delta.type
                if delta_type == "thinking_delta":
                    if log_fh:
                        if not _wrote_reasoning_header:
                            log_fh.write("===== 思考过程 =====\n")
                            _wrote_reasoning_header = True
                        log_fh.write(event.delta.thinking)
                        log_fh.flush()
                else:
                    full_text += event.delta.text
                    if log_fh:
                        if not _wrote_content_header:
                            log_fh.write("\n===== 返回内容 =====\n")
                            _wrote_content_header = True
                        log_fh.write(event.delta.text)
                        log_fh.flush()
        if log_fh:
            log_fh.close()
        logger.info("LLM响应接收完成(Anthropic SDK, key=%s..., 长度%d)", api_key[:8], len(full_text))
        return full_text
    else:
        from openai import OpenAI, APITimeoutError
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        if not verify_ssl or disable_proxy:
            import httpx
            kwargs["http_client"] = httpx.Client(verify=verify_ssl, trust_env=trust_env)
        client = OpenAI(**kwargs)
        stream = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=temperature, timeout=timeout, stream=True, extra_body={"enable_thinking": True})
        log_fh = open(log_file, "w", encoding="utf-8") if log_file else None
        _wrote_reasoning_header = False
        _wrote_content_header = False
        full_text = ""
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta:
                reasoning = getattr(delta, 'reasoning_content', None) or ""
                content = delta.content or ""
                if reasoning:
                    if log_fh:
                        if not _wrote_reasoning_header:
                            log_fh.write("===== 思考过程 =====\n")
                            _wrote_reasoning_header = True
                        log_fh.write(reasoning)
                        log_fh.flush()
                if content:
                    full_text += content
                    if log_fh:
                        if not _wrote_content_header:
                            log_fh.write("\n===== 返回内容 =====\n")
                            _wrote_content_header = True
                        log_fh.write(content)
                        log_fh.flush()
        if log_fh:
            log_fh.close()
        logger.info("LLM响应接收完成(OpenAI SDK, key=%s..., 长度%d)", api_key[:8], len(full_text))
        return full_text


_progress_lock = threading.Lock()
_progress_done = 0
_progress_base = 0
_output_dir = ""


def clean_desc(text):
    """清洗问题描述文本，移除HTML/CSS标签残留和卡片消息等无效内容。
    客服对话数据常见: br(换行残留)、span/p(标签名残留)、
    style/color/text-*(CSS属性残留)、答：卡片消息(小艺卡片无数据)
    """
    if not text or not text.strip():
        return text

    # br → 换行符（HTML换行标记残留）
    text = re.sub(r'\bbr\b', '\n', text)

    # CSS属性残留: 属性名 + 值 + 分号（如 style text-warp-mode wrap;、color rgb 192 0 0;）
    css_props = r'\b(?:style|color|text-\w+(?:-\w+)?|font-\w+|background(?:-\w+)?|margin(?:-\w+)?|padding(?:-\w+)?|border(?:-\w+)?|width|height|display|position|overflow(?:-\w+)?|white-space|word-\w+|line-height|vertical-align|text-align|text-decoration|letter-spacing|rgb)\b[^;]*?;'
    text = re.sub(css_props, '', text)

    # HTML标签名残留: 独立英文单词形式的标签名（如 p、span、div）
    html_tags = r'\b(?:p|span|div|b|i|strong|em|a|font|center|li|ul|ol|table|tr|td|th|img|hr|pre|code|sub|sup|small|big|h[1-6]|section|article|header|footer|nav|main|label|input|button|form|select|option|textarea|script|style)\b'
    text = re.sub(html_tags, '', text)

    # 移除"答：卡片消息"回答段（小艺卡片消息无原始数据，直接删除）
    text = re.sub(r'答[:：]\s*卡片消息', '', text)

    # 移除清理后变空的"答："标记
    text = re.sub(r'\n\s*答[:：]\s*\n', '\n', text)
    text = re.sub(r'^答[:：]\s*$', '', text, flags=re.MULTILINE)

    # 规范化空白: 压缩空格、合并多余换行、清理换行前后空格
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n[ \t]+', '\n', text)
    text = text.strip()

    return text


# 当前域对应的表名（report_function / report_business），由 main() 设置，供 save_item 使用
_TABLE = "report_function"


def save_item(num, classification, reason, app_name, problem_col, df, db_path, status, version_col=None):
    """status: 0=成功, 1=其他问题, 2=失败, 3=描述过长"""
    try:
        conn = _get_db_conn(db_path)
        cursor = conn.cursor()
        row = df.iloc[num - 1]
        problem = clean_desc(str(row[problem_col])) if not pd.isna(row[problem_col]) else ""
        raw_json = json.dumps({c: str(row[c]) if not pd.isna(row[c]) else "" for c in df.columns}, ensure_ascii=False)
        version = str(row[version_col]) if version_col and not pd.isna(row[version_col]) else ""
        t = _TABLE
        if status == 0 and classification and classification[0] != "其他问题":
            l1 = classification[0]
            l2 = classification[1] if len(classification) >= 2 else ""
            l3 = classification[2] if len(classification) >= 3 else ""
            fp = ".".join(filter(None, [l1, l2, l3]))
            cursor.execute(f"INSERT OR REPLACE INTO {t} (id,app,problem,status,cls_app,level1,level2,level3,full_path,reasoning,raw_data,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (num, app_name, problem, status, app_name, l1, l2, l3, fp, reason, raw_json, version))
        elif status == 1:
            cursor.execute(f"INSERT OR REPLACE INTO {t} (id,app,problem,status,cls_app,level1,level2,level3,full_path,reasoning,raw_data,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (num, app_name, problem, status, app_name, "其他问题", "", "", "其他问题", reason, raw_json, version))
        elif status == 3:
            cursor.execute(f"INSERT OR REPLACE INTO {t} (id,app,problem,status,cls_app,level1,level2,level3,full_path,reasoning,raw_data,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (num, app_name, problem, status, app_name, "描述过长", "", "", "描述过长", reason, raw_json, version))
        else:
            cursor.execute(f"INSERT OR REPLACE INTO {t} (id,app,problem,status,reasoning,raw_data,version) VALUES (?,?,?,?,?,?,?)",
                           (num, app_name, problem, status, reason, raw_json, version))
        conn.commit()
        status_label = {0: "成功", 1: "其他问题", 2: "失败", 3: "描述过长"}
        logger.info("行%d 入库成功, 分类: %s, 推理: %s, 状态: %s", num, ".".join(classification) if classification else "无", reason, status_label.get(status, str(status)))
    except Exception as e:
        logger.error("行%d 入库失败: %s", num, e)


def process_batch(batch, app_name, problem_col, df, refs, db_path,
                   provider, api_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, temperature, total, version_col=None, domain="function"):
    """处理一批问题，batch为[{num, desc}]列表"""
    global _progress_done, _output_dir

    results = []
    valid_items = [item for item in batch if item["desc"].strip()]

    nums = [it["num"] for it in batch]
    if len(nums) == 1:
        batch_label = str(nums[0])
        log_base = f"response_{nums[0]}"
    else:
        batch_label = ",".join(str(n) for n in nums)
        log_base = f"response_{'_'.join(str(n) for n in nums)}"

    def _log_file(attempt):
        suffix = f"_retry{attempt + 1}" if attempt > 0 else ""
        return os.path.join(_output_dir, "log", f"{log_base}{suffix}.log") if _output_dir else None

    if not valid_items:
        for item in batch:
            save_item(item["num"], ["其他问题"], "空描述,跳过分类", app_name, problem_col, df, db_path, 2, version_col)
            results.append((item["num"], False))
        with _progress_lock:
            _progress_done += len(batch)
        return results

    try:
        prompt = build_batch_prompt(app_name, valid_items, refs, domain)
        row_nums = ",".join(str(it["num"]) for it in valid_items)
        logger.debug("批量开始LLM推理, 行号[%s], 有效问题数: %d", row_nums, len(valid_items))

        for attempt in range(max_retries):
            try:
                logger.info("LLM请求发送, 第%d/%d次", attempt + 1, max_retries)
                text = call_llm_sdk(prompt, provider, api_key, base_url, model, max_tokens, timeout, verify_ssl, disable_proxy, temperature=temperature, log_file=_log_file(attempt))
                logger.info("批量LLM推理返回, 文本长度: %d", len(text) if text else 0)
            except Exception as e:
                logger.warning("LLM调用失败(第%d/%d次): %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for item in valid_items:
                        save_item(item["num"], ["其他问题"], f"API调用失败: {e}", app_name, problem_col, df, db_path, 2, version_col)
                        results.append((item["num"], 2))
                    break

            parsed = extract_json(text)
            if not parsed or not isinstance(parsed, list):
                logger.warning("JSON解析失败(第%d/%d次), 原始返回: %s", attempt + 1, max_retries, text[:300] if text else "空")
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for item in valid_items:
                        save_item(item["num"], ["其他问题"], "JSON解析失败", app_name, problem_col, df, db_path, 2, version_col)
                        results.append((item["num"], 2))
                    break

            if len(parsed) != len(valid_items):
                logger.warning("结果数量不一致(第%d/%d次): 期望%d条, 返回%d条", attempt + 1, max_retries, len(valid_items), len(parsed))
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for item in valid_items:
                        save_item(item["num"], ["其他问题"], f"结果数量不一致: 期望{len(valid_items)}条, 返回{len(parsed)}条", app_name, problem_col, df, db_path, 2, version_col)
                        results.append((item["num"], 2))
                    break

            # 格式检查: classification应为字符串编码
            code_to_path = refs.get("classification_tree", {})
            format_errors = False
            for p in parsed:
                if not isinstance(p, dict):
                    continue
                cls = p.get("classification", "0")
                if not isinstance(cls, str):
                    format_errors = True
                    break

            if format_errors:
                logger.warning("分类格式错误(第%d/%d次): classification应为字符串编码", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for i, item in enumerate(valid_items):
                        num = item["num"]
                        p = parsed[i]
                        code = p.get("classification", "0") if isinstance(p, dict) else "0"
                        reason = p.get("reason", "") if isinstance(p, dict) else ""
                        classification = code_to_classification(code, code_to_path)
                        if not isinstance(code, str):
                            save_item(num, ["其他问题"], "分类格式错误: classification应为字符串编码", app_name, problem_col, df, db_path, 2, version_col)
                            results.append((num, 2))
                        elif code == "0":
                            save_item(num, classification, reason, app_name, problem_col, df, db_path, 1, version_col)
                            results.append((num, 1))
                        else:
                            save_item(num, classification, reason, app_name, problem_col, df, db_path, 0, version_col)
                            results.append((num, 0))
                        logger.info("行%d 批量推理成功, 编码: %s, 分类: %s", num, code, ".".join(classification))
                    break

            # 分类编码校验: 检查每个编码是否存在于编码→路径字典中
            invalid_codes = []
            for i, p in enumerate(parsed):
                if not isinstance(p, dict):
                    invalid_codes.append((i, "not a dict"))
                    continue
                code = p.get("classification", "0")
                if not isinstance(code, str):
                    continue  # 已在format_errors中处理
                # 容错: 提取编码部分(如"1.1 滑动卡顿" → "1.1")
                code_clean = re.match(r'^(\d+(?:\.\d+)*)', str(code).strip())
                code_str = code_clean.group(1) if code_clean else str(code).strip()
                if code_str != "0" and code_str not in code_to_path:
                    invalid_codes.append((i, code_str))

            if invalid_codes:
                for idx, invalid_code in invalid_codes:
                    logger.warning("分类编码无效(第%d/%d次), 项目%d: '%s' 不存在于编码表", attempt + 1, max_retries, idx + 1, invalid_code)
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue  # 重试整个批次
                else:
                    # 最后一次重试仍无效, 按条保存
                    for i, item in enumerate(valid_items):
                        num = item["num"]
                        p = parsed[i]
                        code = p.get("classification", "0") if isinstance(p, dict) else "0"
                        reason = p.get("reason", "") if isinstance(p, dict) else ""
                        classification = code_to_classification(code, code_to_path)
                        if not isinstance(code, str):
                            save_item(num, ["其他问题"], "分类格式错误", app_name, problem_col, df, db_path, 2, version_col)
                            results.append((num, 2))
                        elif code == "0":
                            save_item(num, classification, reason, app_name, problem_col, df, db_path, 1, version_col)
                            results.append((num, 1))
                        elif classification[0] == "其他问题":
                            # 编码不在字典中, 转换后为其他问题
                            invalid_reason = f"分类编码无效: {code} 不存在于编码表"
                            save_item(num, ["其他问题"], invalid_reason, app_name, problem_col, df, db_path, 2, version_col)
                            results.append((num, 2))
                        else:
                            save_item(num, classification, reason, app_name, problem_col, df, db_path, 0, version_col)
                            results.append((num, 0))
                    break

            for i, item in enumerate(valid_items):
                num = item["num"]
                p = parsed[i]
                code = p.get("classification", "0")
                reason = p.get("reason", "")
                classification = code_to_classification(code, code_to_path)
                if code == "0":
                    save_item(num, classification, reason, app_name, problem_col, df, db_path, 1, version_col)
                    results.append((num, 1))
                else:
                    save_item(num, classification, reason, app_name, problem_col, df, db_path, 0, version_col)
                    results.append((num, 0))
                logger.info("行%d 批量推理成功, 编码: %s, 分类: %s", num, code, ".".join(classification))
            break

    except Exception as e:
        logger.error("批量LLM推理失败: %s", e)
        for item in valid_items:
            save_item(item["num"], ["其他问题"], f"API调用失败: {e}", app_name, problem_col, df, db_path, 2, version_col)
            results.append((item["num"], 2))

    for item in batch:
        if not item["desc"].strip():
            save_item(item["num"], ["其他问题"], "空描述,跳过分类", app_name, problem_col, df, db_path, 2, version_col)
            results.append((item["num"], 2))

    with _progress_lock:
        _progress_done += len(batch)
        pct = _progress_done * 100 // total
        logger.info("[%3d%%] 已完成第%s条 (%d/%d)", pct, batch_label, _progress_done, total)

    return results


def main():
    _load_env()

    # 从环境变量读取LLM配置
    provider = os.environ.get("LLM_PROVIDER", "openai")
    model = os.environ.get("LLM_MODEL")
    api_key_raw = os.environ.get("LLM_API_KEY")
    if not api_key_raw:
        logger.error("需要 LLM_API_KEY 环境变量"); sys.exit(1)
    api_keys = [k.strip() for k in api_key_raw.split(",") if k.strip()]
    if not api_keys:
        logger.error("需要 LLM_API_KEY 环境变量 (解析后无有效key)"); sys.exit(1)
    base_url = os.environ.get("LLM_BASE_URL")
    max_concurrent = int(os.environ.get("LLM_MAX_CONCURRENT", "1"))
    total_concurrent = len(api_keys) * max_concurrent
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "1024"))
    batch_size = int(os.environ.get("LLM_BATCH_SIZE", "1"))
    max_retries = int(os.environ.get("LLM_MAX_RETRIES", "3"))
    timeout = int(os.environ.get("LLM_TIMEOUT", "30"))
    temperature = float(os.environ.get("LLM_TEMPERATURE", "0.7"))
    verify_ssl = os.environ.get("LLM_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
    disable_proxy = os.environ.get("LLM_DISABLE_PROXY", "false").lower() in ("true", "1", "yes")
    log_level = os.environ.get("LLM_LOG_LEVEL", "DEBUG").upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    if not model:
        logger.error("需要 LLM_MODEL 环境变量"); sys.exit(1)

    parser = argparse.ArgumentParser(description="使用LLM API自动分类舆情数据")
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--problem-name", default=None)
    parser.add_argument("--problem-index", type=int, required=True,
                        help="问题描述列索引(从0开始)")
    parser.add_argument("--version-index", type=int, default=-1,
                        help="版本号列索引(从0开始, -1表示无版本号)")
    parser.add_argument("--excel-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--domain", required=True, choices=["function", "business"],
                        help="分类域: function=功能域/性能问题, business=业务域")
    parser.add_argument("--retry", choices=["failed", "unknown"], default=None,
                        help="重试模式: failed=重试失败数据, unknown=重试其他问题数据")
    args = parser.parse_args()

    app_name = args.app_name
    domain = args.domain
    if app_name not in get_supported_apps():
        supported = ", ".join(get_supported_apps())
        print(f"错误: 应用 '{app_name}' 不在支持列表中，当前支持的应用: {supported}")
        sys.exit(1)

    refs = load_reference(app_name, domain)
    if not refs:
        logger.error("无法加载 '%s' 的知识库", app_name); sys.exit(1)
    if not refs.get("classification"):
        logger.error("无法加载 '%s' 域[%s]的分类知识库(classification文件缺失)", app_name, domain); sys.exit(1)

    excel_path = args.excel_path
    output_dir = args.output_dir
    init_output_dir(excel_path, output_dir)
    setup_logging(output_dir)

    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()
    problem_col = args.problem_name or columns[args.problem_index]
    if problem_col not in columns:
        logger.error("问题描述列 '%s' 不存在", problem_col); sys.exit(1)

    # 解析版本号列
    version_col = None
    if args.version_index >= 0:
        version_col = columns[args.version_index]
        if version_col not in columns:
            logger.error("版本号列 '%s' 不存在", version_col); sys.exit(1)
    if version_col:
        logger.info("版本号列: '%s'", version_col)
    else:
        logger.info("无版本号列, version 字段为空")

    filtered = list(range(len(df)))
    logger.info("总行数: %d (无应用名列筛选)", len(df))

    db_path = os.path.join(output_dir, "report.db")
    init_db(db_path, domain)

    conn = sqlite3.connect(db_path)
    table = report_table(domain)
    global _output_dir, _progress_base, _TABLE
    _TABLE = table

    if args.retry:
        # 重试模式: 找出指定状态及缺失的行
        existing = dict(conn.execute(f"SELECT id, status FROM {table}").fetchall())
        retry_ids = set()
        missing_count = 0
        failed_count = 0
        unknown_count = 0
        for i in filtered:
            row_id = i + 1
            if row_id not in existing:
                retry_ids.add(row_id)
                missing_count += 1
            elif args.retry == "failed" and existing[row_id] == 2:
                retry_ids.add(row_id)
                failed_count += 1
            elif args.retry == "unknown" and existing[row_id] == 1:
                retry_ids.add(row_id)
                unknown_count += 1
        conn.close()

        all_data = [{"num": i + 1, "desc": clean_desc(str(df.iloc[i][problem_col])) if not pd.isna(df.iloc[i][problem_col]) else ""}
                     for i in filtered if (i + 1) in retry_ids]

        logger.info("重试模式(%s): 失败%d条, 未知%d条, 缺失%d条, 共需重试%d条, 并发 %d (keys=%d, 每key=%d), 批量大小 %d, provider=%s, model=%s, temperature=%.1f",
                    args.retry, failed_count, unknown_count, missing_count, len(all_data), total_concurrent, len(api_keys), max_concurrent, batch_size, provider, model, temperature)

        _output_dir = output_dir
        _progress_base = 0

        total_all = len(filtered)
    else:
        # 续跑模式: 从最大id之后继续
        max_id = conn.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]
        conn.close()
        if max_id is None:
            max_id = 0

        all_data = [{"num": i + 1, "desc": clean_desc(str(df.iloc[i][problem_col])) if not pd.isna(df.iloc[i][problem_col]) else ""}
                     for i in filtered if (i + 1) > max_id]

        logger.info("共 %d条, 已完成 %d条, 待处理 %d条, 并发 %d (keys=%d, 每key=%d), 批量大小 %d, provider=%s, model=%s, temperature=%.1f",
                    len(filtered), max_id, len(all_data), total_concurrent, len(api_keys), max_concurrent, batch_size, provider, model, temperature)

        _output_dir = output_dir
        _progress_base = max_id

        total_all = len(filtered)
    success = 0
    unknown = 0
    failed = 0
    too_long = 0

    # 描述过长(>300字)的项直接入库status=3, 不送LLM
    too_long_items = [item for item in all_data if len(item["desc"]) > 300]
    all_data = [item for item in all_data if len(item["desc"]) <= 300]
    for item in too_long_items:
        desc_len = len(item["desc"])
        save_item(item["num"], ["描述过长"], f"清洗后描述长度{desc_len}超过300字限制, 跳过分类", app_name, problem_col, df, db_path, 3, version_col)
        too_long += 1
    if too_long_items:
        logger.info("描述过长跳过分类: %d条", len(too_long_items))

    batches = [all_data[i:i + batch_size] for i in range(0, len(all_data), batch_size)]

    logger.info("API key配置: %d个key, 每key最大并发%d, 总并发%d", len(api_keys), max_concurrent, total_concurrent)
    if len(api_keys) > 1:
        key_prefixes = [k[:8] + "..." for k in api_keys]
        logger.info("key列表(前缀): %s", ", ".join(key_prefixes))

    if total_concurrent == 1:
        for i, batch in enumerate(batches):
            assigned_key = api_keys[i % len(api_keys)]
            batch_results = process_batch(batch, app_name, problem_col, df, refs, db_path,
                                          provider, assigned_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, temperature, len(all_data), version_col, domain)
            for _, st in batch_results:
                if st == 0:
                    success += 1
                elif st == 1:
                    unknown += 1
                else:
                    failed += 1
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=total_concurrent) as executor:
            futures = {}
            for i, batch in enumerate(batches):
                assigned_key = api_keys[i % len(api_keys)]
                futures[executor.submit(process_batch, batch, app_name, problem_col, df, refs, db_path,
                                       provider, assigned_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, temperature, len(all_data), version_col, domain)] = i
            for f in concurrent.futures.as_completed(futures):
                try:
                    batch_results = f.result()
                    for _, st in batch_results:
                        if st == 0:
                            success += 1
                        elif st == 1:
                            unknown += 1
                        else:
                            failed += 1
                except Exception:
                    failed += batch_size

    conn = sqlite3.connect(db_path)
    cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    db_status = "验证通过" if cnt == total_all else f"警告: DB {cnt}条, 期望 {total_all}条"
    if args.retry:
        mode_label = f"重试-{args.retry}"
        processed = success + unknown + failed + too_long
    else:
        mode_label = "续跑"
        processed = max_id + success + unknown + failed + too_long
    logger.info("分类完成(%s): %d/%d条 (成功%d, 未知%d, 失败%d, 过长%d) | %s", mode_label, processed, total_all, success, unknown, failed, too_long, db_status)
    print(f"分类完成({mode_label}): {processed}/{total_all}条 (成功{success}, 未知{unknown}, 失败{failed}, 过长{too_long}) | {db_status}")

    # 分类完成后自动生成报告（读 output_dir 下所有域 DB 合并双标签页）
    from generate_report import generate_report
    report_html_path = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(args.excel_path))[0]}_report.html")
    report = generate_report(output_dir, report_html_path)
    if report:
        logger.info("报告已生成: %s (包含域: %s)", report['path'], ",".join(report.get('domains', [])))
        print(f"\n报告已生成: {report['path']}")
        print(f"包含域: {', '.join(report.get('domains', []))}")
        print(f"| 属性 | 值 |")
        print(f"|------|-----|")
        print(f"| 总数据 | {report['total']} |")
        print(f"| 已分类 | {report['classified']} |")
        print(f"| 其他问题 | {report['unknown_issue']} |")
        print(f"| 推理失败 | {report['infer_failed']} |")
    else:
        logger.warning("报告生成失败")

    _close_all_db()


if __name__ == "__main__":
    main()