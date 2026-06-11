# StateBus 架构与完整工作流

日期：`2026-06-11`

---

## 一、系统对象定义

StateBus 是一个四 Agent 协作运行时，核心设计是把通信拆成三个面：

| 面 | 传什么 | 存储在哪 | 通信量指标 | 典型内容 |
|----|--------|---------|-----------|---------|
| **控制面** | 谁干什么、下一步 | 协议消息（线上） | `control_bytes`（控制面字节数） | Plan/PlanStep/StepResult/Ack/Hello |
| **状态面** | 实际数据（中间结果） | StatePool（mmap文件） | `handoff_wire_bytes`（线上指针）+ `handoff_payload_bytes`（本地负载） | evidence文本、FEATURE_BUNDLE、embedding |
| **记忆面** | 历史经验 | SQLite + FAISS | — | 每次 task 的摘要、证据引用、replay 线索 |

**关键边界**：控制面只传指针（`StateRefLite{state_id, kind, length}` ≈ 50-80字节/个）。实际数据在 StatePool 的 mmap 文件里，Agent 通过指针去本地读取（零拷贝）。所以 `handoff_wire_bytes`（线上指针字节）≠ `handoff_payload_bytes`（本地负载字节）。

---

## 二、文件架构与职责

```
project/
├── runtime/                    ← 核心运行时
│   ├── orchestrator.py (1573行)  编排引擎：task派发、replay gate、_prepare_step_input_refs
│   ├── executor_runtime.py(1574行) 执行层：ToolRegistry(7工具)、build_feature_bundle(30+字段)
│   ├── contracts.py (676行)      Schema校验、StateContractRegistry(11合同)、InvariantChecker
│   ├── llm.py (683行)            LLM抽象：OpenAICompatibleLLMClient + DeterministicLLMClient
│   ├── reuse_contract.py (91行)  复用合同：4级(reuse_disabled→exact_replay)→3个gate boolean
│   ├── task_profile.py (109行)   任务配置：benchmark_lane/transfer_strategy/mode解析
│   ├── codeact_runner.py (98行)  CodeAct受控代码执行
│   ├── remote_executor.py (85行) UDS远端执行器
│   ├── uds_transport.py (45行)   AF_UNIX消息传输
│   ├── tool_worker.py (29行)     子进程工具CLI
│   └── smoke.py (44行)           烟雾测试入口
│
├── agents/                     ← Agent实现
│   ├── sample_agents.py (1306行) Planner/Retriever/Executor/Summarizer四Agent
│   └── base_agent.py (20行)     BaseAgent ABC
│
├── protocol/                   ← 通信协议层
│   ├── messages.py (998行)      14种消息dataclass + protobuf/json序列化 + CASF DAG结构
│   ├── statebus.proto (152行)   WireEnvelope oneof定义12种消息
│   └── statebus_pb2.py (20行)   protobuf编译stub
│
├── memory/                     ← 共享记忆层
│   └── store.py (914行)         MemoryStore：SQLite schema + FAISS/numpy + 多信号检索融合
│
├── statepool/                  ← 状态池（数据面）
│   └── store.py (405行)         FileBackedStatePool(mmap) + SharedMemoryStatePool + ContentAddressedBlobStore
│
├── eval/                       ← 评测层
│   ├── runner.py (3327行)       run_benchmark/_run_mode_once/6层aggregation/report生成
│   └── metrics.py (90行)        TaskMetrics：50+指标字段
│
├── tasks/                      ← 任务定义
│   ├── sample_tasks.py (394行)  SampleTask dataclass/build_plan/YAML加载/PLAN_SOURCES
│   ├── local_corpus.py (229行)  CorpusDoc检索（semantic+lexical+tag+theme+group scoring）
│   ├── sample_benchmark.yaml    formal_controlled主包（24 task）
│   └── *_benchmark.yaml         专用包（communication/memory/open_validation/...）
│
└── tests/ (95个pytest)
```

---

## 三、完整执行工作流（从 benchmark runner 到 LLM 调用）

