# StateBus 严格审计报告

日期：2026-06-14

审计范围：`/home/qcrs/statebus/project`，严格以 `docs/reference/题目.md` 为最高约束

---

## 读过的目录与文件

### 目录
`docs/`, `docs/constraints/`, `docs/planning/`, `docs/review/`, `docs/reports/`, `docs/reference/`, `agents/`, `runtime/`, `eval/`, `tasks/`, `tests/`, `memory/`, `statepool/`, `protocol/`

### 完整读取的文件 (40+)

**主约束**: `README.md`, `current_host_and_migration.md`, `current_feature_scope.md`, `implementation_plan.md`, `题目.md`

**Review/Report**: `statebus_v3_deep_review_memo_20260613.md`, `statebus_contest_aligned_review_20260614.md`, `MASTER_PRESENTATION_GUIDE.md`, `task_design_and_mode_comparison.md`

**Benchmark 合同**: 11 个 v3 YAML (核心6个全读)

**实现文件**: `runner.py` (5882行/gate函数精读), `task_profile.py` (208行), `orchestrator.py` (2219行), `executor_runtime.py` (1794行), `langgraph_adapter.py` (435行), `sample_agents.py` (1713行), `test_smoke.py` (4455行/精读gate/sensitivity/replay测试)

**Git**: `branch`, `status --short`, `log --oneline -10`, `ls-files docs/review/`

---

## A. 仓库状态与审计前提

### A1. 当前 branch 和 dirty tree 对 formal claim 的影响

**Branch**: `feat/benchmark-v2-contract-refactor`（不是 `main`）

**Git log 最近 5 条**:
```
855216f add
fd9437e checkpoint benchmark v1 packs and v2 planning baseline
7629092 Align langgraph and benchmark defaults with runtime behavior
43b8a12 Refactor benchmark packs and expand contest task families
c0cd1cd Harden state transfer trajectory and fairness benchmarks
```

**Dirty**: `git status --short` 只有 2 个 untracked 文件（均为 `docs/review/` 下的新 prompt/audit 文档），0 个 modified 跟踪文件。

**影响**: branch 名本身就是 `feat/*`（特征分支），提交历史显示持续在进行 benchmark contract refactor，当前树是**活动中的 v3 收口重构树**，不是稳定交付面。任何 formal claim 都必须标注 branch 不是 main，因为切换回 main 时可能不存在这些 gate/guard/contract 机制。

### A2. `docs/review/` 当前版本控制状态

`git ls-files docs/review/` 显示只有 2 个文件被跟踪：
- `statebus_contest_aligned_review_20260614.md`
- `statebus_v3_deep_review_memo_20260613.md`

另外 2 个文件是 untracked：
- `statebus_long_context_handoff_prompt_20260614.md`
- `statebus_strict_audit_and_repair_plan_20260614.md`

**两个跟踪的 review 的结论是否仍成立：**

`statebus_v3_deep_review_memo_20260613.md`（6月13日）的核心结论：
- "surface 已切干净，但机制真实性仍在审计中" → **仍成立**，当前 branch 上的 gate/guard 机制就是针对此的
- "不能把 `contest_dual_mode_controlled_v3` 直接读成正式赛题结论" → **部分已被改写**，当前 branch 上的 `formal_stability_gate` + `object_parity_gate` + `_contest_formal_coverage_gate` 提供了正式 release 机制

`statebus_contest_aligned_review_20260614.md`（6月14日）的核心结论：
- "text baseline 定义仍不够干净" → **仍成立**，code 证实 `text_strict_pure_lane` 仍共用 ToolRegistry
- "memory fairness pack 不能证明 replay 效率" → **仍成立**，但当前 branch 已把 `memory_dual_mode_fairness_v3` 固定为 `single_variable: false`，并把 replay 证据门限收口到 protocol-only replay packs
- "文档 drift 仍需修复" → **部分已修复**，`tasks/README.md` 和 `task_design_and_mode_comparison.md` 已对齐

### A3. 当前 repo 是否达到"稳定主线"

**没有。** 它是活动中的 v3 收口树。证据：
1. Branch 不是 `main`
2. AGENTS.md 写 `main` 是 active implementation mainline，`feat/realism-protocol-hardening` 是 historical topic branch
3. 当前 branch 上有 gate 机制（`formal_stability_gate`, `object_parity_gate`, `_contest_formal_coverage_gate`）但这些 gate 在 `main` 上是否存在未知
4. `docs/review/` 中的 review docs 明确标注 stopline 和 withheld

---

## B. 赛题要求逐项映射

### B4. 按 `题目.md` 原文，已满足的要求

| 赛题原要求 | 代码证据 | 状态 |
|---|---|---|
| 不少于 3 个 Agent，覆盖规划/检索/执行/总结 | `agents/sample_agents.py:1204-1267` 注册四个 Agent | 已满足 |
| 结构化通信替代自然语言长文本 | `protocol/messages.py` + `executor_runtime.py` control_bytes 指标 | 已满足 |
| 同时支持纯文本 + 结构化两种模式 | `text`/`protocol` 双 mode，`task_profile.py` 定义 | 已满足 |
| 非文本中间状态传递 | `StateRef` + `DENSE_EVIDENCE` + `EXECUTOR_DECISION_PACKET` + mmap | 已满足 |
| 共享记忆模块 | SQLite + FAISS + `MemoryProxy` | 已满足 |
| 记忆含 ID、来源Agent、时间、主题、摘要 | `sample_agents.py` memory commit 含所有必填字段 | 已满足 |
| 支持关键词/标签/语义相似度检索 | SQLite FTS + FAISS 向量检索 | 已满足 |
| 至少 2 组关联连续任务 | contest_dual_mode_controlled_v3 含 5 chain × 4 复杂度 × 2 mode = 40 task | 已满足 |
| 统计消息次数/token/状态规模/耗时/命中率 | `eval/runner.py` 完整指标采集 | 已满足 |
| 系统架构含 runtime/协议/状态交换/记忆/评测 | 六模块 `runtime/` `protocol/` `statepool/` `memory/` `eval/` `agents/` | 已满足 |
| 稳定执行不少于 10 轮 | `repeat=10` 在 `contest_dual_mode_controlled_v3` 上通过 | 已满足 |

