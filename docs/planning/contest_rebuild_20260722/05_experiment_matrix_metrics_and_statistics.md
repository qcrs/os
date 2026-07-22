# 05 实验矩阵、指标、统计与 Claim Gate

> **事实来源**：canonical E0-E6 历史报告、[`readiness audit`](../../reports/statebus_v2_contest_readiness_audit_20260722.md)、当前 telemetry/runner 代码，以及 [`02`](02_prefix_engine_local_reuse_design.md)、[`03`](03_logitstate_core_chain_design.md)、[`04`](04_vertical_data_preprocess_and_task_design.md) 的 preregistration。
> **设计假设**：正式 API timing 全部串行；能取得排他服务窗口；冷 cache epoch 若需重启将另行授权。
> **待验证实验**：R0-R12、L0-L3、P-A/P-B/P-C、L-A/L-B/L-C/L-D。本文件只定义设计和判定，不含正式结果。

文档导航：[索引](README.md) | [00 决策与包装](00_executive_decision_and_packaging.md) | [01 现状与整改](01_current_state_and_remediation.md) | [02 Prefix](02_prefix_engine_local_reuse_design.md) | [03 LogitState](03_logitstate_core_chain_design.md) | [04 数据与任务](04_vertical_data_preprocess_and_task_design.md) | [05 实验](05_experiment_matrix_metrics_and_statistics.md) | [06 实施与验收](06_implementation_plan_and_acceptance.md) | [07 辅助核对](07_auxiliary_verification_record.md)

## 1. 实验架构原则

```text
Main matrix M: 只测 L0-L3（prefix=off, logit=off, latent=off）
Semantic mechanism S: state off/on/perturbed（memory/prefix/logit=off）
Memory matrix H: off/disclosed/actual-consumed（prefix/logit/latent=off）
Prefix matrix P: off/friendly/hostile（memory/logit/latent固定）
Logit matrix G: off/telemetry/gated（prefix/memory/latent固定）
```

每个矩阵只有一个主要改变项。实验 ID、run root、manifest、order 和 stopping rule 在首个模型请求前冻结。失败、timeout、fallback、invalid observation 均保留并进入分母；不得删掉后重跑同一 ID。

## 2. R0-R12 必要实验

| ID | 研究问题 | 固定项 / 唯一改变 | 主要输出 | 通过/降级规则 |
| --- | --- | --- | --- | --- |
| R0 Freeze/Regression | 当前版本可识别且可复现吗 | 固定 source/config/data/runtime/image；无 treatment | hashes、dirty diff digest、focused/full tests、preflight | 未 freeze/测试失败不进入 formal |
| R1 Embedding mechanism | matrix是否跨 PID消费并改变 hydration | 同 task/evidence/model；state off/on/合法 perturb/refusal | ref/shape/dtype/bytes/PIDs/selected IDs/hydration/release/quality | true chain闭环且质量不降；否则只保留实现事实 |
| R2 L0-L3 causal matrix | control/semantic/memory各自影响 | 同 tasks/model/roles/topology/validator；只按 lane开关 | bytes/tokens/state/memory/quality/latency descriptive | 每 lane quality过门；不强求 latency优势 |
| R3 2x10 continuous | 两条公开企业链是否稳定 | 两 frozen families，独立 roots | 每轮依赖、artifact、rejection/recompute、10/10 | 每 family恰好10/10；不能跨 family凑数 |
| R4 Memory actual effect | memory是否真实进入prompt/recipe并有作用 | memory off/disclosed-only/actual consumed + incompatible | receipt、quality、calls/steps/tokens/latency | candidate不计consume；无effect降为store/query机制 |
| R5 Prefix render integrity | common prefix是否exact same tokens | stable vs reordered/unstable/legacy；evidence等固定 | token hash/count/full blocks、visibility、quality | exact equality + negative control + quality等价 |
| R6 Prefix engine mechanism | schedule是否改变真实APC observation/TTFT | same request multiset；friendly vs hostile | valid query/hit token delta、TTFT、order、cold/hot | 无valid counters只报 unavailable；不以estimate替代 |
| R7 Prefix end-to-end | prefix policy有净任务价值吗 | tasks/other flags固定；prefix off/on | total/stage latency、tokens、quality、scheduler cost | quality等价、paired CI；无total优势只留R6 |
| R8 Logit calibration | features能预测闭集选择错误吗 | calibration data；feature/calibrator policy改变 | reliability/ECE/Brier/NLL/risk-coverage/AURC | 无预测力/校准价值则 telemetry-only/off |
| R9 Logit lifecycle | float Ref是否被独立consumer使用 | valid vs permuted/corrupt/expired/wrong task | PIDs/bytes/gate decision/effect/release | publish-resolve-consume-effect-release全闭环 |
| R10 Logit quality-cost | gate是否有净verified价值 | off/telemetry/calibrated gate | recovery/false trigger/quality/extra calls/tokens/latency | 无净价值不进headline；成本必须同报 |
| R11 Public vertical holdout | 是否非repo-local造例 | public source ledger + frozen issuer-disjoint holdout | source/terms/hash/transform/gold visibility/quality | 任一 provenance/gold隔离失败只能称repo-local |
| R12 Natural capability coverage | semantic/table、DSL/Python是否自然选择 | frozen tasks；不强制route | selected counts、candidate surface、failures | 只报告自然计数；未覆盖就缩窄claim |