### 3.1 进入：eval/runner.py 发起 benchmark

```
run_benchmark(task_set="formal_controlled", repeat=3, modes=("text","protocol"))
  │
  ├─ load_task_set_bundle() → 24个 SampleTask 对象
  │
  └─ for run_index in range(3):          # 跑3轮
       for mode in ("text","protocol"):   # 每轮 text→proto 交替
           │
           ├─ 创建 RunSession(mode)       # 每个 task_group 共享 memory.sqlite3
           ├─ 创建 Orchestrator(agents)   # Planner/Retriever/Executor/Summarizer
           │
           └─ for task in 24个task:       # 串行执行
                │
                ├─ ctx = create_context(task, mode, state_root, memory_db_path, ...)
                │    ctx.runtime_profile → transfer_strategy, reuse_contract
                │    ctx.runtime_gates   → allow_memory_assist/allow_execute_prune/allow_exact_replay
                │
                └─ await orchestrator.run_task(task, ctx)
```

### 3.2 阶段A：规划（runtime/orchestrator.py `_plan_task`）

```
_plan_task(task, ctx)
  │
  ├─ plan_source == "yaml" (受控包默认):
  │    return build_plan(task)           # tasks/sample_tasks.py
  │    → 固定3-step DAG:                 # 不调LLM。planner_requests=0
  │       retrieve(owner=retriever)      # 所有task共用
  │       → execute(owner=executor)      #
  │       → summarize(owner=summarizer)  #
  │
  └─ plan_source == "llm" (仅open_validation):
       return await planner.plan_task(task, ctx)
       → PlannerAgent 调 LLM 生成 Plan → _plan_from_llm_output 解析
       → _expected_plan_contract 严格校验 → 不满足则 raise
```

### 3.3 阶段B：执行（runtime/orchestrator.py `_execute_plan`）

这是核心执行循环。每一步都有 replay gate 检查：

