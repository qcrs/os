# StateBus Batch 03 — Artifact Lifecycle / Verification / Commit / Replay Truthfulness 全链源码审计

> 项目：`qcrs/os`  
> 分支：`master`  
> 审计基线：`8bfc6464ec236c0e121911095fc283129b0e7696`  
> 日期：2026-09-03  
> 本轮状态：**只审计 / 只分析，不修改代码**  
>
> 审计主链：
>
> ```text
> Candidate Output
>     ↓
> Artifact Content / Manifest
>     ↓
> Input / Output / Capability Validator
>     ↓
> CapabilityQualityReport
>     ↓
> VERIFIED
>     ↓
> Settlement / Invalidation
>     ↓
> Replay Eligibility
>     ↓
> Artifact Restore / Recipe Recompute
>     ↓
> Memory Admission
> ```
>
> 本轮目标不是判断“有没有 SHA256”，而是回答六个问题：
>
> 1. **Artifact 的内容身份是什么？**
> 2. **谁有权把 Candidate 提升成 VERIFIED？**
> 3. **VERIFIED 到底代表哪一级正确性？**
> 4. **Artifact 状态失效后，旧 Ref 是否还能被使用？**
> 5. **Artifact VERIFIED 为什么可以/不可以 Replay？**
> 6. **Artifact Truth、Replay Truth、Memory Truth、Answer Adoption 是否被错误地绑在一起？**

---

# 1. Executive Summary

这一轮最重要的结论是：

> **StateBus 已经有相当不错的 Artifact 内容 hash、Capability Quality Report、历史 Replay hash 校验和下游 rehydrate 校验，但 Artifact Truth Promotion 目前没有唯一 Authority Owner；Artifact 内容身份、生成过程、验证强度、Replay 资格、Memory 写入资格、Answer Adoption 仍被多个字段和多条路径混在一起。**

当前至少存在两套 Artifact “晋级”体系：

```text
A. Legacy / General Commit Gate

Candidate
   ↓
InputValidatorReport
ArtifactValidatorReport
QualityFloor
AnswerAdopted
   ↓
RuntimeCommitGate
   ↓
VERIFIED / INVALIDATED
   ↓
Settlement
   ↓
Memory Commit
```

以及：

```text
B. Adaptive Product Mainline

DSL / CodeAct / Projection / Summarizer
   ↓
各自局部 ArtifactLifecycleManager()
   ↓
register_candidate()
   ↓
mark_verified()
   ↓
AdaptiveDispatchContext.artifacts
   ↓
下游直接消费
   ↓
Mainline 最后再单独判断是否 Memory Commit
```

这两套体系的最大区别是：

```text
Legacy:
“中央 CommitGate 决定 Artifact Truth”

Adaptive:
“Producer 自己完成局部验证，然后自己 mark_verified”
```

因此现在没有一个统一的：

# **Artifact Verification Authority**

这不是说 Adaptive 路径“不验证”。

事实上：

- DSL 有 schema + business validator + recomputation；
- CodeAct 有 sandbox + output validator + capability validator；
- ClaimSet 有 claim validator；
- Projection 是 deterministic Runtime transform；
- 下游还会重新读取真实文件并验证 blob hash。

问题在于：

> **这些不同强度、不同来源的验证最终都被压扁成同一个 `RefStatus.VERIFIED`，并且 `mark_verified()` 自动赋予 `replay_ready=True`。**

这是 Batch 03 的核心架构问题。

---

# 2. 当前 Artifact Truth 主链地图

主要源码：

```text
statebus/refs/models.py

statebus/runtime/workspace.py
statebus/runtime/commit_gate.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/transform_dsl.py
statebus/runtime/llm_codeact.py
statebus/runtime/evidence_projection.py
statebus/runtime/capability_validators.py
statebus/runtime/replay.py

statebus/state/disk.py

tests/test_replay.py
tests/test_adaptive_codeact_integration.py
tests/test_adaptive_mainline_integration.py
tests/test_adaptive_claims.py
...
```

核心对象：

```text
ExecutionArtifactRef
InputManifest
ArtifactOutputManifest

ArtifactValidatorReport
InputValidatorReport
CapabilityQualityReport

ArtifactSettlementRecord
ArtifactInvalidationRecord

ArtifactLifecycleManager
RuntimeCommitGate

ReplayCandidate
ReplayLedgerEntry
HistoryReplayRecord
MemoryCommit
```

---

# 3. `ExecutionArtifactRef` 当前表达了什么

当前 Artifact Ref：

```python
ExecutionArtifactRef(
    artifact_id,
    task_id,
    step_id,
    artifact_type,

    root_id,
    relpath,

    blob_hash,
    size_bytes,

    produced_by,

    verification_state,
    replay_ready,

    workspace_relpath,
    manifest_hash,

    metadata,
)
```

它已经同时承载四类语义：

```text
A. Logical identity
    artifact_id
    task_id / step_id

B. Physical location
    root_id
    relpath
    workspace_relpath

C. Content identity
    blob_hash
    size_bytes

D. Lifecycle / reuse
    verification_state
    replay_ready

E. Derivation / sidecar pointer
    manifest_hash
    metadata
```

这在早期很方便。

但随着 Artifact 类型增多，它已经开始出现：

```text
one field
multiple semantics
```

的问题。

最典型的就是：

# `manifest_hash`

---

# 4. P0 — `manifest_hash` 的语义已经发生严重 Overload

Legacy History Replay 中：

```text
ExecutionArtifactRef.manifest_hash
=
ArtifactOutputManifest.manifest_hash
```

这是一种很清晰的语义：

```text
Artifact Ref
    ↓ manifest_hash
ArtifactOutputManifest
    ↓
output name / relpath / size / sha256
```

但是 Adaptive 主线不同 Producer 填的值并不一样。

---

# 5. Projection Artifact 的 `manifest_hash`

`EvidenceProjectionAdapter` 当前写：

```text
manifest_hash
=
EvidenceProjectionRequest.request_hash
```

所以这里的 `manifest_hash` 实际是：

```text
Projection Request Identity
```

不是：

```text
ArtifactOutputManifest Identity
```

。

---

# 6. Transform DSL Artifact 的 `manifest_hash`

`TransformDslInterpreter.run_verified()` 写：

```text
manifest_hash
=
TransformProgram.program_hash
```

所以这里实际是：

```text
Derivation / Program Identity
```

。

---

# 7. CodeAct Artifact 的 `manifest_hash`

`LlmCodeActRunner` 写：

```text
manifest_hash
=
CodeGenerationRequest.input_manifest_digest
```

这里又变成：

```text
Input Manifest / Semantic Input Identity
```

。

---

# 8. ClaimSet Artifact 的 `manifest_hash`

Summarizer 写：

```text
manifest_hash
=
sha256(claim_set.canonical_payload())
```

它几乎等于：

```text
ClaimSet Content Identity
```

。

---

# 9. 当前四种语义汇总

| Artifact Producer | `manifest_hash` 实际指向 |
|---|---|
| Legacy History Artifact | `ArtifactOutputManifest.manifest_hash` |
| Evidence Projection | Projection Request hash |
| Transform DSL | Program hash |
| LLM CodeAct | Input manifest digest |
| ClaimSet | ClaimSet content hash |

所以：

> **`ExecutionArtifactRef.manifest_hash` 已经没有统一 referent。**

这不是命名风格问题。

它会直接影响：

```text
Ref Registry
History Replay
Artifact Persistence
Cross-run Restore
Audit
Future CAS
```

。

因为 Legacy `runtime/replay.py::_load_history_artifact_ref()` 明确假设：

```text
entry.manifest_hash
    ↓
read_artifact_output_manifest(manifest_hash)
```

对 Adaptive DSL / CodeAct / Projection / Claim Artifact，这个假设并不成立。

因此当前：

