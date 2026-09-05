# StateBus 非文本状态深度源码审计：Embedding Hardening 与 StateBridge LatentState 设计

> **Repository baseline**：`qcrs/os` `master`  
> **Pinned commit**：`8bfc6464ec236c0e121911095fc283129b0e7696`（2026-07-30）  
> **Historical reference**：`qcrs/os1`（仅用于理解演进，不覆盖当前 `os/master` 事实）  
> **StateBridge reference**：`YanwenPneg/StateBridge` `main`  
> **Pinned StateBridge commit**：`3f6bf5442c6e8848555a6132516e6d36f35444fb`（COLM 2026 release）  
> **日期**：2026-09-02  
> **文档定位**：源码审计 / Contract Before→After / Latent State Provider 设计 / 实施前基线  
> **本阶段不做**：不修改 StateBus 源码，不修改 vLLM，不运行正式 benchmark，不把 Hidden State 强行接入当前 Qwen3-32B vLLM 主线。

---

# 0. 本文要解决的问题

StateBus 当前已经存在多种“非文本”机制：

```text
Embedding
Logit
APC
Explicit KV
```

但它们解决的是不同层次的问题。

本文不再把它们混成一个“Non-text State”概念，而是专门完成两件事：

1. **深度审计当前 Embedding / SemanticState 的真实代码链和 contract 缺口；**
2. **设计一个真正独立的 `LatentStateRef`，把 StateBridge 的**
   `HiddenStateCapture → Alignment → inputs_embeds`
   **映射进 StateBus 已经存在的**
   `publish → Ref → UDS → consume → receipt → release`
   **生命周期。**

本文同时记录 Logit、StateStore、Control Plane、CapabilityGrant、Explicit KV 中与 latent state 直接相关的设计问题，但不在这一阶段实现 KV/Logit 重构。

---

# 1. 核心结论

先给最终判断。

## 1.1 当前 Embedding 不是 toy，但它的“系统工程”强于“语义表达能力”

当前真实链路是：

```text
Retriever
  │
  ├─ query embedding
  └─ candidate embeddings
          │
          ▼
DenseSemanticStateContract
          │
          ▼
float32 matrix
row0=query
row1..N=candidates
          │
          ▼
LayeredStateStore
  ├─ shared_memory
  └─ mmap
          │
          ▼
SemanticStateRef
          │
          ▼
typed Protobuf / UDS
          │
          ▼
another PID
          │
          ▼
read-only resolve
hash / lease / encoder validation
          │
          ▼
candidate_matrix @ query
          │
          ▼
top-k IDs
          │
          ▼
Runtime hydrate EvidencePack
          │
          ▼
release
```

这是一个完整的：

```text
publish
→ cross-process transport
→ validate
→ consume
→ behavioral effect
→ cleanup
```

闭环。

但下游 LLM 并没有直接消费这段 continuous vector。

它实际做的是：

```text
Embedding
  ↓
选择 Evidence ID
  ↓
Evidence 再文本化 / hydrate
  ↓
LLM
```

所以它应该被准确命名为：

# Semantic Selection State

而不是：

```text
Latent reasoning communication
```

。

---

## 1.2 `SemanticStateRef` 不应该直接扩成 Hidden State

当前 `SemanticStateRef` 和 `DenseSemanticStateContract` 强绑定：

```text
query_then_candidates
float32
little endian
unit normalized
HydrateManifest
top-k
source text hashes
encoder signature
```

这些全部是 retrieval-selection 语义。

Hidden State 则需要：

```text
producer model
receiver model
source layer
generated token lineage
[K, H]
alignment method
alignment config
injection position
consumer model compatibility
visible commitment
```

因此正确设计是：

```text
SemanticStateRef
    保持兼容

新增：

LatentStateRef
LatentStateContract
LatentConsumptionReceipt
```

而不是：

```text
SemanticStateRef v2
什么状态都往里面塞
```

。

---

## 1.3 在引入 Hidden State 之前，有一组 State Foundation 问题必须先 harden

其中最重要的是：

```text
当前 UDS RefHandle
只有：
ref_id
ref_kind
```

消费者随后：

```text
ref_id
  ↓
读取 sidecar
  ↓
从 sidecar 自己重建 SemanticStateRef
```

同时：

```text
CapabilityGrant
只绑定 input_ref_ids
```

而不是：

```text
ref_id
+ blob hash
+ contract hash
```

。

这意味着当前的验证在很大程度上是：

```text
sidecar
和
sidecar 重建出来的 Ref
自洽
```

而不是：

```text
Controller 发送的不可变 Ref commitment
和
消费者实际打开的 payload
一致
```

。

在当前：

```text
同机
可信 Runtime
controlled benchmark
```

环境下，这不是项目级灾难。

但 Hidden/KV 一旦变成真正的 Agent 内部状态：

# 这是必须修的 integrity boundary。

---

## 1.4 StateBridge 非常适合第一版 Latent Provider，但不要原样嵌入

StateBridge 的核心方法值得借：

```text
final-layer hidden states
  ↓
centering / whitening
  ↓
Orthogonal Procrustes
  ↓
norm calibration
  ↓
vocabulary anchoring
  ↓
continuous prefix
  ↓
inputs_embeds
```

它：

```text
training-free
不训练 projector
不改 transformer weights
同模型 homogeneous MAS
```

非常适合 StateBus 第一阶段。

但是其官方仓库是：

```text
v0.1.0 research release
API 未稳定
```

而且参考实现：

```text
capture
alignment
generation
benchmark
logging
```

大量耦合在一个 `StateBridge` 类里。

StateBus 不应该：

```text
import StateBridge
然后直接 run_item()
```

而应该提取：

```text
HiddenStateCapture
Aligner
LatentProvider
```

三个最小机制。

---

## 1.5 Hidden State 第一版应作为“Advisory Sideband”，不能成为 Authority

最推荐的正式主链插入点：

```text
Executor
   │
   ├──────── ExecutionArtifactRef ─────────┐
   │                                       │
   └──────── LatentStateRef ───────────────┤
                                           ▼
                                      Summarizer
```

其中：

```text
ExecutionArtifactRef
    authoritative / verified facts

LatentStateRef
    advisory reasoning context
```

最终 Claim / Report 仍必须回溯：

```text
Evidence
Artifact
```

而不能说：

```text
“hidden state 告诉我的，所以这个 claim 是事实”
```

。

---

# 2. 当前非文本状态重新分类

建议正式统一术语：

| State Layer | State Object | 解决什么问题 | 当前状态 |
|---|---|---|---|
| Semantic Selection | `SemanticStateRef` | “应该看什么 Evidence？” | 已实现 |
| Decision Sideband | `LogitStateRef` / future `DecisionStateRef` | “这个闭集决策是否可信？” | 已实现 |
| Latent Semantic | `LatentStateRef` | “上游模型内部编码了什么？” | 缺失 |
| Compute Continuation | `KVStateRef` / legacy handle | “哪些 Transformer 计算已经完成？” | 局部实现 |
| Automatic Compute Reuse | APC | “相同 token prefix 能否自动命中？” | 已实现 |

其中：

```text
APC
```

不需要 StateRef。

它属于：

```text
Inference Reuse Policy
```

。

---

# 2.1 重要补充：Semantic Selection、Latent Handoff、Decision State 的因果顺序

前文将 StateBus 非文本状态分为不同类型是正确的，但必须进一步强调：

> **Embedding / Latent / Decision 是类型上并列，执行上串联。**

真实链路：

```text
Task / Query
    ↓
Semantic Retrieval Embedding
    ↓
Selected Evidence / Memory
    ↓
Producer Agent Request
    ↓
Model Input Embeddings
    ↓
Transformer
    ↓
Producer Hidden H_A
    ├─→ Visible Output / Artifact
    └─→ Hidden Capture
             ↓
       StateBridge Alignment
             ↓
       Aligned Latent Z_A→B
             ↓
Consumer Agent Input-Embedding Boundary
             ↓
Transformer
             ↓
Consumer Hidden H_B
             ↓
LM Head
             ↓
Bounded Candidate Logits
             ↓
DecisionState
             ↓
Runtime Policy
   ├─ ACCEPT
   ├─ RETRY
   ├─ EXPAND_EVIDENCE ─► 回到 Semantic Retrieval Embedding
   └─ REPLAN
```

这意味着：

```text
SemanticStateRef
```

主要决定：

```text
“模型接下来看到什么”
```

；

```text
LatentStateRef
```

主要决定：

```text
“上游 Agent 新形成的内部 representation
如何进入下游 Agent”
```

；

```text
DecisionStateRef
```

则是：

```text
“下游模型当前内部状态
在 Runtime 合法动作空间中的低维 belief projection”
```

三者协同，但不应共享同一个 Ref Contract。

---

# 2.2 两种 Embedding 必须明确区分

当前 `SemanticStateRef` 使用的是：

```text
Retrieval / Semantic Embedding
```

例如 Qwen3-Embedding 或 deterministic test encoder。

它和 Transformer 内部：

```text
token_id
→ embedding table
→ input embeddings
```

完全不是同一个概念。

StateBridge 做的是：

```text
Producer deep/final hidden
→ alignment
→ Consumer-compatible continuous input representation
```

所以：

```text
Retrieval Embedding
≠
Transformer Input Embedding
≠
Producer Hidden
≠
Aligned Latent Prefix
```

未来源码和文档应坚持这四个名字，不再统称 “Embedding”。

---

# 2.3 Latent v1 不是 Layer-to-Layer Continuation

Latent v1 的计算图：

```text
Producer:
Input Embedding
→ Layer 1
→ ...
→ Layer N
→ Hidden H_A

H_A
→ Alignment
→ Z_A→B

Consumer:
[Text Embeddings + Z_A→B]
→ Layer 1
→ ...
→ Layer N
```