```
_execute_plan(plan, ctx)
  │
  ├─ ctx.emit(plan)                           # 控制面：序列化Plan消息 → control_bytes累加
  │
  ├─ [Replay Gate 1: 精确回放]                # 尝试跳过 retrieve + execute 两层
  │   _resolve_skip_retrieve_execute(plan, ctx)
  │   │
  │   ├─ 条件: ctx.runtime_gates["allow_exact_replay"] == True
  │   ├─ ctx.replay_candidates() → memory_store.replay_candidates()
  │   │   查 SQLite WHERE memory_purpose="replay" AND task_theme=当前theme
  │   │   返回 MemoryHit（含 evidence_state_refs 和 metadata）
  │   │
  │   ├─ 匹配条件:
  │   │   - task_theme 完全相同
  │   │   - feature_route 非 "generic_triage"
  │   │   - reusable_steps 包含 "retrieve" 和 "execute"
  │   │   - 归一化 query 精确匹配
  │   │   - evidence_sha256 非空
  │   │   - route_confidence >= 0.80 && "lexical" in route_provenance
  │   │
  │   ├─ 匹配成功 → 从 MemoryHit.evidence_state_refs 重建 StepResult
  │   │   _prepare_step_input_refs(execute, overrides=retrieve_result)
  │   │   _prepare_step_input_refs(summarize, overrides=both)
  │   │   ctx.pruned_step_ids = ["retrieve","execute"]
  │   │   ctx.metrics.skipped_step_count += 2
  │   │   → 跳过retrieve和execute，直接进入summarize
  │   │
  │   └─ 不匹配 → 继续正常流程
  │
  ├─ Step "retrieve"                            # ── Retriever执行 ──
  │   │
  │   ├─ _prepare_step_input_refs(plan, step, ctx)
  │   │   step_input_contract(agent="retriever") → sources=[] (无上游)
  │   │   → selected_refs = []
  │   │
  │   ├─ ctx.emit(step)                        # 控制面：序列化PlanStep → control_bytes累加
  │   │
  │   ├─ agent = self.agents["retriever"]
  │   ├─ result = await retriever.execute_step(step, ctx)
  │   │   │                                     # ↓ 详见 §四
  │   │   └─ 返回 StepResult(output_state_refs=[evidence_ref, feature_ref, ...])
  │   │
  │   ├─ SchemaInterceptor.validate_result()
  │   ├─ _register_result(result, ctx)
  │   │   ├─ 注册所有 output_state_refs → ctx.state_refs
  │   │   └─ ctx.results["retrieve"] = result
  │   │
  │   └─ if not result.success: break
  │
  ├─ Step "execute"                             # ── Executor执行 ──
  │   │
  │   ├─ [Replay Gate 2: 执行剪枝]              # 尝试只跳过 execute
  │   │   _resolve_skip_execute(plan, ctx)
  │   │   │
  │   │   ├─ 条件: ctx.runtime_gates["allow_execute_prune"] == True
  │   │   │        + ctx.results["retrieve"] 已存在
  │   │   ├─ 查 replay candidates → 比较:
  │   │   │   - feature_route 匹配
  │   │   │   - fresh_evidence_sha256 匹配
  │   │   │   - 归一化 query token overlap >= 85%
  │   │   │   - route_confidence >= 0.70 && lexical in provenance
  │   │   │
  │   │   ├─ 匹配成功 → 合成 execute StepResult
  │   │   │   ctx.pruned_step_ids = ["execute"]
  │   │   │   ctx.metrics.skipped_step_count += 1
  │   │   │   → 跳过execute，直接summarize
  │   │   │
  │   │   └─ 不匹配 → 继续正常流程
  │   │
  │   ├─ _prepare_step_input_refs(plan, step, ctx)
  │   │   step_input_contract(agent="executor", variant=transfer_strategy):
  │   │     source step="retrieve"
  │   │     include_kinds = [DENSE_EVIDENCE, TOOL_ARTIFACT, FEATURE_BUNDLE, ...]
  │   │   → 从 retrieve_result.output_state_refs 中筛选匹配kind的 StateRef
  │   │   → selected_refs = [evidence_ref, feature_ref?, transfer_brief_ref?, ...]
  │   │
  │   ├─ ctx.record_transfer_inputs(selected_refs)  # ← 这里产生 handoff 指标！
  │   │   ├─ handoff_wire_bytes += StateRefLite序列化大小(~50-80/个)   ← 线上通信 ✅
  │   │   └─ handoff_payload_bytes += ref.length (mmap payload大小)    ← 本地读取 ❌
  │   │
  │   ├─ agent = self.agents["executor"]
  │   ├─ result = await executor.execute_step(step, ctx)
  │   │   │                                     # ↓ 详见 §四
  │   │   └─ 返回 StepResult(output_state_refs=[tool_artifact_ref])
  │   │
  │   └─ _register_result → ctx.results["execute"] = result
  │
  └─ Step "summarize"                           # ── Summarizer执行 ──
      │
      ├─ _prepare_step_input_refs(plan, step, ctx)
      │   step_input_contract(agent="summarizer"):
      │     source step="retrieve": include_kinds=[DENSE_EVIDENCE, FEATURE_BUNDLE, EMBEDDING, ...]
      │     source step="execute":  include_kinds=[TOOL_ARTIFACT]
      │   → selected_refs = [evidence_ref, feature_ref?, ..., artifact_ref]
      │
      ├─ agent = self.agents["summarizer"]
      ├─ result = await summarizer.execute_step(step, ctx)
      │   │                                     # ↓ 详见 §四
      │   └─ 返回 StepResult(output_state_refs=[summary_ref],
      │                       memory_commit=assist_commit,
      │                       memory_commits=[replay_commit])
      │
      └─ _register_result → ctx.results["summarize"] = result
           ├─ ctx.commit_memory(assist_commit)  → SQLite + FAISS  (purpose=assist)
           └─ ctx.commit_memory(replay_commit)  → SQLite + FAISS  (purpose=replay)
```

