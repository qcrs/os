# StateBus 全系统审计报告

日期：2026-06-15
数据源：`/home/qcrs/statebus/runs/api_smoke_then_v3_20260615_104805/v3_api_repeat3_suite/`
审计方法：赛题原文 → 代码实现 → 任务定义 → Benchmark 合同 → 实验结果，逐层对照，定位不一致。

本文档**仅描述问题**，不包含修复建议。

---

# 一、赛题要求逐条对照

## 1.1 多 Agent 系统要求（系统完整性 20 分）

| 编号 | 赛题原文要求 | 代码实现 | 实际情况 |
|---|---|---|---|
| A1 | 不少于 3 个 Agent，覆盖规划/检索/执行/总结等 3+ 角色 | `agents/sample_agents.py` 定义了 PlannerAgent、RetrieverAgent、ExecutorAgent、SummarizerAgent 四个类 | **PlannerAgent 在所有核心 benchmark 中从未被调用。** 代码路径存在（`PlannerAgent.plan_task()` at :255），但 `plan_source` 默认值 `"yaml"` 绕过了它。见问题 P1 |
| A2 | 完成一个包含多步骤处理过程的复杂任务 | `build_plan()` 生成固定 3 步 retrieve→execute→summarize | 所有任务的 plan 结构完全相同。不存在"多步骤"的变化——永远是 3 步。见问题 P3 |

## 1.2 结构化通信要求（通信效率 25 分）

| 编号 | 赛题原文要求 | 代码实现 | 实际情况 |
|---|---|---|---|
| B1 | 通信内容至少包含动作类型、输入参数、返回结果、能力描述 | `protocol/messages.py` 定义 Hello/Capability/Plan/PlanStep/StepResult/Ack/Error/MemoryCommit/Heartbeat | 消息结构存在。但所有 task 的消息数 text 和 protocol 相同（252.00 条），因为两个模式跑的是同一个固定 3 步流水线 |
| B2 | 支持基本的握手、能力发现或协议映射 | `runtime/contracts.py` 定义 CapabilityTable 和 SchemaInterceptor | CapabilityTable 在 `build_sample_agents()` 中静态注册，运行时没有动态 Agent 发现或协商。Agent 的数量和角色在启动时就固定了 |
| B3 | 不得仅通过自然语言长文本直接透传全部协作信息 | `runtime/executor_runtime.py` 定义了 9 种 transfer strategy，protocol 侧走 StateRef 而非 inline text | 这条是满足的。但 protocol summarizer 又 `_build_protocol_summary_handoff()` 把结构化信息展开成文本喂给 LLM，等于"用结构化协议传输→展开成文本→喂给 LLM"。见问题 P7 |

## 1.3 双模式要求（实验验证 15 分）

| 编号 | 赛题原文要求 | 代码实现 | 实际情况 |
|---|---|---|---|
| C1 | 同时支持"纯文本协作模式"和"结构化协议协作模式" | `runtime/task_profile.py` 定义 `TASK_MODES = ("text", "protocol")`，各 Agent 按 mode 分发 | 双模式存在且跑通。但两个模式的差异远超"通信格式"——prompt、state 产出、executor 输入路径、summarizer 输入全部不同。见问题 P8 |
| C2 | 在相同任务条件下完成可复现实验对比 | `contest_dual_mode_controlled_v3` 为每个 case_id 配 text+protocol 各一行 | 实验跑通。但 `single_variable: no`，`variable_axes: [mode, handoff_object]`，两个变量同向变化，无法归因。见问题 P9 |

## 1.4 非文本状态传递要求（状态传递创新 20 分）

| 编号 | 赛题原文要求 | 代码实现 | 实际情况 |
|---|---|---|---|
| D1 | 实现 embedding/语义向量/隐藏状态或其他中间表示在 Agent 间直接交换 | `statepool/store.py` 实现 mmap StatePool，`protocol/messages.py` 定义 StateRef，executor 消费 DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET | 机制存在且通过 consumer sensitivity 的存在性验证。但缺少正确的效率对比。见问题 P11 |
| D2 | 说明生成方式、传递方式、接收方式及后续使用方式 | Retriever 生成 → StatePool mmap → Executor 读 msgpack → 用于 route/tool selection | 代码上可以说明这条链路。但 5 个 task family 永远只有一个正确答案（route_hint 预写在文档里），executor 用或不用 EXECUTOR_DECISION_PACKET 对正确率没有影响——丰富度被任务设计抵消了。见问题 P6 |

