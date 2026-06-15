# Requirements Decomposition — 题目.md

> Source: `docs/reference/题目.md` (41 lines)
> Title: 一种面向多智能体协作的低开销通信、状态传递与共享记忆机制

---

## A. Multi-Agent System (≥3 agents, ≥3 roles)

### A1. Agent Count and Role Diversity

| Field | Detail |
|---|---|
| **Exact original text** | `至少3个agent、3类任务` / `系统需支持不少于 3 个 Agent 协同运行，至少覆盖任务规划、信息检索、总结生成、工具执行等角色中的 3 类，并能够完成一个包含多步骤处理过程的复杂任务` (lines 7–8) / `系统支持不少于3个Agent协同运行，覆盖规划、检索、执行、总结等角色` (line 28) |
| **Engineering meaning** | The system must instantiate ≥3 distinct agent processes/workers, each assigned ≥1 role from the set {Planner, Retriever, Summarizer, Executor}. These agents must collaboratively complete a multi-step complex task (not a single-turn Q&A). "Agent" means a runtime entity with an identity, a role, and the ability to send/receive messages. |
| **"Satisfied" evidence** | (a) Code defines 3+ agent classes/instances with distinct role labels. (b) A run log shows all 3+ agents participating in ≥1 end-to-end task with ≥3 sequential steps. (c) Each agent's messages are attributable to its role. |
| **"Superiority" evidence** | (a) Scale to 5–10 agents with dynamic role assignment. (b) Agents can assume multiple roles or switch roles mid-task (role fluidity). (c) New agents can join a running task without restart. (d) Demonstrate that adding agents improves throughput or accuracy (not just counts). |
| **Scoring weight** | `系统完整性 (20分)` — number of agents, role coverage, and multi-step task completion |

---

### A2. Multi-Step Complex Task Execution

| Field | Detail |
|---|---|
| **Exact original text** | `能够完成一个包含多步骤处理过程的复杂任务` (line 8) |
| **Engineering meaning** | The task must have a DAG of sub-tasks with dependencies (not just linear). Agents must coordinate: Planner decomposes, Retriever fetches, Executor acts, Summarizer condenses. Intermediate outputs from one step feed into the next. |
| **"Satisfied" evidence** | Task trace shows ≥3 sequential or parallel sub-steps with distinct agent handoffs. At least one step's input depends on a prior step's output. |
| **"Superiority" evidence** | (a) Task DAG with branching/merging, parallel sub-tasks assigned to different agents. (b) Dynamic replanning when a step fails. (c) Sub-step parallelism reduces wall-clock time measurably. |
| **Scoring weight** | `系统完整性 (20分)` — complexity of task graph, dependency handling |

---

## B. Structured Communication (Protocol Design)

### B1. Structured Communication Mechanism

