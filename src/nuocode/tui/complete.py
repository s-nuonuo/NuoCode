"""自动补全菜单：状态机 + 渲染。

仅依赖 ``command.Registry``；激活逻辑由 ``NuoCodeApp`` 在 TextArea 输入变化时驱动。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nuocode.command import Command, Registry

MAX_ROWS = 8


@dataclass
class CompletionMenu:
    items: list[Command] = field(default_factory=list)
    cursor: int = 0
    offset: int = 0
    active: bool = False

    def update(self, input_text: str, reg: Registry) -> None:
        s = input_text.strip()
        if "\n" in input_text:
            self.hide()
            return
        if not s.startswith("/"):
            self.hide()
            return
        self.active = True
        self.items = reg.prefix_match(s)
        # 夹紧 cursor / offset
        if self.cursor >= len(self.items):
            self.cursor = max(0, len(self.items) - 1)
        if self.cursor < 0:
            self.cursor = 0
        self._fix_offset()

    def move_up(self) -> None:
        if not self.items:
            return
        self.cursor = (self.cursor - 1) % len(self.items)
        self._fix_offset()

    def move_down(self) -> None:
        if not self.items:
            return
        self.cursor = (self.cursor + 1) % len(self.items)
        self._fix_offset()

    def selected(self) -> Command | None:
        if not self.items:
            return None
        if 0 <= self.cursor < len(self.items):
            return self.items[self.cursor]
        return None

    def hide(self) -> None:
        self.items = []
        self.cursor = 0
        self.offset = 0
        self.active = False

    def _fix_offset(self) -> None:
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + MAX_ROWS:
            self.offset = self.cursor - MAX_ROWS + 1

    def render(self, width: int = 80) -> str:
        if not self.active:
            return ""
        if not self.items:
            return "(无匹配命令)"
        w = max(len(c.name) for c in self.items) + 1
        end = min(self.offset + MAX_ROWS, len(self.items))
        lines: list[str] = []
        if self.offset > 0:
            lines.append(f"  ↑ {self.offset} more")
        for i in range(self.offset, end):
            c = self.items[i]
            line = f"/{c.name.ljust(w - 1)}  {c.description}"
            if i == self.cursor:
                lines.append(f"> {line}")
            else:
                lines.append(f"  {line}")
        remain = len(self.items) - end
        if remain > 0:
            lines.append(f"  ↓ {remain} more")
        return "\n".join(lines)


__all__ = ["MAX_ROWS", "CompletionMenu"]
