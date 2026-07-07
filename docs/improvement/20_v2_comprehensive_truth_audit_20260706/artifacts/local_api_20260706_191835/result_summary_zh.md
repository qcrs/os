# local+api 全面测试结果汇总

运行 ID：`v2-local-api-20260706_191835`

模式：

- `role_path_mode=api`
- `embedding_mode=local`
- formal / compare / carrier compare 使用 `--state-pool-mode memfd`
- 每个 stage 使用独立 `runtime_root` / `workspace_root`
- AF_UNIX socket 使用短路径 `/tmp/sb2-<16hex>.sock`，本次未出现 socket path 过长问题

结果位置：

- 主结果目录：`/home/qcrs/statebus/runs/v2-local-api-20260706_191835/artifacts`
- 审计目录副本：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260706_191835/`

## 总体结论

本轮 `local+api` 全面测试完成，13 个 stage 全部 exit 0，required stage 失败数为 0。

总耗时按 stage duration 求和为 6374 秒，约 1 小时 46 分 14 秒。

最重要的新证据：

- API + local embedding preflight 通过，使用 `/statebus/models/Qwen3-Embedding-0.6B` 和 `cuda:0`。
- formal internal benchmark 在 API + local + memfd 下 25/25 通过，覆盖 5 个 formal families。
- formal internal benchmark 记录 25 次 memfd transfer / publish，`memfd_bytes_transferred=247076`。
- formal internal benchmark 中四角色 API call telemetry 均为 25：planner / retriever / executor / summarizer 各 25 次。
- continuous replay API + local 跑通：30 rounds，20 个 replay target 全部 observed，validated replay 17，exact replay 3，`answer_restoration_replay_count=0`。
- replay negative audit 7/7 pass。
- flagship ablation 跑通，但 stress pass 为 4/6，不应表述为全部 stress family 通过。

## Stage 状态

| Stage | Required | Exit | 耗时 |
|---|---:|---:|---:|
| `00_env_probe` | 1 | 0 | 0s |
| `01_py_compile` | 1 | 0 | 0s |
| `02_pytest_focused_v2` | 1 | 0 | 383s |
| `03_runtime_smoke` | 1 | 0 | 36s |
| `r01_04_preflight_api_local` | 1 | 0 | 3s |
| `r01_05_formal_api_local_memfd` | 1 | 0 | 866s |
| `r01_06_formal_compare_api_local_memfd` | 1 | 0 | 122s |
| `r01_07_dev_compare_api_local_memfd` | 0 | 0 | 51s |
| `r01_08_carrier_compare_api_local_memfd` | 0 | 0 | 55s |
| `r01_09_continuous_api_local` | 0 | 0 | 1067s |
| `r01_10_continuous_replay_api_local` | 0 | 0 | 1051s |
| `r01_11_replay_negative_api_local` | 1 | 0 | 3s |
| `r01_12_flagship_ablation_api_local` | 0 | 0 | 2737s |

## 核心指标

### API + local preflight

- `preflight_ok=True`
- `embedding_model_path=/statebus/models/Qwen3-Embedding-0.6B`
- `embedding_device=cuda:0`
- `llm_config_source=/workspace/statebus/project/deploy/statebus_llm.yaml.local`

### Formal internal API + local + memfd

- `L3_case_count=25`
- `L3_quality_pass_count=25`
- `family_count=5`
- `state_pool_mode_requested=memfd`
- `state_pool_mode_used=memfd`
- `memfd_transfer_count=25`
- `memfd_publish_count=25`
- `memfd_bytes_transferred=247076`
- `semantic_state_transfer_count=25`
- `shared_memory_publish_count=0`
- `mmap_publish_count=0`
- `api_planner_call_count=25`
- `api_retriever_call_count=25`
- `api_executor_call_count=25`
- `api_summarizer_call_count=25`

结论：这是本轮最强的正向证据。可以支持“formal internal 25-case / 5-family 在 API + local + memfd 路径下跑通并 25/25 通过”，也可以支持“四角色 API 调用在该 formal internal run 中真实发生”。

### Formal compare API + local + memfd

该 stage exit 0，但 claim 解读必须谨慎：

- `fixed_answer_external_comparison_valid=False`
- `api_comparison_valid=0`
- `invalid_reason=quality_floor_gate_failed`
- `external_comparator_claim_scope=formal_financial_family`
- `formal_headline_eligible=False`
- `formal_superiority_claim_allowed=True`
- `formal_efficiency_claim_allowed=True`
- `state_pool_mode_used=memfd`
- `memfd_transfer_count=8`
- debug metrics 显示 StateBus quality 为 8，external quality 为 5，quality delta 为 +3
- external fairness gate coverage 为 true，fairness failure 为 0

结论：这是 formal external comparison 的重要新信号，但不是可直接升级为 headline formal external superiority 的闭环证据。原因是 suite 自身仍给出 `comparison_valid=False` 和 `formal_headline_eligible=False`。更稳妥表述是：API+local formal compare 已跑通并显示 StateBus 质量优于 external baseline，但当前 gate 仍将该 comparison 标为 invalid，因此不能把它写成最终 formal external superiority claim。

### Dev compare API + local + memfd

- `fixed_answer_external_comparison_valid=True`
- `external_comparator_claim_scope=dev_fixed_answer_only`
- `api_comparison_valid=1`
- `api_llm_total_tokens_delta=-986`
- `api_prompt_bytes_delta=-5082`
- `api_control_bytes_delta=-305`
- `api_task_ms_delta=13546.113`
- fairness gate coverage 为 true，failure 为 0

结论：dev fixed-answer compare 是有效比较，显示 token/prompt/control bytes 更少，但 task time 更慢约 13.5 秒。不能据此声称端到端速度优势。

### Continuous API + local

- `family_count=3`
- `continuous_round_count=30`
- `L2_semantic_state_transfer_count=30`
- `L3_reuse_gain=9`

结论：API + local 下 continuous families 跑通，并有 semantic state transfer 与 L3 reuse gain。

### Continuous replay API + local

- `family_count=3`
- `continuous_round_count=30`
- `replay_target_round_count=20`
- `replay_observed_round_count=20`
- `replay_missing_target_round_count=0`
- `validated_replay_count=17`
- `validated_downgraded_reuse_count=17`
- `exact_replay_count=3`
- `answer_restoration_replay_count=0`
- `L2_semantic_state_transfer_count=30`
- `L3_reuse_gain=20`

结论：这是 replay/reuse 的强证据。尤其是 `answer_restoration_replay_count=0` 与本轮修复后的 claim boundary 一致，避免把 exact replay 包装成 generic answer restoration。

### Replay negative audit

- `audit_pass=True`
- `case_count=7`

结论：负向 replay audit 通过。仍需注意，它验证的是构造的 negative checks，不等于已经覆盖所有 persisted live history artifact 的成熟 audit。

### Flagship ablation API + local

- `stress_family_count=6`
- `stress_pass_family_count=4`
- `total_llm_prompt_saved_by_state_ref_bytes=22079`
- `total_prompt_visible_saved_by_state_ref_bytes=8514`

结论：flagship ablation 跑通并显示 state ref 节省 prompt bytes，但 stress family 只通过 4/6，不能表述为全量 stress 通过。

## Claim 分级

可以升级为强证据：

- API + local + memfd 下 formal internal 25/25、5 families。
- API formal internal run 中四角色调用真实发生，各 25 次。
- memfd formal internal 正路径真实发生，25 transfers / publishes。
- continuous replay API + local 观察到 20/20 target replay，17 validated replay，3 exact replay。

可以作为部分支持：

- formal external comparison 已跑通，并显示 StateBus 8/8 vs external 5/8 的质量优势信号。
- flagship ablation 显示 state ref prompt savings。
- dev compare 显示 token/prompt/control bytes 更少。

仍不能 claim：

- headline formal external superiority：因为 `comparison_valid=False` 且 `formal_headline_eligible=False`。
- 端到端速度优势：dev compare 中 `api_task_ms_delta=+13546.113`，StateBus 更慢。
- flagship stress 全量通过：仅 4/6。
- generic answer restoration：`answer_restoration_replay_count=0`，这是正确边界。
- openEuler VM validation：本轮是 container local+api，不是 VM validation。

