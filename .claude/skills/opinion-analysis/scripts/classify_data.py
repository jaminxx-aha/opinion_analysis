#!/usr/bin/env python3
"""
classify_data.py - 使用LLM API自动分类舆情数据

一条命令完成: 初始化输出目录 → 分类 → 验证

用法:
  python classify_data.py \
    --app-name 抖音 --app-index 2 --problem-index 5 \
    --excel-path test/douyin_100.xlsx \
    --output-dir output/douyin_100

LLM配置从项目根目录.env自动加载, 也可命令行参数覆盖:
  --provider / LLM_PROVIDER    openai 或 anthropic (默认openai)
  --model / LLM_MODEL          模型名称
  --api-key / LLM_API_KEY      API密钥
  --base-url / LLM_BASE_URL    API基础URL (仅openai)
  --max-concurrent             最大并发数 (默认5)
  --max-tokens                 最大生成token (默认8192)
  --max-retries                最大重试次数 (默认3)
"""

import sys
import os
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


def build_prompt(app_name, desc, refs):
    return "\n".join([
        f"你是一位专业的{app_name}应用性能问题分类专家，精通{app_name}的功能模块、页面结构和各类性能问题的表现特征。你需要根据用户反馈的问题描述，结合{app_name}的应用知识，逐层推导出最准确的分类。\n\n",
        f"当前需要分类的{app_name}舆情问题描述如下：\n\n---DATA---\n{desc}\n---DATA_END---\n",
        "请根据以下参考资料推导分类：\n",
        f"【应用描述】\n{refs.get('info', '')}\n",
        f"【问题分类树】\n{refs.get('classification', '')}\n",
        f"【分类推理示例】\n{refs.get('examples', '')}\n",
        "分类格式：一级分类.二级分类.三级分类\n\n逐层推导规则：\n1. 分析问题描述，根据\"应用描述\"、\"问题分类树\"，结合\"分类推理示例\"，推理问题的一级分类\n2. 分析问题描述，根据\"应用描述\"、\"问题分类树\"，结合第一步推理出的一级分类下的二级分类，推理问题的二级分类\n3. 分析问题描述，根据\"应用描述\"、\"问题分类树\"，结合第二步推理出的二级分类下的三级分类，推理问题的三级分类\n",
        "输出JSON格式：\n{\"classification\": [\"一级分类\", \"二级分类\", \"三级分类\"], \"reason\": \"推理过程\"}\n\n如果无法推导出一级分类，返回[\"未知问题\"]；无法推导出二级分类，返回[\"一级分类值\"]；无法推导出三级分类，返回[\"一级分类值\", \"二级分类值\"]；全部推理出，返回[\"一级分类值\", \"二级分类值\", \"三级分类值\"]。\n\nreason必须包含推导过程，不允许只写结论。\n请只返回JSON，不要添加其他文字。",
    ])


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
    brace = re.search(r'\{[\s\S]*\}', text)
    if brace:
        try:
            return json.loads(brace.group())
        except json.JSONDecodeError:
            pass
    return None


def create_client(provider, api_key, base_url):
    if provider == "anthropic":
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)
    else:
        from openai import OpenAI
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)


def call_llm(client, provider, prompt, model, max_tokens, max_retries):
    for attempt in range(max_retries):
        try:
            if provider == "anthropic":
                resp = client.messages.create(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}], temperature=0.3)
                return resp.content[0].text
            else:
                resp = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=0.3)
                return resp.choices[0].message.content
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


_progress_lock = threading.Lock()
_progress_done = 0


