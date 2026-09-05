# StateBus Batch 09 — Security / Privacy Boundary Final Pass
## 项目安全边界、信任域与端到端执行链最终审计

> **项目**：StateBus / `qcrs/os`
>
> **源码 Truth**：`qcrs/os:master`
>
> **日期**：2026-09-03
>
> **定位**：Batch 09 / Security & Privacy Final Pass
>
> **本轮边界非常明确**：
>
> ```text
> 只为当前 StateBus 项目确定安全边界；
> 只修会影响当前比赛 / 项目正确性的安全问题；
> 不建设通用安全平台；
> 不扩展成多租户 RBAC / KMS / PKI / 零信任系统；
> 不把安全能力包装成新的核心卖点。
> ```
>
> Batch 09 之后不再继续设计新的安全功能。
>
> 本文目标只有两个：
>
> 1. 明确当前 StateBus 到底信任谁、不信任谁；
> 2. 把 Task → Plan → Capability → State/Memory → Worker/CodeAct → Artifact → Evaluator 的完整安全链闭合。

---

# 0. Executive Summary

当前 StateBus 的安全设计主线其实已经比较清楚：

# **安全核心不是“相信 Agent 不犯错”，而是“Agent 没有直接执行权限”。**

整体 authority path：

```text
User / Evidence / Model Output
        │
        │ untrusted data / proposal
        ▼
Task / Plan Proposal
        │
        ▼
PlanPolicy
        │
        │ bounded authority
        ▼
ApprovedPlan
        │
        ▼
CapabilityGrant
        │
        │ step + attempt + input refs + contract + TTL
        ▼
Provider / Worker / CodeAct
        │
        ▼
Candidate Artifact
        │
        ▼
Validator / CommitGate
        │
        ▼
Verified Artifact
        │
        ├──> Memory Commit / Replay Eligible
        └──> Final Result
```

这里真正重要的是：

```text
Model Suggestion
≠
Runtime Authority
```

。

这与 StateBus 前八批设计实际上是一致的：

```text
PlanSelector
→ PlanPolicy

Logical Capability
→ ExecutionBindingPolicy

Approved Step
→ CapabilityGrant

State Candidate
→ Consumption Policy

Memory Candidate
→ Compatibility / Replay Policy

Generated Code
→ Policy + Sandbox + Validator

Artifact Candidate
→ CommitGate
```

---

# 1. Batch 09 的安全目标

当前项目不是：

```text
Internet-facing multi-tenant agent cloud
```

。

它是：

```text
single-host
single project/user trust domain
openEuler
local Runtime Controller
local workers / local vLLM
competition / research environment
```

。

因此合理的安全目标是：

```text
1.
模型不能扩大自己的执行权限

2.
Agent 不能越过 Capability / Ref / Workspace 边界

3.
模型生成 Python 不能访问宿主敏感资源或网络

4.
未经验证 Artifact 不能进入 Memory / Replay

5.
不兼容 Memory / KV / State 不得被误复用

6.
旧 attempt / stale result 不得覆盖当前执行

7.
Evaluator Gold 不进入 Runtime

8.
Runtime logs 不无意义复制业务内容

9.
所有临时 State / KV / Workspace 有明确生命周期

10.
安全边界与真实部署能力一致，不夸大为多租户零信任
```

。

---

# 2. 明确 Trust Model

Batch 09 最重要的产物就是这一张表。

| 对象 | 信任级别 | 当前处理 |
|---|---|---|
| User Request | Untrusted Data | 可影响任务语义，不能直接获得 capability |
| Retrieved Evidence | Untrusted Data | 可作为 evidence，不作为 authority |
| LLM Planner Output | Untrusted Proposal | 必须过 PlanPolicy |
| LLM Role Output | Untrusted Semantic Output | parser / contract / validator |
| LLM Generated Python | Untrusted Code | mandatory bwrap sandbox |
| Memory Candidate | Untrusted Until Compatible | compatibility + policy |
| Semantic/Logit/Latent State | Sensitive Runtime State | ref/hash/schema/consumer contract |
| Runtime Controller | Trusted | authority owner |
| Capability Registry | Trusted | capability truth |
| PlanPolicy | Trusted | plan authority |
| ExecutionBindingPolicy | Trusted | provider authority |
| Validator / CommitGate | Trusted | output acceptance |
| Trusted deterministic Worker | Trusted local executor | 只能执行 Grant 范围 |
| vLLM local service | Trusted inference provider | 不作为 authorization source |
| Benchmark Evaluator | Trusted but isolated | Runtime 完成后评分 |
| Host kernel / root admin | Out of Scope | 当前项目不防 host root |
| 同 UID 恶意本地进程 | Mostly Out of Scope | 当前非多租户模型 |

---

# 3. 最重要的边界：Runtime Controller 是 Authority Root

当前 `AdaptiveTaskEnvelope` 已经定义：

```text
allowed_capability_ids
allowed_output_contracts
allowed_memory_policies
role_cardinality

max_plan_steps
max_dependency_depth

max planner tokens
max retrieval
max runtime
max replan
max attempts

risk_class
allow_llm_python
```

。

所以它不是普通 config。

它实际上是：

# **Task Authority Envelope**

。

模型最多只能：

```text
在这个 envelope 中提出方案。
```

不能：

```text
修改 envelope。
```

不能：

```text
创建新的 capability。
```

不能：

```text
提高 risk class。
```

不能：

```text
无限 retry。
```

不能：

```text
自己授权 LLM Python。
```

---

# 4. Planner 不是安全主体

完整路径：

```text
Planner
    │
    ▼
PlanProposal
    │
    ▼
PlanPolicyValidator
```

`PlanPolicyValidator` 当前会检查：

```text
task id
schema

step budget
dependency depth
cycle

allowed capability
capability owner role

input ref kinds
upstream ref kinds

output contract

memory policy

risk class

LLM Python permission

completion criteria

prompt/completion budget

failure behavior
```

。

因此：

# **Planner 的输出永远只是 Proposal。**

这应该成为最终架构说明中的固定语义。

---

