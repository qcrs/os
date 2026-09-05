# StateBus Round 05 — Typed State / Ref / Shared-State Data Plane 全链源码审计与演进设计

> 审计对象：`qcrs/os`  
> 分支：`master`  
> 审计基线：`8bfc6464ec236c0e121911095fc283129b0e7696`  
> 日期：2026-09-03  
> Round 定位：在 Routing、Benchmark Boundary、CodeAct/Verified Recipe、Memory Runtime 之后，回到 StateBus 最核心的“低开销结构化 / 非文本状态传递”主张，审计 **Ref → Representation → Placement → Materialization → Control/Data Plane → Resolve → Consume → Lifecycle → Telemetry** 的完整链路。

---

# 0. Executive Summary

Round 05 最适合走的路线是：

# **Typed State / Ref / Shared-State Data Plane 全链审计**

而不是继续扩 Memory，也不是现在直接进入 KV。

原因是：StateBus 最有辨识度、同时也是比赛题目最看重的核心能力，不是 Planner、Memory 或 CodeAct 本身，而是：

> **多 Agent 之间是否真的能够以受控 Ref 指向非文本中间状态，并在不把重 payload 塞进文本消息的情况下完成跨进程消费、选择、复用和审计。**

源码审计后的总体判断是：

## 0.1 这一块是真机制，不是包装

当前确实存在两条真实的 typed non-text state 路径。

第一条：

```text
Retriever
  ↓
query/candidate embeddings
  ↓
float32 Dense Semantic State
  ↓
shared_memory / mmap
  ↓
UDS + Protobuf 只传 RefHandle
  ↓
另一个 PID resolve
  ↓
read-only NumPy view
  ↓
cosine selection
  ↓
candidate IDs
  ↓
hydrate selected evidence
```

第二条：

```text
Executor
  ↓
closed-set candidate probabilities
  ↓
LogitState
  ↓
shared memory
  ↓
independent Gate PID
  ↓
accept / retry
```

因此下面这些能力都是真实存在的：

```text
non-text intermediate state
cross-process state consumption
typed control plane
control/data plane separation
state-side selection before hydration
```

## 0.2 但当前还不能叫“成熟通用 Shared-State Runtime”

当前更准确的定位是：

> **已经拥有两个真实的专用 typed-state data-plane mechanism，但通用 State Runtime 的 Authority、Lifecycle、Materializer、性能和可观测性还没有完全闭环。**

最关键的问题如下。

| Priority | 问题 | 影响 |
|---|---|---|
| **P0** | `capability_grant_hash` 在 worker 侧只检查非空，没有真正验证 state access binding | “Runtime authorizes” 在 State Resolve 上没有完全落地 |
| **P0** | `RefHandle` 只有 `ref_id/ref_kind`，worker 从 sidecar 自行重建 Ref | Supervisor 没把 expected blob/manifest/session identity 密封进请求，存在 identity / TOCTOU gap |
| **P0** | Dense state resolve 为校验 hash 先执行 `bytes(buffer)` | 每次消费仍完整 copy 一遍 state，不能宣称 end-to-end zero-copy |
| **P0/P1** | Adaptive semantic path 每个 bundle 都创建新的 Python subprocess | `Popen + interpreter startup` 远大于一次 SHM resolve，本质仍是机制证明 harness |
| **P1** | `LayeredStoragePolicy` 能选 CAS/WORKSPACE，但 `LayeredStateStore` 没对应 materializer | Policy 与物理 provider 能力不一致 |
| **P1** | `LOGIT_STATE` policy 支持 memfd/mmap fallback，但 publish 明确只接受 SHM | 配置合同互相矛盾 |
| **P1** | Semantic release 只删 payload，不删 metadata/manifest；Logit release 则有 tombstone | 生命周期语义不统一 |
| **P1** | 文档说 release 幂等，但 `release()` 直接 `pop`，重复 release 会 `KeyError` | 文档超前于实现 |
| **P1** | `owner_session_id` 被写入 Dense contract，但 resolve 不校验当前 consumer session | owner 是 audit metadata，而非 access control |
| **P1** | Ref Registry 没 owner/session/lease/access scope 字段 | Registry 当前不足以承担 State Authorization |
| **P1** | `JsonContractStore.persist_contract_bundle()` 先发布 Registry，再逐文件写 sidecar | crash 时可能出现 visible Ref 指向未完成 sidecar |
| **P1** | `_write_json_batch()` 不是事务，`write_bytes()` 也没有 temp+rename | Contract Bundle 不具备 crash atomicity |
| **P1** | 重复 `ref_id` publish 会覆盖 handle map，但旧物理对象没有先释放 | 可能泄漏 SHM/memfd/mmap |
| **P1** | materialize 后写 metadata 失败时 rollback 不完整 | failure path 可能泄漏底层资源 |
| **P1** | SHM 有预算，memfd 没总量预算，mmap 也没磁盘/对象上限 | Placement 仍是简单 preference，不是 resource-aware policy |
| **P1** | `semantic_state_transfer_count` 实际等于“cross-PID resolve 次数” | “transfer” metric 命名不准确 |
| **P1** | adaptive semantic path 临时创建 Transport 后直接 `.execute()`，没有保留 `last_exchange_audit` | 正式 adaptive 路径缺少 control wire bytes 证据 |
| **P1** | `StateConsumptionRecord.behavioral_effect` 通过两个不同 surface hash 是否相等判断 | 更像“projection changed”，并非严格 counterfactual behavioral effect |
| **P2** | Dense state schema 固定 `query_then_candidates + normalized float32` | 是专用 representation，不是通用 latent-state contract |
| **P2** | 没有 generic backend capability descriptor / refcount / renew / orphan recovery | 扩展 multi-consumer / persistent worker 时会遇到架构瓶颈 |
| **P2** | named SHM 没有 kernel-enforced immutable seal | 当前依赖受信任 producer；未来可考虑 sealed memfd |

本轮最重要的判断不是“换成更快的共享内存库”，而是：

```text
当前最值得做的是
Identity
Authority
Lifecycle
Copy Path
Worker Lifetime
Measurement
```

---

# 1. 为什么 Round 05 应该走 State Data Plane

前四轮已经把控制面的大部分问题拆开了。

## 1.1 Round 01：Routing Plane

已经冻结：

```text
PlanSelector
Logical Capability Selection
Execution Binding
State Placement
Decision Gate
Inference Reuse
```

这些是不同 plane，不应该重新混回一个“万能 Router”。

## 1.2 Round 02：Benchmark Boundary

解决：

```text
Benchmark Adapter
Runtime Visibility
Gold / Grader Leakage
External Generalization
```

所以 Round 05 也必须保持一个原则：

> State Runtime 只能看到 Runtime-authorized state identity 与公开任务上下文，不能因为 benchmark 需要而绕过 authority。

## 1.3 Round 03：CodeAct / Verified Recipe

解决：

```text
Code generation
repair
verified source identity
execution receipt
recipe replay truthfulness
```

## 1.4 Round 04：Memory Runtime

解决：

```text
long-term memory
hybrid retrieval
compatibility
recipe replay
memory projection/binding
```

## 1.5 Round 05 的自然问题

就是：

```text
当 Runtime 已经决定：
  谁要执行
  执行什么
  可以读取什么

真正的大对象 / 非文本状态
是如何跨进程存在、传递、映射、读取和释放的？
```

这就是 State Data Plane。

---

# 2. Round 05 必须先冻结 State 边界

“State”这个词在 repo 中覆盖很多东西，必须区分。

## 2.1 Runtime Typed State

例如：

```text
DenseSemanticState
LogitState
```

是：

```text
StateBus-owned explicit non-text state
```

这是本 Round 的主对象。

## 2.2 Execution Artifact

例如：

```text
JSON
CSV
generated file
validated table
```

是 durable artifact。

它可以通过 Ref 被引用，但不应该被 `LayeredStateStore` 假装成 shared-memory state。

