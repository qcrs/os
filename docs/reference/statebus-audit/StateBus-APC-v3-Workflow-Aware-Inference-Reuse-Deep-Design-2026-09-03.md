# StateBus APC v3：Workflow-Aware Inference Reuse 深度源码审计与重构设计

> 日期：2026-09-03  
> 审计仓库：`qcrs/os`  
> 审计分支：`master`  
> 审计基线提交：`8bfc6464ec236c0e121911095fc283129b0e7696`  
> 目标：在不 fork vLLM KV allocator、不把 APC 暴露给 Planner、不引入 benchmark oracle 的前提下，把现有 Engine-Local Prefix Reuse 从固定 RolePath / benchmark 专项能力升级为 Adaptive StateBus 的正式 Workflow-Aware Inference Reuse Policy。

---

## 0. 结论先行

当前 StateBus 的 APC 并不是“没有实现”，相反，**底层机制已经实现得相当完整，而且专项实验结果已经足够强**：

- canonical shared evidence prefix；
- token position 0 的共享 Prompt layout；
- stable-key / digest / visibility 约束；
- exact-token prefix identity；
- full-block alignment；
- vLLM APC 实际 query/hit counter 观测；
- cache-affinity benchmark scheduler；
- prediction-vs-observation feedback；
- 另外还存在一套完全不同的显式 Engine-Local KV Continuation。

真正的问题不是“APC 底层还不够快”，而是：

> **这些能力目前分散在 `run_smoke()`、`RolePathRunner`、`prefix_identity.py`、`neural_state.py`、continuous benchmark scheduler、metrics/feedback 和 engine-local KV sideband 中，没有成为 `AdaptiveMainline -> AdaptiveRuntimeEngine` 的统一 Runtime 决策面。**

因此本设计不建议重写 APC，也不建议去修改 vLLM 的 block hash / allocator / eviction。正确方向是：

```text
APC v3 = Workflow-Aware Inference Reuse
```

即把 StateBus 的职责定义为：

```text
StateBus：
- 判断哪些 Runtime-visible 状态可以进入公共 Prefix
- 判断哪些请求被授权共享同一 Prefix
- 生成 canonical prefix layout
- 证明真实 exact-token / full-block identity
- 为共享范围生成 cache namespace / cache_salt
- 在 ApprovedPlan 的 READY set 内做 cache-aware ordering
- 根据 residency / cost / future-use 决定 APC、普通 Prefill 或显式 continuation
- 记录 decision / observation / effect receipt

vLLM：
- 对完整 Token 序列进行 block hashing
- 创建 / 查询 / 引用 / 淘汰 KV block
- 实际执行 Prefix Cache hit
- 通过 KV Events / metrics 暴露可观测状态
```

最终目标主链：

```text
External/Canonical Task
        ↓
PlanSelector / Planner
        ↓
PlanPolicy
        ↓
ApprovedPlan
        ↓
AdaptiveRuntimeEngine
        ↓
READY SET
        ↓
WorkflowAwareReuseScheduler
        ↓
chosen step
        ↓
InferenceInvocationCompiler
        ├─ PromptContextBuilder
        ├─ ShareablePrefixCompiler
        ├─ Exact Prefix Boundary / Membership
        └─ ReuseNamespace / cache_salt
        ↓
InferenceReusePolicy
        ├─ RECOMPUTE
        ├─ APC_FULL_PROMPT
        └─ ENGINE_LOCAL_CONTINUATION   [conditional]
        ↓
LLM Provider / vLLM
        ↓
KV Events + Metrics + Runtime Outcome
        ↓
InferenceReuseReceipt / Cost Calibration
```

### 最重要的三个开发目标

1. **把 APC 接进 AdaptiveMainline / AdaptiveRuntime，而不是继续加固 smoke benchmark。**
2. **利用 ApprovedPlan DAG 做 ready-set / next-use-aware scheduling，这是 StateBus 相比普通 serving engine 真正独有的信息。**
3. **把“事后 APC 证明”升级为“事前 exact identity + 在线 observation”，并用 vLLM `cache_salt` 做授权边界。**

---

# 1. 本次源码审计范围

本次不是只读 APC 单文件，而是围绕“一个 Adaptive StateBus 请求如何真正到达模型”重新走了一遍链路。

## 1.1 StateBus 当前实现

重点阅读：

```text
statebus/contracts/prefix.py
statebus/runtime/prefix_identity.py
statebus/runtime/role_path.py
statebus/runtime/neural_state.py
statebus/runtime/vllm_metrics.py
statebus/runtime/prefix_feedback.py
statebus/runtime/smoke.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/llm_codeact.py
statebus/runtime/kv_budget.py
statebus/benchmark/kv_prefix_schedule.py
statebus/benchmark/continuous_runner.py
statebus/benchmark/adaptive_formal_mainline.py
statebus/integrations/llm.py
statebus/contracts/engine_local_kv.py
statebus/integrations/vllm_kv/role_client.py
statebus/integrations/vllm_kv/registry.py
statebus/integrations/vllm_kv/tokenizer_client.py
scripts/experiments/engine_local_kv/start_engine_local_kv_probe_service.sh
```

以及当前实现说明：

```text
docs/implementation/runtime/engine-local-prefix-reuse.md
docs/implementation/runtime/engine-local-kv-continuation.md
docs/implementation/runtime/model-state-paths.md
```

## 1.2 外部系统 / 论文参考

重点不是照抄，而是确认“哪些问题已经被 serving 系统证明真实存在”：

- vLLM Automatic Prefix Caching：hash-based full-block APC、`cache_salt`；
- vLLM KV Events：`BlockStored` / `BlockRemoved` / `AllBlocksCleared`；
- vLLM Renderer API：服务端权威 request -> token IDs preprocessing；
- SGLang RadixCache / LPM cache-aware scheduling；
- SGLang in-batch prefix warm-first 思路；
- SGLang session-aware radix cache；
- KVFlow：Agent Step Graph + steps-to-execution；
- Continuum：Agent tool gap 与 KV TTL；
- TOPAS：workflow critical path + prefix locality + aging。

---

# 2. 先把 StateBus 当前四类“模型状态”重新分清

当前仓库已经存在一份 `model-state-paths.md`，其核心划分是正确的：

| 路径 | StateBus 对象 | 目的 | 是否直接传 KV tensor |
|---|---|---|---|
| Embedding | `SemanticStateRef` | 检索 / 证据选择 | 否 |
| Logit | `LogitStateRef` / Gate Receipt | 候选授权 / Retry Gate | 否 |
| Prefix Reuse | canonical prefix / exact identity / observation | 多请求相同左前缀的 Prefill 复用 | 否，KV 留在 vLLM |
| Explicit KV Continuation | `EngineLocalKVHandle` / `KVForwardProof` | Producer -> Consumer 显式继承父序列 KV | 是，Worker 内部显式保存/加载 |

这四条线不能合并成“非文本状态”一个模糊概念。

尤其是 APC 与 KV Continuation：

```text
APC：
完整 logical prompt 仍发送给 vLLM
↓
vLLM 根据 token block hash 自动发现已有 KV
↓
命中则跳过相同完整 block 的 prefill

Continuation：
Producer 主动捕获某段 paged KV
↓
StateBus 得到 opaque handle
↓
Consumer 发送 handle + suffix
↓
Worker 显式把 KV 注入 Consumer slots
```

所以本设计中的“统一”只发生在：

```text
InferenceReusePolicy
```

也就是统一**决策面 / 成本面 / 审计面**，而不是把 APC 与 continuation 的数据面实现混为一套。

---

# 3. 当前 Engine-Local Prefix Reuse：源码级主链

## 3.1 `prefix.py`：当前 Contract 实际比表面成熟

当前 `statebus/contracts/prefix.py` 不是一个 toy contract。

已经有四类重要对象：

```text
CanonicalPrefixEntry
CanonicalSharedEvidencePrefix
ExactTokenPrefixIdentity
PrefixReuseIntentV2
PrefixObservationV2
```

其中最值得注意的是 `PrefixReuseIntentV2`。

它已经绑定：

```text
trace_id / task_id / step_id / request_id
participant_role
engine_instance_id
cache_namespace
cache_epoch
model_id / model_revision / weights_digest
tokenizer_id / tokenizer_revision
chat_template_sha256
template_kwargs_sha256
prefix_layout_version
normalizer_version
source_doc_hashes
evidence_pack_hash
hydrate_manifest_hash
authorized_common_keys_digest
visibility_policy_version
shared_prefix_text_sha256
exact_token_ids_sha256
exact_token_count
full_block_token_count
block_size
message_shape_digest
adapter_digest
multimodal_digest
cache_salt_digest
rope_config_digest
kv_cache_dtype
quantization_digest
tensor_parallel_size
pipeline_parallel_size
dependency_ids
ready_set_epoch
schedule_priority
lease_expires_at_ns
```

这意味着：

> 当前 APC 的最大问题不是“没有合同”，而是这些合同没有进入 Adaptive Runtime 的真实 dispatch lifecycle。

因此 R0 不应再造一套完全重复的 Prefix contract，而应：

- 保留 `CanonicalPrefixEntry` 的 stable identity；
- 保留 exact token/full-block proof；
- 保留 engine/model/tokenizer/template/cache epoch identity；
- 保留 observation fail-closed 语义；
- 将固定 role participant 泛化成 Adaptive step / inference invocation participant；
- 增加 reuse scope / namespace / mechanism decision；
- 把 contract 从“smoke 事后 audit 对象”变成“dispatch 前控制对象”。

---

# 4. Canonical Shared Prefix：当前算法做对了什么

`build_canonical_shared_evidence_prefix()` 当前完成：

1. participant 唯一性校验；
2. role 内 stable key 唯一性校验；
3. 多 role stable-key intersection；
4. 同 stable key 的 `entry_digest` 一致性校验；
5. 稳定排序；
6. canonical JSON-line rendering。

这几项应该保留，因为它们同时解决：

```text
语义可共享性
+ 可见性授权
+ 内容一致性
+ deterministic rendering
```

当前 canonical entry 的 identity 不是“文本看起来一样”，而是：

```text
source_doc_hash
+ locator
+ evidence_kind
+ rendered content digest
```

这比简单 `prompt.startswith()` 强得多。

## 4.1 当前最大限制：participant 是固定角色语义

现在 `PrefixParticipantRole` 只有：

```text
executor
summarizer
```

同时 `build_canonical_shared_evidence_prefix()` 默认 participant 也是 Executor + Summarizer。

这和旧固定 RolePath 完全一致，但和 Adaptive Plan 不一致。

Adaptive Plan 以后可能是：

```text
Retriever
  ├─ Executor-1
  ├─ Executor-2
  └─ Verifier
        ↓
     Composer
```

甚至：

```text
Retriever
   ↓
Executor
```

根本没有 Summarizer。

所以 **Prefix participant 必须从 role enum 改成 inference invocation identity**。

建议未来核心 identity：

```python
InferenceParticipantId = str   # normally step_id + invocation ordinal
```

role 只是 metadata：

