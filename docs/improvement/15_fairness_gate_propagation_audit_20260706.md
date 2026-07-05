# StateBus v2 External Fairness Gate Propagation Audit

- Date: 2026-07-06
- Branch: `feat/statebus-v2-container-runtime`
- Base commit inspected: `cadc2d1`
- Container: `statebus-dev-qcrs`
- Activation: `/usr/local/bin/activate_statebus_container.sh`
- Project root in container: `/workspace/statebus/project`
- Scope: second-pass follow-up on external pure-text comparator fairness-gate propagation

## Summary

This pass found and fixed a real comparator audit gap: `run_external_text_case()` evaluated a per-case `fairness_gate`, but `run_external_text_family()` did not aggregate that gate into the family report. As a result, `comparator_runner` could only check coarse contamination and role-count signals; visible-candidate and metadata-leakage failures could be dropped before `pass_hard_gate`.

The fix is fail-closed:

1. External family reports now expose per-case fairness gate audits and aggregate pass/fail counts.
2. Comparator hard-gate logic now requires full external fairness-gate coverage and zero failed external fairness cases.
3. Compare diagnostics now surfaces `external_per_case_fairness_gate` as a named gate.
4. The external planner prompt and deterministic parser were made consistent so the default external baseline satisfies the visible-candidate contract instead of failing due to prompt formatting.

## Current Code Reality Map

Evidence Tier: strong for code paths inspected and covered by current tests; medium for paths primarily supported by prior full-audit artifacts; weak for capability-only paths not benchmark-active in this pass.

| Area | Current reality | Evidence tier | Boundary |
| --- | --- | --- | --- |
| Compiler / canonical task spec | Benchmark strict mode consumes precompiled `CanonicalTaskSpec`; this is a typed task-contract path, not open-ended task understanding. | strong | Strong claims should be scoped to benchmark families with canonical specs. |
| Four-role path | Planner, Retriever, Executor, Summarizer run as sequential roles through `RolePathRunner` and benchmark drivers. | strong | Not evidence of distributed or concurrent agent execution. |
| Structured vs text handoff | Structured prompts/control reduce visible payload in some lanes; formal token savings remain materially entangled with retrieval pruning. | strong | Do not attribute all prompt savings to structured carrier alone. |
| Control plane / UDS | Loopback UDS framing and typed control objects are real; subprocess transport exists and is covered separately. | medium | Default formal/compare path is not a multi-process transport benchmark. |
| Non-text state | Semantic state transfer and `shared_memory` state publish are benchmark-active in prior full-audit evidence. | medium | `memfd + SCM_RIGHTS` and persistent `mmap` are capability/test evidence here. |
| Retrieval | Formal financial family is table-structured and precision-oriented; continuous families add semantic and replay stress. | strong | Formal breadth remains narrow. |
| Replay / memory | Exact replay and validated downgraded reuse exist in prior full collection evidence. | medium | `validated_replay` should not be described as generic answer restoration. |
| CodeAct | Code execution, AST policy, sandbox path, and deterministic helper path exist; live benchmark CodeAct is not primarily LLM codegen. | medium | LLM code generation remains demo/specific-test evidence, not default formal path evidence. |
| External baseline | Four-role pure-text baseline is real and now carries per-case fairness-gate evidence into comparator hard gates. | strong | Compare suite remains dev fixed-answer evidence unless run under formal tier with appropriate family. |

## Mode Truth Table

Current preflight was run in the container for all four role/embedding combinations.

| role_path_mode | embedding_mode | Current preflight | Evidence tier | Use in this pass |
| --- | --- | ---: | --- | --- |
| `api` | `local` | pass | strong | Primary live compare and JSON inspection. |
| `api` | `deterministic` | pass | medium | Availability check only. |
| `deterministic` | `local` | pass | medium | Availability check and deterministic fallback confidence. |
| `deterministic` | `deterministic` | pass | weak | Lowest-tier fallback only. |

Preflight facts:

- API configuration is ready in the container.
- Local embedding model exists at `/statebus/models/Qwen3-Embedding-0.6B`.
- CUDA is available for `cuda:0`.

## Issue Status Table

