# StateBus v2 Qwen3-32B Extended Run 严格真实性审计

审计日期：2026-07-14  
审计对象：`/home/qcrs/statebus/runs/full_qwen3_extended_gpu1_20260713_225438`  
结构化数据：`43_full_qwen3_extended_audit_20260714.json`  
生成脚本：`scripts/analyze_full_qwen3_extended_run.py`  
历史基线：tag `v2-non-kv-baseline-20260710`，peeled commit `d83627dc2b792b4c8ac2c2d58337fc8281771803`

## 1. 执行摘要

本次 run 形成了可信的 compare、replay、两组 continuous、formal L0-L3 和 subprocess UDS 正向证据，但它不是完整的 extended matrix。`08_genericity_holdout` 失败后，launcher 因 `set -e` 在 17:35:36 退出，Stage 09-15 从未执行。`summary.json.execution_scope=full` 只表示 continuous 没有限制 round，不能解释成 16-stage 计划矩阵完整。证据见 `launcher.log`、`status.tsv` 和 [run script](/home/qcrs/statebus/project/scripts/run_v2_full_qwen3_container.sh:643)。

最强结论仍是等质量 token 结果。Stage 02 在相同 25 case、5 registry family、相同 Qwen3-32B 和相同 scorer 下，StateBus 与 external text 都是 25/25 quality pass；StateBus prompt token 为 59,491，external 为 71,526，差值 -12,035（-16.83%）；total token 差值 -11,978（-15.27%）。25/25 case 的 StateBus prompt token 都更低。它支持系统级 first-pass compare，不支持把全部差值因果归于 typed carrier，因为两侧 Planner JSON schema、prompt、证据暴露和执行实现不等价。

Planner 是本轮最重要的真实性缺口。359/359 个 `planner_handoff.json` 都有 Planner 调用和持久化 payload，但 `planner_plan_payload.retrieval_objective` 出现 0 次、模型 objective 字段总数为 0。最终 `retrieval_objective` 由 Runtime scope、`build_retrieval_objective()` 和 `plan_workflow()` fallback 合成。与此矛盾的是，359/359 个 case 都写了 `planner_generated_retrieval_objective_count=1` 和 `planner_objective_present=1`。因此当前实验只证明 Planner 被调用、产生 payload、payload 被保存/透传；没有证明模型 Planner 数据改变了 route、tool 或 retrieval 行为。

KV/hidden-state 的证据边界必须收紧。本 run 有 334 个 target LogitState 记录，全部 peak 位于最后 token 之前，但它们是 executor top-logprobs 派生的 compact probability summary，不是 hidden state 或 KV tensor。`neural_prefix_*` 是 task-session 控制面估算：330 estimated hits / 660 queries，重算 0.5；没有 vLLM 实际 counter、task/stage delta 或 Prefix Feedback 调度闭环。不得宣称 KV tensor handoff、真实 task-local prefix hit rate或 causal prefix speedup。

Stage 08 的四个 case 本身都质量通过、route hint 关闭、四角色完整；唯一失败条件是 `planner_workflow_step_count >= 3`。四个 holdout 只替换 `request_text`，保留预编译 `CanonicalTaskSpec`。与 Stage 06 对应 case 比较，spec、Planner plan、objective、route、tool、summary 全部相同。因此它不是自由文本泛化实验，失败的是不合理 gate，而不是四个任务的质量。

## 2. 审计方法和数据完整性

分析脚本不导入 Runtime，也不修改 run。它递归枚举 19,104 个文件，解析 17,649 个 JSON、718 个 JSONL 文件中的 19,502 条记录，并扫描 11 个 log。逐 case 主表包括 359 个 StateBus workspace 和 25 个 external case。359/359 个 StateBus `outputs/result.json` 存在，且 SHA-256 与 `logs/artifact_audit.json.output_artifact_hash` 一致。

唯一 JSON parse failure 是空文件 `vllm_health.json`，错误为 `Expecting value: line 1 column 1`。它不影响 Stage 00 的 `stdout.json.ok=true`，但说明 health sidecar 不能作为 vLLM 请求成功证据。718 个 JSONL 无解析错误。原始明细见结构化 JSON 的 `artifact_inventory`、`cases` 和 `memory_replay.output_artifact_integrity`。

