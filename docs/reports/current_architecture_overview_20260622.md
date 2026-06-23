# StateBus 当前架构说明

日期：2026-06-22

适用范围：本文只说明 `/home/qcrs/statebus/project` 当前实现仓库里的真实架构，不回退到早期设计稿，也不把尚未落地的终态能力写成现状。

---

## 1. 一句话结论

当前 StateBus 不是“一个 LangGraph demo + 若干 prompt”，而是一个以 `Orchestrator` 为语义核心、以 LangGraph 为编排外壳、以 `StateRef + StatePool + MemoryStore + formal benchmark/report gates` 为基础设施的多 Agent 运行时。

它当前已经形成四层闭环：

1. 任务层：`tasks/` 定义 formal pack、task contract 和 current reading boundary。
2. 运行时层：`runtime/orchestrator.py` 负责 plan 编译、step 执行、schema 校验、replay gate、task commit。
3. 状态/记忆层：`statepool/` 和 `memory/` 负责非文本状态与跨任务复用。
4. 评测层：`eval/runner.py` 负责 repeat、双模式对照、gate 和报告。

---

## 2. 当前系统要解决的不是“通用 Agent 编排”，而是赛题三件事

题目要求的核心对象一直没变：

- 低开销通信
- 非文本状态传递
- 共享记忆复用

因此当前架构不是按“聊天代理平台”来组织，而是按三条机制主线来组织：

- 控制面：谁做什么、按什么协议做
- 数据面：中间状态如何不靠长文本透传
- 记忆面：历史结果如何沉淀、检索、复用

这也是当前仓库里最稳定的解释顺序：先三平面，再四角色，再 benchmark 与 claim surface。

---

## 3. 当前总体拓扑

```text
TaskSet YAML / bundle
  -> eval/runner.py
      -> StateBusGraphRunner (runtime/langgraph_adapter.py)
          -> Orchestrator (runtime/orchestrator.py)
              -> Planner / Retriever / Executor / Summarizer
              -> StatePool (mmap/shared_memory/CAS)
              -> MemoryStore (SQLite + vector index)
              -> Schema / role / replay / fairness gates
      -> result aggregation + report gates
      -> benchmark_report.md / benchmark_results.json / compare CSV
```

更具体地说：

- `eval/runner.py` 是 benchmark 主入口，不只是“跑任务”，还负责 pack metadata、单变量边界、跨 mode 聚合和 claim gate。
- `runtime/langgraph_adapter.py` 负责把一个 task 放进固定图里跑。
- `runtime/orchestrator.py` 才是真正的语义引擎。
- `agents/sample_agents.py` 里落着四个角色的默认实现。
- `statepool/store.py` 和 `memory/store.py` 是非文本状态与共享记忆的宿主。

---

## 4. 三平面架构

### 4.1 控制面

控制面由 `protocol/messages.py`、`runtime/contracts.py`、`runtime/orchestrator.py` 共同组成。

当前控制面消息对象至少包括：

- `Hello`
- `Capability`
- `Plan`
- `PlanStep`
- `StepResult`
- `MemoryQuery`
- `MemoryHit`
- `MemoryCommit`
- `ChannelPatch`
- `ChannelSnapshot`
- `RemoteStepRequest`
- `RemoteStepResponse`
- `TaskCommit`

这里最关键的点不是“用了 protobuf”，而是：

- `PlanStep` 带 `semantic_role`，执行引擎按语义角色而不是硬编码 step_id 调度。
- `CapabilityTable + SchemaInterceptor` 会在 plan、step、result、memory commit 层做合同校验。
- 控制面不负责传完整重状态，重状态尽量落到 `StateRef` 指向的数据面。

因此，当前协议层的本质是“结构化动作骨架 + 状态引用 + 合同校验”，不是简单 JSON 包装。

### 4.2 数据面

数据面由 `protocol/messages.py::StateRef`、`statepool/store.py`、`protocol/channels.py` 组成。

`StateRef` 当前至少携带：

- `state_id`
- `kind`
- `length`
- `storage`
- `handle`
- `blob_hash/checksum`
- `channel`
- `metadata`

当前状态后端有三类：

- `FileBackedStatePool`
  - 默认主线
  - 基于文件与 `mmap`
- `SharedMemoryStatePool`
  - 可选验证路径
  - 用 Python `shared_memory`
- `ContentAddressedBlobStore`
  - 负责 CAS/dedup/replay-ready blob

当前不是所有状态都一视同仁。仓库已经把状态种类和 channel 组织成正式合同：