所以 Consumer **不是**从 Producer 的 Layer N 接着算。

这与：

```text
Communicating Activations
```

这类 mid-layer injection 路线不同。

因此当前 Contract 应描述为：

```text
representation_type = aligned_hidden_prefix
injection_boundary = model_input_embedding
```

而不是模糊地写：

```text
hidden continuation
```

。

---

# 2.4 DecisionState 并不直接消费 LatentState

Decision 的真实数据依赖：

```text
LatentState
→ Consumer Transformer
→ Consumer Hidden
→ LM Head
→ Candidate Logits
→ DecisionState
```

所以 Latent 会影响 Decision，但属于：

```text
causal upstream influence
```

而不是：

```text
Decision worker 读取 LatentStateRef
```

第一版实现不应让 `DecisionPolicy` 直接解释 Hidden tensor；这既没有必要，也会破坏清晰的 authority boundary。

---

# 3. 源码基线

本文主要审计：

```text
statebus/contracts/models.py
statebus/contracts/adaptive.py

statebus/refs/models.py

statebus/state/semantic_state.py
statebus/state/logit_state.py
statebus/state/store.py

statebus/memory/embedding.py
statebus/retrieval/pipeline.py

statebus/control/messages.py
statebus/control/statebus_control.proto
statebus/control/subprocess_worker.py

statebus/integrations/llm.py

statebus/integrations/vllm_kv/registry.py
statebus/integrations/vllm_kv/connector.py
statebus/integrations/vllm_kv/paged_cache.py
```

外部：

```text
YanwenPneg/StateBridge
  methods/state_bridge.py
  models.py
  README.md
  RELEASE_NOTES.md
```

---

# 4. 当前 Embedding 生成链路

`statebus/retrieval/pipeline.py` 中：

```python
@dataclass(frozen=True)
class SemanticChunkRetriever:
    encoder: EmbeddingEncoder = field(
        default_factory=lambda:
            DeterministicEmbeddingEncoder(dims=16)
    )
```

这是第一个需要注意的事实。

默认 encoder 不是神经 embedding 模型。

而是：

```text
16D deterministic hash embedding
```

。

---

# 5. 两套 Embedding Encoder 必须严格分开

当前：

```text
statebus/memory/embedding.py
```

存在两个 backend。

## 5.1 DeterministicEmbeddingEncoder

流程：

```text
text
  ↓
[a-z0-9]+ tokenization
  ↓
SHA256(token) % 16
  ↓
bucket count * token length
  ↓
L2 normalize
```

默认：

```text
dims = 16
encoding = hashed-bow-v1
```

。

它非常适合：

```text
unit test
deterministic CI
cross-process transport test
```

但不能代表：

```text
现代 semantic embedding quality
```

。

---

## 5.2 SentenceTransformerEmbeddingEncoder

当前 local backend：

```text
SentenceTransformer
Qwen3-Embedding-0.6B
```

调用：

```python
model.encode(
    text,
    normalize_embeddings=True,
    convert_to_numpy=True,
)
```

。

这才应该作为：

```text
Semantic State 正式语义实验 backend
```

。

---

# 6. Embedding 实验叙事必须修改

以后任何 headline：

```text
raw evidence -84%
prompt token -49%
9/9 cross-PID
```

都应该显式记录：

```text
embedding_mode
encoder model
model fingerprint
embedding dims
device
dtype
```

至少：

```text
Encoder:
Qwen3-Embedding-0.6B

Backend:
SentenceTransformers

Transport:
shared_memory / mmap

State dtype:
float32
```

否则源码默认：

```text
DeterministicEmbeddingEncoder(dims=16)
```

会给评审造成非常强的：

```text
“你这个 semantic embedding 是 hash stub”
```

印象。

---

# 7. 问题 E-01：真实 embedding 被 round 到 6 位小数

当前：

```python
values = tuple(
    round(float(item), 6)
    for item in vector.tolist()
)
```

。

然后 `DenseSemanticState` 又转成：

```text
float32
```

。

所以链路变成：

```text
model native vector
→ Python float
→ decimal round(6)
→ tuple
→ numpy float32
→ bytes
```

。

这不是 correctness bug。

但它：

```text
增加 Python overhead
增加 object memory
造成不必要的数值量化
```

。

---

## 推荐修改

短期：

```python
values = tuple(float(item) for item in vector.tolist())
```

至少取消 `round()`。

更合理的长期方向：

```text
StructuredEmbedding
```

不要把：

```text
dense vector
```

当成：

```text
tuple[float, ...]
```

长期传递。

应该让：

```text
EmbeddingEncoder
```

可以直接返回：

```text
numpy float32 tensor
+
metadata
```

。

但这个会碰 Memory subsystem，

所以第一阶段只取消 rounding 即可。

---

# 8. 问题 E-02：Encoder Identity 不够强

当前：

```text
encoder_signature
```

大致绑定：

```text
encoder_id
encoder_revision
dims
normalized
dtype
```

。

但是 local SentenceTransformer 当前 encoding：

```text
sentence-transformers:{model_path.name}
```

。

如果：

```text
/models/Qwen3-Embedding-0.6B
```

路径不变，

但里面的：

```text
weights
tokenizer
config
```

变化：

当前 identity 有可能仍然相同。

---

# 9. 为什么这是一个真正的 compatibility 问题

Embedding space compatible 不是：

```text
shape 相同
```

。

即使：

```text
dims = 1024
```

都一样，

不同权重产生的空间也不能混用。

所以未来：

```text
encoder_signature
```

应该升级成真正的：

# EncoderFingerprint

建议：

```text
EncoderFingerprint
├─ encoder_family
├─ model_id
├─ model_revision
├─ local_source_digest / HF commit
├─ config_digest
├─ tokenizer_digest
├─ pooling_strategy
├─ normalization
├─ output_dtype
└─ output_dim
```

然后：

```text
encoder_fingerprint_hash
```

作为 compatibility identity。

---

# 10. 问题 E-03：`SemanticStateRef.manifest_hash` 语义错误

当前 `SemanticStateRef.registry_entry()`：

```python
manifest_hash=self.manifest_id
```

。

这是一个明确的 contract bug。

因为：

```text
manifest ID
```

和：

```text
manifest content hash
```

不是一回事。

当前真正的 hydrate manifest hash 实际保存在 contract/metadata：

```text
hydrate_manifest_hash
```

。

---

## 推荐修改

`SemanticStateRef` 一等字段增加：

```text
manifest_id
manifest_hash
```

Registry：

```text
manifest_hash=self.manifest_hash
```

不要从 metadata 临时取。

---

# 11. 问题 E-04：`SemanticStateRef` 核心身份太依赖开放 `metadata`

当前 Ref：

```python
state_id
state_kind
storage_kind
length
blob_hash
manifest_id
channel
source_doc_hashes
compatibility_hint
exact_replay_ready
metadata: dict
```

。

很多关键 contract 信息都只在：

```text
metadata
```

里面。

问题：

```text
frozen dataclass
```

并不意味着：

```text
metadata dict
```

不可变。

---

## 推荐原则

真正影响：

```text
identity
compatibility
authorization
lifecycle
```

的字段必须一等化。

开放 metadata 只能存：

```text
telemetry
diagnostic
non-authoritative annotations
```

。

---

# 12. 问题 E-05：Consumer Ref 是从 sidecar 自己重建的

当前 UDS：

```python
@dataclass(frozen=True)
class RefHandle:
    ref_id: str
    ref_kind: str
```

。

消费者：

```text
ExecRequest
  ↓
RefHandle(ref_id)
  ↓
semantic_ref_from_sidecar(state_root, ref_id)
  ↓
读取 sidecar
  ↓
构造 SemanticStateRef
```

。

然后：

```text
Ref vs Contract
```

很多字段来自同一个 sidecar。

这形成：

```text
self-consistency validation
```

而不是完整：

```text
end-to-end commitment validation
```

。

---

# 13. 为什么当前 Embedding 还能算成立

因为当前实验假设是：

```text
单机
StateBus 自己的 Runtime
StateBus 自己的 state root
可信 producer
可信 OS user
```

。

实验主要证明：

```text
数值 state 确实跨 PID
另一个进程确实读取
确实改变 candidate selection
```

。

在这个 threat model 下：

```text
ref_id + controlled state root
```

是够用的。

所以这不是：

```text
“9/9 结果无效”
```

。

---

# 14. 为什么 Hidden State 之前必须修

Hidden/KV 与 retrieval embedding 不同：

```text
Embedding:
低敏感度 retrieval feature

Hidden/KV:
模型内部高维状态
可能包含更丰富上下文
且不可人工解释
```

。

2026 的：

**When Latent Agents Lie: KV-Cache Integrity in Multi-Agent LLM Collaboration**

专门证明：

```text
visible text commitment
可能正常

hidden payload
却被修改
```

而只看 visible text 的 verifier 抓不到这种问题。

论文最后采用：

```text
HMAC-SHA256 manifest
```

绑定：

```text
specialist
session
model
visible commitment
tensor metadata
payload digest
```

并在其记录攻击实验中拒绝所有篡改 payload。

所以 StateBus 在引入 LatentState 时：

# 必须让 Controller 持有 payload commitment。

---

# 15. 问题 E-06：CapabilityGrant 只绑定 Ref ID，不绑定 Ref 内容

当前：

```python
CapabilityGrant(
    ...
    input_ref_ids: tuple[str, ...]
)
```

。

没有：

```text
blob hash
contract hash
ref commitment
```

。

于是理论上：

```text
同一个 ref_id
```

对应物理 payload 如果被替换，

Grant 自身无法发现。

---

## 推荐修改

新增：

```text
InputRefCommitment
├─ ref_id
├─ ref_kind
├─ blob_hash
├─ contract_hash
└─ lease_expires_at_ns
```

Grant：

