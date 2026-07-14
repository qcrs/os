# Qwen3-32B 综合实验真值分析（2026-07-12）

## Executive Summary

本轮实验完成了 Qwen3-32B local vLLM 下的健康检查、2-case logit 链路、25-case external compare、两组 10-round continuous family，以及 25-case/5-family L0-L3 formal attribution。可直接成立的最强结果是：Stage 6 四层均为 25/25 quality pass，L3 相对 L0 减少 43369.0 total tokens（39.48%）和 40128.0 prompt tokens（40.28%）。但它仍是同一 StateBus 主线内部的 attribution ladder，不是外部 text baseline 的等质量 superiority 证据。

Stage 3 的 -29120.0 tokens（30.46%）不能作为公平效率结论：StateBus 25/25 通过，external baseline 0/25。根因不是 Qwen3-32B 完全不会抽取事实，而是 Track C schema 与 Retriever 输出契约冲突。schema 只允许 candidate/route/tool，禁止 metric/evidence/doc 字段；实际 25/25 route、tool、doc hash 和 summary 均正确，但 metric_name、metric_value、admissible_match 全部失败。因此 Track C 在本轮是负向回归，不是有效修复。

Stage 4 未产生 replay 证据。formal-tier 分支在 `suite=statebus` 逻辑之前返回，忽略了 `--statebus-mode replay-ready`；L3 的 reuse_gain、skipped_step_count、validated_replay_count 均为 0，metadata 也明确记录四层 seed 均为 false。Stage 5 则证明 local vLLM continuous runner 能稳定完成两个 family 共 20 rounds；其中 cross-period family 有 4 次 validated replay 和 4 个 skipped steps，csv family 只有 history-backed reuse，没有 replay skip。

Track A 已成功把 logit telemetry 带到所有 StateBus case：共有 313 个 case-layer 观测，全部 quality pass，peak 从未落在最后 token，通常位于最后 token 前约 1 个位置。varentropy 有非零区分度，但整体偏低，且 confidence gate 总触发数为 0；因此当前只证明“观测链路有效”，未证明决策质量提升。Track B 没有被任何 runner 导入或激活，必须另做预测值对实测 vLLM gauge 的校准实验。

## Stage 结果

| Stage | 状态 | 关键结论 |
| --- | --- | --- |
| S0 | 通过 | vLLM health 与 GPU 快照落盘；没有压力或 per-stage cache metric |
| S1 | 形式通过 | 4 项环境检查通过，但未调用 schema-constrained generation，不能验证 Track C |
| S2 | 通过 | 2 cases × 4 layers，logit transfer 8/8；peak 均非末位 |
| S3 | 数据生成成功，wrapper 失败 | live runner 完成；旧 jq 汇总因 `.layers` 为空报错；comparison 本身因 quality gate 无效 |
| S4 | 命令成功，目标失败 | 实际运行 cold-start formal ladder，未启用 replay-ready bootstrap |
| S5 | 通过 | 2 families、20 rounds、20/20 quality、0 runtime fallback |
| S6 | 通过 | 25 cases、5 families、L0-L3 各 25/25；内部 token attribution 成立 |

## Track A: Logit Peak-Scan

- Stage 2 的 peak position 为 33/37 等值，对应 executor completion 的倒数第二个 token 索引；8 个 layer-case 观测均避开最后 token。
- 全部实验汇总的 peak-before-last 为 313/313，peak-is-last 为 0。
- varentropy 范围 0.000002 到 0.034244，均值 0.004632。它能区分受约束程度，但数值很小，尚无校准阈值。
- top-gap 范围 0.0624 到 0.9979。较大 gap 表示 peak token 仍较确定，不能仅凭“最大 entropy”认定存在真实语义歧义。
- S3/S4/S5/S6 的 StateBus 路径均有正的 `logit_state_transfer_count`；external baseline 不经过该链路。
- `logit_confidence_gate_trigger_count=0`，且没有旧算法 A/B 或关闭 logit 的质量对照。结论限定为 telemetry plumbing validated，不是 quality improvement validated。
- logit transfer 与 shared prefix bytes 在每个完成 case 中共同出现，但 transfer_count 基本恒为 1，统计方差为零，不能计算有意义的相关系数，也不能推导因果关系。

## Track B: Prefix Feedback

`PrefixCacheFeedbackLoop` 只存在于未跟踪文件 `v2/runtime/prefix_feedback.py`，仓库搜索未发现 runner/runtime/tests 的调用。所有本轮 artifact 也没有 `prefix_feedback_*` telemetry。Track B 状态为 implemented prototype / not deployed / not experimentally validated。

最低验证设计应在每个 stage 前后抓取 vLLM `/metrics`，记录预测 hit-rate、实际 `gpu_prefix_cache_hit_rate`、服务生命周期和请求数，再比较 feedback 开/关下的 reorder 决策、TTFT 与质量。当前不能使用累计 service gauge 反推某个 stage 的实际命中率。

