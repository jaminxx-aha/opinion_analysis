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
  LLM_RUNTIME       调用方式 (native/sdk, 默认native)
  LLM_MODEL         模型名称
  LLM_API_KEY       API密钥
  LLM_BASE_URL      API基础URL
  LLM_MAX_CONCURRENT 最大并发数
  LLM_MAX_TOKENS    最大生成token
  LLM_BATCH_SIZE    每次LLM调用处理的问题数(默认1)
  LLM_MAX_RETRIES   最大重试次数
  LLM_TIMEOUT      请求超时时间(秒, 默认120)
  LLM_VERIFY_SSL  SDK模式SSL校验(true/false, 默认true)
  LLM_LOG_LEVEL  日志等级(DEBUG/INFO/WARNING/ERROR, 默认INFO)
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
import ssl
import sqlite3
import threading
import logging
import concurrent.futures
import urllib.request
import urllib.error

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
    problems_text = "\n".join([
        f"[问题{i+1}] {item['desc']}\n"
        for i, item in enumerate(items)
    ])
    return f"""你是一位专业的{app_name}应用性能问题分类专家，精通{app_name}的功能模块、页面结构和各类性能问题的表现特征。你需要根据用户反馈的问题描述，结合{app_name}的应用知识，逐层推导出最准确的分类。

当前需要分类的{"1个" if len(items) == 1 else f"{len(items)}个"}{app_name}舆情问题描述如下：

---DATA---
{problems_text}
---DATA_END---

请根据以下参考资料推导分类：

【应用描述】
{refs.get('info', '')}

【问题分类树】
{refs.get('classification', '')}

【分类推理示例】（注意：问题描述可能不含应用名，但已知为{app_name}的问题）
{refs.get('examples', '')}

推导规则：参照示例的推理方式逐层推导，无法推导的层级截断（如无法推导二级则只返回一级，无法推导三级则只返回到二级）；不属于性能问题的归为"未知问题"。

必须按照以下json格式返回，不要返回多余数据，json格式被三个反引号分割
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


# ========== 原生HTTP LLM客户端 (urllib) ==========

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def call_llm(prompt, provider, api_key, base_url, model, max_tokens, max_retries, timeout, log_file=None):
    base_url = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"
    headers = {"Content-Type": "application/json"}
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "stream": True
    }

    if provider == "anthropic":
        url = base_url + "/messages"
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        if base_url.endswith("/v1"):
            url = base_url + "/chat/completions"
        else:
            url = base_url + "/v1/chat/completions"
        headers["Authorization"] = f"Bearer {api_key}"

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    for attempt in range(max_retries):
        try:
            logger.info("LLM请求发送(原生), 尝试%d/%d", attempt + 1, max_retries)
            resp = urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout)
            result = _read_stream(resp, provider, log_file)
            logger.info("LLM响应接收完成(原生), 长度%d", len(result))
            return result
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            logger.error("LLM API HTTP错误 %d: %s", e.code, error_body[:300])
            if attempt < max_retries - 1:
                time.sleep(3)
            else:
                raise Exception(f"API错误 {e.code}: {error_body[:300]}")
        except urllib.error.URLError as e:
            logger.error("LLM API连接错误: %s", e.reason)
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                raise
        except Exception as e:
            logger.error("LLM调用异常: %s", e)
            if attempt < max_retries - 1:
                time.sleep(3)
            else:
                raise


def _read_stream(resp, provider, log_file=None):
    """读取SSE流式响应，拼接完整文本，流式打印到日志文件"""
    full_text = ""
    log_fh = open(log_file, "w", encoding="utf-8") if log_file else None
    _wrote_reasoning_header = False
    _wrote_content_header = False

    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        if provider == "anthropic":
            if line.startswith("event: content_block_start"):
                next_raw = next(resp, None)
                if next_raw:
                    next_line = next_raw.decode("utf-8", errors="replace").strip()
                    if next_line.startswith("data: "):
                        try:
                            block = json.loads(next_line[6:])
                            block_type = block.get("content_block", {}).get("type", "")
                            if log_fh:
                                if block_type == "thinking" and not _wrote_reasoning_header:
                                    log_fh.write("===== 思考过程 =====\n")
                                    log_fh.flush()
                                    _wrote_reasoning_header = True
                                elif block_type == "text" and not _wrote_content_header:
                                    log_fh.write("\n===== 返回内容 =====\n")
                                    log_fh.flush()
                                    _wrote_content_header = True
                        except json.JSONDecodeError:
                            continue
            elif line.startswith("event: content_block_delta"):
                next_raw = next(resp, None)
                if next_raw:
                    next_line = next_raw.decode("utf-8", errors="replace").strip()
                    if next_line.startswith("data: "):
                        try:
                            delta_data = json.loads(next_line[6:])
                            delta = delta_data.get("delta", {})
                            delta_type = delta.get("type", "")
                            if delta_type == "thinking_delta":
                                thinking = delta.get("thinking", "")
                                if log_fh:
                                    if not _wrote_reasoning_header:
                                        log_fh.write("===== 思考过程 =====\n")
                                        _wrote_reasoning_header = True
                                    log_fh.write(thinking)
                                    log_fh.flush()
                            else:
                                text = delta.get("text", "")
                                full_text += text
                                if log_fh:
                                    if not _wrote_content_header:
                                        log_fh.write("\n===== 返回内容 =====\n")
                                        _wrote_content_header = True
                                    log_fh.write(text)
                                    log_fh.flush()
                        except json.JSONDecodeError:
                            continue
        else:
            if line.startswith("data: "):
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        reasoning = delta.get("reasoning_content") or ""
                        content = delta.get("content") or ""
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
                except json.JSONDecodeError:
                    continue

    if log_fh:
        log_fh.close()

    return full_text


# ========== Python SDK客户端 ==========

def call_llm_sdk(prompt, provider, api_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy=False, log_file=None):
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
        for attempt in range(max_retries):
            try:
                logger.info("LLM请求发送(Anthropic SDK), 尝试%d/%d", attempt + 1, max_retries)
                resp = client.messages.create(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}], temperature=0.3, timeout=timeout, stream=True)
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
                logger.debug("Anthropic SDK流式拼接完成, 总长度: %d", len(full_text))
                logger.info("LLM响应接收完成(Anthropic SDK), 长度%d", len(full_text))
                return full_text
            except APITimeoutError:
                logger.warning("LLM调用超时(%ds), 第%d次重试", int(timeout), attempt + 1)
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    raise
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(3)
                else:
                    raise
    else:
        from openai import OpenAI, APITimeoutError
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        if not verify_ssl or disable_proxy:
            import httpx
            kwargs["http_client"] = httpx.Client(verify=verify_ssl, trust_env=trust_env)
        client = OpenAI(**kwargs)
        for attempt in range(max_retries):
            try:
                logger.info("LLM请求发送(OpenAI SDK), 尝试%d/%d", attempt + 1, max_retries)
                stream = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=0.3, timeout=timeout, stream=True)
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
                logger.debug("OpenAI SDK流式拼接完成, 总长度: %d", len(full_text))
                logger.info("LLM响应接收完成(OpenAI SDK), 长度%d", len(full_text))
                return full_text
            except APITimeoutError:
                logger.warning("LLM调用超时(%ds), 第%d次重试", int(timeout), attempt + 1)
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    raise
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(3)
                else:
                    raise


_progress_lock = threading.Lock()
_progress_done = 0
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
                   runtime, provider, api_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, total):
    """处理一批问题，batch为[{num, desc}]列表"""
    global _progress_done, _output_dir

    results = []
    valid_items = [item for item in batch if item["desc"].strip()]

    start_num = batch[0]["num"]
    end_num = batch[-1]["num"]
    log_file = os.path.join(_output_dir, "log", f"llm_{start_num}_{end_num}.log") if _output_dir else None

    if not valid_items:
        for item in batch:
            save_item(item["num"], ["未知问题"], "空描述,跳过分类", app_name, problem_col, df, db_path, 2)
            results.append((item["num"], False))
        with _progress_lock:
            _progress_done += len(batch)
        return results

    try:
        prompt = build_batch_prompt(app_name, valid_items, refs)
        logger.debug("批量开始LLM推理, 有效问题数: %d", len(valid_items))

        for parse_attempt in range(max_retries):
            if runtime == "sdk":
                text = call_llm_sdk(prompt, provider, api_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, log_file=log_file)
            else:
                text = call_llm(prompt, provider, api_key, base_url, model, max_tokens, max_retries, timeout, log_file=log_file)

            logger.info("批量LLM推理返回, 文本长度: %d", len(text) if text else 0)

            parsed = extract_json(text)
            if not parsed or not isinstance(parsed, list):
                logger.warning("批量LLM推理返回JSON解析失败(第%d次), 原始返回: %s", parse_attempt + 1, text[:300] if text else "空")
                if parse_attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for item in valid_items:
                        save_item(item["num"], ["未知问题"], "JSON解析失败", app_name, problem_col, df, db_path, 2)
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
                logger.warning("批量LLM推理返回分类格式错误(第%d次)", parse_attempt + 1)
                if parse_attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                else:
                    for i, item in enumerate(valid_items):
                        num = item["num"]
                        p = parsed[i] if i < len(parsed) and isinstance(parsed[i], dict) else None
                        if p:
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
                        else:
                            save_item(num, ["未知问题"], "批量结果数量不足", app_name, problem_col, df, db_path, 2)
                            results.append((num, 2))
                            logger.warning("行%d 批量结果数量不足", num)
                    break

            for i, item in enumerate(valid_items):
                num = item["num"]
                p = parsed[i] if i < len(parsed) and isinstance(parsed[i], dict) else None
                if p:
                    cls = p.get("classification", ["未知问题"])
                    reason = p.get("reason", "")
                    if cls[0] == "未知问题":
                        save_item(num, cls, reason, app_name, problem_col, df, db_path, 1)
                        results.append((num, 1))
                    else:
                        save_item(num, cls, reason, app_name, problem_col, df, db_path, 0)
                        results.append((num, 0))
                    logger.info("行%d 批量推理成功, 分类: %s", num, ".".join(cls))
                else:
                    save_item(num, ["未知问题"], "批量结果数量不足", app_name, problem_col, df, db_path, 2)
                    results.append((num, 2))
                    logger.warning("行%d 批量结果数量不足", num)
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
        logger.debug("[%3d%%] 批量完成 %d条", pct, len(batch))

    return results


def main():
    _load_env()

    # 从环境变量读取LLM配置
    provider = os.environ.get("LLM_PROVIDER", "openai")
    runtime = os.environ.get("LLM_RUNTIME", "native")
    model = os.environ.get("LLM_MODEL")
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    max_concurrent = int(os.environ.get("LLM_MAX_CONCURRENT", "5"))
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "8192"))
    batch_size = int(os.environ.get("LLM_BATCH_SIZE", "1"))
    max_retries = int(os.environ.get("LLM_MAX_RETRIES", "3"))
    timeout = int(os.environ.get("LLM_TIMEOUT", "60"))
    verify_ssl = os.environ.get("LLM_VERIFY_SSL", "true").lower() in ("true", "1", "yes")
    disable_proxy = os.environ.get("LLM_DISABLE_PROXY", "false").lower() in ("true", "1", "yes")
    log_level = os.environ.get("LLM_LOG_LEVEL", "INFO").upper()
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
    max_id = conn.execute("SELECT MAX(id) FROM report").fetchone()[0]
    conn.close()
    if max_id is None:
        max_id = 0

    all_data = [{"num": i + 1, "desc": str(df.iloc[i][problem_col]) if not pd.isna(df.iloc[i][problem_col]) else ""}
                 for i in filtered if (i + 1) > max_id]

    logger.info("共 %d条, 已完成 %d条, 待处理 %d条, 并发 %d, 批量大小 %d, provider=%s, runtime=%s, model=%s",
                len(filtered), max_id, len(all_data), max_concurrent, batch_size, provider, runtime, model)

    global _output_dir
    _output_dir = output_dir

    total = len(all_data)
    success = 0
    unknown = 0
    failed = 0

    batches = [all_data[i:i + batch_size] for i in range(0, len(all_data), batch_size)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {executor.submit(process_batch, batch, app_name, problem_col, df, refs, db_path,
                                   runtime, provider, api_key, base_url, model, max_tokens, max_retries, timeout, verify_ssl, disable_proxy, total): i
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
    total_all = len(filtered)
    db_status = "验证通过" if cnt == total_all else f"警告: DB {cnt}条, 期望 {total_all}条"
    logger.info("分类完成: %d/%d条 (成功%d, 未知%d, 失败%d) | %s", success + unknown + failed, len(all_data), success, unknown, failed, db_status)
    print(f"分类完成: {success + unknown + failed}/{len(all_data)}条 (成功{success}, 未知{unknown}, 失败{failed}) | {db_status}")

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