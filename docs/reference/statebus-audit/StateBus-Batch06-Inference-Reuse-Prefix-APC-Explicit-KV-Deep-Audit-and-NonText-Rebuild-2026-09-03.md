# StateBus Batch 06 — Inference Reuse / Prefix / APC / Explicit KV 全链整合审计
## 兼论 Non-Text State 重构边界、Workflow-Aware Serving 参考与 Adaptive Runtime 接入设计

> **项目**：StateBus / `qcrs/os`  
> **主仓库**：https://github.com/qcrs/os  
> **历史参考仓库**：https://github.com/qcrs/os1  
> **源码基线**：`qcrs/os:master` → `8bfc6464ec236c0e121911095fc283129b0e7696`  
> **日期**：2026-09-03  
> **Batch 定位**：Batch 01–05 之后的 **Inference Reuse Integration Audit**  
> **模式**：源码审计 + 既有设计复核 + GitHub / 论文调研 + Target Architecture；**不修改代码、不运行新 benchmark**  
> **本轮明确不做**：
>
> - 不重新设计 Planner / Routing；
> - 不把 READY-set Scheduler 完整实现塞进本 Batch；
> - 不接 LMCache / SSD / RDMA / Remote KV；
> - 不做 CacheBlend / Semantic KV Relay / KVCOMM 类非前缀语义 KV；
> - 不实现 Hidden / Latent；
> - 不修改 vLLM；
> - 不进入 Batch 07 Reliability / Scheduler / Deployment；
> - 不把本文 Target Architecture 写成“当前已经实现”。

---

# 0. Executive Summary

这一轮最重要的结论不是：

> StateBus 还缺一个更复杂的 KV Cache 算法。

而是：

> **StateBus 已经拥有 APC、Prefix identity、prefix feedback、workflow affinity、Explicit KV continuation 等多个真实机制，但它们当前属于不同实验链 / sideband，并没有被统一收敛到 `AdaptiveMainline → AdaptiveRuntime → Model Invocation` 的正式执行边界。**

当前真实系统更接近：

```text
Adaptive Mainline
    │
    ├─ Planner / ApprovedPlan / Grant / Dispatcher
    │
    └─ 普通 LLM Provider 调用
             │
             └─ 没有正式 InferenceReusePolicy

另外存在：

A. Prefix/APC 路径
   RolePath / Smoke / Prefix Identity / Metrics / Benchmark Scheduler

B. Explicit KV 路径
   Executor → Summarizer 专用 RoleClient
   → private KV API
   → custom vLLM KVConnector
   → host KV registry

C. Non-Text 路径
   Semantic Embedding / Logit / planned Latent Hidden
```

所以 Batch 06 的核心工作不是继续扩 feature，而是完成三个架构收口：

```text
1. Model Invocation 必须成为 Runtime-owned seam

2. APC / Explicit KV 必须统一进入 Compute Reuse Plane

3. Semantic Non-Text 与 Compute Reuse 必须彻底解耦
```

---

## 0.1 对原 APC v3 的总体评价

原：

`StateBus-APC-v3-Workflow-Aware-Inference-Reuse-Deep-Design-2026-09-03.md`

**整体方向应保留，不建议推翻。**

其中这些判断是正确的：

```text
✅ APC 不应该暴露给 Planner
✅ Runtime 应维护 exact-token identity
✅ Prefix reuse 必须有 cache_salt / trust boundary
✅ StateBus 不应 fork vLLM allocator / block hash
✅ StateBus 应消费 vLLM observation，而不是自称“命中”
✅ APC 与 Explicit KV 应在同一个 Compute Reuse Plane 比较
✅ DAG / future-use 信息对 agentic serving 有独特价值
✅ LMCache / Remote KV 当前不应抢主线
```

但有 **五个关键边界需要修订**：

```text
修订 1：
InferenceReusePolicy
≠
READY-step Scheduler

修订 2：
Explicit KV
应重新定性为
Experimental Engine-Local Host KV Continuation

修订 3：
Latent-bearing invocation
v1 默认禁止 APC / Explicit KV composition

修订 4：
必须先建立统一 InferenceInvocation seam，
再谈 APC 接 Adaptive Runtime

修订 5：
当前 neural_state.py 中 Prefix bookkeeping
不能继续叫 NeuralState，
否则会与真正 Latent Hidden 冲突
```

---

## 0.2 本 Batch 最终冻结的目标关系

```text
                 Semantic / Agent State Plane

SemanticEmbedding
    │
    ▼
Selected Evidence / Memory
    │
    ▼
LatentStateRef          [future rebuild]
    │
    ▼
Model Invocation
    │
    ▼
DecisionState
    │
    ▼
Runtime Decision / Feedback


==========================================================


                 Compute Reuse Plane

Approved Logical Step
    │
    ▼
Execution Provider Binding
    │
    ▼
InferenceInvocation
    │
    ▼
Reuse Authorization
    │
    ▼
Exact Prefix Identity / Membership
    │
    ▼
InferenceReusePolicy
    ├─ RECOMPUTE
    ├─ APC_FULL_PROMPT
    └─ ENGINE_LOCAL_CONTINUATION
             │
             ▼
       RuntimeInferenceInvoker
             │
             ▼
            vLLM
             │
             ▼
    InferenceReuseReceipt
             │
             ▼
      Residency / Cost Hint
             │
             ▼
        Batch 07 Scheduler
```

最重要的冻结：

# **Semantic State 决定“模型看到/继承什么”；Compute Reuse 决定“同一语义输入如何少算”。**

两者不可再混成“非文本状态”。

---

# 1. Batch 06 接在 Batch 05 后面的精确位置

Batch 05 已冻结：

```text
Planner chooses WHAT

Runtime Binder chooses HOW
```

即：

```text
ApprovedPlan
    ↓
STEP_READY
    ↓
ExecutionBindingPolicy
    ↓
Provider-bound CapabilityGrant
    ↓
ProtocolInvocationBinding
    ↓
Provider
```

Batch 06 只接在：

```text
“Provider 已经确定，
且这个 provider 需要调用 LLM inference”
```

之后。

所以正确主链应是：

```text
Approved Logical Step
        ↓
ExecutionBindingPolicy
        ↓
Bound Provider
        ↓
Provider-bound Grant
        ↓
InferenceInvocationBuilder      ← Batch 06 新 seam
        ↓
InferenceInvocation
        ↓
InferenceReusePolicy             ← Batch 06
        ↓
RuntimeInferenceInvoker
        ↓
LLM Backend / vLLM
```

---

# 2. 先纠正一个重要设计：Batch 06 不负责 READY-set Scheduler

原 APC v3 中曾写：

```text
AdaptiveRuntimeEngine
    ↓
READY SET
    ↓
WorkflowAwareReuseScheduler
    ↓
chosen step
    ↓
InferenceReusePolicy
```

这个想法从系统效果上没有错，但从职责边界上应该调整。

## 2.1 为什么要拆

`InferenceReusePolicy` 回答的是：

> **已经决定执行这个 inference call 以后，用什么复用机制？**

例如：

```text
RECOMPUTE
APC
ENGINE_LOCAL_CONTINUATION
```

而 Scheduler 回答的是：

> **READY 的多个 step，先执行哪个？**

例如：

```text
Step A:
cache resident
critical path high

Step B:
cache miss
wait age high

Step C:
prefix likely reused soon
```

这已经涉及：

```text
fairness
critical path
aging
concurrency
resource admission
worker load
tool gap
preemption
```

