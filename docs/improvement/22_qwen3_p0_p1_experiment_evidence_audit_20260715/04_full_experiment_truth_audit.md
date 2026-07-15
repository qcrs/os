# Full Experiment Truth Audit

## Executive Summary

This audit indexes every file under the P0 full run, the partial pytest repair run, and the P1 additive extension. It preserves historical statuses. P0 has a complete 16-label record but is not an all-green matrix because `01_pytest_v2` failed. The later repair log can support only the tests/v2 repair conclusion. P1 Stage 18 remains historical `fail`; the completed request artifact independently satisfies the repaired default verifier, so it is recorded as `post_run_validator_repair`, not as a rerun or a summary rewrite. The primary metric ledger has `948` records; `546` repair-root candidates are excluded from it.

## Reproducibility And Coverage

Inputs, hashes, file sizes, mtimes, JSON/JSONL parse coverage, errors, empty files and exclusion rationale are in `01_artifact_inventory.json`. The analysis command and current worktree state are in `04_full_experiment_truth_audit.json`. All averages and rates below are built from additive numerator/denominator fields when those fields were present; missing values remain null rather than zero. In `02_stage_layer_family_case.csv`, `metric_field_paths` is a deterministic JSON mapping from every populated normalized metric to one or more `artifact-path#JSONPath` locations; `missing_metric_fields` and `missing_metric_reason` retain field-level null causes rather than silently zero-filling them.

P0 configuration/provenance artifacts are below. P0 has no root `manifest.txt`, so the audit intentionally does not invent a source revision. P1 `manifest.txt` records revision `2a8b402aecf2b89f9b64f94ebfb1900cea865641`. Current-vs-anchor drift is recorded from `git diff` in the JSON; it cannot reconstruct the historical dirty worktree: `The P1 manifest records an anchor revision, but no immutable snapshot of the historical dirty worktree exists. Current diff is evidence of later drift, not proof of the exact run-time tree.`.

| P0 configuration artifact | SHA256 | Model labels found | Endpoint values found |
| --- | --- | --- | --- |
| statebus_llm.local_vllm.yaml | 06b13013cb3b759438643209e0b0adfdef4920c9e56dd038be8168df26e4aa27 | ["qwen3-32b"] | ["http://127.0.0.1:53334/v1"] |

P0 preflight projection: `{"checks":[{"detail":"local_vllm configuration ready","name":"llm_api_ready","ok":true},{"detail":"python dependency present: sentence_transformers","name":"embedding_python_dependency","ok":true},{"detail":"embedding model present: /statebus/models/Qwen3-Embedding-0.6B","name":"embedding_model_path","ok":true},{"detail":"cuda available for cuda:0","name":"embedding_device","ok":true}],"cuda_available":true,"embedding_device":"cuda:0","embedding_mode":"local","embedding_model_path":"/statebus/models/Qwen3-Embedding-0.6B","llm_config_source":"/statebus/runs/full_qwen3_full_p1_20260715_001059/statebus_llm.local_vllm.yaml","ok":true,"path":"/home/qcrs/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/00_preflight/stdout.json","role_path_mode":"local_vllm"}`.

## Immutable Runtime Environment And Declared Order

The P0 local-vLLM configuration and the P1 manifest-referenced copy both record the model endpoint/configuration contract. The retained immutable run artifacts do not contain a shell environment snapshot, so this audit records that absence rather than inferring environment variables from the current host. P1's referenced configuration is a provenance link to the P0 run artifact; it is not an independent P1 configuration capture.

| Configuration source | Role | Model | Temperature | Max tokens | Max context tokens |
| --- | --- | --- | ---: | ---: | ---: |
| P0 configuration artifact | planner | qwen3-32b | 0.0 | 1024 | 4096 |
| P0 configuration artifact | retriever | qwen3-32b | 0.0 | 1024 | 4096 |
| P0 configuration artifact | executor | qwen3-32b | 0.0 | 1536 | 4096 |
| P0 configuration artifact | summarizer | qwen3-32b | 0.0 | 1024 | 4096 |
| P1 configuration artifact | planner | qwen3-32b | 0.0 | 1024 | 4096 |
| P1 configuration artifact | retriever | qwen3-32b | 0.0 | 1024 | 4096 |
| P1 configuration artifact | executor | qwen3-32b | 0.0 | 1536 | 4096 |
| P1 configuration artifact | summarizer | qwen3-32b | 0.0 | 1024 | 4096 |
| P1 manifest referenced source config | planner | qwen3-32b | 0.0 | 1024 | 4096 |
| P1 manifest referenced source config | retriever | qwen3-32b | 0.0 | 1024 | 4096 |
| P1 manifest referenced source config | executor | qwen3-32b | 0.0 | 1536 | 4096 |
| P1 manifest referenced source config | summarizer | qwen3-32b | 0.0 | 1024 | 4096 |

| Run | Environment-variable evidence | Preserved variable names | Immutable artifacts checked |
| --- | --- | --- | --- |
| p0 | not_preserved_in_immutable_run_artifacts | [] | [] |
| p1 | not_preserved_in_immutable_run_artifacts | [] | ["/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/manifest.txt"] |

| Run | `status.tsv` declared order | `summary.json` order |
| --- | --- | --- |
| p0 |  | 00_preflight:pass, 01_pytest_v2:fail, 02_compare_full:pass, 03_replay_full:pass, 04_continuous_csv_full:pass, 05_continuous_cross_full:pass, 06_formal_full:pass, 07_formal_subprocess_uds_full:pass, 08_genericity_holdout:pass, 09_prefix_shared:pass, 10_prefix_independent:pass, 11_carrier_compare_full:pass, 12_compare_repeat_2:pass, 13_compare_repeat_3:pass, 14_latency_repeat_aggregate:pass, 15_tag_baseline_audit:pass |
| p1 |  | 16_backend_matrix:pass, 17_flagship_refresh:pass, 18_prefix_parity_clean_repeats:fail |

| Run | StatePool modes from primary normalized metric rows |
| --- | --- |
| p0_full | {"shared_memory":256} |
| p1_extension | {"memfd":25,"mmap_file":25,"shared_memory":154} |

Stage 18 cache-service evidence: `clean_service_requested=False`, `service_window=continuous_service_between_pairs`. Stage 18 is a continuous-service window, not a per-repeat clean-service restart cohort.

## P0/P1 Timeline And Stage Status

| Stage | Purpose | Historical status | StateBus metric records | External records | Total normalized records | Strongest immediate interpretation | Artifact |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 00_preflight | environment/configuration precondition | pass | 0 | 0 | 0 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/00_preflight/stdout.json` |
| 01_pytest_v2 | v2 regression suite | fail | 0 | 0 | 0 | not a historical pass | `/statebus/runs/full_qwen3_full_p1_20260715_001059/logs/01_pytest_v2.log` |
| 02_compare_full | StateBus/external-text comparison | pass | 25 | 25 | 50 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/02_compare_full/stdout.json` |
| 03_replay_full | replay classification and reuse | pass | 50 | 0 | 50 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/03_replay_full/stdout.json` |
| 04_continuous_csv_full | CSV continuous-task reuse | pass | 40 | 0 | 40 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/04_continuous_csv_full/stdout.json` |
| 05_continuous_cross_full | cross-period continuous-task reuse | pass | 40 | 0 | 40 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/05_continuous_cross_full/stdout.json` |
| 06_formal_full | formal L0-L3 matrix | pass | 100 | 0 | 100 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/06_formal_full/stdout.json` |
| 07_formal_subprocess_uds_full | subprocess UDS execution | pass | 100 | 0 | 100 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/07_formal_subprocess_uds_full/stdout.json` |
| 08_genericity_holdout | genericity, paraphrase and taint holdout | pass | 16 | 0 | 16 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/08_genericity_holdout/stdout.json` |
| 09_prefix_shared | shared-prefix measurement | pass | 0 | 0 | 0 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/09_prefix_shared/stdout.json` |
| 10_prefix_independent | independent-prefix measurement | pass | 0 | 0 | 0 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/10_prefix_independent/stdout.json` |
| 11_carrier_compare_full | carrier comparison | pass | 50 | 0 | 50 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/11_carrier_compare_full/stdout.json` |
| 12_compare_repeat_2 | serialized comparison repeat 2 | pass | 25 | 25 | 50 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/12_compare_repeat_2/stdout.json` |
| 13_compare_repeat_3 | serialized comparison repeat 3 | pass | 25 | 25 | 50 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/13_compare_repeat_3/stdout.json` |
| 14_latency_repeat_aggregate | serialized latency aggregation | pass | 0 | 0 | 0 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/latency_repeat_summary.json` |
| 15_tag_baseline_audit | historical tag-baseline audit | pass | 0 | 0 | 0 | artifact-level review required | `/statebus/runs/full_qwen3_full_p1_20260715_001059/tag_baseline_audit.json` |
| 16_backend_matrix | mmap/shared-memory/memfd matrix | pass | 75 | 0 | 75 | artifact-level review required | `/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/stages/16_backend_matrix/stdout.json` |
| 17_flagship_refresh | flagship refresh and StateRef stress | pass | 324 | 3 | 327 | artifact-level review required | `/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/stages/17_flagship_refresh/stdout.json` |
| 18_prefix_parity_clean_repeats | paired prefix parity repeats | fail | 0 | 0 | 0 | not a historical pass | `/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/logs/18_prefix_parity_clean_repeats.stderr.log` |

The pytest repair is deliberately outside this stage table: it was a partial rerun stopped after Stage 02 and therefore cannot be counted as a fresh P0 matrix.

P1's own `source_eligibility.json` records mode `repaired_pytest_only`, `15` source pass stages, and source `01_pytest_v2=fail`. It admits P1 only through the later repair log reporting `320` passes (SHA256 `e543910abdfac99b22677d4d7690a9e41020c1af6d20c6d4bd9128cd5a66a419`); it explicitly preserves the historical P0 failure and does not create a replacement full matrix.

## Per-Stage Integrity Matrix

`03_stage_integrity_matrix.csv` is the complete machine-readable reconciliation of `summary.json`, `status.tsv`, stage stdout, run log mentions, artifact coverage and parse errors. Case counts and quality values are recomputed from the normalized ledger; an empty denominator is kept as `0/0`, never promoted to a pass.