## 1.5 共享记忆要求（记忆复用效果 20 分）

| 编号 | 赛题原文要求 | 代码实现 | 实际情况 |
|---|---|---|---|
| E1 | 保存为统一的记忆单元，记录 ID/来源 Agent/时间/主题/摘要 | `memory/store.py` SQLite schema 含所有必填字段 | 满足 |
| E2 | 支持按关键词/标签或语义相似度检索 | FTS5 + FAISS 向量检索 | 满足 |
| E3 | 不同 Agent 在后续任务中直接复用已有记忆 | `orchestrator.py` 的 replay gate（`resolve_skip_retrieve_execute` / `resolve_skip_execute`） | memory_policy_controlled_v3 上 replay gate passed。但在 contest 包（最重要的 formal headline）上 memory 被全局关闭。见问题 P4 |

## 1.6 实验验证要求

| 编号 | 赛题原文要求 | 实现 | 实际情况 |
|---|---|---|---|
| F1 | 统计消息次数 | `orchestrator.py` `message_count` | 有产出，但与 UDS 路径有交互（见 ANOM-1） |
| F2 | 统计文本通信 token 开销 | `orchestrator.py` `llm_total_tokens` | 有产出。protocol summarizer 比 text 多 23%（见 ANOM-4） |
| F3 | 统计非文本状态传递次数及数据规模 | `orchestrator.py` `handoff_nontext_ref_count` + `handoff_nontext_bytes` | 有产出。但 text handoff bytes 被错误地清零或等于 protocol 值（见 ANOM-1, ANOM-2） |
| F4 | 统计单任务总耗时 | `task_ms` | 有产出 |
| F5 | 统计共享记忆命中率 | `memory_hit_rate` | 指标含义与命名不符——assist 路径和 replay 路径的"命中"定义不同（见 P10） |
| F6 | 统计整体性能提升情况 | `reuse_gain` | memory_dual_mode_fairness 中 protocol 侧为负数（见 ANOM-7） |

---

# 二、P0 级问题（核心功能未运行 / 设计决定导致 benchmark 不能回答赛题核心问题）

## P0-1：Planner 在所有核心 Benchmark 中从未被调用

**代码定位**：
- 默认值：`tasks/sample_tasks.py:283` — `plan_source: str = "yaml"`
- 归一化：`tasks/sample_tasks.py:743` — `normalize_plan_source(item.get("plan_source", "yaml"))` → 缺失/空值 → `"yaml"`
- Plan 硬编码：`tasks/sample_tasks.py:529-568` — `build_plan()` 返回固定的 `Plan(steps=[retrieve, execute, summarize])`
- 调度短路：`runtime/orchestrator.py:1231-1233` — `if plan_source == "yaml": return build_plan(task)` → 跳过 `PlannerAgent.plan_task()`

**受影响范围**：`contest_dual_mode_controlled_v3` 40 行、`memory_dual_mode_fairness_v3` 40 行、`typed_state_mechanism_v3` 8 行、`typed_state_authenticity_v3` 40 行、`typed_state_full_rich_audit_v3` 40 行、`carrier_microbench_v3` 40 行、`external_text_baseline_audit_v3` 4 行、`text_definition_audit_v3` 40 行、`memory_reuse_v3` 4 行、`memory_policy_controlled_v3` 4 行、`typed_state_consumer_sensitivity_v3` 40 行。**合计约 300 个 task 全部绕过 Planner。**

只有 `planner_support_v3` 的 5 个 llm 行和 `open_planner_support` / `open_validation` 的 8 个行调用了 Planner。

**数据表现**：contest 包的 `planner_tokens = 0.00`。planner_support_v3 中 llm 行跑出了 `task_ms=45260ms`（vs yaml 行 ~3500ms），因为 Planner 做了真实 LLM 调用。

