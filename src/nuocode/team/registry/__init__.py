"""AgentNameRegistry：Agent name ↔ agent_id 双向映射（chap15 F35-F38）。

使用 threading.Lock 保护，支持跨线程调用。
后注册的覆盖前注册的（弱引用语义）。
"""

from __future__ import annotations

import threading


class AgentNameRegistry:
    """Agent 名称注册表（F35）。

    维护 name → agent_id 与 agent_id → name 的双向映射。
    后注册的覆盖前注册的（F38）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[str, str] = {}    # name → agent_id
        self._by_id: dict[str, str] = {}      # agent_id → name

    def register(self, name: str, agent_id: str) -> None:
        """注册 name → agent_id 映射（F36、F38）。

        若 name 已有旧 agent_id，先解除旧映射。
        若 agent_id 已有其他 name，先解除旧 name。
        后注册的覆盖前注册的。
        """
        with self._lock:
            # 清理旧 name 绑定的 agent_id
            old_agent_id = self._by_name.get(name)
            if old_agent_id is not None and old_agent_id != agent_id:
                self._by_id.pop(old_agent_id, None)

            # 清理旧 agent_id 绑定的 name
            old_name = self._by_id.get(agent_id)
            if old_name is not None and old_name != name:
                self._by_name.pop(old_name, None)

            self._by_name[name] = agent_id
            self._by_id[agent_id] = name

    def unregister(self, name: str) -> None:
        """注销 name 映射（F36）。"""
        with self._lock:
            agent_id = self._by_name.pop(name, None)
            if agent_id is not None:
                self._by_id.pop(agent_id, None)

    def unregister_by_agent_id(self, agent_id: str) -> None:
        """通过 agent_id 注销映射。"""
        with self._lock:
            name = self._by_id.pop(agent_id, None)
            if name is not None:
                self._by_name.pop(name, None)

    def resolve(self, name_or_id: str) -> str | None:
        """将 name 或 agent_id 解析为 agent_id（F36）。

        先按 name 查，若未找到再按 agent_id 反查。
        """
        with self._lock:
            # 先按 name 查
            result = self._by_name.get(name_or_id)
            if result is not None:
                return result
            # 再按 agent_id 直查（如果直接传了 agent_id）
            if name_or_id in self._by_id:
                return name_or_id
            return None

    def name_of(self, agent_id: str) -> str | None:
        """通过 agent_id 反查 name（F36）。"""
        with self._lock:
            return self._by_id.get(agent_id)

    def list_(self) -> dict[str, str]:
        """返回 name → agent_id 映射副本。"""
        with self._lock:
            return dict(self._by_name)
