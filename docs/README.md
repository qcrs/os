# SynapseX 文档入口

本目录是 SynapseX 的文档索引。当前代码以仓库根目录和 `src/` 为准，核心工作流已经更新为 5 个真实 Agent：

```text
planner → researcher(s) → analyst → executor → summarizer
```

其中 `researcher` 会按 `planner` 生成的多个 `sub_queries` 并行运行，随后通过 LangGraph reducer 汇总到 `analyst`；`executor` 是真实独立节点，负责一个受限 CodeAct 执行步骤，不再是 `analyst` 的别名。

---

## 当前系统概览

SynapseX 是一个基于 LangGraph 的多智能体研究与评测系统，重点验证低开销结构化通信、非文本状态传递和共享记忆复用。

当前实现包含：

- **多 Agent 协作**：`planner`、`researcher`、`analyst`、`executor`、`summarizer` 五个真实节点。
- **结构化通信协议**：`AgentMessage`、`ActionType`、`AgentCard`、`AgentRegistry`。
- **Context Packet 压缩**：把 researcher 生成的大段材料压缩为可校验、可回溯的上下文包。
- **非文本状态传递**：structured 模式仅保留 embedding payload；真正的模型中间状态传递由 trueKV/KV cache 路径实现。
- **共享记忆机制**：运行期 `InMemoryStore` 只回传完整文档；跨任务记忆使用 Qdrant。
- **CodeAct Executor**：在 `analyst` 后执行受限 Python 代码，生成 `execution_result` 和 `execution_summary`。
- **实验入口**：包含基础 demo、通信协议对比实验和任务评测脚本。

---

## Agent 分工

| Agent | 位置 | 主要职责 | 主要输出 |
|---|---|---|---|
| `planner` | 第 1 步 | 理解 query，生成研究计划和 3 个子查询 | `plan`、`sub_queries` |
| `researcher` | 第 2 步，并行 | 根据每个 sub-query 生成研究材料，写入 Store，并打包 context packet | `documents`、`context_packets`、`embedding_payloads` |
| `analyst` | 第 3 步 | 选择上下文、校验证据、必要时 rehydrate，并生成结构化分析 | `analysis`、`analysis_digest`、`evidence`、`selected_context_packets` |
| `executor` | 第 4 步 | 执行受限 CodeAct，对 analyst 的分析和证据做统计检查 | `execution_code`、`execution_result`、`execution_summary` |
| `summarizer` | 第 5 步 | 综合 plan、analysis、evidence 和 execution artifact，输出最终总结 | `summary`、`key_findings`、`recommendations` |

更详细的 Agent 说明见：[`../src/agent/README.md`](../src/agent/README.md)。

---

## 核心代码位置

| 路径 | 说明 |
|---|---|
| [`../src/agent/`](../src/agent/) | 五个 Agent 的拆分实现和 agent 工作流说明 |
| [`../src/agent/planner.py`](../src/agent/planner.py) | 任务规划与子查询生成 |
| [`../src/agent/researcher.py`](../src/agent/researcher.py) | 研究材料生成、context packet 打包、embedding payload 生成 |
| [`../src/agent/analyst.py`](../src/agent/analyst.py) | 上下文选择、证据校验、rehydrate、结构化分析 |
| [`../src/agent/executor.py`](../src/agent/executor.py) | 受限 CodeAct 执行与 metrics artifact 生成 |
| [`../src/agent/summarizer.py`](../src/agent/summarizer.py) | 最终总结生成 |
| [`../src/graph.py`](../src/graph.py) | LangGraph `StateGraph`、fan-out / fan-in、节点连线 |
| [`../src/protocol.py`](../src/protocol.py) | `AgentMessage`、`ActionType`、Context Packet、Agent Registry |
| [`../src/runtime_store.py`](../src/runtime_store.py) | 无索引的运行期文档回传 Store |
| [`../src/memory.py`](../src/memory.py) | embedding 适配器和 Qdrant 长期记忆接口 |
| [`../src/models.py`](../src/models.py) | OpenAI-compatible 和 Transformers Chat 后端封装 |
| [`../src/metrics.py`](../src/metrics.py) | token、时延、通信、压缩和 embedding 指标统计 |
| [`../src/config.py`](../src/config.py) | 环境变量、模型、命名空间和功能开关 |