**与赛题的矛盾**：赛题要求"覆盖规划角色"。PlannerAgent 类存在、代码路径存在（`PlannerAgent.plan_task()` 含 prompt 构造、LLM 调用、输出解析），但 benchmark 从未执行这条路径。

## P0-2：LLM Planner 即使被调用也被限制为固定 3 步模板

**代码定位**：`agents/sample_agents.py:1315-1352` — `_plan_from_llm_output()` 校验：
```python
expected_contract = _expected_plan_contract(task)    # :1377-1412 — 固定 3 步合同
if len(steps) != len(expected_contract):              # :1326 — 必须正好 3 步
    raise ValueError("must contain exactly 3 steps")
if step_id != expected_step_id:                        # :1331 — 必须是 retrieve/execute/summarize
    raise ValueError("step contract mismatch")
```

**`_expected_plan_contract()` (:1377-1412) 与 `build_plan()` (:529-568) 内容完全相同**。LLM Planner 的输出必须匹配硬编码合同。Planner 不能增减步骤、不能修改 owner_agent、不能改变 action 顺序。

**后果**：即使未来启用了 `plan_source="llm"`，Planner 的智能也完全被这个合同校验消除了。它只是一个 yaml→json 翻译器。

## P0-3：Plan 结构被固定——没有动态任务分解

所有任务无论复杂度和类型，都强制走 `retrieve → execute → summarize` 三步。该结构写死在两个地方：
- `sample_tasks.py:529-568` (`build_plan`)
- `agents/sample_agents.py:1377-1412` (`_expected_plan_contract`)

**赛题要求"完成一个包含多步骤处理过程的复杂任务"**——但"多步骤"在实现中被固定为"永远是 3 步"。

## P0-4：Memory 在最重要的 formal headline 包上被全局关闭

**代码定位**：`contest_dual_mode_controlled_v3_benchmark.yaml` 中所有 40 个 task 全部 `runtime_reuse_contract: reuse_disabled`

**后果**：赛题要求 F1（验证记忆复用在"减少重复计算、降低协作开销和提升任务效率"方面的效果）在 contest 包上无法被验证。contest 包是当前 formal headline 的唯一入口，它关掉了 memory 意味着所有 text vs protocol 的对比数据中不包含任何 memory reuse 贡献。

**数据表现**：contest 包的 `memory_hit_rate=0.00`、`reuse_gain=0.00`。这两个零值不是因为协议效果差，而是因为根本没开。

---

# 三、P1 级问题（任务设计导致 benchmark 无法展示协议优势）

## P1-1：Corpus 全部预标签——检索变成了查字典

**代码定位**：`tasks/contest_release_regression_corpus.yaml` — 32 个文档，每个文档显式标注：

```yaml
- doc_id: rr-checkout-incident
  route_hint: db_pool_saturation        # ← 答案写在这里
  tool_name: tool.db_pool_triage        # ← 工具也写在这里
  task_theme: contest_release_checkout_regression
  tags: [release, checkout, latency, database]
  text: |
    ...incident narrative...
```

**检索的执行路径**：
1. YAML 预设 `corpus_doc_ids: [rr-checkout-incident, rr-checkout-metrics, rr-checkout-logs, rr-checkout-worker-false]`
2. `local_corpus.py:retrieve_corpus_docs()` 按 doc_id 直接查找
3. `local_corpus.py:resolve_corpus_feature_hint()` 直接读文档的 `route_hint` 字段
4. `executor_runtime.py:build_feature_bundle()` 用这个 hint 做 route/tool 决策

**检索没有做任何语义检索推理**。它不需要阅读文档正文、不需要做证据链推理、不需要在多 candidate 之间选择。答案是文档元数据的一部分。

**数据表现**：contest 包的 `exact_match_rate=0.85` 在两个模式下完全一致。这表明 route/tool 正确率不受通信格式影响——因为答案不是搜出来的，是在 YAML 里写好的。

## P1-2：5 个 task family 各自只有一个正确答案

