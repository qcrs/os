# 2026-07-08 artifact mining 深度拆解

本文基于两组 run artifact 的递归抽取结果，而不是人工挑单个 report 读数：

- Base run：`/home/qcrs/statebus/runs/sb2-gpu1-20260708_084458`
- Supplement run：`/home/qcrs/statebus/runs/sb2-gpu1-health-20260708_110413`
- 抽取脚本：`scripts/analyze_v2_artifact_evidence.py`
- 机器汇总：`12_artifact_mining_summary_20260708.json`
- 可读索引：`12_artifact_mining_readout_20260708.md`

抽取覆盖面：

| Run | JSON seen | JSON loaded | Benchmark reports | Prompt slices | Telemetry files | Load errors |
|---|---:|---:|---:|---:|---:|---:|
| `sb2-gpu1-20260708_084458` | 23928 | 23919 | 73 | 1976 | 494 | 9 |
| `sb2-gpu1-health-20260708_110413` | 17642 | 17632 | 58 | 1456 | 364 | 10 |

少量 load errors 不影响主结论；本轮主结论来自正式 benchmark reports、stage stdout、prompt slices 和代码 gate 的交叉验证。

## 总体判断

当前结果能支撑的主 claim 是：

- full-registry formal external compare 支持 `quality_superiority`：StateBus 25/25，external pure-text 15/25。
- 同一 compare 中 StateBus 同时降低 prompt tokens 57.9%，降低 total tokens 49.7%。
- formal internal 25 cases / 5 families 在 API + local embedding + memfd 下 25/25 通过，且 L2/L3 有 25 次 semantic StateRef/memfd transfer。
- continuous/replay 证明共享记忆与 replay 不是文档功能：base replay 有 18 validated replay / 2 exact replay；supplement flagship replay rerun 达到 3/3 replay-headline families。
- CodeAct bwrap acceptance 5/5 通过，说明系统完整性和轻量沙箱路径可运行。
- KV prefix demo 只能读作 engine-local prefix identity/scheduling estimate，不是实际 vLLM prefix-cache hit，也不是 KV tensor 或 hidden-state transfer。

当前不能 claim：

- 不能 claim latency superiority：`serialized_latency_superiority_claim_allowed=false`，且 task/LLM/system overhead delta 都是 StateBus 更慢。
- 不能 claim strict equal-quality efficiency superiority：`strict_equal_quality_comparison_valid=false`，formal external compare 的有效 claim kind 是 `quality_superiority`。
- 不能 claim protocol carrier 在 formal text/protocol internal compare 上全面优于 text；该 compare 覆盖 25/5，但 structured 侧少 1 个 quality pass，并且 total tokens/task time 上升。
- 不能 claim openEuler VM 最终验证、真实 vLLM prefix-cache metrics、KV tensor handoff、hidden-state handoff。

## Formal External Compare

source：

`work/r01_07_formal_compare_api_local_memfd/runtime/benchmark_reports/sb2-gpu1-20260708_084458-r01_07_formal_compare_api_local_memfd-cold-start-compare.json#mode_reports[0]:api`

核心读数：

| Metric | StateBus | External | Delta | 解读 |
|---|---:|---:|---:|---|
| quality pass | 25 | 15 | +10 | 支持 quality-superiority |
| prompt tokens | 48754 | 115734 | -66980 | StateBus 输入侧显著更短 |
| completion tokens | 13062 | 7237 | +5825 | StateBus 输出侧更重 |
| total tokens | 61816 | 122971 | -61155 | 尽管 completion 增加，总 token 仍下降 |
| task ms delta | - | - | +73103.7 | StateBus 更慢 |
| LLM ms delta | - | - | +37201.9 | LLM 侧更慢 |
| system overhead ms delta | - | - | +35901.8 | runtime/IO/sandbox/telemetry 开销更高 |

### 为什么能 claim quality-superiority

代码 gate 在 `v2/benchmark/comparator_runner.py`：

- `quality_superiority_comparison_valid` 要求 fairness hard gate 通过、StateBus report eligible、且 `quality_floor_pass_delta > 0`。
- 本轮 external fairness gate coverage=true，pass_count=25，failed_case_count=0。
- StateBus 25/25，external 15/25，因此 `quality_floor_pass_delta=10`。

