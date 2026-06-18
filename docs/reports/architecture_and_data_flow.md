# StateBus 架构与完整工作流

日期：2026-06-16

---

## 一、系统对象定义

StateBus 是一个四 Agent 协作运行时，核心设计是参考赛题"低开销通信、非文本状态传递、共享记忆复用"三项要求，把通信拆成三个面：

| 面 | 传什么 | 存储在哪 | 通信量指标 | 典型内容 |
|----|--------|---------|-----------|---------|
| **控制面** | 谁干什么、下一步 | 协议消息（线上） | `control_bytes` | Plan/PlanStep/StepResult/Ack/Hello |
| **状态面** | 实际数据（中间结果） | StatePool（mmap 文件） | `handoff_wire_bytes`（线上指针）+ `handoff_payload_bytes`（本地负载） | evidence 文本、EXECUTOR_DECISION_PACKET、VALIDATION_GATE_PACKET |
| **记忆面** | 历史经验 | SQLite + FAISS | — | 每次 task 的摘要、证据引用、replay 线索 |

**关键边界**：控制面只传指针（`StateRefLite{state_id, kind, length}` ≈ 50-80 字节/个）。实际数据在 StatePool 的 mmap 文件里，Agent 通过指针去本地读取。这就是赛题要求"不得仅通过自然语言长文本直接透传全部协作信息"的核心实现——重状态不进入消息体，只在控制面传引用，在数据面做零拷贝读取。`handoff_wire_bytes`（线上指针）≠ `handoff_payload_bytes`（本地负载）。

系统支持两种通信模式：**纯文本协作模式**和**结构化协议协作模式**。在纯文本模式下，Agent 间通过自然语言 structured text 传递 route/tool 等决策信息；在结构化模式下，通过 Protobuf 控制帧传递动作语义，通过 StateRef 指针引用 mmap 中的 typed state（EXECUTOR_DECISION_PACKET 等 msgpack 序列化对象）。

---

## 二、文件架构与职责


