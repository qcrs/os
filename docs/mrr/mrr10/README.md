# StateBus MRR-10 — RolePath Compatibility Migration

状态：

```text
Batch 1 = CLOSED
Batch 2 = CLOSED
Batch 3 = CLOSED
Batch 4 = CLOSED

MRR-01 ~ MRR-09 = CLOSED / FROZEN
Competition Gate = UNVALIDATED

MRR-10 = DESIGN / SOURCE RECONCILIATION
```

本目录只定义 RolePath 的兼容迁移边界、authority migration map、slice
decision 和 implementation blueprint。本轮没有修改 production source、test、
benchmark，也没有运行测试或 Competition E2E。

## 目标

```text
RolePath = recipe / prompt / provider compatibility logic
RolePath != execution authority
```

唯一 canonical product assembly 是 `AdaptiveMainlineRunner`，唯一 canonical
execution authority 是 `AdaptiveRuntimeEngine`。固定 topology 仍然是：

```text
retriever → executor → summarizer
```

它由 `StaticRoleRecipe` 编译为不可信 `PlanProposal`，经
`PlanNormalizationReceipt`、`PlanPolicyReport` 后形成 `ApprovedPlanBundle`；
RolePath 不重新定义该 topology，也不产生 ApprovedPlan、Attempt、Binding 或
Grant。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [Source Reconciliation](./StateBus-MRR-10-Source-Reconciliation.md) | 当前 source fact、真实 smoke call chain、责任五分类、file-level migration map |
| [Compatibility Deep Design](./StateBus-MRR-10-RolePath-Compatibility-Deep-Design.md) | provider、planner、LLM、State、Artifact、Memory、instrumentation 和 parity 设计 |
| [Readiness and Slice Decision](./StateBus-MRR-10-Readiness-and-Slice-Decision.md) | design conflict adjudication、Gate blueprint、slice 切分和 readiness |
| [Implementation Plan](./StateBus-MRR-10-Implementation-Plan.md) | 仅为后续 implementation slices 提供范围、顺序和验收条件 |
| [Slice Spec](./MRR-10A-Role-Provider-Authority-Convergence-Slice-Spec.md) | MRR-10A：one-step provider authority convergence |
| [Slice Spec](./MRR-10B-Fixed-Compatibility-Facade-Parity-Slice-Spec.md) | MRR-10B：fixed compatibility facade / parity convergence |

## 明确非目标

```text
不修改 statebus/runtime/role_path.py
不修改 statebus/runtime/smoke.py
不修改 benchmark entry 或 comparator ownership
不删除 run_smoke
不新增 RoleRuntime / FixedRuntime / RolePathRuntime
不重新设计 provider registry、Memory 或 result commit
不迁移 Competition E2E
不生成 artifacts/mrr-10/* implementation evidence
```

`run_smoke` 在 MRR-10 仍是 legacy comparator lane；fixed benchmark entry 的
迁移属于 MRR-11。本轮只记录它当前调用 `run_smoke` 的边界与后续 canonical
target。

## 设计结论摘要

```text
RolePath as Runtime                         REJECTED
RolePath as compatibility source            ACCEPTED
Provider adapter extraction                REQUIRED
Compatibility facade                       REQUIRED: existing FixedMainlineRequest shape
Canonical execution                        AdaptiveRuntimeEngine
Fixed plan source                          StaticRoleRecipe / ApprovedPlanBundle
run_smoke in MRR-10                        LEGACY_COMPARATOR
Slice structure                            MRR-10A + MRR-10B
Implementation readiness                   READY (design only; gates not yet run)
Competition Gate                           UNVALIDATED
```

Machine-readable status marker：`COMPETITION_GATE_UNVALIDATED`。
