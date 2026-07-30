# Planner：把任务语义压缩成待审批计划

Planner 面向任务合同。formal task 先由 TaskCompiler 形成 `CanonicalTaskSpec`，Runtime 再向
Planner 暴露任务目标、`AdaptiveTaskEnvelope`、获准输入 Ref 摘要、capability surface、角色
基数约束和重规划上下文。Planner 据此理解任务目标并组合获准能力。

Planner 的主要输出是 `PlanProposal`。提案中的每个 `PlanStepProposal` 声明角色、
`capability_id`、依赖关系、输入 Ref 及类型、输出合同和完成条件；计划还声明最终输出合同和
记忆策略。LLM 负责处理任务语义，输出以 untrusted candidate 状态进入 PlanPolicy。

`PlanPolicyValidator` 检查任务 ID、DAG 结构、角色顺序与基数、能力登记、输入引用、输出合同
白名单和 LLM Python 开关。schema repair 在固定合同内执行；校验通过后产生 `ApprovedPlan`，
其余情况以 planner hard rejection 收敛。后续 CapabilityGrant 从批准版本派生。

| 合同面 | Planner 的职责 |
|:--|:--|
| 可见输入 | 任务语义、允许输入、能力目录、角色与预算约束 |
| 候选输出 | `PlanProposal`、检索目标、步骤依赖与完成条件 |
| 权威校验 | `PlanPolicyValidator`、计划规范化和批准计划 hash |
| 后续职责 | 工具执行、产物物化与记忆提交由 Runtime 分派给对应组件 |

主要实现位于 [role_path.py](../../../statebus/runtime/role_path.py)、[adaptive_mainline.py](../../../statebus/runtime/adaptive_mainline.py)、[adaptive_plan_compiler.py](../../../statebus/runtime/adaptive_plan_compiler.py) 与 [plan_policy.py](../../../statebus/runtime/plan_policy.py)。任务进入 Planner 之前的编译过程另见[任务编译](../runtime/task-compilation.md)，提案怎样变成能力授权另见[计划策略与能力授权](../runtime/plan-policy-and-capability.md)。
