"""task 包：后台任务管理（chap13 F14-F19）。

提供：
- ``BackgroundTask``：后台任务状态容器
- ``Manager``：后台任务管理器

公共接口：
    from nuocode.task import Manager, BackgroundTask
"""

from nuocode.task.manager import BackgroundTask, Manager

__all__ = ["BackgroundTask", "Manager"]
