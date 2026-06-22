# SynapseX - 面向多智能体协作的低开销通信、状态传递与共享记忆机制

基于 LangGraph 框架的多智能体研究系统，支持 OpenAI 兼容 Chat 后端（默认 DeepSeek）和本地 Transformers 后端（默认模型路径 `/data/models/Qwen3-8B`）。

## 功能覆盖

| # | 需求 | 实现方式 |
|---|------|---------|
| 1 | ≥3 Agent 协同（规划/检索/执行/总结） | 4 个 Agent 节点：planner → retriever(s) → executor → summarizer |
| 2 | 结构化通信协议 | TypedDict 状态 + Channel 系统（LastValue / BinaryOperatorAggregate） |
| 3 | 非文本中间状态传递 | Hidden state 传递 + Context Packet 压缩 + Embedding 向量 |
| 4 | 共享记忆模块 | InMemoryStore + JSONL 长期记忆，支持 put/get/search 与进程重启后加载 |
| 5 | ≥2 组关联连续任务 | `run_demo.py` 跑 A/B 两组关联任务；`run_12rounds.py` 跑 12 轮连续任务 |
| 6 | 性能对比数据 | TEXT vs STRUCTURED 模式对比（tokens、时延、findings） |

## 快速开始

```bash
# 1. 安装基础依赖（DashScope 用于高质量 embedding；不设置 key 时使用本地 fallback）
pip install langgraph langchain-core langchain-openai dashscope numpy

# 2A. 选择本地 Transformers 后端（默认 /data/models/Qwen3-8B）
pip install transformers torch accelerate
export CHAT_BACKEND=transformers
export CHAT_MODEL=qwen3-8b
export LOCAL_MODEL_PATH=/data/models/Qwen3-8B
export LOCAL_MODEL_DEVICE=cuda:0

# 2B. 或选择 OpenAI 兼容后端（默认 DeepSeek 配置）
# export CHAT_BACKEND=openai
# export CHAT_API_KEY="your-chat-api-key"
# export CHAT_BASE_URL="https://api.deepseek.com"
# export CHAT_MODEL="deepseek-chat"

# 可选：启用 DashScope text-embedding-v4；不设置则使用 LocalHashEmbeddings
# export DASHSCOPE_API_KEY="your-dashscope-key"

# 3. 运行 demo
cd /data/mingwei/SynapseX
python run_demo.py
```

## 架构图

```
Task A:
  query → [planner] ──Send──→ [retriever_1 ∥ retriever_2 ∥ retriever_3]
                                    │              │              │
                                    └──────────────┴──────────────┘
                                                    │ (operator.add)
                                              [executor] → [summarizer] → output
                                                    │              │
                                                 Store           Store
                                               (analysis)     (summaries)

Task B (shares same Store):
  query → [planner] ←──reads── Store(summaries from A)
              │
              └──→ [retriever(s)] → [executor] → [summarizer] → output
```

## 文件结构

```
├── src/                    # 核心代码
│   ├── agents.py           # 4 个 Agent 实现（planner/retriever/executor/summarizer）
│   ├── config.py           # 配置常量（模型路径、环境变量）
│   ├── graph.py            # StateGraph 定义（节点、边、Send fan-out）
│   ├── memory.py           # InMemoryStore + JSONL 持久化共享记忆
│   ├── models.py           # Chat 后端封装（OpenAI 兼容接口 / Transformers）
│   ├── metrics.py          # 性能度量工具
│   └── protocol.py         # 结构化通信协议（AgentMessage、ContextPacket）
├── run_demo.py             # 主运行脚本（2 组关联任务）
├── run_12rounds.py         # 12 轮实验脚本（TEXT vs STRUCTURED 对比）
├── run_structured_only.py  # 仅 STRUCTURED 模式测试
├── docs/                   # 项目文档
│   └── openos/             # 详细技术文档
├── langgraph/              # LangGraph 框架（git submodule）
└── README.md               # 本文件
```

## 关键 LangGraph 特性使用

- **StateGraph**: `graph.py` — TypedDict 状态 + `add_node` / `add_edge`
- **Send**: `graph.py` — `fan_out_retrieval()` 动态并行派发
- **Channel**: 自动 — `operator.add` reducer 实现文档累积
- **InMemoryStore + JSONL 持久化**: `memory.py` — 跨任务共享记忆、语义搜索、进程重启后加载历史记忆
- **BaseStore 注入**: `agents.py` — 节点函数签名 `store: BaseStore` 自动注入
