# 赛题9实现规划与架构审计

适用范围：这份文档保留赛题 9 的 requirement 拆解、设计路线和阶段计划，但它**不再是当前实现事实层主文档**。

当前实现与证据请优先看：

- `README.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/progress/contest_requirement_host_audit_20260607.md`
- `runs/comprehensive_eval_20260607_131113/`
- `runs/host_goal_eval_20260607_233858/`
- `runs/host_goal_eval_20260608_002101/`
- `runs/host_goal_eval_20260608_021820_runtime_exact_replay_det_repeat10/`
- `runs/host_goal_eval_20260608_022627_runtime_exact_replay_api_repeat10/`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
- `runs/host_goal_eval_20260608_112452_plan_sideband_runtime_profile_refresh/`
- `runs/host_goal_eval_20260608_113845_runtime_drop_reuse_signature_query_refresh/`
- `docs/planning/goal_prompt_host_mainline_despecialize_then_deepen_20260608.md`

如果本文件后面某些段落仍保留 design-first 或 Docker/openEuler 终态表达，应理解为**历史规划参考或后续阶段对象**，不能覆盖当前 host-mainline 事实。

审计结论先说：

1. 当前仓库已经不是 design-only；它是一个**可运行的 host-side 赛题化原型**。`text/protocol` 双模式、`StateRef`、共享记忆、benchmark、tests、`runtime.smoke` 都已落地。
2. 现有文档里最应该保留的主线仍是 `StateBus`：`控制面 + 数据面 + 记忆面`，以及 `runtime + protocol + statepool + memory + eval` 的宿主机主链路。
3. 当前正确路线不是提前补 Docker/openEuler/强沙箱终态，而是继续把 **host-first requirement closure + honest evidence** 收口：
   - `Planner` 和 `Summarizer` 维持 API LLM；
   - `Retriever`、`Executor`、`StateRef`、共享记忆、benchmark 在当前 Linux 宿主机继续做实；
   - Docker / openEuler / `nsjail` 保留到后续验证阶段，不回灌成当前主线前提。
4. `093111` 之后的下一阶段 active goal，不应直接进入纯 tuning；优先级应改成：
   - 先去赛题特化
   - 再做检索/记忆/工具选择分层解耦
   - 最后才做深度优化与性能细化

---

## 1. 赛题要求拆解表

| 原始要求 | 对应能力 | 是否必须 | 评分影响 |
|---|---|---:|---|
| 不少于 3 个 Agent，覆盖规划/检索/执行/总结等至少 3 类角色 | 至少实现 `Planner`、`Retriever`、`Executor`、`Summarizer` 中 3 个，建议 4 个全上 | 是 | 系统完整性 |
| 结构化通信机制，至少包含动作、参数、结果、能力描述 | `Hello`、`Capability`、`Plan`、`PlanStep`、`StepResult`、`Ack/Error` | 是 | 通信效率 + 系统完整性 |
| 支持握手、能力发现或协议映射 | `AgentRegistry`、`CapabilityTable`、`SchemaInterceptor`、`ProtocolMapper` | 是 | 系统完整性 |
| 不能只靠自然语言长文本透传全部信息 | 控制面只传结构化帧，重状态不内联 | 是 | 通信效率 |
| 同时支持纯文本协作模式和结构化协议协作模式 | 同一任务集的 `text` / `protocol` 双模式运行 | 是 | 实验验证 |
| 实现非文本中间状态传递 | `StateRef` + `StatePool` + `EMBEDDING/DENSE_EVIDENCE/TOOL_ARTIFACT` | 是 | 状态传递创新 |
| 明确状态生成、传递、接收、使用方式 | Producer/Consumer + adapter + 生命周期定义 | 是 | 状态传递创新 |
| 实现共享记忆模块 | SQLite 元数据 + FAISS 向量索引 + `MemoryProxy` | 是 | 记忆复用效果 |
| 每条记忆包含 ID、来源 Agent、时间、任务主题、摘要 | `memory_id/source_agent_id/created_at/task_theme/summary` | 是 | 记忆复用效果 |
| 支持关键词、标签、语义相似度检索 | SQLite FTS/过滤 + FAISS 相似检索 | 是 | 记忆复用效果 |
| 不同 Agent 可在后续任务复用历史记忆 | `MemoryQuery`、`MemoryHit`、`GraphPruner` | 是 | 记忆复用效果 |
| 至少 2 组具有关联性的连续任务 | 两条任务链，每条至少 2 个连续任务 | 是 | 实验验证 |
| 统计消息次数、文本 token/字符、非文本状态次数与规模、总耗时、记忆命中率、整体提升 | `ProtocolProbe`、`TaskProbe`、`MemoryProbe`、`StateProbe` | 是 | 实验验证 + 通信效率 |
| 架构至少包含 runtime / 协议解析与调度 / 状态交换 / 共享记忆 / 评测 | 六模块完整工程结构 | 是 | 系统完整性 |
| 稳定执行不少于 10 轮连续任务 | benchmark runner + 稳定性测试 | 是 | 系统完整性 + 实验验证 |
| 提交源码、设计文档、部署文档、实验报告、演示视频 | 代码仓、部署说明、reports、demo trace | 是 | 交付完整性 |
| 鼓励 IPC/共享内存/Socket/向量库/WASM/容器/eBPF | UDS + memfd/SHM + SQLite/FAISS，后续可加 eBPF 观测 | 否 | 加分项 |
| 鼓励 CodeAct | 受控 CodeAct 执行链路 | 否，但强烈建议做 | 创新展示 |

