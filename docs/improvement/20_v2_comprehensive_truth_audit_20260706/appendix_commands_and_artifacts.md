# 附录：命令与 Artifacts

## 必读文档

本轮审计前和审计过程中阅读了下列文件。部分 prompt 和 01-19 中间态 improvement 文档已在后续整理中从 active docs tree 清理；保留此列表只用于说明当时审计输入，不表示它们仍是当前阅读入口。

- `README.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`
- `docs/reference/题目.md`
- `docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md`
- `docs/improvement/18_claim_upgrade_execution_plan.md`
- `docs/improvement/17_final_system_audit_20260706.md`
- `docs/improvement/artifacts/17_final_system_audit/17a_evidence_table.md`（历史路径，已从 active docs tree 清理）
- `17b_code_review_findings.md`
- `17c_benchmark_json_analysis.md`
- `17d_issue_ledger.md`
- `17e_remediation_plan.md`
- `17f_safe_claim_language.md`
- `docs/improvement/19_claim_upgrade_completion_report_20260706.md`
- `docs/improvement/PROMPT_FOR_V2_COMPREHENSIVE_TRUTH_AUDIT.md`

同时扫描了：

- `docs/improvement/`
- `docs/improvement/artifacts/`（历史路径，已从 active docs tree 清理）
- `v2/`
- `tests/v2/`
- `tasks/formal/`
- `scripts/run_v2_full_container_audit_suite.sh`

## Git 命令

```bash
git status -sb
git log --oneline --decorate -n 50
git log --oneline --decorate -- docs/improvement docs/reports docs/contracts v2 tests/v2 scripts | sed -n '1,200p'
git diff --stat
git diff --check
git show --stat --oneline HEAD
git show --stat --oneline HEAD~1
git show --stat --oneline HEAD~2
git show --stat --oneline HEAD~3
```

## 容器环境命令

Activation 尝试：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && source deploy/activate_statebus_host.sh && python -c "import v2.runtime.driver; print(\"Environment OK\")"'
```

结果：失败，因为 conda 缺失。

Python fallback 检查：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -c "import pytest; print(\"pytest ok\")"'
```

结果：通过。

## 静态检查

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m py_compile v2/runtime/driver.py v2/runtime/smoke.py v2/runtime/replay.py v2/state/store.py v2/benchmark/live_runner.py v2/benchmark/minimal_runner.py v2/benchmark/fixed_answer_runner.py v2/benchmark/comparator_runner.py v2/benchmark/external_text_baseline.py v2/benchmark/task_registry.py v2/benchmark/reporting.py v2/benchmark/models.py v2/control/transport.py v2/control/subprocess_worker.py v2/contracts/models.py v2/refs/models.py'
```

结果：通过。

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && bash -n scripts/run_v2_full_container_audit_suite.sh'
```

结果：通过。

## 测试

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_continuous_runner.py'
```

修复后结果：

```text
11 passed in 342.32s (0:05:42)
```

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_state_materialization.py tests/v2/test_minimal_benchmark.py tests/v2/test_preflight_and_live_runner.py tests/v2/test_continuous_runner.py'
```

结果：

```text
49 passed in 371.18s (0:06:11)
```

Post-fix targeted tests：

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py
```

结果：

```text
45 passed in 16.79s
```

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/v2/test_smoke.py::test_v2_smoke_aggregates_role_path_token_usage tests/v2/test_smoke.py::test_v2_smoke_cold_start_mode_executes_role_path_without_seeded_replay tests/v2/test_minimal_benchmark.py::test_minimal_benchmark_family_api_mode_accepts_compact_role_alias_responses tests/v2/test_minimal_benchmark.py::test_minimal_benchmark_family_api_mode_accepts_string_candidate_alias
```

结果：

