"""AgentTool：主 Agent 可调用的子 Agent 工具（chap13 F1-F3）。

主 Agent 通过此工具启动子 Agent：
- 定义式：指定 subagent_type，从 Catalog 取预定义角色
- Fork 式：不指定 subagent_type，克隆父对话历史 + Fork Boilerplate

防嵌套三道闸（F24/F25）：
1. ALL_AGENT_DISALLOWED_TOOLS：定义式子 Agent 工具列表里没有 Agent 工具
2. QuerySource / Fork 嵌套检测：Fork 子 Agent 再调用 Agent 工具时拦截
3. Boilerplate 标记扫描：is_fork_context 兜底
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from nuocode.agent.fork import is_fork_context
from nuocode.tool import Result
from nuocode.tool.filter import (
    FilterParams,
    apply_agent_tool_filter,
)

if TYPE_CHECKING:
    from nuocode.subagent.catalog import Catalog
    from nuocode.task.manager import Manager as TaskManager


# ── 模型别名映射 ──────────────────────────────────────────────────────────────

_MODEL_ALIASES: dict[str, str] = {
    "inherit": "inherit",
    "haiku": "claude-3-5-haiku-20241022",
    "sonnet": "claude-sonnet-4-5",
    "opus": "claude-opus-4-5",
}

# 前台子 Agent 超时自动切后台阈值（秒），spec F17
AUTO_BACKGROUND_TIMEOUT: float = 120.0


class AgentTool:
    """主 Agent 用于启动子 Agent 的工具（chap13 F1-F3）。

    属性 ``read_only`` 设为 False（子 Agent 可能写文件）；
    ``is_system`` 设为 True（跳过 Skill fork 白名单检查，始终可见）。
    """

    read_only = False
    is_system = True  # 子 Agent 工具是系统级，不受 allowed_tools 白名单裁剪

    def __init__(
        self,
        catalog: Catalog,
        parent_agent: Any,          # nuocode.agent.Agent —— 避免循环引用
        task_manager: TaskManager | None = None,
        enable_background: bool = True,
        parent_conv: Any | None = None,  # 父 Conversation（Fork 路径需要）
    ) -> None:
        self._catalog = catalog
        self._parent_agent = parent_agent
        self._task_manager = task_manager
        self._enable_background = enable_background
        self._parent_conv = parent_conv  # 可选，TUI 侧注入

    # ── Tool 接口 ──────────────────────────────────────────────────────────────

    def name(self) -> str:
        return "Agent"

    def description(self) -> str:
        return (
            "启动一个子 Agent 来完成独立任务。\n"
            "- 定义式：指定 subagent_type 选择预定义角色（Explore/Plan/general-purpose 等）\n"
            "- Fork 式：不指定 subagent_type，克隆当前对话上下文独立完成任务\n"
            "Fork 子 Agent 强制后台执行，不阻塞主对话。\n"
            "可用角色列表: " + ", ".join(self._catalog.names())
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "交给子 Agent 的任务指令（必填）",
                },
                "description": {
                    "type": "string",
                    "description": "一句话描述任务，供 UI 展示（必填）",
                },
                "subagent_type": {
                    "type": "string",
                    "description": "预定义角色名（可选），留空时走 Fork 路径",
                },
                "model": {
                    "type": "string",
                    "enum": ["haiku", "sonnet", "opus", "inherit"],
                    "description": "模型覆盖（可选），留空沿用角色定义中的 model",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "是否后台执行（可选），Fork 路径无条件后台",
                },
                "name": {
                    "type": "string",
                    "description": "给本次任务命名（可选），用于 SendMessage 定位",
                },
            },
            "required": ["prompt", "description"],
        }

    async def execute(self, args: str) -> Result:
        try:
            params = json.loads(args or "{}")
            if not isinstance(params, dict):
                params = {}
        except (json.JSONDecodeError, TypeError):
            return Result(
                content="[AgentTool] 参数 JSON 解析失败",
                is_error=True,
            )

        prompt: str = params.get("prompt") or ""
        subagent_type: str | None = params.get("subagent_type") or None
        run_in_background: bool = bool(params.get("run_in_background", False))
        task_name: str | None = params.get("name") or None

        if not prompt:
            return Result(content="[AgentTool] prompt 不能为空", is_error=True)

        is_fork = subagent_type is None

        # ── Fork 嵌套阻断（F24）──────────────────────────────────────────
        if is_fork:
            # 检测调用方是否来自 Fork 上下文
            parent_msgs = []
            if self._parent_conv is not None:
                try:
                    parent_msgs = list(self._parent_conv.messages())
                except Exception:  # noqa: BLE001
                    pass
            if is_fork_context(parent_msgs):
                return Result(
                    content="[AgentTool] Fork 子 Agent 不能再启动 Agent（嵌套阻断）",
                    is_error=True,
                )

        # ── 后台模式检查 ──────────────────────────────────────────────────
        # Fork 路径强制后台（F18）
        if is_fork:
            run_in_background = True

        if run_in_background and not self._enable_background:
            if is_fork:
                return Result(
                    content="[AgentTool] 后台模式已禁用，无法 Fork（N6）",
                    is_error=True,
                )
            # 定义式：退回前台
            run_in_background = False

        # ── 解析 Definition ──────────────────────────────────────────────
        if is_fork:
            definition = self._catalog.fork_definition()
        else:
            definition = self._catalog.resolve(subagent_type)
            if definition is None:
                return Result(
                    content=f"[AgentTool] 未知 subagent_type: {subagent_type!r}",
                    is_error=True,
                )

        # ── 构建子 Agent ─────────────────────────────────────────────────
        sub_agent, sub_conv = self._build_sub_agent(
            definition=definition,
            is_fork=is_fork,
            is_background=run_in_background,
        )

        # ── 执行 ─────────────────────────────────────────────────────────
        if run_in_background:
            return await self._launch_background(
                sub_agent=sub_agent,
                sub_conv=sub_conv,
                task=prompt,
                task_name=task_name,
                is_fork=is_fork,
            )
        else:
            return await self._run_inline(
                sub_agent=sub_agent,
                sub_conv=sub_conv,
                task=prompt,
                definition_name=definition.name,
            )

    # ── 内部辅助 ──────────────────────────────────────────────────────────────

    def _compute_allowed_tools(
        self,
        definition: Any,  # subagent.Definition
        is_background: bool,
    ) -> list[str]:
        """按 F30 五步过滤计算工具白名单。"""

        # 全量工具名（含 MCP/Skill）
        parent_registry = self._parent_agent._registry
        full_tools = parent_registry.names()

        fp = FilterParams(
            all=full_tools,
            source=int(definition.source),
            background=is_background,
            allowed=list(definition.tools),
            disallowed=list(definition.disallowed_tools),
        )
        return apply_agent_tool_filter(fp)

    def _build_sub_agent(
        self,
        definition: Any,
        is_fork: bool,
        is_background: bool,
    ) -> tuple[Any, Any]:
        """构造子 Agent 和子对话。"""
        import tempfile

        from nuocode.agent import Agent
        from nuocode.agent.fork import build_forked_messages
        from nuocode.agent.runtime import SessionRuntime
        from nuocode.compact import new_session_context
        from nuocode.conversation import Conversation
        from nuocode.permission import new_engine

        parent = self._parent_agent

        # 独立权限引擎（共享项目 root）
        try:
            project_root = str(parent._engine.root)
        except AttributeError:
            project_root = tempfile.gettempdir()
        sub_engine, _ = new_engine(project_root)

        # 工具白名单
        allowed = self._compute_allowed_tools(definition, is_background=is_background)

        # 独立 Runtime
        sub_runtime = SessionRuntime(
            session=new_session_context(tempfile.gettempdir())
        )

        # Permission mode：直接使用 definition 中的 Mode
        sub_mode = definition.permission_mode

        # 构造子 Agent
        sub_agent = Agent(
            provider=parent._provider,
            registry=parent._registry,
            version=parent._version,
            engine=sub_engine,
            runtime=sub_runtime,
            context_window=parent._context_window,
            system_prompt=definition.system_prompt or None,
            max_turns=definition.max_turns if definition.max_turns > 0 else 0,
            permission_mode=sub_mode,
            dont_ask=definition.dont_ask,
            allowed_tools=allowed if allowed else None,
        )

        # 构造子对话
        if is_fork and self._parent_conv is not None:
            # Fork 路径：克隆父消息 + Boilerplate（不传 task，task 后面传给 run_to_completion）
            parent_msgs = list(self._parent_conv.messages())
            forked = build_forked_messages(parent_msgs, "")
            sub_conv = Conversation.from_messages(forked)
        else:
            sub_conv = Conversation()

        return sub_agent, sub_conv

    async def _run_inline(
        self,
        sub_agent: Any,
        sub_conv: Any,
        task: str,
        definition_name: str,
    ) -> Result:
        """前台同步执行（F2：inline）。"""
        from nuocode.agent import MaxTurnsReached

        try:
            # Fork 路径：task 已经在 build_forked_messages 里处理了 Boilerplate
            # 这里直接传 task 给 run_to_completion，它会追加 user 消息
            final_text = await sub_agent.run_to_completion(sub_conv, task)
            return Result(content=final_text)
        except MaxTurnsReached as e:
            return Result(
                content=f"[SubAgent:{definition_name}] 触达最大轮数：{e.final_text}",
                is_error=False,  # 返回已有结果，不是硬错误
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            return Result(
                content=f"[SubAgent:{definition_name}] 执行失败：{e}",
                is_error=True,
            )

    async def _launch_background(
        self,
        sub_agent: Any,
        sub_conv: Any,
        task: str,
        task_name: str | None,
        is_fork: bool,
    ) -> Result:
        """后台异步执行（F2：background）。"""
        if self._task_manager is None:
            # 没有 TaskManager 时降级为内联执行
            from nuocode.agent import MaxTurnsReached

            try:
                final_text = await sub_agent.run_to_completion(sub_conv, task)
                return Result(content=final_text)
            except MaxTurnsReached as e:
                return Result(content=e.final_text)
            except Exception as e:  # noqa: BLE001
                return Result(content=f"执行失败：{e}", is_error=True)

        task_id = await self._task_manager.launch(
            sub_agent=sub_agent,
            conv=sub_conv,
            task=task,
            name=task_name,
        )
        status = "async_launched"
        return Result(
            content=json.dumps(
                {"task_id": task_id, "status": status, "name": task_name or ""},
                ensure_ascii=False,
            )
        )
