# Scope And Run Index

This is a static evidence audit. It does not import Runtime, call a model, modify an existing run artifact, or change tests.

## Inputs

| Group | Host root | Container mapping | Role |
| --- | --- | --- | --- |
| P0 full matrix | `/home/qcrs/statebus/runs/full_qwen3_full_p1_20260715_001059` | `/statebus/runs/full_qwen3_full_p1_20260715_001059` | Historical stages 00-15 |
| pytest repair | `/home/qcrs/statebus/runs/full_qwen3_full_p1_fix_20260715_001459/logs/01_pytest_v2.log` | n/a | Later pytest-only evidence |
| P1 extension | `/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121` | `/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121` | Additive stages 16-18 |

## Counting

- Stage labels: 19 (`00` through `18`).
- User-level independent experimental units: 18 (`01` through `18`). `00_preflight` is a configuration/precondition label, so it belongs in the 19-label stage index but not in the user's 18-experiment convention. The later pytest repair remains separate.
- Primary normalized execution records: `948` total: `870` StateBus task-metric rows and `78` external-comparator rows. These records preserve layer, family, variant, repeat and case expansion; they are intentionally not cross-stage deduplicated.
- Excluded partial-repair candidates: `546`. They remain fully inventoried but cannot be used as experiment evidence because the repair run was interrupted at Stage 02.
- `16_backend_matrix` contains three backend variants. Stage 18 has four paired repeats, two request conditions per pair and two evidence corpora; its request-level observations are held in its own repeat artifact rather than fabricated as task-metric rows.

## Historical Status Boundary

- P0 has 16 recorded labels and historical non-pass label(s): 01_pytest_v2.
- P1 has 3 recorded labels and historical non-pass label(s): 18_prefix_parity_clean_repeats.
- P0 `matrix_complete` describes recorded coverage, not a 16/16 pass. The repair log may support the exact pytest conclusion only; it does not replace the historical P0 summary.

## Reproduction

```bash
python3 scripts/analyze_qwen3_p0_p1_experiment_evidence_20260715.py \
  --full-root "/home/qcrs/statebus/runs/full_qwen3_full_p1_20260715_001059" \
  --pytest-repair-log "/home/qcrs/statebus/runs/full_qwen3_full_p1_fix_20260715_001459/logs/01_pytest_v2.log" \
  --p1-root "/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121" \
  --output-root "docs/improvement/22_qwen3_p0_p1_experiment_evidence_audit_20260715"
```

The script validates its output JSON, CSV header/row shape, unique ledger keys and non-zero denominators before exit.