环境证据来自 `launcher.log` 和 `stages/00_preflight/stdout.json`：容器项目根为 `/workspace/statebus/project`，本地 vLLM 为 `http://127.0.0.1:53334/v1`、model `qwen3-32b`，embedding 为 local、`cuda:1`、`/statebus/models/Qwen3-Embedding-0.6B`。Stage 01 实际结果是 `298 passed, 100 warnings in 481.70s`。

## 3. Stage-by-stage 结果

| Stage | 记录状态 | 实际范围 | Case/workspace | Registry family | Layer | 质量 | 证据强度 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 00 preflight | PASS | 配置/依赖/CUDA检查 | 0 | 0 | 0 | n/a | 配置可用，不是端到端请求 |
| 01 pytest v2 | PASS | `tests/v2` | 298 tests | n/a | n/a | 298 pass | 代码回归证据 |
| 02 compare | PASS | StateBus + external | 25 + 25 | 5 | L3 + external | 25/25 + 25/25 | first-pass 系统 compare |
| 03 replay | PASS | L3 target + L0 bootstrap | 25 + 25 | 5 | L3 target | 25/25 | validated replay diagnostic |
| 04 CSV continuous | PASS | 10 rounds x L0-L3 | 40 | 1 | 4 | 40/40 | assist/artifact lineage |
| 05 cross-period | PASS | 10 rounds x L0-L3 | 40 | 1 | 4 | 40/40 | 4 validated targets |
| 06 formal | PASS | 25 cases x L0-L3 | 100 | 5 | 4 | 100/100 | formal internal attribution |
| 07 subprocess UDS | PASS | 25 cases x L0-L3 | 100 | 5 | 4 | 100/100 | subprocess+UDS代码路径 |
| 08 genericity | FAIL | 4 precompiled-spec holdout | 4 | 4 | L3 | 4/4 | gate 缺陷；非 free-text 泛化 |
| 09-15 | 未记录 | prefix/carrier/repeat/tag audit | 0 | 0 | 0 | n/a | 未执行，不能从本 run 推断 |

Stage 02/03/06/07 的 formal registry 分布一致：financial 8、trend 5、join 5、aggregation 4、anomaly 3。workspace 内 `CanonicalTaskSpec.task_family` 只归并成 3 个 Runtime family；不能用它代替 formal registry 的 5-family 覆盖。证据为 Stage 06 `stdout.json.families`、`layers[].cases[].task_family` 和结构化 JSON `stage_scope[].runtime_task_families`。

上一轮所谓“全部通过”run `full_qwen3_gpu1_20260713_182556` 的 `status.tsv` 只到 Stage 06，共 7 个记录 stage，不含 UDS、genericity、prefix、carrier、repeat 或 tag audit。早期 `full_qwen3_gpu0_20260713_134805` 的 Stage 03 是 `httpx.ReadTimeout/openai.APITimeoutError`，不是 replay gate 判错；其失败不能用作 replay 语义反例。

## 4. Layer、family 和 case 统计

### 4.1 Formal L0-L3

| Layer | Quality | Prompt token | Completion | Total token | Task ms | Control bytes | Semantic transfer | SHM publish |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| L0 | 25/25 | 101,287 | 10,141 | 111,428 | 743,519 | 42,926 | 0 | 0 |
| L1 | 25/25 | 102,950 | 7,123 | 110,073 | 541,565 | 10,936 | 0 | 0 |
| L2 | 25/25 | 59,491 | 6,982 | 66,473 | 534,664 | 11,545 | 25 | 25 |
| L3 | 25/25 | 59,491 | 6,982 | 66,473 | 531,127 | 12,595 | 25 | 25 |

L3 相对 L0 total token 为 -44,955（-40.34%），质量不变。主要 token 变化发生在 L1 到 L2，支持 semantic pruning/state path 与 token 降低相关；formal L3 没有 history，L2 与 L3 token 相同不能归因 memory/replay。

L0/L1 不是严格单变量消融：handoff mode、prompt 模板、结构化控制和 control bytes 同时变化。L2/L3 的 formal cold path也不是 replay ablation。证据为 `stages/06_formal_full/stdout.json.layers[]`；Layer 配置和固定 workflow 见 [driver.py](/home/qcrs/statebus/project/v2/runtime/driver.py:206)。

### 4.2 Formal L3 family

