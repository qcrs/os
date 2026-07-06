# Changes Applied

## V2-AUDIT-002: answer restoration metric overclaim

Changed:

- `v2/runtime/driver.py`
- `v2/benchmark/continuous_runner.py`
- `tests/v2/test_continuous_runner.py`

What changed:

- Runtime exact replay still increments `exact_replay_count`.
- Runtime no longer increments `answer_restoration_replay_count`.
- Continuous report code no longer synthesizes missing answer-restoration metrics from exact replay.
- Tests now require `answer_restoration_replay_count == 0.0` in family, case, and collection summaries.

Why:

- There is no implemented generic answer-restoration feature. Exact replay is a different replay class and must not create that claim surface.

Verification:

- First focused pytest run exposed one stale collection assertion.
- Post-fix `tests/v2/test_continuous_runner.py`: 11 passed.
- Post-fix focused command: 49 passed.

## V2-AUDIT-004: CodeAct historical diagnostic overclaim risk

Changed:

- `docs/reports/v2_experiment_summary_20260703.md`

What changed:

- Added warnings that the CodeAct section is a 2026-07-04 historical diagnostic.
- Changed the summary row from strong "CodeAct LLM generation stability" to a historical diagnostic record.

Why:

- Current formal benchmark evidence does not prove realtime LLM code generation.

Verification:

- Source review confirms current CodeAct path is bounded/controlled.
- Formal benchmark artifacts in this audit are deterministic/local, not API codegen proof.

## Audit evidence and docs

Added:

- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/00_executive_summary.md`
- `01_document_source_map.md`
- `02_git_history_and_change_review.md`
- `03_code_truth_review.md`
- `04_docs_artifacts_resolution_ledger.md`
- `05_merged_issue_ledger.md`
- `06_test_and_benchmark_evidence.md`
- `07_fix_plan.md`
- `08_changes_applied.md`
- `09_remaining_risks.md`
- `appendix_commands_and_artifacts.md`
- benchmark artifacts under `artifacts/`

Commit:

- These changes are intended for local commit message: `Audit StateBus v2 claim upgrade truth and follow-up fixes`.
- Final commit hash is recorded in the final assistant response.