# 5. Prompt Injection 的正确安全边界

当前 `plan_policy.py` 还存在：

```text
ignore previous
<system
```

等 prompt escape marker 检查。

这个机制可以保留。

但不能把它解释为：

```text
Prompt Injection Defense
```

。

因为 indirect prompt injection 可能来自：

```text
retrieved evidence
documents
memory summaries
tool output
```

这些内容不一定经过这个字符串检查。

---

# 6. StateBus 对 Prompt Injection 更可靠的防线是什么

不是：

```text
识别恶意字符串。
```

而是：

```text
即使模型被影响
也不能扩大 authority。
```

也就是：

```text
Malicious Evidence
      ↓
Model chooses bad capability?
      ↓
PlanPolicy
      ↓
not in allowed_capability_ids
      ↓
DENY
```

或者：

```text
Model tries code execution
      ↓
Envelope allow_llm_python = false
      ↓
DENY
```

或者：

```text
Model asks worker read new file
      ↓
Grant input_ref_ids 不包含
      ↓
DENY
```

。

这个安全思路明显比：

```text
prompt string blacklist
```

更加可靠。

外部 OWASP LLM06:2025 对 Excessive Agency 的核心建议也是：

```text
限制可调用功能
限制权限
限制 autonomy
```

与 StateBus 的：

```text
CapabilityDescriptor
AdaptiveTaskEnvelope
CapabilityGrant
```

是同一方向。

---

# 7. ApprovedPlan 也不是最终执行权限

StateBus 还有一层非常好的设计：

```text
ApprovedPlan
      ↓
CapabilityGrant
```

。

`CapabilityGrant` 当前绑定：

```text
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

因此它本质上是：

# **One-Attempt Execution Authorization**

。

---

# 8. Grant 的安全语义

一个 Agent 即使拿到了：

```text
Grant A
```

也不能拿它去执行：

```text
Step B
Attempt B
Capability B
Input Ref B
```

。

Runtime 后续还检查：

```text
result.grant_hash == grant.grant_hash

result.attempt_id == current attempt
```

否则：

```text
grant_binding_mismatch
```

。

LLM CodeAct 的验证更严格：

```text
task
step
attempt
session
capability
approved plan
input refs
expiry
```

全部必须一致。

---

# 9. 但 Grant 不是 Cryptographic Bearer Token

这里要明确边界。

当前：

```text
grant_hash
=
SHA256(canonical payload)
```

。

它证明：

```text
binding / identity / integrity reference
```

但不证明：

```text
只有 Controller 能生成。
```

没有：

```text
MAC
signature
secret
```

。

所以当前 Claim Boundary：

> CapabilityGrant 是 StateBus 可信 Controller 域内的 bounded authorization record，不是面向敌对远程进程的 cryptographic capability token。

这是完全合理的。

比赛没有必要为了这个增加：

```text
PKI
JWT
HMAC grant service
```

。

---

# 10. 当前 Control Plane 的 Trust Boundary

当前：

```text
Controller
    │
    │ Unix Domain Socket
    ▼
Local Worker
```

。

UDS 当前提供：

```text
本机进程通信
typed framing
request/response
```

。

不提供：

```text
remote authentication
encryption
network security
```

。

这应该明确。

---

# 11. UDS 当前两个低成本 P0 Hardening

## P0-1 Frame Size Limit

当前：

```text
4-byte payload length
↓
_recv_exact(payload_len)
```

没有明确：

```text
MAX_CONTROL_FRAME_BYTES。
```

如果意外连接了错误 peer：

```text
大 length
```

可以造成：

```text
memory / blocking DoS。
```

建议：

```python
MAX_CONTROL_FRAME_BYTES = 16 * 1024 * 1024
```

在：

```text
recv_control_message
recv_text_message
recv_text_control_message
```

中先拒绝超限。

---

## P0-2 Socket Permission

建议：

```text
socket dir = 0700
socket file = 0600
```

。

当前 parent dir 已尝试：

```text
0700
```

。

正式路径再明确 chmod socket 即可。

---

# 12. 要不要实现 `SO_PEERCRED`

如果 Batch07 实现：

```text
PersistentWorkerBroker
```

则建议验证：

```text
peer UID
worker PID / generation
```

。

但优先级：

```text
P1
```

。

当前 subprocess 是 Controller 直接 spawn：

```text
same host
same trust domain
```

不需要因此引入复杂认证层。

---

# 13. State Plane 的 Trust Boundary

当前：

```text
LayeredStateStore
```

支持：

```text
INLINE

SHARED_MEMORY

MEMFD

MMAP_FILE

CAS / Workspace 等外围存储
```

。

每个 State Handle 已经有：

```text
ref id
object kind
storage kind
size
blob hash
metadata
```

。

Semantic State 又有：

```text
manifest
encoder identity
producer / consumer proof
```

。

因此：

```text
StateRef
```

不是裸指针。

这是正确方向。

---

# 14. State Plane 当前真正需要修的 P0：Path Containment

`LayeredStateStore` 当前会直接：

```text
metadata/<ref_id>.json

mmap/<ref_id>.bin
```

。

也就是：

```python
self.metadata_dir / f"{ref_id}.json"
self.mmap_dir / f"{ref_id}.bin"
```

。

如果未来一个非 Controller 生成的：

```text
ref_id
```

进入：

```text
publish()
```

例如：

```text
../../foo
```

就有 path traversal 风险。

当前代码通常由 Controller 生成 ref ID，所以现实风险有限。

但这是非常值得 P0 修的：

```text
成本极低
与设计语义完全一致。
```

---

# 15. 推荐统一 ID Grammar

对：

```text
task_id
session_id
step_id
attempt_id
ref_id
artifact_id
state_id
```

统一：

```text
[A-Za-z0-9._-]
```

。

例如：

```text
1–128 chars
```

。

禁止：

```text
/
\
..
NUL
absolute path syntax
```

。

---

# 16. 更好的实现方式

不要每个模块自己判断。

新增：

```text
safe_component(value)

