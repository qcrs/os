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

## 2026-06-07 12: Live latency fairness fix via alternating mode schedule
- Goal: resolve the remaining anomaly where `protocol` had lower bytes/tokens but worse live wall time.
- Changes:
  - diagnosed that the runner executed all `text` runs first and all `protocol` runs second, which biased live API latency by time-of-day/service-load drift
  - changed benchmark scheduling to `paired_round_robin_alternating`
  - added `mode_schedule` to the benchmark manifest/report and a regression test for alternating run order
- Verification:
  - `python -m pytest -q`
  - short live validation at `/home/qcrs/statebus/runs/benchmark_20260607_001002`
  - corrected official live `repeat=10` at `/home/qcrs/statebus/runs/benchmark_20260607_001355`
- Result:
  - the short live validation already flipped end-to-end time in favor of `protocol`
  - corrected official live `repeat=10` now reports:
    - `text`: `control_bytes=30173.20`, `llm_total_tokens=10356.60`, `task_ms=46881.31`
    - `protocol`: `control_bytes=23847.60`, `llm_total_tokens=10230.30`, `task_ms=46658.49`
  - after removing the blocked-by-mode ordering bias, `protocol` is now better than `text` on control bytes, total tokens, and mean end-to-end task time
- Risks / follow-up:
  - the latency win is currently modest, so later work should still target planner/summarizer prompt simplification if a larger gap is needed
  - `grpcio-tools` remains absent from the host env, so proto regeneration is still not self-contained
- Commit: pending latency-fix result commit

## 2026-06-07 13: Compact protocol LLM prompts and official repeat-10 validation
- Goal: deepen the protocol advantage by shrinking planner/summarizer LLM I/O instead of only shrinking wire accounting.
- Changes:
  - introduced compact protocol prompt tags `sb-plan-v1` and `sb-summary-v1`
  - switched protocol planner input to short-key structured packets and protocol planner output to compact `{r,x,s}` JSON
  - switched protocol summarizer input to short-key packets and protocol summarizer output to compact `{s,c,t,r}` JSON
  - kept text mode on natural-language briefs/handoffs so the baseline stayed text-centric
  - preserved backward compatibility by letting plan/summary parsers accept both legacy and compact JSON shapes
  - forced runner progress prints to flush immediately so live long runs are observable in real time
  - reran live API preflight and official `repeat=10` under the compact protocol prompt path
- Verification:
  - `python -m py_compile agents/sample_agents.py runtime/llm.py eval/runner.py tests/test_llm_runtime.py`
  - `python -m pytest -q`
  - live preflight: `/home/qcrs/statebus/project/runs/benchmark_20260607_compact_prompt_preflight`
  - live official `repeat=10`: `/home/qcrs/statebus/project/runs/benchmark_20260607_compact_prompt_repeat10`
- Result:
  - live preflight flipped the gap from modest to large:
    - `text`: `control_bytes=30399`, `llm_total_tokens=10385`, `task_ms=45605.99`
    - `protocol`: `control_bytes=21431`, `llm_total_tokens=6924`, `task_ms=34459.37`
  - official live `repeat=10` confirmed the gain without failures:
    - `text`: `control_bytes=30229.20`, `llm_total_tokens=10362.00`, `task_ms=44201.38`
    - `protocol`: `control_bytes=21467.80`, `llm_total_tokens=6931.10`, `task_ms=33621.55`
  - the compact protocol path now improves all three headline metrics at once:
    - control bytes lower by about `29%`
    - total tokens lower by about `33%`
    - end-to-end task time lower by about `24%`
  - live `repeat=10` completed with `failure_count=0` and `expectation_match_rate=1.00`
- Risks / follow-up:
  - protocol reuse currently hits more often than text in live runs because the more canonical summaries are easier to match; keep that distinction explicit in reporting
  - proto regeneration is still checked-in-source driven until `grpcio-tools` is added to the host env
- Commit: pending compact-prompt result commit