### 必须实现项

- `Planner + Retriever + Executor + Summarizer`
- `text` / `protocol` 双模式
- `StateRef` 非文本状态传递
- SQLite + FAISS 共享记忆
- 2 组连续任务
- 10 轮稳定 benchmark
- 完整指标采集

### 可选增强项

- `KV_PREFILL/HIDDEN_STATE` 同构后端消费
- gRPC over UDS 第二控制面传输层
- `nsjail` 内 FD 注入
- eBPF/perf 观测
- reranker 精排

### 评分重点

1. 先保 `text vs protocol` 对照实验真实成立。
2. 再保 `StateRef` 真正承载非文本状态，而不是只挂个字符串 ID。
3. 再保记忆命中后确实减少步骤或减少重复检索。
4. 最后再做 CodeAct 和更重的系统加速。

---

## 2. 当前文档审计结论

### 2.1 文件分组

| 文件 | 归类 | 结论 |
|---|---|---|
| [题目.md](./题目.md) | 权威需求源 | 唯一必须反向对齐的源头 |
| [statebus_architecture_evolution_feasibility_report.md](./statebus_architecture_evolution_feasibility_report.md) | 主设计文档 | 负责说明题目对象、三层演进、评测目标 |
| [statebus_architecture_and_implementation_plan.md](./statebus_architecture_and_implementation_plan.md) | 主设计文档 | 负责工程模块、协议、记忆、阶段实施 |
| [statebus_dual_plane_deep_design.md](./statebus_dual_plane_deep_design.md) | 主设计文档 | 负责边界、生命周期、事务、回滚、死角处理 |
| [multi-agent-system-design.md](./multi-agent-system-design.md) | 辅助参考文档 | 可用于角色分工和教学式示例，但技术主线不应以它为准 |
| [s_memory_agent_design.md](./s_memory_agent_design.md) | 辅助参考文档 | 可用于目录结构和实验组织参考，但命名体系和技术栈有偏移 |
| [赛题9设计讲解压缩稿.md](./赛题9设计讲解压缩稿.md) | 讲解型文档 | 最适合答辩和口头解释，不应主导技术定稿 |
| [statebus_真实场景时序图消息表状态表.md](./statebus_真实场景时序图消息表状态表.md) | 讲解型文档 | 最适合落地任务链、消息表、状态表 |

### 2.2 核心结论

#### 该保留的

- `StateBus` 三面模型：控制面 / 数据面 / 记忆面。
- `Runtime -> Protocol -> StatePool -> MemoryProxy -> Eval` 主骨架。
- `Planner` 只在入口用 LLM，后续路由由运行时确定。
- `StateRef` 的单写多读、`PREPARE -> COMMIT -> ROLLBACK` 语义。
- SQLite 真源 + FAISS 单写者 + outbox 的记忆一致性方案。
- 两个连续任务的真实场景化表达。

#### 该降级为参考表达的

- `multi-agent-system-design.md` 中以 MessagePack + ChromaDB 作为主线的写法。
- `s_memory_agent_design.md` 中 `SACP`、`MemoryAgent`、`EvaluatorAgent` 这些新命名。它们可以借鉴，但不应覆盖当前仓库稳定术语。
- `embedding` 被描述成“Agent 直接把向量传给下一个模型”的表述。
- 把 Docker 当成 CodeAct 执行沙箱本体的表述。
- `HIDDEN_STATE/KV_PREFILL` 作为主路径的暗示。

### 2.3 设计冲突与不清点

