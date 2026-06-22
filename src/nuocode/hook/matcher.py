"""hook.matcher: 对 payload 字段路径求值 + eval_condition（chap12）。

复用 permission.Matcher，不重复实现四种类型。
"""

from __future__ import annotations

import json
from typing import Any

from nuocode.hook.rule import CombineMode, Condition, Payload


def get_by_path(payload: Payload, path: str) -> str:
    """按 ``.`` 分隔路径从 payload 中取值，返回 str。

    - 中途遇到 None 或非 dict → 返回空串
    - bool/int/float → str(value)
    - 嵌套 dict/list → json.dumps(value, sort_keys=True)
    """
    if not path:
        return ""
    parts = path.split(".")
    cur: Any = payload
    for part in parts:
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(part)
        if cur is None:
            return ""
    if isinstance(cur, bool):
        return str(cur)
    if isinstance(cur, (int, float)):
        return str(cur)
    if isinstance(cur, str):
        return cur
    # 复杂对象
    try:
        return json.dumps(cur, sort_keys=True)
    except (TypeError, ValueError):
        return str(cur)


def eval_condition(cond: Condition | None, payload: Payload) -> bool:
    """对条件表达式求值。

    - ``cond is None`` → True（无条件触发）
    - ALL_OF：所有原子条件都满足
    - ANY_OF：至少一个原子条件满足
    """
    if cond is None:
        return True
    results = [atom.matcher.match(get_by_path(payload, atom.field)) for atom in cond.atoms]
    if cond.mode is CombineMode.ALL_OF:
        return all(results)
    # ANY_OF
    return any(results)


__all__ = ["eval_condition", "get_by_path"]