- `DENSE_EVIDENCE`
- `FEATURE_BUNDLE`
- `CHANNEL_PATCH`
- `CHANNEL_SNAPSHOT`
- `RANKED_EVIDENCE_BUNDLE`
- `TOOL_CANDIDATE_SET`
- `REPLAY_ELIGIBILITY_BUNDLE`
- `EXECUTOR_DECISION_PACKET`
- `VALIDATION_GATE_PACKET`
- `EMBEDDING`
- `TOOL_ARTIFACT`

这些状态再映射到 channel，例如：

- `evidence`
- `route`
- `tool_candidates`
- `replay_gate`
- `legacy_features`
- `embedding`
- `artifact`

这说明当前数据面不是“一个大对象随便塞”，而是：

1. 有显式 state kind；
2. 有 producer/consumer 边界；
3. 有 replay compatibility；
4. 有 schema 和 required metadata。

### 4.3 记忆面

记忆面由 `memory/store.py`、`runtime/orchestrator.py` 和 `agents/sample_agents.py::SummarizerAgent` 共同完成。

`MemoryStore` 当前是：

- SQLite 存元数据与 replay episode
- 向量索引存 embedding 检索面
- `working_memories / long_term_memories / replay_episodes / task_commits` 分层

当前记忆不是单一“命中即复用”。它至少区分：

- `assist`
  - 给当前任务辅助判断
- `validated_replay`
  - 跳过部分步骤
- `exact_replay`
  - 更强的回放命中

而且当前 memory mainline 已把“命中”与“真实效果”分开：

- `memory_hit_rate` 不能直接当 superiority
- formal row 需要同时出现期望 reuse mode、非零 `skipped_step_count`、正 `reuse_gain`

这也是为什么当前 `eval/runner.py` 里有单独的 `Memory replay gate` 和 `Replay Effect Gate`。

---

## 5. 四角色架构

### 5.1 Planner

`PlannerAgent` 当前只负责 plan 编译，不负责 host mainline 里的普通 step 执行。

它支持两种来源：

- `yaml`
  - 直接走 `tasks/sample_tasks.py::build_plan`
- `llm`
  - 走 `_planner_messages()` -> LLM -> `_plan_from_llm_output()`
  - 支持 repair loop

因此当前 Planner 的真实角色是：

- 主动规划器
- 语义角色分配器
- formal pack 中 `plan_source` 的变量来源

而不是“所有任务都靠 Planner 实时自由探索”。

### 5.2 Retriever

`RetrieverAgent` 是当前最复杂的角色之一。它不只是搜文档，还负责：

- corpus retrieval
- 生成 `DENSE_EVIDENCE`
- 生成 `FEATURE_BUNDLE`
- 生成 route/tool candidate
- 生成 `CHANNEL_PATCH` / `CHANNEL_SNAPSHOT`
- 做 assist-style memory lookup
- 为 replay gate 准备 `REPLAY_ELIGIBILITY_BUNDLE`

它当前把“从 query 到 route/tool 候选，再到 typed handoff”的大部分上游结构都生产出来。

### 5.3 Executor

`ExecutorAgent` 负责两类事：

- `VALIDATE_ROUTE`
  - 形成 `VALIDATION_GATE_PACKET`
- `EXECUTE_PLAYBOOK`
  - 消费 retrieve/validate 产物并执行工具

它支持两种传输形态：

- 本地执行
- `UDS` 外部 executor 样机

因此当前 Executor 不只是“运行脚本”，还承担：

- validate gate
- tool contract narrowing
- 远端 transport 适配
- typed/text handoff 的最终消费验证

### 5.4 Summarizer

`SummarizerAgent` 负责：

- 汇总 evidence + actions
- 生成 summary artifact
- 生成 `MemoryCommit`
- 区分 `assist` 与 `replay` 两类 memory commit

它既是控制面面向人的出口，也是记忆面的主要写入口。

当前 memory 的真实沉淀发生在这里，而不是在 Retriever 那里“顺手记一下”。

---

## 6. LangGraph 和 Orchestrator 的真实关系

这是当前最容易被说错的地方。

### 6.1 LangGraph 当前负责什么

`runtime/langgraph_adapter.py::StateBusGraphRunner` 当前负责：

- 建固定节点图
  - `planner -> retriever -> [validate] -> executor -> summarizer`
- 维护 graph state snapshot
- 做节点间状态传播
- 处理失败传播
- 根据 plan 是否含 `validate` 做条件路由

### 6.2 Orchestrator 当前负责什么

`runtime/orchestrator.py::Orchestrator` 当前负责：

- 创建 `RunContext`
- 编译 plan
- handshake / capability 注册
- `semantic_role` 到执行逻辑的映射
- step input ref 准备
- replay gate
- execute prune
- schema validation
- role context slice
- result registration
- task commit sealing

