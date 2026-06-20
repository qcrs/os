# StateBus 第二轮深度追问诊断报告

**日期**: 2026-06-20
**审稿人角色**: 外部独立评审 / 严格实验审稿人
**范围**: 代码级深挖 + 指标定义层 + 行级 artifact 分析
**前序文档**: `docs/analysis/statebus_independent_full_repo_review_20260620.md`

---

## 1. Scope of Follow-up

第一轮给出了方向性判断:
- Comparator 不是 external pure-text baseline
- token 没有下降
- exact_match_rate = 0.25 是严重问题
- support/audit 不能替 headline 抬轿

但这些仍然是"结论层"判断。本轮目标是把每个结论继续往下挖到 **代码路径、行级数据、指标定义**，明确回答:

> 这些坏结果到底是怎么在代码里发生的？是 benchmark object 限制了结论，还是实现根本没有兑现方法承诺？哪些是 measurement artifact，哪些是真的方法缺陷？

本轮新增证据:
- `benchmark_results.json` 行级数据 (400 rows, frozen headline)
- `eval/runner.py:_build_case_contract_audit` 完整逻辑
- `agents/sample_agents.py` SummarizerAgent prompt 构造 (text vs protocol)
- `runtime/orchestrator.py` 指标累积代码路径
- `runtime/llm.py` 完整 prompt 构造
- `eval/open_runner.py` + `eval/text_open_baseline.py` external baseline 实现
- `tasks/contest_family_spec.yaml` case contract 定义
- 2026-06-19 full API repeat=1 全部 10 surface 报告

---

## 2. What the First Review Already Established (不重复)

- StateBus 工程上是一个认真的、机制完整的 prototype
- 但赛题优势证据不足，估分 ~44-54/100
- 主要缺口: external baseline 缺失、token 不降、exact=0.25、memory 过窄
- 根因排名: Comparator Design > Token Drop > exact_match

---

## 3. Deep Question 1: External Pure-Text Baseline Contract

### 3.1 从赛题要求出发，合格的 pure-text baseline 必须满足什么？

赛题原文关键句:
> "系统需同时支持'纯文本协作模式'和'结构化协议协作模式'，并在相同任务条件下完成可复现实验对比"

拆解为硬约束:
1. **纯文本协作模式**: agent 间以自然语言 JSON/text 作为通信媒介，不使用 typed state / StateRef / protocol frames
2. **结构化协议协作模式**: agent 间使用 structured protocol (当前 StateBus protocol lane)
3. **相同任务条件**: 同一任务定义、同一 corpus、同一 LLM model、同一评测标准
4. **可复现实验对比**: 结果可被独立复现

### 3.2 三种候选 Baseline 定义

#### 定义 A: 同 Runtime, 同 Tool Registry, 同 Corpus, 只改 carrier

这是当前 `text_whole_lane` 的定义:
- 运行在 StateBus 同一 LangGraph DAG 上
- 共享 ToolRegistry、lexical match、feature bundle builder
- 差异只在 handoff format: whole-lane text vs typed state packet

**优点**: 最 controlled comparison，variable isolation 最好
**缺点**: 不是赛题要的 "纯文本协作 vs 结构化协议" 对比，而是 "同一 runtime 内两种 handoff 风格" 的对比。text arm 受益于 StateBus 的 lexcial recovery path、tool registry 等结构化辅助

**代码证据**: `executor_runtime.py:1857-1923` (`_feature_bundle_from_text_whole_lane_handoff`) 证明 text executor 有完整的结构化恢复能力

#### 定义 B: 完全独立于 StateBus runtime 的传统 pure-text multi-agent system

例如:
- 简单的 ReAct-style LLM loop (plan → act → observe → plan → summarize)
- 或简单的 chain: `LLM.plan(task) → LLM.execute(plan, evidence) → LLM.summarize(results)`
- 不使用 StateBus 的任何 runtime infrastructure

**优点**: 赛题真正需要的对比。证明结构化 protocol 比传统方法好
**缺点**: 需要重新实现一整套 text baseline；如果做得太简单会被批评"baseline 太弱"，如果做得太复杂会变成另一个工程

#### 定义 C: Hybrid — 独立 LLM calls, 但共享 corpus 与 scoring

- LLM 完全独立 (有自己的 planner/summarizer prompts)
- 共享同一 corpus 和 task definition
- 不使用 StateBus 的 ToolRegistry/lexical match/feature bundle
- 但可以使用相同的 playbook tools (作为函数调用)

**优点**: 务实折中。保持了 LLM agent 的独立性同时控制变量
**缺点**: 边界难划清——"不使用 feature bundle" vs "使用相同的 corpus 意味着相同的 retrieval 质量"

### 3.3 最适合赛题 formal comparator 的定义

**推荐: Definition B-Minimal (最小独立 pure-text baseline)**