```
project/
├── runtime/                       ← 核心运行时
│   ├── orchestrator.py              编排引擎。负责 task 派发、plan 编译、semantic_role 驱动的步骤调度、
│   │                                  replay gate、prior dependency enforcement、TaskCommit 密封。
│   │                                 通过 RunContext 管理每个 task 的完整执行状态。
│   │
│   ├── executor_runtime.py           执行层。定义 9 种 transfer strategy 的分派逻辑、ToolRegistry（10+
│   │                                 工具及其 match pattern）、build_feature_bundle() 路由推理、
│   │                                 execute_playbook_step() 主执行函数。
│   │
│   ├── langgraph_adapter.py          LangGraph 编排适配器。构建 5 节点 DAG（planner→retriever→[validate]
│   │                                 →executor→summarizer）+ 条件路由。每个节点内部调用 Orchestrator
│   │                                 原语，LangGraph 层管理 graph state 传播和失败传播。
│   │
│   ├── contracts.py                  Schema 校验层。StateContractRegistry 注册 15+ 状态合同、
│   │                                 StepInputContract 定义 Agent 间合法的 state 传递链路、
│   │                                 SchemaInterceptor 校验 plan/step/result 合法性、
│   │                                 VALIDATION_GATE_PACKET 的验证合同。
│   │
│   ├── llm.py                        LLM 抽象层。OpenAICompatibleLLMClient（真实 API 调用）+
│   │                                 DeterministicLLMClient（测试用）。含 planner/summarizer 的
│   │                                 prompt 构造、LLM 输出解析（JSON extraction、tagged block）。
│   │
│   ├── reuse_contract.py             复用合同。4 级复用策略（reuse_disabled→assist_allowed→
│   │                                 validated_replay→exact_replay）→ 3 个 boolean gate。
│   │
│   ├── task_profile.py               任务配置归一化。9 种 handoff profile、8 种 transfer strategy、
│   │                                 4 种 benchmark lane 的定义和解析。
│   │
│   ├── codeact_runner.py             CodeAct 受控代码执行（experimental，非主线）。
│   ├── remote_executor.py            UDS 远端执行器样机。
│   ├── uds_transport.py              AF_UNIX 消息传输。
│   └── smoke.py                      烟雾测试入口。
│
├── agents/                        ← Agent 实现
│   ├── sample_agents.py              PlannerAgent（LLM 规划，支持 repair loop 最多 3 次尝试）、
│   │                                 RetrieverAgent（corpus 检索 + typed state 生成 + memory assist）、
│   │                                 ExecutorAgent（工具执行 + _validate_route_step 真实校验 +
│   │                                 VALIDATION_GATE_PACKET 生成）、
│   │                                 SummarizerAgent（LLM 总结 + MemoryCommit 生成）。
│   │                                 含 PLANNER_ROLE_BINDINGS（semantic_role→owner_agent/action 映射）。
│   │
│   └── base_agent.py                 BaseAgent 抽象基类。
│
├── protocol/                      ← 通信协议层
│   ├── messages.py                   14 种消息类型的 dataclass 定义 + Protobuf/JSON 双向序列化 +
│   │                                 semantic_role 字段（PlanStep 的属性，使 step 语义与 step_id 解耦）。
│   │                                 定义 StateRef（typed state 引用）、Plan/PlanStep（含 depends_on DAG）、
│   │                                 StepResult（含 output_state_refs）、MemoryCommit、TaskCommit 等。
│   │
│   ├── statebus.proto                WireEnvelope oneof 定义：12 种消息类型统一序列化为 protobuf bytes。
│   ├── statebus_pb2.py               编译生成的 Python protobuf stub。
│   └── channels.py                   StateChannel 定义 + 8 个 channel registry（evidence/route/tool_candidates 等）。
│
├── memory/                        ← 共享记忆
│   └── store.py                      MemoryStore。SQLite 存储元数据（ID/来源 Agent/时间/主题/摘要），
│                                     FAISS 存储向量索引。支持 assist 语义检索和 replay 精确查询。
│                                     多信号融合排序：semantic × tier + 0.25×BM25 + 0.20×tag + 0.10×recency。
│                                     支持 4 个 tier：working/long_term/replay_episodes/task_commits。
│
├── statepool/                     ← 状态池（数据面）
│   └── store.py                     FileBackedStatePool(mmap) + SharedMemoryStatePool +
│                                     ContentAddressedBlobStore（SHA-256 内容寻址，支持 replay 去重）。
│
├── eval/                          ← 评测层
│   ├── runner.py                     run_benchmark() 主入口。task 加载→ mode 交替执行→ 指标聚合→
│   │                                 report 生成。含 gate 函数系列（object_parity_gate、
│   │                                 memory_replay_evidence_gate、contest_formal_coverage_gate、
│   │                                 _whole_lane_text_guard_payload 等）。6 层聚合：
│   │                                 per-task→per-group→per-reuse-slice→per-lane→per-mode→cross-repeat。
│   │
│   ├── metrics.py                   TaskMetrics dataclass：60+ 基础指标 + derived properties
│   │                                 (assist_memory_hit_rate、reuse_gain、planner_one_shot_valid、
│   │                                 planner_repair_rate、replay_apply_rate 等)。
│   │
│   ├── open_runner.py               Open surface engineering simulator（audit-only，deterministic oracle 模式）。
│   └── text_open_baseline.py        External text baseline（lexical deterministic runtime，audit-only）。
│
├── tasks/                         ← 任务定义（YAML）
│   ├── sample_tasks.py               SampleTask dataclass（60+ 字段：task_id/query/corpus_doc_ids/
│   │                                 transfer_strategy/required_prior_case_ids 等）、build_plan()（含
│   │                                 validate step 的条件生成）、public_surface 系统（4 类 + 8 alias）、
│   │                                 YAML 加载和 contract 校验。
│   │
│   ├── contest_family_spec.yaml      Contest 的全部 family spec（~1,600 行，单源真相）。包含 5 个 family
│   │                                 的 docs（8 类/族）和 cases（4 复杂度/族）定义。
│   │
│   ├── contest_family_spec.py        生成器：解析 spec → 生成 contest_dual_mode_controlled_v3_benchmark.yaml
│   │                                 + contest_release_regression_corpus.yaml。维护入口只在 spec 文件。
│   │
│   ├── local_corpus.py               CorpusDoc 检索逻辑。semantic + lexical + tag 混合检索。
│   │                                 支持 formal_structure_clean_retrieval 模式（关闭 theme/group bonus、
│   │                                 不注入 preferred doc shortlist、不消费 runtime hint）。
│   │
│   ├── contest_dual_mode_controlled_v3_benchmark.yaml     formal headline (40 task, text+protocol)
│   ├── memory_policy_controlled_v3_benchmark.yaml          formal memory (8 task, protocol-only)
│   ├── typed_state_mechanism_v3_benchmark.yaml             formal typed-state (8 task, protocol-only)
│   ├── planner_support_v3_benchmark.yaml                   formal planner (11 task, protocol-only)
│   └── *_benchmark.yaml                                    其余 8 个 audit/support/legacy pack
│
├── scripts/                       ← 运行脚本
│   ├── run_v3_api_repeat3_suite.py    全量 API repeat=3 suite
│   ├── generate_contest_family_yaml.py 从 family spec 生成 contest YAML + corpus YAML
│   └── run_issue_discovery_smoke.sh   定向 issue discovery smoke（5 block）
│
└── tests/ (191 pytest)
```