### 6.3 当前应如何诚实表述

当前不是 LangGraph 完整接管了编排语义。

更准确的说法是：

- LangGraph 已经是正式运行引擎外壳
- 但核心业务语义仍然集中在 `Orchestrator`
- 现在的 graph 更像“固定 DAG + 条件路由 + 状态传播”适配层
- 还不是一个深度依赖 LangGraph 高级动态能力的原生图系统

这和 `docs/reports/weekly_report_20260616.md` 的判断一致。

---

## 7. 当前一次 task 是怎么跑完的

### 7.1 任务装载

任务从 `tasks/sample_tasks.py::load_task_set_bundle()` 进入。

`TaskSetBundle` 当前同时包含：

- `TaskSetMetadata`
- `SampleTask[]`

`TaskSetMetadata` 不只是说明文字，它已经内建：

- `public_surface`
- `claim_lanes`
- `single_variable`
- `variable_axes`
- `evidence_tier`
- `plan_source_default`
- `formal_structure_clean_retrieval`

这意味着 task 层本身已经携带“这个 pack 应该怎么读”的合同。

### 7.2 上下文初始化

`Orchestrator.create_context()` 会为每个 task/run 建：

- `RunSession`
- `StatePool`
- `MemoryStore`
- `RunContext`

`RunContext` 是当前 runtime 的总线对象，后续的 state refs、metrics、results、memory hits、replay decision 都挂在这里。

### 7.3 图执行

`StateBusGraphRunner.run_task()` 调 LangGraph 图执行。

图节点内部不是直接写业务，而是调用 `Orchestrator` 公共原语：

- `compile_task_plan`
- `resolve_skip_retrieve_execute`
- `invoke_plan_step`
- `register_step_result`

### 7.4 semantic_role 驱动

Plan 当前不是靠固定 step 名字驱动，而是靠：

- `retrieve`
- `validate`
- `execute`
- `summarize`

这让同一套执行循环既能跑 yaml plan，也能跑 llm plan。

### 7.5 结果与提交

每步结果进入 `StepResult`，最后由 `seal_task_commit()` 密封成 task commit，并把 channel/state/replay 相关信息固化到 execution DAG。

---

## 8. 当前 benchmark / task / claim 层已经是架构的一部分

这个仓库当前不能只理解成“runtime + 一些测试”，因为 `tasks/` 与 `eval/` 已经内建了 formal surface。

### 8.1 task bundle 的当前对象

`tasks/sample_tasks.py` 当前明确构造了几类对象：

- `superiority_comm_v1`
  - communication mainline
- `superiority_memory_v1`
  - memory mainline scaffold
- `uncertainty_audit_v1`
  - audit-only residual/uncertainty surface
- 以及历史/兼容 surface
  - 如 `contest_honest_headline_v1`
  - `contest_superiority_headline_v2`

这些 pack 不是简单 YAML 别名，而是通过 builder 对 task surface 做二次变换：

- 固定 `plan_source`
- 限制 `complexity_bucket`
- 切换 `transfer_strategy`/`handoff_profile`
- 覆写 `runtime_reuse_contract_override`
- 固定 `reading_contract`

### 8.2 formal validation 为什么也算架构

`eval/runner.py` 当前不只是聚合平均值，还负责 formal gate：

- `object_parity_gate`
- `memory_replay_evidence_gate`
- `contest_formal_coverage_gate`
- `headline_memory_replay_effect_gate`

也就是说，当前系统架构已经把“结果能不能被正式读出来”内建到了评测层。

这和很多只做 runtime、最后手工解释结果的仓库不同。

### 8.3 当前报告层输出什么

一次 benchmark 至少会落：

- `benchmark_results.json`
- `benchmark_report.md`
- `benchmark_compare.csv`
- `benchmark_message_breakdown.csv`
- `benchmark_message_sizes.md`

报告头部会带 pack metadata、planner source、single-variable contract、public surface、evidence tier。

因此当前 `eval/runner.py` 实际上承担了“结果解释接口”的角色。

---

## 9. 当前的可见性/公平性合同

除了协议和状态本体，当前仓库还有一层很关键但容易忽略的架构：角色可见性合同。

这一层主要落在：

- `runtime/role_contracts.py`
- `runtime/orchestrator.py` 里的 role context slice
- `eval/runner.py` 的 text guard / parity 审计

它做的事是：

- 规定不同角色在不同 lane 下能看见什么
- 记录 `projection_class`、`included_fields`、`omitted_fields`
- 审计 text lane 是否偷看 typed state
- 审计 protocol/text 是否发生 object drift

