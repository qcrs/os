# StateBus v2 深度问题分析文档

日期：2026-07-08
分支：`feat/local-hidden-kv-prototype`
依据：代码交叉验证 + artifact mining + 诊断层抽取 + 赛题评分细则

---

## 0. 分析方法论

本文不复述既有文档结论。每个判断标注依据来源：

- `[代码]` = 直接读代码路径确认
- `[artifact]` = 从 run artifact / benchmark report / telemetry 抽取
- `[测试]` = pytest / smoke / targeted rerun 结果
- `[文档推断]` = 仅来自文档描述，未经代码/artifact 交叉验证

---

## 1. 从赛题评分维度拆解

### 1.1 通信效率（25分）

**当前优势：**

- formal external compare 25/5 scope，StateBus prompt tokens 48754 vs external 115734，降 57.9%；total tokens 降 49.7%。`[artifact: r01_07 cold-start-compare.json]`
- formal internal L0→L2 waterfall：prompt bytes 从 254842 降到 139732（-45.2%），主要来自 semantic StateRef + memfd 引入后 evidence 不再全量注入。`[artifact: r01_05 formal-suite.json]`
- formal carrier compare：control bytes delta -30665，scaffolding bytes delta -11150。`[artifact: r01_06]`

**负面结果：**

- completion tokens 增 80.5%（13062 vs 7237）。`[artifact: r01_07]`
- carrier compare 中 structured side total tokens 反而高 4161。`[artifact: r01_06]`
- 没有 v2 formal API text vs protocol 同任务双模 token 对比 stage。formal internal 只跑 protocol mode（L0-L3），没有对应的 text-only formal API stage 输出 `text_total_tokens`。`[代码: v2/benchmark/live_runner.py 只注册 formal 和 compare suite，没有 formal-text-only suite]`

**问题根因分类：**

| 问题 | 类型 | 根因 |
|---|---|---|
| completion tokens +80.5% | 真实系统开销 | `role_path.py` 的 `_complete_json_role` 强制 JSON 输出 + audit/replay/artifact 字段 `[代码]` |
| carrier total tokens 上升 | 实验设计 + 系统开销 | structured carrier JSON completion 更重，visible evidence 未变 `[artifact]` |
| 缺 text vs protocol 双模 formal stage | 实验设计问题 | live_runner 未注册 text-only formal suite `[代码]` |
| 不能 claim latency | 真实系统开销 | CodeAct/persist/telemetry/memfd 是真实开销 `[artifact: telemetry summary]` |

**赛题映射：** 赛题要求「在相同任务条件下完成可复现实验对比」。当前 v2 formal 层的通信效率证据主要来自 external compare（StateBus vs pure-text baseline），不是 StateBus 自身 text vs protocol 双模。v1 有历史数字但不是 v2 API formal evidence。

---

### 1.2 状态传递创新（20分）

**当前优势：**

- 25 次 semantic StateRef/memfd transfer，247076 bytes。`[artifact: r01_05]`
- flagship 5/6 claimable families pass，total LLM prompt saved 21325 bytes，visible saved 7875 bytes。`[artifact: s01_10 stress summary]`
- L2 相比 L0 prompt bytes 降 115110，visible bytes 降 102802。`[artifact: r01_05 waterfall]`
- `SemanticStateRef` 与 `ExecutionArtifactRef` 模型分离。`[代码: v2/refs/models.py]`
- memfd data plane 真实发生：publish/transfer telemetry 非零。`[artifact + 代码: v2/state/store.py _materialize_memfd]`

**负面结果：**

- 非文本状态是 embedding semantic state + refs + hydration accounting；raw evidence/text/table 仍通过 hydration 进入 prompt。`[代码: v2/runtime/driver.py hydration path; artifact: hydration_audit.json]`
- `incident_diagnosis_v2` 负例：L2 比 T2 反而多 1456 prompt bytes，StateRef 无额外 saving。`[artifact: s01_10 per-family]`
- KV prefix 只有 control-plane estimate，无真实 vLLM prefix-cache hit metrics。`[代码: kv_prefix_experiment.py probe skipped; artifact: s01_09 skipped]`

**问题根因分类：**