```text
input_ref_commitment_hash
```

或者：

```text
input_ref_commitments[]
```

。

为了控制 Protobuf/Grant 大小，

推荐：

```text
RefSetCommitment
```

：

```text
sorted(ref commitment list)
→ hash
```

。

---

# 16. 问题 E-07：`LayeredStateStore.publish()` 不拒绝重复 Ref ID

当前 publish 没有在最前面：

```python
if ref_id in self.materializations:
    raise ...
```

。

对于 SHM：

```text
_shared_segments[ref_id]
```

还会被新 handle 覆盖。

这可能导致：

```text
state identity rebinding
旧 SHM orphan
metadata overwrite
```

。

---

## 推荐修改

State ID 必须：

# immutable once published

规则：

```text
publish same state_id twice
→ REF_ALREADY_EXISTS
```

。

禁止 update-in-place。

如果状态发生变化：

```text
new state_id
```

。

---

# 17. 问题 E-08：State publish 不是 transactional commit

当前大致：

```text
materialize payload
→ write sidecar
→ put in materializations
```

。

如果：

```text
payload 创建成功
sidecar write 失败
```

可能产生 orphan resource。

---

## 推荐设计

```text
PREPARE
  ↓
allocate temp payload
  ↓
write temp metadata
  ↓
verify payload hash / contract hash
  ↓
atomic rename / commit
  ↓
register ACTIVE
```

失败：

```text
ABORT
→ cleanup
```

。

对 SHM：

可以用：

```text
unique unpublished internal name
→ metadata commit
→ Registry ACTIVE
```

。

---

# 18. 问题 E-09：metadata / HydrateManifest 写入不是 atomic

当前：

```python
Path.write_text(...)
```

。

建议统一：

```text
tmp file
write
flush
fsync
os.replace
```

。

这是：

```text
state sidecar
hydrate manifest
consumption receipt
```

都应共享的 infrastructure。

---

# 19. 问题 E-10：release 不是 idempotent

当前：

```python
handle = self.materializations.pop(ref_id)
```

重复 release 会抛异常。

但真实异步系统：

```text
normal cleanup
timeout cleanup
cancel cleanup
GC cleanup
```

可能竞态。

所以：

```text
release()
```

应当：

```text
ACTIVE -> RELEASED
RELEASED -> RELEASED
missing known tombstone -> RELEASED
```

。

未知 ID 才：

```text
REF_NOT_FOUND
```

。

---

# 20. 问题 E-11：TTL 只验证消费，没有完整物理 sweep

Semantic/Logit consumer：

```text
now >= lease_expires_at
→ reject
```

。

但物理：

```text
SHM
mmap
sidecar
```

仍依赖显式 release / teardown。

未来 Hidden State：

```text
consumer crash
worker OOM
timeout
```

必须自动清理。

---

## 推荐

增加：

```text
StateLeaseManager
```

或最小：

```text
LayeredStateStore.sweep_expired()
```

维护：

```text
created_at
expires_at
status
```

。

---

# 21. 问题 E-12：Named SHM 没有真正 State ACL

当前：

```text
shared memory name
+
sidecar
```

在同 OS user 下可被其他进程打开。

这对当前 trusted container：

```text
可以接受
```

。

但 Latent State 如果想强调：

```text
authorization
```

则：

```text
allowed_consumer_roles
grant hash
task/attempt
```

必须进入 contract。

如果未来要更强 OS isolation：

```text
memfd + FD passing
```

比 named SHM 更自然。

但第一版 Latent 不必马上做到。

---

# 22. 问题 E-13：当前 Semantic producer 已经做了一次 ranking，consumer 又做一次

`SemanticChunkRetriever`：

```text
encode
→ cosine
→ ranked_candidates
```

然后 StateBus：

```text
publish matrix
→ another PID
→ dot product
→ top-k
```

。

这对 mechanism experiment 有意义：

```text
证明 consumer 决策由 numeric state 驱动
```

。

但 product runtime 里存在：

# duplicated semantic computation

。

---

## 推荐定位

保留：

```text
AUDIT / CONTEST mode
```

当前 cross-PID authoritative top-k。

未来：

```text
PRODUCTION mode
```

可以 Router 判断：

```text
如果 producer 已经是 trusted local retriever
无需再跨 PID semantic select
→ 直接使用 producer result
```

。

不要为了“必须使用 StatePool”在所有任务都多走一次进程。

---

# 23. Embedding Hardening 优先级

| Issue | 当前 controlled 严重度 | Latent 前严重度 | 优先级 |
|---|---:|---:|---:|
| manifest ID/hash 混用 | 中 | 中 | P0 |
| RefHandle 不带 commitment | 低 | **高** | P0 |
| Grant 只绑定 ref IDs | 低 | **高** | P0 |
| duplicate ref ID | 中 | **高** | P0 |
| weak encoder fingerprint | 中 | 高 | P0/P1 |
| non-atomic metadata | 低中 | 中高 | P1 |
| non-idempotent release | 低 | 中高 | P1 |
| TTL no sweep | 低 | 中 | P1 |
| mutable metadata identity | 中 | 高 | P1 |
| local embedding round(6) | 低 | — | P2 |
| producer/consumer double score | 低 | — | P2 |

---

# 24. Logit Side Finding：真正应该叫 Decision State

当前 payload：

```text
candidate probabilities
+
other_mass
```

不是：

```text
full vocabulary logits
```

。

因此建议：

```text
LogitStateRef
```

长期改名/语义升级为：

```text
DecisionStateRef
```

或：

```text
DecisionLogitStateRef
```

。

---

# 25. Logit Gate 当前 acceptance 有一个真实语义缺口

当前：

```text
ACCEPT iff

selected == top1 among legal candidates
AND
p1 - p2 >= threshold
```

。

但：

```text
other_mass
```

虽然进入 entropy，

没有进入 accept gate。

例：

```text
A = 0.25
B = 0.10
other_mass = 0.65
```

：

```text
margin = 0.15
```

可能通过。

但：

```text
candidate mass = 0.35
```

说明模型其实认为大量概率不在合法 candidate surface。

---

## 推荐 gate

定义：

\[
M_{candidate} = 1 - p_{other}
\]

接受：

\[
selected=top1
\]

且：

\[
margin \ge \tau_m
\]

且：

\[
M_{candidate} \ge \tau_c
\]

且：

\[
p(selected) \ge \tau_p
\]

。

这样才是真正：

```text
closed-world decision confidence
```

。

---

# 26. Logit 12~36 B 走 SHM 属于 Contest/Audit 设计，不应视为最终 production path

当前：

```text
2 candidates:
12 B

8 candidates:
36 B
```

。

为了几十字节：

```text
SHM
sidecar
UDS
another PID
receipt
release
```

生产上过重。

所以建议未来区分：

```text
audit mode:
physical non-text SHM transfer

production mode:
inline typed binary decision sideband
```

。

这不影响比赛 evidence。

---

# 27. Explicit KV Side Finding：实现是真的，但 data plane 太重

当前代码确实：

```text
vLLM V1 KVConnector
```

真实从 paged KV：

```text
index_select
→ CPU pinned tensor
→ registry
```

Consumer：

```text
CPU
→ GPU
→ index_copy_
```

。

并且有：

```text
token digest
block alignment
task
engine generation
TTL
forward proof
layer count
byte count
one-load proof
```

。

所以不是 fake KV。

---

# 28. Explicit KV 不建议继续作为当前主要开发投入

核心问题：

```text
GPU→CPU
+
CPU→GPU
+
per-layer gather/scatter
+
synchronize
```

。

对大模型、大 prefix，payload 极大。

这不是 StateBus Control Plane 应该继续手搓的领域。

正确长期抽象：

```text
KVStateRef
    │
    └─ provider
        ├─ statebus_local_legacy
        ├─ modern_vllm_offload
        └─ LMCache
```

。

---

# 29. KV 当前还有一个小 contract bug

`KVRegistryConfig`：

```text
one_shot
```

可配置。

但 `begin_consume()` 对：

```text
CONSUMED
```

始终拒绝。

也就是说：

```text
one_shot=false
```

当前没有真正生效。

建议：

```text
要么删除这个配置
要么真正实现 multi-consumer refcount/lifecycle
```

。

第一阶段直接保持 one-shot 并删除假配置更干净。

---

# 30. 现在进入本文核心：为什么需要独立 `LatentStateRef`

Embedding State 表达：

```text
query/candidate relevance geometry
```

Hidden State 表达：

```text
模型在某次生成过程中产生的 internal representation
```

两者：

```text
producer
shape
compatibility
consumer
使用方式
security
```

完全不同。

所以不能：

```text
state_kind="hidden"
```

就复用当前 SemanticStateRef。

---

# 31. `SemanticStateRef` Before

当前核心：

```python
SemanticStateRef:
    state_id

    state_kind

    storage_kind
    length
    blob_hash

    manifest_id

    channel

    source_doc_hashes

    compatibility_hint

    exact_replay_ready

    metadata
```

它的 semantics 明显偏：

```text
retrieval / hydration
```

。

---

# 32. `DenseSemanticStateContract` Before

当前：

```text
state_id

shape

encoder_id
encoder_revision
encoder_signature

source_text_hashes

hydrate_manifest_id
hydrate_manifest_hash

blob_hash
size_bytes

owner_session_id
lease_expires_at_ns
producer_pid

storage_kind

dtype=float32
byte_order=little
row_layout=query_then_candidates
normalized=true
```

。

这个 contract 很完整，

但非常 domain-specific。

---

# 33. 为什么不要做 `SemanticStateRefV2` 直接塞 latent 字段

如果加入：

```text
source_layer
receiver_model
alignment
prefix_length
```

最后会变成：

```text
SemanticStateRef
├─ retrieval fields
├─ hidden fields
├─ maybe KV fields
└─ generic metadata
```