def save_item(num, classification, reason, app_name, problem_col, df, db_path, infer_ok):
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA busy_timeout = 30000")
        cursor = conn.cursor()
        row = df.iloc[num - 1]
        problem = str(row[problem_col]) if not pd.isna(row[problem_col]) else ""
        raw_json = json.dumps({c: str(row[c]) if not pd.isna(row[c]) else "" for c in df.columns}, ensure_ascii=False)
        status_val = 1 if infer_ok else 0
        if infer_ok and classification and classification[0] != "未知问题":
            l1 = classification[0]
            l2 = classification[1] if len(classification) >= 2 else ""
            l3 = classification[2] if len(classification) >= 3 else ""
            fp = ".".join(filter(None, [l1, l2, l3]))
            cursor.execute("INSERT OR REPLACE INTO report (id,app,problem,status,cls_app,level1,level2,level3,full_path,reasoning,raw_data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (num, app_name, problem, status_val, app_name, l1, l2, l3, fp, reason, raw_json))
        elif infer_ok:
            cursor.execute("INSERT OR REPLACE INTO report (id,app,problem,status,cls_app,level1,level2,level3,full_path,reasoning,raw_data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (num, app_name, problem, status_val, app_name, "未知问题", "", "", "未知问题", reason, raw_json))
        else:
            cursor.execute("INSERT OR REPLACE INTO report (id,app,problem,status,reasoning,raw_data) VALUES (?,?,?,?,?,?)",
                           (num, app_name, problem, status_val, reason, raw_json))
        conn.commit()
        conn.close()
        logger.info("行%d 入库成功, 分类: %s, 推理状态: %s", num, ".".join(classification) if classification else "无", "成功" if infer_ok else "失败")
    except Exception as e:
        logger.error("行%d 入库失败: %s", num, e)


def process_item(num, desc, app_name, problem_col, df, refs, db_path,
                 client, provider, model, max_tokens, max_retries, total):
    global _progress_done
    cls = ["未知问题"]
    reason = "空描述,跳过分类"
    infer_ok = False
    if desc.strip():
        reason = "LLM调用失败"
        try:
            prompt = build_prompt(app_name, desc, refs)
            logger.debug("行%d 开始LLM推理, 描述长度: %d", num, len(desc))
            text = call_llm(client, provider, prompt, model, max_tokens, max_retries)
            logger.debug("行%d LLM推理成功, 返回文本长度: %d", num, len(text) if text else 0)
            parsed = extract_json(text)
            if parsed:
                cls = parsed.get("classification", ["未知问题"])
                reason = parsed.get("reason", parsed.get("reasoning", ""))
                if not isinstance(cls, list):
                    cls = ["未知问题"]
                    reason = "分类格式错误"
                    logger.warning("行%d LLM推理返回分类格式错误, 原始返回: %s", num, text[:200])
                else:
                    infer_ok = True
                if not reason:
                    reason = "LLM未返回reason"
                logger.info("行%d LLM推理分类结果: %s", num, ".".join(cls) if cls else "无")
            else:
                logger.warning("行%d LLM推理返回JSON解析失败, 原始返回: %s", num, text[:200])
                reason = "JSON解析失败"
        except Exception as e:
            reason = f"API调用失败: {e}"
            logger.error("行%d LLM推理失败: %s", num, e)
    else:
        logger.warning("行%d 空描述,跳过分类", num)
    save_item(num, cls, reason, app_name, problem_col, df, db_path, infer_ok)
    with _progress_lock:
        _progress_done += 1
        pct = _progress_done * 100 // total
        logger.debug("[%3d%%] 行%d: %s -> %s", pct, num, cls[0], reason[:60])
    return infer_ok


def main():
    _load_env()
    parser = argparse.ArgumentParser(description="使用LLM API自动分类舆情数据")
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--app-index", type=int, required=True)
    parser.add_argument("--problem-name", default=None)
    parser.add_argument("--problem-index", type=int, required=True)
    parser.add_argument("--excel-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "openai"), choices=["openai", "anthropic"])
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL"))
    parser.add_argument("--api-key", default=os.environ.get("LLM_API_KEY"))
    parser.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL"))
    parser.add_argument("--max-concurrent", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    if not args.api_key:
        logger.error("需要 --api-key 或 LLM_API_KEY 环境变量"); sys.exit(1)
    if not args.model:
        logger.error("需要 --model 或 LLM_MODEL 环境变量"); sys.exit(1)

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

    logger.info("共 %d条, 并发 %d, provider=%s, model=%s", len(all_data), args.max_concurrent, args.provider, args.model)

    client = create_client(args.provider, args.api_key, args.base_url)
    total = len(all_data)
    ok = 0
    fail = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_concurrent) as executor:
        futures = {executor.submit(process_item, d["num"], d["desc"], app_name, problem_col, df, refs, db_path,
                                   client, args.provider, args.model, args.max_tokens, args.max_retries, total): d["num"]
                   for d in all_data}
        for f in concurrent.futures.as_completed(futures):
            try:
                if f.result():
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1

    conn = sqlite3.connect(db_path)
    cnt = conn.execute("SELECT COUNT(*) FROM report").fetchone()[0]
    conn.close()
    status = "验证通过" if cnt == len(all_data) else f"警告: DB {cnt}条, 期望 {len(all_data)}条"
    logger.info("分类完成: %d/%d条 (推理成功%d, 推理失败%d) | %s", ok + fail, len(all_data), ok, fail, status)
    print(f"分类完成: {ok + fail}/{len(all_data)}条 (推理成功{ok}, 推理失败{fail}) | {status}")


if __name__ == "__main__":
    main()