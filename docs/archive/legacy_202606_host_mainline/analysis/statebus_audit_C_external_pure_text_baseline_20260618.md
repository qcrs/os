# StateBus Audit C: External Pure-Text Baseline

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

## Audit Objective

定义并验证一个 audit-only external pure-text baseline，用来说明传统 text-only multi-agent baseline 与当前 `text_whole_lane` internal comparator 的边界差异。

本 audit 不试图证明 StateBus 打赢 external pure-text baseline；它只回答这个 baseline surface 是否能在不使用 StateBus runtime helper path 的情况下独立运行并产出可审计 artifact。

## Single Variable

主变量是 runtime helper availability / external baseline object：

- external pure-text：`external_text_open`，独立 lexical text runtime；
- 不使用 StateBus executor structured decision helper；
- 不消费 `StateRef`；
- 不消费 typed packets；
- 不读取 hidden route/tool slots；
- 不进入 `contest_honest_headline_v1` formal headline。

固定项：

- 不改 frozen `contest_honest_headline_v1` task contract；
- 不覆盖 frozen artifact；
- 不引入 API run；
- 使用同一 local corpus 和公开 text task fields。

## Phase 0 Mini Plan

读到的关键边界：

- `external_text_baseline_audit_v3` 是旧 audit-only task pack，但它仍走 StateBus benchmark runner / text lane surface，不应直接当传统 external pure-text conclusion。
- `eval/text_open_baseline.py` 的 `ExternalTextOpenRuntime` 不导入 `runtime`、`protocol`、`statepool`，用 lexical playbook 和 text message log 做决策。
- `eval/open_runner.py` 的 `run_pure_text_open_baseline()` 已经把 `external_text_open` 从 `open_system_comparison_v1` 中分离出来。

Mini plan：

1. 保留 `pure_text_open_baseline_v1`，不另造重复 runner。
2. 收紧 pure-text task loader：只选 text rows，覆盖 small mixed slice，而不是只抽 simple rows。
3. 把 manifest / summary 的 data source 标成 `lexical_stub`，避免被读成 deterministic oracle 或 API evidence。
4. 增加 targeted tests，证明 external runtime 不读 metadata oracle、StateRef、typed packet 或 StateBus contract。
5. 生成 deterministic repeat=1 artifact。

## Changed Files

- `eval/open_runner.py`
  - `run_pure_text_open_baseline()` 改用 `_load_pure_text_open_tasks()`。
  - manifest 新增 `selected_task_ids` 和 `selected_complexity_buckets`。
  - pure-text summary / manifest 的 `data_source` 改为 `lexical_stub`。
- `tests/test_smoke.py`
  - 增加 pure-text baseline mixed-slice selection tests。
  - 增加 too-narrow task surface rejection test。
  - 扩展 metadata oracle leakage fixture，覆盖 simple / ambiguous / reusable rows。
- `docs/analysis/statebus_audit_C_external_pure_text_baseline_20260618.md`
  - 本 audit 记录。

## Verification Commands

Phase 1 before Audit C edits:

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q
```

Result: `219 passed, 101 warnings`.

```bash
source deploy/activate_statebus_host.sh && python -m runtime.smoke
```

Result: pass; deterministic repeat=1 host sanity emitted `statebus smoke ok` for both text and protocol.

Targeted after Audit C edits:

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q \
  tests/test_smoke.py::test_pure_text_open_baseline_v1_runs_one_external_arm_and_writes_outputs \
  tests/test_smoke.py::test_pure_text_open_baseline_v1_selects_text_rows_across_small_mixed_complexity_slice \
  tests/test_smoke.py::test_pure_text_open_baseline_v1_rejects_too_narrow_task_surface \
  tests/test_smoke.py::test_external_text_open_ignores_expected_metadata_oracle_fields \
  tests/test_smoke.py::test_external_text_open_native_reuse_requires_same_retrieved_doc_set \
  tests/test_smoke.py::test_external_text_open_message_log_stays_text_only_and_without_markers \
  tests/test_smoke.py::test_external_text_open_source_stays_outside_statebus_runtime_and_structured_packets
```