safe_relative_path(root, relpath)
```

。

强制：

```text
resolved_path.is_relative_to(resolved_root)
```

。

---

# 17. Workspace 也存在同样问题

当前：

```text
WorkspaceManager.layout_for_task()
```

直接：

```text
workspace_root / task_id
```

。

`step_layout()`：

```text
task_root / steps / step_id
```

。

`write_json()`：

```text
layout.root / relpath
```

。

这里也应该使用同一个：

```text
safe path primitive。
```

---

# 18. 为什么这比“给系统加鉴权”优先

因为当前 trust model 已经是：

```text
单机可信 Controller。
```

最现实的 bug 不是：

```text
有人伪造 OAuth token。
```

而是：

```text
某个 ID / relpath 经过错误路径
写出了 task root。
```

。

所以 Batch09 应优先修：

```text
真实路径边界。
```

---

# 19. Shared Memory 的隐私边界

Named Shared Memory：

```text
本机 IPC object
```

。

在当前：

```text
single-user / trusted host
```

环境可以接受。

但不能 claim：

```text
对同 UID 恶意进程保密。
```

。

---

# 20. MEMFD 的边界更窄

MEMFD：

```text
anonymous fd
+
explicit pass_fds
```

更适合：

```text
短生命周期
需要明确传递给某个 child
敏感 intermediate state
```

。

但当前 Dense Semantic State 因为需要跨 PID resolver：

```text
仍主要使用 named shared memory / mmap。
```

。

这是合理工程折中。

---

# 21. StateRef 当前还缺一个最小 Authority Binding

`SemanticStateRef` 主要绑定：

```text
state
storage
hash
manifest
source docs
```

。

`LogitStateRef` 有：

```text
producer_role
consumer_role
```

。

但 State Ref 本身没有统一：

```text
task_id
session_id
producer_step_id
allowed_consumer_step_ids
```

。

当前实际是：

```text
Runtime 外部逻辑控制 consumer。
```

所以暂时安全。

---

# 22. Batch09 推荐 P1

不新建复杂 ACL。

只把 State Publication Contract 补成：

```text
owner_task_id
owner_session_id
producer_step_id
allowed_consumer_steps
```

。

Resolver：

```text
resolve(ref, current_task, current_session, current_step)
```

做一次 equality / membership check。

这只是落实已有：

```text
ApprovedPlan / Grant
```

到 data plane，

不是新安全体系。

---

# 23. 非文本状态是否应该持久化

分类：

## Semantic Embedding

可以：

```text
task/session 生命周期
```

必要时：

```text
Memory commit
```

但必须走：

```text
Memory policy。
```

---

## Logit State

默认：

```text
attempt-local
```

执行决策结束：

```text
release。
```

不进长期 Memory。

---

## Latent Hidden State

如果未来实现：

```text
session / attempt scoped
```

默认：

```text
不持久化
不跨 task reuse
```

。

---

## KV

```text
短租约
engine-local
task-bound
authorized consumer only
```

。

---

# 24. Memory Plane 是当前安全设计比较成熟的一部分

当前 Memory 已经不是：

```text
vector 相似
→ 直接 reuse。
```

而是：

```text
Query
 ↓
keyword/tag/vector candidates
 ↓
RRF
 ↓
Compatibility
 ↓
Policy
 ↓
Consumption
```

。

---

# 25. Replay Compatibility 当前会检查

包括：

```text
Memory must be committed

Validation must pass

runtime signature

output contract

validator digest

task family
intent op
required outputs

input schema
input lineage

replay-ready

execution recipe

requested memory policy
```

。

所以：

# **Retrieval Similarity ≠ Replay Authority**

这是非常正确的边界。

---

# 26. Candidate Memory 也不会自动成为 Replay

当前：

```text
CANDIDATE
```

可以进入 candidate pool，

但 replay class 会降到：

```text
ASSIST
```

。

只有：

```text
COMMITTED + PASSED
```

才允许继续走 replay eligibility。

这个设计应该保留。

---

# 27. Memory 当前最大的 Privacy Boundary Gap

不是 compatibility。

而是：

```text
visibility scope。
```

当前 MemoryRef / MemoryQuery 没有显式：

```text
principal_id
tenant_id
trust_domain
```

。

所以 Memory Store 是：

```text
global within store instance。
```

---

# 28. 当前项目如何处理最合适

不要实现复杂：

```text
tenant RBAC。
```

明确：

# **一个 MemoryIndexStore 实例属于一个 StateBus Trust Domain。**

例如：

```text
Benchmark family
Project corpus
Session group
```

。

不同 trust domain：

```text
不同 store root / namespace。
```

即可。

---

# 29. 如果想做最低成本 P1

沿用 Batch06 已冻结的：

```text
ReuseScope

TASK
SESSION
CORPUS
TRUST_DOMAIN
```

Memory Query 首先做：

```text
scope equality
```

然后再：

```text
retrieval / compatibility。
```

不要：

```text
全局搜完
再隐藏。
```

---

# 30. Prefix APC 的安全边界

Prefix reuse 当前已经绑定非常多 identity：

```text
engine
cache namespace
cache epoch

model
revision
weights

tokenizer
template

prefix layout
normalizer

source hashes
evidence pack
hydrate manifest

visibility policy

exact token identity

adapter
multimodal
rope
kv dtype
quantization
TP/PP

cache_salt_digest
```

。

从 reuse correctness 看已经相当完整。

---

# 31. Prefix 的 Privacy Boundary

真正风险不是：

```text
token identity 算错。
```

而是：

```text
两个本来不该共享 cache 的请求
进入同一个 namespace。
```

。

所以 Batch06 的决定应该在 Batch09 固化：

```text
cache salt / namespace
必须包含 ReuseScope / trust identity。
```

。

---

# 32. 推荐

```text
salt =
HMAC(
    runtime_secret,
    scope
    || trust_domain
    || policy_version
)
```

日志只记录：

```text
salt digest。
```

不记录 secret。

---

# 33. 为什么不需要全局加密 KV Cache

当前：

```text
单 host
local vLLM
trusted Runtime
```

。

引入：

```text
KV encryption
GPU memory encryption
```

对当前项目价值极低。

真正重要的是：

```text
不跨错误 scope reuse。
```

---

# 34. Explicit KV 的安全边界

当前 `EngineLocalKVHandle` 已绑定：

```text
engine id
engine generation