属于 Batch 07。

---

## 2.2 外部研究也支持这个分层

### KVFlow

KVFlow 将 Agent workflow 抽象成：

```text
Agent Step Graph
```

并用：

```text
steps-to-execution
```

指导 KV eviction / prefetch。

它证明：

> Workflow 信息非常适合作为 KV 管理和调度信号。

但它不是在每个 model invocation 内部简单选择“APC on/off”。

Paper：

https://arxiv.org/abs/2507.07400

---

### Continuum

Continuum 关注：

```text
LLM call
→ tool gap
→ next LLM call
```

通过预测 tool duration 决定 KV TTL / pinning，同时结合 program-level scheduling。

Paper：

https://arxiv.org/abs/2511.02230

这进一步说明：

```text
KV residency
+
request scheduling
```

是 runtime scheduling plane。

---

### TOPAS

2026-08 的 TOPAS 更直接：

```text
workflow critical path
+
prefix locality
+
cache retention
+
request scheduling
+
aging
```

联合优化 JCT。

Paper：

https://arxiv.org/abs/2608.25523

这和 StateBus 的 DAG 信息高度相关，但应该成为：

# Batch 07 Scheduler 的参考

而不是继续把 Batch 06 扩成 serving scheduler 项目。

---

## 2.3 Batch 06 应输出什么给 Batch 07

Batch 06 只生成：

```python
InferenceReuseHint(
    prefix_group_id,
    reuse_mechanisms,
    residency_status,
    expected_saved_tokens,
    expected_saved_ms,
    continuation_available,
    reuse_scope,
    engine_epoch,
)
```

Batch 07 再决定：

```text
谁先跑
是否 pin
是否 delay
是否优先 warm prefix
是否 age cold request
```

---

# 3. 当前 StateBus Prefix / APC 真实源码链

当前 APC 不是假的。

底层已经有一组比较成熟的机制。

主要文件：

```text
statebus/contracts/prefix.py
statebus/runtime/prefix_identity.py
statebus/runtime/neural_state.py
statebus/runtime/prefix_feedback.py
statebus/runtime/vllm_metrics.py
statebus/runtime/role_path.py
statebus/runtime/smoke.py
statebus/benchmark/kv_prefix_schedule.py
```

---

# 4. 当前 Canonical Shared Prefix 已经做对什么

`statebus/runtime/prefix_identity.py` 当前：

```text
build_canonical_shared_evidence_prefix()
```

会对多个 participant role：

```text
取 authorized visible entry
↓
stable_key intersection
↓
验证相同 stable_key 的 entry_digest 一致
↓
deterministic sort
↓
canonical render
```

这比：

```text
直接拼接 Retriever 返回文本
```

强很多。

它已经建立：

```text
Visibility
→ Common Evidence Identity
→ Deterministic Prefix Layout
```

。

---

# 5. 当前 Exact Token Prefix Identity 也是真机制

`compile_exact_token_prefix_identity()` 会：

```text
rendered prompt by role
↓
apply_chat_template(tokenize=True)
↓
真实 request token ids
↓
sentinel A / sentinel B
↓
stable token boundary
↓
multi-role LCP
↓
向下取整到 full KV block
```

并输出：

```text
ExactTokenPrefixIdentity
```

包含：

```text
exact_token_ids_sha256
exact_token_count
full_block_token_count
block_size
message_shape_digest
shared_prefix_text_sha256
full_request_token_ids_sha256
```

所以当前 StateBus 不只是：

```text
“两个字符串看起来一样”
```

而是真正做到了：

```text
token-level
+
block-aligned
+
template-bound
```

的 Prefix identity。

---

# 6. 但 Exact Identity 仍然主要位于 Audit / Experiment Plane

问题在于：

当前 exact identity 的组织方式要求：

```text
多个完整 participant prompts
```

一起存在。

这非常适合：

```text
Executor prompt
Summarizer prompt
↓
事后验证它们到底共享多少 token
```

但不适合真正 Adaptive DAG：

```text
Step B 的完整 prompt
可能必须等 Step A artifact 产生以后
才知道
```

因此当前能力更像：

```text
post-hoc exact reuse proof
```

而不是：

```text
dispatch-time reuse eligibility
```

。

---

# 7. 原 APC v3 的 Boundary + Membership 拆分应保留

这一设计是正确的。

## 7.1 `CanonicalPrefixTokenBoundary`

只证明：

```text
Canonical Shared Prefix 本身
在当前 tokenizer/chat template 下
稳定覆盖哪些 token
```

建议：

```python
@dataclass(frozen=True)
class CanonicalPrefixTokenBoundary:
    prefix_group_id: str

    canonical_prefix_sha256: str

    boundary_token_ids_sha256: str
    exact_boundary_token_count: int
    full_block_token_count: int
    block_size: int

    tokenizer_digest: str
    chat_template_sha256: str
    template_kwargs_sha256: str
    message_shape_digest: str

    eligible: bool
    reason: str = ""
```

---

## 7.2 `RequestPrefixMembership`

每个真实请求 dispatch 前：

```python
@dataclass(frozen=True)
class RequestPrefixMembership:
    request_id: str
    prefix_group_id: str

    request_token_ids_sha256: str

    matched_boundary_token_count: int
    full_block_token_count: int

    eligible: bool
    reason: str = ""
```

这样：

```text
Canonical prefix
    ↓
stable token boundary

真正 request ready
    ↓
membership validation

然后才：
APC candidate
```

---

# 8. Tokenization Authority：当前本地 tokenizer 可保留，但应能力化

当前 `prefix_identity.py` 要求：

```text
tokenizer.apply_chat_template()
```

并绑定：

```text
model
tokenizer
template
template kwargs
```

第一版仍可用。

但现代 vLLM 已提供 Renderer API：

```text
/v1/completions/render
/v1/chat/completions/render
```

它的价值是：

```text
StateBus 看到的 final token IDs
==
vLLM server 实际执行使用的 token IDs
```

因此未来：

```python
InferenceBackendCapabilities(
    supports_render_api=True
)
```

时可优先：

```text
server-authoritative rendering
```

否则：

```text
pinned local tokenizer fallback
```

。

当前不应强依赖最新 renderer，因为 StateBus 当前部署 vLLM 版本与 main branch 未必一致。

---

# 9. 当前 Prefix Contract 的一个结构性问题：过多 Workflow 字段混进 Reuse Intent

当前 `PrefixReuseIntentV2` 已经有非常丰富的字段：

```text
engine_instance_id
cache_namespace
cache_epoch

model / revision / weights

tokenizer / revision
chat_template
template kwargs

source_doc_hashes
evidence_pack_hash
hydrate_manifest_hash

authorized_common_keys_digest
visibility policy

exact token identity
block size

adapter / multimodal / rope
kv dtype / quantization
TP / PP

dependency_ids
ready_set_epoch
schedule_priority
lease
```

这里前半部分非常有价值。

但：

```text
dependency_ids
ready_set_epoch
schedule_priority
```

应该逐步移出 Prefix mechanism contract。

因为它们属于：

# Scheduler Input

不是：

# Prefix Identity

。

---

# 10. 推荐把当前 Prefix Contract 拆成四类对象

## 10.1 Identity

```text
CanonicalPrefixTokenBoundary
RequestPrefixMembership
```

回答：

```text
这些请求是否真的共享相同 engine-visible prefix？
```

---

## 10.2 Authorization

```text
ReuseAuthorization
ReuseNamespace
```

