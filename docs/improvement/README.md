# StateBus v2 改进计划

**审计基准**：HEAD `0dff814`，实验数据 `v2_experiment_summary_20260703.md`
**代码路径**：基于实际代码探索，所有行号均已核实

---

## 当前评分预估

| 评分维度 | 满分 | 当前预估 | 核心缺口 |
|---|---|---|---|
| 通信效率 | 25 | 19~22 | efficiency gate 路径未在报告中明确展示 |
| 状态传递创新 | 20 | 13~16 | shm 只在 L2 continuous，四环节文档未系统化 |
| 记忆复用 | 20 | 15~18 | CANDIDATE 只能 assist，FTS/标签检索缺失 |
| 系统完整性 | 20 | 14~17 | 同进程顺序、任务多样性不足 |
| 实验验证 | 15 | 10~13 | CodeAct LLM 生成 0%，overhead 未分解 |
| **合计** | **100** | **71~86** | |

---

## 文件索引

| 优先级 | 文件 | 解决的核心问题 |
|---|---|---|
| **P0** | `01_p0_critical_fixes.md` | CodeAct 生成、memory 设计、claim 路径 |
| **P0** | `02_competition_claim_hardening.md` | 竞赛声明精确表述与答辩防御 |
| **P1** | `03_agent_role_and_task_redesign.md` | 3类任务、角色真实性、10轮连续 |
| **P1** | `04_codeact_and_sandbox_hardening.md` | CodeAct 完整修复（代码级） |
| **P1** | `05_memory_and_replay_complete_design.md` | SQLite FTS、replay 完整实现 |
| **P1** | `07_non_text_state_transfer_audit.md` | 非文本传递四环节审计 |
| **P1** | `08_performance_and_overhead_breakdown.md` | overhead 分解与答辩口径 |
| **P2** | `06_kv_cache_implementation.md` | KV Cache 机制（保留原文） |

---

## 执行顺序

```
P0（并行）：01 CodeAct 修复 + 02 claim 口径确认
    ↓
P1-a（并行）：04 CodeAct 深度修复 + 05 memory FTS
    ↓
P1-b（并行）：03 新任务族 + 07 非文本传递加固
    ↓
P1-c：08 overhead 报告字段实现
    ↓
P2：06 KV Cache（时间允许）
```

---

## 核心约束（写报告/答辩时）

1. formal claim 只引用 `--embedding-mode local`（Qwen3-Embedding-0.6B）结果
2. CodeAct 必须区分两条路径：bwrap 执行稳定（8/8）≠ LLM 生成稳定（0/3）
3. memory_match_count=0 在 formal compare 是正确行为（cold-start），与 skipped_steps=19 不矛盾
4. task_ms_delta 的两个数字（-4,772ms vs +28,391ms）测量的是不同视角，均正确
