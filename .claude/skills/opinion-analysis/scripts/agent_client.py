#!/usr/bin/env python3
"""agent_client.py - 推理后端抽象基类与工厂

把“调用大模型做单条分类”这一步抽象成一个统一接口，调用方（classify_agent 等）
只与本模块的 AgentClient 基类及 create_agent 工厂打交道，不感知任何具体后端。

具体后端实现为 AgentClient 的子类，各自放在独立模块中，约定：
  - 模块名 <backend>_agent_client
  - 暴露 create(cfg) -> AgentClient 工厂函数
create_agent 按 cfg['backend'] 动态 import 对应模块并调用其 create(cfg)，
本模块本身不出现任何具体后端的名字——后端选择完全由配置（cfg.backend）决定。

后端在调用 stream() 时逐块 yield 文本（与流式语义一致），由调用方边收边写日志、
拼接全文后 extract_json 解析；超时与日志写入由调用方负责。
"""

import importlib
import logging

logger = logging.getLogger("classify_data")


class AgentClient:
    """推理后端抽象基类。

    子类实现 stream()（异步生成器，逐块 yield 文本）。调用方通过 create_agent(cfg)
    拿到实例后只调用 stream()，不关心子类细节。cfg 为后端无关的配置字典，
    具体后端从中取自己需要的字段（不足的字段由子类自行从环境变量补齐）。
    """

    def __init__(self, cfg):
        self.cfg = cfg or {}

    async def stream(self, desc, *, correction=None, idle_timeout=None):
        """异步生成器：逐块 yield 推理文本。

        - desc：待分类的问题描述。
        - correction：上一次失败的原因上下文，带入本次调用让后端修正（可空）。
        - idle_timeout：空闲超时秒数；后端应在“idle_timeout 秒内无任何产出”时判卡死并
          抛 RuntimeError（持续产出/多轮往返期间不超时），由调用方按失败重试。
        子类必须实现本方法。
        """
        raise NotImplementedError

    async def aclose(self):
        """释放后端持有的资源（如长连接/子进程）。默认空实现，子类按需覆写。"""
        return


def create_agent(cfg):
    """按 cfg['backend'] 动态加载具体后端，返回 AgentClient 子类实例。

    约定后端模块名为 <backend>_agent_client 且暴露 create(cfg) 工厂。
    backend 缺省时抛错（默认后端由配置层 args.load_config 写入 cfg.backend）。
    本函数不出现具体后端名，仅按 cfg.backend 约定分派。
    """
    backend = (cfg or {}).get("backend")
    if not backend:
        raise RuntimeError("未配置推理后端（cfg.backend 为空），请在配置中指定后端")
    module_name = f"{backend}_agent_client"
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        # 区分“后端不存在”与“后端模块在但其依赖 SDK 未安装”
        if e.name == module_name:
            raise RuntimeError(f"未知的推理后端: {backend}（找不到模块 {module_name}）") from e
        raise RuntimeError(
            f"后端 {backend} 缺少依赖: {e.name}（请安装所选后端的 SDK）"
        ) from e
    factory = getattr(mod, "create", None)
    if not callable(factory):
        raise RuntimeError(f"后端 {backend} 未实现 create(cfg) 工厂函数")
    return factory(cfg)
