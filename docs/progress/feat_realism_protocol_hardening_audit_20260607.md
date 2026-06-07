# `feat/realism-protocol-hardening` Audit

Date: `2026-06-07`

Scope: audit the current branch in two layers:

- committed branch baseline at `a05c710` (`baseline: contestized host-side prototype before realism hardening`)
- current uncommitted realism-hardening worktree changes on top of that baseline

## Summary

This branch is no longer a design-only repo branch. The committed baseline already contains a runnable host-side prototype with:

- `text` / `protocol` runnable paths
- `.proto + pb2` control-plane accounting
- `StateRef + mmap/shared_memory + SQLite + FAISS`
- tool-registry-based executor runtime plus subprocess fallback
- sample remote executor / `UDS` transport path

The current uncommitted realism-hardening worktree pushes the branch away from a contest-overfit replay demo and toward a more honest benchmark shape:

- task set widened from narrow replay/follow-up patterns to `12` tasks across `3` chains
- `Retriever` now uses repo-local corpus retrieval instead of mainly wrapping inline YAML evidence
- memory reuse is now `assist/reject`, not prune-and-skip
- current benchmark evidence shows `skipped_step_count = 0`

This is still a contestized host-side prototype. It is not yet a general multi-agent runtime.

## What The Committed Branch Baseline Already Completed

Relative to `main`, the committed branch baseline at `a05c710` already added:

- protocol/runtime hardening in `protocol/messages.py`, `runtime/orchestrator.py`, `runtime/remote_executor.py`, `runtime/uds_transport.py`
- executor runtime structure in `runtime/executor_runtime.py` and `runtime/tool_worker.py`
- explicit current-scope and strict-audit docs in `docs/constraints/current_feature_scope.md` and `docs/review_strict_audit_prompt.md`
- benchmark/test surface expansion in `eval/runner.py`, `tests/test_protocol_messages.py`, and `tests/test_smoke.py`

Accurate branch-baseline claim:

> The repo already has a runnable host-side contest prototype with structured protocol, state passing, shared memory, benchmark reporting, and an external `UDS` executor sample path.

Inaccurate branch-baseline claim:

> A general multi-agent runtime is complete.

## What The Current Worktree Changed

Current uncommitted realism-hardening changes are concentrated in:

- `tasks/sample_benchmark.yaml`
- `tasks/sample_tasks.py`
- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `eval/metrics.py`
- `eval/runner.py`
- `tests/test_smoke.py`
- `tests/test_llm_runtime.py`
- new files `tasks/local_corpus.py` and `tasks/sample_corpus.yaml`

Key behavior changes:

1. Task set realism
   - expanded to `12` tasks
   - uses `cache_chain`, `latency_chain`, `session_chain`
   - each chain includes anchor, assist, reject-control, and replay-control style cases
   - uses `expected_reuse_mode: none|assist` instead of only boolean reuse expectation

2. Retriever realism
   - retrieve step now uses `corpus_doc_ids`
   - local corpus retrieval happens through `tasks/local_corpus.py`
   - benchmark evidence is no longer mainly an inline YAML payload

3. Reuse semantics
   - memory hit no longer short-circuits the entire retrieve/execute step pair
   - fresh evidence is retrieved first
   - memory is accepted only as `assist` when route evidence stays aligned
   - mismatched memory is recorded as rejected reuse

4. Metrics and reports
   - benchmark metrics now track `memory_assist_task_count`, `memory_rejected_task_count`, `validated_reuse_task_count`
   - report section now shows `Memory Assist Decisions By Mode`
   - current deterministic results show `skipped_step_count = 0`

## Verified On This Working Tree

### 1. Targeted tests

