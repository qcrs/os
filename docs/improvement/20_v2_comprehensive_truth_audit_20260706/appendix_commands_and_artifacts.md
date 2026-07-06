# Appendix: Commands And Artifacts

## Required document reads

Read before and during this audit:

- `README.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`
- `docs/reference/题目.md`
- `docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md`
- `docs/improvement/18_claim_upgrade_execution_plan.md`
- `docs/improvement/17_final_system_audit_20260706.md`
- `docs/improvement/artifacts/17_final_system_audit/17a_evidence_table.md`
- `17b_code_review_findings.md`
- `17c_benchmark_json_analysis.md`
- `17d_issue_ledger.md`
- `17e_remediation_plan.md`
- `17f_safe_claim_language.md`
- `docs/improvement/19_claim_upgrade_completion_report_20260706.md`
- `docs/improvement/PROMPT_FOR_V2_COMPREHENSIVE_TRUTH_AUDIT.md`

Also scanned:

- `docs/improvement/`
- `docs/improvement/artifacts/`
- `v2/`
- `tests/v2/`
- `tasks/formal/`
- `scripts/run_v2_full_container_audit_suite.sh`

## Git commands

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

## Container environment commands

Activation attempt:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && source deploy/activate_statebus_host.sh && python -c "import v2.runtime.driver; print(\"Environment OK\")"'
```

Result: failed because conda is absent.

Python fallback check:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -c "import pytest; print(\"pytest ok\")"'
```

Result: passed.

## Static checks

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m py_compile v2/runtime/driver.py v2/runtime/smoke.py v2/runtime/replay.py v2/state/store.py v2/benchmark/live_runner.py v2/benchmark/minimal_runner.py v2/benchmark/fixed_answer_runner.py v2/benchmark/comparator_runner.py v2/benchmark/external_text_baseline.py v2/benchmark/task_registry.py v2/benchmark/reporting.py v2/benchmark/models.py v2/control/transport.py v2/control/subprocess_worker.py v2/contracts/models.py v2/refs/models.py'
```

Result: pass.

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && bash -n scripts/run_v2_full_container_audit_suite.sh'
```

Result: pass.

## Tests

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_continuous_runner.py'
```

Result after fix:

```text
11 passed in 342.32s (0:05:42)
```

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m pytest -q tests/v2/test_state_materialization.py tests/v2/test_minimal_benchmark.py tests/v2/test_preflight_and_live_runner.py tests/v2/test_continuous_runner.py'
```

Result:

```text
49 passed in 371.18s (0:06:11)
```

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m runtime.smoke'
```

Result:

```text
statebus smoke ok: mode=text memory_hits=0.0 messages=292.0 control_bytes=243456.0 task_ms=5895.53
statebus smoke ok: mode=protocol memory_hits=0.0 messages=292.0 control_bytes=215901.0 task_ms=5469.95
statebus comparator artifact ok: external_claim_surface=formal_ready api_repeat1_ready=True
```

## Benchmarks

Auto:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic --state-pool-mode auto --runtime-root /tmp/statebus-audit-formal-auto-runtime --workspace-root /tmp/statebus-audit-formal-auto-workspaces --socket-path /tmp/statebus-audit-formal-auto.sock --suite-id statebus-audit-formal-auto > /tmp/statebus-audit-formal-auto.stdout.json'
```

Shared memory:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic --state-pool-mode shared_memory --runtime-root /tmp/statebus-audit-formal-shm-runtime --workspace-root /tmp/statebus-audit-formal-shm-workspaces --socket-path /tmp/statebus-audit-formal-shm.sock --suite-id statebus-audit-formal-shm > /tmp/statebus-audit-formal-shm.stdout.json'
```

Memfd + local embedding:

```bash
docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && /usr/bin/python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode local --state-pool-mode memfd --runtime-root /tmp/statebus-audit-formal-memfd-runtime --workspace-root /tmp/statebus-audit-formal-memfd-workspaces --socket-path /tmp/statebus-audit-formal-memfd.sock --suite-id statebus-audit-formal-memfd > /tmp/statebus-audit-formal-memfd.stdout.json'
```

Copied artifacts:

- `artifacts/formal_auto.stdout.json`
- `artifacts/formal_shared_memory.stdout.json`
- `artifacts/formal_memfd_local.stdout.json`
- `artifacts/preflight_deterministic.stdout.json`

Extracted formal fields:

```json
{"artifact": "formal_auto.stdout.json", "case_count": 25.0, "embedding_mode": "deterministic", "family_count": 5, "memfd_bytes_transferred": 0.0, "memfd_publish_count": 0.0, "memfd_transfer_count": 0.0, "mmap_publish_count": 0.0, "quality_pass": 25.0, "role_path_mode": "deterministic", "semantic_state_transfer_count": 25.0, "shared_memory_publish_count": 25.0, "state_pool_mode_requested": "auto", "state_pool_mode_used": "shared_memory", "suite_id": "statebus-audit-formal-auto-formal"}
{"artifact": "formal_memfd_local.stdout.json", "case_count": 25.0, "embedding_mode": "local", "family_count": 5, "memfd_bytes_transferred": 247076.0, "memfd_publish_count": 25.0, "memfd_transfer_count": 25.0, "mmap_publish_count": 0.0, "quality_pass": 25.0, "role_path_mode": "deterministic", "semantic_state_transfer_count": 25.0, "shared_memory_publish_count": 0.0, "state_pool_mode_requested": "memfd", "state_pool_mode_used": "memfd", "suite_id": "statebus-audit-formal-memfd-formal"}
{"artifact": "formal_shared_memory.stdout.json", "case_count": 25.0, "embedding_mode": "deterministic", "family_count": 5, "memfd_bytes_transferred": 0.0, "memfd_publish_count": 0.0, "memfd_transfer_count": 0.0, "mmap_publish_count": 0.0, "quality_pass": 25.0, "role_path_mode": "deterministic", "semantic_state_transfer_count": 25.0, "shared_memory_publish_count": 25.0, "state_pool_mode_requested": "shared_memory", "state_pool_mode_used": "shared_memory", "suite_id": "statebus-audit-formal-shm-formal"}
```

## Notes

- The prompt's `jq` extraction failed because `jq` is missing in the container.
- Python extraction was used for the same fields.
- Formal external compare was not run because no API-key-backed formal compare evidence was available in this audit.