## Track C 与 Stage 3 根因

Track C 的 `_build_baseline_selection_schema()` 使用 `additionalProperties=false`，required 仅为 `candidate_key/route/tool_name`。同一个 schema 被传给 Retriever 和 Executor，但 Retriever prompt 明确要求 `evidence_summary/metric_name/metric_value/selected_doc_hashes`。受约束解码会合法地删除这些字段，后续 scorer 读取到空字符串。

25 个 external case 的共同模式：

- route exact: 25/25
- tool exact: 25/25
- selected doc hashes exact: 25/25
- summary present: 25/25，且样例 summary 包含正确事实值
- metric_name exact: 0/25
- metric_value exact: 0/25
- admissible match / quality floor: 0/25
- external fairness hard gate: 25/25

因此 quality floor 并非“对 Qwen3-32B 过严”这一单一问题。它正确暴露了结构化事实字段缺失，但 `exact_match=25/25` 与 quality floor 0/25 同时出现也说明 legacy `exact_match` 语义过宽，容易误导。应分别为 Planner、Retriever、Executor、Summarizer 建 schema；Retriever schema 必须包含评分所需事实字段，Executor schema 必须与其 prompt/action contract 一致，并增加 schema-contract regression test。

让 `comparison_valid=true` 的必要条件：修复 role-specific schema 后重跑 25/5 compare；external 与 StateBus 都通过相同 quality floor；fairness gate 继续 25/25；只有 strict equal-quality 成立时，total/prompt token delta 才能进入 formal efficiency claim。

## G-01: Compare 公平性

Stage 3 覆盖了 25 cases / 5 families，fairness manifest 的 same tier、same role graph、same scorer、no contamination 均通过，因此“实验范围与角色公平性”比历史 8-case API compare 更完整。但结果质量不等价，`comparison_valid=false`、`strict_equal_quality_comparison_valid=false`、formal efficiency superiority 不允许。

Stage 6 没有 external baseline，所以不会遇到同一种 schema failure；它的 L0 与 L3 都在 StateBus runner 内完成并各 25/25。该结果只支持 internal attribution，不关闭 G-01 的 external same-task equal-quality gap。

## G-02: Replay Memory

Stage 4 的 L3 指标：reuse_gain=0、skipped_step_count=0、validated_replay_count=0、memory_match_count=0。`seed_replay_memory_by_layer` 四层均为 false，证明 auto-bootstrap 没有进入目标代码路径。

代码根因是 formal-tier non-compare 分支先调用 `run_minimal_benchmark_suite()` 并 return；后面的 `if args.suite == "statebus"` 永远不可达。修复需让 formal statebus suite 走 fixed-answer statebus runner，或为 minimal formal runner显式传入 replay-ready/history bootstrap contract，并新增 assertion：请求 replay-ready 时 L3 metadata 必须显示 history source，且至少一个 replay target 被观测。

本轮没有持久化任何 stage 前后 vLLM `/metrics` 快照，所以实际 GPU prefix cache hit rate不可恢复。`neural_prefix_cache_hit_count_estimate` 只能标为控制面推断，不能替代实测 gauge。

## G-03 / G-11: Multi-Family 与连续稳定性

| Family | Rounds | L3 quality | L3 total tokens | Replay / skip | History reuse | Headline scope |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| csv_table_profile_v1 | 10 | 10/10 | 38368 | 0 / 0 | gain 1, step reduction 2 | history-backed only |
| cross_period_financial_v1 | 10 | 10/10 | 27990 | 4 / 4 | gain 8, step reduction 12 | replay admissible |

两组 family 均完成，20/20 quality pass，L3 runtime fallback 为 0。cross-period 的目标 rounds 2/4/6/8 全部出现 validated replay，G-03 和“能连续跑 10 rounds”的 G-11 已显著补强。限制是每个 family 只跑一次，没有多 seed/repeat、误差线、服务重启隔离或 per-round vLLM gauge，因此只能 claim single-run continuous stability。

## Stage 6 Formal

| Layer | Cases | Quality pass | Total tokens | Logit transfer | Semantic transfer | Reuse gain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| L0 | 25 | 25 | 109841 | 25 | 0 | 0 |
| L1 | 25 | 25 | 110071 | 25 | 0 | 0 |
| L2 | 25 | 25 | 66472 | 25 | 25 | 0 |
| L3 | 25 | 25 | 66472 | 25 | 25 | 0 |

L3 vs L0：total tokens -43369.0（-39.48%），prompt tokens -40128.0（-40.28%），quality delta 0。L1 的 tokens 略高于 L0，主要收益来自 L2 semantic pruning，而 L2 与 L3 完全相同，进一步证明本轮没有 replay 增量。

