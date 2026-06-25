"""nuocode.subagent — SubAgent 角色定义、Catalog 多来源加载（chap13）。

对外暴露：
- ``Definition`` / ``Source``
- ``Catalog`` / ``load_catalog``
"""

from __future__ import annotations

from nuocode.subagent.catalog import Catalog, load_catalog
from nuocode.subagent.definition import Definition, Source

__all__ = [
    "Catalog",
    "Definition",
    "Source",
    "load_catalog",
]
