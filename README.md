# StateBus 项目说明

当前仓库是 StateBus 的 host-side 实现仓库，主线目标是验证多 Agent 协作里的三类能力：

- 通信开销是否能下降
- 中间状态是否能以非纯文本方式传递
- 共享记忆是否能带来真实复用

如果你第一次进入这个仓库，先看这份 README；需要更细的环境细节、设计文档和 benchmark 报告，再进入对应文档。

## 1. 环境安装

推荐的 host 环境路径约定：

```text
$HOME/statebus/
├── conda-envs/
├── models/
├── caches/
├── logs/
├── runs/
└── work/
```

安装步骤：

```bash
cd /path/to/statebus
bash scripts/setup_host_dev_env.sh
source deploy/activate_statebus_host.sh
```

详细说明见：

- `docs/setup/host_environment.md`
- `docs/start_here.md`

## 2. API 配置

LLM 配置分成两部分：

- `deploy/statebus_llm.yaml.local`
  - provider / model / role 行为配置
- `deploy/statebus_llm.env.local`
  - `STATEBUS_LLM_API_KEY` 等本地敏感信息

推荐先复制模板：

```bash
cp deploy/statebus_llm.yaml.example deploy/statebus_llm.yaml.local
cp deploy/statebus_llm.env.example deploy/statebus_llm.env.local
```

然后只在本地 `.local` 文件里填真实 key。

不要提交：

- `deploy/statebus_llm.yaml.local`
- `deploy/statebus_llm.env.local`

## 3. 嵌入模型配置

默认 embedding 模型路径：

```text
$HOME/statebus/models/Qwen3-Embedding-0.6B
```

如果路径不同，可以覆盖：

```bash
export STATEBUS_EMBED_MODEL_PATH="/your/path/Qwen3-Embedding-0.6B"
```

设备默认是 `auto`，有 GPU 时建议显式指定：

```bash
export STATEBUS_EMBED_DEVICE=cuda:0
```

## 4. 项目结构

核心目录如下：

- `agents/`
  - `Planner / Retriever / Executor / Summarizer`
- `runtime/`
  - 编排、合同、LLM、远端执行入口
- `protocol/`
  - 消息结构、序列化、协议辅助逻辑
- `statepool/`
  - 状态池与 mmap / shared state backend
- `memory/`
  - SQLite + 向量检索记忆层
- `eval/`
  - benchmark runner、指标与报告生成
- `tasks/`
  - corpus、task 定义、benchmark pack
- `tests/`
  - smoke、runtime、protocol、memory、benchmark 相关测试
- `deploy/`
  - 激活脚本与配置模板
- `scripts/`
  - 环境初始化与维护脚本

## 5. 测试命令

基础验证：

```bash
python -m pytest -q
python -m runtime.smoke
```

benchmark 运行主入口在：

- `eval/runner.py`

默认 CLI task-set 当前指向：

- `contest_dual_mode_controlled_v3`
  - 当前正式 dual-mode headline
  - 同任务双模式对照：`text_strict_pure_lane` vs `state_packet_minimal`

v3 deterministic/local 综合检查入口会覆盖 12 个 active v3 pack；其中重点支持入口包括：

- `memory_dual_mode_fairness_v3`
  - dual-mode fairness/object-parity surface
  - 同任务双模式对照：`text_whole_lane` vs `state_packet_minimal`
- `typed_state_mechanism_v3`
  - protocol-only typed-state 机制包
  - 固定 `mode=protocol`、`runtime_reuse_contract=reuse_disabled`，同一 task object 下只比 `natural_handoff_text` vs `state_packet_minimal`
- `memory_policy_controlled_v3`
  - protocol-only memory policy attribution surface
  - 固定 `mode=protocol` 与 `transfer_strategy=state_packet_minimal`，只改变 `runtime_reuse_contract`
- `typed_state_consumer_sensitivity_v3`
  - formal-secondary typed-state consumer sensitivity pack
  - 固定 `mode=protocol`，验证 minimal `EXECUTOR_DECISION_PACKET` 被消费，且缺失/错误 packet 会导致 destructive-control 降级

任务与 pack 定义在：

- `tasks/`

## 6. 实验结果

当前 v3 active surface 与读法边界在：

- `docs/reports/MASTER_PRESENTATION_GUIDE.md`
- `docs/reports/task_design_and_mode_comparison.md`

历史结果/架构参考在：

- `docs/reports/architecture_and_data_flow.md`
- `docs/reports/benchmark_results_interpretation_20260610.md`

这些历史报告保留了 v1/v2 pack 名称、旧任务数或旧运行包数据时，只能作为背景材料；当前 v3 formal 结论以 active v3 pack 的 manifest/report/gate 为准。

当前 active benchmark surface 使用 12 个 v3 pack：

