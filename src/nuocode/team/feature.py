"""FORK_TEAMMATE feature flag（chap15 T15）。

控制是否允许 Fork 路径 spawn 队员（默认关闭）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nuocode.config import Config


def fork_teammate_enabled(cfg: Config) -> bool:
    """读取 FORK_TEAMMATE feature flag（T15）。

    从 cfg.features.fork_teammate 读取，默认 False。
    """
    features = getattr(cfg, "features", None)
    if features is None:
        return False
    return bool(getattr(features, "fork_teammate", False))