Command:

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/test_smoke.py tests/test_llm_runtime.py tests/test_protocol_messages.py tests/test_memory_store.py
```

Result:

- `26 passed, 2 skipped`

Interpretation:

- the `2 skipped` items remain environment-conditioned `UDS` checks in the managed sandbox path
- they are not evidence of failure
- they also must not be counted as completed host validation on their own

### 2. Deterministic `mmap` benchmark

Artifact path:

- `runs/realism_hardening_det_r1`

Verified facts:

- `task_count = 12`
- `task_groups = 3`
- `expected_reuse_task_count = 6`
- `skipped_step_count = 0` in both modes
- reuse decisions are emitted as assist/reject rows
- `expectation_match_rate = 1.0`

Headline numbers:

- `text`: `control_bytes=95263`, `task_ms=26669.69`
- `protocol`: `control_bytes=85809`, `task_ms=23750.72`

### 3. Deterministic `shared_memory` benchmark

Artifact path:

- `runs/realism_hardening_shm_r1`

Verified facts:

- manifest shows `statepool_backend = PY_SHARED_MEMORY`
- manifest shows `embed_state_backend = PY_SHARED_MEMORY`
- full benchmark completed in both modes
- `skipped_step_count = 0`

### 4. Deterministic `repeat=10`

Artifact path:

- `runs/realism_hardening_det_r10`

Verified facts from `benchmark_results.json`:

- `text.run_count = 10`
- `protocol.run_count = 10`
- `text.failure_count = 0`
- `protocol.failure_count = 0`
- `text.expectation_match_rate = 1.0`
- `protocol.expectation_match_rate = 1.0`
- `text.skipped_step_count = 0`
- `protocol.skipped_step_count = 0`

Interpretation:

- current realism-hardening working tree is stable over `repeat=10`
- the new assist/reject semantics do not drift back into prune-and-skip behavior

### 5. Real host `UDS` validation

Artifact path:

- `runs/realism_hardening_uds_r1`

Managed-sandbox result:

- `executor transport 'uds' requires AF_UNIX socket support on the current host`

Real-host rerun result:

- rerun outside the managed sandbox completed successfully
- manifest shows `executor_transport = "uds"`
- `expectation_match_rate = 1.0`
- `skipped_step_count = 0`

Interpretation:

- the earlier `AF_UNIX` failure was a sandbox restriction, not a project failure
- `UDS` should now be counted as host-validated on this branch

### 6. Live API benchmark

Artifact path:

- `runs/realism_hardening_api_r1`

Managed-sandbox result:

- sandboxed run stalled under restricted networking and was not used for conclusions

Real-network rerun result:

- both `text` and `protocol` completed
- `text.failure_count = 0`
- `protocol.failure_count = 0`
- `text.llm_total_tokens = 14780`
- `protocol.llm_total_tokens = 11063`

Headline numbers:

- `text`: `control_bytes=61501`, `llm_total_tokens=14780`, `task_ms=62194.81`
- `protocol`: `control_bytes=51259`, `llm_total_tokens=11063`, `task_ms=56830.90`

Interpretation:

- this branch now has real API-backed Planner/Summarizer evidence on the current working tree
- under the current task set, `protocol` beats `text` on control bytes, total tokens, and end-to-end task time

## Completed And Defensible Claims

The following claims are now supported on this branch and working tree:

- runnable host-side contest prototype exists
- `text` / `protocol` benchmark paths both run
- `.proto + pb2` structured control plane exists
- `StateRef` passes non-text state through `mmap` and `shared_memory`
- current worktree uses conservative memory `assist/reject` semantics instead of step skipping
- current task set is broader than narrow replay-only benchmarking
- repo-local corpus retrieval exists
- real host `UDS` executor sample transport works
- API-backed Planner/Summarizer path has real benchmark evidence

## Not Yet Closed

These items have code or partial structure, but should still be described carefully:

- `Executor` is still closer to a playbook/tool selector than a general action executor
- remote executor request/response path still has a JSON fallback boundary and is not fully converged into `.proto`
- benchmark openness improved, but tasks are still repo-local synthetic incident corpora rather than open external workloads
- current non-text state is stronger than plain text, but still not hidden-state / KV-cache class transfer

## Do Not Claim

The following claims remain unsupported and should not be used:

- openEuler final reproducible delivery is complete
- production-grade secure sandboxing is complete
- general multi-agent runtime is complete
- hidden-state / KV-cache state transfer is implemented
- robust shared-memory reuse on truly open tasks is proven

## Recommended Next Step

The current highest-value next step is no longer basic host validation. That is now closed for:

- targeted tests
- deterministic `mmap`
- deterministic `shared_memory`
- deterministic `repeat=10`
- real host `UDS`
- real API `repeat=1`

The next honest improvement target is:

1. finish protocol-path convergence for remote executor request/response into the main `.proto` line
2. keep pushing the executor away from playbook selection toward parameterized tool execution
3. if benchmark realism still matters more than architecture cleanup, widen corpus/task openness further before claiming practical memory robustness