```python
participant_id="analysis-2:llm-1"
step_id="analysis-2"
role="executor"
```

而不是让 `role` 决定是否可以进入 APC。

---

# 5. Prompt Layout：当前实现真正如何制造 APC 命中

当前 `RolePathRunner` 最关键的不是 vLLM 参数，而是：

```text
compile_prefix_layout()
```

共享模式把 Prompt 编译成：

```text
<statebus-shared-prefix-v2>
CANONICAL COMMON EVIDENCE
</statebus-shared-prefix-v2>

<statebus-role-suffix-v2 role="executor">
ROLE-SPECIFIC INSTRUCTION
ROLE-SPECIFIC PAYLOAD
</statebus-role-suffix-v2>
```

Summarizer：

```text
<statebus-shared-prefix-v2>
SAME CANONICAL COMMON EVIDENCE
</statebus-shared-prefix-v2>

<statebus-role-suffix-v2 role="summarizer">
DIFFERENT ROLE SUFFIX
</statebus-role-suffix-v2>
```

因此真正被 vLLM APC 利用的是：

```text
Token position 0
开始的一段完全相同 Token block chain
```

不是“StateBus 传了一个 KV Ref”。

## 5.1 这也是为什么 APC 是 Prompt Compiler 问题

vLLM APC 本身已经会：

```text
hash full block
lookup cached block
reuse or compute
```

如果 StateBus 把角色差异放在 token 0：

```text
Executor system prompt ...
```

和：

```text
Summarizer system prompt ...
```

那么后面即使都有同一 5000-token 文档：

```text
第一个 block 已经不同
→ chained prefix hash 全部分叉
→ 共享文档无法作为共同 cache chain
```

所以 StateBus 的核心价值是：

```text
把最稳定、最广泛共享、被共同授权的内容尽量向左组织
```

而不是修改 vLLM cache manager。

---

# 6. 当前 Prompt 去重还有一个实际可优化点

当前 `compile_prefix_layout()` 会尝试从 suffix 删除已经放进共享 Prefix 的 Evidence，但现有逻辑主要依赖：

```text
整个 evidence text == shared_prefix_text
```

如果角色 Evidence 是：

```text
Executor: A B C D
Summarizer: A B C D E F
```

公共 Prefix 是：

```text
A B C D
```

Summarizer 原 evidence block 仍然可能包含：

```text
A B C D E F
```

因为它不是“整个字符串完全等于”公共 Prefix。

这样会出现：

```text
Prefix: A B C D
Suffix: A B C D E F
```

其中 A/B/C/D 被重复送入模型。

### 建议：stable-key subtraction

在 R1 内做：

```text
RoleVisibleEntries
-
SelectedSharedEntries
=
RoleSpecificSuffixEntries
```

例如：

```text
Executor suffix evidence = ∅
Summarizer suffix evidence = E F
```

最终：

```text
Prefix A B C D
+ Summarizer-specific E F
```

这项优化：

- 不改变证据权限；
- 不改变事实集合；
- 不依赖 benchmark；
- 直接减少 token duplication；
- 可以让 shared layout 本身的 prompt bytes 真正下降，而不仅仅依赖 APC 命中。

必须通过现有 quality / JSON contract 回归。

---

# 7. Exact Token Identity：当前实现很正确，但处在错误时间点

当前 `compile_exact_token_prefix_identity()` 做了很重要的一件事：

```text
不是比较字符串
而是：
真实 tokenizer
+ chat template
+ actual rendered prompts
+ sentinel suffix
+ longest common prefix
+ block alignment
```

它最终得到：

```text
exact_token_ids
exact_token_count
full_block_token_count
```

并且：

```text
full_block_token_count % block_size == 0
```

才能形成可复用完整 block。

这是正确的。

## 7.1 但当前它主要是“事后证明”

现有 `smoke.py` 流程是：

```text
先实际调用 Executor/Summarizer
↓
RolePathRunner 把 rendered request 写 audit
↓
smoke.py 再读取 rendered request
↓
compile exact-token identity
↓
写 prefix_cache_observation
```

这说明当前 Exact Identity 能回答：

```text
“刚才这两个请求事实上共享了多少完整 Token block？”
```

但无法在请求发送前回答：

```text
“这次到底应该启用 APC layout 吗？”
```

所以它目前是：

```text
Evidence / Audit Plane
```

不是：

```text
Runtime Decision Plane
```

这是 APC v3 必须修的核心问题。

---

# 8. Exact Identity 应拆成“边界证明 + 单请求成员证明”

当前函数需要一次拿到多个 participant prompts 才计算 LCP。

这对 fixed Executor/Summarizer 没问题，但 Adaptive Runtime 有一个现实问题：

> 后续某个 step 的完整 Prompt 可能要等上游 Artifact 真正产生后才知道。

因此不能要求 Plan 批准时就拥有所有 future full prompts。

建议把 exact identity 拆成两层。

## 8.1 `CanonicalPrefixTokenBoundary`

仅对共享 Prefix 本身证明：

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

做法仍然可复用当前 sentinel 思想：

```text
shared envelope + sentinel A
shared envelope + sentinel B
↓
LCP
↓
找到不会被 suffix tokenization 影响的稳定边界
↓
向下对齐 full block
```

这一步不需要真实 future role suffix。

## 8.2 `RequestPrefixMembership`

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

检查：

```text
真实 request token IDs
是否以前缀 boundary token IDs 开始
```

这样：

```text
Plan 时：知道候选 Prefix
↓
PromptContext ready 时：知道 canonical boundary
↓
真正发送请求前：证明当前 request 是该 group 的合法 member
```

这比“等所有请求完成以后再做一次 LCP”更适合 Adaptive Runtime。

---

# 9. Tokenization Authority：当前路径和未来路径

当前 APC 通过本地 tokenizer + `apply_chat_template()` 进行 exact identity；显式 KV continuation 又已经有 `VllmTokenCodec`，通过 vLLM `/tokenize` 对私有 raw prompt 进行分词。

未来有三个层级：

## 9.1 当前兼容路径

继续使用：

```text
pinned tokenizer
pinned tokenizer revision
pinned chat template
pinned template kwargs
```

并绑定：

```text
weights_digest
tokenizer_digest
chat_template_sha256
template_kwargs_sha256
```

这些字段 `PrefixReuseIntentV2` 已经有。

## 9.2 更强的服务端验证

现代 vLLM 已提供 renderer / tokenizer metadata 能力。

未来可优先使用：

```text
/v1/chat/completions/render
```

让 vLLM 自己把完整 ChatCompletionRequest 渲染成最终 token IDs。

优点：

```text
StateBus 判断的 token IDs
==
vLLM 真实生成请求使用的 token IDs
```

避免：

```text
本地 tokenizer config
和
server-side chat-template
微小漂移
```

但这应是 modern backend capability，不应作为 R1 前置条件。

## 9.3 Capability discovery

建议增加：

```python
@dataclass(frozen=True)
class InferenceBackendCapabilities:
    supports_apc: bool
    supports_cache_salt: bool
    supports_render_api: bool
    supports_kv_events: bool
    supports_prefix_metrics: bool
    supports_explicit_continuation: bool
```

Runtime 不猜版本：

```text
支持 → 使用
不支持 → fallback / UNKNOWN
```

---

# 10. `neural_state.py`：当前 APC control-plane 模型的问题

当前：

```text
DEFAULT_NEURAL_REUSE_SCOPE = task_session
```

同时 `EngineLocalPrefixRegistry` key 包含：

```text
engine_id
cache_namespace
cache_epoch
session_id
prefix_hash
model_id
tokenizer_id
chat_template_sha256
template_kwargs_sha256
```

这个 registry 作为实验 bookkeeping 没问题，但它造成：

```text
StateBus metadata 认为：
不同 session = 不同 handle

而 vLLM APC：
只要完整 block hash + extra key 兼容，实际上可以跨 request / task reuse
```

于是 StateBus 的控制面 scope 比 serving engine 的实际能力更窄。

---

# 11. 引入正式 `ReuseScope` 与 `ReuseNamespace`

建议：

```python
class ReuseScope(StrEnum):
    TASK = "task"
    SESSION = "session"
    CORPUS = "corpus"
    TRUST_DOMAIN = "trust_domain"
```

含义：

| Scope | 允许共享范围 | 典型场景 |
|---|---|---|
| TASK | 单个 Task 内 | Executor -> Summarizer |
| SESSION | 同一 workflow / conversation | 多轮 Agent |
| CORPUS | 同一公共 Corpus | 多任务查询同一报告 / repo |
| TRUST_DOMAIN | 同一 tenant / trust boundary | 公共 system/tool/runtime prefix |

再生成：

```python
@dataclass(frozen=True)
class ReuseNamespace:
    scope: ReuseScope
    principal_digest: str
    policy_version: str
    cache_salt_digest: str
```

### 11.1 `cache_salt` 不应直接等于 task/corpus 名字

建议真实传给 vLLM：

```text
cache_salt = HMAC(
    runtime_secret,
    scope_kind || principal_identity || policy_version
)
```

StateBus audit 只存：

```text
cache_salt_digest
```

不持久化 salt 明文。

理由：

- 相同授权域稳定命中；
- 不同授权域 block hash 天然分叉；
- 不把 tenant/corpus semantic identifier 暴露进 inference request；
- 和 vLLM 当前 cache-salt security model 对齐。

---

# 12. ReuseScope 必须是 Runtime Authorization，不是 Planner Choice

不能出现：

```text
Planner:
  use_apc=true
  reuse_scope=trust_domain
```

原因：

```text
APC 是物理计算复用
共享范围是数据安全授权
```

两者都不属于模型自由决策。

正确来源：

```text
TaskContract / Public Visibility
        +
StateBus Trust Policy
        +
Artifact/Evidence visibility
        ↓
ReuseAuthorizationPolicy
        ↓
ReuseNamespace
```

Planner 只决定：

```text
语义目标 / capability plan
```

Runtime 决定：

```text
如何低成本执行这个已经批准的逻辑计划
```

这和已有 StateBus 原则一致：

```text
Agents propose
Runtime authorizes / executes / validates / commits
```

---

# 13. Benchmark Boundary：生产 APC 绝不能吃 `kv_probe_corpus_group`

当前 `statebus/benchmark/kv_prefix_schedule.py` 会从 benchmark sample 中拿：

```text
kv_probe_corpus_group
dataset_id
document_path
intent_op
```

构造 affinity hint。

这在受控机制实验里合理，但不能进入 product runtime。

否则变成：

```text
Benchmark 自己告诉 Runtime：
“这几个 task 应该命中同一缓存组”
```

那就不能证明 general runtime detection。

正式 Runtime 的 affinity 必须只来自：

```text
PUBLIC / RUNTIME AUTHORITATIVE
```

例如：

```text
InputAssetRef.content_digest
CanonicalEvidencePack source hashes
verified ArtifactRef lineage
public session identity
public trust-domain identity
runtime provider identity
```

禁止：

```text
benchmark family
case category
scenario tag
expected metric effect
gold answer
hidden evaluator
kv_probe_corpus_group
```

这一条必须沿用现有 Benchmark Visibility Boundary。