| 问题 | 类型 | 根因 |
|---|---|---|
| 非文本 ≠ hidden-state/KV transfer | claim 口径问题 | 实现是 embedding state materialization，不是 KV tensor handoff `[代码]` |
| incident_diagnosis 负例 | 真实系统边界 | semantic selection 已把 evidence 压得很紧时，StateRef scaffolding 反而更重 `[artifact]` |
| KV prefix 无机制证据 | 实验设计问题 | vLLM probe 环境变量未打开，local vLLM 未部署 `[代码: STATEBUS_RUN_VLLM_PREFIX_PROBE=0]` |

**赛题映射：** 赛题要求「探索 embedding、语义向量、隐藏状态特征或其他中间表示在 Agent 之间的直接传递机制」。当前实现覆盖 embedding/semantic state 传递，有 memfd data plane 证据；但「隐藏状态特征」维度只有 control-plane estimate，不能 claim 真实 KV/hidden-state transfer。

---

### 1.3 记忆复用效果（20分）

**当前优势：**

- continuous replay：18 validated replay / 2 exact replay，answer_restoration=0。`[artifact: r01_11]`
- supplement flagship replay：3/3 replay-headline families 通过。`[artifact: s01_10 continuous-replay]`
- L3 reuse_gain=20（replay），9（continuous）。`[artifact]`
- history_artifact_reuse_count=50，history_step_reduction_count=13。`[artifact: r01_10]`
- replay negative audit 7/7 通过，证明 gate 不只正向通过。`[artifact: r01_12]`

**负面结果：**

- base continuous-replay 中 `long_doc_metric_replay_v1` missing target round 7。`[artifact: r01_11 family readout]`
- KV prefix demo missing target round 3。`[artifact: s01_08]`
- cold formal（L3）reuse_gain=0，因为 cold-start 没有 replay history。`[artifact: r01_05 L3 reuse_gain=0]`
- continuous 组 replay_headline_eligible_family_count=0。`[artifact: r01_10]`

**问题根因分类：**

| 问题 | 类型 | 根因 |
|---|---|---|
| missing target round 7 | 实现问题 | `long_doc_metric_replay_v1` round 7 的 route/metric projection 被 quality gate 拦下 `[artifact]` |
| cold formal reuse_gain=0 | 实验设计（正确行为） | formal cold-start 无 history，不应从此 claim memory benefit `[代码逻辑正确]` |
| KV prefix missing round 3 | 实现问题 | family manifest round 3 的 replay target 未被 continuous runner 覆盖 `[artifact: s01_08]` |

**赛题映射：** 赛题要求「至少设计 2 组具有关联性的连续任务，验证…共享记忆复用在减少重复计算、降低协作开销和提升任务效率方面的实际效果」。当前有 3 个 replay families / 30 rounds，18 validated + 2 exact replay 是强证据。但 2/3 base replay headline 且有 missing rounds 是弱点。

---

### 1.4 系统完整性（20分）

**当前优势：**

- 4 agents（Planner/Retriever/Executor/Summarizer），API 四角色各 25 次。`[artifact: r01_05]`
- 115 pytest passed。`[artifact: 02_pytest_full_v2]`
- UDS + typed Protobuf 控制面有单测 9 passed。`[测试: Docker root control subset]`
- CodeAct bwrap acceptance 5/5，API generation，无 fallback。`[artifact: s01_07]`
- continuous 30 rounds / 3 families 稳定执行完毕。`[artifact: r01_10, r01_11]`
- transport retry + selection retry 已修复并复验。`[artifact: local_api_20260707_163354 全 13 stages exit 0]`

**负面结果：**

- formal benchmark 主路径是 loopback harness，不是 subprocess transport。`[代码: live_runner 使用 ControlPlaneLoopbackServer]`
- openEuler 24.03-LTS-SP3 未验证。`[文档推断: 无任何 openEuler VM artifact]`
- 演示视频缺失。`[文档: 05_merged_issue_ledger V2-AUDIT-022]`
- memfd fallback 主要靠单测，缺真实 no-memfd 环境证据。`[代码+测试]`

**问题根因分类：**

| 问题 | 类型 | 根因 |
|---|---|---|
| loopback vs subprocess | 实验设计问题 | benchmark 设计选择了 loopback 以保证稳定性 `[代码]` |
| openEuler 未验证 | 交付阻塞 | VM 环境未配置/部署 `[约束]` |
| 演示视频缺失 | 交付材料缺失 | 未规划制作 |

