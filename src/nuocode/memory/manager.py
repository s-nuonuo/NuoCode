"""记忆管理器：合并两级索引、异步 LLM 更新。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from nuocode import llm
from nuocode.memory.prompts import MEMORY_UPDATE_SYSTEM_PROMPT
from nuocode.memory.store import Store
from nuocode.memory.types import UpdateAction

logger = logging.getLogger(__name__)

INDEX_MAX_BYTES = 25 * 1024
TRUNCATED_NOTICE = "\n\n(index truncated)\n"

_MEM_KEYWORDS_RE = re.compile(r"记住|记忆|别忘|remember|memo", re.IGNORECASE)


class Manager:
    def __init__(
        self,
        project_dir: str,
        user_dir: str,
        provider: llm.Provider | None = None,
        model: str = "",
    ) -> None:
        self._project_store = Store(project_dir)
        self._user_store = Store(user_dir)
        self._provider = provider
        self._model = model
        self._lock = asyncio.Lock()

    @property
    def project_store(self) -> Store:
        return self._project_store

    @property
    def user_store(self) -> Store:
        return self._user_store

    def set_provider(self, provider: llm.Provider, model: str = "") -> None:
        self._provider = provider
        if model:
            self._model = model

    def list_files(self) -> tuple[list[str], list[str]]:
        """列出项目层与用户层 memory 目录下的 ``.md`` 文件名（含 MEMORY.md），按字典序。

        目录不存在视为空 list；其他 ``OSError`` 记 warning 后视为空 list。
        """
        return self._scan(self._project_store.dir), self._scan(self._user_store.dir)

    @staticmethod
    def _scan(d: str) -> list[str]:
        import os as _os

        try:
            entries = _os.listdir(d)
        except FileNotFoundError:
            return []
        except OSError as e:
            logger.warning("list memory dir failed: %s (%s)", d, e)
            return []
        return sorted(n for n in entries if n.endswith(".md"))

    def load_index(self) -> str:
        """合并两级索引：项目级在前、用户级在后；超 25KB 截断。"""
        project = self._project_store.load_index()
        user = self._user_store.load_index()
        parts = []
        if project.strip():
            parts.append("# 项目记忆索引\n\n" + project.rstrip())
        if user.strip():
            parts.append("# 用户记忆索引\n\n" + user.rstrip())
        text = "\n\n".join(parts)
        encoded = text.encode("utf-8")
        if len(encoded) > INDEX_MAX_BYTES:
            keep = encoded[:INDEX_MAX_BYTES].decode("utf-8", errors="ignore")
            text = keep + TRUNCATED_NOTICE
        return text

    @staticmethod
    def has_memory_signal(recent_msgs: list[llm.Message]) -> bool:
        for m in recent_msgs:
            if m.role == llm.ROLE_USER and m.content and _MEM_KEYWORDS_RE.search(m.content):
                return True
        return False

    async def update_async(self, recent_msgs: list[llm.Message]) -> None:
        """异步执行一次记忆更新。失败静默。"""
        if self._provider is None:
            return
        async with self._lock:
            try:
                actions = await self._call_llm(recent_msgs)
            except Exception:  # noqa: BLE001
                logger.exception("记忆更新 LLM 调用失败")
                return
            try:
                self._dispatch(actions)
            except Exception:  # noqa: BLE001
                logger.exception("记忆更新写入失败")

    async def _call_llm(self, recent_msgs: list[llm.Message]) -> list[UpdateAction]:
        assert self._provider is not None
        index_text = self.load_index() or "(empty)"
        # 拼装最近对话的纯文本
        convo_lines: list[str] = []
        for m in recent_msgs:
            if m.role == llm.ROLE_USER:
                convo_lines.append(f"[user] {m.content}")
            elif m.role == llm.ROLE_ASSISTANT and m.content:
                convo_lines.append(f"[assistant] {m.content}")
        user_msg = (
            "现有索引：\n```\n" + index_text + "\n```\n\n"
            "最近一轮对话：\n```\n" + "\n".join(convo_lines) + "\n```\n\n"
            "请输出 JSON 数组。"
        )
        req = llm.Request(
            messages=[llm.Message(role=llm.ROLE_USER, content=user_msg)],
            tools=[],
            system=llm.System(stable=MEMORY_UPDATE_SYSTEM_PROMPT, environment=""),
            reminder="",
        )
        buf: list[str] = []
        async for ev in self._provider.stream(req):
            if ev.err is not None:
                raise ev.err
            if ev.text:
                buf.append(ev.text)
            if ev.done:
                break
        text = "".join(buf).strip()
        return _parse_actions(text)

    def _dispatch(self, actions: list[UpdateAction]) -> None:
        proj_actions = [a for a in actions if a.level == "project"]
        user_actions = [a for a in actions if a.level == "user"]
        if proj_actions:
            self._project_store.apply(proj_actions)
        if user_actions:
            self._user_store.apply(user_actions)


def _parse_actions(text: str) -> list[UpdateAction]:
    if not text:
        return []
    # 兼容模型偶尔包裹的代码块
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    try:
        data: Any = json.loads(s)
    except json.JSONDecodeError:
        logger.warning("记忆更新返回非合法 JSON: %r", s[:200])
        return []
    if not isinstance(data, list):
        return []
    out: list[UpdateAction] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                UpdateAction(
                    action=str(item.get("action", "")),
                    level=str(item.get("level", "")),
                    type=str(item.get("type", "")),
                    title=str(item.get("title", "")),
                    slug=str(item.get("slug", "")),
                    content=str(item.get("content", "")),
                    filename=str(item.get("filename", "")),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


__all__ = ["INDEX_MAX_BYTES", "Manager"]
