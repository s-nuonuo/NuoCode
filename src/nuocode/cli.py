"""nuocode CLI 入口：加载配置 → 构造权限引擎 → 启动 TUI。"""

from __future__ import annotations

import sys
from pathlib import Path

from nuocode.config import ConfigError, load


def main() -> None:
    try:
        cfg = load(".nuocode/config.yaml")
    except ConfigError as e:
        print(f"[nuocode] 配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    from nuocode import permission
    from nuocode.tool import new_default_registry
    from nuocode.tui.app import NuoCodeApp

    root = str(Path.cwd().resolve())
    engine, perm_err = permission.new_engine(root)
    if perm_err is not None:
        print(f"[nuocode] 权限引擎降级: {perm_err}", file=sys.stderr)

    registry = new_default_registry()
    app = NuoCodeApp(cfg.providers, registry, engine)
    try:
        app.run()
    except KeyboardInterrupt:
        return
    except Exception as e:  # noqa: BLE001
        print(f"[nuocode] 运行异常: {e}", file=sys.stderr)
        sys.exit(1)
