# 02 Engine-Local Prefix Reuse 实施就绪设计

> **事实来源**：`v2/runtime/neural_state.py`、`role_path.py`、`vllm_metrics.py`、`prefix_feedback.py`、`v2/benchmark/kv_prefix_schedule.py`、`continuous_runner.py`、现有 tests 与 [`07`](07_auxiliary_verification_record.md)；vLLM 官方 APC/metrics 文档。
> **设计假设**：未来 formal engine 开启 vLLM APC；StateBus 只能安排 exact token prefix 和记录观测，不能访问/导出/迁移引擎私有 KV blocks。
> **待验证实验**：P-A 渲染完整性、P-B 引擎机制、P-C 端到端；对应 R5-R7，preregistration 见 [`05`](05_experiment_matrix_metrics_and_statistics.md)。

文档导航：[索引](README.md) | [00 决策与包装](00_executive_decision_and_packaging.md) | [01 现状与整改](01_current_state_and_remediation.md) | [02 Prefix](02_prefix_engine_local_reuse_design.md) | [03 LogitState](03_logitstate_core_chain_design.md) | [04 数据与任务](04_vertical_data_preprocess_and_task_design.md) | [05 实验](05_experiment_matrix_metrics_and_statistics.md) | [06 实施与验收](06_implementation_plan_and_acceptance.md) | [07 辅助核对](07_auxiliary_verification_record.md)

## 1. 理论边界与正式名称

正式名称为 **Engine-Local Prefix Reuse**。StateBus 生成相同的 token 前缀、声明兼容性和安排依赖安全顺序；同一 vLLM 实例根据自己的 APC block hash、容量与 LRU 状态决定实际命中。不存在 Agent 间 KV tensor 导出、网络传输、恢复或显存句柄。

vLLM 官方说明：APC 只有在新请求与既有请求共享相同前缀时复用 KV，且只减少 prefill，不减少 decode；只缓存完整 blocks。其 block identity 包含 parent hash、exact block tokens 和 adapter/multimodal/cache-salt 等 extra hashes。参考：

