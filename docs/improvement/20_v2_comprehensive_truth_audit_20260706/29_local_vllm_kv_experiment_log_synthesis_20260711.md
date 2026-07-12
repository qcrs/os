# Local vLLM KV Experiment Log Synthesis - 2026-07-11

## Executive Judgment

当前日志和 artifact 支持一个谨慎但已经可用的结论：StateBus 现在有机制收益证据，具体是通过 schedule/layout 控制触发 vLLM 的 `Engine-Local Prefix Reuse`，再配合输入级 dynamic pruning 降低 prompt/KV 压力。

不能写成 KV tensor 传递、hidden-state 传递、cross-engine KV reuse、2-GPU 成功或 openEuler 已验证。

机器可读汇总：`docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_vllm_kv_experiment_log_summary_20260711.json`

## Evidence Map

| Area | Best Evidence | Key Numbers | Judgment |
| --- | --- | --- | --- |
| E0 observability | `local_vllm_kv_audit_20260711.json` | health=True; metrics=prefix/cache/kv metrics exposed; single GPU0 32B service | 服务可观测性恢复，后续 KV 机制测试有意义。 |
| E1 schedule | `e1_e2_clean_service_repeat_summary_20260711_1438.json` | friendly hit-rate 0.789094; hostile hit-rate 0.523947; TTFT delta -683.97 ms | cache-friendly ordering 在 clean-service 条件下复现收益。 |
| E2 prefix layout | `e1_e2_clean_service_repeat_summary_20260711_1438.json` | shared hit-rate 0.779545; independent hit-rate 0; TTFT delta -2558.56 ms | `shared_evidence_prefix` 是当前最强机制证据。 |
| E3 pruning | `e3_dynamic_pruning_ablation_20260711.json` | selected bytes 333 -> 112; KV token saved delta 56; quality proxy pass=True | 证明输入级裁剪有效，但本身不是 end-to-end formal quality 证明。 |
| E6 formal guard | `e6_formal_guard_summary_20260711_1448.json` | L0-L3 all 25/25; L3 tokens 62667; L0 tokens 113949; quality delta 0 | 组合机制 profile 没伤 formal 25-case 质量底线。 |

## What The Logs Say

- E0 的失败是服务未监听和 profile/启动问题，不是 StateBus 质量失败；恢复后 `/health` 为 200，`/metrics` 暴露 prefix/cache/KV gauge。
- E1 的 repeat=3 压力不够，repeat=4 和 clean-service repeat 才是主证据；这解释了为什么要用容量敏感压力设置。
- E2 的 clean-service 结果最干净：independent 从冷 cache 起步仍为 0.0，shared prefix 到 0.779545，且 TTFT 大幅下降。
- E3 是 retrieval-level deterministic probe；它证明 pruning 机制和 hard-fact proxy，不应单独承担 formal quality claim。
- E6 是质量闭环：机制开关打开后 L0/L1/L2/L3 都是 25/25，Protocol L3 相比 Text L0 少 51282 total tokens、45652 prompt tokens。

## Historical Runs

| Run | Status | Extracted Cases | Token Delta |
| --- | --- | ---: | ---: |
| kv-e6-guard-20260711-1448 | formal_pass_all_L0_L3 | L0 25/25, L1 25/25, L2 25/25, L3 25/25 | -51282 |
| sb32bcap3k | partial_layer_reports_present | L0 25/25 |  |
| sb32bcompact | formal_pass_all_L0_L3 | L0 25/25, L1 25/25, L2 25/25, L3 25/25 | -57946 |
| sb32bformal3k | no_suite_summary_empty_stdout |  |  |
| sb32bformal900 | partial_layer_reports_present | L0 25/25 |  |
| sb32bformalx4k | no_suite_summary_empty_stdout |  |  |
| v2-local-vllm-qwen3-32b-gpu0-formal-20260710_2250 | partial_layer_reports_present | L0 25/25 |  |
| v2-local-vllm-qwen3-32b-gpu0-formal-timeout900-20260711_0015 | no_suite_summary_empty_stdout |  |  |
| v2-local-vllm-qwen3-32b-gpu0-mini5-20260710_2234 | partial_layer_reports_present | L0 5/5, L1 5/5, L2 5/5, L3 5/5 | -2436 |

