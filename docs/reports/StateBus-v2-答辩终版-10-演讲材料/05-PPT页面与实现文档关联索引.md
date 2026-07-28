# PPT 页面与实现文档关联索引

本索引把 28 页 PPT、项目说明书章节、实现手册专题和实验来源放在同一张检索表中。PPT 决定现场叙事顺序，项目说明书提供完整书面解释，implementation 文档用于回答“代码里具体怎样实现”，实验报告用于确认数字和分母。

## 全局来源

- 当前演示文稿：[StateBus-v2-答辩终版-10.pptx](../StateBus-v2-答辩终版-10.pptx)
- 项目说明书：[项目说明书-总.pdf](../项目说明书-总.pdf)
- 实现手册总入口：[docs/implementation/README.md](../../implementation/README.md)
- PPT 固定实验口径：[StateBus-v2-最终实验结果与PPT绘图数据-20260726.md](../StateBus-v2-最终实验结果与PPT绘图数据-20260726.md)
- Logit Gate 补充实验：[StateBus-v2-LogitRetryGate受控机制实验-20260727.md](../StateBus-v2-LogitRetryGate受控机制实验-20260727.md)

## 逐页关联

| 页码 | 页面作用 | 项目说明书对应内容 | 实现与证据入口 |
|:--|:--|:--|:--|
| P01 | 用一句话定义作品类别 | 摘要；1.1 目的与意义 | [总体分层](../../implementation/architecture/overview.md) |
| P02 | 给出五部分汇报结构 | 目录 | 本目录 [README](README.md) |
| P03 | 项目介绍转场 | 第 1 章、第 3 章 | 无需展开技术细节 |
| P04 | 给出全文 handoff 的根因：控制、状态、记忆混装 | 1.1、1.2；2.1 设计思想 | [总体分层](../../implementation/architecture/overview.md)、[对象模型](../../implementation/architecture/object-model.md) |
| P05 | 用三轮财报链具体化角色交付和因果依赖 | 3.2 多 Agent 协作；3.4 跨任务复用 | [三轮财务记忆链](../../implementation/walkthrough/continuous-financial-memory.md)、[四角色合同](../../implementation/roles/README.md) |
| P06 | 给出 Runtime 总地图和三条对象通道 | 3.1 总体架构；3.2 结构化运行时 | [系统架构导航](../../implementation/01-system-architecture.md)、[进程与存储](../../implementation/architecture/process-and-storage.md)、[Ref 边界](../../implementation/state/ref-boundaries.md) |
| P07 | 项目亮点转场 | 5.1 核心技术亮点 | 不停留解释 |
| P08 | 定义结构化通信亮点：字段合法升级为语义获准 | 2.2 技术路线；3.2 结构化运行时 | [Protobuf 与 UDS](../../implementation/runtime/protobuf-and-uds.md)、[Worker 生命周期](../../implementation/runtime/worker-lifecycle.md) |
| P09 | 展示 TaskSpec、PlanPolicy、Grant 和 RoleView | 3.2；5.2 执行语义难点 | [任务编译](../../implementation/runtime/task-compilation.md)、[计划策略与授权](../../implementation/runtime/plan-policy-and-capability.md)、[Planner](../../implementation/roles/planner.md) |
| P10 | 定义可验证非文本状态对象 | 3.3 非文本状态；5.1 核心亮点 | [稠密语义状态](../../implementation/state/dense-semantic-state.md)、[Ref 边界](../../implementation/state/ref-boundaries.md) |
| P11 | 展示 Producer、StatePool、Consumer 和 hydration | 3.3；图 3-3 | [稠密语义状态](../../implementation/state/dense-semantic-state.md)、[Hydration 与证据](../../implementation/state/hydration-and-evidence.md)、[存储生命周期](../../implementation/state/storage-and-lifecycle.md) |
| P12 | 区分候选命中、兼容、消费和行为效果 | 3.4 共享记忆；5.1 | [兼容门与真实消费](../../implementation/memory/compatibility-and-consumption.md) |
| P13 | 展示 FTS/向量/RRF、Memory Passport 和 RoleView | 3.4；图 3-4 | [混合记忆检索](../../implementation/memory/hybrid-retrieval.md)、[兼容与消费](../../implementation/memory/compatibility-and-consumption.md)、[提交与重放](../../implementation/memory/commit-and-replay.md) |
| P14 | 展示 CodeAct 从候选源码到 verified Artifact | 3.5 CodeAct、DSL 与可信产物 | [受限 Python CodeAct](../../implementation/execution/bounded-python-codeact.md)、[产物质量门](../../implementation/execution/artifact-and-quality-gate.md)、[Transform DSL](../../implementation/execution/transform-dsl.md) |
| P15 | 技术难点转场 | 5.2 关键实现难点 | 不停留解释 |
| P16 | 三重授权校验：计划、Grant、发送前对象 | 3.2；5.2.1 | [计划策略与授权](../../implementation/runtime/plan-policy-and-capability.md)、[失败恢复](../../implementation/operations/failure-recovery.md) |
| P17 | 解释低复制与可信消费的折中 | 3.3；5.2 非文本状态难点 | [Ref 边界](../../implementation/state/ref-boundaries.md)、[存储生命周期](../../implementation/state/storage-and-lifecycle.md)、[稠密语义状态](../../implementation/state/dense-semantic-state.md) |
| P18 | 解释相似度与硬兼容条件的二维关系 | 3.4；5.2 跨任务兼容 | [兼容门与真实消费](../../implementation/memory/compatibility-and-consumption.md)、[提交与重放](../../implementation/memory/commit-and-replay.md) |
| P19 | 项目测试转场 | 第 4 章 | 不停留解释 |
| P20 | 定义任务、四层验证、95 次执行和公平条件 | 4.1—4.4 | [固定实验口径](../StateBus-v2-最终实验结果与PPT绘图数据-20260726.md) |
| P21 | 总览质量、Token、wire、总耗时和三个专项 | 4.5、4.6 | [固定实验口径](../StateBus-v2-最终实验结果与PPT绘图数据-20260726.md) |
| P22 | 区分完整链 L0/L3 与控制面 L0/L1 | 4.6 完整链；4.7 结构化通信 | [Protobuf 与 UDS](../../implementation/runtime/protobuf-and-uds.md)、固定实验口径 |
| P23 | 非文本状态的跨 PID、行为效果和释放 | 4.8 非文本状态专项 | [稠密语义状态](../../implementation/state/dense-semantic-state.md)、[Telemetry](../../implementation/operations/telemetry-and-metrics.md) |
| P24 | 查询级 actual-use 与候选级拒绝率 | 4.9 共享记忆专项 | [兼容与消费](../../implementation/memory/compatibility-and-consumption.md)、[提交与重放](../../implementation/memory/commit-and-replay.md) |
| P25 | 五类任务、18/7 路径、0 fallback、回归和 openEuler | 4.10 能力覆盖；3.5、3.7 | [CodeAct/质量门导航](../../implementation/05-codeact-artifact-and-quality.md)、[测试清单](../../implementation/extensions/testing-and-review.md) |
| P26 | 作品演示转场 | 3.7 软件界面 | 不停留解释 |
| P27 | 展示 Studio 的真实任务流、代码、产物和回执 | 3.7；图 3-6、图 3-7 | [StateBus Studio](../../implementation/06-statebus-studio.md)、[前端交互](../../implementation/studio/frontend-and-interaction.md)、[后端 API](../../implementation/studio/backend-jobs-and-api.md)、[IQR 单任务走读](../../implementation/walkthrough/single-task-iqr.md) |
| P28 | 用系统级价值收束 | 第 6 章总结 | [整套逻辑](01-整套答辩逻辑与叙事主线.md) |