**赛题映射：** 赛题要求「不少于 3 个 Agent 协同运行…稳定执行不少于 10 轮连续任务」和「在 openEuler 24.03-LTS-SP3 上能够正常编译、运行和测试」。前者已满足（4 agents, 30 rounds），后者是硬性交付阻塞。

---

### 1.5 实验验证（15分）

**当前优势：**

- full registry 25/5 formal compare + continuous/replay + CodeAct + KV demo。`[artifact]`
- fairness gate 25/25 pass，证明 baseline 不是污染。`[artifact: r01_07]`
- artifact mining 覆盖广：23928 JSON files, 73 benchmark reports, 1976 prompt slices。`[artifact: 12_artifact_mining]`
- token split schema 已补齐，可分别读 prompt/completion/total。`[代码: comparator_runner.py]`

**负面结果：**

- latency 明确负结果：task_ms_delta +73103.7ms。`[artifact: r01_07]`
- 无 serialized repeat rerun（当前只有单轮）。`[artifact 只有一次 run]`
- formal compare 历史上从 8-case 扩到 25-case 只在 2026-07-08 code update 后有新 adapter，但最新 artifact 已有 25/5。`[artifact: r01_07 scope=formal_registry_25case_5family_compare]`
- flagship stress 只有 5/6（不是 all-pass）。`[artifact: s01_10]`

**问题根因分类：**

| 问题 | 类型 | 根因 |
|---|---|---|
| latency 负结果 | 真实系统开销 | CodeAct 22.4s + persist/reload + telemetry + memfd + JSON completion `[artifact: telemetry]` |
| 无 serialized repeat | 实验设计问题 | 脚本默认 repeat=1，API 波动无法对消 `[代码: scripts/]` |
| flagship 5/6 | 真实系统边界 | incident_diagnosis_v2 是负例 `[artifact]` |

---

## 2. 跨维度核心问题深度拆解

### 2.1 Latency 为什么慢

**事实拆解（来自 14_diagnostic_artifact_mining）：**

总 delta：task_ms_delta = +73103.7ms（StateBus 更慢）

分解：
- LLM wall time delta：+37201.9ms
- system overhead delta：+35901.8ms

StateBus-only 显性成本（来自 telemetry summary top）：
- codeact_execution_stage_ms = 22389.2（最大单项）
- runtime_driver_stage_ms = 1378.6
- persist_and_reload_stage_ms = 738.5
- persist_bundle_write_stage_ms = 524.8
- control_plane_exchange_stage_ms = 160.4
- workspace_input_stage_ms = 109.3
- telemetry_emit_stage_ms = 91.2

**LLM wall time 为什么更高（+37.2s）：**

1. completion tokens 增加 80.5%：StateBus 强制 JSON + audit 字段，每个 role 输出更长。`[代码: role_path.py _complete_json_role]`
2. JSON retry：偶发 malformed JSON 会触发 bounded retry，虽然 retry count 不高但每次额外 API round trip。`[代码: role_path.py json extraction retry]`
3. llm_call_count_delta=0：四角色调用次数相同，说明不是多调用导致，而是每次调用的 generation 更长。`[artifact: r01_07]`

**system overhead 为什么高（+35.9s）：**

1. CodeAct bwrap 执行：22.4s，占 system overhead 62%。这是 StateBus-only 的可执行 artifact path。`[artifact: telemetry]`
2. persist/reload 全链路：JSONL stage totals 中 persist_and_reload=24.5s（含 bundle write 16.6s + integrity check 1.8s + core reload 4.7s）。`[artifact: JSONL totals]`
3. runtime driver orchestration：各角色 runtime event lifecycle 很短（planner 单次 8.7ms max），但 commit/finalize/replay-ledger 加起来 ~6s。`[artifact: JSONL component aggregates]`

**判断：** latency 负结果不是 bug，而是 StateBus 用 CodeAct execution + persist/audit/telemetry + structured JSON completion 换来了可审计性和数值正确率。这是设计取舍，不是"优化后就能反转"的问题。除非：
- 关闭 CodeAct（牺牲系统完整性）
- 减少 persist/telemetry（牺牲 replay 和 audit 能力）
- 瘦身 JSON schema（可能改善 completion tokens）

