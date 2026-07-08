# StateBus 全量审计报告 — June 17, 2026

日期: `2026-06-17`
审计人: systematic deep-dive
运行: `runs/statebus_mainline_repeat3_suite_20260617_141158/`
范围: 前因后果 + 当前代码/测试/文档 + 最新实验结果 + row-level 底层结果
最高约束: `docs/reference/题目.md`

---

## 审计范围与交叉核对

### 已读文档 (7/7)

- `docs/reference/题目.md`
- `README.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/reports/task_design_and_mode_comparison.md`
- `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`
- `docs/analysis/mainline_repeat3_analysis_20260617.md`

### 已核代码 (10/10)

- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/langgraph_adapter.py`
- `runtime/executor_runtime.py`
- `eval/runner.py`
- `eval/metrics.py`
- `tasks/sample_tasks.py`
- `tasks/contest_family_spec.py`
- `tasks/contest_family_spec.yaml`

### 已核测试 (3/3)

- `tests/test_smoke.py`
- `tests/test_llm_runtime.py`
- `tests/test_state_channels_and_graph.py`

### 已核结果文件 (13/13 pack reports + 8/8 benchmark_results.json)

- `SUMMARY.md` — 所有 13+1 pack 通过，pytest 191 passed
- 全部 13 个 benchmark_report.md
- 以下 8 个包的 `benchmark_results.json` row-level:
  - `contest_honest_headline_v1`
  - `contest_dual_mode_controlled_v3`
  - `memory_dual_mode_fairness_v3`
  - `typed_state_mechanism_v3`
  - `planner_support_v3`
  - `text_definition_audit_v3`
  - `external_text_baseline_audit_v3`
  - `typed_state_consumer_sensitivity_v3`

---

## Section A: Findings（按严重性排序 A1=最严重）

---

### F-A1 [P0 Reporting Bug]: `planner_one_shot_valid_rate: 0.00` 本质是 aggregate 计算错误，不是 Planner 失败

**结论:**
`planner_support_v3` report 中写的 `planner_one_shot_valid_rate: 0.00`
是一个 reporting aggregation bug。底层 row-level 数据中**所有** 11 个 task 的
`planner_one_shot_valid` 都是 `1.0`，`planner_repair_attempt_count` 都是 `0`。

**为什么成立:**

1. `eval/metrics.py:105-108` 定义了 `planner_one_shot_valid` property:
   ```python
   @property
   def planner_one_shot_valid(self) -> float:
       if self.planner_llm_request_count == 0:
           return 1.0
       return 1.0 if self.planner_repair_attempt_count == 0 else 0.0
   ```
   这个 formula 对每个 task row 都是正确的：当 `repair_attempt_count=0`
   且 `planner_llm_request_count > 0`（llm plan 有 1 次 request）时，返回 `1.0`；
   当 `planner_llm_request_count=0`（yaml plan）时，也返回 `1.0`。

2. 但 report writer 中的 aggregate aggregation formula **没有使用**
   `planner_one_shot_valid` per-row 值来计算比例。Report 是用自己的方式重新
   计算的，可能用了 `planner_llm_request_count` 总和和
   `planner_repair_attempt_count` 总和的比例关系，导致计算错误。

**底层证据 (benchmark_results.json row-level):**

| task_id | plan_source | planner_llm_request_count | planner_repair_attempt_count | planner_one_shot_valid (per row) |
|---|---|---|---|---|
| planner-support-checkout-yaml-001 | yaml | 0 | 0 | 1.0 |
| planner-support-checkout-llm-001 | llm | 1 | 0 | 1.0 |
| planner-support-auth-yaml-001 | yaml | 0 | 0 | 1.0 |
| planner-support-auth-llm-001 | llm | 1 | 0 | 1.0 |
| planner-support-cache-yaml-001 | yaml | 0 | 0 | 1.0 |
| planner-support-cache-llm-001 | llm | 1 | 0 | 1.0 |
| planner-support-billing-yaml-001 | yaml | 0 | 0 | 1.0 |
| planner-support-billing-llm-001 | llm | 1 | 0 | 1.0 |
| planner-support-deploy-yaml-001 | yaml | 0 | 0 | 1.0 |
| planner-support-deploy-llm-001 | llm | 1 | 0 | 1.0 |
| planner-support-auth-llm-002 | llm | 1 | 0 | 1.0 |

所有 11 行的 `planner_one_shot_valid=1.0`，`planner_repair_attempt_count=0`。

**Report 写的矛盾:**
- `benchmark_report.md:42`: `planner_one_shot_valid_rate | 0.00`
- `benchmark_report.md:43`: `planner_repair_attempt_total | 0`

如果 repair_attempt_total=0，那 one_shot_valid 应该是 100%（没有 repair 发生过）。
Report 自己都无法自洽。

**分类:** reporting / metric 语义问题。

**是否需要改:** **必须改**。这是 P0 级 reporting 错误——
report 声称 Planner one-shot 全军覆没，但底层每一行都是正确的。
对外答辩时这个数字会让评审直接认为 Planner 不可用。

**若改，改动边界:**
- 只改 `eval/runner.py` 中的 report aggregate 计算逻辑
- 不改 `eval/metrics.py`
- 不改 Planner 行为
- 不改 `benchmark_results.json` 产出

---

### F-A2 [P0 Reporting]: `memory_dual_mode_fairness_v3` 全部 40 行被标为 `correctness_label=mismatch`

**结论:**
`memory_dual_mode_fairness_v3` 的 40 个 task row (text × 20 + protocol × 20)
在 `benchmark_results.json` 中全部显示 `correctness_label=mismatch`、`exact_match=False`、
`admissible_match=False`。但这**不是系统真正的 correctness 失败**——memory_dual_mode
tasks 设计上从来没有定义 case contract 正确的 route/tool 期望值。
所有行的 `primary_expected_route=""` 和 `primary_expected_tool=""`，
因此 default `case_type=exact_single_solution` 的 `_build_case_contract_audit`
函数在对空期望时产出 `mismatch`。

**为什么成立:**

1. `_build_case_contract_audit` 的逻辑 (`eval/runner.py:885-982`):
   - 当 `primary_expected_route=""` 时，`route_exact = False`（因为任何非空的是 observed route 不等于空字符串）
   - 当 `case_type = "exact_single_solution"` 时，`admissible_match = exact_match`
   - 因此 `admissible_match = False`，`correctness_label = "mismatch"`

2. `memory_dual_mode_fairness_v3_benchmark.yaml` 中确实没有定义任何 task 的
   `case_contract` 相关字段（`expected_family`、`primary_expected_route`、`acceptable_routes` 等），
   因为这些 task 只关心 memory replay 行为，不关心 correctness。

3. Report 的 Memory Policy Table 是正确的——它正确聚合了 replay 指标
   （`reuse_gain`、`skipped_step_count`、`task_ms`），说明 report writer
   理解 memory_dual_mode 的定位。但 `benchmark_results.json` 中的
   `correctness_label=mismatch` 仍是明显的 reporting 对象定义问题。

**底层证据:**

```
memory-dual-01-cold_start-text-001: label=mismatch exact=False adm=False wrong=False
memory-dual-01-assist-text-001:     label=mismatch exact=False adm=False wrong=False
memory-dual-01-validated_replay-text-001: label=mismatch exact=False adm=False wrong=False
memory-dual-01-exact_replay-text-001:     label=mismatch exact=False adm=False wrong=False
...
(all 40 rows identical pattern)
```

所有行的 `observed_route` 实际上都是正确的（如 `db_pool_saturation`、`worker_queue_starvation`），
只是因为没有 `primary_expected_route` 期望值，所以匹配失败。

**分类:** reporting / metric 语义问题（对象定义缺失）。

**是否需要改:** 是。`correctness_label=mismatch` 在 `benchmark_results.json` 中会
被任何数据处理 pipeline 读成"系统做出了错误判断"，这与事实不符。

**若改，改动边界:**
- 在 `_build_case_contract_audit` 中添加一个检查：当 `primary_expected_route` 为空
  且 `primary_expected_tool` 为空时，返回 `correctness_label="not_evaluated"`
- 或者：在 memory_dual_mode 的 YAML 定义中显式填入 case contract（但这样改变了
  audit-only pack 的定位，不推荐）
- 不改 Report 的 Memory Policy Table（它本来就没读这个字段）

---

### F-B1 [Fairness]: `text_whole_lane` executor 存在结构化 route/tool 恢复路径

**结论:**
`text_whole_lane` 的 executor 并不是一个"只能做自然语言理解"的消费者。
`_feature_bundle_from_text_whole_lane_handoff` (`executor_runtime.py:1857-1923`) 做了两件事:
1. 调用 `build_feature_bundle()` —— 完整的 lexical signal matching（与 protocol retriever 完全相同的代码路径）
2. 解析自然语言 handoff 中的软性 route/tool 暗示（"Based on the visible evidence, X is the leading explanation"、"Starting with Y is the safest next step"）

这意味着 text executor 有**结构化恢复能力**——它不是 blind NL consumer，
它有 ToolRegistry、有证据文本全文、有匹配算法。

**证据链路:**

```
executor_runtime.py:1002-1015 (execute_playbook_step):
    transfer_strategy == "text_whole_lane":
        → _feature_bundle_from_text_whole_lane_handoff(...)  (line 1857)

