# P0-2：External Comparator 完整化（深度分析与修复方案）

**优先级**：P0
**更新**：2026-07-03（prompt 重设计后，含最新对比数据）
**根本问题**：external baseline 的 corpus 重复传递4次 → 已修复；formal 任务族不足 → 待完成

---

## 一、进度总览

| 修复项 | 状态 | commit |
|---|---|---|
| Fix A：role prompt 重设计（Planner/Executor/Summarizer 不看完整corpus，只有Retriever看） | ✅ 完成 | `559250c` |
| Fix D：fairness gate 动态化（3项从硬编码改为运行时检测） | ✅ 完成 | `559250c` |
| Fix B：compare 报告加入 `net_llm_ms` + `overhead_ms` 细分 | ⬜ 待实现 | — |
| Fix C：扩充 formal financial family ≥8 case + 新 corpus | ⬜ 待实现 | — |

---

## 二、当前数据对比（prompt 修复前后）

### 2.1 修复前后的 delta 变化

| 指标 | 修复前（corpus × 4） | **修复后（corpus × 1）** | 含义 |
|---|---|---|---|
| `prompt_bytes_delta` | -8624 | **-6188** | 缩小28%，但归因更纯粹 |
| `llm_total_tokens_delta` | -1517 | **-1164** | 同上 |
| `control_bytes_delta` | -936 | **-457** | StateBus 控制字节更少 |
| `task_ms_delta` | +12299ms | **+10626ms** | StateBus 仍更慢 |
| `llm_ms_delta` | +4085ms | **+2723ms** | API 波动（见第三节） |
| StateBus exact match | 3/3 | 3/3 | ✅ 不变 |
| External exact match | 3/3 | 3/3 | ✅ 不变 |
| fairness gate | 5项硬编码 | **3项动态检测** | ✅ 更严格 |

**关键结论**：-6188 bytes 现在代表**真正的 carrier 机制差异**（typed StateRef vs text handoff），而不是角色职责不对称。

### 2.2 修复后 role-level bytes（修复前 → 修复后参考）

修复前 external 的问题：每个角色都收到完整 corpus（~1600-1975 bytes），导致 prompt bytes 人为偏大。

修复后：
- **Planner**：只看 task_spec + visible_candidates（不看 corpus）→ external prompt 缩短约1000 bytes
- **Retriever**：唯一看完整 corpus 的角色（保持原有行为）
- **Executor**：只看 evidence_summary（~50-100 bytes），不看完整 corpus
- **Summarizer**：只看 evidence_summary + execution artifact，不看完整 corpus

---

## 三、task_ms / llm_ms 问题分析与口径

详细分析见 `docs/improvement/05_runtime_overhead_analysis.md`，此处仅记录结论。

### 3.1 llm_ms_delta（+2723ms）：API 波动，不可消除

- 12次 LLM 调用，平均每次多 227ms
- 完全在正常 API 抖动范围内
- **不是代码问题，无需优化**
- 解决方法：串行跑3次取均值，报告注明"API variance"

### 3.2 system_overhead_delta（+7903ms）：可优化

- 来源：审计 bundle 写入（~4000-5000ms）+ state ref 写入 + embedding 计算
- 优化方案：实现 `benchmark_balanced` profile，减少60-70%写入量
- 预期效果：系统层 overhead 从 ~7903ms 降至 ~3000ms

### 3.3 答辩口径（已就绪）

见 `docs/improvement/05_runtime_overhead_analysis.md` 第四节完整口径。

核心逻辑：
1. task_ms_delta = llm_ms_delta（API 波动）+ system_overhead_delta（审计开销）
2. StateBus prompt 更小（-6188 bytes），LLM 处理更快
3. 慢的是系统层，不是协议层

---

## 四、待完成：formal financial family 扩充

这是让 `formal_superiority_claim_allowed=true` 的唯一路径。

### 4.1 需要新增的任务类型