model id/revision
tokenizer

task
producer request

token digest

seq len
block
dtype

created / expires
status
```

。

这已经阻止大量错误复用。

---

# 35. Explicit KV 仍建议补的一个最小字段

当前 handle 主要知道：

```text
producer
```

但 consumer authority 不明显。

推荐绑定：

```text
authorized_consumer_request_id
```

或者：

```text
authorized_consumer_step_id
```

。

消费时同时验证：

```text
task
engine generation
consumer
TTL
status == READY
```

。

---

# 36. KV 生命周期

建议正式 invariant：

```text
PREPARING
   ↓
READY
   ↓
CONSUMING
   ↓
CONSUMED
   ↓
RELEASED
```

任意异常：

```text
INVALIDATED / EXPIRED。
```

已 release / consumed：

```text
不得再次 load。
```

。

---

# 37. LLM CodeAct 是当前最强的真实安全边界

这一部分可以明确肯定。

当前模型生成 Python 并不是：

```text
LLM
→ subprocess python
```

。

而是：

```text
LLM source
      ↓
GeneratedCodeCandidate
      ↓
AST / Source Policy
      ↓
CodePolicyReport
      ↓
bwrap readiness
      ↓
isolated execution
      ↓
Output Schema
      ↓
Capability Quality Validator
      ↓
Verified Artifact
```

。

---

# 38. LLM CodeAct 的 Authority Binding

`CodeGenerationRequest` 会绑定：

```text
task
step
attempt
session

approved plan
capability grant

capability

input refs
input manifest

output schema

model / prompt / runtime signature

policy
validator
authorized input schemas
```

。

Runner 执行前全部重新校验。

---

# 39. Grant 还是 One-Shot

`LlmCodeActRunner` 内部：

```text
_consumed_grant_hashes
```

。

同一 grant 第二次执行：

```text
capability_grant_already_consumed
```

。

这很重要。

---

# 40. Generated Code 不能自己扩大 Input

执行前：

```text
set(input_files)
==
set(policy.allowed_input_relpaths)
```

。

也就是说：

```text
Runtime 给什么
Code 才能看到什么。
```

。

不是：

```text
Python 想 open 什么就 open 什么。
```

。

---

# 41. Input / Output Path Policy

当前 LLM CodeAct 已明确禁止：

```text
absolute path
..
```

Input：

```text
inputs/<file>
```

Output：

```text
outputs/<file>
```

。

并要求：

```text
exact expected output file

no symlink

no extra output

JSON schema exact

output bytes bounded
```

。

这部分值得作为 Workspace 通用 path-safety 的参考实现。

---

# 42. bwrap 当前策略

LLM generated code 使用的专用路径：

```text
run_llm_bwrap()
```

而不是 generic：

```text
run()
```

。

它会：

```text
unshare PID

unshare IPC

unshare UTS

unshare NET

minimal /proc
minimal /dev

/tmp tmpfs

read-only Python runtime

read-only generated.py

read-only exact inputs

only outputs writable

minimal environment

non-root sandbox uid/gid

CPU / memory / file / fd / process limits
```

。

---

# 43. Readiness Probe 也是真实执行检查

当前不是：

```text
which bwrap
→ safe。
```

而是实际 probe：

```text
sandbox UID/GID != root

network unavailable

outside write denied

repo not visible

other task workspace not visible

output writable
```

。

这非常好。

---

# 44. Bubblewrap Claim Boundary

Bubblewrap 官方自己也强调：

```text
bubblewrap 只是构建 sandbox 的低层工具；
是否形成安全边界完全取决于传入的 namespace / bind 参数。
```

。

所以 StateBus 能 claim 的不是：

> “用了 bubblewrap，所以安全。”

而是：

> “StateBus 对 LLM-generated Python 使用独立的 fail-closed bwrap profile，并通过 readiness probe 验证网络、文件系统、身份和输出边界。”

---

# 45. 一个必须明确的 CodeAct 边界

当前 `CodeActSandboxRunner.run()` generic path 支持：

```text
auto
bwrap
resource
none
```

甚至：

```text
auto bwrap 失败
→ resource fallback。
```

。

但：

```text
run_llm_bwrap()
```

是：

```text
bwrap required
fail closed。
```

---

# 46. 所以最终规则

```text
LLM_BOUNDED_PYTHON
→ only LlmCodeActRunner
→ only run_llm_bwrap
→ no resource fallback
→ no none
```

。

Generic CodeAct：

```text
resource/none
```

只允许：

```text
Runtime-generated deterministic/trusted script。
```

。

建议加一个 unit invariant 防止未来回归。

---

# 47. CodeAct 不需要继续扩安全功能

当前不用再：

```text
加 VM
加 gVisor
加 microVM
加 seccomp DSL
加 network proxy
```

。

比赛安全边界已经足够：

```text
mandatory bwrap
+
minimal mounts
+
no network
+
nonroot
+
rlimit
+
AST policy
+
output validator。
```

---

# 48. Artifact 是“数据提交边界”

模型或者 Worker 产生：

```text
Candidate Artifact
```

并不代表：

```text
可以复用。
```

。

当前：

```text
ArtifactLifecycleManager
```

有：

```text
CANDIDATE
VERIFIED
INVALIDATED
```

。

---

# 49. CommitGate 是关键安全关口

`RuntimeCommitGate` 需要：

```text
quality floor pass
answer adopted
artifact validators pass
input validators pass
```

全部成立：

```text
Artifact
→ VERIFIED

Memory
→ COMMITTED
```

。

否则：

```text
Artifact
→ INVALIDATED