---

### 2.2 Completion tokens 为什么涨 80.5%

**per-family 拆解：**

| Family | SB completion | External completion | Delta | SB avg output keys |
|---|---:|---:|---:|---:|
| anomaly_detection_v1 | 1389 | 862 | +527 | 25.3 |
| conditional_aggregation_v1 | 2076 | 1331 | +745 | 25 |
| cross_table_join_analysis_v1 | 2792 | 1598 | +1194 | 25.2 |
| financial_report_analysis | 3856 | 1859 | +1997 | 20 |
| multi_period_trend_analysis_v1 | 2949 | 1587 | +1362 | 24.4 |

**schema surface 对比：**

- StateBus-only top-level keys（25+ 个）：action_contract, codeact_action_count, codeact_plan_hash, consumed_artifact_refs, evidence_pack_hash, execution_goal, intent_op, route, tool_name... `[artifact: 14_diagnostic schema surface]`
- External top-level keys（~9 个）：metric_name, metric_value, route, summary_text, task_id, tool_name... `[artifact]`

**根因：**

1. `role_path.py` 的 JSON role surface 要求每个 role 返回完整 structured JSON，包括 route/tool/action_contract/consumed_refs/produced_refs/strategy_refs/evidence_pack_hash 等字段。`[代码]`
2. executor 产出 `summary_json` 而不是短文本 answer，这让 scorer/replay/audit 稳定，但 completion 更重。`[代码]`
3. summarizer 也输出 structured summary + confidence + tags + reusable metadata。`[代码]`

**判断：** 这不是 bug。StateBus 的 completion 重是结构化可审计性的成本。真正可优化的是：把 benchmark audit 字段（evidence_pack_hash、consumed_artifact_refs、produced_strategy_refs 等）和 role 必需输出字段分开，前者只写入 telemetry 不进 LLM completion。

---

### 2.3 External baseline 为什么 10 个 case 失败

**失败维度统一是 `metric_value_exact=0`：** `[artifact: r01_07 external failed cases]`

- anomaly_detection_v1：3/3 全失败
- conditional_aggregation_v1：4/4 全失败
- multi_period_trend_analysis_v1：3/5 失败

**不是 route/tool/doc 选错：** external baseline 的 route_exact、tool_exact、selected_doc_hashes 在大部分 case 中正确。`[artifact: 14_diagnostic route miss forensic 提到 text side route/tool/doc 正确]`

**真实原因：** pure-text 四角色链路中，retriever 把结构化表格/数值压缩成自然语言 `evidence_summary`，后续 executor/summarizer 再继续传递。在复杂表格聚合（条件过滤后求和）、异常检测（多列对比判断异常数）、趋势计算（多期数值投影）这类任务中，中间数值在文本传递中容易丢失或变形。

StateBus 通过 selected evidence + tool artifact + metric_projection + summary_json 保持数值链路可审计，所以更稳定。

**这是否公平？**

- fairness gate 25/25 pass：external 看到的 candidate、证据、route 选项和 StateBus 完全相同。`[artifact: r01_07 fairness gate]`
- llm_call_count_delta=0：双方都是四角色各 25 次。`[artifact]`
- external 不是少给了候选或 oracle 提示。

因此这是真实的方法优势，不是不公平的实验设计。但必须准确表述为「quality superiority in numeric extraction tasks」而非「universal superiority」。

---

### 2.4 formal-trend-002 route miss 深度分析

**现象：** carrier compare (r01_06) 中 structured L1 侧 route_exact=0，但 tool/doc/value/trend 全部正确。`[artifact: 14_diagnostic route miss forensic]`

**细节：**
- structured route/tool：generate_chart / table_retriever
- text route/tool：compare_metric / table_retriever
- 两侧 trend values 和 direction 完全一致：72,79,87 / increasing
- visible candidate keys 两侧相同：compare_metric::table_retriever, summarize_risk::semantic_retriever, generate_chart::table_retriever