---

# 14. 当前 `estimate_engine_local_prefix_reuse()` 为什么只能做粗筛

当前 estimator：

```text
estimated_tokens = ceil(shared_prefix_bytes / 4)
```

并假设：

```text
第一个 consumer miss
后续 consumer hit
```

它适合：

```text
early planning / benchmark estimate
```

不适合：

```text
AUTO Runtime final decision
```

因为：

- 中文 / JSON / path / number tokenization 比例不同；
- chat template 会额外引入 tokens；
- only-full-block 约束；
- prefix 可能已 resident，也可能已 evicted；
- participant 数量不一定都真正执行；
- dynamic branch 可能不走。

因此保留它，但降级为：

```text
Stage A: Approximate Benefit Screening
```

最终权威输入改为：

```text
Stage B: Exact Full-Block Identity
```

---

# 15. 当前 APC 命中观测：做得很严谨，但不等于 residency

`vllm_metrics.py` 已经做了很多正确保护：

```text
counter alias validation
query/hit label matching
monotonic delta
counter reset detection
hit <= query
engine/cache identity
exclusive interval
pollution flag
retry count
```

`PrefixObservationV2` 甚至要求：

```text
exclusive_interval = true
pollution_detected = false
retry_count = 0
```

才能宣称：

```text
OBSERVED_HIT / OBSERVED_MISS
```

这是好设计，应保留。

但 `/metrics` 回答的是：

```text
“刚才这个观察窗口发生了多少 query/hit token？”
```

它并不能告诉 Runtime：

```text
“Prefix X 现在仍然 resident 吗？”
```

所以：

```text
metrics = observation / calibration
```

不能继续承担：

```text
residency database
```

---

# 16. 现代 vLLM KV Events：更适合 `PrefixResidencyIndex`

现代 vLLM 已公开：

```text
BlockStored
BlockRemoved
AllBlocksCleared
```

`BlockStored` 暴露的信息包括：

```text
block_hashes
parent_block_hash
token_ids
block_size
extra_keys
medium
cache-spec metadata
locality
ownership
```

其中 `extra_keys` 可包含：

```text
cache_salt
LoRA
multimodal identity
prompt embedding identity
...
```

这比 task-level `/metrics` 更适合做 control-plane residency mirror。

---

# 17. `PrefixResidencyIndex` 设计

注意：这个 Index **不存 KV tensor**。

只存 control-plane metadata：

```python
class ResidencyState(StrEnum):
    UNKNOWN = "unknown"
    GPU_RESIDENT = "gpu_resident"
    HOST_RESIDENT = "host_resident"
    STORAGE_RESIDENT = "storage_resident"
    EVICTED = "evicted"

@dataclass(frozen=True)
class PrefixResidencyRecord:
    engine_instance_id: str
    cache_epoch: str
    namespace_digest: str
    prefix_group_id: str

    exact_prefix_token_digest: str
    expected_full_blocks: int
    observed_resident_blocks: int

    block_hashes: tuple[str, ...]
    parent_chain_digest: str

    state: ResidencyState
    medium: str
    observation_source: str

    last_store_ns: int
    last_remove_ns: int
    last_refresh_ns: int
```

### 17.1 必须 fail-closed

KV event consumer 如果：

```text
丢事件
重连
cache epoch 变化
publisher replay 不完整
block chain 映射不确定
```

不能说：

```text
WARM
```

必须：

```text
UNKNOWN
```

AUTO Policy 在 UNKNOWN 时仍可发送完整 prompt：

```text
APC 可能 hit，也可能普通 prefill
```

但不能把 UNKNOWN 计成 guaranteed cache hit。

---

# 18. vLLM `cache_salt`：StateBus 可以直接利用的安全能力

现代 vLLM APC 的 block key 由：

```text
parent block hash
block token IDs
extra hashes
```

组成。

`cache_salt` 会进入第一个 block identity，因此不同 salt 的请求后续整个 chained hash 都分叉。

这正好把：

```text
StateBus authorization
```

映射成：

```text
vLLM cache isolation
```

即：

```text
ReuseScope / Trust Policy
        ↓
ReuseNamespace
        ↓
cache_salt
        ↓
vLLM block hash namespace
```

这是 APC v3 很值得做的一点，因为它不只是性能优化，也把：

```text
“谁可以共享计算结果”
```

变成一个 Runtime policy。

---

# 19. 当前 `LLMClient` 协议无法承载动态 APC metadata

当前 `statebus/integrations/llm.py` 的 `LLMClient.complete()` 大致只有：

```python
complete(
    messages,
    purpose,
    temperature=None,
    response_schema=None,
)
```

没有：

```text
request_id
cache_salt
prefix intent
reuse decision
engine affinity
```

虽然 `RoleLLMConfig` 有 `extra_body` / `request_kwargs`，但它们是静态 role config，不适合：

```text
Task A → salt X
Task B → salt Y
```

这种 per-request authorization。

所以 R1 需要一个正式 inference request context。

---

# 20. 推荐新增 `InferenceInvocationContext`

```python
@dataclass(frozen=True)
class InferenceInvocationContext:
    trace_id: str
    task_id: str
    step_id: str
    attempt_id: str
    request_id: str

    provider_id: str
    engine_instance_id: str

    reuse_mode: str
    reuse_namespace: ReuseNamespace | None
    prefix_group_id: str = ""
    prefix_intent_id: str = ""

    cache_salt: str = ""        # in-memory only
    cache_salt_digest: str = ""

    schedule_epoch: int = 0
    metadata: Mapping[str, object] = field(default_factory=dict)
```

然后扩展：

```python
LLMClient.complete(..., invocation_context=None)
```

### provider 行为

```text
DeepSeek/API backend:
- 不支持 StateBus engine-local APC
- 不发送 cache_salt
- reuse mechanism = RECOMPUTE / remote-provider-native-unknown

local_vllm backend:
- capability says supports_cache_salt
- 把 cache_salt 注入 vLLM request body
- 绑定 request_id / telemetry
```

不要把 vLLM-specific 参数硬编码进所有 capability handler。

---

# 21. 更重要：Adaptive Runtime 目前没有统一“Inference Invocation”层

这是本轮源码审计后比上一版更明确的结论。

Adaptive Dispatcher 目前执行的是：

```text
RETRIEVAL_ADAPTER
TRANSFORM_DSL
LLM_BOUNDED_PYTHON
RUNTIME_BUILTIN
```

但“LLM_BOUNDED_PYTHON”内部真正生成代码时，`code_source_factory` 仍是 caller 提供的函数；formal mainline 中甚至直接自己创建 local-vLLM client 完成代码生成。

也就是说：

```text
AdaptiveRuntimeEngine
知道 step

AdaptiveCapabilityDispatcher
知道 capability

但是模型请求本身
仍可能从外部 factory 直接发出去
```

这会导致 APC、logit、request identity、cache salt、provider telemetry 难以统一。

### 建议增加一层：`RuntimeInferenceInvoker`

```text
Adaptive Capability
      ↓
needs model inference
      ↓
RuntimeInferenceInvoker
      ├─ compile prompt
      ├─ attach InvocationContext
      ├─ evaluate ReusePolicy
      ├─ dispatch provider
      └─ emit receipt
```

它不是 Agent。

它是 Runtime-owned inference data plane adapter。

---

# 22. `RuntimeInferenceInvoker` 应覆盖哪些调用

第一阶段只收敛当前 local-vLLM 重要调用：

```text
CodeAct code generation
CodeAct repair generation
Claim / cited report composition
未来 generic executor/provider LLM
```

Planner 暂时可以留在 PlanSelector 之前：

```text
Task -> Planner -> ApprovedPlan
```

因为 workflow-aware future-use 必须等 ApprovedPlan 后才存在。

Planner 未来可以使用：

```text
cross-task corpus APC
```

但不是 R1 的必要范围。

---

# 23. AdaptiveMainline：APC 应该在哪里接入

当前 `AdaptiveMainlineRunner.run()`：

```text
build StateStore
build MemoryStore
build Workspace
↓
_assemble_plan()
↓
AdaptiveDispatchContext
↓
AdaptiveRuntimeRequest
↓
AdaptiveRuntimeEngine.run()
```

建议加入：

```text
_assemble_plan()
↓
ApprovedPlan
↓
build InferenceReuseContext
↓
AdaptiveDispatchContext.inference_reuse_context
AdaptiveRuntimeRequest.reuse_scheduler
↓
AdaptiveRuntimeEngine
```

## 23.1 新 `InferenceReuseContext`

```python
@dataclass
class InferenceReuseContext:
    mode: InferenceReuseMode
    backend_capabilities: InferenceBackendCapabilities
    namespace_policy: ReuseNamespacePolicy
    prefix_compiler: ShareablePrefixCompiler
    exact_identity_compiler: ExactPrefixIdentityCompiler
    decision_policy: InferenceReusePolicy
    residency_index: PrefixResidencyIndex
    cost_model: InferenceReuseCostModel
    invoker: RuntimeInferenceInvoker

    prefix_groups: dict[str, PrefixReuseGroup]
    decisions: dict[str, InferenceReuseDecision]
    receipts: list[InferenceReuseReceipt]
```

这个 Context 属于 Runtime，不属于 Planner output。

---

# 24. AdaptiveRuntimeEngine：真正干净的 scheduler seam 已经存在

当前核心 loop：

```text
remaining = unfinished steps
↓
ready = dependency subset completed
↓
sorted(ready, key=step_id)
↓
逐个执行
```

这意味着最好的插入点非常清晰：

```text
READY SET 构造之后
Grant 之前
```

因为此时：

- Plan 已批准；
- dependencies 已满足；
- step 仍未获得本次 attempt Grant；
- Runtime 可以安全决定“先执行哪个 ready step”；
- 但绝不能添加/删除语义 step。

---

# 25. 不建议只把 `sorted()` 换成另一个 sort key

更好的改法是把当前：

```python
for step in sorted(ready, key=lambda x: x.step_id):
    execute(step)
```

改成：

```python
ready = compute_ready(...)
chosen = scheduler.choose_next(
    ready=ready,
    runtime_state=...,
)
execute(chosen)
continue
```

也就是：

```text
每完成一个 step
↓
重新计算 ready set
↓
重新读取最新 residency / warmed prefix / DAG state
↓
再选下一步
```

原因：

假设：

```text
A Prefix X
B Prefix X
C Prefix Y
```

开始时 X cold。

执行 A 后：

```text
X 可能已经 warm
```

如果 ready ordering 是在 A 前一次性排完：

```text
A C B
```

就错过了：

```text
A -> B
```

这个新状态。

所以 APC-aware scheduler 应是：

```text
choose-one → execute → observe → choose-one
```

而不是一次性全排序。

---

# 26. `WorkflowAwareReuseScheduler` 的硬边界

Scheduler 只能：

```text
从当前 READY SET 里选一个
```

不能：

```text
跨 dependency
提前执行 blocked step
增加 role
删除 role
替换 capability
修改 completion criteria
```

所以它不是 Router，也不是 Replanner。

正确职责：

