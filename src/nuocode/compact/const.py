"""compact 包硬编码常量集合（不暴露为配置项）。"""

from __future__ import annotations

# 单条工具结果落盘阈值（UTF-8 字节）
SINGLE_RESULT_LIMIT: int = 50000

# 单条 RoleTool 消息内工具结果聚合阈值（UTF-8 字节）
MESSAGE_AGGREGATE_LIMIT: int = 200000

# 给摘要 LLM 输出预留的 token 空间
SUMMARY_RESERVE: int = 20000

# 自动触发的额外安全余量：防估算误差与单轮波动
AUTO_SAFETY_MARGIN: int = 13000

# 手动触发的安全余量：只用来判断摘要请求本身是否能塞下
MANUAL_SAFETY_MARGIN: int = 3000

# 恢复段最多展示几个文件
RECOVERY_FILE_LIMIT: int = 5

# 单个文件快照的 token 上限（超出时保留头部、截掉尾部）
RECOVERY_TOKENS_PER_FILE: int = 5000

# 摘要后保留近期原文的 token 下界
RECENT_KEEP_TOKENS: int = 10000

# 摘要后保留近期原文的条数下界
RECENT_KEEP_MESSAGES: int = 5

# 自动摘要熔断阈值（连续失败次数达到即跳闸）
MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES: int = 3

# 摘要请求自身 PTL 的"直接重试"次数
PTL_RETRY_LIMIT: int = 3

# 3 次直接重试用光后，每次再丢的比例
PTL_DROP_PERCENTAGE: float = 0.2

# 字符 → token 估算比（用于两次真实 usage 之间的增量估算）
ESTIMATE_CHARS_PER_TOKEN: float = 3.5

# 预览体头部字节数上限
PREVIEW_HEAD_BYTES: int = 2048

# 预览体头部行数上限
PREVIEW_HEAD_LINES: int = 20