## 2.3 Long-Term Memory

例如：

```text
strategy
recipe
historical fact
```

是 cross-task Memory Runtime。

Round 04 已经单独处理。

## 2.4 Engine-Local Inference State

例如：

```text
APC prefix
EngineLocalKVHandle
paged KV
```

属于 Inference Reuse Plane。

它不是本 Round 的 generic StateStore。

这条线应该留给 Round 06。

---

# 3. 当前正式 Typed Ref

`statebus/refs/models.py` 中最重要的是：

```text
SemanticStateRef
LogitStateRef
ExecutionArtifactRef
HydrateManifest
CanonicalEvidencePack
```

其中 Round 05 的核心是前两个。

---

# 4. SemanticStateRef：当前 Logical Ref 还不够完整

当前 `SemanticStateRef` 顶层字段：

```text
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

它可以生成：

```text
RefRegistryEntry(
    ref_kind = semantic_state,
    storage_kind = ...,
    status = ACTIVE,
    blob_hash = ...,
    manifest_hash = ...
)
```

这已经比“一个字符串 ID”强很多。

但真正关键的 identity / access 字段：

```text
owner_session_id
lease_expires_at_ns
producer_pid
encoder_signature
shape
dtype
row_layout
```

都被放进 `metadata`，而不是 Ref 顶层合同。

这导致目前至少有三层描述：

```text
SemanticStateRef
    ↓
Ref.metadata
    ↓
DenseSemanticStateContract
    ↓
metadata sidecar.contract_metadata
```

这些层目前靠运行时交叉检查保持一致，而不是由一个更明确的 State Identity 合同统一。

---

# 5. DenseSemanticStateContract：专用合同本身做得很好

当前 Dense contract 包含：

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
dtype
byte_order
row_layout
normalized
schema_version
```

这是一个相当完整的 representation-specific contract。

它真正的问题不是“字段不够”，而是：

> 它还没有被放进通用 State Identity / Access / Placement 协议中。

---

# 6. Dense Semantic State 的真实表示

编码格式固定：

```text
row 0 = query embedding
row 1..N = candidate embeddings

dtype = little-endian float32
layout = C-order
normalized = True
```

也就是说它不是：

```text
arbitrary latent tensor
```

而是一个非常明确的：

```text
query-to-candidates semantic selection matrix
```

这点必须准确描述。

---

# 7. 发布前验证链

`encode_dense_semantic_matrix()` 会验证：

```text
candidate non-empty
same dims
same encoding
matrix shape
finite values
unit norm
```

随后构造：

```text
np.asarray(... dtype="<f4")
```

最后：

```text
matrix.tobytes(order="C")
```

这保证了状态 payload 的 representation 是 deterministic 的。

---

# 8. HydrateManifest 是 StateBus 这一条链很重要的部分

Dense matrix 只有 row index。

真正业务对象通过 `HydrateManifestEntry` 绑定：

```text
row_idx
candidate_id
bucket
locator
stable_key
byte_hint
importance_score
```

因此真实链路不是：

```text
vector
→ model 自己猜含义
```

而是：

```text
vector row
→ typed candidate ID
→ locator
→ source evidence
```

这是值得保留的架构点。

---

# 9. 当前 Dense State 发布链

```text
query embedding
candidate embeddings
    ↓
encode_dense_semantic_matrix()
    ↓
bytes payload
    ↓
DenseSemanticStateContract
    ↓
persist_hydrate_manifest()
    ↓
LayeredStateStore.publish()
    ↓
SHM or mmap
    ↓
metadata sidecar
    ↓
SemanticStateRef
```

---

# 10. 当前 Placement Policy

默认偏好大致是：

```text
EMBEDDING_STATE
    SHARED_MEMORY
    → MMAP_FILE

DENSE_SEMANTIC_STATE
    SHARED_MEMORY
    → MMAP_FILE

LOGIT_STATE
    MEMFD
    → SHARED_MEMORY
    → MMAP_FILE

FEATURE_BUNDLE
    INLINE
    → MMAP_FILE

MEMORY_MATCH_RESULT / MEMORY_COMMIT
    CAS_SIDECAR
    → MMAP_FILE

HYDRATE_MANIFEST / CANONICAL_EVIDENCE_PACK
    CAS_SIDECAR
    → MMAP_FILE

EXECUTION_ARTIFACT
    WORKSPACE_ROOT
    → CAS_SIDECAR
```

运行 profile：

```text
auto
memfd
shared_memory
mmap
```

---

# 11. Dense Semantic State 为什么当前不走 memfd

这是源码里一个合理的实现选择。

在 `memfd` mode 下，Dense 仍然保持：

```text
SHM → mmap
```

原因是当前 Dense consumer 的模型是：

```text
另一个 PID
    ↓
根据 state_root + metadata
重新打开 named backend
```

anonymous memfd 没有名字，当前实现只有父进程创建子进程时通过：

```text
Popen(pass_fds=...)
```

才能让 child 访问。

因此：

```text
Dense Semantic State 当前不支持 generic memfd resolver
```

是源码事实。

---

# 12. Future Persistent Worker 下 memfd 应该怎么做

如果未来 worker 是 long-lived：

```text
Popen(pass_fds)
```

无法持续传新 FD。

更合适的是：

```text
UDS
+
SCM_RIGHTS
```

传 FD。

如果再结合：

```text
memfd_create(MFD_ALLOW_SEALING)
F_SEAL_WRITE
F_SEAL_GROW
F_SEAL_SHRINK
F_SEAL_SEAL
```

就可以得到：

```text
anonymous
cross-process
kernel-enforced immutable
read-only mmap
```

的 data plane。

但这不是当前第一优先级。

---

# 13. LayeredStateStore 当前真正实现哪些 Materializer

真正有物理实现的只有：

```text
SHARED_MEMORY
MEMFD
MMAP_FILE
INLINE
```

核心分支是：

```text
if SHARED_MEMORY
elif MEMFD
elif MMAP_FILE
else
    _materialize_inline()
```

---

# 14. Policy 和 Materializer 能力不一致

`LayeredStoragePolicy` 可以返回：

```text
CAS_SIDECAR
WORKSPACE_ROOT
```

但 `LayeredStateStore` 并没有：

```text
_materialize_cas()
_materialize_workspace()
```

因此如果有人真的执行：

```python
store.publish(object_kind="MEMORY_COMMIT", ...)
```

Policy 可能选择：

```text
CAS_SIDECAR
```

Store 却会落到：

```text
_materialize_inline()
```

而 handle 的 `storage_kind` 仍可能标成 CAS。

这是典型的：

```text
logical storage label
≠
physical materialization
```

当前主线没爆，是因为 Memory/Artifact 实际走各自 store/workspace，不一定调用这条 StateStore。

但这个抽象必须修。

---

# 15. 推荐拆分 Placement 与 Materializer

目标：

```text
StatePlacementPolicy
        ↓
Backend Capability Registry
        ↓
StateMaterializer
```

而不是：

```text
object_kind → StorageKind enum → 大 if/else
```

---

# 16. StateBackendDescriptor

推荐：

```python
@dataclass(frozen=True)
class StateBackendDescriptor:
    backend_id: str
    storage_kind: str

    same_host_only: bool
    cross_process: bool

    reopenable_by_name: bool
    supports_fd_transfer: bool
    supports_readonly_mapping: bool

    immutable_enforced: bool
    persistent: bool

    max_object_bytes: int
    cost_class: str
```

当前后端可以描述成：

| Backend | Cross PID | reopen | read-only view | kernel immutable | persistent | 当前问题 |
|---|---:|---:|---:|---:|---:|---|
| named SHM | yes | name | yes | no | no | validation full-copy |
| mmap file | yes | path | yes | file perms only | semi | filesystem lifecycle |
| memfd current | child only | inherited FD | worker 当前用 `os.read` | no sealing | no | tied to `Popen(pass_fds)` |
| inline | same process/control | no | no | no | no | only small object |
| CAS | conceptual | yes | provider-dependent | content-addressed | yes | `LayeredStateStore` 未实现 |
| workspace | conceptual | path | provider-dependent | no | yes | `LayeredStateStore` 未实现 |

