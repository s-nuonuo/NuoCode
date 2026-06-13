"""nuocode CLI 入口：加载配置 → 启动 TUI。"""

from __future__ import annotations

import sys

from nuocode.config import ConfigError, load


def main() -> None:
    try:
        cfg = load(".nuocode/config.yaml")
    except ConfigError as e:
        print(f"[nuocode] 配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 延迟导入 textual：让配置错误更快返回，并避免无配置时强行加载 TUI 依赖。
    from nuocode.tool import new_default_registry
    from nuocode.tui.app import NuoCodeApp

    registry = new_default_registry()
    app = NuoCodeApp(cfg.providers, registry)
    try:
        app.run()
    except KeyboardInterrupt:
        return
    except Exception as e:  # noqa: BLE001
        print(f"[nuocode] 运行异常: {e}", file=sys.stderr)
        sys.exit(1)
