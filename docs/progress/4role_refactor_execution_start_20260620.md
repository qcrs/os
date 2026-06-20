# 4-Role Refactor Execution Start

日期：2026-06-20
主合同：`docs/planning/statebus_4_role_comparator_contract_20260620.md`
实施计划：`docs/planning/statebus_four_llm_refactor_implementation_plan_20260620.md`

## 1. 执行前提

本轮按用户要求执行真实重构，不做 brainstorming，不做 review-only。

执行边界固定为：

- 只在当前 Linux host 环境下工作
- 使用 `deploy/activate_statebus_host.sh`
- 不进入 VM / openEuler / Docker / `nsjail`
- 不破坏已有 `contest_honest_headline_v1` 语义
- 合同冲突时以主合同为准

## 2. 执行前阅读完成情况

已完成阅读：

- 主合同与实施计划
- 赛题原文与仓库主说明
- host 约束与当前 feature scope
- 原总实施计划
- 4-role 相关分析/诊断/设计背景
- 本轮要求涉及的核心实现文件

## 3. 当前分支与工作区处理

执行开始时分支：

- `feat/active-surface-and-external-text-baseline-20260619`

工作区处理策略：

- 先记录 dirty worktree 基线
- 将当前相关改动保存为 checkpoint commit
- 在干净工作树上新建实施分支

## 4. 本轮目标

严格基于主合同与实施计划，推进：

- Phase 0：对齐、清理、分支、起始记录
- Phase 1：role-level runtime 抽象准备
- Phase 2：fairness / contract enforcement

## 5. 本轮计划 phase

计划按以下顺序执行：

1. Phase 0
2. Phase 1
3. Phase 2

阶段边界：

- Phase 1 仅触达：
  - `runtime/llm.py`
  - `eval/metrics.py`
  - `runtime/role_contracts.py`
  - `runtime/context_slice.py`
- Phase 2 仅触达：
  - `runtime/orchestrator.py`
  - `runtime/langgraph_adapter.py`
  - `eval/fairness_gates.py`
- Phase 1/2 通过前：
  - 不进入全面 4-agent semantic 重写
  - 不先改 external pure-text baseline
  - 不跑大规模 API

## 6. 起始验收要求

每个 phase 完成后至少执行相关最小测试，并记录：

- 运行了哪些测试
- 没运行哪些测试
- 原因

## 7. 当前状态

本文件写入时，仍处于 Phase 0，尚未开始 Phase 1 代码实现。