Formal claim 边界：可以 claim Qwen3-32B 下 25-case/5-family internal attribution quality parity 和 token reduction；不能 claim external baseline efficiency superiority、真实 KV tensor handoff、Stage 6 replay gain 或 per-stage GPU cache hit-rate。

## 历史 API 对照

| Evidence | Scope | Quality | Token / reuse result | Interpretation |
| --- | --- | --- | --- | --- |
| API formal internal `r01_05`（归档未保留模型标识） | 25 cases / 5 families | 25/25 L3 | memfd 25 transfers, 247076 bytes | 完整 API formal 质量与 state transfer 证据 |
| API external compare `r01_06`（归档未保留模型标识） | 8 cases / 1 family | strict equal-quality valid | StateBus total-token delta +6463.0 | 等质量但 total tokens 退步，claim=debug_only |
| Qwen3 Stage 3 | 25 cases / 5 families | 25/25 vs 0/25 | delta -29120.0 | token 方向更好但 baseline schema 失效，不可比较 |
| API continuous `r01_09` | 3 families / 30 rounds | completed | L3 reuse_gain 9.0 | 多 family history reuse 更广 |
| API replay `r01_10` | 3 families / 30 rounds | replay targets 20/20 | 17 validated, 3 exact, reuse_gain 20.0 | replay 证据强于本轮 Stage 4 |
| Qwen3 Stage 5 | 2 families / 20 rounds | 20/20 | 4 validated replay, 4 skipped steps | local vLLM replay 正向进展，但覆盖更小 |

Qwen3 相对历史 API 路径的进步是 formal registry 覆盖从 external 8/1 扩展到 25/5、internal L0-L3 token reduction 明确、local vLLM continuous replay 首次出现正值。退步/未闭环之处是 external baseline schema 回归导致 0/25、Stage 4 formal replay flag 被吞、实际 prefix gauge 未采集，且没有统计 repeat。由于历史 summary 未归档 role model 名称，这不是严格的 Qwen3 vs DeepSeek 模型隔离实验，不能把差异全部归因于模型。

## Bug 与优化优先级

### P0

1. External baseline role schema contract mismatch：拆分 Retriever/Executor schema，恢复 metric/evidence/doc 字段，补 25-family-aware regression tests。
2. Stage 4 formal routing bug：保证 replay-ready 不被 minimal formal branch截获；runner 应在输出 metadata 中回显 effective statebus mode/history source。
3. Claim guard：当 external quality 为 0 或 strict equal-quality false 时，禁止把 token delta写入 headline；保留 quality-superiority 字段但明确它不是 efficiency comparison。

### P1

1. 综合脚本 summary：export `STAMP/RESULTS_DIR/HOST_RUNS_ROOT`，按真实 schema 读取；compare jq failure 应只影响 summary，不把成功的 live runner 标成 stage failure。
2. Stage 1 加一个真实 schema probe case，并验证评分所需字段，而不只是 environment preflight。
3. 每个 stage 前后采集 vLLM `/metrics`、请求计数和 service-lifetime id；clean-service 实验单独重启服务。
4. 持久化 `logit_sequence_length`、`decision_entropy` 和 per-role logit source，避免用 completion token 数近似判断 peak 是否末位。
5. 将 PrefixCacheFeedbackLoop 接入调度器和 telemetry，并增加 feedback on/off A/B。

### P2

1. 连续实验增加 3 seeds 或 3 clean repeats，输出 TTFT/token/replay 的均值、标准差和失败率。
2. 解释/修正 legacy `exact_match=25/25` 与 quality 0/25 的语义冲突。
3. 分离 dynamic pruning 的 token 收益、structured control 的 carrier 收益与 prefix cache 的 engine 收益，避免把 L0-L3 总 delta 全归因于 protocol。

## 仍缺实验

- 修复 schema 后的 Qwen3 full 25/5 external compare，目标 strict equal-quality + comparison_valid=true。
- 修复 formal routing 后的 replay-ready 25/5 run，要求 reuse_gain/skipped steps/validated replay 至少一项为正。
- Track B feedback on/off clean-service A/B，直接读取 vLLM gauge 与 TTFT。
- Track A peak-scan vs old last-token telemetry A/B；需要预注册阈值和真实 decision intervention，而非只记录字段。
- answer_restoration 端到端验证仍为 0，需要 replay 后答案等价性检查。
- mmap formal artifact、subprocess UDS formal 路径、openEuler VM smoke/pytest 仍未由本轮覆盖。
- 统计 repeat、错误条/置信区间和服务生命周期隔离仍缺失。

## 最终判定

Track A：链路有效，质量收益未验证。Track B：未部署。Track C：本轮构成 schema 回归。G-01：internal attribution 已补强，external公平效率未关闭。G-02：Stage 4 未关闭，根因是 runner routing。G-03：已通过两个 local-vLLM continuous family 补强。G-11：单次 10-round×2 family 稳定性成立，但无统计 repeat。Stage 6：formal internal claim 可用，external superiority claim 不可用。