---

## 三、LangGraph 编排架构

系统使用 LangGraph 作为 task 执行编排的基础设施。LangGraph 构建一个 5 节点的有向无环图（DAG），管理 task 执行的完整生命周期。

```
StateBusGraphRunner.build_langgraph()                  runtime/langgraph_adapter.py:185-197

    graph.add_node("planner",    → _planner_node)      编译 plan（调用 orchestrator.compile_task_plan）
    graph.add_node("retriever",  → _retriever_node)    检索 + replay gate 检查
    graph.add_node("validate",   → _validate_node)     路由验证（按 plan 结构可选加入）
    graph.add_node("executor",   → _executor_node)     工具执行 + validate gate 检查
    graph.add_node("summarizer", → _summarizer_node)   LLM 总结 + MemoryCommit

    graph.set_entry_point("planner")
    graph.add_edge("planner", "retriever")

    graph.add_conditional_edges("retriever", _next_after_retrieve)
    → plan 含 semantic_role="validate" 的步骤时路由到 validate 节点
    → 否则直通 executor 节点

    graph.add_edge("validate", "executor")
    graph.add_edge("executor", "summarizer")
    graph.add_edge("summarizer", END)
```

**LangGraph 的具体职责**：
- **Graph state 管理**：每个节点执行后，`_refresh_state_snapshot()` 将 ctx 中的 results、state_refs、memory_hits、metrics、replay_decision 拷贝到 graph state dict，保证节点间状态传播
- **失败传播**：任一节点失败 → `state["status"] = "failed"` → 后续节点检查状态后跳过
- **条件路由**：`_next_after_retrieve()` 根据 Plan 结构（是否含 `semantic_role="validate"` 的步骤）决定下一步走 validate 还是 executor

每个 LangGraph 节点内部**不包含业务逻辑**——它调用 Orchestrator 的公开方法（`compile_task_plan`、`resolve_skip_retrieve_execute`、`invoke_plan_step`、`register_step_result` 等）。Orchestrator 承担所有业务语义：plan 编译、步骤执行、replay gate 决策、schema 校验、StatePool/MemoryStore 副作用。

**为什么用 LangGraph**：它提供标准化的 DAG 编排能力（条件路由、状态传播、失败处理），让 benchmark runner 不需要自己实现执行循环。Orchestrator 也可以独立运行（在测试中使用），LangGraph 和 Orchestrator 的关系是编排层和语义层的分离。

