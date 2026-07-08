# StateBus Audit D: Route / Corpus Stress

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

## Audit Objective

验证 current advantage 是否过度依赖 release-regression family、route labels、tool taxonomy 和 local corpus shaping。

本 audit 只做 secondary stress，不修改 `contest_honest_headline_v1` frozen task contract，也不把结果反向覆盖 current formal headline。

## Single Variable

主变量是 corpus / evidence surface：

- 隐去或弱化 route-aligned wording；
- 将相邻路线 distractor 文档提前；
- 保持 text/protocol pair、expected route/tool contract、plan source、memory policy 不变。

固定项：

- `plan_source = yaml`；
- `runtime_reuse_contract = reuse_disabled`；
- text row 使用 `text_strict_pure_lane`；
- protocol row 使用 `state_packet_minimal`；
- 不引入 API run；
- 不改 frozen headline rows。

## Phase 0 Mini Plan

1. 新建 audit-only pack `route_corpus_stress_audit_v1`。
2. 只覆盖两个 small stress cases：
   - auth drift vs throttle；
   - billing worker backlog vs database distractor。
3. 每个 case 保持 text/protocol paired rows。
4. 跑 deterministic repeat=1，读取 row-level route/tool/case-contract result。
5. 如果 stress 触发 route-family failure，记录为 route/corpus sensitivity；如果只触发 tool ambiguity，记录为 tool taxonomy caveat。

## Changed Files

- `tasks/sample_tasks.py`
  - 新增 `route_corpus_stress_audit_v1` alias / pack type。
- `tasks/route_corpus_stress_audit_v1_benchmark.yaml`
  - 新增 audit-only paired stress pack。
- `tests/test_smoke.py`
  - 新增 pack metadata / pair matching test。
  - 更新 active alias count。
- `docs/analysis/statebus_audit_D_route_corpus_stress_20260618.md`
  - 本 audit 记录。

## Verification Commands

Targeted metadata / loader tests:

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q \
  tests/test_smoke.py::test_active_v3_pack_aliases_all_load_with_explicit_metadata \
  tests/test_smoke.py::test_route_corpus_stress_audit_pack_is_audit_only_and_pair_matched
```

Result: `2 passed`.

Initial deterministic CLI attempt:

```bash
source deploy/activate_statebus_host.sh && python -m eval.runner \
  --task-set route_corpus_stress_audit_v1 \
  --repeat 1 \
  --modes text,protocol \
  --out /home/qcrs/statebus/runs/route_corpus_stress_audit_v1_det_r1_20260618_231500
```

Result: failed before benchmark execution with CUDA OOM while loading the default sentence-transformer embedder.

Final deterministic artifact run:

```bash
source deploy/activate_statebus_host.sh && python -m eval.runner \
  --task-set route_corpus_stress_audit_v1 \
  --repeat 1 \
  --modes text,protocol \
  --embedding-mode deterministic \
  --llm-mode deterministic \
  --out /home/qcrs/statebus/runs/route_corpus_stress_audit_v1_det_r1_20260618_231800
```

Result: pass.

## Artifact Path

Final artifact:

- `/home/qcrs/statebus/runs/route_corpus_stress_audit_v1_det_r1_20260618_231800/`

Files:

- `benchmark_results.json`
- `benchmark_report.md`
- `benchmark_compare.csv`
- `benchmark_message_breakdown.csv`
- `benchmark_message_sizes.md`

Superseded failed empty output directory:

- `/home/qcrs/statebus/runs/route_corpus_stress_audit_v1_det_r1_20260618_231500/`

No API repeat was run. The stress question was deterministic object sensitivity, and the default-embedder CLI attempt failed on CUDA resource allocation before producing evidence.

## Row-Level Evidence

Manifest:

| field | value |
| --- | --- |
| task_pack_type | `route_corpus_stress_audit_v1` |
| task_count | 4 |
| modes | `text`, `protocol` |
| public_surface | `audit_only` |
| evidence_tier | `audit_only` |
| single_variable | `true` |
| variable_axes | `corpus_evidence_surface` |
| encoder | `deterministic-v1` |
| llm_backend | `deterministic` |

Case-contract summary:

| mode | route_exact_rate | tool_exact_rate | exact_match_rate | admissible_match_rate | wrong_family_rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| text | 1.00 | 0.50 | 0.50 | 1.00 | 0.00 |
| protocol | 1.00 | 0.50 | 0.50 | 1.00 | 0.00 |

Rows:

| mode | task | route | tool | correctness | retrieved docs |
| --- | --- | --- | --- | --- | --- |
| text | `stress-auth-ambiguous-text-001` | `auth_session_drift` | `tool.auth_session_repair` | exact_match | `rr-auth-incident`, `rr-auth-rate-limit-false` |
| protocol | `stress-auth-ambiguous-protocol-001` | `auth_session_drift` | `tool.auth_session_repair` | exact_match | `rr-auth-incident`, `rr-auth-rate-limit-false` |
| text | `stress-billing-ambiguous-text-001` | `worker_queue_starvation` | `tool.retry_storm_relief` | admissible_match | `rr-billing-incident`, `rr-billing-ambiguous` |
| protocol | `stress-billing-ambiguous-protocol-001` | `worker_queue_starvation` | `tool.retry_storm_relief` | admissible_match | `rr-billing-incident`, `rr-billing-ambiguous` |

Observed failure mode:

- No wrong-family route failure occurred.
- Billing stress selected `tool.retry_storm_relief` instead of primary `tool.worker_queue_triage` in both modes.
- Because `tool.retry_storm_relief` is in the acceptable tool set, this is not a wrong-family or inadmissible result; it is a tool-taxonomy ambiguity signal.

## What Can Now Be Claimed

Audit D supports the narrow secondary statement:

> On the covered route/corpus stress rows, route-family selection stayed stable across text and protocol despite route-label weakening and adjacent distractor evidence. The stress did expose a billing tool-selection ambiguity, where both modes selected an admissible alternate tool rather than the primary tool.

This is secondary object-sensitivity evidence only.

## What Still Cannot Be Claimed

- This does not prove broad corpus robustness.
- This does not show the frozen headline is route/corpus independent.
- This does not prove open-world retrieval quality.
- This does not validate a larger tool taxonomy.
- This does not promote stress rows into formal headline evidence.
- This does not require Docker, openEuler, nsjail, hidden-state, KV transfer, or API repeat.

## Promote / Repeat / Stop

Recommendation: stop Audit D for this batch.

Reason:

- The audit object is fair and single-variable.
- It produced interpretable row-level evidence.
- Further stress should be a larger route/tool taxonomy audit, not additional ad hoc reruns.

Handoff:

- Next audit should be Audit E: planner-open secondary.