| Registry family | Cases | Quality | Prompt token | Total token | Task ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| financial_report_analysis | 8 | 8/8 | 12,091 | 14,375 | 172,946 |
| multi_period_trend_analysis_v1 | 5 | 5/5 | 11,542 | 12,936 | 105,943 |
| cross_table_join_analysis_v1 | 5 | 5/5 | 11,308 | 12,671 | 102,840 |
| conditional_aggregation_v1 | 4 | 4/4 | 14,031 | 15,156 | 87,046 |
| anomaly_detection_v1 | 3 | 3/3 | 10,519 | 11,335 | 62,352 |

完整 L0-L3 x family x case 明细在 JSON `case_aggregates`；每条 case 保留 `task_metrics`、Planner handoff、retrieval log、replay audit 和 result 绝对路径。

### 4.3 Continuous L3

| Family | Rounds | Quality | Prompt/total token | Memory match | Consumed artifact/strategy refs | Validated/exact | Skip | History step/gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CSV | 10 | 10/10 | 35,602 / 38,370 | 16 | 19 / 6 | 0 / 0 | 0 | 2 / 1 |
| cross-period | 10 | 10/10 | 25,228 / 27,990 | 18 | 16 / 3 | 4 / 0 | 4 | 12 / 8 |

CSV 的 `history_artifact_reuse_count` 事件和为 21、`history_strategy_reuse_count` 为 7，而 result 中实际 consumed ref 数为 19/6；报告采用两者并列，不把事件计数误写成唯一对象数。

## 5. Compare 公平性、token 和时间

同条件证据：两 lane 都覆盖 25 case/5 family、同 Qwen3-32B、相同 expected-fact scorer/quality floor，每 case Planner/Retriever/Executor/Summarizer 各调用一次。external fairness hard gate 25/25，`contamination_detected=0`。

| 指标 | StateBus | External | Delta |
| --- | ---: | ---: | ---: |
| Quality pass | 25 | 25 | 0 |
| Prompt token | 59,491 | 71,526 | -12,035 (-16.83%) |
| Completion token | 6,982 | 6,925 | +57 |
| Total token | 66,473 | 78,451 | -11,978 (-15.27%) |
| Task ms | case delta sum | - | -13,952.8 |

时间不构成稳定 superiority：StateBus 12/25 case 更快，external 13/25 更快；per-case delta 均值 -558 ms，但中位数为 StateBus 慢 760 ms，且只有一次 serialized run。Stage 12-14 的两次 repeat 和 aggregate 因 Stage 08 中止未执行。

公平性限制：external Planner schema强制 `candidate_key/route/tool_name/retrieval_objective`，见 [external_text_baseline.py](/home/qcrs/statebus/project/v2/benchmark/external_text_baseline.py:723)；StateBus Planner 没有同等 required-field schema。StateBus 走 typed state、内部 deterministic CodeAct/data helper，external 走 pure-text/public deterministic tool。结论只能写“同模型、同任务、同质量门的系统级比较”，不能写“typed carrier 单变量造成 15.27% token 收益”。逐 case delta 位于 JSON `compare.cases`。

## 6. KV Prefix 证据边界

目标 case 共 334 个，其中 `neural_prefix_cache_hit_count_estimate` 总和 330、query 总和 660，重算 estimated rate=0.5。多数 case 固定 hits=1、queries=2、rate=0.5、savings ratio=0.5；CSV lineage case使 334 case 不等于 334 hit。

这些字段来自 `statebus.engine_local_prefix.v1` identity/scheduling contract：一个 shared prefix 给 executor/summarizer，后续 consumer 被估算为 hit。artifact 中没有：

- vLLM 实际 prefix cache counter；
- task/stage 前后 counter delta；
- service-lifetime counter snapshot；
- `prefix_feedback_*` artifact；
- observed hit rate或 causal savings。

`PrefixCacheFeedbackLoop` 与 `record_live()` 只存在于 [prefix_feedback.py](/home/qcrs/statebus/project/v2/runtime/prefix_feedback.py:103)，runner/scheduler 没有调用。计划中的 Stage 09/10 没执行。因此当前只能宣称 prefix identity/scheduling control plane 和 prefill savings estimate 已落盘；不能宣称真实 KV cache hit、KV tensor export/transfer 或真实时间/token 收益。

严格术语：vLLM Engine-Local Prefix Reuse 是同一 engine 内重复前缀计算的潜在复用；prefix identity 是控制面；`neural_prefix_*` 是估算；它们都不是 Agent 间 KV tensor handoff。

## 7. LogitState 审计

