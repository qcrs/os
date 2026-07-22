# 03 LogitState 核心闭环实施就绪设计

> **事实来源**：`runtime/llm.py`、`v2/runtime/logit_state.py`、`role_path.py`、`smoke.py`、`v2/refs/models.py`、`v2/state/store.py`、`semantic_state.py`、现有 tests 与 [`07`](07_auxiliary_verification_record.md)。
> **设计假设**：主路径只处理 Executor 的闭集 tool/recipe alias 选择；未来服务能为该请求返回 token-level top-logprobs，但本轮未向服务发请求确认。
> **待验证实验**：L-A calibration、L-B lifecycle/counterfactual、L-C quality-cost、L-D fail-closed；对应 R8-R10，详见 [`05`](05_experiment_matrix_metrics_and_statistics.md)。

文档导航：[索引](README.md) | [00 决策与包装](00_executive_decision_and_packaging.md) | [01 现状与整改](01_current_state_and_remediation.md) | [02 Prefix](02_prefix_engine_local_reuse_design.md) | [03 LogitState](03_logitstate_core_chain_design.md) | [04 数据与任务](04_vertical_data_preprocess_and_task_design.md) | [05 实验](05_experiment_matrix_metrics_and_statistics.md) | [06 实施与验收](06_implementation_plan_and_acceptance.md) | [07 辅助核对](07_auxiliary_verification_record.md)

## 1. 目标与非目标

LogitState 是模型在一个 **冻结、可判对错的闭集决定点** 上产生的候选概率状态。它被发布为短命 little-endian float32 Ref，由独立数值 `ConfidenceGate` 读取，最多触发一次预注册动作；Runtime 执行动作并留下 effect receipt 后释放 Ref。

它不是：

- 模型自述的一句 confidence；
- 整段自由文本生成的“最高 entropy token”；
- 正确率证明、隐藏态、KV cache 或 latent；
- 默认节省 token/latency 的机制；核验可能增加成本；
- 下游 LLM 读取的文本化概率。

## 2. 主路径决定

### 2.1 选择：Executor 的 tool/recipe alias

在 Retriever 给出候选 EvidencePack/route 后，Executor 必须从 Runtime 注册的有限 capability/recipe surface 选择一个执行方案。正式 LogitState producer 改为一个专用的 `ExecutorChoiceProbe`：

```text
CandidateSurfaceV2 (2..8 candidates, frozen order)
  -> alias table: A/B/C/... -> candidate_id/route/tool/recipe digest
  -> JSON schema: {"choice_code": enum[A..H]}
  -> local_vllm response with top_logprobs
  -> locate exactly the choice alias token position
  -> map probabilities into candidate order + other_mass
```

选择理由：

- tool/recipe 有确定的 registry/capability 兼容规则和独立 validator，可定义正确/错误标签；
- 当前只有 local_vllm Executor 请求 top-logprobs，最小改动面明确；
- 不确定时可以执行 `verify_once`、`selection_retry_once` 或 evidence `expand_once`，effect 可观察；
- 候选面小，可要求每个 alias 在冻结 tokenizer/template 下为唯一单 token decision surface。

### 2.2 不选择的 producer

| 候选决定点 | 不作为本轮主线的原因 |
| --- | --- |
| Retriever semantic/table route | 自然 route 覆盖当前不足；需同时改 Retriever producer，扩大 P0 面；可作为 future extension |
| Summarizer claim token | 开放文本、同义表达和多 token claim 难以建立位置/标签；Kuhn 等人的 semantic entropy 不能直接由当前单 completion peak token替代 |
| 任意 Executor JSON peak entropy | `{`、引号、字段名和 schema token 可成为峰值；当前实现即有此风险 |
| model-generated textual confidence | 不是二进制数值 consumer，不满足非文本交接 |

### 2.3 正确标签

`choice_correct` 由 task contract + capability registry + deterministic validator 的独立 oracle 生成：

- oracle 只在 calibration/evaluation harness 可见，Runtime/role prompt 不可见；
- label 是选中 `candidate_id` 是否属于 pre-registered valid set，不比较 model prose；
- 多个候选都合法时 label set 可多值，risk 以“选中项不在 valid set”为 1；
- task/registry 无法给出独立 valid set 的样本不用于 calibration，也不允许 gated action；
- holdout gold 不参与阈值、feature 或 alias 调整。