```text
PlanSelector      → 选逻辑 Plan 来源
Planner           → 产生语义 DAG
PlanPolicy        → 批准语义 DAG
ExecutionBinding → 选 physical provider
ReuseScheduler    → 在已 ready 的合法 step 中选执行顺序
```

---

# 27. 不是所有 Adaptive Step 都应该参与 APC scheduling

READY set 可能同时包含：

```text
retrieval
DSL transform
LLM code generation
builtin validation
claim composition
```

APC 只对真正需要同一 local-vLLM 进行 Prefill 的 invocation 有意义。

所以每个 ready step 需要一个：

```python
@dataclass(frozen=True)
class StepInferenceProfile:
    step_id: str
    has_inference: bool
    provider_id: str
    engine_instance_id: str
    prefix_group_id: str
    estimated_prompt_tokens: int
    exact_reusable_full_block_tokens: int
    next_consumer_count: int
```

### R2 第一版建议非常保守

只在：

```text
多个 ready step
AND
都使用同一个 local-vLLM engine
AND
至少一个合法 prefix affinity
```

时重排。

否则沿用：

```text
step_id stable order
```

这样不会为了 APC 大规模改变 Runtime 行为。

---

# 28. Scheduler Score：第一版不要只看 hit tokens

只做：

```text
score = matched_prefix_tokens
```

会产生 starvation / critical-path regression。

建议：

\[
Score(s)
= \alpha B_{resident}
+ \beta B_{warm}
+ \gamma U_{critical}
+ \delta A_{age}
- \lambda C_{delay}
\]

其中：

## 28.1 `B_resident`

如果 residency 已证明 GPU resident：

```text
exact reusable full-block tokens
× calibrated prefill value
```

## 28.2 `B_warm`

执行当前 step 后，有多少近期 downstream inference 可以复用本次前缀。

例如：

```text
Executor
↓
CodeAct
↓
Summarizer
```

Executor 的 Prefix X 虽然当前 cold，但它执行后会 warm X，Summarizer 很快需要 X。

## 28.3 `U_critical`

当前 step 是否在 ApprovedPlan 剩余 critical path 上。

第一版不需要精确 JCT predictor，可用：

```text
remaining longest-path depth
```

作为 urgency proxy。

## 28.4 `A_age`

等待越久，优先级逐渐提高。

避免 cache-hot request 无限压住 cache-cold request。

## 28.5 `C_delay`

为了 cache locality 推迟当前 step 的预计代价。

---

# 29. StateBus 真正独有的优势：ApprovedPlan 直接提供 Future Use

普通 vLLM/SGLang scheduler 主要看到：

```text
当前 waiting queue
当前 cached prefix
```

StateBus 额外知道：

```text
ApprovedPlan DAG
```

所以可以知道：

```text
当前 Executor 完成后
还有 Summarizer

当前 Executor 完成后
还有 Verifier -> Summarizer

某个 Prefix 下一次可能在几步以后再次使用
```

这正是 KVFlow 所谓的：

```text
workflow-aware future activation
```

但 StateBus 不需要额外“猜一个 Agent Step Graph”：

```text
ApprovedPlan 本身就是合法 Runtime DAG
```

这是最值得利用的地方。

---

# 30. `NextUsePrediction`：不要一开始做机器学习

第一版完全可以 deterministic：

```python
@dataclass(frozen=True)
class PrefixNextUseEstimate:
    prefix_group_id: str
    current_step_id: str
    next_consumer_step_ids: tuple[str, ...]
    min_dag_distance: int
    max_dag_distance: int
    ready_consumer_count: int
    blocked_consumer_count: int
    expected_tool_gap_ms: float = 0.0
```

`min_dag_distance`：

```text
当前完成后最少还要多少个 Runtime step 才可能再次消费
```

无需神经网络。

---

# 31. Tool Gap：StateBus APC 很值得利用的一个场景

典型：

```text
Executor LLM
    ↓
CodeAct / Tool
    ↓
Summarizer LLM
```

中间：

```text
CPU Python
filesystem
DB
shell sandbox
retrieval
```

可能花数百 ms 到几秒。

这期间 vLLM 并不知道：

```text
“这个 Executor 的 Prefix 很快还会被 Summarizer 用。”
```

但 StateBus 知道：

```text
ApprovedPlan:
Executor -> CodeAct -> Summarizer
```

所以第一阶段不必 pin KV，只做：

```text
Summarizer READY 后
优先执行与刚刚 warm prefix 相同的请求
```

后续如果真实 residency + concurrency 证明需要，再考虑：

```text
TTL / pin / prefetch
```

当前不要改 vLLM eviction。

---

# 32. 当前 `DependencyAwarePrefixScheduler` 应该怎么复用

现有 benchmark scheduler 已经有：

- dependency validation；
- cycle detection；
- ready task selection；
- warmed affinity；
- adaptive affinity score；
- priority；
- estimated prefix tokens。

不要删。

但建议拆成两层：

```text
statebus/runtime/inference_reuse/scheduler.py
    ↓
通用 Runtime ready-set algorithm

statebus/benchmark/kv_prefix_schedule.py
    ↓
只负责把受控 benchmark manifest 转成实验 hint
```

生产 Runtime **绝不能 import benchmark module**。

---

# 33. Prefix Group：上一版“多个 group”需要更严格地定义

上一版为了说明动态角色，举过：

```text
G1: Executor-A + Summarizer
G2: Executor-B + Summarizer
G3: Verifier + Summarizer
```

这里需要进一步严格化：

> 一个具体 Summarizer invocation 只有一个 Token 0，只能使用一种最终 Prefix layout。

所以它不能在同一次调用里同时：

```text
以 G1 开头
又以 G2 开头
```

因此必须区分：

```text
Candidate Group
vs
Selected Prefix Assignment
```

---

# 34. 推荐 `PrefixReuseGroupCandidate`

```python
@dataclass(frozen=True)
class PrefixReuseGroupCandidate:
    group_id: str
    participant_invocation_ids: tuple[str, ...]
    participant_step_ids: tuple[str, ...]

    shared_entry_keys: tuple[str, ...]
    shared_ref_ids: tuple[str, ...]
    canonical_prefix_digest: str

    visibility_commitment_digest: str
    reuse_namespace_digest: str

    approximate_prefix_tokens: int
    predicted_execution_count: int
    predicted_reuse_count: int

    estimated_benefit_score: float
```

Runtime 可以生成多个 candidate，但最终：

```text
每个 invocation 至多选择一个 active prefix assignment
```

---

# 35. R1 不要做复杂 group optimization

候选 group 组合可能变成 set-packing / prefix-tree optimization。

现在没有必要。

第一版：

```text
每个 workflow
只选一个收益最大的 multi-invocation shared group
```

或者更保守：

```text
只支持一个 producer + immediate downstream LLM consumer
```

例如：

```text
Executor -> Summarizer
```

但 participant contract 本身不写死角色。

等真实 workload 证明需要，再做 hierarchical prefix layout。

---

# 36. 高级形态应该是 `PrefixReuseTree`，不是任意 flat groups

例如：

```text
            Base Evidence A B
             /            \
        + C D              + E
        /   \                 \
      E1     S                E2
```

这里：

- E1 与 S 共享更长 `A B C D`；
- E2 只共享 `A B E` 分支；
- 所有请求可以在 base `A B` 形成 radix hierarchy。

这和 vLLM/SGLang 的 prefix tree 更一致。

但这是 R4/P2，不是当前必要工作。

---

# 37. `InferenceReuseMode`：正式替代散落 env flag 的控制语义

当前：

```text
STATEBUS_PREFIX_ALIGNMENT_MODE=independent|shared_evidence_prefix
STATEBUS_PREFIX_POLICY=off|observe|on
STATEBUS_ENGINE_LOCAL_KV_MODE=off|full_replay|continuation
```

这些 flag 对实验很方便，但产品 Runtime 语义分散。

建议统一一个上层模式：

```python
class InferenceReuseMode(StrEnum):
    OFF = "off"
    OBSERVE = "observe"
    AUTO = "auto"
    FORCE_EXPERIMENT = "force_experiment"
```

含义：

## OFF

```text
完全不改变请求 layout / ordering
```

## OBSERVE

```text
构造 candidate
计算 exact identity
计算 predicted benefit
读取 residency

但是：
不改 Prompt
不改 ready order
不发 cache_salt based sharing change
```

用于 shadow validation。

## AUTO

```text
只有通过 authorization + exact identity + benefit gate
才启用 shared prefix / scheduling
```

## FORCE_EXPERIMENT

```text
用于受控 A/B
```

强制 shared / independent / continuation 等 mechanism，但仍不能绕过 correctness gate。

---

# 38. 统一 `InferenceReusePolicy`：APC 与 Continuation 放在同一决策面

建议 mechanism：

```python
class ReuseMechanism(StrEnum):
    RECOMPUTE = "recompute"
    APC_FULL_PROMPT = "apc_full_prompt"
    ENGINE_LOCAL_CONTINUATION = "engine_local_continuation"
```

未来再加：

```text
OFFLOAD_RESTORE
REMOTE_KV
```

不是现在。

---

# 39. 为什么 Explicit KV Continuation 不应该默认优先于 APC

当前专项实验已经说明两者成本差别很大。

Prefix Reuse 实验：

```text
block hit rate: 0% -> 78.016%
全部请求平均 TTFT: -68.7%
全部请求端到端: -43.0%
warm reuse TTFT: 约 -88.3%
```

而显式 KV Continuation：

```text
4,096-token handle ≈ 1 GiB
store p50 ≈ 1.713 s
load p50 ≈ 0.297 s
Consumer TTFT: -61.62%
完整主链 wall: -5.69%
```

这说明：

```text
APC：
几乎没有 Producer 侧显式保存成本
但 residency 不由 StateBus 保证

Continuation：
StateBus 可以显式控制 lifetime / load
但 capture/store 成本和 host memory 很高
```

因此当前最合理的 policy 是：

```text
优先 APC
↓
若 exact prefix 不适用 / residency 风险高 / tool gap 特别长
且 continuation 已有合法 handle、成本模型为正
↓
才考虑 continuation
```

而不是：

```text
有 handle 就永远 continuation
```

---

# 40. 当前 Continuation 实现也暴露了为什么它不能直接接 Adaptive Runtime

`EngineLocalKVRoleClient` 当前内部持有：

```text
_parent_token_ids
_handle_id
```

而且逻辑固定：

```text
role == executor → produce
role == summarizer → consume
其他 role → delegate
```

这意味着它天然假设：

```text
单 Task
单 Executor producer
单 Summarizer consumer
严格相邻的 logical pair
```

它不支持：

```text
Executor-1 / Executor-2 并行
多个 Consumer
动态 role omission
跨 task handle
多 outstanding handles
```

因此 continuation 也应该以后从：

```text
stateful RoleClient wrapper
```

升级成：

```text
Runtime-owned ContinuationHandleRegistry + InferenceReusePolicy
```

但这不是 APC-R1 的前置工作。

---

# 41. 当前 WorkerKVRegistry：可以保留，但用途要清楚

