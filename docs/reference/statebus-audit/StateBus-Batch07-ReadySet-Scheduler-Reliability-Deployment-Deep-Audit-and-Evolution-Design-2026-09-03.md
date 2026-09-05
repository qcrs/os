# StateBus Batch 07 — READY SET / Scheduler / Reliability / Deployment 全链源码审计与演进设计

> **项目**：StateBus / `qcrs/os`  
> **主仓库**：`https://github.com/qcrs/os`  
> **历史参考仓库**：`https://github.com/qcrs/os1`  
> **源码审计基线**：`qcrs/os:master`，与 Batch 01–06 使用的主线基线一致  
> **日期**：2026-09-03  
> **Batch 定位**：Batch 06 `Inference Reuse` 之后的 **Runtime Execution Plane** 审计  
> **范围**：
>
> ```text
> ApprovedPlan / RuntimeSession
>         ↓
> Dependency Resolution
>         ↓
> READY SET
>         ↓
> Admission / Scheduling
>         ↓
> Attempt / Grant
>         ↓
> Dispatcher / Worker / Provider
>         ↓
> ACK / RUN_START / HEARTBEAT / RESULT
>         ↓
> Retry / Rebind / Replan / Cancel
>         ↓
> Resource Ownership / GC
>         ↓
> Telemetry / Runtime Facts
>         ↓
> Persistent Service / openEuler Deployment
> ```
>
> **本轮明确不重新展开**：
>
> - Task Admission / Planner / Replan 语义正确性；
> - Evidence / Provenance / Artifact Truth；
> - Protocol / Capability / Provider Binding；
> - APC / Prefix / Explicit KV 机制本身；
> - Latent Hidden 重构；
> - External Benchmark 最终证据口径；
> - Security / Privacy 最终横向审计。
>
> 这些分别属于 Batch 01–06、08、09。
>
> 本文的任务是回答：
>
> # **StateBus 现在是否已经是一个真正的 Runtime Scheduler / Reliable Runtime？如果不是，缺在哪些 seam？应该怎样在不把项目膨胀成 Kubernetes / Ray / 分布式 Serving 的前提下补齐？**

---

# 0. Executive Summary

先给最终判断。

当前 StateBus **不是没有 Runtime**。

它已经拥有：

```text
ApprovedPlan DAG
CapabilityGrant
RuntimeTaskSession
StepAttemptRecord
RuntimeSupervisor
typed UDS / Protobuf worker protocol
ACK / RUN_START / HEARTBEAT / RESULT schema
failure / fallback / replan
state / artifact / memory lifecycle
telemetry
Docker + openEuler 24.03-LTS-SP3
host vLLM service management
continuous-task benchmark harness
```

因此它已经超过：

```text
for role in roles:
    call_llm()
```

这种简单 Agent orchestration。

但当前更准确的定位仍然是：

# **Bounded Sequential DAG Executor + Mechanism Harness**

而不是：

# **Event-Driven, Resource-Aware, Recoverable Runtime Scheduler**

最核心的差距有四类：

---

## 0.1 第一类：`READY SET` 目前并没有真正 Scheduler

当前 `AdaptiveRuntimeEngine`：

```python
ready = [
    step
    for step in remaining
    if set(step.depends_on) <= completed
]

for step in sorted(ready, key=lambda item: item.step_id):
    ...
    dispatch(step)
```

因此当前真实策略基本是：

```text
dependency-ready
+
step_id lexical order
+
serial execution
```

它不看：

```text
wait age
critical path
downstream fan-out
provider health
provider concurrency
resource pressure
state-store budget
sandbox capacity
InferenceReuseHint
PrefixResidencyHint
estimated runtime
deadline
fairness
```

所以：

> `READY SET` 现在只是一个集合，不是 Runtime Scheduling Plane。

---

## 0.2 第二类：Lifecycle Model 是真的，但 Adaptive Mainline 的事件不是 Worker 驱动

这是本 Batch 最重要的 P0。

`RuntimeSupervisor` 设计了：

```text
PENDING
→ DISPATCHED
→ ACKED
→ RUNNING
→ COMPLETED / FAILED / TRAPPED / CANCELLED
→ GC_PENDING
→ GC_DONE
```

并且已经有：

```text
ack timeout
heartbeat lease timeout
```

模型。

真实 `subprocess_worker` 也会发送：

```text
AckReceived
RunStart
Heartbeat
SuccessResult / ErrorResult
```

但是 `AdaptiveRuntimeEngine._dispatch_lifecycle()` 当前在真正调用 Dispatcher **之前**，由 Controller 自己直接执行：

```python
supervisor.dispatch(step_id)

supervisor.ack(step_id)

supervisor.run_start(step_id)

# 然后才真正：
dispatcher.dispatch(...)
```

也就是说：

```text
STEP_ACKED
STEP_RUNNING
```

在 Adaptive Mainline 中目前表达的是：

```text
Controller 决定“假定 Worker 已经 ack / running”
```

而不是：

```text
真实 Worker 发来了 ACK / RUN_START
```

。

这会直接影响：

```text
timeout truth
heartbeat truth
crash detection
late result fencing
worker health
retry correctness
```

。

---

## 0.3 第三类：当前低风险 State Worker 仍是 one-request-one-process

当前 Semantic State 正式 Adaptive 路径：

```text
Retriever
↓
publish DenseSemanticState
↓
AdaptiveDispatcher
↓
new SubprocessExecutorTransport(...)
↓
subprocess.Popen(
    python -m statebus.control.subprocess_worker
)
↓
UDS
↓
semantic_select_v1
↓
worker exits
```

而且：

```text
每一个 retrieval bundle
都可以启动一次新的 Python subprocess
```

。

这意味着当前所谓：

```text
SHM / memfd 低开销
```

的 payload data path 是低开销的，

但：

```text
Process creation
Python startup
module import
UDS setup
process teardown
```

仍然可能远大于一次：

```text
shared-memory resolve + cosine top-k
```

。

因此 Round 01 里提出的：

# `PersistentWorkerBroker`

到了 Batch 07 已经不应该再只是文档建议。

它应该成为 Runtime Execution Plane 的正式 Target。

---

## 0.4 第四类：部署是真 openEuler，但还偏 Development / Experiment Service

当前：

```text
docker/Dockerfile
FROM hub.oepkgs.net/openeuler/openeuler:24.03-lts-sp3
```

所以：

# openEuler requirement 是真实满足的，不是 README claim。

当前还已有：

```text
Docker Compose
host-network
1 GiB SHM
host vLLM
health probe script
PID ownership check
runtime/log/cache/work mounts
```

。

但目前仍缺：

```text
container HEALTHCHECK
restart policy
runtime readiness/liveness
system-level worker watchdog
runtime graceful drain
persistent session recovery
resource limits
automatic orphan cleanup
service unit / restart semantics
```

。

所以部署当前更准确是：

# **Reproducible openEuler Development Deployment**

而不是：

# **Self-Healing Production Runtime**

比赛不要求做 Kubernetes。

正确方向是：

```text
Docker/openEuler
+
systemd / healthcheck
+
RuntimeCoordinator
+
persistent worker
+
bounded resources
+
continuous-task stability evidence
```

。

---

# 1. Batch 06 → Batch 07 的严格边界

Batch 06 已冻结：

```text
InferenceReusePolicy
只决定：

RECOMPUTE
APC
ENGINE_LOCAL_CONTINUATION
```

并输出：

```text
InferenceReuseHint
PrefixResidencyHint
ReuseCostObservation
```

。

Batch 07 才回答：

# **多个 READY step 到底谁先执行？**

因此最终关系应为：

```text
             Batch 06

InferenceInvocation
      ↓
InferenceReusePolicy
      ↓
InferenceReuseHint
PrefixResidencyHint
ReuseCostObservation

================================

             Batch 07

ApprovedPlan DAG
      ↓
DependencyResolver
      ↓
READY SET
      +
InferenceReuseHint
Provider Facts
Resource Facts
Attempt Age
Critical Path
      ↓
ReadyStepScheduler
      ↓
DispatchPermit
```

不要再把：

```text
cache mechanism
```

和：

```text
runtime scheduling
```

揉在一起。

---

# 2. 本轮源码审计地图

本轮主要阅读：

```text
statebus/runtime/
    adaptive_runtime.py
    adaptive_mainline.py
    adaptive_dispatcher.py
    supervisor.py
    session.py
    telemetry.py

statebus/control/
    transport.py
    subprocess_worker.py
    messages.py
    schema.py

statebus/state/
    store.py
    semantic_state.py
    logit_state.py

statebus/benchmark/
    continuous_runner.py
    kv_prefix_schedule.py

deploy/
    activate_statebus_host.sh
    activate_statebus_local_vllm_profile.sh
    vllm.env.example

docker/
    Dockerfile
    compose.yaml
    README.md

scripts/vllm/
    manage_qwen3_32b.sh
```

