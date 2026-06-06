# StateBus Optimization Journal

## 2026-06-06 01: Host-side Phase 4 baseline
- Goal: make the host-side StateBus path runnable through `Phase 4`.
- Changes:
  - connected `protocol/messages`, `runtime/orchestrator`, `statepool/store`, and `memory/store`
  - enabled file-backed `mmap` `StateRef` flow plus SQLite + FAISS shared memory
  - kept repo-local sample tasks as the default benchmark input
- Verification:
  - `python -m pytest -q`
  - `python -m runtime.smoke`
- Result:
  - host-side runnable path exists and `Phase 0-4` work moved out of design-only status
- Risks / follow-up:
  - protocol accounting still used JSON frame size
  - benchmark scope was still skeleton-level
- Commit: pending retroactive baseline before journal creation

## 2026-06-06 02: LLM configuration decoupling
- Goal: let `Planner` and `Summarizer` switch OpenAI-compatible providers and models without Python edits.
- Changes:
  - added shared LLM runtime abstraction
  - split secret env from role/provider YAML config
  - enabled role-specific `planner` and `summarizer` model selection
- Verification:
  - config loading tests
  - deterministic benchmark manifest inspection
- Result:
  - DeepSeek / GPT-style API backends can be selected from repo-local config
- Risks / follow-up:
  - live long-run observability was still weak
- Commit: pending retroactive baseline before journal creation

## 2026-06-06 03: Text baseline naturalization
- Goal: stop using a plain structured-message dump as the text baseline.
- Changes:
  - changed planner and summarizer prompts to natural-language brief / handoff form
  - changed `text_frame()` to narrative control messages
- Verification:
  - `tests/test_llm_runtime.py`
  - `tests/test_smoke.py`
- Result:
  - text mode now measures a more realistic text-collaboration path
- Risks / follow-up:
  - communication-efficiency claims still depended on current protocol byte accounting
- Commit: pending retroactive baseline before journal creation

## 2026-06-06 04: Phase 4 reuse pruning and repeat-10 deterministic benchmark
- Goal: make shared memory reuse skip real work and validate stability over a continuous task chain.
- Changes:
  - memory hits now prune `retrieve` and `execute`
  - expanded default task set to two task groups with ten continuous tasks per run
  - added `memory_hit_rate`, `skipped_step_count`, `reuse_gain`, and expectation matching to reports
- Verification:
  - `python -m pytest -q`
  - deterministic `repeat=10` benchmark
- Result:
  - deterministic benchmark completed 10 runs with stable reuse behavior
- Risks / follow-up:
  - handshake/control setup still counted per task
  - live API `repeat=10` not yet formalized
- Commit: pending retroactive baseline before journal creation

## 2026-06-06 05: Communication-efficiency diagnosis
- Goal: explain why `protocol` control bytes were larger than `text` in the deterministic report.
- Changes:
  - ran message-type breakdown experiments against the current 10-task deterministic path
  - measured representative `MemoryCommit` and `StepResult` payload composition
- Verification:
  - message-type byte breakdown experiment
  - single-task field-size inspection for `MemoryCommit` and `StepResult`
- Result:
  - `MemoryCommit` and `StepResult` dominate protocol bloat
  - `MemoryCommit.evidence_state_refs` and `StepResult.output_state_refs` are the largest offenders
  - repeated task-level handshake also pollutes communication accounting
- Risks / follow-up:
  - protocol wire format must be compacted before communication-efficiency claims are defensible
  - setup vs steady-state bytes must be split in benchmark output
- Commit: pending next implementation round

## 2026-06-06 06: Commit anchor backfill
- Goal: resolve the earlier journal placeholders with concrete git anchors.
- Changes:
  - mapped the host-side initialization work to `ebb6be4`
  - mapped the Phase 4 reuse pruning plus deterministic repeat-10 baseline to `576decc`
- Verification:
  - `git log --oneline --decorate -n 6`
  - `git show --stat --summary --format=fuller ebb6be4`
  - `git show --stat --summary --format=fuller 576decc`
- Result:
  - journal history now has explicit commit anchors for the first two recorded implementation waves
- Risks / follow-up:
  - the current protobuf/session/shared-memory hardening work still needs its own commit anchor
- Commit: pending current local baseline commit

## 2026-06-06 07: Protobuf wire/session/shared-memory hardening groundwork
- Goal: move the benchmark/runtime stack from JSON-sized protocol accounting toward compact protobuf wire accounting and run-scoped setup accounting.
- Changes:
  - added `protocol/statebus.proto` and checked-in `protocol/statebus_pb2.py`
  - switched protocol byte sizing to protobuf envelopes with compact `StateRefLite`
  - made handshake/capability registration run-scoped and split setup vs steady-state metrics
  - added message-breakdown artifacts, run-level partial flush, and progress reporting
  - introduced `CapabilityTable` and `SchemaInterceptor`
  - upgraded `StatePool` to support `MMAP_FILE` plus `PY_SHARED_MEMORY` backends with embedding-specific selection
  - fixed protobuf runtime compatibility by replacing legacy generated code with a modern builder-based `statebus_pb2.py`
  - fixed partial-flush reporting so single-mode intermediate results no longer break compare/report generation