R5/R6/R7 分别等价于 P-A/P-B/P-C；R8/R9/R10 覆盖 L-A-D，详细 treatment 见对应机制文档。

## 3. L0-L3 主矩阵

| Lane | 唯一新增机制 | 必须关闭/固定 | 预期回答 |
| --- | --- | --- | --- |
| L0 | matched pure-text collaboration | typed refs、semantic selection、memory、prefix/logit/latent关闭 | 同 harness text comparator 的成本/质量 |
| L1 | L0 + typed Protobuf/UDS control | semantic state、memory、prefix/logit/latent关闭 | control/wire bytes；不预设 token下降 |
| L2 | L1 + embedding SemanticStateRef + selected hydration | memory、prefix/logit/latent关闭 | numeric state/hydration、prompt-visible context、quality |
| L3 | L2 + compatible MemoryRef/assist/replay | prefix/logit/latent关闭；无跨lane memory | actual memory receipt、replay/skip/cost |

共同固定：

- `CanonicalTaskSpec`、source corpus/hash、request/gold、role order/candidate surface；
- model/revision/tokenizer/template/temperature/seed/max tokens；
- embedding model/revision/dims/device；
- subprocess topology、executor transport、workspace/state backend profile；
- validator/tolerance/citation policy、timeout/retry/fallback；
- public 2x10 family manifests；
- 串行 run，独立 lane roots；L3 memory只能来自同 family同 lane已通过的历史轮。

L0 必须标为 `matched text comparator inside StateBus harness`，不能称外部独立系统。若某 lane 的 role-visible business information 不同，fairness audit失败，该 pair不进入 superiority comparison。

## 4. 辅助矩阵

### 4.1 Semantic S

| Lane | State | 目的 |
| --- | --- | --- |
| S0 | off，deterministic baseline selection | baseline quality/context |
| S1 | true `<f4` Ref + independent selector | mechanism/effect |
| S2 | approved row permutation + matching/incorrect manifest controls | selected-ID counterfactual与fail closed |
| S3 | hash/lease/task incompatible | rejection/cleanup |

### 4.2 Memory H

| Lane | Role visibility/use | 计数规则 |
| --- | --- | --- |
| H0 | memory off | 0 candidate/consume/effect |
| H1 | candidate disclosed but role/recipe不使用 | candidate/approved可非零，consumed必须0 |
| H2 | actual prompt/recipe receipt | consumed只来自receipt；effect另计 |
| H3 | incompatible/expired candidate | rejected + current recompute；consume=0 |

H0/H1/H2 用 ABBA paired order；同一 sample 若 quality不一致，不比较成本优势。

### 4.3 Prefix P

- P-A：stable/unstable/legacy render，无需模型的 token identity先行；quality 部分后跑。
- P-B：cache-friendly vs hostile；continuous服务与cold/independent epoch分层；estimate只作协变量。
- P-C：prefix off/on，公开 formal tasks，其他 flags固定。

### 4.4 Logit G

