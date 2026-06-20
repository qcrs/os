# StateBus Audit F: LangGraph-Native / Open Comparison

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

## Audit Objective

回答 LangGraph-native/open comparison 在当前报告中能承担什么：它只能作为 Q&A / support audit，说明 LangGraph 可以独立承载 native text/checkpoint/store semantics，不能替代 StateBus mainline，也不能证明或否定 StateBus 的机制创新。

本 audit 不修改 `contest_honest_headline_v1` frozen task contract，不并入 current formal headline。

## Single Variable

This audit intentionally does not claim a single-variable formal comparison.

Observed surface:

- runtime arm: `langgraph_native_text_open`；
- native memory policy: `native_reuse_on`；
- task object: duplicated text row smoke, used only to trigger native replay；
- data source: `deterministic_oracle`。

The manifest correctly records:

- `single_variable = false`
- `public_surface = audit_only`
- `statebus_contract_used = false` on rows

## Phase 0 Mini Plan

1. Reuse existing `run_langgraph_native_text_open_smoke()` surface.
2. Generate a small deterministic smoke artifact only if it stays outside StateBus replay contract.
3. Verify row-level fields show native LangGraph memory backend, not StateBus `StateRef` / typed packet / replay contract.
4. Document stopline: this is not a StateBus-vs-LangGraph benchmark.

## Changed Files

- `docs/analysis/statebus_audit_F_langgraph_native_open_20260618.md`
  - 本 audit 记录。

No runner or task-contract code was changed for Audit F. Existing surfaces used:

- `eval/open_runner.py`
- `tests/test_smoke.py`

## Verification Commands

Deterministic artifact run:

```bash
source deploy/activate_statebus_host.sh && python -m eval.open_runner \
  --pack langgraph_native_text_open \
  --repeat 1 \
  --out /home/qcrs/statebus/runs/langgraph_native_text_open_smoke_det_r1_20260618_183700
```

Result: pass.

Targeted test to run after this report:

```bash
source deploy/activate_statebus_host.sh && python -m pytest -q \
  tests/test_smoke.py::test_langgraph_native_text_open_smoke_is_independent_from_statebus_replay_contract
```

Result: `1 passed`.

## Artifact Path

- `/home/qcrs/statebus/runs/langgraph_native_text_open_smoke_det_r1_20260618_183700/`

Files:

- `open_results.json`
- `open_compare.csv`
- `open_report.md`

No API repeat was run. The question is boundary placement for Q&A/support, not formal performance evidence.

## Row-Level Evidence

Manifest:

| field | value |
| --- | --- |
| task_pack | `langgraph_native_text_open_smoke` |
| runtime_arms | `langgraph_native_text_open` |
| open_memory_policies | `native_reuse_on` |
| public_surface | `audit_only` |
| single_variable | `false` |
| data_source | `deterministic_oracle` |
| artifact_reuse | `false` |

Summary:

| runtime_arm | policy | exact_match_rate | replay_hit_rate | skipped_step_count | reuse_gain | handoff_wire_bytes | data_source |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `langgraph_native_text_open` | `native_reuse_on` | 1.00 | 0.50 | 1.00 | 0.25 | 433.00 | `deterministic_oracle` |

Rows:

| task | replay_hit | skipped_step_count | statebus_contract_used | native backend |
| --- | ---: | ---: | ---: | --- |
| `rr-auth-clean-text-001` first run | false | 0 | false | `langgraph.MemorySaver+InMemoryStore` |
| `rr-auth-clean-text-001` second run | true | 2 | false | `langgraph.MemorySaver+InMemoryStore` |

Interpretation:

- Native LangGraph text/checkpoint/store replay exists on this smoke surface.
- The rows do not use StateBus replay contract, `StateRef`, typed packet, or executor structured decision helper.
- This is not a matched formal comparison against StateBus protocol mode.

## What Can Now Be Claimed

Audit F supports only this Q&A/support statement:

> The repo has a small audit-only LangGraph-native text smoke surface. It can show native checkpoint/store replay behavior with `statebus_contract_used=false`, so LangGraph can be discussed as an orchestration substrate or comparison reference without being merged into the StateBus headline.

## What Still Cannot Be Claimed

- This does not prove StateBus beats LangGraph.
- This does not prove LangGraph is weak.
- This does not replace `contest_honest_headline_v1`.
- This does not prove StateBus's innovation is LangGraph itself.
- This does not provide real-LLM, API, open-world, or framework-benchmark evidence.
- This does not validate hidden-state/KV transfer, Docker, openEuler, nsjail, or delivery packaging.

## Promote / Repeat / Stop

Recommendation: stop Audit F for this batch.

Reason:

- The Q&A boundary is answered.
- The artifact is explicitly audit-only and non-single-variable.
- A real LangGraph-native benchmark would need a new fair comparison object and should not be folded into Batch 2.
