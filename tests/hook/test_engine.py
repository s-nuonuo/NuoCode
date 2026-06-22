"""hook.engine 单元测试（chap12 T13）。"""

from __future__ import annotations

import asyncio

import pytest

from nuocode.hook.engine import DispatchResult, Engine
from nuocode.hook.event import Event
from nuocode.hook.rule import (
    Action,
    ActionType,
    PromptAction,
    Rule,
    ShellAction,
)


def _shell_rule(name: str, event: Event, cmd: str, **kwargs) -> Rule:
    return Rule(
        name=name,
        event=event,
        action=Action(type=ActionType.SHELL, shell=ShellAction(command=cmd)),
        timeout_s=5.0,
        **kwargs,
    )


def _prompt_rule(name: str, event: Event, text: str, **kwargs) -> Rule:
    return Rule(
        name=name,
        event=event,
        action=Action(type=ActionType.PROMPT, prompt=PromptAction(text=text)),
        timeout_s=5.0,
        **kwargs,
    )


# ────────── 多 rule 顺序执行 ──────────

@pytest.mark.asyncio
async def test_multiple_rules_execute_in_order() -> None:
    log: list[str] = []
    ex_results: list = []

    class FakeExecutor:
        async def run(self, rule, payload, *, blocking):
            log.append(rule.name)
            from nuocode.hook.executor import ExecutionResult
            return ExecutionResult()

    rules = [
        _shell_rule("a", Event.SESSION_START, "echo a"),
        _shell_rule("b", Event.SESSION_START, "echo b"),
        _shell_rule("c", Event.SESSION_START, "echo c"),
    ]
    eng = Engine(rules=rules, sources=[])
    eng._executor = FakeExecutor()  # type: ignore[assignment]
    await eng.dispatch(Event.SESSION_START, {})
    assert log == ["a", "b", "c"]


# ────────── 拦截事件下首个 blocked 中断后续 ──────────

@pytest.mark.asyncio
async def test_blocking_event_stops_at_first_block() -> None:
    executed: list[str] = []

    class FakeExecutor:
        async def run(self, rule, payload, *, blocking):
            executed.append(rule.name)
            from nuocode.hook.executor import ExecutionResult
            if rule.name == "blocker":
                return ExecutionResult(blocked=True, reason="blocked!")
            return ExecutionResult()

    rules = [
        _shell_rule("blocker", Event.PRE_TOOL_USE, "exit 2"),
        _shell_rule("after", Event.PRE_TOOL_USE, "echo after"),
    ]
    eng = Engine(rules=rules, sources=[])
    eng._executor = FakeExecutor()  # type: ignore[assignment]
    result = await eng.dispatch(Event.PRE_TOOL_USE, {"tool_name": "bash"})
    assert result.blocked is True
    assert result.reason == "blocked!"
    assert result.blocking_hook_name == "blocker"
    assert "after" not in executed


# ────────── 非拦截事件不传递 blocked ──────────

@pytest.mark.asyncio
async def test_non_blocking_event_does_not_set_blocked() -> None:
    """非拦截事件即使 executor 返回 blocked=True 也不进入 DispatchResult.blocked。"""

    class FakeExecutor:
        async def run(self, rule, payload, *, blocking):
            from nuocode.hook.executor import ExecutionResult
            # blocking=False 时，executor 的 shell 实现会把 exit2 视为 err 而非 blocked
            # Engine 层面：is_blocking(SessionStart)=False → outcome.blocked 不传递
            return ExecutionResult(blocked=True, reason="fake block")

    rules = [_shell_rule("r", Event.SESSION_START, "exit 2")]
    eng = Engine(rules=rules, sources=[])
    eng._executor = FakeExecutor()  # type: ignore[assignment]
    result = await eng.dispatch(Event.SESSION_START, {})
    assert result.blocked is False


# ────────── prompt 累加到 injected_prompts ──────────

@pytest.mark.asyncio
async def test_prompt_rules_accumulate() -> None:
    rules = [
        _prompt_rule("p1", Event.SESSION_START, "text A"),
        _prompt_rule("p2", Event.SESSION_START, "text B"),
    ]
    eng = Engine(rules=rules, sources=[])
    result = await eng.dispatch(Event.SESSION_START, {})
    assert result.injected_prompts == ["text A", "text B"]


# ────────── only_once 首次执行后跳过 ──────────

@pytest.mark.asyncio
async def test_only_once_skips_on_second_dispatch() -> None:
    call_count = [0]

    class FakeExecutor:
        async def run(self, rule, payload, *, blocking):
            call_count[0] += 1
            from nuocode.hook.executor import ExecutionResult
            return ExecutionResult()

    rules = [_shell_rule("once", Event.PRE_USER_MESSAGE, "echo hi", only_once=True)]
    eng = Engine(rules=rules, sources=[])
    eng._executor = FakeExecutor()  # type: ignore[assignment]
    await eng.dispatch(Event.PRE_USER_MESSAGE, {})
    assert call_count[0] == 1
    await eng.dispatch(Event.PRE_USER_MESSAGE, {})
    assert call_count[0] == 1  # 第二次被跳过


# ────────── reset_for_new_session 后 only_once 重置 ──────────

@pytest.mark.asyncio
async def test_reset_clears_once_fired() -> None:
    call_count = [0]

    class FakeExecutor:
        async def run(self, rule, payload, *, blocking):
            call_count[0] += 1
            from nuocode.hook.executor import ExecutionResult
            return ExecutionResult()

    rules = [_shell_rule("once", Event.PRE_USER_MESSAGE, "echo hi", only_once=True)]
    eng = Engine(rules=rules, sources=[])
    eng._executor = FakeExecutor()  # type: ignore[assignment]
    await eng.dispatch(Event.PRE_USER_MESSAGE, {})
    assert call_count[0] == 1
    await eng.reset_for_new_session()
    await eng.dispatch(Event.PRE_USER_MESSAGE, {})
    assert call_count[0] == 2  # 重置后再次执行


# ────────── async rule 不参与 blocked 判定 ──────────

@pytest.mark.asyncio
async def test_async_rule_does_not_block() -> None:
    task_started = asyncio.Event()

    class FakeExecutor:
        async def run(self, rule, payload, *, blocking):
            task_started.set()
            from nuocode.hook.executor import ExecutionResult
            return ExecutionResult(blocked=True, reason="from async rule")

    rules = [_shell_rule("async-rule", Event.SESSION_START, "exit 2", asyncio_mode=True)]
    eng = Engine(rules=rules, sources=[])
    eng._executor = FakeExecutor()  # type: ignore[assignment]
    result = await eng.dispatch(Event.SESSION_START, {})
    # async rule 不参与 blocked 判定
    assert result.blocked is False
    assert result.injected_prompts == []
    # 等待后台 task 完成（验证 task 已起）
    await asyncio.sleep(0.01)
    assert task_started.is_set()