### 3.4 回到 runner：指标收集

```
_run_mode_once 中每个 task 完成后:
  ctx.metrics.to_dict() → {
    control_bytes, state_bytes, llm_total_tokens, task_ms,
    handoff_wire_bytes, handoff_payload_bytes,
    handoff_textual_bytes, handoff_nontext_bytes,
    memory_hit_rate, skipped_step_count, reuse_gain,
    planner_total_tokens, summarizer_total_tokens,
    ...
  }
  
所有 task 跑完后:
  _aggregate_mode_runs → 平均/求和 → benchmark_results.json
  _write_markdown_report → benchmark_report.md
```

---

## 四、四个 Agent 在两种模式下的详细行为

### 4.0 总览

| Agent | 调 LLM? | 两种模式差异 | 差异层面 | token 影响 |
|-------|:---:|------|---------|:---:|
| Planner | 受控包：否 | 受控包：无差异（plan 来自 YAML） | — | 0 |
| Retriever | 否 | 完全相同（产出相同的 StateRef） | 仅握手格式不同 | 0 |
| Executor | 否 | text_brief 下解析文本；state_ref 下直接读字段 | 仅握手格式不同 | 0 |
| Summarizer | **是** | text: 原材料（原始 evidence 全文）；proto: 加工品（结构化 handoff） | prompt 内容+格式都不同 | **全部差异来源** |

### 4.1 Planner

```
职责: 把用户 task 分解为 step 序列

受控包 (plan_source="yaml"):
  build_plan() → 固定3-step DAG → 不调 LLM
  planner_requests = 0, planner_total_tokens = 0

开放包 (plan_source="llm", 仅 open_validation):
  PlannerAgent.plan_task() → _planner_messages() → LLM → _plan_from_llm_output()
  → _expected_plan_contract() 校验 (必须3-step)
```

### 4.2 Retriever

```
职责: 检索 corpus → 查共享记忆 → 构建特征 → 写入 StatePool → 返回 StateRef 指针
不调 LLM。两种模式完全相同。

执行流程:
  1. retrieve_corpus_docs(query, tags, corpus_doc_ids)  → 本地 corpus 语义+词法检索
  2. ctx.search_memory(purpose="assist")                 → 查共享记忆
  3. build_feature_bundle(query, evidence, tags, ...)    → route/confidence/signals
  4. 根据 transfer_strategy 决定握手格式:
     
     state_ref (大部分task):                     text_brief (仅 transfer_lane text模式):
     ├─ put_feature_state() → FEATURE_BUNDLE     ├─ _build_transfer_brief() → Key-Value文本
     ├─ put_ranked_evidence() → RANKED_EVIDENCE  ├─ put_text_state() → TOOL_ARTIFACT
     ├─ put_tool_candidate() → TOOL_CANDIDATE    │
     ├─ put_replay_eligibility() → REPLAY_ELIG   │   产出: 1个 StateRef, ~1790字节
     ├─ put_embedding() → EMBEDDING              │
     │                                            │
     产出: 5个 StateRef, ~3600字节               │

    ⚠️ 两者都走 StatePool → StateRef指针 → mmap     两者都走 StatePool → StateRef指针 → mmap
    通信路径完全相同！                                通信路径完全相同！
    只差在 payload 格式(msgpack vs Key-Value文本)     只差在 payload 格式
```

### 4.3 Executor

```
职责: 读 StateRef 指针 → mmap 取 payload → 选 tool → subprocess 执行
不调 LLM。两种模式下的 tool 选择结果相同（expectation_match=1.00）。

text_brief 握手 (transfer_lane text模式):
  收到: 1个 TOOL_ARTIFACT StateRef
  读 payload: "Route: cache_invalidation\nTool: fix_invalidation_hook\n..."
  → 解析 Key-Value 文本 → 提取 route/tool/confidence
  → select_tool_name(feature_bundle) → tool lookup → subprocess 执行
  
state_ref 握手 (其余所有):
  收到: 5个 StateRef (FEATURE_BUNDLE + TOOL_CANDIDATE_SET + ...)
  读 FEATURE_BUNDLE payload: msgpack bytes → dict{route:"cache_invalidation",tool:"fix_cache",...}
  → 直接读结构化字段 → select_tool_name(feature_bundle) → tool lookup → subprocess 执行

产出: TOOL_ARTIFACT StateRef (actions 文本)
```