---

## 文档索引

| 文档 | 当前用途 |
|---|---|
| [`current_codeact_design.md`](current_codeact_design.md) | 当前分支 CodeAct 的完整设计说明，包含 executor 接入、runtime/helper、代码生成协议和 Group1 测试结果分析 |
| [`how_to_run.md`](how_to_run.md) | 运行方式、依赖安装、后端选择、环境变量、入口脚本说明 |
| [`langgraph_features_in_demo.md`](langgraph_features_in_demo.md) | SynapseX 中用到的 LangGraph / LangChain 能力说明 |
| [`openos/communication/structured_communication_protocol.md`](openos/communication/structured_communication_protocol.md) | 结构化通信协议、Context Packet 和 embedding 通道说明 |
| [`openos/memory/delayed_memory_commit.md`](openos/memory/delayed_memory_commit.md) | 长期记忆与运行期文档的边界、候选缓冲、延迟提交和实验观测说明 |
| [`openos/race9.md`](openos/race9.md) | 赛题/需求原文或整理版，用于对照实现范围 |

> 注意：部分历史报告类文档可能仍保留旧命名，例如 `retriever` / `executor` 四节点架构描述。当前实现以 `src/agent/README.md`、`src/graph.py` 和本 README 为准。

---

## 实验与任务入口

| 路径 | 说明 |
|---|---|
| [`../exp/run_demo.py`](../exp/run_demo.py) | 基础 demo：Text / Structured 双模式对比 |
| [`../exp/comm_exp/`](../exp/comm_exp/) | 通信协议、context packet 和任务评测相关产物 |
| [`../exp/12run_smoke/run_12rounds.py`](../exp/12run_smoke/run_12rounds.py) | 12 轮连续任务 smoke / 对比实验入口 |
| [`../task/`](../task/) | 任务评测脚本、结果和报告材料 |

---

## 推荐阅读顺序

如果是第一次看项目，建议按下面顺序阅读：

1. [`../README.md`](../README.md)：了解项目目标、快速开始和整体架构。
2. [`../src/agent/README.md`](../src/agent/README.md)：理解五个 Agent 的职责和完整工作流。
3. [`how_to_run.md`](how_to_run.md)：选择运行后端并设置环境变量。
4. [`openos/communication/structured_communication_protocol.md`](openos/communication/structured_communication_protocol.md)：理解 structured mode、context packet 和非文本状态传递。
5. [`langgraph_features_in_demo.md`](langgraph_features_in_demo.md)：对照 LangGraph API 看实现细节。

---

## 当前命名约定

当前推荐使用的新角色名：

```text
planner / researcher / analyst / executor / summarizer
```

兼容关系：

- `retriever` 仅作为 `researcher` 的旧兼容别名保留。
- `executor` 是真实独立 Agent，不再是 `analyst` 的别名。

当前主要 action：

| Action | 来源 → 目标 | 含义 |
|---|---|---|
| `plan` | `planner → researcher` | 任务规划结果 |
| `research` | `researcher → analyst` | 研究材料和上下文包 |
| `analyze` | `analyst → executor` | 结构化分析和证据 |
| `execute` | `executor → summarizer` | CodeAct 执行结果 |
| `summarize` | `summarizer → output` | 最终总结 |

---

## 当前记忆边界

| 层级 | 存储内容 | 生命周期 |
|---|---|---|
| Runtime Store `("docs",)` | researcher 的完整文档，按 `doc_key` 回填 | 单个 graph 实例 |
| Qdrant `analysis` / `summary` / `task_state` | 可复用的长期分析、总结和状态 | 跨任务、跨进程 |

---

## 运行提示

常用 structured mode 能力开关：

```bash
export ENABLE_CONTEXT_PACKETS=1
export ENABLE_EMBEDDING_TRANSFER=1
```

Chat 后端可以选择：

```bash
# OpenAI-compatible / DeepSeek / vLLM
export CHAT_BACKEND=openai

# 本地 Transformers
export CHAT_BACKEND=transformers
```

详细运行命令见：[`how_to_run.md`](how_to_run.md)。