Result: `7 passed`.

Deterministic artifact run:

```bash
source deploy/activate_statebus_host.sh && python -m eval.open_runner \
  --pack pure_text_open_baseline_v1 \
  --repeat 1 \
  --task-set contest_dual_mode_controlled_v3 \
  --out /home/qcrs/statebus/runs/pure_text_open_baseline_v1_det_r1_20260618_230500
```

Result: pass.

## Artifact Path

- `/home/qcrs/statebus/runs/pure_text_open_baseline_v1_det_r1_20260618_230500/`

Files:

- `open_results.json`
- `open_compare.csv`
- `open_report.md`

No API repeat was run. The deterministic lexical artifact answers the object-boundary question; API would not strengthen the baseline definition.

## Row-Level Evidence

Manifest:

| field | value |
| --- | --- |
| task_pack | `pure_text_open_baseline_v1` |
| runtime_arms | `external_text_open` |
| open_memory_policies | `memory_off`, `native_reuse_on` |
| public_surface | `audit_only` |
| data_source | `lexical_stub` |
| selected_complexity_buckets | `ambiguous`, `reusable`, `simple` |
| statebus contract | not used by rows |

Summary:

| policy | exact_match_rate | replay_hit_rate | skipped_step_count | reuse_gain | handoff_wire_bytes | data_source |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| memory_off | 1.00 | 0.00 | 0.00 | 0.00 | 449.33 | lexical_stub |
| native_reuse_on | 1.00 | 0.50 | 1.00 | 0.25 | 417.33 | lexical_stub |

Selected row families and buckets:

| family | rows |
| --- | --- |
| `contest_release_auth_rotation` | clean / ambiguous / replay_reusable text rows |
| `contest_release_billing_queue` | clean / ambiguous / replay_reusable text rows |

Per-row guard fields:

- `runtime_arm = external_text_open`
- `statebus_contract_used = false`
- `metadata_oracle_used = false`
- `decision_source = text_only_lexical_playbook`
- `data_source = lexical_stub`

Targeted oracle-leak test evidence:

- Custom fixture sets wrong `primary_expected_route` and wrong `primary_expected_tool`.
- External runtime still selects route/tool from lexical corpus/playbook.
- Correctness becomes false against the intentionally wrong oracle fields, proving the decision did not consume expected metadata.

## What Can Now Be Claimed

Audit C supports the narrow secondary statement:

> A separate audit-only external pure-text baseline surface now exists and runs outside StateBus runtime/protocol/statepool helper paths. On the covered lexical-stub slice, it uses text messages, corpus snippets, and a lexical playbook rather than StateRef, typed packets, metadata oracle fields, or executor structured-decision recovery.

It can also be said that current `text_whole_lane` should remain an internal runtime-assisted comparator, while `pure_text_open_baseline_v1` is the separate external-text audit surface.

## What Still Cannot Be Claimed

- This is not API / real-LLM evidence.
- This does not prove StateBus beats external pure-text MAS.
- This does not become part of the frozen formal headline.
- This does not validate open-world agent benchmark performance.
- This does not compare against AutoGen, CAMEL, MetaGPT, ToolBench, AgentBench, or GAIA.
- This does not prove long-term memory; `native_reuse_on` is a baseline-local text replay store.

## Promote / Repeat / Stop

Recommendation: stop Audit C after current deterministic evidence.

Reason:

- The external pure-text object is now separately runnable and guarded.
- The audit shows boundary distance from `text_whole_lane`.
- A real external framework/API comparison would be a different audit object and should not be folded into Batch 2 unless explicitly reopened.

Handoff:

- Next audit should be Audit D: route/corpus stress.