以及此前已经审过的：

```text
statebus/runtime/neural_state.py
statebus/runtime/prefix_feedback.py
statebus/integrations/vllm_kv/*
```

本轮只消费它们输出的 Runtime Facts，不重新设计 APC/KV。

---

# 3. 当前真实 Adaptive Runtime 主链

当前主链可以还原成：

```text
AdaptiveMainlineRunner
        │
        ├─ create LayeredStateStore
        ├─ create MemoryIndexStore
        ├─ create WorkspaceManager
        │
        ▼
ApprovedPlan
        │
        ▼
AdaptiveRuntimeEngine.run()
        │
        ▼
RuntimeSessionManager.start()
        │
        ▼
attach_workflow()
        │
        ▼
while pending steps:
        │
        ├─ remaining
        │
        ├─ ready
        │
        └─ sorted(ready, step_id)
                  │
                  ▼
            issue CapabilityGrant
                  │
                  ▼
         _dispatch_lifecycle()
                  │
          ┌───────┼────────┐
          ▼       ▼        ▼
      DISPATCH   ACK     RUN_START
      [local]   [local]    [local]
                  │
                  ▼
        AdaptiveDispatcher.dispatch()
                  │
                  ├─ Retrieval Adapter
                  ├─ Transform DSL
                  ├─ Bounded Python
                  └─ Runtime Builtin
                  │
                  ▼
           AdaptiveStepResult
                  │
          ┌───────┴────────┐
          ▼                ▼
       success           failure
          │                │
          ▼                ├─ fallback
       complete            ├─ replan
          │                └─ terminal fail
          ▼
     produced refs
          │
          ▼
     downstream ready
```

这条链：

```text
authority
dependency
grant
result binding
replan
```

都已经有。

缺的是：

```text
真实调度
真实 worker lifecycle
真实 resource admission
真实 recovery
```

。

---

# 4. 当前 READY SET 的语义其实已经不错

这里不要把现有实现全推翻。

当前：

```python
set(step.depends_on) <= completed
```

作为 READY 条件是合理的机械基础。

而且：

```text
failed dependency
```

最后会让：

```text
downstream CANCELLED
dependency_not_completed
```

。

这说明 StateBus 已经有：

# Dependency Authority

应该保留。

---

# 5. 但 READY ≠ Eligible ≠ Admitted ≠ Scheduled

这是 Batch 07 最需要补的概念。

当前只有：

```text
PENDING
READY
DISPATCH
```

之间的隐式逻辑。

目标应拆成：

```text
Dependency Ready
        ↓
Eligibility
        ↓
Admission
        ↓
Scheduling
        ↓
Dispatch
```

分别回答：

---

## 5.1 Dependency Ready

```text
所有 hard dependencies completed
```

。

---

## 5.2 Eligibility

```text
input refs available
provider binding still valid
provider supports required contract
grant budget available
risk policy allows
```

。

---

## 5.3 Admission

```text
当前资源是否允许启动？
```

例如：

```text
persistent worker slot
sandbox slot
LLM inflight slot
shared memory budget
CPU subprocess budget
provider concurrency budget
```

。

---

## 5.4 Scheduling

在所有：

```text
ready + eligible + admissible
```

的 step 中：

```text
谁先执行？
```

。

---

# 6. 推荐新增 `ReadyStepCandidate`

```python
@dataclass(frozen=True)
class ReadyStepCandidate:
    task_id: str
    session_id: str

    step_id: str
    attempt_index: int

    capability_id: str
    provider_binding_id: str

    ready_since_ns: int

    downstream_fanout: int
    remaining_critical_path_ms: float

    expected_service_ms: float

    inference_reuse_hint: InferenceReuseHint | None

    required_resources: ResourceDemand

    admission_state: str
```

注意：

```text
它不是 Planner object。
```

它完全由 Runtime 从：

```text
ApprovedPlan
+
Runtime Facts
```

派生。

---

# 7. 当前 Runtime 是“单 Task Runtime”，这是 Scheduling 的重要边界

当前：

```text
AdaptiveRuntimeEngine.run(request)
```

一次只处理：

```text
一个 task
一个 RuntimeTaskSession
```

而且：

```text
RuntimeSessionManager()
RuntimeSupervisor()
```

都是在这一次 `run()` 内创建。

所以当前一个 Scheduler 即使加进去，也最多看到：

```text
一个 DAG 内的 READY steps
```

。

它看不到：

```text
Task A ready step
Task B ready step
Task C ready step
```

。

---

# 8. 为什么这对 Agentic Scheduling 很关键

外部工作近两年越来越一致地指出：

```text
Agentic Serving
不能只把每次 LLM call 当独立 request
```

。

---

## 8.1 Agentix

NSDI 2026 的 Agentix：

```text
把 Program 作为 first-class scheduling object
```

重点不是单次 LLM request latency，

而是：

```text
整个 Agent Program 的累计等待
和 end-to-end latency
```

。

StateBus 已经天然有：

```text
Canonical Task
ApprovedPlan
RuntimeSession
DAG
```

所以其实非常适合走这条路。

---

## 8.2 TOPAS

TOPAS 直接基于：

```text
workflow longest remaining service path
+
near-term prefix reuse
+
cache movement / preemption cost
+
task aging
```

联合调度。

这与 StateBus：

```text
ApprovedPlan DAG
+
Batch06 Reuse Hint
```

非常契合。

---

## 8.3 KVFlow

KVFlow 用：

```text
Agent Step Graph
steps-to-execution
```

预测某个 Agent KV：

```text
距离下一次使用还有多远
```

。

说明：

```text
DAG future-use
```

本身就是极有价值的 Runtime signal。

---

## 8.4 Continuum

Continuum 进一步把：

```text
tool-call gap
+
program continuity
```

纳入：

```text
KV TTL
+
program scheduling
```

。

---

# 9. StateBus 最适合的最终 Scheduling Object

建议不是：

```text
Request
```

也不是：

```text
Role
```

。

而是：

# `(RuntimeTaskSession, ReadyStepAttempt)`

即：

```python
SchedulingKey(
    session_id,
    task_id,
    step_id,
    attempt_id,
)
```

。

这样：

```text
Program-level context
+
Step-level execution
```

可以同时保留。

---

# 10. 推荐两层 Runtime 结构

目标：

```text
RuntimeCoordinator                ← global / long-lived
    │
    ├─ SessionRegistry
    ├─ GlobalReadyQueue
    ├─ ProviderHealthIndex
    ├─ ResourceLedger
    ├─ WorkerBroker
    ├─ RuntimeJournal
    └─ Scheduler
         │
         ├──────── Task A Session
         │           ├ step A1
         │           └ step A2
         │
         ├──────── Task B Session
         │           ├ step B1
         │           └ step B2
         │
         └──────── Task C Session
```

每个 Task 内仍有：

```text
ApprovedPlan DAG
RuntimeTaskSession
Artifact / State ownership
```

。

---

# 11. 为什么需要 `RuntimeCoordinator`

不是为了做分布式系统。

而是解决当前 5 个现实问题：

```text
1. Persistent workers 不能每 task 重建

2. Provider health 应跨 task 保存

3. Global resource budget 应跨 task 生效

4. continuous task scheduling 才能真正进入 runtime

5. crash / recovery 需要长期 runtime owner
```

。

---

# 12. V1 不需要立刻并行

这是非常重要的 scope control。

可以先：

```python
max_concurrent_tasks = 1
max_parallel_steps_per_task = 1
```

但所有执行都经过：

```text
RuntimeCoordinator
→ ReadyStepScheduler
→ DispatchPermit
```

。

这样：

```text
行为基本不变
```

但 architecture seam 建立了。

之后再：

```text
1 → 2 → N
```

逐步放开并行。

---

# 13. 当前 Scheduler V0：Lexical Sequential

当前：

```text
ready set
↓
sort step_id
↓
同步 dispatch
```

优势：

```text
deterministic
简单
易调试
```

。

缺点：

```text
不知道哪个 step 更关键
不知道哪个 step cache 更热
不知道谁等太久
不知道谁资源不足
不会并行
```

。

应该保留成：

# `FCFS_SAFE / DETERMINISTIC_BASELINE`

而不是删除。

---

# 14. 不建议第一版直接上 Weighted Score

看起来很自然：

\[
score =
w_1 CP +
w_2 Reuse +
w_3 Age -
w_4 Cost
\]

但第一版不建议。

原因：

```text
权重如何解释？
不同 workload 怎么调？
比赛数据量能否支撑 tuning？
是不是 benchmark-specific？
```

很容易重新变成：

```text
为了实验调参数
```

。

---

# 15. 推荐 `WorkflowAwareV1` 使用 Lexicographic Policy

第一版建议：

```text
Hard Filter
    ↓
Starvation Override
    ↓
Critical Path
    ↓
Reuse Benefit
    ↓
Provider / Resource Locality
    ↓
Stable FCFS Tie-break
```