| Issue | Current status | Evidence tier | Notes |
| --- | --- | --- | --- |
| External per-case fairness gate not propagated | resolved in this pass | strong | Family reports now expose aggregate and per-case fairness gate data; comparator hard gate consumes it. |
| Deterministic external planner failed visible-candidate gate due to prompt layout | resolved in this pass | strong | Prompt and parser now agree on inline `Visible route/tool candidates:`. |
| External revenue fallback into gold answer | resolved before this pass | strong | Current tests assert empty revenue remains a failed extraction rather than gold replacement. |
| `continuous-replay --family` ignored alias | resolved before this pass | medium | Covered by prior follow-up tests and docs. |
| API + local replay full collection evidence | resolved before this pass | strong | `14_full_validation_rollup_20260706.md` records full collection pass after rerun. |
| Formal family breadth | unresolved design limitation | strong | Formal remains a precision anchor, not broad reasoning coverage. |
| Structured-control-only attribution | unresolved claim-boundary issue | strong | Prompt savings should be attributed to typed control plus pruning/hydration, not structured carrier alone. |
| Validated replay naming | unresolved narrative risk | medium | Runtime behavior is safer to describe as validated downgraded reuse / strategy-backed reuse. |
| Subprocess transport, memfd, persistent mmap benchmark activation | partially unresolved | weak/medium | Capability/tests exist; benchmark-mainline evidence still limited. |

## Findings

### P0

No current P0 correctness bug was found in the changed comparator path after the fix and verification.

Evidence Tier: strong.

Rationale: targeted tests, full `tests/v2`, full repo pytest, runtime smoke, and live `api + local` compare all passed after the fairness propagation fix.

### P1

1. External comparator fairness previously masked per-case failures.
   - Evidence Tier: strong.
   - Status: fixed.
   - Impact: comparator hard gate now fails closed when visible-candidate, metadata leakage, typed-state, or LLM-only decision checks fail at case level.
2. Formal benchmark breadth remains narrow.
   - Evidence Tier: strong.
   - Status: open.
   - Impact: formal financial suite is useful as precision evidence, but not enough for a broad multi-agent reasoning claim.
3. End-to-end speed superiority is not proven by current live compare.
   - Evidence Tier: strong.
   - Status: open claim boundary.
   - Impact: live `api + local` compare supports lower token/prompt/control exposure but shows positive `task_ms_delta`.

### P2

1. Benchmark-mainline evidence for subprocess transport and memfd remains limited.
   - Evidence Tier: weak/medium.
   - Status: open.
   - Impact: keep as capability/test evidence unless a benchmark lane is added.
2. CodeAct LLM code-generation claim remains narrow.
   - Evidence Tier: medium.
   - Status: open.
   - Impact: benchmark path can claim audited code execution and sandboxing, but not default live LLM codegen.

### P3

1. Stronger innovation framing is available without overstating results.
   - Evidence Tier: medium.
   - Status: documentation opportunity.
   - Suggested framing: typed task contracts, semantic state carriers, and replay-admissibility gates are the real innovations.

## Benchmark And Fairness Audit

Evidence Tier: strong for the external compare path changed in this pass.

The prior failure mode was concrete: per-case `fairness_gate` existed only in leaf reports. The family report and comparator manifest could therefore report a hard gate pass even if a role violated visible-candidate or metadata-leakage checks. This is now fixed by:

- preserving `audit_summary.external_fairness_gate` on every external case;
- adding aggregate external fairness metrics to `aggregated_metrics` and `telemetry_summary`;
- requiring `external_fairness_gate_coverage` and `no_external_fairness_gate_failures` in comparator `pass_hard_gate`;
- adding diagnostics gate `external_per_case_fairness_gate`.

Live `api + local` compare result:

- `fixed_answer_external_comparison_valid = true`
- `api_comparison_valid = 1.0`
- `fairness_manifest.pass_hard_gate = true`
- `external_fairness_gate_coverage = true`
- `no_external_fairness_gate_failures = true`
- `external_fairness_gate_failed_case_count = 0`

Claim boundary:

- Supported: StateBus reduced `llm_total_tokens`, `prompt_bytes`, and `control_bytes` in this dev compare.
- Not supported: end-to-end speed superiority in this compare, because `api_debug_task_ms_delta = +10210.589388`.

## Replay And Memory Audit

Evidence Tier: medium for this pass, strong when combined with `14_full_validation_rollup_20260706.md`.

This pass did not modify replay or memory code. Current claim boundaries remain:

- Exact replay is answer restoration under stricter matching.
- Validated replay is better described as validated downgraded reuse / strategy-backed reuse, not generic safe answer replay.
- Strongest replay collection evidence remains the prior full-audit `api + local` collection pass.
- Memory/replay claims should cite `skipped_step_count`, replay class distribution, and quality-floor preservation, not only memory-hit counts.

## CodeAct Audit

Evidence Tier: medium.

This pass did not modify CodeAct. Current boundaries remain:

- Safe to claim: CodeAct execution artifacts, AST policy checks, sandbox execution path, and helper/cache behavior are implemented and tested.
- Unsafe to overclaim: default formal benchmark path is not primarily live LLM code generation.
- Stronger future evidence would be a benchmark lane that explicitly separates deterministic helper execution from live LLM-generated code execution.

## Retrieval, State, And Transport Audit

Evidence Tier: medium for this pass; stronger for prior full-audit artifacts.

Retrieval:

- Formal financial tasks still lean on structured table retrieval.
- Continuous families provide broader replay and semantic evidence.
- External baseline receives visible candidates and public evidence under a fairness contract; after this pass, that contract is now auditable at comparator level.

State:

- Semantic state transfer is benchmark-active in prior reports.
- `shared_memory` is the strongest currently evidenced semantic-state backend.
- `mmap` and `memfd` should remain capability/test-level unless a benchmark lane directly uses them.

Transport:

- UDS loopback is real and default-visible.
- `SubprocessExecutorTransport` exists but is not the primary compare/formal benchmark path in this pass.
- Socket-path length was handled in prior full-audit tooling; this pass used short `/tmp/cfg.sock` for live compare.

## Innovation Audit

Evidence Tier: medium.

The best competition narrative is not "everything is universally faster." The stronger and more defensible innovation claims are:

- typed task contracts and role-visible candidate constraints make comparator fairness auditable;
- semantic state carriers make non-text state transfer observable and measurable;
- replay gates distinguish exact replay from validated downgraded reuse;
- compare diagnostics now make fairness failures explainable instead of silently collapsing into generic invalidity.

Claims to avoid:

- broad formal superiority from dev fixed-answer compare;
- end-to-end speed win from the current live compare;
- hidden-state or KV-transfer implementation;
- benchmark-mainline multi-process transport superiority.

## Code Changes

- `v2/benchmark/external_text_baseline.py`
  - Added `external_fairness_gate_contract` metadata.
  - Added per-case metrics:
    - `external_fairness_gate_pass`
    - `external_fairness_gate_failed`
    - `external_fairness_gate_failed_check_count`
    - `external_fairness_failed_<check_name>`
  - Added aggregate metrics:
    - `external_fairness_gate_pass_count`
    - `external_fairness_gate_failed_case_count`
    - `external_fairness_gate_failed_check_count`
    - `external_fairness_gate_reported_case_count`
  - Added per-case `audit_summary.external_fairness_gate`.
  - Fixed planner prompt layout so `Visible route/tool candidates:` is parseable by deterministic mode.
- `v2/benchmark/comparator_runner.py`
  - Hard gate now requires:
    - `external_fairness_gate_coverage == true`
    - `no_external_fairness_gate_failures == true`
  - Fairness manifest now includes the external gate counts and failed-check names.
- `runtime/llm.py`
  - `parse_text_route_tool_planner_prompt()` now ends the task-query block at the visible-candidate label prefix, so it supports inline candidate values.
- `scripts/v2_diagnostics/compare_diagnostics.py`
  - Added diagnostics gate `external_per_case_fairness_gate`.
- Tests:
  - Added regression coverage for family aggregation, comparator fail-closed behavior, diagnostics visibility, and default external-lane fairness pass.

## Evidence

All verification below was run inside `statebus-dev-qcrs` with:

```bash
source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project
```

### Targeted Tests

```bash
/usr/bin/python3 -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py tests/v2/test_compare_diagnostics.py
```

Result:

- `38 passed in 21.82s`

### Full v2 Tests

```bash
/usr/bin/python3 -m pytest -q tests/v2
```

Result:

- `212 passed, 100 warnings in 388.02s`

### Strong Mode Preflight

```bash
/usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode api --embedding-mode local
```

Result:

- `ok = true`
- API configuration ready.
- Embedding model present at `/statebus/models/Qwen3-Embedding-0.6B`.
- CUDA available for `cuda:0`.

### Live Compare: `api + local`

```bash
/usr/bin/python3 -m v2.benchmark.live_runner \
  --suite compare \
  --benchmark-tier dev \
  --statebus-mode cold-start \
  --role-path-mode api \
  --embedding-mode local \
  --suite-id codex-fairness-gate-20260706 \
  --workspace-root /statebus/work/codex-fairness-gate-20260706/workspaces \
  --runtime-root /statebus/runs/codex-fairness-gate-20260706/runtime \
  --socket-path /tmp/cfg.sock
```

Primary reports:

- `/home/qcrs/statebus/runs/codex-fairness-gate-20260706/runtime/benchmark_reports/codex-fairness-gate-20260706-cold-start-compare.json`
- `/home/qcrs/statebus/runs/codex-fairness-gate-20260706/runtime/benchmark_reports/codex-fairness-gate-20260706-cold-start-compare-api.json`

Inspected JSON facts:

- `fixed_answer_external_comparison_valid = true`
- `api_comparison_valid = 1.0`
- `fairness_manifest.pass_hard_gate = true`
- `external_fairness_gate_coverage = true`
- `no_external_fairness_gate_failures = true`
- `external_fairness_gate_pass_count = 3`
- `external_fairness_gate_failed_case_count = 0`
- `external_fairness_gate_failed_check_count = 0`
- all external case audits have `failed_checks = []`