具体 contract:
1. **LLM model**: 与 headline 相同 (`deepseek-v4-flash`)
2. **Corpus**: 与 headline 相同 (相同 corpus docs)
3. **Task definition**: 与 headline 相同 (相同 queries, summary contracts, expected answers)
4. **Agent roles**: 最小 2-3 个 LLM agent:
   - `Planner`: LLM 生成 natural language plan (不预写 YAML)
   - `Executor/Retriever`: LLM 选择 tool 并解释 (或者固定 tool invocation pattern)
   - `Summarizer`: LLM 生成 final summary
5. **Inter-agent communication**: 纯 natural language text (JSON with natural language values, or plain text blocks)
6. **禁止使用**: StateRef, Feature Bundle, ToolRegistry lexical match, StateBus protocol frames, LangGraph DAG, memory replay
7. **允许使用**: 相同 playbook tools (作为函数调用), 相同 corpus docs (作为检索对象)
8. **Metric alignment**: 统计 LLM tokens, message bytes, task time, route/tool correctness — 与 headline 相同口径

### 3.4 当前 `pure_text_open_live_api_slice_v1` 为什么还不够？

| 维度 | 现状 | 缺口 |
|------|------|------|
| 规模 | 8 tasks (从 headline 40 中选取) | 不足。至少需要与 headline 同规模 |
| Contract | 从 headline text rows 中 slice 出来 | 仍然继承 StateBus task contract (acceptable_routes, acceptable_tools 来自 spec) |
| Formality | `audit_only` evidence tier | 不能作为 formal comparator |
| 与 headline 对齐 | 选择了 headline text rows | 但 measurement framework 不同 (open_runner vs runner) |
| Baseline 实现 | `ExternalTextOpenRuntime` 的 live_api_text_only path | 这个 runtime 仍然用 lexical playbook 做 fallback，不够"纯" |

**最严重的问题**: `ExternalTextOpenRuntime._run_live_text_task()` (`text_open_baseline.py:207`) 在 live API mode 下仍然有 `_sanitize_route_tool()` fallback。虽然可能不是主路径，但只要 fallback 存在，就不能严格声称它是纯 LLM 基线。

### 3.5 最小充分 Baseline Contract

```text
Name: external_pure_text_strict_baseline_v1
Type: formal_comparator (升格自 audit_only)
Evidence tier: formal_headline_comparator

Hard constraints:
1. Must use real LLM for ALL agent decisions (planner + executor + summarizer)
2. Must NOT import or use any StateBus runtime module (orchestrator, contracts, feature_bundle, langgraph_adapter, reuse_contract)
3. May share: corpus docs, playbook tools (as standalone functions), task queries, expected answers, LLM model/config
4. Must run on same hardware with same LLM model
5. Must measure: llm_total_tokens, message_count, task_ms, route_exact_rate, tool_exact_rate, exact_match_rate, admissible_match_rate
6. Must use same case contract definitions from contest_family_spec.yaml for scoring
7. Scale: all 20 text-mode tasks from headline (or all 40 if dual-mode needed)
8. Repeat: >=10 (matching headline repeat gate)

Reading contract:
- This is THE external pure-text comparator against which StateBus protocol mode is judged.
- It is NOT run inside StateBus runtime.
- Its results directly answer: does structured protocol reduce overhead vs traditional pure-text collaboration?
```

---

## 4. Deep Question 2: Why LLM Tokens Did Not Drop — Code-Level Root-Cause Chain

### 4.1 Who calls LLM in the headline?

从 `agents/sample_agents.py` 和 `runtime/orchestrator.py`:

| Agent | Calls LLM? | headline (plan_source=yaml) | Token contribution |
|-------|-----------|----------------------------|-------------------|
| Planner | Yes (if LLM plan) | **NO** (YAML contract compiler) | 0 both sides |
| Retriever | **NO** | Embedding only (no LLM) | 0 both sides |
| Executor | **NO** | Tool registry only (no LLM) | 0 both sides |
| Validator | **NO** | Contract check only (no LLM) | 0 both sides |
| Summarizer | **YES** | Always calls LLM | **ALL tokens** |

**关键发现**: 在 headline 中，**只有 Summarizer 调用 LLM**。Planner 使用 YAML plan source，不是 LLM。

从 `benchmark_compare.csv` aggregate row 验证:
```
text_llm_total_tokens = 8435.9
protocol_llm_total_tokens = 8430.9
delta = -5.0
text_planner_total_tokens = 0.0
protocol_planner_total_tokens = 0.0
text_summarizer_total_tokens = 8435.9
protocol_summarizer_total_tokens = 8430.9
```

Planner tokens 确实是 0。100% 的 LLM tokens 来自 Summarizer。

### 4.2 What does the Summarizer receive in each mode?

来自 `agents/sample_agents.py:1586-1642`:

```python
summary_evidence_text = evidence_text  # default: raw evidence text

if transfer_strategy == "text_whole_lane":
    summary_evidence_text = actions_text          # text: raw actions text
elif mode != "text" and summary_contract == "protocol_handoff_audit":
    summary_evidence_text = _build_protocol_summary_handoff(...)   # human-readable handoff string
elif mode != "text" and transfer_strategy != "text_whole_lane":
    summary_evidence_text = json.dumps(
        _build_protocol_summary_input_packet(...)  # JSON of typed packet
    )
```

然后 `summary_evidence_text` 被放入 prompt payload:
```python
summary_input = {
    ...
    "evidence_text": summary_evidence_text,   # <-- THIS is what Summarizer LLM sees
    ...
}
```

### 4.3 The Prompt Construction Comparison

来自 `agents/sample_agents.py:_summarizer_messages()` (lines 2257-2302):

**Text mode prompt:**
```
System: "You are the StateBus Summarizer in a text-only collaboration baseline.
         You are receiving a natural language handoff from prior agents
         instead of a structured packet. Output strict JSON only.
         Return an object with summary, confidence, tags, and reusable_steps."
User:   "Summarizer handoff for a text-only multi-agent workflow.
         Task ID: {id}
         Task theme: {theme}
         Tags: {tags}
         Reusable steps: {reusable_steps}
         Summary hint: {hint}
         Evidence note: {evidence_text}     <-- RAW EVIDENCE
         Playbook actions: {actions_text}   <-- RAW ACTIONS"
```

**Protocol mode prompt:**
```
System: "You are the StateBus Summarizer. Output JSON only.
         Return {\"s\":\"summary\",\"c\":0.95,\"t\":[...],\"r\":[...]}"
User:   <sb-summary-v1>
         {"h":"{hint}",
          "e":"{evidence_text}",           <-- SAME EVIDENCE (re-textualized)
          "a":"{actions_text}",            <-- SAME ACTIONS (re-textualized)
          "t":[...],
          "r":[...]}
        </sb-summary-v1>
```

### 4.4 The Root-Cause Chain: Why Tokens Don't Drop

```
Step 1: In headline, Planner uses YAML (no LLM call)
    → 0 planner tokens in both modes
    → No token savings possible from "structured plan handoff"

Step 2: Retriever/Executor/Validator don't call LLM
    → 0 tokens in both modes
    → No token savings possible here either

Step 3: Summarizer MUST call LLM
    → ALL tokens come from Summarizer

Step 4: Summarizer MUST receive evidence as TEXT
    → LLM tokenizer operates on text, not on typed state
    → Protocol-side typed state MUST be re-expanded into text for LLM consumption
    → The _build_protocol_summary_input_packet() converts typed state → JSON dict → json.dumps() → text string

Step 5: The content VOLUME is identical
    → Text mode: raw evidence_text + raw actions_text → ~same number of tokens
    → Protocol mode: json.dumps(packet) → same evidence, different format → ~same number of tokens
    → Protocol format is MORE compact in JSON keys but evidence content dominates

Step 6: System prompt difference is negligible
    → Text system prompt: ~80 words
    → Protocol system prompt: ~30 words
    → Difference: ~50 words ≈ ~30-40 tokens
    → But aggregate delta is only -5 tokens total over 40 tasks → ~0.1 tokens per task

Result: llm_total_tokens delta = -5 (negligible, zero for all practical purposes)
```

### 4.5 Root-Cause Attribution

| 层 | 是否影响 token 不降 | 说明 |
|----|---------------------|------|
| Benchmark object | **YES (primary)** | Headline 只用 YAML Planner → Planner 不产生 LLM tokens → protocol 的 "structured plan handoff" 优势无处体现 |
| Prompt 设计 | **MINOR** | Protocol prompt 确实更紧凑 (~50 words less in system prompt)，但影响太小 |
| Protocol 设计 | **PARTIAL** | Protocol 确实结构化 agent 间 carrier，但 LLM 消费点必须把内容重新展开为文本。这不是 protocol 的 bug，而是 LLM 本质决定的: LLM 只能消费文本 |
| Executor contract | **NO** | Executor 不调 LLM |
| 方法本身 | **FUNDAMENTAL CONSTRAINT** | 只要 Summarizer 用 LLM 生成文本摘要，LLM 就必须接收文本输入。Protocol 的结构化收益停止在"agent-to-agent wire"这一层，不延伸至"agent-to-LLM"这一层 |

### 4.6 可证伪的判断

> **"StateBus protocol 降低 LLM token 开销"这个主张在当前 headline 架构下不可能成立，因为 LLM 只被 Summarizer 调用，而 Summarizer 无论收到 typed state 还是 natural language handoff，都必须将其展开为等效文本才能送入 LLM。**

这个判断可被证伪的条件: 如果 headline 改用了 LLM Planner + protocol 的 structured plan 可以减少 Planner prompt 长度 → Planner tokens 会出现差异。

---