external 失败不是因为不公平地少给了候选，也不是 route/tool/doc 选错。10 个 external failed cases 的 failed dimension 全部是 `metric_value_exact=0`：

| Family | StateBus quality | External quality | External failed dimension |
|---|---:|---:|---|
| `anomaly_detection_v1` | 3/3 | 0/3 | `metric_value_exact` |
| `conditional_aggregation_v1` | 4/4 | 0/4 | `metric_value_exact` |
| `multi_period_trend_analysis_v1` | 5/5 | 2/5 | `metric_value_exact` |
| `cross_table_join_analysis_v1` | 5/5 | 5/5 | none |
| `financial_report_analysis` | 8/8 | 8/8 | none |

这说明 StateBus 的有效收益集中在“结构化数值投影 + evidence/artifact 可审计化”上：external pure-text 四角色能看到候选并能选对 route/tool/doc，但在复杂表格聚合、异常检测、趋势计算里更容易生成错误数值。

### 为什么不能 claim strict equal-quality efficiency

strict equal-quality compare 的语义是双方质量相等后再比效率。代码里 formal efficiency gate 要求：

- `comparison_valid=true`
- `llm_total_tokens_delta < 0`
- `prompt_bytes_delta < 0`
- `quality_floor_pass_delta == 0`

本轮 `quality_floor_pass_delta=10`，所以 strict equal-quality comparison 本身就是 false。虽然 StateBus total tokens 低 49.7%，但这是在 StateBus 质量更高的条件下取得的，不能把它改写成“同质量更高效”。

### 为什么 prompt/total 下降但 completion 上升

prompt token 下降来自两层：

- external pure-text 要把候选、证据和中间语义以可读长文本反复塞给四个角色。
- StateBus 用 typed state、selected evidence、metric projection 和 artifact refs 收敛输入面，尤其在 anomaly / aggregation 这类长表格任务上明显。

completion token 上升主要来自 StateBus 的严格 JSON role surface：

- `v2/runtime/role_path.py` 的 `_complete_json_role` 要求每个 role 返回合法 JSON；失败还会追加 JSON retry instruction。
- StateBus 输出里包含结构字段、audit/replay/summary JSON、artifact metadata，external 则更接近自由文本短答。
- 因此 completion 增加不是“优势反证”，而是结构化输出可审计性的成本。当前最准确的说法是：StateBus 用更重的结构化 completion 换来了更短的 prompt、更低 total tokens 和更高数值正确率。

### 为什么不能 claim latency

代码 gate 在 `v2/benchmark/comparator_runner.py` 中要求：

- benchmark tier 是 formal；
- strict equal-quality comparison valid；
- 所有 mode 的 `task_ms_delta < 0`。

本轮恰好相反：

- `strict_equal_quality_comparison_valid=false`
- `task_ms_delta=+73103.7`
- `llm_ms_delta=+37201.9`
- `system_overhead_ms_delta=+35901.8`

原因拆解：

- 四角色 API call 数没有减少，`llm_call_count_delta=0`。
- StateBus JSON completion 更长，且 role path 要做 JSON extraction/validation。
- StateBus runtime 还要做 artifact bundle、persist/reload、memfd publish/transfer、telemetry、bwrap CodeAct 等额外系统工作。
- formal external compare 中 StateBus codeact execution stage 约 22.4s；这提升系统完整性，但不帮助 latency headline。

所以当前 latency 是明确负结果。后续如果要重开 latency claim，必须做 serialized repeat rerun，并单独拆 JSON completion、bwrap、persist/telemetry、memfd 各自开销。

## Formal Internal Layer Waterfall

source：

`work/r01_05_formal_api_local_memfd/runtime/benchmark_reports/sb2-gpu1-20260708_084458-r01_05_formal_api_local_memfd-formal-suite.json`

