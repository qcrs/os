# StateBus v2 Final Evidence Index

Date: 2026-07-03

Scope: `feat/statebus-v2-container-runtime` v2 delivery evidence.

This index binds the current frozen v2 evidence package to a concrete commit
and records the artifact hashes needed for review. It does not claim a fresh
rerun of the full evidence suite on 2026-07-03.

## 1. Frozen Code State

| Field | Value |
| --- | --- |
| Repository | `/home/qcrs/statebus/project` |
| Branch | `feat/statebus-v2-container-runtime` |
| Frozen baseline commit | `f7dcb15bd9726078fae8252afa5c30a51ce79ded` |
| Frozen baseline subject | `chore: freeze current statebus v2 evidence snapshot` |
| Worktree status when indexed | clean, from `git status --short` |
| Evidence readout | `docs/reports/v2_api_evidence_readout_and_claim_boundary_20260702.md` |
| openEuler container report | `docs/reports/openeuler_container_validation_20260703.md` |
| Remediation source | `docs/archive/legacy_202606_host_mainline/review/v2_issue_remediation_plan_20260703.md` P0-001 |

## 2. Evidence Root

| Field | Value |
| --- | --- |
| Host evidence root | `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352` |
| Container evidence root | `/statebus/runs/v2-api-evidence-20260702_145352` |
| Runtime artifact root | `/home/qcrs/statebus/runs/v2-live/runtime` |
| Container runtime root | `/statebus/runs/v2-live/runtime` |

The evidence root contains log copies and `report_paths.txt`. The benchmark
JSON reports live under the runtime artifact root.

## 3. Environment Summary

The recorded preflight and local embedding logs report:

| Field | Value |
| --- | --- |
| `role_path_mode` | `api` |
| `embedding_mode` | `local` |
| `STATEBUS_EMBED_DEVICE` | `cuda:0` |
| `torch_cuda_available` | `true` |
| `torch_version` | `2.5.1+cu121` |
| `sentence_transformers_present` | `true` |
| embedding model path in container | `/statebus/models/Qwen3-Embedding-0.6B` |

## 4. Verification Logs

| Log | Result | sha256 |
| --- | --- | --- |
| `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/pytest-v2.log` | `152 passed in 358.04s` | `07438af471f654c0641d231afa962e75f1d57d124621491c8e5102fdebaf2f97` |
| `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/preflight-api.log` | `ok=true` | `ec16293de3d476083ae607156ab75c9890b1774f7507dbfd07e414f7d3cc605f` |
| `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/formal-api.log` | formal suite JSON copy | `8b83c60500455a42f9bf2696ba28631011500861be0a11003163ad92ec1c5cbc` |
| `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/carrier-compare-api.log` | internal carrier compare log | `5275acaeca7f35d00972f6fce765e5c4c29d5f83998bd2e73942a801ee703fa9` |
| `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/external-compare-api-debug.log` | external compare debug log | `11763631aa2a219c42c1495726eeb83cf01a9051a9bb35cb7b1d00063c39b572` |
| `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/flagship-ablation-api.log` | flagship ablation JSON copy | `66f0180b38cfcd4bb124053607096632138d54f61dab0882c8daf13952f7b5d5` |
| `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/replay-negative-audit.log` | replay audit JSON copy | `4bb3af17999ec4d7956a8b13498d11882f70e6d8cf37072531f6f9e49dd855ec` |
| `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/local-embedding-stack.log` | CUDA/local embedding stack summary | `30a545ca3d20f4fd90515353d65b5abb7914f4b44ab2e306c764a58a820f6490` |
| `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/report_paths.txt` | key JSON path index | `60e63dbc2fc9203269dcabf7e9321ba2065c4875a53f4d3f10ee9b209afd6f43` |

## 5. Key JSON Artifacts

| Artifact | Host path | Container path | sha256 | Key result |
| --- | --- | --- | --- | --- |
| Formal suite | `/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-formal-suite.json` | `/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-formal-suite.json` | `8b83c60500455a42f9bf2696ba28631011500861be0a11003163ad92ec1c5cbc` | `family_case_count=3`; `quality_floor_pass_count=3` at L3; `role_path_mode=api`; `embedding_mode=local`; internal attribution only |
| Internal carrier compare | `/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-carrier-compare.json` | `/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-carrier-compare.json` | `6c44b16d22407074255602fb2f84fb86bb05def46bbe0c94243ed90b87ca97b9` | `comparison_valid=true`; `llm_prompt_bytes_delta=-1922`; `llm_total_tokens_delta=-250`; quality unchanged |
| External compare debug | `/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-compare.json` | `/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-compare.json` | `00848b7af84263eb19e43935df1153331cc4b68ee83830b883b6aae0823bd061` | `comparison_valid=false`; `formal_superiority_claim_allowed=false`; debug-only |
| Non-text flagship ablation | `/home/qcrs/statebus/runs/v2-live/runtime/flagship-ablation/benchmark_reports/statebus-v2-benchmark-non-text-flagship-ablation.json` | `/statebus/runs/v2-live/runtime/flagship-ablation/benchmark_reports/statebus-v2-benchmark-non-text-flagship-ablation.json` | `66f0180b38cfcd4bb124053607096632138d54f61dab0882c8daf13952f7b5d5` | `stress_pass_family_count=4/4`; `total_llm_prompt_saved_by_state_ref_bytes=13834`; `total_prompt_visible_saved_by_state_ref_bytes=2100` |
| Replay negative audit | `/home/qcrs/statebus/runs/v2-live/runtime/replay-negative-audit/benchmark_reports/statebus-v2-benchmark-replay-negative-audit.json` | `/statebus/runs/v2-live/runtime/replay-negative-audit/benchmark_reports/statebus-v2-benchmark-replay-negative-audit.json` | `4bb3af17999ec4d7956a8b13498d11882f70e6d8cf37072531f6f9e49dd855ec` | `audit_pass=true`; `case_count=7`; not mature audit-grade replay |