。

---

# 16. 第 0 层：Hard Eligibility

任何 ranking 前必须先过滤：

```text
dependency complete

input refs available

plan authority valid

provider binding valid

provider health != unavailable

attempt budget available

required resource budget available

no terminal dependency failure
```

。

这非常重要：

# Eligibility 永远不能被 Score 覆盖。

---

# 17. 第 1 层：Starvation Override

如果：

```text
ready_wait_ms >= starvation_threshold_ms
```

则进入：

```text
aged_ready
```

优先。

为什么必须第一版就做？

因为 SGLang 2026 的 LPM 实际 issue 已经给出非常直接的生产案例：

```text
纯 prefix locality
+
持续 hot request 到达
→ cold request 可长期被压在队尾
```

。

该 issue 报告：

```text
median TTFT 很好
但 cold miss 请求形成 20–60s tail
```

。

所以：

# Cache-aware scheduler 如果没有 aging，设计是不完整的。

---

# 18. 第 2 层：Critical Path

对于 DAG：

```python
CP(step) =
    estimated_service(step)
    +
    max(CP(child))
```

叶子：

```text
CP = estimated_service
```

。

READY step：

```text
remaining critical path 越长
→ 越优先
```

。

这不是为了理论漂亮。

它直接对应：

```text
哪个 step 如果继续等，
最可能拖慢整个 Task JCT
```

。

---

# 19. `estimated_service_ms` 第一版如何来

不要模型预测。

先做：

```text
static default
+
observed EWMA
```

。

Key：

```text
capability_id
provider_id
execution_kind
coarse input-size bucket
```

。

例如：

```python
RuntimeCostKey(
    capability_id="retrieve_semantic_evidence_v1",
    provider_id="local",
    input_bucket="medium",
)
```

。

---

# 20. 为什么不能用 benchmark gold 预测成本

同样遵守前面 Benchmark Boundary：

```text
Runtime scheduler
只能看 runtime-visible facts
```

不能：

```text
看 future ground truth
看 grader
看 expected answer complexity
```

。

---

# 21. 第 3 层：Reuse Benefit

Batch 06 输出：

```text
InferenceReuseHint
```

包含：

```text
known residency
expected saved prefill tokens
expected saved ms
reuse scope
```

。

第一版只分：

```text
KNOWN_RESIDENT + meaningful benefit

UNKNOWN

KNOWN_ABSENT
```

。

不要为了 scheduler 再自己猜 vLLM cache。

---

# 22. 为什么不能 `reuse > critical path`

因为这会导致：

```text
热 prefix request
永远压过 workflow bottleneck
```

。

TOPAS 的核心动机恰恰是：

```text
只优化 immediate prefix locality
会拉长 task JCT
```

。

所以 StateBus V1：

```text
aging
critical path
```

应高于：

```text
cache locality
```

。

---

# 23. 第 4 层：Resource / Provider Locality

例如：

```text
semantic worker 已空闲
→ semantic-select 可执行

CodeAct sandbox slot 满
→ CodeAct 仍 READY
但不是 ADMISSIBLE

vLLM provider degraded
→ 暂不 dispatch
```

。

这不是 replan。

只是：

# resource wait

。

---

# 24. 推荐新增 `WAITING_RESOURCE`

当前主要：

```text
PENDING
DISPATCHED
RUNNING
...
```

。

建议 Runtime 内部至少有 scheduling state：

```text
BLOCKED_DEPENDENCY
READY
WAITING_RESOURCE
DISPATCHED
```

。

它不一定要进入已有 `StepLifecycleState` enum 第一版。

也可以单独：

```text
SchedulingState
```

避免污染 execution lifecycle。

---

# 25. 为什么 Resource Wait 不应该直接失败

现在如果某个 provider 暂时没有资源：

```text
立即 fail
→ replan
```

会把：

```text
暂时不可调度
```

错误提升成：

```text
semantic execution failure
```

。

正确：

```text
READY
↓
not admitted
↓
WAITING_RESOURCE
↓
resource changed
↓
READY again
```

。

---

# 26. Scheduler 自身也要有 Overhead Budget

SGLang 当前实现有一个很值得借的工程细节：

```text
LPM 在 waiting queue 很大时
自动退回 FCFS
```

原因：

```text
prefix match + sorting 本身会变成 scheduler overhead
```

。

StateBus 也应该：

```text
scheduler decision
不能比 step 本身还复杂
```

。

建议：

```python
scheduler_budget_ms = small constant
```

超过：

```text
fallback DETERMINISTIC_FCFS
```

。

---

# 27. `ScheduleDecisionReceipt`

每次选择必须能解释：

```python
@dataclass(frozen=True)
class ScheduleDecisionReceipt:
    decision_id: str

    candidate_ids: tuple[str, ...]
    chosen_candidate_id: str

    starvation_override: bool

    chosen_critical_path_ms: float
    chosen_wait_age_ms: float

    reuse_status: str
    expected_saved_ms: float

    admission_snapshot_hash: str

    policy_version: str
    fallback_used: bool
```

。

这样 Batch 08 才能证明：

```text
Scheduler 真改变了执行顺序
```

。

---

# 28. 当前最大的 Reliability Bug：Supervisor keyed by `step_id`

当前：

```python
RuntimeSupervisor.steps: dict[str, StepRuntimeRecord]
```

。

`register()`：

```python
self.steps[step_id] = record
```

。

如果：

```text
step A attempt 1
↓
retry
↓
step A attempt 2
```

第二次：

```text
覆盖 attempt 1 supervisor record
```

。

---

# 29. 为什么这在并行 / retry 以后会非常危险

可能发生：

```text
Attempt 1 timeout
↓
Attempt 2 已启动
↓
Attempt 1 晚到 RESULT
```

如果 Supervisor 只按：

```text
step_id
```

找当前 record，

就可能把：

```text
旧 attempt 的结果
```

错误作用到：

```text
新 attempt
```

。

---

# 30. 好消息：Session Ledger 已经是 attempt-aware

`StepAttemptRecord` 已经有：

```text
task_id
step_id
attempt_id
worker_id
timestamps
resource handles
...
```

。

所以正确修法不是新造第三套 Ledger。

应该：

# `StepAttemptRecord` 成为 canonical attempt truth

而 `RuntimeSupervisor` 变成：

```text
active attempt event reducer
```

。

---

# 31. 推荐 Supervisor identity

改成：

```python
attempts: dict[str, StepRuntimeRecord]
active_attempt_by_step: dict[str, str]
```

或者：

```python
dict[(step_id, attempt_id), StepRuntimeRecord]
```

。

任何 Event：

```text
ACK
HEARTBEAT
RESULT
TRAP
```

必须同时匹配：

```text
task_id
step_id
attempt_id
```

。

---

# 32. Late Result Fencing

核心规则：

```text
attempt_id != active_attempt_by_step[step_id]
→ LATE_RESULT
→ audit
→ ignore
```

。

不能：

```text
覆盖新 attempt 状态
```

。

这在：

```text
timeout
retry
provider rebind
worker restart
```

后都很关键。

---

# 33. Controller 当前 synthetic ACK / RUN_START 必须删除

当前：

```text
Controller dispatch
↓
Controller 自己 ack
↓
Controller 自己 run_start
↓
真实执行
```

应该改成：

```text
Controller
↓
ATTEMPT_DISPATCHED

Worker / Provider
↓
ACK_RECV
↓
ATTEMPT_ACKED

Worker
↓
RUN_START
↓
ATTEMPT_RUNNING
```

。

---

# 34. 推荐 `WorkerEvent`

```python
class WorkerEventType:
    ACK
    RUN_START
    HEARTBEAT
    RESULT_SUCCESS
    RESULT_ERROR
    TRAP
    DISCONNECTED
```

统一：

```python
WorkerEvent(
    task_id,
    step_id,
    attempt_id,
    worker_id,
    event_type,
    payload,
)
```

。

---

# 35. `RuntimeSupervisor.apply_event()`

目标：

```text
WorkerEvent
↓
verify attempt identity
↓
verify legal transition
↓
update Attempt Ledger
↓
emit Runtime Fact
```

。

不要再：

```text
Controller 手工调用 ack()
```

。

---

# 36. Timeout 必须从“Result 字段”变成 Runtime Timer

当前 `AdaptiveStepResult` 有：

```text
timed_out
```

。

这只是：

```text
下游告诉 Runtime：
“我超时了”
```

。

真正 Runtime timeout 应是：

```text
Dispatcher 已发
↓
deadline 到
↓
Supervisor 主动判断
↓
Cancel / Trap
```

。

---

# 37. 现有 `RuntimeSupervisor` 已经有正确 primitive

已有：

```text
trap_if_ack_timed_out()

trap_if_lease_expired()
```

。

问题不是算法缺失。

问题是：

# 没进入 Adaptive Mainline event loop。

---

# 38. ACK Timeout

