# 四 Agent 角色合同

StateBus v2 保留 Planner、Retriever、Executor、Summarizer 四个认知角色，但它们并不是四个可以任意互发文本、共享目录或直接修改全局状态的自治进程。每个角色只在 Runtime 给出的可见面内生成候选对象；对象能否进入下一阶段，由计划策略、CapabilityGrant、Ref Registry、Validator 和 Commit Gate 决定。这样既保留 LLM 对任务语义的处理能力，也把执行权限和可信状态迁移留在确定性的系统边界内。

```mermaid
flowchart LR
    T[CanonicalTaskSpec] --> P[Planner\nPlanProposal]
    P -->|PlanPolicy| AP[ApprovedPlan]
    AP --> R[Retriever\nEvidenceRequest]
    R -->|检索、Hydration、状态发布| EP[EvidencePack\nSemanticStateRef]
    EP --> E[Executor\n闭集选择]
    E -->|gate off| EX[程序或动作候选]
    E -->|gate enabled| LS[LogitStateRef]
    LS -->|Gate: accept / retry| EX[程序或动作候选]
    EX -->|沙箱、产物校验| AR[verified\nExecutionArtifactRef]
    AR --> S[Summarizer\nClaimSet 候选]
    EP --> S
    S -->|ClaimSetValidator| C[validated ClaimSet]
    C -->|Runtime Commit| M[MemoryRef]
```

图中的 Agent 节点表示受限决策，箭头上的策略和校验节点表示系统权威。比如 Retriever 可以提出证据请求，但不能绕过语料范围读取任意文件；Executor 可以生成 Python 或 Transform DSL 候选，但不能自行把退出码为零解释成“产物可信”；Summarizer 可以组织结论，却不能引用 EvidencePack 和 verified artifact 之外的事实。

| 角色 | 主要候选输出 | Runtime 接管后的可信对象 | 明确不负责 |
|:--|:--|:--|:--|
| [Planner](planner.md) | `PlanProposal`、检索目标、步骤依赖 | `ApprovedPlan` | 调工具、执行代码、写最终答案、提交记忆 |
| [Retriever](retriever.md) | `EvidenceRequest`、闭集路由选择 | `CanonicalEvidencePack`、`HydrateManifest`、`SemanticStateRef` | 改写任务输出合同、生成最终结论、确认执行产物 |
| [Executor](executor.md) | 闭集选择、TransformProgram 或受限 Python 候选 | `LogitGateReceipt`、verified `ExecutionArtifactRef` | 越权取证、扩展能力范围、提交记忆摘要 |
| [Summarizer](summarizer.md) | `ClaimSet` 候选、可复用步骤描述 | validated `ClaimSet`、受控的记忆提交输入 | 重选工具、修改产物、绕过引用校验 |

源码中的 [role_contract.py](../../../v2/runtime/role_contract.py) 还为四个角色规定了必须出现的遥测键、预期产物和 forbidden scope，用于审计实际报告是否真的经过完整角色图。具体任务执行由 [adaptive_mainline.py](../../../v2/runtime/adaptive_mainline.py)、[adaptive_runtime.py](../../../v2/runtime/adaptive_runtime.py) 和 [adaptive_dispatcher.py](../../../v2/runtime/adaptive_dispatcher.py) 共同编排；角色合同不是提示词约定，而是与计划、授权、对象状态和遥测相互印证的运行约束。
