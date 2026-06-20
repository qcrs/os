# Worktree Baseline Before 4-Role Refactor

日期：2026-06-20
仓库：`/home/qcrs/statebus/project`

## 1. 目的

在开始 `4-role paired comparator` 重构前，先固化当前工作区状态，满足：

- 先记录 dirty worktree
- 先说明后续安全清理方式
- 不静默丢弃任何已有改动

## 2. 当前分支

- `feat/active-surface-and-external-text-baseline-20260619`

## 3. 当前 git 状态

执行命令：

```bash
git status --short --branch
git diff --stat
```

`git status --short --branch` 结果摘要：

- 当前分支存在未提交修改
- 已修改文件：
  - `agents/sample_agents.py`
  - `docs/reports/MASTER_PRESENTATION_GUIDE.md`
  - `eval/open_runner.py`
  - `eval/runner.py`
  - `eval/text_open_baseline.py`
  - `runtime/executor_runtime.py`
  - `runtime/task_profile.py`
  - `tasks/sample_tasks.py`
  - `tests/test_llm_runtime.py`
  - `tests/test_smoke.py`
- 未跟踪文件：
  - 多个 `docs/analysis/*.md`
  - 多个 `docs/planning/*.md`
  - 多个 `scripts/*.py`
  - 多个 `tasks/*.yaml`

`git diff --stat` 结果摘要：

- 已跟踪改动共 `10` 个文件
- 统计为 `1700 insertions(+), 41 deletions(-)`

## 4. 当前状态判断

当前 dirty worktree 不是无关噪音；它与以下主线直接相关：

- frozen headline 冻结与切片
- external pure-text baseline 审计/合同
- 4-role comparator 诊断与重构前分析

因此本轮不做 destructive cleanup，也不做静默回退。

## 5. 计划采用的安全清理方式

采用：

- 先写本记录文档
- 再做 checkpoint commit 保存当前树状态
- 在工作树干净后新建 `4-role comparator` 实施分支

不采用：

- `git reset --hard`
- `git checkout --`
- 静默删除未跟踪文件

## 6. 与本轮重构的关系

本文件只记录进入 `4-role comparator` 重构前的基线状态，不代表 Phase 1/2 已开始实现。
