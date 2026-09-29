# 四个角色

Runtime 当前的角色合同位于 `src/statebus/runtime/role_contract.py`，主要角色为 Planner、Retriever、Executor 和 Summarizer。角色生成候选；`PlanPolicy`、capability grant、Ref Registry、validator 和 commit gate 负责授权与状态提升。

```mermaid
flowchart LR
    T[CanonicalTaskSpec] --> P[Planner / PlanProposal]
    P --> A[PlanPolicy / ApprovedPlan]
    A --> R[Retriever / EvidencePack]
    R --> E[Executor / Artifact candidate]
    E --> V[Verifier / verified Artifact]
    V --> S[Summarizer / ClaimSet]
    S --> M[Memory commit]
```

角色实现与路径：

| 角色 | 主要代码 | 可信输出 |
| --- | --- | --- |
| Planner | `runtime/adaptive_mainline.py`、`plan_policy.py` | `PlanProposal`、`ApprovedPlan` |
| Retriever | `retrieval/`、`runtime/evidence_projection.py` | `EvidencePack`、可选 `SemanticStateRef` |
| Executor | `runtime/adaptive_dispatcher.py`、`codeact.py` | candidate program、`ExecutionArtifactRef` |
| Summarizer | role provider 与 `runtime/claims.py` | validated `ClaimSet` |

APC、显式 KV 和 Logit 是模型侧旁路，不增加新的业务角色。
