"""单级记忆存储：笔记 .md 文件与 MEMORY.md 索引的 CRUD。"""

from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from nuocode.memory.types import UpdateAction

logger = logging.getLogger(__name__)

INDEX_FILENAME = "MEMORY.md"


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _frontmatter(type_: str, title: str, created: str, updated: str) -> str:
    # 手写以避免引入额外依赖；title 转义双引号
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'---\ntype: {type_}\ntitle: "{safe_title}"\ncreated: {created}\nupdated: {updated}\n---\n'
    )


def _read_frontmatter_created(path: str) -> str:
    """从已有笔记 frontmatter 解析 created 字段。"""
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(2048)
    except OSError:
        return _now_iso()
    m = re.search(r"^created:\s*(.+)$", head, flags=re.MULTILINE)
    if m:
        return m.group(1).strip()
    return _now_iso()


def _index_line(action: UpdateAction) -> str:
    short = (action.content or "").splitlines()[0] if action.content else ""
    short = short.strip()
    if len(short) > 80:
        short = short[:79] + "…"
    return f"- [{action.type}] {action.title} — {short}".rstrip()


class Store:
    """单级（项目级或用户级）笔记目录管理器。"""

    def __init__(self, dir: str) -> None:
        self._dir = dir
        self._lock = threading.Lock()

    @property
    def dir(self) -> str:
        return self._dir

    @property
    def index_path(self) -> str:
        return os.path.join(self._dir, INDEX_FILENAME)

    def ensure_dir(self) -> None:
        os.makedirs(self._dir, exist_ok=True)

    def load_index(self) -> str:
        try:
            with open(self.index_path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""
        except OSError as e:
            logger.warning("读取索引失败: %s (%s)", self.index_path, e)
            return ""

    # ── 操作 ──

    def apply(self, actions: list[UpdateAction]) -> None:
        with self._lock:
            self.ensure_dir()
            for a in actions:
                try:
                    if a.action == "create":
                        self._do_create(a)
                    elif a.action == "update":
                        self._do_update(a)
                    elif a.action == "delete":
                        self._do_delete(a)
                    else:
                        logger.warning("未知 memory action: %s", a.action)
                except OSError as e:
                    logger.warning("memory %s 失败: %s (%s)", a.action, a, e)

    def _do_create(self, a: UpdateAction) -> None:
        slug = a.slug or _slugify(a.title)
        filename = a.filename or f"{a.type}_{slug}.md"
        path = os.path.join(self._dir, filename)
        now = _now_iso()
        body = _frontmatter(a.type, a.title, now, now) + "\n" + a.content + "\n"
        Path(path).write_text(body, encoding="utf-8")
        # 索引追加
        a.filename = filename
        self._append_index_line(a)

    def _do_update(self, a: UpdateAction) -> None:
        if not a.filename:
            logger.warning("update 缺 filename: %s", a)
            return
        path = os.path.join(self._dir, a.filename)
        created = _read_frontmatter_created(path)
        now = _now_iso()
        body = _frontmatter(a.type, a.title, created, now) + "\n" + a.content + "\n"
        Path(path).write_text(body, encoding="utf-8")
        self._update_index_line(a)

    def _do_delete(self, a: UpdateAction) -> None:
        if not a.filename:
            return
        path = os.path.join(self._dir, a.filename)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        self._remove_index_line(a.filename)

    # ── 索引 line 维护 ──

    def _append_index_line(self, a: UpdateAction) -> None:
        line = _index_line(a)
        existing = self.load_index()
        if existing and not existing.endswith("\n"):
            existing += "\n"
        Path(self.index_path).write_text(existing + line + "\n", encoding="utf-8")

    def _update_index_line(self, a: UpdateAction) -> None:
        existing = self.load_index().splitlines()
        new_line = _index_line(a)
        # 索引行没记录 filename，按 type+title 匹配；找不到就追加
        prefix = f"- [{a.type}] {a.title}"
        replaced = False
        for i, line in enumerate(existing):
            if line.startswith(prefix):
                existing[i] = new_line
                replaced = True
                break
        if not replaced:
            existing.append(new_line)
        Path(self.index_path).write_text("\n".join(existing) + "\n", encoding="utf-8")

    def _remove_index_line(self, filename: str) -> None:
        # filename 带 type 前缀，可以反向解析
        m = re.match(r"^([a-z_]+)_(.+)\.md$", filename)
        if m is None:
            return
        type_ = m.group(1)
        existing = self.load_index().splitlines()
        # 我们没法从 filename 反推 title；保守：删除所有以 [type] 开头且 slug 与 filename 对应的行
        slug_part = m.group(2)
        kept = []
        for line in existing:
            if line.startswith(f"- [{type_}]") and _slugify(_extract_title(line)) == slug_part:
                continue
            kept.append(line)
        body = "\n".join(kept)
        if body and not body.endswith("\n"):
            body += "\n"
        Path(self.index_path).write_text(body, encoding="utf-8")


def _extract_title(line: str) -> str:
    """从 ``- [type] Title — desc`` 中提取 Title。"""
    m = re.match(r"^- \[[a-z_]+\] (.+?)(?: — .*)?$", line)
    if m is None:
        return ""
    return m.group(1).strip()


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "note"


__all__ = ["INDEX_FILENAME", "Store"]