# Adaptive Artifact Ref 与 Legacy Artifact Replay Contract 并不是统一 ABI。

---

# 10. Target：Artifact Content 与 Artifact Derivation 必须拆开

推荐以后不要继续用一个 `manifest_hash` 表达所有东西。

至少概念上拆成：

```text
ArtifactContentDescriptor
    ↓
“产物本身是什么”

ArtifactDerivationReceipt
    ↓
“它是怎么被生成的”

ArtifactVerificationReceipt
    ↓
“Runtime 验证了什么”

ArtifactLocationBinding
    ↓
“现在在哪里 materialize”
```

这四件事生命周期都不同。

---

# 11. P0 — `mark_verified()` 不是 Verification，它只是状态切换

当前：

```python
ArtifactLifecycleManager.mark_verified(artifact_id)
```

逻辑本质是：

```text
取当前 ArtifactRef
    ↓
verification_state = VERIFIED
replay_ready = True
    ↓
写回 dict
```

它本身没有验证：

```text
文件是否存在
size 是否一致
blob hash 是否一致
validator report 是否存在
validator report 是否通过
quality report 是否绑定该 output hash
input lineage 是否完整
CapabilityGrant 是否匹配
```

。

因此：

> `mark_verified()` 这个名字比真实行为强。

它实际更像：

```text
promote_to_verified_state()
```

并假设：

```text
调用方已经完成所有验证
```

。

---

# 12. 这本身不是绝对错误

很多系统都会有：

```text
validator
    ↓
commit state transition
```

。

问题在于当前：

```text
没有一个统一 ArtifactVerificationPolicy
来决定谁有资格调用 mark_verified
```

。

Projection、DSL、CodeAct、Summarizer 都自己构造一个新的：

```python
ArtifactLifecycleManager()
```

然后直接：

```text
register_candidate()
mark_verified()
```

。

所以 `ArtifactLifecycleManager` 并不是一个真正共享的 Runtime authority object。

---

# 13. P0 — Artifact Truth Promotion 存在两套 Authority

## Path A — `RuntimeCommitGate`

旧路径：

```text
quality floor
+
answer adopted
+
artifact validator reports
+
input validator reports
    ↓
mark_verified
    ↓
Memory commit
    ↓
Settlement
```

。

这里 promotion 是：

```text
Centralized
```

。

---

# 14. Path B — Adaptive Producers

### Evidence Projection

```text
Projection deterministic transform
    ↓
register_candidate
    ↓
mark_verified
```

。

### Transform DSL

```text
program validation
business quality validation
    ↓
run_verified()
    ↓
register_candidate
    ↓
mark_verified
```

。

### CodeAct

```text
Source Policy
Sandbox
Output Validator
CapabilityQualityReport
    ↓
register_candidate
    ↓
mark_verified
```

。

### ClaimSet

```text
ClaimSetValidator
    ↓
register_candidate
    ↓
mark_verified
```

。

这些 Artifact 进入：

```text
AdaptiveDispatchContext.artifacts
```

以后，下游就可以按：

```text
verification_state == VERIFIED
```

消费。

---

# 15. 这意味着什么

现在 Artifact Truth 的 owner 是：

```text
Producer-local validator + Producer-local lifecycle
```

而不是：

```text
Runtime Artifact Authority
```

。

这和 StateBus 一直强调的：

```text
Agents propose;
Runtime authorizes.
```

在 Artifact 层还不完全一致。

更准确：

```text
Provider validates and self-promotes;
Runtime later consumes the promoted Ref.
```

。

---

# 16. P0 — `VERIFIED` 自动意味着 `replay_ready=True`

当前 `mark_verified()`：

```text
VERIFIED
+
replay_ready=True
```

是一起发生的。

这是这一轮最重要的设计耦合之一。

因为：

# Artifact Verification ≠ Replay Eligibility

---

# 17. 为什么两者不同

Artifact Verification 回答：

```text
“这个输出现在能不能被当前 Workflow 当成有效 Artifact 使用？”
```

Replay Eligibility 回答：

```text
“未来另一个运行能不能跳过某些计算，直接复用这个 Artifact / Recipe？”
```

后者需要额外考虑：

```text
determinism
runtime version
provider version
validator version
input identity
output contract
policy version
source/program identity
side effects
security scope
lifetime
```

。

因此：

```text
Artifact valid now
```

绝对不自动推出：

```text
Artifact safe to replay later
```

。

---

# 18. Generic Validator 正好证明这个问题

`CapabilityQualityReport` 已经有很好的 nuance：

```text
verified
recomputation_evaluated
recomputation_passed
semantic_verification_status
```

。

例如 `generic_analysis`：

```text
schema/provenance/completion checks
可以全部通过

verified = True

但是：

recomputation_evaluated = False
recomputation_passed = False
semantic_verification_status = not_evaluated
```

。

这说明 Contract 层已经承认：

```text
VERIFIED
```

并不总表示：

```text
独立语义重算已证明正确
```

。

但 Artifact 层把所有这些情况压成：

```text
RefStatus.VERIFIED
replay_ready=True
```

。

因此信息被丢失了。

---

# 19. 推荐 `VerificationStrength`

建议未来 Artifact Verification 至少区分：

```text
STRUCTURAL
    文件/hash/schema/provenance 检查

CONTRACT_VALIDATED
    Capability 业务合同已检查

INDEPENDENT_RECOMPUTATION
    Runtime 独立重算并与 output 比较

EXTERNAL_EVALUATED
    只作为外部 benchmark audit
    不进入 Runtime replay authority
```

其中：

```text
EXTERNAL_EVALUATED
```

不能把 benchmark private grader 回灌 Runtime。

它只是 Harness 的 Evidence。

---

# 20. P0 — `RuntimeCommitGate` 把 Answer Adoption 混进 Artifact Truth

当前 `RuntimeCommitGate.finalize()`：

```text
if:
    quality_floor_pass
    AND answer_adopted
    AND validator_reports_passed
    AND input_validators_passed

then:
    Artifact → VERIFIED
```

否则：

```text
Artifact → INVALIDATED
```

。

这意味着：

```text
Artifact 技术上完全正确
+
Validator 全通过
+
Quality Floor 通过
+
用户/上层没有 adopted
```

仍然会：

```text
INVALIDATED
```

。

这是错误的语义耦合。

---

# 21. 更具体的代码问题：错误 Invalidation Reason

Else 分支的 invalidation reason：

```text
input_validator_failed
else validator_failed
else quality_floor_failed
```

没有：

```text
answer_not_adopted
```

这个分支。

所以：

```text
quality_floor_pass = True
validators = True
answer_adopted = False
```

最终会记录：

```text
invalidation_reason = quality_floor_failed
quality_floor_pass = False
```

。

但真实情况明明：

```text
quality floor passed
```

。

这是一个明确的：

# **Audit Truth Bug**

。

---

# 22. Artifact Truth / Answer Adoption 应彻底分开

正确关系：

```text
Artifact Verification
    ├─ verified
    └─ invalid

Answer Adoption
    ├─ adopted
    └─ not adopted

Memory Admission
    ├─ admitted
    └─ rejected

Replay Eligibility
    ├─ eligible
    └─ ineligible
```

四个状态应该正交。

例如：

```text
Artifact:
VERIFIED

Answer:
NOT_ADOPTED

Memory:
NOT_ADMITTED

Replay:
ELIGIBLE
```

完全合法。

---

# 23. 更有意思的是：Adaptive Mainline 又使用了另一种 Adoption 语义

Adaptive `_commit_verified_memory()` 最终直接：

```python
memory_store.commit_candidate(
    quality_floor_pass=True,
    answer_adopted=True,
)
```

也就是：

```text
answer_adopted=True
```

被硬编码。

它不是用户 adoption，也不是 final answer adoption。

它只是：

```text
“Runtime 决定把 verified recipe 写 Memory”
```

