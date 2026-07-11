#!/usr/bin/env python3
"""opencode_agent_client.py - opencode-ai 后端（AgentClient 子类）

通过 opencode-ai 库驱动一个 opencode 服务（headless），对单条问题描述流式返回文本
（含 {result, reason} JSON）。本模块仅在 cfg.backend == 'opencode' 时被
agent_client.create_agent 动态 import，故 opencode-ai 仅在选用本后端时才需要安装。

工作模型（经实测确认）：
  - opencode 服务以 HTTP 形式提供（opencode serve），SDK 是它的客户端。
  - POST /session 创建会话（id 由服务端生成）；服务端用“启动时的工作目录”作为会话
    工作目录，故本后端在未配置外部服务时，自行从 skill_dir 拉起一个 opencode 服务，
    使会话工作目录 == skill_dir（与 claude 后端 cwd=skill_dir 对齐）。
  - session.chat 阻塞至当轮推理完成；助手文本通过 /event 的 SSE 事件流增量推送
    （message.part.updated，part.type==text 的 text 字段累积），session.idle 表示完成。
  - 因 SDK 的 EventListResponse 联合类型在本 Python 版本下无法实例化、且 SDK 未暴露
    会话创建接口，故创建会话与消费 SSE 用 httpx 直连，chat 调用走 opencode-ai 库。

stream() 是异步生成器，逐块 yield 文本，由调用方消费：边收边写日志、拼接全文后 extract_json
解析；超时与日志写入由调用方负责。
"""

import asyncio
import atexit
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time

import httpx
import opencode_ai
from opencode_ai.types.session_chat_params import TextPartInputParam

from agent_client import AgentClient

logger = logging.getLogger("classify_data")


# ========== opencode 服务生命周期（进程内单例，按 skill_dir 拉起，退出时回收）==========

_server_lock = threading.Lock()
_server_state = {"proc": None, "base_url": None, "skill_dir": None, "log_path": None}


def _stop_server():
    proc = _server_state.get("proc")
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except Exception:
            pass


