"""permission 模块单测：黑名单 / 沙箱 / 规则 / 配置 / 引擎 / 持久化。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nuocode.llm import ToolCall
from nuocode.permission import (
    Category,
    Decision,
    Mode,
    Outcome,
    SettingsError,
    new_engine,
    parse_mode,
)
from nuocode.permission.blacklist import hits_blacklist
from nuocode.permission.engine import mode_fallback
from nuocode.permission.rule import RuleSet, match_pattern, parse_rule
from nuocode.permission.sandbox import sandbox_ok
from nuocode.permission.settings import (
    categorize,
    extract_target,
    friendly_name,
    load_settings,
    to_rule_set,
)

# ───────── T1 类型 ─────────


def test_mode_str() -> None:
    assert str(Mode.DEFAULT) == "default"
    assert str(Mode.ACCEPT_EDITS) == "acceptEdits"
    assert str(Mode.PLAN) == "plan"
    assert str(Mode.BYPASS) == "bypassPermissions"


def test_parse_mode() -> None:
    assert parse_mode("default") == (Mode.DEFAULT, True)
    assert parse_mode("ACCEPTEDITS") == (Mode.ACCEPT_EDITS, True)
    assert parse_mode("plan") == (Mode.PLAN, True)
    assert parse_mode("bypassPermissions") == (Mode.BYPASS, True)
    assert parse_mode("bypass") == (Mode.BYPASS, True)
    assert parse_mode("x")[1] is False


def test_outcome_values() -> None:
    assert Outcome.DENY_ONCE.value == 0
    assert Outcome.ALLOW_ONCE.value == 1
    assert Outcome.ALLOW_FOREVER.value == 2


# ───────── T2 黑名单 ─────────


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /",
        "rm -fr ~",
        "rm -rf $HOME",
        "rm -rf /*",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
        "mkfs.ext4 /dev/sda1",
        "echo bad > /dev/sda",
        "chmod -R 777 /",
    ],
)
def test_blacklist_hits(cmd: str) -> None:
    assert hits_blacklist(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf ./build",
        "rm file.txt",
        "git status",
        "ls -la",
        "echo hi",
    ],
)
def test_blacklist_misses(cmd: str) -> None:
    assert not hits_blacklist(cmd)


# ───────── T3 沙箱 ─────────


def test_sandbox_inside_outside(tmp_path: Path) -> None:
    eng, _ = new_engine(str(tmp_path))
    assert sandbox_ok(eng, str(tmp_path / "a.txt"))
    assert sandbox_ok(eng, "a/b/c.txt")  # 相对路径
    assert sandbox_ok(eng, "")  # 空 = root
    assert not sandbox_ok(eng, "/etc/passwd")
    assert not sandbox_ok(eng, "../outside")


def test_sandbox_ancestor_fallback(tmp_path: Path) -> None:
    """目标不存在 + 含未创建中间目录 → 回退到祖先 resolve。"""
    eng, _ = new_engine(str(tmp_path))
    target = str(tmp_path / "new1" / "new2" / "new3" / "x.txt")
    assert sandbox_ok(eng, target)


def test_sandbox_symlink_escape(tmp_path: Path) -> None:
    """指向 root 外的软链接 → 拒。"""
    outside = tmp_path.parent / "outside_target_test"
    outside.mkdir(exist_ok=True)
    try:
        eng, _ = new_engine(str(tmp_path))
        link = tmp_path / "evil"
        link.symlink_to(outside)
        assert not sandbox_ok(eng, str(link / "x.txt"))
    finally:
        try:
            outside.rmdir()
        except OSError:
            pass


# ───────── T4 规则 ─────────


def test_parse_rule() -> None:
    r, ok = parse_rule("Bash(git *)")
    assert ok and r.tool == "Bash" and r.pattern == "git *"
    r, ok = parse_rule("Read")
    assert ok and r.tool == "Read" and r.pattern == ""
    r, ok = parse_rule("Bash(  ")
    assert not ok


def test_match_pattern_command() -> None:
    assert match_pattern("git *", "git status")
    assert not match_pattern("git *", "npm i")
    assert match_pattern("", "anything")
    assert match_pattern("git status", "git status")
    assert not match_pattern("git status", "git push")


def test_match_pattern_path() -> None:
    assert match_pattern("src/**", "src/a/b.py")
    assert match_pattern("src/**", "src/a")
    assert not match_pattern("src/**", "docs/x")
    assert match_pattern("src/*.py", "src/a.py")
    assert not match_pattern("src/*.py", "src/a/b.py")


def test_ruleset_deny_priority() -> None:
    from nuocode.permission.rule import Rule

    rs = RuleSet(
        allow=[Rule("Bash", "git *", True)],
        deny=[Rule("Bash", "git push", False)],
    )
    d, hit = rs.match("Bash", "git push")
    assert hit and d == Decision.DENY
    d, hit = rs.match("Bash", "git status")
    assert hit and d == Decision.ALLOW
    d, hit = rs.match("Bash", "npm i")
    assert not hit


# ───────── T5 配置 ─────────


def test_load_settings_missing(tmp_path: Path) -> None:
    s = load_settings(str(tmp_path / "nope.yaml"))
    assert s.default_mode == "" and s.permissions.allow == [] and s.permissions.deny == []


def test_load_settings_invalid(tmp_path: Path) -> None:
    f = tmp_path / "bad.yaml"
    f.write_text("not: valid: yaml: : :\n  ::: --", encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(str(f))


def test_to_rule_set_skips_invalid(tmp_path: Path) -> None:
    from nuocode.permission.settings import PermissionsBlock, Settings

    s = Settings(permissions=PermissionsBlock(allow=["Bash(git *)", ""], deny=["Read(.env)"]))
    rs = to_rule_set(s)
    assert len(rs.allow) == 1
    assert rs.allow[0].tool == "Bash"
    assert len(rs.deny) == 1


def test_friendly_name_and_categorize() -> None:
    assert friendly_name("bash") == "Bash"
    assert friendly_name("read_file") == "Read"
    assert friendly_name("write_file") == "Write"
    assert friendly_name("unknown_tool") == "unknown_tool"
    assert categorize("read_file", True) == Category.READ
    assert categorize("write_file", False) == Category.WRITE
    assert categorize("bash", False) == Category.EXEC
    # 未知工具 read_only=False → EXEC（最严）
    assert categorize("unknown", False) == Category.EXEC
    # read_only=True 优先
    assert categorize("write_file", True) == Category.READ


def test_extract_target() -> None:
    c = ToolCall(id="1", name="read_file", input=json.dumps({"path": "a.txt"}))
    t, is_file, ok = extract_target(c)
    assert t == "a.txt" and is_file and ok

    c = ToolCall(id="2", name="bash", input=json.dumps({"command": "ls -la"}))
    t, is_file, ok = extract_target(c)
    assert t == "ls -la" and not is_file and ok

    c = ToolCall(id="3", name="glob", input=json.dumps({"pattern": "**/*.py"}))
    t, is_file, ok = extract_target(c)
    assert t == "." and is_file and ok

    # JSON 解析失败：文件类返回 ok=False（沙箱将拒）
    c = ToolCall(id="4", name="read_file", input="not-json")
    t, is_file, ok = extract_target(c)
    assert is_file and not ok

    # bash 缺 command → ok=False，is_file=False（不被拦但落 Ask）
    c = ToolCall(id="5", name="bash", input=json.dumps({}))
    t, is_file, ok = extract_target(c)
    assert not is_file and not ok

    # 未知工具
    c = ToolCall(id="6", name="ghost", input="{}")
    t, is_file, ok = extract_target(c)
    assert t == "" and not is_file and not ok


# ───────── T6 引擎 ─────────


def test_mode_fallback_matrix() -> None:
    # 只读：所有模式 → ALLOW
    for m in Mode:
        assert mode_fallback(m, Category.READ) == Decision.ALLOW
    # default：写/执行 → ASK
    assert mode_fallback(Mode.DEFAULT, Category.WRITE) == Decision.ASK
    assert mode_fallback(Mode.DEFAULT, Category.EXEC) == Decision.ASK
    # acceptEdits：写 → ALLOW；执行 → ASK
    assert mode_fallback(Mode.ACCEPT_EDITS, Category.WRITE) == Decision.ALLOW
    assert mode_fallback(Mode.ACCEPT_EDITS, Category.EXEC) == Decision.ASK
    # plan：写/执行 → ASK（防御兜底）
    assert mode_fallback(Mode.PLAN, Category.WRITE) == Decision.ASK
    assert mode_fallback(Mode.PLAN, Category.EXEC) == Decision.ASK
    # bypass：全 ALLOW
    assert mode_fallback(Mode.BYPASS, Category.WRITE) == Decision.ALLOW
    assert mode_fallback(Mode.BYPASS, Category.EXEC) == Decision.ALLOW


def test_check_blacklist_short_circuits(tmp_path: Path) -> None:
    eng, _ = new_engine(str(tmp_path))
    c = ToolCall(id="b", name="bash", input=json.dumps({"command": "rm -rf /"}))
    d, reason = eng.check(Mode.BYPASS, c, False)
    assert d == Decision.DENY and "黑名单" in reason


def test_check_sandbox_outside(tmp_path: Path) -> None:
    eng, _ = new_engine(str(tmp_path))
    c = ToolCall(id="w", name="write_file", input=json.dumps({"path": "/etc/passwd"}))
    d, reason = eng.check(Mode.DEFAULT, c, False)
    assert d == Decision.DENY and "项目目录之外" in reason


def test_check_unparseable_path_denies(tmp_path: Path) -> None:
    eng, _ = new_engine(str(tmp_path))
    c = ToolCall(id="w", name="write_file", input="not-json")
    d, _ = eng.check(Mode.BYPASS, c, False)
    assert d == Decision.DENY


def test_check_mode_fallback(tmp_path: Path) -> None:
    eng, _ = new_engine(str(tmp_path))
    # default 下写文件 → Ask
    c = ToolCall(id="w", name="write_file", input=json.dumps({"path": "a.txt"}))
    d, _ = eng.check(Mode.DEFAULT, c, False)
    assert d == Decision.ASK
    # acceptEdits 下写 → Allow
    d, _ = eng.check(Mode.ACCEPT_EDITS, c, False)
    assert d == Decision.ALLOW
    # bypass 下任意写 → Allow
    d, _ = eng.check(Mode.BYPASS, c, False)
    assert d == Decision.ALLOW


def test_check_rule_priority(tmp_path: Path) -> None:
    """本地 deny 盖项目 allow。"""
    proj = tmp_path / ".nuocode"
    proj.mkdir()
    (proj / "settings.yaml").write_text(
        'permissions:\n  allow: ["Bash(git *)"]\n', encoding="utf-8"
    )
    (proj / "settings.local.yaml").write_text(
        'permissions:\n  deny: ["Bash(git push)"]\n', encoding="utf-8"
    )
    eng, _ = new_engine(str(tmp_path))
    c = ToolCall(id="b", name="bash", input=json.dumps({"command": "git push"}))
    d, _ = eng.check(Mode.DEFAULT, c, False)
    assert d == Decision.DENY
    c = ToolCall(id="b2", name="bash", input=json.dumps({"command": "git status"}))
    d, _ = eng.check(Mode.DEFAULT, c, False)
    assert d == Decision.ALLOW


def test_new_engine_invalid_yaml_degrades(tmp_path: Path) -> None:
    proj = tmp_path / ".nuocode"
    proj.mkdir()
    (proj / "settings.yaml").write_text("not: valid: : :", encoding="utf-8")
    eng, err = new_engine(str(tmp_path))
    assert err is None
    # 引擎仍可用：空规则 + DEFAULT 模式
    assert eng.start_mode() == Mode.DEFAULT


def test_new_engine_default_mode_priority(tmp_path: Path) -> None:
    proj = tmp_path / ".nuocode"
    proj.mkdir()
    (proj / "settings.yaml").write_text("default_mode: plan\n", encoding="utf-8")
    (proj / "settings.local.yaml").write_text("default_mode: acceptEdits\n", encoding="utf-8")
    eng, _ = new_engine(str(tmp_path))
    assert eng.start_mode() == Mode.ACCEPT_EDITS  # local 优先


def test_new_engine_bad_root_returns_safe_engine() -> None:
    eng, err = new_engine("/nonexistent/aaa/bbb/ccc")
    assert eng is not None
    assert err is not None


# ───────── T7 永久放行 ─────────


def test_persist_local_allow(tmp_path: Path) -> None:
    eng, _ = new_engine(str(tmp_path))
    c = ToolCall(id="w", name="write_file", input=json.dumps({"path": "a.txt"}))
    eng.persist_local_allow(c)
    text = Path(eng.local_path).read_text()
    assert "Write(a.txt)" in text
    # 重载新引擎，规则已生效
    eng2, _ = new_engine(str(tmp_path))
    d, _ = eng2.check(Mode.DEFAULT, c, False)
    assert d == Decision.ALLOW
    # 幂等
    eng2.persist_local_allow(c)
    text2 = Path(eng2.local_path).read_text()
    assert text2.count("Write(a.txt)") == 1


def test_persist_bash_command(tmp_path: Path) -> None:
    eng, _ = new_engine(str(tmp_path))
    c = ToolCall(id="b", name="bash", input=json.dumps({"command": "git status"}))
    eng.persist_local_allow(c)
    text = Path(eng.local_path).read_text()
    assert "Bash(git status)" in text


# ───────── 跳层 ─────────


def test_pipeline_skip_layers(tmp_path: Path) -> None:
    """非 EXEC 不被黑名单拦；bash 不被沙箱拦。"""
    eng, _ = new_engine(str(tmp_path))
    # write_file 命令字符 'rm -rf /' 作为 path 字符串 → 沙箱判（路径是相对，不构成 /）
    c = ToolCall(
        id="w",
        name="write_file",
        input=json.dumps({"path": "rm-rf-poc.txt", "content": ""}),
    )
    d, _ = eng.check(Mode.BYPASS, c, False)
    assert d == Decision.ALLOW  # 不被黑名单误拦
    # bash 不入沙箱：cd 到项目外的命令不被沙箱拦（虽然落到模式兜底 → BYPASS=Allow）
    c = ToolCall(id="b", name="bash", input=json.dumps({"command": "ls /etc"}))
    d, _ = eng.check(Mode.BYPASS, c, False)
    assert d == Decision.ALLOW
