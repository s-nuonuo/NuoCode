"""TUI 流式消费与计时辅助。

实际逻辑内联在 :mod:`nuocode.tui.app` 的 ``NuoCodeApp`` 中
(``_consume_stream`` / ``_tick`` / ``_finish_with_*``)，此模块保留导出以匹配文件清单。
"""

from __future__ import annotations

from nuocode.tui.app import NuoCodeApp

__all__ = ["NuoCodeApp"]