334/334 个 target case 有 `logit_state_transfer_count=1`。分布：

| 字段 | Min | Median | Mean | Max | Unique |
| --- | ---: | ---: | ---: | ---: | ---: |
| peak entropy（误名 mean） | 0.0081 | 0.1594 | 0.2505 | 0.7195 | 89 |
| varentropy | 0.000002 | 0.000782 | 0.004289 | 0.021222 | 159 |
| top_gap | 0.0312 | 0.9253 | 0.8478 | 0.9979 | 89 |
| peak_position | 3 | 29 | 28.85 | 35 | 7 |
| sequence_length | 29 | 31 | 31.68 | 37 | 6 |
| decision_entropy | 0.7504 | 1.6094 | 1.7146 | 2.1972 | 44 |

334/334 peak 都在最后 token 之前，证明 peak scan 没有机械读取 grammar closing token。实现见 [logit_state.py](/home/qcrs/statebus/project/v2/runtime/logit_state.py:135) 和 [role_path.py](/home/qcrs/statebus/project/v2/runtime/role_path.py:1516)。

但原始 top-logprobs 没有持久化，无法在 artifact 层重算 last-token entropy 或比较 peak vs last 的质量，因此不能证明 peak scan “优于”末 token，只能证明选择位置不同。`logit_state_mean_entropy` 实际写入 `_logit_result.entropy`，即 peak entropy，不是 dataclass 的 `aggregated_entropy`，见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2924)，字段名误导。

decision entropy 高频精确落在 `ln(5)`、`ln(8)`、`ln(9)` 等值，表明它强受 closed candidate clusters/grammar 影响。所有 `logit_confidence_gate_trigger_count=0`，代码搜索和 artifact 都没有 route/tool/置信门消费证据。LogitStateRef 在当前 run 是记录，不是行为干预，更不是 hidden state 或 KV。

## 8. 共享记忆与 Replay

### 8.1 Stage 03

25 个 target 各有独立 `_history_bootstrap/<task>` workspace/runtime root；25 对 `CanonicalTaskSpec` hash 相同但目录不同。target 的 `replay_audit.history_runtime_roots` 指向本 stage bootstrap，未发现跨 stage root。

结果为 memory match 25、validated replay 25、exact replay 0、skip 25、reuse_gain 25。每个 decision 都是 `exact_key_mismatch_validated_replay`，`downgraded_execution_goal=true`。然而每个 target 四角色仍各调用一次、LLM call=4。因此 `skipped_step_count=1` 是 [replay.py](/home/qcrs/statebus/project/v2/runtime/replay.py:147) 的 validated 分类常量，不等于少调用一个 Agent。

只有 exact replay 分支才恢复历史 output 并将 Retriever/Executor/Summarizer 置零，见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2204) 和 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2764)。本 run 没有 exact replay，不能宣称 answer restoration 或 exact replay 时延收益。

### 8.2 Continuous

Round 2+ 的 `history_runtime_roots` 真实指向依赖 round，result 中也有 consumed artifact/strategy refs，证明后续 round 消费前序产物。CSV 应归类为 assist/artifact lineage reuse；cross-period rounds 2/4/6/8 有 4 次 validated replay，但四角色仍全部调用。

`cross-period-008` 是关键不一致 case：`validated_replay_count=1`、`skipped_step_count=1`，但 consumed artifact/strategy refs 都为 0，`history_step_reduction_count=0`、`history_reuse_gain=0`。证据为 `stages/05_continuous_cross_full/workspaces/L3/cross-period-008/logs/task_metrics.json` 与 `outputs/result.json`。说明 replay gate 分类计数与 output reuse/减算不是同一概念。

更严重的消融缺陷是 [continuous_runner.py](/home/qcrs/statebus/project/v2/benchmark/continuous_runner.py:1087) 对 L0-L3 全部传 `history_runtime_roots`；L0-L2 result 实际也有 consumed refs。与此同时 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:828) 在 `replay_enabled=false` 时把 history reuse metrics强制归零。故 continuous L0-L2 不是无历史基线，L2-L3 不是纯净 history ablation。

## 9. Formal、UDS 和 genericity 可靠性

Formal 25/5 覆盖完整，四层质量均 25/25，shared-memory embedding state 在 L2/L3 各 publish/transfer 25 次。它强支持固定任务集上的 internal attribution，不证明 open-ended Planner、真实 KV 或 exact replay。