```text
DISPATCHED
↓
ack_timeout_ms
↓
仍无真实 ACK
↓
TRAPPED: ack_timeout
```

然后：

```text
terminate / fence worker
↓
release resources
↓
retry / rebind / fail
```

。

---

# 39. Heartbeat Lease

```text
ACKED / RUNNING
↓
periodic HEARTBEAT
↓
lease_timeout
↓
TRAPPED: heartbeat_timeout
```

。

当前真实 `subprocess_worker` 只：

```text
启动时发送一次 Heartbeat
```

。

它不是长期 lease protocol。

---

# 40. Persistent Worker 后必须变成真实周期 heartbeat

例如：

```text
Broker worker:
每 2s heartbeat
```

payload：

```text
worker_id
generation
pid
active_attempt_id
queue_depth
rss
```

。

Runtime：

```text
last_heartbeat
```

驱动 provider health。

---

# 41. 不要对所有 Execution Provider 使用同一种 Worker

建议分三类。

---

## 41.1 Trusted Persistent Worker

适合：

```text
semantic selection
logit gate
deterministic state projection
bounded read-only helper
```

特点：

```text
persistent process
typed UDS
multiple requests
periodic heartbeat
bounded queue
no arbitrary model code
```

。

---

## 41.2 In-Process Trusted Provider

例如：

```text
Transform DSL
simple builtin
certain retrieval adapters
```

不必为了：

```text
“所有东西都跨进程”
```

强制加 subprocess。

---

## 41.3 Ephemeral Isolated Worker

继续用于：

```text
LLM CodeAct
untrusted generated Python
```

。

这一类：

# 不要 persistent。

因为：

```text
隔离优先于 process startup overhead
```

。

---

# 42. `PersistentWorkerBroker`

推荐：

```text
RuntimeCoordinator
       │
       ▼
PersistentWorkerBroker
       │
       ├── semantic-worker-0
       │       UDS persistent session
       │
       ├── semantic-worker-1
       │
       └── decision-worker-0
```

。

第一版甚至：

```text
每种 trusted worker = 1
```

就够了。

---

# 43. 为什么这个优化比换 IPC 协议更重要

当前一次 semantic operation：

```text
Popen
Python startup
imports
UDS server
connect
Protobuf
state resolve
cosine
result
process exit
```

真正 payload operation 只是最后几步。

所以先优化：

```text
process lifetime
```

比：

```text
Protobuf → Cap'n Proto
UDS → shared ring
Python → C++
```

更有意义。

---

# 44. PersistentWorker Protocol

建议：

```text
HELLO / CAPABILITIES
       ↓
READY

REQ_EXEC
       ↓
ACK
       ↓
RUN_START
       ↓
HEARTBEAT*
       ↓
RESULT

REQ_EXEC
       ↓
...
```

Worker 不退出。

---

# 45. Worker Generation

每次 Worker 启动分配：

```text
worker_generation
```

。

Event 必须绑定：

```text
worker_id
worker_generation
```

。

这样：

```text
旧 worker 重启前的迟到事件
```

可直接 fence。

---

# 46. Worker Health

建议：

```python
class WorkerHealth:
    READY
    BUSY
    DEGRADED
    UNAVAILABLE
    RESTARTING
```

。

Runtime 不要：

```text
每次 dispatch 才发现 subprocess 起不来
```

。

---

# 47. Provider Health 也应该一等化

Batch 05 已经拆了：

```text
Logical Capability
≠
Execution Provider
```

。

Batch 07 正好补：

```text
Provider Runtime Facts
```

。

例如：

```python
ProviderRuntimeStatus(
    provider_id,
    generation,
    health,
    inflight,
    queue_depth,
    recent_failure_rate,
    updated_at_ns,
)
```

。

---

# 48. Retry / Rebind / Replan 必须最终分清

正确：

---

## Retry

```text
同一个 provider
同一个 logical step
新 attempt
```

例如：

```text
temporary transport timeout
```

。

---

## Rebind

```text
同一个 logical step
换 execution provider
新 grant
```

例如：

```text
DSL provider unavailable
→ bounded Python provider
```

前提：

```text
Batch 05 provider equivalence
```

成立。

---

## Replan

```text
logical DAG / capability semantic 发生变化
```

。

例如：

```text
当前 logical capability 无法完成任务
```

。

---

# 49. 当前 hard-coded fallback 应逐步收回 Binding Plane

当前 AdaptiveRuntime 对：

```text
LLM_BOUNDED_PYTHON
```

有 deterministic fallback 路径。

未来应该统一成：

```text
ProviderBindingPolicy
```

而不是：

```text
RuntimeEngine 对某个 execution kind 特判
```

。

---

# 50. Retry Classification

建议建立：

```text
TRANSIENT_TRANSPORT
PROVIDER_UNAVAILABLE
RESOURCE_EXHAUSTED
TIMEOUT
CONTRACT_INVALID
VALIDATION_FAILED
AUTHORITY_VIOLATION
SECURITY_FAILURE
```

。

推荐：

| 类型 | 默认动作 |
|---|---|
| transient transport | retry |
| provider unavailable | rebind / wait |
| resource exhausted | wait / rebind |
| timeout | bounded retry / rebind |
| contract invalid | fail / replan |
| validation failed | bounded repair / replan |
| authority violation | fail closed |
| security failure | fail closed |

---

# 51. Current Resource Model 还不够 Scheduling

当前真正有的资源 budget 比较分散：

```text
LayeredStateStore:
SHM budget

CodeAct:
RLIMIT / sandbox limits

Explicit KV:
registry bytes / entries

vLLM:
自身 GPU token/KV scheduler

Adaptive Runtime:
attempt budget
```

但没有：

# `Runtime Resource Ledger`

。

---

# 52. 推荐 `ResourceDemand`

```python
@dataclass(frozen=True)
class ResourceDemand:
    trusted_worker_slots: int = 0
    sandbox_slots: int = 0

    provider_inflight_slots: int = 0

    expected_state_bytes: int = 0

    cpu_weight: int = 0
```

不要：

```text
Scheduler 自己管理 GPU token budget
```

。

GPU 内部：

# 继续交给 vLLM Scheduler。

---

# 53. `ResourceLedger`

```python
@dataclass
class RuntimeResourceLedger:
    max_inflight_attempts: int

    max_trusted_workers: int
    max_sandbox_workers: int

    max_llm_inflight: int

    shared_memory_budget_bytes: int
```

维护：

```text
reserved
active
released
```

。

---

# 54. Admission 必须是 Reservation

正确：

```text
scheduler chooses
↓
reserve resources
↓
create DispatchPermit
↓
dispatch
```

如果 dispatch 失败：

```text
rollback reservation
```

。

不要：

```text
先启动进程
再发现资源不足
```

。

---

# 55. `DispatchPermit`

```python
@dataclass(frozen=True)
class DispatchPermit:
    permit_id: str

    task_id: str
    step_id: str
    attempt_id: str

    provider_id: str

    resource_reservation_id: str

    expires_at_ns: int
```

。

它与：

```text
CapabilityGrant
```

不同。

---

# 56. CapabilityGrant 与 DispatchPermit 边界

```text
CapabilityGrant
=
我允许你做什么

DispatchPermit
=
现在资源允许你运行
```

。

这两个不要混。

---

# 57. 当前 Data Plane 不能直接安全开启并行

这是非常重要的现实约束。

当前 `LayeredStateStore`：

```text
materializations: dict
_shared_segments: dict
_memfd_fds: dict
shared_memory_bytes_used
```

没有锁。

而且：

```python
release():
    self.materializations.pop(ref_id)
```

不是 idempotent。

因此：

```text
直接把 ready steps asyncio.gather()
```

是错误路线。

---

# 58. 并行化前的 Gate

至少先做到：

```text
StateStore thread-safe

release idempotent

duplicate ref reject/idempotent

resource accounting atomic

artifact lifecycle owner-safe

attempt-scoped resource ownership
```

。

否则：

```text
并发越多
bug 越难复现
```

。

---

# 59. 第一版并行应该只开放给 Safe Class

可以：

```text
independent
read-only
no shared mutable output
```

的 step。

例如：

```text
两个独立 retrieval/read-only projections
```

。

但：

```text
CodeAct
memory commit
artifact promotion
shared state mutation
```

先保持串行。

---

# 60. 推荐 `ConcurrencyClass`

```text
SERIAL_ONLY

PARALLEL_READ_ONLY

PARALLEL_PROVIDER_BOUND
```

由 Runtime / Provider Descriptor 决定。

Planner 不决定。

---

# 61. Runtime Invariant Checker

这是从 SGLang 最值得直接借的一类机制。

SGLang 当前有独立：

```text
SchedulerInvariantChecker
```

检查：

```text
available
+
evictable
+
protected
+
session-held
+
uncached
=
total
```

并进一步检查：

```text
double free
use-after-free
KV page ownership
```