### 4.4 Summarizer —— 唯一调 LLM 的 Agent，text/proto 差异根源

```
text 模式                          protocol 模式
─────────                          ─────────────

收到 evidence (来自 Retriever):
  原始 corpus 文档全文              _build_protocol_summary_handoff()
  (几千字节自然语言)                 生成的紧凑描述:
                                   "Query: inventory stale...
                                    Route: cache_invalidation
                                    Route confidence: 0.92
                                    Matched signals: invalidation, batch-sync
                                    Evidence preview: Fresh evidence should..."

收到 prompt:
  system: "你是纯文本协作环境中       system: (无额外包装，紧凑模式)
           的 Summarizer。你收到了     
           之前 Agent 的自然语言交接..."
  user: 自然语言格式                  user: tagged_json(
           "Summarizer handoff for           "statebus-summary-input",
           a text-only workflow.             {"h": hint, "e": evidence,
           Task ID: sample-cache-001          "a": actions, "t": tags,
           Task theme: ...                    "r": reusable_steps}
           Evidence note: ..."               )

token 消耗: ≈ 500+                    token 消耗: ≈ 200+

导致差异的根因:
  Retriever的推理(route)→文本化→Summarizer再理解    Retriever的推理→结构化→Summarizer直接读
  = "内部状态→文本→内部状态" 反复转换                = 消灭了转换损耗

这不是"给 Summarizer 更少信息"——是给"更浓缩的信息"。
上游已经提取好的 route/confidence/signals，不需要 Summarizer 重新推理。
expectation_match=1.00 证明输出一致性。
```

---

## 五、StateRef 生命周期与指标采集点

```
Retriever                             Executor
────────                              ────────
ctx.put_feature_state()
  ├─ msgpack 序列化 feature_bundle
  ├─ 写入 StatePool (mmap文件)  → data/task-001-features.bin
  └─ 返回 StateRef {
       state_id: "task-001-features"
       kind: "FEATURE_BUNDLE"
       storage: "MMAP_FILE"
       handle: "/path/to/data/task-001-features.bin"
       length: 1200
       checksum: "abc123..."
       metadata: {route:"cache_invalidation", ...}
     }
         │
         │ 放入 StepResult.output_state_refs = [evidence_ref, feature_ref, ...]
         │
         ├── 控制面序列化 (protobuf WireEnvelope) ──→
         │   StateRefLite {                          _prepare_step_input_refs
         │     state_id: "task-001-features"          │
         │     kind: "FEATURE_BUNDLE"                 ├─ 按 contract 筛选 kind
         │     length: 1200                           │   executor contract:
         │   }                                        │     include_kinds=[DENSE_EVIDENCE,
         │   ≈ 60-80 字节 (不含payload!)              │       TOOL_ARTIFACT, FEATURE_BUNDLE, ...]
         │                                            │
         │                                            ├─ handoff_wire_bytes    ← ✅ 线上通信！
         │   ① 序列化 StateRefLite → protocol_bytes   │   += 每个指针 60-80 字节
         │   ② 嵌入 StepResult → protocol_bytes       │
         │   ③ Session.record_message →               ├─ handoff_payload_bytes ← ❌ 本地读取！
         │      metrics.control_bytes +=               │   += ref.length (mmap文件大小)
         │                                            │
         │   注意: payload (1200字节) 不进入控制面    │
         │                                            │
         │                                            ├─ ctx.resolve_ref(state_id)
         │                                            │   → statepool.get_bytes(ref)
         │                                            │   → mmap 零拷贝读取 1200字节
         │                                            │   → msgpack 反序列化
         │                                            │   → 得到 route/tool/confidence
         │                                            │
         │                                            └─ 选 tool → subprocess 执行
```

