"""后端检测函数（chap15 F14）。

按优先级一次性决定使用哪种后端：
1. $TMUX 环境变量 → tmux
2. $TERM_PROGRAM==iTerm.app && shutil.which("it2") → iterm2
3. shutil.which("tmux") → tmux
4. 否则 → in-process
"""

from __future__ import annotations

import os
import shutil

from nuocode.team.types import BackendType


def detect() -> BackendType:
    """检测当前环境可用的后端类型（F14）。

    一次性决定，不做运行时回退。
    """
    # 优先级 1：在 tmux 会话内
    if os.environ.get("TMUX"):
        return BackendType.TMUX

    # 优先级 2：iTerm2 环境且 it2 命令可用
    if os.environ.get("TERM_PROGRAM") == "iTerm.app" and shutil.which("it2"):
        return BackendType.ITERM2

    # 优先级 3：tmux 二进制可用（外部 spawn 新 session）
    if shutil.which("tmux"):
        return BackendType.TMUX

    # 默认：in-process
    return BackendType.IN_PROCESS