。

StateBus 也应该建立自己的：

# `RuntimeInvariantChecker`

。

---

# 62. StateBus 的 Runtime Invariants

至少：

```text
I1
每个 active attempt
只有一个 active provider binding

I2
每个 active attempt
最多一个 valid DispatchPermit

I3
terminal attempt
不能继续持有 ephemeral resource reservation

I4
同一个 resource handle
必须有明确 owner

I5
released state
不能仍被 active attempt 引用

I6
active worker assignment
必须绑定同 attempt_id + generation

I7
resource used <= budget

I8
COMPLETED step
输出 Ref 必须存在并满足 contract

I9
GC_DONE attempt
ephemeral handles = 0

I10
一个 step 同时最多一个 active attempt
除非未来明确 hedge
```

。

---

# 63. 为什么 Invariant 比高级 Scheduler 更优先

如果：

```text
scheduler 很聪明
```

但：

```text
retry 覆盖 attempt
state leak
worker late result
resource accounting drift
```

那系统越复杂越不可信。

所以 Batch 07 优先级：

```text
Truth
→ Isolation
→ Resource Bound
→ Scheduling Optimization
```

。

---

# 64. GC 当前模型有，但 Mainline 没真正闭环

`RuntimeSupervisor` 已有：

```text
GC_PENDING
GC_DONE
```

。

Telemetry 也有：

```text
GC_ISSUED
```

。

但当前 AdaptiveRuntime 主循环主要处理：

```text
complete/fail/trap
```

没有形成：

```text
terminal attempt
↓
explicit GC
↓
resource release proof
↓
GC_DONE
```

的正式闭环。

---

# 65. 推荐 `AttemptResourceManifest`

每个 attempt：

```python
AttemptResourceManifest(
    attempt_id,

    state_ref_ids,
    temp_artifact_ids,
    workspace_dirs,
    memfd_handles,
    shm_handles,
    worker_assignment,
    provider_request_ids,
)
```

。

---

# 66. Terminal 后进入 GC

```text
COMPLETED / FAILED / TRAPPED / CANCELLED
        ↓
GC_PENDING
        ↓
release transient resources
        ↓
verify ownership empty
        ↓
GC_DONE
```

。

注意：

```text
Committed Artifact
Persistent Memory
```

不应该被 GC。

---

# 67. GC 必须 Idempotent

因为：

```text
normal completion
timeout path
process crash
service restart
```

都可能重复触发 cleanup。

所以：

```text
release if exists
```

而不是：

```text
pop or crash
```

。

---

# 68. Runtime Session 目前是内存态

`RuntimeSessionManager` 当前：

```python
sessions: dict[str, RuntimeTaskSession]
```

。

每次：

```text
start
update
replace
```

只存在 Python memory。

因此：

```text
Runtime process crash
```

之后：

```text
current attempt
ready set
resource ownership
replan history
```

不能自动恢复。

---

# 69. Telemetry JSONL 不能直接当 Recovery Store

当前：

```text
runtime_events.jsonl
runtime_facts.jsonl
```

很好用于：

```text
audit
metrics
debug
```

。

但它不是一个完整：

```text
transactional runtime state store
```

。

原因包括：

```text
事件可能没 flush
同一 transition 多文件
resource side effect 与 log 不原子
recovery projection 未定义
```

。

---

# 70. 推荐把 Telemetry 与 Runtime Journal 分开

```text
Telemetry
=
observability

Runtime Journal
=
recovery authority
```

。

---

# 71. Runtime Journal 第一版不用复杂分布式 DB

选择：

```text
SQLite WAL
```

其实非常适合。

原因：

```text
单节点
已有 sqlite dependency
transaction
crash recovery
query方便
实现量可控
```

。

不需要：

```text
etcd
Redis
Raft
Postgres
```

。

---

# 72. 建议 Runtime Journal 记录什么

最小：

```text
sessions
steps
attempts
provider bindings
resource reservations
terminal result commitments
```

。

不必把：

```text
所有 telemetry
```

塞进去。

---

# 73. Restart Recovery

Runtime 重启：

```text
load non-terminal sessions
↓
all previously RUNNING attempts
标记 LOST / ORPHANED
↓
fence old worker generation
↓
reconcile resources
↓
GC orphan
↓
重新计算 ready set
↓
按 policy retry / rebind / fail
```

。

---

# 74. 为什么不直接“恢复旧 Python 调用”

不可靠。

Runtime restart 后：

```text
旧 call 到底执行到哪里？
artifact 写了一半吗？
provider 还在生成吗？
```

很难证明。

第一版更安全：

```text
in-flight attempt
→ lost
→ reconcile
→ fresh attempt
```

。

已 commit 的 artifact：

```text
保持
```

。

---

# 75. Provider / Engine Fault 参考 vLLM 的正确思路

现代 vLLM 已经把：

```text
engine health
```

作为独立状态：

```text
HEALTHY
UNHEALTHY
DEAD
```

。

Fault 时：

```text
abort running requests
clear queued state
push health status
recovery 后再 resume
```

。

StateBus 不应该复制 vLLM 内部 fault tolerance。

但可以借：

# **Provider failure 与 Step semantic failure 分层。**

---

# 76. 推荐 Provider Health State

```text
HEALTHY
DEGRADED
UNAVAILABLE
RECOVERING
DEAD
```

。

如果：

```text
vLLM service down
```

不是：

```text
Summarizer 语义失败
```

。

它是：

# provider failure。

---

# 77. Cancellation 当前也没有真正 E2E

Control protocol 有：

```text
CMD_CANCEL
```

模型。

但正式 Adaptive Dispatcher 并没有统一：

```text
Runtime cancel
→ worker/provider cancel
→ terminal confirmation
```

。

---

# 78. Target Cancel Flow

```text
lease / user / dependency cancellation
↓
CANCEL_REQUESTED
↓
send provider-specific cancel
↓
fence attempt
↓
CANCELLED
↓
GC
```

。

如果 provider 无法 cancel：

```text
fence attempt
```

也必须保证：

```text
late result 不会被 adopt
```

。

---

# 79. Scheduler 与 vLLM Scheduler 的边界

非常重要。

StateBus 不应该调：

```text
每轮多少 token
哪个 decode request
chunked prefill token budget
KV block allocation
continuous batching
```

。

这些继续由：

# vLLM Scheduler

负责。

StateBus 调的是：

```text
哪个 Agent / Capability Step
何时提交到 provider
```

。

---

# 80. 两层 Scheduler

```text
StateBus Workflow Scheduler
        │
        │ submit LLM calls
        ▼
vLLM Request Scheduler
        │
        ▼
GPU execution
```

。

这样不会重复造 vLLM。

---

# 81. SGLang 可以借什么

SGLang 当前 scheduler 已有：

```text
FCFS
LPM
DFS_WEIGHT
priority
routing-key
in-batch prefix awareness
```

。

我们不需要复制。

最值得借三点：

```text
1.
Cache locality 是调度信号，不是唯一目标

2.
Scheduler overhead 也必须受控

3.
Resource / memory invariant checker
必须独立存在
```

。

---

# 82. TOPAS 可以借什么

借：

```text
critical path
reuse locality
aging
```

。

不借：

```text
第一版 joint KV retention optimizer
```

。

因为：

```text
StateBus 不应控制 vLLM physical BlockPool
```

。

---

# 83. KVFlow 可以借什么

借：

```text
steps-to-execution / next-use distance
```

未来作为：

```text
reuse hint
```

。

不做：

```text
CPU↔GPU async prefetch
```

。

---

# 84. Continuum 可以借什么

借：

```text
tool gap / execution gap
```

作为未来：

```text
residency hint
```

。

第一版不训练 duration predictor。

可以先：

```text
observed EWMA by capability/provider
```

。

---

# 85. SMetric 可以借什么

SMetric 发现 agent serving：

```text
session 内 KV locality
```

非常高。

它强调：

```text
session-centric
```

调度。

StateBus 本身已有：

```text
RuntimeTaskSession
```

所以：

# 不需要另外发明 Session abstraction。

只需要真正让 Session 进入 Scheduler。

---

# 86. JITServe / FastServe 为什么不是当前重点

JITServe：

```text
SLO goodput
```

FastServe：

```text
token-level preemptive GPU scheduling
```

都很强。

但那是：

```text
LLM serving inner scheduler
```

领域。

StateBus 当前不应该进入：

```text
token-level preemption
GPU iteration scheduler
```

。

只借：

```text
deadline / SLO 是可选 Runtime signal
```

即可。

---

# 87. 推荐最终 Scheduler V1

```text
Policy:
WORKFLOW_AWARE_V1
```

执行：

```text
1. Dependency filter

2. Contract / Provider eligibility

3. Resource admission

4. Aging override

5. Remaining critical path descending

6. Known reuse benefit descending

7. Ready timestamp ascending

8. Stable task_id / step_id tie-break
```

