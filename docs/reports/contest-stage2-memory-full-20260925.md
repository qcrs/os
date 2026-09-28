# B1 Memory 完整小对比（2026-09-25）

运行目录：`runs/contest-stage2-memory-context-fix-20260925_213240/`。

## 结果

- 计划 12 项，启动 12 项，通过 12 项，失败 0 项。
- F01→F02→F06 与 O01→O02→O06 均完成 `SB-NO-MEMORY`/`validated_replay` 配对。
- 所有任务的业务 scorer 与报告质量检查通过。
- `acceptance.ok=true`；`formal_stage2_ready=false` 与 `stage3_allowed=false` 保持不变，因为本批只回答 Memory 机制。

| 配置 | 任务 | 通过 | provider 请求 | provider tokens | Executor 请求 | 总耗时（秒） |
|---|---:|---:|---:|---:|---:|---:|
| SB-NO-MEMORY | 6 | 6 | 35 | 98,087 | 7 | 927.217 |
| validated_replay | 6 | 6 | 33 | 91,460 | 5 | 772.957 |

相对这组匹配任务的描述性观察：validated replay 少 2 次 provider 请求、少 2 次 Executor 请求、少 6,627 provider tokens，总耗时少 154.260 秒（约 16.6%）。这不是跨批次或统计显著性结论；GPU 和模型服务共享环境，耗时只作为本批记录。

## Memory 具体行为

- F02 与 O02 的 validated replay 没有发起 Executor 请求，使用已验证 recipe 对当前输入重新计算；这是本批最直接的重复生成减少证据。
- F06 与 O06 的旧 recipe 因 schema/lineage 变化降级为 `assist`，仍由 Executor 重新生成当前任务代码；没有强行重放旧方法。
- 12 项质量均通过，证明记忆复用没有破坏当前任务的正确性。

## 证据边界

本批完成 B1 Memory；不代表通信、语义状态、跨 Agent Memory 或 A 主链已完成。它也不把 `provider tokens` 当作 Agent 通信 token。`formal_stage2_ready=false` 和 `stage3_allowed=false` 是正确状态，不应通过改布尔值放行。

## 下一步

依据 `astra-measurement-proposal/37-CONTEST-DELIVERY-EXPERIMENT-PLAN-20260925.md`，下一项开发交付是 A 主实验：补齐 F03–F05、F07–F10 与 O03–O05、O07–O10 的 taskpack、独立 scorer、连续 caller 和共同 handoff 指标。完成接线和最小离线验证后，再运行两配置的 40 次主实验。B2 通信只需 F01 的 text/typed matched receiver 两次；B3 复用已有 s1 三组；B4 优先接入 F10/O10 的跨 Agent Memory 消费；C 再跑固定 10 个 CodeAct 代表任务。
