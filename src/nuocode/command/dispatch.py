"""输入解析：判断是否为 ``/`` 命令并提取 name。"""

from __future__ import annotations


def parse(input_text: str) -> tuple[str, bool]:
    """解析输入文本。

    返回 ``(name, is_slash)``：

    - 空白/空串/非 ``/`` 开头 → ``("", False)``
    - 单独 ``/`` 或 ``/<空白>`` → ``("", True)``
    - ``/<name>``（name 后无空白尾巴）→ ``(name.lower(), True)``
    - ``/<name> <args>``（带参数）→ ``("", True)``，让 lookup 必然 miss

    本期不支持参数；任何尾随非空字符都会让命令变成未命中走未知提示分支。
    """
    s = input_text.strip()
    if not s.startswith("/"):
        return ("", False)
    if s == "/":
        return ("", True)
    rest = s[1:]
    parts = rest.split(maxsplit=1)
    if len(parts) > 1:
        # 带参数
        return ("", True)
    name = parts[0]
    if not name:
        return ("", True)
    if name.startswith("/"):  # //double 等退化形式
        return ("", True)
    return (name.lower(), True)


__all__ = ["parse"]