当前 registry 已有：

```text
PREPARING
READY
CONSUMING
CONSUMED
RELEASED
EXPIRED
INVALIDATED
```

以及：

```text
max_entries
max_bytes
TTL
one_shot
capacity eviction
layer completeness
forward proof
```

这是一个很不错的 bounded explicit-state registry。

不要把它改造成 APC registry。

APC：

```text
vLLM 自己拥有 KV block
```

Continuation：

```text
WorkerKVRegistry 拥有显式 tensor copies
```

统一只发生在：

```text
Reuse Policy + Cost Accounting
```

---

# 42. 一个更完整的 Cost Model

APC 决策不要写：

```python
if prefix_tokens > 1000:
    use_apc = True
```

建议：

## 42.1 APC

\[
E[B_{APC}]
=
P_{hit}
\cdot C_{prefill}(T_{prefix})
\cdot N_{future}
-
C_{layout}
-
C_{schedule-delay}
\]

其中：

- `P_hit`：residency / recent observation / cache pressure 推断；
- `C_prefill(T)`：由真实历史 telemetry 校准，不必一开始建复杂模型；
- `N_future`：ApprovedPlan future consumer 数；
- `C_layout`：prefix compile/tokenize/extra request overhead；
- `C_schedule-delay`：为了 affinity 改变执行顺序的代价。

## 42.2 Explicit Continuation

\[
E[B_{KV}]
=
P_{consume}
\cdot C_{recompute}(T_{parent})
-
C_{store}
-
C_{load}
-
C_{memory}
-
C_{serialization}
\]

当前 4K / 1GiB 数据说明：

```text
C_store
```

非常不能忽略。

---

# 43. 第一版 Cost Model 不需要复杂拟合

建议先用 bucket EMA：

```text
prefix tokens bucket:
0-512
512-1K
1K-2K
2K-4K
4K+
```

记录：

```text
cold TTFT
warm TTFT
observed hit tokens
request wall
```

得到：

```text
prefill_saved_ms_per_token_bucket
```

然后：

```text
predicted_benefit_ms
```

只用于 tie-break / threshold。

不需要训练模型。

---

# 44. Prefix Feedback Loop 应从“直接重排 benchmark”改成“校准模型”

当前 `PrefixCacheFeedbackLoop`：

```text
predicted hit rate
vs
observed task-local hit rate
```

误差超过 threshold 后，continuous benchmark 会把剩余 task 直接重排成 cache-friendly order。

这个作为 benchmark experiment 可以保留。

产品 Runtime 中建议变成：

```text
prediction error
↓
update cost/residency confidence
↓
未来 scheduler score 变化
```

不要：

```text
一次 aggregate error
→ 粗暴 reorder 整个 workflow
```

因为 workflow dependency / critical path 远比 benchmark task list 更复杂。

---

# 45. APC v3 最终架构

```text
                        ┌──────────────────────┐
                        │     ApprovedPlan      │
                        └──────────┬───────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │ AdaptiveRuntimeEngine │
                        └──────────┬───────────┘
                                   │
                            compute READY set
                                   │
                                   ▼
                  ┌────────────────────────────────┐
                  │ WorkflowAwareReuseScheduler     │
                  │ - dependency hard guard         │
                  │ - critical path                 │
                  │ - age                           │
                  │ - cache affinity / future use   │
                  └──────────────┬─────────────────┘
                                 │ chosen step
                                 ▼
                  ┌────────────────────────────────┐
                  │ RuntimeInferenceInvoker         │
                  └──────────────┬─────────────────┘
                                 │
               ┌─────────────────┼─────────────────────┐
               │                 │                     │
               ▼                 ▼                     ▼
       PromptContextBuilder   PrefixCompiler      ReuseNamespace
               │                 │                     │
               │                 ▼                     │
               │        Canonical Prefix Group         │
               │                 │                     │
               └──────────────┬──┴─────────────────────┘
                              ▼
                  Exact Prefix Boundary
                              │
                  Request Membership Proof
                              │
                              ▼
                  InferenceReusePolicy
                    /         |          \
                   /          |           \
          RECOMPUTE      APC FULL      CONTINUATION
             │               │               │
             └───────────────┼───────────────┘
                             ▼
                         LLM Client
                             │
                             ▼
                           vLLM
                             │
                ┌────────────┴────────────┐
                ▼                         ▼
             KV Events                 Metrics
                │                         │
                ▼                         ▼
       PrefixResidencyIndex      Observation/Calibration
                └────────────┬────────────┘
                             ▼
                  InferenceReuseReceipt
```

---

# 46. 推荐的新 contracts

不建议删除 `prefix.py` v2。

建议兼容升级：

```text
prefix.py
- 保留 v2 read compatibility
- 新增 generic v3 participant/group contracts

inference_reuse.py
- 统一 mechanism / decision / receipt
```

## 46.1 `PrefixReuseGroup`

```python
@dataclass(frozen=True)
class PrefixReuseGroup:
    group_id: str
    task_or_session_id: str

    participant_invocation_ids: tuple[str, ...]
    participant_step_ids: tuple[str, ...]

    canonical_entry_keys: tuple[str, ...]
    canonical_prefix_sha256: str
    visibility_commitment_digest: str

    reuse_scope: ReuseScope
    reuse_namespace_digest: str

    predicted_execution_count: int
    predicted_reuse_count: int

    status: str
    reason: str = ""
```

## 46.2 `InferenceReuseDecision`

```python
@dataclass(frozen=True)
class InferenceReuseDecision:
    decision_id: str
    request_id: str
    step_id: str

    mechanism: ReuseMechanism
    prefix_group_id: str

    exact_full_block_tokens: int
    residency_state: str
    predicted_future_consumers: int

    predicted_saved_prefill_ms: float
    predicted_overhead_ms: float
    predicted_net_benefit_ms: float

    authorization_passed: bool
    exact_identity_passed: bool
    provider_compatible: bool

    reason_codes: tuple[str, ...]
```

## 46.3 `InferenceReuseReceipt`

```python
@dataclass(frozen=True)
class InferenceReuseReceipt:
    decision: InferenceReuseDecision

    dispatched_mechanism: ReuseMechanism
    provider_request_id: str

    observed_query_tokens: float = 0
    observed_hit_tokens: float = 0
    observed_ttft_ms: float = 0

    continuation_inherited_tokens: int = 0
    continuation_store_ms: float = 0
    continuation_load_ms: float = 0

    observation_valid: bool = False
    observation_reason: str = ""

    decision_hash: str = ""
```

---

# 47. 不要重复定义已有 identity 字段

`PrefixReuseIntentV2` 已经有大量：

```text
engine/model/tokenizer/template/cache identity
```

所以 v3 的迁移原则：

```text
复用字段
而不是复制字段到五个 dataclass
```

可以定义：

```python
@dataclass(frozen=True)
class InferenceEngineIdentity:
    engine_instance_id
    cache_namespace
    cache_epoch
    model_id
    model_revision
    weights_digest
    tokenizer_id
    tokenizer_revision
    chat_template_sha256
    template_kwargs_sha256
    adapter_digest
    multimodal_digest
    cache_salt_digest
    rope_config_digest
    kv_cache_dtype
    quantization_digest
    tp
    pp
```

然后 Prefix / Continuation 共享这个 logical compatibility identity。

注意：

```text
共享 compatibility identity
≠
共享 KV tensor implementation
```

---

# 48. `PrefixReuseIntentV2` 到 v3 的具体修改建议

当前最不适合 Adaptive 的字段：

```text
participant_role: PrefixParticipantRole
```

建议 v3：

```text
participant_id: str
participant_step_id: str
participant_role: str     # metadata only
prefix_group_id: str
reuse_scope: ReuseScope
reuse_namespace_digest: str
```

保留：

```text
engine identity
exact token identity
cache salt digest
dependency_ids
ready_set_epoch
schedule_priority
lease
```

所以不是推倒重来，而是：

```text
Role-centric intent
→
Invocation-centric intent
```

---

# 49. `CanonicalSharedEvidencePrefix` 是否要立刻改名？

不建议 R0 直接大规模 rename。

第一版还是让 APC 只共享：

```text
verified evidence entries
```

因为这是当前质量已验证的范围。

等 R1/R2 稳定，再增加：

```text
Memory material
stable runtime tool schema
public session context
```

然后再升级成：

```text
CanonicalSharedPrefix
```

不要在一个 Slice 同时做：

```text
Adaptive integration
+ generic content layers
+ memory prefix
+ scheduler
```

风险太高。

---

# 50. Prefix Layering：后续如何扩展而不破坏 APC

高级 Prompt layout 可以定义：

```text
Layer 0: Trust-domain stable runtime context
Layer 1: Corpus / shared evidence
Layer 2: Session public context
Layer 3: Runtime selected reusable state
Layer 4: Role / step suffix
```

原则：

```text
越稳定、越广泛共享、越少变化
→ 越靠左
```

但每个 layer 都必须：

```text
visibility authorized
semantic presence legitimate
stable canonical identity
```

绝不能为了 cache hit，把某个 participant 本来不需要/不应看到的状态硬塞进去。

---

# 51. Memory 与 APC 的正确关系

Memory：

```text
“是否已经有历史知识 / artifact 可以复用？”
```

APC：

```text
“这次仍需要模型读取相同上下文时，能否不重复 Prefill？”
```

所以：

```text
Memory Hit
↓
选择历史 artifact / strategy
↓
形成当前合法 Prompt Context
↓
其中稳定公共部分
↓
APC
```

不是：

```text
Memory = APC
```

也不是：

```text
APC hit 后就跳过 Memory policy
```

---

# 52. Hidden / Latent State 与 APC 的正确关系

未来 LatentState 如果加入：

```text
Agent A hidden representation
→ Agent B
```

它解决的是：

```text
跨 Agent 传新的中间语义
```

APC 解决：

```text
跨请求不重复计算完全相同左前缀
```

两者可同时存在：

```text
Shared Evidence Prefix
↓ APC
Executor
↓
LatentState
↓
Verifier/Summarizer
```

但 LatentState 本身是否应进入 Prefix 是另一个 representation 研究问题，不应在 APC-R1 顺手做掉。

---

# 53. Router 与 APC 的边界

已有 Routing Architecture 应保持：

```text
Task
↓
PlanSelector
↓
Planner
↓
PlanPolicy
↓
Approved Logical Plan
↓
ExecutionBinding
↓
CapabilityGrant
↓
Provider Dispatch
```

APC 不属于：

```text
Logical Capability selection
```

它属于：

```text
Inference Reuse / Physical Execution Optimization
```

因此：

```text
Planner 不看 cache hit
Planner 不选择 APC
Capability descriptor 不新增 use_apc capability
```

但 Execution Binding / Runtime Scheduler 可以看：

```text
provider compatibility
engine locality
prefix residency
```

---

# 54. Routing 与 Reuse 的最佳组合

未来 R0/R1 逻辑 provider split 后：

```text
Logical capability: analyze_verified_data

Provider A: DSL
Provider B: bounded Python + local vLLM
```

APC 只能作用在真正发 LLM request 的 Provider B。

