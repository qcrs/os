# Contest39 Mainchain Result Package

This derived package contains compact evidence from the final 48-task Contest39 mainchain runs.

- `task_results.jsonl` is the canonical per-task record.
- `task_results.csv` is a flattened index for analysis and citation.
- `summary.json` and `summary.md` contain aggregate results and matched SB-FULL/P-TEXT comparisons.
- `manifest.json` records the two input run roots and collection scope.

The collector does not copy raw logs and does not infer `wire_bytes`, `typed_bytes`, object-boundary serialization bytes, or counterfactual avoided provider tokens.
