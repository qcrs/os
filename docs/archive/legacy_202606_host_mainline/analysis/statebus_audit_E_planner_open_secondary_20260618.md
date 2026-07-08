# StateBus Audit E: Planner-Open Secondary

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

## Audit Objective

验证 Planner 在 secondary surface 中是否真实走 `plan_source=llm` 路径，并且是否被 plan contract / parser / gate 限制在可执行计划内。

本 audit 只读成 formal-secondary planner evidence，不修改 `contest_honest_headline_v1` frozen task contract，也不把 planner-open 结果写入 current communication headline。

## Single Variable

主变量是 `plan_source`：

- control rows: `plan_source=yaml`；
- planner rows: `plan_source=llm`。

固定项：

- mode 固定为 `protocol`；
- transfer strategy 固定为 `state_packet_minimal`；
- memory policy 固定为 `memory_off`；
- 不混入 text-vs-protocol headline；
- 不引入 API run；
- 不改 frozen headline rows。

## Phase 0 Mini Plan

1. 复用现有 `planner_support_v3` formal-secondary pack。
2. 只跑 protocol deterministic repeat=1，验证 LLM planner path 是否真实触发。
3. 从 row-level metrics 读取 YAML/LLM 行数、planner request、repair attempts、step roles。
4. 用 targeted tests 覆盖 report boundary 和 parser/repair gate。
5. 如果 LLM planner 失败，只记录为 secondary planner limitation，不回改 mainline headline。

## Changed Files

- `docs/analysis/statebus_audit_E_planner_open_secondary_20260618.md`
  - 本 audit 记录。

No runner or task-contract code was changed for Audit E. Existing surfaces used:

- `tasks/planner_support_v3_benchmark.yaml`
- `eval/runner.py`
- `tests/test_smoke.py`
- `tests/test_llm_runtime.py`

## Verification Commands

Deterministic artifact run:

```bash
source deploy/activate_statebus_host.sh && python -m eval.runner \
  --task-set planner_support_v3 \
  --repeat 1 \
  --modes protocol \
  --embedding-mode deterministic \
  --llm-mode deterministic \
  --out /home/qcrs/statebus/runs/planner_open_secondary_v3_det_r1_20260618_232500
```

Result: pass.

Targeted tests to run after this report:

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q \
  tests/test_smoke.py::test_planner_support_v3_runs_llm_planner_in_protocol_mode \
  tests/test_smoke.py::test_planner_support_v3_report_uses_row_level_one_shot_rate \
  tests/test_llm_runtime.py::test_planner_agent_retries_until_planner_contract_is_valid \
  tests/test_llm_runtime.py::test_plan_parser_rejects_unsupported_memory_reuse_action
```

Result: `4 passed`.

## Artifact Path

- `/home/qcrs/statebus/runs/planner_open_secondary_v3_det_r1_20260618_232500/`

Files:

- `benchmark_results.json`
- `benchmark_report.md`
- `benchmark_compare.csv`
- `benchmark_message_breakdown.csv`
- `benchmark_message_sizes.md`

No API repeat was run. The audit question is planner-path existence and contract gating; deterministic LLM output is enough for this secondary boundary check.

## Row-Level Evidence

Manifest:

| field | value |
| --- | --- |
| task_pack_type | `planner_support_v3` |
| public_surface | `formal_secondary_planner` |
| evidence_tier | `formal_secondary` |
| task_count | 11 |
| modes | `protocol` |
| single_variable | `true` |
| variable_axes | `plan_source` |
| observed planner sources | `llm`, `yaml` |
| encoder | `deterministic-v1` |
| llm_backend | `deterministic` |

Report metrics:

| metric | value |
| --- | ---: |
| yaml_control_admissible_match_rate | 0.80 |
| llm_plan_admissible_match_rate | 0.83 |
| planner_one_shot_valid_rate | 1.00 |
| planner_repair_attempt_total | 0 |
| planner_llm_request_count | 6 |
| planned_step_count | 38 |

Rows:

| plan_source | rows | planner_llm_request_count | contract final valid | one-shot valid | repair attempts |
| --- | ---: | ---: | ---: | ---: | ---: |
| `yaml` | 5 | 0 | 5/5 | 5/5 | 0 |
| `llm` | 6 | 6 | 6/6 | 6/6 | 0 |

Plan-shape observations:

| task | plan_source | planned steps | validate step |
| --- | --- | ---: | --- |
| `planner-support-checkout-yaml-001` | `yaml` | 4 | yes |
| `planner-support-checkout-llm-001` | `llm` | 4 | yes |
| `planner-support-auth-yaml-001` | `yaml` | 3 | no |
| `planner-support-auth-llm-001` | `llm` | 3 | no |
| `planner-support-cache-yaml-001` | `yaml` | 3 | no |
| `planner-support-cache-llm-001` | `llm` | 3 | no |
| `planner-support-billing-yaml-001` | `yaml` | 3 | no |
| `planner-support-billing-llm-001` | `llm` | 3 | no |
| `planner-support-deploy-yaml-001` | `yaml` | 4 | yes |
| `planner-support-deploy-llm-001` | `llm` | 4 | yes |
| `planner-support-auth-llm-002` | `llm` | 4 | yes |

Interpretation:

- The LLM planner path exists: all six LLM rows issued planner requests.
- The planner is contract-gated: all LLM rows were final-valid and one-shot-valid in this deterministic artifact.
- Validate-first rows are preserved where the task contract requires validation.
- The observed value is limited: LLM planning did not produce broad performance or correctness superiority over YAML control rows.

## What Can Now Be Claimed

Audit E supports the narrow secondary statement:

> `planner_support_v3` shows a real protocol-mode LLM planner path under a matched YAML-vs-LLM `plan_source` variable. In the deterministic repeat=1 artifact, six LLM planner rows were contract-valid on first parse, required validation steps were preserved, and no planner repair was needed.

This is planner-role and contract-gating evidence only.

## What Still Cannot Be Claimed

- This does not prove open-world autonomous planning.
- This does not prove planner-open improves the current formal headline.
- This does not prove text-vs-protocol superiority.
- This does not validate API planner stability.
- This does not show broad task decomposition novelty.
- This does not promote `planner_support_v3` into the main communication headline.

## Promote / Repeat / Stop

Recommendation: stop Audit E for this batch.

Reason:

- The single variable is clean.
- The artifact demonstrates planner path existence and contract gating.
- Further planner work should be a separate formal-secondary API repeat or harder planner task set, not a Batch 2 rerun.

Handoff:

- Next audit should be Audit F: LangGraph-native/open comparison, only as Q&A/support evidence.