```text
4 passed in 4.40s
```

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/v2/test_runtime_and_benchmark.py::test_fixed_answer_metric_value_schema_distinguishes_requested_metric_from_revenue tests/v2/test_compare_diagnostics.py
```

结果：

```text
6 passed in 8.96s
```

Closure-pass targeted tests：

```bash
source deploy/activate_statebus_host.sh
python -m py_compile v2/benchmark/external_text_baseline.py tests/v2/test_fixed_answer_and_external_baseline.py
```

结果：通过。

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py tests/v2/test_compare_diagnostics.py tests/v2/test_runtime_and_benchmark.py::test_fixed_answer_metric_value_schema_distinguishes_requested_metric_from_revenue
```

结果：

```text
53 passed in 18.45s
```

Transport retry targeted tests:

```bash
source deploy/activate_statebus_host.sh
python -m py_compile runtime/llm.py tests/v2/test_fixed_answer_and_external_baseline.py
python -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py::test_openai_compatible_client_retries_transient_transport_error tests/v2/test_fixed_answer_and_external_baseline.py::test_openai_compatible_client_stops_after_transport_retry_budget
```

结果：

```text
2 passed in 0.75s
```

Focused local+api comprehensive diagnostic test stage：

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/stages/02_pytest_focused_v2/console.log
```

结果：

```text
109 passed
```

Docker root control/UDS/subprocess subset：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && source /usr/local/bin/activate_statebus_container.sh && /usr/bin/python3 -m pytest -q tests/v2/test_control_plane.py tests/v2/test_uds_loopback.py tests/v2/test_subprocess_executor.py'
```

结果：

```text
9 passed
```

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m runtime.smoke'
```

结果：

```text
statebus smoke ok: mode=text memory_hits=0.0 messages=292.0 control_bytes=243456.0 task_ms=5895.53
statebus smoke ok: mode=protocol memory_hits=0.0 messages=292.0 control_bytes=215901.0 task_ms=5469.95
statebus comparator artifact ok: external_claim_surface=formal_ready api_repeat1_ready=True
```

## Benchmark 命令

Auto 模式：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic --state-pool-mode auto --runtime-root /tmp/statebus-audit-formal-auto-runtime --workspace-root /tmp/statebus-audit-formal-auto-workspaces --socket-path /tmp/statebus-audit-formal-auto.sock --suite-id statebus-audit-formal-auto > /tmp/statebus-audit-formal-auto.stdout.json'
```

Shared memory 模式：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic --state-pool-mode shared_memory --runtime-root /tmp/statebus-audit-formal-shm-runtime --workspace-root /tmp/statebus-audit-formal-shm-workspaces --socket-path /tmp/statebus-audit-formal-shm.sock --suite-id statebus-audit-formal-shm > /tmp/statebus-audit-formal-shm.stdout.json'
```

Memfd + local embedding 模式：

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode local --state-pool-mode memfd --runtime-root /tmp/statebus-audit-formal-memfd-runtime --workspace-root /tmp/statebus-audit-formal-memfd-workspaces --socket-path /tmp/statebus-audit-formal-memfd.sock --suite-id statebus-audit-formal-memfd > /tmp/statebus-audit-formal-memfd.stdout.json'
```

已复制 artifacts：

- `artifacts/formal_auto.stdout.json`
- `artifacts/formal_shared_memory.stdout.json`
- `artifacts/formal_memfd_local.stdout.json`
- `artifacts/preflight_deterministic.stdout.json`

抽取的 formal 字段：

