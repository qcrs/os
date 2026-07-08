# 新人术语表

本文档专门解决"看不懂英文字段和内部术语"的问题。

它不是完整方法文档，而是**辅助阅读的工具文档**。当你在其他文档或代码中遇到不熟悉的术语时，可以回到这里查找。

每个词条包含：英文名、中文解释、在本项目里的具体含义、常见误解。

---

## 1. 核心对象术语

### SampleTask（任务定义）

- **在本项目里的具体含义**：一次 benchmark run 的最小任务单元。包含 `task_id`、`query`（查询文本）、`family`（所属任务族）、`complexity_bucket`（复杂度桶）、`case contract`（用例合同——expected route/tool、acceptable sets、disallowed families）、`prior dependency`（前序依赖）等字段。
- **常见误解**：它不是"一个简单的问答对"。它包含了完整的评估合同和依赖关系。

### Plan（执行计划）

- **在本项目里的具体含义**：Planner 产出的结构化步骤序列。包含一组 `PlanStep`，定义了每个 step 的语义角色（semantic_role）、负责 Agent（owner_agent）、动作类型（action）、依赖关系（depends_on）。
- **常见误解**：Plan 不是“随便让 LLM 自由聊天生成的”。它总是受 task contract（任务合同）、capability table（能力表）和 schema（结构合同）约束。不同 pack 会固定不同来源：有些机制 pack 用 `yaml`，当前 active communication headline `superiority_comm_v1` 用 `llm`。

### PlanStep（计划步骤）

- **在本项目里的具体含义**：Plan 中的单个步骤。关键字段：`step_id`（步骤标识）、`owner_agent`（负责 Agent）、`action`（RETRIEVE_EVIDENCE/EXECUTE_PLAYBOOK/SUMMARIZE_AND_COMMIT/VALIDATE_ROUTE）、`semantic_role`（retrieve/validate/execute/summarize）、`input_state_refs`（输入状态引用列表）、`params`（参数）、`depends_on`（依赖的前序步骤）。
- **常见误解**：`semantic_role` 不是 Agent 名字——它是步骤的语义功能标签，用于驱动执行引擎调度。

### StepResult（步骤结果）

- **在本项目里的具体含义**：步骤执行完成后的结果对象。包含 `output_state_refs`（输出状态引用列表）、`status`（成功/失败）、`metrics`（执行指标）。
- **常见误解**：它不是"Agent 回复的文本"。它是结构化的结果对象，其中的重数据通过 StateRef 引用。

### StateRef（状态引用）

- **在本项目里的具体含义**：一个轻量级引用对象（50-80 字节），指向 StatePool 中的实际数据。关键字段：`state_id`、`kind`（状态种类，如 DENSE_EVIDENCE）、`length`、`blob_hash`（内容 SHA-256 哈希）、`channel`（归属通道）、`storage`（存储后端）、`handle`（后端句柄）、`compatibility`（兼容性元数据）。
- **常见误解**：它不是"一个字符串 ID"。它带完整元数据，支持内容寻址、dedup（去重）、replay restore（回放恢复）。

### MemoryHit（记忆命中）

- **在本项目里的具体含义**：MemoryStore 查询返回的结果。包含 `memory_id`、`score`（匹配分数）、`tier`（记忆层级）、`source_agent_id`（来源 Agent）、`summary`（摘要）、`evidence_refs`（证据引用）。
- **常见误解**：`MemoryHit` 不等于"复用收益"。只有在 validated_replay 或 exact_replay 模式下，命中才可能转化为 skip_execute。

### MemoryCommit（记忆写入记录）

- **在本项目里的具体含义**：Summarizer 在 task 完成时写到 MemoryStore 的记录。包含 `memory_id`、`source_agent_id`、`created_at`（创建时间）、`task_theme`（任务主题）、`summary`（摘要）、`evidence_refs`、`replay_episode`（回放记录）。
- **常见误解**：它不是"Summarizer 输出的全文总结"。它是一个结构化的持久化记录，嵌入向量和元数据分别存储在 FAISS 和 SQLite 中。

### RunContext（运行时上下文）

- **在本项目里的具体含义**：一次 task 运行的总线对象。通过 `Orchestrator.create_context()` 创建，挂载了 session、state refs、metrics、results、memory hits、replay decision、execution DAG（执行有向无环图）。
- **常见误解**：它不是"全局配置对象"。它是 per-task 的运行时总线，保证不同 task 之间的隔离。

---

## 2. 实验变量术语

### mode（模式）

- **控制什么**：Agent 间通信格式——`text`（自然语言文本）vs `protocol`（结构化协议）。
- **在本项目里的具体含义**：决定 Agent 间 handoff 的载体：全文本透传还是结构化 packet + StateRef。
- **改它会影响哪条结论**：communication headline（通信开销对比）、state transfer（状态传递对比）。

### transfer_strategy（传递策略）

