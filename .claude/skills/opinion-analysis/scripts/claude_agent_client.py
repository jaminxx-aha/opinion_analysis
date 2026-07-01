#!/usr/bin/env python3
"""claude_agent_client.py - Claude Agent SDK 流式封装（抖音舆情 skill 调用）

把"调用大模型"这一步从 openai/anthropic 直调改为跑一个 headless Claude Code
agent，让 agent 加载用户已实现的「抖音舆情分析」skill，对单条问题描述流式返回
文本（含 {result, reason} JSON）。

call_agent_sdk 是异步生成器，逐块 yield agent 的文本产出（与 SDK 的 query() 流式
语义一致），由调用方消费：边收边写日志、拼接全文后 extract_json 解析。
超时与日志写入由调用方负责（asyncio.wait_for 包裹消费协程 + 边收边写）。
"""

import logging

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
)

logger = logging.getLogger("classify_data")


def _build_prompt(skill_name, desc):
    return (
        f"请使用「{skill_name}」skill 对以下抖音用户问题描述进行分类，"
        "严格按 skill 自身的分类体系与输出约定逐层推导，"
        "最终返回该 skill 规定的 JSON 对象（用三个反引号包裹），不要附加任何其它内容。\n\n"
        f"问题描述：\n{desc}"
    )


async def call_agent_sdk(desc, *, skill_dir, skill_name, model, api_key, base_url, max_turns):
    """异步生成器：流式 yield agent 的文本块（与 SDK 的 query() 一致，按轮次产出）。

    - 遇 AssistantMessage 的 TextBlock 即逐块 yield 其 text。
    - 遇 ResultMessage 终止：若 is_error 抛 RuntimeError（由调用方捕获重试）；
      若此前未产出任何文本，用 result 兜底 yield 一次。
    - 不在此处理超时/日志，交由调用方（asyncio.wait_for 包裹 + 边收边写）。
    """
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
        disallowed_tools=["Bash", "WebFetch", "WebSearch"],
    )
    if model:
        opts_kwargs["model"] = model
    if max_turns:
        opts_kwargs["max_turns"] = max_turns
    if env:
        opts_kwargs["env"] = env
    options = ClaudeAgentOptions(**opts_kwargs)

    gen = query(prompt=prompt, options=options)
    yielded_any = False
    try:
        async for msg in gen:
            if isinstance(msg, AssistantMessage):
                for block in (getattr(msg, "content", None) or []):
                    if getattr(block, "type", None) == "text":
                        t = getattr(block, "text", "")
                        if t:
                            yielded_any = True
                            yield t
            elif isinstance(msg, ResultMessage):
                if getattr(msg, "is_error", False):
                    errs = getattr(msg, "errors", None) or []
                    raise RuntimeError("agent 返回错误: %s" % ("; ".join(errs) if errs else "未知错误"))
                # 未流式产出过文本时，用 result 兜底
                if not yielded_any:
                    r = getattr(msg, "result", None) or ""
                    if r:
                        yield r
                return
    finally:
        # 显式关闭 query 生成器，避免 asyncio 在 loop 收尾时报
        # "an error occurred during closing of asynchronous generator"（超时/异常退出时常见）。
        # aclose 自身的异常一律吞掉（属清理噪音，不影响已产出/已抛出的结果）。
        try:
            await gen.aclose()
        except Exception:
            pass