| Stage | Purpose | Historical | Status consistency | Artifact completeness | StateBus/external units | Quality | Failure or anomaly | Supported | Unsupported |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 00_preflight | environment/configuration precondition | pass | consistent | stage_artifacts_present | 0/0 | 0/0 | none recorded | the recorded stage contract and artifacts | claims outside the stage contract or absent fairness controls |
| 01_pytest_v2 | v2 regression suite | fail | consistent | stage_artifacts_present | 0/0 | 0/0 | historical_status=fail | historical failure is preserved | an all-green matrix conclusion |
| 02_compare_full | StateBus/external-text comparison | pass | consistent | stage_artifacts_present | 25/25 | 50/50 | none recorded | the recorded system-level comparison | single-variable typed-carrier causality without matched controls |
| 03_replay_full | replay classification and reuse | pass | consistent | stage_artifacts_present | 50/0 | 50/50 | none recorded | the recorded stage contract and artifacts | claims outside the stage contract or absent fairness controls |
| 04_continuous_csv_full | CSV continuous-task reuse | pass | consistent | stage_artifacts_present | 40/0 | 40/40 | none recorded | the recorded stage contract and artifacts | claims outside the stage contract or absent fairness controls |
| 05_continuous_cross_full | cross-period continuous-task reuse | pass | consistent | stage_artifacts_present | 40/0 | 40/40 | none recorded | the recorded stage contract and artifacts | claims outside the stage contract or absent fairness controls |
| 06_formal_full | formal L0-L3 matrix | pass | consistent | stage_artifacts_present | 100/0 | 100/100 | none recorded | the recorded stage contract and artifacts | claims outside the stage contract or absent fairness controls |
| 07_formal_subprocess_uds_full | subprocess UDS execution | pass | consistent | stage_artifacts_present | 100/0 | 100/100 | none recorded | the recorded stage contract and artifacts | claims outside the stage contract or absent fairness controls |
| 08_genericity_holdout | genericity, paraphrase and taint holdout | pass | consistent | stage_artifacts_present | 16/0 | 16/16 | none recorded | bounded precompiled-contract holdout evidence | free-text task-contract compilation generalization |
| 09_prefix_shared | shared-prefix measurement | pass | consistent | stage_artifacts_present | 0/0 | 0/0 | none recorded | recorded prefix-counter behavior | agent-to-agent KV/hidden-state handoff or general latency superiority |
| 10_prefix_independent | independent-prefix measurement | pass | consistent | stage_artifacts_present | 0/0 | 0/0 | none recorded | recorded prefix-counter behavior | agent-to-agent KV/hidden-state handoff or general latency superiority |
| 11_carrier_compare_full | carrier comparison | pass | consistent | stage_artifacts_present | 50/0 | 50/50 | none recorded | the recorded system-level comparison | single-variable typed-carrier causality without matched controls |
| 12_compare_repeat_2 | serialized comparison repeat 2 | pass | consistent | stage_artifacts_present | 25/25 | 50/50 | none recorded | the recorded system-level comparison | single-variable typed-carrier causality without matched controls |
| 13_compare_repeat_3 | serialized comparison repeat 3 | pass | consistent | stage_artifacts_present | 25/25 | 50/50 | none recorded | the recorded system-level comparison | single-variable typed-carrier causality without matched controls |
| 14_latency_repeat_aggregate | serialized latency aggregation | pass | consistent | stage_artifacts_present | 0/0 | 0/0 | none recorded | the recorded system-level comparison | single-variable typed-carrier causality without matched controls |
| 15_tag_baseline_audit | historical tag-baseline audit | pass | consistent | stage_artifacts_present | 0/0 | 0/0 | none recorded | the recorded stage contract and artifacts | claims outside the stage contract or absent fairness controls |
| 16_backend_matrix | mmap/shared-memory/memfd matrix | pass | consistent | stage_artifacts_present | 75/0 | 75/75 | none recorded | functional backend realization under the recorded variant contracts | cross-backend speed superiority or loopback IPC |
| 17_flagship_refresh | flagship refresh and StateRef stress | pass | consistent | parse_errors_present | 324/3 | 327/327 | parse_errors=10 | the recorded stage contract and artifacts | claims outside the stage contract or absent fairness controls |
| 18_prefix_parity_clean_repeats | paired prefix parity repeats | fail | consistent | stage_artifacts_present | 0/0 | 0/0 | historical_status=fail | existing repeat artifact may support a separately-labelled repaired-verifier result | historical Stage 18 pass or a new model rerun |

## StateBus Normalized Metrics

