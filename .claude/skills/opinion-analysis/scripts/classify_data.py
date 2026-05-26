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
  LLM_RUNTIME       调用方式 (python/node)
  LLM_MODEL         模型名称
  LLM_API_KEY       API密钥
  LLM_BASE_URL      API基础URL
  LLM_MAX_CONCURRENT 最大并发数
  LLM_MAX_TOKENS    最大生成token
  LLM_BATCH_SIZE    每次LLM调用处理的问题数(默认1)
  LLM_MAX_RETRIES   最大重试次数
"""

import sys
import os
import io

# Windows下强制UTF-8输出
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
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
import subprocess
import uuid

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
    dest = os.path.join(output_dir, os.path.basename(excel_path))
    if not os.path.isfile(dest):
        shutil.copy2(excel_path, dest)
    cache_path = os.path.join(output_dir, "_excel_cache.pkl")
    if not os.path.isfile(cache_path):
        pd.read_excel(excel_path).to_pickle(cache_path)


def setup_logging(output_dir):
    log_path = os.path.join(output_dir, "report.log")
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
        f"[问题{i+1}] 编号:{item['num']}\n描述:{item['desc']}\n"
        for i, item in enumerate(items)
    ])
    return f"""你是一位专业的{app_name}应用性能问题分类专家，精通{app_name}的功能模块、页面结构和各类性能问题的表现特征。你需要根据用户反馈的问题描述，结合{app_name}的应用知识，逐层推导出最准确的分类。

当前需要分类的{len(items)}个{app_name}舆情问题描述如下：

---DATA---
{problems_text}
---DATA_END---

请根据以下参考资料推导分类：

【应用描述】
{refs.get('info', '')}

【问题分类树】
{refs.get('classification', '')}

【分类推理示例】
{refs.get('examples', '')}

逐层推导规则：
如果无法推导出一级分类，返回["未知问题"]；无法推导出二级分类，返回["一级分类值"]；无法推导出三级分类，返回["一级分类值", "二级分类值"]。
1. 分析问题描述，根据"应用描述"、"问题分类树"，结合"分类推理示例"，推理问题的一级分类
2. 分析问题描述，根据"应用描述"、"问题分类树"，结合第一步推理出的一级分类下的二级分类，推理问题的二级分类
3. 分析问题描述，根据"应用描述"、"问题分类树"，结合第二步推理出的二级分类下的三级分类，推理问题的三级分类