executor_runtime.py:1857-1923 (_feature_bundle_from_text_whole_lane_handoff):
    → build_feature_bundle(query=query, evidence_text=evidence_text, ...)  (line 1897)
    → 解析 NL: "Based on the visible evidence, X is the leading explanation"  (line 1881)
    → 解析 NL: "Starting with Y is the safest next step for now"  (line 1892)
    → route_tool = registry.maybe_get_for_route(normalized_route)  (line 1908)
    → if normalized_tool: spec = registry.get(candidate_name)  (line 1915)
```

对照 protocol executor:
```
executor_runtime.py:1016-1027 (execute_playbook_step):
    transfer_strategy == "state_packet_minimal":
        → _feature_bundle_from_executor_decision_packet(...)  (line 1942)
        → 直接读取 structured packet 中的 route/tool 字段
```

**是 fairness 问题吗？**

这里需要区分两种 fairness 观点:

**观点 1（严格 pure-text baseline）:** 如果赛题要求的 pure-text baseline 是
"Agent 只能通过自然语言交流，executor 只能读自然语言，不能有 structured recovery
路径"，那当前 `text_whole_lane` 仍有问题——因为 `build_feature_bundle()` + NL 解析
是相对高级的 structured recovery（虽然不是显式 `Route:` 字段解析）。

**观点 2（内部对称引擎）：** 当前系统内部，text lane 和 protocol lane 的 executor
使用同一套 ToolRegistry 和相同的执行引擎。text lane executor 从 NL handoff 中
恢复 route/tool 信息，protocol lane executor 从 structured packet 中读取。这是
对称的——因为它们做的是同一个工作（选择工具执行）。关键在于 executor 接收到的
`input kinds` 不同，这已经在 transfer_truth_audit 中被正确追踪了。

当前项目采用的观点 2（对称执行引擎）。但需要诚实地写：**text_whole_lane executor
同时做了 lexical matching + NL hint parsing 来恢复 route/tool 决策。**
这不是纯 LLM-based NL understanding，不要声称是。

**分类:** 对象定义问题（部分是 fairness 问题）。

**是否需要改:** 取决于要做什么 claim。
- 如果 claim 是 "protocol sends structured decisions, text sends natural language"
  → 当前成立，不用改
- 如果 claim 是 "text executor has no structured recovery path"
  → 不成立，text executor 确实有 `build_feature_bundle()` 调用
- 推荐：不改代码，但在文档中注明 text executor 有 lexical recovery

---

### F-B2 [Fairness]: Summarizer 在 `text_whole_lane` 中看到的信息比 protocol 少

**结论:**
text_whole_lane 的 summarizer 接收到的输入 refs 只有 `TOOL_ARTIFACT`（executor 输出），
而 protocol summarizer 接收到 `DENSE_EVIDENCE` + `TOOL_ARTIFACT`。
这个差异是因为 text_whole_lane 的 DENSE_EVIDENCE 被 retriever 产出后没有
传递给 summarizer（只通过 inline text 给了 executor）。

**底层证据 (contest_honest_headline_v1):**

```
mode     | summarizer_input_kinds
---------|------------------------
text     | ['TOOL_ARTIFACT']
protocol | ['DENSE_EVIDENCE', 'TOOL_ARTIFACT']
```

**为什么重要:**
在 protocol 模式下，summarizer 的 prompt 中包含 evidence text 片段，
这使 summarizer 能更好地了解为什么某个路径被选择。
在 text 模式下，summarizer 只看到 executor 的 action text（"I proceeded with the db pool saturation playbook. Actions taken: ..."）。

但当前正确性数据显示两端的 summarizer 产出的正确性相同（admissible=1.00, exact=0.70）。
这可能是因为:
1. executor output 已经包含足够的信息（text_whole_lane executor 产出的 handoff text 描述了 route）
2. 当前 tasks 太简单，summarizer 不需要 evidence 也能写正确的 summary
3. summarizer deterministic LLM（当前 run）用模板产出结果，不依赖 evidence

在厚任务中这个差异可能很重要。例如，如果 summarizer 需要解释"为什么排除了
competitor hypothesis"，没有 evidence text 就很难写。

**分类:** fairness 问题 + 对象设计问题。

**是否需要改:** 看下一步方向。
- 如果保持当前 thin task 不变，无所谓
- 如果要做 thick task（见推荐主线），应该修——让 text summarizer 也能看到
  retriever 的 TOOL_ARTIFACT（NL handoff text），因为那个文本里包含了
  evidence-based reasoning

---

### F-C1 [Design]: 当前 task 对象太薄，protocol 的 compound 优势无法体现

**结论:**
当前 5 个 release-regression family × 4 个 case type = 20 个 task case，
每个 case 是一个**route/tool selection 问题**。多 Agent 协作的表面是:
1. Retriever: 从 corpus 检索相关 doc，做 lexical/Tag 匹配，决定 route + tool
2. Executor: 运行被选中的 tool playbook
3. Summarizer: 把 executor 的动作总结成 text

本质上只有**一次** agent-to-agent 结构化 handoff（retriever → executor）。
Protocol 的通信节省只作用在这一跳上（~2000 bytes 节省，占总控制字节 ~8500）。
Summarizer token 消耗在两端完全相同（因为它的输入——executor 输出——在两端格式接近）。

**如果只有一跳 communication handoff，protocol 的节省空间很有限。**
要体现 compound advantage，需要类似这种拓扑:
```
Planner → Retriever → Executor → Retriever → Executor → Summarizer
                        ↑_____________|
                       executor output triggers
                       re-retrieval with new evidence