---

# 17. Current SHM Path：确实有真实共享读

发布：

```text
SharedMemory(create=True)
    ↓
payload copied into shared.buf
    ↓
shared_memory_name written to metadata
```

消费：

```text
SharedMemory(name=...)
    ↓
memoryview(shared.buf)
    ↓
np.ndarray(buffer=...)
```

最终 `np.ndarray` 确实直接 view 在共享映射上。

因此：

```text
consumer compute view is zero-copy
```

这一点成立。

---

# 18. 但当前不是 end-to-end zero-copy

关键代码：

```python
payload = bytes(buffer)
```

它发生在：

```text
resolve_dense_semantic_state()
```

目的：重新计算完整 SHA256。

因此 consumer 真实链路：

```text
SHM / mmap
    ↓
bytes(buffer)       ← full copy
    ↓
hash validation
    ↓
np.ndarray(buffer)  ← zero-copy compute view
```

所以当前正确表述必须是：

> **State payload 不经过 UDS；消费者数值计算使用共享只读映射，但 resolve integrity check 仍会复制完整 payload。**

不能写：

```text
end-to-end zero-copy
```

---

# 19. Producer 侧也有中间 copy

当前：

```text
Python / tuple embeddings
    ↓
np.asarray(matrix)
    ↓
matrix.tobytes()
    ↓
shared.buf[:] = payload
```

因此有：

```text
matrix → bytes
bytes → SHM
```

的中间内存移动。

---

# 20. 第一阶段 copy 优化

## 20.1 Consumer

避免：

```python
bytes(buffer)
```

直接用支持 buffer protocol 的 hash：

```text
hashlib.sha256(buffer)
```

目标：

```text
validation_copy_bytes = 0
```

## 20.2 Producer

在 SHM backend 中直接建立：

```text
np.ndarray(shape, dtype, buffer=shared.buf)
```

然后一次 copy row data 到目标 shared object。

可以避免大 `bytes` 中间对象。

## 20.3 不追求不现实的 publish zero-copy

只要 encoder 原始输出已经存在于 producer private memory，至少要有一次：

```text
producer memory → shared object
```

除非 encoder 直接写目标 buffer。

当前没必要追这个。

---

# 21. Current mmap Path

发布位置：

```text
state_root/mmap/{ref_id}.bin
```

消费会：

```text
resolve(strict=True)
确认 parent == state_root/mmap
open(rb)
mmap(ACCESS_READ)
```

这一层路径约束做得较好。

mmap 的主要价值不是“必然更快”，而是：

```text
named
cross-process reopenable
SHM pressure fallback
```

现有 backend matrix 正确地没有把它写成性能 superiority claim。

---

# 22. Current memfd Path

发布：

```text
memfd_create
ftruncate
write
lseek
```

跨进程：

```text
Popen(pass_fds=...)
```

worker：

```text
os.read(fd, length)
```

因此当前 memfd 的主要优势是：

```text
anonymous
not filesystem-backed
```

而不是 zero-copy。

worker 的 `os.read()` 会产生 Python bytes copy。

---

# 23. Current Control Plane 是正确的方向

当前 transport 是：

```text
Unix Domain Socket
+
length-prefixed Protobuf
```

`ExecRequest` 携带：

```text
ControlHeader
state_refs
artifact_refs
memory_refs
reuse policy
workspace root
input manifest hash
operation
state root
hydrate manifest id
semantic top-k
evidence budget
expected encoder signature
capability grant hash
```

重 payload 并不通过 Protobuf 发送。

这是实质上的：

```text
Control Plane
≠
Data Plane
```

---

# 24. RefHandle 当前太弱

现在：

```python
@dataclass(frozen=True)
class RefHandle:
    ref_id: str
    ref_kind: str
```

它没有：

```text
blob_hash
manifest_hash
owner_session
lease_id
binding_hash
grant binding
```

---

# 25. Worker 实际如何得到完整 State Ref

不是从 Supervisor 发送的完整 Ref。

而是：

```text
state_root
+
ref_id
    ↓
metadata sidecar
    ↓
semantic_ref_from_sidecar()
```

也就是说 Supervisor 当时持有：

```text
publication.ref
blob hash
manifest ID
encoder signature
owner session
```

但 UDS 只发送：

```text
ref_id
ref_kind
```

---

# 26. Identity / TOCTOU Gap

Consumer 后续重新相信：

```text
sidecar
```

因此缺少一个强 binding 来证明：

```text
Worker resolve 的这个状态
就是 Supervisor 当时授权的那个 state generation / blob / manifest
```

当前所有进程都在 trusted local environment，所以这不是在说“现在已有远程安全漏洞”。

它是：

```text
contract completeness gap
```

但对于 StateBus “Runtime authorizes” 的架构叙述，这是必须补的。

---

# 27. `capability_grant_hash` 当前只是“存在性字段”

Semantic request 确实传：

```text
capability_grant_hash = grant.grant_hash
```

但 worker 侧真正做的只是：

```text
if empty:
    invalid_exec_request
```

它没有：

```text
lookup grant
verify grant hash
verify task/session/step/attempt
verify ref authorized by grant
verify role
verify operation
```

---

# 28. 当前真实 authority model

更接近：

```text
Supervisor constructs trusted request
    ↓
Worker trusts Supervisor
    ↓
Possession of state_root + ref_id
    ↓
Resolve allowed
```

而不是：

```text
CapabilityGrant independently authorizes every state read
```

这点必须在文档与比赛叙述中准确标注。

---

# 29. owner_session_id 当前不是 ACL

Dense contract 确实有：

```text
owner_session_id
```

resolve 会验证：

```text
Ref metadata.owner_session_id
==
sidecar contract.owner_session_id
```

但没有传：

```text
current_consumer_session_id
```

来比较。

因此：

```text
owner_session_id = audit identity
```

目前不是：

```text
access-control boundary
```

---

# 30. Ref Registry 当前也不足以承担 Authorization

`RefRegistryEntry` 只有：

```text
ref_id
ref_kind
storage_kind
status
blob_hash
manifest_hash
root_id
relpath
workspace_relpath
schema_version
```

没有：

```text
owner
session
lease
allowed consumers
capability binding
```

所以现有 Registry 更接近：

```text
small object index
```

而不是完整 State Authority DB。

---

# 31. 推荐 `BoundRefHandle`

```python
@dataclass(frozen=True)
class BoundRefHandle:
    ref_id: str
    ref_kind: str

    object_digest: str
    manifest_digest: str

    owner_session_id: str
    generation: int

    access_grant_hash: str
    binding_hash: str
```

其中 `binding_hash` 应摘要：

```text
task
session
step
attempt
capability grant
ref ID
generation
blob
manifest
consumer role
operation
expiry
```

---

# 32. 推荐 `StateAccessGrant`

```python
@dataclass(frozen=True)
class StateAccessGrant:
    task_id: str
    session_id: str
    step_id: str
    attempt_id: str

    consumer_role: str
    capability_id: str

    state_ref_id: str
    state_generation: int
    state_digest: str

    permitted_operation: str
    expires_at_ns: int

    capability_grant_hash: str
    access_grant_hash: str
```

worker 必须验证：

```text
request header == access grant identity
ref ID == authorized ref
state digest == expected digest
operation == permitted operation
now < expiry
contract.owner_session_id == grant.session_id
capability_grant_hash matches
```

---

# 33. Registry 建议分“Index”和“Access”两层

不要把所有字段塞进一个小 JSON entry。

## 33.1 Ref Index

保存：

```text
identity
kind
state
content digest
placement binding
```

## 33.2 Lease / Access Table

保存：

```text
owner
scope
lease
readers
consumer bindings
```

这样职责更清晰。