| family | 正确答案(route) | 正确答案(tool) | distractor 文档的作用 |
|---|---|---|---|
| checkout | db_pool_saturation | tool.db_pool_triage | rr-checkout-worker-false 提供替代假说，但预期答案不变 |
| auth | auth_session_drift | tool.auth_session_repair | rr-auth-rate-limit-false 提供替代假说，预期答案不变 |
| inventory | cache_invalidation | tool.cache_invalidation_playbook | rr-cache-replica-false 提供替代假说，预期答案不变 |
| billing | worker_queue_starvation | tool.worker_queue_triage | rr-billing-db-false 提供替代假说，预期答案不变 |
| deploy | db_pool_saturation | tool.db_pool_triage | rr-deploy-worker-false 提供替代假说，预期答案不变 |

**"distractor" 和 "ambiguous" 复杂度等级的 task 仍然要求同一个正确答案**。区别只是多给了一个 `-false` 文档，但如果系统正确选择了预标签文档的 route_hint，distractor 文档根本不会被选中。

**后果**：协议模式下精确的 route metadata 传递没有带来正确率提升——因为 text 模式也能同样准确地从预标签文档中拿到答案。协议的结构化精度优势在只有 5 个候选 route 且有预标签的场景下完全无法体现。

## P1-3：Query 文本本身就指向了正确答案

每个 task 的 query 字段直接嵌入了 route 的关键词：
- `"connection pool waits and slow orders"` → db_pool_saturation
- `"issuer mismatch stale jwks"` → auth_session_drift
- `"dropped aggregate invalidation rate"` → cache_invalidation
- `"growing queue depth...retry storms"` → worker_queue_starvation

即使完全不读 corpus 文档，仅凭 query 文本的词法匹配就能猜到正确答案。`ToolRegistry.retrieve_candidates()` 的默认行为就是做 `query_text` 的词法匹配。

**后果**：协议传 EXECUTOR_DECISION_PACKET 里的 route metadata 对于正确率是冗余的——text 侧的 executor 自己也能从 query 文本中匹配出同样的 route。

## P1-4：Task 没有跨 family 的鉴别诊断压力

所有 5 个 family 的 task 都是"family 内对比"——每个 task 的目标 route 就是在它自己的 corpus 文档里标注的那个 route。不存在"一个 task 需要从 5 个 route 中选一个正确"的情况。因为 system 在每个 task 上都被预先告诉要读哪些 `corpus_doc_ids`，而每个 doc 的 `route_hint` 都指向同一个 route。

**真正的多 Agent 通信压力在于**：Retriever 找到多条证据指向不同 route 时，需要把完整的证据链 + 置信度传递给 Executor 和 Summarizer 做决策。但当前 benchmark 中没有这种压力——所有证据都指向同一个结论。

---

# 四、P2 级问题（代码实现中的结构性效率矛盾）

## P2-1：`build_feature_bundle()` 在 protocol executor 路径被冗余调用

**调用链**：
1. RetrieverAgent → `build_feature_bundle()` → 产出 EXECUTOR_DECISION_PACKET（含 route/tool/signals/doc_ids/hash），写入 StatePool
2. ExecutorAgent → `_feature_bundle_from_executor_decision_packet()` (`executor_runtime.py:1689-1734`) → 内部调 `build_feature_bundle()` (`executor_runtime.py:1696`) → **重新做一遍完整的 tool candidate search + evidence hashing**
3. 然后把 deserialized packet 的字段覆盖回 bundle（`executor_runtime.py:1704-1719`）

**对比 text_strict_pure_lane 路径**：只有一次 `registry.retrieve_candidates()` 调用，不调 `build_feature_bundle()`。

**数据表现**：typed_state_mechanism_v3 中 `state_packet_minimal` 的控制面比 `natural_handoff_text` 多 95 bytes，其中一部分来自这次冗余的 feature construction。

## P2-2：Protocol Summarizer 把结构化 metadata 展开成文本——token 反增

**代码路径**：
1. `agents/sample_agents.py:978-983` — 当 `mode != "text"` 且 `summary_contract != "protocol_handoff_audit"` 时
2. `_build_protocol_summary_handoff()` 被调用（未在当前文件中定义，但在 `sample_agents.py` 中引用）
3. 该函数把 route、route_source、route_confidence、retrieved_doc_ids、matched_signals、evidence_preview 等结构化字段展开为自然语言段落
4. 这段文本被注入到 summarizer 的 LLM prompt