因此顺序：

```text
Logical capability
↓
Execution Binding
↓
确定 physical provider / engine
↓
Inference Reuse Policy
```

不能反过来：

```text
“因为 GPU 上 Prefix X warm
所以改变语义 capability”
```

cache locality 不能改变语义正确性。

---

# 55. `cache_salt` 与 Execution Binding 的关系

如果未来多个 local-vLLM provider：

```text
vLLM-A
vLLM-B
```

APC residency 是 engine-local：

```text
Prefix X warm on A
Prefix X cold on B
```

所以 Execution Binding 可以在多个**语义等价、资源都合法**的 provider 之间使用：

```text
cache locality
```

作为 tie-break。

前提仍是：

```text
Eligibility First
Authority
Contract
Expressiveness
Resource
Risk
Quality
```

之后才：

```text
latency / token / cache affinity
```

这和此前 Routing Architecture 完全一致。

---

# 56. APC v3 的四阶段实施路线

下面建议严格按 Slice 推进。

---

# APC-R0 — Contract Consolidation / No Behavior Change

## 目标

把现有分散 Prefix contract 重新收束成可被 Adaptive Runtime 使用的接口，但**不改变任何现有运行行为**。

## 修改

### `statebus/contracts/prefix.py`

- 保留所有 v2；
- 新增 generic participant/group adapter；
- 增加 `ReuseScope`；
- 增加 `ReuseNamespace`；
- 增加 `PrefixReuseGroup`；
- 设计 `PrefixReuseIntentV3`，不立刻删除 v2。

### 新增 `statebus/contracts/inference_reuse.py`

```text
InferenceReuseMode
ReuseMechanism
InferenceEngineIdentity
InferenceReuseDecision
InferenceReuseReceipt
```

### `statebus/runtime/prefix_identity.py`

拆出：

```text
compile_prefix_token_boundary()
verify_request_prefix_membership()
```

旧：

```text
compile_exact_token_prefix_identity()
```

保留为兼容 wrapper。

### `statebus/runtime/neural_state.py`

- 标注旧 `task_session` registry 为 legacy control-plane estimate；
- 不再让它成为 future AUTO authority；
- estimator 保留。

## R0 明确不做

```text
不改 Prompt
不改 role path
不改 AdaptiveRuntime order
不发 cache_salt
不接 KV events
不改 benchmark result
```

## Acceptance

```text
现有 Prefix tests 全 PASS
现有 Engine-Local KV tests 全 PASS
现有 25 formal behavior 不变
shared / independent prompt hash 不发生意外变化
v2 artifact 仍可读取
v3 serialization/hash deterministic
```

---

# APC-R1 — AdaptiveMainline Integration / AUTO Decision Plane

## 目标

让 APC 第一次真正出现在：

```text
AdaptiveMainline -> AdaptiveRuntime
```

而不是只在 smoke。

## 新增目录建议

```text
statebus/runtime/inference_reuse/
    __init__.py
    context.py
    prompt_context.py
    prefix_compiler.py
    exact_identity.py
    policy.py
    cost_model.py
    receipts.py
```

## 修改 `AdaptiveMainlineBindings`

新增：

```python
inference_invoker: RuntimeInferenceInvoker | None
inference_reuse_policy: InferenceReusePolicy | None
```

## 修改 `AdaptiveDispatchContext`

新增：

```python
inference_reuse_context: InferenceReuseContext | None
```

## 修改 `AdaptiveRuntimeRequest`

新增：

```python
reuse_scheduler: WorkflowAwareReuseScheduler | None
inference_reuse_context: InferenceReuseContext | None
```

R1 scheduler 仍可以 no-op。

## 修改 `LLMClient`

增加 optional：

```python
invocation_context: InferenceInvocationContext | None = None
```

本地 vLLM adapter 从中读取：

```text
cache_salt
request identity
```

其他 provider 忽略不支持项或 policy bypass。

## R1 的 AUTO Gate

```text
1. backend supports APC
2. ReuseAuthorization PASS
3. candidate participant count >= 2
4. canonical prefix eligible
5. exact boundary >= min full blocks
6. current request membership verified
7. estimated net benefit > threshold
8. no context truncation / model identity conflict
9. quality-sensitive prompt contract unchanged
```

不满足：

```text
RECOMPUTE
```

## R1 第一版 participant

虽然 contract 泛化，实际只需要先覆盖：

```text
当前已经质量验证过的 Executor-like → Summarizer-like shared evidence path
```

但不要用 enum 写死。

## Acceptance

```text
OFF：与旧 AdaptiveMainline 完全等价
OBSERVE：产生 reuse decisions，但 request/prompt/order 不改变
AUTO：至少一组 controlled adaptive case 真正使用 APC
AUTO bypass：短 prefix / scope mismatch / tokenizer mismatch 正确退回
benchmark metadata 不进入 reuse context
quality gate 与 OFF 相同
```

---

# APC-R1.5 — Stable-Key Suffix Subtraction

可以独立一个小 Slice。

## 目标

把 shared entries 从 role suffix 真正按 entry identity 删除。

```text
common: A B C
summarizer visible: A B C D E
↓
suffix: D E
```

而不是依赖整块文本 equality。

## Acceptance

```text
可见证据集合不变
公共证据只出现一次
role-specific evidence 不丢失
prompt bytes 非增
quality 不降
```

---

# APC-R2 — Workflow-Aware Ready-Set Scheduling

## 目标

利用 ApprovedPlan DAG，而不是 benchmark manifest，决定当前 READY steps 的执行顺序。

## 修改 `AdaptiveRuntimeEngine.run()`

从：

```text
ready
↓
sorted ready
↓
for all
```

变：

```text
ready
↓
choose one
↓
execute
↓
update runtime/reuse state
↓
recompute ready
```

## 新增：

```text
statebus/runtime/inference_reuse/scheduler.py
```

### Scheduler 输入

```text
ApprovedPlan
completed / failed
current ready set
StepInferenceProfile
PrefixResidencySnapshot
PrefixNextUseEstimate
wait age
runtime priority
```

### Scheduler 输出

```text
chosen step_id
score breakdown
reason codes
ready_set_epoch
```

### 第一版 score

```text
cache benefit
+ downstream warm benefit
+ critical-path urgency
+ age
- schedule delay
```

### Hard invariant

```python
assert chosen_step in ready_set
```

## Benchmark scheduler 迁移

从 `benchmark/kv_prefix_schedule.py` 抽取算法，但：

```text
不复用 benchmark hint generation
```

## Acceptance

```text
dependency order 100% preserved
ready-set membership 100% preserved
no cache metadata 时顺序退化为 stable baseline
cache affinity case 中产生 measurable reorder
cache-cold step 不 starvation
quality / output hash contracts 保持
```

---

# APC-R3 — Event-Driven Prefix Residency

## 前提

当前服务 backend 必须通过 capability discovery 证明支持现代 vLLM KV Events。

不要为了 R3 强行升级整个项目主链。

## 新增：

```text
statebus/runtime/inference_reuse/residency.py
statebus/integrations/vllm_prefix/events.py
```

## Event consumer

消费：

```text
BlockStored
BlockRemoved
AllBlocksCleared
```

维护：

```text
engine/cache epoch
block chain
medium/locality
prefix group mapping
```

## Event gap

```text
dropped / reconnect / epoch changed
→ UNKNOWN
```

如果 vLLM replay endpoint 可用：

```text
先 replay gap
再恢复 LIVE
```

不能在 gap 后继续假定 warm。

## Metrics 的新职责

```text
KV Events → online residency
Prometheus counters → task-level mechanism evidence / calibration
```

## Acceptance

```text
BlockStored → resident
BlockRemoved → partial/evicted
AllBlocksCleared → all invalidated
cache epoch change → old state invalid
lost event → UNKNOWN
UNKNOWN 不被计为 guaranteed hit
metrics 与 event observation 可交叉审计
```

---

# APC-R4 — Conditional Continuation + Hierarchical Prefix（可选）

不是当前前置。

只有 R1-R3 证明：

```text
APC 仍经常因 tool gap / pressure 被 eviction
```

再考虑：

```text
APC vs Explicit Continuation
```

统一 policy。

或证明 flat prefix group 不够，才做：

```text
PrefixReuseTree
```

---

# 57. 推荐实施顺序与现有 Routing / Benchmark 计划的协调

之前的联合路线：

```text
B0 Visibility Inventory
B1 Boundary Contracts
R0 Logical Capability / Provider split
B3 AssetRegistry
R1 Execution Binding
R2 PlanSelector
B6 TeamBench
B7 IDA
B8 Memory genericization
```

APC 不应该插进去打乱 semantic architecture。

建议：

```text
Benchmark Boundary B0/B1
        ↓
Routing R0 provider split
        ↓
APC-R0 contracts
        ↓
Routing R1 binding
        ↓
APC-R1 Adaptive integration
        ↓
PlanSelector / External lane
        ↓
APC-R2 Runtime scheduler
        ↓
APC-R3 residency（backend 条件满足再做）
```

原因：

```text
APC 必须知道最终 physical inference provider / engine
```

所以 Logical Capability / Provider split 应先于完整 reuse binding。

---

# 58. 测试矩阵

## 58.1 Contract Tests

```text
test_reuse_scope_namespace_stable.py
test_reuse_namespace_scope_isolation.py
test_cache_salt_digest_not_plaintext.py
test_prefix_group_participant_unique.py
test_prefix_v2_v3_compatibility.py
test_exact_boundary_block_alignment.py
test_request_membership_mismatch.py
```

## 58.2 Visibility / Security

```text
test_private_gold_not_prefix_input.py
test_audit_metadata_not_prefix_affinity.py
test_cross_scope_prefix_share_rejected.py
test_cross_tenant_cache_salt_differs.py
test_visibility_intersection_required.py
```

## 58.3 Adaptive Runtime

```text
test_scheduler_selects_only_ready.py
test_scheduler_preserves_dependency.py
test_scheduler_noop_without_reuse_context.py
test_scheduler_recomputes_after_each_step.py
test_cache_affinity_does_not_change_capability.py
test_reuse_decision_does_not_change_plan.py
```

## 58.4 Prompt

```text
test_stable_key_suffix_subtraction.py
test_shared_prefix_at_token_zero.py
test_role_specific_evidence_retained.py
test_template_change_invalidates_identity.py
test_left_truncation_rejects_reuse.py
```

## 58.5 vLLM Integration

```text
test_cache_salt_injected_only_local_vllm.py
test_backend_without_cache_salt_bypasses.py
test_kv_event_store_remove_clear.py
test_event_gap_marks_unknown.py
```

## 58.6 Continuation Boundary

```text
test_apc_and_continuation_token_accounting_exclusive.py
test_continuation_not_selected_without_positive_cost.py
test_explicit_kv_handle_not_treated_as_apc_residency.py
```

---

# 59. Telemetry / Receipts：以后实验要能回答什么

每一次 inference 至少能回答：

