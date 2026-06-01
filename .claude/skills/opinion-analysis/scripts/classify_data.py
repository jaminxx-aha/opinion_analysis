#!/usr/bin/env python3
"""
classify_data.py - 使用LLM API自动分类舆情数据

用法:
  python classify_data.py \
    --app-name 抖音 --app-index 2 --problem-index 5 \
    --excel-path test/douyin_100.xlsx \
    --output-dir output/douyin_100

LLM配置从项目根目录.env自动加载:
  LLM_PROVIDER      API格式 (openai/anthropic)
  LLM_MODEL         模型名称
  LLM_API_KEY       API密钥
  LLM_BASE_URL      API基础URL
  LLM_MAX_CONCURRENT 最大并发数(默认1)
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
from config import resolve_column, app_alias_map, SUPPORTED_APPS, get_app_dir


DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS report (
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
    raw_data TEXT
)
"""


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute(DB_SCHEMA)
    conn.commit()
    conn.close()


def init_output_dir(excel_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "log"), exist_ok=True)
    shutil.copy2(excel_path, os.path.join(output_dir, os.path.basename(excel_path)))


def setup_logging(output_dir):
    log_dir = os.path.join(output_dir, "log")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "report.log")
    handler = logging.FileHandler(log_path, encoding="utf-8", mode="a")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.info("日志初始化完成, 日志文件: %s", log_path)


def load_reference(app_name):
    app_dir = get_app_dir(SKILL_DIR, app_name)
    if not app_dir:
        return None
    refs = {}
    for fname, key in [("info.md", "info"), ("classification.md", "classification"), ("examples.md", "examples")]:
        fpath = os.path.join(app_dir, fname)
        refs[key] = open(fpath, "r", encoding="utf-8").read() if os.path.isfile(fpath) else ""
    return refs


