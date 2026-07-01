#!/usr/bin/env python3
"""args.py - Phase 1：参数解析、环境变量加载、配置构建、参考知识库加载

classify_data.main 仅在此完成"读入参数 + 算出本次运行的 Config + 加载参考库"，
之后把 Config 交给 processor 执行。本模块不依赖 processor/db_utils，处于依赖底层。
"""

import sys
import os
import io
import re
import argparse
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from dotenv import load_dotenv
from app_list import get_supported_apps, get_app_dir

# Windows下强制UTF-8输出（与原 classify_data 顶部一致）
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'buffer') and (not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if hasattr(sys.stderr, 'buffer') and (not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != 'utf-8'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

logger = logging.getLogger("classify_data")
logger.setLevel(logging.INFO)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SKILL_DIR)))

# 描述长度上限（字符数，clean_desc 清洗后）：超过则跳过分类、直接入库 status=3
MAX_DESC_LENGTH = 500

_ENV_LOADED = False


def _load_env():
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    for p in [os.path.join(PROJECT_DIR, ".env"), os.path.join(PROJECT_DIR, ".env.local")]:
        if os.path.isfile(p):
            load_dotenv(p, override=False)
    _ENV_LOADED = True


def setup_logging(output_dir):
    log_dir = os.path.join(output_dir, "log")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "report.log")
    handler = logging.FileHandler(log_path, encoding="utf-8", mode="a")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.info("日志初始化完成, 日志文件: %s", log_path)


def parse_args():
    """命令行参数解析。"""
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
                        help="重试模式: failed=重试失败数据, unknown=重试未知问题数据")
    return parser.parse_args()


def resolve_columns(args, df):
    """根据 --problem-name/--problem-index/--version-index 解析出列名，校验存在性。
    返回 (problem_col, version_col)。"""
    columns = df.columns.tolist()
    problem_col = args.problem_name or columns[args.problem_index]
    if problem_col not in columns:
        logger.error("问题描述列 '%s' 不存在", problem_col); sys.exit(1)
    version_col = None
    if args.version_index >= 0:
        version_col = columns[args.version_index]
        if version_col not in columns:
            logger.error("版本号列 '%s' 不存在", version_col); sys.exit(1)
    if version_col:
        logger.info("版本号列: '%s'", version_col)
    else:
        logger.info("无版本号列, version 字段为空")
    return problem_col, version_col


@dataclass
class Config:
    """本次运行的完整配置（Phase 1 产出，Phase 2/3 消费）。"""
    is_agent: bool
    reason_mode: str
    provider: str
    model: Optional[str]
    api_keys: List[str]
    base_url: Optional[str]
    max_concurrent: int
    total_concurrent: int
    max_tokens: int
    batch_size: int
    max_retries: int
    timeout: int
    temperature: float
    verify_ssl: bool
    disable_proxy: bool
    agent_cfg: Optional[dict] = None