```json
{"artifact": "formal_auto.stdout.json", "case_count": 25.0, "embedding_mode": "deterministic", "family_count": 5, "memfd_bytes_transferred": 0.0, "memfd_publish_count": 0.0, "memfd_transfer_count": 0.0, "mmap_publish_count": 0.0, "quality_pass": 25.0, "role_path_mode": "deterministic", "semantic_state_transfer_count": 25.0, "shared_memory_publish_count": 25.0, "state_pool_mode_requested": "auto", "state_pool_mode_used": "shared_memory", "suite_id": "statebus-audit-formal-auto-formal"}
{"artifact": "formal_memfd_local.stdout.json", "case_count": 25.0, "embedding_mode": "local", "family_count": 5, "memfd_bytes_transferred": 247076.0, "memfd_publish_count": 25.0, "memfd_transfer_count": 25.0, "mmap_publish_count": 0.0, "quality_pass": 25.0, "role_path_mode": "deterministic", "semantic_state_transfer_count": 25.0, "shared_memory_publish_count": 0.0, "state_pool_mode_requested": "memfd", "state_pool_mode_used": "memfd", "suite_id": "statebus-audit-formal-memfd-formal"}
{"artifact": "formal_shared_memory.stdout.json", "case_count": 25.0, "embedding_mode": "deterministic", "family_count": 5, "memfd_bytes_transferred": 0.0, "memfd_publish_count": 0.0, "memfd_transfer_count": 0.0, "mmap_publish_count": 0.0, "quality_pass": 25.0, "role_path_mode": "deterministic", "semantic_state_transfer_count": 25.0, "shared_memory_publish_count": 25.0, "state_pool_mode_requested": "shared_memory", "state_pool_mode_used": "shared_memory", "suite_id": "statebus-audit-formal-shm-formal"}
```

## Post-fix targeted live artifacts

Formal internal targeted rerun：

```text
/home/qcrs/statebus/runs/v2-targeted-json-retry-formal-20260707_191045/
```

结果：

```json
{"suite_id":"targeted-json-retry-formal-formal","L3_case_count":25,"L3_quality_pass_count":25,"family_count":5,"state_pool_mode_used":"memfd","memfd_transfer_count":25,"memfd_bytes_transferred":247076}
```

Formal compare targeted rerun：

```text
/home/qcrs/statebus/runs/v2-targeted-json-retry-compare-20260707_192452/
```

结果：

```json
{"formal_compare_scope_label":"formal_financial_family_8case_compare","formal_compare_case_count":8,"formal_compare_family_count":1,"formal_registry_case_count":25,"formal_registry_family_count":5,"formal_compare_full_registry_coverage":false,"strict_equal_quality_comparison_valid":true,"quality_superiority_comparison_valid":false,"formal_external_claim_kind":"efficiency_superiority_equal_quality","formal_efficiency_superiority_claim_allowed":true,"formal_quality_superiority_claim_allowed":false,"state_pool_mode_used":"memfd","memfd_transfer_count":8}
```

Interrupted comprehensive run:

```text
/home/qcrs/statebus/runs/v2-local-api-20260707_015709/
```

关键状态：

- `02_pytest_focused_v2`：107 passed。
- `r01_05_formal_api_local_memfd`：required failure，empty executor JSON before retry fix。
- `r01_06_formal_compare_api_local_memfd`：required pass。
- `r01_09_continuous_api_local`：optional timeout 124 at 2400s。
- `r01_10_continuous_replay_api_local`：optional failure，malformed summarizer JSON before retry fix。
- `r01_11_replay_negative_api_local`：required pass。
- no final `summary.json` because optional flagship tail was stopped after the run was already invalid.

Post-fix comprehensive diagnostic rerun:

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/
/home/qcrs/statebus/runs/v2-local-api-20260707_034412/
```

状态：

```json
{"failed_required_stage_count":1,"failed_required_stages":["r01_05_formal_api_local_memfd"],"formal_compare_claim_kind":"debug_only","formal_compare_case_count":8,"formal_compare_family_count":1,"formal_compare_full_registry_coverage":false}
```

关键结果：

- container activation：`/usr/local/bin/activate_statebus_container.sh` success。
- focused pytest：109 passed。
- required formal internal：timeout 124 at 1800s。
- formal compare：exit 0，8/8 quality floor pass，但 external fairness hard gate 7/8；`benchmark-sample-6` failed `planner_visible_choice_only`。
- replay negative：7/7 pass。
- optional continuous、continuous replay、flagship：timeout。

Diagnostics artifact：

```json
{"manifest":"docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_034412/diagnostics/manifest.json","copied_file_count":2310}
```

该 artifact copy 包含 nested benchmark reports、external/statebus outputs、state metadata、hydration audits、ref registries、socket path logs；可从 docs tree 复盘 compare case expected/observed fields。

Post-fix passing comprehensive core rerun:

```bash
source deploy/activate_statebus_host.sh
STATEBUS_LOCAL_API_RUN_FLAGSHIP=0 \
STATEBUS_LOCAL_API_FORMAL_TIMEOUT_SECONDS=3600 \
STATEBUS_LOCAL_API_COMPARE_TIMEOUT_SECONDS=2400 \
STATEBUS_LOCAL_API_CONTINUOUS_TIMEOUT_SECONDS=4200 \
STATEBUS_LOCAL_API_REPLAY_TIMEOUT_SECONDS=4200 \
bash scripts/run_v2_local_api_comprehensive_stats.sh
```

Artifact:

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/
/home/qcrs/statebus/runs/v2-local-api-20260707_091807/
```

