# Multi-Agent Research System Demo

基于 LangGraph 框架 + DeepSeek V4 API 的多智能体研究系统。

## 功能覆盖

| # | 需求 | 实现方式 |
|---|------|---------|
| 1 | ≥3 Agent 协同（规划/检索/执行/总结） | 4 个 Agent 节点：planner → retriever(s) → executor → summarizer |
| 2 | 结构化通信协议 | TypedDict 状态 + Channel 系统（LastValue / BinaryOperatorAggregate） |
| 3 | 非文本中间状态传递 | DashScope `text-embedding-v4` 生成语义向量，InMemoryStore 向量检索 |
| 4 | 共享记忆模块 | InMemoryStore + 层级化 namespace，支持 put/get/search |
| 5 | ≥2 组关联连续任务 | Task A（框架分析）→ Task B（系统设计），B 复用 A 的记忆 |
| 6 | 性能对比数据 | perf_counter 测量各节点时延、通信开销、记忆复用率 |

## 快速开始

```bash
# 1. 安装依赖
pip install langgraph langchain-core langchain-openai dashscope

# 2. 设置 API Key
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export DASHSCOPE_API_KEY="your-dashscope-api-key"

# 3. 运行 demo
cd /data/mingwei/Synapse
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
├── src/                # 核心代码
│   ├── agents.py       # 4 个 Agent 实现（调用 DeepSeek V4）
│   ├── config.py       # 配置常量
│   ├── graph.py        # StateGraph 定义（节点、边、Send fan-out）
│   ├── memory.py       # InMemoryStore + DashScope text-embedding-v4
│   ├── models.py       # DeepSeek V4 模型配置
│   ├── metrics.py      # 性能度量工具
│   └── protocol.py     # 结构化通信协议
├── run_demo.py         # 主运行脚本
├── run_12rounds.py     # 12 轮实验脚本
├── docs/               # 项目文档
├── langgraph/          # LangGraph 框架（git submodule）
└── README.md           # 本文件
```

## 关键 LangGraph 特性使用

- **StateGraph**: `graph.py` — TypedDict 状态 + `add_node` / `add_edge`
- **Send**: `graph.py` — `fan_out_retrieval()` 动态并行派发
- **Channel**: 自动 — `operator.add` reducer 实现文档累积
- **InMemoryStore**: `memory.py` — 跨任务共享记忆 + 语义搜索
- **BaseStore 注入**: `agents.py` — 节点函数签名 `store: BaseStore` 自动注入
