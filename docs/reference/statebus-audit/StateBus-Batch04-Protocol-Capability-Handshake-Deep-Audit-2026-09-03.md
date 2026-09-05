# StateBus Batch-04 — Protocol / Capability / Handshake 深度源码审计与改进设计

> Repository: `https://github.com/qcrs/os`  
> Branch: `master`  
> Audited baseline: `8bfc6464ec236c0e121911095fc283129b0e7696`  
> Date: 2026-09-03  
> Scope: **Protocol / Capability / Handshake only**  
> Mode: **Source audit + external design research; no code changes**
>
> 本轮明确不进入：
>
> ```text
> Logical Capability / Provider Binding
> Prefix / APC / Explicit KV
> Scheduler policy
> Deployment hardening
> External benchmark
> Final security/privacy pass
> ```
>
> 这些分别属于后续 Batch。

---

# 0. 本轮先回答什么

Batch-04 不是简单检查：

```text
“有没有 Protobuf？”
“有没有 CapabilityRegistry？”
“有没有 ACK / Heartbeat？”
```

真正需要回答的是：

```text
1. Planner 看到的 Capability 到底是什么？

2. Runtime 真正授权执行的 Capability 到底是什么？

3. Worker 收到的 Protocol Request
   是否能证明：
   “我执行的就是 Runtime 授权的那个动作”？

4. Control Protocol 的版本、schema、feature
   是真正协商 / 校验，
   还是只是写了一个 version 字符串？

5. ACK / RUN_START / HEARTBEAT
   是否真来自 Worker，
   还是 Runtime 本地把状态机往前推？

6. CapabilityGrant 是否真的 one-attempt / one-consumption？

7. Worker 返回 Success 时，
   Runtime 是否证明：
   Result 属于这个 Task / Step / Attempt / Grant /
   Output Contract？

8. Protocol evolution 时，
   `.proto`、Python model、Runtime policy
   能否不发生 silent drift？
```

---

# 1. Executive Summary

这一轮的核心结论可以压缩成一句话：

> **StateBus Controller 内部已经形成比较强的 Capability Authority，但这个 Authority 还没有完整延伸到 Worker Protocol Boundary。**

Controller 内：

```text
DomainPack
    ↓
CapabilityRegistry
    ↓
Planner Public Surface
    ↓
PlanPolicy
    ↓
ApprovedPlan
    ↓
CapabilityGrant
```

这一段已经相当清晰。

特别是：

```text
ApprovedPlan
绑定 capability_registry_digest

CapabilityGrant
绑定：
task
session
step
attempt
capability_id
capability_version
input refs
output contract
workspace
runtime budget
expiry
approved plan
```

这是好的。

但是进入 Worker 后，当前链路退化成：

```text
CapabilityGrant
    ↓
grant_hash
    ↓
ExecRequest.capability_grant_hash
    ↓
Worker:
“这个字符串非空”
```

Worker 实际执行什么，则主要由：

```text
message.operation
```

决定。

因此：

# `CapabilityGrant hash present` ≠ `Worker independently enforces CapabilityGrant`

。

---

# 2. 更重要的第二个结论

当前系统实际上有三种不同的 Capability Surface：

```text
A. Planner Capability Surface

B. Runtime Authorization Surface

C. Worker Protocol Surface
```

它们现在部分混在一起讨论。

本轮建议正式拆开。

---

# 3. Planner Capability Surface

当前来源：

```text
DomainPack
+
CapabilityRegistry.public_view()
```

它回答：

> Planner 可以考虑哪些语义能力？

例如：

```text
retrieve_semantic_evidence_v1

execute_analysis_dsl_v2

execute_bounded_python_v2

compose_cited_report_v1
```

Planner 需要知道：

```text
能力叫什么
谁负责
大致做什么
输入类型
输出类型
completion criteria
fallback hint
```

它不应该知道：

```text
worker PID
socket path
root_id
network endpoint
provider implementation
GPU
process topology
```

当前测试甚至明确要求：

```text
public capability surface
不出现 root_id / network
```

这个方向是正确的。

---

# 4. Runtime Authorization Surface

当前来源：

```text
CapabilityDescriptor
+
AdaptiveTaskEnvelope
+
ApprovedPlan
+
CapabilityGrant
```

它回答：

> Runtime 当前这一次到底允许做什么？

这个 Surface 比 Planner View 强得多。

---

# 5. Worker Protocol Surface

当前来源：

```text
ControlHeader
ExecRequest
RefHandle
ReusePolicy
operation
SuccessResult
ErrorResult
```

它回答：

> Worker 实际收到什么？

这才是 Batch-04 最关键的边界。

---

# 6. 三层应该是什么关系

正确关系不是：

```text
CapabilityDescriptor
直接序列化给 Worker
```

也不是：

```text
Planner Public View
就是 Worker Handshake
```

而应该：

```text
Planner Capability Surface
        ↓ semantic choice

Approved Logical Capability
        ↓

Runtime Authorization Surface
        ↓ exact authority

CapabilityGrant
        ↓

Protocol Invocation Binding
        ↓ exact worker operation authority

Worker Protocol Surface
```

。

---

# 7. 当前源码地图

Batch-04 主要审计：

```text
statebus/contracts/adaptive.py
statebus/contracts/constants.py

statebus/runtime/capability_registry.py
statebus/runtime/domain_packs.py
statebus/runtime/plan_policy.py
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/supervisor.py

statebus/control/statebus_control.proto
statebus/control/schema.py
statebus/control/messages.py
statebus/control/transport.py
statebus/control/subprocess_worker.py

tests/test_adaptive_capability_surface.py
tests/test_control_plane.py
tests/test_subprocess_executor.py
```

。

---

# 8. 当前 Control Protocol

当前：

```proto
package statebus.control.v1;
```

。

ControlEnvelope：

```text
REQ_EXEC
ACK_RECV
RUN_START
HEARTBEAT
RES_SUCC
RES_ERR
CMD_CANCEL
TRAP_FATAL
CMD_GC
```

。

从结构上看，它已经不是：

```text
随便发 JSON
```

而是：

```text
typed control protocol
```

。

这一点应该保留。

---

# 9. 当前 Control Header

```text
trace_id
task_id
step_id
attempt_id
target_role
timeout_ms
schema_version
event_type
```

。

已经具备：

```text
trace
task
step
attempt
role
timeout
version
event
```

这些非常重要的控制面字段。

---

# 10. 当前 ExecRequest

当前同时承担：

```text
Reuse Policy

State Refs
Artifact Refs
Memory Refs

Runtime Reuse Contract

Output Contract

Workspace

Input Manifest

Operation

State Root

Hydrate Manifest

Semantic Top-K

Evidence Budget

Encoder Signature

Capability Grant Hash
```

。

这已经逐渐成为一个：

# **Mega ExecRequest**

。

---

# 11. 当前 Result

`SuccessResult` 同时承担：

```text
generic refs

semantic selection:
    candidate ids
    scores
    row indices
    evidence bytes
    encoder signature

Decision / Logit:
    gate action
    gate reason
    aliases
    probabilities
    entropy
    other mass
    decision id
```

。

这同样是：

# **Mega SuccessResult**

。

---

# 12. P0 — 当前没有真正的 Protocol Version Enforcement

虽然 Header 有：

```text
schema_version
```

默认：

```text
statebus.control.v1
```

但是 decode 时：

```python
schema_version =
    pb.schema_version
    or CONTROL_PLANE_SCHEMA_VERSION
```

也就是说：

```text
wire message 根本没提供 schema_version
```

会被解释成：

```text
当前版本
```

。

---

# 13. 这为什么危险

假设：

```text
旧 Worker
没有 schema_version
```

Controller：

```text
decode
→ 自动补成 v1
```

。

结果 Audit 会声称：

```text
protocol = statebus.control.v1
```

但实际：

```text
sender 没有声明这个事实
```

。

这是：

# **Version Identity Fabrication**

。

---

# 14. Text Control Path 也一样

Text decoder：

```text
missing schema_version
→ CONTROL_PLANE_SCHEMA_VERSION
```

。

所以这是统一的 contract 问题，

不是 protobuf 特例。

---

# 15. Target

Protocol Version 应：

```text
Sender declared
```

和：

```text
Receiver inferred
```

严格分开。

第一版甚至可以非常保守：

```text
schema_version missing
→ reject
```

。

---

# 16. 不需要复杂 SemVer

StateBus 当前可以保持：

```text
statebus.control.v1
```

。

规则：

```text
v1:
只允许 protobuf wire-safe additive evolution

真正 semantic breaking:
新建 statebus.control.v2
```

。

不需要：

```text
1.3.17-beta
```

这种复杂版本。

---

# 17. P0 — `.proto` 与 `schema.py` 是两份独立 Schema Source

当前：

```text
statebus/control/statebus_control.proto
```

定义一次。

同时：

```text
statebus/control/schema.py
```

又手工：

```python
descriptor_pb2.FileDescriptorProto
```

重新定义一遍：

```text
message
field name
field number
field type
oneof
enum
```

。

---

# 18. 当前审计版本两者看起来仍同步

本轮没有发现：

```text
当前 field number 已经错位
```

。

但是架构风险非常明确：

```text
改 .proto
忘了改 schema.py

或者

改 schema.py
忘了改 .proto
```

。

两者都能发生。

---

# 19. 为什么这是 P0/P1 级问题

因为 Protobuf 的真正 wire identity 是：

```text
field number
+
wire type
```

。

如果两个 schema source drift：

```text
README / .proto
说 A

Runtime
实际 encode B
```

。

这会让：

```text
Protocol 文档
Protocol Runtime
```

分裂。

---

# 20. 外部 Protobuf 的原则

Protocol Buffers 官方明确要求：

