"""会话目录过期清理。"""

from __future__ import annotations

import datetime as _dt
import logging
import shutil
from pathlib import Path

from nuocode.compact.state import parse_session_time

logger = logging.getLogger(__name__)


async def clean_expired(sessions_dir: str, max_age: _dt.timedelta) -> None:
    """异步清理超过 ``max_age`` 的会话目录。

    - 只处理新格式 ID（能解析时间戳）的目录；旧格式跳过。
    - 删除单个目录失败时记录日志但继续。
    - 函数体内不调用阻塞操作的异步等待，仅以 async 方式提供，便于
      ``asyncio.create_task`` 后台运行。
    """
    p = Path(sessions_dir)
    if not p.is_dir():
        return
    now = _dt.datetime.now()
    for child in p.iterdir():
        if not child.is_dir():
            continue
        try:
            ts = parse_session_time(child.name)
        except ValueError:
            continue  # 旧格式保留
        if now - ts <= max_age:
            continue
        try:
            shutil.rmtree(str(child))
        except OSError as e:
            logger.warning("清理会话目录失败: %s (%s)", child, e)


__all__ = ["clean_expired"]