## 四个核心对象的检索关系

| 对象 | 现场一句话解释 | 深入阅读 |
|:--|:--|:--|
| `CanonicalTaskSpec` / `ApprovedPlan` / `CapabilityGrant` | 把任务、计划和一次执行权分开，模型提议不能直接变成权限 | [任务编译](../../implementation/runtime/task-compilation.md)、[计划策略与授权](../../implementation/runtime/plan-policy-and-capability.md) |
| `SemanticStateRef` | 连接连续 `float32` 载荷、解释合同、对象身份和生命周期的可信引用 | [稠密语义状态](../../implementation/state/dense-semantic-state.md) |
| `ExecutionArtifactRef` | Executor 文件结果的引用，只有 Validator 通过后才从 candidate 提升为 verified | [产物质量门](../../implementation/execution/artifact-and-quality-gate.md) |
| `MemoryRef` | 带任务、schema、lineage、Runtime 条件和提交状态的跨任务知识单元 | [兼容与消费](../../implementation/memory/compatibility-and-consumption.md) |

新增的 `LogitStateRef` 不在 PPT 主叙事中。它保存 Executor 闭集候选概率与 `other_mass`，由独立 PID 的 Logit Gate 消费，用于执行前的 accept、retry 或 fail-closed。需要补充时阅读 [LogitState](../../implementation/state/logit-state.md)、[Logit Retry Gate](../../implementation/runtime/logit-retry-gate.md)和[受控挑战走读](../../implementation/walkthrough/logit-retry-challenge.md)。

## 固定基线与当前实现的时间差

项目说明书和 PPT 的实验主体固定在 `bda1774`，因此 P25 保留 `558 passed`。实现手册又包含 7 月 27 日加入的 Logit Retry Gate，机制合入后的当前 `tests/v2` 为 `582 passed`。两者不是互相否定：前者是 PPT 固定证据快照，后者是新增机制后的工程回归。现场如果不讨论 Logit Gate，就按 PPT 讲 558；如果评委问当前代码状态，再补充 582，并明确 95/95 正式业务基线未改。