Memory
→ non-committed / failed
```

。

---

# 50. 这个边界为什么重要

因为 Memory poisoning 的最直接防线就是：

```text
未经验证 output
不能成为 replay source。
```

。

也就是：

```text
LLM Says X
≠
Memory Stores X
```

。

而是：

```text
LLM Says X
↓
Artifact
↓
Validator
↓
CommitGate
↓
Memory
```

。

---

# 51. Benchmark Gold 与 Runtime 必须完全分离

Batch08 已经发现：

```text
summary_hint
expected facts
expected metric effects
```

等 benchmark-only 信息的问题。

Batch09 安全边界最终冻结：

# **Gold is Evaluator Authority, never Runtime Input.**

---

# 52. 正确链路

```text
Public Task
      ↓
Runtime
      ↓
Output Artifact
      ↓
Runtime Settlement Complete
      ↓
Private Evaluator
      ↓
Gold Score
```

。

Evaluator Gold：

```text
不得进入：
Planner
Retriever
Executor
Summarizer
Memory
Replay
Telemetry intended for Runtime decisions
```

。

---

# 53. 最理想实现

正式实验：

```text
Runtime process
无 gold mount

Evaluator process
只读 output + gold
```

。

但如果比赛时间紧：

```text
same process
```

也至少保证：

```text
runtime API 不接受 expected_facts。
```

---

# 54. Telemetry 是当前最容易发生 Privacy Duplication 的地方

当前 `TelemetryEvent.payload`：

```text
arbitrary dict
```

会被原样写：

```text
runtime_events.jsonl

runtime_facts.jsonl
```

。

当前很多 Event 已经主要使用：

```text
hash
ID
count
```

这是好事。

但某些：

```text
decision record
audit payload
```

仍可能包含业务语义内容。

---

# 55. Batch09 不需要做完整 DLP

只增加一个简单原则：

# **Audit by Reference, not by Content**

。

比如日志优先：

```text
artifact_ref_id

state_ref_id

memory_id

payload_hash

schema version

size

decision reason
```

。

不要复制：

```text
full evidence text

full memory summary

raw model response

raw latent vector

raw token IDs

KV bytes。
```

---

# 56. Runtime Artifact 本身统一视为 Sensitive

当前目录：

```text
/statebus/runs

/statebus/work

/statebus/workspaces

runtime_root

telemetry

memory store
```

都可能包含：

```text
user task
source evidence
model outputs
memory
state metadata
```

。

所以不要逐文件猜“是不是隐私”。

统一：

# **Sensitive Experiment Artifact**

最简单。

---

# 57. 文件权限建议

正式运行根：

```text
0700
```

。

普通 sidecar：

```text
0600
```

。

需要 sandbox read：

通过：

```text
明确 bind / chmod
```

处理。

不要默认依赖：

```text
host umask。
```

---

# 58. Container 当前运行 Root

当前 Dockerfile 虽然：

```text
创建 statebus 用户
```

最终却：

```text
USER 0:0
```

。

entrypoint 也没有：

```text
drop privileges。
```

所以：

# **StateBus 主 Runtime 当前是 root container process。**

必须如实记录。

---

# 59. 这是不是比赛前 P0

不是。

原因：

当前 LLM CodeAct 的正式 bwrap 路径：

```text
root Runtime
→ enter bwrap
→ setpriv nobody
```

是当前 openEuler/container 环境的已适配机制。

如果现在贸然把整个 Runtime 改成 non-root：

```text
可能破坏 nested user namespace / bwrap readiness。
```

。

---

# 60. 当前最合理的 Deployment Security Claim

> StateBus Runtime container 是可信执行域；不把模型生成代码直接运行在该 root 域中，而是通过 mandatory non-root bubblewrap sandbox 执行。

同时确保：

```text
不 mount docker.sock

不 mount host /

不 mount SSH key

不 mount cloud credential

业务 volumes 最小化

vLLM endpoint 只在可信 host/network
```

。

---

# 61. Runtime Non-root 可以作为 P1

如果后续验证：

```text
openEuler
Docker seccomp
user namespace
bwrap
```

组合在 non-root 下工作稳定，

再把 entrypoint：

```text
privileged init
→ exec statebus user
```

。

不是 Batch09 exit gate。

---

# 62. Host Network 的边界

Batch07 deployment 使用：

```text
host network
```

是为了：

```text
本地 vLLM / deployment convenience。
```

。

这意味着：

```text
容器网络隔离不是安全边界。
```

因此：

```text
StateBus API
vLLM metrics/API
```

都应该只对：

```text
trusted host / private environment
```

开放。

---

# 63. 整体安全链：从 Request 到 Final Output

下面是 Batch01–09 的最终链路。

```text
┌────────────────────────────────────┐
│ 1. User Request / Public Sources   │
│            UNTRUSTED DATA          │
└─────────────────┬──────────────────┘
                  │
                  ▼
┌────────────────────────────────────┐
│ 2. TaskCompiler / Admission        │
│ CanonicalTaskSpec                  │
│ AdaptiveTaskEnvelope               │
└─────────────────┬──────────────────┘
                  │
                  ▼
┌────────────────────────────────────┐
│ 3. Planner                         │
│ PlanProposal                       │
│         UNTRUSTED PROPOSAL         │
└─────────────────┬──────────────────┘
                  │
                  ▼
┌────────────────────────────────────┐
│ 4. PlanPolicy                      │
│ capability / risk / refs / budget  │
│ output / memory / graph            │
└─────────────────┬──────────────────┘
                  │
                  ▼
             ApprovedPlan
                  │
                  ▼
┌────────────────────────────────────┐
│ 5. ExecutionBindingPolicy          │
│ logical capability → provider      │
└─────────────────┬──────────────────┘
                  │
                  ▼
┌────────────────────────────────────┐
│ 6. Ready / Admission / Scheduler   │
│ only orders already-authorized     │
│ work; cannot expand authority      │
└─────────────────┬──────────────────┘
                  │
                  ▼
┌────────────────────────────────────┐
│ 7. CapabilityGrant                 │
│ task/session/step/attempt           │
│ capability/input refs/output/TTL   │
└──────────────┬─────────────────────┘
               │
          ┌────┴─────────────────────┐
          │                          │
          ▼                          ▼