## 3. consumer 方案比较

| 方案 | 数值 consumer | 动作 | 优点 | 风险 | 决定 |
| --- | --- | --- | --- | --- | --- |
| A Runtime `ConfidenceGate` subprocess | 直接 resolve `<f4` | accept/expand/verify/retry/fail closed | 独立 PID、易做 counterfactual、动作有界 | calibration 成本；可能过度触发 | **主方案** |
| B 独立 Verifier worker | resolve 后执行业务 verifier | verify/reject | 验证语义强 | 需要额外 verifier contract；成本高 | A 的 `verify_once` 执行者，不是 gate owner |
| C 下游 LLM 看文本 confidence | 无数值 resolve | 自行决定 | 实现简单 | 不构成数值状态消费；不可审计 | 拒绝 |

主方案将 **数值判门** 与 **验证动作** 分离：ConfidenceGate 只输出动作，Runtime/Verifier 执行动作。它不成为第五个 Agent。

## 4. decision token 的可审计定位

当前字符串前缀匹配必须删除。未来 producer 遵循：

1. Candidate surface 排序后分配不含业务语义的 ASCII alias（`A`..`H`）。
2. Preflight 用冻结 tokenizer + chat template 验证每个 `"choice_code":"X"` 上的 X 在相同上下文中恰为一个 token；记录 token ID，但不写入公开 telemetry 原始 token text。
3. response schema 只允许该 enum；producer 用 response logprob entries 的 `bytes` 累计 offset 找到 parsed JSON alias value span。
4. 必须且只能有一个 token span与 alias value重合；peak entropy 不参与位置选择。
5. top-logprobs alternatives 通过 **精确 token ID/bytes mapping** 映射 alias；括号、引号、字段名和 whitespace 一律排除。
6. 每个候选 alias 必须出现在 top-k alternatives；缺失、重复、multi-token、bytes不可用或 response alias 与所选 token不一致时 `unavailable`。
7. retry completion 各自产生 request ID；不得把多次 completion 的 logprobs 合并后发布一个 Ref。

若服务响应不提供 token IDs，只接受 preflight 冻结的 `(token_bytes -> alias)` 一一映射；存在歧义即 fail closed。不得为得到预期 entropy 改 alias 后继续使用同一 calibration version。

## 5. 数值 payload 合同

### 5.1 payload layout

```text
dtype: little-endian float32 (<f4)
shape: [candidate_count + 1]
row/order: probabilities in CandidateSurfaceV2 canonical order,
           final element = other_mass
probability source: exp(raw logprob) at the unique choice position
normalization: do not renormalize top-k candidates to 1;
               other_mass = clamp(1 - sum(mapped candidate probs), 0, 1)
sum tolerance: abs(sum(payload) - 1) <= 1e-5
candidate_count: 2..8
payload max: 36 bytes at 8 candidates; metadata/event budget separate
```

如果 API 的 logprob 语义或 truncation 无法构造可信 `other_mass`，contract version 改为 `conditional_topk_v1` 并在 calibration/metrics 中明确“top-k 条件分布”；不能默默把它称为完整概率。正式默认要求完整候选都在 top-k 且保留 tail mass。

### 5.2 `LogitStateRefV2`