| 问题 | 体现文件 | 审计结论 | 处理方式 |
|---|---|---|---|
| 协议主格式不统一 | `multi-agent-system-design.md` 倾向 MessagePack；`statebus_*` 主文档倾向 Protobuf | 主线必须统一 | MVP 可用 JSON/MessagePack 调试，但正式主线定为 Protobuf |
| 向量库方案不统一 | `multi-agent-system-design.md` 提 ChromaDB；主文档提 SQLite + FAISS | 不能双主线 | 统一为 SQLite + FAISS，ChromaDB 只作为废弃参考 |
| 工具层与 Agent 层边界不清 | 辅助文档常把检索/执行都写成 LLM Agent | 容易误导初学者 | 强制区分脚本型、LLM 型、混合型 Agent |
| Docker 与 nsjail 关系不清 | 有的文档把 Docker 当沙箱，有的把 nsjail 当沙箱 | 工程边界需要统一 | Docker 是外层复现环境，nsjail 是内层 CodeAct 沙箱 |
| embedding 使用语义不稳定 | 有的文档写“embedding 直传”，有的文档写“只用于检索” | 必须收敛 | 主线规定：embedding 主要给检索/记忆用，不直接给通用 LLM 看 |
| 当前是否已实现容易被误解 | 全仓库都是设计文档，讲解稿很像已经实现 | 风险很大 | 必须显式写明：当前仅文档覆盖，不是实现覆盖 |

### 2.4 当前实现覆盖结论

| 赛题要求 | 文档级覆盖 | 代码级覆盖 | 当前判断 |
|---|---|---|---|
| 4 个 Agent 分工 | 高 | 高 | 已实现 `Planner/Retriever/Executor/Summarizer` 主链路 |
| 结构化协议 | 高 | 高 | 已实现 Protobuf 控制帧、握手、能力表与 schema 校验 |
| 非文本状态传递 | 高 | 高 | 已实现 `StateRef + mmap/shared_memory + FEATURE_BUNDLE/EMBEDDING` |
| 共享记忆 | 高 | 高 | 已实现 SQLite + FAISS + 共享记忆查询/写回 |
| 连续任务与复用验证 | 高 | 高 | 已有 `18` 任务链与 replay-aware benchmark 任务集 |
| 双模式 benchmark | 高 | 高 | `eval.runner`、`benchmark_report.md`、compare CSV 已落地 |
| Docker/openEuler 复现 | 中 | 低 | 仍属于后续阶段，不应当作当前 host-mainline 已闭环 |
| 10 轮稳定运行 | 中 | 高 | 宿主机 repeat-10 已有正式基线；replay-aware `18` 任务链现在也已有 deterministic 和 serialized API 两套 repeat-10 证据 |

**硬结论**：当前仓库已经覆盖赛题实现主骨架；真正未闭环的是通用性去特化、`shared_memory` 更清晰稳定的 backend 结论，以及 Docker/openEuler/强沙箱这些后续阶段对象。

---

## 3. 主实现路线

### 3.1 只选这一条

选择：**StateBus 混合式本地优先路线**

- 控制面：Protobuf 控制帧 + 本地运行时调度
- 数据面：`StateRef` + `mmap/shared_memory` 状态池
- 记忆面：SQLite + FAISS + `MemoryProxy`
- LLM：`Planner`、`Summarizer` 用 API
- Embedding：本地模型
- `Executor`：固定工具优先，CodeAct 兜底
- 外层环境：当前主开发固定为 Linux 宿主机；Docker + openEuler 24.03-LTS-SP3 放后续验证阶段
- 内层执行隔离：当前主线是 tool registry + lightweight subprocess / UDS 样机；正式 `nsjail` 留在 Phase 5 以后

### 3.2 为什么选它

1. 它最贴合题目对象。题目考的是系统层协作机制，不是本地大模型部署秀肌肉。
2. 它能最快做出第一版可运行闭环。把本地 GPU 压力从“大模型推理”挪到“embedding + 工具 + sandbox + benchmark”上，更可控。
3. 它保留后续演进空间。API LLM 后续可以无缝替换为本地 Qwen，接口层不变。
4. 它最符合当前仓库已有文档主线，改动成本最低。

### 3.3 为什么不选其它路线

#### 不选“全流程多 LLM 本地化”

- 这会把主要工程风险转成模型部署和显存预算问题。
- 会稀释题目核心，评委很容易追问你是不是只是在搭模型服务。
- 对第一版原型和 10 轮稳定 benchmark 不利。

#### 不选“所有能力都走 API”

- 这样会削弱“本地协议、状态池、共享记忆、沙箱”的系统层证明力。
- 非文本状态传递和共享记忆复用会变成口头概念，而不是本地运行时行为。

#### 不选“默认 CodeAct 主路径”

- 题目鼓励 CodeAct，但不要求把它变成主执行机制。
- 默认 CodeAct 会让结果不稳定、调试成本高、评测噪声大。

---

## 4. 系统总架构

```text
用户任务
  -> Runtime
      -> Protocol Engine
      -> Planner
      -> Scheduler / DAG / FSM
      -> Retriever / Executor / Summarizer
      -> StatePool
      -> MemoryProxy
      -> Eval / Telemetry
```

### 4.1 运行时

- `runtime/orchestrator.py`
- `runtime/registry.py`
- `runtime/scheduler.py`
- `runtime/graph_pruner.py`
- `runtime/fsm.py`