┌──────────────────────┐   ┌────────────────────────┐
│ Trusted Worker       │   │ LLM CodeAct            │
│ semantic/logit/etc.  │   │ UNTRUSTED CODE         │
│ bounded by Grant     │   │ AST → bwrap → validate │
└──────────┬───────────┘   └────────────┬───────────┘
           │                            │
           └────────────┬───────────────┘
                        ▼
┌────────────────────────────────────┐
│ 8. Candidate Artifact              │
│ hash / manifest / provenance       │
└─────────────────┬──────────────────┘
                  ▼
┌────────────────────────────────────┐
│ 9. Validator / CommitGate          │
│ schema / recompute / provenance    │
│ completion criteria                │
└─────────────────┬──────────────────┘
                  ▼
             Verified Artifact
                  │
          ┌───────┴──────────┐
          ▼                  ▼
       Final Output        Memory Commit
                             │
                             ▼
                    Future Query Candidate
                             │
                             ▼
                    Compatibility / Policy
                             │
                             ▼
                          Consume
```

---

# 64. Retrieval / Evidence 在链路中的安全地位

Retriever 的结果：

```text
Evidence
```

只应该影响：

```text
what model reasons about。
```

不能直接影响：

```text
what model is authorized to do。
```

。

这是非常重要的 separation：

```text
Evidence Plane
≠
Authority Plane
```

。

---

# 65. State 在链路中的安全地位

Semantic / Logit / Latent State：

```text
是 data / decision state。
```

它们可以影响：

```text
selection
retry
evidence
model input。
```

不能：

```text
自己创建 capability
自己扩大 input refs
绕过 validator。
```

---

# 66. Memory 在链路中的安全地位

Memory Candidate：

```text
是 historical data candidate。
```

它必须经过：

```text
Compatibility
Policy
Consumption
```

才能影响当前执行。

Replay 更进一步要求：

```text
verified artifact
runtime compatibility
lineage
contract
validator
replay ready。
```

---

# 67. Scheduler 在安全链中的地位

Batch07 的 Scheduler：

```text
选择哪个 Ready Step 先跑。
```

它不应该改变：

```text
Capability
Input refs
Output contract
Risk class
Memory policy
```

。

因此安全 invariant：

# **Scheduling changes order, never authority.**

---

# 68. Batch07 生命周期问题与安全关系

当前 Adaptive Runtime 的：

```text
ACK
RUN_START
```

仍由 Controller synthetic transition。

因此现在：

```text
STEP_ACKED
STEP_RUNNING
```

不能作为：

```text
Worker authenticity proof。
```

。

Batch07 已冻结：

```text
real WorkerEvent
→ RuntimeSupervisor
```

。

Batch09 不重新设计。

只记录：

> Worker lifecycle evidence 与 authorization 是两件事；Grant 决定能做什么，真实 ACK/Heartbeat 证明 Worker 是否真的进入对应生命周期。

---

# 69. Late Result / Attempt Fencing

安全上必须满足：

```text
Attempt A failed / timeout
↓
Attempt B started
↓
Attempt A late result
↓
IGNORE / AUDIT
```

不能：

```text
覆盖 Attempt B。
```

。

Batch07 已计划：

```text
attempt_id
worker_generation
active_attempt_by_step
```

作为唯一接收依据。

---

# 70. GC 也是安全边界的一部分

敏感 state / temp data：

```text
不应该永久残留。
```

Attempt terminal：

```text
COMPLETED
FAILED
TRAPPED
CANCELLED
```

进入：

```text
GC_PENDING
```

最终：

```text
GC_DONE。
```

需要释放：

```text
Shared Memory

memfd

mmap temp

KV handle

workspace temp

worker reservation

grant / lease state
```

。

---

# 71. Threat Matrix

| Threat | 当前防线 | Batch09 判断 |
|---|---|---|
| Planner hallucinated capability | Envelope + Registry + PlanPolicy | 已覆盖 |
| Prompt injection requests dangerous tool | Authority allowlist/risk gate | 已覆盖；string detector 仅辅助 |
| Model-generated Python reads host | mandatory LLM bwrap | 已覆盖 |
| Generated Python network access | `--unshare-net` + readiness probe | 已覆盖 |
| Generated Python writes extra files | exact output mount + validator | 已覆盖 |
| Grant reused | LlmCodeAct one-shot hash set | 已覆盖 |
| Wrong attempt result | grant hash / attempt check | 当前有；Batch07 再强化 late fencing |
| Invalid Artifact enters replay | CommitGate + Memory compatibility | 已覆盖 |
| Similar but incompatible Memory reused | compatibility decision | 已覆盖 |
| Cross-domain Memory leak | no first-class tenant scope | 不支持多租户；P1 namespace |
| State ref path traversal | Controller-generated today | **P0 harden path** |
| Workspace path traversal | implicit trusted IDs | **P0 harden path** |
| Oversize UDS frame | no max frame size | **P0 add bound** |
| Malicious same-UID process reads SHM | not protected strongly | Out of current trust model |
| Telemetry duplicates content | possible | **P1 minimize content** |
| Benchmark Gold leaks to Agent | Batch08 audit | **P0 experiment boundary** |
| APC cross-scope reuse | cache namespace/salt exists | enforce trust scope |
| KV stale engine reuse | engine generation identity | covered |
| Host root compromise | none | Out of Scope |

---

# 72. Privacy Classification

不做复杂数据分类系统。

项目里只需要三档。

---

## P0 — Public / Structural

```text
schema version
policy version
capability ID
metric names
event types
counts
timings
hashes
```

可以进入 telemetry。

---

## P1 — Sensitive Runtime Metadata

```text
task ID
source doc hash
artifact ID
memory ID
state ID
provider binding
```

允许审计保存，但不对外公开原始目录。

---

## P2 — Content / Model State

```text
user request

evidence text

memory summary/content

LLM prompt / output

embedding vector

logit vector

latent hidden

KV

artifact payload
```

尽量：

```text
只存真实 object
日志记录 digest/ref。
```

---

# 73. Retention Boundary

比赛不需要实现 retention service。

只要求：

```text
Run结束
↓
transient state teardown