---

## 四、完整执行工作流

### 4.1 入口：benchmark runner 发起 task

Benchmark 从 `eval/runner.py` 的 `run_benchmark()` 启动。加载指定 pack 的 YAML → 创建 StateBusGraphRunner → 为每个 task 创建 RunContext → 串行执行。

```
run_benchmark(task_set, repeat, modes)                  eval/runner.py
  │
  ├─ load_task_set_bundle() → SampleTask[]              tasks/sample_tasks.py
  │   └─ YAML → TaskSetMetadata + tuple[SampleTask]
  │      public_surface / evidence_tier / variable_axes / plan_source_default
  │
  └─ for run_index in range(repeat):
       for mode in modes:
         │
         ├─ 创建 RunSession(mode) / StatePool(MMAP_FILE) / MemoryStore(SQLite+FAISS)
         ├─ 创建 StateBusGraphRunner (langgraph 编排)
         │
         └─ for task in tasks:
              │
              ├─ ctx = Orchestrator.create_context(...)
              │    ctx.runtime_profile → transfer_strategy, handoff_profile
              │    ctx.runtime_gates   → allow_memory_assist / allow_execute_prune / allow_exact_replay
              │
              └─ await graph_runner.run_task(task, ctx)
                   → build_langgraph().ainvoke(state)
                   → 5 个节点顺序执行（含条件路由）
```

### 4.2 Planner — 任务规划

Plan 编译是执行的第一步。系统支持两种 plan 来源：

**yaml plan**：`build_plan()` 从 SampleTask 生成固定 3-step plan（retrieve→execute→summarize），每步标记 `semantic_role`。当 task 的 `required_plan_semantic_roles` 含 `validate` 时，自动插入 validate 步骤变为 4-step。不调 LLM——用于受控实验（contest 和 memory_policy 包通过 `plan_source_default: yaml` 使用此模式）。

**llm plan**：`PlannerAgent.plan_task()` 通过 LLM 生成计划。流程是：

```
compile_task_plan(task, ctx)
  │
  ├─ plan_source == "yaml" → build_plan(task)
  │
  └─ plan_source == "llm" → PlannerAgent.plan_task()
        │
        ├─ _planner_messages() → 构造 LLM prompt
        │   ├─ 注入 required_plan_semantic_roles（如 ["retrieve","validate","execute","summarize"]）
        │   ├─ protocol 模式：提示 LLM 产出显式 {"steps":[...]} 格式
        │   └─ 禁止 planner 作为 step owner
        │
        ├─ LLM 调用（支持 repair loop: 最多 3 次尝试）
        │   └─ _plan_from_llm_output() 解析失败时，_planner_repair_messages()
        │      构造修复提示，把原 LLM 输出和验证错误传给 LLM 重新生成
        │
        ├─ _plan_from_llm_output()
        │   ├─ extract_json_object() → 解析 LLM 输出
        │   ├─ _normalize_planner_step() → 通过 PLANNER_ROLE_BINDINGS
        │   │   校验 semantic_role 对应的 owner_agent 和 action 是否正确
        │   ├─ _validate_plan_dag() → DAG 无循环、step_id 唯一
        │   └─ _validate_planner_semantic_coverage() → 检查 required_roles 全部覆盖
        │
        └─ 产出 Plan(steps=[PlanStep(semantic_role="retrieve", ...), ...])

prepare_plan(plan, ctx):
  ├─ ctx.set_step_role(step.step_id, step.semantic_role)   ← 注册语义角色映射
  ├─ SchemaInterceptor.validate_plan()                      ← DAG 合法性 + CapabilityTable 校验
  └─ ctx.emit(plan) → protobuf 序列化 → control_bytes 累加
```

### 4.3 执行循环 — semantic_role 驱动的步骤调度