- `contest_dual_mode_controlled_v3`
- `memory_dual_mode_fairness_v3`
- `typed_state_mechanism_v3`
- `external_text_baseline_audit_v3`
- `text_definition_audit_v3`
- `typed_state_authenticity_v3`
- `typed_state_full_rich_audit_v3`
- `carrier_microbench_v3`
- `memory_reuse_v3`
- `memory_policy_controlled_v3`
- `planner_support_v3`
- `typed_state_consumer_sensitivity_v3`

读法边界：

- `contest_dual_mode_controlled_v3` 是当前正式双模式 headline。`text` 的正式定义是 `text_strict_pure_lane`，读法固定为 `text_strict_pure_lane` vs `state_packet_minimal` 这组受控 mainline handoff object。
- 当前 `contest_dual_mode_controlled_v3` 已收紧为 stronger multi-route formal contract：clean / distractor / ambiguous / reusable 都要求 route 竞争集，且 reusable 显式携带 prior dependency / prior rejection 合同。
- 当前 contest formal retrieval 按 structure-level clean 读取：formal corpus 不暴露 runtime hint，formal retrieval 不再注入 preferred-doc shortlist，也不再依赖 theme/group bonus 托举 formal 候选空间。
- `text_strict_pure_lane` 仍是 StateBus runtime 内部的 strict text lane：executor 不接 typed state ref，但仍复用同一套 lexical route/tool helper path 与 playbook executor。
- `text_whole_lane` 是内部 whole-lane text audit object；两者都不是 external traditional pure-text multi-agent baseline。
- `memory_dual_mode_fairness_v3` 是保留的 dual-mode fairness/object-parity surface；不承担 replay proof。
- `typed_state_mechanism_v3` 只回答 `natural_handoff_text` vs `state_packet_minimal(DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET)` 是否真实生产、传递、消费；不读成 dual-mode headline，也不读成 replay 结论。
- `external_text_baseline_audit_v3` 是独立 external text baseline audit surface；先做 audit-only，不并入 contest headline 或 typed-state 机制 claim。
- `text_definition_audit_v3` 只负责 executor-boundary inline text 审计，不负责 formal headline。
- `typed_state_authenticity_v3` 只保留 legacy compatibility surface；正式机制 claim 优先读 `typed_state_mechanism_v3`。
- `typed_state_full_rich_audit_v3` 只保留 full-rich support/audit，不进 formal headline。
- `carrier_microbench_v3` 是 engineering audit only，不读成 “纯文本 vs structured” 正式 headline。
- `memory_policy_controlled_v3` 负责 protocol-only replay policy 归因；`memory_reuse_v3` 保留 protocol-only replay proof surface。
- `planner_support_v3` 是独立的 planner support/formal-secondary surface：它受控比较 `plan_source=yaml` 与 `plan_source=llm`，用于证明系统覆盖规划角色并支持开放 planner，但不并入 `contest_dual_mode_controlled_v3` 的 communication headline。
- `typed_state_consumer_sensitivity_v3` 是 formal-secondary support surface，只说明 minimal `EXECUTOR_DECISION_PACKET` 被生产、传递、消费，且缺失/错误 packet 会导致 destructive-control 降级；不升格为主 headline。
- `open_system_comparison_v1` 是独立 open engineering comparison surface，由 `eval/open_runner.py` 生成，不并入 `eval.runner` 的 formal v3 headline。

当前脚本入口：

- `scripts/run_v3_comprehensive_check.py` 是 v3 deterministic/local 综合检查入口。
- `scripts/run_v3_next_stage_repeat3_suite.py` 是下一阶段 post-gate repeat suite 入口；它会先跑 `memory_dual_mode_fairness_v3 repeat=1 deterministic` 和 `typed_state_consumer_sensitivity_v3 repeat=1 deterministic` gate，失败则退出。该入口在 gate 通过前只能读成 smoke-capable launcher，不是 formal repeat evidence 入口。
- `scripts/nohup_v3_next_stage_repeat3_suite.sh` 是后台启动包装入口，会写入 `PID`、`COMMANDS.md`、`SUMMARY.md` 和 `logs/launcher.log`。
- `scripts/run_v2_comprehensive_check.py` 和 `scripts/run_v2_api_repeat3_suite.py` 是 archived v2 入口，默认不应作为交付主入口。

当前环境、benchmark 设计与结果边界相关的详细材料在：

- `docs/planning/`
- `docs/analysis/`

说明：

- 仓库提交代码、任务定义、报告文档和配置模板
- 本地 `runs/` 结果产物默认不进 git

## 7. 建议先读什么

如果你要快速理解当前主线，建议先看：

1. `docs/constraints/current_host_and_migration.md`
2. `docs/constraints/current_feature_scope.md`
3. `docs/setup/host_environment.md`
4. `docs/reports/MASTER_PRESENTATION_GUIDE.md`

## 8. 历史说明

之前较长的 host-side 背景、验证快照和仓库角色说明已移到：

- `docs/reference/readme_archive_20260611.md`