- [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/)
- [vLLM Prefix Caching Design](https://docs.vllm.ai/en/latest/design/prefix_caching/)
- [vLLM Production Metrics](https://docs.vllm.ai/en/stable/usage/metrics/)

因此以下蕴含关系不成立：

```text
same EvidencePack metadata hash != same rendered text
same rendered text             != same chat-template token IDs（模板/kwargs 可变）
same token IDs                 != resident full KV blocks（epoch/eviction 可变）
registry handle seen           != engine hit
engine cached-token hit        != end-to-end latency improvement
```

## 2. 候选方案与决定

| 方案 | 做法 | 优点 | 缺点/风险 | 决定 |
| --- | --- | --- | --- | --- |
| A 当前元数据 hash + role `combined_text()` | 沿用 `evidence_prefix_hash`、bytes/4 estimate | 改动小 | 角色 slice 不同；不绑定 tokenizer；registry hit 误名 | 拒绝作为 formal |
| B canonical authorized common prefix + role suffix | 从 selected EvidencePack 的角色可见交集稳定渲染，模板后 exact tokenize | 可审计；保持最小权限；与 APC exact token 条件一致 | 需改 layout/accounting/scheduler | **主方案** |
| C 手工导出/装载 KV 或跨 engine connector | StateBus 管 KV bytes | 可能跨实例 | 违反本轮边界，安全/兼容复杂，等同 KV handoff | 永久禁止 |
| D 每角色独立 prefix，仅做同角色跨任务复用 | 相同 role/task family 聚类 | 权限最简单 | 不能证明跨角色公共前缀；机会较少 | P-B 补充对照，不替代 B |

主方案 B 的最小参与角色为 Executor 和 Summarizer。Planner 没有 corpus evidence；Retriever 负责选择，不为制造命中而扩大可见面。若授权交集为空或少于一个完整 APC block，事件为 `ineligible`，请求按普通布局执行。

## 3. 当前基线逐项审计

| 部件/调用点 | 真实输入 -> 输出 | 主路径状态 | 问题/错误命名 | 保留或替换 |
| --- | --- | --- | --- | --- |
| `build_corpus_prefix_hash()` | sorted source doc hashes -> corpus hash | schedule 使用 | corpus affinity，不是 token identity | 保留并改名/文档化为 affinity hash |
| `build_evidence_prefix_hash()` | corpus/evidence-pack/hydrate-manifest/version -> hash | telemetry/estimate | 不含 final text、template/token IDs | 降为 lineage hash；新增 token identity |
| `NeuralPrefixIdentity` | 两级 metadata hash | audit summary | 名称易暗示 engine identity | 迁移为 `PrefixLineageIdentity` |
| `EngineLocalPrefixRegistry` | engine/session/prefix/model/tokenizer -> handle | 主要合同/测试；非 engine cache | `cache_hit=True` 仅 handle 复见；缺 epoch/template/config | v2 schema；字段改 `candidate_handle_seen` |
| `estimate_engine_local_prefix_reuse()` | selected bytes、roles、bytes/token -> estimate | smoke metrics | 假设 roles-1 均 hit；忽略 block/eviction | 仅 planning estimate；与 observed namespace 隔离 |
| `compile_prefix_layout()` | 调用者 shared text + role suffix -> prompt/layout hashes | flag 开启时被 role path 使用 | helper 不保证跨 role 同 text；只有 text hash/bytes | 保留 renderer，输入改 typed canonical prefix |
| `_build_role_hydrated_slices()` | EvidencePack -> role-specific slices | 主路径 | Executor table 与 Summarizer semantic+table 常不相同 | 新增 visibility intersection；额外项仍为 suffix |
| `_neural_prefix_consumer_roles()` | 有 external bytes 的 executor/summarizer -> roles | estimate | 不检查相同 prefix/token IDs | 改由 eligible intent 决定 participants |
| `order_prefix_schedule_hints()` | affinity hints -> global sort/interleave | probe 工具 | 不接受 DAG ready set | 仅用于 plan visualization；runtime 用 ready-set API |
| `build_kv_prefix_schedule_plan()` | manifest explicit order -> plan | `kv_prefix_reuse_v1` | 当前三种 plan 静态安全，但没有通用证明接口 | 保留 fixture；加 dependency validator |
| `parse/compute_vllm_prefix_cache_*()` | Prometheus text/snapshots -> delta | smoke/feedback | 当前 endpoint 未核对；单位未显式记录；labels 聚合 | 扩展 schema/labels/unit，严格 invalidation |
| `run_smoke()` snapshot | 整 task 前/后 -> aggregate delta | local_vllm path | 覆盖所有角色请求；可能有其他流量 | 只作 legacy task-window；formal 改 request-window |
| `PrefixCacheFeedbackLoop` | predicted + valid delta -> reorder signal | probe family | 输入若非同粒度会误导 | 只接受 typed `PrefixObservation` |
| continuous runner adaptive reorder | pending list -> friendly order | probe family input schedule | 不是显式 ready-set；整 task observation | 替换为 dependency-aware scheduler |

本轮 fixture 事实：同一 shared text 经本地 Qwen3-32B chat template 产生相同 44-token common window；模拟当前不同 role slice 时 shared hash 不同、full-message LCP 仅 11 tokens。它证明 renderer 有可用骨架，也证明主路径尚未满足 formal identity。它不证明 vLLM hit。

## 4. Canonical shared prefix

### 4.1 输入集合

`CanonicalSharedEvidencePrefix` 从 **semantic selector 已选中的 EvidencePack** 构建：

1. Controller 取得每个拟参与角色的 authorized stable keys。
2. `common_keys = intersection(executor_keys, summarizer_keys)`；不得为了 cache 扩大权限。
3. 按下列 tuple 排序，不使用模型 rank 或 Python 容器迭代顺序：

```text
(source_doc_hash, locator_kind, canonical_locator_fields, evidence_kind, stable_key)
```

4. 每个 entry 以 versioned canonical JSON/文本渲染；数字、日期、单位和换行遵循固定 normalizer。
5. prefix header 只含公开合同字段，不含 role、task question、output schema、memory hint 或 gold。
6. entry 集为空、存在 conflict 未解决、locator/hash 缺失或 visibility digest 不一致时 fail closed 为 ineligible。

### 4.2 精确文本布局

保持当前单个 `user` message 形状以缩小改动；不同角色的 message count、chat template kwargs 与 generation prompt 必须相同。角色专属 system message 不能出现在公共 evidence 之前。

```text
<statebus-shared-prefix-v2>
prefix_layout_version=statebus.shared_evidence_prefix.v2
evidence_entry_count=N
evidence:
<canonical entry 1>
...
</statebus-shared-prefix-v2>

<statebus-role-suffix-v2 role="executor|summarizer">
role instruction
task/request-specific objective
role-only evidence (authorized common set 之外)
memory/artifact hints
response JSON schema description
</statebus-role-suffix-v2>
```

比较窗口不是字符 LCP，而是 chat template 渲染完成后，从 token 0 到 closing prefix delimiter 后最后一个 **不跨边界** token。窗口必须：

- 在所有 participant 中 token IDs 完全相同；
- 从绝对 position 0 开始；
- 至少覆盖 `min_prefix_tokens` 且记录 `full_block_token_count=floor(N/block_size)*block_size`；
- closing delimiter 后留固定 separator，防止 BPE token 跨 role 边界；
- 记录 full request token IDs hash 以检查 suffix 只发生预期变化。

角色专属 evidence 放在 suffix；因此公共前缀相同不要求整个 prompt 相同，也不改变每个角色原有 authorized information。P-A 必须验证旧布局与新布局的 role output/validator 等价。

## 5. 精确兼容合同

### 5.1 `PrefixReuseIntentV2`

| 字段 | 类型 | 来源/含义 | 变化时行为 |
| --- | --- | --- | --- |
| `schema_version` | string | `statebus.prefix_reuse_intent.v2` | 非支持版本 reject |
| `intent_id/trace_id/task_id/step_id/request_id` | string | 审计 identity | 仅 trace 字段不参与 token hash；缺失 reject |
| `participant_role` | enum | executor/summarizer | role 不参与 common token hash，但决定 suffix/权限 |
| `engine_instance_id` | string | 启动实例 UUID，不是 hostname | 不同 -> ineligible |
| `cache_namespace/cache_epoch` | string/u64 | trust group + restart/reset epoch | 不同 -> ineligible |
| `model_id/model_revision/weights_digest` | string | 实际权重 identity | 不同 -> ineligible |
| `tokenizer_id/tokenizer_revision` | string | tokenizer files digest | 不同 -> ineligible |
| `chat_template_sha256/template_kwargs_sha256` | string | template + `enable_thinking` 等 | 不同 -> ineligible |
| `prefix_layout_version/normalizer_version` | string | canonical renderer identity | 不同 -> ineligible |
| `source_doc_hashes/evidence_pack_hash/hydrate_manifest_hash` | repeated/string | lineage | 变化 -> 新 intent；不能代替 token hash |
| `authorized_common_keys_digest/visibility_policy_version` | string | 最小权限证明 | 不同 -> ineligible |
| `shared_prefix_text_sha256/prefix_bytes` | string/u64 | canonical text | 不同 -> ineligible |
| `exact_token_ids_sha256/exact_token_count` | string/u64 | 核心 identity | 不同 -> ineligible |
| `full_block_token_count/block_size` | u64 | vLLM only caches full blocks | 0 -> ineligible |
| `position_base/message_shape_digest` | u64/string | 必须从 token 0 开始、同 template envelope | 不同 -> ineligible |
| `adapter_digest/multimodal_digest/cache_salt_digest` | string | vLLM extra hash inputs | 不同 -> ineligible；不用时固定 `none` |
| `rope_config_digest/kv_cache_dtype/quantization_digest` | string | engine/model execution compatibility | 不同 -> ineligible |
| `tensor_parallel_size/pipeline_parallel_size` | u32 | engine namespace审计 | engine-local 内固定；变化意味着新 epoch |
| `eligible_reason/ineligible_reason` | enum/string | policy decision | 只有 eligible 可 requested |
| `dependency_ids/ready_set_epoch/schedule_priority` | repeated/u64/double | DAG safety | 非 ready 不得入队 |
| `lease_expires_at_ns` | u64 | intent 控制面 lease | 过期 invalidated |

温度、max tokens 等不决定 prefix KV compatibility，但必须进入 experiment request/config digest，用于质量/成本公平性；不混入 exact prefix hash。

### 5.2 状态与事件

```text
CREATED
  -> INELIGIBLE(reason) [terminal, baseline request]
  -> ELIGIBLE
       -> QUEUED(ready-set proof)
       -> REQUESTED(before snapshot + request timestamp)
            -> OBSERVED_HIT(valid query/hit token delta)
            -> OBSERVED_MISS(valid query delta, zero hit)
            -> OBSERVATION_UNAVAILABLE(reason)
            -> INVALIDATED(reason: epoch/template/counter/pollution/restart)
       -> EXPIRED
```

事件合同：

| 事件 | 必须字段 | 禁止解释 |
| --- | --- | --- |
| `PREFIX_ELIGIBILITY_DECIDED` | identity digests、token count、reason | eligible 不是 hit |
| `PREFIX_CANDIDATE_HANDLE_SEEN` | registry key、first/seen timestamps | 不叫 cache hit |
| `PREFIX_REQUESTED` | request ID、engine/epoch、before snapshot、TTFT clock start | requested 不保证引擎查询 |
| `PREFIX_OBSERVED` | before/after names+labels、`observed_query_token_delta`、`observed_hit_token_delta`、`observed_token_hit_rate`、validity、TTFT/latency | lifetime gauge 不得转 observed hit |
| `PREFIX_INVALIDATED` | reason、snapshot hashes、fallback | invalidated 样本不进入 hit-rate 分母 |
| `PREFIX_EXPIRED` | lease/epoch | 不推断 eviction 时刻 |

`observed_token_hit_rate = sum(observed_hit_token_delta) / sum(observed_query_token_delta)`；另报 request-level `requests_with_nonzero_hit / valid_observed_requests`，两者不可混名。旧的无单位 `observed_hit_rate` 不写入 v2 event。

## 6. 跨进程时序与 owner

```text
semantic selector (PID S)
  -> selected IDs + HydrateManifest receipt

Controller (PID C)
  -> compute role visibility intersection
  -> PrefixRenderer.render() -> canonical text
  -> TokenIdentityCompiler(chat template/tokenizer) -> exact token IDs/hash
  -> PrefixEligibilityPolicy -> intent
  -> Ref/Event registry (control-plane only)

DependencyAwarePrefixScheduler (PID C)
  -> choose only from DAG ready set within same engine/epoch namespace
  -> PREFIX_REQUESTED

RolePath/LLM client (PID C -> vLLM process V)
  -> snapshot before (formal exclusive interval)
  -> send ordinary chat completion request
  -> streaming first-token timestamp + completion timestamp
  -> snapshot after

PrefixObservationValidator (PID C)
  -> validate schema/labels/monotonicity/exclusive request
  -> observed hit/miss/unavailable event
  -> feedback (valid events only)

vLLM PID V owns KV creation, lookup and eviction throughout.
```

不跨进程传送 token IDs 以外的 engine-private state。若 tokenizer compiler 与请求 frontend 不在同一版本/模板 identity，intent ineligible。

## 7. Dependency-safe scheduling

正式 scheduler 不能全局 sort。算法：

```python
completed = set()
pending = all_tasks
while pending:
    ready = [t for t in pending if set(t.depends_on) <= completed]
    if not ready:
        fail("dependency_cycle_or_missing_dependency")
    chosen = max(ready, key=(same_epoch_affinity, warmed_prefix_score,
                             schedule_priority, deterministic_task_id_tiebreak))
    run(chosen)
    completed.add(chosen.id)
```

约束：

- affinity 只能在 `ready` 内破平局，不能提前执行依赖未完成任务；
- 不同 family/lane/run root 不混排；
- history/replay 的 source round 必须完成并通过 quality gate 才解锁；
- failed task 依 manifest policy 阻断依赖或走明确 fallback，不能假装完成；
- feedback 只调整 ready-set 的 affinity score，不改变 DAG、gold、task payload；
- schedule plan 自带 `dependency_proof_digest`，runner 开始前和每次 adaptive reorder 后验证。

本轮静态 fixture 显示 `kv_prefix_reuse_v1` 的 input/friendly/hostile 三个显式顺序均 dependency-safe；这不替代通用 API 的上述约束。

## 8. 观测、原子性与不可比较条件

### 8.1 metrics

当前服务环境安装的 vLLM 0.9.2 源码定义 `prefix_cache_queries`/`prefix_cache_hits` counter，单位是 queried/cached **tokens**；但本轮未 GET 服务 `/metrics`，所以 endpoint 暴露名/labels 仍未核对。

正式有效 observation 必须同时满足：

1. before/after 都有同名、同 labels 的 query/hit counters；
2. `query_delta > 0`、`0 <= hit_delta <= query_delta`；
3. engine instance/epoch 不变；
4. interval 内只有被测 request（串行 runner + 服务独占证明/traffic guard）；
5. 无 retry、context-adjusted retry 或额外角色请求混入；如有则按 request 分段；
6. scrape 失败、counter reset、label cardinality 变化、其他流量、服务重启均 invalidated；
7. gauge 只作 service lifetime context，不能产生 task-local hit。

若无法取得独占服务，记录 `pollution_possible`，只可做诊断，不进入 P-B canonical aggregation。

### 8.2 latency

- `TTFT = first streamed response byte/token timestamp - client request dispatch timestamp`；非 streaming response 不产生 formal TTFT。
- `request_latency = final response received - dispatch`。
- `stage_latency` 分 render/tokenize/queue/prefill-observable/role completion；若 vLLM 不暴露 prefill time则标 unavailable，不用 TTFT 冒充。
- `task_latency` 包含四角色/执行/验证；P-C 才比较。
- client clock 使用 `perf_counter_ns`；记录 warm/cold、queue depth、prompt/completion tokens、output length。

## 9. 配置、迁移与关闭语义

| 配置 | 值/默认 | 语义 |
| --- | --- | --- |
| `STATEBUS_PREFIX_POLICY` | `off`（默认）、`observe`、`on` | off 完全走 independent baseline；observe 生成 intent/identity 不重排；on 才重排 |
| `STATEBUS_PREFIX_LAYOUT_VERSION` | pinned v2 | 不可在 run 中变化 |
| `STATEBUS_PREFIX_CACHE_NAMESPACE` | run-scoped | trust/isolation boundary |
| `STATEBUS_PREFIX_CACHE_EPOCH` | engine start/reset UUID | restart/reset 后新值 |
| `STATEBUS_PREFIX_MIN_FULL_BLOCKS` | 1 | 少于阈值 ineligible |
| `STATEBUS_PREFIX_REQUIRE_EXCLUSIVE_METRICS` | formal=true | 无独占证明 observation invalid |
| `STATEBUS_PREFIX_FEEDBACK_ADAPTIVE` | formal=false until P-B | 防止先适应后测量 |
| `STATEBUS_LATENT_MODE` | formal=`off` | 与 prefix 无关且不可被自动打开 |

迁移：

- 旧 `NeuralPrefixIdentity` payload 继续可读，写入时标 `legacy_lineage_only`。
- `NeuralPrefixRegistryResult.cache_hit` 保留一版 deprecated alias，但新 telemetry 只写 `candidate_handle_seen`。
- `neural_prefix_*_estimate` 保留 `estimate` namespace，不汇总到 `observed_*`。
- 关闭 policy 时，prompt 必须回到冻结的 independent baseline；不生成 hidden state、不影响 semantic/memory/logit flags。
- epoch 变化只清控制面 handles；不由 StateBus 操作 vLLM KV。冷 cache 需要服务动作时先获用户许可。

## 10. 文件级改动表

以下均为未来计划，本轮未实施。

| 文件/符号 | 变更 | 输入/输出与调用者 | 兼容/删除责任 |
| --- | --- | --- | --- |
| `v2/contracts/prefix.py`（新增） | `PrefixReuseIntentV2`、event/observation/identity dataclasses | Controller -> scheduler/telemetry | schema v2；拒绝未知版本 |
| `v2/contracts/__init__.py` | 导出 prefix contracts | 全调用者 | 无行为变化 |
| `v2/control/statebus_v2.proto`、`schema.py`、`messages.py` | typed intent/event envelope 或明确本地-only mapping | Controller/worker | 生成/compat tests；不含 KV bytes |
| `v2/runtime/neural_state.py` | 拆 `PrefixLineageIdentity` 与 `ExactTokenPrefixIdentity`；registry rename/compat fields | render/token compiler -> registry | deprecate `cache_hit`、保留 reader shim |
| `v2/retrieval/pipeline.py` | 暴露稳定 selected-entry/visibility key 序列 | semantic selection -> prefix renderer | 不改变 selected IDs/rank |
| `v2/runtime/smoke.py::_build_role_hydrated_slices` | 计算 authorized common keys；额外 role evidence 保留 suffix | EvidencePack -> role slices + common prefix spec | accounting schema version bump |
| `v2/runtime/role_path.py::compile_prefix_layout` | 接收 typed prefix；固定 boundary/separator；返回 token window metadata slot | role runners | legacy string input仅 tests过渡 |
| `v2/runtime/prefix_identity.py`（新增） | 用 frozen tokenizer/chat template 编译 exact IDs/hash/full blocks | renderer -> eligibility | tokenizer unavailable -> ineligible |
| `runtime/llm.py` | 暴露最终 request message/template kwargs digest；stream TTFT hooks | role path -> provider | provider 不支持 streaming时 TTFT unavailable |
| `v2/runtime/vllm_metrics.py` | 支持实际 schema names/labels/unit，request observation validator | runner snapshots -> typed observation | gauge-only 永不升级 |
| `v2/runtime/prefix_feedback.py` | 只接受 valid typed observation | runner -> scheduler | legacy `record()` 仅 deprecated diagnostic |
| `v2/benchmark/kv_prefix_schedule.py` | 添加 DAG proof、ready-set scorer | manifest -> plan | explicit orders先静态验证 |
| `v2/benchmark/continuous_runner.py` | request级 before/after、exclusive guard、ready-set loop、P-B order metadata | family runner | formal adaptive off；独立 run roots |
| `v2/benchmark/kv_prefix_experiment.py` | P-A/B/C preregistered runner、ABBA/cold-hot metadata | frozen fixtures/config | 新 run root，永不覆盖旧 artifact |
| `tests/v2/test_kv_prefix_control_plane.py` | rename/compat/fail-closed contract | unit | 旧语义明确 deprecated |
| `tests/v2/test_prefix_render_identity.py`（新增） | real tokenizer/template exact IDs、boundary/full blocks | fixture | 无模型请求 |
| `tests/v2/test_prefix_dependency_schedule.py`（新增） | DAG ready set、cycle/failure/adaptive reorder | manifest fixture | 不触服务 |
| `tests/v2/test_prefix_metrics_observation.py`（新增） | counter labels/unit/reset/pollution/gauge-only | Prometheus fixtures | 不触服务 |
| `tests/v2/test_prefix_live_capability.py`（新增、opt-in） | 单次 `/metrics` schema probe | local service | 明确 opt-in；不发 completion |

## 11. 测试与实验映射

| 层 | 无模型可完成 | 需要服务/授权 | 对应 claim |
| --- | --- | --- | --- |
| unit | stable ordering、hash inputs、registry rename、event state machine、fail closed | 否 | 仅合同存在 |
| contract | Proto round-trip、identity compatibility、epoch/lease | 否 | 仅控制面完整 |
| render/tokenize | Qwen3 fixed tokenizer、chat template、common window equality、negative reorder | 本地 tokenizer即可 | P-A identity，不是 hit |
| scheduler | DAG ready-set、friendly/hostile、failure/cycle | 否 | 因果顺序未改变 |
| metrics parser | static Prometheus fixtures、counter reset/labels/gauge | 否 | parser validity |
| capability probe | `/metrics` 是否有 counters/units/labels | 只读服务探针；本轮未做 | available/unavailable |
| P-A | stable vs reordered/unstable render；旧/新 quality fixture | API quality部分需正式授权 | exact token identity + quality |
| P-B | friendly vs hostile；ABBA；continuous/cold epoch | 模型请求；cold restart需单独授权 | observed cached tokens/TTFT |
| P-C | prefix off/on，其他机制固定 | 正式模型实验 | end-to-end effect |

## 12. P-A/P-B/P-C preregistration

### P-A 渲染完整性

- 固定：source EvidencePack、selected IDs、role visibility、model/tokenizer/template、task、output schema。
- 唯一改变：v2 stable common layout vs deliberately reordered/unstable prefix；另有 independent legacy layout。
- 输出：common token IDs/hash/count/full blocks、full prompt hash、role validator/quality、visibility equality。
- 通过：stable 的 participants common IDs 全等；negative control 不等；新旧 role quality 等价；无未授权 evidence 泄漏。

### P-B 引擎机制

- 固定：相同请求 multiset、tokens、model、generation params、quality validator、其他 StateBus flags。
- 唯一改变：dependency-safe cache-friendly vs cache-hostile order。
- 顺序：ABBA/BAAB 随机 blocks；连续服务与独立 cache epoch 分表。
- 输出：valid query/hit token deltas、request-with-hit rate、TTFT/request latency、prompt/completion tokens、quality、eviction/unavailable、run order。
- 通过：不预设速度；只有 counters valid、quality 等价、重复方向/CI 支持时才形成相应机制 claim。

### P-C 端到端

- 固定：公开 formal tasks、roles、semantic/memory/logit/latent 设置、资源、model。
- 唯一改变：prefix policy `off` vs `on`；两边 prompt 可见信息必须等价。
- 输出：total/stage latency、tokens、wire bytes、quality、actual observations、scheduler overhead。
- 通过：质量等价、配对重复、CI 和失败清单齐全；TTFT 变化但 total 无变化时只保留 mechanism claim。

## 13. 降级、回滚与资源上限

| 故障 | 行为 | 记账 |
| --- | --- | --- |
| tokenizer/template unavailable或漂移 | ineligible，baseline layout | `token_identity_unavailable/template_mismatch` |
| common visibility set为空 | baseline | `authorized_intersection_empty` |
| 少于完整 block | baseline | `insufficient_full_blocks` |
| service restart/epoch mismatch | invalidate handles；不推断 miss | `engine_epoch_changed` |
| counter 无/重置/schema变 | request继续，observation unavailable | 不进入 observed 分母 |
| concurrent traffic | 标污染；formal sample invalid | 保留失败，不补成 hit |
| cache eviction | 正常 miss；不重试请求制造 hit | valid miss 或无法识别时 unavailable |
| scheduler cycle/dependency failure | fail run before model request | `dependency_proof_failed` |
| quality下降 | 关闭 prefix policy，保留 P-A/P-C负结果 | 不发布性能 superiority |
| resource超限 | prefix text受 evidence budget；identity/event <64 KiB | fallback baseline |

回滚只切 `STATEBUS_PREFIX_POLICY=off` 并恢复冻结 baseline renderer；不删除历史 observation、不清用户服务 cache、不更改 semantic/memory/logit。

## 14. 最小实施顺序与验收

1. **Identity slice**：canonical authorized entries -> render -> local tokenizer exact ID；unit/P-A fixture 全绿。
2. **Typed lifecycle**：intent/events/registry rename/epoch/lease；无模型 integration 全绿。
3. **DAG scheduler**：ready-set API 替换全局排序；现有五个 manifests + cycle/failed dependency tests。
4. **Observation slice**：actual-version static metrics fixture、units/labels、stream TTFT；未授权服务仍可完成代码合同。
5. **Capability probe**：先请求授权；只读 `/metrics`，不发模型请求；结果只能 available/unavailable。
6. **P-A**：冻结 renderer/tokenizer/template/quality。
7. **P-B continuous**：获模型实验授权后串行 ABBA；cold epoch 另行授权。
8. **P-C**：R11 数据与其他 P0 gates 完成后运行。

最终 claim gate：

- 看不到 valid hit：可交付 exact-token intent、dependency-safe scheduling 和 honest unavailable/negative result；不可说 APC 实际命中。
- 有 hit 无 TTFT/总时延优势：可交付 engine mechanism evidence；不可说加速。
- P-C 质量不等价：性能结论全部阻断。
