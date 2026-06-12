# nuocode

Claude Code 风格的终端 AI Agent。chap02 阶段：多协议（Anthropic / OpenAI）LLM 终端对话客户端。

## 安装

```bash
uv sync           # 推荐
# 或
pip install -e ".[dev]"
```

## 配置

```bash
cp .nuocode/config.yaml.example .nuocode/config.yaml
# 编辑 .nuocode/config.yaml 填入 api_key / model
```

## 运行

```bash
python -m nuocode
# 或装好后直接：
nuocode
```

## 测试

```bash
pytest
ruff check .
ruff format --check .
```