- L-A：offline calibration，不执行动作。
- L-B：valid/perturbed/refused lifecycle，验证数值consumer。
- L-C：off/telemetry/gated quality-cost。
- L-D：compatible/incompatible/expired robustness。

## 5. 指标字典

### 5.1 通信与 token

| 指标 | 定义/分母 | 采集点 | 不可比较条件 |
| --- | --- | --- | --- |
| `message_count` | 实际 serialized envelopes数 | control transport | retry策略不同未分层 |
| `control_bytes` | Protobuf control envelope serialized bytes | send boundary | 含/不含 framing不一致 |
| `inline_bytes` | inline payload bytes，不含 descriptors | envelope serializer | business info不同 |
| `state_ref_descriptor_bytes` | typed Ref descriptor serialized bytes | envelope serializer | Ref schema版本不同未说明 |
| `total_wire_bytes` | control+inline+descriptor+framing，明列公式 | UDS boundary | L0 text统计面不同 |
| `role_prompt_tokens` | tokenizer/API reported prompt tokens per role | final accepted request | tokenizer/template/retry不同 |
| `role_completion_tokens` | accepted+failed attempts分别报 | provider response | failed attempts被丢弃 |
| `prompt_visible_evidence_bytes` | role实际 request中external evidence UTF-8 bytes | rendered request audit | artifact/memory混入external定义 |
| `hydrated_evidence_bytes` | manifest resolve后进入role slice bytes | hydration receipt | prepared但未rendered时不可称visible |

历史 E1 的 L0->L1 token `+2.88%` 必须与 bytes结果同时保留；state bytes不得换算成 token saving。

### 5.2 Semantic 与 Logit state

| 指标 | 定义 | 必须维度 |
| --- | --- | --- |
| `*_publish_count/bytes` | payload+sidecar+active registry成功 | ref/kind/storage/dtype/shape/producer PID |
| `*_resolve_count` | consumer完成contract/hash/lease验证并打开 | physical component/PID、task/session |
| `*_consume_count` | 数值被算法读取并形成selection/gate receipt | logical target、input/output digest |
| `*_effect_count` | selected IDs/action改变且effect receipt完整 | downstream refs、before/after hash |
| `*_reject_count{reason}` | incompatible/corrupt/expired | fallback correctness |
| `*_release_count/bytes` | payload unlink、registry terminal | reason/timestamp/tombstone |
| `semantic_selected_ids/bytes` | selector实际返回 | top-k/budget/score/manifest hash |
| `logit_candidate_probs/other_mass` | 不在公开汇总展示raw值；artifact可hash-addressed | calibration/policy version |

publish不等于transfer；resolve不等于effect。只有 producer PID != consumer PID 才能计 cross-process consume。

### 5.3 Memory

| 阶段 | 指标 | 升级条件 |
| --- | --- | --- |
| query | `memory_query_count` | 实际查询发出 |
| candidate | `memory_candidate_count` | 检索返回 |
| compatible | `memory_compatible/degraded/rejected_count` | signature verdict |
| approved | `memory_policy_approved_count` | policy grant |
| projected | `memory_projected_to_role_count` | role input准备完成 |
| actual consumed | `memory_actual_consumed_count` | ID在RoleExecutionReceipt且input/recipe hash匹配 |
| effect | `memory_effect_count` | before/after surface、outcome、downstream refs完整 |
| assist/replay | 分 `assist/validated_replay/exact_replay` | class合同与receipt一致 |
| efficiency | `skipped_step/llm_call/tool_call` | paired counterfactual中实际少发生且quality等价 |

`reuse_gain` 必须公开公式和分母；为0时不得用 artifact reuse 数量替代。

### 5.4 Prefix

