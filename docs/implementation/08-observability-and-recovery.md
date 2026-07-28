# 可观测性与恢复导航

StateBus 不把运行状态只写进 console。Telemetry 记录逐事件事实与任务终态指标，Ledger 记录重放决定，sidecar 保存合同与报告，Supervisor/JobManager 负责把失败收敛为明确终态。

| 文档 | 核心问题 |
|:--|:--|
| [Telemetry 与指标聚合](operations/telemetry-and-metrics.md) | 哪些事件是增量、哪些是快照，任务指标如何避免重复累加 |
| [失败恢复与资源结算](operations/failure-recovery.md) | ACK/heartbeat、策略拒绝、Validator 失败、取消与 GC 如何处理 |
| [Run 目录、sidecar 与 Ledger](operations/run-evidence-layout.md) | 一次结论如何回到 summary、event、Ref、Validator 和 replay decision |

事件出现只是起点。机制真实性通常还需要对象分母、消费回执、行为效果和质量门共同解释。Logit Gate 尤其要把 Producer Receipt、独立 PID GateReceipt、最终 dispatch/fail-closed 状态和 release tombstone 放在一起，不能只展示一个 entropy 或 margin 数字。