，当前使用 `semantic_role` 驱动步骤调度。这意味着 Plan 的步骤可以任意命名（如 `"gather-001"`），只要 `semantic_role` 正确，执行引擎就能找到对应的处理逻辑。

```
_execute_plan(plan, ctx)                                orchestrator.py:947

  for step in plan.steps:
    step_role = ctx.semantic_role_for_step(step.step_id)

    if step_role == "retrieve":
      │
      ├─ [Replay Gate 1: 精确回放]
      │   resolve_skip_retrieve_execute(plan, ctx)
      │   ├─ 条件: allow_exact_replay + prior_dependency_satisfied
      │   ├─ ctx.replay_candidates() → memory_store.replay_candidates()
      │   ├─ 匹配: task_theme + route(非generic) + query精确匹配
      │   │        + evidence_sha256 + route_confidence≥0.80 + lexical prov
      │   └─ 匹配成功 → 合成 retrieve+execute StepResult
      │       ctx.skipped_step_count += 2 → 跳过后续 retrieve/execute
      │
      └─ RetrieverAgent.execute_step()
            ├─ retrieve_corpus_docs() → 语义+词法检索
            ├─ _resolve_runtime_corpus_hints() → formal 包返回空
            ├─ build_feature_bundle() → route/tool/confidence/evidence_hash
            ├─ 按 transfer_strategy 生成 typed state
            └─ 返回 StepResult(output_state_refs=[...])

    if step_role == "validate":
      │
      └─ ExecutorAgent._validate_route_step()
            ├─ 读 EXECUTOR_DECISION_PACKET (msgpack)
            ├─ 读 retrieve_result.payload
            ├─ 8 项校验: route非空/非generic_triage → confidence≥0.5
            │   → tool在acceptable_tools → doc_ids非空
            │   → decision_packet与retrieve一致性
            ├─ 产出 VALIDATION_GATE_PACKET typed state
            └─ validation_success=False → 后续 execute 将被阻断

    if step_role == "execute":
      │
      ├─ [Replay Gate 2: 执行剪枝]
      │   resolve_skip_execute(plan, ctx)
      │   ├─ 条件: allow_execute_prune + retrieve_result存在 + prior_dependency_satisfied
      │   ├─ 匹配: route+evidence_hash→ ctx.skipped_step_count += 1
      │   └─ 不匹配 → 继续正常流程
      │
      ├─ [Validate Gate] 读 VALIDATION_GATE_PACKET (如有)
      │   └─ validation_success != true → raise ValueError，阻断执行
      │
      └─ ExecutorAgent.execute_step()
            ├─ 按 transfer_strategy 选择 execution 路径
            ├─ state_packet_minimal: 读 EXECUTOR_DECISION_PACKET → route/tool
            ├─ text_strict_pure_lane: 解析 structured text handoff
            ├─ select_tool_name() → ToolRegistry
            └─ _invoke_tool() → playbook 执行 → TOOL_ARTIFACT

    if step_role == "summarize":
      │
      └─ SummarizerAgent.execute_step()
            ├─ protocol 模式: 收 compact JSON structured digest
            ├─ text 模式: 收纯文本 evidence
            ├─ LLM 调用 → summary + tags + reusable_steps
            ├─ MemoryCommit × 2 (assist + replay)
            └─ ctx.commit_memory() → SQLite + FAISS
```

### 4.4 9 种 Transfer Strategy 详解

Transfer strategy 决定了 Retriever 产出什么、Executor 收到什么。系统当前定义了 9 种 strategy，对应不同的赛题验证需求：