实验 artifact
↓
按 run root 保存

需要提交的 evidence
↓
单独 export
```

。

不要：

```text
长期保留所有 SHM/KV/temp。
```

---

# 74. Batch09 P0 修改清单

真正建议比赛前落实的安全修改只有以下几个。

---

## S0 — Safe Path Primitive

涉及：

```text
WorkspaceManager
LayeredStateStore
```

新增：

```text
safe_component()
safe_relative_path()
```

。

---

## S1 — Control Frame Bound

`control/transport.py`

新增：

```text
MAX_CONTROL_FRAME_BYTES
```

。

---

## S2 — Secure Socket / Runtime Roots

确保：

```text
UDS dir 0700
socket 0600

runtime/workspace/state root 0700
```

。

---

## S3 — CodeAct Security Invariant Tests

测试：

```text
LLM_BOUNDED_PYTHON
never generic sandbox fallback

network denied

repo denied

other task denied

only output writable

grant reuse denied
```

。

现有 readiness 已覆盖多数，只需要把 contract freeze。

---

## S4 — Evaluator Isolation

这是 Batch08/09 共用。

正式 benchmark：

```text
Gold not Runtime-visible。
```

。

---

## S5 — Cache / Memory Scope Freeze

至少 metadata 明确：

```text
trust_domain / corpus scope。
```

。

不需要多租户系统。

---

# 75. Batch09 P1

有时间再做：

```text
StateRef consumer binding

Memory first-class security_scope

SO_PEERCRED persistent worker verification

AuditPayloadPolicy

Runtime non-root deployment
```

。

这些不是比赛主链 blocker。

---

# 76. 不做的东西

Batch09 明确不做：

```text
OAuth

RBAC admin system

KMS

Vault

certificate authority

mTLS

remote worker PKI

multi-tenant isolation

encrypted vector DB

encrypted GPU KV

TEE

confidential computing

microVM

gVisor

Kubernetes NetworkPolicy

SIEM

DLP platform
```

。

这些会让项目继续膨胀，和赛题没有关系。

---

# 77. 最终 Security Claim

项目最终安全描述建议：

> StateBus 将模型输出视为不可信 proposal/data，而不是执行权限。Controller 通过 Task Envelope、PlanPolicy、Capability Registry 与 step/attempt scoped CapabilityGrant 限制 Agent 的操作范围；非文本 State 与 Memory 通过 Ref、hash、schema、compatibility 和 consumption receipt 管理，未经验证的 Artifact 不允许进入 Replay。LLM-generated Python 仅在 fail-closed bubblewrap sandbox 中执行，网络与非授权文件系统不可见，并在返回后经过 schema 和 capability-level quality validation。当前部署的安全边界是单机单信任域的 openEuler Runtime，不宣称 hostile-host 或多租户零信任隔离。

这已经足够。

---

# 78. 最终 Privacy Claim

> StateBus 的隐私边界建立在单一可信 Runtime 域上。业务内容、Embedding、Logit、Latent、KV、Memory 和 Artifact 均视为敏感运行时数据；跨组件主要通过 Ref/hash 传递，Telemetry 优先记录身份、digest、状态和计数，而不是复制原始内容。跨任务复用仅应发生在显式 Reuse/Trust Scope 内，Benchmark Gold 独立于 Runtime 决策链。

---

# 79. Batch09 Exit Gate

Batch09 可以在满足以下条件后关闭：

```text
[ ] Trust Model 写清楚

[ ] Runtime Controller = Authority Root

[ ] Model output = untrusted proposal/data

[ ] PlanPolicy / CapabilityGrant authority chain 固定

[ ] LLM CodeAct mandatory bwrap fail-closed

[ ] Generic CodeAct 与 LLM CodeAct 安全边界区分

[ ] Workspace / State path containment 修复计划冻结

[ ] UDS frame size bound 修复计划冻结

[ ] Memory/Prefix/KV scope 写清楚

[ ] Gold evaluator boundary 与 Batch08 对齐

[ ] Telemetry content-minimization rule 写清楚

[ ] Host root / multi-tenant / hostile same-UID 明确 Out of Scope

[ ] Batch07 attempt fencing / GC 作为生命周期安全依赖

[ ] 不引入新的安全子系统
```

。

---

# 80. Batch01–09 最终整体链路

经过前九批后，StateBus 的最终主链可以压缩成：

```text
User Request
    ↓
TaskCompiler
    ↓
CanonicalTaskSpec
    ↓
AdaptiveTaskEnvelope
    ↓
Planner
    ↓
PlanProposal
    ↓
PlanPolicy
    ↓
ApprovedPlan
    ↓
DependencyResolver
    ↓
READY
    ↓
Admission
    ↓
ReadyStepScheduler
    ↓
ExecutionBindingPolicy
    ↓
CapabilityGrant
    ↓
┌────────────────────────────────────────────┐
│ Runtime Data / Execution Plane             │
│                                            │
│ Retrieval                                  │
│   ↓                                        │
│ EvidencePack                               │
│   ↓                                        │
│ Semantic / Logit / Latent State            │
│   ↓                                        │
│ StatePlacementPolicy                       │
│                                            │
│ MemoryQuery                                │
│   ↓                                        │
│ Candidate → Compatibility → Consumption    │
│                                            │
│ InferenceReusePolicy                       │
│   ├─ Recompute                             │
│   ├─ APC                                   │
│   └─ Explicit KV                           │
│                                            │
│ Trusted Worker / LLM CodeAct Sandbox       │
└─────────────────────┬──────────────────────┘
                      ↓
Candidate Artifact
                      ↓
Capability Validator
                      ↓
CommitGate
                      ↓
Verified Artifact
            ┌─────────┴─────────┐
            ↓                   ↓
        Final Output        Memory Commit
                                ↓
                            Future Reuse
```

旁路：

```text
RuntimeSupervisor
Attempt Ledger
Heartbeat / Timeout
Retry / Rebind / Replan
GC
Telemetry
```

共同保证：

```text
authority
lifecycle
evidence
```

三条链闭合。

---

# 81. 最终架构的三个“真相源”

为了避免未来再混淆，建议最终 Architecture Reconciliation 使用三个 Truth Plane：

---

## Authority Truth

```text
Envelope

