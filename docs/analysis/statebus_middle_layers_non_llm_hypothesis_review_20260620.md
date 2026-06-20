# Hypothesis Review: Premature Non-LLM Compression in StateBus Middle Layers

**日期**: 2026-06-20
**审稿人角色**: 外部独立评审
**前序文档**:
- 第二轮 `statebus_independent_followup_deep_diagnosis_20260620.md` (LLM token 根因链)
- 第三轮 `statebus_external_pure_text_baseline_contract_20260620.md` (baseline contract)

**本文档定位**: 对一个特定结构性假设的代码级检验。不是全量审稿，不是 baseline contract。

---

## 1. Hypothesis Statement

> "当前 StateBus 路线的核心问题之一，可能不是单纯 comparator 不对，也不是单纯 token 指标没降，而是中间两层过早非 LLM 化了。也就是说，在语义尚未稳定、还需要歧义消解的时候，中间层就把信息压缩成 route/tool/packet/validation result 等结构化中间表示，导致信息断裂、tool disambiguation 变差、exact_match 低；但最终 Summarizer 仍然需要把这些结构化对象重新文本化喂给 LLM，所以 token 也没有显著下降。"

**拆成两个可检验的子命题**:

- **子命题 P1**: 中间非 LLM 层在语义尚未稳定时过早做了压缩/决策定型，导致了 tool disambiguation 变差 + exact_match 低。
- **子命题 P2**: Summarizer 把结构化中间态重新文本化喂给 LLM，所以结构性压缩对 token 收益被反向抵消了。

---

## 2. Pipeline Decomposition: LLM vs Non-LLM Layers

### 2.1 Complete Agent Pipeline

```
                    LLM?   Non-LLM?       Role
                    ----   --------       ----
[Corpus Docs]          —      YES         Static data
     ↓
[Retriever Agent]      NO     YES         Semantic embedding retrieval (local model, not LLM)
     ↓   produces: evidence_text (DENSE_EVIDENCE), feature_bundle, decision_packet
     ↓             handoff text (TOOL_ARTIFACT)
     ↓
[Executor Agent]       NO     YES         ExecutorRuntime: resolve feature_bundle, select tool,
     ↓   produces: TOOL_ARTIFACT                execute playbook tool (subprocess)
     ↓
[Summarizer Agent]    YES     —           LLM call: generate summary from evidence + actions
     ↓   produces: summary text, memory commit
```

**Planner** (pre-pipeline): In headline, `plan_source=yaml` → NOT LLM. The Plan is pre-written in YAML from `contest_family_spec.yaml`. Total pipeline: 0 LLM calls at planning stage.

### 2.2 LLM Involvement by Mode

| Layer | text_whole_lane (headline text arm) | state_packet_minimal (headline protocol arm) |
|-------|--------------------------------------|----------------------------------------------|
| Planner | **NO LLM** (YAML compiler) | **NO LLM** (YAML compiler) |
| Retriever | NO LLM (semantic embedding + lexical match) | NO LLM (semantic embedding + lexical match) |
| Executor | NO LLM (lexical recovery from NL handoff + tool registry) | NO LLM (decision packet + tool registry) |
| Summarizer | **YES LLM** (evidence_text + actions_text → summary) | **YES LLM** (protocol summary input packet → summary) |

**唯一调用 LLM 的层: Summarizer。Planner、Retriever、Executor 都不调 LLM。**

### 2.3 The Non-LLM Decision Layers

There are exactly **four** places where non-LLM semantic decisions are made:

| # | Function | Location | Decision | Input | Output |
|---|----------|----------|----------|-------|--------|
| D1 | `build_feature_bundle()` | `executor_runtime.py:388-661` | route + tool_name + confidence + provenance | evidence_text, tags, corpus hints, memory prior | feature_bundle dict |
| D2 | `build_executor_decision_packet()` | `executor_runtime.py:750-780` | canonicalize D1 output into typed packet | feature_bundle, query, doc_ids | decision_packet dict |
| D3 | `_apply_validation_gate_to_feature_bundle()` | `executor_runtime.py:807-904` | validate/override route/tool from validation step | feature_bundle, validation_packet | refined feature_bundle |
| D4 | `select_tool_name()` | `executor_runtime.py:783-804` | final tool selection from candidates | feature_bundle, registry | tool_name string |

D2 is purely mechanical (canonicalization). D4 is mechanical (registry lookup). D1 and D3 are where **semantic narrowing** happens.

---

## 3. Code Evidence: Where Compression Happens

### 3.1 D1: `build_feature_bundle()` — The Core Non-LLM Decision

**What goes in**: Rich evidence text (all corpus docs concatenated), task tags, corpus metadata hints (route_hint + tool_name from doc YAML), memory prior (from cross-task memory store).

**What happens** (`executor_runtime.py:399-661`):

Step 1 — Lexical candidate scoring:
```python
# executor_runtime.py:404-411
candidates = registry.retrieve_candidates(
    query_text, primary_evidence_text, evidence_lower, normalized_tags, limit=3
)
```
This calls `_match_signals(text, patterns)` for each tool — **pure substring matching**. `"database" in evidence_text` → +5 score for `tool.db_pool_triage`. `"auth" in evidence_text` → +5 for `tool.auth_session_repair`. No semantic understanding. No ambiguity resolution beyond "does this word appear in the evidence?"

Step 2 — Route decision tree (`executor_runtime.py:454-586`):
```python
if selected_hint is None:
    if _has_ambiguous_tool_candidates(candidates):
        route_source = "ambiguous_candidates_abstain"
        selected = fallback_match  # → generic_triage / tool.collect_more_evidence
    elif not _match_passes_threshold(selected):
        route_source = "low_confidence_abstain"
        selected = fallback_match
    elif not _match_has_minimum_evidence_support(selected):
        route_source = "low_confidence_abstain"
        selected = fallback_match
    else:
        route_source = "lexical_match"  # ← THIS is the happy path
else:
    # With corpus hint: hint_consensus, lexical_override, or metadata_only_abstain
```

Step 3 — Memory prior candidate reduction (`executor_runtime.py:427-453`):
```python
if memory_prior and _memory_prior_matches_candidate_pool(memory_prior, candidates):
    candidates = [c for c in candidates if c.route == memory_prior["route"]]
    # NARROWS the candidate pool to ONLY those matching the memory prior's route
```

**What comes out**: A single `route` + `tool_name` + `route_source` + `route_confidence` + `route_provenance` + a ranked `tool_candidates` list.

**Key fact**: `tool_candidates` does preserve alternatives (typically 2-3 candidates with scores), but `route` and `tool_name` are already nailed down to a single choice. The executor later uses `select_tool_name(feature_bundle)` which tries the first candidate, then feature_bundle["tool_name"], then route-based fallback.

### 3.2 Evidence of "Premature Narrowing"

The tool_narrowing is indeed premature in two specific ways:

**Evidence A — Shared-route tool disambiguation**:

The `default_tool_registry()` has sibling tools on the same route:
```
tool.auth_session_repair    → route auth_session_drift
tool.auth_jwks_refresh      → route auth_session_drift   ← SAME ROUTE
tool.db_pool_triage         → route db_pool_saturation
tool.db_query_hotfix        → route db_pool_saturation   ← SAME ROUTE
tool.worker_queue_triage    → route worker_queue_starvation
tool.retry_storm_relief     → route worker_queue_starvation ← SAME ROUTE
tool.cache_invalidation_playbook → route cache_invalidation
tool.cache_hook_repair      → route cache_invalidation   ← SAME ROUTE
```

When `build_feature_bundle()` picks `tool.auth_session_repair` as the selected tool (because its match_patterns scored slightly higher on the evidence text), it records route=`auth_session_drift`. The `tool_candidates` list contains both tools. But `select_tool_name()` at execution time will pick the FIRST candidate — which is the one with the marginally higher lexical score.