## 5. Deep Question 3: Why exact_match Stayed at 0.25 — Row-Level Decomposition

### 5.1 The Data

来自 `benchmark_results.json` frozen headline (400 rows: 40 tasks × 10 repeats):

| 指标 | 值 |
|------|-----|
| Total rows | 400 |
| exact_match=True | 100 (25%) |
| exact_match=False | 300 (75%) |
| route_exact=True | 400 (100%) |
| tool_exact=True | 100 (25%) |
| admissible_match=True | 400 (100%) |
| correct_family | 400 (100%) |

**关键发现: route_exact 永远是 True。每个 mismatch 都是 tool substitution。**

### 5.2 The Tool Substitution Pattern

| Family | Case Type | Primary Expected Tool | Observed Tool | Rows |
|--------|-----------|----------------------|---------------|------|
| auth_session_drift | clean | `tool.auth_session_repair` | `tool.auth_jwks_refresh` | 30 |
| auth_session_drift | distractor | `tool.auth_session_repair` | `tool.auth_jwks_refresh` | 30 |
| auth_session_drift | ambiguous | `tool.auth_session_repair` | `tool.auth_jwks_refresh` | 30 |
| worker_queue_starvation | clean | `tool.worker_queue_triage` | `tool.retry_storm_relief` | 40 |
| worker_queue_starvation | distractor | `tool.worker_queue_triage` | `tool.retry_storm_relief` | 40 |
| worker_queue_starvation | ambiguous | `tool.worker_queue_triage` | `tool.collect_more_evidence` | 20 (abstention) |
| db_pool_saturation | clean | `tool.db_pool_triage` | `tool.db_query_hotfix` | 20 |
| db_pool_saturation | ambiguous | `tool.db_pool_triage` | `tool.collect_more_evidence` | 20 (abstention) |
| cache_invalidation | clean | `tool.cache_invalidation_playbook` | `tool.cache_hook_repair` | 30 |
| cache_invalidation | distractor | `tool.cache_invalidation_playbook` | `tool.cache_hook_repair` | 30 |

**Only 10 tasks get exact_match**: the 5 families' `replay_reusable` (S2) cases — these have `expected_reuse_mode=skip_execute` and the tool is pre-determined from replay.

### 5.3 Why Are These Tool Substitutions Happening?

两组工具之间的关系: 它们是 **family 内部的 sibling tools**。

来自 `contest_family_spec.yaml`:
```yaml
auth_rotation:
  cases:
    auth_session_drift_clean:
      acceptable_routes: [auth_session_drift, auth_certificate_rotation]
      acceptable_tools: [tool.auth_session_repair, tool.auth_jwks_refresh]
      primary_expected_route: auth_session_drift
      primary_expected_tool: tool.auth_session_repair
```

每个 family 的 4 个 cases (clean/distractor/ambiguous/reusable) 通常有:
- 2 个 `acceptable_routes` (primary + competing)
- 2-4 个 `acceptable_tools` (primary + alternative + maybe collect_more_evidence)
- `acceptable_tools` 中**同时包含** primary 和 alternative tool

系统在每个 case 上:
1. Route correctly (route_exact=True) → 走到了对的 family
2. 但在 family 内选了 alternative tool 而不是 primary tool

**这不是 correctness 失败。这是 benchmark contract 的设计问题: 当两张 tool 都在 acceptable 列表中时，系统的 tool disambiguation 信号不足以区分它们。**

### 5.4 Is This a Real Problem or a Measurement Artifact?

**判断: 主要是 benchmark contract 设计问题，次要才是 tool choice 精度问题。**

证据:
1. 替代是 **确定性的** — 在所有 10 次 repeat 中，每个 case 都选同一个替代 tool。如果是随机 LLM 噪声，应该会有 variance。
2. 替代 tool 在 **acceptable_tools 中** — 不是错误选择，只是不是 "primary"
3. 所有 observed tools 在语义上都是 **正确的 family tools** — `auth_session_repair ↔ auth_jwks_refresh` 都处理 auth；`worker_queue_triage ↔ retry_storm_relief` 都处理 worker queue
4. admissible_match = 1.00 — 从合同角度看，所有结果都是可接受的
5. 只在 S2 replay cases (where tool is skipped via replay) 出现 exact_match — 其他 case 的 tool 选择全部偏离 primary

**What this means for contest scoring**: 如果评审理解 `admissible_match_rate = 1.00` 意味着 "系统在所有任务上做出了可接受的路由和工具选择"，那 exact=0.25 就不是 correctness 危机。但如果评审只看 exact=0.25 这个数字，就会直接给 low score。

### 5.5 Impact of External Baseline

如果引入 external baseline:
- External baseline 的 exact_match 也会受相同 acceptable/primary tool 定义影响
- 如果 external baseline 的 tool exact 显著更高 → protocol 确实有 tool disambiguation 问题
- 如果 external baseline 的 tool exact 也同样低 → 这纯粹是 contract 定义问题 (acceptable_tools 里放了两张太相似的工具)

