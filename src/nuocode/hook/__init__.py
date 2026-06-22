"""nuocode.hook 包：Hook 生命周期挂钩系统（chap12）。

公开接口：
  - ``Engine``          — 事件分派引擎
  - ``DispatchResult``  — dispatch 返回值
  - ``Event``           — 11 个生命周期事件枚举
  - ``load``            — 从 YAML 文件加载并返回 Engine
"""

from __future__ import annotations

from nuocode.hook.engine import DispatchResult, Engine
from nuocode.hook.event import Event
from nuocode.hook.loader import load

__all__ = ["DispatchResult", "Engine", "Event", "load"]
