"""Coordinator 包（chap15 F52-F55、T24）。

提供：
- is_enabled(cfg) → bool：双锁机制（feature flag + 环境变量）
- allowed_tools() → list[str]：Coordinator Mode 工具白名单
- system_prompt_suffix() → str：四阶段 + "派完就停手" 纪律提示词
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nuocode.config import Config

# ── 常量 ─────────────────────────────────────────────────────────────────────

COORDINATOR_ALLOWED_TOOLS: list[str] = [
    "Agent",
    "TeamCreate",
    "TeamDelete",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
    "read_file",
    "glob",
    "grep",
    "bash",
]

COORDINATOR_SYSTEM_PROMPT_SUFFIX = """

## Coordinator Mode — 四阶段框架与调度纪律

你当前处于 **Coordinator Mode**，工具集已收窄（移除了 write_file / edit_file）。
你的职责是指挥团队，而非亲自写代码。

### 四阶段

1. **Research（定位）**：用 read_file / glob / grep 快速了解代码库目标区域，然后**停止自己探索**。
2. **Synthesis（分工）**：把工作切分成任务，用 Agent(team_name=...) 派出队员；用 TaskCreate 建任务。
3. **Implementation（等待）**：派完队员后 **停手等汇报**。不要用 TaskList 轮询，不要 sleep。
4. **Verification（收敛）**：收到所有队员 idle 通知后，用 bash 跑 git merge 逐个合并，用 read_file 看冲突，用 bash 解冲突后提交。

### 铁律：派完就停手

- 派出 Agent / SendMessage 后，**禁止立刻调 read_file / glob / grep / bash 自己探索**
- 禁止用 TaskList 轮询凑时间
- 发一行总结"已派 N 名队员探索 X，等结果"，**让本轮结束**
- 唯一允许自己读的场景：
  - Research 第一次目标定位
  - Synthesis 读队员产出的报告文件
  - Verification git diff / git status 等收敛操作
"""


def env_truthy(v: str) -> bool:
    """判断环境变量值是否为 truthy（F52）。"""
    return v.strip().lower() in {"1", "true", "yes"}


def is_enabled(cfg: Config) -> bool:
    """判断 Coordinator Mode 是否启用（F52）。

    双锁：feature flag 开 AND 环境变量 nuocode_COORDINATOR_MODE 为 truthy。
    """
    features = getattr(cfg, "features", None)
    if features is None:
        return False
    if not bool(getattr(features, "coordinator_mode", False)):
        return False
    return env_truthy(os.environ.get("nuocode_COORDINATOR_MODE", ""))


def allowed_tools() -> list[str]:
    """返回 Coordinator Mode 工具白名单（F53）。"""
    return list(COORDINATOR_ALLOWED_TOOLS)


def system_prompt_suffix() -> str:
    """返回 Coordinator 系统提示词后缀（F55）。"""
    return COORDINATOR_SYSTEM_PROMPT_SUFFIX
