# Code Truth Review

This file records source-level observations, not presentation wording.

## Four agent roles

Observed implementation:

- `v2/runtime/role_path.py` defines `RolePathRunner` with separate methods for planner, retriever, executor, and summarizer.
- Each method calls `llm_client.complete(...)` with a role-specific `purpose`.
- `v2/benchmark/live_runner.py` exposes `--role-path-mode deterministic|api`.

Evidence:

- Planner: `RolePathRunner.plan_workflow`.
- Retriever: `RolePathRunner.choose_retrieval_candidate`.
- Executor: `RolePathRunner.validate_execution_choice`.
- Summarizer: `RolePathRunner.summarize`.
- Fresh formal artifacts in this audit use `role_path_mode=deterministic`.

What is real:

- API role-path code exists and is role-separated.
- Deterministic formal mode is runnable and produces telemetry.

What is simulated / deterministic / harness:

- Fresh 25/25 formal evidence here is deterministic harness evidence.
- It is not proof that API mode achieved the same quality or latency.

Main risks:

- Docs can easily blur "four role architecture exists" into "fresh formal API four-role proof exists."

Recommended fixes:

- Run formal compare/API mode with explicit `STATEBUS_LLM_API_KEY` and archive JSON before upgrading role claims.

## CodeAct

Observed implementation:

- `v2/runtime/codeact.py` builds a bounded plan and executes a generated `run_executor.py` script in a task workspace.
- `v2/runtime/codeact_sandbox.py` supports `bwrap`, `resource`, and `none`, with `auto` fallback.
- Runtime telemetry records `codeact_plan_stage_count`, `codeact_plan_action_count`, and sandbox backend counts.

Evidence:

- CodeAct plan classes and execution record are real.
- `CodeActSandboxRunner` tries `bwrap` first when available, otherwise resource limits or `none`.
- `docs/reports/v2_experiment_summary_20260703.md` now marks older LLM generation numbers as historical diagnostic evidence only.

What is real:

- Bounded CodeAct / controlled execution path.
- Artifact write and audit sidecar support.
- Sandbox telemetry.

What is simulated / deterministic / harness:

- Current formal benchmark does not prove realtime open-ended LLM-generated Python.
- The plan is bounded by current runner contracts.

Main risks:

- Historical "LLM generated 5/5" diagnostics can be overclaimed as current formal proof.

Recommended fixes:

- Add an explicit formal CodeAct API benchmark stage if realtime LLM code generation is desired as a claim.

## Structured control plane

Observed implementation:

- `protocol/statebus.proto` defines typed messages and `WireEnvelope`.
- `protocol/messages.py` serializes known messages to protobuf envelopes using `SerializeToString()`.
- `parse_protocol_bytes()` parses `WireEnvelope` first and falls back to JSON frames for older/unknown frames.

Evidence:

- `python3 -m runtime.smoke` passed both text and protocol modes in the container-root path.

What is real:

- UDS + typed Protobuf envelope is a real control-plane path.
- Protocol smoke runs.

What is simulated / deterministic / harness:

- Some protobuf message fields carry JSON strings such as `params_json`, `payload_json`, and `metadata_json`.
- JSON fallback remains for compatibility.

Main risks:

- "typed Protobuf" should mean typed envelope and typed top-level contract, not pure protobuf payload for every nested object.

Recommended fixes:

- Document remaining JSON-in-protobuf fields as compatibility fields, or migrate high-value nested payloads to typed messages.

## SemanticStateRef / non-text state

Observed implementation:

- `v2/refs/models.py` defines separate `SemanticStateRef` and `ExecutionArtifactRef` classes.
- `RuntimeDriver` imports both and emits semantic-state telemetry and execution artifact refs separately.
- `HydrationAccountingAudit` records raw evidence bytes, prompt-visible bytes, and role hydration bytes.

Evidence:

- Fresh formal artifacts show `semantic_state_transfer_count=25` for all formal runs.
- Memfd formal local artifact shows `state_pool_mode_used=memfd`.

What is real:

- Ref separation is real.
- Semantic state transfer and hydration accounting are real telemetry surfaces.

What is simulated / deterministic / harness:

- Current formal quality proof is deterministic; it does not prove arbitrary non-text reasoning under API mode.

Main risks:

- Claims may imply raw evidence never reaches prompt. The correct claim is measured pruning/hydration behavior per telemetry.

