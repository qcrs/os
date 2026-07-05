# Tasks

当前文件是任务包和 benchmark object 的索引文档。它回答三件事：

1. 当前有哪些正式 pack / object。
2. 每个 object 回答什么，不回答什么。
3. 哪些 object 只是历史或 audit，不应混成当前主结论。

当前 active headline / support / audit 口径应优先以：

- `docs/reports/current_task_results_overview_20260622.md`
- `docs/planning/statebus_contest_requirement_first_split_execution_plan_20260621.md`
- 对应 authoritative `runs/*/benchmark_report.md`

为准。

## 1. 当前主对象分层

当前 object 应按 `headline / formal-secondary / audit / historical` 分层读取。

### headline

- `superiority_comm_v1`
  - 当前 active communication headline
  - 只回答 communication 的 `llm_total_tokens`、`task_ms` 与 `quality floor`

### formal-secondary

- `superiority_memory_v1`
  - replay effect / exact-replay-backed effect
- `typed_state_mechanism_v3`
  - protocol-only typed-state mechanism surface
- `typed_state_consumer_sensitivity_v3`
  - minimal decision packet consumer sensitivity / destructive negative control
- `planner_support_v3`
  - planner support surface
- `memory_policy_controlled_v3`
  - protocol-only memory policy attribution
- `memory_reuse_v3`
  - protocol-only replay proof surface

### audit

- `memory_dual_mode_fairness_v3`
- `external_text_baseline_audit_v3`
- `text_definition_audit_v3`
- `carrier_microbench_v3`
- `typed_state_full_rich_audit_v3`

### historical / legacy

- `contest_honest_headline_v1`
  - 历史 frozen formal headline / carrier-isolation object
- `contest_dual_mode_controlled_v3`
  - 当前只读 internal controlled composite surface
- `typed_state_authenticity_v3`
  - legacy compatibility surface

## 2. 正式 v3 packs

正式 v3 packs：

- `contest_dual_mode_controlled_v3_benchmark.yaml`
  - `contest_dual_mode_controlled_v3`
- `memory_dual_mode_fairness_v3_benchmark.yaml`
  - `memory_dual_mode_fairness_v3`
- `typed_state_mechanism_v3_benchmark.yaml`
  - `typed_state_mechanism_v3`
- `external_text_baseline_audit_v3_benchmark.yaml`
  - `external_text_baseline_audit_v3`
- `text_definition_audit_v3_benchmark.yaml`
  - `text_definition_audit_v3`
  - strict pure-text boundary 与 protocol inline boundary 分离审计
- `typed_state_authenticity_v3_benchmark.yaml`
- `typed_state_authenticity_v3`
  - protocol natural text vs `state_packet_minimal` 真实性，保留为 formal-secondary legacy compatibility surface
- `typed_state_full_rich_audit_v3_benchmark.yaml`
  - `typed_state_full_rich_audit_v3`
  - protocol natural text vs explicit full-rich audit typed state support/audit
- `carrier_microbench_v3_benchmark.yaml`
  - `carrier_microbench_v3`
  - minimal text/state packet engineering audit
- `memory_reuse_v3_benchmark.yaml`
  - `memory_reuse_v3`
- `memory_policy_controlled_v3_benchmark.yaml`
  - `memory_policy_controlled_v3`
  - protocol carrier-fixed memory policy 单变量归因
- `planner_support_v3_benchmark.yaml`
- `planner_support_v3`
- `state_ref_consumer_sensitivity_audit_benchmark.yaml`
  - `typed_state_consumer_sensitivity_v3`
  - minimal decision packet consumer-sensitivity / negative-control support surface

## 3. 读法边界

- `superiority_comm_v1` 是当前 active communication headline，当前 formal 读法不再从 `contest_honest_headline_v1` 读取。
- `superiority_memory_v1` 只回答 replay effect，不回答 memory superiority 或 overall superiority。
- `typed_state_mechanism_v3` 与 `typed_state_consumer_sensitivity_v3` 一起组成当前 non-text state-transfer formal-secondary evidence。
- 正式机制 claim 仍优先读 `typed_state_mechanism_v3`；`typed_state_authenticity_v3` 只保留 legacy compatibility surface。
- `memory_policy_controlled_v3` 只读 protocol + state_packet_minimal 固定后的 memory policy 单变量归因。
- `external_text_baseline_audit_v3` 只读独立 external text baseline 审计，不并入 formal headline。
- `contest_honest_headline_v1` 是历史 frozen object，可用于展示历史对照与机制边界，但不是当前 active source-of-truth。
- `contest_dual_mode_controlled_v3` 是内部 controlled composite surface，不再承担 contest-facing pure-text headline。
- `tasks/state_ref_consumer_sensitivity_audit_benchmark.yaml` 是 mechanism audit pack；它既做 rich helper visibility audit，也做 minimal packet 缺包/错包负控。

## 4. 入口脚本

- `scripts/run_v3_comprehensive_check.py`
  - 当前 v3 deterministic/local 综合检查入口
- `scripts/run_v2_*`
  - archived / archaeology only
