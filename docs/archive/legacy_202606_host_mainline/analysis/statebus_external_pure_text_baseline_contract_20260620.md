# StateBus External Pure-Text Baseline: Formal Comparator Contract

**日期**: 2026-06-20
**审稿人角色**: 外部独立评审
**前序文档**: 
- `docs/analysis/statebus_independent_full_repo_review_20260620.md` (第一轮)
- `docs/analysis/statebus_independent_followup_deep_diagnosis_20260620.md` (第二轮)

**本文档定位**: 不是评论、不是审计、不是诊断。这是一份**可执行的实验设计规范 (contract doc)**。读者拿着这份文档就应该知道: baseline 怎么定义、怎么实现、怎么测、怎么读。

---

## 1. Goal

定义一个严格、公平、可复现、可与 StateBus frozen headline (`contest_honest_headline_v1`, API repeat=10, `state_packet_minimal`) 正式对比的 **external pure-text multi-agent baseline**。

这份 baseline 完成后:
- 赛题的 "纯文本协作 vs 结构化协议" 核心对比将被真正闭合
- 当前 headline 的所有内部指标 (control_bytes, llm_total_tokens, handoff_wire_bytes, message_count, exact/admissible rates, task_ms) 将获得可信的外部参照物
- "protocol 到底有没有优势" 这个问题将有可证伪的实验答案

---

## 2. Why This Third Round Exists

第一轮: 发现 comparator 不是 external baseline。
第二轮: 追踪到代码根因 (Summarizer 只调 LLM、typed state 被重新文本化、exact=0.25 是 tool substitution)。
本轮: 把第二轮的推荐 (Definition B-Minimal) 收敛成可执行的实验合同。

本轮**不**解决: memory claim 的降级问题、如何提升 exact_match、如何改写叙事。这些是后续轮次的任务。

---

## 3. Inputs From Previous Reviews

| 来源 | 关键输入 |
|------|----------|
| 第一轮 §3 | Definition B-Minimal 概念骨架 |
| 第一轮 §10.2 | "text_whole_lane 是内部 comparator 不是 external baseline" |
| 第二轮 §3 | 三种 baseline 定义的优缺点对比 |
| 第二轮 §4 | LLM token 根因链 (Summarizer must consume text) |
| 第二轮 §5 | row-level exact=0.25 decomposition (tool substitution pattern) |
| 第二轮 §6 | 指标公平性分析 (control_bytes vs llm_tokens 错位) |
| 第二轮 §11 | 唯一主方向: 补 external baseline |

---

## 4. What Definition B-Minimal Must Solve

### 4.1 It Must Answer

赛题核心问题: "结构化协议协作模式相比传统纯文本协作方式，是否在通信开销、任务时延和记忆复用方面有改进效果？"

要对准这个问题的 baseline 必须:
1. 是一个真实的纯文本 multi-agent 协作系统
2. 在相同任务、相同 corpus、相同模型条件下运行
3. 不使用 StateBus 的结构化协议基础设施
4. 有独立、可审计的通信开销测量

### 4.2 It Must Not Be

- StateBus runtime 内部的一个 mode switch
- 共享 StateBus ToolRegistry / lexical match / feature bundle 的 "轻改 carrier" 版本
- 一个 deterministic stub 或 lexical matcher (那是 engineering sanity check, 不是 baseline)
- 一个完全不同任务对象的外部系统 (不可比)

### 4.3 Why Not Alternatives

| 方案 | 为什么不够 |
|------|------------|
| `text_whole_lane` (current internal comparator) | 共享 StateBus runtime, lexical recovery path, ToolRegistry; 不是赛题要的 "传统纯文本协作方式" |
| 完全独立传统 MAS (e.g. raw ReAct) | 实现复杂度高, 与当前 task object 的 contract match 难度大, 变量控制差 |
| `pure_text_open_baseline_v1` (lexical stub) | 不是 real-LLM system; 用 keyword overlap 做 routing, 不涉及任何 communication overhead |

**B-Minimal 是当前最合理的折中**: 保持 LLM agent 的独立性, 共享 task/corpus/scoring 以控制变量, 禁止 StateBus infrastructure。

---

## 5. Recommended External Baseline Definition

### 5.1 Formal Name

```
external_pure_text_strict_baseline_v1
```

### 5.2 Evidence Tier

```
formal_headline_comparator
```

(升格自当前的 `audit_only`)

### 5.3 One-Sentence Definition

