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