关键结果：

- stage_count：12。
- failed_stage_count：0。
- failed_required_stage_count：0。
- focused pytest：111 passed。
- `r01_05_formal_api_local_memfd`：25/25，5 families，memfd transfer 25，memfd bytes 247076。
- `r01_06_formal_compare_api_local_memfd`：8/8 strict equal-quality，fairness gate failed case count 0，full registry coverage false，`formal_external_claim_kind=debug_only`。
- `r01_10_continuous_replay_api_local`：20/20 target replay observed，17 validated，3 exact，answer restoration 0。
- `r01_11_replay_negative_api_local`：7/7 pass。

Diagnostics artifact：

```json
{"manifest":"docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/diagnostics/manifest.json","copied_file_count":1384}
```

Flagship-enabled partial rerun:

```bash
source deploy/activate_statebus_host.sh
STATEBUS_LOCAL_API_RUN_FLAGSHIP=1 \
STATEBUS_LOCAL_API_FORMAL_TIMEOUT_SECONDS=3600 \
STATEBUS_LOCAL_API_COMPARE_TIMEOUT_SECONDS=2400 \
STATEBUS_LOCAL_API_CONTINUOUS_TIMEOUT_SECONDS=4200 \
STATEBUS_LOCAL_API_REPLAY_TIMEOUT_SECONDS=4200 \
STATEBUS_LOCAL_API_FLAGSHIP_TIMEOUT_SECONDS=7200 \
bash scripts/run_v2_local_api_comprehensive_stats.sh
```

Artifact:

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/
/home/qcrs/statebus/runs/v2-local-api-20260707_115051/
```

关键结果：

- stage_count：13。
- failed_stage_count：3。
- failed_required_stage_count：0。
- failed_stages：`r01_09_continuous_api_local`、`r01_10_continuous_replay_api_local`、`r01_12_flagship_ablation_api_local`。
- `r01_05_formal_api_local_memfd`：25/25，5 families，memfd transfer 25，memfd bytes 247076。
- `r01_06_formal_compare_api_local_memfd`：8/8 strict equal-quality，fairness gate failed case count 0，full registry coverage false，`formal_external_claim_kind=debug_only`。
- `r01_11_replay_negative_api_local`：7/7 pass。

失败原因：

- `r01_09_continuous_api_local`：API DNS/connect error。
- `r01_10_continuous_replay_api_local`：API DNS/connect error。
- `r01_12_flagship_ablation_api_local`：API read timeout。

Diagnostics artifact：

```json
{"manifest":"docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_115051/diagnostics/manifest.json","copied_file_count":663}
```

该 run 不能作为 optional continuous/replay/flagship passing evidence。

Post-transport-retry flagship rerun before selection retry:

```bash
source deploy/activate_statebus_host.sh
STATEBUS_LOCAL_API_RUN_FLAGSHIP=1 \
STATEBUS_LOCAL_API_FORMAL_TIMEOUT_SECONDS=3600 \
STATEBUS_LOCAL_API_COMPARE_TIMEOUT_SECONDS=2400 \
STATEBUS_LOCAL_API_CONTINUOUS_TIMEOUT_SECONDS=4200 \
STATEBUS_LOCAL_API_REPLAY_TIMEOUT_SECONDS=4200 \
STATEBUS_LOCAL_API_FLAGSHIP_TIMEOUT_SECONDS=7200 \
bash scripts/run_v2_local_api_comprehensive_stats.sh
```

Artifact:

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_130958/
/home/qcrs/statebus/runs/v2-local-api-20260707_130958/
```