> 一个使用真实 LLM 做规划、检索决策、总结的独立纯文本 multi-agent system, 与 StateBus headline 共享相同的 corpus、task query、playbook tools 和 case correctness contracts, 但不使用 StateBus 的 runtime infrastructure、protocol frames、typed state packets、tool registry lexical match、或任何结构化辅助路径。

---

## 6. Formal Comparator Contract

### 6.1 Fixed Items (MUST be identical between baseline and headline)

| 维度 | 内容 | 来源 |
|------|------|------|
| **Task set** | 完整的 20 条 text-mode tasks from `contest_honest_headline_v1` | `tasks/contest_family_spec.yaml` → `contest_honest_headline_v1` pack |
| **Task IDs** | `rr-*-text-001` (all 20 text rows) | frozen headline task set |
| **Corpus** | 相同的 `corpus_path` YAML files | task.corpus_path |
| **Corpus docs** | 相同的 `corpus_doc_ids` (same evidence universe) | task.corpus_doc_ids |
| **Playbook tools** | 相同的 tool catalog (route-tool 映射) | `contest_family_spec.yaml` tool definitions, or `PLAYBOOK_CATALOG` from `text_open_baseline.py` |
| **Case correctness contract** | 相同的 `primary_expected_route`, `primary_expected_tool`, `acceptable_routes`, `acceptable_tools`, `disallowed_families`, `abstention_allowed` | `contest_family_spec.yaml` case definitions |
| **Summary contract** | 相同的 `summary_contract`, `summary_hint` | task.summary_hint |
| **LLM model** | `deepseek-v4-flash` (与 headline 相同) | `deploy/statebus_llm.yaml.local` |
| **LLM config** | 相同 API endpoint, temperature, max_tokens | 同上 |
| **Repeat policy** | `repeat=10` (与 headline 相同) | frozen headline repeat gate |
| **Scoring judge** | 相同的 `_build_case_contract_audit` 逻辑 (但需独立实现, 见 §6.3) | `eval/runner.py:885-982` |
| **Report structure** | 相同的 primary metric 表 + compare CSV | frozen headline report format |
| **Metric definitions** | 见 §9 |

### 6.2 Varied Items (MUST differ between baseline and headline)

| 维度 | Baseline (External Pure-Text) | Headline (StateBus Protocol) |
|------|-------------------------------|------------------------------|
| **Agent-to-agent carrier** | Natural language text blocks (plain text or JSON-with-NL-values) | Protobuf control frames + StateRefLite pointers |
| **State transfer** | No typed state. Evidence text inlined in messages. | `DENSE_EVIDENCE` + `EXECUTOR_DECISION_PACKET` via StateRef |
| **Memory/replay** | Native replay only: re-run LLM on matched retrieval set (no StateBus memory contract) | `validated_replay` / `exact_replay` with MemoryStore + replay gate |
| **Planner** | LLM-generated plan (not YAML contract compiler) | YAML contract compiler (in headline) |
| **Route/tool decision** | LLM-only with plain-text evidence | StateBus lexical match + feature bundle + tool registry |
| **Executor** | Direct tool invocation based on LLM's chosen route/tool | StateBus playbook executor with typed state input |
| **Runtime engine** | Standalone Python loop or minimal DAG, NOT StateBus orchestrator | StateBus orchestrator + LangGraph DAG |

### 6.3 Forbidden Items (MUST NOT be used by baseline)

| 禁止项 | 原因 |
|--------|------|
| `StateRef`, `StateRefLite`, `StateRefFull` | 核心 typed state 机制 |
| `EXECUTOR_DECISION_PACKET` | 核心 typed state packet |
| `DENSE_EVIDENCE` (as typed state kind) | 同 typed state |
| `FEATURE_BUNDLE` / `CHANNEL_SNAPSHOT` / `TOOL_CANDIDATE_SET` / `REPLAY_ELIGIBILITY_BUNDLE` | 同 typed state channel |
| `StatePool` (mmap/SHM/CAS) | 核心 statepool infrastructure |
| `statepool/store.py` | 同上 |
| `runtime/orchestrator.py` | StateBus 核心编排 |
| `runtime/executor_runtime.py` | 包含 `_feature_bundle_from_text_whole_lane_handoff` 等恢复路径 |
| `runtime/contracts.py` | Schema 校验 |
| `runtime/task_profile.py` | Runtime policy normalization |
| `runtime/reuse_contract.py` | StateBus replay contract |
| `runtime/langgraph_adapter.py` | LangGraph DAG adapter |
| `agents/sample_agents.py` | All StateBus agent implementations |
| `protocol/messages.py` | Protobuf message framework |
| `protocol/channels.py` | StateChannel registry |
| `memory/store.py` | StateBus MemoryStore |
| `eval/runner.py` | StateBus benchmark runner (scoring logic can be independently re-implemented, see §6.4) |
| Any import of `runtime/*` or `agents/*` or `protocol/*` or `statepool/*` or `memory/*` | 系统性污染防护 |
| `primary_expected_route` / `primary_expected_tool` / `acceptable_routes` / `acceptable_tools` passed to baseline agents as input (metadata leakage) | Would make baseline "know" the answer |
| `corpus_metadata` hints in task definition | 同上 |
| `reuse_signature` / `runtime_reuse_contract` fields | StateBus-specific replay contract |