| 字段 | 类型 | 验证规则 |
| --- | --- | --- |
| `schema_version` | string | 精确 `statebus.logit_state.v2` |
| `state_id/ref_id` | UUID/string | registry 唯一、active |
| `task_id/session_id/trace_id/step_id/request_id/attempt_id` | string | consumer context 全等；缺失 reject |
| `producer_role/producer_component/producer_pid` | enum/string/u32 | role=executor；PID>0 |
| `logical_target/consumer_component/expected_consumer_pid` | string | target=executor choice；consumer=confidence_gate；PID grant 可匹配 |
| `decision_type` | enum | `executor_tool_recipe_choice_v1` |
| `candidate_surface_digest/candidate_count/alias_mapping_digest` | string/u32/string | 与 gate registry snapshot 全等 |
| `decision_token_position/sequence_length/top_k` | u32 | position<length；top_k>=candidate_count |
| `prompt_sha256/source_evidence_digest/hydration_digest` | string | 与 request/evidence receipts 全等 |
| `model_id/model_revision/tokenizer_id/tokenizer_revision` | string | 冻结 identity 全等 |
| `chat_template_sha256/template_kwargs_sha256/response_schema_digest` | string | producer/consumer policy 全等 |
| `dtype/byte_order/shape/probability_semantics` | enum/list/string | `<f4`、little、`[N+1]`、支持版本 |
| `blob_hash/size_bytes/storage_kind` | string/u32/enum | sidecar/payload 全等；formal shared_memory or mmap |
| `owner_session_id/lease_created_at_ns/lease_expires_at_ns` | string/u64 | 未过期；owner context 全等 |
| `calibration_version/threshold_policy_version/gate_budget_version` | string | frozen, hash-addressed；缺失只可 telemetry-only |
| `sensitivity_class` | enum | 默认 `derived_probability_state`；不记录 raw completion |
| `release_reason/released_at_ns` | event fields | release 后 registry 不再 active |

默认不保存 token strings、完整 completion 或 top-k raw alternatives。`CandidateSurfaceV2` sidecar只保存 candidate IDs/digests、alias ordinal和 position mapping digest；业务描述留在原 authorized artifact。

### 5.3 producer validate rules

- response/request/attempt identity 一致；只处理最后被 Runtime 接受的单次选择，但失败 attempts 各留 unavailable event；
- unique alias decision position；候选 mapping 完整且 digest 匹配；
- probabilities finite、非负、sum/tail tolerance 合格；selected alias probability 可定位；
- model/tokenizer/template/schema/candidate surface 与 calibration version 兼容；
- payload/blob hash/sidecar 写入成功后才注册 active Ref；
- publish 失败不计 transfer/gate，普通路径继续。

### 5.4 consumer validate rules

- grant、task/session/request/ref、owner、lease、registry status 全匹配；
- shared-memory/mmap handle 位于允许的 state root；不接受 inline/raw path；
- size/hash/dtype/shape/order/probability semantics 验证后只读 resolve；
- candidate/policy/calibration/model/template digest 全匹配；
- producer PID != consumer PID；否则 L-B 不算跨进程；
- duplicate action token 已存在则幂等返回原 decision，不再执行动作；
- 任一失败写 `LOGIT_STATE_REJECTED(reason)`，走 baseline validator，绝不伪报 consumed。

## 6. 生命周期、进程边界和清理

```text
Executor choice completion (LLM service PID V -> Runtime PID C)
  -> ChoiceLogprobExtractor PID C
       locate alias position, validate, build <f4 payload
  -> LogitStateStore PID C
       publish shared_memory, sidecar, active registry, lease
       LOGIT_STATE_PUBLISHED (publish != transfer)
  -> SubprocessExecutorTransport / ConfidenceGate PID G
       resolve by ref + grant; validate hash/contract/lease
       numeric features + frozen calibration policy
       LOGIT_STATE_RESOLVED / CONSUMED
  -> GateDecisionRef/typed result back to Controller PID C
       accept | expand_once | verify_once | selection_retry_once | fail_closed
  -> Runtime PID C executes at most one action
       ActionEffectReceipt(before/after/quality/cost/downstream refs)
  -> Controller release/unlink + registry transition
       LOGIT_STATE_RELEASED(reason=consumed|rejected|expired|cancelled)
```

owner 与 PID：

| 步骤 | owner | PID/边界 | 幂等与异常 |
| --- | --- | --- | --- |
| completion/extract | RolePath producer adapter | Controller PID | request ID 幂等；解析异常 unavailable |
| publish/register | Controller/StateStore | Controller PID -> shared memory | sidecar/handle 原子提交；失败回滚 unlink |
| resolve/gate | `ConfidenceGateWorker` | 独立 subprocess PID | grant hash + action token 防重复 |
| action | Runtime Controller/Verifier | Controller/worker | `max_gate_actions=1`；重试不递归触发 gate |
| effect receipt | Runtime Controller | Controller | before/after digest、downstream ref、cost齐全 |
| release/expiry | lifecycle supervisor | Controller | `finally` release；worker crash由 TTL reaper |

