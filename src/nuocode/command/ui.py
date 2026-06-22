"""UI 抽象层：handler 通过该 Protocol 操作 TUI；不依赖 Textual。

`NuoCodeApp` 在 `nuocode.tui.app` 中按照接口要求实现这些属性/方法。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nuocode.permission import Mode


@runtime_checkable
class UI(Protocol):
    # 属性形态字段（与 NuoCodeApp 实例属性同名）
    mode: Mode
    usage_in: int
    usage_out: int

    # 输出
    def println(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...

    # 模式
    def set_mode(self, m: Mode) -> None: ...

    # 对话注入（KindPrompt 命令使用）
    def inject_and_send(self, display_label: str, preset_prompt: str) -> None: ...

    # 只读查询
    def model_name(self) -> str: ...
    def cwd(self) -> str: ...
    def tool_count(self) -> int: ...
    def memory_files(self) -> list[str]: ...
    def session_path(self) -> str: ...
    def session_id(self) -> str: ...

    # 影响界面动作
    def quit(self) -> None: ...
    def force_compact(self) -> None: ...
    def open_resume_menu(self) -> None: ...
    def clear_and_new_session(self) -> None: ...

    # 状态机查询
    def idle(self) -> bool: ...

    # chap11: skills
    def list_catalog_skills(self) -> list[tuple[str, str, str]]: ...
    def list_active_skills(self) -> list[str]: ...
    def clear_active_skills(self) -> None: ...
    def append_assistant_message(self, text: str) -> None: ...
    def recent_messages(self, n: int) -> list: ...
    def all_messages(self) -> list: ...


class NopUI:
    """测试桩：所有写入方法 no-op；查询返回零值。"""

    def __init__(self) -> None:
        self.mode: Mode = Mode.DEFAULT
        self.usage_in: int = 0
        self.usage_out: int = 0

    # 写入 no-op
    def println(self, msg: str) -> None:
        return None

    def error(self, msg: str) -> None:
        return None

    def set_mode(self, m: Mode) -> None:
        self.mode = m

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None:
        return None

    def quit(self) -> None:
        return None

    def force_compact(self) -> None:
        return None

    def open_resume_menu(self) -> None:
        return None

    def clear_and_new_session(self) -> None:
        return None

    # 查询零值
    def model_name(self) -> str:
        return ""

    def cwd(self) -> str:
        return ""

    def tool_count(self) -> int:
        return 0

    def memory_files(self) -> list[str]:
        return []

    def session_path(self) -> str:
        return ""

    def session_id(self) -> str:
        return ""

    def idle(self) -> bool:
        return True

    # chap11 skills no-op
    def list_catalog_skills(self) -> list[tuple[str, str, str]]:
        return []

    def list_active_skills(self) -> list[str]:
        return []

    def clear_active_skills(self) -> None:
        return None

    def append_assistant_message(self, text: str) -> None:
        return None

    def recent_messages(self, n: int) -> list:
        return []

    def all_messages(self) -> list:
        return []


__all__ = ["NopUI", "UI"]