。

因此现在同一个字段：

```text
answer_adopted
```

在两套路径中实际上有不同含义。

---

# 24. P0/P1 — Empty Validator Tuple 会 Vacuous Pass

`RuntimeCommitGate`：

```python
validator_reports_passed = all(validator_reports)
input_validators_passed = all(input_validator_reports)
```

准确代码是对 `report.passed` 做 `all(...)`。

如果传：

```text
validator_reports = ()
input_validator_reports = ()
```

Python：

```text
all(()) == True
```

。

所以 CommitGate Contract 本身允许：

```text
没有任何 validator report
```

却被视为：

```text
validators_passed = True
```

。

如果上层的 `quality_floor` 与 adoption 又是 True：

```text
Artifact 可以 VERIFIED
```

。

当前某些 caller 可能总会提供 report，所以这不一定已形成实际主线 bug。

但作为：

```text
Runtime Truth Promotion API
```

这是明显的 fail-open contract seam。

---

# 25. P0/P1 — Artifact Lifecycle 没有合法 Transition Policy

当前 Lifecycle Manager：

```text
register_candidate
mark_verified
mark_invalidated
```

只是覆盖状态。

例如：

```text
CANDIDATE → VERIFIED
```

可以。

但：

```text
INVALIDATED → VERIFIED
```

同样可以直接调用。

也没有：

```text
VERIFIED → VERIFIED
```

重复 promotion 限制。

没有：

```text
expected_previous_state
```

。

所以它现在不是严格 state machine。

---

# 26. 推荐真正的 Lifecycle State Machine

第一版不需要复杂：

```text
PRODUCING
    ↓
CANDIDATE
    ↓
VERIFIED
    ↓
ACTIVE
    ├─ SUPERSEDED
    ├─ INVALIDATED
    └─ EXPIRED
```

。

其中：

```text
ReplayEligibility
```

仍然保持 orthogonal。

---

# 27. P1 — `ArtifactLifecycleManager` 是局部 ephemeral object

DSL：

```python
lifecycle = ArtifactLifecycleManager()
```

CodeAct：

```python
lifecycle = ArtifactLifecycleManager()
```

Projection：

```python
lifecycle = ArtifactLifecycleManager()
```

Summarizer：

```python
lifecycle = ArtifactLifecycleManager()
```

。

每个 Producer 都临时创建自己的 manager。

返回 ArtifactRef 以后：

```text
manager 自身很快失去作用域
```

。

---

# 28. 这会导致 Logical Revocation 问题

下游 Context 中保存：

```text
一个 immutable ExecutionArtifactRef
verification_state = VERIFIED
```

假如后来 Artifact 被：

```text
INVALIDATED
```

某个旧 holder 手里的 Ref 仍然是：

```text
VERIFIED
```

。

当前下游 `_artifact_in_grant_scope()` 主要检查这个本地 Ref 的：

```text
verification_state
task
session
attempt
```

不会去一个 central lifecycle registry 查询：

```text
这个 artifact 现在是不是仍 ACTIVE
```

。

所以：

# **Stale Verified Ref 不具备中央 revocation 语义。**

---

# 29. 当前什么能挡住篡改

这里要区分：

```text
Logical Revocation
```

和：

```text
Content Tampering
```

。

Content Tampering 其实做得不错。

`_read_verified_artifact_rows()` 会：

```text
resolve root/path
确保 path 在 root 下
拒绝 symlink
读取 bytes
检查 size
检查 blob hash
JSON decode
与 cached rows 比较
```

。

所以：

```text
文件内容被改
```

通常会 fail closed。

---

# 30. 但逻辑状态失效不是同一件事

例如：

```text
artifact bytes 没变

但是后来发现：
validator 有 bug
source provenance 被撤销
policy version 失效
```

这种：

```text
Logical INVALIDATED
```

不会改变：

```text
blob hash
```

。

所以仅靠 blob hash 无法表达：

```text
这个 Artifact 还能不能被信任
```

。

必须有 central current-state / verification receipt。

---

# 31. P1 — Settlement / Invalidation 不是 Append-only Event History

`ArtifactLifecycleManager`：

```text
settlement_records[artifact_id] = record
invalidation_records[artifact_id] = record
```

。

`JsonContractStore` 也把：

```text
artifact_settlements/{artifact_id}.json
artifact_invalidations/{artifact_id}.json
```

作为单文件写入。

结果：

```text
同一个 Artifact 后续再发生 transition
```

会覆盖之前对应类型的记录。

---

# 32. 为什么 Artifact 需要 Event History

真正审计经常需要知道：

```text
CANDIDATE
    ↓ validator v1
VERIFIED
    ↓ validator bug found
INVALIDATED
    ↓ re-evaluated with validator v2
? 
```

。

如果只保留：

```text
latest settlement
latest invalidation
```

很多历史会丢失。

---

# 33. 推荐 Append-only Lifecycle Ledger

例如：

```python
ArtifactLifecycleEvent(
    event_id,
    artifact_id,
    content_digest,

    previous_state,
    new_state,

    reason,

    verification_receipt_hashes,
    replay_receipt_hash,

    created_at_ns,

    previous_event_hash,
)
```

。

不一定需要区块链。

一个简单：

```text
append-only JSONL / SQLite event table
```

就够。

---

# 34. P1 — Settlement Record 本身没有进入 Replay 的强 hash chain

`ArtifactSettlementRecord` 有：

```text
settlement_hash
```

property。

但 persistence：

```text
write_artifact_settlement_record()
```

写的是：

```text
record.canonical_payload()
```

不包含：

```text
settlement_hash
```

。

History Replay 读取：

```text
settlement_payload["replay_ready"]
```

直接使用。

没有：

```text
recompute settlement hash
+
compare expected receipt hash
```

。

在当前：

```text
local trusted filesystem
```

模型下不一定是安全漏洞。

但它说明：

```text
settlement
```

目前是：

```text
mutable local metadata
```

不是：

```text
tamper-evident receipt
```

。

---

# 35. P1 — Registry Status 与 Settlement `replay_ready` 没有强一致性检查

History Replay `_load_history_artifact_ref()`：

```text
RefRegistry entry
    ↓
entry.status

ArtifactSettlementRecord
    ↓
replay_ready

ArtifactOutputManifest
    ↓
output hash/path
```

然后构造：

```text
ExecutionArtifactRef(
    verification_state = entry.status,
    replay_ready = settlement.replay_ready
)
```

。

但是后面的 `_history_replay_records()` 只重点检查：

```text
artifact_ref.replay_ready
```

没有明确要求：

```text
artifact_ref.verification_state == VERIFIED
```

。

---

# 36. 这意味着状态不一致时可能出现危险组合

例如持久状态因为 crash / manual mutation / incomplete invalidation 形成：

```text
Registry:
INVALIDATED

Settlement:
replay_ready = True
```

当前 History Replay 仍有机会继续把它当 Replay Candidate。

它最终还会校验 output bytes hash，

但：

```text
内容没变
```

不代表：

```text
logical verification 仍有效
```

。

因此：

# Replay Admission 必须同时验证 Current Lifecycle State。

---

# 37. P1 — Invalidation 传播到 Memory / Replay 目前没有统一机制

Current Artifact 可能同时被引用在：

```text
Context.artifacts

RefRegistry

MemoryRef.artifact_ref_id

ReplayLedger

ArtifactSettlement

Adaptive Mainline manifest
```

。

Artifact invalidation 发生以后：

```text
哪些引用会被更新？
```

目前没有一个统一：

```text
Invalidation Propagation
```

协议。

---

# 38. Target 原则

Memory / Replay 中不要复制：

```text
artifact is trusted
```

这个事实。

而应该保存：

```text
artifact_id / content digest
```

每次使用时查询：

```text
ArtifactAuthorityStore
```

或读取：