```text
不要复用 field number

删除字段以后 reserve number

不要随意改变 field type

新增字段通常 wire-safe

client/server 不可能永远同步升级
```

。

因此：

> Protocol schema 必须只有一个 canonical source。

参考：

```text
https://protobuf.dev/best-practices/dos-donts/
https://protobuf.dev/programming-guides/proto3/
```

。

---

# 21. 推荐方案

最合理：

```text
statebus_control.proto
        ↓
protoc
        ↓
generated Python descriptor / pb2
```

。

Runtime 不再手写：

```text
build_control_file_descriptor()
```

。

---

# 22. 如果暂时不想 commit generated pb2

至少：

```text
.proto
    ↓ build step
FileDescriptorSet
    ↓
schema_digest
    ↓
runtime dynamic descriptor
```

。

然后 CI 做：

```text
canonical .proto descriptor digest
==
runtime descriptor digest
```

。

---

# 23. P1 — `.proto` 还没有 Schema Evolution Guard

当前 `.proto` 没有明显看到：

```proto
reserved ...
```

。

现在还没有删除字段，

所以不是现存 bug。

但进入 v1 evolution 后应该冻结：

```text
removed field number never reuse
removed enum number never reuse
```

。

---

# 24. P0 — 当前 ACK / RUN_START 有两套 Truth

这是 Batch-04 最重要的发现之一。

---

# 25. 第一套：Adaptive Runtime Supervisor

`AdaptiveRuntimeEngine._dispatch_lifecycle()` 当前：

```text
supervisor.register()

supervisor.dispatch()

telemetry:
STEP_DISPATCHED

supervisor.ack()

telemetry:
STEP_ACKED

supervisor.run_start()

telemetry:
STEP_RUNNING
```

。

然后才：

```text
dispatcher.dispatch(...)
```

。

---

# 26. 也就是说

当前 Adaptive Runtime：

```text
还没真正把工作交给具体 Worker

就已经记录：

ACKED
RUNNING
```

。

这是：

# **Synthetic Lifecycle Transition**

。

---

# 27. 第二套：真实 IPC Worker

Subprocess worker 实际也会发：

```text
AckReceived
RunStart
Heartbeat
SuccessResult
```

。

这是：

# **Real Process Protocol Lifecycle**

。

---

# 28. 两套并没有接起来

Adaptive Runtime 的：

```text
RuntimeSupervisor
```

没有在 semantic-state subprocess 路径上：

```text
消费真实 AckReceived

消费真实 RunStart

消费真实 Heartbeat
```

。

它是自己先：

```text
ack()
run_start()
```

。

然后内部某个 capability handler：

```text
又启动 subprocess
```

。

---

# 29. 结果

系统现在存在：

```text
Logical Runtime Lifecycle

和

Physical Worker Lifecycle
```

两套 timeline。

但 telemetry 容易让人误以为：

```text
STEP_ACKED
=
Worker 已经 ACK
```

。

当前并不严格成立。

---

# 30. 这会影响什么

例如：

```text
ACK latency

Worker startup latency

Dispatch queue latency

Lease timeout

Heartbeat health

Crash attribution
```

都会失真。

---

# 31. `RuntimeSupervisor` 本身反而设计得不错

Supervisor 有合法状态机：

```text
PENDING
  ↓
DISPATCHED
  ↓
ACKED
  ↓
RUNNING
  ↓
COMPLETED / FAILED / TRAPPED / CANCELLED
  ↓
GC_PENDING
  ↓
GC_DONE
```

。

还实现：

```text
trap_if_ack_timed_out()

trap_if_lease_expired()
```

。

问题不是 Supervisor。

问题是：

> **Adaptive Runtime 没有让真实 Protocol Events 驱动 Supervisor。**

---

# 32. Target

未来应该：

```text
Runtime
    ↓ send invocation

Worker:
AckReceived
    ↓
RuntimeSupervisor.ack()

Worker:
RunStart
    ↓
RuntimeSupervisor.run_start()

Worker:
Heartbeat
    ↓
RuntimeSupervisor.heartbeat()

Worker:
Success/Error/Trap
    ↓
RuntimeSupervisor complete/fail/trap
```

。

---

# 33. 但是不是所有 Capability 都要 subprocess

不是。

当前很多：

```text
DSL
Runtime Builtin
```

是在当前 Runtime process 内。

对于 in-process provider：

```text
ACK
```

没有真实 IPC 意义。

因此后续 Provider Binding 才应该决定：

```text
execution_provider_kind
```

。

Batch-04 这里只冻结：

```text
Physical ACK
只能用于 physical worker/provider path。

In-process execution
应该用 LOCAL_EXEC_START
或者直接 Running，
而不是伪装成 remote/process ACK。
```

。

---

# 34. P0 — `capability_grant_hash` 当前不是 Worker Authority

`CapabilityGrant` 本身非常完整：

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

其：

```text
grant_hash
```

绑定全部字段。

这是好的。

---

# 35. 但 Worker 没有看到这些字段

当前 semantic state IPC：

```text
ExecRequest.capability_grant_hash
=
grant.grant_hash
```

。

Worker 只检查：

```text
capability_grant_hash non-empty
```

。

Worker 没有：

```text
CapabilityGrant object

capability_id

capability_version

approved_plan_hash

grant expiry

authorized input_ref_ids
```

。

---

# 36. 因此 Worker 无法证明

```text
operation = semantic_select_v1
```

确实属于：

```text
这个 grant
```

。

它只知道：

```text
有人给了我一个 grant hash 字符串。
```

。

---

# 37. Hash 不是 Authorization Token

更严格地说：

```text
SHA256(CapabilityGrant)
```

可以作为：

```text
identity / integrity binding
```

。

它不是：

```text
authentication
```

。

更不是：

```text
authorization proof
```

。

如果 Worker 看不到 canonical grant payload，

它甚至不能自己重算 hash。

---

# 38. 这里不要直接把整个 CapabilityGrant 发给 Worker

原因：

Worker 实际执行的可能不是整个 logical capability。

例如当前：

```text
Retrieval Capability
    ↓
内部启动 subprocess
    ↓
semantic_select_v1
```

。

`semantic_select_v1` 更像：

```text
Capability execution 内部的 physical sub-operation
```

。

---

# 39. 所以需要一个新的桥

建议：

# `ProtocolInvocationBinding`

。

它由 Runtime 从 CapabilityGrant 派生。

---

# 40. Target：ProtocolInvocationBinding

概念上：

```python
ProtocolInvocationBinding(
    invocation_id,

    parent_grant_hash,

    task_id,
    session_id,
    step_id,
    attempt_id,

    target_role,

    operation_id,
    operation_version,

    input_ref_bindings,

    output_contract_version,

    protocol_version,
    schema_digest,

    expires_at_ns,

    binding_hash,
)
```

。

---

# 41. Worker 验证的是这个

```text
ExecRequest
    ↓
ProtocolInvocationBinding
    ↓
operation
refs
contract
expiry
protocol
```

一致。

而不是要求 Worker 理解整个：

```text
Planner
ApprovedPlan
DomainPack
```

。

---

# 42. 这符合最小权限

Worker 不需要知道：

```text
整个 Plan
所有 Capability
所有 Memory policy
所有 Domain Pack
```

。

只需要知道：

> “这次 invocation 允许我干什么。”

---

# 43. P0/P1 — CapabilityGrant 并没有全局 One-shot Consumption

当前 CodeAct：

```text
LlmCodeActRunner
```

有：

```text
_consumed_grant_hashes
```

会拒绝：

```text
capability_grant_already_consumed
```

。

这是好的。

---

# 44. 但 Generic CapabilityGrant 没有统一 Grant Ledger

Retrieval：

```text
没有统一 consumed-grant gate
```

DSL：

```text
没有统一 consumed-grant gate
```

Builtin：

```text
没有统一 consumed-grant gate
```

。

正常 `AdaptiveRuntimeEngine` 确实：

```text
一个 grant
调用一次 dispatcher
```

。

所以主路径暂时没出现重复消费。

但：

```text
CapabilityGrant contract
```

本身不是 one-shot enforced object。

---

# 45. 推荐 Grant Lifecycle

```text
ISSUED
    ↓
BOUND
    ↓
CONSUMED

或者：

ISSUED
    ↓
EXPIRED

ISSUED / BOUND
    ↓
REVOKED
```

。

---

# 46. 推荐 `GrantLedger`

```python
GrantLedgerEntry(
    grant_hash,

    state,

    issued_at_ns,
    bound_at_ns,
    consumed_at_ns,

    invocation_binding_hash,

    result_binding_hash,
)
```

。

---

# 47. 不需要数据库

当前直接：

```text
Runtime-owned dict
+
optional JSONL audit
```

就够。

---

# 48. P0 — SuccessResult 不绑定 Grant

当前 Result 有：

```text
header
state refs
artifact refs
output contract
...
```

但没有：

```text
capability_grant_hash
```

或：

```text
invocation_binding_hash
```

。

---

# 49. 因此 IPC Result 无法直接证明

```text
这个 Result
是对哪个 Grant / Invocation 的响应
```

。

当前只能依赖：

```text
connection context
+
copied header
```

。

---

# 50. Target

Result 至少回显：

```text
invocation_binding_hash
```

。

例如：

```python
ExecutionResultBinding(
    invocation_id,
    invocation_binding_hash,

    task_id,
    step_id,
    attempt_id,

    output_contract_version,

    result_kind,

    output_ref_ids,

    result_hash,
)
```

。

---

# 51. P1 — Response Header 当前没有在 Transport 层校验

Subprocess transport 收到：

```text
AckReceived
RunStart
Heartbeat
SuccessResult
```

以后主要：

```text
append
```

