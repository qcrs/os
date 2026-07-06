# Evidence Log

审计日期：2026-07-06

## 赛题约束

- 赛题要求至少 3 Agent、结构化协议、上下文/状态压缩、共享记忆检索复用、双模式对比、至少 2 组连续任务、10 轮稳定与 openEuler 最终交付。
- 事实源：`docs/reference/题目.md`、`docs/reference/赛题9设计讲解压缩稿.md`。
- 当前仓库事实：v2 正式控制面是 `UDS + typed Protobuf`，数据面按对象类型分层；openEuler 仍只能说待 VM 验证，不能说已验证。

## 最新 full audit

- 最新完整结果：`/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/summary.latest.json`
- 关键字段：`stage_count=16`、`failed_stage_count=0`、`failed_stages=[]`。
- 对应代码提交：运行目录 env probe 记录为当时 full audit run；当前代码 HEAD 为 `be74494 Harden external fairness gate raw payload checks`，之后本轮会新增审计修复提交。

## Formal evidence

Artifact:

`/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/07_formal_primary/stdout.json`

关键字段：

- `waterfall_metrics.L0_case_count=8`
- `waterfall_metrics.L3_quality_floor_pass_count=8`
- `waterfall_metrics.L2_semantic_state_transfer_count=8`
- `waterfall_metrics.L3_reuse_gain=0`
- `comparison_summary.control_bytes_delta_l0_to_l1=360`
- `comparison_summary.pruning_bytes_saved_vs_l0=6255`

审计判断：formal financial 是 precision anchor 和结构化控制/语义状态传递证据，不是 replay gain 或 broad reasoning superiority 证据。

## External fairness evidence

最新 raw fairness 修复后证据：

`/home/qcrs/statebus/runs/codex-raw-fairness-20260706/runtime/benchmark_reports/codex-raw-fairness-20260706-cold-start-compare-api.json`

关键字段：

- `fairness_manifest.pass_hard_gate=true`
- `fairness_manifest.external_fairness_gate_coverage=true`
- `fairness_manifest.no_external_fairness_gate_failures=true`
- `fairness_manifest.external_fairness_gate_failed_case_count=0`
- `fairness_manifest.external_fairness_gate_failed_check_count=0`

Suite-level claim boundary:

`/home/qcrs/statebus/runs/codex-raw-fairness-20260706/runtime/benchmark_reports/codex-raw-fairness-20260706-cold-start-compare.json`

- `metadata.fixed_answer_external_comparison_valid=true`
- `metadata.external_comparator_claim_scope=dev_fixed_answer_only`
- `metadata.formal_headline_eligible=false`
- `metadata.formal_superiority_claim_allowed=false`
- `comparison_summary.api_llm_total_tokens_delta=-1023`
- `comparison_summary.api_prompt_bytes_delta=-4992`
- `comparison_summary.api_control_bytes_delta=-351`
- `comparison_summary.api_task_ms_delta=9906.00388`

审计判断：支持 dev fixed-answer 外部 baseline 公平性与 token/prompt/control exposure 降低；不支持 formal superiority 或端到端速度胜利。

## Replay / reuse evidence

Artifact:

`/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/10_continuous_replay_collection_primary/stdout.json`

关键字段：

- `collection_summary.family_count=3`
- `collection_summary.continuous_round_count=30`
- `collection_summary.replay_target_round_count=20`
- `collection_summary.replay_observed_round_count=20`
- `collection_summary.replay_missing_target_round_count=0`
- `collection_summary.validated_replay_count=17`
- `collection_summary.exact_replay_count=3`
- `collection_summary.L2_semantic_state_transfer_count=30`
- `collection_summary.L3_artifact_reuse_count=39`
- `collection_summary.L3_reuse_gain=20`

代码证据：

- contract compatibility 只比对 family / intent / tools / outputs / argument shape：`v2/runtime/replay.py:349`
- 测试明确允许同 shape 不同 ticker 的 validated replay：`tests/v2/test_replay.py:236`
- 本轮修复增加保守指标别名，避免把 validated replay 误读为 exact answer restoration：`v2/runtime/driver.py:1215`

审计判断：应对外称为 exact replay + validated downgraded reuse / strategy-backed reuse，不应笼统称为安全恢复答案。

## Structured / non-text state evidence

代码证据：

- `SemanticStateRef` 与 `ExecutionArtifactRef` 分离：`v2/refs/models.py:50`、`v2/refs/models.py:77`
- `ExecutionArtifactRef.registry_entry()` 使用 `StorageKind.WORKSPACE_ROOT`：`v2/refs/models.py:93`
- `LayeredStoragePolicy` 对 `EMBEDDING_STATE` / `DENSE_SEMANTIC_STATE` 首选 `SHARED_MEMORY`，fallback 到 `MMAP_FILE`：`v2/state/store.py:22`
- `LayeredStateStore.publish()` materialize 真实 payload：`v2/state/store.py:150`
- shared memory materialization：`v2/state/store.py:246`
- mmap materialization：`v2/state/store.py:270`
- memfd ref 编解码和 subprocess transport：`v2/control/transport.py:260`、`v2/control/transport.py:306`
- memfd subprocess e2e test：`tests/v2/test_control_plane.py:95`

Benchmark 证据：

`/home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/15_flagship_ablation_primary/stdout.json`

- `non_text_state_stress_summary.stress_family_count=6`
- `non_text_state_stress_summary.stress_pass_family_count=4`
- `non_text_state_stress_summary.total_llm_prompt_saved_by_state_ref_bytes=22208`
- `non_text_state_stress_summary.total_prompt_visible_saved_by_state_ref_bytes=8409`

审计判断：非文本 StateRef 有代码主路径和 stress benchmark 证据；memfd 是能力/e2e 证据，不是 formal/compare 主 benchmark 证据。

## Memory store evidence

- `v2/memory/store.py` 当前 `lookup_by_tags()` 已有 SQL `LIKE` 粗筛，不再是旧审计中“完全不按 tag 过滤”的状态。
- FAISS 路径已有 normalize 测试覆盖；旧 `05_memory_and_replay_complete_design.md` 对 FAISS 未实装的结论已过时。

## Fairness gate code evidence

- raw role JSON 和 raw choices 参与 gate：`v2/benchmark/external_text_baseline.py:111`
- 外部 baseline 不再 revenue fallback gold：`v2/benchmark/external_text_baseline.py:542`
- comparator hard gate 要求 fairness coverage 和 no failures：`v2/benchmark/comparator_runner.py:142`、`v2/benchmark/comparator_runner.py:157`

## 本轮修复证据

- `scripts/run_v2_full_container_audit_suite.sh`：
  - socket path 纳入 run id：`short_socket_path()`。
  - summary 解析 `key_metrics`。
- `v2/runtime/driver.py`：
  - 新增 `validated_downgraded_reuse_count`。
  - 新增 `answer_restoration_replay_count`。
- `v2/benchmark/continuous_runner.py`：
  - continuous suite / collection / evidence pack 透出 replay 保守别名。
- `tests/v2/test_continuous_runner.py`：
  - 增加 regression assertions。