**关键：控制面只传指针（~60字节），payload 在本地 mmap 文件里。`handoff_wire_bytes` 才是通信量，`handoff_payload_bytes` 是本地 StatePool 存储量。**

---

## 六、记忆流：写入与检索

### 6.1 写入（Summarizer → SQLite + FAISS）

```
Summarizer 生成两份 MemoryCommit:
  ├─ assist_commit (purpose="assist", reusable_steps=["retrieve"])
  │   嵌入文本: query + route + summary
  │   evidence_state_refs: [evidence_ref, feature_ref, ..., summary_ref]
  │
  └─ replay_commit (purpose="replay", reusable_steps=["retrieve","execute"])
      嵌入文本: query + route + summary + full actions
      evidence_state_refs: [*assist_refs, artifact_ref]

ctx.commit_memory(commit) → memory_store.commit_memory():
  ├─ INSERT INTO memories (...) → SQLite 行
  ├─ embed(embedding_text) → FAISS 向量索引
  └─ faiss_outbox → 异步索引同步
```

### 6.2 查询（Retriever/Ochestrator → 检索记忆）

```
assist 查询（在 RetrieverAgent 中）:
  ctx.search_memory(task_theme, query_text, tags, 
                    required_metadata={"memory_purpose":"assist"})
  → memory_store.search(MemoryQuery)
  → FAISS 向量搜索 + SQLite metadata/tag 过滤
  → 多信号融合排序:
      combined = semantic × tier(同session=1.5) 
               + 0.25×BM25 + 0.20×tag + 0.10×recency
  → 返回 MemoryHit[]

replay 查询（在 _resolve_skip_* 中）:
  ctx.replay_candidates(task_theme, required_metadata={"memory_purpose":"replay"})
  → memory_store.replay_candidates()
  → SQLite 精确查询 WHERE task_theme=? AND purpose=replay
  → 返回 MemoryHit[] (含 evidence_state_refs)
```

---

## 七、受控包 vs 开放包的运行时差异

```
                 formal_controlled               open_validation
                 ────────────────                ───────────────
Plan 来源:        build_plan() (固定3-step)       PlannerAgent.plan_task() (LLM生成)
Planner LLM调用:  0次                             3次 (仅 plan_source="llm" 的task)
Per-task 变量:    通信格式 + prompt + 握手         通信格式 + prompt + plan变异性
宣称范围:         正式 headline                    support-only (答辩佐证)
设计意图:         公平对比：控制Plan变量            证明Planner能工作、系统能处理开放场景
```

---

## 八、关键决策点总表

| 决策点 | 位置 | 条件 | 效果 |
|--------|------|------|------|
| Plan 来源 | orchestrator L820 | `plan_source="yaml"` → `build_plan()` | 固定3-step，不调LLM |
| | | `plan_source="llm"` → `PlannerAgent.plan_task()` | LLM 生成，受 contract 校验 |
| 跳过 retrieve+execute | orchestrator L716 | `allow_exact_replay` + route/evidence hash/query 全匹配 | 两层跳过，`skipped_step_count += 2` |
| 只跳过 execute | orchestrator L774 | `allow_execute_prune` + retrieve 已完成 + evidence hash/route 匹配 | 跳过 execute，`skipped_step_count += 1` |
| 握手策略 (text) | task_profile L101 | `mode_split` + mode="text" → `text_brief` | Retriever→Executor 传 Key-Value 文本 |
| 握手策略 (proto) | task_profile L102 | `mode_split` + mode="protocol" → `state_ref` | Retriever→Executor 传结构化 msgpack |
| Summarizer 输入 | sample_agents L635 | mode="text" → raw evidence 全文 | Summarizer 看到原材料 |
| | sample_agents L636 | mode="protocol" → `_build_protocol_summary_handoff` | Summarizer 看到结构化加工品 |