。

没有统一：

```text
response.trace_id == request.trace_id

response.task_id == request.task_id

response.step_id == request.step_id

response.attempt_id == request.attempt_id

response.target_role == request.target_role

response.schema_version == negotiated version
```

。

---

# 52. 当前为什么还能正常

因为：

```text
官方 worker
```

直接：

```python
replace(request.header, event_type=...)
```

。

所以当前 trusted worker 会复制正确 Header。

但是 protocol contract 本身没有 enforcement。

---

# 53. P1 — Semantic IPC Path 也没检查 Output Contract

Adaptive Dispatcher：

```text
request.output_contract_version
=
statebus.evidence_selection.v1
```

Worker：

```text
response.output_contract_version
```

。

Controller 后面会检查：

```text
state id
consumer pid
candidate ids
```

但没有看到统一：

```text
response.output_contract_version
==
request.output_contract_version
```

gate。

---

# 54. Target：Response Binder

所有 subprocess result 进入业务逻辑之前：

```text
ControlResponseBinder.validate(
    request,
    response,
    negotiation,
    invocation_binding,
)
```

。

先做：

```text
protocol
header
grant
attempt
contract
message kind
```

再交给：

```text
semantic selector
decision gate
...
```

。

---

# 55. P1 — ControlEnvelope body 与 Header.event_type 是重复 Truth

当前：

```text
ControlEnvelope.oneof body
```

已经能知道：

```text
req_exec
ack_recv
run_start
...
```

。

同时 Header 又有：

```text
event_type
```

。

所以存在：

```text
body = SuccessResult

header.event_type = REQ_EXEC
```

这种理论组合。

---

# 56. Loopback Harness 会检查 Request Event

Harness：

```text
header.event_type must REQ_EXEC
```

。

但真实 subprocess worker：

```text
只检查 isinstance(message, ExecRequest)
```

没有检查：

```text
header.event_type
```

。

这是：

# **Harness / Real Worker Validation Drift**

。

---

# 57. Target

两个选择。

## 最小修改

保留 event_type，

但统一：

```text
body type ↔ event_type
```

映射 validator。

---

# 58. 更干净的 v2

Header 不再携带：

```text
event_type
```

。

由：

```text
oneof body
```

作为唯一 truth。

Telemetry 转换时再 derive。

第一阶段不用急着 breaking。

---

# 59. P1 — `runtime_reuse_contract` 已经变成 Untyped Control Flag Channel

当前它名字叫：

```text
runtime_reuse_contract
```

。

但代码里出现：

```text
no_semantic_state

drop_ack

lease_timeout

force_trap
```

等字符串行为。

---

# 60. 有些还是 Harness Fault Injection

例如：

```text
drop_ack

lease_timeout

force_trap
```

本质上是：

```text
test harness fault injection
```

。

但通过：

```text
runtime_reuse_contract
```

这个 production-ish 字段驱动。

---

# 61. Worker 也会解释其中某些字符串

真实 Worker：

```text
"no_semantic_state"
```

决定：

```text
state_refs 是否 required
```

。

所以它已经不仅是：

```text
audit description
```

而是：

```text
protocol behavior switch
```

。

---

# 62. Target

拆成：

```text
ReusePolicy
```

当前已经有 typed struct，

继续扩 typed policy。

以及：

```text
InvocationFeatureSet
```

。

Fault Injection：

```text
只存在 tests/harness
```

。

不要进入 production Control Contract。

---

# 63. P0/P1 — `operation` 是自由字符串

当前：

```text
semantic_select_v1

logit_gate_v1
```

。

Worker：

```python
if message.operation == ...
```

。

---

# 64. 问题

ExecRequest 同时存在：

```text
semantic fields
logit fields
generic refs
```

。

Operation string 决定：

```text
哪些字段有意义
```

。

这属于：

# **String-discriminated union**

。

实际上 Protobuf 已经有：

```text
oneof
```

可以表达得更强。

---

# 65. 推荐 v1.x 过渡

先保留：

```text
operation
```

但增加：

```text
ProtocolOperationRegistry
```

。

例如：

```text
semantic_select_v1
    requires:
        one semantic state ref
        state_root
        hydrate_manifest
        top_k
        encoder signature
        grant binding

decision_gate_v1
    requires:
        one decision/logit ref
        state_root
        grant binding
```

。

---

# 66. 推荐 v2

```proto
message ExecRequest {
    ControlHeader header = 1;
    InvocationBinding binding = 2;

    oneof operation {
        SemanticSelectRequest semantic_select = 10;
        DecisionGateRequest decision_gate = 11;
    }
}
```

。

---

# 67. SuccessResult 同样拆

```proto
message SuccessResult {
    ControlHeader header = 1;
    ResultBinding binding = 2;

    oneof result {
        SemanticSelectResult semantic_select = 10;
        DecisionGateResult decision_gate = 11;
    }
}
```

。

---

# 68. 这样做的直接收益

不再出现：

```text
Semantic Select Result
同时带一堆默认 Decision 字段
```

也不会：

```text
Decision Gate
携带 semantic row indices
```

。

---

# 69. P1 — `RefHandle` 太弱

当前：

```text
ref_id
ref_kind
```

。

其中：

```text
ref_kind
```

是自由字符串。

---

# 70. Worker Protocol 真正需要什么

不一定要复制完整 RefRegistry。

但至少可以有：

```text
ref_id
ref_kind
content/manifest binding
generation
```

中的必要子集。

---

# 71. 推荐

```python
ProtocolRefBinding(
    ref_id,
    ref_kind,

    identity_hash,

    generation=0,
)
```

。

。

其中：

```text
identity_hash
```

不是一定等于 payload blob hash。

可能是：

```text
Ref canonical binding hash
```

。

这样 Protocol 才能证明：

```text
“我读的是被授权的这个 ref identity”
```

。

---

# 72. P0/P1 — Adaptive Runtime 对 Success 的 Output Contract 太弱

高层 `AdaptiveStepResult`：

```text
success
output_refs
output_ref_kinds
```

。

Runtime 成功判定：

```text
success=True

len(output_refs) == len(output_ref_kinds)

all(returned kind
    in descriptor.output_ref_kinds)
```

。

---

# 73. 空输出问题

如果：

```text
success=True

output_refs=()

output_ref_kinds=()
```

则：

```text
len == len
```

成立。

同时：

```text
all(())
==
True
```

。

因此即使 Descriptor 明确：

```text
output_ref_kinds = ("execution_artifact",)
```

Runtime Engine 层也可以：

```text
把一个零输出 Step 标 COMPLETED
```

。

Production Dispatcher 通常不会这么返回，

但 Contract Gate 本身是 fail-open。

---

# 74. Target：Output Cardinality Contract

Capability Descriptor 不应该只有：

```text
可接受 output kind union
```

。

还要：

```text
required_output_ref_kinds

min_output_count

max_output_count
```

或者更结构化：

```python
OutputRefContract(
    ref_kind,
    min_count,
    max_count,
)
```

。

---

# 75. 这和 Input 已经做了一半

当前已经有：

```text
input_ref_kinds
required_input_ref_kinds
```

。

Output 应该对称。

---

# 76. P1 — Result Report Hash 目前只是 Audit String

`AdaptiveStepResult` 可以携带：

```text
validator_report_hashes
quality_report_hashes
projection_report_hashes
```

。

Runtime：

```text
attach to session audit
```

。

但 RuntimeEngine 本身不会统一证明：

```text
这些 report hash
确实存在于 authoritative report registry
```

。

Dispatcher 当前会持有 context store，

所以产品主线大多成立。

但 Contract 层仍然薄。

---

# 77. Target

未来：

```text
StepResult
```

最好不是：

```text
“我说我有这个 report hash”
```

。

而是：

```text
ResultBinder
从 Runtime-owned ReportRegistry
resolve + bind
```

。

---

# 78. P1 — Capability Identity 有双重 Version

目前：

```text
capability_id =
extract_metric_series_v1

同时：

descriptor.version =
v1
```

。

所以 Version 同时存在于：

```text
ID 字符串

和

version 字段
```

。

---

# 79. 风险

未来可以出现：

```text
capability_id = extract_metric_series_v1

version = v2
```

。

Registry 当前不会拒绝。

---

# 80. Target

两个选择：

## 方案 A

```text
capability_id
永远就是：
extract_metric_series_v1
```

然后删除独立：

```text
version
```

。

---

# 81. 方案 B — 更推荐为下一轮 Binding 做准备

```python
LogicalCapabilityIdentity(
    name="extract_metric_series",
    version="v1",
)
```

。

Canonical ID：

```text
extract_metric_series@v1
```

由 Runtime 统一生成。

---

# 82. 现在不要把 Provider Version 放进来

这是下一 Batch。

当前：

```text
Logical Capability Version
```

和未来：

```text
Provider Version
```

必须是两回事。

---

# 83. P1 — CapabilityRegistry.digest 包含 Description

Registry digest：

```text
sha256(all descriptor canonical payload)
```

。

Descriptor canonical payload 包含：

```text
description
```

。

---

# 84. 这意味着

只改：

```text
"Retrieve cited semantic evidence..."
```

的文案，

即使：

```text
contract
risk
validator
execution kind
```

全都没变，

Registry digest 仍会变。

---

# 85. 后果

当前：

```text
ApprovedPlan
绑定 capability_registry_digest
```

。

所以一个纯文案改动可能造成：

```text
ApprovedPlan registry mismatch
Replay/runtime signature变化
```

。

这是：

# **Presentation Identity 污染 Authority Identity**

。

---

# 86. Target

拆：

```text
CapabilityAuthorityDigest
```

只包含：

```text
logical id/version
owner role
input/output contracts
execution kind
risk
runtime limits
validator identities
fallback
completion contract
```

