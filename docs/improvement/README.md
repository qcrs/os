# StateBus v2 改进计划总索引

**制定时间**：2026-07-03
**基于**：`docs/reports/v2_code_review_20260703.md` 审阅结论
**约束**：基于赛题、可落地可实现、本轮只分析不改代码

---

## 问题分类与文件索引

| 优先级 | 问题域 | 文档 | 核心目标 |
|---|---|---|---|
| P0 | 证据刷新与验证闭环 | `01_p0_evidence_refresh.md` | HEAD 代码下 pytest 全绿 + evidence 重新落盘 |
| P0 | External Comparator 完整化 | `02_external_comparator_upgrade.md` | formal financial family 下的公平对比成立 |
| P1 | 任务设计补充 | `03_task_design_expansion.md` | 任务更贴赛题、更有说服力 |
| P1 | CodeAct API 稳定化 | `04_codeact_stabilization.md` | API 生成代码至少一次通过 AST policy |
| P1 | Runtime Overhead 分析与优化 | `05_runtime_overhead_analysis.md` | 解释 +9263ms 并有优化路径 |
| P2 | KV Cache 实现路径 | `06_kv_cache_implementation.md` | 本地 vLLM + prefix cache 机制验证 |
| 深度审阅 | 四大模块代码级问题 | `07_deep_implementation_analysis.md` | 结构化通信、Embedding、记忆复用、CodeAct 的代码级 Bug 和优化点 |

---

## 执行顺序建议

```
P0-1（pytest 复验）
    ↓
P0-2（external comparator formal 化）
    ↓
P1-a（任务设计扩充）+ P1-b（CodeAct 稳定化）  ← 可并行
    ↓
P1-c（runtime overhead 说明文档）
    ↓
P2（KV Cache 机制验证）
```

---

## 核心原则

1. **每个改动不破坏已有证据**：只新增任务族、新增对比，不修改现有 expected fields
2. **claim 边界必须在结果产出时重新标定**：每次新实验后更新 claim boundary
3. **容器内复验优先**：所有实验命令以容器版本为准
4. **formal 对比是核心**：赛题评分最重的是"实验验证"和"通信效率"，external comparator 直接影响这两项

---

## 当前已确认的证据状态

| 证据 | 状态 | 可用于 claim |
|---|---|---|
| container pytest 154 passed | frozen baseline (f7dcb15) | 需要在 HEAD 重确认 |
| external compare dev gate pass | 3/3，但 HEAD 之前的结果 | dev scope only |
| continuous 20 轮 | frozen baseline | 需要在 HEAD 重确认 |
| replay 16 轮 validated=13 exact=3 | frozen baseline | 需要在 HEAD 重确认 |
| flagship ablation 4/4 | frozen baseline | 需要在 HEAD 重确认 |
| CodeAct bwrap ok | deterministic fallback | 不能 claim API 生成稳定 |