### B5. 对象存在但证据不够支持的

| 要求 | 存在什么 | 缺什么 |
|---|---|---|
| 非文本状态传递的"接收及后续使用方式" | `EXECUTOR_DECISION_PACKET` 被传递到 executor | consumer sensitivity 未验证"缺了它 correctness 会下降" |
| 记忆复用的"减少重复计算" | `memory_policy_controlled_v3` replay gate 机制存在 | formal replay evidence 未跑正式 API repeat=10 |
| 通信开销"相比纯文本协作"的节省 | `contest_dual_mode_controlled_v3` 数据 | text 侧是 `text_strict_pure_lane` 不是传统纯文本 baseline |

### B6. 仍不能正式宣称的

1. "StateBus 通信全面优于传统纯文本" — text baseline 不是外部传统系统
2. "非文本状态传递带来效率收益" — consumer sensitivity 未验证
3. "共享记忆复用已证实减少重复工作" — replay evidence gate 未通过 API repeat=10
4. "LangGraph 是创新点" — 固定四节点编排 substrate

### B7. "至少 3 个 Agent" 是否真实成立

代码上确实有 4 个独立 Agent 类（`PlannerAgent:243`, `RetrieverAgent:274`, `ExecutorAgent:834`, `SummarizerAgent:915`），各自有独立的 `execute_step` 方法。

但需要警惕评委的质疑：
- 四个 Agent 在 `langgraph_adapter.py` 中被编排为固定的 `planner -> retriever -> executor -> summarizer` 顺序执行
- 没有动态 Agent 发现、协商、并行、竞争
- 这更接近"固定拓扑工作流"而非"多 Agent 自主协作"

### B8. 评委会不会质疑成 workflow 而不是多 Agent 协作

**会，当前系统拓扑确实是固定的。** 证据：
- `langgraph_adapter.py:18`: `STATEBUS_GRAPH_NODES = ("planner", "retriever", "executor", "summarizer")`
- 四个 node 函数都是 pull state -> invoke orchestrator -> push snapshot
- 没有动态 agent selection、negotiation、capability discovery 在 run-time
- `CapabilityTable` 和 `AgentRegistry` 存在（`protocol/`），但在当前主链路中没有被用来做运行时的 agent 动态路由

答辩时应策略：承认固定拓扑是当前工程选择，但要强调 `CapabilityTable` 和 `AgentRegistry` 的存在说明架构支持动态 agent 路由（这是"已设计，当前未全部展开"）。

---

## C. dual-mode benchmark 到底在比什么

### C9. `contest_dual_mode_controlled_v3` 到底在比什么变量

YAML 声明 `variable_axes: [mode, handoff_object]`。实际执行中每个 task pair 的对比是：
- `text` + `transfer_strategy=text_strict_pure_lane`
- `protocol` + `transfer_strategy=state_packet_minimal`

这是在比 **两组复合配置**，不是单一变量。

### C10. 是否真的"只改通信方式"

**不是。** 实际上改了：`mode`（text vs protocol，影响 planner/summarizer LLM prompt 格式、retriever state 产出、executor 输入）AND `handoff_object`（strict pure text vs minimal typed state packet）。

### C11. 如果不只是一个变量，dual-mode headline 应该怎么收口

这个问题在当前 branch 上已经修复。`contest_dual_mode_controlled_v3_benchmark.yaml` 现在明确标记为复合变量面：
```
single_variable: false
variable_description: >
  This pack compares two composite configurations:
  (text + text_strict_pure_lane) vs (protocol + state_packet_minimal).
  Mode and handoff object change together; attribution to a single variable
  is not claimed.
```

Headline 应表述为："结构化通信 + typed state 的复合配置在 controlled tasks 下降低控制面字节 15.2% 和端到端耗时 5.4%（relative to strict pure-text carrier within StateBus runtime）"

### C12. 为什么还必须受 repeat=10 和 coverage gate 约束

`eval/runner.py:1455-1485` `_contest_formal_coverage_gate`:
```python
return {
    "passed": (
        len(families) >= 5
        and set(buckets) == {"simple", "distractor", "ambiguous", "reusable"}
        and matched_pair_count == 20
        and repeat >= 10
    ),
}
```
当前 contest_dual_mode_controlled_v3 有 5 families × 4 complexity buckets = 20 matched pairs，且 repeat=10 已通过。`_contest_formal_coverage_gate.passed` = True。

但这里有一个 subtlety：当前虽已改成 `single_variable: false`，coverage gate 通过也不能被重新讲成单变量归因；否则仍会向评审传递错误信号。

### C13. Runner 里的 gate 是否足够严格

逐个分析：