- Verification:
  - `python -m pytest -q`
  - `python -m runtime.smoke`
- Result:
  - the repo now has a runnable protobuf-based control-plane accounting path and a stable test baseline for the next live API round
- Risks / follow-up:
  - need explicit wire-size regression tests for `MemoryCommit` and `StepResult`
  - still need formal live API `repeat=1` preflight and `repeat=10` artifact capture under `$STATEBUS_RUNS_DIR`
- Commit: pending current local baseline commit

## 2026-06-06 08: Commit anchor for protobuf/session/shared-memory groundwork
- Goal: resolve the placeholder for the protobuf/session/shared-memory hardening wave.
- Changes:
  - recorded the commit anchor for the groundwork implementation as `9ca43f6`
- Verification:
  - `git log --oneline --decorate -n 3`
- Result:
  - the protocol/session/shared-memory groundwork now has a stable rollback and discussion anchor
- Risks / follow-up:
  - communication-efficiency still needed one more accounting correction pass before live API formalization
- Commit: pending current accounting-fix commit

## 2026-06-06 09: Communication-accounting correction pass
- Goal: make deterministic control-byte comparison match the intended experiment semantics instead of undercounting the text baseline.
- Changes:
  - enriched `text_frame()` for `MemoryQuery` and `MemoryCommit` so the text path carries the same core semantics the protobuf wire is replacing
  - trimmed protobuf wire metadata for `MemoryQuery` and `MemoryCommit` down to `reuse_signature`-level fields that actually participate in reuse decisions
  - updated the proto regeneration script to refuse legacy `protoc` and point users at `grpcio-tools`
  - added wire regression tests and a benchmark assertion that protocol steady-state control bytes stay below text
- Verification:
  - `python -m pytest -q`
  - `python -m eval.runner --out /tmp/statebus_proto_accounting_check_v2 --repeat 10 --llm-mode deterministic --quiet-progress`
- Result:
  - deterministic `repeat=10` now reports `protocol steady_state_control_bytes = 30133` vs `text = 34579`
  - `MemoryCommit` and `MemoryQuery` are no longer protocol-bloat offenders; both are now smaller on protobuf wire than on the text baseline
- Risks / follow-up:
  - still need live API `repeat=1` preflight and official `repeat=10` artifact capture
  - `grpcio-tools` is not installed in the host env yet, so proto regeneration remains a checked-in-source workflow unless the env is extended
- Commit: pending current accounting-fix commit

## 2026-06-06 10: Commit anchor for communication-accounting correction
- Goal: resolve the placeholder for the accounting-fix wave.
- Changes:
  - recorded the commit anchor for the accounting-fix implementation as `3dc4a38`
- Verification:
  - `git log --oneline --decorate -n 4`
- Result:
  - the deterministic control-byte flip is now tied to a concrete implementation commit
- Risks / follow-up:
  - live API still needed formal preflight and official `repeat=10`
- Commit: pending live-results record commit

## 2026-06-06 11: Live API preflight and official repeat-10 capture
- Goal: turn the deterministic benchmark improvements into formal DeepSeek-backed evidence with persistent run artifacts.
- Changes:
  - ran live API preflight at `/home/qcrs/statebus/runs/benchmark_20260606_234503`
  - ran official live `repeat=10` at `/home/qcrs/statebus/runs/benchmark_20260606_234731`
  - used the new partial-flush runner path so long runs produced observable intermediate results
- Verification:
  - `/home/qcrs/statebus/runs/benchmark_20260606_234503/benchmark_report.md`
  - `/home/qcrs/statebus/runs/benchmark_20260606_234731/benchmark_report.md`
  - `/home/qcrs/statebus/runs/benchmark_20260606_234731/benchmark_compare.csv`
  - `/home/qcrs/statebus/runs/benchmark_20260606_234731/benchmark_message_sizes.md`
- Result:
  - preflight completed with both modes, no failures, and already showed `protocol` below `text` on control bytes and total tokens
  - official live `repeat=10` completed with `failure_count=0` and `expectation_match_rate=1.00` for both modes
  - live mean metrics now read:
    - `text`: `control_bytes=30233.30`, `llm_total_tokens=10365.00`, `task_ms=42445.21`
    - `protocol`: `control_bytes=23892.40`, `llm_total_tokens=10237.50`, `task_ms=43965.53`
  - `protocol` now beats `text` on both control bytes and total token usage under live API conditions
- Risks / follow-up:
  - `protocol` still lags `text` slightly on end-to-end wall time in the current live `repeat=10` run, so latency advantage is not yet established
  - proto regeneration still depends on adding `grpcio-tools` if we want reproducible local codegen instead of checked-in generated output
- Commit: pending live-results record commit