def load_config(args):
    """读环境变量、判定 provider/reason_mode、构建 agent_cfg、校验，返回 Config。"""
    _load_env()

    provider = os.environ.get("LLM_PROVIDER", "openai")
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

    # Claude Agent SDK provider: 走 headless agent 加载抖音舆情 skill，单条问题→单个JSON，
    # skill 一次性返回完整编码，故 batch/layered 两种 reason mode 在此退化为每条一次 agent 调用。
    is_agent = (provider == "claude-agent-sdk")
    agent_cfg = None
    if is_agent:
        reason_mode = "agent"
        agent_skill_dir = os.environ.get("LLM_AGENT_SKILL_DIR", "").strip()
        agent_skill_name = os.environ.get("LLM_AGENT_SKILL_NAME", "douyin-performance-problem-classifier").strip()
        # model / api_key / base_url 复用 LLM_*（与 openai 路径同一套，不再单独 LLM_AGENT_*）
        model = os.environ.get("LLM_MODEL") or None
        # 多 key 支持：逗号分隔 → 列表，按 task 轮询分配给 worker（与 openai 路径一致）
        api_key_raw = os.environ.get("LLM_API_KEY", "").strip()
        api_keys = [k.strip() for k in api_key_raw.split(",") if k.strip()] if api_key_raw else []
        base_url = os.environ.get("LLM_BASE_URL", "").strip() or None
        agent_max_turns = int(os.environ.get("LLM_AGENT_MAX_TURNS", "10"))
        # agent 需多轮读 skill 的 reference 文件做逐层分类，30s 默认不够，单独给更长超时
        agent_timeout = int(os.environ.get("LLM_AGENT_TIMEOUT", "120"))
        if not agent_skill_dir:
            logger.error("LLM_PROVIDER=claude-agent-sdk 需要配置 LLM_AGENT_SKILL_DIR (含 .claude/skills/<skill>/SKILL.md 的项目根目录)"); sys.exit(1)
        skill_md = os.path.join(agent_skill_dir, ".claude", "skills", agent_skill_name, "SKILL.md")
        if not os.path.isfile(skill_md):
            logger.error("未找到 skill: %s (期望 %s)。请确认 LLM_AGENT_SKILL_DIR / LLM_AGENT_SKILL_NAME", agent_skill_name, skill_md); sys.exit(1)
        # agent 支持多 key 轮询；未配 API key 时回退到 claude CLI 自身的 OAuth 登录
        total_concurrent = (len(api_keys) * max_concurrent) if api_keys else max_concurrent
        agent_cfg = {
            "skill_dir": agent_skill_dir,
            "skill_name": agent_skill_name,
            "model": model,
            "api_key": api_keys[0] if api_keys else None,
            "base_url": base_url,
            "max_turns": agent_max_turns,
            "timeout": agent_timeout,
            "max_retries": max_retries,
        }
        logger.info("推理模式: Claude Agent SDK (skill=%s, model=%s, skill_dir=%s, 并发%d)",
                    agent_skill_name, model or "default", agent_skill_dir, total_concurrent)
    else:
        # 推理模式: batch=批量一次性推导(受 LLM_BATCH_SIZE 控制); layered=逐层串行推导(LLM_BATCH_SIZE 不生效)
        reason_mode = os.environ.get("LLM_REASON_MODE", "batch").lower()
        if reason_mode not in ("batch", "layered"):
            logger.warning("未知 LLM_REASON_MODE=%s, 回退为 batch", reason_mode)
            reason_mode = "batch"
        if reason_mode == "layered":
            logger.info("推理模式: 逐层推导(layered), LLM_BATCH_SIZE 不生效, 每条问题按一级→二级→三级串行推导")
        else:
            logger.info("推理模式: 批量推导(batch), 批量大小 %d", batch_size)

        model = os.environ.get("LLM_MODEL")
        api_key_raw = os.environ.get("LLM_API_KEY")
        if not api_key_raw:
            logger.error("需要 LLM_API_KEY 环境变量"); sys.exit(1)
        api_keys = [k.strip() for k in api_key_raw.split(",") if k.strip()]
        if not api_keys:
            logger.error("需要 LLM_API_KEY 环境变量 (解析后无有效key)"); sys.exit(1)
        base_url = os.environ.get("LLM_BASE_URL")
        total_concurrent = len(api_keys) * max_concurrent
        if not model:
            logger.error("需要 LLM_MODEL 环境变量"); sys.exit(1)

    # app_name 合法性校验
    if args.app_name not in get_supported_apps():
        supported = ", ".join(get_supported_apps())
        print(f"错误: 应用 '{args.app_name}' 不在支持列表中，当前支持的应用: {supported}")
        sys.exit(1)

    return Config(
        is_agent=is_agent,
        reason_mode=reason_mode,
        provider=provider,
        model=model,
        api_keys=api_keys,
        base_url=base_url,
        max_concurrent=max_concurrent,
        total_concurrent=total_concurrent,
        max_tokens=max_tokens,
        batch_size=batch_size,
        max_retries=max_retries,
        timeout=timeout,
        temperature=temperature,
        verify_ssl=verify_ssl,
        disable_proxy=disable_proxy,
        agent_cfg=agent_cfg,
    )