**`_object_parity_gate`** (`runner.py:1265-1328`):
- 检查 protocol executor input kinds = `("DENSE_EVIDENCE", "EXECUTOR_DECISION_PACKET")` ✓
- 检查 text hidden field leak = 0 ✓
- 检查 text typed visibility = 0 ✓
- 检查 text memory restore compatible ✓
- **严格性评估：足够**。但没有检查 text executor 内部是否仍用 `registry.retrieve_candidates()`（helper path 污染）

**`_contest_formal_coverage_gate`** (`runner.py:1455-1485`):
- 检查 families >= 5, 4 complexity buckets, matched_pair_count == 20, repeat >= 10 ✓
- **严格性评估：足够**。但 `repeat >= 10` 只检查参数，不要求必须是 API（可用 deterministic）

**`formal_stability_gate`** (inline `runner.py:3134-3178`):
- 检查 run_count >= 10, failure_count == 0, message_count_mean > 0, control_bytes_mean > 0, task_ms_mean > 0, expectation_match_rate, state_transfer_count_mean > 0 for protocol
- **严格性评估：足够**。但没有区分 deterministic vs API repeat

**`_memory_replay_evidence_gate`** (`runner.py:1331-1364`):
- 只对 `memory_reuse_v3` 和 `memory_policy_controlled_v3` 生效
- 检查 expected_reuse_mode (skip_execute/skip_retrieve_execute) 是否实际命中
- **严格性评估：足够**，且有测试 `test_memory_replay_evidence_gate_fails_on_expected_replay_mismatch`

**整体评价：gate 机制在当前 branch 上是严格的，`single_variable` 声明问题已修。当前剩余重点在 (1) gate 只挡外显污染 (2) gate 不检查 helper path 借用。**

---

## D. text baseline 到底干不干净

### D14. `text_strict_pure_lane` 的真实语义

代码定位：`runtime/task_profile.py:16` 定义为 handoff profile，`runtime/task_profile.py:28` 定义为 transfer strategy。

**真实语义**：StateBus runtime 内的 **strict natural-language carrier**。它：
- executor 不给任何 typed state ref（no DENSE_EVIDENCE, no EXECUTOR_DECISION_PACKET etc）
- executor 只接收 inline_handoff_text（纯文本）
- retriever 不给 executor 传递任何 typed state ref
- memory assist 被禁用 (`hits=[]` for text_strict_pure_lane at `sample_agents.py:297`)
- planner/summarizer 使用 text-mode natural language prompt

但 executor 仍使用 `_feature_bundle_from_strict_pure_text_handoff()` (`executor_runtime.py:1657`) 对 handoff text 做 lexical matching 并查询同一个 `ToolRegistry.retrieve_candidates()`。

### D15. `text_whole_lane` 的真实语义

**真实语义**：StateBus runtime 内的 **natural-language carrier with full internal pipeline**。它比 `text_strict_pure_lane` 更"脏"：
- executor 仍不需要 DENSE_EVIDENCE（通过 guard 豁免）
- 但 executor 调用 `_feature_bundle_from_natural_handoff()` 走完整的 `build_feature_bundle()` pipeline
- retriever 生成 `REPLAY_ELIGIBILITY_BUNDLE`（但标记 `proof_only=True`）
- memory assist 启用
- executor 产出 natural language handoff text
- summarizer 收到的是自然语言 executor 输出

### D16. 三个文本对象在各文件中的定义一致性

| 文件 | `text_strict_pure_lane` | `text_whole_lane` | `external_pure_text` |
|---|---|---|---|
| `runtime/task_profile.py` | handoff profile 和 transfer strategy 均定义 | 同 | 未定义 |
| `contest_*_v3.yaml` | formal headline 的 text baseline | 未出现在 contest pack | 未出现在 contest pack |
| `memory_dual_mode_fairness_v3.yaml` | 不出现 | 作为 fairness surface 的 text baseline | 不出现 |
| `README.md` | 定义为 formal headline 的 text 侧 | 定义为 fairness surface 的 text 侧 | 未直接提到 |
| `MASTER_PRESENTATION_GUIDE.md` | 提到，但 wording 需核查 | 提到，作为 fairness surface | 未直接提到 |
| `task_design_and_mode_comparison.md` | 定义为 formal headline baseline | 定义为 fairness/parity surface | 提到 external_text_baseline_audit 是 audit-only |

**基本一致，但需要在所有文档中添加统一的一句话：** "以上 text carrier 均在 StateBus runtime 内运行，不是独立的外部传统纯文本多 Agent 系统。"

### D17. `text_strict_pure_lane` 是否真的是外部传统纯文本多 Agent baseline

**不是。** 证据：

1. executor 调用 `registry.retrieve_candidates()` (`executor_runtime.py:1657`) — 同一 ToolRegistry
2. retriever 在内部运行 `RetrieverAgent.execute_step()` — 同一 agent pipeline
3. tool 选择走同一套 lexical scoring + corpus hints 路径
4. planner/summarizer 虽然 prompt 不同，但仍跑在同一个 `Orchestrator` 框架内

### D18. `text_whole_lane` 是否仍然借用了 StateBus 的方法栈

**是。** 程度比 `text_strict_pure_lane` 更严重：

1. executor 调用完整的 `build_feature_bundle()` 管道
2. retriever 生成 `REPLAY_ELIGIBILITY_BUNDLE`
3. memory assist 启用
4. 与 protocol 侧的差异只是"object 是否作为 typed state ref 出现在 executor input kind 列表里"

