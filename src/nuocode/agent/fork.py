"""Fork 路径辅助函数（chap13）。

提供：
- ``FORK_BOILERPLATE`` / ``FORK_BOILERPLATE_TAG`` 常量
- ``build_forked_messages``：克隆父对话 + 处理悬空 tool_use + 追加 Boilerplate
- ``is_fork_context``：扫描消息历史判断是否为 Fork 上下文（QuerySource 兜底）

spec F22/F23/F24。
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Fork 子 Agent 首条 user 消息中的标签，用于嵌套阻断检测（spec F24）
FORK_BOILERPLATE_TAG = "<fork_boilerplate>"

FORK_BOILERPLATE = """<fork_boilerplate>
你是一个 Fork 出来的工作进程。你不是主 Agent。
规则（不可协商）：
1. 不能再 Fork（调用 Agent 工具会被拦截）。
2. 不要对话、不要提问、不要请求确认。
3. 直接使用工具：读文件、搜索代码、做修改。
4. 严格限制在你被分配的任务范围内。
5. 最终报告以 "Scope:" 开头，500 字以内。
</fork_boilerplate>

"""


def build_forked_messages(parent_msgs: list, task: str) -> list:
    """把父对话克隆到 Fork 子对话，处理悬空 tool_use，追加 Boilerplate + task。

    行为（spec F22）：
    1. 深拷贝 parent_msgs 的全部消息
    2. 扫描末尾 assistant 消息的 tool_calls；若对应的 tool_result 消息缺失，
       生成 placeholder tool_results（每个 tool_call_id 对应一条 "[forked, skipped]" 错误内容）
    3. 追加 user 消息 = FORK_BOILERPLATE + task

    返回新消息列表，用 ``Conversation.from_messages`` 装载即可。
    """
    from nuocode import llm

    # 深拷贝
    cloned = copy.deepcopy(parent_msgs)

    # 查找末尾 assistant 消息的未配对 tool_call_id
    # assistant 消息角色 = llm.ROLE_ASSISTANT
    last_assistant_idx = -1
    for i in range(len(cloned) - 1, -1, -1):
        if cloned[i].role == llm.ROLE_ASSISTANT:
            last_assistant_idx = i
            break

    if last_assistant_idx >= 0:
        last_assistant = cloned[last_assistant_idx]
        tool_calls = getattr(last_assistant, "tool_calls", None) or []
        if tool_calls:
            # 收集已存在的 tool_result id
            existing_ids: set[str] = set()
            for msg in cloned[last_assistant_idx + 1:]:
                if msg.role == llm.ROLE_TOOL:
                    tr_list = getattr(msg, "tool_results", None) or []
                    for tr in tr_list:
                        existing_ids.add(tr.tool_call_id)

            # 对未配对的 tool_call 构造 placeholder
            missing_results = []
            for tc in tool_calls:
                if tc.id not in existing_ids:
                    missing_results.append(
                        llm.ToolResult(
                            tool_call_id=tc.id,
                            content="[forked, skipped]",
                            is_error=True,
                        )
                    )
            if missing_results:
                placeholder_msg = llm.Message(
                    role=llm.ROLE_TOOL,
                    tool_results=missing_results,
                )
                cloned.append(placeholder_msg)

    # 追加 user 消息：FORK_BOILERPLATE + task
    fork_user_content = FORK_BOILERPLATE + (task or "")
    cloned.append(llm.Message(role=llm.ROLE_USER, content=fork_user_content))

    return cloned


def is_fork_context(msgs: list) -> bool:
    """判断对话历史是否来自 Fork（通过扫描 FORK_BOILERPLATE_TAG）。

    QuerySource 检测的兜底机制——caller 链丢失时靠这个（spec F24）。
    """
    for msg in msgs:
        # 扫描 user 消息 content
        content = getattr(msg, "content", None)
        if isinstance(content, str) and FORK_BOILERPLATE_TAG in content:
            return True
        # tool_results 内容（理论上不含，但防御性检查）
        for tr in (getattr(msg, "tool_results", None) or []):
            if isinstance(getattr(tr, "content", None), str) and FORK_BOILERPLATE_TAG in tr.content:
                return True
    return False
