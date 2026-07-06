# StateBus v2 Comprehensive Truth Audit - Executive Summary

Date: 2026-07-06
Branch: `feat/statebus-v2-container-runtime`
Scope: claim-upgrade docs, artifacts, source, tests, Docker-root verification, and follow-up fixes.

## Direct conclusion

The current v2 claim-upgrade is partially real and partially still bounded by deterministic or missing external evidence.

Fully supported by this audit:

- Formal internal benchmark now loads 25 cases across 5 registered families and passes 25/25 in deterministic formal runs.
- `--state-pool-mode` is wired through the formal runner; fresh runs prove `auto` and `shared_memory` use shared memory, and `memfd + local embedding` uses memfd with 25 publish/transfer events.
- State-pool backend observability survives handle release via `last_published_storage_kind` and `storage_publish_counts`.
- `SemanticStateRef` and `ExecutionArtifactRef` are separate model types and registry entries.
- Text and protocol smoke paths run in the container-root Python path.

Partially supported:

- Four roles exist and API mode calls Planner, Retriever, Executor, and Summarizer separately, but the fresh formal evidence in this audit is deterministic harness evidence, not fresh API role evidence.
- UDS + typed Protobuf is implemented for protocol frames, but protobuf messages still carry several JSON-encoded fields. That is acceptable as a typed-envelope implementation, not a pure protobuf schema.
- Semantic state transfer and hydration accounting are real, but current claims must stay tied to the measured telemetry and not imply arbitrary non-text reasoning.
- CodeAct is a bounded, deterministic plan/execution path with sandbox telemetry. Current formal evidence does not prove realtime LLM-generated code.

Unsupported or documentation-only:

- Formal external superiority: not rerun; no `STATEBUS_LLM_API_KEY` formal compare JSON in this audit.
- End-to-end speed advantage: not supported by current evidence.
- openEuler VM validation: not performed here.
- Generic answer restoration: explicitly not supported; exact replay is no longer counted as answer restoration.
- Container activation via `deploy/activate_statebus_host.sh`: failed in the running container because conda is absent.

## Highest-risk findings

1. The Docker prompt path and environment instructions are stale. The repository is mounted at `/workspace/statebus/project`, not `/workspace`, and the activation script fails in the container because conda is missing.
2. A stale test/reporting contract still equated exact replay with `answer_restoration_replay_count`. This was fixed in code and tests during this audit.
3. Formal external superiority remains unproven. The full audit script still runs compare at `--benchmark-tier dev`, not formal.
4. CodeAct evidence must stay bounded. Existing historical LLM generation diagnostics cannot be promoted to current formal benchmark proof.
5. `tasks/formal/*/validator.py` files exist but are not the main benchmark validation path. The actual quality gate is the generic `expected_facts` path in `v2/runtime/smoke.py`.
6. Memfd unavailable fallback remains mostly unit/monkeypatch evidence, not a real no-memfd host validation.
7. The formal runs are strong internal deterministic evidence, not external API evidence.
8. `jq` is absent inside the container, so required extraction had to use container-root `python3`.

## Fixes applied in this audit

- `v2/runtime/driver.py`: `answer_restoration_replay_count` is now always `0.0` instead of aliasing exact replay.
- `v2/benchmark/continuous_runner.py`: removed fallback logic that synthesized answer restoration from exact replay.
- `tests/v2/test_continuous_runner.py`: updated family, case, and collection assertions to enforce the corrected metric.
- `docs/reports/v2_experiment_summary_20260703.md`: added a historical warning around the CodeAct diagnostic section.
- Added this audit directory and copied fresh benchmark JSON artifacts.

## Verification summary

All verification below was run with Docker root using `/usr/bin/python3` inside `statebus-dev-qcrs`, because conda activation failed:

- `py_compile` for required v2 modules: pass.
- `bash -n scripts/run_v2_full_container_audit_suite.sh`: pass.
- Focused post-fix pytest command: 49 passed in 371.18s.
- `tests/v2/test_continuous_runner.py`: 11 passed in 342.32s after the metric fix.
- `python3 -m runtime.smoke`: text and protocol smoke both passed.
- Formal benchmark artifacts copied under `artifacts/`:
  - `formal_auto.stdout.json`: 25/25, 5 families, used `shared_memory`.
  - `formal_shared_memory.stdout.json`: 25/25, 5 families, used `shared_memory`.
  - `formal_memfd_local.stdout.json`: 25/25, 5 families, used `memfd`, 25 memfd transfers, 247076 bytes.

## Current claim-upgrade status

Fully supported:

- Internal formal benchmark expansion to 25 cases / 5 families.
- State-pool mode reporting for shared memory and memfd on fresh formal runs.
- Typed Protobuf envelope path and protocol smoke execution.
- Ref separation between semantic state and execution artifacts.

Partially supported:

- Four-role architecture.
- Semantic state and hydration accounting.
- Bounded CodeAct / controlled execution.
- Memory replay and reuse, only when telemetry shows validated replay, exact replay, skipped steps, or reuse gain.

Documentation-only:

- Historical CodeAct LLM-generation diagnostics.
- Some older improvement reports after newer safe-claim docs superseded them.

Unsupported:

- Formal external superiority.
- End-to-end speed advantage.
- openEuler VM validation.
- Generic answer restoration.
- Realtime open-ended LLM code generation in the current formal benchmark.