这会彻底失去 type safety。

正确：

```text
RefKind
├─ SEMANTIC_STATE
├─ LOGIT_STATE
├─ LATENT_STATE    # NEW
└─ ...
```

。

---

# 34. `LatentStateRef` After：推荐结构

```python
@dataclass(frozen=True)
class LatentStateRef:
    state_id: str

    task_id: str
    trace_id: str

    producer_step_id: str
    producer_attempt_id: str

    producer_role: str
    allowed_consumer_roles: tuple[str, ...]

    representation_type: str

    storage_kind: StorageKind

    length: int
    blob_hash: str

    contract_hash: str
    commitment_hash: str

    producer_model_fingerprint: str
    receiver_model_fingerprint: str
    tokenizer_fingerprint: str

    prefix_length: int
    hidden_dim: int
    dtype: str

    lease_created_at_ns: int
    lease_expires_at_ns: int

    channel: str = "latent_state"

    schema_version: str = "statebus.latent_state_ref.v1"
```

注意：

```text
source_layer
alignment detail
token lineage
```

更适合放 Contract，

Ref 只保留 compatibility critical summary。

---

# 35. `LatentStateContract` 推荐结构

```python
LatentStateContract:
    schema_version

    state_id

    task_id
    trace_id

    producer_step_id
    producer_attempt_id

    producer_role
    allowed_consumer_roles

    representation_type

    producer_model_fingerprint
    receiver_model_fingerprint
    tokenizer_fingerprint

    shape
    dtype
    byte_order
    tensor_layout

    source_layer

    generated_token_count
    source_token_digest

    extraction_policy
    actual_prefix_tokens
    max_prefix_tokens

    alignment_method
    alignment_version
    alignment_config_hash

    alignment_regularization
    vocabulary_snap_ratio
    prefix_processing_strategy

    visible_commitment_hash

    grant_hash
    authorization_policy_hash

    blob_hash
    size_bytes

    producer_pid

    lease_created_at_ns
    lease_expires_at_ns
```

。

---

# 36. `representation_type`

第一版固定：

```text
aligned_hidden_prefix
```

。

未来可以扩：

```text
raw_hidden_state
aligned_hidden_prefix
pooled_activation
cipher_embedding
kv_semantic_state
```

但第一版：

# 不要做枚举大全。

只实现一个。

---

# 37. Hidden State Wire DType

StateBridge 模型在 CUDA 上一般：

```text
bfloat16
```

。

但跨进程原始 SHM serialization：

```text
bfloat16
```

在 NumPy / portable binary handling 上不如 float16/float32 直观。

第一版建议：

```text
wire dtype = float16
```

消费：

```text
FP16 SHM
→ validate hash
→ torch.from_numpy / tensor
→ cast receiver model dtype BF16
```

。

---

# 38. 为什么 FP16 第一版足够

StateBridge 默认：

```text
K <= 64
```

。

假设：

```text
H = 4096
```

：

```text
64 * 4096 * 2 bytes
≈ 512 KiB
```

。

即使：

```text
H = 5120
```

也约：

```text
640 KiB
```

。

相比你当前：

```text
4096-token KV
≈ 1 GiB
```

完全不是一个量级。

所以：

```text
SHM
```

非常适合 Latent v1。

---

# 39. 建议保留 FP32 reference mode

为了验证数值误差：

```text
LATENT_WIRE_DTYPE=fp32
```

作为 oracle。

正式消融：

```text
FP32
vs
FP16
```

。

如果 quality 无差异：

```text
default FP16
```

。

---

# 40. `visible_commitment_hash`

这是我认为 StateBus + StateBridge 最值得做的一点。

Latent state 不可读。

所以应该绑定：

```text
Producer 可见且可审计的 authoritative output
```

例如 Executor：

```text
ExecutionArtifactRef.artifact_hash
```

。

于是：

```text
visible_commitment_hash
=
hash(
    producer artifact
    or
    visible producer output
)
```

。

---

# 41. 但 `visible_commitment_hash` 不证明 Latent 的语义正确

它只证明：

```text
这个 latent payload
和这个 producer-visible output
属于同一次 committed production
```

。

它不能证明：

```text
latent 内部没有错误推理
```

。

所以：

# Latent State 必须保持 Advisory。

---

# 42. 推荐 `commitment_hash`

```text
commitment_hash =
SHA256(
    state_id
    task_id
    trace_id
    producer_step_id
    producer_attempt_id

    contract_hash
    blob_hash

    producer_model_fingerprint
    receiver_model_fingerprint

    visible_commitment_hash

    lease_expires_at_ns
)
```

。

如果以后跨 trust domain：

```text
HMAC
或
签名
```

覆盖这个 commitment。

---

# 43. `RefHandleV2`

当前：

```python
RefHandle:
    ref_id
    ref_kind
```

Hidden 之前建议升级：

```python
RefHandleV2:
    ref_id
    ref_kind

    blob_hash
    contract_hash

    commitment_hash

    lease_expires_at_ns
```

。

---

# 44. 为什么不直接把整个 `LatentStateRef` 塞进 Protobuf

控制面应该小。

StateBus 的优势就是：

```text
small typed control
+
large payload out-of-band
```

。

因此：

```text
UDS / Protobuf
```

只传：

```text
identity
commitment
operation
```

。

tensor 继续：

```text
SHM / mmap
```

。

---

# 45. CapabilityGrant Before

当前：

```text
grant_id
task_id
session_id
step_id
attempt_id

capability_id
capability_version

input_ref_ids

output_contract_version

workspace_root_id

max_runtime_ms
expires_at_ns

approved_plan_hash
```

。

---

# 46. CapabilityGrant After：Latent 前最小改动

新增：

```text
input_ref_commitment_hash
```

。

或者：

```text
input_ref_commitments
```

。

我更推荐：

```text
RefSetCommitmentHash
```

，因为控制消息更小。

定义：

```text
sort by ref_id
  ↓
canonical list:
(ref_id, kind, blob_hash, contract_hash)
  ↓
SHA256
```

。

---

# 47. `LatentConsumptionReceipt`

建议新增：

```python
@dataclass(frozen=True)
class LatentConsumptionReceipt:
    state_id: str

    consumer_role: str
    consumer_step_id: str
    consumer_attempt_id: str

    consumer_pid: int
    provider_instance_id: str

    receiver_model_fingerprint: str

    contract_hash: str
    payload_hash: str

    prefix_length: int
    hidden_dim: int

    insert_position: int

    prompt_commitment_hash: str

    output_commitment_hash: str

    fallback_used: bool
    fallback_reason: str

    behavioral_effect: str

    consumed_at_ns: int

    schema_version:
        statebus.latent_consumption_receipt.v1
```

。

---

# 48. 不建议继续扩 `SuccessResult`

当前 `SuccessResult` 已经出现：

```text
selected_candidate_ids
selected_scores
selected_row_indices
encoder_signature

gate_action
gate_reason
selected_probability
top_margin
other_mass
...
```

也就是：

```text
Semantic State
+
Logit Gate
```

的 operation-specific 字段都塞在 generic result 里。

如果再加：

```text
latent_prefix_length
alignment_method
insert_position
```

会越来越坏。

---

# 49. 推荐 Control Result 重构方向

Generic：

```text
SuccessResult
├─ output refs
├─ consumed refs
└─ operation_receipt_ref_id
```

。

Semantic：

```text
DenseSemanticSelectionReceipt
```

。

Decision：

```text
DecisionGateReceipt
```

。

Latent：

```text
LatentConsumptionReceipt
```

。

各自作为：

```text
small typed artifact / receipt
```

被 Runtime 读。

第一版不一定马上重构旧 Semantic/Logit，

但 Latent 不要再继续复制旧模式。

---

> **Hidden 位置精度要求**：设计文档中的 “final hidden” 只能作为概念简称。真正实现时必须记录 Provider 的准确 `source_layer / hook_point / pre_or_post_norm`。需要保证捕获语义和 StateBridge reference 一致，再进行 alignment；不能仅因为 tensor shape 为 `[K,H]` 就认定为同一种 hidden representation。

# 50. StateBridge 源码真正做了什么

官方核心：

```text
methods/state_bridge.py
```

。

先看：

```python
class HiddenStateCapture
```

它通过：

```python
last_layer.register_forward_hook(...)
```

每个 forward step 只保存：

```text
last layer
last position
```

。

不是：

```text
所有 layer
所有 token hidden
```

。

所以内存明显小于：

```text
output_hidden_states=True
```

全量存储。

---

# 51. Capture 输出的语义

捕获结果：

```text
[B, generated_steps, hidden_dim]
```

。

同时必须保留：

```text
gen_token_ids
```

因为 StateBridge alignment 需要：

```text
generated hidden state
↔
这些 token 对应的 input embedding
```

配对。

---

# 52. 一个必须纠正的 StateBridge 叙事

StateBridge 并不是：

```text
Sender 完全不生成 token
```

。

源码仍然：

```python
model.generate(...)
```

。

只是：

```text
Agent A generated internal states
```

不必再：

```text
decode text
→ serialize text
→ Agent B tokenize
→ Agent B embed
```

作为唯一 communication channel。

更准确：

> StateBridge 消除的是 agent-to-agent communication 的离散文本瓶颈，而不是 sender-side autoregressive generation 本身。

---

# 53. StateBridge Hidden Selection Policy

官方：

```text
优先找 </think>
```

然后：

```text
只保留 </think> 后面的 hidden
```

并最多：

```text
last K
K = max_prefix_tokens
default 64
```

。

如果找不到：

```text
last K from all generated hidden
```

。

---

# 54. 这个逻辑不能硬编码进 StateStore

应该显式变成：

```text
LatentExtractionPolicy
```

第一版：

```text
post_think_last_k
```

可选：

```text
last_k
```

以后：