职责：

- Agent 注册与能力表维护
- `Plan` 编译与 DAG 依赖校验
- `text` / `protocol` 模式切换
- step 调度、失败回滚、重规划入口
- benchmark trace 汇总

### 4.2 控制面

协议对象固定为：

- `Hello`
- `Capability`
- `Plan`
- `PlanStep`
- `StepResult`
- `MemoryQuery`
- `MemoryHit`
- `MemoryCommit`
- `Ack`
- `Error`
- `Heartbeat`

规则：

- 控制面只传动作骨架和引用
- 不内联大段证据或大段历史
- 后续路由不能靠 LLM 决策

### 4.3 数据面

状态类型只把 3 类做成第一版主链路：

- `EMBEDDING`
- `DENSE_EVIDENCE`
- `TOOL_ARTIFACT`

`KV_PREFILL/HIDDEN_STATE` 放 Phase 6 以后，不进 MVP 主链路。

### 4.4 记忆面

- 真源：SQLite
- 检索核：FAISS
- 写入入口：`MemoryProxy`
- 写入一致性：SQLite `pending/active` + `memory_outbox`

### 4.5 工具 / CodeAct

- 固定工具层承担主路径
- 工具组合层承担复用流程
- CodeAct 仅在工具不足时进入

### 4.6 评测模块

必须实现的 8 个指标：

- `message_count`
- `text_tokens`
- `text_chars`
- `protocol_bytes`
- `state_ref_count`
- `state_bytes`
- `task_ms`
- `memory_hit_rate`

建议补充：

- `memory_search_count`
- `memory_reuse_count`
- `reuse_gain`
- `tool_call_count`
- `codeact_fallback_count`

### 4.7 Benchmark 对比策略

#### 必做对比

1. `text` vs `protocol`
   - 同任务
   - 同模型
   - 同 prompt
   - 同工具
   - 同随机种子
   - 用来回答赛题最核心的问题：结构化通信是否真的降低开销

2. `protocol` vs `protocol + memory reuse`
   - 同任务链的第一轮与第二轮
   - 用来回答共享记忆是否真的减少重复计算

#### 建议消融

- `protocol only`
- `protocol + state_ref`
- `protocol + state_ref + memory`

这样可以把收益拆开，不会把全部提升都混在一起。

#### 是否需要和外部框架对比

结论：**第一版不需要。**

- 赛题硬性要求是纯文本协作模式 vs 结构化协议协作模式。
- 如果一开始就拿 LangGraph、AutoGen、AgentScope 做横向对比，会明显分散实现精力。
- 外部框架对比最多放到附录或答辩补充，不应占主线。

#### 两组连续任务的正式定义

**任务链 A：openEuler 服务启动慢诊断**

- A1：分析 `inference-gateway.service` 启动慢
- A2：分析 `service-b.service` 启动慢，复用 A1 策略
- A3：分析 `service-c.service` 启动慢，验证复用稳定性
- A4：回放 A1，验证 10 轮中的重复执行一致性
- A5：回放 A2，验证命中率和剪枝稳定性

**任务链 B：Python 依赖安全与迁移建议**

- B1：扫描项目依赖并生成漏洞列表
- B2：基于 B1 的漏洞列表生成迁移建议
- B3：对迁移建议做一次验证探针
- B4：换一个相近项目复用 B1/B2 经验
- B5：回放 B2/B4，验证复用与稳定性

这样一共正好能组织成不少于 10 轮连续任务。

---

## 5. 4 个 Agent 的职责表

### 5.1 赛题真正要求的“多 Agent”是什么

不是“至少 3 个 LLM”，而是“至少 3 个有独立职责、可被调度、可协作的 Agent 角色”。

- LLM 型 Agent：成立。适合规划、总结。
- 工具型 Agent：成立。适合检索、执行。
- 混合型 Agent：也成立。适合 `Executor`。

因此，主实现应明确分工：

- `Planner`：LLM 型
- `Retriever`：工具型
- `Executor`：混合型
- `Summarizer`：LLM 型

### 5.2 职责表

| Agent | 输入 | 输出 | 是否需要 LLM | 是否需要 embedding | 是否依赖工具/脚本 | 是否需要 adapter | 对应平面关系 |
|---|---|---|---:|---:|---:|---:|---|
| `Planner` | 用户任务文本、可选 `MemoryHit`、能力表 | `Plan`、`PlanStep[]` | 是 | 否 | 否 | 否 | 控制面主生产者 |
| `Retriever` | `PlanStep(action=RETRIEVE)`、主题、过滤条件 | `StepResult` + `EMBEDDING` / `DENSE_EVIDENCE` refs | 否 | 是 | 是 | 是 | 数据面主生产者、记忆面辅助生产者 |
| `Executor` | `PlanStep(action=EXECUTE)`、输入 `StateRef[]`、工具参数 | `StepResult` + `TOOL_ARTIFACT` refs | 默认否 | 可选 | 是 | 是 | 数据面消费者/生产者 |
| `Summarizer` | `PlanStep(action=SUMMARIZE)`、证据 refs、产物 refs、可选复用记忆 | `summary` + `memory_candidate` | 是 | 否 | 否 | 是 | 控制面结果生产者、记忆面候选生产者 |