| Run | Stage | Layer | Family | Quality | Prompt tokens | Total tokens | Observed prefix hits/queries | Source paths |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| p0_full | 02_compare_full | L3 | continuous_csv_table_analysis | 7/7 | 13297.0 | 15935.0 | 294.0/817.0 | 7 |
| p0_full | 02_compare_full | L3 | cross_period_financial_analysis | 10/10 | 19155.0 | 23339.0 | 490.0/1180.0 | 10 |
| p0_full | 02_compare_full | L3 | financial_report_analysis | 8/8 | 11969.0 | 15593.0 | 142.0/735.0 | 8 |
| p0_full | 03_replay_full | L0 | continuous_csv_table_analysis | 7/7 | 44104.0 | 47156.0 | 2024.0/2744.0 | 7 |
| p0_full | 03_replay_full | L0 | cross_period_financial_analysis | 10/10 | 28605.0 | 33149.0 | 1422.0/1769.0 | 10 |
| p0_full | 03_replay_full | L0 | financial_report_analysis | 8/8 | 13212.0 | 16975.0 | 291.0/808.0 | 8 |
| p0_full | 03_replay_full | L3 | continuous_csv_table_analysis | 7/7 | 11200.0 | 13622.0 | 175.0/689.0 | 7 |
| p0_full | 03_replay_full | L3 | cross_period_financial_analysis | 10/10 | 4774.0 | 7774.0 | 153.0/293.0 | 10 |
| p0_full | 03_replay_full | L3 | financial_report_analysis | 8/8 | 8037.0 | 11126.0 | 119.0/493.0 | 8 |
| p0_full | 04_continuous_csv_full | L0 | continuous_csv_table_analysis | 10/10 | 58293.0 | 62411.0 | 2864.0/3625.0 | 10 |
| p0_full | 04_continuous_csv_full | L1 | continuous_csv_table_analysis | 10/10 | 59225.0 | 63245.0 | 2897.0/3686.0 | 10 |
| p0_full | 04_continuous_csv_full | L2 | continuous_csv_table_analysis | 10/10 | 20811.0 | 24817.0 | 359.0/1285.0 | 10 |
| p0_full | 04_continuous_csv_full | L3 | continuous_csv_table_analysis | 10/10 | 20811.0 | 24817.0 | 359.0/1285.0 | 10 |
| p0_full | 05_continuous_cross_full | L0 | cross_period_financial_analysis | 10/10 | 29112.0 | 33638.0 | 1299.0/1800.0 | 10 |
| p0_full | 05_continuous_cross_full | L1 | cross_period_financial_analysis | 10/10 | 29977.0 | 34460.0 | 1468.0/1854.0 | 10 |
| p0_full | 05_continuous_cross_full | L2 | cross_period_financial_analysis | 10/10 | 21403.0 | 25777.0 | 356.0/1318.0 | 10 |
| p0_full | 05_continuous_cross_full | L3 | cross_period_financial_analysis | 10/10 | 21452.0 | 25820.0 | 366.0/1320.0 | 10 |
| p0_full | 06_formal_full | L0 | continuous_csv_table_analysis | 7/7 | 44104.0 | 47155.0 | 2158.0/2744.0 | 7 |
| p0_full | 06_formal_full | L0 | cross_period_financial_analysis | 10/10 | 28605.0 | 33149.0 | 1422.0/1769.0 | 10 |
| p0_full | 06_formal_full | L0 | financial_report_analysis | 8/8 | 13206.0 | 16938.0 | 301.0/809.0 | 8 |
| p0_full | 06_formal_full | L1 | continuous_csv_table_analysis | 7/7 | 44615.0 | 47279.0 | 2175.0/2776.0 | 7 |
| p0_full | 06_formal_full | L1 | cross_period_financial_analysis | 10/10 | 29664.0 | 33872.0 | 1538.0/1839.0 | 10 |
| p0_full | 06_formal_full | L1 | financial_report_analysis | 8/8 | 13636.0 | 17341.0 | 348.0/838.0 | 8 |
| p0_full | 06_formal_full | L2 | continuous_csv_table_analysis | 7/7 | 13297.0 | 15935.0 | 294.0/817.0 | 7 |
| p0_full | 06_formal_full | L2 | cross_period_financial_analysis | 10/10 | 19155.0 | 23339.0 | 490.0/1180.0 | 10 |
| p0_full | 06_formal_full | L2 | financial_report_analysis | 8/8 | 11969.0 | 15593.0 | 142.0/735.0 | 8 |
| p0_full | 06_formal_full | L3 | continuous_csv_table_analysis | 7/7 | 13297.0 | 15935.0 | 294.0/817.0 | 7 |
| p0_full | 06_formal_full | L3 | cross_period_financial_analysis | 10/10 | 19155.0 | 23339.0 | 490.0/1180.0 | 10 |
| p0_full | 06_formal_full | L3 | financial_report_analysis | 8/8 | 11969.0 | 15593.0 | 142.0/735.0 | 8 |
| p0_full | 07_formal_subprocess_uds_full | L0 | continuous_csv_table_analysis | 7/7 | 44104.0 | 47155.0 | 2158.0/2744.0 | 7 |
| p0_full | 07_formal_subprocess_uds_full | L0 | cross_period_financial_analysis | 10/10 | 28605.0 | 33149.0 | 1422.0/1769.0 | 10 |
| p0_full | 07_formal_subprocess_uds_full | L0 | financial_report_analysis | 8/8 | 13206.0 | 16938.0 | 301.0/809.0 | 8 |
| p0_full | 07_formal_subprocess_uds_full | L1 | continuous_csv_table_analysis | 7/7 | 44615.0 | 47279.0 | 2175.0/2776.0 | 7 |
| p0_full | 07_formal_subprocess_uds_full | L1 | cross_period_financial_analysis | 10/10 | 29664.0 | 33872.0 | 1538.0/1839.0 | 10 |
| p0_full | 07_formal_subprocess_uds_full | L1 | financial_report_analysis | 8/8 | 13636.0 | 17341.0 | 348.0/838.0 | 8 |
| p0_full | 07_formal_subprocess_uds_full | L2 | continuous_csv_table_analysis | 7/7 | 13297.0 | 15935.0 | 294.0/817.0 | 7 |
| p0_full | 07_formal_subprocess_uds_full | L2 | cross_period_financial_analysis | 10/10 | 19155.0 | 23339.0 | 490.0/1180.0 | 10 |
| p0_full | 07_formal_subprocess_uds_full | L2 | financial_report_analysis | 8/8 | 11969.0 | 15593.0 | 142.0/735.0 | 8 |
| p0_full | 07_formal_subprocess_uds_full | L3 | continuous_csv_table_analysis | 7/7 | 13297.0 | 15935.0 | 294.0/817.0 | 7 |
| p0_full | 07_formal_subprocess_uds_full | L3 | cross_period_financial_analysis | 10/10 | 19155.0 | 23339.0 | 490.0/1180.0 | 10 |
| p0_full | 07_formal_subprocess_uds_full | L3 | financial_report_analysis | 8/8 | 11969.0 | 15593.0 | 142.0/735.0 | 8 |
| p0_full | 08_genericity_holdout | L3 | continuous_csv_table_analysis | 8/8 | 14748.0 | 17590.0 | 486.0/905.0 | 8 |
| p0_full | 08_genericity_holdout | L3 | cross_period_financial_analysis | 8/8 | 15045.0 | 18425.0 | 670.0/922.0 | 8 |
| p0_full | 11_carrier_compare_full | L0 | continuous_csv_table_analysis | 7/7 | 44104.0 | 47155.0 | 2158.0/2744.0 | 7 |
| p0_full | 11_carrier_compare_full | L0 | cross_period_financial_analysis | 10/10 | 28605.0 | 33149.0 | 1422.0/1769.0 | 10 |
| p0_full | 11_carrier_compare_full | L0 | financial_report_analysis | 8/8 | 13212.0 | 16975.0 | 291.0/808.0 | 8 |
| p0_full | 11_carrier_compare_full | L1 | continuous_csv_table_analysis | 7/7 | 44615.0 | 47279.0 | 2175.0/2776.0 | 7 |
| p0_full | 11_carrier_compare_full | L1 | cross_period_financial_analysis | 10/10 | 29664.0 | 33872.0 | 1538.0/1839.0 | 10 |
| p0_full | 11_carrier_compare_full | L1 | financial_report_analysis | 8/8 | 13636.0 | 17341.0 | 348.0/838.0 | 8 |
| p0_full | 12_compare_repeat_2 | L3 | continuous_csv_table_analysis | 7/7 | 13297.0 | 15935.0 | 294.0/817.0 | 7 |
| p0_full | 12_compare_repeat_2 | L3 | cross_period_financial_analysis | 10/10 | 19155.0 | 23339.0 | 490.0/1180.0 | 10 |
| p0_full | 12_compare_repeat_2 | L3 | financial_report_analysis | 8/8 | 11969.0 | 15593.0 | 142.0/735.0 | 8 |
| p0_full | 13_compare_repeat_3 | L3 | continuous_csv_table_analysis | 7/7 | 13329.0 | 16015.0 | 308.0/819.0 | 7 |
| p0_full | 13_compare_repeat_3 | L3 | cross_period_financial_analysis | 10/10 | 19157.0 | 23337.0 | 490.0/1180.0 | 10 |
| p0_full | 13_compare_repeat_3 | L3 | financial_report_analysis | 8/8 | 11963.0 | 15579.0 | 131.0/735.0 | 8 |
| p1_extension | 16_backend_matrix | L2 | continuous_csv_table_analysis | 21/21 | 40550.0 | 49718.0 | 2286.0/5929.0 | 21 |
| p1_extension | 16_backend_matrix | L2 | cross_period_financial_analysis | 30/30 | 57471.0 | 69943.0 | 2768.0/8057.0 | 30 |
| p1_extension | 16_backend_matrix | L2 | financial_report_analysis | 24/24 | 35898.0 | 46608.0 | 1599.0/5546.0 | 24 |
| p1_extension | 17_flagship_refresh | L0 | continuous_csv_table_analysis | 20/20 | 120184.0 | 128635.0 | 6991.0/9692.0 | 20 |
| p1_extension | 17_flagship_refresh | L0 | continuous_long_doc_table_analysis | 20/20 | 71929.0 | 81073.0 | 4108.0/6479.0 | 20 |
| p1_extension | 17_flagship_refresh | L0 | cross_period_financial_analysis | 10/10 | 29114.0 | 33640.0 | 2754.0/3731.0 | 10 |
| p1_extension | 17_flagship_refresh | L0 | financial_report_analysis | 6/6 | 10088.0 | 12910.0 | 2180.0/3064.0 | 6 |
| p1_extension | 17_flagship_refresh | L0 | incident_diagnosis_v2 | 10/10 | 21412.0 | 25923.0 | 1058.0/2641.0 | 10 |
| p1_extension | 17_flagship_refresh | L1 | continuous_csv_table_analysis | 20/20 | 121552.0 | 130271.0 | 8147.0/10094.0 | 20 |
| p1_extension | 17_flagship_refresh | L1 | continuous_long_doc_table_analysis | 20/20 | 74626.0 | 84781.0 | 5525.0/7737.0 | 20 |
| p1_extension | 17_flagship_refresh | L1 | cross_period_financial_analysis | 10/10 | 29988.0 | 34423.0 | 2700.0/3930.0 | 10 |
| p1_extension | 17_flagship_refresh | L1 | financial_report_analysis | 6/6 | 10947.0 | 14780.0 | 1100.0/2062.0 | 6 |
| p1_extension | 17_flagship_refresh | L1 | incident_diagnosis_v2 | 10/10 | 22912.0 | 27323.0 | 1257.0/2459.0 | 10 |
| p1_extension | 17_flagship_refresh | L2 | continuous_csv_table_analysis | 20/20 | 42631.0 | 51273.0 | 3733.0/6796.0 | 20 |
| p1_extension | 17_flagship_refresh | L2 | continuous_long_doc_table_analysis | 20/20 | 48911.0 | 60185.0 | 2344.0/5942.0 | 20 |
| p1_extension | 17_flagship_refresh | L2 | cross_period_financial_analysis | 10/10 | 21413.0 | 25783.0 | 775.0/2419.0 | 10 |
| p1_extension | 17_flagship_refresh | L2 | financial_report_analysis | 3/3 | 5065.0 | 7458.0 | 702.0/1096.0 | 3 |
| p1_extension | 17_flagship_refresh | L2 | incident_diagnosis_v2 | 10/10 | 17867.0 | 22157.0 | 1523.0/2698.0 | 10 |
| p1_extension | 17_flagship_refresh | L3 | continuous_csv_table_analysis | 20/20 | 43153.0 | 51901.0 | 1779.0/5042.0 | 20 |
| p1_extension | 17_flagship_refresh | L3 | continuous_long_doc_table_analysis | 20/20 | 41366.0 | 51175.0 | 1362.0/4361.0 | 20 |
| p1_extension | 17_flagship_refresh | L3 | cross_period_financial_analysis | 10/10 | 21456.0 | 25836.0 | 695.0/2422.0 | 10 |
| p1_extension | 17_flagship_refresh | L3 | financial_report_analysis | 6/6 | 9255.0 | 11891.0 | 1035.0/2012.0 | 6 |
| p1_extension | 17_flagship_refresh | L3 | incident_diagnosis_v2 | 10/10 | 11780.0 | 15516.0 | 1769.0/3101.0 | 10 |
| p1_extension | 17_flagship_refresh | T2 | continuous_csv_table_analysis | 20/20 | 43604.0 | 52129.0 | 2456.0/7725.0 | 20 |
| p1_extension | 17_flagship_refresh | T2 | continuous_long_doc_table_analysis | 20/20 | 46783.0 | 56160.0 | 3173.0/6796.0 | 20 |
| p1_extension | 17_flagship_refresh | T2 | cross_period_financial_analysis | 10/10 | 21712.0 | 26319.0 | 1257.0/2755.0 | 10 |
| p1_extension | 17_flagship_refresh | T2 | financial_report_analysis | 3/3 | 4441.0 | 5835.0 | 910.0/1390.0 | 3 |
| p1_extension | 17_flagship_refresh | T2 | incident_diagnosis_v2 | 10/10 | 16605.0 | 20980.0 | 407.0/1993.0 | 10 |

## External Comparator Metrics

| Run | Stage | Layer | Family | Quality | Prompt tokens | Total tokens | Observed prefix hits/queries | Source paths |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| p0_full | 02_compare_full | local_vllm | anomaly_detection_v1 | 3/3 | 14793.0 | 15731.0 | None/None | 1 |
| p0_full | 02_compare_full | local_vllm | conditional_aggregation_v1 | 4/4 | 19324.0 | 20545.0 | None/None | 1 |
| p0_full | 02_compare_full | local_vllm | cross_table_join_analysis_v1 | 5/5 | 12156.0 | 13470.0 | None/None | 1 |
| p0_full | 02_compare_full | local_vllm | financial_report_analysis | 8/8 | 12694.0 | 14499.0 | None/None | 1 |
| p0_full | 02_compare_full | local_vllm | multi_period_trend_analysis_v1 | 5/5 | 12559.0 | 14210.0 | None/None | 1 |
| p0_full | 12_compare_repeat_2 | local_vllm | anomaly_detection_v1 | 3/3 | 14799.0 | 15739.0 | None/None | 1 |
| p0_full | 12_compare_repeat_2 | local_vllm | conditional_aggregation_v1 | 4/4 | 19332.0 | 20516.0 | None/None | 1 |
| p0_full | 12_compare_repeat_2 | local_vllm | cross_table_join_analysis_v1 | 5/5 | 12156.0 | 13470.0 | None/None | 1 |
| p0_full | 12_compare_repeat_2 | local_vllm | financial_report_analysis | 8/8 | 12694.0 | 14499.0 | None/None | 1 |
| p0_full | 12_compare_repeat_2 | local_vllm | multi_period_trend_analysis_v1 | 5/5 | 12559.0 | 14210.0 | None/None | 1 |
| p0_full | 13_compare_repeat_3 | local_vllm | anomaly_detection_v1 | 3/3 | 14799.0 | 15739.0 | None/None | 1 |
| p0_full | 13_compare_repeat_3 | local_vllm | conditional_aggregation_v1 | 4/4 | 19332.0 | 20516.0 | None/None | 1 |
| p0_full | 13_compare_repeat_3 | local_vllm | cross_table_join_analysis_v1 | 5/5 | 12156.0 | 13470.0 | None/None | 1 |
| p0_full | 13_compare_repeat_3 | local_vllm | financial_report_analysis | 8/8 | 12694.0 | 14499.0 | None/None | 1 |
| p0_full | 13_compare_repeat_3 | local_vllm | multi_period_trend_analysis_v1 | 5/5 | 12559.0 | 14210.0 | None/None | 1 |
| p1_extension | 17_flagship_refresh | flagship-ablation | fixed_answer_route_tool | 3/3 | 5030.0 | 5837.0 | None/None | 1 |