```text
为什么这次启用 / 没启用 APC？
共享范围是什么？
共享给了谁？
共享内容来自哪些 verified refs？
真正 exact full-block token 有多少？
当前 residency 是什么？
预计省多少？
Runtime 是否因为 cache 改变了 ready order？
实际 vLLM hit token 是多少？
质量有没有变化？
```

建议 metrics：

```text
prefix_group_candidate_count
prefix_group_selected_count
prefix_authorization_reject_count
prefix_exact_eligible_count
prefix_exact_ineligible_count
prefix_full_block_tokens
prefix_request_membership_pass_count
prefix_request_membership_fail_count

apc_decision_count
apc_bypass_count
apc_resident_decision_count
apc_unknown_residency_decision_count

reuse_scheduler_choose_count
reuse_scheduler_reorder_count
reuse_scheduler_cache_affinity_win_count
reuse_scheduler_age_override_count
reuse_scheduler_critical_path_override_count

vllm_prefix_observed_query_tokens
vllm_prefix_observed_hit_tokens
vllm_prefix_observed_hit_rate

predicted_prefill_saved_ms
observed_ttft_ms
prediction_error_ms
```

不要把：

```text
estimated hit
```

写成：

```text
actual hit
```

---

# 60. 实验设计：APC v3 怎么证明“对系统真的有用”

不能只再跑一遍：

```text
shared prompt vs independent prompt
```

旧实验已经证明 mechanism。

新实验必须证明：

```text
Runtime Policy Value
```

---

# 61. Experiment A — Adaptive Mainline Integration

比较：

```text
OFF
OBSERVE
AUTO
```

保持：

```text
同一 Plan
同一 capability/provider
同一 quality validator
同一 model
```

看：

```text
AUTO APC decision count
exact eligible rate
TTFT
wall
quality
```

目标不是必须大幅提升所有 case，而是：

```text
有自然共享时 AUTO 启用
无共享时 AUTO bypass
```

证明不会“为了 APC 让所有任务都变复杂”。

---

# 62. Experiment B — Ready-Set Causal Scheduling

构造真实 DAG：

```text
       A(prefix X)
      /           \
root               join
      \           /
       B(prefix X)

另有 C(prefix Y)
```

保持 dependency 合法。

比较：

```text
stable step-id order
vs
workflow-aware order
```

需要证明：

```text
same ApprovedPlan
same completed steps
same outputs

但：
A -> B adjacency 更高
observed hit tokens 更高
TTFT / JCT 更低
```

Benchmark 只定义任务与 dependency，不告诉 Runtime `prefix X` label；Runtime 必须从 verified public refs/canonical prefix 自己检测 affinity。

---

# 63. Experiment C — Tool Gap

```text
Executor
↓
CodeAct gap = 0 / 200ms / 500ms / 1s / 2s
↓
Summarizer
```

同时制造不同 cache pressure。

观察：

```text
APC hit probability
TTFT
residency
```

这能回答：

```text
什么时候只靠 APC 足够？
什么时候 tool gap 让 continuation/TTL 才可能值得？
```

这比直接加入 LMCache 更有决策价值。

---

# 64. Experiment D — Reuse Scope

测试：

```text
TASK
SESSION
CORPUS
TRUST_DOMAIN
```

要求：

```text
同 namespace → 可以 hit
不同 namespace → 不能 cross-hit
```

并验证：

```text
cache_salt isolation
```

这是系统安全性证据，不只是性能。

---

# 65. Experiment E — APC vs Explicit Continuation

在同一逻辑 Prompt、相同 parent token 长度下：

```text
cold recompute
warm APC
continuation
```

维度：

```text
prefix tokens
cache pressure
tool gap
store/load cost
```

最后得到一个真实 mechanism selection surface：

```text
什么时候 APC 最优
什么时候 recompute 最优
什么时候 continuation 才值得
```

而不是人为宣布 continuation 更高级。

---

# 66. External Benchmark 怎么处理 APC

TeamBench / IDA-Bench 等 external lane 的主要目的仍然是：

```text
Routing / Input generalization
```

不要为了证明 APC，给它们人工注入：

```text
corpus_group
prefix_expected_hit
reuse labels
```

如果外部任务自然存在：

```text
same repo
same file
same session
```

Runtime 可以通过公共 asset digest 自己发现。

否则 APC：

```text
bypass
```

完全合理。

一个好的 Adaptive system 本来就应该：

```text
不是每个 feature 每个 task 都打开
```

---

# 67. Prompt Quality Gate：APC 不能只追 hit rate

shared-prefix layout 会改变 prompt ordering。

虽然当前 40/40 role JSON 与 formal quality 已经证明当前 evidence-first layout 没有明显破坏质量，但未来 Adaptive 化后必须继续 gate：

```text
semantic output
schema output
citation
validator
CodeAct correctness
```

尤其不要为了 cache 把：

```text
所有 role instruction
```

随便移动到很后面而不测质量。

性能指标必须永远和：

```text
Quality PASS
```

一起报告。

---

# 68. Context Truncation 是容易漏掉的 APC 正确性问题

如果 Runtime 预测：

```text
Prefix = 4K
```

但 provider 因 max context 做：

```text
left truncation
```

那么 token 0 prefix 可能被截掉。

所以 AUTO eligibility 必须检查：

```text
final rendered request length
max context
truncation policy
```

如果发生左截断：

```text
prefix identity invalid
→ RECOMPUTE / no APC claim
```

不能继续沿用 pre-truncation identity。

---

# 69. Model / Adapter / MM / Quantization 兼容性

当前 `PrefixReuseIntentV2` 已经预留：

```text
adapter_digest
multimodal_digest
rope_config_digest
kv_cache_dtype
quantization_digest
tensor_parallel_size
pipeline_parallel_size
```

这是对的。

AUTO policy 应严格要求：

```text
所有影响 KV 的 identity 一致
```

不能只比较：

```text
prompt text
```

尤其现代 vLLM block `extra_keys` 本身就会考虑 LoRA / multimodal / salt 等身份。

---

# 70. Current Explicit KV Service 的部署约束也说明为什么 R1 先做 APC

当前 engine-local KV probe service：

```text
single GPU
max_num_seqs=1
APC disabled
enforce eager
custom kv connector
worker extension
middleware
registry max 2 entries / 2 GiB
pin memory false
```

这是一条很好用的 mechanism experiment lane，但并不是普通产品 vLLM path。

反过来 APC：

```text
不需要保存额外 1GiB host handle
不需要自定义 Consumer load
不需要改变 logical request body
```

因此在当前比赛 / 系统工程投入下：

```text
先 productize APC
```

明显比：

```text
继续加复杂 continuation features
```

更划算。

---

# 71. 不建议现在做的事情

明确禁止当前阶段：

```text
❌ fork vLLM KV allocator
❌ 自己实现 prefix hash table
❌ 修改 PagedAttention kernel
❌ 自己实现 eviction manager
❌ 直接上 LMCache / SSD KV
❌ 为了 APC 加 KVCOMM correction
❌ 为了 APC 做 CacheBlend
❌ Planner 输出 use_apc=true
❌ CapabilityRegistry 注册 “APC capability”
❌ 使用 benchmark category/kv_probe_corpus_group 做 production affinity
❌ 用 bytes/4 estimate 宣称真实 hit
❌ 用 PrefixRegistry handle-seen 宣称 vLLM cache hit
❌ 为 cache locality 违反 DAG dependency
❌ 把 Explicit KV Handle 当作 APC block residency
```

---

# 72. 与外部系统的对应关系：哪些借，哪些不借

## vLLM

### 借

```text
hash-based full-block APC
cache_salt isolation
KV Events
Renderer / token identity capability
```

### 不借 / 不改

```text
不 fork block allocator
不改 eviction
```

---

## SGLang

### 借

```text
cache-aware scheduling 思路
longest-prefix locality
warm-first / in-batch shared-prefix 思路
session affinity / soft protection概念
```

### 不照搬

```text
不引入一套 RadixCache 到 StateBus
```

vLLM 已经是实际 cache owner。

---

## KVFlow

### 借

```text
workflow future-use
Agent Step Graph / steps-to-execution 的思想
```

StateBus 甚至更直接：

```text
ApprovedPlan 就是 Runtime 已批准的 workflow graph
```

### 暂不借

```text
node-level eviction modification
CPU→GPU async prefetch implementation
```

---

## Continuum

### 借

```text
Tool Gap 是 Agent serving 的真实 KV reuse 问题
TTL / future return time 会影响保留价值
```

### 暂不借

```text
不马上做 GPU KV pinning / TTL eviction fork
```

先用 ready-set scheduling 和 observation 验证是否真的需要。

---

## TOPAS

### 借

```text
不能只优化 prefix locality
还要考虑 workflow progress / critical path / aging
```

### 暂不借

```text
复杂并发 JCT optimizer
prefix movement / preemption joint control
```

当前 `max_num_seqs=1` / 串行 Runtime 阶段不需要。

---

# 73. 推荐最终文件布局

```text
statebus/contracts/
    prefix.py                       # existing v2 + v3 prefix-specific contracts
    inference_reuse.py              # new unified decision contracts

statebus/runtime/inference_reuse/
    __init__.py
    context.py
    prompt_context.py
    prefix_compiler.py
    exact_identity.py
    namespace.py
    policy.py
    cost_model.py
    scheduler.py
    residency.py
    receipts.py

statebus/integrations/
    llm.py                          # add optional invocation context
    vllm_prefix/
        capabilities.py
        cache_salt.py
        events.py                   # R3
        renderer.py                 # optional modern backend

statebus/runtime/
    adaptive_mainline.py            # assemble InferenceReuseContext
    adaptive_runtime.py             # choose-one ready scheduler seam
    adaptive_dispatcher.py          # pass inference runtime context
    llm_codeact.py                  # use RuntimeInferenceInvoker

statebus/benchmark/
    kv_prefix_schedule.py           # only experiment adapter/hints
    continuous_runner.py            # experiments, not runtime algorithm owner
```

注意：

```text
statebus/runtime/**
```

不能 import：

```text
statebus/benchmark/**
```

作为产品逻辑依赖。

---

# 74. 一个 Codex 可以直接执行的 R0 Parent Task

```text
APC-R0 — Inference Reuse Contract Consolidation

Goal:
Prepare existing StateBus prefix reuse contracts for Adaptive Runtime integration without changing runtime behavior.

Read first:
- statebus/contracts/prefix.py
- statebus/runtime/prefix_identity.py
- statebus/runtime/neural_state.py
- statebus/runtime/role_path.py
- statebus/runtime/smoke.py
- statebus/contracts/engine_local_kv.py
- docs/implementation/runtime/engine-local-prefix-reuse.md
- docs/implementation/runtime/engine-local-kv-continuation.md

Implement:
1. Add ReuseScope and ReuseNamespace contracts.
2. Add PrefixReuseGroup / generic participant identity.
3. Add InferenceReuseMode / ReuseMechanism / InferenceReuseDecision / Receipt.
4. Add exact prefix boundary + request membership primitives.
5. Keep PrefixReuseIntentV2 and current artifact schemas readable.
6. Keep compile_exact_token_prefix_identity as compatibility wrapper where practical.

Do not:
- alter prompt layout;
- alter AdaptiveRuntime scheduling;
- inject cache_salt into live requests;
- enable APC by default;
- touch vLLM source;
- modify benchmark affinity semantics;
- modify explicit KV connector/registry behavior.

Acceptance:
- all existing prefix/kv tests pass;
- serialization deterministic;
- v2 compatibility tests pass;
- no live benchmark output changes;
- new contracts contain no benchmark-only labels.
```