### 5.3 每个 Agent 的落地说明

#### Planner

- 输入：`task_text`、`capability_table`、`MemoryHit`
- 输出：结构化 `Plan`
- 后端：API 大模型
- 只在入口和 `REPLAN` 时调用
- 不直接处理 embedding

#### Retriever

- 输入：`service/topic/query/tags/top_k`
- 输出：
  - `EMBEDDING`：给检索和记忆流程
  - `DENSE_EVIDENCE`：给 `Executor` / `Summarizer`
- 后端：本地脚本 + 本地 embedding 模型
- 可以零 LLM

#### Executor

- 输入：证据 refs、工具参数、可选复用策略
- 输出：`TOOL_ARTIFACT`
- 后端：预注册脚本优先，必要时一次性 CodeAct
- 第一版不单独配大模型

#### Summarizer

- 输入：证据摘要、执行产物摘要、可选命中记忆
- 输出：最终面向人的报告 + `memory_candidate`
- 后端：API 大模型
- 通过 adapter 消费整理后的状态，而不是直接看裸向量

---

## 6. 模型与 API 配置结论

模型结论按 **2026-06-06** 官方资料核过一遍后收敛如下：

### 6.1 推荐结论

| 能力 | 推荐 | 是否本地 | 结论 |
|---|---|---:|---|
| 主 LLM | `deepseek-v4-flash` | 否 | 第一版主控模型，给 `Planner` 和 `Summarizer` |
| Embedding 模型 | `Qwen3-Embedding-0.6B` | 是 | 第一版统一 embedding 模型 |
| Reranker | 第一版不必上；Phase 4 质量不够再加 `Qwen3-Reranker-0.6B` | 是 | 非必需 |
| Executor 专用模型 | 不需要 | 否 | 第一版禁止给 `Executor` 单独配大模型 |
| 本地替代 LLM | `Qwen3` Instruct 系列，经 vLLM 接入 | 是 | 后续完全离线/本地化时再切换 |

### 6.2 明确回答用户关心的问题

#### `Planner` 和 `Summarizer` 用 API 还是本地模型

结论：**第一版用 API。**

- 选 `deepseek-v4-flash`，原因是：
  - 官方 API 直接支持 OpenAI 兼容接口；
  - 适合先把系统层机制跑通；
  - 把 GPU 压力留给 embedding、本地脚本、状态池、FAISS 和 sandbox。

#### `Retriever` 的 embedding 用什么本地模型

结论：**本地用 `Qwen3-Embedding-0.6B`。**

- 相比旧文档里的 `bge-small-zh-v1.5`，它更适合作为统一主线：
  - 更适合中文 + 英文混合的日志/文档场景；
  - 有同系列 reranker 可无缝追加；
  - 支持 instruction-aware retrieval。

#### 是否需要给 `Executor` 单独配置模型

结论：**不需要。**

- 第一版 `Executor` 必须是工具/脚本优先。
- 只有进入 CodeAct 兜底时，才借用主 LLM 生成一次性 Python。
- 不要让 `Executor` 平时变成“另一个聊天模型”。

#### 是否推荐 Qwen 系列

结论：**推荐，但当前推荐位置是本地 embedding 和后续本地 LLM 备份，不是第一版主 LLM。**

- 现在就推荐：
  - `Qwen3-Embedding-0.6B`
  - 可选 `Qwen3-Reranker-0.6B`
- 后续如要全本地化，再把 `Planner/Summarizer` 换成 Qwen 本地 Instruct。

#### 是否推荐 DeepSeek API

结论：**推荐，且第一版主路线就用它。**

- 推荐 `deepseek-v4-flash`
- 不推荐在第一版上 `deepseek-v4-pro`，因为 benchmark 更关心系统机制而非极限回答质量
- 不推荐第一版上 thinking mode，先用非复杂推理路径保证稳定 telemetry

### 6.3 哪些能力必须本地，哪些能力可以先走 API

#### 必须本地

- Runtime
- Protocol Engine
- StatePool
- SQLite
- FAISS
- Embedding 模型
- 工具脚本
- Telemetry
- CodeAct sandbox

#### 可以先走 API

- `Planner`
- `Summarizer`

### 6.4 为什么不把 embedding 直接传给下一个 LLM

因为主链路里 embedding 的消费者应是：