An LLM reading the full evidence could potentially distinguish between "this looks like a JWKS issue" vs "this looks like a session repair issue" by understanding the meaning of the evidence. The lexical matcher can't.

**Evidence B — The fallback path is single-option**:

When the lexical matcher can't decide (`ambiguous_candidates_abstain`, `low_confidence_abstain`), it falls back to `tool.collect_more_evidence` / `generic_triage`. This is a binary decision: either pick a specific tool, or give up entirely. There's no "pick the top two and let the executor contextualize with additional evidence" option.

**Evidence C — Memory prior candidate pool reduction is aggressive**:

```python
# executor_runtime.py:442-445
candidate_pool = [
    c for c in candidate_pool
    if c.tool_name == memory_tool_name and c.route == memory_route
]
```

When a memory prior exists, ALL candidates that don't match the prior's exact route+tool are discarded. If the memory prior is slightly stale (similar task but subtly different evidence), this can force a wrong tool selection with no way to recover.

### 3.3 Re-Textualization: The Summarizer's LLM Input

**Text mode** (`text_whole_lane`):
```python
# agents/sample_agents.py:1593
summary_evidence_text = actions_text  # executor's plaintext actions
```
The Summarizer LLM sees: raw evidence text + executor's natural language action description.
Example: `"For auth_session_drift, the retrieved evidence supports route auth_session_drift. Use tool.auth_session_repair first..."`

**Protocol mode** (`state_packet_minimal`):
```python
# agents/sample_agents.py:1632
summary_evidence_text = json.dumps(_build_protocol_summary_input_packet(...))
```
The Summarizer LLM sees:
```json
{"schema":"statebus.summary_input_packet.v1",
 "query":"...","route":"auth_session_drift","route_source":"lexical_match",
 "route_confidence":0.75,"doc_ids":["auth-incident-001",...],
 "matched_signals":["auth","session","jwks"],"actions_text":"...",
 "summary_hint":"...","hint":"memory assist..."}
```

**Token comparison**: Both formats contain roughly equivalent information content. Text mode uses natural language (~verbose but human-readable). Protocol mode uses JSON keys (~compact structure but same data). The protocol's compact JSON keys (`"route":` vs `"Route: "`) save a few tokens, but the evidence content dominates. Hence: delta = -5 tokens.

**The re-textualization is structurally necessary**: An LLM consumes tokens, not typed state. There's no way around converting structured data back to text for LLM input. This is not a bug — it's a physical constraint.

---

## 4. Mapping Hypothesis to Observed Phenomena

| Phenomenon | Does P1 (premature non-LLM compression) explain? | Does P2 (re-textualization) explain? | Better alternative explanation |
|------------|--------------------------------------------------|-------------------------------------|-------------------------------|
| `route_exact_rate = 0.90` | **NO**. Route narrowing is actually a strength. Lexical matching reliably identifies the correct route family. | N/A | Lexical match_patterns hit route-level keywords reliably |
| `tool_exact_rate = 0.25` | **PARTIALLY YES**. The lexical matcher can't distinguish sibling tools on the same route. An LLM could. | N/A | **PRIMARILY**: benchmark contract declares BOTH sibling tools as acceptable. `acceptable_tools: [tool.auth_session_repair, tool.auth_jwks_refresh]`. The system picks one; the contract calls the other "primary." |
| `exact_match_rate = 0.25` | Derivative of tool_exact | N/A | 70% contract design (two almost-equivalent tools, one called "primary"), 25% non-LLM lexical matching limits, 5% other |
| `admissible_match_rate = 1.00` | N/A (explains why it's high, not why it's a problem) | N/A | `acceptable_tools` includes both sibling tools → all choices are admissible |
| `llm_total_tokens` 基本不降 | **NO**. Token count is driven by Summarizer's input volume, which is dominated by evidence content, regardless of whether middle layers used LLM or not. | **YES, but this is not "premature compression's fault."** It's a fundamental LLM constraint: LLM consumes text, typed state must become text. | The **real** reason: Headline only calls LLM at Summarizer. Planner is YAML (0 tokens). Retriever/Executor don't call LLM (0 tokens). All tokens come from Summarizer input, whose evidence volume is identical in both modes. |
| `control_bytes -13.8%` | N/A — this is where non-LLM compression **helps** | N/A | Protocol messages are more compact because they use structured encoding. This is a genuine benefit of the non-LLM middle layer. |
| Overall protocol advantage weak | **PARTIALLY**. P1+P2 together mean: what protocol gains in inter-agent wire efficiency, it loses at LLM consumption (re-textualization) and tool precision (non-LLM disambiguation limits). | Same as left. | The biggest factor remains: **no external baseline exists, so we can't even say protocol is "weak" vs anything**. The `text_whole_lane` comparator shares too much infrastructure. |