---

# 75. 一个 Codex 可以直接执行的 R1 Parent Task

```text
APC-R1 — Adaptive Mainline Inference Reuse Integration

Goal:
Move prefix reuse from fixed RolePath/smoke-only integration into the AdaptiveMainline inference request lifecycle.

Implement:
1. Create RuntimeInferenceInvoker.
2. Add optional InferenceInvocationContext to LLMClient path.
3. Assemble InferenceReuseContext in AdaptiveMainlineRunner.
4. Make local-vLLM provider support per-request reuse namespace/cache_salt.
5. Build canonical shared evidence prefix from Runtime-authorized refs only.
6. Finalize exact prefix membership before each inference dispatch.
7. Support OFF / OBSERVE / AUTO.
8. Persist InferenceReuseDecision / Receipt.
9. Keep ready-set ordering unchanged in R1.

Hard guards:
- Planner cannot request APC.
- private gold / benchmark metadata cannot enter prefix inputs.
- scope mismatch => bypass.
- exact identity unavailable => bypass in AUTO.
- backend unsupported => bypass.
- output/quality contracts unchanged.

Acceptance:
- OFF behavior equivalent to current AdaptiveMainline.
- OBSERVE has zero behavior effect.
- AUTO obtains an actual vLLM APC hit on a controlled adaptive task with shared verified prefix.
- AUTO bypass works on non-shareable task.
- quality gate remains PASS.
```

---

# 76. 一个 Codex 可以直接执行的 R2 Parent Task

```text
APC-R2 — Workflow-Aware Ready-Set Scheduler

Goal:
Use ApprovedPlan DAG and inference reuse state to choose among already-ready steps without modifying plan semantics.

Implement:
1. Extract generic dependency-aware scheduling from benchmark ownership.
2. Add WorkflowAwareReuseScheduler in runtime/inference_reuse.
3. Change AdaptiveRuntime from for-all-ready to choose-one/recompute-ready.
4. Add StepInferenceProfile and PrefixNextUseEstimate.
5. Add stable fallback ordering.
6. Add score breakdown / scheduler receipt.

Do not:
- execute blocked step;
- change capability;
- create/delete plan step;
- use benchmark affinity labels;
- add vLLM eviction hooks.

Acceptance:
- chosen step always belongs to current ready set;
- all dependencies preserved;
- no reuse context reproduces stable order;
- controlled repeated-prefix DAG gets more cache-adjacent executions;
- no starvation under aging guard;
- output quality unchanged.
```

---

# 77. 一个 Codex 可以直接执行的 R3 Parent Task

```text
APC-R3 — vLLM KV-Event Residency Backend

Goal:
Replace cache-residency guesses with a fail-closed metadata mirror built from supported vLLM KV events.

Implement:
1. Add backend feature discovery.
2. Add ZMQ event subscriber/replay support when configured.
3. Maintain PrefixResidencyIndex.
4. Handle BlockStored / BlockRemoved / AllBlocksCleared.
5. Bind engine/cache epoch.
6. Treat event gaps or mapping uncertainty as UNKNOWN.
7. Feed residency into policy/scheduler.
8. Keep Prometheus counters as independent mechanism observation.

Do not:
- store KV tensors;
- modify vLLM cache manager;
- claim guaranteed hit from UNKNOWN;
- require R3 backend for correctness.
```

---

# 78. 最终项目叙事应该如何变化

旧叙事：

> StateBus 通过调整 Prompt，让多个 Agent 共享 vLLM APC，提高 Prefix Cache Hit Rate。

这个太像一个 prompt trick。

更合理的系统叙事：

> **StateBus 将推理侧 KV 复用纳入 workflow-level physical execution policy。Runtime 在 ApprovedPlan 之后，根据状态可见性与共享授权构造 canonical prefix，在真实 tokenizer/chat-template 下证明 exact full-block identity，并结合执行 DAG、未来消费者、cache residency 和 provider compatibility，在不改变逻辑计划的前提下选择请求布局与 ready-step 顺序。vLLM 保持 KV block 的实际所有权和淘汰权；StateBus 负责共享边界、计算复用决策、调度与可审计回执。**

再与其他模块放在一起：

```text
Routing
→ 决定“做什么 / 用哪个合法 provider”

Semantic Memory
→ 决定“过去已经知道什么可以复用”

Workflow-Aware APC
→ 决定“当前相同上下文是否需要重新 Prefill”

Explicit KV Continuation
→ 在 APC 不稳定且显式继承收益足够时，提供受控纵向 KV carry

Embedding / Latent State
→ 减少文本状态传递或提供数值中间表示

Logit Gate
→ 决定候选执行是否获得下游资格
```

这时 StateBus 不再是“堆了几个 side feature”，而是一个分层的 Runtime：

```text
Semantic Plan
↓
Authorization
↓
Provider Binding
↓
State Placement
↓
Inference Reuse
↓
Decision Gate
↓
Verified Commit
```

---

# 79. 最终优先级

| 项目 | 优先级 | 原因 |
|---|---:|---|
| Prefix contracts 泛化 / consolidation | P0 | 已有实现成熟，先把职责收束 |
| Exact identity 前移到 dispatch 前 | P0 | AUTO 的必要条件 |
| AdaptiveMainline inference reuse context | P0 | 当前真正缺口 |
| Runtime per-request cache_salt / ReuseScope | P0 | cross-task + security 的基础 |
| Stable-key suffix subtraction | P0/P1 | 简单、直接减少重复 token |
| Ready-set workflow-aware scheduling | P1 | 最体现 StateBus 独特价值 |
| Prefix next-use / tool-gap heuristic | P1 | ApprovedPlan 可直接提供 |
| KV Events ResidencyIndex | P1 / backend-dependent | 让 online decision 从猜测变成可观测 |
| Prefix feedback cost calibration | P1 | 提升 policy 精度 |
| APC vs continuation unified cost policy | P2 | 先证明 APC residency 问题再做 |
| Hierarchical PrefixReuseTree | P2 | flat group 不足后再做 |
| KV TTL / pin / prefetch | P2/P3 | 需要并发/pressure evidence |
| LMCache / SSD / distributed KV | DEFER | 当前没有必要为 APC 主线增加重型数据面 |
| KVCOMM / CacheBlend | DEFER | 当前 exact-prefix 主问题尚未 productize |

---

# 80. 最终建议

当前最值得做的不是“继续优化 APC 实验结果”，而是完成一次非常明确的架构升级：

```text
Existing APC mechanism
        ↓
从 smoke / benchmark feature
        ↓
变成 Adaptive Runtime 的
Workflow-Aware Inference Reuse Policy
```

第一阶段只需要做到：

```text
ReuseScope
+ Runtime-owned prefix group
+ dispatch-before exact identity
+ AUTO/bypass policy
+ AdaptiveMainline integration
```

就已经能解决当前最大的结构问题。

第二阶段再加入：

```text
ApprovedPlan ready-set scheduling
+ future-use/tool-gap
```

这一步是最有 StateBus 差异化的部分。

第三阶段如果当前 vLLM backend 支持：

```text
KV Events
```

再把 residency 从估计升级成 event-driven observation。

这条路线的优点是：

1. 不推翻现有 APC；
2. 不浪费已经做好的 exact identity / metrics / prefix contracts；
3. 不 fork vLLM；
4. 不破坏已有 Routing 架构；
5. 不污染 External Benchmark boundary；
6. 能直接利用当前已经测出的 APC 大幅 TTFT 收益；
7. 真正把 APC 变成“系统能力”，而不是 demo feature。

---

# 81. 参考实现与外部资料

## StateBus 源码基线

- Repository: `https://github.com/qcrs/os`
- Branch: `master`
- Commit: `8bfc6464ec236c0e121911095fc283129b0e7696`

关键文件：

```text
statebus/contracts/prefix.py
statebus/runtime/prefix_identity.py
statebus/runtime/role_path.py
statebus/runtime/neural_state.py
statebus/runtime/vllm_metrics.py
statebus/runtime/prefix_feedback.py
statebus/runtime/smoke.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/integrations/llm.py
statebus/contracts/engine_local_kv.py
statebus/integrations/vllm_kv/role_client.py
statebus/integrations/vllm_kv/registry.py
statebus/integrations/vllm_kv/tokenizer_client.py
statebus/benchmark/kv_prefix_schedule.py
statebus/benchmark/continuous_runner.py
```

## vLLM

- Automatic Prefix Caching design:  
  `https://docs.vllm.ai/en/latest/design/prefix_caching/`
- APC feature guide:  
  `https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html`
- Prefix cache security / cache salting:  
  `https://docs.vllm.ai/en/latest/usage/security/`
- KV Events config:  
  `https://docs.vllm.ai/en/latest/api/vllm/config/kv_events/`
- KV Events API:  
  `https://docs.vllm.ai/en/latest/api/vllm/distributed/kv_events/`
- Renderer APIs:  
  `https://docs.vllm.ai/en/latest/serving/online_serving/renderer/`

## SGLang

- Schedule policy source:  
  `https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/managers/schedule_policy.py`
- Radix cache source:  
  `https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/mem_cache/radix_cache.py`
- Session-aware radix cache:  
  `https://github.com/sgl-project/sglang/blob/main/docs/docs/advanced_features/session_radix_cache.mdx`

## Workflow-aware KV research

### KVFlow — NeurIPS 2025

`KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows`

- NeurIPS:  
  `https://proceedings.nips.cc/paper_files/paper/2025/hash/b7971d31a7d5eb0f1eed2f8f6f368195-Abstract-Conference.html`
- arXiv:  
  `https://arxiv.org/abs/2507.07400`

核心参考点：Agent Step Graph、steps-to-execution、workflow-aware eviction/prefetch。

### Continuum — UC Berkeley 2026

`Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache Time-to-Live`

`https://www2.eecs.berkeley.edu/Pubs/TechRpts/2026/EECS-2026-234.html`

核心参考点：tool-call gap、multi-turn agent KV lifetime、TTL。

### TOPAS — 2026

`TOPAS: Workflow-Aware Prefix-State Scheduling for Multi-Agent LLM Serving`

`https://arxiv.org/abs/2608.25523`

核心参考点：prefix locality 不能脱离 workflow critical path、movement/preemption cost 与 aging 单独优化。

---

# 82. 一句话版本

> **StateBus APC 下一步不是“把 vLLM 的缓存写得更复杂”，而是把已经验证有效的 Prefix Reuse 提升成 ApprovedPlan 之后的正式 Runtime Physical Policy：用 StateBus 自己掌握的 visibility、DAG、provider identity 和 future-use 信息决定共享与调度，让 vLLM 继续只负责它最擅长的 KV block 存储与命中。**