异常清理：consumer crash、timeout、controller cancel、action failure 都进入 `finally` release；sidecar保留最小 tombstone（无 raw概率）用于审计，payload必须 unlink。当前 generic store release 后 sidecar仍存在，未来 Logit store需显式把 active sidecar转 tombstone，而不是留 active metadata。

## 7. ConfidenceGate 与动作合同

### 7.1 输入 features

只使用 calibration 冻结的数值/结构特征：

- calibrated selected-candidate probability；
- candidate entropy（含 other mass）及 normalized entropy；
- top-1/top-2 margin；
- other mass；
- candidate count、decision type；
- 可选的 deterministic compatibility flags（不含 gold）。

当前 serializer 的 sequence peak entropy、aggregated entropy、varentropy 可作为 dev diagnostic，但不自动进入 v1 gate。任何新 feature 都要新 calibration/policy version。

### 7.2 输出动作

| 动作 | 精确定义 | Runtime effect | 循环防护 |
| --- | --- | --- | --- |
| `accept` | calibrated risk <= frozen accept threshold | 继续选中 tool/recipe + 标准 validator | 不额外调用 |
| `expand_once` | 证据充分性低且 budget允许 | Retriever top-k/byte budget扩大一次，再做普通 selection | expanded request `gate_depth=1`，不再产生 gate action |
| `verify_once` | 选择可执行但风险处于 verify band | 独立 deterministic verifier 或 registered verifier worker一次 | verifier结果终结；失败走 baseline reject/recompute |
| `selection_retry_once` | alias margin低且候选面可重排/补证据 | 以相同 candidate IDs、明确 failure context 重选一次 | retry request不再 gated；只走 validator |
| `fail_closed` | ref/contract/calibration不可用，或风险超过资源允许且无安全动作 | 不依据 LogitState改业务结论；回到普通选择+标准 validator，必要时 task-level拒绝 | 不算 gate success/transfer |

`fail_closed` 的含义是“LogitState 失效时不放宽基线安全规则”，不是无条件把整个任务判失败。业务 validator 本来应拒绝的结果仍拒绝。

### 7.3 ActionEffectReceipt

必须包含：`decision_id/action_token/ref_id/task/step`、consumer PID、policy versions、`before_decision_surface_hash`、action、`after_decision_surface_hash`、downstream artifact/validator refs、是否改变 selection、是否恢复错误、extra LLM/tool calls/tokens/latency/evidence bytes、outcome/fallback/release reason。只有 receipt 完整才能计 `actual_consumed` 和 `effect`。

## 8. Calibration 方案

### 8.1 数据隔离

```text
public-source dev tasks
  -> feature engineering / alias feasibility / model choice
calibration split (issuer- and task-instance-disjoint)
  -> fit temperature or monotone mapping, choose thresholds
  -> freeze calibration + policy + feature hashes
frozen test/holdout
  -> once-per-version evaluation; never tune thresholds
```

Logit calibration split与 P-C/R11 holdout独立。失败样本、missing logprobs 和所有 fallback 计入覆盖分母，不得只保留成功返回。

### 8.2 标签、基线和指标

- binary error label：selected candidate不在 independent valid set；
- multiclass Brier：candidate probabilities对 valid target distribution；多合法候选按预注册规则分配 target mass；
- calibration：reliability diagram、ECE（固定 10 等频 bins，同时报告 bin counts）、maximum calibration error；
- proper score：Brier score、negative log likelihood；
- discrimination：AUROC/AUPRC 仅作补充，不能替代 calibration；
- selective behavior：risk-coverage curve、AURC、在预注册 coverage 点的 error risk；
- action utility：verified errors recovered - false triggers - budget-weighted extra cost。

理论依据：

