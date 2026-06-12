"""内置 system prompt 与启动 banner。"""

from __future__ import annotations

SYSTEM_PROMPT: str = """\
You are nuocode, a helpful AI assistant running inside a terminal chat client.
- Be concise, accurate and friendly.
- Use markdown formatting (code blocks, lists, emphasis) when it improves readability.
- The user is on a terminal; avoid extremely long single lines.
- If you are unsure, say so instead of guessing.
"""

CAT_BANNER: str = r"""
 /\_/\
( o.o )
 > ^ <
""".lstrip("\n")


def render_banner(version: str, cwd: str) -> str:
    """启动横幅：ASCII 猫 + 应用名版本 + cwd + 就绪提示行。"""
    lines = [
        CAT_BANNER.rstrip(),
        "",
        f"  nuocode v{version}",
        f"  cwd: {cwd}",
        "",
        "  Ready. Type your message and press Enter to send. (Alt+Enter for newline, /exit to quit)",
    ]
    return "\n".join(lines)