```text
attention_selected
pooled
```

再扩。

---

# 55. StateBridge Alignment

源码真实步骤：

```text
H = sender hidden states
E = embedding(token_ids)
```

然后：

### Step 1

```text
center H
center E
```

。

### Step 2

```text
Cov_H
Cov_E
+
regularization
```

。

### Step 3

```text
eigendecomposition
Cov^-1/2
```

完成 whitening。

### Step 4

```text
M = H_w^T E_w
SVD(M)
R = U V^T
```

Orthogonal Procrustes。

### Step 5

```text
恢复 receiver embedding covariance / mean
```

。

### Step 6

```text
norm calibration
```

到 input vocabulary embedding mean norm。

### Step 7

```text
vocabulary anchoring
```

：

```text
aligned vector
→ cosine against vocab embedding matrix
→ nearest vocab embedding
→ linear mix
```

默认：

```text
snap_ratio=0.3
```

。

---

# 56. 为什么 StateBridge 不只是“hidden state shape 一样所以直接塞进去”

Transformer final hidden state：

```text
H dimension
```

虽然和 embedding dimension 一样，

但两个 representation distribution 不一样。

直接：

```text
final hidden
→ inputs_embeds
```

往往 OOD。

StateBridge 的核心创新就是：

```text
distribution / geometry alignment
```

而不是 tensor transport。

---

# 57. StateBridge 计算成本要诚实分析

Alignment 包含：

```text
H × H covariance
eigh
SVD
```

近似：

```text
O(H^3)
```

。

Vocabulary anchoring：

```text
K aligned states
×
V vocabulary embeddings
×
H
```

约：

```text
O(K V H)
```

。

所以：

```text
Qwen3-32B
```

不是第一版最理想实验对象。

---

# 58. 推荐第一模型

```text
Qwen3-4B
```

第一。

然后：

```text
Qwen3-8B
```

。

完成：

```text
correctness
transport
StateBus lifecycle
```

之后再碰 32B。

StateBridge 官方本身也报告 Qwen3-4B/8B/32B，

但其完整实验环境是多 GPU research setup。

---

# 59. StateBridge reference code 不应该原样 copy

其仓库明确：

```text
v0.1.0
research release
public API not stable
```

。

而且：

```text
benchmark loop
GPU cleanup
generation
alignment
answer parsing
```

耦合在一起。

StateBus 应该只借：

```text
method
```

不依赖：

```text
their orchestration runtime
```

。

---

# 60. 推荐拆成三个 Provider 组件

```text
HFStateBridgeProvider
    │
    ├─ HiddenStateCaptureSession
    │
    ├─ StateBridgeAligner
    │
    └─ LatentPrefixInjector
```

。

---

# 61. 组件 1：`HiddenStateCaptureSession`

接口概念：

```python
capture = provider.begin_capture(
    model_fingerprint=...,
    extraction_policy=...
)

result = provider.generate(...)

captured = capture.finish()
```

输出：

```text
hidden_seq
token_ids

source_layer
generated_token_count
capture_time
```

。

---

# 62. Capture Provider 必须知道 model fingerprint

因为：

```text
hidden space
```

与：

```text
具体 weights
```

强相关。

所以：

```text
model name
```

不够。

至少：

```text
model config hash
tokenizer hash
weight revision
hidden dim
architecture
```

。

---

# 63. 组件 2：`StateBridgeAligner`

接口：

```python
align(
    hidden_seq,
    token_ids,
    receiver_embedding_space,
    alignment_config,
) -> AlignedLatentTensor
```

。

同时返回：

```text
AlignmentReceipt
```

。

---

# 64. `AlignmentReceipt`

建议：

```text
alignment_method
alignment_version

input_shape
output_shape

regularization
snap_ratio

input_hidden_norm
output_prefix_norm
target_embedding_norm

source_model_fp
receiver_model_fp

source_token_digest

alignment_ms
```

。

它属于 telemetry / audit，

不是 Ref identity 的所有字段。

---

# 65. StateBridge 性能优化：Receiver vocab normalized matrix 应缓存

官方每次：

```python
F.normalize(self.vocab_embeds)
```

然后：

```text
aligned @ vocab^T
```

。

StateBus provider 生命周期更长。

可以提前：

```text
normalized_vocab_embeddings
```

常驻。

减少每次 handoff 重复 normalize。

---

# 66. 还可以缓存 receiver embedding statistics

例如：

```text
target_norm
embedding mean / static properties
```

。

但：

```text
message-specific Procrustes
```

仍然需要每次算。

不要错误缓存：

```text
R
```

跨任意 message，

除非实验验证 alignment 能稳定复用。

---

# 67. 组件 3：`LatentPrefixInjector`

职责：

```text
normal receiver prompt
  ↓
tokenizer
  ↓
input embeddings
  ↓
insert aligned prefix
  ↓
attention mask extension
  ↓
model.generate(inputs_embeds=...)
```

。

这和 StateBridge `_generate_with_prefix()` 对应。

---

# 68. Injection Position 必须成为 contract

StateBridge 通过：

```text
EMBEDDING_HINT_MARKER
```

在 prompt 中找到插入点。

StateBus 不应该依赖某个 hard-coded字符串 marker。

第一版可用：

```text
LatentInjectionPolicy
```

：

```text
PREPEND
AFTER_SYSTEM
BEFORE_USER_QUERY
AT_TEMPLATE_MARKER
```

。

建议第一版：

```text
AT_TEMPLATE_MARKER
```

但 marker identity 由 prompt/template manifest 绑定。

---

# 69. Hidden State 与 StateBus 生命周期映射总图

```text
Producer Role
    │
    ▼
HFStateBridgeProvider.generate_and_capture()
    │
    ├─ normal visible output / Artifact
    │
    └─ raw hidden sequence + token IDs
              │
              ▼
      LatentExtractionPolicy
              │
              ▼
      StateBridgeAligner
              │
              ▼
        aligned [K,H]
              │
              ▼
     publish_latent_state()
              │
              ▼
       LayeredStateStore
        ├─ SHM
        └─ mmap fallback
              │
              ▼
        LatentStateRef
              │
              ▼
   RefHandleV2 over Protobuf/UDS
              │
              ▼
      LatentHFProviderWorker
              │
      validate commitment/grant
              │
      resolve payload read-only
              │
      FP16 -> model dtype/GPU
              │
              ▼
      LatentPrefixInjector
              │
              ▼
    receiver.generate(inputs_embeds)
              │
              ▼
 LatentConsumptionReceipt
              │
              ▼
 Runtime validates receipt
              │
              ▼
         release()
```

。

---

# 70. `publish` 映射

当前可以复用：

```text
LayeredStateStore.publish()
```

的大方向。

新增：

```python
publish_latent_state(...)
```

负责：

```text
shape validation
finite validation

wire dtype cast

contract creation

payload hash
contract hash
commitment hash

StateStore publish

Ref creation
```

。

---

# 71. `LayeredStoragePolicy`

新增：

```text
object_kind = LATENT_HIDDEN_STATE
```

第一版 preference：

```text
SHARED_MEMORY
→ MMAP_FILE
```

。

不要优先：

```text
INLINE
```

。

虽然 K=64 payload 不巨大，

但几十万字节不适合 Protobuf control plane。

---

# 72. `Ref`

新增：

```text
RefKind.LATENT_STATE
```

不要复用：

```text
RefKind.SEMANTIC_STATE
```

。

因为 Policy / Consumer 要能够：

```text
明确区分 retrieval vector
和 model-internal latent state
```

。

---

# 73. `UDS`

当前：

```text
SubprocessExecutorTransport
+
typed Protobuf
```

模式值得复用。

但：

# 当前 `subprocess_worker.py` 不应该直接变成 Latent Model Worker。

它现在是：

```text
轻量
单请求
semantic select
logit gate
```

。

如果让它 import：

```text
Qwen3-4B / 8B
```

会破坏其职责和资源模型。

---

# 74. 推荐新增 `LatentHFProviderWorker`

它是：

```text
long-lived model hosting process
```

或者第一版：

```text
single-process provider
```

。

真正跨进程版再：

```text
UDS provider worker
```

。

关键是：

```text
Control Plane 可以复用

Worker Implementation 不复用
```

。

---

# 75. Consume Validation 顺序

Consumer 收到 Ref 后必须：

```text
1. Validate ControlHeader
   task / trace / step / attempt

2. Validate Grant
   grant not expired
   capability allowed

3. Validate RefSet commitment

4. Validate LatentStateRef
   ref kind
   blob hash
   contract hash

5. Load sidecar / Contract

6. Verify sidecar contract hash
   against RefHandle

7. Verify consumer role
   ∈ allowed_consumer_roles

8. Verify model fingerprint

9. Verify tokenizer fingerprint

10. Verify lease

11. Map payload read-only

12. Hash payload

13. Reshape [K,H]

14. Check finite

15. Cast to receiver dtype/device

16. Inject

17. Generate

18. Receipt
```

。

---

# 76. 为什么不能像当前 Semantic Consumer 一样只给 `expected_encoder_signature`

Hidden compatibility 比 embedding selection 更复杂。

至少包括：

```text
producer model
receiver model
tokenizer
hidden dim
representation type
alignment method
prompt/template injection policy
```

。

所以：

```text
expected_latent_compatibility_hash
```

更合理。

---

# 77. Receiver Model Compatibility v1

第一版只允许：

```text
producer_model_fingerprint
==
receiver_model_fingerprint
```

。

也就是：

# homogeneous same weights

这和 StateBridge 当前公开 scope 一致。

即使同模型，

仍需要 Alignment。

因为：

```text
final hidden space
!=
input embedding distribution
```

。

---

# 78. Heterogeneous 模型以后再做

例如：

```text
Qwen3-4B
→ Qwen3-8B
```

不能因为：