。

以及：

```text
CapabilityPresentationDigest
```

包含：

```text
description
labels
planner-facing documentation
```

。

---

# 87. Planner Prompt 是否要感知 Description 变化

可以。

因为 Planner decision surface 可能改变。

因此可以另有：

```text
PlannerCapabilitySurfaceDigest
```

。

但不要让：

```text
Runtime Authority Digest
```

因为文案换词而变化。

---

# 88. P1 — CapabilityRegistry 注册验证仍偏 Structural

当前验证：

```text
ID/role 非空

无重复 ID

runtime > 0

input/output contract 非空

required input kind
是 accepted input kind 子集
```

。

这是好的基础。

---

# 89. 但还没检查

```text
descriptor.schema_version

capability version format

duplicate input/output kinds

validator identity compatibility

fallback exists

fallback role

fallback output contract

fallback risk

fallback execution semantics
```

。

---

# 90. Fallback 特别值得注意

Descriptor public view 会暴露：

```text
fallback_capability_id
```

。

但 Adaptive Runtime 当前自动 fallback 分支只对：

```text
LLM_BOUNDED_PYTHON
+
on_failure=fallback_deterministic
```

生效。

---

# 91. 某些 deterministic Descriptor 也声明 fallback

例如源码中存在：

```text
compare_periods_v1
→ fallback extract_metric_series_v1

aggregate_metrics_v1
→ fallback extract_metric_series_v1
```

等声明。

但当前 Runtime 自动 fallback branch：

```text
execution_kind == llm_bounded_python
```

才会执行。

---

# 92. 因此 Public Capability Surface 会出现

```text
“这个 Capability 有 fallback X”
```

但 Controller Runtime：

```text
不会在这个 execution kind
自动采用它
```

。

这是：

# **Advertised Capability Semantics Drift**

。

---

# 93. Target

Fallback 不应该只是：

```text
descriptor string
```

。

而应该：

```python
FallbackContract(
    fallback_capability_id,

    trigger_classes,

    preserves_output_contract,

    preserves_input_authority,

    max_risk_class,

    policy_owner="runtime",
)
```

。

---

# 94. Registry Load 时做 Closure Audit

```text
fallback ID exists

role compatible

output contract compatible
或者显式 converter

risk not expanded

no fallback cycle
```

。

---

# 95. P1 — Planner Public View 不等于 Worker Capability Discovery

当前 public view 故意很简洁。

它省略：

```text
capability version

input contract version

max runtime

supports replay

validator IDs

descriptor schema version
```

。

---

# 96. 这不是当前 Planner View 的 Bug

Planner 不应该看到所有底层信息。

问题是：

> **不要以后直接拿 public_view() 当 Worker Handshake Manifest。**

。

---

# 97. Kubernetes Discovery 给了非常好的类比

Kubernetes 明确区分：

```text
Discovery API
    紧凑：
    有哪些 group/version/resource/operation

OpenAPI
    完整：
    schema/endpoint contract
```

。

StateBus 也应该：

```text
Planner Discovery
    compact semantic surface

Runtime Capability Contract
    full authority contract
```

。

参考：

```text
https://kubernetes.io/docs/concepts/overview/kubernetes-api/
```

。

---

# 98. 可以新增第三种 Manifest

不是给 Planner，

也不是完整 CapabilityDescriptor。

而是：

# `ProtocolPeerManifest`

。

---

# 99. ProtocolPeerManifest 表达什么

只表达 Worker Protocol 能力：

```python
ProtocolPeerManifest(
    peer_id,

    supported_protocol_versions,
    schema_digests,

    supported_carriers,

    supported_operation_ids,

    supported_ref_kinds,

    max_frame_bytes,

    feature_flags,

    manifest_digest,
)
```

。

---

# 100. 注意它不表达 Logical Capability

不要放：

```text
extract_metric_series_v1
```

除非未来这个 Worker 本身就是该 capability provider。

那属于下一轮：

```text
Provider Binding
```

。

当前 subprocess worker 主要处理：

```text
semantic_select_v1
decision/logit_gate
```

等 protocol operation。

---

# 101. P1 — 当前其实没有真正 Capability Handshake

现在的：

```text
ExecRequest
→ AckReceived
→ RunStart
```

是：

```text
execution lifecycle handshake
```

。

不是：

```text
protocol/capability negotiation
```

。

不存在：

```text
Hello
Capabilities
ProtocolVersionSelection
SchemaDigestSelection
FeatureSelection
```

。

---

# 102. 但本轮结论不是“立刻加 Hello”

这一点非常重要。

---

# 103. 最新 MCP 给出的反例

MCP 2026-07-28 已经移除了旧：

```text
initialize
initialized
session
```

握手。

现在：

```text
每个 request
自带 protocol version
client capabilities
client identity

server/discover
变成 optional
```

。

参考：

```text
https://blog.modelcontextprotocol.io/posts/2026-07-28/
```

。

---

# 104. 为什么这非常适合 StateBus

你的当前 worker：

```text
本机 subprocess

一个 invocation

执行完退出
```

。

如果为了“正规”增加：

```text
HELLO
CAPABILITIES
NEGOTIATE
EXEC
```

会直接增加：

```text
额外 frames
额外 RTT
额外状态
```

。

这和赛题：

```text
低开销通信
```

是冲突的。

---

# 105. 所以推荐

# **Self-describing Invocation**

。

每次：

```text
ExecRequest
```

自己携带：

```text
protocol version

schema digest

requested operation

required features

invocation binding

grant parent identity
```

。

Worker：

```text
支持
→ Ack

不支持
→ structured ProtocolError
```

。

---

# 106. Optional Discovery 什么时候有用

如果以后 Worker 变成：

```text
persistent process

remote provider

long-lived GPU service

heterogeneous backend
```

再：

```text
Discover once
cache manifest
```

。

---

# 107. 当前 short-lived subprocess 不需要先 discover

这就是本轮推荐与传统“Handshake”最大的差别。

---

# 108. Target Protocol Flow

推荐第一阶段：

```text
Controller
    ↓
build ProtocolInvocationBinding
    ↓
ExecRequest
    - protocol_version
    - schema_digest
    - operation
    - required features
    - invocation_binding_hash
    ↓
Worker

Worker:
validate version
validate schema/features
validate invocation
validate refs
validate expiry
    ↓
AckReceived
    - invocation_binding_hash
    - accepted_protocol_version
    - worker_schema_digest
    ↓
RunStart
    ↓
Heartbeat*
    ↓
Success/Error
    - invocation_binding_hash
    - output contract
```

。

---

# 109. 这不是增加额外 RTT

ACK 本来就已经存在。

只需要：

```text
让 ACK 真正有 binding semantics
```

。

---

# 110. P1 — ACK 当前只有时间戳

`AckReceived`：

```text
header
acked_at_ns
```

。

它没有表达：

```text
我接受了哪个 grant

我接受了哪个 protocol schema

我接受了哪个 operation

我接受了哪个 input ref set
```

。

---

# 111. 推荐 `AckReceived v2`

```text
invocation_binding_hash

accepted_protocol_version

worker_schema_digest

accepted_operation_id

worker_pid
```

。

---

# 112. ACK 的准确语义

应该冻结为：

> Worker 已完成 invocation envelope 的 structural / protocol / authority validation，并接受执行。

不是：

```text
socket connect 成功
```

。

---

# 113. gRPC Health 的借鉴

gRPC 把：

```text
Health / Serving
```

作为独立 service 状态。

这说明：

```text
Worker 健康

Worker 支持某能力

Worker 接受某 invocation
```

本来就应该是三件事。

参考：

```text
https://grpc.io/docs/guides/health-checking/
```

。

---

# 114. 对 StateBus

不要让：

```text
ACK
```

同时表示：

```text
health
capability discovery
authorization
execution started
```

。

ACK 只表达：

```text
接受这一个 invocation
```

。

---

# 115. P1 — Current Heartbeat 不是持续 Lease Signal

实际 subprocess worker：

```text
Ack
RunStart
发送一次 Heartbeat
执行
Result
```

。

没有：

```text
heartbeat loop
```

。

对于当前 semantic selection：

```text
操作很短
```

问题不大。

---

# 116. 但是 Control Protocol 已经声明

```text
heartbeat_interval_ms
lease_timeout_ms
```

。

这会给人：

```text
持续 lease
```

的印象。

---

# 117. 这部分留给 Reliability Batch

Batch-04 只冻结：

```text
Protocol 声明的 lifecycle
必须与实际实现能力一致。
```

。

如果 Worker 不实现 heartbeat loop：

```text
RunStart
应该明确 heartbeat_mode=none/one_shot
```

或者：

```text
不发布 lease contract
```

。

---

# 118. P1 — Cancel / GC 也属于“声明多于实现”

Protocol 定义：

```text
CMD_CANCEL
CMD_GC
```

。

Loopback 可以模拟。

但是当前 one-shot subprocess worker：

```text
接收一个 ExecRequest

同步执行

发 Result

退出
```

。

并没有一个真正：

```text
同时监听 CancelCommand
```

的执行 loop。

---

# 119. 因此当前正确表述

可以说：

```text
Control Protocol 定义了 Cancel/GC message types。
```

不要说：

```text
实际 worker 已经支持实时 cancel / GC protocol。
```

。

---

# 120. P1 — Transport 把 Protocol Exception 吞成 Timeout

`SubprocessExecutorTransport._serve()`：

```python
except Exception:
    pass
```

。

如果：

```text
decode error
bad frame
unexpected protocol exception
```

可能最后表现成：

```text
subprocess_timeout
```

。

---

# 121. 这会损失真实故障语义

例如：

```text
schema mismatch
```