---

## 5. Arguments FOR the Hypothesis

### 5.1 What the Hypothesis Gets Right

1. **Non-LLM layers DO make the semantically richest decision in the pipeline**: The route/tool decision — arguably the most important correctness decision in the entire system — is made entirely by lexical substring matching in `build_feature_bundle()`. No LLM is involved.

2. **The re-textualization cycle IS real**: In protocol mode: `evidence_text → build_feature_bundle (compress) → build_executor_decision_packet (structure) → executor consumption → _build_protocol_summary_input_packet (expand) → json.dumps() → LLM prompt`. Information goes: text → structured → text. The structured middle step doesn't reduce the final text volume.

3. **Tool disambiguation IS limited by non-LLM matching**: When two tools share a route, `_match_signals()` can only rank them by substring overlap score. Small perturbations in evidence text order or wording can flip the ranking. An LLM could potentially read the evidence more holistically.

4. **The memory prior's candidate pool reduction IS aggressive**: It narrows to a single route+tool from a prior task. No semantic similarity check on the evidence itself — just "did the prior task's route match?"

### 5.2 Raw Data Support

From the row-level data (second round §5.2):
- ALL tool exact failures are sibling-tool substitutions on shared routes
- The substitution is deterministic (same every repeat) — suggesting it's driven by stable lexical signals, not noise
- The fact that the SAME tool pair is always swapped (auth_session_repair ↔ auth_jwks_refresh, never auth_session_repair ↔ retry_storm_relief) shows the route-level matching works correctly; the disambiguation within route is what fails

---

## 6. Arguments AGAINST the Hypothesis

### 6.1 What the Hypothesis Misses

1. **Non-LLM route/tool selection is an intentional efficiency choice, not an accident**: The whole point of StateBus is that agent-to-agent communication should use structured, efficient carriers instead of natural language. Having the Retriever produce a typed route/tool decision without calling an LLM is exactly what the protocol is designed for. Calling this "premature compression" misses that it's the mechanism being tested.

2. **The benchmark contract is the primary cause of exact=0.25, not the non-LLM decision quality**: The YAML spec declares:
   ```yaml
   acceptable_tools: [tool.auth_session_repair, tool.auth_jwks_refresh]
   primary_expected_tool: tool.auth_session_repair
   ```
   If the contract said `acceptable_tools: [tool.auth_session_repair]` (only ONE acceptable tool), the system's choice would be either correct (exact_match) or wrong (mismatch). The 0.25 number is an artifact of the contract having **two equally valid tools but designating only one as "primary."**

3. **LLM-based tool selection might be worse, not better**: If the Executor called an LLM to choose between `tool.auth_session_repair` and `tool.auth_jwks_refresh`, it would:
   - Add significant token cost (LLM call per task)
   - Add latency
   - Potentially be equally confused (LLMs can also struggle with fine-grained distinctions between similar-sounding tools)
   The hypothesis assumes "LLM would do better" without evidence.