。

---

# 88. 简化伪代码

```python
def choose(candidates, facts):

    eligible = [
        c for c in candidates
        if dependency_ready(c)
        and authority_valid(c)
        and provider_eligible(c)
        and inputs_available(c)
        and attempt_budget_ok(c)
    ]

    admissible = [
        c for c in eligible
        if resource_ledger.can_reserve(c.resource_demand)
    ]

    aged = [
        c for c in admissible
        if c.wait_age_ms >= starvation_threshold_ms
    ]

    pool = aged or admissible

    return min(
        pool,
        key=lambda c: (
            -c.remaining_critical_path_ms,
            -c.reuse_expected_saved_ms,
            c.ready_since_ns,
            c.task_id,
            c.step_id,
        )
    )
```

。

---

# 89. 为什么 Age 用 Threshold Override

比：

```text
age × weight
```

更容易解释：

```text
没有饿死请求
```

。

同时不会：

```text
刚等 20ms
就因为 age 微小变化
打乱 cache locality
```

。

---

# 90. Critical Path 只有估计值，怎么办

不要假装准确。

`ScheduleDecisionReceipt` 记录：

```text
estimate source
confidence
```

。

没有数据：

```text
use static class default
```

。

随着实际执行：

```text
EWMA calibration
```

。

---

# 91. `RuntimeCostModel`

建议非常轻：

```python
key = (
    capability_id,
    provider_id,
    input_size_bucket,
)
```

保存：

```text
count
ewma_service_ms
p50-ish rolling
last_updated
```

。

无需 ML。

---

# 92. Current Continuous Runner 的问题

`continuous_runner.py` 当前已经可以：

```text
按 continuous family
顺序跑多轮
维护 prior round context
Memory history
KV prefix schedule plan
feedback
```

。

这是很好的实验 harness。

但它仍属于：

# Benchmark-owned scheduling

而不是：

# Runtime-owned scheduling。

---

# 93. Batch 07 后应迁移的职责

Benchmark 可以继续决定：

```text
测试 workload
arrival pattern
baseline mode
```

但不应该自己：

```text
重排 Runtime execution
```

。

正确：

```text
Benchmark submits tasks
↓
RuntimeCoordinator schedules
↓
Benchmark observes decisions
```

。

---

# 94. 为什么这很重要

否则最后可能出现：

```text
“StateBus Scheduler 提升了”
```

但真实：

```text
是 benchmark runner
提前把 task 排好了
```

。

Batch 08 会很难做 claim closure。

---

# 95. Deployment 当前做对了什么

当前已经：

```text
Dockerfile:
openEuler 24.03 LTS SP3

Compose:
init=true
host network
shm=1g
persistent host volumes

vLLM:
host process
pinned environment
health endpoint
PID ownership

StateBus:
separate app container
CPU embedding
host vLLM
```

。

这是好的。

---

# 96. 不需要换 Kubernetes

比赛要求：

```text
openEuler
```

不是：

```text
必须 Kubernetes
```

。

引入 K8s 会新增：

```text
deployment yaml
service discovery
storage class
GPU operator
liveness semantics
network
```

没有必要。

---

# 97. 推荐最终部署形态

```text
openEuler Host
│
├─ systemd
│    ├─ statebus-vllm.service
│    └─ docker.service
│
├─ vLLM
│    └─ GPU
│
└─ StateBus Container
     │
     ├─ RuntimeCoordinator
     ├─ PersistentWorkerBroker
     ├─ Memory Store
     ├─ State Store
     └─ Studio/API
```

。

---

# 98. 为什么 vLLM 建议 systemd 化

当前：

```text
nohup
PID file
health loop
```

已经比：

```text
手动 python -m vllm
```

强很多。

但 systemd 可以天然提供：

```text
Restart=on-failure
StartLimit
TimeoutStopSec
journal
dependency
resource control
```

。

而且 openEuler 官方文档本身就是：

```text
systemctl
```

标准服务管理路线。

---

# 99. 不要让 sysmonitor 与 systemd 重复自愈

openEuler `sysmonitor` 很适合：

```text
系统异常监控
日志
关键进程检测
```

。

官方文档也提示：

```text
恢复命令与 systemd 自身恢复机制
不要冲突
```

。

所以建议：

```text
systemd:
服务 restart authority

sysmonitor:
monitor / alert / diagnostics
```

。

---

# 100. Container Healthcheck

当前 Compose 没有正式：

```text
healthcheck
```

。

openEuler 官方容器文档支持 Docker：

```text
HEALTHCHECK
```

。

建议增加：

```text
/statebus/health/live
/statebus/health/ready
```

。

---

# 101. Liveness 与 Readiness 要分开

## Liveness

```text
event loop alive
journal writable
broker heartbeat thread alive
```

。

## Readiness

```text
RuntimeCoordinator initialized
Memory store loaded
Worker broker healthy
required provider available
resource ledger sane
```

。

---

# 102. Provider 不健康时 Runtime 是否应该“不健康”

看 deployment mode。

如果：

```text
必须 local vLLM
```

则：

```text
ready=false
```

。

如果：

```text
有 external API fallback
```

则：

```text
degraded=true
ready=true
```

。

---

# 103. Graceful Shutdown

当前不应该：

```text
docker stop
↓
立刻杀所有东西
```

。

目标：

```text
STOP_ADMISSION
↓
drain / bounded cancel inflight
↓
fence attempts
↓
GC ephemeral resources
↓
flush runtime journal
↓
flush telemetry
↓
stop workers
↓
exit
```

。

---

# 104. Container 当前以 root 运行

Dockerfile 虽然创建了：

```text
statebus user
```

但最终：

```dockerfile
USER 0:0
```

。

这属于：

```text
Batch 09 Security
```

的重点。

Batch 07 这里只记录：

```text
当前 deployment fact
```

不在本轮大改权限模型。

---

# 105. Resource Limits

Compose 最终建议至少明确：

```text
pids
memory
shm
nofile
```

以及 Runtime 自己：

```text
max workers
max inflight
max sandbox
state bytes
```

。

OS limit 与 application limit 两层都要有。

---

# 106. Telemetry 当前优点

当前 `TelemetryEmitter`：

```text
event / fact 分流
trace/task/step/attempt identity
JSONL append
task metric summary
write overhead measurement
```

这已经不错。

---

# 107. Telemetry 当前问题

## 107.1 flush_interval 默认 1

大量 Runtime event：

```text
每次 emit
可能 flush
```

在高频 scheduler/heartbeat 后：

```text
I/O overhead
```

会明显放大。

---

## 107.2 span 字段目前没有真正使用

虽然 contract 有：

```text
span_id
parent_span_id
```

但普通 `TelemetryEvent.create()` 并没有形成真正 trace hierarchy。

---

## 107.3 Telemetry 不能代替 Runtime Recovery Ledger

前面已经说明。

---

# 108. 推荐 Telemetry 分级

```text
Critical Runtime Fact
    → Runtime Journal
    → durable

Observability Event
    → buffered JSONL

High-frequency Metric
    → aggregation / periodic snapshot
```

例如：

```text
HEARTBEAT
```

不应：

```text
每 2s × workers
全部 fsync
```

。

---

# 109. 推荐新增关键 Scheduling Metrics

```text
ready_queue_depth

ready_wait_ms

resource_wait_ms

scheduler_decision_ms

scheduler_fallback_count

starvation_override_count

critical_path_selected_count

reuse_preferred_count

admission_blocked_count

provider_unavailable_count

active_attempt_count

persistent_worker_reuse_count

worker_restart_count

late_result_rejected_count
```

。

---

# 110. Reliability Metrics

```text
ack_timeout_count

lease_timeout_count

worker_disconnect_count

retry_count

rebind_count

replan_count

cancel_count

orphan_attempt_count

gc_pending_count

gc_done_count

resource_leak_detected_count

invariant_violation_count
```

。

---

# 111. Deployment / Stability Metrics

连续任务：

```text
rss_start / rss_end

fd_start / fd_end

thread_start / thread_end

process_spawn_count

shm_live_bytes

memfd_live_count

workspace_temp_bytes

worker_restart_count
```

。

---

# 112. P0 问题总表

| P0 | 当前问题 | 影响 |
|---|---|---|
| P0-1 | READY set 只是 `step_id` 排序 | 没有 Scheduler |
| P0-2 | AdaptiveRuntime synthetic ACK/RUN_START | lifecycle telemetry 不是真 worker truth |
| P0-3 | Supervisor keyed by `step_id` | retry / late result identity 风险 |
| P0-4 | ack/lease timeout primitive 未接 event loop | timeout 模型未真实生效 |
| P0-5 | semantic state 每 bundle 新 Popen | process startup 吞噬 IPC 收益 |
| P0-6 | no persistent WorkerBroker | worker health / resource admission 无统一 owner |
| P0-7 | no Runtime Resource Ledger | 无法安全并发 |
| P0-8 | LayeredStateStore 非并发安全且 release 非幂等 | 不能直接开启 parallel ready steps |
| P0-9 | terminal attempt 未显式走 GC_PENDING→GC_DONE | resource truth 不闭环 |
| P0-10 | Runtime session in-memory only | crash recovery 不成立 |
| P0-11 | benchmark 自己做 cross-task prefix scheduling | runtime claim 边界不干净 |
| P0-12 | deployment 无正式 Runtime health/restart/drain | 连续运行可靠性不足 |