```text
同 tokenizer
```

就认为 latent compatible。

这需要：

```text
trained projector
dense alignment
cross-model transformation
```

属于 C2C / heterogeneous latent research。

不是 v1。

---

# 79. Receipt

Consumer 返回：

```text
LatentConsumptionReceipt
```

不是简单：

```text
SUCCESS
```

。

Runtime 要证明：

```text
哪个 state
被哪个 role
哪个 provider
以多少 prefix length
真正注入
```

。

这和你现有：

```text
Embedding actual-use
Logit actual-use
KV forward proof
```

精神一致。

---

# 80. `behavioral_effect` 怎么定义才不造假

不要单次请求写：

```text
quality_improved=true
```

。

消费回执只证明：

```text
USED
```

。

例如：

```text
prefix_injected_and_receiver_forward_observed
```

。

“改善质量”只能通过：

```text
A/B benchmark
```

证明。

---

# 81. 更强 actual-use proof

可以在专项实验记录：

```text
no_latent output hash
latent output hash

or

receiver first-step logits digest
```

。

但不能把：

```text
输出不同
```

等同于：

```text
更好
```

。

它只证明：

```text
latent had behavioral effect
```

。

---

# 82. `release`

Latent 第一版推荐：

```text
one-shot
```

。

Consumer：

```text
close mapped view
```

。

Runtime：

```text
receipt validated
→ state_store.release()
```

。

如果 consumer crash：

```text
TTL sweep
```

清理。

---

# 83. 不要让 Consumer 自己 unlink payload

生命周期 owner 应该是：

```text
Runtime / StateStore
```

。

否则：

```text
consumer success
receipt还没回
payload先被删
```

会破坏 audit / retry。

---

# 84. `StateConsumptionRecord` 是否复用

当前：

```text
StateConsumptionRecord
```

字段偏：

```text
read_field_ids
selected_ids
decision surface hash
```

明显是 selection-state 风格。

不建议硬塞 Latent。

---

## 推荐

第一版：

```text
LatentConsumptionReceipt
```

独立。

以后如果需要统一 UI：

```text
StateConsumptionRecordV2
```

只保留 generic core：

```text
state_ref
consumer
operation
effect
downstream refs
time
receipt_hash
```

详细信息仍在专用 receipt。

---

# 85. StateBridge Capture → StateBus 映射

| StateBridge | StateBus 设计 |
|---|---|
| `HiddenStateCapture` | `HiddenStateCaptureSession` |
| forward hook last layer | HF provider-local hook |
| `gen_hidden_seq` | unpublished provider-local tensor |
| `gen_token_ids` | source token lineage |
| last K / post-think | `LatentExtractionPolicy` |
| `_align_hidden_sequence` | `StateBridgeAligner` |
| `aligned_embeds` | publishable payload |
| `_process_prefix` | `LatentPrefixTransform` |
| `current_prefix` | `LatentStateRef` payload |
| `_generate_with_prefix` | `LatentPrefixInjector` |
| `inputs_embeds` | receiver provider execution |
| agent trace | `LatentConsumptionReceipt` + telemetry |

---

# 86. StateBus 当前哪些东西可以直接复用

可以复用：

```text
LayeredStateStore backend abstraction

SHM / mmap data plane

blob hash

typed Protobuf / UDS framing

ControlHeader:
trace/task/step/attempt/role

heartbeat / timeout / cancel pattern

CapabilityGrant authority concept

Ref registry concept

lease concept

State actual-use / consumption audit idea
```

。

---

# 87. 哪些只能借模式、不能直接复用实现

```text
SemanticStateRef
DenseSemanticStateContract

semantic_ref_from_sidecar

semantic_select_v1 worker

Semantic SuccessResult fields

HydrateManifest

query_then_candidates layout
```

。

这些都是 retrieval-specific。

---

# 88. 哪些必须新增

```text
RefKind.LATENT_STATE

LatentStateRef

LatentStateContract

LatentConsumptionReceipt

ModelFingerprint
TokenizerFingerprint

LatentExtractionPolicy

AlignmentConfig

StateBridgeAligner

LatentInferenceProvider

HFStateBridgeProvider

LatentPrefixInjector

Latent provider worker / process contract
```

。

---

# 89. 不建议侵入现有 `LLMClient`

当前：

```python
LLMClient.complete(messages, ...)
```

是标准：

```text
text chat
```

抽象。

如果加：

```python
prompt_embeds=
capture_hidden=
alignment=
```

会污染所有：

```text
DeepSeek API
OpenAI-compatible
vLLM
```

backend。

---

# 90. 推荐单独 Provider Protocol

```python
class LatentInferenceProvider(Protocol):

    def describe_model(self) -> ModelFingerprint:
        ...

    def generate_and_capture(
        self,
        ...
    ) -> CapturedLatentSource:
        ...

    def generate_with_latent_prefix(
        self,
        ...,
        latent_ref: LatentStateRef,
    ) -> LatentGenerationResult:
        ...
```

。

第一实现：

```text
HFStateBridgeProvider
```

。

---

# 91. 为什么 HF Provider 第一版更安全

StateBridge 原生就是：

```text
Hugging Face Transformers
inputs_embeds
forward hook
```

。

StateBus 当前 vLLM 0.9.2 虽然 API 层已经存在：

```text
prompt_embeds
```

处理对象，

但 0.9.x 官方 Prompt Embedding 文档明确曾限制：

```text
V0 engine only
```

。

vLLM 后来专门做了：

```text
Prompt Embeddings Support in V1 Engine
```

RFC / implementation。

因此：

```text
当前 vLLM 0.9.2 + StateBus V1 KV connector
```

不能假设：

```text
prompt_embeds 可直接稳定使用
```

。

---

# 92. vLLM 后续 compatibility probe

独立做：

```text
VLLM-LATENT-PROBE
```

检查：

```text
0.9.2 exact build

V1 engine

Qwen3

--enable-prompt-embeds

offline / Completions / Chat

mixed text + embeds

CUDA graph

prefix caching interaction

tool calling interaction
```

。

不阻塞 HF Latent 实验。

---

# 93. 最新 vLLM 对未来是好消息

2026 最新 vLLM 已支持：

```text
--enable-prompt-embeds
```

并且在线：

```text
Completions
Chat Completions
```

都能接：

```text
base64 serialized prompt embeddings
```

甚至混合 text / prompt embeds。

所以长期：

```text
vLLM native latent provider
```

是有现实路径的。

但这属于：

```text
版本升级后的 provider
```

而不是第一阶段 StateBus core requirement。

---

# 94. StateBridge 第一阶段 benchmark 还必须加入 Causal Audit

只做：

```text
Text
vs
Latent
```

然后看到：

```text
Latent +3%
```

还不够。

2026 的：

**When Does Latent Communication Pay? A Causal Audit of Relayed KV Caches in Multi-Agent LLMs**

指出：

> latent benchmark delta 并不能自动证明 receiver 使用的是对应 example 的语义状态。

他们使用：

```text
matched state
mismatched-example state
zero state
moment-matched random state
```

做 causal audit。

这个实验设计非常值得直接借。

---

# 95. StateBus Latent 必须至少有四个 control

```text
TEXT
    正常文本 handoff

MATCHED_LATENT
    当前样本真实 latent

MISMATCHED_LATENT
    其他样本 latent

ZERO_LATENT
    全零相同 shape
```

最好再：

```text
MOMENT_MATCHED_RANDOM
```

。

---

# 96. 为什么 Mismatched 特别重要

如果：

```text
Matched 80
Mismatched 79
Zero 60
```

说明：

```text
有一个 prefix
```

很重要，

但：

```text
是不是这个样本对应的 latent semantic content
```

未被证明。

如果：

```text
Matched 80
Mismatched 55
Zero 50
```

才有更强证据：

```text
example-specific information
```

真的在通过 latent channel。

---

# 97. StateBus 的“非文本实际消费”实验因此可以比 StateBridge 本身更严谨

你可以把：

```text
payload hash
state ID
producer/consumer
Ref commitment
```

和：

```text
matched/mismatched causal control
```

结合。

这会非常适合比赛“真实使用非文本状态”的要求。

---

# 98. Latent Integrity Test Matrix

必须加入：

```text
T1
payload bit flip
→ reject

T2
sidecar blob hash tamper
→ authoritative RefHandle mismatch → reject

T3
same state_id republish
→ reject

T4
expired lease
→ reject

T5
wrong consumer role
→ reject

T6
wrong model fingerprint
→ reject

T7
wrong tokenizer fingerprint
→ reject

T8
wrong grant commitment
→ reject

T9
consumer crash
→ TTL cleanup

T10
mismatched sample latent
→ allowed only in explicit causal benchmark mode
```

。

---

# 99. Latent Quality Test Matrix

先用 StateBridge 已验证 workload。

推荐：

```text
GPQA
MedQA

MBPP+
HumanEval+
```

。

但第一轮只需要：

```text
一个 QA
+
一个 code
```

。

例如：

```text
MedQA
MBPP+
```

。

---

# 100. 为什么不一开始用 StateBus 当前 retrieval dataset

因为当前内部任务主要依赖：

```text
verified data
structured extraction
evidence
```

。

这些任务不一定：

```text
需要上游 Agent 的 private reasoning
```

。

如果 downstream 本来只需要：

```text
verified artifact
```

Hidden State 可能没有增益。

这会导致：

```text
错误结论：
Hidden State 没用
```

。

---

# 101. Native StateBridge Reproduction 设计

固定：

```text
Qwen3-4B
same prompts
same seed
same temperature/top_p
```

比较：

```text
TextMAS

StateBridge reference

StateBus Latent State
```

。

目标：

```text
StateBus 封装后
方法 quality 不显著低于 reference
```

而不是第一步就追求超过 StateBridge。

---

# 102. Metrics

必须记录：