回答：

```text
即使技术上能共享，
是否被允许共享？
```

---

## 10.3 Mechanism Decision

```text
InferenceReuseDecision
```

回答：

```text
这次调用到底：
RECOMPUTE / APC / CONTINUATION？
```

---

## 10.4 Observation / Scheduler Hint

```text
InferenceReuseReceipt
PrefixResidencyHint
InferenceReuseHint
```

回答：

```text
真实发生了什么？
下次 Scheduler 应该知道什么？
```

---

# 11. `neural_state.py` 必须重新命名 / 降级

这是本 Batch 很容易忽略但非常重要的问题。

当前：

```text
statebus/runtime/neural_state.py
```

主要包含：

```text
PrefixLineageIdentity
NeuralStateHandle
EngineLocalPrefixRegistry
NeuralPrefixReuseEstimate
...
```

但它自己已经在注释中承认：

```text
metadata lineage only
not exact token identity
no KV tensor export
```

而你后面真正要实现的是：

```text
Latent Hidden State
```

如果继续保留：

```text
NeuralStateHandle
```

来表示 prefix bookkeeping，会导致整个架构术语污染。

---

## 11.1 建议

未来迁移成：

```text
PrefixReuseCandidate
PrefixResidencyHint
PrefixReuseEstimate
PrefixReuseRegistry
```

。

不要再叫：

```text
NeuralState
Neural Prefix State
```

。

因为：

```text
Neural State
```

应保留给真正：

```text
Latent Hidden / Model Internal Representation
```

。

---

# 12. 当前 Prefix Registry 并不证明 Engine Residency

`EngineLocalPrefixRegistry` 当前记录：

```text
candidate_handle_seen_count
last_candidate_handle_seen_ns
estimated_resident_until_ns
eviction_risk
```

这属于：

```text
StateBus control-plane estimate
```

。

它不能证明：

```text
vLLM 这块 KV 现在真的还在 GPU cache
```

当前源码甚至已经通过 deprecated alias 提醒：

```text
cache_hit
不是实际 vLLM cache hit
```

这个方向是正确的。

---

# 13. Prefix Observation 当前已经比早期版本严谨很多

`PrefixObservationV2` 和 `prefix_feedback.py` 已经要求：

```text
counter delta
而不是 lifetime gauge
```

并要求：

```text
exclusive interval
no pollution
no retry
positive query delta
hit <= query
```

之后才允许：

```text
OBSERVED_HIT
OBSERVED_MISS
```

。

这应保留。

---

# 14. 下一步 Observation 应演进为 capability-based Residency

现代 vLLM 有 KV Events：

```text
BlockStored
BlockRemoved
AllBlocksCleared
```

因此建议未来增加：

```python
class ResidencyStatus(StrEnum):
    KNOWN_RESIDENT = "known_resident"
    KNOWN_ABSENT = "known_absent"
    UNKNOWN = "unknown"
```

```python
@dataclass(frozen=True)
class PrefixResidencyHint:
    prefix_group_id: str
    engine_instance_id: str
    cache_epoch: str

    status: ResidencyStatus
    observation_source: str
    observed_at_ns: int

    confidence: float
    reason: str
```

来源优先级：

```text
KV Events
    >
validated request-local metric delta
    >
StateBus estimate
    >
UNKNOWN
```

原则：

# 不知道就是 UNKNOWN，不要猜成 hit。

---

# 15. 当前 Benchmark 已经有一个不错的 dependency-aware prefix scheduler

`statebus/benchmark/kv_prefix_schedule.py` 已经有：

```text
DependencyAwarePrefixScheduler
```

它能：

```text
validate DAG
find ready tasks
choose next
respect dependencies

同时考虑：
warmed affinity
adaptive score
schedule priority
estimated prefix tokens
```

这说明：

> Scheduler idea 并不是从零开始。

但它目前属于：

```text
benchmark task-family scheduler
```

而不是：

```text
AdaptiveRuntimeEngine scheduler
```

。

因此：

# 不应在 Batch 06 复制进去。

应该在 Batch 07 抽象：

```text
AdaptiveRuntime READY SET
+
InferenceReuseHint
+
runtime resource facts
```

。

---

# 16. 当前 Adaptive Runtime 的真正 seam 在哪里

`AdaptiveRuntimeEngine` 当前：

```text
remaining steps
↓
ready = dependencies completed
↓
for step in sorted(ready, key=step_id)
↓
grant
↓
dispatch
```

所以有两个清晰 seam：

```text
A.
READY SET
→ choose step
```

属于：

# Batch 07 Scheduler

以及：

```text
B.
chosen step
→ grant/provider/model call
```

属于：

# Batch 06 Inference Reuse

。

这次必须把它们严格分开。

---

# 17. 当前 AdaptiveMainline 最大缺口：没有正式 Inference Context

`AdaptiveMainlineRequest` / `AdaptiveDispatchContext` 当前有：

```text
State Store
Memory Store
Workspace
Artifacts
Capability Registry
Validators
CodeAct
Retrieval
...
```

但没有：

```text
InferenceBackendCapabilities
ReuseAuthorization
ReuseNamespace
PrefixResidencyIndex
InferenceReusePolicy
```

。

所以当前 APC 并没有成为 Mainline capability。

---

# 18. `LLMClient.complete()` 是第二个关键断点

当前核心接口近似：

```python
complete(
    messages,
    purpose,
    temperature,
    response_schema,
)
```

没有：

```text
request identity
task / step / attempt
cache_salt
reuse policy
latent refs
tokenization authority
provider binding
reuse receipt
```

。

继续通过：

```text
extra_body
环境变量
RolePath feature flag
wrapper
```

塞功能，会越来越乱。

---

# 19. Batch 06 最重要的新 seam：`InferenceInvocation`

建议增加一个 Runtime-owned 对象：

```python
@dataclass(frozen=True)
class InferenceInvocation:
    invocation_id: str

    trace_id: str
    task_id: str
    step_id: str
    attempt_id: str

    purpose: str
    provider_binding_hash: str

    model_id: str
    model_revision: str

    messages_hash: str
    prompt_context_hash: str

    authorized_input_ref_commitments: tuple[str, ...]

    latent_ref_ids: tuple[str, ...] = ()

    response_contract_hash: str = ""

    reuse_authorization_id: str = ""
```

它不是：

```text
又一个 Prompt 类
```

而是：

# Runtime 对“一次 LLM inference”的正式身份对象。

---

# 20. 为什么这个 seam 比 APC 本身更重要

一旦有：

```text
InferenceInvocation
```

以后这些调用才能统一：

```text
Planner inference
Retriever query generation
Executor reasoning
CodeAct source generation
CodeAct repair
Summarizer
Decision probe
Latent receiver
```

然后 Runtime 才能统一回答：

```text
这个调用能不能 APC？
有没有 Latent？
cache_salt 是什么？
是不是需要 bypass？
怎么计 metrics？
如何产生 receipt？
```

否则 APC 永远是：

```text
某个 RoleClient wrapper
```

而不是：

```text
Runtime mechanism
```

。

---

# 21. 推荐新的 Model Invocation 主链

```text
Role / Capability Logic
        ↓
InferenceInvocationBuilder
        ↓
InferenceInvocation
        ↓
InferenceBackendCapabilityGate
        ↓
ReuseAuthorizationPolicy
        ↓
PromptContext / Prefix Compiler
        ↓
Exact Identity / Membership
        ↓
InferenceReusePolicy
        ↓
RuntimeInferenceInvoker
        ↓
Backend Adapter
        ↓
vLLM
        ↓
InferenceResult
        +
InferenceReuseReceipt
```