### 6.4 Allowed Shared Items (with restrictions)

| 允许共享 | 限制 |
|----------|------|
| `tasks/sample_tasks.py` `SampleTask` dataclass | 只用于加载 task definition (query, goal, corpus_path, corpus_doc_ids, task_theme, summary_hint)。不加载 case contract correctness fields |
| `tasks/local_corpus.py` `CorpusDoc` | 只用于 corpus document loading。不 load metadata hints |
| Corpus YAML files | 完全共享 |
| `contest_family_spec.yaml` case contract fields | 只在 scoring judge 阶段加载 (post-hoc evaluation), 不在 agent execution 阶段暴露 |
| `eval/runner.py:885-982` `_build_case_contract_audit` logic | 独立重新实现为 standalone scoring function。不 import runner.py |
| `eval/metrics.py` `TaskMetrics` dataclass | 独立重新定义 compatible metrics struct |
| `runtime/llm.py` `ChatMessage`, `LLMClient`, `LLMConfig`, `build_llm_client`, `extract_json_object` | 纯 LLM 调用基础设施。允许 import |
| Playbook tool names and route→tool mappings | 作为 plain data (list of dicts or enum), 不作为 StateBus `ToolRegistry` |
| Same corpus docs | `retrieve_corpus_docs()` can be independently re-implemented with lexical ranking |

---

## 7. Runtime Contract

### 7.1 Is This Baseline a Multi-Agent System?

**Yes.** It has at minimum two independently-reasoning LLM agents:
- **Planner**: reads task + evidence, produces route/tool decision
- **Summarizer**: reads task + evidence + decision, produces final summary

This satisfies the 赛题 requirement of "不少于 3 个 Agent 协同" when counted together with the implicit Retriever role.

### 7.2 Agent Roles and Capabilities

| Role | Implementation | LLM? | Allowed Actions |
|------|---------------|------|-----------------|
| **Planner** | LLM call: receive task query + corpus evidence text → output `{route, tool_name, strongest_competing_route, validation_check}` | Yes | Read task, read evidence, decide route/tool |
| **Retriever** | Lexical ranking of corpus docs by word overlap with task query | No | Rank corpus docs, return top-N evidence snippets |
| **Executor** | Direct invocation of chosen tool (playbook) based on Planner's decision | No | Execute tool, return results |
| **Summarizer** | LLM call: receive task + evidence + chosen route/tool → output plain-text summary | Yes | Generate summary |

### 7.3 Inter-Agent Communication Contract

Agent 间只允许传递**自然语言文本消息**。消息格式:

```
Planner → Retriever:
  "Task: {goal}. Query: {query}"

Retriever → Planner:
  "Evidence: doc {doc_id}: {snippet}. doc {doc_id}: {snippet}."

Planner → Executor:
  "Decision: route={route}, tool={tool_name}. Competing: {competing_route}. Validation: {check}."

Executor → Summarizer:
  "Action: executed {tool_name} on route {route}"

Summarizer → (final output):
  Plain text summary. No JSON, no structured protocol names.
```

Each message is a single plain-text string. No protobuf, no JSON envelopes, no typed fields.

### 7.4 Contamination Detection

以下任一情况出现, baseline 即被判定为"被污染":
1. Any import of `runtime/*`, `agents/*`, `protocol/*`, `statepool/*`, `memory/*` modules
2. Use of `StateRef`, `StateRefLite`, typed packet names in message content
3. `primary_expected_route` / `primary_expected_tool` / `acceptable_routes` / `acceptable_tools` appearing in any agent input
4. `corpus_metadata` hints being read from corpus files (only raw text may be used)
5. Route/tool decision relying on lexical match against pre-defined keyword sets (i.e. `choose_playbook()` from `text_open_baseline.py`)
6. Use of StateBus `ToolRegistry` or `FeatureBundle` or `ChannelSnapshot`

