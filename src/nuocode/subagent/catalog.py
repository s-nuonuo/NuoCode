"""SubAgent Catalog：多来源加载与优先级覆盖（chap13）。

加载顺序（优先级从低到高）：
  1. 内置（随包）
  2. 用户级 ``~/.nuocode/agents/*.md``
  3. 项目级 ``<root>/.nuocode/agents/*.md``

同名定义按 source 优先级覆盖——项目级 > 用户级 > 内置级。

spec F5/F6/F7/F8。
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from nuocode.permission import Mode
from nuocode.subagent.definition import Definition, Source
from nuocode.subagent.embed import builtin_definitions
from nuocode.subagent.parser import parse_file


class Catalog:
    """Agent 定义 Catalog，线程安全（读多写少场景）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # name（原始大小写）-> 最高优先级 Definition
        self._defs: dict[str, Definition] = {}
        # 各来源的副本（供调试与 /agents 命令展示）
        self._by_source: dict[Source, list[Definition]] = {s: [] for s in Source}

    # ── 内部 ──

    def _add_all(self, defs: list[Definition]) -> None:
        """批量添加定义；同名时高优先级覆盖（调用顺序须为 builtin → user → project）。"""
        with self._lock:
            for d in defs:
                key = d.name.lower()
                existing = self._defs.get(key)
                if existing is None or d.source >= existing.source:
                    self._defs[key] = d
                self._by_source[d.source].append(d)

    # ── 公共查询 ──

    def resolve(self, name: str) -> Definition | None:
        """按 name（大小写不敏感）返回最高优先级 Definition，不存在返回 None。"""
        with self._lock:
            return self._defs.get(name.lower())

    def list(self) -> list[Definition]:
        """返回所有定义（每个 name 只保留最高优先级版本），按 name 升序。"""
        with self._lock:
            defs = list(self._defs.values())
        defs.sort(key=lambda d: d.name.lower())
        return defs

    def list_by_source(self, src: Source) -> list[Definition]:
        """返回指定来源的所有定义（原始，含被覆盖的旧版本），按 name 升序。"""
        with self._lock:
            result = list(self._by_source.get(src, []))
        result.sort(key=lambda d: d.name.lower())
        return result

    def fork_definition(self) -> Definition:
        """返回 Fork 路径用的临时 Definition（name='__fork__'）。

        Fork 子 Agent 工具集继承父，靠 QuerySource + Boilerplate 双闸拦截嵌套（spec F22）。
        """
        return Definition(
            name="__fork__",
            description="Fork-based subagent",
            model="inherit",
            max_turns=25,
            permission_mode=Mode.DEFAULT,
            source=Source.BUILTIN,
        )


def _load_from_dir(dir_path: Path, source: Source) -> list[Definition]:
    """从目录加载所有 *.md 文件；目录不存在时返回空列表；
    单文件解析失败 stderr 警告并跳过（spec F7）。
    """
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    defs: list[Definition] = []
    for md_path in sorted(dir_path.glob("*.md")):
        try:
            d = parse_file(str(md_path), source)
            defs.append(d)
        except Exception as e:  # noqa: BLE001
            print(
                f"[subagent] {md_path.name}: 解析失败，已跳过 ({e})",
                file=sys.stderr,
            )
    return defs


def load_catalog(root: str) -> Catalog:
    """按 builtin → user → project 顺序加载 Catalog，高优先级覆盖低优先级同名定义。

    - 内置：随包发布，解析失败 raise（代码 bug）
    - 用户/项目级：解析失败 stderr 警告并跳过（spec F7）
    """
    catalog = Catalog()

    # 1. 内置（失败即灾难）
    catalog._add_all(builtin_definitions())

    # 2. 用户级
    user_agents_dir = Path.home() / ".nuocode" / "agents"
    catalog._add_all(_load_from_dir(user_agents_dir, Source.USER))

    # 3. 项目级
    project_agents_dir = Path(root) / ".nuocode" / "agents"
    catalog._add_all(_load_from_dir(project_agents_dir, Source.PROJECT))

    return catalog
