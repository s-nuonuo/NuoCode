# NuoCode

Claude Code 风格的终端 AI Agent，支持 Anthropic / OpenAI 双协议，内置权限防御、上下文压缩、会话持久化、Skill 扩展、Hook 生命周期挂钩等完整功能。

---

## 快速开始

### 1. 克隆并安装依赖

推荐使用 [uv](https://github.com/astral-sh/uv)：

```bash
git clone https://github.com/s-nuonuo/NuoCode.git
cd NuoCode
uv sync
```

也可以用 pip（需要 Python ≥ 3.12）：

```bash
pip install -e ".[dev]"
```

### 2. 创建配置文件

项目附带了配置示例文件，**直接复制并填入你的 API Key**：

```bash
cp .nuocode/config.yaml.example .nuocode/config.yaml
```

然后编辑 `.nuocode/config.yaml`，将 `REPLACE_ME` 替换为真实的 API Key：

```yaml
providers:
  - name: claude-sonnet
    protocol: anthropic
    api_key: sk-ant-你的密钥          # ← 替换这里
    model: claude-sonnet-4
    context_window: 200000
```

> **注意**：`config.yaml` 含有密钥，已被 `.gitignore` 排除，不会提交到 git。

### 3. （可选）配置权限

```bash
cp .nuocode/settings.yaml.example .nuocode/settings.local.yaml
# 编辑 settings.local.yaml 按需配置 allow / deny 规则
```

### 4. 启动

```bash
# 直接运行
uv run nuocode

# 或装好后
nuocode
```

---

## 目录结构

```
NuoCode/
├── src/nuocode/          # 源码包
│   ├── agent/            # ReAct 循环 + Hook 接入
│   ├── cli.py            # CLI 入口
│   ├── command/          # /help /hooks 等内置命令
│   ├── compact/          # 上下文压缩（layer1 落盘 + layer2 摘要）
│   ├── config.py         # 配置加载
│   ├── conversation.py   # 对话对象
│   ├── hook/             # 生命周期 Hook 系统（chap12）
│   ├── instructions.py   # 项目指令加载（nuocode.md）
│   ├── llm/              # Anthropic / OpenAI provider
│   ├── mcp/              # MCP 工具客户端
│   ├── memory/           # 项目/用户记忆管理
│   ├── permission/       # 五层权限防御
│   ├── prompt/           # 系统提示 + environment + reminder
│   ├── session/          # 会话 JSONL 落盘
│   ├── skills/           # Skill 扩展系统（chap11）
│   ├── tool/             # 内置工具（Read/Write/Edit/Bash/Glob/Grep）
│   └── tui/              # Textual TUI
├── tests/                # pytest 测试（342 个）
├── .nuocode/
│   ├── config.yaml.example    # 配置示例（可提交）
│   └── settings.yaml.example  # 权限配置示例（可提交）
└── pyproject.toml
```

---

## 配置说明

### `.nuocode/config.yaml`（必须，**不提交**）

| 字段 | 说明 |
|------|------|
| `providers[].protocol` | `anthropic` 或 `openai` |
| `providers[].api_key` | API 密钥 |
| `providers[].model` | 模型名称（如 `claude-sonnet-4`、`gpt-4o`） |
| `providers[].base_url` | 可选，自定义 API 地址（兼容 OpenAI 协议的第三方服务） |
| `providers[].context_window` | 可选，上下文窗口大小，影响自动压缩阈值 |
| `providers[].thinking` | 可选，Anthropic extended thinking 开关 |

多个 provider 启动时会显示选择列表。

### 权限配置（可选）

三层配置，优先级：**本地 > 项目 > 用户**

| 文件 | 层级 | 是否提交 |
|------|------|---------|
| `~/.nuocode/settings.yaml` | 用户级 | — |
| `.nuocode/settings.yaml` | 项目级 | ✅ 可提交 |
| `.nuocode/settings.local.yaml` | 本地级（个人放行） | ❌ 已 gitignore |

```yaml
# settings.local.yaml 示例
default_mode: default  # default / plan / auto / full
permissions:
  allow:
    - "Bash(git *)"
    - "Read"
  deny:
    - "Bash(rm *)"
```

### 项目指令（可选）

在项目根目录创建 `nuocode.md`，内容会自动注入到每次对话的系统提示：

```bash
echo "你是这个项目的 AI 助手，请用中文回复。" > nuocode.md
```

也支持 `@include <路径>` 引入其他文件，最多嵌套 5 层。

### Hook 生命周期挂钩（可选）

在 `.nuocode/hooks.yaml` 定义自定义 Hook：

```yaml
hooks:
  - name: notify-on-tool
    event: PostToolUse
    action:
      type: prompt
      text: "请简述刚才执行的工具操作。"

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
        echo "$input" | grep -q "rm -rf" && { echo "危险命令被拦截" >&2; exit 2; } || exit 0
```

支持事件：`SessionStart`、`SessionEnd`、`SessionResume`、`UserPromptSubmit`、`Stop`、`PreUserMessage`、`PreToolUse`（可拦截）、`PostToolUse`、`PreCompact`、`PostCompact`、`Notification`。

---

## 开发

```bash
# 运行测试
uv run pytest

# 代码检查
uv run ruff check .
uv run ruff format --check .
```

---

## 许可证

MIT