### Quality

```text
accuracy
pass@1
```

。

### Communication

```text
sender visible handoff tokens
wire text bytes

latent payload bytes

control bytes
```

。

### Latency

```text
sender generation

capture overhead

alignment time

publish time

UDS control

resolve time

H2D

injection setup

receiver generation

E2E
```

。

### Memory

```text
GPU peak
CPU/SHM bytes
```

。

### Reliability

```text
fallback count
contract reject
lease expiry
consumer failure
```

。

---

# 103. Important Metric：不要把 Latent “prefix token count”直接当普通 token

StateBridge：

```text
K aligned vectors
```

在 receiver attention 中占：

```text
K sequence positions
```

。

但它没有：

```text
token IDs
```

。

所以报告应该分：

```text
text tokens

latent positions

latent bytes
```

。

不要把：

```text
64 latent positions
```

简单写成：

```text
64 tokens
```

。

---

# 104. Break-even Analysis

对：

```text
K = 8, 16, 32, 64
```

测试：

\[
C_{latent}
=
T_{capture}
+
T_{align}
+
T_{publish}
+
T_{consume}
\]

对比：

\[
C_{text}
=
T_{decode\ handoff}
+
T_{serialize}
+
T_{retokenize}
+
T_{recompute}
\]

。

注意 StateBridge Sender 本身仍 generate，

所以 savings 主要来自：

```text
handoff representation
receiver side text processing
information preservation
```

而不是 Sender decode 完全消失。

---

# 105. `StateBridge + StateBus` 真正可形成的项目创新

不是：

```text
我们也实现 StateBridge
```

。

而是：

> **StateBus 将不可解释的 latent representation 转化为一个具有 identity、model compatibility、authorization、lease、payload commitment、visible commitment、actual-use receipt 和 fallback 的 Runtime State Object。**

StateBridge解决：

```text
怎么把 hidden 对齐到 inputs_embeds
```

StateBus解决：

```text
这个 state
是谁的
能给谁
何时有效
是否被篡改
是否真的被使用
失败如何回退
如何审计
```

。

这个组合有明确系统价值。

---

# 106. 更进一步：Latent State 不应自动获得 Authority

建议 Policy：

```text
LatentStateTrustClass:
    ADVISORY
```

第一版只有：

```text
ADVISORY
```

。

禁止：

```text
Latent-only final fact
Latent-only capability authorization
Latent-only memory exact replay
```

。

---

# 107. Mainline 第一接入点

最推荐：

```text
Executor
→ Summarizer
```

。

原因：

1. Executor 已经产生较丰富语义；
2. Summarizer 是 natural language consumer；
3. 同时已经有 verified Artifact；
4. Latent 可以是 sideband；
5. 失败直接 fallback text/artifact；
6. 不影响 Planner authority。

---

# 108. 不推荐第一接入 Planner → Runtime

Planner 产出的：

```text
PlanProposal
```

必须：

```text
可读
可审计
可 PlanPolicy validate
```

。

如果 Planner 只输出 latent：

```text
Runtime 不知道它计划了什么
```

直接破坏 StateBus 最核心 authority model。

所以：

# Planner semantic plan 必须保持 typed/visible。

---

# 109. 不推荐用 Latent 替代 EvidencePack

EvidencePack 负责：

```text
source
locator
provenance
```

。

Hidden State 无法替代。

正确：

```text
Evidence / Artifact
= authoritative

Latent
= advisory
```

。

---

# 110. Fallback

所有 latent path 必须：

```text
fail open to safe text path
```

。

不是：

```text
contract fail
→ whole task fail
```

。

例如：

```text
capture unavailable
alignment error
model mismatch
lease expired
payload invalid
inputs_embeds unsupported
```

都：

```text
TEXT_FALLBACK
```

。

同时留下：

```text
fallback reason
```

。

---

# 111. 未来 StateRepresentationPolicy

最终 Router 可以：

```text
state representation decision

TEXT
SEMANTIC_SELECTION
LATENT_ADVISORY
```

。

注意：

```text
APC/KV
```

不放这里。

它们属于：

```text
InferenceReusePolicy
```

。

---

# 112. 第一阶段代码文件建议

新增：

```text
statebus/contracts/latent.py

statebus/state/latent_state.py

statebus/integrations/latent/
├── __init__.py
├── base.py
└── hf_statebridge.py

statebus/control/latent_worker.py
```

测试：

```text
tests/test_latent_contract.py
tests/test_latent_state_store.py
tests/test_latent_state_cross_process.py
tests/test_latent_hf_provider.py
tests/test_latent_fallback.py
tests/test_latent_integrity.py
```

。

---

# 113. 现有文件最小修改

```text
statebus/contracts/models.py
    + RefKind.LATENT_STATE

statebus/refs/models.py
    + LatentStateRef

statebus/state/store.py
    + LATENT_HIDDEN_STATE preference
    + hardening

statebus/control/messages.py
statebus/control/statebus_control.proto
    + commitment-aware Ref handle / generic receipt ref

statebus/contracts/adaptive.py
    + ref commitment binding to grant

statebus/runtime/...
    later mainline sideband policy
```

。

---

# 114. 不建议第一阶段修改

```text
statebus/integrations/llm.py
```

大接口。

保持：

```text
normal LLMClient
```

不动。

新增：

```text
LatentInferenceProvider
```

旁路。

---

# 115. 实施 Slice L0：State Foundation Hardening

目标：

```text
不增加 Hidden State
不改变现有 Embedding 行为
```

修改：

```text
fix manifest ID/hash

EncoderFingerprint

duplicate state ID reject

atomic metadata / manifest

idempotent release

Ref commitment

Grant binds ref commitment
```

。

---

# 116. L0 Gate

必须：

```text
existing Embedding 9/9 tests PASS

existing controlled benchmark PASS

existing Logit tests PASS

existing Memory tests PASS

existing KV tests PASS
```

。

这条非常重要：

# Hidden State 不能破坏旧测试。

---

# 117. Slice L1：Latent Contract Only

新增：

```text
RefKind.LATENT_STATE
LatentStateRef
LatentStateContract
LatentConsumptionReceipt
```

测试：

```text
serialization
canonical hash
compatibility
expiry
role authorization
model mismatch
```

。

不加载模型。

---

# 118. Slice L2：Cross-process Synthetic Latent

生成：

```text
random [K,H] FP16
```

。

然后：

```text
publish
→ RefHandle
→ UDS
→ another process
→ resolve
→ hash
→ receipt
→ release
```

。

这一步证明：

# StateBus Latent Lifecycle

而不是证明模型能力。

---

# 119. Slice L3：HF StateBridge Provider

接：

```text
Qwen3-4B
```

实现：

```text
capture
alignment
inputs_embeds
```

。

先跑 StateBridge native task。

---

# 120. Slice L3 Gate

至少：

```text
TextMAS
Reference StateBridge
StateBus Latent

Matched / mismatched / zero
```

。

如果：

```text
StateBus Latent
明显劣于 StateBridge reference
```

先查封装/serialization/FP16/injection，

不要继续接主线。

---

# 121. Slice L4：Executor → Summarizer Mainline

模式：

```text
STATEBUS_LATENT_MODE=
off
telemetry
enabled
```

。

更后面：

```text
adaptive
```

。

第一版：

```text
enabled
```

也必须有 text fallback。

---

# 122. Slice L5：vLLM Prompt Embeds Probe

只做 probe：

```text
current pinned 0.9.2

V1

Qwen3

prompt embeds
```

。

如果不支持：

```text
记录 NO-GO
```

不改当前 vLLM。

如果支持：

再设计：

```text
VLLMLatentProvider
```

。

---

# 123. 不要把 vLLM Probe 和 StateBridge PoC 绑死

正确依赖：

```text
L0
 ↓
L1
 ↓
L2
 ↓
L3 HF
 ↓
L4 mainline

L5 vLLM probe
独立
```

。

这样当前旧 vLLM stack 不会卡住创新。

---

# 124. 未来替代方案：CIPHER

ICLR 2024：

**Let Models Speak Ciphers**

不是传 final hidden。

它利用：

```text
raw output distribution
→ expected embedding
```

作为 communication。

优点：

```text
不需要复杂 Hidden Hook
无额外训练
已是正式 ICLR
```

。

但它更接近：

```text
rich Decision / Belief State
```

而不是：

```text
full internal reasoning state
```

。

可以作为：

```text
LatentState provider alternative
```

但不是当前第一实现。

---

# 125. 未来替代方案：Communicating Activations

ICML 2025：

```text
Agent A intermediate activation
+
Agent B intermediate activation
↓
f(A,B)
↓
B 继续后半层 forward
```

。

这是真正 activation communication。

论文报告最高约：

```text
27% improvement
< 1/4 compute
```

。

但它要求：

```text
暂停模型中间 layer
跨模型组合 activation
继续 forward
```

对 vLLM serving 侵入远大于 StateBridge。

所以研究价值高，

第一版不做。

---

# 126. 未来替代方案：Heterogeneous Dense Latent Communication

2026：

```text
Qwen3-4B/8B/14B
不同模型方向
```

通过：

```text
cross-model cache transformation
+
training
```

实现 heterogeneous communication。

它说明：

```text
未来 heterogeneous StateBus Latent
```

有研究路径。

但第一版 homogeneous 足够。

---

# 127. 未来 Compute-State 方向仍与 Latent 分离

例如：

```text
KVCOMM
C2C
compressed latent KV
LMCache
```

都可以继续研究。

但项目树上应该是：

```text
Latent Semantic Handoff
    StateBridge provider

Compute Reuse
    APC
    KVStateRef
    LMCache / KVCOMM
```

两条线。

---

# 128. 一个非常重要的实验原则：需要 Private Information Dependency

最新 causal audit 还有一个关键结论：