历史 32B 运行里，失败主要集中在 wrapper timeout、空 stdout、上下文/JSON 截断风险和 partial L0 report；这些更像工程运行条件问题。当前可引用的质量闭环是 `sb32bcompact` 和 `kv-e6-guard-20260711-1448` 这类完整 L0-L3 pass。

## Broader Local API Packages

| Package | Stages | Required Failed | Optional Failed | Failed Stage Sample |
| --- | ---: | ---: | ---: | --- |
| local_api_20260706_191835 | 13 | 0 | 0 |  |
| local_api_20260707_004456 | 13 | 2 | 5 | r01_05_formal_api_local_memfd:1, r01_06_formal_compare_api_local_memfd:1, r01_07_dev_compare_api_local_memfd:1 |
| local_api_20260707_034412 | 13 | 1 | 3 | r01_05_formal_api_local_memfd:124, r01_09_continuous_api_local:124, r01_10_continuous_replay_api_local:124 |
| local_api_20260707_091807 | 12 | 0 | 0 |  |
| local_api_20260707_115051 | 13 | 0 | 3 | r01_09_continuous_api_local:1, r01_10_continuous_replay_api_local:1, r01_12_flagship_ablation_api_local:1 |
| local_api_20260707_130958 | 13 | 0 | 1 | r01_12_flagship_ablation_api_local:1 |
| local_api_20260707_163354 | 13 | 0 | 0 |  |
| local_api_20260708_084458 | 14 | 0 | 1 | r01_13_flagship_ablation_api_local:1 |
| local_api_20260708_084458_supplement_20260708_110413 | 14 | 2 | 0 | s01_00b_base_artifact_integrity_audit:1, s01_00c_base_claim_boundary_audit:1 |
| extras | 35 | 0 | 1 | x17b_continuous_gridops_world_api_local:1 |
| flagship | 0 | 0 | 0 |  |
| flagship_family_diag | 0 | 0 | 0 |  |
| lr01 | 0 | 0 | 0 |  |

这些综合包说明：非 KV 主线在 2026-07-07 到 2026-07-08 已经有多次 required stages clean 的证据；早期 required failure 主要来自 API/timeout/修复前 artifact 审计，而不是当前 E1-E3 机制 probe。

## vLLM Launch Logs

Scanned `15` Qwen3-32B vLLM launch logs; `1` contained error lines.

| Log | Error Signal |
| --- | --- |
| `vllm_qwen3_32b_gpu0_53334_8192_e2_independent_blocks573_20260711_1400.log` | ERROR 07-11 14:01:55 serving_chat.py:197] ValueError: This model's maximum context length is 8192 tokens. However, you requested 11270 tokens (11246 in the messages, 24 in the completion). Please reduce the length of the messages or complet |

日志扫描的实用结论是：8192 context 可以支撑当前 E1/E2/E6 证据，但曾出现过 independent layout 探索请求超过 8192 token 的报错；这解释了为什么后续要继续保留 context cap、shared prefix layout 和 dynamic pruning。

## Decision

- Overall: mechanism evidence is sufficient for a careful Engine-Local Prefix Reuse claim.
- 当前可以把 E1/E2/E3/E6 固化成“机制收益 + formal guard”证据包。
- 后续不建议继续消耗 GPU 去重复 E1/E2，除非要做最终图表误差线或改了 prompt/layout/pruning 代码。
- E4/E5 仍然暂缓；8192 以上 context 和 multi-GPU 需要安全重启窗口，不能从现有日志推导成功。
- 下一步更有价值的是把这份证据链合入主报告/答辩材料，并把 claim boundary 写死。

## Claim Boundary

Engine-Local Prefix Reuse via schedule/layout control and input-level dynamic pruning only; no KV tensor export, hidden-state transfer, cross-engine reuse, 2-GPU success, or openEuler VM validation is claimed.