**关键**: 没有 external baseline，就无法区分 "benchmark contract 把门槛设太高" vs "系统的 tool choice 能力真的不够"。

---

## 6. Deep Question 4: Whether Communication Metrics Are Fair

### 6.1 Metric Measurement Code Paths

| 指标 | 代码位置 | 测量方式 |
|------|----------|----------|
| `control_bytes` | `orchestrator.py:emit()` → `session.record_message()` | `len(protocol_bytes(message))` — msgpack 序列化后的字节数 |
| `protocol_bytes` | 同上 | 同 control_bytes (别名，按 phase 分 setup vs steady) |
| `handoff_wire_bytes` | `orchestrator.py:record_transfer_inputs()` | StateRefLite protobuf wire encoding 的累计字节数 |
| `handoff_payload_bytes` | 同上 | `ref.length` — StatePool 中 payload 的实际字节数 (local) |
| `llm_total_tokens` | `orchestrator.py:record_llm_result()` | API response 的 `usage.total_tokens` |
| `message_count` | `orchestrator.py:emit()` | 每 emit 一次 +1 |
| `task_ms` | `orchestrator.py` session timer | wall-clock 计时 |

### 6.2 Asymmetry Analysis

| 开销类别 | text side 计入方式 | protocol side 计入方式 | 是否公平？ |
|----------|-------------------|----------------------|-----------|
| Agent-to-Agent 消息 | `control_bytes` (text_frame → msgpack) | `control_bytes` (protobuf → msgpack) | **公平** — 同一函数测量 |
| State transfer wire | 无 (text handoff 内联在消息中) | `handoff_wire_bytes` (StateRefLite protobuf) | **不对称** — protocol 额外计量了这一项 |
| State payload bytes | 无 (payload 也在消息中) | `handoff_payload_bytes` (local mmap size) | **不对称** — protocol 把 payload 开销拆出来了 |
| LLM prompt tokens | `llm_total_tokens` (Summarizer) | `llm_total_tokens` (Summarizer) | **公平** — 同一 API |
| Local state storage | 不计量 | 不计量 (mmap 是 local) | **公平** |
| Lexical match cost | 不计量 (CPU, 无 tokens) | 不计量 | **公平** |

### 6.3 Why control_bytes Down, tokens Flat, wire_bytes Up

```
                      text mode          protocol mode        delta
control_bytes         223741.2           192935.2             -30806  (-13.8%)
llm_total_tokens       8435.9             8430.9                 -5   (~0%)
handoff_wire_bytes      195.5              342.0               +146.5 (+75%)
message_count           292                302                  +10    (+3.4%)
```

**control_bytes 下降**: 原因明确 — protocol 的控制消息使用结构化 protobuf 帧，比 text 的 natural-language text_frame 更紧凑。这是 protocol 机制的直接收益。

**llm_total_tokens 持平**: 原因在 §4 已分析 — Summarizer LLM 需要消费的证据内容量在两种模式下相同，protocol 的 typed state 在进入 LLM 前被重新文本化。

**handoff_wire_bytes 上升**: protocol 需要额外传输 StateRefLite 指针。每个 StateRefLite 包含 `state_id, kind, length, blob_hash, channel, exact_replay_ready` 等字段的 protobuf encoding。text mode 不需要这些，因为 evidence 直接内联在 control message 中。

**message_count 上升**: protocol 额外发送 state ref 相关的消息 (FetchRequest/FetchResponse, StepResult with output_state_refs)。

### 6.4 当前 headline 中最接近赛题 "通信效率 25 分" 的指标

赛题原文:
> "统计并展示 Agent 间消息次数、文本通信 token 或字符开销"

对应指标:
- `message_count` (次数)
- `llm_total_tokens` / `text_chars` / `text_bytes` (token/字符)

**问题**: 
- `message_count`: protocol 反而更高 (+10 messages)
- `llm_total_tokens`: 持平 (无优势)
- `text_chars` / `text_bytes`: 主要是 control frame 的 text rendering — 这更多是内部表示，不是 agent 间真实通信

**最接近的 superiority 指标是 `control_bytes`**，但 control_bytes 测量的是 protobuf 消息体的 msgpack 序列化字节，**不是** 赛题评分员通常会关注的 "LLM token 开销"。

### 6.5 指标错位判断

| 指标 | 类型 | 当前值 | 赛题相关性 |
|------|------|--------|-----------|
| control_bytes -13.8% | 内部工程指标 | protocol better | 低 — 赛题评分为 "token/字符开销" |
| llm_total_tokens ~0% | **直接评分指标** | 持平 | **高 — 这是赛题要的** |
| handoff_wire_bytes +75% | 内部工程指标 | protocol worse | 中 — 表示状态传递有额外 wire cost |
| message_count +3.4% | 直接评分指标 | protocol worse | 高 |
| task_ms -2.6% | 直接评分指标 | protocol slightly better | 中 |