| Layer | Quality | LLM prompt bytes | Visible bytes | Raw evidence bytes | Semantic transfers | memfd transfers |
|---|---:|---:|---:|---:|---:|---:|
| L0 text | 25/25 | 254842 | 180106 | 173736 | 0 | 0 |
| L1 structured carrier | 25/25 | 243692 | 180106 | 173736 | 0 | 0 |
| L2 semantic StateRef | 25/25 | 139732 | 77304 | 70934 | 25 | 25 |
| L3 memory/replay-enabled cold start | 25/25 | 139732 | 77304 | 70934 | 25 | 25 |

关键拆解：

- L1 相比 L0 主要省 scaffolding/control，visible evidence 没变，所以收益有限：prompt bytes 只降 11150。
- L2 才是主要转折点：引入 semantic StateRef + memfd 后，prompt bytes 相比 L0 降 115110，visible bytes 降 102802，raw evidence bytes 降 102802。
- L3 在 cold formal 里和 L2 基本相同，`reuse_gain=0`。这不是 bug，而是 formal cold-start 任务没有 replay history；memory/replay 优势要读 continuous/replay，不应从 cold formal 强行 claim。
- memfd data plane 是真实发生的：25 publish/transfer，247076 bytes transferred。

这部分支持“非文本中间状态传递确实进入主链路”，但不能扩大成 hidden-state/KV transfer。当前非文本对象是 embedding/semantic state refs、hydration accounting、memfd-backed materialization。

## Formal Text/Protocol Carrier Compare

source：

`r01_06_formal_carrier_compare_api_local_memfd`

metadata 显示它是 `formal_registry_25case_5family_text_protocol_compare`，覆盖 full registry 25/5。但它是 internal carrier compare，不是 external baseline。

| Metric | Delta | 解读 |
|---|---:|---|
| control bytes | -30665 | structured carrier 明显减少控制面字节 |
| prompt scaffolding bytes | -11150 | structured carrier 减少模板/协议 scaffolding |
| prompt visible bytes | 0 | 证据可见内容未减少 |
| raw evidence bytes | 0 | 证据选择未改变 |
| llm total tokens | +4161 | structured side completion/format 成本更高 |
| task ms | +16836.6 | structured side 更慢 |
| quality floor pass | -1 | structured side 少 1 个 pass |
| route exact | -1 | `formal-trend-002` route miss |

这个结果的价值是拆 carrier 成本：typed protocol 能压 control/scaffolding，但只靠 carrier 不等于质量或速度优势。它还暴露一个仍需修的点：`formal-trend-002` 在 structured L1 carrier compare 中 route_exact=0，但 metric/tool/doc/value 都正确。这更像 structured route surface 或 candidate normalization 的稳定性问题，应补 targeted regression。

## Continuous / Replay

Base continuous：

| Stage | Families | Rounds | Quality headline families | Replay headline families | L3 reuse gain | Artifact reuse | Validated replay | Exact replay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `r01_10_continuous_api_local` | 3 | 30 | 2 | 0 | 9 | 50 | 4 | 5 |

Base continuous-replay：

| Stage | Families | Rounds | Replay target | Replay observed | Replay headline families | L3 reuse gain | Validated replay | Exact replay |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `r01_11_continuous_replay_api_local` | 3 | 30 | 20 | 19 | 2 | 20 | 18 | 2 |

关键拆解：

- Continuous 证明 history-backed reuse 真实发生：artifact reuse 50，history step reduction 13，L3 reuse gain 9。
- Continuous-replay 证明 replay 真实发生：18 validated replay，2 exact replay，`answer_restoration_replay_count=0`，说明没有把答案恢复冒充 replay。
- Base replay 的缺口集中在 `long_doc_metric_replay_v1`：target round 7 缺失，且 gate reason 包含 `quality_gate_failed;missing_target_replay_rounds;missing_exact_target_rounds`。

Supplement flagship rerun 进一步关闭了这个 family-level 缺口：

| Supplement scope | Replay headline families | Replay target | Replay observed | Validated replay | Exact replay | L3 reuse gain |
|---|---:|---:|---:|---:|---:|---:|
| continuous-replay under `s01_10_flagship_ablation_api_local` | 3/3 | 20 | 20 | 17 | 3 | 20 |

因此当前最准确说法是：