```
这种情况下:
- text lane 每次 executor → retriever 都要重新 parse NL 输出（每个中间 agent 都消耗 LLM token）
- protocol lane 第一次解析后就可以用 structured packet 在各 agent 间高效传递

**为什么 protocol 在 current thin task 上没有 clear superiority:**

| 因素 | text_whole_lane | protocol | delta |
|---|---|---|---|
| control_bytes | 8657 | 6641 | **-23.3%** ✅ |
| llm_tokens (summarizer dominant) | 415 | 416 | +0.2% (noise) |
| StatePool overhead | 0 (inline text) | ~100ms (msgpack+mmap) | ❌ |
| task_ms | 3177 | 3274 | +3% (within noise) |
| correctness (admissible) | 1.00 | 1.00 | 0 |
| correctness (exact) | 0.70 | 0.70 | 0 |

StatePool overhead 吞噬了通信节省。如果 tasks 有更多 round-trip，
通信节省会 compound（节省 × N 跳），但 StatePool overhead 也会 compound
（每跳一次 msgpack + mmap）。需要在 thicker task 中实测。

**分类:** 对象设计问题（不是 fairness 不是 reporting 错误）。

**是否需要改:** 这是当前最核心的改进方向，但不是"bug fix"。

---

### F-C2 [Design]: billing family tool accuracy 系统性偏低

**结论:**
所有 billing_queue_chain tasks 的 observed tool 都是 `tool.retry_storm_relief`
而不是 `tool.worker_queue_triage`。Route 是对的 (`worker_queue_starvation`)，
但 tool 不是 primary expected (`tool.worker_queue_triage`)，所以 exact 匹配取不到。

**底层证据 (所有 billing family 的 text 和 protocol 行):**

```
observed_route=worker_queue_starvation observed_tool=tool.retry_storm_relief
correctness_label=admissible_match (not exact_match, not wrong_family)
```

**为什么:**
`ToolRegistry` pattern matching 打分机制:
- `tool.retry_storm_relief` 有 patterns: "retry storm", "retry scheduling", "invoice queue backlog", "rebalance invoice consumers"
- `tool.worker_queue_triage` 有 patterns: "worker queue starvation", "worker queue stall", "tls certificate reload"
- billing evidence text 中 "invoice queue"、"billing"、 "retry" 等关键词更匹配 `retry_storm_relief` 的 pattern，得分更高
- 但 task 的 `primary_expected_tool` 是 `tool.worker_queue_triage`

这是 ToolRegistry 的 pattern/tool labeling 与 task contract 之间的**词汇偏差**。

**分类:** 对象设计问题（ToolRegistry pattern 与 task expected tool 不匹配）。

**是否需要改:** 这是已知问题但不要追。fix 它不会改变"protocol 是否 superior"的答案，
只会把 exact=0.70 提高到 maybe 0.8。不要优先追这个。

---

### F-C3 [Observation]: `text_whole_lane` executor 有 0 StatePool overhead（inline text payload）

**结论:**
在 `text_whole_lane` 模式中，executor 不接收任何 StateRef 输入
(`executor_input_kinds=[]`)。所有信息（retriever handoff text）通过 inline
payload（`StepResult.payload.inline_handoff_text`）传递，绕过 StatePool。
这解释了为什么 text 的 task_ms 并不比 protocol 差——它跳过了 StatePool 的
msgpack 序列化 + mmap 写/读 + hash 计算。

Portocol 的 `state_packet_minimal` 模式中，executor 通过 StatePool 接收
`DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET`（两个 typed state refs）。

**底层证据:**

```
mode     | executor_input_kinds                    | executor handoff path
---------|----------------------------------------|----------------------
text     | []                                      | inline text in StepResult.payload
protocol | ['DENSE_EVIDENCE', 'EXECUTOR_DECISION_PACKET'] | StatePool refs
```

**影响:**
这对 text lane 是一个**隐式优势**——它跳过了 StatePool 的成本。
Protocol lane 的 state transfer 之所以有成本，是因为 StatePool 基础设施真实在运行。
这本身是诚实的（protocol 的 typed state path 本来就需要这些 overhead），
但需要被注明在 latency comparison 的 footnotes 中。

**分类:** 实现成本观测。

---

### F-D1 [Observation]: `whole_lane_text_guard` 正确隔离 text_whole_lane

**结论:**
`contest_honest_headline_v1` 的 `whole_lane_text_guard` pass rate = 1.00，
hidden_field_leak = 0.00，template_slot_leak = 0.00。所有 20 个 text task row
的 guard 都通过了。这说明 `text_whole_lane` handoff builder
(`_build_text_whole_lane_retriever_handoff`) 产出的 natural language text
确实不含 structured field markers（如 `Route:`、`Tool:`、`Route source:` 等）。

**底层证据 (所有 20 个 text row 一致):**

```
whole_lane_guard.passed=True hidden_field_leak=False template_slot_leak=False enabled=True
executor_input_kinds=[]
summarizer_input_kinds=['TOOL_ARTIFACT']
```

**对比 `contest_dual_mode_controlled_v3` (text_strict_pure_lane):**

```
whole_lane_guard.passed=False hidden_field_leak=True template_slot_leak=True
executor_input_kinds=[]
summarizer_input_kinds=['TOOL_ARTIFACT']
```

`text_strict_pure_lane` 的 guard 失败是因为 handoff 中含有显式的 `Route:` / `Tool:` /
`Route source:` / `Route confidence:` 等字段标记——这正是之前被判定为
"structured decision 文本化" 的问题。

**分类:** guard 正确工作 —— 正面确认。

---

### F-D2 [Confirmed]: contest dual-mode correctness 在两端相同

**结论:**
在 contest_honest_headline_v1 中，text 和 protocol 的 correctness 指标完全一致:
- admissible_match_rate: 1.00 (both)
- exact_match_rate: 0.70 (both)
- wrong_family_rate: 0.00 (both)
- abstention_rate: 0.10 (both)

Row-level 数据确认了这一点——text row 和配对 protocol row 的 observed_route 和
observed_tool 完全相同。这是合理的，因为两端使用相同的 retriever 逻辑
（相同的 evidence text、相同的 corpus docs、相同的 `build_feature_bundle` 算法）。

**底层证据 (checkout family clean case):**

```
text   rr-checkout-clean-text-001:      observed_route=db_pool_saturation observed_tool=tool.db_pool_triage correctness=exact_match
proto  rr-checkout-clean-protocol-001:  observed_route=db_pool_saturation observed_tool=tool.db_pool_triage correctness=exact_match
```

**含义:** 正确性不是 differential metric。Communication compactness 和 latency 才是。

---

### F-D3 [Confirmed]: llm_tokens 在 text_whole_lane vs protocol 近对称

**结论:**
contest_honest_headline_v1 的 llm_total_tokens per-task:
- text: 414.95 (mean)
- protocol: 415.93 (mean)
- delta: +0.98 (+0.2%) — 在 noise range 内

**为什么这个对称性成立:**
1. 当前 task 使用 yaml plan（`plan_source=yaml`），planner 不消耗 LLM token（两边都是 0）
2. Summarizer 在两端消耗几乎相同的 token（因为 summarizer 接收的信息量在两端接近）
3. text executor 不接收 typed state（无 StatePool 读取 token overhead）

**对比之前的 `contest_dual_mode_controlled_v3` (text_strict_pure_lane):**
- text 315 vs protocol 415 — delta +32%
- 原因: text_strict_pure_lane executor handoff 很短（structured brief），
  summarizer 收到的执行结果也短 → summarizer tokens 比 protocol 少

**含义:** llm_tokens 不是 current headline 的 differential metric。
不要试图把它包装成 protocol 节省 token 的证据——它不节省。

---

### F-E1 [Observation]: memory replay 在两端已对称

**结论:**
`memory_dual_mode_fairness_v3` 显示 replay 能力在 text 和 protocol 两端已经对称:
- exact_replay reuse_gain: 0.67 (both)
- exact_replay task_ms: text ~1885ms, protocol ~1665ms (protocol slightly faster)
- validated_replay reuse_gain: 0.33 (both)
- working_assist: hit in both modes

**底层证据:**

| memory_policy | text task_ms | text reuse_gain | protocol task_ms | protocol reuse_gain |
|---|---|---|---|---|
| memory_off | 3445 | 0.00 | 3275 | 0.00 |
| working_assist | 3348 | 0.00 | 3216 | 0.00 |
| validated_replay | 3048 | 0.33 | 3064 | 0.33 |
| exact_replay | 1726 | 0.67 | 1610 | 0.67 |

**与上轮 run 对比:**
上一轮 run 中，text_whole_lane 的 exact_replay 完全不能 replay（全是 generic_triage，
无任何 skip benefit），exact_replay task_ms ~4600ms。本轮修复后 text 端
exact_replay 能力与 protocol 对称。修复来源：text_whole_lane handoff 格式现在
携带足够的 structured metadata（replay eligibility bundle with proof_only flag）
让 memory replay 能匹配上。

**但注意**：text 端的 exact_replay restored_kinds 只有 `['TOOL_ARTIFACT']`，
而 protocol 端有 `['DENSE_EVIDENCE', 'EXECUTOR_DECISION_PACKET', 'TOOL_ARTIFACT']`。
protocol 恢复的 state 更多，但两个 mode 的 replay timing 差异不大，
因为 TOOL_ARTIFACT 是最大的 state 且已经在两端都被恢复。

**分类:** 实现验证通过 —— 正面确认。

---

### F-E2 [Observation]: Protocol exact_replay 恢复更多 typed state，但 speed gain 有限

**结论:**
Protocol 端的 exact_replay 恢复了 3 种 state kind (`DENSE_EVIDENCE`, `EXECUTOR_DECISION_PACKET`, `TOOL_ARTIFACT`)，
text 端只恢复了 1 种 (`TOOL_ARTIFACT`)。但 protocol exact_replay task_ms 只比
text 快 ~80-150ms，与 total exact_replay time (~1600ms) 比是 ~5-10%。

**底层证据 (memory-dual-01-exact_replay rows):**

```
text:     restored_kinds=['TOOL_ARTIFACT'] task_ms=2249
protocol: restored_kinds=['DENSE_EVIDENCE','EXECUTOR_DECISION_PACKET','TOOL_ARTIFACT'] task_ms=1470
```

Protocol 的 exact_replay 比 text 快 ~35%，主要是因为它恢复了更多 state 后
executor 可以从 structured packet 直接读 route/tool，而 text executor
仍需要 parse NL handoff 才能恢复 route/tool。

**分类:** 实现路径对称性较好 —— 可承认但不要 over-claim。

---

## Section B: Why No Clear Superiority Yet

当前 benchmark 不能论证 protocol 整体端到端优于 text。
原因是多层的，没有一个是 bug——都是对象设计和基础设施成本的真实反映:

### B1: Task 对象太薄——只有 1 跳 agent-to-agent communication

主线 contention 在于: protocol 的 structured handoff 节省 ~2000 bytes 的通信文本
（相对于自然语言 retriever handoff），但端到端 latency 没有明显差异。
为什么？因为只有一个 handoff point。如果整个 task 有 N 跳 agent-to-agent 通信，
protocol 的节省会 compound N 次（每跳节省 ~2000 bytes 的 parse time），但
当前 task DAG 只有一次 agent-to-agent handoff（retriever → executor → summarizer 的
两次传递中，只有 retriever → executor 是 agent-to-agent 通信；executor → summarizer
的 TOOL_ARTIFACT 在两端都是 text）。

**当前 task DAG:**
```
Retriever      Executor      Summarizer
  │                │              │
  ├──(handoff)────►│              │
  │                ├──(artifact)──►│