**过程**：
```
结构化 EXECUTOR_DECISION_PACKET (msgpack, 1114 bytes)
  → Retriever 传给 Executor (StateRef, 161 wire bytes)
  → Executor 使用 route/tool 选择 playbook
  → Summarizer 收到时又展开成自然语言文本（~400-800 字符）
  → LLM 需要消耗更多 token 来处理这段展开文本
```

**数据表现**：contest 包中 protocol summarizer tokens = 395 vs text summarizer tokens = 321（+23%）。per-family 差异在 +19%~+26% 之间（auth +23%, billing +24%, checkout +26%, deploy +24%, inventory +19%）。**结构化的优势在最后一步被"结构化→文本→LLM"的往返抵消了。**

## P2-3：Protocol 在 3/4 的 protocol-only 内部对比中 control_bytes 更重

| pack | text baseline 侧 | protocol 侧 | delta | task 数 |
|---|---:|---:|---:|---:|
| `typed_state_authenticity_v3` | natural_handoff_text: 6767 | state_packet_minimal: 7002 | **+235** | 40 |
| `typed_state_mechanism_v3` | natural_handoff_text: 6959 | state_packet_minimal: 7054 | **+95** | 8 |
| `carrier_microbench_v3` | text_packet_minimal: 6526 | state_packet_minimal: 6683 | **+157** | 40 |
| `text_definition_audit_v3` | inline_text_handoff: 7078 | state_packet_minimal: 6741 | −337 | 40 |

**只有跨 mode 对比的 `contest_dual_mode_controlled_v3` 和 `text_definition_audit_v3` 显示 protocol 更轻。**在 protocol-only 内部对比中（只改 handoff object 不改 mode），`state_packet_minimal` 反而更重。

**根因分解**：
- state_packet 需要额外写入 EXECUTOR_DECISION_PACKET (msgpack) + 可能的 embedding_ref + replay_eligibility_ref 到 StatePool
- MemoryCommit 消息在 protocol 侧携带的 state ref 列表更长
- text_packet_minimal 和 natural_handoff_text 都是纯文本——没有 msgpack 序列化开销

## P2-4：协议模式下 StatePool 读写是多出来的固定成本

| 操作 | text_strict_pure_lane | state_packet_minimal |
|---|---|---|
| Retriever 的 StatePool 写入 | 1 次 (inline text) | 2-3 次 (evidence text + msgpack decision_packet + embedding) |
| Executor 的 StatePool 读取 | 0 次 | 2 次 (evidence_ref + decision_packet_ref) |
| msgpack 序列化/反序列化 | 0 次 | 1 次 (EXECUTOR_DECISION_PACKET pack + unpack) |
| evidence sha256 计算 | 0 次 | 1 次 (在 build_feature_bundle 内) |

每一项操作单独耗时很小，但在 3500ms 量级的 task 上，这些操作累积起来会吃掉通信节省（control_bytes -18.5%）带来的收益。

**数据表现**：contest 包 task_ms_delta = −237.99ms (−6.7%)，远小于 control_bytes_delta = −18.5%。大部分通信节省被 I/O 和计算开销吃掉了。

---

# 五、P3 级问题（Benchmark 合同设计问题）

## P3-1：Contest 包的 `single_variable` 声明与实际不符

**YAML 声明**：`single_variable: no`，`variable_axes: [mode, handoff_object]`

**实际执行**：text 行永远搭配 `transfer_strategy: text_strict_pure_lane`，protocol 行永远搭配 `transfer_strategy: state_packet_minimal`。没有任何交叉行（mode=text + state_packet_minimal 或 mode=protocol + text_strict_pure_lane）。

**后果**：无法区分"协议的优势来自 protobuf 消息格式"还是"来自于 typed state 传递"。两个变量完全共线。

## P3-2：Contest 包改变的不是"通信方式"——是整个 Agent Pipeline

两个模式下差异覆盖：
1. Planner 提示格式（自然语言 vs compact JSON）
2. Retriever 产出对象（纯 text vs typed state bundles）
3. Executor 输入路径（inline text 0 IO vs StatePool 2 reads + msgpack）
4. Executor 产出格式（纯 text actions vs typed artifact）
5. Summarizer 输入（evidence text vs structured metadata text）
6. Memory commit refs（[summary] vs [evidence, decision_packet, artifact, ...]）

