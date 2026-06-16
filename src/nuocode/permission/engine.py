"""权限引擎：前四层流水线 + 配置加载 + 启动模式 + 永久放行写入。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from nuocode.llm import ToolCall
from nuocode.permission import Category, Decision, Mode, SettingsError, parse_mode
from nuocode.permission.blacklist import hits_blacklist
from nuocode.permission.rule import RuleSet
from nuocode.permission.sandbox import resolve_root, sandbox_ok
from nuocode.permission.settings import (
    categorize,
    extract_target,
    friendly_name,
    load_settings,
    to_rule_set,
)

logger = logging.getLogger(__name__)


@dataclass
class Engine:
    root: str
    user: RuleSet = field(default_factory=RuleSet)
    project: RuleSet = field(default_factory=RuleSet)
    local: RuleSet = field(default_factory=RuleSet)
    local_path: str = ""
    _start_mode: Mode = Mode.DEFAULT

    def start_mode(self) -> Mode:
        return self._start_mode

    def check(self, mode: Mode, call: ToolCall, read_only: bool) -> tuple[Decision, str]:
        """前四层判定（短路）。"""
        cat = categorize(call.name, read_only)
        friendly = friendly_name(call.name)
        target, is_file, ok = extract_target(call)

        # ① 黑名单（仅命令执行；任何配置/模式/bypass 不可放开）
        if cat == Category.EXEC and target and hits_blacklist(target):
            preview = target if len(target) <= 60 else target[:60] + "…"
            return (Decision.DENY, f"命中危险命令黑名单：{preview}")

        # ② 沙箱（仅文件类）
        if is_file:
            if not ok:
                return (Decision.DENY, "无法解析文件路径参数，安全拒绝")
            if not sandbox_ok(self, target):
                return (Decision.DENY, f"路径在项目目录之外：{target}")

        # ③ 三级规则（local > project > user，就近命中即返）
        match_target = _match_target(call.name, target, is_file, self.root)
        for rs in (self.local, self.project, self.user):
            d, hit = rs.match(friendly, match_target)
            if hit:
                if d == Decision.DENY:
                    return (
                        Decision.DENY,
                        f"匹配 deny 规则：{friendly}({_pat_preview(match_target)})",
                    )
                return (Decision.ALLOW, "")

        # ④ 模式兜底
        d = mode_fallback(mode, cat)
        if d == Decision.ALLOW:
            return (Decision.ALLOW, "")
        cat_name = {Category.READ: "只读", Category.WRITE: "文件写", Category.EXEC: "命令执行"}[cat]
        return (Decision.ASK, f"{mode} 模式下 {cat_name} 类操作需确认")

    def persist_local_allow(self, call: ToolCall) -> None:
        """永久放行：精确规则写入本地层文件 + 同步内存。"""
        # 延迟导入，避免循环
        from nuocode.permission.persist import rule_for

        rule, rule_str, ok = rule_for(call, self.root)
        if not ok:
            return
        # 加载现有 settings、追加去重
        try:
            s = load_settings(self.local_path)
        except SettingsError:
            # 现有文件损坏：从空开始覆盖（安全：不丢失已有 deny 也不可能，因为损坏必先降级；
            # 这里采取保守策略——直接创建新内容，避免失败）
            from nuocode.permission.settings import PermissionsBlock, Settings

            s = Settings(permissions=PermissionsBlock())
        if rule_str not in s.permissions.allow:
            s.permissions.allow.append(rule_str)
        # 写文件
        Path(self.local_path).parent.mkdir(parents=True, exist_ok=True)
        import yaml

        out: dict = {}
        if s.default_mode:
            out["default_mode"] = s.default_mode
        out["permissions"] = {
            "allow": s.permissions.allow,
            "deny": s.permissions.deny,
        }
        Path(self.local_path).write_text(
            yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        # 同步内存
        if not any(
            r.tool == rule.tool and r.pattern == rule.pattern and r.allow for r in self.local.allow
        ):
            self.local.allow.append(rule)


def _match_target(internal_name: str, target: str, is_file: bool, root: str) -> str:
    """规则匹配的目标：文件类用项目相对 slash 路径；命令类用命令串。"""
    if not is_file:
        return target
    if not target:
        return ""
    p = Path(target)
    if not p.is_absolute():
        p = Path(root) / p
    try:
        rel = p.resolve(strict=False).relative_to(Path(root))
        return str(rel).replace("\\", "/")
    except (ValueError, OSError):
        return str(p).replace("\\", "/")


def _pat_preview(s: str) -> str:
    return s if len(s) <= 60 else s[:60] + "…"


def mode_fallback(mode: Mode, cat: Category) -> Decision:
    """F5 矩阵：只产 ALLOW / ASK。"""
    if cat == Category.READ:
        return Decision.ALLOW
    if mode == Mode.BYPASS:
        return Decision.ALLOW
    if mode == Mode.ACCEPT_EDITS and cat == Category.WRITE:
        return Decision.ALLOW
    return Decision.ASK


def new_engine(root: str) -> tuple[Engine, Exception | None]:
    """构造引擎：解析 root、加载三层配置、确定启动模式。

    - 配置文件读/解析失败仅降级该文件为空，**不**致 new_engine 失败。
    - resolve_root 失败时仍返回非 None 空规则安全引擎 + err。
    """
    err: Exception | None = None
    try:
        resolved = resolve_root(root)
    except Exception as e:  # noqa: BLE001
        err = e
        # 退化：root 用传入值（保证 cli 注入永不为 None）。
        engine = Engine(root=root, local_path=str(Path(root) / ".nuocode" / "settings.local.yaml"))
        return (engine, err)

    user_path = str(Path.home() / ".nuocode" / "settings.yaml")
    project_path = str(Path(resolved) / ".nuocode" / "settings.yaml")
    local_path = str(Path(resolved) / ".nuocode" / "settings.local.yaml")

    user_rs, user_dm = _load_rs(user_path)
    project_rs, project_dm = _load_rs(project_path)
    local_rs, local_dm = _load_rs(local_path)

    # 启动模式：local > project > user，皆无→DEFAULT
    start = Mode.DEFAULT
    for dm in (local_dm, project_dm, user_dm):
        if dm:
            m, ok = parse_mode(dm)
            if ok:
                start = m
                break

    engine = Engine(
        root=resolved,
        user=user_rs,
        project=project_rs,
        local=local_rs,
        local_path=local_path,
        _start_mode=start,
    )
    return (engine, None)


def _load_rs(path: str) -> tuple[RuleSet, str]:
    try:
        s = load_settings(path)
    except SettingsError as e:
        logger.warning("权限配置降级（%s）：%s", path, e)
        return (RuleSet(), "")
    except Exception as e:  # noqa: BLE001
        logger.warning("权限配置读取异常（%s）：%s", path, e)
        return (RuleSet(), "")
    return (to_rule_set(s), s.default_mode)


__all__ = ["Engine", "mode_fallback", "new_engine"]