- Guo et al., [On Calibration of Modern Neural Networks](https://arxiv.org/abs/1706.04599)：现代网络概率可能失准，temperature scaling 是需验证的简单后处理，不是自动保证。
- Geifman & El-Yaniv, [Selective Classification for Deep Neural Networks](https://arxiv.org/abs/1705.08500)：拒绝/覆盖与风险必须共同报告。
- Brier, [Verification of Forecasts Expressed in Terms of Probability](https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2)：Brier score 作为概率预测 proper score。
- Kuhn et al., [Semantic Uncertainty](https://arxiv.org/abs/2302.09664)：开放文本存在同义语义等价问题；这正是本轮选择闭集 alias 而不使用任意 JSON peak entropy 的原因。该论文不证明本系统 token entropy 有效。

### 8.3 阈值选择与退出

在 calibration split 上，按以下顺序冻结：

1. 先选校准器（未校准、temperature、isotonic 中通过 nested dev 的最简单者）；
2. 定义资源预算：每 task 最多一次动作、最多 1 次额外 LLM 或 verifier call、额外 evidence不超过 baseline budget的 100%；
3. 选 accept/verify/retry bands，使预注册 coverage 下 risk下降且 false-trigger/成本不超预算；
4. hash feature list、calibrator parameters、thresholds、training IDs 和代码版本；
5. holdout只评估。

停止/降级：

- alias/token位置在 >1% eligible samples不可唯一定位 -> 不进入 gate；
- calibration不优于 constant/base rate（Brier/NLL bootstrap interval）或 risk-coverage无稳定改善 -> telemetry-only/off；
- threshold只能靠 holdout才能成立 -> 版本作废，新版本重新开发，旧结果保留；
- L-C 无净 verified quality value或超资源预算 -> 不进入 headline。

## 9. 当前基线与迁移差距

| 当前实现 | 当前事实 | v2 目标 |
| --- | --- | --- |
| `runtime/llm.py` local Executor top-20 | request字段存在；服务能力未探针 | dedicated choice request + capability receipt |
| `serialize_logit_state_v2()` | 全序列 peak、top-k renormalize、字符串前缀候选 entropy | unique alias position、candidate-order probs + other mass |
| `role_path` 捕获异常后 `pass` | unavailable原因丢失 | structured producer failure event |
| `ExecutorRoleDecision` scalar fields | telemetry projection | active Ref ID + producer receipt；scalars只作 derived diagnostic |
| `LogitStateRef` v1 | 字段少，默认 consumer_role | v2 binding/lease/PID/policy完整 contract |
| `LayeredStoragePolicy` auto优先 memfd | fixed fixture generic publish可用 | formal profile shared_memory -> mmap fallback |
| `smoke` bytes>0计 transfer | 未跨进程 | publish/resolve/consume/release分计数 |
| hardcoded confidence `<0.3` | 未 calibration、无 action | 删除/legacy metric；frozen policy only |
| consumer/action/effect | 不存在 | ConfidenceGate subprocess + bounded action receipt |

## 10. 文件级改动表

以下是未来计划，本轮未实施。

| 文件/符号 | 变更 | 输入 -> 输出/调用顺序 | 迁移责任 |
| --- | --- | --- | --- |
| `v2/contracts/logit.py`（新增） | `CandidateSurfaceV2`、`LogitStateContractV2`、GateDecision、EffectReceipt | role path/controller/gate共用 | schema/hash validation |
| `v2/contracts/__init__.py` | 导出新合同 | callers | 无行为变化 |
| `v2/refs/models.py::LogitStateRef` | 扩展 v2 fields或新增 `LogitStateRefV2` | store -> registry/grant | v1只读兼容；v1不得 gated |
| `v2/control/statebus_v2.proto`、`schema.py`、`messages.py` | typed logit ref/grant/gate result event | Controller <-> worker | 禁止 raw completion/token strings |
| `runtime/llm.py::OpenAICompatibleLLMClient.complete` | 每attempt logprob capability/bytes receipt；不合并 | API -> LLMResultV2 | provider不支持则 unavailable |
| `v2/runtime/role_path.py::validate_execution_choice` | 拆 dedicated alias choice；返回 producer request receipt | candidate surface -> accepted choice + raw logprob envelope | legacy JSON path可 baseline fallback |
| `v2/runtime/logit_state.py` | 替换 peak extractor为 exact alias extractor；旧函数 deprecated diagnostic | logprob envelope + mapping -> candidate payload | 保留旧 tests但不用于 gate |
| `v2/state/logit_state.py`（新增） | 参考 `semantic_state.py` 实现 contract、publish/resolve/tombstone/release/TTL | payload/ref/state root | shared_memory first；hash/lease校验 |
| `v2/state/store.py::LayeredStoragePolicy` | contest profile `LOGIT_STATE=(SHARED_MEMORY,MMAP_FILE)` | config -> decision | generic auto行为变更需测试 |
| `v2/runtime/confidence_gate.py`（新增） | numeric feature、calibrator、bounded policy | resolved ref -> GateDecision | 无 calibration时 telemetry-only/fail closed |
| `v2/control/worker_operations.py`、`subprocess_worker.py` | `logit_gate_v1` operation | grant -> independent PID result | timeout/crash cleanup |
| `v2/runtime/smoke.py` | publish/grant/action/effect/release；删除伪 transfer/0.3 gate | executor decision -> runtime effect | flags默认off；metrics migration |
| `v2/runtime/adaptive_dispatcher.py` | 在闭集 Executor dispatcher接同一 receipt（第二阶段） | adaptive path | 不先扩大到所有 roles |
| `v2/benchmark/logit_calibration.py`（新增） | L-A offline fit/eval + frozen artifact | dev/calibration examples | holdout不可写参数 |
| `v2/benchmark/logit_state_experiment.py`（新增） | L-B/C/D runner | frozen policies/tasks | 新 run root，失败保留 |
| `tests/v2/test_logit_state.py` | exact position/tail/mapping/legacy tests | static fixtures | 不发模型请求 |
| `tests/v2/test_logit_state_lifecycle.py`（新增） | shared-memory cross-PID resolve/hash/lease/release/tombstone | temp roots | assert producer PID != consumer PID |
| `tests/v2/test_confidence_gate.py`（新增） | actions/budget/idempotency/calibration missing | fixtures | no model |
| `tests/v2/test_logit_state_fail_closed.py`（新增） | 全失败矩阵 | fixtures | baseline outcome unchanged |
| `tests/v2/test_logit_live_capability.py`（新增 opt-in） | 单固定 request top_logprobs shape | local service | 用户授权；只写 capability |

## 11. 可观测性与计数定义

| event/metric | 何时计 1 | 不代表什么 |
| --- | --- | --- |
| `logit_state_extraction_available` | unique position + complete mapping | 尚未 publish |
| `logit_state_publish_count` | payload+sidecar+active registry成功 | transfer/consume |
| `logit_state_resolve_count` | 独立 worker hash/contract验证并打开 | action/effect |
| `logit_state_consume_count` | worker读取数值并生成 GateDecision | quality改善 |
| `logit_state_reject_count{reason}` | validate失败 | task失败（可 baseline fallback） |
| `logit_gate_action_count{action}` | Controller接受唯一动作token | action成功 |
| `logit_gate_effect_count` | EffectReceipt完整且 decision surface/action outcome已记录 | 净质量价值 |
| `logit_state_release_count{reason}` | payload unlink + registry terminal | sidecar一定删除（保留 tombstone） |
| `logit_state_bytes` | 实际 payload bytes | token saving |
| `extra_llm/tool_calls/tokens/latency` | 相对 gate-off paired差 | 不可跨不等质量样本聚合 |
| `false_trigger/recovered_error` | 基于独立 gold/validator | holdout前不可用于调阈值 |

mechanism receipt 是 publish/resolve/consume/release；只有 L-C frozen paired结果才能形成 quality/cost claim。

## 12. 测试、扰动与失败行为

| 扰动 | 预期行为 |
| --- | --- |
| 无 `top_logprobs`/endpoint拒绝 | `unavailable_top_logprobs`，baseline validator，0 publish/consume |
| decision position是多 token/无法定位 | extraction rejected；不回退 peak entropy |
| 候选 alias 缺失/重复/top-k不全 | mapping rejected |
| NaN/negative/sum或tail错误 | payload rejected |
| 截断 bytes、错误 dtype/shape/byte order/hash | consumer reject；release；baseline |
| expired lease、跨 task/session/request ref | consumer reject；无 action |
| model/tokenizer/template/schema/policy不兼容 | consumer reject；新 calibration required |
| producer/consumer PID相同 | L-B fail；不计 cross-process transfer |
| consumer crash/timeout | supervisor release；baseline；reason完整 |
| calibration/threshold文件缺失或hash错 | telemetry-only/fail closed，不用默认0.3 |
| duplicate GateDecision/action token | 幂等返回，不执行第二次 |
| action failure | effect receipt=failure；标准 validator/recompute；不递归 gate |
| incompatible/expired ref injected | L-D 应证明无 selection/artifact污染 |

## 13. L-A/L-B/L-C/L-D preregistration

### L-A 离线 calibration

- 唯一改变：候选 risk feature/calibrator/policy；不执行 gate action。
- 记录：labels、missingness、reliability/ECE/Brier/NLL、risk-coverage/AURC、bootstrap CI、threshold来源和freeze hash。
- 通过：位置/数据覆盖充分；calibration相对 base rate有价值；threshold不触 holdout。

### L-B 生命周期机制

- 对照：valid true ref、概率排列 perturbation、hash/dtype/lease/task refusal controls。
- 记录：producer/consumer PID、bytes、candidate digest、GateDecision、是否改变所选 action、release/tombstone。
- 通过：独立 PID真实读取数值；true/perturbed至少产生预注册可区分 decision；refusal无污染。

### L-C 受控质量收益

- lanes：`off`、`telemetry_only`、`calibrated_gate`；相同 tasks/model/order，prefix/memory固定off或相同。
- 记录：verified quality、error recovery、false trigger、无效扩展、额外 calls/tokens/latency/evidence、失败/fallback。
- 通过：不预设必须改善；只有 frozen holdout净质量价值和成本预算均满足才进 headline。

### L-D 端到端鲁棒性

- 唯一改变：compatible vs expired/wrong task/wrong model/corrupt ref。
- 记录：reject reason、fallback correctness、artifact/policy hashes、payload cleanup。
- 通过：所有 incompatible cases fail closed，quality不低于普通基线且无 stale action。

## 14. 配置、回滚、资源与验收

| 配置 | 默认/迁移 |
| --- | --- |
| `STATEBUS_LOGIT_POLICY` | `off` 默认；实现后先 `telemetry_only`；L-A-C通过才允许 `gated` |
| `STATEBUS_LOGIT_DECISION_TYPE` | `executor_tool_recipe_choice_v1` only |
| `STATEBUS_LOGIT_CALIBRATION_ARTIFACT` | hash-addressed；缺失不能 gated |
| `STATEBUS_LOGIT_THRESHOLD_POLICY` | hash-addressed；禁止环境内裸 `0.3` |
| `STATEBUS_LOGIT_MAX_ACTIONS` | 1，formal不可提高 |
| `STATEBUS_LOGIT_LEASE_MS` | 30,000 默认，按测试冻结 |
| `STATEBUS_LOGIT_STATE_POOL_MODE` | shared_memory，mmap fallback |
| `STATEBUS_LATENT_MODE` | formal固定off，与 Logit policy无联动 |

最小实施顺序：exact alias extractor -> v2 contract/store -> cross-PID gate -> bounded action receipt -> calibration harness -> L-A -> frozen thresholds -> L-B/D -> L-C。每一步先完成无模型 unit/contract；服务 capability probe需用户授权。

回滚：`STATEBUS_LOGIT_POLICY=off` 恢复现有 baseline choice+validator；不得删除失败 artifacts。若无预测力，删除 gated packaging 而非改阈值迎合 holdout。

最终可交付层次：

- 只有 contract/lifecycle：可说“实现短命概率 Ref 和独立数值消费”，不能说质量改善。
- L-A无预测力：保留负结果并关闭 gate。
- L-A/B/D通过、L-C无净收益：可说受控机制与 fail-closed，不进质量 headline。
- L-C通过：只在该 frozen decision/task/model 上报告 verified quality-cost effect，不泛化到任意生成正确率。