**结论**: 当前 headline 把 `control_bytes -13.8%` 作为主 evidence 来支撑通信效率主张，但赛题评分真正会看的 `llm_total_tokens` 没有下降，`message_count` 反而上升。**指标的优先级错位了**。

---

## 7. Deep Question 5: Whether Memory Claims Should Be Downgraded

### 7.1 What Memory/Replay Code Actually Supports

来自 `runtime/orchestrator.py` 和 `memory/store.py`:

触发条件 (replay eligibility):
1. Task 标记了 `runtime_reuse_contract = validated_replay` 或 `exact_replay`
2. MemoryStore 查询返回匹配的 prior StepResult
3. Query 匹配基于: task_theme, semantic similarity, route/evidence gate
4. 如果匹配: skip execute step, 返回 cached StepResult

在 headline 中:
- 只有 S2 (replay_reusable) cases 标记了 `expected_reuse_mode = skip_execute`
- 只有 10/40 tasks 有 replay eligibility
- 只跳过 execute step (不跳 retrieve, validate, or summarize)

### 7.2 What Has Been Proven

| 主张 | 证据 | 证据强度 |
|------|------|----------|
| 机制存在 | MemoryStore + replay gate 代码存在且可运行 | 强 |
| 受控 replay 有效 | S2 skip_execute 省了执行步骤 (reuse_gain=0.25/task) | 中 (范围窄) |
| 跨任务泛化记忆 | X | **无证据** |
| 长期记忆积累 | X | **无证据** |
| 不同 task theme 间的迁移 | X | **无证据** |
| 减少 token 开销 | 仅 S2 rows 跳过 executor → reduced task time, 不影响 LLM tokens (executor 不调 LLM) | 弱 |

### 7.3 与赛题要求的差距

赛题要求:
> "将任务执行过程中形成的摘要、证据、策略、经验等内容沉淀为可标识、可检索、可复用的共享记忆单元，使系统具备跨任务的知识积累和协同增强能力"

差距:
1. **跨任务**: 当前 replay 只在 S2 (same-family prior-dependent) tasks 中触发，不是 truly "跨" task
2. **知识积累**: 只有 step-skipping，没有 evidence enrichment, strategy refinement, or learning
3. **协同增强**: 没有 evidence of multi-agent collaborative memory use

### 7.4 是否应该降级？

**应该明确降级。** 当前最诚实的表述必须是:

> "StateBus 实现了共享记忆存储和检索模块，并在受控的有先验依赖的连续任务中证明了步骤跳过 (step-skipping) 的 replay 效果。尚未证明广义跨任务的记忆复用、长期知识积累或协同增强能力。"

在答辩中:
- **可以说**: "我们有 SQLite + FAISS 记忆模块，支持 assist 和 validated replay。在同家族有先验依赖的任务中，replay 跳过 executor 步骤，证明 replay 机制成立。"
- **不能说**: "共享记忆带来了显著的跨任务效率提升"、"记忆复用是系统的主要创新"、"系统具备持续学习和积累能力"

### 7.5 `memory_policy_controlled_v3` 的高分说明什么？

这个 surface 的 exact_match=1.00 来自:
- 只有 4 tasks (2 per memory policy, protocol-only)
- Tasks 预设了 exact_replay expected behavior
- 非常窄的受控 setting

它说明: **在充分预设条件下，replay mechanism 可以按预期工作**。不说明 memory 在开放条件下有 generalization 能力。

---

## 8. Rewritten Separation of Phenomena vs Root Causes vs Main Direction

### 8.1 Phenomena Layer (可被观测的症状)

| # | 现象 | 证据 | 严重度 |
|---|------|------|--------|
| P1 | LLM tokens 完全持平 | benchmark_compare.csv: delta=-5 | **致命** |
| P2 | exact_match_rate = 0.25 | 400 rows from headline | **严重** |
| P3 | handoff_wire_bytes higher on protocol | +75% vs text | 中等 |
| P4 | message_count higher on protocol | +3.4% vs text | 中等 |
| P5 | task_ms 优势极小 | -2.6% over 80 tasks | 中等 |
| P6 | external pure-text baseline 缺失 | pure_text_open_* 是 audit-only lexical stub | **致命** |
| P7 | memory replay 过窄 | 10/40 tasks, S2 only | 严重 |
| P8 | Planner 在 headline 中不是 LLM | plan_source=yaml, planner_tokens=0 | 严重 |

### 8.2 Root-Cause Layer (机制层面的原因)