`02_stage_layer_family_case.csv` retains every primary source artifact. The tables keep StateBus and external rows separate; `Source paths` is the number of retained source artifacts in each aggregate. Missing fields are empty/null rather than inferred as zero. The repair root is fully present in the inventory but excluded from these normalized experimental metrics because its only admissible conclusion is the later pytest result.

## Matched Comparison Recomputation

`03_comparison_recomputation.csv` retains only same-case/family pairs that can be identified directly from the task-metric ledger. It recomputes deltas as treatment minus baseline and reductions as `(baseline - treatment) / baseline`, retaining null when either input is absent. `T2` is explicitly the Stage 17 `text_same_semantic_selection` lane while `semantic_base_layer` retains its raw L2 value; it is not folded into L2.

| Scope | Family | Case | Baseline | Treatment | Equal-quality | Visible-byte delta | Prompt-token delta | Total-token delta | Wall-ms delta |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-001 | L0 | L1 | 1/1 | 0.0 | 114.0 | 34.0 | -5313.854814000002 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-001 | L0 | L2 | 1/1 | -11424.0 | -4111.0 | -4214.0 | -6592.9215570000015 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-001 | L0 | L3 | 1/1 | -11424.0 | -4111.0 | -4214.0 | -6885.237551999999 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-002 | L0 | L1 | 1/1 | 0.0 | 42.0 | -52.0 | -6298.884478999997 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-002 | L0 | L2 | 1/1 | -11379.0 | -4110.0 | -4185.0 | -5442.452804999997 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-002 | L0 | L3 | 1/1 | -11379.0 | -4110.0 | -4185.0 | -5505.061691999999 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-003 | L0 | L1 | 1/1 | 0.0 | 119.0 | 125.0 | 473.67666800000006 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-003 | L0 | L2 | 1/1 | -8435.0 | -4526.0 | -4522.0 | 638.600814999998 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-003 | L0 | L3 | 1/1 | -8435.0 | -4526.0 | -4522.0 | 67.84976999999344 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-004 | L0 | L1 | 1/1 | 0.0 | 37.0 | -14.0 | -3611.986685 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-004 | L0 | L2 | 1/1 | -8433.0 | -4606.0 | -4663.0 | -4468.045000999999 |
| P0 formal ladder | continuous_csv_table_analysis | formal-agg-004 | L0 | L3 | 1/1 | -8433.0 | -4606.0 | -4663.0 | -2019.797470999998 |
| P0 formal ladder | continuous_csv_table_analysis | formal-anomaly-001 | L0 | L1 | 1/1 | 0.0 | 28.0 | 7.0 | -1257.1016220000056 |
| P0 formal ladder | continuous_csv_table_analysis | formal-anomaly-001 | L0 | L2 | 1/1 | -11566.0 | -4339.0 | -4368.0 | -1696.3192100000015 |
| P0 formal ladder | continuous_csv_table_analysis | formal-anomaly-001 | L0 | L3 | 1/1 | -11566.0 | -4339.0 | -4368.0 | -2147.397326000002 |
| P0 formal ladder | continuous_csv_table_analysis | formal-anomaly-002 | L0 | L1 | 1/1 | 0.0 | 31.0 | -49.0 | -5262.141604000004 |
| P0 formal ladder | continuous_csv_table_analysis | formal-anomaly-002 | L0 | L2 | 1/1 | -8433.0 | -4612.0 | -4699.0 | -5729.297499000004 |
| P0 formal ladder | continuous_csv_table_analysis | formal-anomaly-002 | L0 | L3 | 1/1 | -8433.0 | -4612.0 | -4699.0 | -5938.099573000003 |
| P0 formal ladder | continuous_csv_table_analysis | formal-anomaly-003 | L0 | L1 | 1/1 | 0.0 | 140.0 | 73.0 | -4503.145998 |
| P0 formal ladder | continuous_csv_table_analysis | formal-anomaly-003 | L0 | L2 | 1/1 | -8433.0 | -4503.0 | -4569.0 | -3971.5453839999973 |
| P0 formal ladder | continuous_csv_table_analysis | formal-anomaly-003 | L0 | L3 | 1/1 | -8433.0 | -4503.0 | -4569.0 | -4722.0606139999945 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-001 | L0 | L1 | 1/1 | 0.0 | 103.0 | 75.0 | -1886.5397520000006 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-001 | L0 | L2 | 1/1 | -2948.0 | -1006.0 | -1043.0 | -2572.5233320000007 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-001 | L0 | L3 | 1/1 | -2948.0 | -1006.0 | -1043.0 | -2493.321820000001 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-002 | L0 | L1 | 1/1 | 0.0 | 103.0 | 82.0 | -1536.2653839999984 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-002 | L0 | L2 | 1/1 | -2948.0 | -1006.0 | -1037.0 | -1901.4535739999992 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-002 | L0 | L3 | 1/1 | -2948.0 | -1006.0 | -1037.0 | -1848.7345199999982 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-003 | L0 | L1 | 1/1 | 0.0 | 103.0 | 82.0 | -1428.3334060000016 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-003 | L0 | L2 | 1/1 | -2951.0 | -1009.0 | -1036.0 | -1612.6190010000028 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-003 | L0 | L3 | 1/1 | -2951.0 | -1009.0 | -1036.0 | -1546.4618719999999 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-004 | L0 | L1 | 1/1 | 0.0 | 114.0 | 160.0 | 3097.7535000000025 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-004 | L0 | L2 | 1/1 | -2585.0 | -798.0 | -754.0 | 2692.1620950000033 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-004 | L0 | L3 | 1/1 | -2585.0 | -798.0 | -754.0 | 2743.841221999999 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-005 | L0 | L1 | 1/1 | 0.0 | 107.0 | 102.0 | -114.57979499999783 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-005 | L0 | L2 | 1/1 | -2948.0 | -1002.0 | -1016.0 | -679.2597530000021 |
| P0 formal ladder | cross_period_financial_analysis | formal-join-005 | L0 | L3 | 1/1 | -2948.0 | -1002.0 | -1016.0 | -737.1381540000039 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-001 | L0 | L1 | 1/1 | 0.0 | 101.0 | 9.0 | -6006.007367999995 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-001 | L0 | L2 | 1/1 | -2855.0 | -957.0 | -1050.0 | -5943.777351999997 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-001 | L0 | L3 | 1/1 | -2855.0 | -957.0 | -1050.0 | -5808.220849999998 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-002 | L0 | L1 | 1/1 | 0.0 | 108.0 | 24.0 | -5458.314738000001 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-002 | L0 | L2 | 1/1 | -2731.0 | -859.0 | -921.0 | -3827.1585620000005 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-002 | L0 | L3 | 1/1 | -2731.0 | -859.0 | -921.0 | -3757.4367010000024 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-003 | L0 | L1 | 1/1 | 0.0 | 87.0 | -14.0 | -6549.563463000002 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-003 | L0 | L2 | 1/1 | -2948.0 | -1022.0 | -1126.0 | -7032.257288000004 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-003 | L0 | L3 | 1/1 | -2948.0 | -1022.0 | -1126.0 | -6930.364231000007 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-004 | L0 | L1 | 1/1 | 0.0 | 134.0 | 160.0 | 1674.6274580000027 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-004 | L0 | L2 | 1/1 | -2951.0 | -978.0 | -956.0 | 1586.344444000002 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-004 | L0 | L3 | 1/1 | -2951.0 | -978.0 | -956.0 | 1695.0453000000052 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-005 | L0 | L1 | 1/1 | 0.0 | 99.0 | 43.0 | -3634.120371000001 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-005 | L0 | L2 | 1/1 | -2585.0 | -813.0 | -871.0 | -3710.402060999997 |
| P0 formal ladder | cross_period_financial_analysis | formal-trend-005 | L0 | L3 | 1/1 | -2585.0 | -813.0 | -871.0 | -3628.1320369999958 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-1 | L0 | L1 | 1/1 | 0.0 | 57.0 | 66.0 | 271.3241190000008 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-1 | L0 | L2 | 1/1 | -769.0 | -145.0 | -181.0 | -2708.827532000003 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-1 | L0 | L3 | 1/1 | -769.0 | -145.0 | -181.0 | -2674.0882009999987 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-2 | L0 | L1 | 1/1 | 0.0 | 58.0 | 60.0 | 393.50890799999615 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-2 | L0 | L2 | 1/1 | -788.0 | -139.0 | -145.0 | -232.9114140000056 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-2 | L0 | L3 | 1/1 | -788.0 | -139.0 | -145.0 | -243.1242100000054 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-3 | L0 | L1 | 1/1 | 0.0 | 55.0 | 72.0 | 1243.6546940000007 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-3 | L0 | L2 | 1/1 | -792.0 | -146.0 | -147.0 | -84.24349199999779 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-3 | L0 | L3 | 1/1 | -792.0 | -146.0 | -147.0 | 224.55201400000442 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-4 | L0 | L1 | 1/1 | 0.0 | 77.0 | 128.0 | 3287.4771459999974 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-4 | L0 | L2 | 1/1 | -822.0 | -182.0 | -140.0 | 2592.5664019999967 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-4 | L0 | L3 | 1/1 | -822.0 | -182.0 | -140.0 | 2837.520555999996 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-5 | L0 | L1 | 1/1 | 0.0 | 69.0 | 83.0 | 1132.329885999996 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-5 | L0 | L2 | 1/1 | -789.0 | -138.0 | -121.0 | 1187.9606840000015 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-5 | L0 | L3 | 1/1 | -789.0 | -138.0 | -121.0 | 1462.7539609999985 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-6 | L0 | L1 | 1/1 | 0.0 | 35.0 | -5.0 | -2374.2626029999956 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-6 | L0 | L2 | 1/1 | -776.0 | -159.0 | -215.0 | -3444.9327509999966 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-6 | L0 | L3 | 1/1 | -776.0 | -159.0 | -215.0 | -3358.2298079999964 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-7 | L0 | L1 | 1/1 | 0.0 | 28.0 | -10.0 | -2525.084732999996 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-7 | L0 | L2 | 1/1 | -745.0 | -172.0 | -211.0 | -2418.873112999998 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-7 | L0 | L3 | 1/1 | -745.0 | -172.0 | -211.0 | -2530.3466630000003 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-8 | L0 | L1 | 1/1 | 0.0 | 51.0 | 9.0 | -2698.121325 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-8 | L0 | L2 | 1/1 | -774.0 | -156.0 | -185.0 | -2042.5312339999946 |
| P0 formal ladder | financial_report_analysis | benchmark-sample-8 | L0 | L3 | 1/1 | -774.0 | -156.0 | -185.0 | -1759.736364999997 |
| P1 flagship ladder | financial_report_analysis | fixed-answer-auth-001 | L0 | L1 | 1/1 | 0.0 | 549.0 | 1647.0 | 60757.067492 |
| P1 flagship ladder | financial_report_analysis | fixed-answer-auth-001 | L0 | L2 | 1/1 | -792.0 | -132.0 | -150.0 | -15477.642725999991 |
| P1 flagship ladder | financial_report_analysis | fixed-answer-auth-001 | L0 | L3 | 1/1 | -792.0 | -132.0 | -150.0 | -16075.663694000003 |
| P1 L2 versus text-same-semantic-selection | financial_report_analysis | fixed-answer-auth-001 | L2 | T2 | 1/1 | -6.0 | -66.0 | -48.0 | 8556.854503999988 |
| P1 flagship ladder | financial_report_analysis | fixed-answer-cache-001 | L0 | L1 | 1/1 | 0.0 | 60.0 | 55.0 | 1754.1675849999956 |