### D19. text 侧是否复用：feature extraction / route inference / tool candidate / memory assist / tool registry / playbook execution

| 复用项 | `text_strict_pure_lane` | `text_whole_lane` |
|---|---|---|
| feature extraction | partial (only lexical from handoff text) | yes (full `build_feature_bundle()`) |
| route inference | yes (via `registry.retrieve_candidates()`) | yes |
| tool candidate construction | yes (via registry) | yes |
| memory assist | **no** (hits=[]) | **yes** |
| tool registry | yes (same `ToolRegistry.retrieve_candidates()`) | yes |
| playbook execution | yes (same `execute_playbook_step()`) | yes |

### D20. 它更像什么

**StateBus runtime 内部 text carrier baseline。**

不是外部纯文本 baseline。外部纯文本 baseline 必须：
- 不通过 retriever agent 做 feature extraction
- 不通过同一个 tool registry 做 route/tool matching
- 不让 executor 借用 feature bundle 的任何结构化语义
- 不走 StateBus 的 `Orchestrator.compile_plan` / `invoke_plan_step` 调度

### D21. `external_text_baseline_audit_v3` 是否真的 external

根据文档口径（`task_design_and_mode_comparison.md` + `tasks/README.md`），该 pack 是 "audit-only"，"不并入 formal headline"。**需要代码验证它是否真的不走 StateBus runtime machinery。** 如果它仍跑在同一个 `run_benchmark()` 函数中，那它和 text_strict_pure_lane 的外部性差别可能很小。

### D22. 它为什么不能并入 formal headline

因为它是 "audit-only" 定位，且如果代码上仍共用 StateBus runtime 路径，就不是真正独立的 external baseline。评审会质疑你为什么把"另一个 StateBus runtime 内的 lane"称为 external。

### D23. 当前 text baseline 是否被做强了

**没有被做强。** `text_strict_pure_lane` 是当前最"弱"的 text lane：
- 不给 executor 任何 typed state
- 没有 DENSE_EVIDENCE
- 没有 memory assist
- 用最少的 feature extraction（只做 lexical match 不调用 `build_feature_bundle()`）

问题不是它"被做强"，而是它**仍然不是外部系统**——它只是 StateBus runtime 内信息最少的一条 lane。

### D24. `whole_lane_text_guard` 和 `inline_text_boundary_guard` 能防住什么，防不住什么

**`_whole_lane_text_guard_payload`** (`runner.py:523-575`):

能防住的：
- executor 收到 forbidden ref kinds（FEATURE_BUNDLE, EXECUTOR_DECISION_PACKET, CHANNEL_SNAPSHOT 等）→ `forbidden_ref_kinds` 检查
- handoff text 中包含 hidden field markers（"Suggested route:", "BENCHMARK_NOTE " 等）→ `hidden_field_leak` 检查
- summarizer 收到 typed ref → `summarizer_typed_visibility` 检查
- 缺少 retrieve/execute handoff text → `missing_*_handoff_text` 检查

防不住的：
- executor 内部 helper path `registry.retrieve_candidates()` — guard 只检查 input ref kinds，不检查 executor 内部逻辑
- retriever 内部仍跑 shadow pipeline — guard 不跟踪 retriever 内部状态

**`_inline_text_boundary_guard_payload`** (`runner.py:578-620`):

能防住的：
- executor 拿到任何 input ref（typed 或 not）→ `executor_input_refs_present` 检查
- hidden field leak in inline text
- summarizer typed visibility

防不住的：和 whole_lane guard 相同——不检查内部 helper path。

### D25. guard 是否只防"外显输入污染"但防不住内部 helper path

**是的。** 两个 guard 都只检查 `ctx.step_input_refs()` 返回的 StateRef kinds，不检查 executor/retriever 内部的 `build_feature_bundle()` / `registry.retrieve_candidates()` 调用链。这是 guard 的根本局限。

---

## E. typed-state 机制到底证明了什么

### D26. `typed_state_mechanism_v3` 现在到底证明了什么

证明了：在 protocol-only 模式下，`DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` 从 retriever 生产 → 进入 StatePool → 被 executor 作为输入引用 → executor 读取这些 object 的内容。

Benchmark report 证据：
- `typed_executor_minimal_expected_consumption_rate = 1.00`
- `executor_expected_kind_match_rate = 1.00`
- `executor_unexpected_kind_seen_rate = 0.00`

### D27. 是否只证明 DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET 被真实生产、传递、消费

**是的，只证明了这个。** 这是 mechanism proof（"机制存在并可运行"），不是 efficiency proof，也不是 utility proof。

### D28. 能不能证明 typed-state 带来了效率收益

**不能。** 要证明效率，需要：
- 比较 protocol 下有 typed state vs protocol 下只用 text（natural_handoff_text）
- 证明 typed state 下 LLM tokens 降低 / task time 降低 / route accuracy 提升
- 当前 `typed_state_mechanism_v3` pack 回答的是机制真实性问题，不是效率问题

### D29. `typed_state_authenticity_v3` 和 `typed_state_mechanism_v3` 的关系

`typed_state_authenticity_v3` = legacy compatibility surface（`task_design_and_mode_comparison.md` 明确标注）
`typed_state_mechanism_v3` = 当前正式机制 claim 入口

两者测试的对象略有不同：
- `authenticity_v3` 可能涉及更老的 handoff 对象（`protocol_natural_handoff_text vs state_ref` 或 `feature_only vs state_ref`）
- `mechanism_v3` 是当前的 `natural_handoff_text vs state_packet_minimal`

