#!/usr/bin/env python3
"""
classify_data.py - 使用LLM API自动分类舆情数据

用法:
  python classify_data.py \
    --app-name 抖音 \
    --app-index 2 \
    --problem-index 5 \
    --excel-path test/抖音卡顿舆情数据.xlsx \
    --output-dir output/抖音卡顿舆情数据

LLM API配置 (命令行参数或.env环境变量):
  --provider / LLM_PROVIDER    API类型: openai 或 anthropic (默认openai)
  --model / LLM_MODEL          模型名称
  --api-key / LLM_API_KEY      API密钥
  --base-url / LLM_BASE_URL    API基础URL (仅openai类型)
  --max-concurrent             最大并发调用数 (默认5)
  --max-tokens                 最大生成token数 (默认8192)
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
import concurrent.futures

import pandas as pd
from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))

_ENV_LOADED = False


def _load_env():
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    for env_path in [os.path.join(PROJECT_DIR, ".env"), os.path.join(PROJECT_DIR, ".env.local")]:
        if os.path.isfile(env_path):
            load_dotenv(env_path, override=False)
    _ENV_LOADED = True


sys.path.insert(0, SCRIPT_DIR)
from config import resolve_column, app_alias_map, SUPPORTED_APPS, get_app_dir
from save_results import init_db


def load_reference(app_name):
    app_dir = get_app_dir(SKILL_DIR, app_name)
    if not app_dir:
        return None
    refs = {}
    for fname, key in [("info.md", "info"), ("classification.md", "classification"), ("examples.md", "examples")]:
        fpath = os.path.join(app_dir, fname)
        if os.path.isfile(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                refs[key] = f.read()
        else:
            refs[key] = ""
    return refs


def build_prompt(app_name, desc, refs):
    parts = [
        f"你是一位专业的{app_name}应用性能问题分类专家，精通{app_name}的功能模块、页面结构和各类性能问题的表现特征。你需要根据用户反馈的问题描述，结合{app_name}的应用知识，逐层推导出最准确的分类。\n\n",
        f"当前需要分类的{app_name}舆情问题描述如下：\n\n---DATA---\n{desc}\n---DATA_END---\n",
        "请根据以下参考资料推导分类：\n",
        f"【应用描述】\n{refs.get('info', '')}\n",
        f"【问题分类树】\n{refs.get('classification', '')}\n",
        f"【分类推理示例】\n{refs.get('examples', '')}\n",
        "分类格式：一级分类.二级分类.三级分类\n\n逐层推导规则：\n1. 先从用户描述中提取关键词，推断一级分类\n2. 根据一级分类下的二级分类，结合场景关键词推断二级分类\n3. 根据二级分类下的三级分类，结合页面/功能推断三级分类\n",
        "输出JSON格式：\n{\"classification\": [\"一级分类\", \"二级分类\", \"三级分类\"], \"reason\": \"关键词→一级分类原因，场景→二级分类原因→三级分类原因\"}\n\n如果无法推导出一级分类，返回[\"未知问题\"]；无法推导出二级分类，返回[\"一级分类值\"]；无法推导出三级分类，返回[\"一级分类值\", \"二级分类值\"]；全部推理出，返回[\"一级分类值\", \"二级分类值\", \"三级分类值\"]。\n\nreason必须包含推导过程，不允许只写结论。\n请只返回JSON，不要添加其他文字。",
    ]
    return "\n".join(parts)


def extract_json_from_response(text):
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
    brace_match = re.search(r'\{[\s\S]*\}', text)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass
    return None


def call_llm_openai(prompt, model, api_key, base_url, max_tokens):
    from openai import OpenAI
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.3,
    )
    return response.choices[0].message.content


def call_llm_anthropic(prompt, model, api_key, max_tokens):
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.content[0].text


def call_llm(prompt, provider, model, api_key, base_url, max_tokens, max_retries):
    for attempt in range(max_retries):
        try:
            if provider == "anthropic":
                return call_llm_anthropic(prompt, model, api_key, max_tokens)
            else:
                return call_llm_openai(prompt, model, api_key, base_url, max_tokens)
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  API调用失败 (第{attempt+1}次): {e}, {wait}秒后重试...")
                time.sleep(wait)
            else:
                print(f"  API调用失败，已达最大重试次数: {e}")
                raise


def init_output_dir(excel_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    excel_basename = os.path.basename(excel_path)
    dest = os.path.join(output_dir, excel_basename)
    if not os.path.isfile(dest):
        shutil.copy2(excel_path, dest)
        print(f"已复制Excel文件到: {dest}")
    else:
        print(f"Excel文件已存在: {dest}")
    cache_path = os.path.join(output_dir, "_excel_cache.pkl")
    if not os.path.isfile(cache_path):
        df = pd.read_excel(excel_path)
        df.to_pickle(cache_path)
        print(f"已缓存Excel数据到: {cache_path}")
    print(f"输出目录已初始化: {output_dir}")


def save_item_to_db(num, classification, reason, app_name, problem_col, df, output_dir):
    db_path = os.path.join(output_dir, "report.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 30000")
    cursor = conn.cursor()
    row_idx = num - 1
    row = df.iloc[row_idx]
    problem = str(row[problem_col]) if not pd.isna(row[problem_col]) else ""
    raw_data = {col: str(row[col]) if not pd.isna(row[col]) else "" for col in df.columns}
    raw_data_json = json.dumps(raw_data, ensure_ascii=False)
    if classification[0] == "未知问题" or not classification:
        cursor.execute(
            "INSERT OR REPLACE INTO report (id, app, problem, status, reasoning, raw_data) VALUES (?, ?, ?, ?, ?, ?)",
            (num, app_name, problem, "unrecognized", reason, raw_data_json),
        )
    else:
        level1 = classification[0]
        level2 = classification[1] if len(classification) >= 2 else ""
        level3 = classification[2] if len(classification) >= 3 else ""
        full_path = ".".join([l for l in [level1, level2, level3] if l])
        cursor.execute(
            "INSERT OR REPLACE INTO report (id, app, problem, status, cls_app, level1, level2, level3, full_path, reasoning, raw_data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (num, app_name, problem, "success", app_name, level1, level2, level3, full_path, reason, raw_data_json),
        )
    conn.commit()
    conn.close()


def process_item(num, desc, app_name, problem_col, df, refs, output_dir,
                 provider, model, api_key, base_url, max_tokens, max_retries):
    prompt = build_prompt(app_name, desc, refs)
    cls = ["未知问题"]
    reason = "LLM调用失败"
    try:
        response_text = call_llm(prompt, provider, model, api_key, base_url, max_tokens, max_retries)
        parsed = extract_json_from_response(response_text)
        if parsed:
            cls = parsed.get("classification", ["未知问题"])
            reason = parsed.get("reason", parsed.get("reasoning", ""))
            if not isinstance(cls, list):
                cls = ["未知问题"]
                reason = "分类格式错误"
            if not reason:
                reason = "LLM未返回reason"
    except Exception as e:
        reason = f"API调用失败: {e}"
    save_item_to_db(num, cls, reason, app_name, problem_col, df, output_dir)
    is_failed = cls[0] == "未知问题" and ("LLM" in reason or "失败" in reason)
    return is_failed


def main():
    _load_env()

    parser = argparse.ArgumentParser(description="使用LLM API自动分类舆情数据")
    parser.add_argument("--app-name", required=True, help="应用名 (如 抖音、微信)")
    parser.add_argument("--app-index", type=int, required=True, help="应用名列号 (1-based, 0=无应用名列)")
    parser.add_argument("--problem-name", default=None, help="问题描述列名")
    parser.add_argument("--problem-index", type=int, required=True, help="问题描述列号 (1-based)")
    parser.add_argument("--excel-path", required=True, help="Excel文件路径")
    parser.add_argument("--output-dir", required=True, help="输出目录路径")

    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "openai"),
                        choices=["openai", "anthropic"], help="API类型")
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", None), help="模型名称")
    parser.add_argument("--api-key", default=os.environ.get("LLM_API_KEY", None), help="API密钥")
    parser.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", None), help="API基础URL (仅openai)")
    parser.add_argument("--max-concurrent", type=int, default=5, help="最大并发调用数")
    parser.add_argument("--max-tokens", type=int, default=8192, help="最大生成token数")
    parser.add_argument("--max-retries", type=int, default=3, help="最大重试次数")

    args = parser.parse_args()

    if not args.api_key:
        print("错误: 需要API密钥 (--api-key 或 LLM_API_KEY 环境变量)")
        sys.exit(1)
    if not args.model:
        print("错误: 需要模型名称 (--model 或 LLM_MODEL 环境变量)")
        sys.exit(1)

    app_name = args.app_name
    if app_name not in SUPPORTED_APPS:
        print(f"警告: '{app_name}' 不在支持列表 {SUPPORTED_APPS} 中，所有数据将归为'未知问题'")
        refs = {"info": "", "classification": "", "examples": ""}
    else:
        refs = load_reference(app_name)
        if not refs:
            print(f"错误: 无法加载 '{app_name}' 的知识库")
            sys.exit(1)

    excel_path = args.excel_path
    output_dir = args.output_dir
    init_output_dir(excel_path, output_dir)

    df = pd.read_excel(excel_path)
    columns = df.columns.tolist()

    problem_col = args.problem_name if args.problem_name else resolve_column(args.problem_index, columns)
    if problem_col not in columns:
        print(f"错误: 问题描述列 '{problem_col}' 不存在")
        sys.exit(1)

    if args.app_index > 0:
        app_col = resolve_column(args.app_index, columns)
        if app_col not in columns:
            print(f"错误: 应用名列 '{app_col}' 不存在")
            sys.exit(1)
        filtered_indices = []
        for idx, row in df.iterrows():
            val = str(row[app_col]).strip() if not pd.isna(row[app_col]) else ""
            resolved = app_alias_map.get(val, val)
            if resolved == app_name:
                filtered_indices.append(idx)
        total_rows = len(df)
        filtered_count = len(filtered_indices)
        print(f"总行数: {total_rows}, 筛选 '{app_name}' 行数: {filtered_count}")
        if filtered_count == 0:
            print(f"警告: 未找到 '{app_name}' 相关数据，将处理全部行")
            filtered_indices = list(range(len(df)))
    else:
        filtered_indices = list(range(len(df)))
        filtered_count = len(df)
        print(f"总行数: {filtered_count} (无应用名列筛选)")

    all_data = []
    for idx in filtered_indices:
        num = idx + 1
        desc = str(df.iloc[idx][problem_col]) if not pd.isna(df.iloc[idx][problem_col]) else ""
        all_data.append({"num": num, "desc": desc})

    db_path = os.path.join(output_dir, "report.db")
    init_db(db_path)

    print(f"共 {len(all_data)} 条数据, 每条单独调用LLM并直接写DB, 并发 {args.max_concurrent}")
    print(f"LLM配置: provider={args.provider}, model={args.model}")
    print()

    total_classified = 0
    failed_items = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_concurrent) as executor:
        future_to_num = {}
        for item in all_data:
            future = executor.submit(
                process_item,
                item["num"], item["desc"], app_name, problem_col, df, refs, output_dir,
                args.provider, args.model, args.api_key, args.base_url,
                args.max_tokens, args.max_retries,
            )
            future_to_num[future] = item["num"]

        for future in concurrent.futures.as_completed(future_to_num):
            num = future_to_num[future]
            try:
                is_failed = future.result()
                if is_failed:
                    failed_items += 1
                else:
                    total_classified += 1
            except Exception as e:
                print(f"  行{num}: 执行失败 {e}")
                failed_items += 1

    print()
    print(f"分类完成: {total_classified + failed_items}/{len(all_data)} 条 (成功 {total_classified}, 失败 {failed_items})")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM report")
    db_count = cursor.fetchone()[0]
    conn.close()
    if db_count == len(all_data):
        print(f"验证通过: 数据库 {db_count} 条")
    else:
        print(f"警告: 数据库 {db_count} 条, 期望 {len(all_data)} 条, 差 {len(all_data) - db_count} 条")


if __name__ == "__main__":
    main()