## Role-Level Case Metrics

`02_role_case_metrics.csv` has one row per persisted task-metric source and role, retaining layer/family/case/source path and role-scoped hydrated, memory, artifact, text and table metrics. This summary is additive across retained primary task metrics; it is not a quality attribution to an individual role.

| Role | Task-metric role rows | Call-count sum | Hydrated bytes sum | Memory bytes sum | Artifact bytes sum |
| --- | ---: | ---: | ---: | ---: | ---: |
| executor | 870 | 848.0 | 404621.0 | 72355.0 | 0.0 |
| planner | 870 | 870.0 | 0.0 | 0.0 | 0.0 |
| retriever | 870 | 848.0 | 656925.0 | 72355.0 | 0.0 |
| summarizer | 870 | 852.0 | 656925.0 | 72355.0 | 224836.0 |

## P0 Pytest Failure And Repair Boundary

The historical P0 pytest log names `["tests/v2/test_smoke.py::test_v2_smoke_aggregates_role_path_token_usage","tests/v2/test_smoke.py::test_v2_smoke_cold_start_mode_executes_role_path_without_seeded_replay"]`. It records `2` failure lines. The repair log reports `[320]` passes, SHA256 `e543910abdfac99b22677d4d7690a9e41020c1af6d20c6d4bd9128cd5a66a419`, and `repair_log_is_later_than_p0_pytest=True`; it does not reproduce individual test names, so it supports the suite-level repair conclusion only.

The current worktree diff records a post-run change in `v2/runtime/smoke.py` that separates execution role calls from optional rendered-request artifacts. This is consistent with the stated P0 lightweight-stub failure mode, but the audit does not use current code to relabel historical P0. The proper conclusion is: historical P0 pytest failed; later pytest-only evidence may repair the tests/v2 conclusion; neither establishes a new 16-stage all-pass matrix.

## P1 Stage 18 Validator Failure

| Repaired default verifier gate | Existing repeat artifact |
| --- | --- |
| pair_parity | True |
| repeat_coverage_ge_4 | True |
| AB_BA_coverage | True |
| completion_contract_parity | True |
| two_corpus_coverage | True |
| clean_service_readiness | True |
| aggregate_counter_rate_recomputation | True |

Historical post-processing signal: `unrecoverable from preserved artifacts: Stage 18 stderr is zero bytes`. Evidence quality: `zero-byte stderr; run.log records only generic stage failure`. The current verifier source at `scripts/run_v2_post_full_p1_qwen3_container.sh:211-251` imports `os`; that is post-run validation code, not evidence of the historical exception. Since the original stderr is zero-byte, the documented `NameError` remains an uncorroborated explanation rather than an audit fact. `clean_service_requested=False` and `service_window=continuous_service_between_pairs` mean this is not a per-repeat clean-service-restart experiment. Its valid claim boundary is paired engine-local vLLM prefix reuse under the recorded continuous service window, not Agent KV transfer or a clean-service general latency result.

The aggregate counters and TTFT rows below are recomputed directly from P0 Stage 09/10 summaries and the P1 Stage 18 repeat summary. `03_prefix_pair_validation.csv` independently reconciles all four repeat-summary pair references to their per-repeat `pair_summary.json`; pair-level counters are not persisted in those pair summaries and therefore remain null instead of being fabricated.

| Source | Scope | Mode | Hits/queries | Recomputed hit rate | Warm TTFT mean ms | Warm TTFT median ms | Rate matches raw report |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| p0 | 09_prefix_shared | shared | 1376.0/1769.0 | 0.7778405879027699 | 262.67147525 | None | True |
| p0 | 10_prefix_independent | independent | 0.0/1810.0 | 0.0 | 2315.2378047499997 | None | True |
| p1 | 18_prefix_parity_clean_repeats | shared | 5691.0/7553.0 | 0.7534754402224282 | 7750.0314248125 | 7761.451744375 | True |
| p1 | 18_prefix_parity_clean_repeats | independent | 66.0/7571.0 | 0.008717474574032493 | 9284.4096116875 | 9586.131996125001 | True |

| Repeat | Order | Evidence file | Pair ok | Completion contracts | Direct pair-summary validation |
| ---: | --- | --- | --- | --- | --- |
| 1 | shared_first | v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/orion_factory_ops_report_2026.md | True | True | validated |
| 2 | independent_first | v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/nova_retail_ops_report_2026.md | True | True | validated |
| 3 | shared_first | v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/orion_factory_ops_report_2026.md | True | True | validated |
| 4 | independent_first | v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/nova_retail_ops_report_2026.md | True | True | validated |

## Replay, Genericity And Latency

P0 Stage 03 has `25` cases, quality `{"deterministic_checks_passed_count":25.0,"fact_coverage_passed_count":25.0,"quality_floor_pass_count":25.0}`, and replay distribution `{"exact_replay":15.0,"validated_replay":10.0}`. Its aggregated role/call and reuse fields are `{"answer_restoration_replay_count":15.0,"artifact_reuse_count":15.0,"exact_replay_count":15.0,"executor_call_count":10.0,"llm_call_count":55.0,"planner_call_count":25.0,"retriever_call_count":10.0,"reuse_gain":25.0,"skipped_step_count":40.0,"summarizer_call_count":10.0,"validated_replay_count":10.0}`. Exact replay, restored answer, artifact reuse, skipped steps and reduced calls are separate values; the report does not infer one from another.

P0 Stage 08 records `4` cases across `4` families, route hints `disabled`, and paraphrase equivalence `{"formal-agg-004":false,"formal-anomaly-001":true,"formal-join-004":true,"formal-trend-001":true}`. Its own taint audit is `{"pass":true,"scanned_request_count":64,"violation_count":0}`. This supports a bounded precompiled-contract audit only, as stated by its source boundary: `paraphrase_and_no-preferred-candidate_route-selection_holdout_with_precompiled_canonical_task_spec; does_not_claim_free-form_intent_compilation_generalization`.

The P0 serialized compare aggregate reports `3` repeats, all equal-quality validity `True`, favorable task-ms repeats `0`, median task delta `211452.1721800001`, and `latency_superiority_claim_allowed=False`. `03_latency_repeat_recomputation.csv` preserves every raw repeat metric and recomputes each aggregate below. Do not replace that explicit non-superiority gate with token results.