| 指标 | 定义/单位 | 有效条件 |
| --- | --- | --- |
| `prefix_eligible_count` | exact identity + full block + engine/epoch compatible requests | visibility/DAG通过 |
| `prefix_requested_count` | eligible request实际dispatch | before snapshot存在 |
| `candidate_handle_seen_count` | control registry复见 | 永不叫hit |
| `observed_query_token_delta` | vLLM counter queried tokens after-before | same names/labels/epoch、exclusive interval |
| `observed_hit_token_delta` | cached tokens after-before | `0<=hit<=query` |
| `observed_token_hit_rate` | sum(hit tokens)/sum(query tokens) | valid observations only |
| `requests_with_hit_rate` | requests hit>0 / valid observed requests | 与token hit rate分开 |
| `prefix_invalidated/unavailable_count` | 按 reason | 进入availability分母，不进入hit分母 |
| `exact_prefix_token_count/full_blocks` | common exact tokens/完整blocks | tokenizer/template frozen |
| `TTFT/request/task_latency` | 见 [`02`](02_prefix_engine_local_reuse_design.md) | streaming/clock/order/quality有效 |

### 5.5 Logit quality/cost

| 指标 | 定义 |
| --- | --- |
| ECE/MCE | fixed 10 equal-frequency bins；同时报每bin count |
| Brier/NLL | candidate probability vs independent valid-set label |
| risk-coverage/AURC | 按 calibrated risk排序后的选择性错误/覆盖 |
| gate trigger/action | 每个预注册 action count与rate |
| recovered error | off错误、gated经verified action转正确的paired样本 |
| false trigger | off已正确且gate触发无益/有害动作 |
| invalid expansion | 扩证据但selection/quality未改善 |
| extra calls/tokens/latency | gated - off paired差；失败也计入 |

### 5.6 质量与复现

- deterministic field accuracy、numeric tolerance、artifact manifest pass；
- citation/source locator coverage、provenance completeness、conflict handling；
- validator pass、failure/retry/fallback reason；
- per-role output schema valid；
- service cold/hot、engine epoch、run order、seed；
- model/tokenizer/chat template/vLLM/embedding IDs与hash；
- source/task/gold/config/runtime/container/image/calibration/policy hashes；
- git commit、dirty diff digest，不能只写 branch name。

## 6. Quality gate 与等价性

### 6.1 硬门

任何 treatment 必须：

- deterministic required fields 100% present；
- numeric答案在 task-specific Decimal tolerance；
- artifact/manifest/hash/locator/provenance checks 100% pass；
- 无 gold leakage、unauthorized evidence、stale Ref 或 silent fallback；
- 同 baseline 至少达到预注册 citation coverage。

硬门失败的 pair 不可用于“更快”claim，但失败仍进入 quality/failure rate。

### 6.2 等价/非劣

- deterministic tasks：treatment 与 baseline 的每-task pass必须相同；不采用平均分掩盖单个错误。
- narrative claims：只以 verified claim/citation coverage为主；LLM judge仅补充，预注册非劣 margin且盲评。
- latency superiority 需要 quality等价；若 treatment质量更高但更慢，单独报告 quality-cost frontier。

## 7. 顺序、重复与样本量

### 7.1 通用纪律

- API请求严格串行；不把并发启动当正式 timing。
- treatment pair按 task ID配对；ABBA/BAAB blocks由冻结seed随机选择。
- 报 median、mean、p50/p95、paired difference、95% interval和所有失败；不只报最好run。
- bootstrap以 `family -> task` 为cluster，至少10,000 resamples；小样本同时给exact/permutation interval。
- 预注册样本跑完前不看聚合方向决定停止；基础设施失败按规则标 invalid，不用结果方向决定重跑。

### 7.2 最小计划

| 实验 | 最小有效样本 | 备注 |
| --- | --- | --- |
| R1/S | 每个公开 family 全10轮 + 全扰动fixture | 机制可 deterministic重复2次检查identity |
| R2 | 2 families x 10 rounds x 4 lanes x 5 order blocks | lane内串行；paired family/task bootstrap |
| R3 | 每family每lane至少1完整10轮；正式稳定性5次 | 任一依赖失败记family failure |
| R4/H | 至少20 tasks x 5 paired blocks | actual consumed子集另报，不稀释 |
| P-A | 所有participant prompts/20 formal tasks + negative controls | token identity全量，不抽样 |
| P-B | 每schedule每warm/cold层至少10个ABBA blocks | cold动作需授权；无授权只报continuous |
| P-C | 20 formal tasks x 至少10 paired order blocks | 端到端波动较大，先pilot估方差但不改quality |
| L-A | >=200 labeled dev/calibration decisions，错误正例>=40 | 不足则exploratory，不冻结gate |
| L-B/D | 每种failure mode>=5，true/perturbed配对>=20 | lifecycle/mechanism |
| L-C | >=100 frozen holdout decisions或全部holdout（取较大） | 若正例不足只报CI/negative result |