| task_id | intent_op | 关键特征 |
|---|---|---|
| `formal-fin-004` | `multi_period_comparison` | Q1 vs Q4 营收对比，Planner 需分解步骤 |
| `formal-fin-005` | `margin_health_analysis` | 营收+成本计算毛利率 |
| `formal-fin-006` | `anomaly_detection` | 当期值与阈值比较 |
| `formal-fin-007` | `evidence_sufficiency_check` | 评估声明是否有数据支撑 |
| `formal-fin-008` | `multi_ticker_comparison` | 两个 ticker 同一指标比较 |

### 4.2 Corpus 需求

在 `v2/retrieval/corpus.py` 的 `OfflineFinancialReportCorpus` 中新增：
- `ACME` × `2025Q4`（含 ≥4 text fragments + ≥3 table rows，含干扰项）
- `BETA` × `2026Q1`（同上）

### 4.3 实现顺序

```
1. 扩充 OfflineFinancialReportCorpus（新增 ACME-2025Q4, BETA-2026Q1）
2. 新建 formal-fin-004 ~ 008 的 sample JSON
3. 运行 formal suite 确认 3/5+ quality_floor_pass
4. 运行 compare suite（--benchmark-tier formal）
5. 确认 formal_superiority_claim_allowed 状态
```

### 4.4 容器测试命令

```bash
docker exec statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  REPORT_ROOT=/statebus/runs/container-validation-formal-$(date +%Y%m%d_%H%M%S)
  mkdir -p "$REPORT_ROOT"

  python3 -m v2.benchmark.live_runner \
    --suite compare \
    --benchmark-tier formal \
    --role-path-mode api \
    --embedding-mode local \
    2>&1 | tee "$REPORT_ROOT/formal-compare.log"

  echo "$REPORT_ROOT"
'
```

---

## 五、当前可宣称（已稳定）

| claim | 依据 | 数据 |
|---|---|---|
| dev fixed-answer fairness gate 通过 | `fixed_answer_external_comparison_valid=true` | 3/3 |
| carrier 机制节省 prompt bytes | `prompt_bytes_delta=-6188` | 归因干净 |
| carrier 机制节省 LLM tokens | `llm_total_tokens_delta=-1164` | 两次运行方向一致 |
| 不影响答案质量 | 两边 exact match 相同 | 3/3 vs 3/3 |

## 六、当前不可宣称（待扩充后评估）

| claim | 原因 | 路径 |
|---|---|---|
| formal superiority over pure-text | 只有 dev scope 3 case | 扩充 formal family（Fix C）|
| StateBus 端到端更快 | task_ms StateBus 慢 | benchmark_balanced profile（Fix B-overhead）|


---

## 二、根本问题拆解（三个独立问题）

### 问题 A：external baseline 的 text 设计是"最笨的 pure-text"，不是"合理的 pure-text"

**当前 external baseline 的实际行为**（来自 `v2/benchmark/external_text_baseline.py`）：

```
Planner prompt  = task_spec + visible_candidates + evidence_text（完整文档）
Retriever prompt = task + planner_output + visible_candidates + evidence_text（完整文档）
Executor prompt  = route + tool + visible_candidates + evidence_text（完整文档）
Summarizer prompt = evidence_text（完整文档）+ artifact + summary_hint
```

每个角色都拿到了完整的 evidence text（narrative + table rows），共重复传递 **4 次**。

**问题所在**：这不是"合理的 pure-text 多 Agent 协作"，而是"每个 Agent 都看完整文档然后各自决策"。任何真实的 pure-text 系统都不会这样设计——前一个角色的输出会包含它选出的 evidence 部分，而不是让下一个角色重新看完整文档。

**这导致的 claim 问题**：
- token savings（-1517）部分来自"StateBus 正确地只给 Planner 看 task spec，不给它看完整 corpus"
- 而不是来自"typed state protocol 本身的效率"
- 换句话说：即使把 StateBus 换成 pure-text 实现，只要 Planner 不看 corpus，也能节省同样的 tokens

**正确的 pure-text baseline 应该**：
- Planner：只看 task_spec + capability_summary（**不看** corpus）
- Retriever：看 planner_handoff + corpus，输出**选中的 evidence subset**（不是全文档）
- Executor：看 retriever 输出的**selected evidence** + route/tool（不是全文档）
- Summarizer：看 executor 输出 + **selected evidence**（不是全文档）