### 7.5 Lexical Fallback: Strictly Forbidden

当前 `ExternalTextOpenRuntime._sanitize_route_tool()` (`text_open_baseline.py:569-582`) 在 LLM 输出不匹配 PLAYBOOK_CATALOG 时回退到 `fallback_route/fallback_tool_name` (来自 `choose_playbook()` 的 lexical 结果)。

**Baseline B-Minimal MUST NOT have this fallback.**

替代方案: 如果 LLM 输出的 route/tool 不在合法集合中:
1. Record the exact LLM output as-is
2. Mark the task as `correctness_label=mismatch` in scoring
3. Do NOT silently replace with a lexical fallback

This ensures the baseline is genuinely "LLM-decided", not "LLM-suggested but lexical-corrected".

### 7.6 Allowed LLM Prompt Content

Planner prompt must contain ONLY:
- Task goal text
- Task query text
- Task theme
- Summary hint
- Evidence snippets from corpus docs (plain text)
- List of available route→tool pairs (as plain text names, not as structured protocol)

Planner prompt MUST NOT contain:
- `primary_expected_route` or `primary_expected_tool`
- `acceptable_routes` or `acceptable_tools` lists
- `abstention_allowed` flag
- `case_type` or `complexity_bucket`
- Any StateBus-specific terminology (DENSE_EVIDENCE, EXECUTOR_DECISION_PACKET, StateRef, FeatureBundle, etc)

Summarizer prompt must contain ONLY:
- Task theme
- Summary hint
- Evidence snippets
- Chosen route and tool (from Planner output)
- Competing route and validation check (from Planner output)

Summarizer output MUST BE plain text (not JSON, not structured protocol).

---

## 8. Task Surface Contract

### 8.1 Current Gap

`pure_text_open_live_api_slice_v1` has 8 tasks:
```
rr-auth-clean-text-001, rr-auth-ambiguous-text-001,
rr-billing-clean-text-001, rr-billing-ambiguous-text-001,
rr-checkout-clean-text-001, rr-checkout-ambiguous-text-001,
rr-deploy-distractor-text-001, rr-cache-distractor-text-001
```

Coverage gaps:
- Missing: `billing distractor`, `checkout distractor`, `deploy clean`, `deploy ambiguous`, `cache clean`, `cache ambiguous`, and ALL `replay_reusable (S2)` cases
- Only `simple` and `ambiguous` complexity covered for 3 of 5 families
- No S2/replay tasks → cannot assess memory claim

### 8.2 Recommended Task Surface

**All 20 text-mode tasks from `contest_honest_headline_v1`.**

Rationale:
1. Complete alignment with headline → direct row-by-row comparison possible
2. Covers all 5 families, all 4 complexity buckets (clean/distractor/ambiguous/reusable)
3. S2 (replay_reusable) tasks allow baseline-vs-headline memory replay comparison
4. 20 tasks × repeat=10 = 200 row-level results → statistically meaningful
5. Same task IDs as headline text side → no interpretation gap

### 8.3 Task Selection Logic

```python
tasks = [
    task for task in load_task_set_bundle("contest_honest_headline_v1").tasks
    if task.supports_mode("text")
    and task.transfer_strategy == "text_whole_lane"
]
# All 20 text-mode tasks from headline
```

Do NOT filter by:
- `complexity_bucket` (include all)
- `expected_reuse_mode` (include none + skip_execute)
- `primary_expected_tool` (include even those without)

### 8.4 MUST Cover

- **Simple**: `*-clean-*` cases (5 families → 5 tasks)
- **Distractor**: `*-distractor-*` cases (5 families → 5 tasks)
- **Ambiguous**: `*-ambiguous-*` cases (5 families → 5 tasks)
- **Reusable/S2**: `*-replay_reusable-*` cases with `expected_reuse_mode=skip_execute` (5 families → 5 tasks)

Total: 20 tasks.

---

## 9. Metrics Contract

### 9.1 Primary Metrics (these answer the contest scoring question)