**这不是"只改通信方式"。这是两套不同的 agent execution pipeline 在比较。** YAML 的 `reading_contract` 写了 "mode and handoff object differ together" 但没有说明差异有这么大。

## P3-3：memory_dual_mode_fairness_v3 的变量缠绕

YAML 声明 `variable_axes: [mode, runtime_reuse_contract, restore_object_class]`，三个变量同时变化。但它又声明自己是 "fairness/object-parity surface"——实际上由于三个变量同时变，无法归因到任何一个。

**数据表现**：protocol exact_replay 的 reuse_gain 为负数（−0.126），但无法判断是 protocol 的 restore 开销、policy 门的严格度、还是 restore_object_class 的兼容性问题导致的。

---

# 六、P4 级问题（指标/度量问题）

## P4-1：`memory_hit_rate` 的含义与命名不符

**数据**（memory_policy_controlled_v3）：
| policy | memory_hit_rate | skipped_step_count |
|---|---|---|
| memory_off | 0.00 | 0.00 |
| working_assist | 1.00 | 0.00 |
| validated_replay | 0.00 | 1.00 |
| exact_replay | 0.00 | 2.00 |

validated_replay 和 exact_replay 正确跳过了步骤，但 `memory_hit_rate=0.00`。hit_rate=1.00 只出现在 working_assist——这是 assist 路径（用记忆结果做候选提示），不是 replay 路径（直接跳过计算步骤）。

**命名问题**：`memory_hit_rate` 只度量 assist 命中，不度量 replay 命中。对外展示时会造成"记忆没有命中"的误解——实际上记忆命中了（跳过了步骤），只是 metric 没反映。

## P4-2：`handoff_bytes` 和 `handoff_payload_bytes` 重复

**代码定位**：`orchestrator.py:263-264`：
```python
self.metrics.handoff_payload_bytes += ref.length
self.metrics.handoff_bytes += ref.length          # 同一行，同一个值
```

两个不同的 metric 名字指向同一个数据。在报告中它们被作为两个独立的列展示，但数值永远相同。

## P4-3：Consumer sensitivity 的 negative control 大量未触发

SUMMARY 数据：
```
expected_negative_control_failures={'text': 0, 'protocol': 15}
failures={'text': 0, 'protocol': 3}
```

**15 个 task 被标记为应有 negative control failure，实际只触发了 3 个。** 12 个 task 本应因为缺失 EXECUTOR_DECISION_PACKET 或接收到错误 route/tool 而失败或走错，但实际上通过了。

**报告声称的 `missing_decision_failure_rate=1.00` 和真实数据 3/15=20% 矛盾。**

## P4-4：Rich helper objects 全 disable 后零 impact

60 个 task（4 种 disable × 15 个 task）全部 `failure_rate=0.00，route_misfire_rate=0.00，tool_misfire_rate=0.00`。

而报告同时声称 `feature_bundle_executor_visibility_rate=0.62，channel_snapshot_executor_visibility_rate=0.50`。

**如果 executor 真的有 50-62% 的概率"看到"这些 object，关闭它们不应该零 impact。** 这说明 visibility rate 度量的是"对象被写入 StatePool 且 executor 的 input contract 允许读取"——不代表 executor 真正使用了它们。

---

# 七、LangGraph 的角色分析

## L1：LangGraph 未增加任何多 Agent 协作能力

`runtime/langgraph_adapter.py:186-191`：
```python
graph.add_edge("planner", "retriever")
graph.add_edge("retriever", "executor")
graph.add_edge("executor", "summarizer")
graph.add_edge("summarizer", END)
```

- 无并行 — 严格顺序
- 无动态路由 — `add_edge` 硬编码，零 `add_conditional_edges`
- 无 Agent 发现 — agents 字典在构造时传入
- 所有语义逻辑在 `Orchestrator` 内

`Orchestrator._execute_plan()` 已经做了相同的线性循环。LangGraph 增加了：(1) graph state snapshot 传播（observability）；(2) 一个 engine 标签；(3) 早期失败标记。