# ========== 参考知识库加载 ==========

def parse_classification_md(md_content):
    """解析编号大纲格式的classification.md，生成编码→路径字典。

    Returns:
        dict: 编码字符串到名称路径列表的映射，
        如 {"0": ["未知问题"], "1": ["卡顿"], "1.1": ["卡顿","滑动卡顿"], "1.1.1": ["卡顿","滑动卡顿","首页推荐视频流上下滑动卡顿"]}
    """
    code_to_path = {"0": ["未知问题"]}

    lines = md_content.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 二级/三级: "1.1 滑动卡顿" 或 "1.1.1 首页推荐视频流上下滑动卡顿"
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

    # 功能域兜底：当无法确定性能问题属于「动效卡顿 / 响应慢·加载慢 / 启动慢」中哪一类时，
    # 归类为「卡顿」。该一级类不在 classification_function.md 中展示，此处按最大一级编码 +1 追加。
    if any(path == ["动效卡顿"] for path in code_to_path.values()):
        max_l1 = max((int(k) for k in code_to_path if re.match(r'^\d+$', k)), default=0)
        code_to_path[str(max_l1 + 1)] = ["卡顿"]

    return code_to_path


def code_to_classification(code, code_to_path):
    """将分类编码转换为名称路径列表，用于存库。

    Args:
        code: 分类编码字符串，如 "1.1.1" 或 "0"
        code_to_path: 编码→路径字典

    Returns:
        名称路径列表，如 ["卡顿", "滑动卡顿", "首页推荐视频流上下滑动卡顿"]
        编码"0"返回["未知问题"]
    """
    if not code or code == "0":
        return ["未知问题"]
    # 容错: 若LLM返回"1.1 滑动卡顿"格式，提取编码部分
    code_match = re.match(r'^(\d+(?:\.\d+)*)', str(code).strip())
    if code_match:
        code = code_match.group(1)
    return code_to_path.get(code, ["未知问题"])


def validate_classification(classification, code_to_path):
    """校验分类路径是否存在于编码→路径字典中

    Args:
        classification: 分类名称列表, 如 ["卡顿", "滑动卡顿", "首页推荐视频流上下滑动卡顿"]
        code_to_path: 编码→路径字典 (来自 parse_classification_md)

    Returns:
        True if path is valid (or classification is ["未知问题"])
        False if any path doesn't match any registered code path
    """
    # 特殊情况: "未知问题"是Prompt规则允许的, 不在字典中但直接放行
    if not classification or classification[0] == "未知问题":
        return True

    # 检查名称路径是否与字典中某个编码对应的路径完全匹配
    valid_paths = set(tuple(v) for v in code_to_path.values())
    return tuple(classification) in valid_paths


# 各域对应的知识库文件名（除共享的 info.md 外）。
# function/business 域分别使用 *_function.md / *_business.md。
DOMAIN_FILES = {
    "function": {
        "info": "info.md",
        "examples": "examples_function.md",
        "error_examples": "error_examples_function.md",
        "classification": "classification_function.md",
        "examples_layered": "examples_layered_function.md",
        "error_examples_layered": "error_examples_layered_function.md",
    },
    "business": {
        "info": "info.md",
        "examples": "examples_business.md",
        "error_examples": "error_examples_business.md",
        "classification": "classification_business.md",
        "examples_layered": "examples_layered_business.md",
        "error_examples_layered": "error_examples_layered_business.md",
    },
}


def load_reference(app_name, domain="function"):
    app_dir = get_app_dir(app_name)
    if not app_dir:
        return None
    files = DOMAIN_FILES.get(domain, DOMAIN_FILES["function"])
    refs = {}
    # info.md 与 examples_*.md / error_examples_*.md 保持 markdown 原文
    # 批量模式用 examples/error_examples；逐层模式用 examples_layered/error_examples_layered
    for key in ("info", "examples", "error_examples", "examples_layered", "error_examples_layered"):
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
        refs["classification_tree"] = {"0": ["未知问题"]}
        refs["classification"] = ""

    return refs