Stage 07 `stdout.json.transport=subprocess`，Runtime 在 [driver.py](/home/qcrs/statebus/project/v2/runtime/driver.py:1608) 进入 `SubprocessExecutorTransport`；transport 实际使用 `AF_UNIX` 和 `subprocess.Popen`，见 [transport.py](/home/qcrs/statebus/project/v2/control/transport.py:346) 与 [transport.py](/home/qcrs/statebus/project/v2/control/transport.py:377)。Stage 06/07 的 100 对 case：quality、prompt token 和 output hash全部相同。

| Layer | Loopback task ms | Subprocess task ms | Delta |
| --- | ---: | ---: | ---: |
| L0 | 743,519 | 746,970 | +3,451 |
| L1 | 541,565 | 539,994 | -1,571 |
| L2 | 534,664 | 532,223 | -2,441 |
| L3 | 531,127 | 530,484 | -643 |

两 stage 是独立 LLM 执行且 repeat=1，正负混合，不能解释为 subprocess overhead 或 speedup。Stage 07 的 200 个 runtime JSONL 中没有 PID、socket path 或 `transport=subprocess` payload，run-level transport observability不足。

Genericity 四对 Stage 06/08 case的 spec hash、Planner plan hash、objective hash、route、tool、summary hash全部相同。脚本 [run_v2_genericity_holdout.py](/home/qcrs/statebus/project/scripts/run_v2_genericity_holdout.py:89) 只用 `dataclasses.replace` 改 task id/request text，保留原 precompiled spec；[smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:1815) 优先使用 precompiled spec重建 goal/query/summary。因此 route hints 关闭不等于模型独立理解自由文本；`intent_op/required_tools/required_outputs/quality_checks` 仍是强先验。

## 10. Agent 真实贡献和答案泄露

334 个 target case 逐 case都满足四角色各一次，不只是 suite aggregate。分层判定：

| Agent | 被调用 | 产生数据 | 保存/透传 | 下游消费 | 影响行为 |
| --- | --- | --- | --- | --- | --- |
| Planner | 334/334 | 是 | 334 handoff，334 result roundtrip | final fallback objective被 pipeline读取 | 模型字段影响：0 证据 |
| Retriever | 334/334 | 三路 evidence/query embedding/log | 是 | Executor/Summarizer消费 evidence | 有，但固定 fan-out + 闭集选择 |
| Executor | 334/334 | route/tool/action contract | CodeAct/result | deterministic CodeAct消费 | 有，但非自由 Python 生成 |
| Summarizer | 334/334 | 334 non-empty summary | result + memory commit | 后续 history可消费 | 有 fallback 风险，raw completion缺失 |

Retriever fan-out 固定执行 lexical/semantic/table，见 [pipeline.py](/home/qcrs/statebus/project/v2/retrieval/pipeline.py:978)。三个 retriever共享同一个 normalized Planner scope/query，不存在三个分别由 Planner 生成的 objective。memory lookup 是后续独立路径。

审计扫描 2,513 个 role-visible 文件：359 spec、359 Planner handoff、359 CodeAct bundle、1,436 prompt slice。`expected_facts/expected_route/expected_tool_name/oracle_answer/correctness_hint` 字面命中 0。`expected_facts` 在 role完成后进入 validator，见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2565)。

这只能写成“已枚举 surface 未发现禁止字段名泄露”。taint scan不检查 oracle 值、同义表达或模板特化；CanonicalTaskSpec 的 route/tool/output先验仍存在。未发现 case-id 分支，但没有动态 counterfactual test，不能宣称形式化无泄露。

## 11. Planner 当前事实