- Base comprehensive run 已证明 replay 路径有效，但 2/3 replay families 进入 headline。
- Supplement rerun 证明同一类 flagship replay family-level 修复后可达 3/3 replay-headline families。
- 仍应在后续 comprehensive base 脚本里把该补跑合入正式 required/optional evidence，而不是长期靠人工拼读。

## Flagship Non-Text State Stress

source：

`artifacts/stages/s01_10_flagship_ablation_api_local/stdout.json`

stress summary：

| Family | Scope | Pass | LLM prompt saved | Visible saved | 解读 |
|---|---|---:|---:|---:|---|
| `csv_correlation_replay_v1` | claimable | yes | 12980 | 7242 | 最强正例，StateRef 直接减少 visible prompt |
| `long_doc_metric_replay_v1` | claimable | yes | 3885 | 615 | 长文指标 replay 正例 |
| `long_doc_table_v1` | claimable | yes | 941 | 18 | 小幅 visible saving |
| `cross_period_financial_v1` | claimable | yes | 1957 | 0 | 主要省 scaffolding，不省 visible |
| `csv_table_profile_v1` | claimable | yes | 1562 | 0 | 主要省 scaffolding，不省 visible |
| `incident_diagnosis_v2` | diagnostic-only | no | 0 | 0 | semantic selection dominates，StateRef 没额外 saving |

这个实验比单纯 L2/L3 waterfall 更有诊断价值，因为它用 T2 text same semantic selection 控制了“选中了什么证据”这个变量。结论是：

- StateRef family-level 正证据成立，5 个 claimable families 通过。
- 收益分两类：一类真的减少 visible prompt，一类主要减少 scaffolding/structured handoff。
- 不具备 universal claim；`incident_diagnosis_v2` 是明确负例，说明有些任务瓶颈在 semantic selection 本身，不在 state ref carrier。

## KV Prefix Demo

source：

`artifacts/stages/s01_08_kv_prefix_demo_api_local/stdout.json`

读数：

| Metric | Value |
|---|---:|
| L3 quality | 10/10 |
| L3 reuse gain | 6 |
| corpus prefix hash reuse count | 8 |
| corpus-level prefill saved tokens estimate | 2144 |
| engine-local prefill saved tokens estimate | 2680 |
| replay headline | false |
| replay gate reason | `missing_target_replay_rounds` |

代码边界在 `v2/benchmark/kv_analysis.py` 写得很清楚：`theoretical_prefix_reuse_analysis_only_actual_vllm_metrics_required_for_mechanism_claim`。

因此当前 KV 只能作为 future-work / estimate evidence：

- 可以说 prefix identity 和 engine-local reuse scheduling 能被分析出来。
- 可以说 demo 质量通过，且出现 corpus prefix reuse estimate。
- 不能说真实 vLLM prefix-cache hit。
- 不能说 TTFT 下降。
- 不能说 KV tensor 或 hidden-state 在 agent 间传递。

## CodeAct

source：

`artifacts/stages/s01_07_codeact_acceptance_api/stdout.json`

5/5 acceptance 成功，5 次均为 `generated_by=llm_api`，`ast_policy_pass=true`，`sandbox_backend=bwrap`，没有 generation fallback。

它支持的 claim 是系统完整性和可隔离 CodeAct 路径可运行。它不支持 latency superiority；在 formal external compare 中，CodeAct/bwrap 是 StateBus system overhead 的组成部分。

## 问题与修复计划

### P0：carrier compare 的 `formal-trend-002` route miss

现象：

- formal text/protocol carrier compare full 25/5 覆盖。
- structured side 24/25，text side 25/25。
- failed case：`formal-trend-002`，`route_exact=0`，但 `tool_exact=1`、`metric_name_exact=1`、`metric_value_exact=1`、`selected_doc_hashes_exact=1`。

判断：

- 这不是数值计算能力问题，而是 structured route label/candidate normalization 稳定性问题。
- 影响 text/protocol carrier superiority 读法；不能把 carrier compare 写成 equal-quality win。

修复：