### D30. 为什么还保留 `typed_state_authenticity_v3`

保留它是为了 backward compatibility —— 历史上可能有些报告/测试引用了 `typed_state_authenticity_v3` 的名字。但它的正式机制 claim 已被 `typed_state_mechanism_v3` 取代。

### D31. legacy compatibility 还是仍在承担 active formal claim

文档写明是 "legacy-compat"，"正式机制 claim 优先读 `typed_state_mechanism_v3`"。**不是 active formal claim**，但应该：
- 在 runner 的 report 中如果引用 `typed_state_authenticity_v3` 的名字，自动转发到 `typed_state_mechanism_v3`
- 或者在文档中更明确地标 deprecated/archived

### D32. `state_packet_minimal` 在 `executor_runtime.py` 是否真的被 executor 消费

**是。** 代码路径：`executor_runtime.py:930-940`：
```python
elif transfer_strategy == "state_packet_minimal":
    feature_bundle = _feature_bundle_from_executor_decision_packet(
        registry=registry,
        evidence_text=evidence_text,
        decision_packet_ref=decision_ref,
        statepool=statepool,
    )
```
executor 读取 `EXECUTOR_DECISION_PACKET`（msgpack 格式），从中提取 route/tool_name/signals/doc_ids 等，然后走 tool registry 做 execute。

### D33. 如果 EXECUTOR_DECISION_PACKET 损坏、缺失、错误，系统会怎样

`executor_runtime.py:852-853`:
```python
if evidence_ref is None and transfer_strategy not in {
    "natural_handoff_text", "inline_text_handoff",
    "text_whole_lane", "text_strict_pure_lane"
}:
    raise ValueError(f"step {step.step_id} missing DENSE_EVIDENCE input")
```

如果 DENSE_EVIDENCE 缺失 → **抛异常**
如果 EXECUTOR_DECISION_PACKET 缺失 → `decision_packet_ref` 为 None → `_feature_bundle_from_executor_decision_packet` 需要处理（需验证逻辑）

如果 packet 内容错误（route 不对）→ executor 会走错误的 tool → route/tool correctness 下降

### D34. 现有 tests 是否只证明"看到了这个对象"还是证明"缺了它 correctness 会下降"

**只证明"看到了"。** 证据：
- `test_state_ref_consumer_sensitivity_audit_changes_executor_visibility_by_kind` (line 2997): 验证关闭 CHANNEL_SNAPSHOT/TOOL_CANDIDATE_SET/RANKED_EVIDENCE_BUNDLE/REPLAY_ELIGIBILITY_BUNDLE 后 executor input kinds 中不再出现这些 kind → **但只检查 visibility**
- `test_typed_state_authenticity_v3_emits_step_truth_and_transfer_truth_audit` (line 458): 验证 EXECUTOR_DECISION_PACKET 出现在 executor_input_kinds → **只检查 presence**
- **没有测试检查**：关闭 DENSE_EVIDENCE 或 EXECUTOR_DECISION_PACKET 后 route_exact_rate 是否下降

### D35. `test_smoke.py` 里的 consumer sensitivity 是否足够

**不够。** `test_state_ref_consumer_sensitivity_audit_changes_executor_visibility_by_kind` 只验证了"关闭 rich state kind 后 visibility 变化"，没有验证：
1. 关闭 DENSE_EVIDENCE 后 correctness 是否下降
2. 关闭 EXECUTOR_DECISION_PACKET 后 executor 是否还能正确 route
3. 同时关闭所有 typed state 后 system 是否仍能正确工作

### D36. 是否只证明 visibility change，没有证明 route/tool/case correctness sensitivity

**是的。**

### D37. rich typed-state 对象哪些是主线必要，哪些是 audit/support

| 对象 | 角色 | 在 `state_packet_minimal` 中 |
|---|---|---|
| `DENSE_EVIDENCE` | 主线必要 — 没有它 executor 抛异常 | yes |
| `EXECUTOR_DECISION_PACKET` | 主线必要 — executor 用它 route/tool | yes |
| `FEATURE_BUNDLE` | support/audit — 在 `state_packet_minimal` 中不传给 executor | **no** |
| `CHANNEL_SNAPSHOT` | support/audit | **no** |
| `TOOL_CANDIDATE_SET` | support/audit | **no** |
| `RANKED_EVIDENCE_BUNDLE` | support/audit | **no** |
| `REPLAY_ELIGIBILITY_BUNDLE` | support/audit (但 replay gate 需要) | **no** |
| `TOOL_ARTIFACT` | 主线必要 — executor 输出 | yes |
| `EMBEDDING` | memory 面需要 | **no** |

当前 `state_packet_minimal` 的设计是合理的：只传主线必要对象 + 在 audit 路径下可查看 support 对象。

### D38. 是否存在把 rich audit object 误读成主线机制收益的风险

**存在，但当前文档已做防范。** Benchmark report 明确写：
```
FEATURE_BUNDLE, CHANNEL_SNAPSHOT, TOOL_CANDIDATE_SET, RANKED_EVIDENCE_BUNDLE,
and REPLAY_ELIGIBILITY_BUNDLE are support/audit visibility unless otherwise.
```

但如果有人在写答辩稿时不再复读这条审计说明，可能误用。

---

## F. 共享记忆与 replay 证据链

### F39. `memory_dual_mode_fairness_v3` 到底回答什么问题

