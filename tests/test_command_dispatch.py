"""parse 单测：表驱动样本。"""

from __future__ import annotations

import pytest

from nuocode.command import parse


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", ("", False)),
        ("   ", ("", False)),
        ("hello", ("", False)),
        ("/", ("", True)),
        ("/help", ("help", True)),
        ("  /HELP  ", ("help", True)),
        ("/help xx", ("", True)),
        ("/help   ", ("help", True)),
        ("//double", ("", True)),
        ("/ /help", ("", True)),
        ("/Status", ("status", True)),
    ],
)
def test_parse_table(text: str, expected: tuple[str, bool]) -> None:
    assert parse(text) == expected