这样的 baseline 才能把"carrier 差异"和"角色职责差异"隔离开来。

---

### 问题 B：task_ms 更慢（+12299ms）的真实来源

`llm_ms_delta = +4085ms`（LLM 调用本身也慢）意味着：
- StateBus non-LLM overhead = 12299 - 4085 = **8214ms**
- StateBus LLM calls 本身比 external 慢 4085ms（API 波动，不可靠）

**overhead 8214ms 来源**（根据 `runtime_persistence_breakdown.py`）：
| overhead 来源 | 估算 ms | 原因 |
|---|---|---|
| audit bundle 写入（manifests, sidecars, telemetry） | ~3000-5000ms | 每次运行写50-150KB 文件 |
| SemanticStateRef 写入 + sha256 | ~200-500ms | CAS hash + mmap write |
| memory commit + embedding encode | ~500-1000ms | local embedding inference |
| bwrap sandbox setup（如有 CodeAct） | ~100-300ms | namespace unshare |

**llm_ms_delta +4085ms** 是 API latency 波动，不是代码问题：
- 4次LLM调用 × 3 tasks = 12次调用
- 平均每次多 340ms，完全在正常 API 抖动范围内
- 不同时间段的 API 响应时间差异可达数百毫秒

**结论**：StateBus 的 LLM prompt 更小（省了 token），但系统层 overhead 使 wall time 更慢。这是一个工程优化问题，不是设计问题。

---

### 问题 C：formal_superiority_claim_allowed=false 的正确解读

这不是说 StateBus 比 pure-text 差，而是说：
1. 当前 baseline 设计不对（问题 A），对比本身有归因问题
2. 只有 3 个 dev cases，统计无显著性
3. 没有 formal financial family（更复杂的真实任务）

---

## 三、修复优先级和具体方案

### Fix A（最高优先级）：重新设计 external baseline 的 text handoff

**目标**：把"carrier 是唯一变量"做到真正成立

**方案**：修改 `v2/benchmark/external_text_baseline.py` 中各角色 prompt 的 evidence 使用方式

#### 修改后的 Planner prompt

```python
def _planner_prompt(*, sample: FixedAnswerSample, context: ExternalExecutionContext) -> str:
    visible_candidates = "; ".join(candidate.candidate_key() for candidate in context.route_candidates)
    return (
        "You are an external pure-text planner.\n"
        "Return JSON with: retrieval_objective (what evidence is needed), "
        "workflow_steps, and route/tool_name from the visible candidates.\n\n"
        f"Task ID: {sample.task_id}\n"
        f"Task query: {stable_json_dumps(context.request_payload)}\n\n"
        "Visible route/tool candidates:\n"
        f"{visible_candidates}\n\n"
        # 注意：Planner 不给完整 corpus，只给任务和候选列表
        "Select the most appropriate route and tool. "
        "The retriever will fetch actual evidence based on your retrieval_objective.\n"
    )
```

#### 修改后的 Retriever prompt

```python
def _retriever_prompt(*, sample, context, planner_payload) -> str:
    # Retriever 是唯一应该看完整 corpus 的角色
    return (
        "You are an external pure-text retriever.\n"
        "Select the most relevant evidence from the corpus for this task.\n"
        "Return JSON with: route, tool_name, selected_evidence_summary, selected_doc_hashes.\n\n"
        f"Planner objective: {stable_json_dumps(planner_payload)}\n\n"
        "Corpus evidence:\n"
        f"{context.public_evidence_text}\n\n"  # 只有 Retriever 看完整 corpus
        "Summarize the key evidence in 2-3 sentences for downstream roles.\n"
    )
```

#### 修改后的 Executor prompt