```text
current lifecycle / verification receipt
```

。

这样：

```text
一次 invalidation
```

才能全局生效。

---

# 39. P1 — Artifact ID Collision 默认是 Last-write-wins

`register_candidate()`：

```python
self.artifacts[candidate.artifact_id] = candidate
```

没有：

```text
if artifact_id already active:
    reject
```

。

当前 Artifact ID 大多：

```text
task + step + attempt
```

正常 Runtime 下通常唯一。

但 Contract 层仍然没有保证：

```text
same ID cannot bind different content
```

。

这和前面 State Ref duplicate-id 问题一致。

---

# 40. 推荐 Artifact Identity 分层

不要把：

```text
artifact_id
```

同时当：

```text
logical name
content identity
generation identity
```

。

推荐：

```text
artifact_id
    logical artifact identity

generation
    lifecycle generation

content_digest
    immutable bytes identity
```

。

---

# 41. P1 — Workspace Artifact Write 不是 Crash-atomic

`WorkspaceManager.write_json()`：

```text
path.write_bytes(rendered)
```

。

DSL：

```text
output_path.write_bytes(payload)
```

Claim：

```text
output_path.write_bytes(payload)
```

CodeAct sandbox 自己写 output。

目前没有统一：

```text
temp
fsync
atomic rename
```

promotion protocol。

---

# 42. 为什么 hash 不能完全解决 Crash Atomicity

如果 crash 发生在：

```text
write file
    ↓
write metadata
```

之间，

重启以后可能看到：

```text
有 payload
没 registry
```

。

反过来，如果 publication 顺序错：

```text
registry ACTIVE
payload 还没 durable
```

风险更高。

正确顺序：

```text
payload durable
    ↓
verification receipts durable
    ↓
registry visibility last
```

。

---

# 43. P1 — RuntimeCommitGate 不是 Transaction

成功 path：

```text
mark_verified()
    ↓
memory_store.commit_candidate()
    ↓
record_settlement()
```

。

假设：

```text
mark_verified 成功
memory_store 写失败
```

则当前 Runtime 内：

```text
Artifact 已 VERIFIED
```

但：

```text
Memory 未 commit
Settlement 未记录
```

。

---

# 44. 失败 path 也一样

```text
mark_invalidated()
    ↓
memory_store.commit_candidate(candidate)
    ↓
record settlement
    ↓
record invalidation
```

中间任意错误都会留下 partial state。

因此它并不是：

```text
Commit Gate Transaction
```

。

更准确：

```text
Commit Gate Orchestration
```

。

---

# 45. Artifact Truth 和 Memory Truth 不应该放在同一个 Transaction

这里更深一层：

其实没有必要追求：

```text
Artifact + Memory
必须一个跨 Store ACID transaction
```

。

更合理：

```text
Artifact Verification
先独立 durable commit

然后：

MemoryAdmissionPolicy
读取 verified Artifact
    ↓
独立 Memory commit
```

。

如果 Memory commit 失败：

```text
Artifact 仍然 VERIFIED
```

这是正确的。

所以真正应该拆开的是 authority，而不是强绑 transaction。

---

# 46. Target Promotion Protocol

推荐概念流程：

```text
Provider writes temp output
        ↓
Basic structural validation
        ↓
fsync temp
        ↓
compute content digest + size
        ↓
ArtifactContentDescriptor
        ↓
ArtifactDerivationReceipt
        ↓
Capability Validators
        ↓
ArtifactVerificationReceipt
        ↓
atomic materialization / CAS insert
        ↓
Lifecycle Event:
CANDIDATE → VERIFIED
        ↓
Registry ACTIVE pointer commit last
```

之后另走：

```text
ReplayEligibilityPolicy
```

和：

```text
MemoryAdmissionPolicy
```

。

---

# 47. P1 — DSL 的 Quality Report 与最终 Materialized Output 缺显式再绑定

Adaptive DSL path 先：

```text
transform_interpreter.run(program)
    ↓
transformed
```

然后 Validator：

```text
CapabilityQualityReport.output_artifact_hash
=
hash(transformed)
```

。

接着：

```text
TransformDslInterpreter.run_verified()
```

又执行一次：

```text
self.run(program, inputs)
```

然后写 Artifact。

`run_verified()` 只检查：

```text
quality_report.verified
```

没有显式：

```text
quality_report.output_artifact_hash
==
final output_hash
```

。

---

# 48. 当前为什么通常没出问题

因为 DSL Interpreter 是 deterministic。

同一个：

```text
program + inputs
```

第二次通常会生成完全相同 stable rows。

而 Adaptive Mainline 后面的 Memory commit 也会再次验证：

```text
QualityReport.output_artifact_hash
==
Artifact.blob_hash
```

。

所以当前 Mainline Memory commit 有兜底。

---

# 49. 但下游 Artifact 消费发生在 Mainline Memory commit 之前

Artifact 一旦：

```text
run_verified()
→ mark_verified()
```

就进入 Context。

后续 Summarizer 可以读取。

因此：

```text
final output digest
和 quality report digest
```

最好在 Artifact promotion 当场绑定，

不能依赖后面的 Memory commit 再证明。

---

# 50. CodeAct 在这一点反而更完整

CodeAct：

```text
sandbox output
    ↓
_validate_output()
    ↓
output_hash
    ↓
CapabilityQualityReport(output_artifact_hash=output_hash)
    ↓
ExecutionArtifactRef(blob_hash=output_hash)
```

因此：

```text
QualityReport
Artifact
```

在同一份真实 sandbox output bytes 上绑定。

这是好的。

---

# 51. P1 — Verification Strength 被 `RefStatus` 压扁

我们可以把当前 Artifact producer 分类：

| Producer | 实际验证强度 |
|---|---|
| Evidence Projection | Trusted deterministic Runtime transform |
| Transform DSL | Contract + often independent recomputation |
| CodeAct generic | Sandbox + schema/provenance/contract，可能未 independent recompute |
| CodeAct formal business validator | 可能 independent recompute |
| ClaimSet | Structural claim/provenance validation |
| Legacy CommitGate artifact | 取决于 supplied validators / quality floor |

但全部最终：

```text
verification_state = VERIFIED
```

。

所以消费者无法单从 RefStatus 知道：

```text
这个 Artifact 到底被验证到了哪一层
```

。

---

# 52. 推荐 Verification Receipt 而不是增加十几个 RefStatus

不要做：

```text
VERIFIED_SCHEMA
VERIFIED_RECOMPUTED
VERIFIED_PROVENANCE
...
```

让状态机爆炸。

更合理：

```text
Artifact state = VERIFIED

VerificationReceipt:
    schema_passed
    provenance_passed
    contract_passed
    recomputation_evaluated
    recomputation_passed
    verification_strength
    validator identities
```

。

Consumer policy 决定：

```text
当前 capability 需要哪一级 VerificationStrength
```

。

---

# 53. History Replay 当前做对了什么

这一部分必须肯定。

`tests/test_replay.py` 已经专门构造：

```text
declared output hash
≠
actual output bytes
```

然后要求：

```text
load_history_replay_candidates()
    ↓
{}
```

。

`_matching_history_output_path()` 也确实会：

```text
read actual bytes
    ↓
sha256
    ↓
compare expected blob hash
```

。

所以：

# History Replay 不是只相信 metadata。

这是很重要的正确设计。

---

# 54. P1 — History Replay 的 Path Verification 比 Adaptive Artifact Read 弱

Adaptive `_read_verified_artifact_rows()`：

```text
root.resolve(strict=True)

path.resolve(strict=True)

path.is_relative_to(root)

reject symlink

is_file

size check

blob hash check
```

。

History `_matching_history_output_path()` 当前主要：

```text
construct path
exists
read bytes
hash match
```

。

没有同等级的：

```text
resolved containment
symlink rejection
size check
```