| # | Metric | Definition | Why Primary | Scoring Alignment |
|---|--------|-----------|-------------|-------------------|
| 1 | **llm_total_tokens** | Sum of prompt_tokens + completion_tokens from ALL LLM API calls (Planner + Summarizer) | 赛题 25 分 "通信效率: token节省效果" 的直接测量 | 通信效率 25分 |
| 2 | **message_count** | Total number of inter-agent text messages exchanged | 赛题要求 "Agent 间消息次数" | 通信效率 25分 |
| 3 | **task_ms** | Wall-clock time from task start to final summary output | 赛题要求 "单任务总耗时", "任务时延" | 实验验证 15分 |
| 4 | **exact_match_rate** | `route_exact AND tool_exact` over all task runs | 路由和工具选择 precision — system correctness | 系统完整性 20分 |
| 5 | **admissible_match_rate** | `(exact OR acceptable_pair OR abstention) AND NOT wrong_family` | 系统没有做出错误选择的范围 | 系统完整性 20分 |

### 9.2 Secondary Metrics (support evidence, not primary scoring)

| # | Metric | Definition | Why Secondary |
|---|--------|-----------|---------------|
| 6 | **control_bytes** | Total wire bytes of all agent-to-agent messages (text encoding) | Internal engineering metric. Maps more closely to StateBus's protocol_bytes, but less directly to contest's "token开销" than `llm_total_tokens` |
| 7 | **route_exact_rate** | Fraction of tasks where observed_route == primary_expected_route | Sub-component of exact_match |
| 8 | **tool_exact_rate** | Fraction of tasks where observed_tool == primary_expected_tool | Sub-component of exact_match |
| 9 | **wrong_family_rate** | Fraction where observed family is in disallowed_families | Negative control |
| 10 | **abstention_rate** | Fraction where observed tool == allowed_abstain_tool | Diagnostic only |
| 11 | **replay_hit_rate** | Fraction of tasks where native replay was used (S2 tasks only) | Memory mechanism evidence |
| 12 | **skipped_step_count** | Steps skipped due to replay | Memory mechanism evidence |
| 13 | **reuse_gain** | skipped_step_count / planned_step_count | Memory mechanism evidence |

### 9.3 Metrics That Should NOT Lead Contest Claims

| Metric | Why Not |
|--------|---------|
| `control_bytes` alone (without `llm_total_tokens`) | Measures internal message encoding efficiency, not end-to-end LLM cost. Misleading as primary evidence of "token节省" |
| `state_transfer_count` | Only meaningful for protocol side. Baseline has 0 by definition |
| `handoff_wire_bytes` | Protocol-specific measurement. Not a fairness metric across arms |
| `handoff_payload_bytes` | Local storage cost, not communication cost |
| `protocol_bytes` | Same as control_bytes — internal encoding efficiency |
| `planner_one_shot_valid` | Gate metric, not superiority |

### 9.4 Comparison Table Format

The comparison table between baseline and headline MUST present primary metrics first, secondary metrics later:

```
| Metric                    | External Pure-Text Baseline | StateBus Protocol (Headline) | Delta  | Direction |
|---------------------------|----------------------------|------------------------------|--------|-----------|
| llm_total_tokens (mean)   | ...                        | 8430.9                       | ...    | ...       |
| message_count (mean)      | ...                        | 302.0                        | ...    | ...       |
| task_ms (mean)            | ...                        | 68850.85                     | ...    | ...       |
| exact_match_rate          | ...                        | 0.25                         | ...    | ...       |
| admissible_match_rate     | ...                        | 1.00                         | ...    | ...       |
| ---                       |                            |                              |        |           |
| control_bytes (mean)      | ...                        | 192935.2                     | ...    | ...       |
| route_exact_rate          | ...                        | 0.90                         | ...    | ...       |
| tool_exact_rate           | ...                        | 0.25                         | ...    | ...       |
```

---

## 10. Artifact Contract

### 10.1 Run Script Entry

```bash
python -m eval.open_runner \
  --pack external_pure_text_strict_baseline_v1 \
  --task-set contest_honest_headline_v1 \
  --repeat 10 \
  --llm-mode api \
  --llm-config deploy/statebus_llm.yaml.local \
  --out runs/external_pure_text_strict_baseline_v1_api_r10_YYYYMMDD_HHMMSS/
```

Or a dedicated script: `scripts/run_external_pure_text_strict_baseline_r10.py`

### 10.2 Output Directory Structure