---

# 34. Current Adaptive Semantic State 确实跨 PID

现有测试覆盖：

```text
shared_memory
mmap
```

两种 backend。

它验证：

```text
consumer_pid != producer_pid
```

并且 selected candidate IDs/scores/rows 与 reference selection 一致。

所以这条 claim 可以硬讲：

> **Dense Semantic State 在 producer 中发布为二进制 float32 state，控制面只把 Ref 通过 UDS/Protobuf 传给独立 consumer PID，consumer 根据 sidecar 映射共享对象并执行 cosine selection。**

---

# 35. 但不能扩大成“任意 hidden state 通信”

当前没有：

```text
LLM internal hidden layer tensor direct communication
```

当前 state 是：

```text
embedding space query/candidate matrix
```

所以更准确的定位是：

```text
Specialized Semantic Selection State
```

而不是：

```text
Generic Latent Communication Bus
```

---

# 36. Semantic State 的真实业务价值

它做的是：

```text
大候选集
    ↓
non-text numeric selection
    ↓
只 hydrate 少量 evidence
    ↓
后续 LLM
```

真正的优势不是：

```text
embedding 永远替代 text
```

而是：

> **在文本进入下游模型之前，用非文本状态决定“谁值得被 hydrate”。**

这更符合实际源码。

---

# 37. Hydration 最终仍然回到 tokens

selected candidate IDs 最终会：

```text
candidate ID
→ locator
→ EvidenceItem
→ rendered/structured evidence
→ role prompt
```

这是正常的。

LLM 最终消费的仍是 tokens。

StateBus 的价值是：

```text
谁需要 hydrate
hydrate 多少
什么时候 hydrate
```

而不是假装完全摆脱 token 输入。

---

# 38. LogitState：第二条真实 non-text path

当前 payload 是：

```text
[p(candidate A), p(candidate B), ..., p(candidate N), other_mass]
```

而不是完整 logits。

大小：

```text
4 × (candidate_count + 1) bytes
```

这是候选级概率投影。

---

# 39. LogitState 合同比 Ref docstring 更准确

`LogitStateRef` 旧 docstring 仍写：

```text
log 概率 float32 向量
```

但实际 current contract 强制：

```text
0 <= p <= 1
sum(values) ≈ 1
```

因此 current payload 是：

```text
candidate probability state
```

不是 raw logprob state。

文档和命名应统一。

---

# 40. Logit lifecycle 反而更完整

`release_logit_state()` 会：

```text
release physical payload
remove active metadata
write tombstone
```

而 Dense Semantic mainline 只是：

```text
state_store.release(state_id)
```

Generic Store release：

```text
SHM close/unlink
memfd close
mmap unlink
```

但不会自动删除：

```text
metadata sidecar
hydrate manifest
```

因此两类 state lifecycle 不一致。

---

# 41. Logit Storage Policy 与 Publisher 有直接冲突

Policy 默认：

```text
LOGIT_STATE:
MEMFD → SHARED_MEMORY → MMAP_FILE
```

但 `publish_logit_state()` 明确要求：

```text
handle.storage_kind == SHARED_MEMORY
```

否则：

```text
release
raise logit_state_requires_shared_memory
```

所以如果：

```text
state_pool_mode = memfd
```

并且 memfd 成功，Policy 会做出一个“成功选择”，Publisher 随后却主动拒绝。

同样，SHM budget 超限 fallback 到 mmap 也会被 Publisher 拒绝。

这说明：

> Backend eligibility 应在 Placement 前判断，不能“先选错 provider，再由业务 Publisher 拒绝”。

---

# 42. `release()` 当前不是幂等

当前：

```python
handle = self.materializations.pop(ref_id)
```

第二次 release 会直接失败。

但文档写：

```text
清理采用幂等实现
```

真正成立的是：

```text
Mainline caller 自己用 released_state_ids / membership guard 避免重复 release
```

不是 Store API 本身幂等。

Target 应该是：

```python
release(ref_id) -> StateReleaseReceipt
```

如果已经 released：

```text
return already_released
```

而不是抛异常。

---

# 43. Semantic release 的 stale sidecar 问题

payload unlink 后：

```text
metadata/{state_id}.json
manifests/{manifest_id}.json
```

还在。

后续 resolve 最终会报：

```text
payload_missing
```

所以 correctness 还能维持。

但长期运行会出现：

```text
active-looking metadata
without live payload
```

大量堆积。

需要正式 lifecycle state / tombstone。

---

# 44. 推荐统一 State Lifecycle

至少：

```text
ACTIVE
RELEASE_PENDING
RELEASED
EXPIRED
INVALIDATED
```

publish 内部可以再有：

```text
PUBLISHING
```

用于 crash recovery。

---

# 45. Tombstone 只需要 compact audit

不用把完整大 contract 永久复制。

建议：

```text
state_id
generation
blob_hash
owner_session
published_at
released_at
release_reason
producer_pid
consumer_pids
backend
size_bytes
```

---

# 46. 当前没有真正的 multi-consumer refcount

现在主要模式是：

```text
one producer
one consumer
synchronous response
then release
```

所以还够用。

但 generic shared state 很快会遇到：

```text
State X
   ├→ Executor A
   ├→ Executor B
   └→ Summarizer
```

此时“谁可以 release”必须有正式模型。

---

# 47. 推荐 Owner + Consumer Pin

不用复制 Ray 的 distributed reference counting 全套。

同机版本足够：

```python
StateLeaseRecord(
    owner_session_id=...,
    owner_release_requested=False,
    active_consumer_grants=(...),
    lifecycle_state="ACTIVE",
)
```

释放条件：

```text
owner requested release
AND
active consumer pins == 0
```

才物理 unlink。

---

# 48. Lease 的正确语义

TTL 不应该简单等于：

```text
到点立即删物理对象
```

更合理：

```text
lease expired
→ no new consumer binding
→ existing active readers drain
→ reclaim
```

当前 Dense lease 已经有“过期后拒绝新 resolve”的方向，只缺 active consumer accounting。

---

# 49. Publish Failure Path 有潜在资源泄漏

当前 SHM materialization 大致：

```text
create SharedMemory
copy payload
register in _shared_segments
increment shared_memory_bytes_used
construct handle
write metadata
```

如果最后 `write_metadata()` 抛 OSError，资源已经创建。

`publish()` 会捕获部分 OSError 并尝试 fallback，但没有明确 rollback 首次已创建资源。

可能造成：

```text
orphan SHM
stale shared_memory_bytes_used
```

memfd 同理。

---

# 50. Publish 应是 transaction-like

推荐：

```text
allocate
    ↓
write payload
    ↓
validate
    ↓
write metadata staging
    ↓
commit handle to active registry
```

任何失败：

```text
rollback physical resource
```

---

# 51. Duplicate ref_id 需要正式处理

当前：

```text
self.materializations[ref_id] = handle
```

会覆盖旧 handle。

如果旧 ref 仍 active：

```text
old SHM / memfd / mmap
```

并不会自动释放。

Target 默认应：

```text
active_ref_id_collision
→ reject
```

或者显式采用：

```text
state_id + generation
```

---

# 52. 建议 State Identity 引入 generation

例如：

```text
state-X:g1
state-X:g2
```

logical state 可以同名演进，但每个 physical generation identity 唯一。

---

# 53. JsonContractStore 当前不是 crash-safe Registry

`put_ref_registry_entries()`：

```text
read whole JSON registry
modify dict
write whole JSON
```

更关键的是 `persist_contract_bundle()` 当前会先：

```text
put_ref_registry_entries(registry_entries)
```

然后才准备写其它 sidecar。

这意味着 publication order 可能是：

```text
Registry visible
    ↓
Sidecars written later
```

这是错误的 durable commit 顺序。

---

# 54. Registry 应该最后提交

正确顺序：

```text
payload
    ↓
sidecar / manifest
    ↓
validate / fsync
    ↓
Registry visibility commit LAST
```