Capability Registry

ApprovedPlan

Provider Binding

CapabilityGrant
```

回答：

> 谁被允许做什么？

---

## Data Truth

```text
EvidencePack

StateRef

MemoryRef

ArtifactRef

KV Handle
```

回答：

> 当前计算到底在消费什么？

---

## Execution Truth

```text
Attempt

Worker Event

Validator

CommitGate

GC

Telemetry
```

回答：

> 实际发生了什么？

---

# 82. 这三个 Plane 是整个项目最值得保留的抽象

如果最终答辩只需要解释 StateBus 为什么不是普通 Agent Workflow：

可以说：

```text
传统 Agent Framework
通常：
Model Output
→ Tool

StateBus：
Model Proposal
→ Authority
→ Ref-bound Data
→ Attempt-bound Execution
→ Verified Commit
```

。

这比列：

```text
Protobuf / SHM / Memory / KV / CodeAct
```

更能解释整个项目的系统设计。

---

# 83. Batch09 Final Freeze

安全最终冻结如下：

```text
StateBus Security
不是：
“让 LLM 可信”

而是：
“让不可信 LLM 只能在受控 Authority/Data/Execution 边界里工作。”
```

当前项目的合理安全边界：

```text
Trusted:
StateBus Controller / Policy / Validator
local host/runtime domain

Untrusted:
LLM output
generated code
retrieved content
unverified memory/artifacts

Out of Scope:
host root compromise
hostile hypervisor
multi-tenant zero trust
remote worker internet security
advanced GPU side channel
```

比赛前只做：

```text
path safety
frame bound
scope freeze
sandbox invariant
gold isolation
audit minimization
```

到这里安全设计就应该停止。

---

# 84. Final Conclusion

Batch09 的结论不是：

```text
StateBus 需要再增加一套 Security Architecture。
```

恰恰相反。

当前 Batch01–08 已经自然形成了一套合理安全结构：

```text
PlanPolicy
CapabilityGrant
Ref / Hash
Memory Compatibility
Artifact CommitGate
CodeAct Sandbox
Attempt Lifecycle
Evaluator Isolation
```

真正需要做的是：

```text
把这些边界明确写出来，
修几个 implementation seam，
然后停止扩张。
```

最终 StateBus 可以被准确描述为：

> **一个 single-trust-domain、controller-authorized 的 multi-agent runtime。LLM、检索内容和生成代码均被视为不可信输入；执行权限由 Controller 通过 plan policy 与 attempt-scoped grants 管理；State、Memory、Artifact 与 KV 以 Ref/identity/compatibility 管理；生成代码在独立 fail-closed sandbox 中运行；只有验证通过的 Artifact 可以提交或复用。**

这已经足够支撑当前比赛、项目展示和后续 Final Architecture Reconciliation。

---

# Appendix A — Current Source Truth Map

```text
statebus/contracts/adaptive.py
    AdaptiveTaskEnvelope
    ApprovedPlan
    CapabilityGrant
    StateConsumptionRecord
    CapabilityQualityReport

statebus/runtime/plan_policy.py
    PlanPolicyValidator

statebus/runtime/adaptive_runtime.py
    grant issue
    dispatch
    grant-result binding
    fallback regrant
    replan validation

statebus/contracts/llm_codeact.py
    CodeGenerationPolicy
    CodeGenerationRequest
    CodeExecutionRecord

statebus/runtime/llm_codeact.py
    one-shot grant
    source audit
    mandatory bwrap
    output validation
    quality validation

statebus/runtime/codeact_sandbox.py
    bwrap readiness
    namespaces
    mounts
    resource limits

statebus/state/store.py
    SHM / memfd / mmap / inline
    materialization lifecycle

statebus/memory/models.py
    MemoryQuery / Ref / Consumption

statebus/memory/store.py
    hybrid retrieval
    compatibility policy

statebus/contracts/prefix.py
    exact prefix identity
    cache namespace / salt digest
    visibility identity

statebus/contracts/engine_local_kv.py
    engine-local KV handle / proof

statebus/runtime/workspace.py
    Artifact candidate / verified / invalidated

statebus/runtime/commit_gate.py
    Verified Artifact → Memory Commit

statebus/runtime/telemetry.py
    Runtime event / fact logs

statebus/control/transport.py
    UDS control transport

docker/Dockerfile
docker/entrypoint.sh
    openEuler deployment / root Runtime
```

---

# Appendix B — External Security Principles Used

仅作为边界校验，不引入外部安全系统。

## OWASP LLM06:2025 — Excessive Agency

与 StateBus 最相关的核心原则：

```text
least functionality
least privilege
bounded autonomy
```

StateBus 当前：

```text
Capability Registry
Envelope
PlanPolicy
Grant
```

已经在这个方向上。

---

## Bubblewrap upstream

关键原则：

```text
bubblewrap 是低层 sandbox constructor，
安全性取决于实际 namespace / bind / privilege 参数。
```

StateBus 因此必须验证：

```text
实际 bwrap profile
```

而不能只验证：

```text
binary exists。
```

当前 readiness probe 的设计是正确的。

---

# Appendix C — Security Fix Priority

| Priority | Item | 是否比赛前必须 |
|---|---|---|
| P0 | Workspace/State path containment | 是 |
| P0 | UDS max frame size | 是 |
| P0 | Gold isolation | 是，与 Batch08 同步 |
| P0 | LLM CodeAct bwrap invariant | 是 |
| P0 | Trust scope/claim boundary 文档 | 是 |
| P1 | StateRef consumer binding | 推荐 |
| P1 | Memory first-class trust scope | 推荐 |
| P1 | Telemetry payload minimization | 推荐 |
| P1 | SO_PEERCRED persistent worker | Batch07 persistent worker 后 |
| P1 | non-root Runtime | 有环境验证再做 |
| NO | OAuth/RBAC/KMS/mTLS/TEE | 不做 |
