# Issue Ledger: 15 Fairness Gate Propagation

| ID | Issue | Status | Evidence tier | Resolution / boundary |
| --- | --- | --- | --- | --- |
| FG-001 | External per-case fairness gate was not propagated to family/comparator level. | resolved | strong | Added family aggregate metrics, per-case audit summaries, comparator hard-gate checks, and tests. |
| FG-002 | Deterministic external planner failed visible-candidate gate because prompt used next-line candidates while parser expected inline label values. | resolved | strong | Made external prompt inline and parser delimiter tolerant of inline label values. |
| FG-003 | Diagnostics could not name per-case external fairness failures. | resolved | strong | Added `external_per_case_fairness_gate` diagnostics gate and unit coverage. |
| FG-004 | Raw invisible route/tool choices could pass after assisted normalization. | resolved | strong | Raw planner/retriever/executor route/tool fields must now directly match a visible candidate. |
| FG-005 | Raw role JSON-only `oracle_answer` or `StateRef` leakage was not scanned. | resolved | strong | Raw role JSON is now included in metadata and typed-state leakage scans. |
| CLAIM-001 | Live compare supports end-to-end speed superiority. | not supported | strong | Current `api + local` compare has positive `task_ms_delta`; only token/prompt/control reductions are supported. |
| CLAIM-002 | External compare is formal superiority evidence. | not supported | strong | Current run is dev fixed-answer compare; keep formal claims separate. |
| SYS-001 | Subprocess transport / memfd are benchmark-mainline proof. | open | weak | Capability/tests exist, but this pass did not add a benchmark lane. |
| REPLAY-001 | Validated replay means generic safe answer restoration. | open wording risk | medium | Prefer validated downgraded reuse / strategy-backed reuse. |
