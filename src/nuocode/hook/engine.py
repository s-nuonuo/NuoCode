"""hook.engine: 事件分派主流程、only_once 集合（chap12）。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

from nuocode.hook.event import Event, is_blocking
from nuocode.hook.executor import ExecutionResult, Executor
from nuocode.hook.matcher import eval_condition
from nuocode.hook.rule import Payload, Rule


@dataclass
class DispatchResult:
    blocked: bool = False
    reason: str = ""
    blocking_hook_name: str = ""
    injected_prompts: list[str] = field(default_factory=list)


class Engine:
    """Hook 事件分派引擎。持有 rules 列表与 only_once 状态。"""

    def __init__(self, rules: list[Rule], sources: list[str]) -> None:
        self._rules = rules
        self._sources = sources
        self._once_fired: set[str] = set()
        self._lock = asyncio.Lock()
        self._executor = Executor()

    async def dispatch(self, event: Event, payload: Payload) -> DispatchResult:
        """按声明顺序执行匹配到 event 的 rules。

        - async rule：起 asyncio task 后立即继续，不参与 blocked/injected_prompts 判定
        - 同步 rule：等结果；拦截类事件下首个 blocked rule 中断后续
        - 所有失败（非 0 returncode 但非拦截、http 错误等）写 stderr，不抛异常
        """
        result = DispatchResult()
        for rule in self._rules:
            if rule.event is not event:
                continue
            async with self._lock:
                if rule.only_once and rule.name in self._once_fired:
                    continue
            if not eval_condition(rule.condition, payload):
                continue

            if rule.asyncio_mode:
                # 后台异步执行，不等结果、不影响 blocked/injected_prompts
                asyncio.create_task(
                    self._executor.run(rule, payload, blocking=False),
                    name=f"hook-async-{rule.name}",
                )
                if rule.only_once:
                    async with self._lock:
                        self._once_fired.add(rule.name)
                continue

            # 同步执行
            outcome: ExecutionResult = await self._executor.run(
                rule, payload, blocking=is_blocking(event)
            )

            if outcome.err is not None:
                print(
                    f"[hook {rule.name}] {event.value} failed: {outcome.err}",
                    file=sys.stderr,
                )
                continue  # 失败不标记 once_fired，也不拦截

            if outcome.prompt:
                result.injected_prompts.append(outcome.prompt)

            if rule.only_once:
                async with self._lock:
                    self._once_fired.add(rule.name)

            if outcome.blocked and is_blocking(event):
                result.blocked = True
                result.reason = outcome.reason
                result.blocking_hook_name = rule.name
                break  # 第一个拦截中断后续

        return result

    async def reset_for_new_session(self) -> None:
        """新会话开始时清空 only_once 已触发集合（/clear / /resume 时调用）。"""
        async with self._lock:
            self._once_fired.clear()

    @property
    def sources(self) -> list[str]:
        """加载来源文件列表（副本）。"""
        return list(self._sources)

    @property
    def rules(self) -> list[Rule]:
        """已加载 rule 列表（副本）。"""
        return list(self._rules)


__all__ = ["DispatchResult", "Engine"]