应该是：

```text
PROTOCOL_SCHEMA_MISMATCH
```

而不是：

```text
TIMEOUT
```

。

---

# 122. Target

Transport exception 至少转换：

```text
TransportErrorRecord
```

：

```text
phase
exception class
frame count
peer pid
stderr hash
```

。

不把 raw secrets 塞 telemetry。

---

# 123. P1 — Frame Length 无上限

当前：

```text
读取 4-byte big-endian length

然后：
_recv_exact(sock, payload_len)
```

。

没有：

```text
MAX_CONTROL_FRAME_BYTES
```

。

---

# 124. 风险

坏 peer 可以声明：

```text
4 GiB frame
```

。

Receiver：

```text
持续等待 / 分配 chunks
```

。

本机 trusted subprocess 风险较低，

但 Protocol Contract 应有明确上限。

---

# 125. Target

例如：

```text
MAX_CONTROL_FRAME_BYTES
=
1 MiB
```

或者基于实测：

```text
64 KiB
```

。

因为真正大 payload：

```text
Embedding
Hidden
KV
Artifact
```

本来就应该：

```text
走 SHM / memfd / workspace ref
```

。

Control plane 更应该保持小。

---

# 126. 这和赛题低开销完全一致

控制面：

```text
传 ID / Ref / Receipt
```

。

数据面：

```text
SHM / memfd / file / engine-local state
```

。

不要让 Protobuf Control Frame 变成数据面。

---

# 127. P1 — Control Protocol 没有统一 Semantic Validator

Decode 以后，

没有一个统一：

```python
validate_control_message(message)
```

检查：

```text
schema

IDs non-empty

event/body

timeout range

ref kinds

operation-specific fields

vector lengths

result contract
```

。

---

# 128. 当前 Validation 分散在

```text
Loopback harness

Subprocess worker

Adaptive dispatcher

Adaptive runtime
```

不同层。

所以容易 drift。

---

# 129. 典型例子

Harness：

```text
REQ_EXEC event type required
```

。

Actual Worker：

```text
不检查 event_type
```

。

这已经发生。

---

# 130. Target Validation 分层

```text
Wire Validation
    frame
    protobuf parse

Protocol Validation
    version
    schema
    message/body
    header
    frame limits

Invocation Validation
    operation
    refs
    features
    binding

Runtime Authorization
    grant / policy

Domain Validation
    semantic selection / decision logic
```

。

---

# 131. 不要一个函数做完所有

否则又会变成：

```text
巨大 Validator
```

。

---

# 132. P1 — Intermediate Output Contract Allowlist 语义模糊

`AdaptiveTaskEnvelope` 有：

```text
allowed_output_contracts
```

。

PlanPolicy：

```text
final output
必须在 allowlist
```

。

Step 层：

```python
if step.output_contract_version
   != descriptor.output_contract_version:
    reject

if step.output_contract_version
   not in envelope.allowed_output_contracts
   and step.output_contract_version
       != descriptor.output_contract_version:
    reject
```

。

---

# 133. 第二个条件实际效果

只要：

```text
step contract == descriptor contract
```

那么：

```text
即使 contract 不在 envelope.allowed_output_contracts
```

第二个 gate 也不触发。

---

# 134. 所以需要明确设计意图

如果：

```text
allowed_output_contracts
```

只表示：

```text
允许的 final output contracts
```

那字段应该改名：

```text
allowed_final_output_contracts
```

。

---

# 135. 如果它本来要限制所有 Step

那当前 gate 是错的。

应该：

```text
every step.output_contract
∈ allowed_output_contracts
```

。

本轮不擅自判定产品意图，

但必须把这个 ambiguity 冻结。

---

# 136. Positive Finding — Registry Digest 已经进入 ApprovedPlan

这是非常好的。

Runtime 启动时：

```text
approved_plan.capability_registry_digest
!=
current registry.digest

→ reject
```

。

这防止：

```text
Planner 基于 Registry A 生成 Plan

Runtime 在 Registry B 下执行
```

。

---

# 137. Positive Finding — Runtime 会重新验证 ApprovedPlan

不是：

```text
有 ApprovedPlan object
就无条件执行
```

。

Runtime 会重新走：

```text
PlanPolicyValidator
```

并要求：

```text
approved steps
一致
```

。

这非常重要。

---

# 138. Positive Finding — Grant 输入 kind 会在发放前检查

Runtime：

```text
actual produced ref kind

必须属于 descriptor.input_ref_kinds
```

。

同时：

```text
required_input_ref_kinds
必须存在
```

。

这是：

```text
Grant 最小权限
```

的真实机制。

---

# 139. Positive Finding — Fallback 使用 Fresh Grant

Bounded Python 失败：

```text
不能继续拿原 Python Grant
执行 deterministic fallback
```

。

Runtime 会：

```text
创建 fallback step

读取 fallback descriptor

重新 issue fresh CapabilityGrant
```

。

这是非常正确的 Authority 设计。

---

# 140. Positive Finding — Result 至少绑定 High-level Grant Hash

AdaptiveStepResult：

```text
grant_hash
attempt_id
```

。

Runtime 会检查：

```text
result.grant_hash
==
grant.grant_hash

attempt_id
==
current attempt
```

。

这已经比很多 Agent demo 强。

---

# 141. 但它只在 In-process AdaptiveStepResult 层成立

IPC `SuccessResult` 自身：

```text
没有 grant hash
```

。

所以：

```text
High-level Runtime Result Binding
```

和：

```text
Physical Worker Result Binding
```

还没有统一。

---

# 142. Positive Finding — Replan 不允许修改 Completed Steps

Replacement plan：

```text
task same

registry digest current

重新 policy validate

completed step canonical payload
必须完全相同
```

。

这是很好的：

```text
immutable committed history
```

思想。

---

# 143. External Research — MCP 2026-07-28

最新 MCP 非常值得借鉴，

但不是复制。

---

# 144. MCP 最新变化

2026-07-28：

```text
删除 initialize / initialized handshake

删除 protocol session dependency

每个 request 自描述：

protocol version
client capabilities
client identity

server/discover optional
```

。

官方说明：

```text
https://blog.modelcontextprotocol.io/posts/2026-07-28/
```

。

GitHub TypeScript SDK 当前也有：

```text
versionNegotiation

server/discover

per-request protocolVersion/capabilities
```

相关实现。

---

# 145. StateBus 应借什么

不是：

```text
改成 HTTP
```

。

而是：

> **不要为了 version/capability negotiation 强迫每个短 worker 增加一次握手 RTT。**

。

---

# 146. 应借的模型

```text
Self-describing request
+
Optional discovery
+
Explicit version acceptance
```

。

---

# 147. External Research — Protobuf

官方最重要原则：

```text
field number 是 wire identity

不能复用

删除要 reserve

additive fields 通常 wire-safe

wire-compatible
不代表 application-semantic-compatible
```

。

---

# 148. 对 StateBus 的含义

必须区分：

```text
Wire Compatibility

和

StateBus Semantic Compatibility
```

。

例如：

```text
新增 optional field
```

Protobuf 可能 wire safe。

但如果：

```text
新 Controller
把这个 field
当成 mandatory security decision
```

旧 Worker 忽略它，

业务语义仍然不兼容。

---

# 149. 所以不能只依赖 Protobuf Unknown Fields

需要：

```text
protocol version
required features
schema digest
```

。

---

# 150. External Research — Kubernetes

Kubernetes 的两个设计很适合 StateBus。

---

# 151. 第一：Discovery 与 Full Schema 分离

Kubernetes：

```text
Discovery API
→ 简要说明资源/version/operations

OpenAPI
→ 完整 schema
```

。

StateBus：

```text
PlannerCapabilityView
→ 简要语义面

RuntimeCapabilityDescriptor
→ 完整 authority
```

。

不要合并。

---

# 152. 第二：Versioned API 不直接原地破坏

Kubernetes API deprecation policy 强调：

```text
API version 独立演进

同 release 可同时支持多个版本

新旧 version 有 transition window
```

。

参考：

```text
https://kubernetes.io/docs/reference/using-api/deprecation-policy/
```

。

---

# 153. 对 StateBus

如果未来出：

```text
statebus.control.v2
```

应该：

```text
Controller:
支持 v1 + v2 一个迁移周期

Worker:
明确声明自己支持哪些

ProtocolInvocation:
明确选定一个
```

。

不要：

```text
把 v1 message
原地改成新语义
却继续叫 v1
```

。

---

# 154. 推荐 StateBus Protocol v1 Evolution Rule

冻结：

```text
1.
现有 field number 永不改变

2.
删除 field 后 reserve

3.
新增 optional/additive field 可以留在 v1

4.
新增 mandatory semantic requirement
必须：
feature negotiation
或 protocol v2

5.
oneof 结构 breaking
进入 v2

6.
protocol decoder
不得把 missing version
冒充当前 version
```

。

---

# 155. 推荐 Protocol Feature Negotiation

不需要复杂 capability tree。

第一版：

```text
required_features
```

例如：

```text
semantic_state_v1

decision_gate_v2

grant_binding_v1

result_binding_v1
```

。

Worker：

```text
missing feature
→ unsupported_feature
```

。

---

# 156. 为什么 feature 比 minor version 更实用

因为可能：

```text
Worker A
支持 semantic state

Worker B
支持 decision gate

两者都基于 control.v1
```

。

不用：

```text
v1.7 / v1.8
```

。

---

# 157. 但是 Feature 不能取代 Contract Version

三种 version 必须分开：

```text
Protocol Version

Logical Capability Version

Input / Output Contract Version
```

。

未来还有：

```text
Provider Version
```

下一 Batch。

---

# 158. 推荐 Identity Stack