必须按照以下json格式返回，不要返回多余数据，json格式被三个反引号分割
```
[{{"num": 编号, "classification": ["一级分类", "二级分类", "三级分类"], "reason": "推理过程"}}]
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


# ========== Node.js服务进程管理 ==========

_node_service = None
_response_thread = None
_pending_responses = {}  # {request_id: {"event": threading.Event, "result": None, "error": None}}
_response_lock = threading.Lock()


def _response_reader():
    """后台线程：持续读取Node.js服务的响应，分发给等待的线程"""
    global _node_service, _pending_responses, _response_lock

    while _node_service and _node_service.poll() is None:
        try:
            line = _node_service.stdout.readline()
            if not line:
                break

            response = json.loads(line.strip())
            request_id = response.get("id")

            with _response_lock:
                if request_id in _pending_responses:
                    pending = _pending_responses[request_id]
                    if response.get("error"):
                        pending["error"] = response["error"]
                    else:
                        pending["result"] = response.get("result")
                    pending["event"].set()

        except json.JSONDecodeError:
            logger.warning("响应JSON解析失败: %s", line[:100] if line else "空")
        except Exception as e:
            logger.error("响应读取异常: %s", e)
            break


def start_node_service():
    """启动Node.js长运行服务进程和响应读取线程"""
    global _node_service, _response_thread

    js_script = os.path.join(SCRIPT_DIR, "js", "llm_service.js")
    _node_service = subprocess.Popen(
        ["node", js_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        bufsize=1  # 行缓冲
    )

    # 启动后台响应读取线程
    _response_thread = threading.Thread(target=_response_reader, daemon=True)
    _response_thread.start()

    logger.info("Node.js服务进程已启动, PID: %d, 响应读取线程已启动", _node_service.pid)
    return _node_service


def stop_node_service():
    """停止Node.js服务进程"""
    global _node_service, _response_thread

    if _node_service and _node_service.poll() is None:
        try:
            # 发送结束信号
            _node_service.stdin.write(json.dumps({"id": "end", "end": True}) + "\n")
            _node_service.stdin.flush()
            _node_service.wait(timeout=5)
        except Exception:
            _node_service.terminate()
            _node_service.wait(timeout=3)
        logger.info("Node.js服务进程已停止")


def call_node_service(prompt, model, max_tokens, request_id=None, timeout=120):
    """调用Node.js服务（真正并发）"""
    global _node_service, _pending_responses, _response_lock

    if request_id is None:
        request_id = str(uuid.uuid4())

    # 注册等待事件
    event = threading.Event()
    with _response_lock:
        _pending_responses[request_id] = {"event": event, "result": None, "error": None}

    request = {
        "id": request_id,
        "prompt": prompt,
        "model": model,
        "maxTokens": max_tokens
    }

    try:
        # 发送请求（无需锁，stdin写入是线程安全的）
        _node_service.stdin.write(json.dumps(request) + "\n")
        _node_service.stdin.flush()

        # 等待响应（每个线程独立等待自己的event）
        if not event.wait(timeout=timeout):
            raise Exception(f"等待响应超时({timeout}s)")

        # 获取结果
        with _response_lock:
            pending = _pending_responses.pop(request_id, {})

        if pending.get("error"):
            raise Exception(pending["error"])

        return pending.get("result")

    except Exception as e:
        # 清理
        with _response_lock:
            _pending_responses.pop(request_id, None)
        raise Exception(f"Node.js服务调用失败: {e}")


# ========== Python SDK客户端 ==========

def create_python_client(provider, api_key, base_url):
    if provider == "anthropic":
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)
    else:
        from openai import OpenAI
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)


def call_python_llm(client, provider, prompt, model, max_tokens, max_retries):
    from openai import APITimeoutError

    for attempt in range(max_retries):
        try:
            if provider == "anthropic":
                resp = client.messages.create(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}], temperature=0.3, timeout=90.0)
                # 过滤出文本块，跳过ThinkingBlock等其他类型
                text_block = next((b for b in resp.content if hasattr(b, 'text')), None)
                return text_block.text if text_block else ""
            else:
                resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=0.3, timeout=90.0)
                return resp.choices[0].message.content
        except APITimeoutError:
            logger.warning("LLM调用超时(90s), 第%d次重试", attempt + 1)
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
                  client, runtime, provider, model, max_tokens, max_retries, total):
    """处理一批问题，batch为[{num, desc}]列表"""
    global _progress_done

    results = []
    valid_items = [item for item in batch if item["desc"].strip()]

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

        # 根据runtime选择调用方式
        if runtime in ["node", "js"]:
            text = call_node_service(prompt, model, max_tokens)
        else:
            text = call_python_llm(client, provider, prompt, model, max_tokens, max_retries)

        logger.info("批量LLM推理返回, 文本长度: %d", len(text) if text else 0)

        parsed = extract_json(text)
        if parsed and isinstance(parsed, list):
            parsed_map = {int(p.get("num", 0)): p for p in parsed if isinstance(p, dict)}
            for item in valid_items:
                num = item["num"]
                p = parsed_map.get(num)
                if p:
                    cls = p.get("classification", ["未知问题"])
                    reason = p.get("reason", p.get("reasoning", ""))
                    if not isinstance(cls, list):
                        cls = ["未知问题"]
                        reason = "分类格式错误"
                        save_item(num, cls, reason, app_name, problem_col, df, db_path, 2)
                        results.append((num, 2))
                    elif cls[0] == "未知问题":
                        save_item(num, cls, reason, app_name, problem_col, df, db_path, 1)
                        results.append((num, 1))
                    else:
                        save_item(num, cls, reason, app_name, problem_col, df, db_path, 0)
                        results.append((num, 0))
                    logger.info("行%d 批量推理成功, 分类: %s", num, ".".join(cls))
                else:
                    save_item(num, ["未知问题"], "批量结果中未找到该编号", app_name, problem_col, df, db_path, 2)
                    results.append((num, 2))
                    logger.warning("行%d 批量结果中未找到", num)
        else:
            logger.warning("批量LLM推理返回JSON解析失败, 原始返回: %s", text[:300] if text else "空")
            for item in valid_items:
                save_item(item["num"], ["未知问题"], "JSON解析失败", app_name, problem_col, df, db_path, 2)
                results.append((item["num"], 2))

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
    provider = os.environ.get("LLM_PROVIDER", "openai")  # API格式: openai/anthropic
    runtime = os.environ.get("LLM_RUNTIME", "python")     # 调用方式: python/node
    model = os.environ.get("LLM_MODEL")
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    max_concurrent = int(os.environ.get("LLM_MAX_CONCURRENT", "5"))
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "8192"))
    batch_size = int(os.environ.get("LLM_BATCH_SIZE", "1"))
    max_retries = int(os.environ.get("LLM_MAX_RETRIES", "3"))

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

    all_data = [{"num": i + 1, "desc": str(df.iloc[i][problem_col]) if not pd.isna(df.iloc[i][problem_col]) else ""}
                 for i in filtered]

    db_path = os.path.join(output_dir, "report.db")
    init_db(db_path)

    logger.info("共 %d条, 并发 %d, 批量大小 %d, provider=%s, runtime=%s, model=%s", len(all_data), max_concurrent, batch_size, provider, runtime, model)

    # 初始化客户端
    client = None
    if runtime in ["node", "js"]:
        start_node_service()
    else:
        client = create_python_client(provider, api_key, base_url)

    total = len(all_data)
    success = 0
    unknown = 0
    failed = 0

    batches = [all_data[i:i + batch_size] for i in range(0, len(all_data), batch_size)]

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {executor.submit(process_batch, batch, app_name, problem_col, df, refs, db_path,
                                       client, runtime, provider, model, max_tokens, max_retries, total): i
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
    finally:
        # 停止Node.js服务
        if runtime in ["node", "js"]:
            stop_node_service()

    conn = sqlite3.connect(db_path)
    cnt = conn.execute("SELECT COUNT(*) FROM report").fetchone()[0]
    conn.close()
    db_status = "验证通过" if cnt == len(all_data) else f"警告: DB {cnt}条, 期望 {len(all_data)}条"
    logger.info("分类完成: %d/%d条 (成功%d, 未知%d, 失败%d) | %s", success + unknown + failed, len(all_data), success, unknown, failed, db_status)
    print(f"分类完成: {success + unknown + failed}/{len(all_data)}条 (成功{success}, 未知{unknown}, 失败{failed}) | {db_status}")


if __name__ == "__main__":
    main()