- **控制什么**：状态的传递方式。
- **在本项目里的具体含义**：8 种策略：`text_whole_lane`（全通道文本）、`text_strict_pure_lane`（严格纯文本）、`natural_handoff_text`（自然交接文本）、`state_packet_minimal`（最小状态包）、`text_brief`（文本摘要）、`text_packet_minimal`（文本最小包）、`channel_store_hashref`、`flat_state_ref`。
- **改它会影响哪条结论**：typed-state 机制证据、handoff wire/payload bytes。

### handoff_profile（交接配置）

- **控制什么**：Agent 间 handoff 时的信息密度和格式。
- **在本项目里的具体含义**：定义 Executor 收到的信息是以 full evidence 内联还是以精简 typed packet 呈现。
- **改它会影响哪条结论**：communication 开销、Executor 消费方式。

### runtime_reuse_contract（运行时复用合同）

- **控制什么**：记忆复用的策略级别。
- **在本项目里的具体含义**：4 级：`reuse_disabled`（禁用复用）→ `assist_allowed`（允许辅助）→ `validated_replay`（验证回放）→ `exact_replay`（精确回放）。
- **改它会影响哪条结论**：memory replay effect、`skipped_step_count`、`reuse_gain`。

### plan_source（计划来源）

- **控制什么**：Plan 是来自固定 YAML 文件还是 LLM 实时生成。
- **在本项目里的具体含义**：`yaml`（固定脚本化 plan，用于受控对照）vs `llm`（LLM 自主规划，用于证明开放规划能力）。
- **改它会影响哪条结论**：planner support 证据、系统开放规划能力。

### benchmark_lane（评测通道）

- **控制什么**：指标归属于哪条赛题轴。
- **在本项目里的具体含义**：`communication`、`state_transfer`、`memory`、`integrity`、`internal_regression`。每个 lane 对应不同的 claim 和不同的 gate。
- **改它会影响哪条结论**：claim lane 归因——避免把所有指标混在一个维度里解读。

### variable_axes（变量轴）

- **控制什么**：该 pack 的 single-variable contract（单变量合同）标识。
- **在本项目里的具体含义**：标识该 pack 只改变了哪个变量（如 `mode`），证明它是单变量对照实验。
- **改它会影响哪条结论**：如果 pack 没有 clear single-variable contract，它的结论不能用于 formal claim。

---

## 3. 结果解释术语

### headline（主结论）

- **在本项目里的具体含义**：当前承担正式主结论职责的 object。headline 是对象级概念，不等于“所有 gate 都过完”。当前 active communication headline object 是 `superiority_comm_v1`；`contest_honest_headline_v1` 是历史 frozen formal headline / carrier-isolation object。
- **常见误解**：不是"所有正向结果都是 headline"，也不是"只有所有 gate 都过完才算 headline"。要区分 active headline object、communication gate、formal stability gate。

### support / formal-secondary（支撑/正式二级）

- **在本项目里的具体含义**：已成立但不应替代 headline 的机制证据。在 final report 中是 required secondary verdict（必需二级判定），不是 appendix-like optional support（可选附录）。
- **常见误解**：support 不等于"不重要"。它是赛题完整性的必要组成部分（如 typed-state mechanism、memory replay effect），但不能抢 communication headline 的位置。

### audit（审计）

- **在本项目里的具体含义**：仅供消融分析、边界验证或历史对照的证据面。不能升格为 headline。
- **常见误解**：audit 对象可能在数字上看起来不错，但不能因此把它当 headline 用。

### authoritative artifact（权威产物）

- **在本项目里的具体含义**：当前冻结 docs 明确指向的、作为正式结论依据的 run artifact。包含 `benchmark_report.md`、`benchmark_results.json`、`benchmark_compare.csv`。
- **常见误解**：不是"最新生成的那个 run"。必须是冻结 docs 明确指定的那个。

### quality floor（质量底线）

- **在本项目里的具体含义**：protocol 路径不降低正确性的最低保证。由 `wrong_family_rate = 0.00` 和 `admissible_match_rate = 1.00` 来证明。
- **常见误解**：quality floor 稳定不等于"所有指标全面更好"。它只证明"没有变差"。

### `llm_total_tokens`（LLM 总 token）

- **在本项目里的具体含义**：一次 benchmark 对象里所有 LLM 调用消耗的总 token。
- **常见误解**：它不是只统计 Planner 和 Summarizer。当前实现里 Retriever 和 Executor 也会进入 role-specific LLM contract；只是当前 report 只单独拆出了 `planner_total_tokens` 与 `summarizer_total_tokens`，没有再单列 `retriever_total_tokens` / `executor_total_tokens`。

### parity（等价性）

- **在本项目里的具体含义**：text/protocol 两侧在某些指标上的对齐程度。parity diagnostic（等价性诊断）是辅助定位工具，不是"protocol 做错了"的证据。
- **常见误解**：parity divergence（等价性偏差）不等于 failure（失败）。只要 `admissible_match_rate = 1.00`，质量就没有退化。

### residual（残差）