- `MemoryProxy`
- 检索流程
- rerank 流程

而不是通用 LLM。通用 LLM 真正消费的是：

- 结构化字段
- `StateRef` 经过 adapter 整理出的证据摘要
- 必要的短文本补充

---

## 7. 工具 / 脚本 / CodeAct 三层执行策略

### 7.1 总原则

1. 先固定工具。
2. 再做工具组合。
3. 最后才进 CodeAct。

不要反过来。

### 7.2 固定工具层

第一版最小工具清单：

| 工具名 | 输入 | 输出 | 是否进入数据面 | 备注 |
|---|---|---|---:|---|
| `tool.collect_logs` | `service_name` `boot_window` | `DENSE_EVIDENCE StateRef` | 是 | 收集 journal / service log |
| `tool.collect_docs` | `topic` `tags` | `DENSE_EVIDENCE StateRef` | 是 | 收集文档/历史案例 |
| `tool.embed_texts` | `texts[]` `encoder_id` | `EMBEDDING StateRef` | 是 | 供检索/记忆使用 |
| `tool.run_probe` | `probe_profile` `input_refs[]` | `TOOL_ARTIFACT StateRef` | 是 | 执行探针脚本 |
| `tool.extract_metrics` | `artifact_ref` | 结构化 JSON | 否 | 只留局部，用于 `Summarizer` |
| `tool.render_evidence_digest` | `evidence_ref` | 证据摘要 JSON | 否 | adapter 辅助，不直接存共享态 |

### 7.3 工具组合层

把固定工具编成命名流程，不让 LLM 每次自由探索。

#### 组合 1：`startup_slow_diag_v1`

`collect_logs -> collect_docs -> run_probe -> extract_metrics`

#### 组合 2：`dependency_risk_diag_v1`

`scan_deps -> query_cve -> validate_fix`

第一版 runtime 调度的是“组合名 + 参数”，不是“让模型自由决定 shell 命令”。

### 7.4 如果没有现成脚本怎么办

处理顺序必须固定：

1. 先看能不能用现有工具组合解决。
2. 不能解决，再允许一次受控 CodeAct 生成脚本。
3. 若 CodeAct 路径连续 2 次在相同任务族成功，就将其沉淀成正式工具：
   - 抽成 `tools/*.py`
   - 增加输入输出 schema
   - 加能力注册
   - 加单元测试

### 7.5 CodeAct 兜底层

进入条件必须同时满足：

- 当前步骤属于 `EXECUTE`
- 固定工具层不存在匹配能力
- 工具组合层也无法完成
- 输入状态已被 adapter 规整
- 任务范围可被 1 个短 Python 脚本完成

禁止进入 CodeAct 的情况：

- 纯检索任务
- 纯总结任务
- 可以用已有脚本完成的任务
- 需要联网下载大量依赖的任务

### 7.6 哪些产物进入数据面，哪些只留局部

#### 进入数据面

- `EMBEDDING`
- `DENSE_EVIDENCE`
- `TOOL_ARTIFACT`

#### 只留局部

- 中间调试日志
- LLM 草稿文本
- adapter 过渡对象
- 工具标准输出中无复用价值的内容

---

## 8. Docker + openEuler 实现环境方案

### 8.1 宿主机与容器关系

#### 宿主机

- 提供 Docker Engine
- 挂载项目目录
- 提供 GPU 与本地模型缓存目录

#### 容器

- 以 `openEuler 24.03-LTS-SP3` 为基础镜像
- 运行 Runtime、Protocol、StatePool、SQLite、FAISS、Embedding 服务、benchmark
- 通过环境变量访问外部 API

#### 内层沙箱

- `Executor` 在 Phase 5 以后通过 `nsjail` 进入二级隔离
- 即：`Docker` 是复现外壳，`nsjail` 是代码执行隔离壳

### 8.2 openEuler 镜像作用

- 保证最终构建、运行、测试环境对齐赛题交付要求
- 让 Python、SQLite、FAISS、protobuf、共享内存、UDS 等能力在目标系统族上验证

### 8.3 推荐仓库目录结构

```text
.
├── agents/
├── docker/
│   ├── Dockerfile
│   ├── compose.yaml
│   └── entrypoint.sh
├── docs/
├── deploy/
│   ├── env.example
│   └── install_openeuler.sh
├── eval/
├── memory/
├── protocol/
├── reports/
├── runtime/
├── sandbox/
├── scripts/
├── statepool/
├── tasks/
│   ├── chain_a/
│   └── chain_b/
├── tests/
└── pyproject.toml
```

### 8.4 Dockerfile / compose 需要

#### 必须有

- `docker/Dockerfile`
- `docker/compose.yaml`

#### compose 至少定义 1 个服务

- `statebus-dev`

可选第 2 个服务：

