"""skills → prompt 桥接类型（避免反向依赖）。"""

from __future__ import annotations

from dataclasses import dataclass

from nuocode.skills.active import ActiveSkills


@dataclass(frozen=True)
class PromptItem:
    name: str
    description: str


@dataclass(frozen=True)
class PromptEntry:
    name: str
    body: str


def catalog_to_prompt_items(catalog) -> list[PromptItem]:  # noqa: ANN001
    return [PromptItem(name=s.meta.name, description=s.meta.description) for s in catalog.list()]


def active_to_prompt_entries(active: ActiveSkills) -> list[PromptEntry]:
    return [PromptEntry(name=e.name, body=e.body) for e in active.snapshot()]


__all__ = [
    "PromptEntry",
    "PromptItem",
    "active_to_prompt_entries",
    "catalog_to_prompt_items",
]