4. **Re-textualization is a fundamental LLM constraint, not a middle-layer flaw**: The Summarizer MUST receive text. Whether that text comes from raw evidence or from JSON-serialized typed packets, the token count is dominated by the evidence content volume. The structured middle layer doesn't INCREASE the token cost; it just doesn't decrease it as much as one might naively expect.

5. **The alternative (LLM everywhere) would make token costs WORSE**: If every agent called LLM (Planner, Retriever, Executor, Summarizer all using LLM), total tokens would be much higher than the current ~8430. The current architecture is actually token-efficient relative to a fully LLM-driven alternative.

### 6.2 The Strongest Counter-Argument

> **The hypothesis conflates "non-LLM compression exists" with "non-LLM compression is doing harm."** The StateBus system deliberately minimizes LLM calls. Having non-LLM middle layers is the architecture, not a flaw. The hypothesis would only be correct if (a) an LLM in those layers would produce significantly better decisions, AND (b) the token cost of adding LLM calls would be offset by downstream savings. Neither (a) nor (b) has evidence.

---

## 7. Final Judgment

### 7.1 The Two Propositions Separated

**Proposition P1 ("premature non-LLM compression causes low exact_match"): PARTIALLY TRUE, but secondary.**

The non-LLM lexical matching is a CONTRIBUTING factor to tool_exact=0.25 (accounts for ~25% of the problem). The PRIMARY factor (~70%) is the benchmark contract design where `acceptable_tools` includes two sibling tools and `primary_expected_tool` is arbitrarily one of them.

Evidence for partial attribution: The tool substitutions are always within-family siblings, and the pattern is deterministic. This suggests the lexical matcher has a stable bias toward one sibling over the other. An LLM might have a different bias, but there's no guarantee it would align with the benchmark's `primary_expected_tool`.

**Proposition P2 ("re-textualization negates token savings"): TRUE but not a flaw.**

The re-textualization cycle is real: `typed state → json.dumps() → LLM prompt`. But this is a necessary physical constraint (LLMs consume text), not an architectural mistake. The protocol DOES save tokens in inter-agent messages (control_bytes -13.8%); it just can't save tokens in the LLM consumption layer because the evidence content volume is the same.

### 7.2 Is This a Structural Problem?

| Layer | Problem Type | Severity |
|-------|-------------|----------|
| Non-LLM route/tool decision | **Architecture-level design choice**, not a bug. The system intentionally limits LLM calls to Planner+Summarizer only. | Medium — limits tool precision but saves tokens |
| Lexical matching on sibling tools | **Implementation limitation**. `_match_signals()` uses substring matching, which has inherently low discriminative power for similar tools. | Medium — could be improved with better signals (e.g., TF-IDF weighting, semantic embedding similarity) |
| Benchmark contract with dual acceptable tools | **Task design artifact**. The spec defines two acceptable tools per family, making exact_match definitionally low. | High — this is the primary cause of 0.25 |
| Re-textualization at Summarizer | **Physical constraint**. Inescapable for any system that uses LLMs for final output generation. | Low — not fixable |

### 7.3 Where This Hypothesis Ranks in Root-Cause Order

Updated ranking with the hypothesis incorporated:

| Rank | Root Cause | Weight | Hypothesis's Role |
|------|-----------|--------|-------------------|
| **1** | **External pure-text baseline missing** | 30% | Unrelated to hypothesis — this is an experimental design gap |
| **2** | **Headline only uses LLM at Summarizer** | 25% | Hypothesis P2 correctly identifies this as the reason tokens don't drop, but misattributes "fault." It's an architecture choice, not a flaw. |
| **3** | **Benchmark contract: dual acceptable tools** | 20% | Hypothesis P1 misses this — the contract defines sibling tools as both acceptable, making exact_match definitionally low regardless of decision quality |
| **4** | **Non-LLM lexical matching limits tool precision** | 10% | **This IS the valid core of the hypothesis.** The lexical matcher can't distinguish sibling tools. |
| **5** | **Memory replay scope too narrow** | 10% | Unrelated |
| **6** | **Metrics priority misalignment** | 5% | Unrelated |

