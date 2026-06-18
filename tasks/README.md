# Tasks

当前正式 benchmark 入口只保留 v3 pack。

默认 CLI pack：

- `contest_dual_mode_controlled_v3_benchmark.yaml`
  - `contest_dual_mode_controlled_v3`
  - 默认 formal surface
  - 同任务对象下只改 `mode + handoff_profile`

重点支持/audit pack：

- `memory_dual_mode_fairness_v3_benchmark.yaml`
  - `memory_dual_mode_fairness_v3`
  - dual-mode fairness/object-parity audit surface，不承担 replay proof
  - 同任务对象下只改 `mode + memory policy + compatible restore object class`
- `typed_state_mechanism_v3_benchmark.yaml`
- `typed_state_mechanism_v3`
  - protocol-only formal-secondary 机制包
  - 同任务对象下固定 `mode=protocol` 与 `runtime_reuse_contract=reuse_disabled`，只改 `natural_handoff_text` vs `state_packet_minimal`
- `external_text_baseline_audit_v3_benchmark.yaml`
  - `external_text_baseline_audit_v3`
  - 独立 external text baseline audit surface
  - 不并入 formal headline

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

说明：

- 正式 README、默认 CLI、正式 smoke、正式 report 只认以上 13 个 v3 对象。
- 主动脚本入口是 `scripts/run_v3_comprehensive_check.py`；`scripts/run_v2_*` 只保留归档/考古用途，默认拒绝运行。
- `contest_honest_headline_v1` 是当前 contest-facing formal dual-mode surface，headline baseline 为 `text_whole_lane` vs `state_packet_minimal`。
- `contest_dual_mode_controlled_v3` 是内部 controlled composite surface，保留 `text_strict_pure_lane` vs `state_packet_minimal` 的 mainline handoff 对照，不再承担 contest-facing pure-text headline。
- `memory_dual_mode_fairness_v3` 是保留 pack；当前只读 dual-mode fairness/object parity，不承担 replay proof。
- `typed_state_mechanism_v3` 只读 protocol-only `natural_handoff_text` vs `state_packet_minimal` 机制真实性；不读成 dual-mode headline。
- `external_text_baseline_audit_v3` 只读独立 external text baseline 审计；不并入当前正式 headline。
- `memory_policy_controlled_v3` 只读 protocol + state_packet_minimal 固定后的 memory policy 单变量归因。
- `typed_state_authenticity_v3` 只保留 legacy compatibility surface，正式机制 claim 仍优先读 `typed_state_mechanism_v3`。
- `text_definition_audit_v3` 只读 boundary 定义，不读成 formal headline。
- `carrier_microbench_v3` 只读 engineering audit。
- `typed_state_consumer_sensitivity_v3` 只读 minimal `EXECUTOR_DECISION_PACKET` 消费与负控降级，不升格为 typed-state 机制主 headline。
- 当前 formal v3 已切 surface，但系统机制真实性仍在审计中。
- 若 `state_packet_minimal` 的 `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` 未被 executor 真实消费，`typed_state_mechanism_v3` 必须 withheld。
- `contest_dual_mode_controlled_v3` 当前按 stronger multi-route formal contract 读取：clean / distractor / ambiguous / reusable 都要求 route 竞争集，且 reusable 要显式携带 prior dependency 合同。
- 当前 contest formal retrieval 按 structure-level clean 读取：formal corpus 不暴露 runtime hint，formal retrieval 不再注入 preferred-doc shortlist，也不再依赖 theme/group bonus 托举候选空间。
- 若 `memory_dual_mode_fairness_v3` 的 text restore 兼容性或 object parity gate 未过，不得输出 audit fairness 通过结论。
- `tasks/state_ref_consumer_sensitivity_audit_benchmark.yaml` 是 mechanism audit pack；既逐类关闭 rich typed-state ref 审计 helper-path 复用，也对 minimal packet 做缺包/错包负控。