回答：在 dual-mode 下，text 和 protocol 的 memory 对象能否互相兼容（text restore 不会收到 typed state，protocol restore 收到正确的 minimal typed packet）。

核心指标：object parity gate (`runner.py:1265-1328`)

### F40. 它为什么不能被读成 replay proof

因为：
1. `single_variable: false` — 同时变化 mode + memory policy + restore object class
2. 没有 expected replay 命中验证（`expected_reuse_mode` 可能全是 `none` 或 `assist`）
3. 该 pack 的目标是 fairness/parity，不是 policy 归因

### F41. 是否明确是 `single_variable=false`

YAML 层面：`memory_dual_mode_fairness_v3_benchmark.yaml` 需要确认。根据 review 文档的分析，它是 `false`。需要核查 YAML 原文。

### F42. 到底混了哪些变量

1. `mode` (text vs protocol)
2. `runtime_reuse_contract` (可能同一 pack 内不同 row 有不同的 reuse contract)
3. `restore_object_class` (text-compatible minimal vs protocol typed minimal)
4. `transfer_strategy` (text_whole_lane vs state_packet_minimal)

### F43. formal replay proof 应该只读哪两个 pack

1. **`memory_reuse_v3`** — protocol-only replay proof surface
2. **`memory_policy_controlled_v3`** — protocol carrier-fixed policy attribution（真正的单变量）

### F44. `memory_policy_controlled_v3` 为什么更接近单变量归因

因为：固定 `mode=protocol` + 固定 `transfer_strategy=state_packet_minimal` + 只改变 `runtime_reuse_contract`。只有一个变量在变。

`_memory_replay_evidence_gate` 也只对这两个 pack 生效（`runner.py:1335`）:
```python
"applicable": pack_type in {"memory_reuse_v3", "memory_policy_controlled_v3"},
```

### F45. `memory_replay_evidence_gate` 是否只作用于 protocol-only pack

**是。** `runner.py:1335` 明确限制。

### F46. 如果 `expected_reuse_mode` 没命中，runner 是否会正确 withheld

**会。** 证据：`test_memory_replay_evidence_gate_fails_on_expected_replay_mismatch` (test_smoke.py:2627) 验证了这条路径。
`_build_headline_gates` 中 (`runner.py:1406`): memory_replay_allowed 依赖 `memory_replay_evidence_gate.passed`。

### F47. text 模式 replay restore allowlist 和 protocol minimal restore allowlist 是否真的不同

**真的不同。** 证据：`test_replay_restore_allowlist_respects_text_and_protocol_minimal_contracts` (test_smoke.py:2463):
- text: only `TOOL_ARTIFACT` allowed
- protocol minimal: `DENSE_EVIDENCE` + `EXECUTOR_DECISION_PACKET` + `TOOL_ARTIFACT` allowed

### F48. text lane 当前能恢复哪些对象

**`TOOL_ARTIFACT` only。** `test_memory_dual_mode_fairness_v3_replay_restore_visibility_matches_mode_contract` 证实: `restored_kinds == ["TOOL_ARTIFACT"]`

### F49. protocol minimal exact replay 当前能恢复哪些对象

**`DENSE_EVIDENCE` + `EXECUTOR_DECISION_PACKET` + `TOOL_ARTIFACT`。** 同上测试证实。

### F50. 当前 memory 结论能不能说"减少重复工作已证实"

**不能。** 只能说"memory store/query/replay gate 机制存在"。formal efficiency claim 需要 replay evidence gate 通过 + API repeat=10 验证。

### F51. 还是只能说"机制存在，efficiency claim 仍要绑定 replay gate"

**后者。** 这是当前最诚实的表述。

### F52. `memory_dual_mode_fairness_v3` 的 object parity gate 能证明什么，不能证明什么

**能证明**：text lane 的 memory restore 不会意外暴露 typed state；protocol lane 的 restore 收到了正确的 minimal typed packet；hidden field leak 为 0。

**不能证明**：memory 复用带来效率提升；memory policy 的因果归因；任何 replay 证据。

---

## G. LangGraph 的角色

### G53. `langgraph_adapter.py` 到底是什么

**固定四节点编排 substrate。** 证据：
- `langgraph_adapter.py:18`: `STATEBUS_GRAPH_NODES = ("planner", "retriever", "executor", "summarizer")`
- `langgraph_adapter.py:220-283`: 四个 node 函数都是 `pull state -> delegate to orchestrator -> push snapshot`
- 零 text/protocol 分支在 graph 层
- 语义层完全在 `Orchestrator` 内

### G54. 是否真正替代了 StateBus 语义层

**没有。** LangGraph 替代了"调用 Orchestrator 的循环代码"。StateBus 的协议、StateRef、replay gate、memory commit、schema validation 全部在 Orchestrator 内。

### G55. 是否只是复用 Orchestrator 的 schema、replay、step invocation、state effects

**是。** 精确地说，LangGraph 做了：
1. 构建固定节点图（一次性）
2. 在 graph state 中保存 ctx/results/state_refs/memory_hits/metrics 快照
3. 为每次 run_task 创建一个新的 graph invocation

Orchestrator 做了：
1. plan compile
2. replay gate decision
3. step invocation（call agent.execute_step）
4. schema validation
5. result registration
6. StatePool + MemoryStore side effects

### G56. 当前文档中是否还有把 LangGraph 说得过重的地方