| Strategy | Retriever 产出 | Executor 输入 | 使用场景 |
|---|---|---|---|
| `text_strict_pure_lane` | structured text handoff（含 Route:/Tool: 显式字段） | 解析 handoff 文本中的 route/tool | contest formal headline 的 text 侧。公平性修复后，executor 不独立做词法匹配 |
| `text_whole_lane` | 自然语言 handoff（无结构化字段） | 纯自然文本，无 route/tool 信息 | memory fairness 的 text 侧。格式固有限制：无法携带结构化决策 |
| `state_packet_minimal` | DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET (msgpack) | 直接读 decision packet 的 route/tool | contest/memory_policy/replay 的 protocol 侧。最小 typed state 集合 |
| `natural_handoff_text` | DENSE_EVIDENCE + TOOL_ARTIFACT 自然文本 | 读 TOOL_ARTIFACT 中的 route/tool | typed_state_mechanism 对照实验 |
| `inline_text_handoff` | 纯 inline text（零 typed state ref） | 零 StateRef，executor 只读文本 | text_definition audit：验证 executor boundary |
| `text_packet_minimal` | DENSE_EVIDENCE + TOOL_ARTIFACT text packet | 解析 text packet 中的 route/tool | carrier microbench：对比 text packet vs state packet 的工程开销 |
| `text_brief` | Key-Value 文本 brief | 解析 brief 文本 | 旧兼容 |
| `state_ref` | FEATURE_BUNDLE + CHANNEL_SNAPSHOT + TOOL_CANDIDATE_SET + RANKED_EVIDENCE + REPLAY_ELIGIBILITY + EMBEDDING | 读多个 typed state ref | full rich audit：查看所有 rich helper 对象的可见性 |
| `protocol_full_rich_audit` | 同上 + 全量 rich typed state | 同上 | audit support |

**公平性合同**：当前 lane policy 的核心约束是——两种 lane 的 executor 都只消费上游 handoff 对象中显式给出的 route/tool，不做独立 lexical recovery。text_strict_pure_lane 从 structured text 中解析 route/tool，state_packet_minimal 从 msgpack packet 中直接读取。两条路径对称，差异只来自 handoff 对象的格式能力，不来自 executor 的补救能力。

### 4.5 指标采集体系

每个 task 执行完成后，`RunContext.metrics` 包含 60+ 基础指标字段。通过 `TaskMetrics.to_dict()` 导出，再由 runner 的 6 层聚合系统生成 benchmark report。

```
每个 task 的指标:
  ├─ 通信面
  │   control_bytes, text_bytes, protocol_bytes    ← 控制面字节数
  │   handoff_wire_bytes, handoff_payload_bytes    ← 状态面线上指针 vs 本地负载
  │   handoff_textual_bytes, handoff_nontext_bytes ← 状态面文本 vs 非文本分解
  │   handoff_ref_count, handoff_nontext_ref_count ← StateRef 指针计数
  │
  ├─ LLM 面
  │   planner_total_tokens, summarizer_total_tokens, llm_total_tokens
  │   planner_llm_request_count, planner_repair_attempt_count
  │
  ├─ 记忆面
  │   assist_memory_hit_rate ← assist 路径命中率
  │   replay_probe_hit_rate  ← replay 候选命中率
  │   skipped_step_count, reuse_gain
  │
  ├─ 正确率面
  │   route_exact_rate, tool_exact_rate, exact_match_rate
  │   admissible_match_rate, abstention_rate, wrong_family_rate
  │
  ├─ typed-state 消费面
  │   typed_executor_minimal_expected_consumption_rate
  │   executor_expected_kind_match_rate
  │   executor_unexpected_kind_seen_rate
  │
  └─ Planner 面
      planner_one_shot_valid, planner_repair_rate
      planner_contract_valid_final

聚合层次:
  per-task → per-group (_aggregate_task_groups)
          → per-reuse-slice (_aggregate_named_task_summaries)
          → per-lane (_aggregate_named_task_summaries)
          → per-mode (_aggregate_mode_runs)
          → cross-repeat (_build_stability_summary)
          → headline gates (_build_headline_gates)

输出:
  benchmark_results.json  ← 完整 JSON
  benchmark_report.md     ← markdown 报告
  benchmark_compare.csv   ← per-family 对比 CSV
```

---

## 五、记忆流：写入、检索与 Replay

### 5.1 写入路径