因此，当前架构不是只有“功能模块”，还有一层“可见性与比较公平性架构”。

---

## 10. 当前已实现到什么程度

### 10.1 已经落地的主线

当前可以诚实说已经落地的：

- `text` / `protocol` 双模式
- `Plan / PlanStep / StepResult / MemoryCommit` 等协议对象
- `semantic_role` 驱动执行
- `StateRef` 非文本状态引用
- `mmap` 主线状态池
- `shared_memory` 备选后端
- CAS/dedup/replay-restorable blob
- SQLite + 向量索引记忆层
- assist / validated_replay / exact_replay 分层复用
- UDS executor transport 样机
- formal pack / gate / report 体系

### 10.2 还没有落地成“当前事实”的

以下仍然不该写成现状：

- `nsjail` 正式沙箱链
- Docker 终态复现链
- openEuler 最终交付验证
- `SCM_RIGHTS` / FD passing 数据面
- hidden-state / KV cache 直传
- 容器级多角色分布式 runtime
- WASM / eBPF 等加分项正式集成

当前最诚实的表述是：

> 已实现 `StateRef + feature/state bundle + replay-ready memory` 这一层非文本协作基础设施；更强的系统与模型级状态传递仍属于后续增强。

---

## 11. 当前代码层的主模块分工

### 11.1 `runtime/`

- `orchestrator.py`
  - 语义核心
- `langgraph_adapter.py`
  - 图执行适配层
- `contracts.py`
  - schema/state contract 校验
- `role_contracts.py`
  - 角色可见性与输入输出合同
- `executor_runtime.py`
  - 执行与 handoff 消费逻辑
- `llm.py`
  - LLM client、prompt、deterministic client

### 11.2 `protocol/`

- `messages.py`
  - 所有核心消息 dataclass 与 protobuf/json 转换
- `channels.py`
  - typed channel registry

### 11.3 `statepool/`

- 后端状态存储
- CAS blob
- `StateRef` 读写

### 11.4 `memory/`

- memory schema
- embedding/index
- assist/replay 查询
- replay episode 持久化

### 11.5 `tasks/`

- `SampleTask` / `TaskSetMetadata`
- pack builder
- formal task contract
- reusable/prior dependency contract

### 11.6 `eval/`

- repeat benchmark 执行
- cross-mode compare
- gate
- markdown/json/csv 报告

---

## 12. 和赛题要求的一一映射

| 赛题要求 | 当前实现对应 |
| --- | --- |
| 至少 3 个 Agent | 当前是 4 角色：Planner / Retriever / Executor / Summarizer |
| 结构化通信协议 | `protocol/messages.py` + protobuf + capability/schema validation |
| 纯文本模式 + 结构化模式 | `text` / `protocol` 双模式，runner 统一执行 |
| 非文本状态传递 | `StateRef` + `StatePool` + typed state kinds |
| 共享记忆模块 | `MemoryStore` + `MemoryCommit` + `MemoryHit` |
| 记忆检索与复用 | assist / validated_replay / exact_replay gates |
| 至少两组连续任务 | task bundle 支持 reusable/prior dependency rows |
| 展示通信/时延/复用指标 | `eval/runner.py` 聚合 `protocol_bytes` / `llm_total_tokens` / `task_ms` / `reuse_gain` 等 |
| 稳定执行不少于 10 轮 | benchmark runner 原生支持 repeat |

---

## 13. 当前最重要的阅读边界

如果只记一条，应该记这条：

> 当前 StateBus 的“架构”不只是四个 Agent 加一个图，而是 `formal task contract + orchestrator semantics + typed state substrate + memory replay gates + report reading boundary` 这五层一起构成的。

如果把其中任何一层删掉，都会误读当前仓库：

- 只看 LangGraph，会高估图层、低估 `Orchestrator`
- 只看 Agent，会漏掉 state/memory substrate
- 只看 runtime，会漏掉 `tasks/` 和 `eval/` 里的 formal surface
- 只看报告，会看不到真实执行语义与约束

---

## 14. 推荐连读顺序

如果要继续深挖当前实现，推荐按这个顺序读：

1. `README.md`
2. `docs/constraints/current_host_and_migration.md`
3. `docs/constraints/current_feature_scope.md`
4. `docs/reports/architecture_and_data_flow.md`
5. `runtime/orchestrator.py`
6. `runtime/langgraph_adapter.py`
7. `protocol/messages.py`
8. `statepool/store.py`
9. `memory/store.py`
10. `tasks/sample_tasks.py`
11. `eval/runner.py`

这样读，能同时看到：

- 当前边界
- 当前运行链
- 当前 formal benchmark surface
- 当前哪些能力是真实实现，哪些只是后续项