如果 receiver 本来已经拥有 sender 的全部关键信息，

那么：

```text
matched latent
```

不一定比：

```text
mismatched latent
```

更好。

这不是 latent failure，

而是 task 没有：

```text
information dependency
```

。

所以 Latent benchmark 必须选择：

```text
Receiver 真的需要 Sender 产生的信息
```

的任务。

---

# 129. StateBus 内部 Latent Task 设计原则

例如：

```text
Executor
拥有：
raw execution details / derived insight

Summarizer
不重新得到所有 intermediate reasoning text
只得到：
Artifact
+
Latent sideband
```

。

这样才能测试：

```text
latent 是否补充 artifact 中没有完整显式表达的 reasoning context
```

。

---

# 130. 但不要人为隐去 authoritative facts 让 Latent 作弊

Artifact 仍必须包含：

```text
最终 claim 所需事实
```

。

Latent 应增加：

```text
reasoning quality
aggregation
focus
```

而不是：

```text
唯一携带某个 Gold answer
```

。

否则实验不公平。

---

# 131. 推荐最终 State Contract 分层

```text
StateRef Family

SemanticStateRef
    retrieval selection

DecisionStateRef
    bounded numeric gate

LatentStateRef
    advisory neural representation

KVStateRef
    compute continuation
```

它们共享：

```text
state_id
storage
blob hash
contract hash
lease
authorization
commitment
lifecycle
```

但不共享：

```text
业务语义字段
```

。

---

# 132. 什么时候再抽 `StateRefBase`

不是现在。

先等：

```text
SemanticStateRef hardening
+
LatentStateRef v1
```

都稳定。

如果发现：

```text
10+ 一样的字段
```

再抽：

```text
StateRefBase
```

。

避免现在为了 OO 美观做大迁移。

---

# 133. 最终改造优先级

## P0 — Hidden 前必须

```text
Semantic manifest hash fix

immutable state_id

Ref commitment

Grant binds ref commitment

EncoderFingerprint

Latent separate RefKind / Contract
```

。

## P1 — 同期 hardening

```text
atomic sidecar/manifest
idempotent release
lease sweep
role authorization
Latent receipt
```

。

## P2 — 性能/整洁

```text
remove embedding round(6)
reduce duplicate semantic ranking

generic SuccessResult receipt ref

tiny Decision State inline mode
```

。

## Future

```text
vLLM latent provider
heterogeneous alignment
LMCache
KVCOMM
C2C
```

。

---

# 134. 最终推荐的第一版架构

```text
                        StateBus
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
      Authoritative Plane         Advisory Neural Plane
              │                         │
      Evidence / Artifact         LatentStateRef
              │                         │
              │                  HFStateBridgeProvider
              │                         │
              └────────────┬────────────┘
                           ▼
                       Consumer
                           │
                           ▼
                     Verified Output
```

StateBus policy：

```text
Latent invalid
→ ignore/fallback

Artifact invalid
→ reject task
```

这两个 trust level 不同。

---

# 135. 最终项目叙事

不要再：

> “我们有 Embedding、Logit、APC、KV，所以有很多非文本状态。”

更准确：

> **StateBus 将非文本中间状态分为语义选择状态、决策状态、潜在语义状态与计算状态。Embedding 用于选择可恢复证据，Decision State 用于闭集决策门控，LatentState 用于跨 Agent 传递连续内部表示，而 APC/KV 仅负责复用已经完成的 Transformer 计算。所有显式状态通过统一的 identity、commitment、authorization、lease、actual-use receipt 和 fallback 机制治理。**

其中：

```text
StateBridge
```

解决：

```text
hidden → compatible receiver embedding
```

StateBus解决：

```text
hidden state
如何成为一个
可寻址
可验证
可授权
可消费证明
可回退
可清理
的 Runtime object
```

。

这才是最值得实现的组合。

---

# 136. 下一阶段建议

下一步仍然不要马上改完整主线。

建议按：

```text
LATENT-HARDEN-01
    State foundation hardening

LATENT-CONTRACT-01
    Ref/Contract/Receipt

LATENT-XPID-01
    synthetic cross-process lifecycle

LATENT-HF-01
    StateBridge provider reproduction

LATENT-MAINLINE-01
    Executor→Summarizer advisory sideband

LATENT-VLLM-PROBE-01
    current vLLM prompt_embeds capability probe
```

拆成独立 Slice。

其中：

```text
任何 Slice
```

都必须：

```text
existing internal tests PASS
existing Embedding evidence semantics unchanged
existing Logit/KV paths unchanged
```

。

---

# 137. 参考资料

## StateBus current main

Repository:

https://github.com/qcrs/os

Pinned commit:

https://github.com/qcrs/os/commit/8bfc6464ec236c0e121911095fc283129b0e7696

Key files:

https://github.com/qcrs/os/blob/master/statebus/state/semantic_state.py

https://github.com/qcrs/os/blob/master/statebus/state/store.py

https://github.com/qcrs/os/blob/master/statebus/state/logit_state.py

https://github.com/qcrs/os/blob/master/statebus/refs/models.py

https://github.com/qcrs/os/blob/master/statebus/memory/embedding.py

https://github.com/qcrs/os/blob/master/statebus/retrieval/pipeline.py

https://github.com/qcrs/os/blob/master/statebus/control/subprocess_worker.py

https://github.com/qcrs/os/blob/master/statebus/control/messages.py

https://github.com/qcrs/os/blob/master/statebus/control/statebus_control.proto

https://github.com/qcrs/os/blob/master/statebus/contracts/adaptive.py

https://github.com/qcrs/os/blob/master/statebus/integrations/llm.py

---

## StateBridge

Paper:

https://arxiv.org/abs/2608.13317

Repository:

https://github.com/YanwenPneg/StateBridge

Pinned release commit:

https://github.com/YanwenPneg/StateBridge/commit/3f6bf5442c6e8848555a6132516e6d36f35444fb

Core:

https://github.com/YanwenPneg/StateBridge/blob/main/methods/state_bridge.py

Model wrapper:

https://github.com/YanwenPneg/StateBridge/blob/main/models.py

Release notes:

https://github.com/YanwenPneg/StateBridge/blob/main/RELEASE_NOTES.md

---

## Latent integrity / causal audit

When Latent Agents Lie: KV-Cache Integrity in Multi-Agent LLM Collaboration

https://arxiv.org/abs/2606.28958

When Does Latent Communication Pay? A Causal Audit of Relayed KV Caches in Multi-Agent LLMs

https://arxiv.org/abs/2608.04893

---

## Alternative latent communication

Communicating Activations Between Language Model Agents — ICML 2025

https://proceedings.mlr.press/v267/ramesh25a.html

Let Models Speak Ciphers: Multiagent Debate through Embeddings — ICLR 2024

https://proceedings.iclr.cc/paper_files/paper/2024/hash/e444859b2a22df6b56af9381ad1e9480-Abstract-Conference.html

See What I See, Know What I Think: Dense Latent Communication Across Heterogeneous Agents

https://arxiv.org/abs/2606.13594

---

## vLLM Prompt Embeddings

vLLM 0.9.x prompt embeds:

https://docs.vllm.ai/en/v0.9.0/features/prompt_embeds.html

vLLM 0.9.2 input preprocessing:

https://docs.vllm.ai/en/v0.9.2/api/vllm/inputs/preprocess.html

V1 Prompt Embedding RFC:

https://github.com/vllm-project/vllm/issues/22124

Current prompt embedding docs:

https://docs.vllm.ai/en/latest/features/prompt_embeds/

---

# 138. 最终冻结结论

1. 当前 Embedding 的跨 PID State 生命周期是真实、完整的，不是 toy；
2. 但其语义角色是 Evidence Selection，不是 Latent Reasoning；
3. 正式 Embedding headline 必须显式使用真实 Qwen3-Embedding backend，不能和 16D deterministic hash backend混淆；
4. 当前 Ref/sidecar/grant 的 integrity binding 对 trusted controlled path够用，但 Hidden State 前必须升级；
5. `manifest_hash=self.manifest_id` 是明确应修 contract 问题；
6. `LayeredStateStore` 需要 immutable ID、transactional publish、atomic metadata、idempotent release、TTL sweep；
7. `SemanticStateRef` 不应扩成万能神经状态；
8. 新增 `LatentStateRef / LatentStateContract / LatentConsumptionReceipt`；
9. Latent v1 只支持 homogeneous same-model StateBridge alignment；
10. Latent payload 第一版推荐 FP16 + SHM，K≤64；
11. StateBridge capture/alignment/injection 应拆成独立 provider components，不直接 copy `run_item()`；
12. 当前轻量 `subprocess_worker.py` 不应承担模型 hosting；Latent 应使用独立 HF provider worker；
13. UDS 控制模式可复用，但 RefHandle 应升级为 commitment-aware；
14. CapabilityGrant 必须绑定 Ref commitment，而不仅是 ref ID；
15. Latent 应作为 advisory sideband，不能替代 Evidence/Artifact authority；
16. 第一正式主链接入位置优先 `Executor → Summarizer`；
17. 所有 latent failure 必须 fallback text/artifact path；
18. StateBridge 不消除 Sender autoregressive generation，只消除跨 Agent 必须离散文本化的 communication bottleneck；
19. Latent benchmark 必须包含 matched / mismatched / zero / random controls，不能只看 Text vs Latent；
20. vLLM prompt embeds 未来可行，但当前 pinned 0.9.2/V1 需要单独 compatibility probe，不能阻塞 HF provider；
21. APC 保持独立 Inference Reuse；Explicit KV 保留 compute-state PoC，不继续成为 semantic-state主线；
22. StateBus + StateBridge 的真正价值是：**把 continuous hidden communication 变成具有 identity、compatibility、authorization、commitment、lease、actual-use proof、fallback 和 lifecycle 的 Runtime State。**