---

# 113. P1 问题总表

```text
P1-1
没有 critical path estimate

P1-2
没有 ready_since / age

P1-3
没有 WAITING_RESOURCE

P1-4
provider health 不进入 Scheduler

P1-5
Batch06 reuse hint 不进入 Scheduler

P1-6
provider retry / rebind 尚未统一

P1-7
cancel command 没有 E2E propagation

P1-8
没有 worker generation fencing

P1-9
Telemetry 高频 flush

P1-10
没有 runtime invariant checker

P1-11
vLLM host management 仍是 nohup/PID 文件

P1-12
Docker 无 health/restart/resource control
```

。

---

# 114. P2 / DEFER

当前明确不做：

```text
DEFER:
Kubernetes

DEFER:
Ray

DEFER:
multi-node StateBus scheduler

DEFER:
distributed consensus

DEFER:
token-level GPU scheduler

DEFER:
vLLM internal scheduler fork

DEFER:
learned scheduling model

DEFER:
RL scheduler

DEFER:
TOPAS 全量 KV retention optimizer

DEFER:
KVFlow CPU/GPU prefetch system

DEFER:
SMetric multi-instance router

DEFER:
JITServe SLO optimizer

DEFER:
FastServe token preemption
```

。

---

# 115. Target Architecture

```text
                       RuntimeCoordinator
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
 SessionRegistry       ProviderHealthIndex     ResourceLedger
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
                      DependencyResolver
                              │
                              ▼
                          READY SET
                              │
                     RuntimeFactSnapshot
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
 Critical Path         Batch06 Reuse Hint        Wait Age
                              │
                              ▼
                       AdmissionController
                              │
                              ▼
                       ReadyStepScheduler
                              │
                              ▼
                        DispatchPermit
                              │
                              ▼
                 Provider Binding / Rebinding
                              │
                  ┌───────────┼────────────┐
                  │           │            │
                  ▼           ▼            ▼
            Trusted      vLLM/API      CodeAct
          WorkerBroker   Provider      Sandbox
                  │           │            │
                  └───────────┼────────────┘
                              │
                              ▼
                  Worker / Provider Events
                              │
      ACK → RUN_START → HEARTBEAT → RESULT / TRAP
                              │
                              ▼
                       RuntimeSupervisor
                              │
                              ▼
                       Attempt Ledger
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
           Verification                  Failure
              Commit            Retry/Rebind/Replan
                 │                         │
                 └────────────┬────────────┘
                              ▼
                         GC Manager
                              │
                              ▼
                     RuntimeInvariantCheck
                              │
                              ▼
                   Runtime Journal + Telemetry
```

---

# 116. Implementation Migration — 不直接“大重构”

建议按 Slice 推。

---

## S0 — Freeze Current Baseline

目的：

```text
当前 lexical sequential execution
保留为 baseline
```

新增测试冻结：

```text
same plan
same deterministic order
same outputs
```

。

---

## S1 — ReadyStepScheduler Seam

新增：

```text
DependencyResolver
ReadyStepCandidate
ReadyStepScheduler
ScheduleDecisionReceipt
```

第一版：

```text
scheduler = DETERMINISTIC_FCFS
max_parallel = 1
```

输出必须与当前一致。

Gate：

```text
行为不变
```

。

---

## S2 — Attempt Identity Fix

先改：

```text
Supervisor keyed by attempt
```

加入：

```text
late result fencing
```

。

在这一步之前：

# 不开 retry concurrency。

---

## S3 — Real Worker-Driven Lifecycle

去掉：

```text
Controller synthetic ACK / RUN_START
```

让：

```text
transport/provider event
```

驱动 Supervisor。

先接现有 subprocess transport。

---

## S4 — Lease Monitor

把：

```text
ack timeout
heartbeat timeout
```

接进真实 Runtime loop。

测试：

```text
drop ack
drop heartbeat
kill worker
```

。

---

## S5 — Attempt GC Closure

实现：

```text
terminal
→ GC_PENDING
→ resource release
→ invariant
→ GC_DONE
```

。

release 全部幂等。

---

## S6 — Persistent Trusted Worker Broker

只迁：

```text
semantic_select
logit_gate
```

。

CodeAct 继续 ephemeral。

对比：

```text
Popen per request
vs
persistent worker
```

。

---

## S7 — Resource Ledger + Admission

先资源：

```text
worker slots
sandbox slots
LLM inflight
state budget
```

。

仍：

```text
max_parallel=1
```

。

---

## S8 — WorkflowAwareV1 Scheduler

加入：

```text
aging
critical path
reuse hint
```

。

先：

```text
single active execution
```

，只改变 order。

这样实验可解释。

---

## S9 — Safe Parallelism

仅放开：

```text
PARALLEL_READ_ONLY
```

。

`max_parallel=2`

观察：

```text
race
resource invariant
speedup
```

。

---

## S10 — RuntimeCoordinator

把：

```text
SessionManager
WorkerBroker
ProviderHealth
ResourceLedger
Scheduler
```

提升为：

```text
long-lived service
```

。

允许连续 task submission。

---

## S11 — Runtime Journal / Recovery

SQLite WAL。

实现：

```text
restart
orphan reconciliation
```

。

---

## S12 — openEuler Service Hardening

```text
health endpoints
container healthcheck
restart policy
systemd vLLM
graceful shutdown
continuous run evidence
```

。

---

# 117. 哪些 Slice 是比赛前必须，哪些可延后

## Must

```text
S1 Scheduler seam
S2 attempt identity
S3 real lifecycle
S4 lease monitor
S5 GC closure
S6 persistent trusted worker
S7 resource admission
S8 workflow-aware order
S12 deployment health / continuous evidence
```

。

## Strongly Recommended

```text
S9 limited safe parallelism
S10 RuntimeCoordinator
```

。

## Optional Hardening

```text
S11 full crash resume
```

如果时间不足：

可以诚实定位：

```text
restart-safe cleanup
而不是
transparent task resume
```

。

---

# 118. 实验矩阵

Batch 07 最终不能只跑：

```text
功能单测
```

。

需要 5 类实验。

---

## E1 — Scheduling Correctness

构造 DAG：

```text
A
├─ B
├─ C
│
└─ D(B,C)
```

验证：

```text
D 不提前
B/C 只在 A 后 ready
stable ordering
```

。

---

## E2 — Aging / Critical Path / Reuse

Workload：

```text
Hot-prefix short branch
Cold-prefix critical branch
Old waiting branch
```

比较：

```text
FCFS
Reuse-only
WorkflowAwareV1
```

测：

```text
mean JCT
p95/p99 JCT
max wait
reuse hit
scheduler decision ms
```

。

---

## E3 — Worker Lifecycle Fault Injection

逐项：

```text
worker never ACK

ACK 后不 RUN_START

RUNNING 后 heartbeat stop

worker SIGKILL

late old result

duplicate result

provider disconnect
```

要求：

```text
状态正确
无错误 adoption
资源释放
bounded retry
```

。

---

## E4 — Persistent Worker

至少：

```text
100 / 1000 semantic selections
```

比较：

```text
subprocess per request
persistent worker
```

测：

```text
wall
p50/p95
process spawn count
CPU
RSS
wire bytes
state resolve bytes
```

。

最关键证据：

```text
payload mechanism 不变
只改变 worker lifetime
```

。

---

## E5 — 10+ Continuous Tasks

必须：

```text
同一个 RuntimeCoordinator
连续运行
```

不是：

```text
每 task 重启 Python
```

。

记录：

```text
RSS
FD
threads
live SHM
worker PID
worker generation
provider health
memory store size
task JCT
GC count
orphan count
```

。

---

# 119. Continuous Stability Gate

建议：

```text
至少 20 task
更好 50 task
```

。

退出条件：

```text
no unreleased SHM

no orphan worker

no monotonic FD growth

no monotonic process growth

no invalid late result adoption

all terminal attempts GC_DONE

quality floor unchanged
```

。

---

# 120. Crash / Restart 实验

如果做 S11：

```text
Runtime 正在 RUNNING
↓
kill -9 Runtime
↓
restart
```

要求：

```text
旧 attempt = LOST/ORPHANED

旧 worker fenced / killed

ephemeral state cleaned

committed artifact preserved

pending safe step can continue/retry
```

。

---

# 121. openEuler Deployment Evidence

最终报告应记录：

