# StateBus Audit B: Text Helper Ablation

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

## Audit Objective

验证 `text_whole_lane` 的 route/tool 恢复有多少依赖 StateBus runtime helper path，而不是只来自自然语言 handoff 本身。

本 audit 不回答 external pure-text baseline 是否强弱；它只回答 current internal text comparator 是否 runtime-assisted。

## Single Variable

主变量是 `text_whole_lane` route/tool recovery helper availability：

- helper enabled：保持现有 `text_whole_lane` 行为；
- helper disabled：保留同一自然语言 handoff，但禁用 runtime 从 text handoff 和 hidden retrieve payload 恢复 route/tool 的路径。

固定项：

- 不改 `contest_honest_headline_v1` frozen task contract；
- 不覆盖 frozen artifact；
- protocol control rows 仍使用 `state_packet_minimal`；
- 不引入 API run。

## Why This Does Not Mutate Frozen Headline

新增的是 audit-only field、audit-only task pack、targeted tests 和 audit report。默认 `audit_text_helper_mode` 为空，现有 `text_whole_lane` 行为不变。

新增 pack：

- `text_helper_ablation_audit_v1`
- `public_surface: audit_only`
- `evidence_tier: audit_only`
- `variable_axes: [text_route_tool_recovery_helper]`

## Changed Files

- `runtime/task_profile.py`
  - 新增 `audit_text_helper_mode` 和 `audit_text_helper_disabled`。
- `tasks/sample_tasks.py`
  - 将 `audit_text_helper_mode` 接入 `SampleTask`、`runtime_profile`、plan params、YAML loading 和 alias table。
- `agents/sample_agents.py`
  - validation path 在 helper-off text row 中不再从 `TOOL_ARTIFACT` text 或 hidden retrieve payload 恢复 route/tool。
  - LLM plan parser 保持与 `build_plan()` 相同的 audit param。
- `runtime/executor_runtime.py`
  - execution path 在 helper-off text row 中回落到 `generic_triage` / `tool.collect_more_evidence`，并记录 audit marker。
- `eval/runner.py`
  - runner rows 输出 `audit_text_helper_mode`。
  - 新增 `text_helper_ablation_audit_v1` report section。
- `tasks/text_helper_ablation_audit_v1_benchmark.yaml`
  - 新增 audit-only helper-on/helper-off/protocol-control pack。
- `tests/test_smoke.py`
  - 新增 helper-off executor / validation / pack contract tests。
  - 更新 active pack alias count。

## Verification Commands

Phase 1 baseline before Audit B edits:

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q
```

Result: `216 passed`.

```bash
source deploy/activate_statebus_host.sh && python -m runtime.smoke
```

Result: pass.

Targeted after Audit B edits:

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q \
  tests/test_smoke.py::test_text_whole_lane_executor_recovers_route_and_tool_from_headline_handoff \
  tests/test_smoke.py::test_text_whole_lane_executor_helper_disabled_does_not_recover_route_or_tool \
  tests/test_smoke.py::test_text_helper_ablation_audit_pack_is_audit_only_and_keeps_helper_flag_single_variable \
  tests/test_smoke.py::test_validate_route_can_recover_text_whole_lane_route_and_tool_without_decision_packet \
  tests/test_smoke.py::test_validate_route_helper_disabled_does_not_recover_text_whole_lane_tool
```

Result: `5 passed`.

Regression subset after full-suite failures were fixed:

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q \
  tests/test_llm_runtime.py::test_plan_parser_accepts_nested_deepseek_shape \
  tests/test_llm_runtime.py::test_plan_parser_accepts_numeric_step_ids_from_text_llm \
  tests/test_llm_runtime.py::test_deterministic_llm_parses_text_mode_prompts \
  tests/test_llm_runtime.py::test_deterministic_llm_uses_compact_protocol_shapes \
  tests/test_smoke.py::test_active_v3_pack_aliases_all_load_with_explicit_metadata
```

Result: `5 passed`.

Full post-change regression:

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q
```

Result: `219 passed`.

```bash
source deploy/activate_statebus_host.sh && python -m runtime.smoke
```

Result: pass; deterministic repeat=1 host sanity emitted `statebus smoke ok` for both text and protocol.

## Artifact Path

Final deterministic artifact:

- `/home/qcrs/statebus/runs/text_helper_ablation_audit_v1_det_r1_20260618_223000/`

Superseded intermediate artifacts:

- `/home/qcrs/statebus/runs/text_helper_ablation_audit_v1_det_r1_20260618_220000/`
- `/home/qcrs/statebus/runs/text_helper_ablation_audit_v1_det_r1_20260618_221500/`

No API repeat was run. The deterministic artifact directly answers the helper-dependence question; an API run would add cost/noise without changing the object boundary.

## Row-Level Evidence

From `benchmark_report.md`:

| helper_mode | validation_success_rate | recovered_route_tool_rate | execute_reached_rate | validation_block_rate |
| --- | ---: | ---: | ---: | ---: |
| disabled | 0.00 | 0.00 | 0.00 | 1.00 |
| enabled | 1.00 | 1.00 | 1.00 | 0.00 |

Text row details from `benchmark_results.json`:

| row | helper_mode | pre_validation_route/tool | validation | execute |
| --- | --- | --- | --- | --- |
| `rr-checkout-clean-text-helper-on-001` | enabled | `db_pool_saturation` / `tool.db_pool_triage` | success | `db_pool_saturation` / `tool.db_pool_triage` |
| `rr-checkout-clean-text-helper-off-001` | disabled | empty / empty | blocked: `validate route requires executor decision packet` | not reached |
| `rr-checkout-ambiguous-text-helper-on-001` | enabled | `db_pool_saturation` / `tool.db_pool_triage` | success | `db_pool_saturation` / `tool.db_pool_triage` |
| `rr-checkout-ambiguous-text-helper-off-001` | disabled | empty / empty | blocked: `validate route requires executor decision packet` | not reached |

Protocol compactness control from `benchmark_report.md`:

| metric | text | protocol | delta(protocol - text) |
| --- | ---: | ---: | ---: |
| steady_state_text_bytes | 40159.00 | 20207.00 | -19952.00 |
| steady_state_protocol_bytes | 39396.00 | 19088.00 | -20308.00 |
| handoff_textual_bytes | 10902.00 | 3712.00 | -7190.00 |
| handoff_nontext_bytes | 0.00 | 7271.00 | 7271.00 |

## What Can Now Be Claimed

Audit B supports the narrow secondary statement:

> Current `text_whole_lane` is a runtime-assisted internal comparator. On the covered helper-off rows, the same natural text handoff no longer recovers route/tool or reaches execution when StateBus recovery helpers and hidden route/tool payload reuse are disabled.

Protocol compactness still holds on this audit-only subset, but this subset must stay secondary and cannot replace the frozen headline artifact.

## What Still Cannot Be Claimed

- This does not prove an external pure-text baseline.
- This does not prove open-world agent benchmark superiority.
- This does not change the frozen `contest_honest_headline_v1` claim.
- This does not show text should be intentionally weakened in formal comparison.
- This does not require or validate API repeat behavior.

## Promote / Repeat / Stop

Recommendation: stop Audit B after current deterministic evidence.

Reason:

- Single variable is preserved.
- Helper-on/off difference is visible at validation and execution boundaries.
- Protocol control rows remain unchanged and compact.
- The correct next question is Audit C: a separately defined external pure-text baseline, not more helper-off reruns.

Handoff:

- Audit C should define a fair external pure-text object without StateRef, typed packets, hidden route/tool slots, or StateBus executor structured-decision shortcuts.