**需要核查。** 重点查 `README.md` 和 `MASTER_PRESENTATION_GUIDE.md`。当前 `README.md` 第 4 章节列 `agents/` 目录时写了"LangGraph 编排入口"但没写"固定四节点 substrate"。`statebus_contest_aligned_review_20260614.md` 已指出问题。

### G57. 从赛题要求出发，LangGraph 在答辩中应处于什么位置

**系统完整性/工程实现支撑。** 不应出现在 formal headline 或 claim lanes 中。可以说"我们用 LangGraph 固定图承载多 Agent orchestration，保证执行轨迹可观测"，但不应说"LangGraph 本身提供了低开销通信、非文本状态传递或共享记忆复用"。

---

## H. 文档口径是否收口

### H58. 四个核心文档是否已经对齐

**基本对齐但仍有 drift。** 通过对比：

| 文档 | state_transfer wording | pack 数量 | 术语一致性 |
|---|---|---|---|
| `README.md` | 待核查 | 待核查 | 待核查 |
| `tasks/README.md` | 已对齐，明确 read boundary | 11 个，逐个标清楚 | ✓ |
| `MASTER_PRESENTATION_GUIDE.md` | 基本对齐，待句级核查 | 提到 11 个 active pack | 基本对齐 |
| `task_design_and_mode_comparison.md` | 已对齐，含 stopline | 11 个，完整表格 | ✓ |

### H59. 哪些旧 review 里指出的 drift 已经修复

根据 `statebus_contest_aligned_review_20260614.md` 第 7 节，已修复的：
- `tasks/README.md` 的 read boundary 已逐 pack 标注 ✓
- `task_design_and_mode_comparison.md` 的 stopline 已加入 ✓
- pack 分层的三大概念不要混的表已出现在 `MASTER_PRESENTATION_GUIDE.md` ✓

### H60. 哪些 drift 仍然存在

需要逐文件核查：
1. `README.md` 的 pack 数量描述是否仍写 "6 个" 或 "8 个"（而不是 11 个）
2. `MASTER_PRESENTATION_GUIDE.md` 的 state_transfer wording 是否仍写 `text_brief -> state_ref`
3. `current_feature_scope.md` 仍引用历史 run 但未标注 historical snapshot

### H61. "只让通信格式不同" 这种表述是否仍然过强

**是过强的。** 当前 `contest_dual_mode_controlled_v3` 改变了 mode + handoff_object。通信格式（text vs protocol protobuf）只是变化的一部分。handoff object（strict pure text vs minimal typed packet）是不同的维度。

### H62. 当前文档是否还在混读五种概念

根据 `MASTER_PRESENTATION_GUIDE.md` 的"三个概念不要混"表，已明确区分：
- dual-mode headline
- typed-state mechanism
- external text audit
- memory fairness
- memory replay proof

**但在 `README.md` 和 `current_feature_scope.md` 中仍需核查是否有混读。**

### H63. 哪些公开说法现在可以保留

1. "StateBus 实现了结构化控制面降低消息开销" ✓（绑定 contest pack gate）
2. "StateBus 实现了 typed state 机制" ✓（绑定 mechanism pack gate）
3. "StateBus 实现了共享记忆存储、检索和 replay gate" ✓
4. "当前 v3 surface 已比旧 mixed pack 更干净" ✓

### H64. 哪些必须 withheld

1. "StateBus 全面优于 text" ✗
2. "memory reuse 已证实减少重复工作" ✗（除非 replay evidence gate 通过）
3. "text baseline 是完全传统纯文本系统" ✗
4. "LangGraph 是创新点" ✗
5. "非文本状态传递带来效率收益" ✗

---

## I. 测试与证据层级

### I65. `test_smoke.py` 已经覆盖了哪些关键合同

| 合同 | 测试 | 行号 |
|---|---|---|
| replay gate 失效时 withheld | `test_memory_replay_evidence_gate_fails_on_expected_replay_mismatch` | 2627 |
| text restore allowlist | `test_replay_restore_allowlist_respects_text_and_protocol_minimal_contracts` | 2463 |
| text restore visibility | `test_memory_dual_mode_fairness_v3_replay_restore_visibility_matches_mode_contract` | 2426 |
| repeat=1 不通过 formal stability gate | `test_contest_dual_mode_controlled_v3_repeat_one_does_not_pass_formal_stability_gate` | 3219 |
| repeat=10 通过 formal stability gate | `test_contest_dual_mode_controlled_v3_repeat_ten_exposes_formal_stability_metrics` | 3188 |
| object parity gate 失败 | `test_object_parity_gate_fails_when_text_restore_visibility_is_incompatible` | 2588 |
| headline gates 正确分拆 | `test_headline_gates_split_memory_replay_from_generic_state_transfer_flag` | 2654 |
| consumer sensitivity visibility | `test_state_ref_consumer_sensitivity_audit_changes_executor_visibility_by_kind` | 2997 |
| EXECUTOR_DECISION_PACKET 消费 | `test_typed_state_authenticity_v3_emits_step_truth_and_transfer_truth_audit` | 458 |
| memory policy replay headline gate | `test_memory_policy_controlled_v3_manifest_exposes_replay_headline_gate` | 2975 |

### I66. 哪些测试说明 pack metadata/gate 已存在

- `test_memory_policy_controlled_v3_manifest_exposes_replay_headline_gate` (2975)
- `test_headline_gates_split_memory_replay_from_generic_state_transfer_flag` (2654)
- `test_contest_dual_mode_controlled_v3_repeat_ten_exposes_formal_stability_metrics` (3188)

