# NuoCode

Claude Code 风格的终端 AI Agent，支持 Anthropic / OpenAI 双协议。

内置完整功能栈：**权限防御 · 上下文压缩 · 会话持久化 · Skill 扩展 · Hook 生命周期 · SubAgent 并发 · Git Worktree 隔离 · Agent Team 多智能体协作**。

---

## 目录

- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [配置详解](#配置详解)
- [功能概览](#功能概览)
- [目录结构](#目录结构)
- [开发指南](#开发指南)
- [常见问题](#常见问题)

---

## 环境要求

| 要求 | 版本 |
|------|------|
| Python | **≥ 3.12** |
| 操作系统 | macOS / Linux |
| （推荐）uv | 任意最新版 |

> **注意**：`StrEnum` 等特性依赖 Python 3.12+，低版本会直接报错。

---

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/s-nuonuo/NuoCode.git
cd NuoCode
```

### 2. 安装依赖

**方案 A（推荐）：使用 uv**

```bash
# 如果没有 uv，先安装
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建虚拟环境并同步依赖（会读取 uv.lock，版本精确复现）
uv sync
```

**方案 B：使用 pip**

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. 创建 API 配置

```bash
cp .nuocode/config.yaml.example .nuocode/config.yaml
```

用任意编辑器打开 `.nuocode/config.yaml`，把 `REPLACE_ME` 换成你的真实 API Key：

```yaml
providers:
  - name: claude-sonnet
    protocol: anthropic
    api_key: sk-ant-你的密钥          # ← 填入 Anthropic API Key
    model: claude-sonnet-4
    context_window: 200000

  # 可选：同时配置 OpenAI 兼容接口（多 provider 启动时会显示选择列表）
  - name: deepseek-v4-pro
    protocol: openai
    api_key: sk-你的密钥
    model: deepseek-v4-pro
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    context_window: 128000
```

> `config.yaml` 含有密钥，已被 `.gitignore` 排除，不会上传到 git。

### 4. 启动

```bash
# 使用 uv（推荐）
uv run nuocode

# 或激活虚拟环境后直接运行
source .venv/bin/activate
nuocode
```

启动后进入 TUI 界面，直接输入问题与 AI 对话即可。按 `Ctrl+C` 退出。

---

## 配置详解

### `.nuocode/config.yaml`（必须，不提交 git）

完整字段说明：

```yaml
providers:
  - name: 显示名称（任意）
    protocol: anthropic   # 或 openai
    api_key: sk-...
    model: claude-sonnet-4
    base_url: https://...  # 可选，自定义 API 地址（兼容 OpenAI 的第三方服务）
    context_window: 200000 # 可选，影响上下文压缩阈值
    thinking: true         # 可选，仅 Anthropic extended thinking

# chap15：Agent Team 功能开关（可选）
features:
  coordinator_mode: false  # Coordinator Mode：Lead 只调度不写代码
  fork_teammate: false     # 允许队员再 fork 子 Agent
```

### 权限配置（可选）

三层权限配置，优先级：**本地 > 项目 > 用户**

| 文件 | 层级 | 是否提交 |
|------|------|---------:|
| `~/.nuocode/settings.yaml` | 用户级 | 否 |
| `.nuocode/settings.yaml` | 项目级 | ✅ 可提交 |
| `.nuocode/settings.local.yaml` | 本地级（个人放行） | ❌ gitignore |

```bash
# 从示例创建本地权限配置
cp .nuocode/settings.yaml.example .nuocode/settings.local.yaml
```

```yaml
# settings.local.yaml 示例
default_mode: default   # default / plan / accept_edits / bypass

permissions:
  allow:
    - "Bash(git *)"
    - "Bash(pytest)"
    - "Read"
  deny:
    - "Bash(rm -rf *)"
    - "Read(.env)"
```

权限模式说明：

| 模式 | 行为 |
|------|------|
| `default` | 写操作需逐次确认 |
| `plan` | 只读，不执行写操作 |
| `accept_edits` | 写文件自动放行，bash 仍需确认 |
| `bypass` | 全部自动放行（⚠️ 谨慎使用） |

### 项目指令（可选）

在项目根目录创建 `nuocode.md`，内容自动注入系统提示（最高优先级）：

```bash
cat > nuocode.md << 'EOF'
你是这个项目的 AI 助手，请始终用中文回复。
代码风格遵循 PEP 8，测试框架为 pytest。
EOF
```

支持 `@include <相对路径>` 引用其他文件，最多嵌套 5 层。

### Hook 配置（可选）

在 `.nuocode/hooks.yaml` 定义生命周期钩子：

```yaml
hooks:
  - name: block-dangerous-bash
    event: PreToolUse
    if:
      all_of:
        - field: tool_name
          match: {type: exact, value: Bash}
    action:
      type: shell
      command: |
        input=$(cat)
        echo "$input" | grep -qE "rm -rf|format|fdisk" \
          && { echo "危险命令被拦截" >&2; exit 2; } || exit 0
```

支持事件：`SessionStart` · `UserPromptSubmit`（可拦截）· `PreToolUse`（可拦截）· `PostToolUse` · `PreCompact` · `PostCompact` · `Stop` · `Notification`

---

## 功能概览

### TUI 界面

| 操作 | 说明 |
|------|------|
| 直接输入 + Enter | 发送消息 |
| Alt+Enter | 消息内换行 |
| Shift+Tab | 切换权限模式 |
| Ctrl+C | 取消当前流式输出 / 退出 |
| `/help` | 显示所有命令 |

### 内置 Slash 命令

| 命令 | 说明 |
|------|------|
| `/plan` | 切换到 Plan 模式（只读） |
| `/do` | 切回 Default 模式并执行计划 |
| `/compact` | 手动触发上下文压缩 |
| `/clear` | 清空当前会话，开启新 session |
| `/resume` | 从历史会话恢复 |
| `/session` | 显示会话 ID 与存档路径 |
| `/status` | 模式 / 用量 / 工具 / 模型概览 |
| `/memory` | 列出已加载的记忆文件 |
| `/hooks` | 列出已加载的 Hook 规则 |
| `/skill <name>` | 激活 Skill 扩展 |
| `/worktree` | 管理 Git Worktree（create/list/enter/exit/remove） |
| `/team` | 管理 Agent Team（list/info/delete/kill） |
| `/exit` | 退出 |

### SubAgent 并发（chap13）

通过 `Agent` 工具在对话中启动子 Agent：

```
帮我用后台子 Agent 并行执行以下 3 个任务：
1. 搜索所有 TODO 注释
2. 检查测试覆盖率
3. 生成 API 文档
```

- **定义式**：指定 `subagent_type` 选择预定义角色（Explore / Plan / general-purpose 等）
- **Fork 式**：不指定类型，克隆当前上下文独立执行，强制后台
- 通过 `/status` 或 `TaskList` 工具查看后台任务状态

### Git Worktree 隔离（chap14）

为长任务创建独立工作树，避免污染主分支：

```
/worktree create feature-login
/worktree list
/worktree enter feature-login
# ... 在隔离环境中工作 ...
/worktree exit --remove
```

### Agent Team 多智能体协作（chap15）

Lead + Teammates 架构，支持三种后端：

| 后端 | 触发条件 | 说明 |
|------|----------|------|
| `in-process` | 无 tmux/iTerm2 时自动选用 | 同进程内并发 |
| `tmux` | 在 tmux session 中运行时 | 每个队员一个 pane |
| `iterm2` | 在 iTerm2 中运行时 | 每个队员一个 split pane |

```
# 创建团队并派遣队员
用 TeamCreate 创建一个叫 "refactor-team" 的团队，
然后派 3 个队员并行重构 src/nuocode/tool/ 下的所有工具文件。
```

队员专属工具：`TaskCreate` · `TaskGet` · `TaskList` · `TaskUpdate` · `SendMessage`

**Coordinator Mode**（双锁启用）：

```yaml
# config.yaml
features:
  coordinator_mode: true

# 同时设置环境变量
export nuocode_COORDINATOR_MODE=true
```

开启后 Lead 的 `write_file` / `edit_file` 工具被移除，强制其专注调度而非亲自写代码。

---

## 目录结构

```
NuoCode/
├── src/nuocode/
│   ├── __main__.py          # python -m nuocode 入口（支持 --team-member）
│   ├── cli.py               # 主 CLI 装配（config → tools → TUI）
│   ├── cli/
│   │   └── team_member.py   # --team-member 自治循环（Pane 后端子进程）
│   ├── agent/               # ReAct 循环 + 审批流 + 队员上下文
│   │   ├── agent_tool.py    # Agent 工具（SubAgent / Team spawn）
│   │   ├── team_hook.py     # TeamHook Protocol + TeammateContext
│   │   └── team_mailbox.py  # Loop 头部邮件注入
│   ├── command/             # Slash 命令体系
│   │   └── builtin_team.py  # /team 命令族
│   ├── compact/             # 上下文压缩（layer1 落盘 + layer2 摘要）
│   ├── config.py            # 配置加载（含 FeaturesConfig）
│   ├── conversation.py      # 对话对象
│   ├── coordinator/         # Coordinator Mode（双锁 + 提示词后缀）
│   ├── hook/                # 生命周期 Hook 引擎
│   ├── instructions.py      # nuocode.md 项目指令加载
│   ├── llm/                 # Anthropic / OpenAI provider
│   ├── mcp/                 # MCP 工具客户端
│   ├── memory/              # 项目/用户记忆管理
│   ├── permission/          # 五层权限防御（Engine / Mode / Outcome）
│   ├── prompt/              # 系统提示 + environment + reminder
│   ├── session/             # 会话 JSONL 落盘
│   ├── skills/              # Skill 扩展（builtin + user + project）
│   ├── subagent/            # SubAgent 定义解析与 Catalog
│   ├── task/                # 后台任务 Manager（on_task_done 回调）
│   ├── team/                # Agent Team 完整实现
│   │   ├── types.py         # BackendType, Team, TeammateInfo
│   │   ├── persistence.py   # sanitize, atomic_write_json
│   │   ├── manager.py       # 团队生命周期管理
│   │   ├── spawn.py         # spawn_teammate 主流程
│   │   ├── filelock.py      # 文件锁（O_CREAT|O_EXCL + 随机 backoff）
│   │   ├── mailbox/         # 跨进程文件邮箱
│   │   ├── registry/        # AgentNameRegistry 双向映射
│   │   ├── tasks/           # 共享任务列表 Store
│   │   ├── backend/         # tmux / iterm2 / in-process 后端
│   │   └── tools/           # 7 个协作工具
│   ├── tool/                # 内置工具（Read/Write/Edit/Bash/Glob/Grep）
│   │   └── filter.py        # 多层工具过滤（含 TEAMMATE_EXTRA_TOOLS）
│   ├── tui/                 # Textual TUI
│   └── worktree/            # Git Worktree 隔离
├── tests/                   # pytest 测试套件（583 个）
├── .nuocode/
│   ├── config.yaml.example  # API 配置示例（可提交）
│   └── settings.yaml.example # 权限配置示例（可提交）
├── pyproject.toml
└── uv.lock                  # 精确依赖锁定
```

---

## 开发指南

### 运行测试

```bash
# 全套测试
uv run pytest

# 仅运行某章节测试
uv run pytest tests/test_chap15.py -v

# 快速冒烟
uv run pytest -x -q
```

### 代码检查

```bash
# lint
uv run ruff check .

# 自动修复
uv run ruff check --fix .

# 格式检查
uv run ruff format --check .
```

### 添加自定义 SubAgent 角色

在 `.nuocode/agents/` 目录下创建 Markdown 文件（项目级，优先级高于内置）：

```markdown
---
name: code-reviewer
description: 专注代码审查，输出结构化 Review 报告
model: haiku
permission_mode: plan
max_turns: 20
---

你是资深代码审查员。审查时关注：
1. 潜在 bug 与边界情况
2. 代码可读性与命名规范
3. 测试覆盖缺口

输出格式：
- 严重问题（必须修）
- 建议优化
- 值得称赞的地方
```

也可放在 `~/.nuocode/agents/`（用户级，对所有项目生效）。

### 添加 Skill

在 `.nuocode/skills/` 目录下创建 Markdown 文件：

```markdown
---
name: git-commit
description: 自动生成规范的 git commit message
---

分析 `git diff --staged` 输出，按照 Conventional Commits 规范
生成 commit message，然后执行 `git commit -m "..."` 提交。
```

---

## 常见问题

**Q: 启动报 `ModuleNotFoundError: No module named 'textual'`**

没有正确安装依赖。确保使用 `uv sync` 或 `pip install -e ".[dev]"` 安装，不要用系统 python 直接运行。

---

**Q: 配置文件在哪里？为什么 git 里没有 `config.yaml`？**

`.nuocode/config.yaml` 含有 API Key，已被 `.gitignore` 排除，不会提交到 git。
需要自己执行 `cp .nuocode/config.yaml.example .nuocode/config.yaml` 并填入密钥。

---

**Q: 如何只用单一 Provider（不显示选择列表）？**

`config.yaml` 中只配置一个 `providers` 条目即可，启动时自动进入对话界面。

---

**Q: `uv sync` 很慢或失败？**

尝试指定国内镜像：

```bash
uv sync --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

或使用 pip 方案：

```bash
pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

**Q: Agent Team 功能怎么用？**

1. 直接对话告诉 AI 创建团队并派遣队员（AI 会调用 `TeamCreate` / `Agent` 工具）
2. 或使用 `/team list` 查看现有团队

后端自动检测：在 tmux 中运行自动使用 tmux 后端（每个队员开新 pane）；不在终端复用器中则使用 in-process 后端（同进程并发）。

---

**Q: 如何开启 Coordinator Mode（Lead 只调度不写代码）？**

需要同时满足两个条件（双锁设计，防止误触发）：

```yaml
# .nuocode/config.yaml
features:
  coordinator_mode: true
```

```bash
export nuocode_COORDINATOR_MODE=true
uv run nuocode
```

---

**Q: Python 版本不够怎么办？**

```bash
# 用 uv 安装指定版本的 Python
uv python install 3.12
uv sync
```

---

## 许可证

MIT
