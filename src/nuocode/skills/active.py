"""ActiveSkills：跨轮已激活 Skill 列表。"""

from __future__ import annotations

import threading

from nuocode.skills.types import ActiveEntry


class ActiveSkills:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[ActiveEntry] = []
        self._index: dict[str, int] = {}

    def activate(self, name: str, body: str) -> None:
        with self._lock:
            idx = self._index.get(name)
            if idx is None:
                self._index[name] = len(self._entries)
                self._entries.append(ActiveEntry(name=name, body=body))
            else:
                self._entries[idx] = ActiveEntry(name=name, body=body)

    def clear(self) -> None:
        with self._lock:
            self._entries = []
            self._index = {}

    def snapshot(self) -> list[ActiveEntry]:
        with self._lock:
            return [ActiveEntry(name=e.name, body=e.body) for e in self._entries]

    def names(self) -> list[str]:
        with self._lock:
            return [e.name for e in self._entries]


__all__ = ["ActiveSkills"]