。

---

# 55. 为什么这个值得修

History Root 是：

```text
persisted / imported state
```

比同一 process 内刚生产的 Artifact 更应该使用严格 path validation。

Target 应统一一个：

```text
ArtifactResolver
```

，所有：

```text
current run
history replay
memory restore
```

都调用同一份 path/content verification。

---

# 56. Exact Replay Key 本身不包含 Output Hash —— 这不是 Bug

Current exact key：

```text
CanonicalTaskSpec
input artifact hashes
runtime signature
code template version
extractor version
output contract
```

没有：

```text
historical output hash
```

。

这是合理的。

因为 lookup 时是在回答：

```text
“当前 action/input identity
是否和历史 action/input identity 相同？”
```

输出 hash 是：

```text
cache result descriptor
```

的一部分，不应成为 lookup key 的必要输入。

---

# 57. 但 Exact Replay 需要 Determinism Contract

真正的问题是：

> 这些 key 是否完整捕获了所有决定输出的因素？

例如：

```text
model identity
temperature
random seed
provider version
program/source hash
tool version
environment variables
time-dependent input
external network state
```

。

如果 Artifact producer 不是 deterministic，

就算 input key 一样：

```text
output
```

也未必应该直接 restore。

因此推荐：

```text
DeterminismClass
```

。

---

# 58. 推荐 DeterminismClass

```text
DETERMINISTIC
    DSL / pure deterministic builtin

BOUNDED_REEXECUTABLE
    Code recipe 可重算，但 output 不应直接 restore

NONDETERMINISTIC
    model/tool/environment dependent

EXTERNAL_STATE_DEPENDENT
    时间/网络/外部服务依赖
```

。

然后：

```text
ARTIFACT_RESTORE
```

只允许：

```text
DETERMINISTIC
+
exact identity
```

。

而 CodeAct / LLM 过程更自然：

```text
RECIPE_RECOMPUTE
```

。

---

# 59. 这与 Round 04 Replay Taxonomy 完全一致

推荐继续冻结：

```text
ASSIST_CONTEXT
RECIPE_RECOMPUTE
ARTIFACT_RESTORE
```

。

不要继续让：

```text
EXACT_REPLAY
```

一个词同时表示：

```text
exact recipe
exact artifact
```

。

---

# 60. P1 — Adaptive Artifact 目前通常没有完整 ArtifactOutputManifest / Settlement

Adaptive Producer 创建：

```text
ExecutionArtifactRef
```

后存进 Context。

但它们一般不会自动写：

```text
ArtifactOutputManifest
ArtifactSettlementRecord
RefRegistry Entry
```

形成一个与 Legacy History Replay 一致的 bundle。

这说明：

```text
Adaptive Runtime Artifact
```

当前主要是：

```text
in-run Ref
```

。

而：

```text
Legacy Replay Artifact
```

是：

```text
persisted replay bundle
```

。

两者还没有统一 Artifact persistence ABI。

---

# 61. 这会影响什么

未来如果想：

```text
Adaptive Run A
产生 Artifact
    ↓
Run B
Exact Artifact Restore
```

不能只拿：

```text
ExecutionArtifactRef
```

就认为 old Replay loader 一定能识别。

必须先统一：

```text
ArtifactContentDescriptor
ArtifactDerivationReceipt
ArtifactVerificationReceipt
ArtifactLifecycleReceipt
ArtifactLocation
```

。

---

# 62. P1 — Root Identity 语义也不统一

Adaptive Artifact：

```text
root_id
通常是绝对 attempt workspace path
```

。

Legacy History Test：

```text
root_id = "workspace"
```

真正 Replay 查文件时又主要通过：

```text
RuntimeTaskSession.workspace_root
+
artifact relpath
```

。

所以：

```text
root_id
```

当前同时可能表示：

```text
physical absolute path
logical root name
```

。

这和 `manifest_hash` 一样，是 contract semantic overload。

---

# 63. 推荐 `ArtifactLocationBinding`

```python
ArtifactLocationBinding(
    artifact_digest,
    materialization_id,

    root_kind,
    root_id,

    relpath,

    readonly,

    created_at_ns,
)
```

。

Content identity 不依赖 location。

同一个 Artifact 可以：

```text
workspace materialization
CAS materialization
history import
```

有多个 location。

---

# 64. 外部对照 1：OCI Content Descriptor

OCI 的 Content Descriptor 核心非常简单：

```text
mediaType
digest
size
```

并强调：

```text
从不可信 source 读取内容时
先检查 size
再验证 digest
再做重处理
```

。

StateBus 不需要实现 OCI Image。

值得借的只有：

> **Artifact 的 content identity 应该极小、稳定、与 provenance 分离。**

对应：

```python
ArtifactContentDescriptor(
    media_type,
    digest,
    size_bytes,
)
```

。

当前 `ExecutionArtifactRef.blob_hash + size_bytes + artifact_type`
已经非常接近。

应该保留并强化。

---

# 65. 外部对照 2：Bazel Action Cache + CAS

Bazel Remote Cache 明确分成：

```text
Action Cache
    action hash
        ↓
    result metadata

Content Addressable Store
    content hash
        ↓
    output bytes
```

。

这个分离对 StateBus 非常有启发。

当前 StateBus 把：

```text
program hash
input manifest hash
output manifest hash
claim hash
```

都塞进：

```text
manifest_hash
```

。

更合理：

```text
Action / Derivation Identity
    ↓
ArtifactDerivationReceipt

Content Identity
    ↓
Artifact CAS Descriptor
```

。

Replay：

```text
Action/Replay Key
    ↓
Result Descriptor
    ↓
CAS Digest
```

而不是：

```text
一个 manifest_hash 搞定一切
```

。

---

# 66. 外部对照 3：Nix Content Address vs Derivation

Nix 的一个非常适合 StateBus 的思想是：

> **Output 的 content address 只取决于 output object 本身；它如何被构建，是另一条 derivation identity。**

这正好映射：

```text
Artifact Content
≠
Execution Recipe / Program
≠
Capability Grant
≠
Planner Plan
```

。

当前 StateBus 其实已经拥有这些信息，

只是没有完全分开建模。

---

# 67. 外部对照 4：SLSA Provenance

SLSA Provenance 把 Artifact provenance 大致分成：

```text
subject
    产物 identity

buildDefinition
    怎么构建
    parameters
    resolved dependencies

runDetails
    谁构建
    invocation
    execution details
```

。

StateBus 可以直接借结构思想：

```text
subject
    → ArtifactContentDescriptor

buildDefinition
    → capability
      output contract
      approved plan
      input refs
      recipe/source/program

resolvedDependencies
    → input artifact/evidence digests

builder
    → StateBus Runtime + Provider

invocationId
    → RunID / Step / Attempt

runDetails
    → ExecutionReceipt
```

。

不需要：

```text
做 SLSA 合规
做签名服务
做供应链平台
```

。

只需要学习：

# “产物是什么” 与 “产物怎么来的” 分开。

---

# 68. 不建议当前引入 Sigstore / Public Signature

当前比赛环境：

```text
single local Runtime
trusted local control plane
```

。

主要风险不是：

```text
公网第三方伪造 Artifact 签名
```

。

所以没必要：

```text
Sigstore
Transparency Log
Public PKI
```

。

如果未来：

```text
跨机器
Remote Executor
Untrusted Artifact Store
```

再考虑：

```text
signed verification receipts
```

。

现在 hash chain + local authority 足够。

---

# 69. Target Architecture

推荐 Artifact Plane 最终结构：

