"""ApprovalUpgrader 类型定义（chap13）。

子 Agent 把审批请求升级到父 TUI 的回调接口。

``ApprovalUpgrader`` 是一个异步可调用类型：
- 入参：``ApprovalRequest``（来自 ``nuocode.agent``）
- 返回：``(outcome, ok)``
  - ``ok=True``：outcome 已确定，调用方按 outcome 执行
  - ``ok=False``：升级失败或未处理，调用方走默认的 emit Approval event 路径
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from nuocode.permission import Outcome

# ApprovalUpgrader 接受任意请求对象（ApprovalRequest 来自 nuocode.agent，
# 此处用 Any 避免循环导入）
ApprovalUpgrader = Callable[
    [Any],
    Awaitable[tuple[Outcome, bool]],
]

__all__ = ["ApprovalUpgrader"]