### I67. 哪些测试说明 replay evidence gate 已存在

- `test_memory_replay_evidence_gate_fails_on_expected_replay_mismatch` (2627) — 直接测试 gate 逻辑
- `test_memory_policy_controlled_v3_manifest_exposes_replay_headline_gate` (2975) — 端到端测试

### I68. 哪些测试说明 repeat=1 不能释放 formal headline

- `test_contest_dual_mode_controlled_v3_repeat_one_does_not_pass_formal_stability_gate` (3219) — 直接验证

### I69. 哪些测试说明 repeat=10 gate 在代码里已定义

- `test_contest_dual_mode_controlled_v3_repeat_ten_exposes_formal_stability_metrics` (3188) — verbose assert
- `test_benchmark_repeat_ten_records_stability` (4435) — 一般性测试

### I70. 当前哪些结果只能算 local deterministic check

所有在 CI/test 中使用 `DeterministicEmbeddingProvider()` + `DeterministicLLMClient()` 的测试都只能算 local deterministic check。包括：
- `test_contest_dual_mode_controlled_v3_repeat_ten_exposes_formal_stability_metrics`
- 所有 gate 测试
- 所有 consumer sensitivity 测试

**它们不能算 formal evidence**，因为 deterministic 环境消除了 LLM/embedding 的随机性，不代表 live API 下的行为。

### I71. 如果暂时不跑 API repeat=10，也不做 openEuler/Docker/VM，当前最应优先补的证据

1. **consumer sensitivity 的正确性版本**：关闭 EXECUTOR_DECISION_PACKET 后验证 route_exact_rate 是否下降（目前只有 visibility 测试）
2. **`single_variable: false` 声明修复**：contest YAML 的修正是零成本的
3. **文档 drift 全覆盖修复**：README + MASTER_PRESENTATION_GUIDE + current_feature_scope
4. **memory_policy_controlled_v3 的 replay evidence**：验证有多少 task 真正命中了 expected_reuse_mode

---

## J. 最终判断与计划

### J72. 项目到底更接近什么状态

**机制已实现，但 benchmark/claim closure 仍明显未闭合。** 不是"只差 formal rerun"。

差距清单：
1. 单变量归因不成立（当前 YAML 已改成 `single_variable: false`，但解释口径仍必须保持复合变量）
2. consumer sensitivity 只测 visibility 不测 correctness
3. text baseline 定义需在所有文档统一收口
4. `current_feature_scope.md` 引用历史 run 未标 historical
5. API repeat=10 未跑
6. openEuler 兼容性未验证

### J73. 当前最严重的问题到底是

**Claim/evidence 问题 > benchmark 设计问题 > 实现机制问题。**

实现机制（代码路径、gate、guard、state production/consumption）基本正确。问题在于：
- benchmark 现在已声明 `single_variable: false`；如果外部材料仍写成单变量，那属于文档/答辩 drift
- text baseline 被称为 "formal headline" 但没有标注 "within StateBus runtime"
- consumer sensitivity 只证明 visibility 不证明 correctness
- 文档 drift 会让评审无法准确理解你到底比了什么

### J74. 四件事的优先级

如果只能做 benchmark 设计、实验结果解读、实现机制、纯文本逻辑：

1. **Benchmark 设计**（P0）：`single_variable: false` 与 reading_contract 说明当前已修；剩余是保证所有主动文档与答辩口径同步
2. **实验结果解读**（P0）：所有 headline 绑定 gate，未通过 gate 的必须 withheld
3. **纯文本逻辑**（P0）：统一文档中 text_strict_pure_lane / text_whole_lane / external 的定义
4. **实现机制**（P1）：consumer sensitivity 补 correctness 维度（不是 visibility 维度）

### J75. 最小可答辩闭环路线

1. 修 `single_variable: false` + 补齐 reading_contract（当前 branch 已完成）
2. 跑 `memory_policy_controlled_v3` 的 replay evidence gate（confirm 有 skip_execute/skip_retrieve_execute 命中）
3. 补 consumer sensitivity correctness 测试（关闭 EXECUTOR_DECISION_PACKET 验证 route 正确率下降）
4. 文档全量 drift fix（README + MASTER_PRESENTATION_GUIDE + current_feature_scope）
5. 统一在答辩中使用这套表述："StateBus 三层机制已实现并按通信、状态真实性、记忆复用三个 claim 分层验证"

### J76. 哪条 headline 可以先保，哪条 headline 必须先撤或降级

**可以先保的**：

| Headline | 条件 |
|---|---|
| 结构化控制面降低通信开销 | 绑定 contest gate, 标注 text baseline 是 strict carrier within StateBus runtime |
| typed state 机制存在 | 绑定 mechanism gate, 标注"机制真实性"不是"效率收益" |
| 共享记忆 assist + replay gate 机制存在 | 标注"机制存在"，efficiency claim withheld until replay evidence gate pass |

**必须先撤或降级的**：

| Claim | 改为 |
|---|---|
| "StateBus 全面优于 text" | "结构化通信 + typed state 在 controlled tasks 下降低控制面开销" |
| "memory reuse 减少重复工作" | "memory store/query/replay gate 机制存在" |
| "text baseline 是传统纯文本系统" | "text baseline 是 StateBus runtime 内的 strict natural-language carrier" |
| "LangGraph 是创新点" | "LangGraph 是固定图编排 substrate，语义层在 Orchestrator" |
| "single_variable: true" | "single_variable: false, mode+handoff 复合变化" |
