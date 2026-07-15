# Issues And Minimum Validation Plan

## High Priority

| Issue | Evidence | Impact | Minimum repair | Minimum validation |
| --- | --- | --- | --- | --- |
| P0 pytest status was historical fail | P0 `summary.json`, `status.tsv`, pytest log, later repair log | P0 cannot be called a complete all-pass matrix | Do not rewrite history; retain separate repair provenance | Targeted failing regression plus a separately labelled pytest-only rerun |
| Stage 18 runner post-processing failed | P1 `run.log` plus existing `repeat_summary.json`; preserved stderr is zero-byte | Run status is fail even though requests/artifact completed; exact historical exception is not independently recoverable | Keep original summary; retain the current validator repair only as post-run validation code | Re-run static verifier against immutable artifact; recover original stderr before asserting a specific NameError; rerun model requests only for a new experimental claim |
| Prefix cleanliness is limited | `clean_service_requested=False`, service window `continuous_service_between_pairs` | TTFT sample can have service/warm-order confounding | Explicitly report clean and continuous-service cohorts | Four AB/BA pairs per corpus in both cohorts with before/after counters |

## Medium Priority

| Issue | Evidence | Impact | Minimum repair | Minimum validation |
| --- | --- | --- | --- | --- |
| Backend matrix variants have different process boundaries | Stage 16 variant contracts | Loopback cannot substantiate cross-process IPC or timing superiority | Split functional and timing claims by variant | Matched repeated timing and lifecycle evidence; subprocess-only IPC assertion |
| Memory/replay labels can overstate savings | replay class/call metrics are distinct | Match/validated replay may not skip work | Require per-case output/artifact/call/token deltas | Exact/validated/assist cases with independent checks |
| Compare changes more than carrier | L0-L3/T2/external implementations | Carrier-only attribution is not identified | Freeze semantic selection/tool/scorer/prompt visibility | Serialized AB/BA compare with medians and tail percentiles |
| StateRef consumption is not separately recorded | `STATE_PUBLISHED`/`STATE_HYDRATED` exist but `STATE_CONSUME=0` | Hydration cannot prove a behavior change | Emit role/ref/field consumption plus decision provenance | StateRef on/off or consumed-field perturbation with route/tool/output checks |
| LogitState has no handoff provenance | transfer-count/entropy metrics lack bytes/ref/receiver/consume evidence | No neural-state transfer or benefit claim | Persist payload/ref/receiver/decision linkage and an enabled flag | Matched LogitState on/off with quality/cost outcomes |

## Required Tests Versus Experiments

- Unit or targeted regression: role-call accounting, Stage 18 verifier import, metric denominator aggregation, taint role allowlist, replay call/token consistency.
- Targeted stage: backend variant lifecycle, one UDS subprocess trace, genericity safe-plan/taint gate.
- Clean repeat: prefix counter and TTFT parity under both clean and continuous service policies.
- Full matrix: only after targeted checks retain their contracts; it is required for a new all-stages claim, not to relabel P0.

## Regression Risks

The complete issue fields are in `05_issue_ledger.csv`.

| Priority | Phenomenon | Severity | Regression risk | Minimum validation |
| --- | --- | --- | --- | --- |
| P0 | Historical P0 pytest failure | high | future call totals can again depend on optional rendered-request artifacts | target exact failures plus a clearly-labelled tests/v2-only rerun |
| P0 | Stage 18 post-processing failure lacks preserved exception text | high | post-processing errors can be misreported as model-execution failures | static verify immutable repeat_summary; recover original stderr before asserting a specific historical exception |
| P1 | Carrier comparison changes multiple variables | high | a comparator can regain implicit StateBus-only helper advantages | serialized AB/BA repeated matched-control comparison with medians and tail percentiles |
| P1 | Prefix service window is continuous | medium | warm cache and ordering can be mistaken for protocol benefit | four AB/BA pairs per corpus in both cohorts with before/after counters |
| P1 | StateRef downstream consumption is not separately recorded | medium | hydration can be mistaken for effective use when a downstream role ignores the hydrated state | per-role StateRef on/off or consumed-field perturbation with route/tool/output checks |
| P1 | LogitState participation is only a metric projection | medium | a telemetry field can be misread as a transferred, consumed neural state | matched LogitState on/off experiment with payload/ref/receiver traces and quality/cost outcomes |
| P2 | Precompiled CanonicalTaskSpec is a strong task prior | medium | case-specific metadata or fallback can leak into role prompts | holdout/paraphrase/taint suite with no task-contract oracle and role-aware review |