| # | 根因 | 导致哪些现象 | 验证 |
|---|------|-------------|------|
| R1 | **headline 只让 Summarizer 调 LLM** | P1, P8 | `benchmark_compare.csv`: planner_tokens=0; `agents/sample_agents.py`: YAML contract compiler |
| R2 | **Summarizer LLM 必须消费文本输入** | P1 | `sample_agents.py:1586-1642`: typed state → json.dumps() → text |
| R3 | **Protocol vs text 的差异停在 "agent-to-agent wire" 层** | P1, P3, P4 | `orchestrator.py`: control_bytes 计的是 msgpack 消息体；LLM prompt 在 agent 内部独立构造 |
| R4 | **Benchmark contract 给每个 case 定义了 2 个 acceptable tools** | P2 | `contest_family_spec.yaml`: acceptable_tools 包含 primary+alternative |
| R5 | **text_whole_lane comparator 运行在 StateBus runtime 内** | P6 (缺失 true baseline) | `executor_runtime.py:1857-1923`: text executor 有结构化恢复 |
| R6 | **S2 replay 只覆盖 same-family prior-dependent cases** | P7 | `contest_family_spec.py`: only replay_reusable cases get S2 marking |
| R7 | **指标优先级与赛题错位** | P1-P5 的解读偏移 | §6.4-6.5 |

### 8.3 Main Direction Layer (唯一主方向，只能选一个)

**候选方向:**

| 方向 | 解决什么 | 不能解决什么 | 工作量 |
|------|----------|-------------|--------|
| A: 补 external baseline | P6 (缺失 baseline) | P1 (token 不降), P2 (exact=0.25) | 大 (1-2 weeks) |
| B: 重构 metrics + prompt | P1 (token 持平) partially | P6 (baseline 缺失) | 中 (3-5 days) |
| C: 修 tool exact | P2 (exact=0.25) | P1, P6 | 小 (1-2 days, but may not help) |
| D: 缩 claim + 写诚实报告 | P1-P7 (叙事) | None (不改变实验) | 小 (1 day) |

**选择: A — 补 external baseline**

理由:
1. 这是赛题的核心对比对象缺失 — 这是 blocking issue
2. 在 external baseline 建立之前，任何内部优化都无法转化为赛题评分
3. 如果 external baseline 建立后 token/gap 仍然严重，那方向 B/C 也无济于事
4. 如果 external baseline 建立后发现 protocol 真的有优势 (只是被当前的 lazy comparator 遮掩了)，那整个结论会翻转
5. Direction A 是 **唯一的可证伪验证路径**: 它允许我们 test the null hypothesis ("protocol doesn't help") against a genuine alternative

R1-R7 中能通过 A 解决的:
- R5 (text comparator 不是独立的) — 直接解决
- R3 (agent-to-agent wire vs agent-to-LLM 的区分) — external baseline 提供真正的 comparator
- R4 (contract 定义问题) — external baseline 同受此 contract 约束，可区分 contract artifact vs system issue

R1-R7 中不能通过 A 解决的:
- R1 (headline 只用 YAML Planner) — 这是内部设计选择
- R2 (Summarizer must consume text) — 这是 LLM 本质约束
- R6 (S2 replay 过窄) — 这是 task design 问题
- R7 (指标错位) — 需要指标重构

---

## 9. Updated Root-Cause Ranking

基于本轮深挖，根因需要重新排序:

| Rank | 根因 | 类别 | 致命程度 | 解决方向 |
|------|------|------|----------|----------|
| **1** | **External pure-text baseline 缺失 (R5)** | Experimental Design | 致命 | 方向 A |
| **2** | **Headline 只让 Summarizer 调 LLM (R1)** | System Architecture | 致命 | 需要 LLM Planner in headline |
| **3** | **Protocol 优势停在 agent-to-agent wire, 不延伸到 LLM consumption (R3+R2)** | Method Limitation | 严重 | 需要重新理解 "通信开销" 的含义 |
| **4** | **指标优先级与赛题错位 (R7)** | Measurement | 严重 | 指标重构 |
| **5** | **Benchmark contract 导致 exact=0.25 (R4)** | Task Design | 中等 | 外部 baseline 后重新评估 |
| **6** | **Memory replay 过窄 (R6)** | Task Design | 中等 | 扩大 replay 范围 |

---

## 10. Final Follow-up Judgment

### 10.1 如果 external baseline 定义严格化后，最大风险是什么？

**最大风险: protocol 在 token 上仍然没有优势。**

因为 R2 是 LLM 本质决定的 — Summarizer 必须把 typed state 重新展开为文本才能生成 summary。即使 external baseline 使用独立 LLM agent，这个约束不变。

如果 external baseline 建立后仍然发现 token 不降，那只能得出一个艰难结论: **typed state protocol 在 "LLM 文本生成" 类任务的通信开销上没有显著优势**。它的优势可能主要体现在:
- 结构化路由/调度效率
- 状态一致性管理
- 多 agent 协调

但这些不是赛题给 25 分的 "通信效率 (token节省)"。

### 10.2 token 不降到底是 benchmark / prompt / 方法问题？

