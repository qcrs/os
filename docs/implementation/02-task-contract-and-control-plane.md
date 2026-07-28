# Runtime 与控制面导航

控制链按问题拆分。它们分别解释任务从哪里来、计划为什么不能直接执行、Protobuf 帧实际传什么、Executor 候选怎样经过数值授权门，以及 Worker 失联或重试时状态怎样收敛。

| 文档 | 核心问题 |
|:--|:--|
| [任务编译与正式任务合同](runtime/task-compilation.md) | 自然语言请求如何变成可 hash 的 CanonicalTaskSpec，formal 为什么要求预编译 spec |
| [计划策略与能力授权](runtime/plan-policy-and-capability.md) | PlanProposal 如何批准，CapabilityGrant 如何限制 step 的权限 |
| [Protobuf 与 UDS 控制协议](runtime/protobuf-and-uds.md) | ExecRequest、ACK、heartbeat、result 和 GC 如何在线路中编码 |
| [Logit Retry Gate](runtime/logit-retry-gate.md) | Executor 候选概率如何让 Runtime 决定执行、重查或 fail closed |
| [Worker 生命周期与 attempt 隔离](runtime/worker-lifecycle.md) | Supervisor 状态机、timeout、晚到结果、取消与回收如何工作 |

控制链的最短表达是：

```text
CanonicalTaskSpec
  -> PlanProposal
  -> PlanPolicyReport + ApprovedPlan
  -> CapabilityGrant
  -> Executor closed-set choice
  -> optional LogitStateRef / GateReceipt
  -> ExecRequest
  -> ACK / RUN_START / HEARTBEAT / RES_*
  -> Validators / settlement / GC
```

Protobuf 只能证明消息格式可以解析，不能证明操作已经授权或业务结果正确。授权由 PlanPolicy、CapabilityGrant 与 dispatch 前复核提供；结果可信性由 Ref 校验、Validator 和 Commit Gate 提供。