- `qwen-embed`，如果你想把 embedding 服务拆出来

第一版不建议再拆太多服务，避免观测复杂化。

### 8.5 容器内依赖安装清单

系统包：

- `git`
- `gcc`
- `gcc-c++`
- `make`
- `cmake`
- `python3`
- `python3-devel`
- `python3-pip`
- `sqlite`
- `sqlite-devel`
- `protobuf`
- `protobuf-devel`
- `protobuf-compiler`
- `zlib-devel`
- `openssl-devel`
- `libseccomp-devel`
- `which`
- `procps-ng`

Python 包：

- `protobuf`
- `pydantic`
- `numpy`
- `faiss-cpu`
- `sentence-transformers`
- `transformers`
- `torch`
- `openai`
- `pytest`
- `pytest-asyncio`
- `msgpack`
- `orjson`

### 8.6 组件放置

| 组件 | 放置位置 | 原因 |
|---|---|---|
| Runtime | 容器内 | 主进程 |
| Protocol Engine | 容器内 | 本地控制面 |
| StatePool | 容器内 | 共享内存就近 |
| SQLite | 容器内挂载卷 | 简单稳定 |
| FAISS | 容器内挂载卷 | 与 SQLite 同机 |
| Embedding 模型 | 容器内本地缓存 | 避免每次联网拉取 |
| Planner/Summarizer API | 容器内通过 HTTPS 出站 | 保持接口统一 |
| CodeAct sandbox | 容器内 `nsjail` | 易复现 |

### 8.7 如何保证可复现

1. 固定镜像 tag：`openeuler:24.03-lts-sp3`
2. 固定 Python 依赖版本
3. 固定任务集 JSONL
4. 固定模型名
5. 固定 prompt 模板
6. 固定 benchmark seeds
7. 所有 runs 写入 `runs/` 和 `reports/`

---

## 9. 分阶段实现计划

### Phase 0：环境与仓库初始化

- 目标：建好工程骨架和 openEuler Docker 环境
- 输出物：
  - `docker/Dockerfile`
  - `docker/compose.yaml`
  - `pyproject.toml`
  - 顶层目录结构
- 成功标准：
  - `docker compose up` 能进容器
  - Python 环境、protobuf、SQLite、FAISS 可导入
- 风险点：openEuler 下 FAISS/torch 安装不稳
- 回退策略：先 CPU 版 embedding + `faiss-cpu`；必要时 embedding 独立 sidecar

### Phase 1：最小多 Agent 文本模式跑通

- 目标：先把 `text` 模式跑通
- 输出物：
  - 4 个 Agent 基类
  - 最小 Orchestrator
  - `tasks/chain_a/*.jsonl`
- 成功标准：
  - 4 Agent 能完成一个多步骤任务
  - 有消息日志、任务日志
- 风险点：一开始把协议和状态池一起做太重
- 回退策略：此阶段只允许文本消息，先不做 `StateRef`

### Phase 2：结构化控制面与能力注册

- 目标：从文本透传切到结构化控制面
- 输出物：
  - `protocol/*.proto`
  - `CapabilityTable`
  - `SchemaInterceptor`
  - `text` / `protocol` 双模式切换
- 成功标准：
  - 同任务在两种模式下都能跑
  - `protocol_bytes` 可统计
- 风险点：Agent 私有输出格式不稳定
- 回退策略：先做 adapter 到统一中间模型，再序列化

### Phase 3：StateRef 数据面

- 目标：让重状态脱离文本流
- 输出物：
  - `statepool/manager.py`
  - `StateRef` schema
  - `EMBEDDING/DENSE_EVIDENCE/TOOL_ARTIFACT` adapters
- 成功标准：
  - `Retriever` 产出 `StateRef`
  - `Executor`/`Summarizer` 能通过 adapter 消费
  - `state_ref_count/state_bytes` 可统计
- 风险点：共享内存生命周期和清理
- 回退策略：先用进程内 dict 模拟 `StateRef`，再换 `SharedMemory`

### Phase 4：共享记忆与复用

- 目标：让第二轮任务真的少做事
- 输出物：
  - SQLite schema
  - FAISS index
  - `MemoryProxy`
  - `MemoryQuery/MemoryHit/MemoryCommit`
  - `GraphPruner`
- 成功标准：
  - 第二轮任务出现命中
  - 命中后少走部分 `PLAN/RETRIEVE`
  - `memory_hit_rate` 和 `reuse_gain` 可见
- 风险点：错误复用
- 回退策略：只允许复用“策略和参考证据”，禁止复用“当前对象的实时数据”

### Phase 5：CodeAct + 沙箱

- 目标：补齐鼓励项，但不破坏主路径稳定性
- 输出物：
  - `sandbox/nsjail_runner.py`
  - `CodeActRequest/CodeActResult`
  - fallback policy
