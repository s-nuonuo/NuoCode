"""共用文件锁工具（chap15 T9）。

从 mailbox/lock.py 抽出，mailbox 与 tasks 共用同一套 acquire_lock 实现。

使用方式：
    async with acquire(lock_path):
        # 持锁区间
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from contextlib import asynccontextmanager
from pathlib import Path

# ── 常量 ─────────────────────────────────────────────────────────────────────

LOCK_MAX_RETRIES = 10
LOCK_STALE_AFTER = 10.0       # 秒：锁文件超过此时间视为 stale
LOCK_BACKOFF_MIN = 0.005      # 秒
LOCK_BACKOFF_MAX = 0.1        # 秒


@asynccontextmanager
async def acquire(lock_path: str):
    """抢占文件锁，成功后 yield，退出时释放（T5）。

    - 使用 os.open(O_CREAT|O_EXCL|O_WRONLY) 原子创建锁文件
    - 失败时按 5-100ms 随机抖动重试，最多 10 次
    - 持锁超过 10 秒视为 stale，删除后立即重试一次
    """
    lock_path = str(lock_path)
    acquired = False
    fd = -1

    for _attempt in range(LOCK_MAX_RETRIES):
        try:
            fd = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
            # 成功获取锁
            acquired = True
            break
        except FileExistsError:
            # 检查是否 stale
            try:
                st = Path(lock_path).stat()
                if time.time() - st.st_mtime > LOCK_STALE_AFTER:
                    # stale 锁，删除并立即重试
                    try:
                        os.unlink(lock_path)
                    except OSError:
                        pass
                    # 不 sleep，直接下一次循环
                    continue
            except FileNotFoundError:
                # 锁文件在我们检查时已被删除，直接重试
                continue
            except OSError:
                pass

            # 随机抖动等待
            delay = random.uniform(LOCK_BACKOFF_MIN, LOCK_BACKOFF_MAX)
            await asyncio.sleep(delay)
        except OSError as e:
            # 其他 OS 错误（权限等），直接抛出
            raise RuntimeError(f"无法创建锁文件 {lock_path}: {e}") from e

    if not acquired:
        raise RuntimeError(
            f"获取文件锁失败，超过最大重试次数 {LOCK_MAX_RETRIES}: {lock_path}"
        )

    try:
        yield
    finally:
        # 释放锁
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(lock_path)
        except OSError:
            pass