| Field | Detail |
|---|---|
| **Exact original text** | `系统需设计并实现一套面向 Agent 间协作的结构化通信机制，通信内容至少包括动作类型、输入参数、返回结果和能力描述` (lines 9–10) / `设计结构化通信协议替代自然语言交互` (line 29) |
| **Engineering meaning** | Define a message schema (protobuf, JSON Schema, dataclass, etc.) where every inter-agent message contains: (a) `action_type` (enum/string identifying the operation), (b) `input_params` (typed key-value payload), (c) `return_result` (typed response payload), (d) `capability_description` (what this agent can do — its exposed skills/roles). Messages must be parseable without LLM interpretation. |
| **"Satisfied" evidence** | (a) A schema file or dataclass defines the message format. (b) All inter-agent communication uses this schema (no raw NL strings as primary payload). (c) A parser validates incoming messages against the schema. (d) At least one run log shows messages with all four required fields populated. |
| **"Superiority" evidence** | (a) Versioned protocol with backward compatibility. (b) Schema is extensible (new action types without breaking old agents). (c) Protocol supports streaming/chunking for large payloads. (d) Protocol includes error codes, retry semantics, and timeouts. (e) Binary encoding (protobuf/Cap'n Proto) reduces wire size vs JSON. |
| **Scoring weight** | `通信效率 (25分)` — structure and compactness of protocol |

---

### B2. Handshake, Capability Discovery, Protocol Mapping

| Field | Detail |
|---|---|
| **Exact original text** | `支持基本的握手、能力发现或协议映射机制，不得仅通过自然语言长文本直接透传全部协作信息` (line 10) |
| **Engineering meaning** | Agents must not hard-code knowledge of peers. On startup or join: (a) **Handshake**: a greeting/ack protocol establishes agent presence and session. (b) **Capability discovery**: an agent advertises its roles/skills; other agents discover and route tasks accordingly. (c) **Protocol mapping** (or negotiation): agents agree on protocol version or message format. |
| **"Satisfied" evidence** | (a) Startup log shows agent A sending a HELLO/CAPABILITY message and agent B responding with ACK. (b) A planner routes a retrieval task to a retriever agent based on discovered capability, not hard-coded address. (c) Adding a new agent type works without changing existing agent code. |
| **"Superiority" evidence** | (a) Dynamic capability advertisement (agents can update capabilities at runtime). (b) Protocol version negotiation with fallback. (c) Service-mesh-style registry with health checks. (d) Late-binding: an agent discovers a peer mid-task and delegates to it. |
| **Scoring weight** | `通信效率 (25分)` — sophistication of discovery/negotiation |

---

### B3. No Raw Natural Language Passthrough

| Field | Detail |
|---|---|
| **Exact original text** | `不得仅通过自然语言长文本直接透传全部协作信息` (line 10) |
| **Engineering meaning** | The protocol must not be a thin wrapper around raw LLM text. Structured fields (action, params, etc.) must carry the functional payload; natural language may appear only as supplementary description (e.g., a `summary` field for human readability). |
| **"Satisfied" evidence** | At least one full task trace where the core decision/action information is transmitted via structured fields, and the system still completes the task correctly if NL description fields are stripped. |
| **"Superiority" evidence** | Protocol can operate in a "silent" mode with zero NL text — all task coordination happens via structured fields and semantic vectors alone. |
| **Scoring weight** | `通信效率 (25分)` — degree of NL elimination |

---

## C. Dual-Mode Comparison (Text vs Protocol)

### C1. Dual-Mode Support

| Field | Detail |
|---|---|
| **Exact original text** | `系统需同时支持"纯文本协作模式"和"结构化协议协作模式"` (line 12) |
| **Engineering meaning** | The system must have a toggle/flag to switch between: (a) Text mode: agents communicate via raw natural language strings (baseline). (b) Protocol mode: agents use the structured schema from B1. The same task logic must run under both modes with only the communication layer switching. |
| **"Satisfied" evidence** | (a) A config flag (`mode: text` / `mode: protocol`) changes the message layer. (b) The same task definition file runs under both modes. (c) Output logs show distinct message formats for each mode. |
| **"Superiority" evidence** | (a) Mode can be switched per-task or per-agent (mixed mode). (b) Automatic mode selection based on task type. (c) Protocol mode can fall back to text mode for unhandled cases. |
| **Scoring weight** | `实验验证 (15分)` — enables the comparison |

---

### C2. Reproducible A/B Comparison

| Field | Detail |
|---|---|
| **Exact original text** | `并在相同任务条件下完成可复现实验对比` (line 12) / `提供通信开销、任务时延、记忆复用等方面的性能对比数据` (line 33) |
| **Engineering meaning** | Run both modes on identical task inputs. Collect metrics. The comparison must be scripted and repeatable (same inputs → same outputs within statistical noise). Results must be reported in a table/chart. |
| **"Satisfied" evidence** | (a) A benchmark script runs N tasks under both modes. (b) Output shows per-task and aggregate metrics for both modes. (c) Re-running the script produces consistent results (±5%). |
| **"Superiority" evidence** | (a) Statistical significance tests (t-test or bootstrap confidence intervals). (b) Latency distributions (p50/p95/p99) not just means. (c) Ablation: which protocol features contribute most to savings. (d) Comparison across multiple task categories. |
| **Scoring weight** | `实验验证 (15分)` — reproducibility and rigor |

---

## D. Non-Text State Transfer

### D1. Non-Text Intermediate State Transfer Mechanism

| Field | Detail |
|---|---|
| **Exact original text** | `系统需实现一种非文本中间状态传递机制，支持 embedding、语义向量、隐藏状态特征或其他中间表示在 Agent 间直接交换` (line 13) / `实现非文本中间状态传递机制（embedding/语义向量/隐藏状态）` (line 30) |
| **Engineering meaning** | Instead of serializing Agent A's internal state to text → sending → Agent B parses text back to internal state, agents directly exchange a vector/embedding/tensor/hidden state. This is a "copy, don't convert" philosophy. The representation must be a dense numerical form (NumPy array, tensor, protobuf bytes) that preserves semantic information without text round-trip. |
| **"Satisfied" evidence** | (a) At least one task shows Agent A computing an embedding/vector, sending it via the protocol layer as a binary/vector field (not as a string of numbers), and Agent B using it directly (e.g., as a query vector for similarity search, or as a conditioning vector). (b) The downstream agent does NOT parse text to reconstruct the vector. |
| **"Superiority" evidence** | (a) Multiple state types: embeddings, hidden states from intermediate LLM layers, attention masks, logprobs. (b) Quantization/compression of state vectors without loss of downstream accuracy. (c) State transfer saves measurable time vs text round-trip (timing benchmark). (d) Agent B uses a received hidden state as a prefix/prompt-conditioning for its own generation. (e) Pipeline where state flows through 3+ agents without ever being textified. |
| **Scoring weight** | `状态传递创新 (20分)` — existence and variety of non-text transfer |

---

### D2. Generation, Transfer, Reception, and Usage Explanation

| Field | Detail |
|---|---|
| **Exact original text** | `并说明其生成方式、传递方式、接收方式及后续使用方式` (line 13) |
| **Engineering meaning** | Documentation must describe the full lifecycle: (a) **Generation**: which agent produces the state, using what model/algorithm (e.g., "Planner agent calls sentence-transformer to embed the task description"). (b) **Transfer**: how the state is serialized/packed and sent (e.g., "via UDS binary message, field `state_vector` of type `bytes`"). (c) **Reception**: how the receiving agent deserializes it. (d) **Usage**: what the receiving agent does with it (e.g., "Executor uses the embedding to query FAISS for similar past solutions"). |
| **"Satisfied" evidence** | System design document (or code comments) contains a section with these four sub-headings and concrete examples from the codebase. |
| **"Superiority" evidence** | (a) Design doc includes a sequence diagram showing the full lifecycle. (b) Multiple distinct generation methods demonstrated (different embedding models, different hidden state extraction techniques). (c) Quantitative analysis of serialization overhead. |
| **Scoring weight** | `状态传递创新 (20分)` — clarity and completeness of explanation |

---

## E. Shared Memory (Storage, Retrieval, Reuse)

### E1. Shared Memory Module

| Field | Detail |
|---|---|
| **Exact original text** | `系统需实现共享记忆模块，能够将任务执行过程中的中间结果、摘要、经验片段、证据链、结论或策略保存为统一的记忆单元` (lines 14–15) / `实现共享记忆模块，支持记忆的存储、检索和复用` (line 31) |
| **Engineering meaning** | A persistent store (SQLite + FAISS, or similar) that any agent can write to and read from. Memory units are structured records (not raw chat logs). Types of content: intermediate results, summaries, experience fragments, evidence chains, conclusions, strategies. The store must survive process restarts. |
| **"Satisfied" evidence** | (a) Module is a separate component with a clear API (`store()`, `retrieve()`, `search()`). (b) At least one run shows Agent A writing a memory after task completion and Agent B reading it during a subsequent task. (c) Memory persists across system restarts (restart → memory still queryable). |
| **"Superiority" evidence** | (a) Memory consolidation: similar memories are merged/deduplicated. (b) Memory decay/importance scoring: old, unused memories are pruned. (c) Multi-modal memory: stores both text summaries and embedding vectors. (d) Memory graph: links between memories (e.g., "this conclusion was derived from these evidence fragments"). (e) Streaming write: memories saved incrementally during task execution, not just at end. |
| **Scoring weight** | `记忆复用效果 (20分)` — richness of memory model |

---

### E2. Memory Record Metadata

| Field | Detail |
|---|---|
| **Exact original text** | `并为每条记忆记录至少包含记忆 ID、来源 Agent、创建时间、任务主题和摘要描述等基本元数据` (line 15) |
| **Engineering meaning** | Each memory record must have at minimum: `memory_id` (unique), `source_agent` (which agent created it), `created_at` (timestamp), `task_topic` (what task this memory relates to), `summary` (human-readable description). This is a schema requirement. |
| **"Satisfied" evidence** | (a) Memory schema/file shows all five fields. (b) A query returns memories with all fields populated. (c) Non-null constraints enforced (no memory stored without these fields). |
| **"Superiority" evidence** | (a) Additional metadata: `confidence` (reliability score), `expires_at`, `tags` (structured taxonomy), `dependencies` (links to other memory IDs), `version` (for updated memories). (b) Automated metadata extraction (LLM generates summary/topic from raw content). |
| **Scoring weight** | `记忆复用效果 (20分)` — schema completeness |

---

### E3. Memory Retrieval (Keyword, Tag, Semantic Similarity)

| Field | Detail |
|---|---|
| **Exact original text** | `系统需支持按关键词、标签或语义相似度检索历史记忆` (line 16) |
| **Engineering meaning** | Three retrieval modes: (a) Keyword: exact/partial string match on text fields. (b) Tag: filter by structured tag labels. (c) Semantic similarity: embed the query, search by vector distance (cosine/L2) against stored memory embeddings. |
| **"Satisfied" evidence** | (a) Code demonstrates all three retrieval modes. (b) A test query returns different (correct) results under each mode. (c) Semantic search returns memories that are topically relevant even with no keyword overlap. |
| **"Superiority" evidence** | (a) Hybrid retrieval: combine keyword + semantic scores (BM25 + vector). (b) Reranking: coarse semantic search → fine LLM rerank. (c) Query-time filtering by agent, time range, confidence. (d) Retrieval latency benchmark showing sub-100ms for >10K memories. (e) Recall@K evaluation against a labeled test set. |
| **Scoring weight** | `记忆复用效果 (20分)` — retrieval sophistication |

---

### E4. Cross-Agent Memory Reuse

| Field | Detail |
|---|---|
| **Exact original text** | `并允许不同 Agent 在后续任务中直接复用已有记忆` (line 16) |
| **Engineering meaning** | Agent A creates a memory in Task 1. In Task 2, Agent B (different agent) retrieves and uses that memory to skip computation, improve accuracy, or accelerate its work. "Directly reuse" means the memory content feeds into B's decision/action without human reinterpretation. |
| **"Satisfied" evidence** | (a) Task trace: Task 1 → Agent A stores memory M. Task 2 → Agent B queries, retrieves M, uses M's content (e.g., evidence snippet) in its output. (b) Task 2 shows reduced computation (fewer LLM calls, skipped steps) compared to running without memory. |
| **"Superiority" evidence** | (a) Reuse of strategy memories (not just factual snippets): Agent learns a problem-solving approach in Task 1, Agent B applies same strategy to a different domain in Task 2. (b) Memory chain: Task 3 reuses memories from both Task 1 and Task 2, showing compounding benefit. (c) Quantitative reuse gain: "hit rate > 60% on task chain of length 5+". |
| **Scoring weight** | `记忆复用效果 (20分)` — demonstrated cross-agent, cross-task reuse |

---

## F. Task Design (2+ Related Task Chains)

### F1. Two Related Sequential Task Chains

| Field | Detail |
|---|---|
| **Exact original text** | `系统需至少设计 2 组具有关联性的连续任务` (line 18) / `至少设计2组关联性连续任务进行验证` (line 32) |
| **Engineering meaning** | Design task sets where Task Set B naturally benefits from knowledge/memories generated in Task Set A. Each "set" is a sequence of sub-tasks. The two sets should be thematically or logically connected (e.g., Set A: research topic X, Set B: write a report about topic X using the research). |
| **"Satisfied" evidence** | (a) Task definitions exist for at least 2 sets, each with 2+ sub-tasks. (b) The relationship is documented: what from Set A is useful for Set B. (c) Both sets are runnable under both text and protocol modes. |
| **"Superiority" evidence** | (a) 3+ task chains with increasing complexity. (b) Cross-domain transfer: knowledge from a code-analysis task helps a documentation task. (c) Task chains designed to demonstrate all three system features (protocol, state transfer, memory reuse) in synergy. (d) Tasks are realistic (not toy examples). |
| **Scoring weight** | `系统完整性 (20分)` + `实验验证 (15分)` — task design quality |

---

### F2. Verify Reduction in Duplicate Computation, Lower Overhead, Higher Efficiency

| Field | Detail |
|---|---|
| **Exact original text** | `验证结构化通信、非文本状态传递和共享记忆复用在减少重复计算、降低协作开销和提升任务效率方面的实际效果` (lines 18–19) |
| **Engineering meaning** | The 2 task chains must be instrumented to measure: (a) duplicate computation (e.g., same LLM call made twice — should be zero with memory), (b) collaboration overhead (message count, token count, serialization time), (c) task efficiency (wall-clock time, steps to completion). Compare text mode vs protocol mode, and with/without memory reuse. |
| **"Satisfied" evidence** | A results table showing per-task-chain metrics for: text-mode-no-memory, text-mode-with-memory, protocol-mode-no-memory, protocol-mode-with-memory. At least one metric shows improvement in protocol+memory mode. |
| **"Superiority" evidence** | (a) All metrics improve monotonically across modes. (b) Memory reuse alone reduces duplicate computation to near zero. (c) Protocol mode alone reduces token overhead by >50%. (d) Combined mode shows synergistic gain (whole > sum of parts). (e) Ablation analysis: which feature contributes most to which metric. |
| **Scoring weight** | `实验验证 (15分)` — quality and persuasiveness of the verification |

---

## G. Performance Metrics

### G1. Inter-Agent Message Count

| Field | Detail |
|---|---|
| **Exact original text** | `系统需统计并展示 Agent 间消息次数` (line 20) |
| **Engineering meaning** | Count the total number of inter-agent messages per task. A "message" is one structured protocol message or one text utterance. This metric should decrease in protocol mode (structured messages carry more information per message) and with memory reuse (less need to re-ask). |
| **"Satisfied" evidence** | (a) Each task run outputs a `message_count` number. (b) Bar chart comparing text vs protocol message counts. |
| **"Superiority" evidence** | (a) Breakdown by message type (action/query/response/error). (b) Per-agent message count distribution. (c) Correlation analysis: message count vs task complexity. |
| **Scoring weight** | `通信效率 (25分)` — message count reduction |

---

### G2. Text Communication Token/Character Overhead

| Field | Detail |
|---|---|
| **Exact original text** | `文本通信 token 或字符开销` (line 20) |
| **Engineering meaning** | Count the total tokens (tiktoken or similar) or characters transmitted as natural language in inter-agent communication. Protocol mode should drastically reduce this. Use the same tokenizer for fair comparison. |
| **"Satisfied" evidence** | (a) Token counter integrated into message layer. (b) Per-task token total reported for text mode and protocol mode. (c) Clear >30% reduction in protocol mode. |
| **"Superiority" evidence** | (a) Token breakdown: system/prompt tokens vs content tokens. (b) Cumulative token cost over a full task chain. (c) Cost projection: estimated API cost savings at commercial LLM pricing. (d) Token efficiency ratio: tokens per completed sub-task. |
| **Scoring weight** | `通信效率 (25分)` — primary metric |

---

### G3. Non-Text State Transfer Count and Data Scale

| Field | Detail |
|---|---|
| **Exact original text** | `非文本状态传递次数及数据规模` (line 20) |
| **Engineering meaning** | Count how many non-text state transfers occurred per task, and the total bytes/kB of the transferred state vectors. This establishes the footprint of the D feature. |
| **"Satisfied" evidence** | (a) Each task run reports `state_transfer_count` and `state_transfer_bytes`. (b) No state transfers in text mode (or marked as zero). |
| **"Superiority" evidence** | (a) Compression ratio: raw text size vs state vector size for equivalent information. (b) State transfer overhead as % of total communication bytes. (c) Latency breakdown: state serialization, transfer, deserialization times. |
| **Scoring weight** | `状态传递创新 (20分)` — quantifies the innovation |

---

### G4. Single Task Total Time

| Field | Detail |
|---|---|
| **Exact original text** | `单任务总耗时` (line 20) |
| **Engineering meaning** | Wall-clock time from task start to task completion, measured at the system level (not per-agent). Must include all agent processing, communication, and I/O. |
| **"Satisfied" evidence** | (a) Timer wraps the full task execution. (b) Reported in seconds with millisecond precision. (c) Compared across modes. |
| **"Superiority" evidence** | (a) Phase breakdown: % time in LLM calls, % in communication, % in state transfer, % in memory I/O. (b) Flame graph or Gantt chart of agent activity per task. (c) Latency percentiles across multiple runs. (d) Throughput: tasks completed per hour under continuous load. |
| **Scoring weight** | `系统完整性 (20分)` + `实验验证 (15分)` — execution time |

---

### G5. Shared Memory Hit Rate

| Field | Detail |
|---|---|
| **Exact original text** | `共享记忆命中率` (line 21) |
| **Engineering meaning** | Ratio: (number of times a memory retrieval returned a useful, reused result) / (total memory retrieval attempts). A "hit" means the retrieved memory was actually used by the agent (not just returned by the query but ignored). |
| **"Satisfied" evidence** | (a) Metric calculated and reported per task chain. (b) Hit rate > 0% for at least the second task chain (proving reuse). |
| **"Superiority" evidence** | (a) Hit rate increases with task chain length (learning effect). (b) Precision/Recall evaluation of retrieval. (c) Breakdown: keyword hits vs semantic hits. (d) Cold-start: hit rate = 0 for first task, grows to >50% by task 5. (e) Relevance scoring: user/LLM-judged relevance of retrieved memories. |
| **Scoring weight** | `记忆复用效果 (20分)` — primary metric |

---

### G6. Overall Performance Improvement

| Field | Detail |
|---|---|
| **Exact original text** | `整体性能提升情况` (line 21) |
| **Engineering meaning** | A composite metric or dashboard showing the net improvement of the full system (protocol + state transfer + memory) over the baseline (text-only, no memory). Could be a weighted score, a radar chart, or a single "efficiency ratio". |
| **"Satisfied" evidence** | (a) A summary table or chart showing % improvement across all metrics. (b) At least one composite metric (e.g., "task efficiency score = (tokens_saved / baseline_tokens) * 0.4 + (time_saved / baseline_time) * 0.3 + (hit_rate) * 0.3"). |
| **"Superiority" evidence** | (a) Dashboard/HTML report with interactive charts. (b) Cost-benefit analysis: overhead of running the system vs savings achieved. (c) Breakdown of contribution: what % of improvement comes from protocol vs state transfer vs memory. (d) Diminishing returns analysis: how improvement scales with task chain length. |
| **Scoring weight** | `实验验证 (15分)` — holistic summary |

---

## H. System Architecture (5 Modules)

### H1. Multi-Agent Runtime Module

| Field | Detail |
|---|---|
| **Exact original text** | `系统架构中至少应包含多 Agent 运行时` (line 22) |
| **Engineering meaning** | A module that manages agent lifecycle: spawn/register agents, route messages between them, monitor agent health, handle agent failure/restart. This is the "operating system" layer for agents. |
| **"Satisfied" evidence** | (a) Runtime code launches N agent processes/threads based on config. (b) Message routing: Agent A sends to Agent B via runtime, not directly. (c) Shutdown: runtime terminates all agents cleanly. |
| **"Superiority" evidence** | (a) Async/non-blocking message passing. (b) Agent heartbeat and dead-agent detection. (c) Dynamic agent scaling (spawn more Executors under load). (d) Agent sandboxing (separate processes, resource limits). (e) Hot-reload: update agent code without restarting runtime. |
| **Scoring weight** | `系统完整性 (20分)` — runtime sophistication |

---

### H2. Protocol Parsing and Dispatch Module

| Field | Detail |
|---|---|
| **Exact original text** | `协议解析与调度模块` (line 22) |
| **Engineering meaning** | A module that: (a) Parses incoming structured messages (validates schema, deserializes). (b) Dispatches messages to the correct agent based on action type, capability match, or explicit routing. (c) May also handle serialization of outgoing messages. |
| **"Satisfied" evidence** | (a) Separate class/module with `parse(message) -> ParsedMessage` and `dispatch(parsed_message, agents) -> target_agent`. (b) Invalid messages are rejected with error. (c) Unknown action types are routed to a default handler or returned as errors. |
| **"Superiority" evidence** | (a) Plugin-style action handlers (register new action types without changing core). (b) Content-based routing (route based on message fields, not just explicit target). (c) Priority queuing and backpressure. (d) Message tracing: each message gets a trace ID for end-to-end observability. |
| **Scoring weight** | `通信效率 (25分)` — protocol infrastructure quality |

---

### H3. State Exchange Module

| Field | Detail |
|---|---|
| **Exact original text** | `状态交换模块` (line 22) |
| **Engineering meaning** | The transport layer for non-text state vectors. Handles: serialization of vectors/embeddings/tensors, transmission (UDS, shared memory, socket), deserialization on the receiving end. May include compression, chunking for large states. |
| **"Satisfied" evidence** | (a) Separate module with `send_state(agent_id, state_vector)` and `receive_state() -> state_vector`. (b) Works with at least one transport (UDS or shared memory). (c) State vectors arrive bit-identical at receiver. |
| **"Superiority" evidence** | (a) Multiple transport backends with automatic selection (shared memory for same-host, UDS for cross-process, TCP for remote). (b) Zero-copy transfer via shared memory. (c) Streaming for large state tensors. (d) State compression with configurable precision (fp32 → fp16 → int8). (e) Benchmark: transfer latency < 1ms for <1MB state on localhost. |
| **Scoring weight** | `状态传递创新 (20分)` — state exchange engineering |

---

### H4. Shared Memory Storage and Retrieval Module

| Field | Detail |
|---|---|
| **Exact original text** | `共享记忆存储与检索模块` (line 22) |
| **Engineering meaning** | The persistent layer for memories: (a) Storage: SQLite for metadata + FAISS/Chroma for vector embeddings. (b) Retrieval: keyword search (SQL LIKE/FTS), tag filter, semantic search (vector similarity). (c) CRUD operations for memory records. |
| **"Satisfied" evidence** | (a) Separate module with `store(memory_record)`, `search(query, mode)`, `get(memory_id)`. (b) FAISS or similar index persists to disk. (c) Retrieval returns results ordered by relevance. |
| **"Superiority" evidence** | (a) Incremental indexing (FAISS add-on-write, no full rebuild). (b) Multiple index types (Flat, IVF, HNSW) selectable by config. (c) Batch retrieval API. (d) Memory versioning and rollback. (e) Import/export of memory stores. |
| **Scoring weight** | `记忆复用效果 (20分)` — storage engineering |

---

### H5. Evaluation Module

| Field | Detail |
|---|---|
| **Exact original text** | `和评测模块` (line 22) |
| **Engineering meaning** | A module that: (a) Runs tasks under specified modes. (b) Collects all G metrics automatically. (c) Produces comparison reports (tables, charts). (d) Is scriptable for reproducibility. |
| **"Satisfied" evidence** | (a) `run_benchmark.py` (or similar) executes task chains, collects metrics, outputs a report file. (b) Report includes all metrics from G1–G6. (c) Report format is machine-readable (JSON/CSV) and human-readable (Markdown/HTML). |
| **"Superiority" evidence** | (a) CI-style dashboard. (b) Regression detection: flags if a code change degrades metrics. (c) Statistical analysis (confidence intervals, effect sizes). (d) Export to formats suitable for the experimental report (LaTeX tables, matplotlib charts). (e) Multi-run averaging with standard deviation. |
| **Scoring weight** | `实验验证 (15分)` — automation and rigor of evaluation |

---

## I. Stability (10+ Continuous Rounds)

### I1. Execute ≥10 Consecutive Task Rounds Stably

| Field | Detail |
|---|---|
| **Exact original text** | `能够稳定执行不少于 10 轮连续任务` (line 22) |
| **Engineering meaning** | The system must run 10+ tasks back-to-back (sequentially or with some concurrency) without crashing, hanging, memory leaks, or state corruption. Each round = one complete task execution. This tests robustness for the demo/review scenario. |
| **"Satisfied" evidence** | (a) A script runs 10 tasks consecutively. (b) All 10 complete with valid results. (c) No restarts or manual intervention between tasks. (d) Memory usage does not grow unboundedly. |
| **"Superiority" evidence** | (a) Run 50+ tasks without degradation. (b) Concurrent task execution (multiple tasks running simultaneously on the same agents). (c) Graceful degradation under load (not crash, just slower). (d) Memory leak analysis (valgrind or Python memory profiler). (e) Fault injection testing: agent crash mid-task, system recovers and continues. |
| **Scoring weight** | `系统完整性 (20分)` — stability and reliability |

---

## J. Deliverables

### J1. Complete Source Code

| Field | Detail |
|---|---|
| **Exact original text** | `需提交完整源码` (line 23) |
| **Engineering meaning** | All code must be provided, buildable/runnable from source. No pre-compiled binaries. Must include dependency declarations (requirements.txt, pyproject.toml, etc.). |
| **"Satisfied" evidence** | (a) `git clone` + `pip install -r requirements.txt` + `python main.py` runs the system. (b) All modules from H are present in the source tree. (c) No proprietary or missing dependencies. |
| **"Superiority" evidence** | (a) Well-organized package structure. (b) Type annotations throughout. (c) Comprehensive docstrings. (d) Unit tests with >80% coverage. (e) CI configuration file. |
| **Scoring weight** | N/A (pass/fail gate) |

---

### J2. System Design Document

| Field | Detail |
|---|---|
| **Exact original text** | `系统设计文档` (line 23) |
| **Engineering meaning** | A document describing architecture, module interactions, data flow, protocol schema, memory model, and design rationale. Should include diagrams. |
| **"Satisfied" evidence** | A PDF or Markdown document covering all H modules, with at least one architecture diagram. |
| **"Superiority" evidence** | (a) Sequence diagrams for key workflows. (b) ER diagram for memory schema. (c) Decision records for major design choices. (d) Comparison to related work / alternative designs considered. |
| **Scoring weight** | N/A (pass/fail gate) |

---

### J3. Deployment Document

| Field | Detail |
|---|---|
| **Exact original text** | `部署文档` (line 23) |
| **Engineering meaning** | Step-by-step instructions to deploy the system on a fresh machine (openEuler 24.03-LTS-SP3). Include OS dependencies, Python version, pip packages, config files, startup commands. |
| **"Satisfied" evidence** | A document with numbered steps that a reviewer can follow to get the system running. |
| **"Superiority" evidence** | (a) Automated setup script (`setup.sh`). (b) Docker/Podman image. (c) Troubleshooting section for common issues. (d) Verification commands to confirm successful deployment. |
| **Scoring weight** | N/A (pass/fail gate) |

---

### J4. Experimental Report

| Field | Detail |
|---|---|
| **Exact original text** | `实验报告` (line 23) |
| **Engineering meaning** | A formal report presenting: methodology (task design, test conditions), results (all G metrics, tables, charts), analysis (why protocol mode is better, where state transfer helped, how memory reuse compounded), and conclusions. |
| **"Satisfied" evidence** | A PDF or Markdown document with: introduction, methodology, results, analysis, conclusion sections. All G metrics populated with real numbers. |
| **"Superiority" evidence** | (a) LaTeX-formatted with proper academic style. (b) Statistical analysis (not just raw numbers). (c) Ablation studies. (d) Comparison with literature/baselines. (e) Reproducibility appendix with exact commands and seeds. |
| **Scoring weight** | `实验验证 (15分)` — quality of the report |

---

### J5. Demo Video

| Field | Detail |
|---|---|
| **Exact original text** | `演示视频` (line 23) |
| **Engineering meaning** | A screen recording showing: system startup, task execution in both modes, metric output, memory retrieval, and overall workflow. Should be clear enough for reviewers to understand the system without running it. |
| **"Satisfied" evidence** | A video file (mp4) showing a complete walkthrough of all major features. |
| **"Superiority" evidence** | (a) Split-screen showing text mode vs protocol mode side-by-side. (b) Voiceover explaining key concepts. (c) Animated architecture diagram. (d) Real-time metric dashboard during execution. |
| **Scoring weight** | N/A (pass/fail gate) |

---

### J6. On-Site Review Support

| Field | Detail |
|---|---|
| **Exact original text** | `能够支持评审现` (line 23) — likely truncated: `能够支持评审现场复现` (can support on-site live reproduction) |
| **Engineering meaning** | The system must be demonstrable live. Reviewers may ask to run a specific task or change parameters. The deployment must be simple enough for this. |
| **"Satisfied" evidence** | One-command startup. No manual hacks needed to run. Configurable via CLI args or config file. |
| **"Superiority" evidence** | (a) Live CLI with help text. (b) Web dashboard for interactive exploration. (c) Pre-configured scenarios selectable from a menu. |
| **Scoring weight** | `系统完整性 (20分)` — demo readiness |

---

## K. Bonus (System-Level Technologies)

### K1. System Technology Encouragement

| Field | Detail |
|---|---|
| **Exact original text** | `鼓励结合 IPC、共享内存、Socket、向量数据库、WASM/容器沙箱、eBPF 等系统技术提升实现质量` (lines 23–24) |
| **Engineering meaning** | Extra credit for using OS-level primitives: (a) **IPC**: Unix domain sockets, pipes for agent communication. (b) **Shared memory**: mmap/SysV for zero-copy state transfer. (c) **Socket**: TCP/UDS for networked agents. (d) **Vector DB**: FAISS/Milvus/Chroma for memory retrieval. (e) **WASM/container sandbox**: Isolated code execution. (f) **eBPF**: Kernel-level observability or filtering. |
| **"Satisfied" evidence** | At least one of these technologies is meaningfully integrated (not just installed as a dependency but used for its intended system-level purpose). |
| **"Superiority" evidence** | (a) 3+ technologies used in concert. (b) Shared memory shows measurable zero-copy benefit. (c) eBPF used for protocol-level tracing/monitoring. (d) WASM sandbox with capability-based security model. (e) Each technology's contribution is quantified in benchmarks. |
| **Scoring weight** | Bonus — can elevate scores in `通信效率`, `状态传递创新`, `系统完整性` |

---

### K2. CodeAct Mode

| Field | Detail |
|---|---|
| **Exact original text** | `鼓励系统能够支持基于 CodeAct 模式的 Agent 执行机制，允许 LLM 生成 Python 可执行代码，并在轻量沙箱中安全运行，实现低延迟、可隔离的代码执行与结果回传能力` (lines 25–26) |
| **Engineering meaning** | An Agent mode where: (a) The LLM generates Python code (not just text responses). (b) The code is executed in a restricted sandbox (limited imports, timeouts, no network/filesystem access unless allowed). (c) Execution results are captured and fed back to the agent. (d) This enables the agent to perform computations, data transformations, or tool calls via generated code. |
| **"Satisfied" evidence** | (a) At least one agent can operate in CodeAct mode. (b) LLM output is parsed as Python code and executed. (c) Execution happens in a restricted environment (subprocess with restricted imports, or seccomp, or WASM). (d) Execution output is sent back to the agent as structured result. |
| **"Superiority" evidence** | (a) Sandbox with resource limits (memory, CPU time). (b) Pre-approved module whitelist with import guard. (c) Code caching: same code hash → reuse cached result. (d) Multi-turn CodeAct: agent generates code → runs → sees output → generates more code. (e) Benchmark: CodeAct completes tasks 2x faster than tool-calling equivalent. (f) Security audit of sandbox escape vectors. |
| **Scoring weight** | Bonus — `状态传递创新 (20分)` and `系统完整性 (20分)` |

---

## L. Platform (openEuler 24.03-LTS-SP3)

### L1. openEuler Compatibility

| Field | Detail |
|---|---|
| **Exact original text** | `最终交付的代码需在 openEuler 24.03-LTS-SP3 操作系统版本上能够正常编译、运行和测试` (line 41) |
| **Engineering meaning** | The entire system must work on openEuler 24.03-LTS-SP3. This means: (a) Python version available on that OS must be sufficient. (b) All C/Rust extensions must compile on that kernel/libc. (c) No systemd- or Docker- specific assumptions that fail on openEuler. (d) FAISS, SQLite, and any other native libs must have compatible builds. |
| **"Satisfied" evidence** | (a) The system compiles/runs on an openEuler 24.03-LTS-SP3 VM. (b) All tests pass on that platform. (c) No missing dependencies. |
| **"Superiority" evidence** | (a) RPM spec file or OBS build recipe. (b) CI pipeline that tests on openEuler. (c) Uses openEuler-specific optimizations (e.g., EulerOS kernel features). (d) Deployment doc includes openEuler-specific steps verified by a third party. |
| **Scoring weight** | N/A (pass/fail gate — system won't be scored if it doesn't work on the target platform) |

---

## Scoring Summary (from 评分细则, lines 34–39)

| Category | Weight | Linked Requirements |
|---|---|---|
| 通信效率 (Communication Efficiency) | **25 pts** | B1, B2, B3, G1, G2 |
| 状态传递创新 (State Transfer Innovation) | **20 pts** | D1, D2, G3 |
| 记忆复用效果 (Memory Reuse Effectiveness) | **20 pts** | E1, E2, E3, E4, G5 |
| 系统完整性 (System Completeness) | **20 pts** | A1, A2, F1, G4, H1, H2, H3, H4, H5, I1, J6 |
| 实验验证 (Experimental Verification) | **15 pts** | C1, C2, F2, G6 |
| **Total** | **100 pts** | |

### Bonus Scoring (not in point table but implied by document)

| Bonus Area | Linked Requirements |
|---|---|
| System technologies (IPC, shared memory, WASM, eBPF) | K1 |
| CodeAct mode | K2 |
| Deliverable quality (docs, video, design excellence) | J1–J5 |

---

## Requirement Coverage Matrix

```
Req ID  Category  Scoring Dimension            Priority
------  --------  ---------------------------  --------
A1      A         系统完整性                   Required
A2      A         系统完整性                   Required
B1      B         通信效率                     Required  
B2      B         通信效率                     Required
B3      B         通信效率                     Required
C1      C         实验验证                     Required
C2      C         实验验证                     Required
D1      D         状态传递创新                 Required
D2      D         状态传递创新                 Required
E1      E         记忆复用效果                 Required
E2      E         记忆复用效果                 Required
E3      E         记忆复用效果                 Required
E4      E         记忆复用效果                 Required
F1      F         系统完整性 + 实验验证         Required
F2      F         实验验证                     Required
G1      G         通信效率                     Required
G2      G         通信效率                     Required
G3      G         状态传递创新                 Required
G4      G         系统完整性 + 实验验证         Required
G5      G         记忆复用效果                 Required
G6      G         实验验证                     Required
H1      H         系统完整性                   Required
H2      H         通信效率                     Required
H3      H         状态传递创新                 Required
H4      H         记忆复用效果                 Required
H5      H         实验验证                     Required
I1      I         系统完整性                   Required
J1      J         Pass/Fail Gate               Required
J2      J         Pass/Fail Gate               Required
J3      J         Pass/Fail Gate               Required
J4      J         实验验证                     Required
J5      J         Pass/Fail Gate               Required
J6      J         系统完整性                   Required
K1      K         Bonus                        Encouraged
K2      K         Bonus                        Encouraged
L1      L         Pass/Fail Gate               Required
```

---

## Key Design Tensions (identified from requirement analysis)

1. **Text vs Protocol**: The system must run in BOTH modes, meaning the agent logic must be decoupled from the communication layer. This favors a clean abstraction boundary.

2. **State Transfer Novelty vs Practicality**: Embedding/hidden-state transfer is scientifically interesting but must show measurable benefit. Risk: overhead of serializing/deserializing vectors could negate the benefit for small tasks.

3. **Memory Schema Generality vs Task Specificity**: The memory schema (ID, source, time, topic, summary) is generic, but effective reuse requires task-relevant memory content. The challenge is mapping generic memory records to specific task contexts.

4. **10-Round Stability vs Development Velocity**: The stability requirement pushes toward robust error handling and resource management, which can slow feature development.

5. **openEuler Target vs Linux Host Development**: The AGENTS.md says to develop on the current Linux host and validate on openEuler later. This creates a dual-environment challenge for native dependencies (FAISS, shared memory).

6. **Structured Protocol vs "No Raw NL"**: B3 says no raw NL passthrough, but LLMs natively produce NL. The protocol must bridge between structured machine communication and LLM text generation/interpretation — likely requiring a "protocol↔NL adapter" per agent.