```text
ProtocolIdentity
    statebus.control.v1

LogicalCapabilityIdentity
    execute_analysis@v2

InputContractIdentity
    statebus.transform_input.v1

OutputContractIdentity
    statebus.aggregation.v1

ProtocolOperationIdentity
    semantic_select@v1
```

。

不要互相代替。

---

# 159. 推荐 Batch-04 Target Architecture

```text
DomainPack
    ↓
PlannerCapabilityView
    ↓
PlanProposal
    ↓
PlanPolicy
    ↓
ApprovedPlan
    │
    ├─ CapabilityAuthorityDigest
    │
    └─ exact Logical Capability
    ↓
CapabilityGrant
    ↓
GrantLedger
    ↓
ProtocolInvocationCompiler
    ↓
ProtocolInvocationBinding
    ↓
ExecRequest
    ├─ protocol version
    ├─ schema digest
    ├─ required features
    ├─ operation
    ├─ ref bindings
    └─ invocation binding hash
    ↓
Worker
    ↓
ProtocolValidator
    ↓
AckReceived(binding)
    ↓
RunStart
    ↓
Heartbeat*
    ↓
SuccessResult(binding)
    ↓
ControlResponseBinder
    ↓
Adaptive Runtime
```

。

---

# 160. 注意还没有 Provider Binder

此处：

```text
Worker
```

先理解成：

```text
已知执行端
```

。

下一 Batch 才做：

```text
Logical Capability
    ↓
Execution Provider Selection
```

。

---

# 161. 推荐新模块布局

第一版不需要很多文件。

可以：

```text
statebus/control/
    protocol.py
    validation.py
    binding.py
    peer_manifest.py

statebus/runtime/
    grant_ledger.py
```

。

---

# 162. `protocol.py`

负责：

```text
ProtocolIdentity

feature constants

operation identity

max frame bytes
```

。

---

# 163. `validation.py`

负责：

```text
message/header validation

event/body consistency

version validation

operation field validation

result binding validation
```

。

---

# 164. `binding.py`

负责：

```text
ProtocolInvocationBinding

ExecutionResultBinding
```

。

---

# 165. `peer_manifest.py`

只在：

```text
optional discovery
```

使用。

---

# 166. `grant_ledger.py`

负责：

```text
ISSUED
BOUND
CONSUMED
EXPIRED
REVOKED
```

。

---

# 167. 不要把它们塞进 CapabilityRegistry

Registry 管：

```text
能力定义
```

。

GrantLedger 管：

```text
一次执行授权
```

。

Protocol 管：

```text
跨进程消息合同
```

。

三者职责不同。

---

# 168. 推荐 `ProtocolInvocationBinding`

更完整版本：

```python
@dataclass(frozen=True)
class ProtocolInvocationBinding:
    invocation_id: str

    parent_grant_hash: str

    task_id: str
    session_id: str
    step_id: str
    attempt_id: str

    target_role: str

    operation_id: str
    operation_version: str

    input_ref_ids: tuple[str, ...]
    input_ref_binding_hashes: tuple[str, ...]

    output_contract_version: str

    workspace_root_id: str

    protocol_version: str
    schema_digest: str

    required_features: tuple[str, ...]

    expires_at_ns: int

    schema_version: str = "statebus.protocol_invocation_binding.v1"

    @property
    def binding_hash(self) -> str:
        ...
```

。

---

# 169. 为什么仍保留 Parent Grant Hash

这样 Audit 可以：

```text
Worker Invocation
    ↓
CapabilityGrant
    ↓
ApprovedPlan
```

回溯。

---

# 170. 为什么不只发 Grant Hash

因为 Worker 必须能检查：

```text
operation
refs
contract
expiry
```

。

---

# 171. Same-host Trust Model

当前：

```text
Controller
自己 spawn Worker

UDS
同 host
```

。

所以第一版：

```text
canonical binding
+
hash
+
private socket
```

就足够做：

```text
integrity/audit binding
```

。

---

# 172. 不要现在上数字签名

签名 / MAC：

```text
跨 trust domain
```

才更重要。

Security Final Pass 再决定：

```text
HMAC
SO_PEERCRED
signed grant
```

。

---

# 173. 但要准确描述 Hash

当前和未来都不要说：

```text
grant_hash authenticates worker
```

。

应该说：

```text
grant_hash cryptographically identifies canonical grant content
```

。

---

# 174. P2 — UDS Peer Identity

当前 UDS 使用：

```text
private-ish local socket
```

。

但 Transport 没看到：

```text
SO_PEERCRED
```

验证：

```text
UID
PID
GID
```

。

这放到：

```text
Security Final Pass
```

更合适。

Batch-04 只记录。

---

# 175. P2 — Socket Directory Permission

代码：

```text
mkdir(mode=0700, exist_ok=True)
```

。

如果目录已经存在，

Python 不会：

```text
自动 chmod 成 0700
```

。

同样放 Security Final Pass。

---

# 176. 推荐 Protocol Error Taxonomy

当前很多错误最后变成：

```text
invalid_exec_request
```

。

建议至少：

```text
PROTOCOL_VERSION_UNSUPPORTED

PROTOCOL_SCHEMA_MISMATCH

PROTOCOL_FEATURE_UNSUPPORTED

PROTOCOL_MESSAGE_INVALID

INVOCATION_BINDING_MISMATCH

GRANT_EXPIRED

REF_BINDING_MISMATCH

OUTPUT_CONTRACT_MISMATCH

WORKER_OPERATION_UNSUPPORTED

RESULT_BINDING_MISMATCH
```

。

---

# 177. Error Detail 不要当 Policy

Machine logic：

```text
error_code
```

。

Human debug：

```text
error_detail
```

。

不要：

```text
解析 error_detail 字符串
决定 fallback
```

。

---

# 178. 推荐 ACK Error

如果 Worker 不支持：

```text
protocol v2
```

直接：

```text
RES_ERR:
PROTOCOL_VERSION_UNSUPPORTED
```

。

不要：

```text
超时
```

。

---

# 179. 推荐 Discovery

未来可选：

```text
DISCOVER_REQ
DISCOVER_RES
```

。

但是不必进入每个请求。

---

# 180. ProtocolPeerManifest 示例

```json
{
  "peer_id": "statebus-local-worker",
  "supported_protocol_versions": [
    "statebus.control.v1"
  ],
  "schema_digests": {
    "statebus.control.v1": "sha256:..."
  },
  "supported_operations": [
    "semantic_select@v1",
    "decision_gate@v2"
  ],
  "supported_ref_kinds": [
    "semantic_state",
    "decision_state"
  ],
  "max_frame_bytes": 65536,
  "features": [
    "grant_binding_v1",
    "result_binding_v1"
  ]
}
```

。

---

# 181. 对 short-lived subprocess

可以不发：

```text
DISCOVER
```

。

Controller 本地已经知道：

```text
同版本 worker package
```

。

只在 ExecRequest 自描述。

---

# 182. 对 persistent worker

启动时：

```text
discover once
```

缓存：

```text
manifest_digest
```

。

每次请求只发：

```text
expected_peer_manifest_digest
```

。

---

# 183. 这对后续 Provider Binding 很有用

下一 Batch：

```text
ProviderDescriptor
```

可以引用：

```text
peer_manifest_digest
```

作为：

```text
provider runtime capability facts
```

。

但这一轮不做 selection。

---

# 184. Capability Registry 优化目标

推荐 Registry 初始化结束后执行：

```text
freeze()
```

。

Freeze 时做完整审计。

---

# 185. Freeze Audit

```text
descriptor schema valid

identity/version canonical

input/output kind duplicates

contract IDs known

validator IDs resolvable

fallback graph valid

fallback no cycle

fallback risk safe

completion contract valid

authority digest generated
```

。

---

# 186. 为什么要 Freeze

现在 Registry：

```text
mutable dict
```

。

ApprovedPlan 绑定：

```text
registry digest
```

。

如果 Plan 生成后：

```text
Registry 被 mutation
```

Runtime 会因为 digest mismatch reject，

这是好的。

但更合理：

```text
启动阶段构造
→ freeze
→ runtime read-only
```

。

---

# 187. 推荐 Registry Digests

```text
authority_digest

planner_surface_digest
```

。

---

# 188. `authority_digest`

包含：

```text
capability identity
contracts
risk
execution kind
validator
fallback
completion
runtime bound
```

。

---

# 189. `planner_surface_digest`

包含：

```text
public semantic descriptions
planner-visible completion contract
logical role
```

。

---

# 190. Runtime Signature 用哪个

```text
Authority Digest
```

。

Planner Prompt Cache / Planner Audit：

```text
Planner Surface Digest
```

。

---

# 191. DomainPack 也建议有 Digest

当前：

```text
pack_id
capability_ids
final_output_contract
```

。

可以：

```text
pack_digest
```

绑定：

```text
当前暴露给 Planner 的 capability allowlist
```

。

---

# 192. 这不是 Provider Registry

不要混。

---

# 193. 推荐 Output Contract 改进

新增：

```python
OutputRefContract(
    kind,
    min_count,
    max_count,
)
```

。

Capability Descriptor：

```text
output_contracts = (...)
```

。

---

# 194. Step Success Gate

从：

```text
all(returned kind ∈ allowed)
```

升级：

```text
returned outputs
satisfy descriptor OutputRefContract

AND

output contract version exact match

AND

all refs resolve to Runtime authority store
```

。

---

# 195. 推荐 Ref Result Admission

```text
Worker/Provider
返回 Ref ID

Runtime
不立即把它加入 produced_refs

先：

RefAdmissionGate
    ↓
resolve ref
verify kind
verify task/session
verify producer attempt
verify integrity
    ↓
produced_refs
```

。

---

