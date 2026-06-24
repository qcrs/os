# StateBus Snapshot

这个仓库分支是从 `statebus/project` 同步出来的精简快照，用于对外阅读、复核当前实现与最新正式结果。

当前同步来源：

- source repo: `/home/qcrs/statebus/project`
- source branch: `feat/taskset-mainline-split`
- source revision: `99685b6`

## 先看什么

如果你第一次读这个项目，建议按下面顺序看：

1. `docs/reports/statebus_system_method_task_and_results_explainer.md`
2. `docs/reader_guide/README.md`
3. `docs/reports/current_task_results_overview_20260622.md`
4. `docs/reports/current_architecture_overview_20260622.md`
5. `docs/reference/题目.md`

## 当前正式读法

当前 active headline 只有：

- `superiority_comm_v1`

当前 formal-secondary support 包括：

- `typed_state_mechanism_v3`
- `typed_state_consumer_sensitivity_v3`
- `superiority_memory_v1`

当前必须明确区分：

- `Communication gate`
- `Formal stability gate`

## 这份快照保留了什么

1. 核心实现代码
   - `agents/`
   - `runtime/`
   - `protocol/`
   - `statepool/`
   - `memory/`
   - `eval/`
   - `tasks/`
   - `scripts/`
   - `deploy/`
   - `tests/`
2. 当前主阅读面
   - `docs/reader_guide/`
   - `docs/reports/statebus_system_method_task_and_results_explainer.md`
   - `docs/reports/current_task_results_overview_20260622.md`
   - `docs/reports/current_architecture_overview_20260622.md`
   - `docs/reference/题目.md`
3. 最小实验结果集
   - `runs/superiority_comm_v1_api_repeat3_post_gate_semantics_split/`
   - `runs/superiority_comm_v1_api_repeat1_post_summarizer_schema_native_contract_repair/`
   - `runs/typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623/`
   - `runs/typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623/`
   - `runs/superiority_memory_v1_api_repeat3_post_replay_contract_hardening/`

每个 `runs/*` 目录只保留三个核心文件：

- `benchmark_report.md`
- `benchmark_results.json`
- `benchmark_compare.csv`

## 这份快照故意没有保留什么

为了避免历史噪音和超大体积，这里没有同步：

- 全量 `runs/` 历史产物
- `third_party/`
- `docs/analysis/`
- `docs/progress/`
- `docs/review/`
- 其他历史审计、草稿和冻结前提示材料

## 基础命令

环境激活：

```bash
source deploy/activate_statebus_host.sh
```

基础验证：

```bash
python -m pytest -q
python -m runtime.smoke
```

benchmark 主入口：

```bash
python -m eval.runner
```