**判断：** 这是 structured route surface 的候选选择稳定性问题。visible candidate 列表中 `generate_chart::table_retriever` 和 `compare_metric::table_retriever` 都存在，LLM 在 structured JSON 模式下选了前者。这不是 metadata leakage（候选确实可见），而是 route label normalization 在 structured 模式下不够稳定。

**影响：** carrier compare 不能写成 equal-quality win（structured 24/25 vs text 25/25）。

---

### 2.5 KV Prefix：控制面 vs 机制验证的差距

**当前实现层级（来自代码交叉验证）：**

| 层级 | 代码位置 | 实现状态 | 证据状态 |
|---|---|---|---|
| prefix identity & hash | `neural_state.py` build_corpus/evidence_prefix_hash | 完整 `[代码]` | demo 10/10 quality pass `[artifact: s01_08]` |
| schedule planning | `kv_prefix_schedule.py` build_kv_prefix_schedule_plan | 完整 `[代码]` | cache_friendly max_run=5, hostile max_run=1 `[测试]` |
| prefix layout compiler | `role_path.py` compile_prefix_layout / PrefixLayoutPlan | 完整但默认关闭 `[代码: STATEBUS_PREFIX_ALIGNMENT_MODE 默认 off]` | 单测通过 `[测试]` |
| engine-local registry | `neural_state.py` EngineLocalPrefixRegistry | 完整 `[代码]` | 单测通过 `[测试]` |
| KV budget estimation | `kv_budget.py` | 完整 `[代码]` | 仅 config-based sizing `[代码]` |
| vLLM metrics probe | `kv_prefix_experiment.py` | 代码存在 `[代码]` | **skipped** `[artifact: s01_09 skipped]` |
| vLLM TTFT streaming | `kv_prefix_experiment.py` | 代码存在 `[代码]` | **skipped** |

**差距分析：**

从 control-plane estimate 到真实 vLLM mechanism claim 需要：
1. 本地 vLLM 部署（Qwen3-8B/14B + `--enable-prefix-caching`）
2. 打开 `STATEBUS_RUN_VLLM_PREFIX_PROBE=1`
3. 收集 `vllm:gpu_prefix_cache_hits_total` delta
4. 收集 streaming TTFT p50/p95
5. 证明 cache-friendly schedule 下 hit rate 显著高于 cache-hostile

当前只有第 0 步完成（代码存在）。所有 5 步未执行。

---

### 2.6 openEuler 交付阻塞

**赛题硬性要求：** 「最终交付的代码需在 openEuler 24.03-LTS-SP3 操作系统版本上能够正常编译、运行和测试」

**当前状态：** 零 openEuler VM evidence。所有 artifact 在 Docker + Ubuntu 20.04 host + openEuler container 环境下产出。`[artifact: 所有 run 的 env_probe]`

**风险点：**
- faiss-cpu 在 openEuler 上可能需要从源码编译（无 wheel）
- sentence-transformers 依赖链较深
- bwrap sandbox 在 openEuler 上的权限模型可能不同
- Python 3.11+ 在 openEuler 24.03 默认仓库中的版本

---

## 3. 问题总分类表

| ID | 问题 | 类型 | 赛题维度影响 | 严重度 | 当前状态 |
|---|---|---|---|---|---|
| PROB-01 | latency 负结果 +73.1s | 真实系统开销 | 通信效率(-), 实验验证(-) | P1 | 已确认，无法短期反转 |
| PROB-02 | completion tokens +80.5% | 真实系统开销 | 通信效率(-) | P1 | 部分可优化（schema 拆分） |
| PROB-03 | 缺 v2 text vs protocol 双模 formal stage | 实验设计 | 通信效率(-15分风险) | P0 | 代码已有 carrier compare，但不是自身双模 |
| PROB-04 | formal-trend-002 route miss | 实现问题 | 通信效率(-) | P1 | 需 targeted regression |
| PROB-05 | KV prefix 无机制证据 | 实验设计 | 状态传递创新(-) | P1 | 需 local vLLM 部署 |
| PROB-06 | 非文本状态 ≠ hidden-state | claim 口径 | 状态传递创新 | P1 | 已明确边界 |
| PROB-07 | missing replay target rounds | 实现问题 | 记忆复用(-) | P2 | round 7 quality gate |
| PROB-08 | openEuler 未验证 | 交付阻塞 | 系统完整性(-20分风险) | P0 | 零进度 |
| PROB-09 | 演示视频缺失 | 交付材料 | 实验验证(-) | P1 | 零进度 |
| PROB-10 | 无 serialized repeat rerun | 实验设计 | 实验验证(-) | P2 | 需新 run |
| PROB-11 | flagship 5/6 非 all-pass | 真实系统边界 | 状态传递创新(-) | P2 | 1 个 diagnostic-only 负例 |
| PROB-12 | formal benchmark loopback vs subprocess | 实验设计 | 系统完整性(-) | P2 | 设计选择 |
| PROB-13 | continuous 组无 replay headline | 实验设计（正确行为） | 记忆复用 | P2 | history-backed only |