```
runs/external_pure_text_strict_baseline_v1_api_r10_YYYYMMDD_HHMMSS/
├── COMMANDS.md              # exact commands run
├── SUMMARY.md               # gate results + key metrics
├── WORKTREE_BASELINE.md     # git commit + dirty status
├── baseline_report.md       # full markdown report
├── baseline_results.json    # complete JSON with all row-level data
├── baseline_compare.csv     # per-task aggregate CSV
├── headline_compare.md      # side-by-side comparison with frozen headline
└── logs/
    ├── runtime_smoke.log
    └── ...
```

### 10.3 Manifest Fields

```json
{
  "baseline_name": "external_pure_text_strict_baseline_v1",
  "baseline_version": "v1",
  "evidence_tier": "formal_headline_comparator",
  "task_set": "contest_honest_headline_v1",
  "task_count": 20,
  "repeat": 10,
  "total_runs": 200,
  "llm_model": "deepseek-v4-flash",
  "llm_mode": "api",
  "generated_at": "2026-06-2xT...",
  "contract": "...",
  "fairness_gate": {
    "no_statebus_imports": true,
    "no_typed_state_used": true,
    "no_metadata_leakage": true,
    "no_lexical_fallback": true,
    "llm_only_decisions": true
  },
  "public_surface": "formal_headline_comparator",
  "single_variable": true,
  "variable_axes": ["runtime_contract"],
  "data_source": "live_api_text_only",
  "statebus_contract_used": false,
  "selected_task_ids": [...],
  "selected_complexity_buckets": ["simple", "distractor", "ambiguous", "reusable"]
}
```

### 10.4 Stopline (MUST appear in report)

```
## Stopline
- This is a formal external pure-text multi-agent baseline comparator.
- It does NOT use StateBus runtime, protocol frames, typed state, or structured helpers.
- All agent decisions (Planner route/tool, Summarizer text) are made by real LLM calls.
- No lexical fallback corrects LLM output silently.
- Case contract correctness fields are only used in post-hoc scoring, never in agent execution.
- This baseline is intended to be the primary comparator for contest_honest_headline_v1.
- Do not merge its outputs into any internal StateBus pack claim.
```

### 10.5 Comparison with Frozen Headline

The `headline_compare.md` file MUST contain a side-by-side table with both primary and secondary metrics, using the frozen headline API r10 artifact as the protocol reference.

---

## 11. Fairness Audit

### 11.1 Why This Baseline Is Fair to StateBus

1. **Same task difficulty**: Baseline faces the same queries, evidence, and correctness contracts
2. **Same LLM**: Uses `deepseek-v4-flash` — no model-quality advantage to either side
3. **Same corpus**: Same evidence documents, same retrieval space
4. **Same scoring**: Same case contract evaluation logic (reimplemented independently)
5. **Same repeat**: 10 rounds — same statistical stability bar
6. **Protocol gets its full advantage**: StateBus still uses all its infrastructure (typed state, structured frames, memory replay). Baseline gets none of it.

### 11.2 Why This Baseline Is NOT Biased Against StateBus

1. Baseline is genuinely harder for the LLM: it must parse natural language evidence and make route/tool decisions without structured helpers. This is the POINT — we want to see if protocol helps.
2. If protocol has real advantage, the gap should be visible and attributable.
3. If protocol does NOT have advantage (tokens similar, exact_match similar), that is honest evidence too.

### 11.3 Why This Baseline Is NOT Biased FOR StateBus

1. Baseline does NOT silently degrade LLM performance: it uses the same model with clear prompts and full evidence text.
2. Baseline does NOT have artificial disadvantages: no hidden restrictions on evidence access, no forced suboptimal routing.
3. Baseline's LLM prompt is designed to be as helpful as StateBus's summarizer prompt — just without typed state encoding.

### 11.4 Most Likely Fairness Challenges and Responses

| Challenge | Response |
|-----------|----------|
| "Baseline's LLM-only planner is weaker than StateBus's structured route selection" | That is the hypothesis being tested. If protocol structure helps, the comparison should show it. |
| "The baseline uses the same corpus docs — isn't that StateBus infrastructure?" | Corpus docs are plain YAML text files. They are not StateBus-specific. |
| "Why not use a completely different multi-agent framework?" | Variable control. Using the same tasks/corpus/scoring eliminates non-system confounds. A completely different framework would introduce too many uncontrolled variables. |
| "The baseline's evidence retrieval (lexical ranking) is simpler than StateBus's (semantic embedding)" | Both systems have equal access to the same evidence documents. Baseline uses simpler ranking (lexical overlap) because it lacks embedding infrastructure. This is a legitimate point of comparison — if StateBus's embedding-based retrieval is better, it should show in results. |
| "The baseline has 0 state_transfer by design — isn't that unfair?" | State transfer is a capability unique to protocol. The comparison should answer: does having state transfer actually help? If baseline without state transfer does equally well, that IS the answer. |

