#!/usr/bin/env python3
"""claude_agent_client.py - Claude Agent SDK 封装（抖音舆情 skill 调用）

把"调用大模型"这一步从 openai/anthropic 直调改为跑一个 headless Claude Code
agent，让 agent 加载用户已实现的「抖音舆情分析」skill，对单条问题描述返回
{"classification": "编码", "reason": "推理过程"} JSON。

与 classify_data.call_llm_sdk 同形契约：入参问题文本，出参文本（供 extract_json 解析）。
SDK 在函数内懒导入，未安装 claude_agent_sdk 时不会影响 classify_data 模块加载。
"""

import os
import asyncio
import logging

logger = logging.getLogger("classify_data")


def _build_prompt(skill_name, desc):
    return (
        f"请使用「{skill_name}」skill 对以下抖音用户问题描述进行分类，"
        "严格按 skill 的分类树逐层推导，最终只返回一个 JSON 对象，"
        "格式为 {\"classification\": \"编码\", \"reason\": \"推理过程\"}，"
        "用三个反引号包裹，不要附加任何其它内容。\n\n"
        f"问题描述：\n{desc}"
    )


def call_agent_sdk(desc, *, skill_dir, skill_name, model, api_key, base_url,
                   max_turns, timeout, log_file=None):
    """调用 Claude Agent SDK 跑 skill，返回 agent 的最终文本（含 JSON）。

    失败抛异常，由调用方（classify_agent.process_item_agent）捕获并重试。
    """
    from claude_agent_sdk import (
        query,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
    )

    prompt = _build_prompt(skill_name, desc)

    env = {}
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url

    # 只传有值的可选字段；env/model/max_turns 为空时一律不传（传 None 会让 SDK 在
    # 拼接子进程 env 时报 'NoneType' object is not a mapping）
    opts_kwargs = dict(
        cwd=skill_dir,
        skills=[skill_name],
        setting_sources=["project", "user"],
        permission_mode="bypassPermissions",
        # 只让 skill 做推理，禁掉有副作用的工具，保证 headless 安全/确定性
        disallowed_tools=["Bash", "WebFetch", "WebSearch"],
    )
    if model:
        opts_kwargs["model"] = model
    if max_turns:
        opts_kwargs["max_turns"] = max_turns
    if env:
        opts_kwargs["env"] = env
    options = ClaudeAgentOptions(**opts_kwargs)

    async def _run():
        text_parts = []
        result_msg = None
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in (getattr(msg, "content", None) or []):
                    if getattr(block, "type", None) == "text":
                        text_parts.append(getattr(block, "text", ""))
            elif isinstance(msg, ResultMessage):
                result_msg = msg
                break
        # ResultMessage.result 优先（agent 的最终结果文本）；为空则回退到拼接的 assistant 文本
        final = ""
        if result_msg is not None:
            if getattr(result_msg, "is_error", False):
                errs = getattr(result_msg, "errors", None) or []
                raise RuntimeError("agent 返回错误: %s" % ("; ".join(errs) if errs else "未知错误"))
            final = getattr(result_msg, "result", None) or ""
        if not final:
            final = "".join(text_parts)
        return final

    try:
        text = asyncio.run(asyncio.wait_for(_run(), timeout=timeout)) if timeout else asyncio.run(_run())
    except asyncio.TimeoutError:
        raise RuntimeError("agent 调用超时(%ds)" % timeout)

    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, "w", encoding="utf-8") as fh:
                fh.write("===== Agent 返回内容 =====\n")
                fh.write(text or "")
        except Exception as e:
            logger.warning("写 agent 日志失败 %s: %s", log_file, e)

    logger.info("Agent 响应接收完成(skill=%s, model=%s, 长度%d)", skill_name, model or "default", len(text or ""))
    return text or ""