def _resolve_base_url(skill_dir):
    """返回 opencode 服务地址：优先外部 OPENCODE_BASE_URL；否则从 skill_dir 拉起一个。"""
    ext = os.environ.get("OPENCODE_BASE_URL")
    if ext:
        return ext.rstrip("/")
    with _server_lock:
        st = _server_state
        if st["base_url"] and st["proc"] and st["proc"].poll() is None:
            return st["base_url"]
        if not skill_dir:
            raise RuntimeError("opencode 后端需配置 skill_dir 或环境变量 OPENCODE_BASE_URL")
        log_path = os.path.join(tempfile.gettempdir(), "opencode_serve.log")
        try:
            fh = open(log_path, "w", encoding="utf-8")
        except Exception:
            fh = None
        proc = subprocess.Popen(
            ["opencode", "serve", "--port", "0", "--hostname", "127.0.0.1", "--log-level", "WARN"],
            cwd=skill_dir,
            stdout=fh if fh else subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        base = None
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                content = ""
            m = re.search(r"https?://[\w\.\-:]+", content)
            if m and "listening" in content.lower():
                base = m.group(0).rstrip("/")
                break
            time.sleep(0.2)
        if not base:
            try:
                proc.terminate()
            except Exception:
                pass
            raise RuntimeError("opencode 服务启动失败（未监听端口），请确认已安装 opencode CLI")
        st.update(proc=proc, base_url=base, skill_dir=skill_dir, log_path=log_path)
        atexit.register(_stop_server)
        logger.info("已拉起 opencode 服务: %s (cwd=%s)", base, skill_dir)
        return base


# ========== skill 文本加载（system 注入 + 参考文件目录提示）==========

_SKILL_CACHE = {}


def _load_skill(skill_dir, skill_name):
    key = (skill_dir, skill_name)
    if key in _SKILL_CACHE:
        return _SKILL_CACHE[key]
    base = os.path.join(skill_dir or "", ".claude", "skills", skill_name or "")
    md_path = os.path.join(base, "SKILL.md")
    content = ""
    if md_path and os.path.isfile(md_path):
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
    _SKILL_CACHE[key] = (content, base)
    return content, base


def _build_messages(cfg, desc, correction):
    """构建 (system, user)：把 skill 的 SKILL.md 作为 system 注入，并指明参考文件目录。"""
    skill_md, skill_base = _load_skill(cfg.get("skill_dir"), cfg.get("skill_name"))
    system = None
    if skill_md:
        system = skill_md
        refs_dir = os.path.join(skill_base, "references") if skill_base else ""
        if refs_dir and os.path.isdir(refs_dir):
            system += (
                "\n\n# 参考文件\n分类体系中提到的 .md 文件均位于目录：" + refs_dir
                + "，需要时请用该目录下的绝对路径读取后再行推导。"
            )
    user = (
        "请严格按上述分类体系与输出约定逐层推导，对以下抖音用户问题描述进行分类，"
        "最终返回规定的 JSON 对象（用三个反引号包裹），不要附加任何其它内容。\n\n"
        "问题描述：\n" + (desc or "")
    )
    if correction:
        user += "\n\n===== 上次返回有误，请按以下修正要求重新返回 =====\n" + correction
    return system, user


class OpencodeAgentClient(AgentClient):
    """opencode-ai 后端实现。"""

    def __init__(self, cfg):
        super().__init__(cfg)
        self.skill_dir = cfg.get("skill_dir")
        self.skill_name = cfg.get("skill_name")
        self.mode = cfg.get("mode") or os.environ.get("LLM_AGENT_MODE") or "ask"
        self.provider_id = cfg.get("provider_id") or os.environ.get("LLM_AGENT_PROVIDER")
        # model_id 优先取后端专用变量，回退到通用 LLM_MODEL
        self.model_id = cfg.get("model_id") or os.environ.get("LLM_AGENT_MODEL_ID") or cfg.get("model")
        if not self.provider_id:
            raise RuntimeError("opencode 后端需配置 LLM_AGENT_PROVIDER（opencode 配置中的 provider id）")
        if not self.model_id:
            raise RuntimeError("opencode 后端需配置 LLM_AGENT_MODEL_ID 或 LLM_MODEL（opencode 配置中的 model id）")

    async def stream(self, desc, *, correction=None, idle_timeout=None):
        """异步生成器：逐块 yield 助手文本（SSE 增量），完成后兜底取完整文本。

        - idle_timeout：对 SSE 每行读取套 asyncio.wait_for；idle_timeout 秒内无任何事件才判卡死，
          抛 RuntimeError（持续产出/多轮往返期间不超时），由调用方按失败重试。
        - session.error / chat 返回 error → 抛 RuntimeError。
        - 若 SSE 全程未拿到文本（如流式异常），用 GET /session/{id}/message 兜底取助手文本。
        """
        base_url = _resolve_base_url(self.skill_dir)
        system, user_text = _build_messages(self.cfg, desc, correction)

        hc = httpx.AsyncClient(base_url=base_url, timeout=None)
        sdk = opencode_ai.AsyncOpencode(base_url=base_url)
        chat_task = None
        streamed_any = False
        try:
            sid = await self._create_session(hc)
            chat_task = asyncio.create_task(self._chat(sdk, sid, system, user_text))

            async with hc.stream("GET", "/event") as resp:
                it = resp.aiter_lines()
                assistant_mid = None
                last_text = ""
                while True:
                    try:
                        if idle_timeout:
                            line = await asyncio.wait_for(it.__anext__(), idle_timeout)
                        else:
                            line = await it.__anext__()
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        raise RuntimeError("agent 空闲超时(%ds 无消息)" % idle_timeout)

                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    try:
                        ev = json.loads(data)
                    except Exception:
                        continue
                    # /event 是服务端全局事件流（非按会话隔离），只处理本会话的事件
                    props = ev.get("properties") or {}
                    if props.get("sessionID") and props.get("sessionID") != sid:
                        continue
                    t = ev.get("type")
                    if t == "message.updated":
                        info = props.get("info") or {}
                        if info.get("role") == "assistant" and not assistant_mid:
                            assistant_mid = info.get("id")
                    elif t == "message.part.updated":
                        part = props.get("part") or {}
                        if part.get("type") == "text" and assistant_mid and part.get("messageID") == assistant_mid:
                            txt = part.get("text", "")
                            if txt and txt != last_text:
                                delta = txt[len(last_text):] if txt.startswith(last_text) else txt
                                last_text = txt
                                streamed_any = True
                                yield delta
                    elif t == "session.idle":
                        break
                    elif t == "session.error":
                        err = props.get("error") or props
                        raise RuntimeError("后端返回错误: %s" % json.dumps(err, ensure_ascii=False)[:300])

            # 等待 chat 返回（idle 后通常已就绪），取其 error
            if chat_task and not chat_task.done():
                try:
                    msg = await asyncio.wait_for(chat_task, timeout=idle_timeout or 30)
                except asyncio.TimeoutError:
                    raise RuntimeError("agent 调用超时未返回")
            else:
                msg = chat_task.result() if chat_task and chat_task.done() else None
            if msg is not None and getattr(msg, "error", None):
                err = getattr(msg, "error", None)
                try:
                    detail = err.model_dump_json()
                except Exception:
                    detail = str(err)
                raise RuntimeError("后端返回错误: %s" % (detail or "未知错误")[:300])

            # 兜底：SSE 未拿到文本时，取会话消息中的助手文本
            if not streamed_any:
                text = await self._fetch_assistant_text(hc, sid)
                if text:
                    yield text
        finally:
            if chat_task and not chat_task.done():
                chat_task.cancel()
                try:
                    await chat_task
                except Exception:
                    pass
            try:
                await hc.aclose()
            except Exception:
                pass
            try:
                await sdk.close()
            except Exception:
                pass

    async def _create_session(self, hc):
        r = await hc.post("/session", json={"title": "classify", "providerID": self.provider_id, "modelID": self.model_id})
        r.raise_for_status()
        return r.json()["id"]

    async def _chat(self, sdk, sid, system, user_text):
        kwargs = dict(
            id=sid,
            model_id=self.model_id,
            provider_id=self.provider_id,
            parts=[TextPartInputParam(type="text", text=user_text)],
            mode=self.mode,
        )
        if system:
            kwargs["system"] = system
        return await sdk.session.chat(**kwargs)

    async def _fetch_assistant_text(self, hc, sid):
        r = await hc.get(f"/session/{sid}/message")
        r.raise_for_status()
        data = r.json()
        msgs = data if isinstance(data, list) else (data.get("messages") or data.get("data") or [])
        for mm in reversed(msgs):
            role = mm.get("role") or (mm.get("info") or {}).get("role")
            if role != "assistant":
                continue
            parts = mm.get("parts") or (mm.get("info") or {}).get("parts") or []
            for p in parts:
                if p.get("type") == "text":
                    t = p.get("text") or ""
                    if t:
                        return t
        return ""


def create(cfg):
    """工厂：供 agent_client.create_agent 按 backend=='opencode' 动态调用。"""
    return OpencodeAgentClient(cfg)