### 11.5 How to Defend Result Interpretability

If baseline and protocol show **similar** results:
- Interpretation: "In this controlled setting, structured protocol did not provide measurable advantage over a well-designed LLM-only text baseline."
- This is NOT a "failure" — it's a finding.
- It may indicate the task complexity is insufficient to stress the protocol's advantages.

If baseline shows **worse** results than protocol:
- Interpretation: "Structured protocol improved route/tool precision and/or reduced token overhead compared to LLM-only text collaboration."
- Need to verify the gap is attributable to protocol mechanism, not to some other confound.

If baseline shows **better** results than protocol:
- Interpretation: "The LLM-only text baseline unexpectedly outperformed the structured protocol on these tasks."
- Would need root-cause analysis (prompt quality? retrieval quality? tool execution differences?).

---

## 12. Rejected Alternatives

| Rejected | Why Rejected |
|----------|-------------|
| Use current `pure_text_open_live_api_slice_v1` with 8 tasks as-is | Too small (8 vs 20). Missing complexity buckets. Missing S2. audit_only tier. |
| Use `text_whole_lane` internal comparator as formal baseline | Not external. Shares StateBus runtime. Has structured recovery path. |
| Build completely independent traditional MAS from scratch | Too much engineering overhead. Variable control too loose. Risk of creating a strawman. |
| Use `LangGraphNativeTextRuntime` | Uses LangGraph primitives (graph state, checkpointer, InMemoryStore) — another framework, not "traditional pure-text collaboration". Also deterministic_oracle, not real LLM. |
| Keep baseline at `audit_only` tier | Would not close the contest's core comparison requirement. |

---

## 13. Final Recommended Contract (Single Convergent Plan)

### 13.1 Baseline Definition

`external_pure_text_strict_baseline_v1` — a real-LLM, pure-text, multi-agent baseline that shares tasks/corpus/scoring/model with the frozen headline but uses ZERO StateBus runtime infrastructure.

### 13.2 Task Surface

**All 20 text-mode tasks from `contest_honest_headline_v1`** — covering all 5 families, all 4 complexity buckets.

### 13.3 Metric Contract

Primary (answer contest scoring): `llm_total_tokens`, `message_count`, `task_ms`, `exact_match_rate`, `admissible_match_rate`.
Secondary (support): `control_bytes`, `route_exact_rate`, `tool_exact_rate`, `wrong_family_rate`, `replay_hit_rate`.

### 13.4 Artifact Contract

Standard open_runner output (`baseline_report.md`, `baseline_results.json`, `baseline_compare.csv`) plus `headline_compare.md` with side-by-side frozen headline comparison.

### 13.5 Implementation Boundary

- Reuse: `eval/text_open_baseline.py` `ExternalTextOpenRuntime` as starting point, but MODIFY to remove `_sanitize_route_tool()` lexical fallback and `choose_playbook()` calls in live API path
- Reuse: `runtime/llm.py` for LLM client (this is pure LLM infrastructure, not StateBus-specific)
- Reuse: `tasks/sample_tasks.py` `SampleTask` for task loading (only task fields, not correctness fields)
- New: Standalone `scoring.py` that reimplements `_build_case_contract_audit` logic without importing `eval/runner.py`
- New: `scripts/run_external_pure_text_strict_baseline_r10.py` as entry point

---

## 14. Minimal Implementation Notes

### 14.1 What the existing `ExternalTextOpenRuntime` Already Does Right

1. `_run_live_text_task()` with `live_mode="api"` — correct structure
2. `_planner_decision()` → LLM call for route/tool — correct
3. `_summary_text()` → LLM call for summary — correct
4. `build_planner_prompt()` → task + evidence + tool list → good starting point
5. `retrieve_corpus_docs()` → lexical ranking — acceptable for baseline

### 14.2 What MUST Be Changed