---

# 22. `InferenceBackendCapabilities`

不要通过：

```text
if vllm_version > x
```

猜能力。

建议：

```python
@dataclass(frozen=True)
class InferenceBackendCapabilities:
    provider_id: str

    supports_apc: bool
    supports_cache_salt: bool

    supports_render_api: bool
    supports_kv_events: bool
    supports_prefix_metrics: bool

    supports_explicit_continuation: bool

    supports_prompt_embeds: bool
    supports_prompt_embeds_cache_identity: bool

    explicit_continuation_single_worker_only: bool
    explicit_continuation_tp1_only: bool
    explicit_continuation_pp1_only: bool
    explicit_continuation_single_seq_only: bool
```

Runtime：

```text
support
→ use

not support
→ fallback

unknown
→ fail closed to recompute
```

。

---

# 23. APC 的正式定位

vLLM APC 是：

```text
identical prefix tokens
↓
hash-based full KV block reuse
↓
skip repeated prefill
```

其重要性质是：

```text
语义输入不变
模型输出语义不应因为 APC 本身变化
```

因此在 StateBus 中：

# APC 是最适合做默认 Compute Reuse 的机制。

---

# 24. APC 不是什么

APC 不是：

```text
Agent A 把“思维”传给 Agent B
```

。

APC 也不是：

```text
Memory
```

。

APC 只是：

```text
Agent B 的 prompt 前缀
和之前某个 request 前缀 token 完全一致
↓
之前已经计算过 Transformer prefill
↓
这部分不用再算
```

。

---

# 25. APC 第一版 Eligibility

建议：

```text
Backend supports APC
AND
ReuseAuthorization allows sharing
AND
cache namespace resolved
AND
request membership exact
AND
full_block_token_count > 0
AND
no unsupported latent/cache composition
```

才：

```text
APC_ELIGIBLE
```

。

否则：

```text
RECOMPUTE
```

。

---

# 26. `cache_salt` 必须升为 P0

这不是 Batch 09 才考虑的普通 security polish。

因为：

> **Cache sharing scope 本身就是功能语义。**

现代 vLLM 的 `cache_salt` 会进入第一块 prefix hash，使不同 salt 的请求无法共享 APC。

所以 StateBus 必须显式建：

```text
ReuseAuthorization
→ ReuseNamespace
→ cache_salt
```

。

---

# 27. 推荐 `ReuseScope`

```python
class ReuseScope(StrEnum):
    TASK = "task"
    SESSION = "session"
    CORPUS = "corpus"
    TRUST_DOMAIN = "trust_domain"
```

典型：

| Scope | 共享范围 | 用途 |
|---|---|---|
| TASK | 一个 task | Executor / Summarizer 内 |
| SESSION | workflow / conversation | 多轮 Agent |
| CORPUS | 同一公共 corpus | 多查询同文档 |
| TRUST_DOMAIN | tenant / project | system/tool common prefix |

---

# 28. `ReuseNamespace`

```python
@dataclass(frozen=True)
class ReuseNamespace:
    scope: ReuseScope
    principal_digest: str
    policy_version: str

    cache_salt_digest: str
```

真实 salt：

```text
HMAC(
    runtime_secret,
    scope || principal || policy_version
)
```

。

建议：

```text
salt plaintext:
仅在内存中传给 backend

audit:
只存 digest
```

。

---

# 29. 为什么不能 cache_salt = task_id / tenant_name

vLLM 当前安全文档明确建议：

```text
salt 应不可预测
```

而不是：

```text
username
tenant ID
task ID
```

这种可猜字符串。

所以 StateBus 不应把 semantic identity 直接当 salt。

---

# 30. 当前 `LLMClient` 没有 cache_salt 通道

这是 P0 integration blocker。

目前：

```text
RoleLLMConfig.extra_body
request_kwargs
```

理论上可以临时透传。

但长期不要让：

```text
业务 role config
```

决定 cache security boundary。

应该：

```text
RuntimeInferenceInvoker
    ↓
backend adapter
    ↓
inject cache_salt
```

。

---

# 31. 当前 Explicit KV 的真实实现必须重新定性

这是本 Batch 最重要的源码事实之一。

当前：

```text
StateBusLocalKVConnector
```

并不是：

```text
在 GPU BlockPool 中保留一个父请求 KV handle
然后给下一个请求直接引用
```

。

真实路径是：

```text
Producer vLLM KV layer
    ↓
extract paged slots
    ↓
copy_to_host()
    ↓
pinned/pageable CPU memory
    ↓
WorkerKVRegistry

Consumer
    ↓
从 WorkerKVRegistry 取 layer tensor
    ↓
inject back to paged KV slots
    ↓
只计算 suffix
```

。

---

# 32. 所以它应该正式命名为

推荐概念名：

# `Engine-Local Host KV Continuation`

而不是笼统：

```text
Explicit KV
```

。

代码 contract 暂时不必立刻 rename，但文档和 architecture 必须准确。

---

# 33. 当前 Explicit KV 的硬限制

`worker_extension.py` 当前 readiness 明确要求：

```text
VLLM_USE_V1 = 1

kv_connector =
StateBusLocalKVConnector

kv_role =
kv_both

automatic_prefix_caching =
False

max_num_seqs =
1

tensor_parallel_size =
1

pipeline_parallel_size =
1
```

。

所以它不是通用 serving path。

它是：

# **严格受控、单 worker、单 sequence 的 mechanism probe。**

---

# 34. 当前 APC 与 Explicit Continuation 实际是互斥的

`StateBusLocalKVConnector.get_num_new_matched_tokens()` 当前：

```text
如果 LOAD request
且 num_computed_tokens != 0
→ local_prefix_cache_must_be_disabled
```

。

也就是说：

```text
APC 先命中了一部分
+
Explicit KV 再补剩余
```

当前并不支持。

所以 Batch 06 v1：

```python
ReuseMechanism:
    RECOMPUTE
    APC_FULL_PROMPT
    ENGINE_LOCAL_CONTINUATION
```

必须是：

# mutually exclusive

。

不要设计：

```text
APC + KV composition
```

这种当前 backend 根本不支持的路径。

---

# 35. 当前 Explicit KV 还有一个 config contract 问题

`KVRegistryConfig` 有：

```python
one_shot: bool = True
```

但当前 registry 生命周期实际总是：

```text
READY
→ CONSUMING
→ CONSUMED
```

之后不能重新：

```text
begin_consume()
```

。

也就是说：

# 当前实现事实上始终 one-shot。

`one_shot=False` 这个 knob 没有真正改变行为。

建议：

```text
v1：
直接把 contract 定义成 one-shot

未来真的支持 multi-consumer
再加语义
```

而不是保留一个看起来可以关闭、实际无效的开关。

---

# 36. 当前 Explicit KV RoleClient 也不是 Adaptive DAG abstraction

`EngineLocalKVRoleClient` 当前写死：

```text
Executor
    = producer

Summarizer
    = consumer
```

内部状态：

```text
_parent_token_ids
_handle_id
```

只有一个。

它适合：

```text
机制实验
```

但不适合：

```text
dynamic Plan
multiple executor
fan-out
parallel branch
optional summarizer
replan
retry
```

。

因此：

# 不建议直接把 RoleClient 接进 AdaptiveMainline。

---