1. Planner 被调用 359 次，所有 handoff 都持久化，所有 plan payload 都原样出现在 result。
2. 两类主要 payload：264 个 target 是 `g/h/q/rr/sp/t/tf` compact echo；70 个 target 是 `steps` payload，其中多数 3-5 step，另有空 steps。raw completion未保存，只能审计规范化后的 payload。
3. 359/359 `planner_plan_payload` 都没有 `retrieval_objective`；模型 objective case=0、字段=0。
4. 最终 objective 合并顺序是 Runtime scope -> `build_retrieval_objective()` -> `plan_workflow()` fallback/model覆盖，见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:1868)。
5. Retriever真实读取 final objective 的 query/scope，并用 candidate_keys/required_tools约束闭集，见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:1880) 与 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2026)。但没有 persisted consumed-objective hash。
6. `planner_plan_payload` 被写入 CodeAct request和 Runtime driver，见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2425) 与 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2670)；CodeAct required outputs、family、intent、args、route/tool均另由 spec/Runtime提供，没有 plan改变行为的实验证据。
7. Runtime DAG固定为 Planner -> Retriever fan-out -> Executor -> Summarizer，见 [driver.py](/home/qcrs/statebus/project/v2/runtime/driver.py:206)。因此 `planner_workflow_step_count=0` 不妨碍任务完成。
8. `planner_generated_retrieval_objective_count=1` 在 [driver.py](/home/qcrs/statebus/project/v2/runtime/driver.py:324) 和 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2769) 无条件写入。
9. `planner_objective_present=1` 在 merge/fallback 后计算，见 [smoke.py](/home/qcrs/statebus/project/v2/runtime/smoke.py:2939)，只能证明最终 dict非空。
10. Stage 06 的 step只出现在 L0：L0 为 zero/3/4/5 step = 1/19/4/1，L1-L3 各25个全部zero；全 stage 合计 76/19/4/1。Stage 08 是4/4 zero step。这进一步说明 step输出不稳定且不控制固定 Runtime DAG。
11. tag 对比显示 `build_default_workflow`、`build_retrieval_objective`、`plan_workflow` 函数 hash 与 `v2-non-kv-baseline-20260710` 完全相同，tag也已有硬编码 generated metric。因此不是新 Planner 行为回归，而是历史 attribution defect。
12. 旧 tag同样固定 `build_default_workflow()`；旧实验的角色计数只能证明调用，不证明 Planner行为贡献。

完整改进设计见 `44_planner_role_and_stability_plan_20260714.md`。

## 12. Bug 和实验缺口

### P0

1. Planner attribution false positive：359 个模型 objective为0，却记录 generated=359；会直接污染 Agent贡献结论。
2. Genericity gate把 `planner_workflow_step_count>=3` 当成功条件；与固定 Runtime workflow设计冲突，并使4/4质量通过的 stage失败。

### P1

3. Continuous L0-L2消费 history却把 reuse指标清零，破坏 L2/L3 history ablation。
4. Prefix只有估算，无 observed counter delta、feedback scheduler integration或 Stage 09/10 A/B。
5. Logit原始 top-logprobs未保存，`mean_entropy`字段误名，且没有行为干预 A/B。
6. Validated replay的 skip是规则常量，不等于 Agent call/action减少；`cross-period-008` gate与实际输出复用不一致。
7. UDS runtime telemetry缺 PID/socket/transport lifecycle证据。
8. Compare schema/执行实现不等价，不能做 carrier-only attribution。
9. Extended `execution_scope=full` 容易掩盖 Stage 09-15 未执行。

### P2

10. `memory_commit_count=2` 来自多个 lifecycle event，不是两条独立 memory；`retrieval_candidate_count`同样是事件累加。
11. 334/334 target均 `bwrap=0/fallback=1`，不能宣称强隔离。
12. raw Planner/Retriever/Executor/Summarizer completion未持久化，限制 payload provenance/fallback复核。
13. 空 `vllm_health.json` 未被 summary视为缺陷。

## 13. 赛题要求覆盖矩阵

| 赛题要求 | 本 run 证据 | 判定 |
| --- | --- | --- |
| >=3 Agent / >=3 role | 4 role，334 target逐 case各一次 | 已覆盖调用与产物；Planner行为贡献不足 |
| >=3 task type | formal 5 registry families | 已覆盖固定 registry |
| 纯文本 + 结构化 | L0-L3，质量一致 | 已覆盖，但非严格单变量 |
| 结构化 action/args/result/capability | typed control、fixed workflow、UDS代码路径 | 已覆盖 |
| 非文本中间状态 | L2/L3 shared-memory embedding state | 已覆盖 embedding state |
| hidden/KV | Logit summary + prefix estimate | 未覆盖 tensor transfer |
| 共享记忆存储/检索/复用 | Stage 03 + 两组 continuous | 已覆盖 assist/validated；无 exact收益 |
| 两组关联连续任务 | CSV + cross-period，各10轮 | 已覆盖 |
| >=10轮稳定 | 两组各10轮质量全过 | 已覆盖单次运行 |
| token/字符/state size/时延 | report字段齐全 | token强；时延仅 first-pass |
| 记忆命中率/性能提升 | raw event/count、refs、skip | 部分覆盖；缺统一 denominator/纯净A/B |
| CodeAct | bounded deterministic plan/script | 部分覆盖；非LLM自由代码 |
| openEuler交付 | openEuler容器路径执行 | 覆盖容器路径，不等于VM/终态复现 |
| UDS subprocess | Stage 07成功100 case | 已覆盖代码路径，观测性不足 |
| 强沙箱 | 334次resource fallback | 当前不能宣称 |