```text
Provider
   ↓
Temporary Output
   ↓
ArtifactContentDescriptor
   │
   ├─ type
   ├─ size
   └─ digest
   ↓
ArtifactDerivationReceipt
   │
   ├─ Task / Run / Session
   ├─ Plan
   ├─ CapabilityGrant
   ├─ Provider
   ├─ Inputs
   ├─ Program / Source / Prompt
   └─ Output Contract
   ↓
ValidatorRegistry
   ↓
ArtifactVerificationReceipt
   │
   ├─ Validator identity
   ├─ exact output digest
   ├─ schema
   ├─ provenance
   ├─ completion
   ├─ recomputation
   └─ verification strength
   ↓
LifecyclePolicy
   ↓
VERIFIED Artifact
   ↓
┌─────────────────────────┬────────────────────────┐
│                         │                        │
▼                         ▼                        ▼
ReplayEligibility     MemoryAdmission       AnswerAdoption
```

三个后续决策彼此独立。

---

# 70. Target Contract：`ArtifactContentDescriptor`

```python
@dataclass(frozen=True)
class ArtifactContentDescriptor:
    artifact_id: str
    generation: int

    media_type: str

    digest: str
    size_bytes: int

    schema_version: str
```

。

最重要原则：

```text
content descriptor
不能包含：
task ID
program hash
validator
replay flag
path
```

。

它只回答：

```text
“这些 bytes 是什么”
```

。

---

# 71. Target Contract：`ArtifactDerivationReceipt`

```python
@dataclass(frozen=True)
class ArtifactDerivationReceipt:
    artifact_id: str
    generation: int

    task_contract_hash: str
    run_id: str
    session_id: str
    step_id: str
    attempt_id: str

    approved_plan_hash: str
    capability_grant_hash: str

    logical_capability_id: str
    execution_provider_id: str

    input_artifact_digests: tuple[str, ...]
    input_evidence_digests: tuple[str, ...]

    program_hash: str = ""
    source_hash: str = ""
    prompt_bundle_hash: str = ""
    policy_digest: str = ""

    output_contract_version: str = ""

    receipt_hash: str = ""
```

。

---

# 72. Target Contract：`ArtifactVerificationReceipt`

```python
@dataclass(frozen=True)
class ArtifactVerificationReceipt:
    artifact_id: str
    generation: int

    content_digest: str

    validator_ids: tuple[str, ...]
    validator_bundle_digest: str

    report_hashes: tuple[str, ...]

    schema_passed: bool
    provenance_passed: bool
    completion_passed: bool

    recomputation_evaluated: bool
    recomputation_passed: bool

    verification_strength: str

    verified: bool

    verified_at_ns: int
    receipt_hash: str
```

。

---

# 73. Target Contract：`ReplayEligibilityReceipt`

```python
@dataclass(frozen=True)
class ReplayEligibilityReceipt:
    artifact_id: str
    generation: int
    content_digest: str

    eligible: bool

    reuse_mode: str
    # artifact_restore
    # recipe_recompute
    # not_replayable

    determinism_class: str

    exact_key: str
    compatibility_fingerprint: str

    runtime_signature: str
    provider_signature: str
    validator_signature: str

    reasons: tuple[str, ...]

    receipt_hash: str
```

。

---

# 74. Target Contract：`ArtifactLifecycleEvent`

```python
@dataclass(frozen=True)
class ArtifactLifecycleEvent:
    event_id: str

    artifact_id: str
    generation: int
    content_digest: str

    previous_state: str
    new_state: str

    reason: str

    verification_receipt_hash: str = ""
    replay_eligibility_receipt_hash: str = ""

    created_at_ns: int = 0

    previous_event_hash: str = ""
    event_hash: str = ""
```

。

---

# 75. Target Contract：`ArtifactLocationBinding`

```python
@dataclass(frozen=True)
class ArtifactLocationBinding:
    content_digest: str

    materialization_id: str

    root_kind: str
    root_id: str

    relpath: str

    readonly: bool

    created_at_ns: int
```

。

---

# 76. 为什么 Target 不一定需要“大型 CAS”

可以先只做：

```text
workspace file
+
content digest
+
central descriptor
```

。

CAS 是逻辑模型。

当前比赛第一版完全可以：

```text
sha256 digest
    ↓
workspace materialization
```

。

后续需要跨 run reuse 时再：

```text
runtime_root/cas/sha256/...
```

。

不要现在为了架构漂亮引入远端 Object Store。

---

# 77. 推荐 Truth Ladder

Artifact Truth 最适合分成：

```text
A0 — Exists
文件存在

A1 — Integrity
size + digest 验证

A2 — Scope
task/session/step/grant 绑定

A3 — Structural Validation
schema / output shape / no symlink / path

A4 — Contract Validation
capability completion criteria

A5 — Provenance Validation
input refs / evidence lineage

A6 — Independent Recomputation
Runtime independently recalculates expected output

A7 — Replay Eligibility
未来 reuse contract 独立通过

A8 — Cross-run Attestation
跨 trust boundary 的 signed provenance
```

当前 StateBus 大致：

```text
A0 ✓
A1 强
A2 较强
A3 强
A4 中强
A5 中强
A6 视 validator 而定
A7 被 VERIFIED 自动带出，语义过强
A8 不需要 / 未实现
```

。

---

# 78. 当前几个 Producer 的 Truth Level

## Evidence Projection

大致：

```text
A1 ✓
A2 ✓
A3 ✓
A4 deterministic request contract
A5 row-lineage 部分
A6 source recomputation ✗
```

所以：

```text
RUNTIME_DERIVED
```

更准确。

---

# 79. Transform DSL

通常：

```text
A1 ✓
A2 ✓
A3 ✓
A4 ✓
A5 ✓
A6 ✓
```

因为：

```text
recompute_transform_program()
```

有独立路径。

是当前最适合：

```text
ARTIFACT_RESTORE
```

候选的一类。

---

# 80. CodeAct

如果使用强业务 validator：

```text
A1-A6
```

可以比较强。

如果：

```text
generic_analysis
```

则：

```text
A6 = NOT_EVALUATED
```

所以不要统一 Replay 权限。

---

# 81. ClaimSet

大致：

```text
A1 ✓
A2 ✓
A3 ✓
A4 claim structural validation
A5 部分
A6 semantic entailment ✗
```

。

因此 ClaimSet 的：

```text
VERIFIED
```

应该理解为：

```text
claim structure/provenance checks passed
```

而不是：

```text
claim semantic truth independently proven
```

。

---

# 82. P1 — Replay Loader 应统一走 Artifact Resolver

现在有两套读取安全强度：

```text
Adaptive current artifact reader
    强

History replay path reader
    较弱
```

建议最终只有：

```python
ArtifactResolver.resolve_verified_content(
    descriptor,
    location,
    current_lifecycle,
)
```

统一负责：

```text
location root
path containment
no symlink
size
digest
current lifecycle state
verification receipt
```

。

---

# 83. P1 — Artifact Registry 应成为 Current Truth，Memory 不应复制状态

未来：

```text
MemoryRef.metadata["replay_ready"]
```

这种复制字段应该尽量减少。

Memory 只保存：

```text
artifact_id
generation
content_digest
replay_receipt_id
```

。

使用时：

```text
查询 ReplayEligibilityStore
```

。

否则：

```text
Artifact invalidated
Memory metadata still replay_ready=true
```

就会出现 stale truth。

---

# 84. `replay_ready` 建议逐步从 Artifact Ref 移出

更合理：

```text
ExecutionArtifactRef
    不带 replay_ready

ReplayEligibilityReceipt
    独立表达
```

。

过渡期可以：

```text
replay_ready
```

保留兼容，

但把它变成：

```text
derived/cached field
```

而不是 authority source。

---

# 85. P1 — Adaptive Memory Commit 的 Late Gate 是值得保留的

虽然 Artifact promotion 本身分散，

Adaptive `_commit_verified_memory()` 做了几件很好的事情：