| Metric | Repeat | Source artifact | Equal-quality comparison | Raw delta |
| --- | ---: | --- | --- | ---: |
| task_ms_delta | 1 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/02_compare_full/stdout.json` | True | 209098.77778 |
| llm_ms_delta | 1 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/02_compare_full/stdout.json` | True | 168869.41155900003 |
| total_tokens_delta | 1 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/02_compare_full/stdout.json` | True | -23588.0 |
| prompt_tokens_delta | 1 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/02_compare_full/stdout.json` | True | -27105.0 |
| task_ms_delta | 2 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/12_compare_repeat_2/stdout.json` | True | 211452.1721800001 |
| llm_ms_delta | 2 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/12_compare_repeat_2/stdout.json` | True | 170579.7196170002 |
| total_tokens_delta | 2 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/12_compare_repeat_2/stdout.json` | True | -23567.0 |
| prompt_tokens_delta | 2 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/12_compare_repeat_2/stdout.json` | True | -27119.0 |
| task_ms_delta | 3 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/13_compare_repeat_3/stdout.json` | True | 213362.4118740001 |
| llm_ms_delta | 3 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/13_compare_repeat_3/stdout.json` | True | 172405.08636199997 |
| total_tokens_delta | 3 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/13_compare_repeat_3/stdout.json` | True | -23503.0 |
| prompt_tokens_delta | 3 | `/statebus/runs/full_qwen3_full_p1_20260715_001059/stages/13_compare_repeat_3/stdout.json` | True | -27091.0 |

| Metric | n | Sum | Recomputed median | Descriptive p90 (linear) | Descriptive p95 (linear) | Reported median | Matches report |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| task_ms_delta | 3 | 633913.3618340002 | 211452.1721800001 | 212980.3639352001 | 213171.3879046001 | 211452.1721800001 | True |
| llm_ms_delta | 3 | 511854.2175380002 | 170579.7196170002 | 172040.01301300002 | 172222.5496875 | 170579.7196170002 | True |
| total_tokens_delta | 3 | -70658.0 | -23567.0 | -23515.8 | -23509.4 | -23567.0 | True |
| prompt_tokens_delta | 3 | -81315.0 | -27105.0 | -27093.8 | -27092.4 | None | None |

The p90/p95 values are descriptive linear interpolation across only three serialized repeats. They do not establish tail-latency stability, and the raw source explicitly disallows a latency-superiority claim.

## P1 Backend And Flagship

| Variant | Requested mode | Actual mode | Transport | Quality | Fallback |
| --- | --- | --- | --- | ---: | ---: |
| mmap_loopback | mmap | mmap_file | loopback | 25/25 | 0 |
| shared_memory_loopback | shared_memory | shared_memory | loopback | 25/25 | 0 |
| memfd_subprocess | memfd | memfd | subprocess | 25/25 | 0 |

This supports functional realization of three modes. `mmap_loopback` and `shared_memory_loopback` are loopbacks, not cross-process IPC. `memfd_subprocess` is the only variant with a subprocess transport. The Stage 16 claim boundary itself withholds cross-backend timing superiority.

Stage 17 declares `first_pass_with_diagnostic_text_controls` and its external comparator restriction is `dev_fixed_answer_external_fairness_gate_passed_not_formal_superiority`. StateRef stress has `5/6` passing families and `1` diagnostic-only family; its accumulated claimed prompt-visible saving is `13112.0` bytes. This evidence must retain the family eligibility and T2 scope present in the raw artifact.

## LogitState / Logits Participation Audit

`03_logitstate_participation_matrix.csv` searches every parsed P0/P1 JSON/JSONL artifact for logit/logprob fields, preserving raw artifact and JSON-field paths. Its numeric totals deliberately use only unique primary StateBus task-metric artifacts, so copied benchmark-report values cannot inflate the count. The task metrics show positive `logit_state_transfer_count` projections, but no primary artifact persists `logit_state_bytes`; missing bytes stay null rather than becoming zero. The normalised `state_ref_count` excludes this separate LogitState projection because no LogitStateRef registration or receiver was retained. Current source can serialize executor top-logprob data, yet the audited run artifacts do not record a LogitStateRef registry entry, a receiving role, a distinct consumption event, or a behavior-changing route/tool/retry/fallback effect.

| Scope | Primary metric rows | Positive transfer-count rows | Persisted logit-byte measurements | Entropy measurements | Confidence-gate sum | StateRef registration | Receiver | Route/tool/retry/fallback effect | A/B evidence |
| --- | ---: | --- | --- | ---: | ---: | --- | --- | --- | --- |
| p0_full | 471 | 456 (sum=456.0) | 0 (sum=None) | 471 | 0.0 | no parsed P0/P1 artifact has ref_kind/channel=logit_state; current v2/refs/models.py defines LogitStateRef.registry_entry(), but definition is not run evidence | no parsed P0/P1 artifact records a LogitStateRef consumer_role or receiving-role hydration | logit_confidence_gate_trigger_count sum=0.0; no artifact maps a LogitState value to a route/tool/retry/fallback outcome | no LogitState enabled/disabled or receiver-consumption A/B is present |
| p1_extension | 399 | 392 (sum=392.0) | 0 (sum=None) | 399 | 0.0 | no parsed P0/P1 artifact has ref_kind/channel=logit_state; current v2/refs/models.py defines LogitStateRef.registry_entry(), but definition is not run evidence | no parsed P0/P1 artifact records a LogitStateRef consumer_role or receiving-role hydration | logit_confidence_gate_trigger_count sum=0.0; no artifact maps a LogitState value to a route/tool/retry/fallback outcome | no LogitState enabled/disabled or receiver-consumption A/B is present |
| p0_p1_combined | 870 | 848 (sum=848.0) | 0 (sum=None) | 870 | 0.0 | no parsed P0/P1 artifact has ref_kind/channel=logit_state; current v2/refs/models.py defines LogitStateRef.registry_entry(), but definition is not run evidence | no parsed P0/P1 artifact records a LogitStateRef consumer_role or receiving-role hydration | logit_confidence_gate_trigger_count sum=0.0; no artifact maps a LogitState value to a route/tool/retry/fallback outcome | no LogitState enabled/disabled or receiver-consumption A/B is present |

The only defensible conclusion is executor-side telemetry/metric projection. It is not evidence of a persisted hidden-state tensor, KV cache, agent-to-agent transfer, receiving-role consumption, or quality/efficiency benefit.

## Mechanisms, Fairness And Boundaries

| Mechanism | Claim status | Evidence level | Boundary |
| --- | --- | ---: | --- |
| P0 matrix | contradicted | 3 | matrix_complete is not all_stages_passed; do not describe P0 as 16/16 green |
| pytest repair | supported_with_boundary | 3 | partial repair was interrupted at Stage 02 and is not a second full matrix |
| Semantic StateRef | supported_through_receiver_hydration_only | 3 | downstream consumption remains uninstrumented and unproven; not hidden state or KV tensor transfer |
| P1 backend matrix | not_supported | 3 | loopback is not cross-process IPC; only memfd subprocess can support that narrower path claim |
| Memory/replay | not_supported_as_general_rule | 4 | distinguish assist, validated replay, exact replay, restored output and skipped calls |
| Prefix | contradicted | 4 | may support engine-local vLLM prefix reuse only; continuous service window is not clean-service restart per repeat |
| LogitState | not_supported | 3 | top-logprob compact summary is not a hidden-state tensor or KV cache; do not infer transfer, consumption, or benefit |
| External compare | limited | 5 | separate semantic selection/pruning, prompt layout, tools and carrier differences |
| Genericity | not_supported | 4 | precompiled task contract remains a strong prior |
| openEuler delivery | not_supported | 2 | VM/final delivery validation is not in the audited evidence |

L0-L3 and T2 comparisons must not collapse semantic selection/pruning, prompt layout, carrier, memory/replay and state transport into one causal attribution. A backend loopback pass proves a functional path, not cross-process IPC or performance superiority. For UDS, only explicit subprocess/AF_UNIX/Protobuf lifecycle evidence can support the narrower external executor claim.

## Mechanism Evidence Matrix

The following matrix combines static source review with executed-artifact evidence. Static rows are bounded lexical line references in current code and the P1 anchor only; they identify paths for review and are explicitly not a data-flow proof. The full columns, including current/anchor references and fairness evidence, are in `03_mechanism_evidence_matrix.csv`.

| Mechanism | Level | Claim status | Artifact evidence | Consumption evidence | Boundary |
| --- | ---: | --- | --- | --- | --- |
| StateRef publication and hydration | 3 | supported_through_receiver_hydration_only | publish=1380, hydrate=4140, consume=0 | publication and receiver hydration are recorded, but no distinct STATE_CONSUME event or behavior-changing consumption record is retained | publication, transfer and receiver hydration are recorded; downstream consumption is not separately instrumented or proven. StateRef is not a hidden-state or KV tensor handoff |
| Memory and replay | 4 | supported_with_replay_class_boundary | {"quality_floor_breakdown":{"deterministic_checks_passed_count":25.0,"fact_coverage_passed_count":25.0,"quality_floor_pass_count":25.0},"replay_class_distribution":{"exact_replay":15.0,"validated_replay":10.0},"selected_case_count":25,"telemetry_summary":{"answer_restoration_replay_count":15.0,"artifact_reuse_count":15.0,"exact_replay_count":15.0,"executor_call_count":10.0,"llm_call_count":55.0,"planner_call_count":25.0,"retriever_call_count":10.0,"reuse_gain":25.0,"skipped_step_count":40.0,"summarizer_call_count":10.0,"validated_replay_count":10.0}} | exact/validated replay, restoration, artifact reuse, skipped steps and calls are retained as separate metrics | do not equate memory match or validated replay with skipped execution, LLM calls, tools, or reuse_gain |
| StatePool modes and fallback | 3 | supported_functionally | mmap_loopback:mmap_file; shared_memory_loopback:shared_memory; memfd_subprocess:memfd | P1 validation records requested/actual mode, transport, case coverage and fallback | mmap/shared_memory loopback is not cross-process IPC; only memfd_subprocess supports the narrower external-boundary claim |
| UDS typed control plane | 3 | supported_as_narrow_transport_path | Stage 16 validates memfd_subprocess separately from loopbacks | subprocess transport is a concrete execution boundary; lifecycle evidence remains stage-specific | do not extend this to all agents, all StatePool modes, or a measured latency advantage |
| Engine-local prefix reuse | 4 | supported_only_as_engine_local_prefix_observation | {"aggregate_recomputation":{"independent":{"hits":66.0,"matches_report":true,"queries":7571.0,"recomputed_hit_rate":0.008717474574032493,"reported_hit_rate":0.008717474574032493},"shared":{"hits":5691.0,"matches_report":true,"queries":7553.0,"recomputed_hit_rate":0.7534754402224282,"reported_hit_rate":0.7534754402224282}},"all_required_pass":true,"artifact_status":"complete_requests_and_summary_present","available":true,"claim_status":"engine_local_prefix_repeat artifact satisfies repaired default verifier; historical summary remains fail","clean_service_requested":false,"current_verifier_status":"post_run_validator_repair_pass","historical_error_evidence":"zero-byte stderr; run.log records only generic stage failure","historical_post_processing_error":"unrecoverable from preserved artifacts: Stage 18 stderr is zero bytes","historical_status":"fail","pair_validation":{"pair_count":4,"rows":[{"all_completion_contracts_valid":true,"counter_claim_allowed":true,"evidence_file":"v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/orion_factory_ops_report_2026.md","failure_or_anomaly":"metadata (repeat/order/evidence) is stored only in repeat_summary; pair_summary provides compatibility/latency","independent_hit_rate":null,"independent_hits":null,"independent_queries":null,"independent_warm_ttft_mean_ms":9717.42440375,"order":"shared_first","pair_ok":true,"pair_summary_parse_status":"ok","pair_summary_path":"/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/stages/18_prefix_parity_clean_repeats/repeat01/pair_summary.json","pair_validation_status":"validated","repeat_index":1,"shared_hit_rate":null,"shared_hits":null,"shared_minus_independent_warm_ttft_ms":-2271.2658707499995,"shared_queries":null,"shared_warm_ttft_mean_ms":7446.158533},{"all_completion_contracts_valid":true,"counter_claim_allowed":true,"evidence_file":"v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/nova_retail_ops_report_2026.md","failure_or_anomaly":"metadata (repeat/order/evidence) is stored only in repeat_summary; pair_summary provides compatibility/latency","independent_hit_rate":null,"independent_hits":null,"independent_queries":null,"independent_warm_ttft_mean_ms":9636.48109225,"order":"independent_first","pair_ok":true,"pair_summary_parse_status":"ok","pair_summary_path":"/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/stages/18_prefix_parity_clean_repeats/repeat02/pair_summary.json","pair_validation_status":"validated","repeat_index":2,"shared_hit_rate":null,"shared_hits":null,"shared_minus_independent_warm_ttft_ms":-1823.1133447500006,"shared_queries":null,"shared_warm_ttft_mean_ms":7813.3677474999995},{"all_completion_contracts_valid":true,"counter_claim_allowed":true,"evidence_file":"v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/orion_factory_ops_report_2026.md","failure_or_anomaly":"metadata (repeat/order/evidence) is stored only in repeat_summary; pair_summary provides compatibility/latency","independent_hit_rate":null,"independent_hits":null,"independent_queries":null,"independent_warm_ttft_mean_ms":9535.7829,"order":"shared_first","pair_ok":true,"pair_summary_parse_status":"ok","pair_summary_path":"/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/stages/18_prefix_parity_clean_repeats/repeat03/pair_summary.json","pair_validation_status":"validated","repeat_index":3,"shared_hit_rate":null,"shared_hits":null,"shared_minus_independent_warm_ttft_ms":-1504.7192225000008,"shared_queries":null,"shared_warm_ttft_mean_ms":8031.063677499999},{"all_completion_contracts_valid":true,"counter_claim_allowed":true,"evidence_file":"v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/nova_retail_ops_report_2026.md","failure_or_anomaly":"metadata (repeat/order/evidence) is stored only in repeat_summary; pair_summary provides compatibility/latency","independent_hit_rate":null,"independent_hits":null,"independent_queries":null,"independent_warm_ttft_mean_ms":8247.950050750002,"order":"independent_first","pair_ok":true,"pair_summary_parse_status":"ok","pair_summary_path":"/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/stages/18_prefix_parity_clean_repeats/repeat04/pair_summary.json","pair_validation_status":"validated","repeat_index":4,"shared_hit_rate":null,"shared_hits":null,"shared_minus_independent_warm_ttft_ms":-538.4143095000009,"shared_queries":null,"shared_warm_ttft_mean_ms":7709.535741250001}],"validated_pair_count":4},"requirements":[{"gate":"pair_parity","pass":true},{"gate":"repeat_coverage_ge_4","pass":true},{"gate":"AB_BA_coverage","pass":true},{"gate":"completion_contract_parity","pass":true},{"gate":"two_corpus_coverage","pass":true},{"gate":"clean_service_readiness","pass":true},{"gate":"aggregate_counter_rate_recomputation","pass":true}],"service_window":"continuous_service_between_pairs"} | vLLM counter observation is engine-local; no StateRef consumer is shown | not agent-to-agent KV, hidden-state transfer, cross-engine reuse, or a clean-service general latency claim |
| LogitState / logprobs | 3 | telemetry_projection_only | positive transfer-count rows=848, transfer-count sum=848.0, persisted byte-value rows=0, confidence-gate sum=0.0, telemetry event names containing LOGIT=0 | no persisted LogitState bytes, ref registration, receiver, separately recorded consumption, or behavior-changing route/tool/retry/fallback record was found | top-logprob summaries are not hidden-state tensors or KV cache transfer; the observed metrics do not support a receiver, efficiency, or quality causal claim |
| CodeAct and sandbox boundary | 3 | implemented_with_safety_boundary | per-role task metric rows retain CodeAct and fallback counters when persisted | execution path is present; static review shows fallback-capable sandbox implementation | not a claim of production-grade isolation, nsjail validation, or a benchmarked CodeAct causal benefit |
| CanonicalTaskSpec, route selection and fallback | 3 | limitation_identified | {"claim_boundary":"paraphrase_and_no-preferred-candidate_route-selection_holdout_with_precompiled_canonical_task_spec; does_not_claim_free-form_intent_compilation_generalization","ok":true,"paraphrase_semantic_equivalence":{"formal-agg-004":false,"formal-anomaly-001":true,"formal-join-004":true,"formal-trend-001":true},"prompt_taint_audit":{"pass":true,"scanned_request_count":64,"violation_count":0},"route_hint_policy":"disabled","selected_case_count":4,"selected_family_count":4} | precompiled contracts are consumed by planning; rendered-request taint findings require role/provenance review | lexical code review identifies specialization/fallback surfaces only; it neither proves cheating nor free-text generalization |

## Taint, Oracle, Fallback And Cache Audit

All available rendered requests were enumerated. The automated scanner reports `12592` raw matches across `450` unique rule/path/fragment signatures. That scanner intentionally does not call a field-name match a confirmed leak: role contract, upstream provenance, value semantics, scorer visibility and whether a verified route/tool was handed to Executor must be judged from the retained ledger. Existing genericity artifacts and precompiled `CanonicalTaskSpec` remain a limitation for free-text generalization claims.

`02_rendered_request_taint_rollup.csv` groups repeat hits by run/stage/case/role/rule, preserving raw occurrence and unique-fragment counts. The lexical static scan includes a complete `v2/`, `scripts/`, `tests/` index for expected-answer/gold/oracle, candidate/order/route/tool hints, case/sample specialization, CanonicalTaskSpec/precompile, and fallback/quality-gate surfaces in both current code and the P1 anchor. Counts below are line hits, not vulnerabilities; capped file/line references are retained in `04_full_experiment_truth_audit.json` as navigation evidence and do not establish answer leakage or cheating without role-aware provenance/data-flow review.

| Static lexical category | Current line hits | Current files | Anchor line hits | Anchor files |
| --- | ---: | ---: | ---: | ---: |
| candidate_order_route_tool_hint | 250 | 23 | 246 | 22 |
| canonical_contract_or_precompile | 487 | 50 | 566 | 71 |
| case_or_sample_specialization | 92 | 12 | 67 | 11 |
| expected_answer_gold_oracle | 117 | 20 | 208 | 41 |
| fallback_or_quality_gate | 545 | 66 | 545 | 72 |

Cache and history remain a confounder unless artifacts demonstrate isolated history roots and case-level replay identity. Memory match, assist reuse, validated replay, exact replay, output restoration and skipped calls/tokens are separate columns in the ledger and must not be conflated.

## Contest Coverage And Claim Level

Evidence level is cumulative: `1` code definition, `2` executed path, `3` raw artifact data, `4` downstream behavior consumption, `5` repeated fair A/B benefit. `03_contest_coverage_matrix.csv` contains the code, run and fairness columns for each requirement derived from `docs/reference/题目.md`.

| Contest requirement | Level | Claim status | Proven content | Risk/gap |
| --- | ---: | --- | --- | --- |
| At least three agents / roles | 3 | partially_proven | four named roles are represented in the audited runtime artifacts | role call accounting changed after the anchor, so historical P0 remains failed |
| Structured protocol and capability/handshake | 3 | partially_proven | typed UDS/subprocess path is exercised | not all roles or all variants cross a process boundary |
| Same-task text and structured comparison | 3 | partially_proven | system-level text/structured comparison records exist | semantic selection, prompts, helpers and carrier vary together in several comparisons |
| Non-text state production, transfer, receipt and consumption | 3 | supported_through_receiver_hydration_only | StateRef publication, transfer and receiver hydration plus backend variants are recorded | downstream consumption is not separately instrumented; not an LLM hidden-state or KV cache handoff |
| Shared memory storage, retrieval and reuse | 4 | supported_with_reuse_class_boundary | memory/replay classes and some reuse signals are persisted | memory match is not automatically a skipped call/tool or reuse_gain |
| Two related continuous tasks and at least ten rounds | 3 | partially_proven | continuous families and round metrics are inventoried | do not generalize a family-specific reuse result to all tasks |
| Communication/token/byte/latency/state/reuse telemetry | 3 | partially_proven | metrics are retained and ratios are recomputed from additive fields | missing values remain null; timing claims require serialized matched reruns |
| Runtime/protocol/statepool/memory/eval system completeness | 3 | partially_proven | multiple implemented subsystems have recorded execution paths | P0 pytest and P1 Stage 18 historical statuses are not all-pass |
| CodeAct and safety boundary | 3 | prototype_or_proxy | fallback-aware CodeAct/sandbox path exists | no nsjail/openEuler final isolation validation in this evidence |
| openEuler delivery reproducibility | 2 | not_supported | container-oriented source/provenance exists | no audited openEuler VM final-delivery validation |

## P0/P1/P2 Issue Ledger

`05_issue_ledger.csv` retains phenomenon, root-cause/hypothesis, evidence, code location, impact, severity, repair, regression risk and minimal validation.

| Priority | Phenomenon | Root cause/hypothesis | Artifact evidence | Code location | Conclusion impact | Minimum repair | Minimum validation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P0 | Historical P0 pytest failure | post-anchor role-call accounting change is consistent with the reported lightweight-stub issue, but does not rewrite history | P0 summary.json/status.tsv/logs/01_pytest_v2.log; later repair log | v2/runtime/smoke.py:56, v2/runtime/smoke.py:59, v2/runtime/smoke.py:115, v2/runtime/smoke.py:319, v2/runtime/smoke.py:349, v2/runtime/smoke.py:469, v2/runtime/smoke.py:470, v2/runtime/smoke.py:473, v2/runtime/smoke.py:474, v2/runtime/smoke.py:479, v2/runtime/smoke.py:480, v2/runtime/smoke.py:483 | P0 cannot be represented as a 16/16 all-pass matrix | retain immutable historical status and separately version the metric repair | target exact failures plus a clearly-labelled tests/v2-only rerun |
| P0 | Stage 18 post-processing failure lacks preserved exception text | documented NameError cannot be independently established because preserved stderr is zero bytes | P1 run.log, Stage 18 stderr, repeat_summary.json | scripts/run_v2_post_full_p1_qwen3_container.sh verifier; current source is post-run code | historical fail stays fail; only a separately-labelled repaired-verifier result is supported | preserve summary and version the static verifier separately | static verify immutable repeat_summary; recover original stderr before asserting a specific historical exception |
| P1 | Carrier comparison changes multiple variables | semantic selection/pruning, prompt layout, tools and carrier are not all frozen | P0 Stages 02/11-14; P1 fixed-answer controls | v2/runtime/compiler.py:8, v2/runtime/compiler.py:147, v2/runtime/compiler.py:151, v2/runtime/compiler.py:154, v2/runtime/compiler.py:180, v2/runtime/compiler.py:188, v2/runtime/compiler.py:215, v2/runtime/compiler.py:250, v2/runtime/compiler.py:260, v2/runtime/compiler.py:285, v2/runtime/compiler.py:296, v2/runtime/compiler.py:316 | typed-carrier-only causal and latency claims are not identified | freeze visibility, selection, tool and scorer contracts | serialized AB/BA repeated matched-control comparison with medians and tail percentiles |
| P1 | Prefix service window is continuous | clean_service_requested is false and cache/order effects can confound a small sample | {"aggregate_recomputation":{"independent":{"hits":66.0,"matches_report":true,"queries":7571.0,"recomputed_hit_rate":0.008717474574032493,"reported_hit_rate":0.008717474574032493},"shared":{"hits":5691.0,"matches_report":true,"queries":7553.0,"recomputed_hit_rate":0.7534754402224282,"reported_hit_rate":0.7534754402224282}},"all_required_pass":true,"artifact_status":"complete_requests_and_summary_present","available":true,"claim_status":"engine_local_prefix_repeat artifact satisfies repaired default verifier; historical summary remains fail","clean_service_requested":false,"current_verifier_status":"post_run_validator_repair_pass","historical_error_evidence":"zero-byte stderr; run.log records only generic stage failure","historical_post_processing_error":"unrecoverable from preserved artifacts: Stage 18 stderr is zero bytes","historical_status":"fail","pair_validation":{"pair_count":4,"rows":[{"all_completion_contracts_valid":true,"counter_claim_allowed":true,"evidence_file":"v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/orion_factory_ops_report_2026.md","failure_or_anomaly":"metadata (repeat/order/evidence) is stored only in repeat_summary; pair_summary provides compatibility/latency","independent_hit_rate":null,"independent_hits":null,"independent_queries":null,"independent_warm_ttft_mean_ms":9717.42440375,"order":"shared_first","pair_ok":true,"pair_summary_parse_status":"ok","pair_summary_path":"/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/stages/18_prefix_parity_clean_repeats/repeat01/pair_summary.json","pair_validation_status":"validated","repeat_index":1,"shared_hit_rate":null,"shared_hits":null,"shared_minus_independent_warm_ttft_ms":-2271.2658707499995,"shared_queries":null,"shared_warm_ttft_mean_ms":7446.158533},{"all_completion_contracts_valid":true,"counter_claim_allowed":true,"evidence_file":"v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/nova_retail_ops_report_2026.md","failure_or_anomaly":"metadata (repeat/order/evidence) is stored only in repeat_summary; pair_summary provides compatibility/latency","independent_hit_rate":null,"independent_hits":null,"independent_queries":null,"independent_warm_ttft_mean_ms":9636.48109225,"order":"independent_first","pair_ok":true,"pair_summary_parse_status":"ok","pair_summary_path":"/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/stages/18_prefix_parity_clean_repeats/repeat02/pair_summary.json","pair_validation_status":"validated","repeat_index":2,"shared_hit_rate":null,"shared_hits":null,"shared_minus_independent_warm_ttft_ms":-1823.1133447500006,"shared_queries":null,"shared_warm_ttft_mean_ms":7813.3677474999995},{"all_completion_contracts_valid":true,"counter_claim_allowed":true,"evidence_file":"v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/orion_factory_ops_report_2026.md","failure_or_anomaly":"metadata (repeat/order/evidence) is stored only in repeat_summary; pair_summary provides compatibility/latency","independent_hit_rate":null,"independent_hits":null,"independent_queries":null,"independent_warm_ttft_mean_ms":9535.7829,"order":"shared_first","pair_ok":true,"pair_summary_parse_status":"ok","pair_summary_path":"/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/stages/18_prefix_parity_clean_repeats/repeat03/pair_summary.json","pair_validation_status":"validated","repeat_index":3,"shared_hit_rate":null,"shared_hits":null,"shared_minus_independent_warm_ttft_ms":-1504.7192225000008,"shared_queries":null,"shared_warm_ttft_mean_ms":8031.063677499999},{"all_completion_contracts_valid":true,"counter_claim_allowed":true,"evidence_file":"v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/nova_retail_ops_report_2026.md","failure_or_anomaly":"metadata (repeat/order/evidence) is stored only in repeat_summary; pair_summary provides compatibility/latency","independent_hit_rate":null,"independent_hits":null,"independent_queries":null,"independent_warm_ttft_mean_ms":8247.950050750002,"order":"independent_first","pair_ok":true,"pair_summary_parse_status":"ok","pair_summary_path":"/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121/stages/18_prefix_parity_clean_repeats/repeat04/pair_summary.json","pair_validation_status":"validated","repeat_index":4,"shared_hit_rate":null,"shared_hits":null,"shared_minus_independent_warm_ttft_ms":-538.4143095000009,"shared_queries":null,"shared_warm_ttft_mean_ms":7709.535741250001}],"validated_pair_count":4},"requirements":[{"gate":"pair_parity","pass":true},{"gate":"repeat_coverage_ge_4","pass":true},{"gate":"AB_BA_coverage","pass":true},{"gate":"completion_contract_parity","pass":true},{"gate":"two_corpus_coverage","pass":true},{"gate":"clean_service_readiness","pass":true},{"gate":"aggregate_counter_rate_recomputation","pass":true}],"service_window":"continuous_service_between_pairs"} | v2/runtime/vllm_metrics.py:9, v2/runtime/vllm_metrics.py:11, v2/runtime/vllm_metrics.py:12, v2/runtime/vllm_metrics.py:19, v2/runtime/vllm_metrics.py:20, v2/runtime/vllm_metrics.py:21, v2/runtime/vllm_metrics.py:22, v2/runtime/vllm_metrics.py:26, v2/runtime/vllm_metrics.py:27, v2/runtime/vllm_metrics.py:35, v2/runtime/vllm_metrics.py:36, v2/runtime/vllm_metrics.py:37 | no clean-service general latency or agent KV-transfer conclusion | report clean and continuous service cohorts separately with counters | four AB/BA pairs per corpus in both cohorts with before/after counters |
| P1 | StateRef downstream consumption is not separately recorded | telemetry has STATE_PUBLISHED and STATE_HYDRATED events but no distinct STATE_CONSUME event or behavior-effect field | runtime_event_evidence: STATE_PUBLISHED=1380, STATE_HYDRATED=4140, STATE_CONSUME=0 | v2/runtime/smoke.py:56, v2/runtime/smoke.py:59, v2/runtime/smoke.py:115, v2/runtime/smoke.py:319, v2/runtime/smoke.py:349, v2/runtime/smoke.py:469, v2/runtime/smoke.py:470, v2/runtime/smoke.py:473, v2/runtime/smoke.py:474, v2/runtime/smoke.py:479, v2/runtime/smoke.py:480, v2/runtime/smoke.py:483 | the audit can support StateRef publication/transfer/receiver hydration, not full behavior-changing consumption | emit a role-attributed consume event plus the consumed field/ref and downstream decision linkage | per-role StateRef on/off or consumed-field perturbation with route/tool/output checks |
| P1 | LogitState participation is only a metric projection | task metrics retain transfer-count/entropy projections but not payload bytes, LogitStateRef registration, receiver, or behavior linkage | 03_logitstate_participation_matrix.csv; 848 positive primary transfer-count rows and zero persisted logit_state_bytes measurements | v2/runtime/logit_state.py:27, v2/runtime/logit_state.py:30, v2/runtime/logit_state.py:31, v2/runtime/logit_state.py:35, v2/runtime/logit_state.py:45, v2/runtime/logit_state.py:83, v2/runtime/logit_state.py:84, v2/runtime/logit_state.py:92, v2/runtime/logit_state.py:94, v2/runtime/logit_state.py:135, v2/runtime/logit_state.py:136, v2/runtime/logit_state.py:140 | no hidden-state/KV-transfer, receiving-agent, route/tool/retry/fallback-effect, quality, or efficiency claim is supported | persist ref registration, byte length/hash, receiver hydration/consume and decision provenance with explicit enabled/disabled mode | matched LogitState on/off experiment with payload/ref/receiver traces and quality/cost outcomes |
| P2 | Precompiled CanonicalTaskSpec is a strong task prior | bounded holdout does not eliminate static task-contract/route surfaces | P0 Stage 08 prompt taint and paraphrase artifacts | v2/runtime/compiler.py:8, v2/runtime/compiler.py:147, v2/runtime/compiler.py:151, v2/runtime/compiler.py:154, v2/runtime/compiler.py:180, v2/runtime/compiler.py:188, v2/runtime/compiler.py:215, v2/runtime/compiler.py:250, v2/runtime/compiler.py:260, v2/runtime/compiler.py:285, v2/runtime/compiler.py:296, v2/runtime/compiler.py:316 | no free-text task-contract compilation headline | separate raw request from a safe semantic-plan suite | holdout/paraphrase/taint suite with no task-contract oracle and role-aware review |

## Conclusion Classes

- **Supported:** P0 has a complete recorded 16-label matrix with a historical pytest failure; P1 is additive; Stage 18 has completed repeat artifacts that satisfy the repaired default verifier.
- **Proxy/diagnostic only:** LogitState metric projection without persisted bytes/ref registration/receiver/behavior evidence; loopback backend functionality; single-run timing.
- **Not claimable:** Agent-to-Agent KV/hidden-state transfer, a new all-green P0 matrix, universal backend performance gain, free-text CanonicalTaskSpec compilation, and openEuler final-delivery validation.