## 14. 当前可以宣称和不能宣称

### 已被实验证明

- Qwen3-32B、25 case/5 family、等质量 first-pass compare 下，StateBus prompt -16.83%、total -15.27%。
- Formal L0-L3 全部25/25，L3相对L0 total token -40.34%；L2/L3有 shared-memory embedding state transfer。
- 两组10轮 continuous全部质量通过，history refs被后续 round实际消费；cross-period有4个 validated target。
- subprocess+UDS+typed Protobuf代码路径成功完成25x4 case。
- Planner被调用、产生 payload、payload保存/透传；模型-generated objective为0。
- Logit compact summary落盘，peak scan没有选择最后 token。

### 只被代码支持但没有实验

- Prefix Feedback Loop接入 live counter后的校准能力。
- exact replay恢复 output并减少下游角色调用的路径。
- 模型 Planner objective理论上可改变 query/candidate constraint。

### 只有估算指标

- 全部 `neural_prefix_*` hit/savings。
- `evidence_pruning_estimated_kv_tokens_saved`。
- 规则化的 `history_step_reduction_count`。

### 当前不能宣称

- hidden-state/KV tensor transfer或Agent间KV handoff。
- task-local真实 vLLM prefix hit和prefix causal时间/token收益。
- Planner自由文本语义规划、动态DAG或对route/tool的已证实贡献。
- Stage 08证明自由文本泛化/paraphrase stability。
- 稳定时延 superiority、exact replay收益、强bwrap隔离。
- 完整 extended matrix通过。

## 15. 最小修复与最小验证矩阵

| 顺序 | 最小修复 | 不改变的边界 | 最小验证 | 全量前 gate |
| --- | --- | --- | --- | --- |
| 1 | 修正 Planner objective source/field/consumption指标 | 固定四步 workflow | unit + 4 holdout + 1 formal L0-L3 | fallback不再算model贡献 |
| 2 | Shadow `SemanticTaskPlan` | 不影响执行 | 25 formal + paraphrase pairs | schema/equivalence/stability/no-oracle |
| 3 | 受限 objective消费 | Runtime掌握拓扑、tool whitelist、replay | Planner enabled/disabled/perturbed A/B | consumed hash一致、失败fallback |
| 4 | 修 continuous history ablation | 不改 scorer/task | 2 rounds x L2/L3 | L2无history，L3有history且refs/metrics一致 |
| 5 | prefix counter delta | 不混入formal token headline | shared/independent clean repeats | vLLM before/after delta + schedule A/B |
| 6 | UDS observability | 不改transport语义 | 1 case loopback/subprocess | PID/socket/transport事件与cleanup |

建议先完成 Planner Phase 1 与 genericity gate修正，再做极小 smoke。不要立即重跑全量；先确认字段语义和验收矩阵，避免再次用错误 gate中止长实验。

## 16. 证据索引

- 结构化逐 case审计：`43_full_qwen3_extended_audit_20260714.json`
- Stage总状态：`/home/qcrs/statebus/runs/full_qwen3_extended_gpu1_20260713_225438/status.tsv`
- Stage 02 compare detail：`stages/02_compare_full/runtime/benchmark_reports/full-02_compare_full-20260713_225438-cold-start-compare-local_vllm.json`
- Stage 03 replay：`stages/03_replay_full/stdout.json` 和每 case `logs/replay_audit.json`
- Continuous：`stages/04_continuous_csv_full/stdout.json`、`stages/05_continuous_cross_full/stdout.json`
- Formal/UDS：`stages/06_formal_full/stdout.json`、`stages/07_formal_subprocess_uds_full/stdout.json`
- Genericity：`stages/08_genericity_holdout/stdout.json`
- Planner代表 case：`stages/06_formal_full/workspaces/L3/formal-agg-003/inputs/planner_handoff.json`
- Tag差异：JSON `tag_baseline.functions`，三个核心函数 hash相同。