Registry 应该是：

```text
commit pointer
```

而不是最先出现的入口。

---

# 55. `_write_json_batch()` 并不是 transaction

它只是：

```python
for write in writes:
    _write_json(...)
```

`_write_json()` 也是直接：

```text
path.write_bytes(rendered)
```

没有：

```text
temp file
fsync
atomic rename
```

所以当前更准确的定义是：

```text
Audit Persistence Helper
```

而不是：

```text
Transactional Ref Registry
```

---

# 56. 最小 crash-safe 文件发布流程

可以先不引 SQLite，先做到：

```text
1. write payload
2. verify payload hash
3. write sidecar.tmp
4. fsync sidecar.tmp
5. rename sidecar.tmp → sidecar
6. write registry.tmp
7. fsync registry.tmp
8. rename registry.tmp → registry
```

如果后续并发和规模增长，再把：

```text
Ref Index
Lease
Lifecycle
```

迁入 SQLite。

---

# 57. Adaptive Semantic Path 最大性能问题不是 cosine

不是：

```text
matrix[1:] @ matrix[0]
```

而是：

# **每个 semantic bundle 都启动一个新的 Python subprocess。**

当前：

```text
SubprocessExecutorTransport(...).execute(request)
```

内部：

```text
subprocess.Popen(
    python -m statebus.control.subprocess_worker
)
```

每次 request 都重新启动。

---

# 58. 一次 state consume 当前包含什么

```text
socket setup
Popen
Python interpreter startup
module imports
worker connect UDS
Protobuf receive
resolve state
integrity validation
selection
response
process exit
```

对于几十 KB / 几 MB 的 local SHM state：

```text
process startup overhead
```

很可能比真正 data-plane operation 大得多。

所以 current subprocess path 最准确的定位是：

> **cross-process mechanism / ownership proof harness**

而不是最终低开销 worker architecture。

---

# 59. 正式 Runtime 应该使用 Persistent Worker

最小方案：

```text
Runtime
    ↓
1 long-lived Executor Worker
    ↓
UDS session
    ↓
multiple ExecRequests
```

worker 保持：

```text
stable PID
state resolver
capability snapshot
workspace/sandbox context
```

这样才能真正测：

```text
Ref handoff overhead
```

而不是：

```text
process launch overhead
```

---

# 60. Persistent Worker 也会逼出真正 Lifecycle 问题

因为一个 worker 会连续处理：

```text
state A
state B
state C
```

此时才能真实验证：

```text
lease
pin
GC
stale ref
cross-session access
worker restart
```

---

# 61. Current Transport 已经有 wire-byte audit

`ExecutorTransportAudit` 有：

```text
carrier
backend
driver_pid
worker_pid
request_frame_count
response_frame_count
request_wire_bytes
response_wire_bytes
total_wire_bytes
```

这非常适合比赛通信指标。

---

# 62. 但 Adaptive Semantic Path 丢掉了它

当前写法：

```text
SubprocessExecutorTransport(...).execute(request)
```

临时对象直接销毁。

于是：

```text
last_exchange_audit
```

没有被 Adaptive Telemetry 保存。

应该改成：

```text
transport = context.executor_transport
response = transport.execute(...)
audit = transport.last_exchange_audit
```

然后写进正式 telemetry。

---

# 63. `semantic_state_transfer_count` 命名不准确

当前它本质上是：

```text
consumer_pid != producer_pid
→ +1
```

证明的是：

```text
cross-process consumption / resolve happened
```

不是：

```text
payload physically transferred once
```

SHM path 的 payload 根本不经过 UDS。

建议改：

```text
semantic_state_cross_process_resolve_count
```

---

# 64. 三种 Bytes 必须分开

当前容易混：

```text
semantic_state_bytes
selected_evidence_bytes
control wire bytes
```

它们完全不是同一件事。

应明确：

## 64.1 Binary State Bytes

```text
float32 matrix / probabilities
```

## 64.2 Control Plane Bytes

```text
Protobuf frames / RefHandle / receipts
```

## 64.3 Hydrated Evidence Bytes

```text
后续真正进入文本/structured prompt 的 evidence
```

## 64.4 Avoided Prompt-Visible Bytes

```text
如果没有 semantic state pruning
原本需要暴露给后续 Agent 的候选文本
-
实际 hydrate 的文本
```

这第四个才是比赛最关键指标之一。

---

# 65. 推荐 StateCommunicationAccounting

```python
@dataclass(frozen=True)
class StateCommunicationAccounting:
    control_wire_bytes: int

    binary_state_bytes_published: int
    binary_state_publish_copy_bytes: int
    binary_state_validation_copy_bytes: int
    binary_state_mapped_bytes: int

    full_candidate_text_bytes: int
    hydrated_selected_text_bytes: int
    avoided_text_bytes: int

    full_candidate_tokens_estimate: int
    selected_tokens_estimate: int
    avoided_tokens_estimate: int
```

这样才能真正回答：

> 相比纯文本 Agent handoff，StateBus 少传了多少文本、少让下游模型看了多少 token，又付出了多少 binary-state 与 control-plane 成本。

---

# 66. StateConsumptionRecord 的方向是对的

当前已经记录：

```text
state_ref_id
consumer_role
consumer_step_id
operation
read_field_ids
input_decision_surface_hash
output_decision_surface_hash
selected_ids
downstream_ref_ids
```

这是非常适合 StateBus 的可审计设计。

---

# 67. 但 `behavioral_effect` 仍然被过度命名

当前：

```text
input hash != output hash
→ changed
```

Semantic selection 的 input 是：

```text
candidate surface
```

output 是：

```text
selected IDs + selected scores
```

这两个 payload schema 本来就不同。

因此 `changed` 更准确证明：

```text
selection / projection happened
```

而不是：

```text
final Agent behavior counterfactually changed
```

建议拆：

```text
mechanistic_effect = selection_changed
counterfactual_evaluated = false
behavioral_effect = not_evaluated
```

如果做 A/B shadow，再填真正 behavioral effect。

---

# 68. Backend Matrix 当前做对了什么

现有 backend matrix 明确写：

```text
task_ms is diagnostic
NOT a cross-backend superiority claim
```

这是正确的。

所以目前它证明的是：

```text
mmap/shared_memory/memfd backend realization
```

不是：

```text
SHM 一定比 mmap 快多少
```

这个 claim boundary 应继续保留。

---

# 69. Round 05 需要新增真正的 State Microbenchmark

现在 backend matrix 太靠近 end-to-end benchmark。

应该加：

```text
pure publish/resolve/consume microbenchmark
```

把 LLM、Planner、Retriever 等干扰去掉。

---

# 70. External Reference：Ray 应该借什么

Round 05 最值得对照 `ray-project/ray` 的不是分布式 scheduler，而是：

```text
ObjectRef
Object Store
ReferenceCounter
shared immutable object
object lifetime / spill
```

Ray 的关键启发：

> **Shared State 的关键不只是“放到共享内存”，而是 Object Identity、Ownership、Reference Lifetime、Immutability 和 Placement 一起形成完整协议。**

StateBus 不需要复制：

```text
GCS
distributed scheduler
cluster object manager
```

同机版本即可。

---

# 71. Round 05 Target Architecture

推荐演进为：