# 37. Explicit KV 第一版正确的处理方式

建议：

```text
保留当前 connector / worker extension / registry

↓
重新包装成

ExperimentalContinuationProvider
```

由 Runtime eligibility gate 决定是否可用。

---

# 38. Explicit Continuation Eligibility

建议必须全部满足：

```text
backend reports capability

same engine instance
same engine generation

same model fingerprint
same tokenizer fingerprint

TP = 1
PP = 1
max_num_seqs = 1

APC disabled for this lane

parent block aligned

exact parent token digest

single producer
single consumer

handle READY
not expired
not consumed

expected benefit > threshold
```

否则：

```text
not eligible
→ APC or RECOMPUTE
```

。

---

# 39. 为什么 Explicit KV 不应该成为默认路径

你以前的专项 evidence 已经给出了很清楚的信号：

```text
4096-token handle
≈ 1 GiB

store:
~1.7 s p50

load:
~0.3 s p50

consumer TTFT:
明显下降

但 full mainline wall:
只小幅下降
```

这非常合理。

因为：

```text
省掉 consumer prefill
```

同时引入：

```text
GPU → CPU capture
CPU storage
CPU → GPU load
KV inject
private API
serialization/control overhead
```

。

所以：

# APC 默认，Continuation 条件式。

这是非常正确的系统选择。

---

# 40. 推荐 `InferenceReusePolicy`

```python
class ReuseMechanism(StrEnum):
    RECOMPUTE = "recompute"
    APC_FULL_PROMPT = "apc_full_prompt"
    ENGINE_LOCAL_CONTINUATION = "engine_local_continuation"
```

Policy 输入：

```text
InferenceInvocation

BackendCapabilities

ReuseAuthorization

CanonicalPrefixTokenBoundary
RequestPrefixMembership

PrefixResidencyHint

ContinuationHandleCandidate

CostObservation
```

输出：

```text
InferenceReuseDecision
```

。

---

# 41. `InferenceReuseDecision`

建议：

```python
@dataclass(frozen=True)
class InferenceReuseDecision:
    invocation_id: str

    mechanism: ReuseMechanism

    eligible: bool
    reason_code: str

    prefix_group_id: str = ""
    prefix_membership_hash: str = ""

    reuse_namespace_id: str = ""
    cache_salt_digest: str = ""

    continuation_handle_id: str = ""

    expected_saved_tokens: int = 0
    expected_saved_ms: float = 0.0

    decision_policy_version: str = ""
```

。

---

# 42. 第一版 Cost Policy 不要做复杂在线学习

Batch 06 只需：

```text
safe threshold + calibrated observations
```

。

## APC

近似：

\[
Benefit_{APC}
=
PrefillSaved
-
Identity/Layout/ControlOverhead
\]

通常 APC overhead 很低。

所以：

```text
full block > threshold
且授权合法
→ prefer APC
```

。

---

## Continuation

近似：

\[
Benefit_{KV}
=
RecomputePrefill
-
(Store + Load + Transfer + Inject + OpportunityCost)
\]

只有：

```text
benefit > positive safety margin
```

才用。

否则：

```text
APC / RECOMPUTE
```

。

---

# 43. 不要让 Planner 决定 reuse

Planner 不应该输出：

```text
use_apc=true
use_explicit_kv=true
cache_scope=corpus
```

。

Planner 只决定：

```text
logical work
```

。

Runtime 根据：

```text
已经批准的 inference invocation
```

再选择物理计算方式。

这和 Batch 05：

```text
Planner chooses WHAT
Runtime chooses HOW
```

完全一致。

---

# 44. `InferenceReuseReceipt`

当前 Prefix 有 observation。

Explicit KV 有：

```text
KVForwardProof
```

。

建议统一到：

```python
@dataclass(frozen=True)
class InferenceReuseReceipt:
    invocation_id: str

    selected_mechanism: str
    effective_mechanism: str

    fallback_used: bool
    fallback_reason: str

    logical_prompt_tokens: int

    reused_tokens: int
    computed_prefill_tokens: int

    observed_ttft_ms: float
    observed_wall_ms: float

    engine_instance_id: str
    engine_epoch: str

    prefix_observation_hash: str = ""
    kv_forward_proof_hash: str = ""
```

它不是替换底层 proof。

而是：

```text
Runtime 统一 surface
```

。

---

# 45. Batch 06 与 Non-Text 重构必须明确对接

你现在决定 Non-Text 肯定重构，这是正确的。

但 Batch 06 不应该：

```text
顺手把 Hidden 也实现
```

。

它应该冻结：

# **未来 Hidden 与 Compute Reuse 如何不互相踩 contract。**

---

# 46. Non-Text 最终建议继续采用四分法

```text
Semantic Embedding
    =
Selection State

Latent Hidden
    =
Representation Handoff State

Decision Logit
    =
Runtime Decision State

APC / KV
    =
Compute Reuse State
```

这个分类建议保留。

---

# 47. 但“State”这个词还要再收紧

更精确：

```text
SemanticEmbedding
LatentState
DecisionState

属于：
Semantic / Runtime State Plane

而：

APC / KV
属于：
Compute Reuse Plane
```

所以最终项目叙述不要说：

> StateBus 有四种 non-text state。

建议说：

> StateBus 有一条 typed non-text semantic state pipeline，并额外提供 engine-local compute reuse mechanisms。

这样更专业。

---

# 48. Semantic Embedding 与 APC 的关系

Semantic Embedding：

```text
Query
↓
选择 Evidence IDs
```

然后：

```text
Selected Evidence
↓
被 PromptContextBuilder 渲染
↓
形成可能可共享的 canonical prefix
```

所以它们的关系是：

```text
Embedding
决定“选什么内容”

APC
决定“这段已经选定且完全一致的文本内容是否少算”
```

。

不是：

```text
Embedding State
直接变成 KV
```

。

---

# 49. Latent Hidden 与 APC 的关系必须 fail-closed

这是对你之前设计最重要的新修订之一。

未来 Latent 可能通过：

```text
inputs_embeds
prompt_embeds
continuous prefix
```

进入下游模型。

这会改变：

```text
Transformer 实际输入表示
```

。

如果 Cache Identity 没把这些 embedding 内容纳入 key：

```text
同样长度
不同 latent
```

就可能错误共享 KV。

---

# 50. 这不是理论担忧

2026 年 vLLM / LMCache 已经出现过真实问题：

```text
不同 prompt_embeds
长度相同
cache_salt 相同

↓
external KV key 没包含 embedding 内容

↓
错误复用旧 KV
```

因此 StateBus v1 必须默认：

```text
if invocation.latent_ref_ids:
    APC = BYPASS
    ExplicitContinuation = BYPASS
```

除非 backend 明确声明：

```text
supports_prompt_embeds_cache_identity
supports_latent_reuse_composition
```

并且 StateBus 有可验证 identity。

---

# 51. Latent-bearing invocation v1 Policy

```text
LatentStateRef present
    │
    ├─ provider 不证明 latent-aware cache identity
    │      ↓
    │   RECOMPUTE
    │
    └─ future verified capability
           ↓
       再研究 composition
```

。

这比：

```text
“Latent + APC 看起来可以一起省更多”
```

安全得多。

---

# 52. DecisionState 与 APC 基本正交

DecisionState 是：

```text
Model inference
↓
bounded candidate logits
↓
Runtime policy
```

发生在：

```text
inference 之后
```

。

它不应该进入：

```text
prefix identity
```

。

它可能影响：