每次 task 的 Summarizer 生成两份 MemoryCommit：

- **assist_commit**（`purpose="assist"`）：轻量级，只包含 route/summary 文本，用于后续 task 的 assist 提示
- **replay_commit**（`purpose="replay"`）：重量级，包含 evidence_state_refs（指向 retriever/executor 产出的全部 StateRef），用于严格 replay gate 匹配

两条 commit 都通过 `ctx.commit_memory()` 同时写入 SQLite（元数据）和 FAISS（向量索引）。写入后通过 `faiss_outbox` 异步同步索引。

### 5.2 检索路径

**assist 查询**（在 RetrieverAgent 中）：通过 `ctx.search_memory()` 发起。FAISS 语义搜索 + SQLite metadata/tag 过滤，多信号融合排序（semantic × tier + 0.25×BM25 + 0.20×tag + 0.10×recency）。返回的 MemoryHit 用作候选 route 的辅助提示。

**replay 查询**（在 Orchestrator 的 gate 函数中）：通过 `ctx.replay_candidates()` 发起。SQLite 精确查询 WHERE task_theme=? AND memory_purpose=replay。返回的 MemoryHit 含 evidence_state_refs——如果能通过 route/docset/hash/query 的全匹配，则直接跳过步骤。

**prior dependency 查询**（在 task 执行前和 replay gate 中）：`_prior_dependency_satisfied()` 通过 `memory_store.task_commit_candidates()` 查找前序 task 的 TaskCommit，验证 `required_prior_case_ids` 和 `required_prior_rejections` 是否被满足。

### 5.3 Replay Gate 机制

| Gate | 触发条件 | 跳过的步骤 | 效果 |
|---|---|---|---|
| `resolve_skip_retrieve_execute` | exact_replay 开启 + route/evidence_hash/query 全匹配 + prior dependency 满足 | retrieve + execute | skipped += 2, reuse_gain 增加 |
| `resolve_skip_execute` | validated_replay 开启 + retrieve 已完成 + route/evidence_hash 匹配 + prior dependency 满足 | execute | skipped += 1 |

两个 gate 都通过 strict matching（非语义相似度）避免误跳。匹配条件包括：归一化 query 精确匹配、evidence_sha256 全一致、route 非 generic_triage、route_confidence 和 provenance 达标。

---

## 六、当前 Benchmark Surface（12 个 v3 pack）

12 个 pack 按赛题三条主线和支撑角色分层：

| 面 | pack | public_surface | 验证内容 |
|---|---|---|---|
| **通信+状态 headline** | contest_dual_mode_controlled_v3 | formal_headline | text vs protocol 同任务对照（40 task） |
| **状态传递机制** | typed_state_mechanism_v3 | formal_secondary | natural_text vs typed_packet 机制真实性（8 task） |
| **记忆单变量归因** | memory_policy_controlled_v3 | formal_secondary_memory | 单变量 replay 归因（8 task） |
| **Planner 能力** | planner_support_v3 | formal_secondary_planner | yaml vs LLM plan 对照（11 task） |
| **Consumer 消融** | typed_state_consumer_sensitivity_v3 | formal_secondary | 缺 packet/错 packet 的负控制（40 task） |
| **记忆 replay proof** | memory_reuse_v3 | formal_secondary | protocol-only replay（4 task） |
| **记忆公平性** | memory_dual_mode_fairness_v3 | audit_only | 双模式 object parity（40 task） |
| **包体工程** | carrier_microbench_v3 | audit_only | text_packet vs state_packet 开销（40 task） |
| **文本边界** | text_definition_audit_v3 | audit_only | inline text executor boundary（40 task） |
| **外部基线** | external_text_baseline_audit_v3 | audit_only | text-only surface（4 task） |
| **旧兼容** | typed_state_authenticity_v3 | audit_only | legacy compatibility（40 task） |
| **Rich audit** | typed_state_full_rich_audit_v3 | audit_only | 全量 rich helper 可见性（40 task） |

---