- **在本项目里的具体含义**：已知但尚未闭合的结果偏差。当前主残差是 `summarize_ms` 轻度正残差。
- **常见误解**：residual ≠ failure（失败）≠ bug。它是"还需要进一步解释和处理"的部分。

---

## 4. 角色与结构术语

### Planner（规划器）

- **在本项目里的具体含义**：LLM 型 Agent。负责接收 task text 和 capability table，产出结构化 Plan（PlanStep 序列）。支持 yaml plan（固定）和 llm plan（自主）两种来源。支持 repair loop（修复循环，最多 3 次尝试）。

### Retriever（检索器）

- **在本项目里的具体含义**：检索增强的语义选择 Agent。负责 corpus retrieval（语料检索）、生成 typed state（DENSE_EVIDENCE、FEATURE_BUNDLE、TOOL_CANDIDATE_SET 等）、assist memory lookup（辅助记忆查询）、replay gate 准备（REPLAY_ELIGIBILITY_BUNDLE），并在当前代码里通过 retriever-role LLM contract 做 semantic selection。

### Executor（执行器）

- **在本项目里的具体含义**：语义决策 + 工具执行混合 Agent。负责 validate route（生成 VALIDATION_GATE_PACKET）和 execute playbook（消费 typed state 并执行工具）。支持本地执行和 UDS 外部 executor 样机。当前代码里会通过 executor-role LLM contract 做 route/tool/action_contract 的语义选择，然后再进入真实工具执行。

### Summarizer（总结器）

- **在本项目里的具体含义**：LLM 型 Agent。负责汇总 evidence 和 actions，生成 summary 和 MemoryCommit。既是控制面面向人的出口，也是记忆面的主要写入口。

### validate（校验——不是 Agent）

- **在本项目里的具体含义**：`semantic_role` 的一种（`validate`），也是 LangGraph 图中的一个可选节点。逻辑由 ExecutorAgent 执行。**它不是第五个 Agent**。

### control plane（控制面）

- **在本项目里的具体含义**：承载 Agent 间协议消息（谁做什么、下一步）的信息表面。存储和传递形式为 Protobuf 控制帧（线上传输）。
- **常见误解**：控制面不等于"所有通信"。数据面（状态面）负载不进入控制面消息体。

### state plane（状态面）

- **在本项目里的具体含义**：承载实际数据负载（检索结果、工具产物、特征向量）的信息表面。存储于 StatePool（本地 mmap/共享内存），通过 StateRef 引用。
- **常见误解**：state_bytes（状态字节数）不等于通信开销。通信开销只看 handoff_wire_bytes。

### memory plane（记忆面）

- **在本项目里的具体含义**：承载历史经验和跨任务知识的信息表面。存储于 SQLite（元数据）+ FAISS（向量索引），由 MemoryCommit 写入，由 MemoryHit 检索。

---

## 5. 任务结构术语

### family（任务族）

- **在本项目里的具体含义**：同一领域的一组 task，共享相同 corpus 和 domain 知识。当前有 5 个族：`auth_rotation`、`billing_queue_backlog`、`checkout_regression`、`deployment_config_drift`、`inventory_rollout`。

### complexity_bucket（复杂度桶）

- **在本项目里的具体含义**：任务的复杂度类型：`simple`（基准）、`distractor`（干扰项）、`ambiguous`（歧义/拒识）、`reusable`（可复用/跨任务记忆）。同一 family 下的不同 bucket 测试不同能力。

### S1 / S2（步骤厚度）

- **在本项目里的具体含义**：S1 是 fresh-retrieval（新鲜检索）独立任务，不带 prior dependency。S2 是 reusable（可复用）关联任务，携带 prior dependency contract，预期复用前序 S1 任务的记忆。
- **常见误解**：S2 不等于"第二步"。它是任务厚度（thickness）的标识，表示该 task 是否携带 prior dependency。

### negative control（负控）

- **在本项目里的具体含义**：故意创造出不应该成功的条件（如缺失 EXECUTOR_DECISION_PACKET），验证系统是否能正确识别并触发预期 failure。
- **常见误解**：负控 failure 不是 bug。它是证明"机制被真实消费"的关键证据。

### case contract（用例合同）

- **在本项目里的具体含义**：每个 task 的评估合同，定义 scorer 如何判断正确性。包含 `case_type`、`expected_family`、`primary_expected_route`、`primary_expected_tool`、`acceptable_routes`、`acceptable_tools`、`disallowed_families`、`abstention_allowed` 等。

---

## 6. 首次建议阅读顺序

如果你刚接触这个项目，建议按以下顺序使用本文档：

1. 先读 [02_project_goal_and_method_overview.md](./02_project_goal_and_method_overview.md)，了解项目在解决什么问题
2. 对照本文档理解遇到的核心术语
3. 再读 [03_system_architecture_and_dataflow_explainer.md](./03_system_architecture_and_dataflow_explainer.md)，理解系统如何运作
4. 遇到不认识的实验变量时回到"实验变量术语"部分
5. 遇到不认识的指标时回到"结果解释术语"部分