**AGENTS.md 开发优先级中没有提到 LangGraph。** 它是工程基础设施，不是创新。

---

# 八、任务设计与 Benchmark 设计的结构性问题

## T1：所有 benchmark YAML 的任务结构完全相同

除了 5 个 family × 4 个复杂度 × 2 个 mode 的排列，所有 task row 都使用相同的模板参数。不同 task 之间只有 query/evidence_text/tags/corpus_doc_ids 不同。没有：
- 不同长度的任务链
- 需要并行 Agent 调用的任务
- 需要动态重规划（REPLAN）的任务
- 不需要检索的纯执行任务
- 不需要总结的纯检索任务

## T2：Plan source 的默认值使 Planner 在所有 pack 上被绕过

```python
# sample_tasks.py:283
plan_source: str = "yaml"

# sample_tasks.py:743
plan_source=normalize_plan_source(item.get("plan_source", "yaml"))

# sample_tasks.py:151-156
def normalize_plan_source(value):
    text = str(value or "").strip().lower()
    normalized = "yaml" if not text else text
```

**空值 → "yaml"。缺失 → "yaml"。** 只有显式写 `plan_source: llm` 才会触发 LLM 规划。

## T3：YAML plan source 模式下 Planner 的 LLM prompt 仍然被定义了但从不用

`agents/sample_agents.py:1400-1460` 定义了 text 和 protocol 两套 Planner prompt（text 用自然语言，protocol 用 compact JSON）。`PlannerAgent.plan_task()` (:255-273) 完整实现了 LLM 调用流程。但这些代码在 340 个 benchmark task 上从未执行。

---

# 九、实验结果批次问题

## R1：当前运行批次不是 live API 运行

`SUMMARY.md:7` → `LLM config: 'reused-existing-results'`

所有 12 个 `logs/benchmark_*.log` 内容相同（仅 4 行 warning）。Open surface log 为空文件。

**当前批次的所有 timing/token 数据来自之前某次运行。不能作为 formal API repeat=3 证据。**

## R2：Open surface 数据不可能来自真实 LLM

`open_system_comparison_v1/open_report.md` 显示 task_ms = 12-18ms。contest 包同类任务 task_ms = 3300-3500ms。200 倍的速度差异说明 open surface 跑的不是同样的 LLM pipeline。

不同 runtime arm（statebus_protocol_open、statebus_text_open、langgraph_native_text_open、external_text_open）的 `replay_hit_rate=0.83、skipped_step_count=1.67、reuse_gain=0.42` **完全相同到小数点后两位**——统计上不可能。这些值来自共享的确定性 stub。

## R3：Formal stability gate 要求 repeat=10，当前只跑了 repeat=3

`_contest_formal_coverage_gate()` (`runner.py:1455-1485`) 正确检查了 `repeat >= 10`。contest 包的 det10 gate 已 pass（deterministic 跑），但 API repeat=10 未跑。

---

# 十、问题影响矩阵

| 问题编号 | 影响的赛题得分项 | 影响权重 |
|---|---|---|
| P0-1 (Planner 被绕过) | 系统完整性 (20分) — "覆盖规划角色" | 高 |
| P0-4 (Memory 关闭) | 记忆复用效果 (20分) — "验证记忆复用在减少重复计算方面的效果" | 高 |
| P1-1 (Corpus 预标签) | 状态传递创新 (20分) — 协议精度优势无展示空间 | 中 |
| P1-2 (单答案) | 实验验证 (15分) — 对比数据缺乏区分度 | 中 |
| P2-1 (双重 build_feature_bundle) | 通信效率 (25分) — protocol 额外开销吃掉通信节省 | 中 |
| P2-2 (Summarizer token 膨胀) | 通信效率 (25分) — protocol 侧 token 比 text 还多 | 高 |
| P2-3 (内部对比 protocol 反重) | 通信效率 (25分) — 对内对比不支持效率 claim | 高 |
| P3-1 (single_variable 不准) | 实验验证 (15分) — 归因不能成立 | 中 |
| P4-1 (memory_hit_rate 命名) | 实验验证 (15分) — 指标解读误导 | 低 |
| L1 (LangGraph 非创新) | 系统完整性 (20分) — 不能作为加分项 | 低 |