## 6. Evidence Commands Represented

The artifact logs correspond to the following validation lanes:

```bash
python3 -m pytest -q tests/v2
python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode api --embedding-mode local
python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode api --embedding-mode local
python3 -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode api --embedding-mode local
python3 -m v2.benchmark.flagship_ablation --role-path-mode api --embedding-mode local
python3 -m v2.benchmark.live_runner --suite replay-negative-audit --role-path-mode api --embedding-mode local
```

This index records the lanes represented by the existing evidence package. It
does not assert that these commands were rerun after commit
`f7dcb15bd9726078fae8252afa5c30a51ce79ded`.

## 7. Claim Boundary

Supported by this evidence:

- Four-role `Planner -> Retriever -> Executor -> Summarizer` v2 mainline runs
  in `api` mode.
- The same StateBus runtime supports internal pure-text carrier and structured
  carrier lanes.
- The internal structured carrier comparison is valid and shows lower prompt
  scaffolding without quality regression on the fixed-answer lane.
- L2 semantic state / StateRef paths reduce raw evidence and prompt-visible
  bytes on the long/table continuous families covered by the flagship ablation.
- Replay can be claimed only for families with non-zero validated/exact replay
  counters, with CSV replay read as validated-only and long-doc replay read as
  mixed exact plus validated replay.
- CodeAct evidence is bounded to controlled CodeAct-style execution under the
  recorded root+bwrap openEuler Docker profile.

Not supported by this evidence:

- No formal external pure-text superiority claim; the external compare remains
  debug-only until its fairness gate passes.
- No KV cache or hidden-state handoff claim.
- No default non-root sandbox claim.
- No openEuler VM-level final delivery claim.
- No mature audit-grade replay claim; the negative audit has 7 cases and is not
  yet persisted-live-history audit coverage.

## 8. Replay Readout

The flagship ablation replay families must be read separately:

| Family | Scope | exact | validated | skipped steps | Boundary |
| --- | --- | ---: | ---: | ---: | --- |
| `csv_correlation_replay_v1` | replay-admissible | 0 | 8 | 8 | validated replay only; no exact replay claim |
| `long_doc_metric_replay_v1` | replay-admissible | 3 | 5 | 11 | mixed exact and validated replay; exact claim is limited to 3 target rounds |

Replay class definitions for final reporting:

| Class | Meaning | Reporting boundary |
| --- | --- | --- |
| `assist` | historical memory is available as a candidate or summary | no skipped-step or reuse-gain claim |
| `validated_replay` | some steps can be skipped after task shape, output contract, and verified-output checks | not exact replay |
| `exact_replay` | exact key matches runtime signature, input hashes, output contract, and task shape | limited to the target rounds with exact counters |

Post-index P0-006 remediation adds a tmp-path persisted-history regression:
`tests/v2/test_replay.py::test_persisted_history_replay_ignores_corrupted_output_artifact`.
It proves a corrupted persisted output artifact hash is not loaded as a replay
candidate. This is still not a full 12-case persisted-live-history audit.

## 9. First-Stage P0 Status

First-stage P0 remediation status from
`docs/archive/legacy_202606_host_mainline/review/v2_issue_remediation_plan_20260703.md`:

- P0-001: final evidence index. Completed in remediation commit `c0be113`.
- P0-004: make memory metadata first-class on `MemoryRef` / memory commits. Completed in remediation commit `c2d3064`.
- P0-005: tighten CodeAct claim wording to controlled CodeAct-style execution. Completed in remediation commit `4431d19`.
- P0-006: harden replay exact / validated / assist boundaries. Boundary docs and a tmp-path persisted-history corrupted-artifact regression are covered in remediation commit `f4475f6`; full persisted-live-history audit remains future work.
- P0-003: convert tested openEuler container results into a reproducible
  validation report with root+bwrap profile boundaries. Covered by
  `docs/reports/openeuler_container_validation_20260703.md`; VM validation
  remains future work.