1. 抽取 `formal-trend-002` 的 planner/retriever/executor prompt slice、raw JSON completion 和 selected candidate key。
2. 对比 L0 text 与 L1 structured 的 visible candidate keys、route normalization、candidate_key fallback。
3. 增加 targeted pytest 或 fixture regression，断言 structured route 输出不会把正确 tool/doc/value 组合映射到错误 route。
4. rerun `r01_06_formal_carrier_compare_api_local_memfd`。

### P0：latency 拆分仍未形成可优化闭环

现象：

- task delta +73.1s，LLM delta +37.2s，system overhead delta +35.9s。
- formal gate 明确禁止 latency claim。

修复：

1. 给 formal compare 输出增加 role-level latency split：planner/retriever/executor/summarizer JSON completion、retry count、completion tokens。
2. 单独打点 bwrap/CodeAct、persist/reload、memfd publish/transfer、telemetry flush。
3. 做 serialized repeat rerun，至少 repeat=3，避免单轮 API 抖动误判。
4. 尝试瘦身 JSON completion schema，把“benchmark audit 字段”和“role 必需输出字段”分开，减少 completion inflation。

### P1：base/supplement 证据应合并为正式 comprehensive 读法

现象：

- Base required stages 全部通过，但 optional flagship old stage failed。
- Supplement 实质 stage 全部通过，但 raw exit=1 来自两个 base-audit false-negative gates。

修复：

1. 保留原始 artifact 不改写。
2. 后续 comprehensive script 应支持 base artifact + supplement artifact 合并判定。
3. base audit gate 不应只看 stage stdout 顶层；需要回填读取 `summary.json.key_metrics` 和正式 report metadata。
4. 对合法 `0` 值不要用 `or -1` 这类会误杀的默认值写法。

### P1：KV prefix 要么降级文案，要么补实际 vLLM probe

现象：

- KV demo 质量和 estimate 成立。
- vLLM metrics / TTFT probe skipped。

修复：

1. 文档中固定写 `Engine-Local Prefix Reuse estimate`。
2. 若要升级 claim，启动 local vLLM prefix-cache service，打开 `STATEBUS_RUN_VLLM_PREFIX_PROBE=1`。
3. 收集真实 prefix-cache hit、TTFT、prefill latency delta。

### P1：openEuler/container final validation 仍缺

现象：

- 当前 runs 是 container/local+api evidence，不等于 openEuler 24.03-LTS-SP3 final delivery validation。

修复：

1. 在 openEuler target 环境跑 py_compile、targeted pytest、preflight、formal internal、formal external compare。
2. 记录 OS/version/GPU/driver/Python/package lock。
3. 只有该阶段通过后才能写 openEuler compatibility claim。

## 面向赛题评分的当前读法

| 评分面 | 当前证据 | 强度 | 口径 |
|---|---|---|---|
| 通信效率 | formal external prompt tokens -57.9%，total tokens -49.7%；formal internal L2 prompt bytes 较 L0 -45.2% | 强 | 可 claim prompt/total token reduction；不可 claim latency |
| 状态传递创新 | 25 次 semantic StateRef/memfd transfer；flagship 5/6 stress，5 claimable families pass | 强但非 universal | 可 claim embedding/semantic state ref + memfd data plane；不可 claim KV/hidden-state transfer |
| 记忆复用效果 | base 18 validated replay / 2 exact replay；supplement flagship replay 3/3 families | 中强 | 可 claim replay/reuse 在连续任务成立；cold formal 不读 memory benefit |
| 系统完整性 | pytest/smoke/formal/preflight/CodeAct bwrap 5/5 | 强 | 可 claim v2 main path runnable；openEuler final validation 仍待补 |
| 实验验证 | full 25/5 formal compare + continuous/replay + supplement health | 强 | 证据覆盖明显提升；后续需 serialized repeat latency 和 openEuler validation |

最终建议的对外一句话：

StateBus v2 当前最强优势不是端到端速度，而是在 full-registry formal local+api 条件下，通过 typed protocol、semantic StateRef/memfd 和 artifact-based numeric projection，显著降低 prompt/total token，同时把 external pure-text baseline 容易错的数值抽取/聚合任务从 15/25 提到 25/25；共享记忆/replay 和 CodeAct 路径已经有补充实验证据，但 latency、KV prefix-cache 和 openEuler final validation 仍必须保守表述。
