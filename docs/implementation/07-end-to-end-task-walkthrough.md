# 端到端任务走读

一次正常任务从 task input 到结果的主要对象关系如下：

~~~mermaid
sequenceDiagram
    participant I as Input / Studio
    participant R as Runtime
    participant W as Role provider
    participant S as State / Artifact store
    I->>R: task input
    R->>R: compile CanonicalTaskSpec
    R->>R: approve PlanProposal
    R->>W: dispatch attempt + CapabilityGrant
    W->>S: resolve StateRef / write Artifact
    W-->>R: result + receipt
    R->>R: validate and settle attempt
    R-->>I: ClaimSet / task result
~~~

## 关键检查点

1. task_id、step_id、attempt_id 和 trace_id 在当前调用链中保持可关联。
2. PlanPolicy 先产生批准计划，provider 不能绕过 grant 直接取得下游权限。
3. StateRef 解析、Artifact verification、quality gate 和 Memory commit 分别留下 receipt 或 telemetry。
4. timeout 或 late result 只能更新匹配的 current attempt；旧 attempt 不应改变已结算步骤。
5. task_wall_ms 包含 Runtime、provider、State/Artifact、服务切换和清理成本。

## 结果入口

走读代码：

~~~text
src/statebus/runtime/driver.py
src/statebus/runtime/adaptive_mainline.py
src/statebus/runtime/adaptive_runtime.py
src/statebus/runtime/adaptive_dispatcher.py
src/statebus/runtime/telemetry.py
~~~

配对结果：

- 主链：48 个任务位置、24 对 SB-FULL/P-TEXT，见 tests/evidence/mainline/；
- 机制：24 个计划位置，当前汇总见 [`tests/evidence/mechanisms/`](../../tests/evidence/mechanisms/)；
- utility：28 个计分位置，见 tests/evidence/model-assist/。

完整事件、ledger 和服务日志按 run ID 位于 `runs/`；本页不重复复制实验表。
