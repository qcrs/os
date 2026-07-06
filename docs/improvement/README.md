# StateBus v2 改进计划

> 2026-07-06 current-source note: 本 README 下方的评分和实验数字保留为 2026-07-04 historical snapshot。当前答辩事实源请优先使用 `14_full_validation_rollup_20260706.md`、`15_fairness_gate_propagation_audit_20260706.md`、`16_deep_contest_audit_20260706.md` 以及对应 `docs/improvement/artifacts/` 证据日志。

**审计基准**：HEAD `6ece8a0`，实验数据 `full-experiment-20260704_111950`
**代码路径**：基于实际代码探索，所有行号均已核实

---

## 当前评分预估（2026-07-04 更新）

| 评分维度 | 满分 | 当前预估 | 核心缺口 |
|---|---|---|---|
| 通信效率 | 25 | 20~23 | comparison_valid=False，formal headline 未激活；carrier 数据强但需要在报告中前置展示 |
| 状态传递创新 | 20 | 15~17 | stress_pass=3/6；memfd 已实现但 formal compare 未激活；lookup_by_tags 仍 Python 扫描 |
| 记忆复用 | 20 | 16~18 | SQLite FTS5 已实现；COMMITTED 已降为 quality_floor_pass；FAISS 未实装 |
| 系统完整性 | 20 | 15~17 | 同进程顺序执行；SubprocessExecutorTransport 未在 formal 中激活；incident_diagnosis_v2 已上线 |
| 实验验证 | 15 | 12~14 | CodeAct 5/5 ✅；codeact -65.7% ✅；stress_pass 3/6 是薄弱点 |
| **合计** | **100** | **78~89** | |

---

## 文件索引

| 优先级 | 文件 | 解决的核心问题 | 状态 |
|---|---|---|---|
| **P0** | `01_p0_critical_fixes.md` | CodeAct 生成、memory 设计、claim 路径 | 大部分已完成 |
| **P0** | `02_competition_claim_hardening.md` | 竞赛声明精确表述与答辩防御 | 最新数据已更新 |
| **P1** | `03_agent_role_and_task_redesign.md` | 3类任务、角色真实性、10轮连续 | incident_v2 已上线 |
| **P1** | `04_codeact_and_sandbox_hardening.md` | CodeAct 完整修复（代码级） | LLM 5/5 已验证 |
| **P1** | `05_memory_and_replay_complete_design.md` | SQLite FTS、replay 完整实现 | FTS5 已实现，FAISS 待做 |
| **P1** | `07_non_text_state_transfer_audit.md` | 非文本传递四环节审计 | MemfdStatePool 已实现 |
| **P1** | `08_performance_and_overhead_breakdown.md` | overhead 分解与答辩口径 | benchmark_balanced+cache 已实现 |
| **P2** | `06_kv_cache_implementation.md` | KV Cache 机制（保留原文，Future Work） | 未实现，不计分 |

最新补充：

- `16_deep_contest_audit_20260706.md`：从赛题要求出发复核 v2 的代码、benchmark JSON、历史审计链路和 claim 边界；修复 full audit script 指标解析/socket 隔离问题，并新增 replay 保守语义指标。
- `15_fairness_gate_propagation_audit_20260706.md`：修复 external pure-text per-case fairness gate 未上卷到 family/comparator hard gate 的问题，并归档 `api + local` compare JSON 证据。

---

## 最新实验关键数字（full-experiment-20260704_111950）

```
pytest:              194 passed
CodeAct LLM gen:     5/5 success，generation_fallback_used=False，attempt_count=1
codeact_stage_ms:    2455→843ms（-65.7%，runner cache 已实现）
formal compare:      superiority_claim=True，efficiency_claim=True
                     StateBus 8/8 vs External 6/8（quality_delta=+2）
                     tokens_delta=-743，bytes_delta=-10928B
                     comparison_valid=False（external 6/8 未过 quality floor gate）
carrier compare:     task_ms_delta=-6114ms，llm_prompt_bytes_delta=-1922B，valid=True
continuous replay:   validated_replay=15，exact_replay=10，missing_target_rounds=0
incident_diag_v2:    eligible_for_replay_headline=True，skipped_step_count=16，
                     exact_replay=7，validated_replay=2
replay neg audit:    7/7 pass
stress_pass:         3/6 families（flagship ablation）
```

---

## 执行顺序（剩余工作）

```
高优先级（影响评分）：
  1. lookup_by_tags() 加 SQL WHERE 子句（B1，1小时）
  2. comparison_valid=False 答辩口径完善（B3，不改代码）
  3. cross_period_financial_v1 任务族实装（提升系统完整性）

中优先级（锦上添花）：
  4. FAISS optional backend（C1）
  5. per-family replay breakdown 报告（C6）
  6. SubprocessExecutorTransport 集成到 formal bench（C5）
```

---

## 核心约束（写报告/答辩时）

1. formal claim 只引用 `--embedding-mode local`（Qwen3-Embedding-0.6B）结果
2. CodeAct LLM 生成 5/5（generation_fallback_used=False）已在 rerun artifact 中验证
3. comparison_valid=False 是设计意图：质量优越路径（8/8 vs 6/8）不要求 external all-pass
4. task_ms_delta 的两个数字（-6,114ms vs +26,224ms）测量不同视角，均正确
5. stress_pass=3/6 是薄弱点，答辩时重点用 continuous replay 数据（15+10）补强
