"""笔记类型与操作 dataclass。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class NoteType(StrEnum):
    USER_PREFERENCE = "user_preference"
    CORRECTION_FEEDBACK = "correction_feedback"
    PROJECT_KNOWLEDGE = "project_knowledge"
    REFERENCE_MATERIAL = "reference_material"


@dataclass
class Note:
    type: NoteType
    title: str
    slug: str
    content: str
    filename: str
    created: datetime
    updated: datetime


@dataclass
class UpdateAction:
    """LLM 返回的单条操作。"""

    action: str  # "create"/"update"/"delete"
    level: str  # "project"/"user"
    type: str = ""  # NoteType 字符串
    title: str = ""
    slug: str = ""
    content: str = ""
    filename: str = ""


__all__ = ["Note", "NoteType", "UpdateAction"]