```text
/etc/os-release

container base digest

Python version

StateBus commit

Docker image ID

vLLM version

model revision

startup command

healthcheck result
```

。

不要只写：

```text
“支持 openEuler”
```

。

---

# 122. Health Drill

至少：

```text
StateBus Runtime restart

vLLM restart

semantic worker restart

CodeAct sandbox failure
```

。

记录：

```text
health state
recovery time
affected task
fallback
resource cleanup
```

。

---

# 123. Final Runtime Claim Boundary

如果 S11 没做完，不要写：

> StateBus 支持 crash-transparent task recovery。

可以写：

> StateBus 提供 attempt-level fault detection、worker restart、resource reconciliation 和 bounded retry；process restart 后对未完成 attempt 进行 fencing/cleanup。

如果有持久 Session Resume 再升级 claim。

---

# 124. Batch 07 Exit Gate

Batch 07 真正完成的标准：

```text
1.
READY set 不再直接 step_id for-loop

2.
存在正式 Scheduler seam

3.
Scheduler 只消费 Runtime-visible facts

4.
有 starvation protection

5.
有 critical-path signal

6.
Batch06 reuse hint 能进入 scheduler

7.
真实 Worker ACK / heartbeat
驱动 lifecycle

8.
attempt identity 不再被 retry 覆盖

9.
late result 可 fence

10.
timeout / worker crash
能主动 detection

11.
terminal attempt
有 GC closure

12.
低风险 state worker
可 persistent reuse

13.
资源有统一 admission / ledger

14.
Runtime invariant 可检查

15.
连续任务无明显资源泄漏

16.
openEuler 容器有真实 health / restart path

17.
Benchmark runner 不再偷偷拥有 production scheduling policy
```

。

---

# 125. Batch 07 → Batch 08 Handoff

Batch 08 不应该再问：

```text
Scheduler 怎么设计？
Worker 怎么重启？
```

。

它应该直接拿：

```text
ScheduleDecisionReceipt
AttemptLifecycleReceipt
ProviderHealthReceipt
GCReceipt
RuntimeInvariantReceipt
DeploymentManifest
```

然后验证：

```text
是否真的减少等待？
是否真的降低 JCT？
是否牺牲 fairness？
是否增加 scheduler overhead？
是否真实复用 persistent worker？
是否 10+ task 稳定？
```

。

---

# 126. 最终建议

StateBus 当前最容易走错的路线是：

```text
看到 TOPAS
→ 实现复杂 weighted scheduler

看到 Agentix
→ 重做一个 agent serving engine

看到 KVFlow
→ 做 CPU/GPU prefetch

看到 openEuler
→ 加 Kubernetes
```

都不建议。

真正适合当前项目的路线是：

# **先把 Runtime Truth 做实，再让已有的 DAG / Reuse / State 信息真正参与调度。**

具体：

```text
Current:
Sequential DAG Executor
+
synthetic lifecycle
+
ephemeral worker
+
benchmark-owned scheduling

        ↓

Target:
Long-lived RuntimeCoordinator
+
attempt-aware event-driven Supervisor
+
persistent trusted workers
+
resource-bounded admission
+
workflow-aware deterministic scheduler
+
explicit GC / invariants
+
openEuler service health
```

。

这会让前面 Batch 01–06 真正连起来：

```text
Task Authority
    ↓
Plan
    ↓
Evidence
    ↓
Artifact Truth
    ↓
Protocol
    ↓
Provider Binding
    ↓
Inference Reuse
    ↓
Runtime Scheduling / Reliability / Deployment
```

而不是继续增加新的 feature island。

---

# 127. 外部参考与可借鉴点

## 127.1 Agentix — NSDI 2026

**Agentix: An Efficient Serving Engine for LLM Agents as General Programs**

- USENIX NSDI 2026
- 核心：Program first-class、program-level scheduling、减少 call/program HOL blocking。
- StateBus 借：
  - RuntimeTaskSession 进入调度；
  - 不把每次 LLM call 当孤立 request。
- 不借：
  - 重写 LLM engine。

参考：

`https://www.usenix.org/conference/nsdi26/presentation/luo`

---

## 127.2 TOPAS — 2026-08

**TOPAS: Workflow-Aware Prefix-State Scheduling for Multi-Agent LLM Serving**

核心：

```text
remaining critical path
+
near-term prefix reuse
+
cache movement/preemption cost
+
aging
```

StateBus 借：

```text
critical path
reuse hint
aging
```

不借：

```text
joint physical KV retention
```

参考：

`https://arxiv.org/abs/2608.25523`

---

## 127.3 KVFlow

**KVFlow: Efficient Prefix Caching for Accelerating LLM-Based Multi-Agent Workflows**

核心：

```text
Agent Step Graph
steps-to-execution
workflow-aware KV retention
prefetch
```

StateBus 借：

```text
future-use distance
```

参考：

`https://arxiv.org/abs/2507.07400`

---

## 127.4 Continuum

**Continuum: Efficient and Robust Multi-Turn LLM Agent Scheduling with KV Cache Time-to-Live**

核心：

```text
tool gap prediction
KV TTL
program-level scheduling
```

StateBus 借：

```text
capability execution gap
program continuity
```

Preview code：

`https://github.com/Hanchenli/vllm-continuum`

Paper：

`https://arxiv.org/abs/2511.02230`

---

## 127.5 SMetric

**SMetric: Rethink LLM Scheduling for Serving Agents with Balanced Session-centric Scheduling**

核心观察：

```text
agent workload
session-level KV locality 很强
```

StateBus 借：

```text
RuntimeTaskSession first-class
```

不进入：

```text
multi-instance router
```

参考：

`https://arxiv.org/abs/2607.08565`

---

## 127.6 SGLang Scheduler

源码：

`https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/managers/schedule_policy.py`

可借：

```text
cache-aware vs cache-agnostic policy 分离
scheduler overhead fallback
waiting queue prefix awareness
```

当前 anti-starvation issue：

`https://github.com/sgl-project/sglang/issues/31954`

它是一个很好的工程警告：

```text
纯 LPM cache locality
需要 aging
```

。

---

## 127.7 SGLang Runtime Invariant Checker

源码：

`https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/managers/scheduler_components/invariant_checker.py`

最值得借：

```text
resource accounting invariant
double-free / use-after-free check
```

。

---

## 127.8 vLLM EngineCore / Fault Tolerance

源码：

`https://github.com/vllm-project/vllm/blob/main/vllm/v1/engine/core.py`

`https://github.com/vllm-project/vllm/blob/main/vllm/v1/fault_tolerance/engine_core_sentinel.py`

可借：

```text
provider engine health
fault state
abort/fence in-flight
recovery generation
```

不借：

```text
vLLM 内部 GPU scheduler
```

。

---

## 127.9 openEuler

openEuler 24.03 LTS SP3 Server：

`https://docs.openeuler.org/zh/docs/24.03_LTS_SP3/server/index.html`

sysmonitor：

`https://docs.openeuler.org/zh/docs/24.03_LTS_SP3/server/maintenance/sysmonitor/sysmonitor_user_guide.html`

Docker Healthcheck：

`https://docs.openeuler.org/zh/docs/24.03_LTS/docs/Container/容器管理-3.html`

推荐定位：

```text
systemd
= service recovery authority

sysmonitor
= host monitoring / diagnostics

Docker healthcheck
= container health
```

。

---

# 128. StateBus 当前源码入口

## Runtime

```text
statebus/runtime/adaptive_runtime.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/adaptive_dispatcher.py
statebus/runtime/supervisor.py
statebus/runtime/session.py
statebus/runtime/telemetry.py
```

## Worker / Protocol

```text
statebus/control/transport.py
statebus/control/subprocess_worker.py
```

## State

```text
statebus/state/store.py
statebus/state/semantic_state.py
statebus/state/logit_state.py
```

## Benchmark

```text
statebus/benchmark/continuous_runner.py
statebus/benchmark/kv_prefix_schedule.py
```

## Deployment

```text
docker/Dockerfile
docker/compose.yaml
docker/README.md

deploy/activate_statebus_host.sh
deploy/vllm.env.example

scripts/vllm/manage_qwen3_32b.sh
```

---

# 129. 一句话冻结

Batch 07 最终建议冻结为：

> **StateBus 不再把 Runtime 等价为“按 DAG 顺序调用函数”，而是建立一个长期存活、Attempt-aware、Event-driven、Resource-bounded 的 RuntimeCoordinator；它以 Task/Session 和 READY Step 为一级调度对象，先通过 hard eligibility/admission，再用 aging → critical path → reuse locality → stable FCFS 做可解释调度；低风险 State 操作迁移到 persistent typed worker，CodeAct 保持 ephemeral sandbox；所有 Worker 生命周期由真实 ACK/Heartbeat/Result 驱动，并通过 GC、Runtime Invariant、openEuler health/restart 完成可靠性闭环。**

这就是 Batch 07 应该承担的边界。