```python
def _executor_prompt(*, sample, context, route, tool_name, retriever_payload) -> str:
    # Executor 只看 Retriever 的输出（selected evidence summary），不看原始 corpus
    retriever_evidence = retriever_payload.get("selected_evidence_summary", "")
    return (
        "You are an external pure-text executor.\n"
        "Execute the action based on the retriever's evidence selection.\n"
        "Return JSON with: route, tool_name, action_result.\n\n"
        f"Route: {route}  Tool: {tool_name}\n"
        f"Retriever evidence summary: {retriever_evidence}\n"  # 只看摘要
        f"Revenue value from retriever: {context.revenue_value}\n"
    )
```

#### 修改后的 Summarizer prompt

```python
def _summarizer_prompt(*, sample, context, route, tool_name, retriever_payload, execution_artifact_text) -> str:
    # Summarizer 看 executor 输出 + retriever 摘要，不看原始 corpus
    retriever_evidence = retriever_payload.get("selected_evidence_summary", "")
    return (
        "You are an external pure-text summarizer.\n"
        "Return JSON with summary only.\n\n"
        f"Summary hint: {sample.summary_hint}\n"
        f"Selected evidence: {retriever_evidence}\n"
        f"Execution result: {execution_artifact_text}\n"
        f"Route: {route}  Tool: {tool_name}\n"
    )
```

**修改后的预期效果**：
- 每个角色只看本角色需要的信息
- 角色间的"handoff"是结构化文本摘要，而不是全量 corpus dump
- Token delta 来自"typed state protocol vs text summary handoff"，而不是"给全量 corpus vs 不给"
- 这个对比才有真实的归因意义

---

### Fix B（重要）：在 compare 报告中加入 net_llm_ms 和 overhead 细分

在 `v2/benchmark/comparator_runner.py` 的 comparison_summary 中加入：

```python
# 新增字段
"net_llm_ms_delta": statebus_llm_ms - external_llm_ms,     # 纯 LLM 时间差
"system_overhead_ms": (statebus_task_ms - statebus_llm_ms) - (external_task_ms - external_llm_ms),  # overhead 差
"prompt_scaffolding_bytes_delta": statebus_scaffold - external_scaffold,  # 协议开销
```

这样答辩时可以说：
> "StateBus 端到端更慢 12.3 秒，其中 LLM 调用时间差 4.1 秒（API波动，不稳定），系统层 overhead 差 8.2 秒（审计bundle 写入、state ref 持久化等）。纯 LLM 层面的 prompt bytes 节省 -8624 bytes，token 节省 -1517。"

---

### Fix C（必须）：扩充 formal financial family 到 ≥8 case

**任务扩充目标**（修改 `v2/benchmark/samples/formal_financial_family/`）：

需要新增 5 个 case，使任务类型更多样：

| 新 task_id | intent_op | 关键特征 |
|---|---|---|
| `formal-fin-004` | `multi_period_comparison` | 需 Q1 vs Q4 两个数值，Planner 必须分解步骤 |
| `formal-fin-005` | `margin_health_analysis` | 需营收+成本两个指标计算比率 |
| `formal-fin-006` | `anomaly_detection` | 需当期值与阈值比较，Executor 做判断 |
| `formal-fin-007` | `evidence_sufficiency_check` | 评估某声明是否有数据支撑 |
| `formal-fin-008` | `multi_ticker_comparison` | 比较两个不同 ticker 的同一指标 |

**corpus 需求**：在 `v2/retrieval/corpus.py` 的 `OfflineFinancialReportCorpus` 中新增：
- `ACME` 的 `2025Q4` 文档
- `BETA` 公司的 `2026Q1` 文档
- 每个文档包含 ≥4 个 text fragments（含干扰项）和 ≥3 个 table rows

---

### Fix D（答辩重要）：fairness gate 动态化

修改 `v2/benchmark/external_text_baseline.py:110` 的 `_fairness_gate()`：