```text
下一个 invocation 是否 RETRY / EXPAND / REPLAN
```

然后新 invocation 再独立做 reuse decision。

---

# 53. Hidden / Latent 不应进入 `ReuseMechanism`

不能写：

```text
ReuseMechanism:
TEXT
LATENT
APC
KV
```

这会再次混乱。

正确：

```text
RepresentationPolicy:
TEXT
LATENT_ADVISORY

InferenceReusePolicy:
RECOMPUTE
APC
CONTINUATION
```

。

两个维度。

---

# 54. Non-Text 重构建议保留 Authoritative / Advisory 双平面

你之前设计：

```text
Evidence / Artifact
    authoritative

Latent
    advisory
```

这是对的。

未来：

```text
Executor
    ├─ Verified ArtifactRef
    └─ LatentStateRef
            ↓
         Summarizer
```

。

如果：

```text
Latent invalid
```

应：

```text
fallback text
```

。

如果：

```text
Artifact invalid
```

应：

```text
reject factual claim
```

。

Batch 06 只要确保：

```text
Compute Reuse
不能把 advisory latent
偷偷当作 cache identity 的普通文本部分
```

。

---

# 55. Explicit KV 也不应该变成 Semantic Authority

即使 Consumer：

```text
继承了 Producer 的 KV
```

也不能说：

```text
KV 是 Evidence
```

。

KV 只是：

```text
Producer prefix 对应的 Transformer compute state
```

。

最终事实仍然必须回溯：

```text
EvidenceRef
ArtifactRef
ClaimSet
```

。

这和 Latent 的 advisory 原则一致。

---

# 56. 为什么当前不应做 Semantic KV Relay

2026 ACL 已经出现非常明确的负面证据：

`When KV Cache Reuse Fails in Multi-Agent Systems: Cross-Candidate Interaction is Crucial for LLM Judges`

指出某些跨候选 / 部分上下文 KV reuse：

```text
最终 accuracy 可能看似稳定
```

但：

```text
judge selection consistency
可能明显偏离 dense prefill
```

。

这说明：

```text
“KV 看起来能复用”
≠
“语义上安全”
```

。

因此 StateBus v1 应坚持：

```text
APC:
exact prefix only

Explicit Continuation:
exact parent continuation only

Semantic KV splice / approximate donor:
DEFER
```

。

---

# 57. 对 vLLM 最新 KV Key Evolution 的启示

vLLM 当前 prefix key 已经越来越复杂。

除了：

```text
tokens
parent hash
```

还会涉及：

```text
cache_salt
LoRA
multimodal
prompt embeds
other extra keys
```

。

2026-08 vLLM 甚至有一个 KV-cache key partitioning conformance RFC，总结多条：

```text
某个 partition dimension 在外部 tier 被漏掉
→ 本应 miss 的请求错误 hit
```

。

所以 StateBus 不应该建立：

```text
“我们自己发明一套永远正确的 KV key”
```

。

正确原则：

# Engine owns physical KV identity.

StateBus 只负责：

```text
semantic authorization
runtime grouping
exact request membership
observation
```

。

---

# 58. StateBus 与 vLLM 的最终职责边界

## StateBus

```text
Task / Plan / Provider Authority

Evidence visibility
ReuseAuthorization
ReuseScope
cache namespace

Canonical Prefix layout

Dispatch-time exact request membership

Choose:
RECOMPUTE / APC / CONTINUATION

Consume:
KV events / metrics / proof

Produce:
scheduler hint / audit / cost observation
```

---

## vLLM

```text
final token / embed representation

physical block hashing

BlockPool / KVCacheManager

cache hit / miss

KV lifetime

actual block allocation

actual prefix reuse

actual KV load/store connector execution
```

。

---

# 59. 不要让 StateBus 重写 vLLM BlockPool

当前没有必要：

```text
fork allocator
自建 block hash
自己控制 LRU
```

。

StateBus 的差异化价值在：

```text
它知道 Agent workflow / Task / Evidence / Trust / DAG
```

而不是：

```text
它能比 vLLM 更好地写一个 hash table
```

。

---

# 60. 对外部工作最值得借什么

## 60.1 vLLM APC

借：

```text
exact prefix
full block
cache_salt
engine-owned physical cache
KV Events
Renderer authority
```

不借：

```text
把 StateBus 退化成 serving backend wrapper
```

。

---

## 60.2 SGLang LPM / Radix

借：

```text
prefix locality 是真正 scheduler signal
```

以及：

```text
cache-first 可能 starvation
```

。

不在 Batch 06 实现 LPM。

---

## 60.3 KVFlow

借：

```text
Agent Step Graph
future-use distance
```

作为：

```text
Batch 07 scheduler hint
```

。

---

## 60.4 Continuum

借：

```text
tool gap
KV TTL
program continuity
```

作为：

```text
residency / scheduling signal
```

。

---

## 60.5 PBKV

PBKV 对 dynamic workflow：

```text
预测未来 agent invocation
```

再保留高 reuse-potential KV。

借：

```text
dynamic workflow future-use
```

。

不借：

```text
第一版 learned predictor
```

。

Paper：

https://arxiv.org/abs/2605.06472

---

## 60.6 CacheScout

CacheScout 在线学习：

```text
agent execution transitions
```

用于：

```text
eviction
prefetch
```

。

借：

```text
当 workflow graph 不完整时，
可以在线学习 reuse likelihood
```

。

但放：

```text
future / Batch 07+
```

。

Paper：

https://arxiv.org/abs/2608.14624

---

## 60.7 TOPAS

最值得 Batch 07 深入。

因为它直接做：

```text
Task critical path
+
prefix retention
+
request scheduling
+
aging
```

。

StateBus 本身已经有：

```text
ApprovedPlan DAG
```

因此在信息层面甚至比纯 serving engine 更天然。

但本轮只输出：

```text
reuse hints
```

。

---

# 61. LMCache 为什么当前继续 DEFER

LMCache 现在是很成熟的：

```text
CPU
disk
remote
multi-engine
non-prefix reuse
KV transform
```

中间层。

但 StateBus 当前问题不是：

```text
KV 没地方存
```

。

而是：

```text
APC / continuation
还没有接进正式 Adaptive Runtime
```

。

此时引入 LMCache 会新增：

```text
external key identity
offload tier
transfer lifecycle
prefetch
remote failure
serialization
resource accounting
```

。

范围会失控。

---

# 62. StateBus 已经有 Host KV Continuation，更没必要立即加 LMCache

当前 Explicit KV 已经证明：

```text
GPU KV
↓
host
↓
consumer load
↓
suffix-only prefill
```

机制上可行。

所以 Batch 06 应先回答：

```text
什么时候值得用？
如何进入 Runtime？
如何证明？
```

而不是：

```text
再换一个更大的 KV data plane
```

。

---

# 63. 推荐最终 Batch 06 Target Architecture