```text
runtime 必须 completed

Artifact 必须 VERIFIED

重新读取真实 artifact bytes
并验证 blob hash

QualityReport 必须 verified

QualityReport.output_artifact_hash
==
Artifact.blob_hash

QualityReport.report_hash
==
Artifact.metadata.quality_report_hash

Execution recipe 必须存在

input lineage 必须存在
```

。

这个 gate 很有价值。

---

# 86. 但它应该改名理解

它现在更像：

# **Memory Admission Gate**

而不是：

```text
Artifact Verification Gate
```

。

Artifact 在到这里之前已经被下游消费过。

所以这条链应该保留，

但职责明确为：

```text
“是否值得进入 Long-Term Memory”
```

。

---

# 87. 和 Round 03 CodeAct Recipe Identity 的连接

Adaptive Memory Commit 虽然要求：

```text
execution recipe exists
```

但当前还没有强制：

```text
recipe.source_hash
==
CodeExecutionRecord.final_source_hash
```

。

Round 03 已经发现：

```text
repair 后最终 verified source B
但 Dispatcher recipe 可能仍保存初始 source A
```

。

因此：

```text
Artifact Truth
```

虽然可能正确，

但：

```text
Recipe Truth
```

仍可能不正确。

这再次证明：

```text
Artifact Verification
≠
Recipe Replay Eligibility
```

必须拆开。

---

# 88. 推荐未来四个独立 Gate

```text
Gate 1
Artifact Verification Gate

Gate 2
Replay Eligibility Gate

Gate 3
Memory Admission Gate

Gate 4
Answer Adoption / Presentation Gate
```

。

绝不能再：

```text
一个 CommitGate
把四件事同时决定
```

。

---

# 89. 推荐实验 / Negative Audit

当前先不实现，但后续应该补这些实验。

---

# 90. Artifact Integrity Negative

```text
verified ref
+
file bytes modified
→ reject
```

已有部分覆盖。

继续补：

```text
size mismatch
symlink
path escape
manifest output mismatch
```

。

---

# 91. Lifecycle Negative

```text
Artifact VERIFIED
    ↓
INVALIDATED
    ↓
旧 Ref holder 尝试消费
```

必须：

```text
reject
```

。

这是当前 central revocation 缺口。

---

# 92. Replay State Mismatch

构造：

```text
RefRegistry:
INVALIDATED

Settlement:
replay_ready=True

Memory:
replay_ready=True
```

Expected：

```text
0 replay candidates
```

。

---

# 93. Settlement Tamper

修改：

```text
settlement.replay_ready
false → true
```

但：

```text
没有 matching ReplayEligibilityReceipt
```

Expected：

```text
reject
```

。

---

# 94. Artifact Manifest Semantic Mismatch

构造一个 Adaptive DSL Artifact：

```text
manifest_hash = program hash
```

尝试走 Legacy ArtifactOutputManifest loader。

目标不是让它成功，

而是：

```text
明确证明当前 ABI 不兼容
```

。

然后修正 contract。

---

# 95. DSL Quality Binding Test

```text
first transformed output hash = A

run_verified final artifact hash = B

quality report binds A
```

即使通过 monkeypatch / nondeterministic test 强制造差异，

必须：

```text
Artifact promotion rejected
```

。

---

# 96. Adoption Orthogonality Test

```text
quality pass
validators pass
answer_adopted=False
```

Expected：

```text
Artifact VERIFIED
Answer NOT_ADOPTED
Memory policy independently decides
```

而不是：

```text
Artifact INVALIDATED
quality_floor_failed
```

。

---

# 97. Empty Validator Set Test

```text
validator_reports=()
input_validator_reports=()
```

必须根据 capability policy：

```text
REJECT
```

除非 capability 明确：

```text
requires_no_validator=True
```

。

不能依赖 `all(())`。

---

# 98. Duplicate Artifact ID Test

```text
Artifact ID X
digest A
ACTIVE

再次 register:
Artifact ID X
digest B
```

Expected：

```text
identity_collision
```

或：

```text
new generation
```

。

不能 silent overwrite。

---

# 99. Crash Atomicity Tests

注入 crash：

```text
after temp output

after digest

after verification receipt

after CAS insert

before registry ACTIVE

after registry ACTIVE
```

必须保证：

```text
没有 ACTIVE Ref
指向 incomplete / unverified output
```

。

---

# 100. Replay Determinism Test

对：

```text
DSL deterministic output
```

允许：

```text
ARTIFACT_RESTORE
```

。

对：

```text
generic LLM output
```

即使输入一样：

```text
不能自动 ARTIFACT_RESTORE
```

除非 contract 固定：

```text
source/model/seed/provider/runtime
```

且 policy 明确允许。

---

# 101. 建议未来测试清单

```text
test_verified_state_requires_verification_receipt

test_artifact_valid_but_not_adopted_remains_verified

test_commit_gate_does_not_report_quality_failure_when_only_adoption_false

test_empty_validator_set_does_not_vacuously_verify

test_invalidated_artifact_cannot_be_consumed_with_stale_ref

test_artifact_lifecycle_rejects_invalid_transition

test_artifact_id_collision_rejected

test_replay_loader_requires_current_verified_state

test_replay_loader_rejects_registry_settlement_state_mismatch

test_history_output_path_escape_rejected

test_history_output_symlink_rejected

test_history_output_size_mismatch_rejected

test_adaptive_artifact_manifest_semantics_are_typed

test_dsl_quality_report_hash_matches_final_artifact_hash

test_codeact_quality_report_hash_matches_final_artifact_hash

test_projection_verification_strength_is_runtime_derived

test_generic_validator_does_not_claim_independent_recomputation

test_replay_eligibility_separate_from_artifact_verification

test_artifact_restore_requires_deterministic_class

test_memory_commit_failure_does_not_invalidate_verified_artifact

test_artifact_invalidation_revokes_memory_replay

test_artifact_lifecycle_ledger_is_append_only

test_atomic_artifact_promotion_crash_before_registry_commit
```

。

---

# 102. 推荐迁移顺序

本轮仍然只审计。

如果未来开始实现，建议严格分 Slice。

---

# ART-R0 — Semantics / Truth Naming

只统一：

```text
VERIFIED
ReplayReady
AnswerAdopted
MemoryCommitted
```

四者语义。

不改大行为。

---

# ART-R1 — Verification Strength / Receipt

增加：

```text
ArtifactVerificationReceipt
VerificationStrength
```

并把：

```text
CapabilityQualityReport
```

正式绑定到 Artifact digest。

---

# ART-R2 — Replay Eligibility Separation

停止：

```text
mark_verified()
自动 replay_ready=True
```

。

新增独立：

```text
ReplayEligibilityPolicy
```

。

---

# ART-R3 — Content / Derivation Split

拆：

```text
ArtifactContentDescriptor
ArtifactDerivationReceipt
```

修正：

```text
manifest_hash overload
```

。

---

# ART-R4 — Central Lifecycle / Revocation

统一：

```text
current lifecycle state
```

和：

```text
append-only lifecycle event
```

。

Downstream consume 必须查 current authority。

---

# ART-R5 — Unified Artifact Resolver

Current / History / Memory restore

统一：

```text
path containment
symlink
size
digest
current state
verification receipt
```

。

---

# ART-R6 — Atomic Persistence / Optional CAS

做到：

```text
temp
fsync
atomic rename
registry commit last
```

。

CAS 只在跨 run reuse 真正需要时加入。

---

# 103. 不建议现在做

```text
❌ 上 OCI Registry

❌ 实现 SLSA Level

❌ 引入 Sigstore 公钥签名

❌ 搭远程 CAS Cluster

❌ 用区块链记录 Artifact

❌ 给每个 verification strength 新增一个 RefStatus

❌ 把所有 Artifact 都强制做 independent recomputation

❌ 用 Benchmark Gold 作为 Runtime Artifact Validator
```

。

---

# 104. 对比赛最重要的 Artifact Story

修正后最强的叙事不是：