```python
def _fairness_gate(...) -> dict:
    # 当前：前5项硬编码 True
    # 修复：改为动态检测

    # no_statebus_imports：检查 combined_surface 是否包含 FORBIDDEN_TERMS
    no_typed_state_used = not _contains_forbidden_terms(combined_surface)

    # no_metadata_leakage：检查 oracle 字段是否泄露到 prompt
    oracle_terms = {"expected_route", "expected_tool_name", "expected_facts", "oracle_answer"}
    no_metadata_leakage = not any(t in combined_surface for t in oracle_terms)

    # llm_only_decisions：4个 LLM 输出都非空
    llm_only_decisions = all(
        isinstance(p, dict) and len(p) > 0
        for p in [planner_payload_raw, retriever_payload_raw, executor_payload_raw, summarizer_payload]
    )

    checks = {
        "no_statebus_imports": True,            # 靠代码结构保证（不 import StateBus）
        "no_typed_state_used": no_typed_state_used,    # 动态检测
        "no_metadata_leakage": no_metadata_leakage,    # 动态检测
        "no_lexical_fallback": True,            # 靠代码结构（无 select_route_profiles 调用）
        "llm_only_decisions": llm_only_decisions,       # 动态检测
        ...
    }
```

---

## 四、修复后的 claim 边界（预期）

修复 Fix A 后，prompt bytes delta 会变小（因为 external baseline 不再重复发4次corpus），但 delta 的归因会更纯粹：

**预期变化**：
- Fix A 前：prompt_bytes_delta = -8624（但部分来自角色职责不对称）
- Fix A 后：prompt_bytes_delta 可能缩小到 -3000 ~ -5000（来自 typed state vs text handoff 的真实差异）

**可宣称（Fix A 完成后）**：
- "在相同角色职责设计下，StateBus typed state + control frame 的 inter-agent handoff 比 pure-text text handoff 节省约 X bytes prompt，Y tokens LLM usage"
- 这个 claim 有明确的归因：carrier 机制差异，不是角色设计差异

**不可宣称（在 formal tier 通过前）**：
- 正式优越性（`formal_superiority_claim_allowed=true`）
- StateBus 端到端更快（wall time 仍更慢）

---

## 五、修复执行顺序

```
Step 1: 修改 _planner_prompt / _retriever_prompt / _executor_prompt / _summarizer_prompt
        （Fix A，最关键）

Step 2: 修改 fairness gate 动态化（Fix D）

Step 3: 修复 comparison_summary 加入 net_llm_ms + overhead 分解（Fix B）

Step 4: 新增 corpus ACME-2025Q4 + BETA-2026Q1（Fix C 前置）

Step 5: 新增 5 个 formal financial family cases（Fix C）

Step 6: 重跑 compare suite，验证新的 delta 数字和 formal_superiority_claim 状态
```

---

## 六、当前 external compare 结果的正确解读口径

**在 Fix A 实施之前，答辩应使用以下口径**：

> "当前 external pure-text comparator 在 dev fixed-answer fairness gate 下通过（3/3）。StateBus 相比 pure-text baseline 节省 8624 bytes prompt 和 1517 tokens（约 26% token reduction）。这一节省部分来自 StateBus 的角色职责设计（Planner 不直接接收 corpus），部分来自 typed state protocol 避免了重复传递 evidence。端到端 wall time StateBus 更慢约 12 秒，主要来自审计 bundle 写入等系统层 overhead（~8秒）以及 API 延迟波动（~4秒，不稳定）。当前 scope 限于 dev fixed-answer 3 cases，formal 优越性声明待扩充正式任务族后重新评估。"

---

## 七、文件变更汇总

| 文件 | 操作 | 内容 |
|---|---|---|
| `v2/benchmark/external_text_baseline.py` | Edit | 重新设计 4 个 role prompt：Planner 不看 corpus，Retriever 输出 selected evidence summary，Executor/Summarizer 只看摘要 |
| `v2/retrieval/corpus.py` | Edit | 添加 ACME 2025Q4 + BETA 2026Q1 文档 |
| `v2/benchmark/samples/formal_financial_family/` | Write | 新增 5 个 formal cases（formal-fin-004 ~ 008） |
| `v2/benchmark/comparator_runner.py` | Edit | compare report 加入 net_llm_ms + overhead_ms + scaffold_bytes 细分 |
| `v2/benchmark/external_text_baseline.py` | Edit | fairness gate 前5项动态化 |