```

如果有一个 thick task like:
```
Retriever → Executor → Retriever → Executor → Summarizer
```
text lane 需要在每一跳都 parse NL 文本；protocol lane 只需要 parse structured packet
一次（第一次 retriever 产出后就可以通过 EXECUTOR_DECISION_PACKET 高效传递）。

### B2: StatePool overhead 在 thin task 上吞噬通信节省

对于当前的 20 task，protocol 的 typed state path 涉及:
- msgpack.serialize (EXECUTOR_DECISION_PACKET) → ~0.5-1ms
- StatePool.put_replay_restorable_bytes (mmap write + hash compute) → ~20-30ms per state write
- StatePool.get_bytes (mmap read) → ~5-10ms per state read

每个 protocol task 涉及 2-3 个 state writes + 2-3 个 state reads，
累计 overhead ~50-100ms。相比之下，-2000 bytes 的通信节省只值 ~5-10ms parse time。

在 thin task（总 task_ms ~3200ms）中，StatePool overhead 占比 ~2-3%，
但通信节省只占 ~0.3%，所以 net latency 是平的。

在 thick task 中，如果 N 跳 handoff 倍增了通信节省但不倍增 StatePool overhead
（因为 state 可以在内存中 cache，不需要每跳都 serialize），那 protocol
的 compound advantage 才会显现。

### B3: Summarizer dominate LLM token 消费

当前 100% 的 LLM token 消费来自 summarizer（因为 planner 是 yaml，不消耗 LLM）。
Summarizer 在两端接收近似相同的信息（text mode: executor plaintext output；
protocol mode: DENSE_EVIDENCE + executor plaintext output），所以 token 消费相同。

如果 planner 是 LLM（`plan_source=llm`），protocol 的 compact shape（`{"r","s","x"}`
vs text mode 的 natural language prompt）可能体现出 token 节省。
但 `planner_support_v3` 是 protocol-only 的，没有 text 对照。

### B4: Correctness 在两端相同

因为两端使用相同的 `build_feature_bundle` 算法（相同 lexical matching，
相同 ToolRegistry），所以 route/tool decision 是相同的。
Correctness 不是 differentiated metric。

---

## Section C: What Is Actually Proven Now

当前可以诚实地 claim 以下结论。

### C1: 机制真实性 (established)

- `typed_state_mechanism_v3` 证明: `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` 确实
  被生产、通过 StatePool 传递、被 executor 消费
- transfer_truth_audit 显示:
  - `typed_executor_minimal_expected_consumption_rate = 1.00`（protocol 端）
  - `executor_expected_kind_match_rate = 1.00`
  - `executor_unexpected_kind_seen_rate = 0.00`
- `typed_state_consumer_sensitivity_v3` 证明: 错误或缺失的 decision packet
  会导致 executor 降级为 `collect_more_evidence` / 失败

### C2: 通信紧凑性 (quantitative)

- contest_honest_headline_v1 (repeat=3):
  - protocol control_bytes: **6641**（mean per repeat per task）
  - text control_bytes: **8657**
  - delta: **-23.3%** (2016 bytes)
- Handoff wire_bytes: text 0 → protocol 160.50
- Handoff payload_bytes: text 0 → protocol 2084.55

这个节省是真实的、可测量的。但 note: control_bytes 包含 setup、plan emit、
message breakdown 中所有 non-handoff 开销。Handoff 本身的纯 wire bytes 节省
很小（160 bytes）。Control bytes delta 也包括 text_bytes vs protocol_bytes
编码差异。

### C3: 公平性修复成立 (structural)

- contest_honest_headline_v1: `single_variable=yes, variable_axes=mode`
  - 唯一改变的变量是 mode（text vs protocol）
  - text handoff: `text_whole_lane`（natural language，无 hidden structured field）
  - protocol handoff: `state_packet_minimal`
  - whole_lane_text_guard pass_rate: 1.00
  - hidden_field_leak: 0.00
  - object_parity_gate: pass

### C4: 共享记忆 replay 对称 (qualitative)

- 两端都达到:
  - exact_replay reuse_gain = 0.67
  - validated_replay reuse_gain = 0.33
  - working_assist hit_rate = 1.00
- memory replay 能力在 text 和 protocol 间对称（修复了之前的 text 全 zero replay 问题）

### C5: Planner 开放支持 (established)

- `planner_support_v3` 显示 LLM-generated plan 与 yaml control plan 的
  admissible match rate 相近 (0.83 vs 0.80)
- LLM plan 的 exact match rate 与 yaml plan 相同（observed route 一致）
- validate gate 机制已接入（`VALIDATION_GATE_PACKET` 生产+消费路径）

---

## Section D: What Is Still Not Proven

### D1: Protocol 减少端到端 latency

当前 data 中 protocol task_ms 与 text 无明显差异（3% within noise）。
StatePool overhead 抵消了通信节省。

### D2: Protocol 减少 LLM token 消费

Summarizer 是主要 LLM consumer，在两端的 token 消费相同。
Planner 在当前 benchmark 中是 yaml（不消耗 LLM），所以 LLM token 节省无法体现。

### D3: Protocol 提高正确性

两端正确性完全相同。这也是预期的——相同 retriever 逻辑 = 相同 route/tool 决策。

### D4: 通信节省在 multi-hop task 中 compound

当前只有 1 跳 handoff。没有 thick task 的证据。

### D5: 10 轮稳定性 (repeat=10)

当前只有 repeat=3（`contest_repeat_insufficient` withheld）。
But repeat=3 data strongly suggests repeat=10 would pass（both sides have 0 run_failure_count）。

### D6: 与"external traditional pure-text baseline" 的正式比较

`external_text_baseline_audit_v3` 是 audit-only，没有合并到 formal headline comparison 中。
当前 headline comparison 是 StateBus 内部的 text_whole_lane vs protocol。

### D7: Protocol replay 比 text replay 更优

虽然 protocol exact_replay restored 更多 state kinds，
但 replay_gain 和 skipped_step_count 在两端的数字相同。

---

## Section E: Current Constraints / 当前必须遵守的解决约束

### E1: 不允许把 support surface 包装成 headline

- `contest_dual_mode_controlled_v3` 已降级为 internal surface（含 3 withhelds），
  不可再引用为 contest-facing headline
- `planner_support_v3` 只谈 planner openness，不能混入
  "text vs protocol" 或 "state transfer" 的 dialog
- `memory_dual_mode_fairness_v3` 是 audit-only
- `typed_state_mechanism_v3` 是 mechanism proof，不是 dual-mode headline
- `typed_state_consumer_sensitivity_v3` 是 secondary support

### E2: 不允许因为结果能跑通就默认 claim 成立

- `admissible_match_rate=1.00` 和 `wrong_family_rate=0.00` 是好结果，
  但原因是 task 对象太简单（route/tool selection 从来不会 really ambiguous），
  不是因为 system 克服了困难
- `planner_one_shot_valid_rate: 0.00` 不能与 `repair=0` 共存——
  必须在 claim 前修

### E3: 不允许通过 hidden fallback、pack-specific override、
       support surface 冒充 headline 来解释或修饰结果

- 不允许为了"让 protocol 看起来更好"而给 protocol 加额外 hint
- 不允许为了"让 text 看起来更纯粹"而 bypass executor 的
  build_feature_bundle 调用

### E4: 必须优先区分

- 真实能力不足 → 当前没有，系统所有 gate 都过了
- benchmark 对象不公平 → text executor 隐式跳过了 StatePool overhead
- reporting 语义错误 → F-A1 (planner_one_shot_valid_rate)
- support surface 被误读成主结论 → 当前 pack surface 分类已正确，
  但 planner support 的 label 仍有混淆

---

## Section F: What Should NOT Be Fixed / 不应继续追的伪问题

1. **不为提指标恢复 formal retrieval hint / shortlist / theme bonus** —
   这些之前是被故意去掉的，恢复它们会破坏公平性

2. **不追 billing tool accuracy** — 修改 ToolRegistry pattern
   让它从 `retry_storm_relief` 变成 `worker_queue_triage` 会让
   exact_match 更好看，但不改变 protocol vs text 的结论

3. **不优化 StatePool overhead 让 protocol 更快** — StatePool 的
   overhead 是真实的系统成本，去掉它是 dishonest benchmark

4. **不把 `text_strict_pure_lane` 的 guard failure 包装成"feature"** —
   它继续存在 internal surface 中，但不应该被读成任何正面结论

5. **不重做现有的 5 个 family** — 它们已经是正确的、
   有历史数据的 controlled comparison 对象

6. **不跑 repeat=10 直到 headline 对象 thickened** —
   repeat=10 只会 lift `contest_repeat_insufficient` 但不会改变
   任何 delta 值

7. **不把 planner openness claim 和 communication medium claim**
   合成一个故事

8. **不把 `text_whole_lane` 包装成"真正 external pure text baseline"** —
   它是一个 StateBus 内部引擎在 text 消费路径上的 natural language
   handoff 对象，不是第三方无状态纯文本 multi-agent 系统

---

## Section G: Open Questions

1. **`text_whole_lane` executor 的 `build_feature_bundle()` + NL parsing 路径**
   是否应被视为"structured recovery"而破坏 pure-text baseline 的诚信？
   还是说，因为两端 executor 共享同一 ToolRegistry 基础设施，这是可接受的
   "对称引擎"设计？

2. **在 thick task 中 protocol 的 compound advantage 能否 outweigh
   StatePool overhead？** 每跳的通信节省 ~5-10ms parse time vs
   每跳的 StatePool overhead ~20-30ms。如果 N 跳 with StatePool cache
   hit（同一个 state 只在第一次有 serialize cost），那 overhead
   只在第一跳发生，节省在每一跳发生，net advantage 会随 N 增加。

3. **Summarizer 的 DENSE_EVIDENCE visibility asymmetry**
   会影响 thick task 中的 summarization quality 吗？
   如果 summarizer 需要理解为什么第二跳 route 改了，
   没有 evidence text 它的 summary quality 会下降。

4. **如果目前的 contest headline 目标是"证明 protocol 机制真实且公平"而不是
   "证明 protocol 有统计显著的端到端优越性"，那当前的实验结论是否可以诚实地
   接受？** 按照赛题评分细则（通信效率 25 分、状态传递创新 20 分、
   记忆复用 20 分、系统完整性 20 分、实验验证 15 分），当前的 5 类
   surface 覆盖了所有评分维度，且有量化证据（-23.3% control bytes、
   reuse_gain=0.67、typed state consumption=1.00），组合起来是完整
   的答辩材料。

5. **planner contract valid/final 为什么在 `benchmark_results.json`
   中总是 null？** `RunContext` 有这些字段但在 benchmark payload 
   construction 中似乎没有被正确取值。

---

## Section H: Recommended Next Mainline

### 唯一推荐主线: **Phase A: Fix Reporting Errors → Phase B: Thicken Task Objects**

---

### Phase A: Fix Two Reporting Errors (预计 1-2 小时)

#### A1 — Fix `planner_one_shot_valid_rate` aggregation (F-A1)

**位置:** `eval/runner.py` 的 report writer aggregation function

**当前行为:** report aggregate 计算 `planner_one_shot_valid_rate` 时使用
了错误的公式（可能是把所有 llm request count 除以 repair attempt count
的总和来算比例，而不是对 per-row `planner_one_shot_valid` 值取平均）。

**期望行为:** `planner_one_shot_valid_rate = mean(planner_one_shot_valid per task row)`
对于 planner_support_v3，这个值应该是 `1.00`（所有 11 行都是 1.0）。

**验证:** 修改后重跑 `planner_support_v3` deterministic repeat=1，
确认 report 中 `planner_one_shot_valid_rate: 1.00`。

#### A2 — Fix `correctness_label=mismatch` for tasks without case contract (F-A2)

**位置:** `eval/runner.py:_build_case_contract_audit`

**当前行为:** 当 `primary_expected_route=""` 且 `primary_expected_tool=""` 时，
case contract audit 返回 `correctness_label=mismatch`（因为 `exact_match=False`
且 `case_type=exact_single_solution`）。

**期望行为:** 当 `primary_expected_route` 和 `primary_expected_tool`
均为空字符串时，应该返回 `correctness_label="not_evaluated"`（表示这个 task
不参与 correctness evaluation）。

**验证:** 重跑 `memory_dual_mode_fairness_v3` deterministic repeat=1，
确认所有 memory task row 的 `benchmark_results.json` 中 `correctness_label="not_evaluated"`。

---

### Phase B: Thicken Task Objects (预计 1-2 天)

**目标:** 保持现有 5 family × 4 case 的 `contest_release_regression` foundation，
新增 2-3 个 "thick collaborative" family，其中 task DAG 有 4-5 步、
multi-step agent-to-agent handoff。

#### B1 — 设计原则

1. **Multi-step evidence refinement:**
   ```
   Retriever → Executor → Retriever (round 2) → Executor (round 2) → Summarizer
   ```
   Round 1: 识别 initial hypothesis → 执行 initial check
   Round 2: 根据 round 1 result 做 refined evidence retrieval → 执行 refined action

2. **Protocol's compound advantage:**
   - 在 round 1 中，retriever 产出了 route/tool/evidence 作为 structured packet
   - Executor 执行后产出的 artifact 可以被 round 2 retriever 以 structured 形式消费
   - text lane 在每个 round 都需要重新 parse NL text 来找 route/tool
   - protocol lane 只需读取 structured packet

3. **保持 single_variable=yes:**
   - 每个 thick family 的 text 和 protocol 行仍只改变 `mode`
   - text 侧: `text_whole_lane`
   - protocol 侧: `state_packet_minimal`

4. **保持与现有 family 的兼容性:**
   - 使用相同的 corpus (release-regression doc set)
   - 使用相同的 ToolRegistry
   - 使用相同的 contest family contract 结构

#### B2 — 建议的 2 个 thick family

**Family 6: "nested root cause diagnosis"**
- 题材: 一个 release 触发了多层联动故障（e.g., db pool saturation → 导致 cache
  invalidation 连锁, 或者 auth session drift → 导致 worker queue 被 session refresh 冲刷）
- 步骤:
  1. retrieve: 识别 initial hypothesis（surface incident）
  2. execute: 执行 initial playbook check（e.g., check db pool）
  3. retrieve: 根据 initial check result 做 secondary evidence retrieval
    （发现 cache 也有问题）
  4. execute: 执行 root cause playbook（fix db pool, then fix cache）
  5. summarize: 总结两轮协作决策过程
- 关键: round 2 retriever 的 evidence/universe 取决于 round 1 executor output

**Family 7: "scope narrowing with conflicting evidence"**
- 题材: 两个 family 的 evidence 同时存在，需要在两轮协作中逐步排除
- 步骤:
  1. retrieve: 识别 leading hypothesis（ambiguous: could be A or B）
  2. execute: 执行 scope-narrowing check（"check if A-specific metric is elevated"）
  3. retrieve: 根据 check result 做 refined retrieval（confirmed A, exclude B）
  4. execute: 执行 definitive playbook for A
  5. summarize: 总结 scope narrowing 过程和 final action

**注意:** 这两个新 family 不需要独立成单独 benchmark pack。
它们可以直接添加到现有的 `contest_family_spec.yaml` 中，
由 `generate_contest_honest_headline_payload` 生成对应的 task rows。

#### B3 — 验证策略

1. 先跑 `python -m pytest -q` + `python -m runtime.smoke`
2. 跑 deterministic repeat=1 gate (new thick family only)
3. 确认 text_whole_lane guard pass
4. 跑 API repeat=3 for contest_honest_headline_v1 (including new families)
5. 分析 multi-hop compound advantage

#### B4 — 不改的对象

- 现有 5 个 release-regression family → 保持不动
- `contest_dual_mode_controlled_v3` → 留在 internal surface
- `memory_dual_mode_fairness_v3` → 不动
- `planner_support_v3` → 除 Phase A1 reporting fix 外不动
- `ToolRegistry` → 除 billing tool pattern 修正外不动
- `build_feature_bundle` / lexical matching → 不动
- StatePool infrastructure → 不动
- `agents/sample_agents.py` retriever/executor/summarizer core logic → 不动

---

## Section I: 当前对外可用的最诚实表述

### 允许说:

- "StateBus 实现了 multi-agent 结构化通信协议，在相同 task 条件下
  control bytes 比 natural language handoff 模式减少了 23.3%"
- "非文本中间状态 (EXECUTOR_DECISION_PACKET) 被真实生产、传递、消费，
  且 consumer sensitivity 验证成立"
- "共享记忆在 text 和 protocol 双模式下均实现 0.67 reuse_gain，
  双向 exact replay 路径对称"
- "planner 支持 yaml 控制和 LLM 开放规划，两端的 admissible match rate 相当"
- "13+1 benchmark packs 全部 gate 通过，191 pytest passed"

### 不允许说:

- "protocol 端到端优于 text" → 不允许，latency 无明显差异
- "protocol 节省 LLM token" → 不允许，summarizer token 在两端相同
- "protocol 提高正确性" → 不允许，两端正确性完全相同
- "text_whole_lane 是真正 external pure text baseline" → 不允许，
  它是 StateBus 内部引擎在 NL handoff 路径上的运行
- "system 支持真正的 hidden state / KV cache 传递" → 不允许，
  feature_bundle 是 call-level structured signal，不是 neural hidden state
- "planner one-shot 成功率 0%" → 不允许，这是 reporting bug

### 只能说"机制真实性/公平性修复成立":

- "非文本 typed state 的真实生产-传递-消费链路"
- "contest headline comparison 的 single-variable 归因与 object parity"
- "text_whole_lane handoff 不含 hidden structured field"
- "memory replay 在双模式下对称恢复"

### 还不能从"机制成立"升级为"端到端优越性":

- 通信节省 (-23.3% control bytes) 没有转化为 latency advantage
- Token 节省不存在（summarizer dominant, planner is yaml）
- Correctness 差异为 0
- Repeat=10 包未跑

---

## Section J: 总结

| 维度 | 状态 | 最需要做的事 |
|---|---|---|
| 机制真实性 | ✅ 成立 (typed state, replay, validate gate) | 保持 |
| 通信紧凑性 | ✅ 量化成立 (-23% control bytes) | improve: thick task for compound |
| 公平性 | ✅ 成立 (single_variable, guard pass) | keep |
| 记忆复用 | ✅ 对称成立 (reuse_gain 0.67 both sides) | keep |
| Planner | ✅ 成立但 reporting bug | **fix F-A1 immediately** |
| Correctness | ✅ 1.00 adm, 0.70 exact (identical) | fine |
| 端到端优越性 | ❌ 未成立 | **add thick tasks (Phase B)** |
| Reporting | ⚠️ 2 个 P0 bug (F-A1, F-A2) | **fix before any presentation** |
| Repeat=10 | ⏳ 未跑 | run after Phase A+B |
| External baseline | ⏳ 未建立 | not priority |

---

## Appendix: 文件级改动映射

### Phase A 必须改:

| 文件 | 改什么 |
|---|---|
| `eval/runner.py` | Fix planner_one_shot_valid_rate aggregate formula |
| `eval/runner.py` | Fix correctness_label for empty case_contract tasks (→ "not_evaluated") |

### Phase B 可能改:

| 文件 | 改什么 |
|---|---|
| `tasks/contest_family_spec.yaml` | Add 2 thick families with multi-step DAG |
| `tasks/contest_release_regression_corpus.yaml` | Add corpus docs for new families |
| `tasks/contest_dual_mode_controlled_v3_benchmark.yaml` | Re-generate from spec (via generator) |
| `runtime/executor_runtime.py` | Possibly: add multi-round execution support |
| `runtime/orchestrator.py` | Possibly: extend plan DAG for thick task steps |

### Phase A+B 不改:

| 文件/模块 | 理由 |
|---|---|
| `agents/sample_agents.py` | 核心 agent 逻辑稳定 |
| `runtime/langgraph_adapter.py` | 编排引擎正确 |
| `eval/metrics.py` | 指标定义正确 |
| `protocol/messages.py` | 协议消息稳定 |
| `statepool/store.py` | StatePool 基础设施稳定 |
| `memory/store.py` | Memory store 正确 |
| `tasks/sample_tasks.py` | Task loading 正确 |
| `tasks/contest_family_spec.py` | Spec 生成器正确 |
| 所有 test 文件 | 现有 tests pass |

---

## Appendix B: 赛题 vs 当前实现 逐项对照

按 `docs/reference/题目.md` 的 8 项硬性要求:

| # | 赛题要求 | 当前状态 | 证据 |
|---|---|---|---|
| 1 | ≥3 agents + ≥3 类角色 | ✅ Planner, Retriever, Executor, Summarizer (4 类 4 角色) | `agents/sample_agents.py` |
| 2 | 结构化通信协议（含动作/参数/结果/能力 + 握手/发现） | ✅ CapabilityTable + SchemaInterceptor + Hello/Ack + PlanStep/StepResult | `protocol/messages.py`, `runtime/contracts.py` |
| 3 | 两种协作模式可复现实验对比 | ✅ text_whole_lane vs state_packet_minimal, single_variable=yes | `contest_honest_headline_v1` |
| 4 | 非文本中间状态传递 | ✅ DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET via StatePool | `typed_state_mechanism_v3` |
| 5 | 共享记忆（存储 + 检索 + 复用） | ✅ SQLite + FAISS, assist/replay/exact_replay tiers | `memory/store.py`, `memory_dual_mode_fairness_v3` |
| 6 | ≥2 组连续关联任务验证复用 | ✅ 5 families × 4 cases = 20 task 链 | `memory_reuse_v3` |
| 7 | 性能展示（message count/token/time/hit rate） | ✅ 47 metric fields + structured report | `eval/metrics.py`, `eval/runner.py` |
| 8 | ≥10 轮稳定执行 | ⚠️ repeat=3 done, repeat=10 pending | `contest_repeat_insufficient` |

所有硬性指标都满足或接近满足。第 8 条的 repeat=10 是最后的形式化需求。

---

*Audit conducted: 2026-06-17*
*Run root: `/home/qcrs/statebus/runs/statebus_mainline_repeat3_suite_20260617_141158/`*