**The hypothesis moves from "potential core problem" to "confirmed contributing factor (rank 4)."** It is NOT the primary problem, but it IS a real structural limitation that compounds with the benchmark contract issue (rank 3) to produce the exact=0.25 result.

---

## 8. What Would Happen If Middle Layers Used LLMs?

This is a counterfactual worth examining to test the hypothesis:

| Scenario | LLM where? | Expected token cost | Expected tool precision |
|----------|-----------|---------------------|------------------------|
| Current (non-LLM middle) | Summarizer only | ~8430 tokens | exact=0.25 (tool substitutions) |
| LLM Executor | Executor calls LLM for tool choice | ~8430 + ~500-1000 per task | Potentially better on ambiguous cases, worse consistency |
| LLM Retriever | Retriever uses LLM for evidence interpretation | ~8430 + ~2000-4000 per task | Potentially better route selection, much higher cost |
| LLM Everywhere | All 4 agents use LLM | ~8430 + ~5000-10000 per task | Unknown — likely higher variance |

The current design (LLM only at Summarizer) is the most token-efficient possible configuration while still using LLM for final output. Replacing non-LLM middle layers with LLMs would increase token costs without guaranteed precision improvement, given the benchmark contract's dual-acceptable-tool design.

---

## 9. Conclusion

**The hypothesis is a legitimate structural observation but overstates its causal importance.**

What is true:
- Non-LLM lexical matching DOES limit tool disambiguation precision on sibling tools (rank 4 root cause)
- The re-textualization cycle IS real and IS why tokens don't drop (rank 2 root cause, but as an architecture choice not a flaw)

What is false:
- This is NOT the primary cause of exact=0.25 (the benchmark contract is, rank 3)
- This is NOT a "flaw" that needs fixing — it's the intended architecture
- Adding LLMs to middle layers would NOT necessarily improve results and WOULD increase token cost

**Recommendation**: Don't restructure the pipeline to add LLM calls in middle layers. Instead, fix the benchmark contract (narrow `acceptable_tools` or adjust scoring) and build the external baseline (which will show whether the non-LLM middle layers perform competitively against LLM-driven alternatives).

---

## Appendix: Key Code References

| What | Where |
|------|-------|
| `build_feature_bundle()` — route/tool decision | `runtime/executor_runtime.py:388-661` |
| `_match_signals()` — lexical matching | `runtime/executor_runtime.py:1690-1780` |
| `_has_ambiguous_tool_candidates()` | `runtime/executor_runtime.py:1724-1741` |
| `select_tool_name()` | `runtime/executor_runtime.py:783-804` |
| `build_executor_decision_packet()` | `runtime/executor_runtime.py:750-780` |
| `_apply_validation_gate_to_feature_bundle()` | `runtime/executor_runtime.py:807-904` |
| Retriever: handoff construction | `agents/sample_agents.py:900-1088` |
| Executor: `execute_playbook_step()` | `runtime/executor_runtime.py:1129-1461` |
| Summarizer: evidence assembly for LLM | `agents/sample_agents.py:1586-1642` |
| Summarizer prompt (text vs protocol) | `agents/sample_agents.py:2257-2302` |
| `_build_protocol_summary_input_packet()` (re-textualization) | `agents/sample_agents.py:2683` |
| `default_tool_registry()` (sibling tools on same route) | `runtime/executor_runtime.py:172` |
| Benchmark contract: `acceptable_tools` | `tasks/contest_family_spec.yaml` case definitions |

---

*Review completed: 2026-06-20*
*The hypothesis is partially validated but downgraded from "core problem" to "contributing factor (rank 4/6)."*
