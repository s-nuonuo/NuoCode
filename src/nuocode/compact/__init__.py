"""compact 子包入口：只导出窄接口给其他模块。

外部模块（agent/tui/cli）应通过本模块导入：
- manage_context / TriggerKind / ManageInput / ManageOutput：编排入口
- ContentReplacementState / RecoveryState / AutoCompactTrackingState / SessionContext：长生命周期状态
- new_session_context：会话目录工厂
- FileReadRecord：恢复段数据结构
"""

from __future__ import annotations

from nuocode.compact.compact import (
    ManageInput,
    ManageOutput,
    TriggerKind,
    manage_context,
)
from nuocode.compact.state import (
    AutoCompactTrackingState,
    ContentReplacementState,
    FileReadRecord,
    RecoveryState,
    SessionContext,
    new_session_context,
)

__all__ = [
    "AutoCompactTrackingState",
    "ContentReplacementState",
    "FileReadRecord",
    "ManageInput",
    "ManageOutput",
    "RecoveryState",
    "SessionContext",
    "TriggerKind",
    "manage_context",
    "new_session_context",
]
