# Frozen Headline Slice View 2026-06-19

- Inputs are frozen only:
  - `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/benchmark_results.json`
  - `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/benchmark_results.json`
- This report does not mix in current-branch support refresh, active-surface repeat=1, or any audit-only pack.

## Family View

| family | task_count | api_control_bytes | det_control_bytes | api_task_ms | det_task_ms | api_exact | det_exact | api_admissible | det_admissible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| auth_rotation | 80 | 10104.92 | 11120.38 | 3485.44 | 191.04 | 0.25 | 0.25 | 1.00 | 1.00 |
| billing_queue_backlog | 80 | 10053.25 | 11036.00 | 3480.48 | 187.71 | 0.00 | 0.00 | 1.00 | 1.00 |
| checkout_regression | 80 | 10265.67 | 11077.75 | 3534.83 | 187.11 | 0.00 | 0.00 | 1.00 | 1.00 |
| deployment_config_drift | 80 | 10079.69 | 10765.12 | 3520.95 | 189.54 | 0.75 | 0.75 | 1.00 | 1.00 |
| inventory_rollout | 80 | 10292.51 | 11300.88 | 3420.19 | 186.45 | 0.25 | 0.25 | 1.00 | 1.00 |

Interpretation: `exact_match_rate=0.25` is a family-distributed issue on the text whole-lane side, not an admissibility collapse. The frozen pack keeps `admissible_match_rate=1.00` because bounded alternatives and abstention contracts still pass while exact route/tool picks remain under pressure.

## S1 vs S2

| thickness | task_count | api_control_bytes | det_control_bytes | api_task_ms | det_task_ms | api_exact | det_exact | api_admissible | det_admissible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S1 | 300 | 9605.94 | 10506.97 | 3525.30 | 233.62 | 0.27 | 0.27 | 1.00 | 1.00 |
| S2 | 100 | 11819.01 | 12719.20 | 3377.61 | 52.61 | 0.20 | 0.20 | 1.00 | 1.00 |

- `S1` fresh-retrieval rows explain most exact slippage; they require action refinement under whole-lane wording but still satisfy admissible family/tool boundaries.
- `S2` rows carry prior dependency and measured step skipping: api mean skipped steps `1.00`, api mean reuse gain `0.25`.
- `S2` therefore speaks to replay-shaped runtime behavior, while `S1` is where route/tool wording sensitivity shows up most directly.

## Fresh Retrieval vs Step Skipping

| expected_reuse_mode | task_count | api_control_bytes | det_control_bytes | api_task_ms | det_task_ms | api_exact | det_exact | api_admissible | det_admissible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| none | 300 | 9605.94 | 10506.97 | 3525.30 | 233.62 | 0.27 | 0.27 | 1.00 | 1.00 |
| skip_execute | 100 | 11819.01 | 12719.20 | 3377.61 | 52.61 | 0.20 | 0.20 | 1.00 | 1.00 |

- `fresh_retrieval` (`expected_reuse_mode=none`) stays at skipped steps `0.00` and carries the whole exact-match burden.
- `step_skipping` (`expected_reuse_mode=skip_execute`) keeps admissible behavior while adding replay effect: api skipped steps `1.00`, api reuse gain `0.25`.

## text_whole_lane vs state_packet_minimal

| family | text_control_bytes | protocol_control_bytes | delta_control_bytes | text_task_ms | protocol_task_ms | delta_task_ms | text_exact | protocol_exact | text_admissible | protocol_admissible |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| auth_rotation | 10588.88 | 9620.98 | -967.90 | 3463.21 | 3507.66 | +44.45 | 0.25 | 0.25 | 1.00 | 1.00 |
| billing_queue_backlog | 10716.48 | 9390.02 | -1326.45 | 3586.62 | 3374.34 | -212.28 | 0.00 | 0.00 | 1.00 | 1.00 |
| checkout_regression | 10858.02 | 9673.33 | -1184.70 | 3649.48 | 3420.19 | -229.30 | 0.00 | 0.00 | 1.00 | 1.00 |
| deployment_config_drift | 10609.33 | 9550.05 | -1059.28 | 3541.49 | 3500.41 | -41.08 | 0.75 | 0.75 | 1.00 | 1.00 |
| inventory_rollout | 10858.60 | 9726.42 | -1132.18 | 3430.26 | 3410.12 | -20.15 | 0.25 | 0.25 | 1.00 | 1.00 |

Interpretation: the frozen gap is not explained by support/audit pack misfires. It is the headline object's own whole-lane text route/tool exactness cost against a protocol minimal packet that keeps the same family and admissible contract intact.

## Pair Notes

- `auth_rotation`: text exact pair coverage `1/4`, protocol exact pair coverage `1/4`.
- `billing_queue_backlog`: text exact pair coverage `0/4`, protocol exact pair coverage `0/4`.
- `checkout_regression`: text exact pair coverage `0/4`, protocol exact pair coverage `0/4`.
- `deployment_config_drift`: text exact pair coverage `3/4`, protocol exact pair coverage `3/4`.
- `inventory_rollout`: text exact pair coverage `1/4`, protocol exact pair coverage `1/4`.