**根本上是方法问题 (R2+R3)，被 benchmark 设计放大了 (R1)。**

- Benchmark: 只用 YAML Planner → Planner 不调 LLM → protocol 的 planner handoff 优势没有机会体现
- Prompt: 两种模式的 Summarizer prompt 内容量相同
- 方法: typed state → LLM text 的 bridge 是必要的，无法消除

即使修复 benchmark (加入 LLM Planner) 和 prompt (进一步紧凑 prompt)，token 的节省空间仍然有限 — 因为 Summarizer 的证据消费量 (主导 token 开销的 bulk) 不会因 protocol 而改变。

### 10.3 exact=0.25 是 correctness 问题还是 contract 问题？

**80% contract 问题, 20% tool disambiguation 问题。**

证据:
- All observed tools are in acceptable_tools list
- admissible_match = 1.00
- Tool substitution is deterministic, suggesting it's driven by signals rather than noise
- But the system cannot distinguish between two sibling tools in the same family when both are in acceptable_tools

Mitigation: 要么把 `primary_expected_tool` 收窄到单一唯一正确工具 (让 alternative 进入 disallowed if not exact)，要么在 contract 中明确 "tool_a and tool_b are both fully correct" 并调整 scoring。

### 10.4 最容易误导答辩评审的一条 repo 叙事？

**"control_bytes 降低了 13.8%，证明了通信效率优势。"**

这条叙事:
1. 把 `control_bytes` (内部 protobuf 消息编码效率) 等同于赛题要的 "文本通信 token 开销"
2. 回避了 `llm_total_tokens` 持平的事实
3. 回避了 `message_count` 和 `handoff_wire_bytes` 上升的事实
4. 用内部机制指标替代了外部可见 superiority 指标

在答辩中，如果评审追问 "你们说的 13.8% 是什么的 13.8%？是 LLM token 吗？"，回答会很困难。

### 10.5 如果只能做一件事，选什么？

**External Pure-Text Baseline。**

理由 (最简):
1. 没有它，所有内部优化都证明不了 "比传统方法更好"
2. 它是赛题评审会第一个会问的问题: "你们的 baseline 是什么？"
3. 它同时为其他问题提供诊断平台 (exact=0.25 是 contract 问题还是系统问题？token 不降是因为 comparator 太强还是方法太弱？)
4. 即使最终结果不理想，有一个诚实的 external comparison 也比没有 comparison 好得多

---

## 11. One Actionable Direction Only

**构建 `external_pure_text_strict_baseline_v1`**:

1. 实现独立的纯文本 multi-agent baseline (不 import StateBus runtime)
2. 在全部 20+ text tasks 上运行 repeat>=10
3. 使用与 headline 相同的 LLM model, corpus, task queries, scoring contracts
4. 统计与 headline 相同口径的: llm_total_tokens, message_count, task_ms, exact/admissible/wrong_family rates
5. 产出: `runs/external_pure_text_strict_baseline_v1_api_r10_YYYYMMDD_HHMMSS/` 及完整报告
6. 将结果与 frozen headline protocol results 做正式对比
7. 基于对比结果改写 claim matrix

不做:
- 不修 tool exact
- 不改 prompt
- 不扩 memory replay
- 不加新 surface
- 不重写文档叙事

这些都可以等 external baseline 结果出来后再决定方向。

---

## Appendix: Key Code References

| 证据 | 位置 |
|------|------|
| Summarizer prompt construction (text vs protocol) | `agents/sample_agents.py:1586-1642` (explain), `2257-2302` (`_summarizer_messages`) |
| Planner prompt construction (text vs protocol) | `agents/sample_agents.py:2148-2223` (`_planner_messages`) |
| LLM token accumulation | `runtime/orchestrator.py:740-760` (`record_llm_result`) |
| control_bytes accumulation | `runtime/orchestrator.py:126-158` (`record_message`), `236-241` (`emit`) |
| handoff_wire_bytes accumulation | `runtime/orchestrator.py:257-277` (`record_transfer_inputs`) |
| case_contract_audit (exact/admissible logic) | `eval/runner.py:885-982` |
| text executor structured recovery | `runtime/executor_runtime.py:1857-1923` (`_feature_bundle_from_text_whole_lane_handoff`) |
| Task generation (acceptable_routes/tools) | `tasks/contest_family_spec.py`, `tasks/contest_family_spec.yaml` |
| ExternalTextOpenRuntime (lexical_stub vs live_api) | `eval/text_open_baseline.py:112-320` |
| Headline row-level data | `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/benchmark_results.json` |
| Latest API repeat=1 suite | `runs/full_api_repeat1_coverage_suite_20260619_095302/` |

---

*审稿完成日期: 2026-06-20*
*本报告是第一轮审稿的后续深度诊断，不是重复。*
*所有关键判断都落在代码行号、artifact 行级数据、和可证伪的假设上。*