```text
                   ┌───────────────────────┐
Producer ─────────▶│ State Representation  │
                   └──────────┬────────────┘
                              │
                              ▼
                   ┌───────────────────────┐
                   │ StateDescriptor       │
                   └──────────┬────────────┘
                              │
                              ▼
                   ┌───────────────────────┐
                   │ StatePlacementPolicy  │
                   └──────────┬────────────┘
                              │
                              ▼
                   ┌───────────────────────┐
                   │ MaterializerRegistry  │
                   └──────────┬────────────┘
                              │
                              ▼
                    physical immutable object
                              │
                              ▼
                   ┌───────────────────────┐
                   │ StatePublishReceipt   │
                   └──────────┬────────────┘
                              │
                     Registry commit LAST
                              │
                              ▼
                         ACTIVE Ref
                              │
                              ▼
                   ┌───────────────────────┐
                   │ StateAccessPolicy     │
                   └──────────┬────────────┘
                              │
                              ▼
                    StateAccessGrant
                              │
                              ▼
                    BoundRefHandle
                              │
                         UDS / Protobuf
                              │
                              ▼
                    Persistent Worker
                              │
                              ▼
                   ┌───────────────────────┐
                   │ Resolver              │
                   └──────────┬────────────┘
                              │
                     read-only mapped view
                              │
                              ▼
                         operation
                              │
                              ▼
                   StateConsumptionReceipt
                              │
                              ▼
                        Release / GC
```

---

# 72. Target Contract：StateDescriptor

推荐：

```python
@dataclass(frozen=True)
class StateDescriptor:
    state_id: str
    generation: int

    state_kind: str
    schema_version: str

    dtype: str
    shape: tuple[int, ...]
    layout: str
    encoding: str

    blob_hash: str
    size_bytes: int

    producer_task_id: str
    producer_session_id: str
    producer_step_id: str
    producer_attempt_id: str
    producer_role: str

    created_at_ns: int
```

它表达逻辑 State identity。

---

# 73. Representation-Specific Extension

Dense Semantic：

```python
@dataclass(frozen=True)
class DenseSemanticDescriptor:
    state_descriptor_hash: str
    encoder_signature: str
    hydrate_manifest_hash: str
    row_layout: str
    normalized: bool
```

Logit：

```python
@dataclass(frozen=True)
class LogitStateDescriptor:
    state_descriptor_hash: str
    candidate_surface_digest: str
    probability_semantics: str
```

不要一上来做“UniversalTensorState”。

---

# 74. Target Contract：StatePlacementBinding

```python
@dataclass(frozen=True)
class StatePlacementBinding:
    state_id: str
    generation: int

    backend_id: str
    storage_kind: str

    locator_kind: str
    payload_locator_hash: str

    backend_capability_hash: str
    placement_policy_version: str

    binding_hash: str
```

重要原则：

```text
logical state identity
≠
physical placement identity
```

以后一个 logical state 即使从 SHM spill 到 mmap，也不需要伪装成另一个业务对象。

---

# 75. Target Contract：StatePublishReceipt

```python
@dataclass(frozen=True)
class StatePublishReceipt:
    state_id: str
    generation: int

    descriptor_hash: str
    placement_binding_hash: str

    blob_hash: str
    size_bytes: int
    backend_id: str

    publish_started_ns: int
    publish_completed_ns: int

    bytes_copied: int
    registry_committed: bool

    receipt_hash: str
```

---

# 76. Target Contract：StateResolveReceipt

```python
@dataclass(frozen=True)
class StateResolveReceipt:
    state_id: str
    generation: int

    access_grant_hash: str

    consumer_pid: int
    consumer_role: str

    backend_id: str

    mapped_bytes: int
    validation_copy_bytes: int

    integrity_verified: bool
    resolve_latency_ns: int

    receipt_hash: str
```

---

# 77. Target Contract：StateConsumptionReceipt

```python
@dataclass(frozen=True)
class StateConsumptionReceipt:
    state_id: str
    generation: int

    access_grant_hash: str
    resolve_receipt_hash: str

    operation: str
    read_regions: tuple[str, ...]

    result_digest: str
    downstream_ref_ids: tuple[str, ...]

    mechanistic_effect: str

    counterfactual_evaluated: bool
    behavioral_effect: str = "not_evaluated"
```

---

# 78. Target Contract：StateLeaseRecord

```python
@dataclass
class StateLeaseRecord:
    state_id: str
    generation: int

    owner_session_id: str
    publish_expires_at_ns: int

    owner_release_requested: bool
    active_consumer_grant_hashes: tuple[str, ...]

    lifecycle_state: str
```

---

# 79. Placement Policy 应该新增哪些输入

当前主要看：

```text
object kind
size
SHM budget
mode
```

Target 再加入：

```text
consumer topology
consumer count
lifetime
mutability
reopenability
persistence requirement
security requirement
memory pressure
backend availability
```

例如 Dense Semantic：

```text
same host
2+ processes
short lived
read-only
medium/large payload
```

当前优先：

```text
named SHM
```

pressure 时：

```text
mmap
```

如果未来 persistent worker + SCM_RIGHTS 完成：

```text
sealed memfd
```

可以成为新候选。

---

# 80. 不要做 UniversalStorageRouter

Round 01 已经冻结 plane separation。

最终应保持：

```text
StatePlacementPolicy
    handles explicit transient state

ArtifactPlacement
    handles workspace/CAS artifacts

MemoryStore
    handles long-term experience

InferenceReuse
    handles APC/KV engine-local state
```

不要为了统一 API 又把这些重新混成一个“大 Storage Router”。

---

# 81. Persistent Worker 是 Round 05 最大性能升级

推荐最小 `ExecutorWorkerPool`：

```text
1 long-lived worker
```

即可。

协议：

```text
START
    ↓
worker register
    ↓
capability snapshot
    ↓
session open

REQ_EXEC #1
REQ_EXEC #2
REQ_EXEC #3
...

SHUTDOWN
```

不要每次：

```text
new socket
new Python process
import statebus
```

---

# 82. Telemetry Target

建议拆成五类。

## 82.1 Control Plane

```text
request_frame_count
response_frame_count
request_wire_bytes
response_wire_bytes
ref_handle_wire_bytes
control_latency_ns
```

## 82.2 Publish

```text
state_payload_bytes
producer_copy_bytes
publish_latency_ns
materialization_latency_ns
backend
fallback_count
```

## 82.3 Resolve

```text
map_latency_ns
integrity_hash_latency_ns
validation_copy_bytes
mapped_bytes
consumer_pid
```

## 82.4 Consumption

```text
operation_latency_ns
rows_read
selected_count
result_bytes
```

## 82.5 Downstream Savings

```text
full_candidate_text_bytes
selected_hydrated_text_bytes
avoided_text_bytes

full_candidate_tokens_estimate
selected_tokens_estimate
avoided_tokens_estimate
```

再额外记录：

```text
worker_startup_ms
worker_rss
shared_memory_bytes
mmap_bytes
open_state_count
GC_count
```

---

# 83. `backend_name` 也不能作为完整 placement truth

当前 `backend_name` 优先返回：

```text
last_published_storage_kind
```

如果同一个 task 同时用了：

```text
SHM
mmap
```

只看 `backend_name` 会丢信息。

应以：

```text
per-ref StatePlacementBinding
+
storage_publish_counts
```

作为真源。

---

# 84. Experiment E0 — Copy Audit

先完全去掉 LLM。

Payload sizes：

```text
4 KB
64 KB
1 MB
8 MB
32 MB
```

分别测：

```text
encode
publish
resolve
operate
release
```

Variants：

```text
SHM
mmap
memfd legacy path
```

必须记录：

```text
publish copy bytes
validation copy bytes
mapped bytes
latency
peak RSS
```

第一目标是定量证明：

```text
bytes(buffer)
```

到底付出多少成本。

---

# 85. Experiment E1 — Current vs No-Copy Validation

A：

```text
bytes(buffer) + hash
```

B：

```text
buffer-protocol hash
```

比较：

```text
resolve latency
peak RSS
CPU time
memory bandwidth
```

这是 Round 05 最容易获得真实性能收益、同时不改变语义的优化。

---

# 86. Experiment E2 — Spawn vs Persistent Worker

A：

```text
Popen per consume
```

B：

```text
persistent worker
```

测：

```text
cold first request
warm p50
warm p95
1000 sequential requests
```

还要记：

```text
worker startup time
steady-state control wire time
state resolve time
```

很可能这个差异比 SHM vs mmap 大得多，但必须由实验确认。

---

# 87. Experiment E3 — Matched Text vs Typed State

