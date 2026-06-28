# SynapseX - 面向多智能体协作的低开销通信、状态传递与共享记忆机制

基于 LangGraph 框架的多智能体研究系统，支持 OpenAI 兼容 Chat 后端（默认 DeepSeek）和本地 Transformers 后端（默认模型路径 `/data/models/Qwen3-8B`）。

## 功能覆盖

| # | 需求 | 实现方式 |
|---|------|---------|
| 1 | ≥3 Agent 协同（规划/研究/分析/执行/总结） | 5 个 Agent 节点：planner → researcher(s) → analyst → executor → summarizer |
| 2 | 结构化通信协议 | TypedDict 状态 + Channel 系统（LastValue / BinaryOperatorAggregate） |
| 3 | 非文本中间状态传递 | true_kvcache：vLLM `SharedStorageConnector` 写入/读取 KV cache tensors，实现 Agent 间模型中间状态复用 |
| 4 | 共享记忆模块 | InMemoryStore + JSONL 长期记忆，支持 put/get/search 与进程重启后加载 |
| 5 | ≥2 组关联连续任务 | `task/longtext/skyforge_cache_tasks.json` 提供 10 轮长上下文连续游戏生成任务 |
| 6 | 性能对比数据 | A/text、B/structured、C/trueKV 三组公平对比（tokens、时延、产物质量、KV 复用规模） |

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

# 3. 运行主线 demo
cd /data/mingwei/SynapseX
python run_demo.py

# 4. 运行 true_kvcache A/B/C 对比实验（建议在 SynapseX-wmw-627 容器内执行）
python exp/kv_cache_exp/run_five_agent_truekv_fair_current.py
```

## 架构图

```
Task A:
  query → [planner] ──Send──→ [researcher_1 ∥ researcher_2 ∥ researcher_3]
                                    │              │              │
                                    └──────────────┴──────────────┘
                                                    │ (operator.add)
                                              [analyst] → [executor] → [summarizer] → output
                                                    │              │
                                                 Store           Store
                                               (analysis)     (summaries)

Task B (shares same Store):
  query → [planner] ←──reads── Store(summaries from A)
              │
              └──→ [researcher(s)] → [analyst] → [executor] → [summarizer] → output
```

## 文件结构

```
├── src/                    # 核心代码
│   ├── agent/              # 5 个 Agent 文件（planner/researcher/analyst/executor/summarizer）
│   │   ├── planner.py      # 任务拆解与子查询规划
│   │   ├── researcher.py   # 研究材料生成与 context packet 打包
│   │   ├── analyst.py      # 上下文选择、验证与证据分析
│   │   ├── executor.py     # 受限 CodeAct 执行与指标产物
│   │   └── summarizer.py   # 最终摘要与发现输出
│   ├── agents.py           # 旧导入兼容层
│   ├── config.py           # 配置常量（模型路径、环境变量）
│   ├── graph.py            # StateGraph 定义（节点、边、Send fan-out）
│   ├── memory.py           # InMemoryStore + JSONL 持久化共享记忆
│   ├── models.py           # Chat 后端封装（OpenAI 兼容接口 / Transformers）
│   ├── metrics.py          # 性能度量工具
│   ├── protocol.py         # 结构化通信协议（AgentMessage、ContextPacket）
│   ├── true_kv_handoff_runtime.py  # vLLM KVTransferConfig / SharedStorageConnector 配置
│   └── vllm_cache_runtime.py       # trueKV/cache 推理运行时封装
├── exp/kv_cache_exp/       # A/text、B/structured、C/trueKV 对比实验与最近两次结果
├── task/longtext/          # 10 轮长上下文连续游戏生成任务
├── task/data_anas/         # 数据分析类历史任务与结果
├── run_demo.py             # 主运行脚本（2 组关联任务）
├── docs/                   # 项目文档
│   └── openos/             # 详细技术文档
├── third_party/            # 外部源码子模块
│   ├── langgraph/          # LangGraph 框架（git submodule）
│   └── vllm/               # vLLM 推理框架（git submodule）
└── README.md               # 本文件
```

## 关键 LangGraph 特性使用

- **StateGraph**: `graph.py` — TypedDict 状态 + `add_node` / `add_edge`
- **Send**: `graph.py` — `fan_out_research()` 动态并行派发
- **Channel**: 自动 — `operator.add` reducer 实现文档累积
- **InMemoryStore + JSONL 持久化**: `memory.py` — 跨任务共享记忆、语义搜索、进程重启后加载历史记忆
- **BaseStore 注入**: `agent/*.py` — 节点函数签名 `store: BaseStore` 自动注入

## true_kvcache 非文本状态传递

本项目的“非文本中间状态传递”以 true_kvcache 为准，而不是 structured 模式里的文本摘要或 hidden-state 相似度筛选。核心流程如下：

```text
ContextPrefillAgent / producer
        │  对长规则文档、长日志或代码库说明执行一次 prefill
        ▼
vLLM SharedStorageConnector
        │  写入 KV cache tensors + handoff metadata
        ▼
下游五个业务 Agent
        │  复用同一长前缀 KV cache，只追加当前 Agent suffix/state
        ▼
继续生成
```

关键代码与文档：

- `src/true_kv_handoff_runtime.py`：构造 `KVTransferConfig` 和 handoff metadata。
- `src/vllm_cache_runtime.py`：封装 vLLM 推理、prefix prefill 和 cache 复用统计。
- `src/agent/cache_agents.py`：同五 Agent 业务链路的 trueKV/cache 旁路线。
- `exp/kv_cache_exp/run_five_agent_truekv_fair_current.py`：A/text、B/structured、C/trueKV 公平对比脚本。
- `docs/openos/notext_state_transfer/kv_cache_handoff_design.md`：trueKV 设计与实验说明。

Structured 模式仍用于低开销结构化通信：`AgentMessage`、`context_packets`、`embedding_payloads`、Store 引用等；它不代表模型中间状态复用。