- 成功标准：
  - 一条受控 CodeAct 路径能完成一次短脚本执行
  - 失败可回滚，不污染记忆
- 风险点：容器内 `nsjail` 权限和动态库路径
- 回退策略：先 `subprocess + timeout + no-network`，再升级 `nsjail`

### Phase 6：评测与展示

- 目标：产出最终验收材料
- 输出物：
  - `eval/runner.py`
  - `eval/compare.py`
  - `reports/*.md`
  - 演示 trace
- 成功标准：
  - 2 组任务链、10 轮稳定跑完
  - 生成总表、对比表、指标图
- 风险点：实验不公平
- 回退策略：固定任务、模型、prompt、工具和随机种子

---

## 10. 第一版就要做的最小可运行闭环

### 10.1 场景

选 `openEuler 服务启动慢诊断` 作为 MVP 主场景：

- 任务 A1：分析 `inference-gateway.service` 启动慢
- 任务 A2：分析 `service-b.service` 启动慢，并复用 A1 经验

理由：

- 能同时覆盖规划、检索、执行、总结
- 天然适合 `DENSE_EVIDENCE + TOOL_ARTIFACT`
- 第二轮任务复用逻辑非常自然

完整实现的第二条正式任务链保留为 `Python 依赖安全与迁移建议`，但不放进第一版 MVP。

### 10.2 Agent 组合

- `Planner`
- `Retriever`
- `Executor`
- `Summarizer`

### 10.3 模型

- `Planner/Summarizer`：`deepseek-v4-flash`
- `Retriever embedding`：`Qwen3-Embedding-0.6B`
- `Executor`：无专用模型

### 10.4 工具

- `collect_logs`
- `collect_docs`
- `run_probe`
- `extract_metrics`

### 10.5 先简化的

- 不做 `KV_PREFILL/HIDDEN_STATE`
- 不做 reranker
- 不做多进程分布式
- 不做 gRPC，先 raw Protobuf + 本地调用
- 不做全功能 `nsjail`，先可控 fallback

### 10.6 必须保留的

- 4 Agent 分工
- `text` / `protocol` 双模式
- `StateRef`
- SQLite + FAISS
- `MemoryHit -> GraphPruner`
- 指标采集

---

## 11. 风险与瓶颈

### 11.1 最大工程瓶颈

**不是 LLM，而是共享状态与记忆一致性。**

最难的真实工程点：

- `StateRef` 生命周期
- SQLite / FAISS 一致性
- benchmark 可复现

缓解策略：

- 先 dict 模拟，再切 `SharedMemory`
- `MemoryProxy` 单写者
- `pending -> active` 严格事务化

### 11.2 最大设计风险

**把“结构化消息”误做成“换个 JSON 壳的文本系统”。**

缓解策略：

- 后续路由禁止走 LLM
- 控制面不内联长证据
- 指标里同时统计 `protocol_bytes` 和 `text_tokens`

### 11.3 最容易被评委追问的点

1. 你们是不是只是多个 LLM 串起来？
   - 回答：不是。`Retriever` 是工具型，`Executor` 是脚本/沙箱优先，LLM 只集中在规划和总结。

2. embedding 是不是直接传给下一个模型看？
   - 回答：不是。embedding 主要用于检索、命中、rerank；通用 LLM 消费的是 adapter 整理后的摘要和结构化字段。

3. 为什么不用多个 LLM 全程探索？
   - 回答：那会把系统层问题退化成 prompt 协调问题，不利于稳定性、成本和可复现实验。

4. 现在是否已经完整实现？
   - 回答：没有。当前仓库是文档完成、代码未起步；本计划就是把它收敛成实施路线。

### 11.4 风险回退总表

| 风险 | 主回退 |
|---|---|
| FAISS 安装/运行不稳 | 先固定 SQLite + 内存检索，再补 FAISS |
| `SharedMemory` 生命周期难调 | 先用进程内 `StateRef` 模拟 |
| CodeAct 不稳定 | 第一版禁用 CodeAct 主路径 |
| API 波动影响 benchmark | 固定请求参数和重试策略，保留后续 Qwen 本地替代入口 |
| 记忆误命中 | 提高阈值，只复用策略类记忆，不复用对象级实时证据 |

---

## 最终收束

最终可执行路线只保留一句话：

> 先在 Docker + openEuler 环境中实现一个本地运行时，跑通 `Planner(API) -> Retriever(local tools + local embedding) -> Executor(script first) -> Summarizer(API)` 的 `text/protocol` 双模式；随后把 `StateRef`、SQLite + FAISS、GraphPruner、10 轮 benchmark 和受控 CodeAct 逐阶段接上。

这样做，第一版能最快满足赛题主指标；后续又能自然扩到完整实现，而不会把项目做成“多个模型随意对话”的演示系统。
