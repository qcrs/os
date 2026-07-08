# StateBus Audit A: S2 Negative Control

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

## Audit Objective

验证 current-headline S2 replay / prior-dependent action 是否真的依赖有效 prior case、prior route、prior rejection 和 replay-compatible artifact，而不是只靠 S2 标签、route 标签或硬编码 shortcut 升级到 validated tool / replay。

## Single Variable

主变量是 prior dependency validity。

固定项：

- 不改 `contest_honest_headline_v1` frozen task contract。
- 不改 frozen artifact。
- 不改 text/protocol mode object。
- 不引入 API run。

## Why This Does Not Mutate Frozen Headline

本 audit 只新增 targeted deterministic tests 和 audit 记录。测试直接覆盖现有 S2 boundary / replay matcher，不新增或修改 `contest_honest_headline_v1` row，不把结果并入 current formal headline。

## Changed Files

- `tests/test_smoke.py`
  - 新增 `test_s2_negative_controls_do_not_upgrade_without_valid_prior`。
  - 新增 `test_s2_replay_negative_controls_require_prior_contract_and_replay_artifact`。
- `docs/reports/MASTER_PRESENTATION_GUIDE.md`
  - 补回 active docs gate 要求的 `单一通信载体变量对照` wording；这是 baseline doc-test 修复，不是 Audit A 的 claim 扩张。
- `docs/analysis/statebus_audit_A_s2_negative_control_20260618.md`
  - 本 audit 记录。

## Verification Commands

Baseline before edits:

```bash
source deploy/activate_statebus_host.sh && python -m runtime.smoke
```

Result: pass.

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q
```

Result before edits: `209 passed, 1 failed`; the failure was doc wording only:
`test_active_docs_reference_memory_dual_mode_fairness_v3_and_drop_old_formal_wording` expected `单一通信载体变量对照` in `docs/reports/MASTER_PRESENTATION_GUIDE.md`.

Targeted after edits:

```bash
python -m pytest -q \
  tests/test_smoke.py::test_active_docs_reference_memory_dual_mode_fairness_v3_and_drop_old_formal_wording \
  tests/test_smoke.py::test_s2_negative_controls_do_not_upgrade_without_valid_prior \
  tests/test_smoke.py::test_s2_replay_negative_controls_require_prior_contract_and_replay_artifact
```

Result: `7 passed`.

Broader S2/headline gate subset:

```bash
python -m pytest -q \
  tests/test_smoke.py::test_s2_prior_dependency_changes_admissible_action_boundary \
  tests/test_smoke.py::test_s2_negative_controls_do_not_upgrade_without_valid_prior \
  tests/test_smoke.py::test_s2_replay_negative_controls_require_prior_contract_and_replay_artifact \
  tests/test_smoke.py::test_headline_gates_split_memory_replay_from_generic_state_transfer_flag \
  tests/test_smoke.py::test_contest_honest_headline_v1_rows_emit_thickness_contract_fields
```

Result: `9 passed`.

Full post-change regression:

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q
```

Result: `216 passed`.

```bash
source deploy/activate_statebus_host.sh && python -m runtime.smoke
```

Result: pass; deterministic repeat=1 host sanity emitted `statebus smoke ok` for both text and protocol.

## Artifact Path

No new benchmark run artifact was created for Audit A. The audit evidence is targeted deterministic pytest coverage plus the already frozen headline artifact:

- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`

Rationale: Audit A is about the validity gate semantics around S2 prior/replay. A new API run would not add object clarity until the negative-control tests first prove the gate-level contract.

## Row-Level Evidence

Positive guard already existed:

- `test_s2_prior_dependency_changes_admissible_action_boundary`
  - no prior: falls back to `tool.collect_more_evidence`;
  - valid prior: upgrades to `tool.db_query_hotfix`;
  - observed prior case, route, and rejection are emitted.

New negative controls:

| Case | Evidence |
| --- | --- |
| missing prior case | `s2_prior_dependency_satisfied = False`; `validated_action_contract = abstain_collect_more_evidence`; missing case reports `rr-checkout-clean` |
| wrong prior route | no upgrade; missing route reports `db_pool_saturation` |
| missing required rejection | no upgrade; missing rejection reports `worker_queue_starvation` |
| wrong rejected route | no upgrade; missing rejection reports `worker_queue_starvation` |
| prior exists but task family mismatch | commit is stored under another `task_theme`; current S2 boundary does not see it and reports missing prior case |
| replay-compatible artifact absent | `_matches_headline_s2_prior_replay` returns false when evidence refs are empty |
| replay artifact incompatible | matcher returns false when `TOOL_ARTIFACT` has `channel_replay_compatible = False` |
| non-artifact replay evidence | matcher returns false for `REPLAY_ELIGIBILITY_BUNDLE` alone |
| wrong replay case / rejection / route / class / reusable step | matcher returns false for each invalid variant |
| positive S2 replay row | matcher returns true only for required case `rr-checkout-clean`, required route `db_pool_saturation`, required rejection `worker_queue_starvation`, `validated_replay`, executable reusable step, lexical provenance, and replay-compatible `TOOL_ARTIFACT` |

## What Can Now Be Claimed

Audit A supports the narrow secondary statement:

> Current S2 prior-dependent action and replay matching do not upgrade on the covered invalid prior/replay variants; valid prior case, route, rejection, replay class, route provenance, and replay-compatible tool artifact are required by the tested gate paths.

## What Still Cannot Be Claimed

- This does not make S2 replay an open-world memory claim.
- This does not promote Audit A into the frozen formal headline.
- This does not prove external pure-text baseline fairness.
- This does not prove route/corpus stress robustness.
- This does not require or validate API repeat behavior.

## Promote / Repeat / Stop

Recommendation: stop Audit A after current targeted evidence unless a later report needs a runner-level negative-control artifact table.

Reason:

- Required invalid prior categories are covered.
- Positive S2 row remains covered.
- The audit preserved single variable and did not touch frozen headline.

Handoff:

- Next audit should be Audit B: text helper ablation.