---

## 4. 关键事实核实结论

### 4.1 复核：formal external compare 25/25 vs 15/25

**结论：经核实属实。**

- artifact `r01_07` 的 `mode_reports[0]` 明确记录 StateBus quality=25, external quality=15。`[artifact]`
- fairness gate 25/25 pass，external_fairness_gate_failed_case_count=0。`[artifact]`
- 10 个失败 case 全部是 `metric_value_exact` 维度。`[artifact: family deltas]`
- external 的 route/tool/doc 维度大部分正确。`[artifact 14_diagnostic]`

### 4.2 复核：prompt tokens 降 57.9%

**结论：经核实属实，但需区分 family。**

- anomaly/aggregation families 贡献 prompt 降幅最大（-74.6% 和 -73.6%）。`[artifact: family token split]`
- financial/cross-table/trend families 降幅较小（-20~24%）。`[artifact]`
- 差异来源：长表格/多证据 families 中 external baseline 的 evidence 更长。`[artifact: role prompt bytes retriever 31757 vs 179217]`

### 4.3 复核：KV prefix demo 质量和 estimate

**结论：经核实属实但范围有限。**

- s01_08 stage exit 0，L3 quality 10/10。`[artifact]`
- corpus prefix hash reuse count=8，engine-local estimate=2680 tokens。`[artifact]`
- 但：evidence_prefix_hash_reuse_count=0（每任务 evidence 不同）。`[artifact: 13_deep_analysis KV section]`
- 且：vLLM probes skipped（无真实 hit metrics）。`[artifact: s01_09 skipped]`

### 4.4 复核：latency 负结果的归因

**结论：经核实属实，多因素。**

- CodeAct 是最大单项：22.4s。`[artifact: telemetry summary]`
- persist/reload 链路第二大：JSONL totals 24.5s。`[artifact: JSONL totals]`
- LLM wall time 也更高（+37.2s），主要来自 completion 更长。`[artifact + 推断]`
- 不是 API retry 导致：retry/fallback count=0。`[artifact: retry checks]`

---

## 5. 最终判断

### 5.1 StateBus 的真实优势在哪里

1. **数值正确率**：在复杂表格聚合/异常检测/趋势计算任务中，结构化 retrieval + tool artifact + metric projection 显著优于 pure-text 链路的数值投影能力。这是 quality-superiority 的核心来源。

2. **prompt/total token 压缩**：semantic StateRef + evidence pruning 真实减少下游角色 prompt，尤其在长证据 families 中。

3. **replay/reuse 机制**：validated replay + exact replay 不是摆设，有 30-round live evidence。

4. **系统可审计性**：persist/telemetry/artifact 虽然增加 latency，但让结果可复现、可追溯。

### 5.2 StateBus 的真实劣势在哪里

1. **Latency**：当前设计是用时间换可审计性+正确率。不能通过"优化"反转，只能通过选择性关闭审计功能来减小 delta。

2. **Completion overhead**：structured JSON role surface 是正确的设计，但 audit 字段不应进 LLM completion。

3. **KV 只在 estimate 层**：从 control-plane design 到真实 vLLM metrics 有 5 步差距。

4. **openEuler 交付**：硬性阻塞，零进度。

### 5.3 不应为答辩包装的事实

- latency 就是慢，不要试图"换个角度解释成优势"
- completion 涨 80.5% 不要写成"信息量更大所以更好"
- KV prefix 不要写成"已实现 KV cache 传递"
- flagship 5/6 不要写成"all-pass"
- openEuler container ≠ openEuler VM validation