```text
ApprovedPlan
    │
    ▼
ExecutionBindingPolicy
    │
    ▼
Bound Provider
    │
    ▼
Provider-bound Grant
    │
    ▼
InferenceInvocationBuilder
    │
    ▼
InferenceInvocation
    │
    ├─────────────── Semantic Inputs
    │                  Evidence / Artifact
    │                  Optional LatentStateRef
    │
    ▼
InferenceBackendCapabilities
    │
    ▼
ReuseAuthorizationPolicy
    │
    ▼
ReuseNamespace
    │
    ▼
ShareablePrefixCompiler
    │
    ▼
CanonicalPrefixTokenBoundary
    │
    ▼
RequestPrefixMembership
    │
    ▼
InferenceReusePolicy
    │
    ├─ RECOMPUTE
    │
    ├─ APC_FULL_PROMPT
    │
    └─ ENGINE_LOCAL_CONTINUATION
    │
    ▼
RuntimeInferenceInvoker
    │
    ▼
Backend Adapter / vLLM
    │
    ▼
InferenceResult
    +
InferenceReuseReceipt
    │
    ├─ PrefixObservation
    ├─ KVForwardProof
    ├─ TTFT
    ├─ prefill tokens
    └─ fallback
    │
    ▼
PrefixResidencyHint / ReuseCostObservation
    │
    ▼
Batch 07 Runtime Scheduler
```

---

# 64. Semantic / Non-Text Target Architecture

与上面平行：

```text
Task / Query
    │
    ▼
SemanticEmbedding
    │
    ▼
Selected Evidence / Memory
    │
    ▼
Agent A
    │
    ├─ Verified ArtifactRef
    └─ LatentStateRef
            │
            ▼
          Agent B
            │
            ▼
       DecisionState
            │
            ▼
        Runtime Policy
```

Compute Reuse：

```text
围绕每一个 Agent LLM invocation
独立决定
RECOMPUTE/APC/CONTINUATION
```

。

---

# 65. 最终不要再画成四个“平行 non-text feature”

旧的：

```text
Embedding
Logit
APC
KV
```

虽然方便展示 feature，但 architecture 上已经不够准确。

推荐最终 PPT / README：

```text
Semantic State Plane
    Semantic Selection
    Latent Handoff
    Decision State

Compute Reuse Plane
    APC
    Explicit Continuation
```

。

---

# 66. P0 问题列表

## P0-1 — Mainline 没有 `InferenceInvocation`

影响：

```text
APC / Latent / Decision
只能继续 wrapper / feature flag 化
```

。

---

## P0-2 — `LLMClient` 没有 Runtime reuse context

缺：

```text
request identity
cache_salt
reuse decision
backend capability
reuse receipt
```

。

---

## P0-3 — Prefix identity 仍偏 post-hoc

需要：

```text
Boundary
+
Membership
```

dispatch-time 化。

---

## P0-4 — cache_salt 未进入正式 inference path

当前 Prefix contract 有 digest 概念，但普通 LLM provider path 没有统一传输 seam。

---

## P0-5 — Explicit KV 被过度泛化描述

真实是：

```text
host KV
single worker
single seq
TP1
PP1
APC off
one-shot
```

。

必须重新定性。

---

## P0-6 — APC / Explicit KV 当前不能组合

需要在 contract 中写成互斥机制，而不是未来想象中的自由组合。

---

## P0-7 — `neural_state.py` Prefix 命名污染 Latent

需要在 Non-Text 重构前拆掉概念冲突。

---

## P0-8 — Latent future path 与 KV reuse identity 存在 correctness 风险

第一版：

```text
Latent present
→ reuse fail closed
```

。

---

# 67. P1 问题列表

## P1-1 — stable-key suffix subtraction

当前 canonical shared prefix 更像：

```text
common intersection
```

未来应更明确：

```text
shared prefix
+
role-private suffix
```

避免重复信息同时出现在两边。

---

## P1-2 — Prefix Residency Index

增加：

```text
KV Events
→ exact residency

metrics
→ request observation

estimate
→ low-confidence hint
```

。

---

## P1-3 — server-authoritative tokenizer/render

现代 backend 支持时：

```text
Renderer API
```

优先。

---

## P1-4 — unified reuse receipt

统一：

```text
APC observation
KVForwardProof
fallback
TTFT
prefill accounting
```

。

---

## P1-5 — Explicit KV one-shot contract cleanup

要么：

```text
删掉 one_shot=False illusion
```

要么未来真正实现 multi-consumer。

当前先前者。

---

# 68. P2 / DEFER

```text
DEFER:
APC + continuation composition

DEFER:
Latent + APC composition

DEFER:
multi-consumer KV handle

DEFER:
TP / PP Explicit KV

DEFER:
max_num_seqs > 1 continuation

DEFER:
GPU-resident pinned explicit handles

DEFER:
LMCache

DEFER:
SSD / remote KV

DEFER:
CacheBlend

DEFER:
Semantic KV donor reuse

DEFER:
learned cache predictor

DEFER:
scheduler critical-path / aging
→ Batch 07
```

。

---

# 69. 推荐实施 Slice

注意：

> 本文只是设计，不表示现在立即进入实现。

真正实施时建议：

---

## R0 — Source Truth / Terminology Freeze

目标：

```text
不改行为
```

完成：

```text
Prefix ≠ Neural State
APC ≠ Semantic State
Explicit KV = Host Continuation
```

并冻结：

```text
ReuseMechanism enum
backend capability surface
```

。

---

## R1 — InferenceInvocation Seam

新增：

```text
InferenceInvocation
RuntimeInferenceInvoker
BackendCapabilities
```

先让普通：

```text
RECOMPUTE
```

完全通过新 seam。

Gate：

```text
所有旧任务行为不变
```

。

---

## R2 — ReuseAuthorization + cache_salt

新增：

```text
ReuseScope
ReuseNamespace
runtime-owned cache_salt
```

。

先只：

```text
APC off
```

验证 identity/authorization。

---

## R3 — Prefix Boundary + Membership

把当前：

```text
post-hoc multi-prompt exact identity
```

演进为：

```text
canonical boundary
+
per-request membership
```

。

---

## R4 — APC Mainline Integration

Runtime：

```text
eligible
→ pass cache_salt
→ normal full prompt
→ let vLLM APC hit/miss
```

。

不碰 vLLM allocator。

---

## R5 — APC Receipt / Residency

接：

```text
request-local metrics delta
```

有能力时再：

```text
KV Events
```

。

---

## R6 — Explicit Continuation Reclassification

不扩能力。

只做：

```text
Backend capability exposes strict constraints

Runtime eligibility can select it
```

。

如果不满足：

```text
not eligible
```

。

---

## R7 — Non-Text Compatibility Guard

为未来 Latent 预留：

```text
latent_ref_ids
```

并默认：

```text
Latent → bypass reuse
```

。

这一步不实现 Hidden。

---

# 70. Batch 06 Exit Gate

完成设计 / 后续实现后，至少要能证明：

```text
1.
APC 不再只存在于 smoke / benchmark

2.
Adaptive Runtime 中每次 LLM call
都有明确 invocation identity

3.
Reuse scope / cache_salt
由 Runtime authority 决定

4.
Exact prefix identity
在 dispatch 前可证明

5.
APC hit/miss
由 vLLM observation 证明

6.
Explicit KV
被准确标记为受限 host continuation

7.
不满足 continuation constraints
不会误选

8.
Latent-bearing invocation
不会错误复用 text-only KV

9.
Planner 不控制 physical reuse

10.
Batch 07 能消费 reuse hint
而 Batch 06 不越权调度
```

。

---

# 71. Batch 06 → Batch 07 Handoff

Batch 07 不需要重新研究：

```text
什么是 APC
什么是 prefix hash
什么是 Explicit KV
```

。

它应该直接拿：

```text
READY SET
+
InferenceReuseHint
+
PrefixResidencyHint
+
Provider runtime facts
+
resource facts
+
step age
+
DAG critical path
```

回答：

```text
哪个 READY step 先执行？
```

