"""邮箱消息类型（chap15 F32）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class MessageType(StrEnum):
    """消息类型（F32）。"""

    TEXT = "text"
    SHUTDOWN_REQUEST = "shutdown_request"
    SHUTDOWN_RESPONSE = "shutdown_response"
    PLAN_APPROVAL_RESPONSE = "plan_approval_response"


@dataclass
class Message:
    """邮箱消息（F32）。

    注意：JSON key 是 "from"，Python 属性是 from_（避免与关键字冲突）。
    """

    from_: str                              # json key: "from"
    to: str
    type: MessageType | str
    summary: str
    content: str
    payload: dict[str, Any] | None = None
    timestamp: int = 0
    read: bool = False

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容 dict。"""
        return {
            "from": self.from_,
            "to": self.to,
            "type": str(self.type),
            "summary": self.summary,
            "content": self.content,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "read": self.read,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Message:
        """从 dict 反序列化。"""
        type_raw = d.get("type", "text")
        try:
            msg_type = MessageType(type_raw)
        except ValueError:
            msg_type = type_raw  # type: ignore[assignment]

        return cls(
            from_=d.get("from", ""),
            to=d.get("to", ""),
            type=msg_type,
            summary=d.get("summary", ""),
            content=d.get("content", ""),
            payload=d.get("payload"),
            timestamp=d.get("timestamp", 0),
            read=bool(d.get("read", False)),
        )