Efficiency/debug facts from the same report:

- `api_debug_llm_total_tokens_delta = -890`
- `api_debug_prompt_bytes_delta = -4872`
- `api_debug_control_bytes_delta = -303`
- `api_debug_task_ms_delta = +10210.589388`
- Interpretation: this supports lower token/prompt/control exposure, not an end-to-end speed win.

### Runtime Smoke

```bash
/usr/bin/python3 -m runtime.smoke
```

Result:

- `statebus smoke ok: mode=text ...`
- `statebus smoke ok: mode=protocol ...`
- `statebus comparator artifact ok: external_claim_surface=formal_ready api_repeat1_ready=True`

### Full Repo Tests

```bash
/usr/bin/python3 -m pytest -q
```

Result:

- `507 passed, 101 warnings in 951.49s`

Warnings are existing generated-Protobuf and LangGraph deprecation warnings; this pass did not introduce new warning classes during inspection.

## Issue Status

Resolved:

- External per-case fairness gate is now preserved at family-report level.
- Comparator hard gate now consumes the external per-case fairness aggregate.
- Diagnostics can identify the failed external per-case fairness gate by name.
- Default deterministic external planner no longer drops visible candidates due to prompt formatting.

Still bounded:

- The external compare suite remains dev fixed-answer evidence, not a formal superiority proof.
- The live `api + local` compare still shows StateBus slower end-to-end in this path; do not claim speed superiority from this report.
- Formal benchmark breadth and replay language caveats from `14_full_validation_rollup_20260706.md` remain unchanged.

## Comparison With Existing Improvement Docs

Evidence Tier: strong for document/code comparison performed in this pass.

| Prior document | Update from this pass |
| --- | --- |
| `11_competition_readiness_audit.md` | Historical P0-A revenue fallback and P0-C table-row concerns remain superseded. This pass adds a new fairness propagation issue not listed there. |
| `12_independent_codex_full_audit.md` | Its claim-boundary warnings remain valid: formal breadth is narrow, CodeAct LLM generation is not default formal path, and structured-control attribution must be separated from pruning. |
| `13_review_followup_and_full_test_script.md` | Its script and replay follow-up remain current. This pass adds comparator-level fairness propagation coverage. |
| `14_full_validation_rollup_20260706.md` | Full-audit green status remains the strongest broad evidence. This pass adds a narrower current-state `api + local` compare rerun after the fairness fix. |

## Action Plan

Evidence Tier: medium.

1. Add a formal or benchmark-balanced lane for subprocess transport / memfd if those systems claims are important.
2. Expand formal task breadth beyond single-metric table retrieval if broad reasoning claims are needed.
3. Rename or externally describe `validated_replay` as validated downgraded reuse / strategy-backed reuse in public-facing materials.
4. Keep external fairness gate fields in future report schemas; do not regress to contamination-only hard gates.
5. If speed claims are needed, use serialized benchmark reruns and isolate system overhead from LLM wall time.

## Landed Artifacts

Evidence Tier: strong for files created in this pass.

Artifact directory:

- `docs/improvement/artifacts/15_fairness_gate_propagation/`

Files:

- `worklog.md`
- `command_log.md`
- `evidence_log.md`
- `issue_ledger.md`
- `final_summary.md`

## Appendix

### Key Report Paths

- `/home/qcrs/statebus/runs/codex-fairness-gate-20260706/runtime/benchmark_reports/codex-fairness-gate-20260706-cold-start-compare.json`
- `/home/qcrs/statebus/runs/codex-fairness-gate-20260706/runtime/benchmark_reports/codex-fairness-gate-20260706-cold-start-compare-api.json`

### Key JSON Fields

Mode report:

- `.fairness_manifest.pass_hard_gate = true`
- `.fairness_manifest.external_fairness_gate_coverage = true`
- `.fairness_manifest.no_external_fairness_gate_failures = true`
- `.fairness_manifest.external_fairness_gate_failed_case_count = 0`
- `.external_report.aggregated_metrics.external_fairness_gate_pass_count = 3`
- `.external_report.aggregated_metrics.external_fairness_gate_failed_case_count = 0`
- `.external_report.cases[].audit_summary.external_fairness_gate.failed_checks = []`

Suite report:

- `.metadata.fixed_answer_external_comparison_valid = true`
- `.comparison_summary.api_comparison_valid = 1.0`
- `.comparison_summary.api_debug_llm_total_tokens_delta = -890`
- `.comparison_summary.api_debug_prompt_bytes_delta = -4872`
- `.comparison_summary.api_debug_control_bytes_delta = -303`
- `.comparison_summary.api_debug_task_ms_delta = +10210.589388`

### Git Commits

- `a6e951e` - `Propagate external fairness gate failures`
- Documentation/audit commit: recorded in final response after commit creation.