```text
“我们给文件算了 SHA256”
```

而是：

> **StateBus 将执行结果作为一等 Artifact 对象管理：产物内容身份与生成过程分离，Runtime 将 CapabilityGrant、输入 Ref、程序/代码、输出合同和 validator receipt 绑定到产物 digest；只有通过当前任务验证的 Artifact 才能进入下游。Replay 资格与 Artifact 正确性独立判断，历史内容在恢复时重新验证 size/digest 和当前生命周期状态，Memory 只引用已经授权的 Artifact/Recipe，而不会反向决定 Artifact 是否真实。**

这比：

```text
hash + cache
```

强很多。

---

# 105. 当前可以准确写进材料的 Claim

可以说：

```text
Execution Artifact carries blob hash and byte size.

Adaptive downstream rehydrates artifact bytes from disk,
checks root containment, rejects symlink,
checks exact size and digest,
and compares them with the cached typed rows.

CodeAct binds its final output digest to CapabilityQualityReport.

Adaptive Memory admission re-reads the terminal executor artifact
and checks the quality report against the exact artifact digest.

History replay re-reads persisted output bytes
and rejects digest mismatch.
```

。

---

# 106. 当前不能过度 Claim

不要说：

```text
All VERIFIED artifacts have identical verification strength.

Every VERIFIED artifact is safe for replay.

Artifact verification is controlled by one central CommitGate.

All Adaptive artifacts have a canonical ArtifactOutputManifest.

manifest_hash always points to an Artifact manifest.

Artifact invalidation is globally propagated to all stale refs.

History replay verifies the same path/security conditions
as current-run artifact consumption.

Answer adoption is independent from artifact validity.
```

这些当前都不成立。

---

# 107. Batch 03 风险表

| Priority | 问题 | 类型 |
|---|---|---|
| **P0** | Artifact Truth Promotion 有两套 authority path | Architecture |
| **P0** | `mark_verified()` 自动 `replay_ready=True` | Replay truth |
| **P0** | `manifest_hash` 语义跨 Producer 严重漂移 | Contract ABI |
| **P0** | `answer_adopted=False` 会把有效 artifact invalidated 且错误记录 `quality_floor_failed` | Audit truth |
| **P0/P1** | Verification strength 被压扁成一个 VERIFIED | Truth semantics |
| **P0/P1** | Artifact invalidation 缺 central revocation，stale verified Ref 可继续存在 | Lifecycle |
| **P1** | Empty validator tuples vacuous pass | Fail-open contract |
| **P1** | Lifecycle Manager 是 producer-local ephemeral object | Authority |
| **P1** | Lifecycle transition 没有合法状态机约束 | Lifecycle |
| **P1** | Settlement / invalidation 非 append-only | Audit |
| **P1** | Registry status / settlement replay_ready 无强一致性检查 | Replay |
| **P1** | Invalidation 没统一传播到 Memory/Replay | Replay |
| **P1** | History replay path confinement/symlink/size 校验弱于 current artifact reader | Security/Integrity |
| **P1** | Artifact writes 缺统一 crash-atomic promotion | Durability |
| **P1** | RuntimeCommitGate promotion + Memory + settlement 非事务 | Consistency |
| **P1** | Duplicate artifact ID silent overwrite | Identity |
| **P1** | DSL QualityReport 未在 `run_verified()` 显式绑定最终 materialized output hash | Verification |
| **P1** | Adaptive artifacts 普遍没有统一 persisted manifest/settlement bundle | Cross-run ABI |
| **P1** | `root_id` 同时承担 logical/physical root 语义 | Contract |
| **P2** | Exact Replay 缺显式 determinism class | Replay policy |
| **P2** | Settlement 本身不是 tamper-evident receipt | Trust boundary |

---

# 108. Batch 03 与前两批的关系

Batch 01：

```text
Task / Plan Authority
回答：
谁有权做什么？
```

Batch 02：

```text
Evidence / Provenance
回答：
它依据什么事实？
```

Batch 03：

```text
Artifact Truth
回答：
执行结果什么时候可以被系统当成真？
```

三条链联合：

```text
Task Contract
    ↓
Approved Plan
    ↓
Evidence Authority
    ↓
CapabilityGrant
    ↓
Provider Execution
    ↓
Artifact Verification
    ↓
Verified Artifact
```

这其实已经形成 StateBus 最核心的一条：

# **Runtime Truth Pipeline**

。

---

# 109. Batch 03 与 Memory 的关系

Memory 不应该：

```text
决定 Artifact VERIFIED
```

。

正确：

```text
Artifact VERIFIED
    ↓
Memory Admission
```

。

Memory 保存的是：

```text
历史经验
```

而不是：

```text
真值 authority
```

。

---

# 110. Batch 03 与 CodeAct 的关系

CodeAct 只负责：

```text
生成 + sandbox + output candidate
```

。

Artifact Plane 负责：

```text
这个 output 是否成为 verified runtime object
```

。

未来 `VerifiedExecutionRecipe` 又由：

```text
ReplayEligibilityPolicy
```

决定是否可重用。

---

# 111. Batch 03 与 Inference Reuse 的关系

Prefix/KV 只是在复用：

```text
physical Transformer compute
```

。

它绝不能绕过：

```text
Artifact Verification
```

。

即使：

```text
KV hit
APC hit
```

最终：

```text
Artifact output
```

仍然走同样的 truth promotion。

---

# 112. 推荐下一批

完成 Artifact Truth 审计以后，下一批有两条都合理：

## 方向 A — Protocol / Capability / Handshake

把：

```text
CapabilityDescriptor
Registry
Handshake
Schema Version
CapabilityGrant
Provider Fallback
```

打穿。

这是控制面下一层。

## 方向 B — Inference Reuse / APC / KV

如果希望继续贴近非文本创新主线：

```text
Prefix
APC
EngineLocalKV
Explicit KV
```

。

从全系统审计顺序看，我更建议先：

# **Protocol / Capability / Handshake**

因为 Artifact / Memory / State / CodeAct 全部依赖：

```text
Capability Contract
```

。

把它审完后再审 KV，整个 authority chain 会更完整。

---

# 113. External Design References

本轮只借设计原则，不建议直接引入这些系统。

## OCI Image Spec — Content Descriptor

参考：

```text
https://github.com/opencontainers/image-spec/blob/main/descriptor.md
https://specs.opencontainers.org/image-spec/descriptor/
```

借鉴：

```text
media type
digest
size
content verification before use
```

。

---

## Bazel Remote Cache

参考：

```text
https://bazel.build/remote/caching
```

借鉴：

```text
Action Cache
    action identity → result metadata

CAS
    content digest → bytes
```

。

---

## Nix Content Addressing / Derivation

参考：

```text
https://releases.nixos.org/nix/
```

借鉴：

```text
content identity
≠
derivation identity
```

。

---

## SLSA Provenance v1.2

参考：

```text
https://slsa.dev/spec/v1.2/
https://slsa.dev/spec/v1.2/provenance
```

借鉴：

```text
subject
build definition
resolved dependencies
builder
run details
```

。

不要为了比赛做：

```text
SLSA compliance
```

。

---

# 114. Batch 03 冻结结论

> **StateBus 当前 Artifact 子系统已经有可靠的内容 hash 验证、较强的当前运行读取校验、CapabilityQualityReport 和历史 Replay 输出 hash 校验；真正的问题不是“Artifact 不可信”，而是 Artifact 的不同真实性维度被压缩进 `VERIFIED/replay_ready/manifest_hash` 几个过载字段，同时 Adaptive 与 Legacy 路径各自拥有一套 promotion/settlement 语义。下一阶段应把 Content、Derivation、Verification、Lifecycle、Replay Eligibility、Memory Admission、Answer Adoption 拆成正交合同，使 Artifact 成为真正统一的 Runtime Truth Object。**
