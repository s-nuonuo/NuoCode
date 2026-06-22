---
name: commit
description: 分析 git diff 并生成规范的 commit
allowed_tools:
  - bash
  - read_file
  - grep
mode: inline
---

你将按下面的 SOP 帮用户提交一次 git commit：

1. 先用 `bash` 跑 `git status -s` 与 `git diff --stat` 了解变更范围。
2. 再用 `bash` 跑 `git diff --cached`（若有 staged）/ `git diff` 仔细阅读变更内容。
3. 必要时用 `read_file` 打开关联文件确认上下文。
4. 总结一条规范的 commit 信息（建议遵循 Conventional Commits：`type(scope): subject`）。
5. 如用户尚未 `git add`，先用 `bash` 执行 `git add -A` 或精确路径添加。
6. 用 `bash` 执行 `git commit -m "<message>"`。
7. 最后输出 commit hash 与一句话总结。

注意事项：
- 严禁 `git push`；仅本地提交。
- 如 working tree 干净则告知用户"无可提交变更"并退出。

$ARGUMENTS
