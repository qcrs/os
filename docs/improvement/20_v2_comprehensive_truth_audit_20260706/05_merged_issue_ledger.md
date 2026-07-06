# Merged Issue Ledger

## ID: V2-AUDIT-001

Severity: P1

Title: Container activation instructions do not match the running container.

Sources: audit prompt, Docker-root verification

Affected files: `deploy/activate_statebus_host.sh`, Docker image/runtime docs

Evidence: `source deploy/activate_statebus_host.sh` failed in `statebus-dev-qcrs` because conda was absent; repo mount is `/workspace/statebus/project`, not `/workspace`.

Why it matters: Required verification can silently become host verification or unactivated container verification.

Fix strategy: Add a container-specific activation path or update container image to include the expected conda environment.

Verification: `docker exec -u root statebus-dev-qcrs bash -lc 'cd /workspace/statebus/project && source deploy/activate_statebus_host.sh && python -c "import v2.runtime.driver"'`.

Status: open; documented limitation

## ID: V2-AUDIT-002

Severity: P1

Title: Exact replay was incorrectly counted as answer restoration.

Sources: `17e_remediation_plan.md`, code audit, failed pytest

Affected files: `v2/runtime/driver.py`, `v2/benchmark/continuous_runner.py`, `tests/v2/test_continuous_runner.py`

Evidence: Runtime metric and continuous runner fallbacks previously made `answer_restoration_replay_count == exact_replay_count`.

Why it matters: It created a false generic answer-restoration claim surface.

Fix strategy: Keep answer restoration at zero until a real answer-restoration mechanism exists.

Verification: `tests/v2/test_continuous_runner.py` passed 11/11; combined focused pytest passed 49/49.

Status: fixed this audit

## ID: V2-AUDIT-003

Severity: P1

Title: Formal external superiority is not proven.

Sources: `19_claim_upgrade_completion_report_20260706.md`, `17f_safe_claim_language.md`, comparator source review

Affected files: `v2/benchmark/comparator_runner.py`, `v2/benchmark/live_runner.py`, `scripts/run_v2_full_container_audit_suite.sh`, docs

Evidence: No formal API compare JSON. Full audit script runs compare at `--benchmark-tier dev`.

Why it matters: External superiority is a high-value contest claim and needs same-tier evidence.

Fix strategy: Run formal compare with real API key and archive JSON, or keep claim unsupported.

Verification: `python3 -m v2.benchmark.live_runner --suite compare --benchmark-tier formal --role-path-mode api --embedding-mode local ...`.

Status: open; unsupported

## ID: V2-AUDIT-004

Severity: P1

Title: CodeAct realtime LLM code generation is not proven by current formal benchmark.

Sources: historical experiment summary, CodeAct source review

Affected files: `docs/reports/v2_experiment_summary_20260703.md`, `v2/runtime/codeact.py`, `v2/runtime/codeact_sandbox.py`

Evidence: Current formal audit evidence is bounded deterministic/local benchmark evidence; older 5/5 CodeAct LLM diagnostic is historical.

Why it matters: Realtime code-generation claims would overstate the current benchmark.

Fix strategy: Keep bounded CodeAct wording; add formal API CodeAct run if needed.

Verification: New report warning added; future API CodeAct artifact required for upgrade.

Status: partially fixed by documentation downgrade; feature claim unsupported

## ID: V2-AUDIT-005

Severity: P2

Title: Family validator files are helper artifacts, not active primary validators.

Sources: `18_claim_upgrade_execution_plan.md`, source search

Affected files: `tasks/formal/*/validator.py`, `v2/runtime/smoke.py`

Evidence: `validator.py` files define simple `validate_output`, but benchmark validation uses `_expected_fact_pass`.

Why it matters: Validator integration can be overclaimed.

Fix strategy: Integrate validators into task loading or rename them as examples.

Verification: Add a failing family-specific validator test that actually affects benchmark quality gate.

Status: open

## ID: V2-AUDIT-006

Severity: P1

Title: Deterministic formal evidence can be confused with API evidence.

Sources: formal artifact review, role-path source review

Affected files: docs, benchmark reports

Evidence: Fresh formal JSON records `role_path_mode=deterministic`; API mode was not rerun in this audit.

Why it matters: Deterministic harness success does not prove API behavior.

Fix strategy: Label deterministic evidence in every claim; run API formal evidence separately.

Verification: API formal JSON with role call telemetry.

Status: open; claim-language control required

## ID: V2-AUDIT-007

Severity: P1

Title: State-pool backend observability previously underreported actual backend after release.

Sources: `3738f34`, state store tests, fresh formal JSON

Affected files: `v2/state/store.py`

Evidence: `backend_name` now uses `last_published_storage_kind` and publish counts; fresh formal runs show correct used backend.

Why it matters: `state_pool_mode_used` must report actual backend, not requested mode.

Fix strategy: Already fixed before this audit.

Verification: auto/shared_memory/memfd formal artifacts.

Status: fixed before this audit; verified here

## ID: V2-AUDIT-008

Severity: P2

Title: Memfd unavailable fallback lacks real-machine validation.

Sources: statepool review, test scope review

Affected files: `v2/state/store.py`, tests

Evidence: Memfd works on this container; unavailable fallback remains unit/failure-path evidence.

Why it matters: Fallback robustness claims need realistic negative environment evidence.

Fix strategy: Add a no-memfd validation stage or explicit capability-masked subprocess test.

Verification: Archived run where memfd is unavailable and fallback respects shared-memory budget.

Status: open

## ID: V2-AUDIT-009

Severity: P1

Title: End-to-end speed advantage is unsupported.

Sources: `17f_safe_claim_language.md`, `19_claim_upgrade_completion_report_20260706.md`

Affected files: docs/reports

Evidence: No serialized formal external API timing rerun in this audit.

Why it matters: Speed claims are easy to invalidate without controlled same-tier reruns.

Fix strategy: Keep unsupported; require serialized benchmark reruns.

Verification: Same-tier StateBus vs external compare with quality/fairness gate pass.

Status: open; unsupported

## ID: V2-AUDIT-010

Severity: P2

Title: openEuler VM validation is not performed.

Sources: AGENTS constraints, audit prompt

Affected files: docs/deploy claims

Evidence: This audit used the running container, not the openEuler VM validation stage.

Why it matters: Compatibility claims must not be made from non-VM evidence.

Fix strategy: Run VM validation stage and archive output.

Verification: VM command log and report.

Status: open; unsupported

## ID: V2-AUDIT-011

Severity: P2

Title: Container lacks `jq`, so prompt extraction command is not portable.

Sources: Docker-root command failure

Affected files: Docker image, audit scripts

Evidence: `bash: line 1: jq: command not found`; Python extraction succeeded.

Why it matters: Required audit scripts should not depend on absent tools.

Fix strategy: Install `jq` in the image or add Python fallback extraction script.

Verification: `docker exec ... jq --version` or Python fallback script green.

Status: open; workaround used
