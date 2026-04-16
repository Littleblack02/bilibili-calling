# DeerFlow Harness

本目录包含 DeerFlow Agent 框架的本地安装版本。

## 说明

DeerFlow 是一个基于 LangGraph 的多 Agent 协作框架，提供了：
- Agent 编排和管理
- 工具调用和中间件
- 记忆系统
- 技���系统
- 多模态支持

## 安装

```bash
pip install -e ./backend/packages/harness
```

## 配置

主配置文件在项目根目录的 `config.yaml`，包含：
- 模型配置
- 工具注册
- Agent 配置
- 技能配置

## 目录结构

```
backend/packages/harness/
├── deerflow/
│   ├── agents/          # Agent 实现
│   ├── tools/           # 内置工具
│   ├── config/          # 配置管理
│   ├── models/          # 模型适配器
│   ├── middlewares/     # 中间件
│   ├── runtime/         # 运行时支持
│   └── skills/          # 技能系统
├── pyproject.toml       # 包配置
└── langgraph.json       # LangGraph 配置
```

## 使用示例

在 `app/main.py` 中初始化 DeerFlow 客户端：

```python
from deerflow.client import DeerFlowClient

client = DeerFlowClient(
    config_path="config.yaml",
    thinking_enabled=False,
    subagent_enabled=True
)

# 使用客户端进行对话
response = client.chat("你好", thread_id="user_123")
```

## 自定义

可以通过修改 `config.yaml` 来配置：
- 使用的模型
- 启用的工具
- Agent 行为
- 记忆系统参数
- 技能加载路径

## 文档

详细文档请参考 DeerFlow 官方文档（如果有的话）。