Recommended fixes:

- Add regression tests that assert prompt-visible bytes stay below raw evidence bytes for representative non-text tasks.

## Statepool: shared_memory / mmap / memfd

Observed implementation:

- `v2/state/store.py` implements `LayeredStateStore` with shared memory, memfd, mmap file, and inline materialization.
- `backend_name` now uses last/past actual publish counts.
- `publish()` falls back from shared memory or memfd `OSError` through policy fallback.

Evidence:

- `formal_auto.stdout.json`: requested `auto`, used `shared_memory`, 25 shared-memory publishes.
- `formal_shared_memory.stdout.json`: requested `shared_memory`, used `shared_memory`, 25 shared-memory publishes.
- `formal_memfd_local.stdout.json`: requested `memfd`, used `memfd`, 25 memfd transfers/publishes, 247076 bytes.

What is real:

- Backend reporting is now evidence-backed on fresh formal runs.
- Memfd path is real in the running container.

What is simulated / deterministic / harness:

- Memfd unavailable fallback remains mostly failure-path/unit evidence.

Main risks:

- Do not claim real no-memfd host fallback validation until run in such an environment or via an explicit container capability block.

Recommended fixes:

- Add a dedicated no-memfd validation environment or subprocess capability mask stage.

## Memory / replay / reuse

Observed implementation:

- Replay metrics distinguish validated replay and exact replay in `v2/runtime/driver.py`.
- This audit corrected `answer_restoration_replay_count` to stay `0.0` unless a real answer-restoration mechanism is implemented.
- `v2/benchmark/continuous_runner.py` no longer backfills answer restoration from exact replay.

Evidence:

- `tests/v2/test_continuous_runner.py` now asserts exact replay and answer restoration are separate.
- Post-fix `tests/v2/test_continuous_runner.py`: 11 passed.

What is real:

- Exact replay and validated replay are implemented and measured.
- Skipped-step/reuse claims are valid only when the corresponding telemetry is non-zero.

What is simulated / deterministic / harness:

- Generic answer restoration is not implemented.

Main risks:

- Older docs may still use "answer restoration" loosely. Current safe wording must avoid it.

Recommended fixes:

- Search and downgrade any remaining generic answer-restoration language before final presentation.

## Formal task families

Observed implementation:

- `v2/benchmark/task_registry.py` registers 5 formal families with expected counts 8, 5, 5, 4, and 3.
- `load_registered_formal_samples()` loads JSON samples and raises if counts do not match.
- `live_runner` uses registered formal samples by default for non-compare formal suites.

Evidence:

- Fresh formal artifacts show `family_count=5`, `L3_case_count=25`, `L3_quality_pass_count=25`.
- Source assets exist under `v2/benchmark/samples/formal_financial_family` and `tasks/formal/*/samples`.

What is real:

- 25-case / 5-family formal internal benchmark is real.
- Families cover single metric, multi-period trend, cross-table join, conditional aggregation, and anomaly detection.

What is simulated / deterministic / harness:

- `tasks/formal/*/validator.py` files are simple helpers and are not the primary runner contract.
- Main gate uses generic `expected_facts` in `v2/runtime/smoke.py`.

Main risks:

- Calling the family validators "real validators" overstates their integration.

Recommended fixes:

- Either integrate family-specific validators into the runner or remove/rename them as helper examples.

## External baseline / formal superiority

Observed implementation:

- `v2/benchmark/external_text_baseline.py` implements a pure-text four-role external baseline.
- `v2/benchmark/comparator_runner.py` computes fairness and superiority gates.
- `scripts/run_v2_full_container_audit_suite.sh` runs formal primary at `--benchmark-tier formal`, but compare primary at `--benchmark-tier dev`.

Evidence:

- `docs/improvement/19_claim_upgrade_completion_report_20260706.md` says `STATEBUS_LLM_API_KEY` was unset and formal external superiority was not upgraded.
- This audit did not run formal API compare.

What is real:

- External compare machinery exists.
- Dev/fixed-answer fairness evidence exists historically.

What is simulated / deterministic / harness:

- Formal external superiority is not proven in this audit.

Main risks:

- Comparator code having a formal gate does not mean formal superiority evidence exists.

Recommended fixes:

- Run and archive `--suite compare --benchmark-tier formal --role-path-mode api --embedding-mode local` with a real API key before any formal external superiority claim.