# 196. 这与 Batch-03 Artifact Truth 接起来

Batch-03 已经说：

```text
Artifact VERIFIED
不能只相信 Producer
```

。

Batch-04 进一步：

```text
Protocol 返回 Artifact Ref
也不能直接变成 Runtime Authority
```

。

---

# 197. 推荐状态链

```text
Physical Result
    ↓
Protocol Result Binding
    ↓
Ref Admission
    ↓
Artifact Verification
    ↓
Logical Step Completed
```

。

---

# 198. 当前顺序需要注意

现在 Runtime：

```text
result.success
+
kind allowed
```

就：

```text
supervisor.complete()
```

并加入：

```text
produced_refs
```

。

产品 Dispatcher 内部通常已经验证。

但 Runtime Engine 的 generic contract 不足。

---

# 199. 如果保留 `execute_step` 注入 seam

至少把它标成：

```text
trusted internal testing/provider adapter interface
```

。

不要把它描述为：

```text
untrusted worker result interface
```

。

---

# 200. 推荐 Control Message Validation Test Matrix

必须补。

---

# 201. Version Tests

```text
missing schema version
→ reject

unknown v2
→ unsupported version

known v1
→ pass

schema digest mismatch
→ reject
```

。

---

# 202. Body/Event Tests

```text
body=ExecRequest
event=Success
→ reject

body=Success
event=ReqExec
→ reject
```

。

---

# 203. Header Binding Tests

篡改任一：

```text
trace
task
step
attempt
role
```

Expected：

```text
RESULT_BINDING_MISMATCH
```

。

---

# 204. Grant Tests

```text
wrong parent grant hash
→ reject

expired binding
→ reject

same binding replay second time
→ reject

operation not authorized
→ reject
```

。

---

# 205. Result Tests

```text
wrong invocation binding hash
→ reject

wrong output contract
→ reject

wrong attempt
→ reject

unknown ref kind
→ reject

zero outputs when min=1
→ reject
```

。

---

# 206. Frame Tests

```text
oversize declared length
→ reject immediately

truncated frame
→ frame error

extra bytes
→ frame mismatch
```

。

---

# 207. Schema Drift Test

CI：

```text
.proto descriptor
==
runtime descriptor
```

。

如果改成 generated pb2，

这条自然消失。

---

# 208. Unknown Field Tests

新 Sender：

```text
新增 additive field
```

旧 Receiver：

```text
能 decode
```

。

但是如果 feature mandatory：

```text
feature negotiation rejects old peer
```

。

这样明确区分：

```text
wire parse
```

和：

```text
semantic support
```

。

---

# 209. Grant Lifecycle Tests

```text
ISSUED
→ BOUND
→ CONSUMED

第二次 BOUND
→ reject

CONSUMED
→ reject

EXPIRED
→ reject
```

。

---

# 210. Real Lifecycle Tests

不要只用：

```text
supervisor.ack()
```

。

要真正：

```text
subprocess sends Ack
→ supervisor transitions ACKED
```

。

---

# 211. ACK Timeout Test

Worker：

```text
connect
但不 ACK
```

。

Runtime：

```text
trap_if_ack_timed_out
```

真实触发。

不是 harness 在：

```text
runtime_reuse_contract
```

里塞 `drop_ack` 然后返回模拟 Error。

---

# 212. Lease Test

未来 persistent / long operation：

```text
RUN_START
Heartbeat
Heartbeat
stop
```

。

Runtime：

```text
真实 heartbeat timeout
```

。

这属于后续 Reliability 实现，

但 Batch-04 应先把 protocol seam 留好。

---

# 213. 推荐迁移 Slice

这一轮不实现。

如果开始改，按下面顺序最稳。

---

# PCH-R0 — Protocol Truth Naming

只做：

```text
区分：

PlannerCapabilityView
RuntimeCapabilityDescriptor
ProtocolPeerManifest

Execution Lifecycle
Protocol Negotiation

CapabilityGrant
ProtocolInvocationBinding
```

。

不改 wire。

---

# PCH-R1 — Single Schema Source

```text
.proto
成为 canonical schema

移除手工 descriptor duplication
或者自动 descriptor parity
```

。

加：

```text
schema digest
```

。

---

# PCH-R2 — Protocol Validator

增加：

```text
version validation
body/event
header IDs
frame limit
operation validation
```

。

不改变 operation message shape。

---

# PCH-R3 — Invocation / Result Binding

增加：

```text
ProtocolInvocationBinding

ACK binding hash

Result binding hash
```

。

把：

```text
grant_hash non-empty
```

升级为：

```text
exact invocation authority
```

。

---

# PCH-R4 — Grant Ledger

统一：

```text
ISSUED
BOUND
CONSUMED
EXPIRED
REVOKED
```

。

CodeAct 不再自己私有一套 one-shot 语义。

---

# PCH-R5 — Real Lifecycle Wiring

让 subprocess：

```text
ACK / RUN_START / HEARTBEAT / Result
```

真实驱动：

```text
RuntimeSupervisor
```

。

删除 Adaptive path 的 synthetic ACK/RUNNING。

---

# PCH-R6 — Output / Ref Admission

补：

```text
required output cardinality

output contract binding

Ref admission
```

。

---

# PCH-R7 — Typed Operations v2

如果 R0-R6 后仍值得：

```text
ExecRequest mega-message
→ oneof typed operations

SuccessResult
→ oneof typed results
```

。

这是 protocol v2 候选，

不需要第一天做。

---

# 214. 为什么 typed oneof 放后面

当前最严重的问题不是：

```text
operation 用字符串
```

本身。

而是：

```text
version 不校验
grant 不绑定
result 不绑定
lifecycle 两套 truth
```

。

先修这些收益更大。

---

# 215. 不建议当前做

```text
❌ 引入 gRPC Server
❌ 上 HTTP/2
❌ 上 service mesh
❌ 上 etcd 做 capability registry
❌ 做复杂 service discovery
❌ 每个 subprocess 先 HELLO 再 NEGOTIATE
❌ 给本地每条 Grant 做公钥签名
❌ 把 PlannerCapabilityView 塞满物理执行信息
❌ 把 Provider selection 提前塞进 Batch-04
❌ 把所有 operation 一次性重写成新 proto v2
```

。

---

# 216. 为什么不推荐 gRPC

你现在：

```text
same-host
short-lived subprocess
UDS
small typed control messages
```

。

gRPC 会增加：

```text
server lifecycle
channel
service definition
HTTP/2 stack
metadata
dependency
```

。

对比赛没有明显收益。

现有：

```text
UDS + Protobuf + length framing
```

完全够。

---

# 217. 真正该做的是

把现在已经很轻的 transport：

```text
变得 contract-correct
```

。

不是换 transport。

---

# 218. 这对“低开销通信”反而更有利

最终：

```text
no extra handshake RTT

one typed request

small control metadata

large state stays out-of-band

one ACK

one Result
```

。

非常适合比赛。

---

# 219. 对赛题叙事的提升

修正以后可以说：

> StateBus 不仅使用 UDS + Protobuf 降低控制消息开销，而且将语义 Capability Authority 与物理协议 Invocation 分层：Planner 只能看到经过裁剪的逻辑能力面，Runtime 通过 ApprovedPlan 和 one-shot CapabilityGrant 冻结本次执行权限，再派生轻量 ProtocolInvocationBinding。短生命周期 Worker 不需要额外 discovery RTT，每个请求自带 protocol/schema/feature/binding identity；ACK 和 Result 必须回显 invocation binding，实际 Worker lifecycle 驱动 Runtime Supervisor。

这会比：

```text
“我们用了 protobuf”
```

高级很多。

---

# 220. 当前可以准确 Claim 的内容

当前已经可以说：

```text
StateBus has a typed protobuf control envelope.

The control plane carries task/step/attempt identity.

Adaptive plans are bound to a capability registry digest.

PlanPolicy checks capability ownership,
risk class,
input ref kinds,
output contract,
completion criteria.

CapabilityGrant binds
task/session/step/attempt/capability/version/input refs/
output contract/workspace/runtime budget/expiry/approved plan.

Adaptive fallback issues a fresh grant
instead of reusing the failed Python grant.

Adaptive Runtime checks returned high-level grant hash
and attempt identity.

The UDS subprocess transport is real cross-process communication.

The worker emits AckReceived / RunStart / Heartbeat / Result frames.
```

。

---

# 221. 当前不能过度 Claim

不要说：

```text
Worker independently verifies CapabilityGrant.

Protocol version is negotiated.

Missing protocol versions are rejected.

ACK means the Runtime received an actual worker ACK.

RuntimeSupervisor is driven by worker heartbeats.

All declared Control commands are implemented end-to-end.

Capability public_view is a complete peer discovery manifest.

Every VERIFIED protocol result is bound to a grant.

Every successful step is guaranteed to produce required outputs.

CapabilityGrant is globally one-shot enforced.

.proto is the sole protocol schema source.
```

这些当前都不成立。

---

# 222. Batch-04 Risk Table

