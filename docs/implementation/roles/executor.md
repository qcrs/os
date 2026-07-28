# Executor：把批准动作变成可验证产物

Executor 取得的是针对单次 attempt 签发的 `CapabilityGrant`，其中固定了任务、会话、步骤、允许的 capability、输入 Ref、输出合同、workspace 和 grant hash。它不能继承 Planner 的宽泛意图后自由行动，也不能扫描 Retriever 没有纳入 EvidencePack 的数据。所有输入先经过 Ref 状态、会话归属、schema、hash 和兼容签名检查，非文本状态还必须留下真实消费回执。

当一个执行步骤存在 2 到 8 个闭集 route/tool 候选且启用 Logit Gate 时，Executor 先只返回候选别名。Runtime 从真实 choice-token 概率生成 `LogitStateRef`，交给独立 Gate PID；只有 Gate 接受，或唯一一次 recheck 后接受，候选才越过 Worker dispatch 边界。第二次仍低 margin、概率不可用或回执身份不一致都会 fail closed。该 Gate 不允许 Executor 扩大证据或 CapabilityGrant。

执行路径取决于批准 capability。确定性 handler 可以直接完成固定计算；Transform DSL 用受限操作集合表达筛选、聚合、跨期比较等数据变换；adaptive CodeAct 才会让 LLM 生成受限 Python。也就是说，Executor 并不等于“所有任务都让 LLM 临场写代码”。无论候选来自哪条路径，实际运行都只能发生在 attempt workspace 和授权输入面内。

Python 候选要经过 AST 与 policy 检查，再由隔离执行器运行；DSL 需要通过操作、字段和参数合同检查。程序正常退出后产生的仍是 candidate artifact。Runtime 随后核对文件范围、manifest、schema、行数、数值不变量、内容 hash 和 lineage，只有全部满足当前完成条件时，Ref Registry 才会把 `ExecutionArtifactRef` 提升为 verified。失败产物保留审计信息，但不会被 Summarizer 当成可信输入。

| 合同面 | Executor 的边界 |
|:--|:--|
| 可见输入 | 当前 Grant、verified 输入 Ref、完整 EvidencePack、被授权的语义状态 |
| 候选输出 | 工具选择、TransformProgram 或 bounded Python、执行文件与 manifest |
| Runtime 物化 | `LogitStateRef`/GateReceipt、candidate 到 verified 的 `ExecutionArtifactRef`、执行记录与 validator receipt |
| 禁止范围 | 读取隐藏证据、扩大 capability、修改任务合同、提交记忆摘要 |

调度与产物注册位于 [adaptive_dispatcher.py](../../../v2/runtime/adaptive_dispatcher.py)；CodeAct 主体位于 [llm_codeact.py](../../../v2/runtime/llm_codeact.py)，DSL 位于 [transform_dsl.py](../../../v2/runtime/transform_dsl.py)。更完整的执行链见[Logit Retry Gate](../runtime/logit-retry-gate.md)、[受限 Python CodeAct](../execution/bounded-python-codeact.md)、[Transform DSL](../execution/transform-dsl.md)和[产物质量门](../execution/artifact-and-quality-gate.md)。
