---
name: test
description: 运行项目测试并分析失败原因
allowed_tools:
  - bash
  - read_file
  - grep
  - glob
mode: inline
---

按下面 SOP 跑项目测试并分析结果：

1. 用 `glob` / `read_file` 检测项目类型：
   - `pyproject.toml` / `pytest.ini` → Python (pytest)
   - `package.json` → Node (npm test / yarn test)
   - `Cargo.toml` → Rust (cargo test)
   - `go.mod` → Go (go test ./...)
2. 用 `bash` 运行对应的测试命令（默认走全量；若用户传入子集路径则限定范围）。
3. 若测试失败，逐个失败点用 `read_file` 打开源码与测试文件分析根因，给出 1-2 条修复建议。
4. 若全部通过，给出耗时与覆盖率（如有）的简短总结。

注意：不要主动修改代码——本 Skill 只跑测试和分析；要修复请用户后续指示。

$ARGUMENTS