1. **Remove `_sanitize_route_tool()` on line 246**: This is the lexical fallback contamination. Replace with: record LLM output as-is; if unrecognized, mark mismatch.
2. **Remove `choose_playbook()` fallback on lines 237-240**: In `live_mode="api"`, the dry-run text path (lines 237-240) should not pre-compute `route, tool_name` via lexical playbook. Move LLM call before any fallback computation.
3. **Remove `try-except` or validity gating that silently corrects LLM output**: If LLM outputs something not in the playbook catalog, record it and score it as mismatch.
4. **Verify no `contest_family_spec.yaml` correctness fields leak into prompts**: `build_planner_prompt()` currently does NOT pass `primary_expected_route`/`primary_expected_tool` — good. Must ensure this remains true for all task types.

### 14.3 What MUST Be Added

1. **Fairness gate check in manifest**: At runtime, verify no StateBus modules are imported. Record as boolean in manifest.
2. **Contamination self-check**: Before writing output, scan all message logs for StateBus-specific terms. If found, flag in manifest.
3. **Compatible scoring implementation**: A standalone `_score_baseline_row()` function that takes `{observed_route, observed_tool, task.case_contract}` and returns the same `{route_exact, tool_exact, exact_match, admissible_match, correctness_label}` as `eval/runner.py:885-982`.
4. **Full S2/replay support**: The baseline should support `native_reuse_on` policy for S2 tasks to compare replay behavior.

---

## 15. Open Questions That Still Need Human Decision

1. **Should baseline use `text_whole_lane` transfer strategy tasks, or `text_strict_pure_lane`?** The headline uses `text_whole_lane` for its text comparator. But for the external baseline, this distinction is irrelevant since the baseline doesn't use transfer_strategy at all. Recommendation: use `text_whole_lane` tasks for task ID alignment with headline, but the actual baseline implementation ignores transfer_strategy.

2. **Should the baseline have a separate "memory_off" and "native_reuse_on" policy dimension?** The headline has memory_policy as a variable axis (memory_off, working_assist, validated_replay, exact_replay). The baseline's native_reuse is simpler (re-run LLM when retrieval matches). Recommendation: run baseline in both `memory_off` and `native_reuse_on` and report both.

3. **Should the baseline report be in `open_report.md` format (open_runner) or `benchmark_report.md` format (runner)?** Currently open_runner uses a different report structure. For formal comparison, the baseline report should match headline report structure as closely as possible. Recommendation: extend open_runner's `_report_md()` to produce headline-compatible tables when `evidence_tier=formal_headline_comparator`.

4. **Should baseline scoring use the EXACT same code as headline scoring?** Risk of import contamination vs risk of scoring divergence. Recommendation: independently reimplement the `_build_case_contract_audit` logic in a standalone module. Add a cross-validation test that verifies both implementations produce identical results on the same test inputs.

5. **What if the LLM planner consistently fails (e.g., outputs invalid JSON)?** Decision needed: count as `correctness_label=mismatch` and record the raw output? Or allow one retry? Recommendation: allow ONE retry with "Output JSON only" instruction reinforced. If still invalid after retry, mark mismatch and record raw output.

---

## 16. Final Hard Answers

### 16.1 Should this baseline be upgraded to future formal headline comparator?

**Yes.** This is the single most important missing piece in the current experimental evidence chain. Without it, the contest's core comparison question ("structured protocol vs traditional pure-text") is unanswered.

### 16.2 If yes, what minimum conditions must be met before upgrade?

1. Baseline runs successfully on all 20 tasks × repeat=10 (200 total runs)
2. No contamination detected (fairness gate passes)
3. All agent decisions are made by real LLM (no silent lexical fallback)
4. Baseline report is generated in headline-compatible format
5. Side-by-side comparison with frozen headline is written
6. A human reviewer verifies the fairness gate claims against source code

### 16.3 Is this contract sufficient for an implementer to start coding?

**Yes.** The contract specifies:
- Which tasks to run (§8)
- What the baseline can and cannot do (§6, §7)
- How to measure success (§9)
- What artifacts to produce (§10)
- How to verify fairness (§11)
- What code to reuse and what to change (§14)

An implementer who reads this document + the existing `eval/text_open_baseline.py` + `eval/open_runner.py` + `tasks/sample_tasks.py` + `tasks/contest_family_spec.yaml` has everything needed to implement.

### 16.4 If not sufficient, what is missing?

One known gap: the standalone scoring implementation (`_build_case_contract_audit` reimplementation) is not specified at code level. The implementer should read `eval/runner.py:885-982` and reproduce the logic without importing it. This is documented in §14.3 item 3.

---

*Contract written: 2026-06-20*
*This document replaces the informal "Definition B-Minimal" concept from Round 2 with a formal, executable specification.*
*The next step after this contract is implementation, not further analysis.*