关键结果：

- stage_count：13。
- failed_stage_count：1。
- failed_required_stage_count：0。
- failed_stages：`r01_12_flagship_ablation_api_local`。
- `r01_05_formal_api_local_memfd`：25/25，5 families，memfd transfer 25，memfd bytes 247076。
- `r01_06_formal_compare_api_local_memfd`：8/8 strict equal-quality，fairness gate failed case count 0，full registry coverage false，`formal_external_claim_kind=debug_only`。
- `r01_09_continuous_api_local`：3 families / 30 rounds，`L3_reuse_gain=9`。
- `r01_10_continuous_replay_api_local`：20/20 target replay observed，17 validated，3 exact，answer restoration 0。
- `r01_12_flagship_ablation_api_local`：`strict_visible_candidate_mismatch:csv_profiler::csv_profiler`。

该 run 是 selection retry 的触发证据，不是 latest passing evidence。

Full `RUN_FLAGSHIP=1` passing comprehensive rerun:

```bash
source deploy/activate_statebus_host.sh
STATEBUS_LOCAL_API_RUN_FLAGSHIP=1 \
STATEBUS_LOCAL_API_FORMAL_TIMEOUT_SECONDS=3600 \
STATEBUS_LOCAL_API_COMPARE_TIMEOUT_SECONDS=2400 \
STATEBUS_LOCAL_API_CONTINUOUS_TIMEOUT_SECONDS=4200 \
STATEBUS_LOCAL_API_REPLAY_TIMEOUT_SECONDS=4200 \
STATEBUS_LOCAL_API_FLAGSHIP_TIMEOUT_SECONDS=7200 \
bash scripts/run_v2_local_api_comprehensive_stats.sh
```

Artifact:

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/
/home/qcrs/statebus/runs/v2-local-api-20260707_163354/
```

关键结果：

- stage_count：13。
- failed_stage_count：0。
- failed_required_stage_count：0。
- focused pytest：115 passed。
- `r01_05_formal_api_local_memfd`：25/25，5 families，memfd transfer 25，memfd bytes 247076。
- `r01_06_formal_compare_api_local_memfd`：8/8 strict equal-quality，fairness gate failed case count 0，full registry coverage false，`formal_external_claim_kind=debug_only`。
- `r01_09_continuous_api_local`：3 families / 30 rounds，`L3_reuse_gain=9`。
- `r01_10_continuous_replay_api_local`：20/20 target replay observed，17 validated，3 exact，answer restoration 0。
- `r01_12_flagship_ablation_api_local`：stage exit 0；stress family pass 3/6；StateRef prompt savings recorded.

Diagnostics artifact：

```json
{"manifest":"docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/diagnostics/manifest.json","copied_file_count":2558}
```

该 run 是当前 latest full `RUN_FLAGSHIP=1` passing evidence。限制是 flagship stress 只有 3/6，不能 claim all-pass；formal compare 仍是 8-case / 1-family scope，不能 claim full registry external superiority。

## 说明

- Prompt 中的 `jq` extraction 失败，因为容器缺少 `jq`。
- 本轮用 Python 抽取相同字段。
- Formal external compare 已有 post-fix API-key-backed evidence，但 scope 仍是 formal financial 8 cases / 1 family，不是 full registry 25/5。
- `local_api_20260707_034412` 是 diagnostic/failing-required comprehensive rerun；`local_api_20260707_091807` 是 historical passing comprehensive core rerun，但 flagship 显式关闭；`local_api_20260707_115051` 是 transport failure rerun；`local_api_20260707_130958` 是 selection retry 触发证据；`local_api_20260707_163354` 是当前 latest full `RUN_FLAGSHIP=1` passing comprehensive rerun。