样本数是 future preregistration 下限，不是已完成事实。pilot只能估方差/能力，不进入formal aggregation。

## 8. 冷/热服务与 Prefix 污染控制

| 层 | 定义 | 使用 |
| --- | --- | --- |
| continuous-hot | 同 engine epoch连续运行；记录先前request set | P-B实际连续服务结果 |
| independent-epoch/cold | 新 engine/cache epoch，首request前确认0或新namespace | P-B冷结果；若需重启先获授权 |
| invalid/mixed | epoch未知、其他流量、counter schema变化 | 仅diagnostic，不聚合 |

不能通过重复发送相同请求“预热到成功”后丢弃早期 miss。每个 warmup request必须在manifest中，warmup与measurement counters分开。

## 9. Artifact 与 checksum 合同

每个 formal run 使用新目录，不覆盖 E0-E6：

```text
runs/contest_rebuild_<version>/<experiment>/<timestamp_run_id>/
  preregistration.json
  environment.json
  source_checksum_ledger.json
  runtime_config.json
  request_order.json
  events.jsonl
  per_case/*.json
  failures.jsonl
  quality_report.json
  metrics_summary.json
  claim_matrix.json
  manifest.json
```

`manifest.json` hash覆盖所有文件相对路径、size、SHA-256；`preregistration.json` 包含 treatment、唯一改变项、样本量、seed、invalid/retry/stop规则、quality margin和claim gates。raw completion、secret、GPU/KV内容不进入公开artifact；必要的敏感原始对象只存受控root并以hash引用。

修改代码/数据/gold/threshold/policy后必须新版本、新run root。旧失败不能删除或混入新canonical summary。

## 10. Claim matrix

| Claim | 必要 gates | 失败时措辞 |
| --- | --- | --- |
| typed control降低wire bytes | R0+R2、quality等价 | 只说typed contract实现 |
| semantic selector减少visible context | R1+R2、selected-ID effect、quality等价 | 只说跨PID状态机制 |
| memory真实复用/少调用 | R4 actual receipt + paired nonzero skip/call | 只说store/query/compatibility；或actual consume无效率收益 |
| Prefix实际命中/TTFT变化 | R5+R6 valid counters、ABBA、cold/hot分开 | exact intent；counter unavailable/negative result |
| 端到端时间减少 | R7 quality等价、paired CI方向一致 | 不说时间优势；可留R6 mechanism |
| LogitState改善质量/风险 | R8+R9+R10、成本预算 | lifecycle/telemetry或negative result |
| 企业垂类有效 | R11 public provenance + holdout quality | repo-local/public-source pilot（按实际） |
| 多种capability自适应 | R12 natural selected counts | 只列实现的closed surface |
| openEuler本版本可交付 | R0后final container regression | 仅历史E6曾验证 |

## 11. 统计报告模板

每项 effect 同时给：

```text
n_total / n_valid / n_failed / n_invalid
baseline and treatment quality
paired absolute difference
paired relative difference（baseline非0时）
95% cluster-bootstrap CI
order/cold-hot strata
all failure reasons
mechanism observation availability
claim_gate: pass | fail | unavailable
```

不以 `p<0.05` 单独判定；同时要求预注册方向、实际效应、CI、quality和机制有效性。多个次要指标做探索性标注，不进行挑选式headline。

## 12. 停止与负结果规则

- 数据/rights/gold leakage失败：停止所有formal请求。
- R0 regression失败：停止实验，不修后继续用同run ID。
- quality hard gate失败：停止对应superiority claim；保留后续安全诊断但另建ID。
- counter unavailable：P-B不改用estimate/gauge；可继续收集TTFT但标不可归因。
- Logit calibration无预测力：不运行gated formal，保留telemetry/off。
- cold cache需服务重启但无授权：只运行continuous-hot并明确限制。
- 外部服务不稳定：保留失败；基础设施修复后新version/manifest，不覆盖。
