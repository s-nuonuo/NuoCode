"""compact 子系统测试：layer1 / layer2 / token / state / recovery / manage_context。"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nuocode.compact import (
    AutoCompactTrackingState,
    ContentReplacementState,
    FileReadRecord,
    ManageInput,
    RecoveryState,
    TriggerKind,
    manage_context,
    new_session_context,
)
from nuocode.compact.const import (
    AUTO_SAFETY_MARGIN,
    MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES,
    SINGLE_RESULT_LIMIT,
    SUMMARY_RESERVE,
)
from nuocode.compact.layer1 import build_preview, offload_and_snip, spill_single
from nuocode.compact.layer2 import (
    group_by_user_turn,
    pick_recent_tail,
    ptl_retry,
)
from nuocode.compact.recovery import build_recovery_attachment
from nuocode.compact.summary_prompt import (
    build_summary_prompt,
    extract_summary,
    serialize_conversation,
)
from nuocode.compact.token import estimate_tokens, message_chars, usage_anchor
from nuocode.conversation import Conversation
from nuocode.llm import (
    Message,
    PromptTooLongError,
    Request,
    StreamEvent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    Usage,
)

# ───────── helpers ─────────


def _session(tmp: Path):
    return new_session_context(str(tmp))


def _user(text: str) -> Message:
    return Message(role="user", content=text)


def _assistant(text: str = "") -> Message:
    return Message(role="assistant", content=text)


def _tool_msg(*results: ToolResult) -> Message:
    return Message(role="tool", tool_results=list(results))


# ───────── token ─────────


def test_usage_anchor_sums_all_fields() -> None:
    u = Usage(input_tokens=100, output_tokens=50, cache_write=10, cache_read=5)
    assert usage_anchor(u) == 165


def test_message_chars_counts_utf8() -> None:
    m = _user("hello 世界")  # 6 ascii + space + 6 utf-8 bytes
    chars = message_chars([m])
    assert chars == len("hello 世界".encode())


def test_estimate_tokens_uses_anchor_plus_tail() -> None:
    msgs = [_user("a"), _assistant("b"), _user("hello")]
    # anchor 已含前 2 条，所以只对 msgs[2:] 估算
    est = estimate_tokens(anchor=1000, all_msgs=msgs, anchor_msg_len=2)
    expected_tail_chars = len(b"hello")
    import math

    assert est == 1000 + math.ceil(expected_tail_chars / 3.5)


# ───────── ContentReplacementState ─────────


def test_replacement_decision_freezes() -> None:
    s = ContentReplacementState()
    out1 = s.decide_once("id1", "X" * 100, lambda: ("replaced", "PREVIEW"))
    assert out1 == "PREVIEW"
    # 再次决策回调返回 kept 也无效，仍取上一次结果
    out2 = s.decide_once("id1", "X" * 100, lambda: ("kept", ""))
    assert out2 == "PREVIEW"


def test_replacement_kept_freezes_to_original() -> None:
    s = ContentReplacementState()
    out1 = s.decide_once("id1", "ABC", lambda: ("kept", ""))
    assert out1 == "ABC"
    out2 = s.decide_once("id1", "ABC", lambda: ("replaced", "PV"))
    assert out2 == "ABC"


def test_replacement_skip_does_not_freeze() -> None:
    s = ContentReplacementState()
    out1 = s.decide_once("id1", "ABC", lambda: ("skip", ""))
    assert out1 == "ABC"
    out2 = s.decide_once("id1", "ABC", lambda: ("replaced", "PV"))
    assert out2 == "PV"


# ───────── layer1 ─────────


def test_spill_single_writes_file(tmp_path: Path) -> None:
    sess = _session(tmp_path)
    spill_single(sess, "tool-id-1", "hello")
    p = Path(sess.spill_dir) / "tool-id-1"
    assert p.read_text() == "hello"
    # 幂等：再次落盘不报错
    spill_single(sess, "tool-id-1", "different content (ignored)")
    assert p.read_text() == "hello"


def test_build_preview_contains_all_markers() -> None:
    pv = build_preview(12345, "head text", "/spill/abc")
    assert "12345" in pv
    assert "[saved to] /spill/abc" in pv
    assert "head preview" in pv
    assert "head text" in pv
    assert "文件读取工具" in pv
    assert "不要凭头部预览猜测" in pv


def test_offload_and_snip_replaces_oversized(tmp_path: Path) -> None:
    sess = _session(tmp_path)
    state = ContentReplacementState()
    big = "X" * (SINGLE_RESULT_LIMIT + 100)
    msgs = [_tool_msg(ToolResult(tool_call_id="t1", content=big))]
    out = offload_and_snip(msgs, state, sess)
    new_content = out[0].tool_results[0].content
    assert "[content offloaded]" in new_content
    # 入参未被修改
    assert msgs[0].tool_results[0].content == big
    # 落盘文件存在
    assert (Path(sess.spill_dir) / "t1").exists()


def test_offload_and_snip_keeps_small(tmp_path: Path) -> None:
    sess = _session(tmp_path)
    state = ContentReplacementState()
    small = "ok"
    msgs = [_tool_msg(ToolResult(tool_call_id="t1", content=small))]
    out = offload_and_snip(msgs, state, sess)
    assert out[0].tool_results[0].content == small


def test_offload_and_snip_idempotent(tmp_path: Path) -> None:
    sess = _session(tmp_path)
    state = ContentReplacementState()
    big = "Y" * (SINGLE_RESULT_LIMIT + 50)
    msgs = [_tool_msg(ToolResult(tool_call_id="t1", content=big))]
    out1 = offload_and_snip(msgs, state, sess)
    # 第二轮入参仍是原文（模拟下一轮主循环把原始消息再次送进来）
    out2 = offload_and_snip(msgs, state, sess)
    assert out1[0].tool_results[0].content == out2[0].tool_results[0].content


# ───────── recovery ─────────


def test_recovery_state_records_and_dedupes() -> None:
    rs = RecoveryState()
    rs.record_file("/abs/a.py", "v1")
    rs.record_file("/abs/a.py", "v2")
    rs.record_file("/abs/b.py", "B")
    snap = rs.snapshot()
    assert {r.path for r in snap} == {"/abs/a.py", "/abs/b.py"}
    by_path = {r.path: r.content for r in snap}
    assert by_path["/abs/a.py"] == "v2"


def test_build_recovery_attachment_has_three_sections() -> None:
    from datetime import datetime

    rec = FileReadRecord(path="/x.py", content="print(1)", timestamp=datetime.now())
    tools = [ToolDefinition(name="ReadFile", description="d", input_schema={"type": "object"})]
    text = build_recovery_attachment([rec], tools)
    assert "最近读过的文件" in text
    assert "/x.py" in text
    assert "当前可用工具" in text
    assert "ReadFile" in text
    assert "边界提示" in text
    assert "不要依据摘要内容做猜测" in text


# ───────── summary_prompt ─────────


def test_summary_prompt_serialization() -> None:
    msgs = [
        _user("hi"),
        Message(
            role="assistant",
            content="thinking",
            tool_calls=[ToolCall(id="c1", name="ReadFile", input='{"path":"a"}')],
        ),
        _tool_msg(ToolResult(tool_call_id="c1", content="file body")),
    ]
    s = serialize_conversation(msgs)
    assert "user: hi" in s
    assert "assistant: thinking" in s
    assert "[call ReadFile" in s
    assert "[result id=c1" in s


def test_summary_prompt_builds_single_user_message() -> None:
    msgs = [_user("hi")]
    out = build_summary_prompt(msgs)
    assert len(out) == 1
    assert out[0].role == "user"
    assert "## 1 主要请求和意图" in out[0].content
    assert "## 6 所有用户消息原文" in out[0].content


def test_extract_summary_picks_last_pair() -> None:
    raw = "<analysis>...</analysis>\nSome stuff <summary>FIRST</summary>\n<summary>FINAL</summary>"
    assert extract_summary(raw) == "FINAL"


def test_extract_summary_fallback_on_missing() -> None:
    raw = "no tags here"
    assert extract_summary(raw) == raw


# ───────── layer2: pick_recent_tail / group_by_user_turn ─────────


def test_pick_recent_tail_satisfies_both_lower_bounds() -> None:
    msgs = [_user(f"u{i}") for i in range(10)]
    tail = pick_recent_tail(msgs)
    assert len(tail) >= 5  # RECENT_KEEP_MESSAGES


def test_group_by_user_turn_basic() -> None:
    msgs = [
        _user("u1"),
        _assistant("a1"),
        _user("u2"),
        _assistant("a2"),
        _tool_msg(ToolResult(tool_call_id="c", content="r")),
    ]
    groups = group_by_user_turn(msgs)
    assert len(groups) == 2
    assert groups[0][0].content == "u1"
    assert groups[1][0].content == "u2"
    assert len(groups[1]) == 3


# ───────── layer2: ptl_retry ─────────


class _FakeProvider:
    def __init__(self, responses: list) -> None:
        self._responses = responses
        self._idx = 0
        self.calls: list[Request] = []
        self.name = "fake"
        self.model = "fake"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.calls.append(req)
        resp = self._responses[self._idx]
        self._idx += 1
        if isinstance(resp, Exception):
            yield StreamEvent(err=resp)
            return
        yield StreamEvent(text=resp)
        yield StreamEvent(usage=Usage(input_tokens=1, output_tokens=1))
        yield StreamEvent(done=True)


@pytest.mark.asyncio
async def test_ptl_retry_succeeds_after_dropping_oldest() -> None:
    provider = _FakeProvider(
        [
            "<summary>OK</summary>",  # second call succeeds
        ]
    )

    # 构造 ManageInput 占位（ptl_retry 仅用 provider）
    from nuocode.compact.compact import ManageInput as MI

    mi = MI(
        conv=Conversation(),
        provider=provider,  # type: ignore[arg-type]
        context_window=200_000,
        tool_defs=[],
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=_session(Path(tempfile.gettempdir())),
        usage_anchor=0,
        anchor_msg_len=0,
        estimated_token=0,
        trigger=TriggerKind.AUTO,
    )

    msgs = [_user("u1"), _assistant("a1"), _user("u2"), _assistant("a2")]
    out = await ptl_retry(mi, msgs, PromptTooLongError("first"))
    assert out == "OK"


@pytest.mark.asyncio
async def test_ptl_retry_raises_when_all_groups_consumed() -> None:
    # 所有重试都返回 PTL
    provider = _FakeProvider([PromptTooLongError("retry-1"), PromptTooLongError("retry-2")])
    from nuocode.compact.compact import ManageInput as MI

    mi = MI(
        conv=Conversation(),
        provider=provider,  # type: ignore[arg-type]
        context_window=200_000,
        tool_defs=[],
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=_session(Path(tempfile.gettempdir())),
        usage_anchor=0,
        anchor_msg_len=0,
        estimated_token=0,
        trigger=TriggerKind.AUTO,
    )
    msgs = [_user("u1"), _user("u2")]
    with pytest.raises(PromptTooLongError):
        await ptl_retry(mi, msgs, PromptTooLongError("first"))


# ───────── auto tracking 熔断 ─────────


def test_auto_tracking_trips_after_n_failures() -> None:
    s = AutoCompactTrackingState()
    for _ in range(MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES - 1):
        s.record_failure()
    assert not s.tripped()
    s.record_failure()
    assert s.tripped()
    s.record_success()
    assert not s.tripped()


# ───────── Conversation.replace_messages ─────────


def test_conversation_replace_messages() -> None:
    conv = Conversation()
    conv.add_user("a")
    conv.add_assistant("b")
    new = [_user("X"), _assistant("Y")]
    conv.replace_messages(new)
    msgs = conv.messages()
    assert len(msgs) == 2
    assert msgs[0].content == "X"
    # 入参拷贝：修改外部 list 不影响 conv
    new.append(_user("Z"))
    assert len(conv.messages()) == 2


# ───────── manage_context (integration) ─────────


@pytest.mark.asyncio
async def test_manage_context_manual_runs_layer2(tmp_path: Path) -> None:
    provider = _FakeProvider(["<summary>SUM</summary>"])
    conv = Conversation()
    conv.add_user("hi")
    conv.add_assistant("ok")

    in_ = ManageInput(
        conv=conv,
        provider=provider,  # type: ignore[arg-type]
        context_window=200_000,
        tool_defs=[],
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=_session(tmp_path),
        usage_anchor=0,
        anchor_msg_len=0,
        estimated_token=100,
        trigger=TriggerKind.MANUAL,
    )
    out = await manage_context(in_)
    assert out.before_tokens == 100
    msgs = conv.messages()
    # 替换后第一条必是含摘要的 user 消息
    assert msgs[0].role == "user"
    assert "SUM" in msgs[0].content
    assert "最近读过的文件" in msgs[0].content


@pytest.mark.asyncio
async def test_manage_context_auto_below_threshold_skips_layer2(tmp_path: Path) -> None:
    """估算远低于阈值时 AUTO 不应调 provider。"""
    provider = _FakeProvider([])  # 任何调用都会越界
    conv = Conversation()
    conv.add_user("small")

    in_ = ManageInput(
        conv=conv,
        provider=provider,  # type: ignore[arg-type]
        context_window=200_000,
        tool_defs=[],
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=AutoCompactTrackingState(),
        session=_session(tmp_path),
        usage_anchor=10,
        anchor_msg_len=1,
        estimated_token=10,
        trigger=TriggerKind.AUTO,
    )
    out = await manage_context(in_)
    assert out.after_tokens < 200_000 - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
    assert provider.calls == []


@pytest.mark.asyncio
async def test_manage_context_auto_circuit_breaker_blocks(tmp_path: Path) -> None:
    """熔断后即使估算超阈值也不应调 provider。"""
    provider = _FakeProvider([])
    conv = Conversation()
    # 制造一些消息
    big = "X" * 50_000
    conv.add_user(big)

    auto_track = AutoCompactTrackingState()
    for _ in range(MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES):
        auto_track.record_failure()
    assert auto_track.tripped()

    in_ = ManageInput(
        conv=conv,
        provider=provider,  # type: ignore[arg-type]
        context_window=10_000,  # 故意把窗口设很小，强制超阈值
        tool_defs=[],
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=auto_track,
        session=_session(tmp_path),
        usage_anchor=0,
        anchor_msg_len=0,
        estimated_token=999_999,
        trigger=TriggerKind.AUTO,
    )
    out = await manage_context(in_)
    # 熔断 + 窗口过小双重保护，不应调 provider
    assert provider.calls == []
    assert isinstance(out.after_tokens, int)


# ───────── PromptTooLongError detection in providers ─────────


def test_promptools_too_long_anthropic_detection() -> None:
    from nuocode.llm.anthropic_provider import _is_prompt_too_long

    assert _is_prompt_too_long(Exception("Error: prompt is too long blah"))
    assert not _is_prompt_too_long(Exception("network error"))


def test_promptools_too_long_openai_detection() -> None:
    from nuocode.llm.openai_provider import _is_prompt_too_long

    e = Exception("This model's maximum context length is 8192 tokens")
    assert _is_prompt_too_long(e)


# ───────── new_session_context ─────────


def test_new_session_context_creates_dir(tmp_path: Path) -> None:
    sess = new_session_context(str(tmp_path))
    p = Path(sess.spill_dir)
    assert p.exists()
    assert p.is_dir()
    # 目录形如 .nuocode/sessions/<id>/tool-results
    assert ".nuocode/sessions" in sess.spill_dir
    assert sess.session_id in sess.spill_dir


# ───────── ProviderConfig.effective_context_window ─────────


def test_provider_config_effective_context_window() -> None:
    from nuocode.config import ProviderConfig

    cfg = ProviderConfig(
        name="x", protocol="anthropic", api_key="k", model="m", context_window=None
    )
    assert cfg.effective_context_window() == 200_000

    cfg2 = ProviderConfig(name="x", protocol="openai", api_key="k", model="m", context_window=None)
    assert cfg2.effective_context_window() == 128_000

    cfg3 = ProviderConfig(
        name="x", protocol="anthropic", api_key="k", model="m", context_window=50_000
    )
    assert cfg3.effective_context_window() == 50_000