| Priority | 问题 | 类型 |
|---|---|---|
| **P0** | Adaptive Runtime synthetic ACK/RUNNING 与真实 subprocess ACK/RUN_START 两套 lifecycle truth | Handshake Truth |
| **P0** | `capability_grant_hash` 到 Worker 只检查 non-empty，无法独立 enforce grant | Authority Boundary |
| **P0** | Missing `schema_version` 被 decoder 自动冒充当前版本 | Protocol Identity |
| **P0/P1** | `.proto` 与 `schema.py` 两份 schema source | Schema Drift |
| **P0/P1** | Success gate 允许 `success=True + zero outputs` vacuous pass | Result Contract |
| **P1** | SuccessResult 不携带 grant/invocation binding | Result Authority |
| **P1** | Response header task/step/attempt/schema 未统一验证 | Protocol Binding |
| **P1** | Actual worker 不检查 Header event type；Harness 检查 | Validation Drift |
| **P1** | `runtime_reuse_contract` 混入 untyped behavior/test flags | Protocol Semantics |
| **P1** | `operation` 是 free string，ExecRequest/SuccessResult 逐渐 mega-message | Typed Protocol |
| **P1** | Frame length 没有 max bound | Protocol Robustness |
| **P1** | Transport exception 被吞并常退化成 timeout | Observability |
| **P1** | CapabilityGrant 没有统一 one-shot GrantLedger | Authorization Lifecycle |
| **P1** | Capability ID 自带 `_v1`，同时 descriptor 又有 `version=v1` | Identity |
| **P1** | Registry Authority digest 被 human description 改动污染 | Identity |
| **P1** | Registry 不验证 fallback closure/schema/version 等 | Capability Integrity |
| **P1** | Public fallback metadata 与 Runtime 实际自动 fallback scope 不完全一致 | Discovery Truth |
| **P1** | Planner public view 不应被误用为 peer capability manifest | Layering |
| **P1** | `allowed_output_contracts` 对 intermediate step 的语义不清 | Policy Contract |
| **P1** | Cancel/GC/Heartbeat lifecycle 定义强于当前实际 worker wiring | Protocol Completeness |
| **P2** | UDS peer credential 未验证 | Security |
| **P2** | Existing socket dir permission / unlink hardening | Security |

---

# 223. Batch-04 Truth Ladder

可以定义：

```text
P0 — Wire Parse
Protobuf 能 decode

P1 — Protocol Identity
version/schema 明确

P2 — Peer Compatibility
features/operation 可执行

P3 — Invocation Binding
request 与 Runtime authority 精确绑定

P4 — Worker Acceptance
真实 ACK

P5 — Execution Liveness
真实 start/heartbeat

P6 — Result Binding
result 与 invocation 精确绑定

P7 — Ref Admission
返回 refs 通过 Runtime authority

P8 — Artifact Truth
进入 Batch-03 Verification
```

。

---

# 224. 当前成熟度

大致：

```text
P0  强

P1  弱到中
version 字段存在但 enforcement 弱

P2  弱
没有正式 peer compatibility negotiation

P3  部分
grant hash 有但 worker 不可独立验证

P4  两套 truth

P5  模型存在，真实 wiring 弱

P6  中弱
高层 result 有 grant hash，
IPC result 没有

P7  产品 dispatcher 内部分实现，
Runtime generic gate 较薄

P8  Batch-03 已有较强基础
```

。

---

# 225. 与 Batch-01 的关系

Batch-01：

```text
谁可以进入系统？
Planner 能提出什么？
```

。

Batch-04：

```text
Runtime 批准以后，
这个 Authority 如何安全地跨执行边界？
```

。

---

# 226. 与 Routing 的关系

Routing 决定：

```text
Logical Capability
```

。

Protocol 不应该：

```text
重新决定 capability
```

。

Protocol 只负责：

```text
把 Runtime 已批准的执行绑定
传给 Worker。
```

。

---

# 227. 与下一 Batch Provider Binding 的关系

下一 Batch 会回答：

```text
一个 Logical Capability
有多个 Provider 时
选谁？
```

。

例如：

```text
execute_analysis

→ DSL Provider
→ Bounded Python Provider
→ Future Native Provider
```

。

Batch-04 不选。

---

# 228. Batch-04 只提供 Provider 必须满足的 Protocol Contract

未来：

```text
ExecutionProviderDescriptor
```

应该声明：

```text
protocol peer manifest digest
supported invocation operations
runtime features
```

。

---

# 229. 与 Batch-03 Artifact 的关系

Batch-04 最终输出：

```text
Result Binding
```

。

Batch-03 再决定：

```text
Result 中的 Artifact
能否 VERIFIED
```

。

所以：

```text
Protocol Success
≠
Artifact Verified
```

。

---

# 230. 与 Shared State 的关系

Control plane 只发：

```text
State Ref
Binding
Manifest
```

。

大 payload：

```text
Embedding
Decision
Hidden
KV
```

仍走：

```text
SHM / memfd / engine local
```

。

---

# 231. 与 Decision State 的关系

未来 Decision：

```text
DecisionStateRef
```

传给 Worker。

Protocol 应只知道：

```text
decision_state ref kind
operation decision_gate
```

。

不在 Control Protocol 中塞：

```text
所有 Decision policy implementation
```

。

---

# 232. 与 Hidden / Latent 的关系

Hidden 以后也一样：

```text
LatentStateRef
```

是 data plane object。

Protocol：

```text
只传 Ref Binding
```

。

绝不能：

```text
把 hidden tensor
塞 protobuf
```

。

---

# 233. 与 KV 的关系

APC/KV 是：

```text
Inference execution optimization
```

。

ProtocolInvocationBinding 可以未来带：

```text
reuse decision receipt ID
```

但：

```text
Worker Protocol
不能决定 logical APC policy
```

。

---

# 234. 推荐最终冻结原则 1

# Planner Discovery ≠ Runtime Authority

。

---

# 235. 原则 2

# Runtime Authority ≠ Worker Operation

需要：

```text
ProtocolInvocationBinding
```

桥接。

---

# 236. 原则 3

# Grant Hash ≠ Authorization By Itself

。

---

# 237. 原则 4

# ACK 必须是真实 Worker Acceptance

不能是：

```text
Runtime 本地状态推进
```

。

---

# 238. 原则 5

# Wire-compatible ≠ Semantic-compatible

。

---

# 239. 原则 6

# Short-lived Worker 不值得额外 Handshake RTT

使用：

```text
self-describing request
```

。

---

# 240. 原则 7

# Optional Discovery 只用于长期 / 异构 Peer

。

---

# 241. 原则 8

# Control Plane 必须保持 Small

大数据永远 out-of-band。

---

# 242. 原则 9

# Protocol Result 必须先 Binding，再进入 Artifact Truth

。

---

# 243. 原则 10

# Capability / Protocol / Provider 三种版本必须分开

。

---

# 244. 推荐下一轮

按照总审计路线：

```text
Batch-05
Logical Capability / Provider Binding
```

最自然。

---

# 245. Batch-05 应重点回答

```text
LogicalCapabilityDescriptor

ExecutionProviderDescriptor

ExecutionBindingPolicy

Provider Eligibility

DSL / Python
是不是两个 capability
还是两个 provider？

Local Runtime
Subprocess
vLLM
未来 Remote
如何作为 provider？

Fallback
是 provider rebind
还是 semantic replan？

Provider health / resource
如何进入 binding？

Provider version
如何和 logical capability version
区分？

Binding Receipt
如何进入 Artifact Derivation？
```

。

---

# 246. Batch-04 最终冻结结论

> **StateBus 当前并不缺 Capability Registry，也不缺 Protobuf，更不缺一个形式上的 ACK/Heartbeat 状态机；真正缺的是把 Controller 内已经较强的 Capability Authority 延伸到 Worker Boundary 的“薄绑定层”。当前 Planner surface、Runtime authority 和 Worker protocol 三层已经客观存在，但还没有被明确建模：协议版本会被默认补成当前版本，`.proto` 与动态 descriptor 有双 source，CapabilityGrant 到 Worker 后退化为 non-empty hash，IPC Result 不回显 grant，Adaptive Runtime 又在真实 dispatch 前 synthetic ACK/RUNNING。最佳改法不是引入 gRPC 或重型 handshake，而是保留 UDS + Protobuf，建立 single-source schema、self-describing invocation、ProtocolInvocationBinding、GrantLedger、grant-bound ACK/result、真实 lifecycle wiring 和 output/ref admission。这样既更准确，也不会破坏赛题最重要的低开销优势。**

---

# 247. External References

## StateBus Source

```text
https://github.com/qcrs/os/blob/master/statebus/runtime/capability_registry.py
https://github.com/qcrs/os/blob/master/statebus/runtime/domain_packs.py
https://github.com/qcrs/os/blob/master/statebus/runtime/plan_policy.py
https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_runtime.py
https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_dispatcher.py
https://github.com/qcrs/os/blob/master/statebus/runtime/supervisor.py

https://github.com/qcrs/os/blob/master/statebus/control/statebus_control.proto
https://github.com/qcrs/os/blob/master/statebus/control/schema.py
https://github.com/qcrs/os/blob/master/statebus/control/messages.py
https://github.com/qcrs/os/blob/master/statebus/control/transport.py
https://github.com/qcrs/os/blob/master/statebus/control/subprocess_worker.py
```

## Protocol Buffers

```text
https://protobuf.dev/best-practices/dos-donts/
https://protobuf.dev/programming-guides/proto3/
```

重点借鉴：

```text
single schema source
never reuse field numbers
reserve removed fields
additive wire evolution
wire compatibility != semantic compatibility
```

## Model Context Protocol 2026-07-28

```text
https://blog.modelcontextprotocol.io/posts/2026-07-28/
https://github.com/modelcontextprotocol/typescript-sdk
```

重点借鉴：

```text
self-describing requests
protocol version per request
capabilities per request
optional server/discover
avoid mandatory handshake/session overhead
```

## Kubernetes API / Discovery

```text
https://kubernetes.io/docs/concepts/overview/kubernetes-api/
https://kubernetes.io/docs/reference/using-api/deprecation-policy/
```

重点借鉴：

```text
compact discovery vs full schema
versioned API evolution
old/new coexistence during migration
```

## gRPC Health Checking

```text
https://grpc.io/docs/guides/health-checking/
```

重点借鉴：

```text
health/readiness
!=
capability support
!=
per-invocation acceptance
```
