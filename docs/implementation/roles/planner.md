# Planner：把任务语义压缩成待审批计划

Planner 面向的是任务合同，而不是原始数据文件。formal task 先由 TaskCompiler 形成 `CanonicalTaskSpec`，Runtime 再向 Planner 暴露任务目标、`AdaptiveTaskEnvelope`、允许使用的输入 Ref 摘要、capability surface、角色基数约束，以及发生重规划时的失败上下文。Planner 因而知道“要完成什么”和“允许组合哪些能力”，却看不到未授权证据，也没有执行工具的句柄。

Planner 的主要输出是 `PlanProposal`。提案中的每个 `PlanStepProposal` 需要声明角色、`capability_id`、依赖关系、输入 Ref 及类型、输出合同和完成条件；计划还会声明最终输出合同和请求的记忆策略。这一步可以由 LLM 处理任务语义，但其结果始终被视为 untrusted candidate，不能直接下发给 Worker。

`PlanPolicyValidator` 会重新检查任务 ID、DAG 结构、角色顺序与基数、能力是否存在、输入引用是否可用、输出合同是否在白名单内，以及当前任务是否允许 LLM Python。必要时系统只允许受约束的 schema repair；最终仍无法通过时，运行会以 planner hard rejection 收敛，而不是让 Planner 临场放宽规则。通过策略检查后，系统产生新的 `ApprovedPlan`，后续 CapabilityGrant 只从这个批准版本派生。

| 合同面 | Planner 的边界 |
|:--|:--|
| 可见输入 | 任务语义、允许输入、能力目录、角色与预算约束 |
| 候选输出 | `PlanProposal`、检索目标、步骤依赖与完成条件 |
| 权威校验 | `PlanPolicyValidator`、计划规范化和批准计划 hash |
| 禁止范围 | 执行工具、物化最终产物、读取隐藏证据、提交记忆 |

主要实现位于 [role_path.py](../../../statebus/runtime/role_path.py)、[adaptive_mainline.py](../../../statebus/runtime/adaptive_mainline.py)、[adaptive_plan_compiler.py](../../../statebus/runtime/adaptive_plan_compiler.py) 与 [plan_policy.py](../../../statebus/runtime/plan_policy.py)。任务进入 Planner 之前的编译过程另见[任务编译](../runtime/task-compilation.md)，提案怎样变成能力授权另见[计划策略与能力授权](../runtime/plan-policy-and-capability.md)。

