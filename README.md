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

默认 CLI `--task-set` 读取的是
`tasks/contest_dual_mode_controlled_v3_benchmark.yaml` 这份 benchmark 文件；
它会物化多个 named pack。当前最常用、且与现行读法直接相关的对象包括：

- `contest_dual_mode_controlled_v3`
  - 当前内部 controlled composite surface
  - 同任务双模式对照：`text_strict_pure_lane` vs `state_packet_minimal`
- `contest_honest_headline_v1`
  - 当前历史保留的 carrier-isolation / mechanism object
  - 同任务双模式对照：`text_whole_lane` vs `state_packet_minimal`
- `superiority_comm_v1`
  - 当前 active communication headline object
  - 读法收窄到 `llm_total_tokens`、`task_ms` 与 `quality floor`
- `superiority_memory_v1`
  - 当前 formal-secondary memory effect object
  - 最终角色是 final report required secondary verdict

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

当前 registry 里保留多组 v3 named packs；当前正式可引用的主对象应按
`headline / secondary / audit` 分层来读，而不是再把所有 pack 混成一个 headline。

当前直接相关的对象至少包括：

- `superiority_comm_v1`
- `superiority_memory_v1`
- `typed_state_mechanism_v3`
- `typed_state_consumer_sensitivity_v3`
- `contest_honest_headline_v1`
- `contest_dual_mode_controlled_v3`
- `planner_support_v3`
- `memory_policy_controlled_v3`
- `memory_reuse_v3`
- `external_text_baseline_audit_v3`
- `text_definition_audit_v3`
- `typed_state_authenticity_v3`
- `typed_state_full_rich_audit_v3`
- `carrier_microbench_v3`

读法边界：

- `superiority_comm_v1` 是当前 active communication headline object。它只回答 communication 的 `llm_total_tokens`、`task_ms` 与 `quality floor`；当前仍要区分 `Communication gate` 与 `Formal stability gate`，不能把正向 aggregate 自动上读成 closure。
- `superiority_memory_v1` 是当前 formal-secondary memory effect object。它回答 replay effect 是否成立；当前最终角色是 final report required secondary verdict，不承担 communication headline，也不承担 overall superiority closure。
- `typed_state_mechanism_v3` 与 `typed_state_consumer_sensitivity_v3` 一起承担当前 non-text state-transfer formal-secondary evidence。它们回答 minimal typed packet 是否被真实生成、传递、接收、消费，以及缺失/错误 packet 是否会触发 failure 或 misfire；当前最终角色应读成 required secondary state-transfer verdict。
- `contest_honest_headline_v1` 已降读为历史保留的 carrier-isolation / mechanism object。它保留 `text_whole_lane` vs `state_packet_minimal` 这组对照，用于证明 structured carrier / typed-state minimal packet / frozen purity-parity-stability 边界，不再承担 overall superiority headline。
- `contest_superiority_headline_v2` 只保留历史 scaffold 参考价值；当前 communication source-of-truth 不再从它读取。
- `contest_dual_mode_controlled_v3` 降为内部 controlled composite surface。它保留 `text_strict_pure_lane` vs `state_packet_minimal` 这组受控 mainline handoff object，但不再承担 contest-facing pure-text headline。
- 当前 `contest_dual_mode_controlled_v3` 已收紧为 stronger multi-route formal contract：clean / distractor / ambiguous / reusable 都要求 route 竞争集，且 reusable 显式携带 prior dependency / prior rejection 合同。
- 当前 contest formal retrieval 按 structure-level clean 读取：formal corpus 不暴露 runtime hint，formal retrieval 不再注入 preferred-doc shortlist，也不再依赖 theme/group bonus 托举 formal 候选空间。
- `text_strict_pure_lane` 仍是 StateBus runtime 内部的 strict text lane：executor 不接 typed state ref，但仍复用同一套 lexical route/tool helper path 与 playbook executor。
- `text_whole_lane` 现在同时承担 contest-facing natural-language whole-lane text headline object；它仍不是 external traditional pure-text multi-agent baseline。
- `memory_dual_mode_fairness_v3` 是保留的 dual-mode fairness/object-parity surface；不承担 replay proof。
- `external_text_baseline_audit_v3` 是独立 external text baseline audit surface；先做 audit-only，不并入 contest headline 或 typed-state 机制 claim。
- `text_definition_audit_v3` 只负责 executor-boundary inline text 审计，不负责 formal headline。
- `typed_state_authenticity_v3` 只保留 legacy compatibility surface；正式机制 claim 优先读 `typed_state_mechanism_v3`。
- `typed_state_full_rich_audit_v3` 只保留 full-rich support/audit，不进 formal headline。
- `carrier_microbench_v3` 是 engineering audit only，不读成 “纯文本 vs structured” 正式 headline。
- `memory_policy_controlled_v3` 负责 protocol-only replay policy 归因；`memory_reuse_v3` 保留 protocol-only replay proof surface。
- `planner_support_v3` 是独立的 planner support/formal-secondary surface：它受控比较 `plan_source=yaml` 与 `plan_source=llm`，用于证明系统覆盖规划角色并支持开放 planner，但不并入 contest communication headline。
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