这是比赛最关键的实验。

## Baseline

把相同 candidate representation 文本化：

```text
query
candidate IDs
candidate evidence/features
```

通过 UTF-8 UDS handoff。

## StateBus

```text
UDS only RefHandle / bound ref
+
binary state
+
consumer-side selection
+
selected IDs
+
minimal hydration
```

## 必须保持相同

```text
same candidate set
same embedding
same top-k
same selection rule
same downstream LLM
same output contract
```

## 指标

```text
quality
control wire bytes
binary state bytes
hydrated text bytes
prompt tokens
E2E latency
state-only latency
RSS / SHR
```

这个实验真正回答题目：

> **结构化非文本状态是否减少 Agent 通信和重复文本暴露。**

---

# 88. Experiment E4 — Multi-Consumer Lifecycle

构造：

```text
State X
    ├→ Consumer A
    ├→ Consumer B
    └→ Consumer C
```

随机插入：

```text
slow consumer
consumer crash
owner release early
lease expiry
```

Gate：

```text
consumer still reading
→ payload must not be physically unlinked
```

---

# 89. Experiment E5 — Authority Negative

必须新增真正 security/authority negative tests。

## Wrong grant

```text
valid state ref
wrong access grant
→ reject
```

## Wrong session

```text
state owner session A
consumer grant session B
→ reject
```

## Wrong blob

```text
same ref_id
sidecar altered / bound digest mismatched
→ reject
```

## Expired grant

```text
→ reject
```

## Wrong operation

```text
grant permits semantic_select_v1
request asks another operation
→ reject
```

现有 semantic consumer test 主要覆盖：

```text
wrong encoder
payload missing
cross PID correctness
```

还没覆盖这条 authority chain。

---

# 90. Experiment E6 — Crash Atomicity

故意在三处 crash：

```text
after payload

after sidecar

after registry
```

重启后必须满足：

> **No ACTIVE registry entry may point to an incomplete/missing authoritative state payload.**

---

# 91. Experiment E7 — Ref Collision

```text
publish state-X
publish state-X again
```

目标只允许两种行为：

```text
reject active collision
```

或：

```text
explicitly create generation+1
```

不能 silent overwrite active handle。

---

# 92. Source Truth vs Documentation Claim

Round 05 建议正式维护这张表。

| Claim | Source Truth | Verdict |
|---|---|---|
| Consumer cross-validates Registry + CapabilityGrant | inspected semantic worker only checks non-empty grant hash; rebuilds Ref from sidecar | **需修正** |
| Dense semantic supports SHM/memfd/mmap | current Dense resolver supports SHM + mmap; policy deliberately avoids memfd | **文档过宽** |
| release idempotent | `materializations.pop(ref_id)` | **不成立** |
| non-text cross-PID state | real worker path + tests | **成立** |
| consumer uses read-only shared view | NumPy matrix uses mapped buffer | **成立** |
| end-to-end zero-copy | `bytes(buffer)` full-copy integrity check exists | **不成立** |
| Logit payload = logprob | current contract uses normalized candidate probabilities | **旧术语** |
| Logit backend can transparently fallback | publish only accepts SHM | **policy/provider mismatch** |
| Ref Registry is state authority | registry lacks owner/session/lease and worker does not enforce registry/grant binding | **尚未成立** |
| backend matrix proves speed | code explicitly says realization diagnostic only | **没有做速度 claim，正确** |

---

# 93. Migration Plan

不要一次重构。

推荐：

```text
S0 Source Truth / Metrics
    ↓
S1 State Access Binding
    ↓
S2 Lifecycle Hardening
    ↓
S3 Remove Validation Full Copy
    ↓
S4 Persistent Worker
    ↓
S5 Materializer Registry
    ↓
S6 Durable Registry
    ↓
S7 Generic State Descriptor
```

---

# 94. S0 — Source Truth / Metric Semantics

第一刀尽量不改 data-plane 核心行为。

修：

```text
Dense backend claim
zero-copy claim
trusted-worker authority boundary
metric naming
doc/source mismatch
```

### S0.1

明确：

```text
Dense Semantic = SHM/mmap current mainline
```

### S0.2

明确：

```text
cross-process mapped view
NOT end-to-end zero-copy
```

### S0.3

明确：

```text
current worker is trusted
CapabilityGrant binding is incomplete
```

### S0.4

把：

```text
semantic_state_transfer_count
```

改成：

```text
semantic_state_cross_process_resolve_count
```

### S0.5

把 StateConsumption：

```text
behavioral_effect
```

拆成：

```text
mechanistic_effect
counterfactual_behavioral_effect
```

---

# 95. S1 — State Access Binding

加入：

```text
BoundRefHandle
StateAccessGrant
```

Gate：

```text
wrong grant
wrong session
wrong state digest
wrong operation
expired grant
```

必须 fail closed。

---

# 96. S2 — Lifecycle Hardening

先不做复杂 refcount。

先修：

```text
idempotent release
semantic tombstone
active metadata cleanup
duplicate ref rejection
materialize rollback
```

这是一组 correctness hardening，不需要引入复杂系统。

---

# 97. S3 — Remove Validation Full Copy

只改 integrity path：

```text
bytes(buffer)
→ direct buffer hash
```

然后跑 E0/E1。

Acceptance：

```text
validation_copy_bytes == 0
quality / selected IDs unchanged
hash mismatch still rejected
```

---

# 98. S4 — Persistent Worker

把 Adaptive Semantic：

```text
Popen per bundle
```

改成：

```text
long-lived ExecutorTransport / WorkerPool
```

这是 Round 05 最大的 runtime-performance slice。

---

# 99. S5 — Materializer Registry

把：

```text
StorageKind enum + if/else
```

演进成：

```text
backend descriptors
materializer implementations
eligibility
placement policy
```

这样 Logit / Dense 的 provider eligibility 就不会互相打架。

---

# 100. S6 — Durable Registry

先实现：

```text
publication-last
atomic temp+rename
```

如果长期需要：

```text
concurrent writer
query by owner/session/state
lease update
```

再迁：

```text
SQLite
```

不要一开始上复杂外部 DB。

---

# 101. S7 — Generic State Descriptor 最后做

不要第一步抽象：

```text
UniversalTensorState
```

先把两条真实 path：

```text
Dense Semantic
Logit
```

的 authority/lifecycle/performance 做对。

再抽共性。

---

# 102. Round 05 第一刀建议

建议 Codex Slice：

# `STATE-R05-S0-SOURCE-TRUTH-AND-AUTHORITY-GAPS`

Scope：

```text
docs/implementation/state/*
statebus/control/messages.py
statebus/control/subprocess_worker.py
statebus/state/semantic_state.py
statebus/runtime/state_consumption.py
tests/test_embedding_state_consumer.py
```

输出：

1. Source Truth 文档修正。
2. Metric rename / claim boundary 修正。
3. State authority gap 明确测试化。
4. 不做 generic materializer 重构。
5. 不做 KV。

---

# 103. 第二 Slice

# `STATE-R05-S1-BOUND-REF-ACCESS-GRANT`

加入：

```text
state digest
session
operation
grant binding
```

---

# 104. 第三 Slice

# `STATE-R05-S2-LIFECYCLE-HARDENING`

修：

```text
idempotent release
duplicate ref
tombstone
rollback
```

---

# 105. 第四 Slice

# `STATE-R05-S3-ZERO-COPY-VALIDATION`

只改：

```text
hash path
copy accounting
```

---

# 106. 第五 Slice

# `STATE-R05-S4-PERSISTENT-WORKER`

这才是大性能 Slice。

---

# 107. 推荐新增测试

## Access

```text
test_semantic_state_wrong_grant_rejected
test_semantic_state_wrong_session_rejected
test_semantic_state_wrong_operation_rejected
test_bound_ref_blob_hash_mismatch_rejected
test_bound_ref_manifest_hash_mismatch_rejected
test_expired_state_access_grant_rejected
```