。

---

# 72. Batch 07 值得重点研究的策略信号

```text
hard dependency ready

critical path distance

prefix residency

expected prefill saved ms

next-use distance

tool gap estimate

provider availability

GPU / worker pressure

attempt age

deadline / fairness

starvation prevention
```

。

外部参考：

```text
TOPAS
KVFlow
Continuum
PBKV
CacheScout
SGLang LPM
```

。

---

# 73. 对当前项目叙事的建议

不要最终写成：

> 我们实现了 Embedding、Logit、APC、KV、Hidden 五种非文本状态。

这会显得功能堆叠。

推荐叙事：

> StateBus 将 Agent 协作拆成语义状态平面与计算复用平面：前者通过 typed semantic selection、latent handoff 与 decision state 减少文本化和控制歧义；后者通过 exact-prefix APC 与受限 engine-local KV continuation 复用已完成的 Transformer 计算。Runtime 统一负责 identity、authorization、provider binding、reuse policy、observation 和 fallback。

这个叙事比：

```text
feature list
```

强很多。

---

# 74. 对赛题“非文本状态创新”的关系

赛题要求至少一种：

```text
embedding
semantic vector
hidden state
other intermediate representation
```

当前 Embedding 已满足最低要求。

未来 Latent Hidden 的意义是：

```text
提升 non-text state innovation
```

。

APC / Explicit KV：

```text
是额外的 inference compute reuse
```

不要拿它们充当赛题最低要求的主要证明。

---

# 75. Batch 06 最终冻结结论

最终建议冻结：

```text
A.
原 APC v3 主方向保留

B.
Scheduler 从 Batch 06 移到 Batch 07

C.
InferenceReusePolicy 只决定 mechanism

D.
APC 是 v1 默认 compute reuse

E.
Explicit KV 重新定性为
Experimental Engine-Local Host KV Continuation

F.
Explicit KV 当前：
APC off
single seq
TP1
PP1
one-shot

G.
建立 Runtime-owned InferenceInvocation seam

H.
cache_salt / ReuseAuthorization 是 P0

I.
Exact identity 拆 Boundary + Membership

J.
Prefix bookkeeping 从 NeuralState 命名中剥离

K.
Non-Text 继续：
Selection → Latent Handoff → Decision

L.
Latent-bearing invocation v1 fail-closed bypass KV reuse

M.
不做 Semantic KV Relay / CacheBlend / LMCache

N.
Batch 06 输出 reuse/residency/cost hint
交给 Batch 07 Scheduler
```

---

# 76. 最终目标图

```text
                         StateBus Runtime
                                │
                 ┌──────────────┴──────────────┐
                 │                             │
                 ▼                             ▼
         Semantic State Plane           Compute Reuse Plane
                 │                             │
     Semantic Selection                       │
                 │                             │
          Latent Handoff                      │
                 │                             │
          Decision State                      │
                 │                             │
                 └──────────────┬──────────────┘
                                │
                                ▼
                       InferenceInvocation
                                │
                                ▼
                    Runtime Authorization
                                │
                    ┌───────────┴───────────┐
                    │                       │
                    ▼                       ▼
             Representation            Reuse Policy
                Policy                     │
                    │              ┌────────┼────────┐
                    │              ▼        ▼        ▼
                    │          RECOMPUTE    APC   CONTINUATION
                    │              │        │        │
                    └──────────────┴────────┴────────┘
                                   │
                                   ▼
                              vLLM Engine
                                   │
                                   ▼
                          Observation / Proof
                                   │
                                   ▼
                         Reuse / Residency Hint
                                   │
                                   ▼
                          Batch 07 Scheduler
```

---

# 77. Source Truth Map

## StateBus Current Source

### Prefix / APC

- https://github.com/qcrs/os/blob/master/statebus/contracts/prefix.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/prefix_identity.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/neural_state.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/prefix_feedback.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/vllm_metrics.py
- https://github.com/qcrs/os/blob/master/statebus/benchmark/kv_prefix_schedule.py

### Adaptive Mainline

- https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_mainline.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_runtime.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_dispatcher.py
- https://github.com/qcrs/os/blob/master/statebus/integrations/llm.py

### Explicit KV

- https://github.com/qcrs/os/blob/master/statebus/contracts/engine_local_kv.py
- https://github.com/qcrs/os/blob/master/statebus/integrations/vllm_kv/connector.py
- https://github.com/qcrs/os/blob/master/statebus/integrations/vllm_kv/registry.py
- https://github.com/qcrs/os/blob/master/statebus/integrations/vllm_kv/role_client.py
- https://github.com/qcrs/os/blob/master/statebus/integrations/vllm_kv/middleware.py
- https://github.com/qcrs/os/blob/master/statebus/integrations/vllm_kv/worker_extension.py

---

# 78. External System / Paper References

## vLLM

### Automatic Prefix Caching

https://docs.vllm.ai/en/latest/design/prefix_caching/

### Prefix Cache Security / cache_salt

https://docs.vllm.ai/en/latest/usage/security/

### Renderer API

https://docs.vllm.ai/en/latest/serving/online_serving/renderer/

### KV Events

https://github.com/vllm-project/vllm/blob/main/vllm/distributed/kv_events.py

### Prefix Cache Core

https://github.com/vllm-project/vllm/blob/main/vllm/v1/core/kv_cache_utils.py

### prompt_embeds / external KV key issue

https://github.com/vllm-project/vllm/issues/42119

### KV key partitioning conformance RFC

https://github.com/vllm-project/vllm/issues/53194

---

## Agentic KV Management

### KVFlow

**KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows**

https://arxiv.org/abs/2507.07400

### Continuum

**Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache Time-to-Live**

https://arxiv.org/abs/2511.02230

### PBKV

**Efficient Serving for Dynamic Agent Workflows with Prediction-based KV-Cache Management**

https://arxiv.org/abs/2605.06472

### CacheScout

**Learning Agent Execution for KV-Cache Management in Agentic Serving**

https://arxiv.org/abs/2608.14624

### TOPAS

**TOPAS: Workflow-Aware Prefix-State Scheduling for Multi-Agent LLM Serving**

https://arxiv.org/abs/2608.25523

---

## KV Reuse Correctness

### ACL 2026

**When KV Cache Reuse Fails in Multi-Agent Systems: Cross-Candidate Interaction is Crucial for LLM Judges**

https://aclanthology.org/2026.acl-long.327/

---

## LMCache

https://docs.lmcache.ai/

当前仅作为后续可能的外部 KV data plane 参考；Batch 06 不接入。

---

# 79. 最后一段判断

StateBus 现在最不缺的是：

```text
再多一个 Feature
```

。

最缺的是：

# **把已经存在的机制收回统一 Runtime Contract。**

Batch 06 做完以后，项目的 Inference 层应该从：

```text
Prefix 实验
KV 实验
RolePath
Smoke
feature flags
private API
```

变成：

```text
Approved Logical Work
    ↓
Bound Provider
    ↓
InferenceInvocation
    ↓
Runtime-authorized Reuse Decision
    ↓
Backend Execution
    ↓
Observed Proof
```

这才是真正能够和前面：

```text
Task Authority
Planning
Evidence
Artifact
Protocol
Provider Binding
```

接起来的完整系统。

而下一批真正值得深入的问题，也会自然变成：

# **当 Runtime 同时拥有 DAG、reuse hint、residency、provider state 和资源状态时，它应该如何调度 READY steps。**

这正是 Batch 07。