def build_batch_prompt(app_name, items, refs):
    """构建批量分类prompt，items为[{num, desc}]列表"""
    problems_text = "\n" + "\n".join([
        f"---PROBLEM_{i+1}---\n\n{item['desc']}\n\n---PROBLEM_{i+1}_END---\n"
        for i, item in enumerate(items)
    ])
    return f"""你是一位专业的{app_name}应用问题分类专家，请根据用户的问题描述（以---PROBLEMS---、---PROBLEMS_END---分隔，内部有{len(items)}个问题，每个问题以---PROBLEM_N---，---PROBLEM_N_END---分隔，每个问题可能属于多个分类，只要给出最相关即可），

结合应用描述（---APP---、---APP_END---分隔）、问题分类（以---CLASSIFICATION---、---CLASSIFICATION_END---分隔）和分类推理示例（以---EXAMPLES---、---EXAMPLES_END---分隔），逐层推导出最准确的分类。

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

推导规则：参照示例的推理方式逐层推导，无法推导的层级截断（如无法推导二级则只返回一级，无法推导三级则只返回到二级）；不属于性能问题的归为"未知问题"。

必须返回{len(items)}个元素，禁止多加或遗漏，必须按照以下json格式返回，json格式被三个反引号分割
```
[{{"classification": ["一级分类", "二级分类", "三级分类"], "reason": "推理过程"}}]
```
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
        logger.info("LLM响应接收完成(Anthropic SDK), 长度%d", len(full_text))
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
        logger.info("LLM响应接收完成(OpenAI SDK), 长度%d", len(full_text))
        return full_text


_progress_lock = threading.Lock()
_progress_done = 0
_progress_base = 0
_output_dir = ""


def save_item(num, classification, reason, app_name, problem_col, df, db_path, status):
    """status: 0=成功, 1=未知问题, 2=失败"""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA busy_timeout = 30000")
        cursor = conn.cursor()
        row = df.iloc[num - 1]
        problem = str(row[problem_col]) if not pd.isna(row[problem_col]) else ""
        raw_json = json.dumps({c: str(row[c]) if not pd.isna(row[c]) else "" for c in df.columns}, ensure_ascii=False)
        if status == 0 and classification and classification[0] != "未知问题":
            l1 = classification[0]
            l2 = classification[1] if len(classification) >= 2 else ""
            l3 = classification[2] if len(classification) >= 3 else ""
            fp = ".".join(filter(None, [l1, l2, l3]))
            cursor.execute("INSERT OR REPLACE INTO report (id,app,problem,status,cls_app,level1,level2,level3,full_path,reasoning,raw_data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (num, app_name, problem, status, app_name, l1, l2, l3, fp, reason, raw_json))
        elif status == 1:
            cursor.execute("INSERT OR REPLACE INTO report (id,app,problem,status,cls_app,level1,level2,level3,full_path,reasoning,raw_data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (num, app_name, problem, status, app_name, "未知问题", "", "", "未知问题", reason, raw_json))
        else:
            cursor.execute("INSERT OR REPLACE INTO report (id,app,problem,status,reasoning,raw_data) VALUES (?,?,?,?,?,?)",
                           (num, app_name, problem, status, reason, raw_json))
        conn.commit()
        conn.close()
        status_label = {0: "成功", 1: "未知问题", 2: "失败"}
        logger.info("行%d 入库成功, 分类: %s, 推理: %s, 状态: %s", num, ".".join(classification) if classification else "无", reason, status_label.get(status, str(status)))
    except Exception as e:
        logger.error("行%d 入库失败: %s", num, e)


def process_batch(batch, app_name, problem_col, df, refs, db_path,
                   provider, api_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, temperature, total):
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
            save_item(item["num"], ["未知问题"], "空描述,跳过分类", app_name, problem_col, df, db_path, 2)
            results.append((item["num"], False))
        with _progress_lock:
            _progress_done += len(batch)
        return results

    try:
        prompt = build_batch_prompt(app_name, valid_items, refs)
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
                        save_item(item["num"], ["未知问题"], f"API调用失败: {e}", app_name, problem_col, df, db_path, 2)
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
                        save_item(item["num"], ["未知问题"], "JSON解析失败", app_name, problem_col, df, db_path, 2)
                        results.append((item["num"], 2))
                    break

            if len(parsed) != len(valid_items):
                logger.warning("结果数量不一致(第%d/%d次): 期望%d条, 返回%d条", attempt + 1, max_retries, len(valid_items), len(parsed))
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for item in valid_items:
                        save_item(item["num"], ["未知问题"], f"结果数量不一致: 期望{len(valid_items)}条, 返回{len(parsed)}条", app_name, problem_col, df, db_path, 2)
                        results.append((item["num"], 2))
                    break

            format_errors = False
            for p in parsed:
                if not isinstance(p, dict):
                    continue
                cls = p.get("classification", ["未知问题"])
                if not isinstance(cls, list):
                    format_errors = True
                    break

            if format_errors:
                logger.warning("分类格式错误(第%d/%d次)", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for i, item in enumerate(valid_items):
                        num = item["num"]
                        p = parsed[i]
                        cls = p.get("classification", ["未知问题"])
                        reason = p.get("reason", "")
                        if not isinstance(cls, list):
                            save_item(num, ["未知问题"], "分类格式错误", app_name, problem_col, df, db_path, 2)
                            results.append((num, 2))
                        elif cls[0] == "未知问题":
                            save_item(num, cls, reason, app_name, problem_col, df, db_path, 1)
                            results.append((num, 1))
                        else:
                            save_item(num, cls, reason, app_name, problem_col, df, db_path, 0)
                            results.append((num, 0))
                        logger.info("行%d 批量推理成功, 分类: %s", num, ".".join(cls) if isinstance(cls, list) else "格式错误")
                    break

            for i, item in enumerate(valid_items):
                num = item["num"]
                p = parsed[i]
                cls = p.get("classification", ["未知问题"])
                reason = p.get("reason", "")
                if cls[0] == "未知问题":
                    save_item(num, cls, reason, app_name, problem_col, df, db_path, 1)
                    results.append((num, 1))
                else:
                    save_item(num, cls, reason, app_name, problem_col, df, db_path, 0)
                    results.append((num, 0))
                logger.info("行%d 批量推理成功, 分类: %s", num, ".".join(cls))
            break

    except Exception as e:
        logger.error("批量LLM推理失败: %s", e)
        for item in valid_items:
            save_item(item["num"], ["未知问题"], f"API调用失败: {e}", app_name, problem_col, df, db_path, 2)
            results.append((item["num"], 2))

    for item in batch:
        if not item["desc"].strip():
            save_item(item["num"], ["未知问题"], "空描述,跳过分类", app_name, problem_col, df, db_path, 2)
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
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    max_concurrent = int(os.environ.get("LLM_MAX_CONCURRENT", "1"))
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "1024"))
    batch_size = int(os.environ.get("LLM_BATCH_SIZE", "1"))
    max_retries = int(os.environ.get("LLM_MAX_RETRIES", "3"))
    timeout = int(os.environ.get("LLM_TIMEOUT", "30"))
    temperature = float(os.environ.get("LLM_TEMPERATURE", "0.7"))
    verify_ssl = os.environ.get("LLM_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
    disable_proxy = os.environ.get("LLM_DISABLE_PROXY", "false").lower() in ("true", "1", "yes")
    log_level = os.environ.get("LLM_LOG_LEVEL", "DEBUG").upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    if not api_key:
        logger.error("需要 LLM_API_KEY 环境变量"); sys.exit(1)
    if not model:
        logger.error("需要 LLM_MODEL 环境变量"); sys.exit(1)

    parser = argparse.ArgumentParser(description="使用LLM API自动分类舆情数据")
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--app-index", type=int, required=True)
    parser.add_argument("--problem-name", default=None)
    parser.add_argument("--problem-index", type=int, required=True)
    parser.add_argument("--excel-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--retry", choices=["failed", "unknown"], default=None,
                        help="重试模式: failed=重试失败数据, unknown=重试未知问题数据")
    args = parser.parse_args()

    app_name = args.app_name
    if app_name not in SUPPORTED_APPS:
        logger.warning("' %s' 不在支持列表中, 所有数据归为'未知问题'", app_name)
        refs = {"info": "", "classification": "", "examples": ""}
    else:
        refs = load_reference(app_name)
        if not refs:
            logger.error("无法加载 '%s' 的知识库", app_name); sys.exit(1)

    excel_path = args.excel_path
    output_dir = args.output_dir
    init_output_dir(excel_path, output_dir)
    setup_logging(output_dir)

    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()
    problem_col = args.problem_name or resolve_column(args.problem_index, columns)
    if problem_col not in columns:
        logger.error("问题描述列 '%s' 不存在", problem_col); sys.exit(1)

    if args.app_index > 0:
        app_col = resolve_column(args.app_index, columns)
        if app_col not in columns:
            logger.error("应用名列 '%s' 不存在", app_col); sys.exit(1)
        filtered = [idx for idx, row in df.iterrows()
                     if app_alias_map.get(str(row[app_col]).strip() if not pd.isna(row[app_col]) else "", str(row[app_col]).strip() if not pd.isna(row[app_col]) else "") == app_name]
        logger.info("总行数: %d, 筛选 '%s': %d条", len(df), app_name, len(filtered))
        if not filtered:
            logger.warning("未找到 '%s' 数据, 处理全部行", app_name)
            filtered = list(range(len(df)))
    else:
        filtered = list(range(len(df)))
        logger.info("总行数: %d (无应用名列筛选)", len(df))

    db_path = os.path.join(output_dir, "report.db")
    init_db(db_path)

    conn = sqlite3.connect(db_path)

    global _output_dir, _progress_base

    if args.retry:
        # 重试模式: 找出指定状态及缺失的行
        existing = dict(conn.execute("SELECT id, status FROM report").fetchall())
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

        all_data = [{"num": i + 1, "desc": str(df.iloc[i][problem_col]) if not pd.isna(df.iloc[i][problem_col]) else ""}
                     for i in filtered if (i + 1) in retry_ids]

        logger.info("重试模式(%s): 失败%d条, 未知%d条, 缺失%d条, 共需重试%d条, 并发 %d, 批量大小 %d, provider=%s, model=%s, temperature=%.1f",
                    args.retry, failed_count, unknown_count, missing_count, len(all_data), max_concurrent, batch_size, provider, model, temperature)

        _output_dir = output_dir
        _progress_base = 0

        total_all = len(filtered)
    else:
        # 续跑模式: 从最大id之后继续
        max_id = conn.execute("SELECT MAX(id) FROM report").fetchone()[0]
        conn.close()
        if max_id is None:
            max_id = 0

        all_data = [{"num": i + 1, "desc": str(df.iloc[i][problem_col]) if not pd.isna(df.iloc[i][problem_col]) else ""}
                     for i in filtered if (i + 1) > max_id]

        logger.info("共 %d条, 已完成 %d条, 待处理 %d条, 并发 %d, 批量大小 %d, provider=%s, model=%s, temperature=%.1f",
                    len(filtered), max_id, len(all_data), max_concurrent, batch_size, provider, model, temperature)

        _output_dir = output_dir
        _progress_base = max_id

        total_all = len(filtered)
    success = 0
    unknown = 0
    failed = 0

    batches = [all_data[i:i + batch_size] for i in range(0, len(all_data), batch_size)]

    if max_concurrent == 1:
        for batch in batches:
            batch_results = process_batch(batch, app_name, problem_col, df, refs, db_path,
                                          provider, api_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, temperature, len(all_data))
            for _, st in batch_results:
                if st == 0:
                    success += 1
                elif st == 1:
                    unknown += 1
                else:
                    failed += 1
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {executor.submit(process_batch, batch, app_name, problem_col, df, refs, db_path,
                                       provider, api_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, temperature, len(all_data)): i
                       for i, batch in enumerate(batches)}
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
    cnt = conn.execute("SELECT COUNT(*) FROM report").fetchone()[0]
    conn.close()
    db_status = "验证通过" if cnt == total_all else f"警告: DB {cnt}条, 期望 {total_all}条"
    if args.retry:
        mode_label = f"重试-{args.retry}"
        processed = success + unknown + failed
    else:
        mode_label = "续跑"
        processed = max_id + success + unknown + failed
    logger.info("分类完成(%s): %d/%d条 (成功%d, 未知%d, 失败%d) | %s", mode_label, processed, total_all, success, unknown, failed, db_status)
    print(f"分类完成({mode_label}): {processed}/{total_all}条 (成功{success}, 未知{unknown}, 失败{failed}) | {db_status}")

    # 分类完成后自动生成报告
    from analyze_excel import generate_report
    report_path = generate_report(db_path, output_dir)
    if report_path:
        logger.info("报告已生成: %s", report_path)
        print(f"报告已生成: {report_path}")
    else:
        logger.warning("报告生成失败")


if __name__ == "__main__":
    main()