## Lifecycle

```text
test_state_release_is_idempotent
test_duplicate_active_ref_publish_rejected
test_failed_metadata_write_rolls_back_shm
test_failed_metadata_write_rolls_back_memfd
test_semantic_release_writes_tombstone
test_semantic_release_removes_active_metadata
test_expired_state_cannot_accept_new_consumer
```

## Multi-consumer

```text
test_owner_release_waits_for_active_consumers
test_consumer_close_decrements_pin
test_consumer_crash_expires_pin
```

后两项可以后置到 persistent worker 后。

## Copy

```text
test_dense_resolve_does_not_materialize_payload_bytes
test_dense_resolve_returns_readonly_shared_view
test_dense_publish_copy_accounting
```

## Placement

```text
test_policy_never_selects_unregistered_materializer
test_logit_state_backend_eligibility_is_shm_only
test_dense_state_memfd_not_selected_without_fd_resolver
test_total_state_budget_enforced
```

## Registry

```text
test_registry_entry_never_visible_before_sidecar_commit
test_bundle_write_crash_does_not_expose_partial_ref
test_ref_registry_atomic_replace
```

## Worker

```text
test_persistent_worker_handles_multiple_state_requests
test_persistent_worker_pid_stable
test_persistent_worker_no_cross_session_state_access
test_worker_restart_invalidates_old_access_grants
```

---

# 108. Competition Evidence 应该怎么写

不要只写：

```text
StateBus uses shared memory.
```

应该写：

```text
For N tasks:

full candidate text before state selection:
    X MB

binary semantic state published:
    Y MB

UDS control-plane wire bytes:
    Z KB

selected text hydrated:
    A MB

prompt-visible text avoided:
    B MB

quality:
    baseline / adaptive

warm handoff latency:
    p50 / p95

cross-process state consumption:
    N/N

unauthorized state negative tests:
    all rejected
```

---

# 109. 最有价值的比赛图

```text
Candidate Surface
      │
      │ embeddings
      ▼
┌───────────────┐
│ Binary State  │
└───────┬───────┘
        │ Ref only over UDS
        ▼
┌───────────────┐
│ Worker select │
└───────┬───────┘
        │ selected IDs
        ▼
┌───────────────┐
│ Hydrate text  │
└───────┬───────┘
        ▼
      LLM
```

旁边标：

```text
control wire bytes
binary state bytes
hydrated bytes
avoided bytes/tokens
```

---

# 110. StateBus 与普通文本 Agent Handoff 的真正区别

不是：

```text
用了 Protobuf
```

Protobuf 本身不是创新。

普通：

```text
Agent A
   ↓
full text payload
   ↓
Agent B
```

StateBus：

```text
Producer
   ↓
typed state object
   ↓
Ref
   ↓
authorized consumer-side operation
   ↓
selected business identities
   ↓
minimal hydration
```

真正的核心是：

> **state remains a first-class runtime object.**

---

# 111. Current State Plane 评级

| 维度 | 当前评价 |
|---|---|
| Typed State Representation | **强** |
| Dense contract integrity | **强** |
| Cross-PID real consumption | **强** |
| Control/Data plane separation | **强** |
| Hydrate lineage | **强** |
| Storage fallback mechanism | **中强** |
| Physical materializer abstraction | **中弱** |
| Capability-bound state access | **弱 / 未闭环** |
| Session authorization | **弱** |
| Ref identity sealing | **中弱** |
| Zero-copy read semantics | **中等：最终 view 是，validation 仍 copy** |
| Publish copy efficiency | **中等** |
| Persistent worker readiness | **弱** |
| Lifecycle | **中弱且多实现不一致** |
| Multi-consumer ownership | **缺失** |
| Crash atomicity | **弱** |
| Telemetry dimensions | **中强** |
| Communication accounting | **仍需拆细** |
| Generic latent-state readiness | **尚未到位** |
| Competition differentiation | **很强** |

---

# 112. 最终判断

Round 05 最重要的结论：

> **StateBus 已经拥有真实的非文本跨进程数据面，但目前 strongest truthful claim 应该是“typed Ref + shared binary state + Ref-only UDS control + cross-process selection + controlled hydration”，而不是“通用 hidden-state communication”或“end-to-end zero-copy”。**

当前真正应该优化的不是继续增加 State 类型，而是：

```text
Identity
Authority
Lifecycle
Copy Path
Worker Lifetime
Measurement
```

---

# 113. 推荐优先顺序

```text
S0 Source Truth
    ↓
S1 State Access Binding
    ↓
S2 Lifecycle
    ↓
S3 Remove validation copy
    ↓
S4 Persistent worker
    ↓
S5 Materializer Registry
    ↓
S6 Durable registry
    ↓
S7 Generic state abstraction
```

---

# 114. 和 Round 03 / 04 的联合顺序

不能忘记前面的 P0。

推荐整个项目联合推进：

```text
Round03 C0
Verified Recipe Identity

        ↓

Round04 M1
Memory Evidence Semantics

        ↓

Round05 S0/S1
State Source Truth + Authority

        ↓

Round05 S2/S3
Lifecycle + Copy

        ↓

Round04 M3/M4
Independent Memory Plane + Binding

        ↓

Round05 S4
Persistent Worker

        ↓

External Benchmarks
```

---

# 115. Round 06 该走什么

Round 05 完成后，最自然的 Round 06 是：

# **Inference Reuse Plane — Prefix/APC / EngineLocalKV / vLLM KV Reuse 全链审计**

原因是 Generic State Data Plane 与 LLM Engine KV Reuse 必须保持架构边界。

Round 06 重点应查：

```text
CanonicalSharedEvidencePrefix
ExactTokenPrefixIdentity

vLLM APC
prefix hit observation

EngineLocalKVHandle
capture
ownership
scheduler proof
forward proof
one-shot consume
release

KV physical bytes
model / engine generation compatibility
```

Round 06 最关键的问题会是：

```text
哪些是 Runtime control-plane identity
哪些是真实 KV data reuse
哪些只是 cache-affinity hint
哪些真的跳过 prefill / transfer / recompute
```

这正好和 Round 05 分开。

---

# Appendix A — 本轮源码范围

```text
statebus/refs/models.py

statebus/contracts/models.py
statebus/contracts/adaptive.py

statebus/state/store.py
statebus/state/semantic_state.py
statebus/state/logit_state.py
statebus/state/disk.py

statebus/control/messages.py
statebus/control/transport.py
statebus/control/subprocess_worker.py

statebus/runtime/adaptive_dispatcher.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/state_consumption.py
statebus/runtime/neural_state.py

statebus/benchmark/backend_matrix.py

tests/test_state_materialization.py
tests/test_embedding_state_consumer.py
tests/test_subprocess_executor.py
tests/test_logit_state.py
```

---

# Appendix B — 当前源码特别值得保留的设计

不要因为问题多就推倒。

值得保留：

```text
RefHandle control-plane idea
DenseSemanticStateContract
encoder signature
HydrateManifest row binding
read-only consumer matrix
SHM / mmap fallback
cross-PID proof
producer / consumer PID receipt
candidate ID rather than raw text return
state consumption receipt
control wire audit
backend matrix claim boundary
```

---

# Appendix C — 外部参考

## Ray

Repository：

```text
https://github.com/ray-project/ray
```

本轮只借：

```text
ObjectRef / immutable object identity
same-node shared object
ownership
reference lifetime / pinning
GC
spill / placement under pressure
```

不借：

```text
GCS
cluster scheduler
distributed object manager
```

StateBus 当前需求只需要同机版本。

---

# Appendix D — 一句话总结

> **Round 05 的任务不是证明“我们会用 shared_memory”，而是把 StateBus 从“两个可工作的跨进程非文本状态实验路径”升级为一个真正有 Ref Identity、Capability-bound Access、Physical Placement、Lifecycle、Persistent Consumer 和可量化通信收益的 Shared-State Runtime。**
