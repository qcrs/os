# StateBus v2 Contest Evidence Index

Date: 2026-07-20

Scope: fresh contest evidence closure for `feat/yzm-v2-migration`.

This index distinguishes canonical evidence from failed, interrupted, overlapping, and diagnostic runs. It binds each canonical run to its manifest identity and checksum ledger. The result report is [contest_evidence_closure_final_report_20260720.md](contest_evidence_closure_final_report_20260720.md).

## 1. Evidence Identity

| Field | Value |
| --- | --- |
| Repository | `/home/qcrs/statebus/project` |
| Branch | `feat/yzm-v2-migration` |
| Recorded HEAD | `a3a5ec836d13c5e9d77811edd25d58d24af227b6` |
| Manifest worktree state | `git_dirty=true` |
| Host evidence root | `/home/qcrs/statebus/runs/contest_evidence_closure_20260720` |
| Container evidence root | `/statebus/runs/contest_evidence_closure_20260720` |
| Container image digest | `sha256:715ded05373ca023f3acf33d180b8db2e0c4f2b1361b6c2a31c58c33c1fb6647` |
| OS | openEuler 24.03 LTS-SP3 |
| Python | 3.11.6 |
| Role model | `qwen3-32b` |
| Embedding model | `/statebus/models/Qwen3-Embedding-0.6B`, revision `4.51.3` |
| Capability registry digest | `239fdc32997c4f81e13e614b8f1fe5c99cf099d3a40e07164b2652d54000ac57` |

The dirty flag is part of the evidence identity and must not be rewritten as a clean commit snapshot. Runtime content was separately frozen and audited for E4.

## 2. Canonical E0-E6 Runs

All paths below are under `/home/qcrs/statebus/runs/contest_evidence_closure_20260720/`.

| ID | Run directory | Result | Primary evidence | `checksums.sha256` sha256 |
| --- | --- | --- | --- | --- |
| E0 | `e0_focused_20260720_142422` | 135 passed; preflight OK | `summary.json`, `pytest.log`, `raw/` | `677d64e0ac8e4990e9abbeda98e1aaaa4e4488c8b269469d013d5ace1b5a2288` |
| E1 | `e1_causal_serial_20260720_150801` | 40/40; fairness valid | `summary.json`, `fairness_manifest.json`, seven audit slices | `ae0b2d341181d347b0745b09fb3ba7d0b1028df9f04d6680b51387ea9d5f0ce8` |
| E2 | `e2_stress_serial_20260720_152924` | 20/20; two families 10/10 | `summary.json`, memory/replay slices | `69f09b982c29a4ef3eabd27990b48f9c3d07ba67dc99728cbbf6e64fadafaccb` |
| E3 | `e3_adaptive_memory_final_20260720_160244` | 6/6; memory loop closed | `summary.json`, `memory_queries/`, `memory_consumption/` | `79b6390bb26e7b6d651fc0a87d4128844946f4b96e9cb89579f9a464c586ecd2` |
| E4 | `e4_semantic_holdout_final4_20260720_175430` | 4/4; semantic 3/table 1 | `summary.json`, `state_consumption/`, Runtime freeze audit | `c002a9b934e6ea408bb5f37318c48fd901fcb91640907e9f6713213026a7d015` |
| E5 | `e5_adaptive_final_20260720_190107` | 25/25; DSL 7/Python 18 | `summary.json`, 25 files in each audit slice | `dbd16c769b666fccb9aef6af973535c21d3180fb856dc831cf3ff7e88c90652a` |
| E6 | `e6_full_final_20260720_201043` | 558 passed; preflight OK | `summary.json`, `pytest.log`, `raw/` | `03b7ef22e69bae2222c419253aaf5d1291a662429b86a32f51ee32aa53002fb3` |

Each canonical root contains the common evidence envelope:

```text
run_manifest.json
environment.json
fairness_manifest.json
capability_registry.json
summary.json
summary.md
pytest.log
console.log
checksums.sha256
case_reports/
role_requests/
state_consumption/
memory_queries/
memory_consumption/
replay_decisions/
artifact_lineage/
```

E0/E6 legitimately have zero materialized case slices because they are pytest/preflight engineering gates. E1-E5 materialize suite-native cases. In E5, each of the seven audit-slice directories contains exactly 25 JSON files.

## 3. Canonical Result Pointers

### E1 causal matrix

- Summary: `e1_causal_serial_20260720_150801/summary.json`
- Fairness: `e1_causal_serial_20260720_150801/fairness_manifest.json`
- Manifest: `e1_causal_serial_20260720_150801/run_manifest.json`
- Per-case payloads: `e1_causal_serial_20260720_150801/case_reports/`
- Native runtime reports: `e1_causal_serial_20260720_150801/runtime/`

The summary records `round_view=causal_core`, `execution_scope=formal_causal_view`, 40 cases, and a 10/10 quality pass for every lane.

### E2 long horizon

- Summary: `e2_stress_serial_20260720_152924/summary.json`
- Manifest: `e2_stress_serial_20260720_152924/run_manifest.json`
- Memory decisions: `e2_stress_serial_20260720_152924/memory_consumption/`
- Replay decisions: `e2_stress_serial_20260720_152924/replay_decisions/`

The summary records `round_view=long_horizon`, `execution_scope=formal_stability_view`, and `stability_evidence_eligible=true`; it is not a four-lane causal comparison.

### E3 Adaptive memory

- Summary: `e3_adaptive_memory_final_20260720_160244/summary.json`
- Candidate/query slices: `e3_adaptive_memory_final_20260720_160244/memory_queries/`
- Actual consumer records: `e3_adaptive_memory_final_20260720_160244/memory_consumption/`
- Negative decisions: `e3_adaptive_memory_final_20260720_160244/replay_decisions/`

The six-case sequence uses a shared family store across fresh Runner instances. The negative fixture remains visible but unconsumed.

### E4 semantic holdout

- Summary: `e4_semantic_holdout_final4_20260720_175430/summary.json`
- State consumption: `e4_semantic_holdout_final4_20260720_175430/state_consumption/`
- Per-case StateRef metadata: `e4_semantic_holdout_final4_20260720_175430/runtime/semantic-holdout/`
- Freeze source: `/home/qcrs/statebus/project/docs/improvement/25_contest_evidence_closure_20260720/runtime_freeze_snapshot.json`
- Freeze per-file ledger: `/home/qcrs/statebus/project/docs/improvement/25_contest_evidence_closure_20260720/runtime_freeze_files.sha256`

The freeze is a content snapshot over four Runtime directories, not a Git range.

### E5 Adaptive/CodeAct

- Summary: `e5_adaptive_final_20260720_190107/summary.json`
- Cases: `e5_adaptive_final_20260720_190107/case_reports/`
- Persisted role requests: `e5_adaptive_final_20260720_190107/role_requests/`
- Execution lineage: `e5_adaptive_final_20260720_190107/artifact_lineage/`

All 18 bounded Python records use bwrap and UID/GID 65534; no model/runtime/sandbox fallback is recorded.

## 4. Runtime Freeze Ledger

| Field | Value |
| --- | --- |
| Freeze kind | `dirty_worktree_content_hash` |
| Runtime freeze SHA | `e0b04923132f4a139eaa4c2b0ec71b1299d5fd75ccb492d362987a67f5f95afa` |
| Per-file count | 59 |
| Per-file ledger hash | `b3a13dd7c23e15c5c726cbec3c7f97259458bed260969d0f712e470122b18ebe` |
| Directories | `v2/runtime`, `v2/control`, `v2/state`, `v2/memory` |
| E4 audit | no added, changed, or removed files |

## 5. Preserved Non-Canonical Runs

These roots are retained for failure analysis and must not be deleted or aggregated into canonical results:

| Run | Classification |
| --- | --- |
| `focused_20260720_140122` | failed focused baseline: 133 passed, 1 failed |
| `causal_20260720_142709` | passing but overlaps E0; excluded from formal serial evidence |
| `e1_causal_20260720_143554` | interrupted, child exit `-15` |
| `stress_20260720_145740` | interrupted, child exit `-15`; cleanup warning retained |
| `e3_adaptive_memory_serial_20260720_154048` | 5/6; negative gate failed |
| `e4_semantic_holdout_serial_20260720_170818` | 1/4 |
| `e4_semantic_holdout_final_20260720_172250` | 2/4 |
| `e4_semantic_holdout_final2_20260720_173344` | 3/4 |
| `e4_semantic_holdout_final3_20260720_174324` | 2/4 |
| `e5_adaptive_serial_20260720_180846` | 24/25; `formal-agg-002` failed |
| `e5_formal_agg_002_probe_20260720_185808` | one-case diagnostic probe, not E5 |
| `e6_full_serial_20260720_195042` | 555 passed, 3 failed; preflight passed |
| `e6_memory_slice_probe_20260720_200735` | memory-input diagnostic, not replay evidence |
| `phase5_focused_20260720_140910` | 125 passed, 1 failed |
| `phase5_focused_20260720_142012` | 126 passed follow-up focused run |

Additional intermediate roots such as `baseline_*`, `phase3_*`, `phase4_*`, `focused_20260720_141403`, and `e3_adaptive_memory_rerun_*` remain available but are not canonical headline evidence.

## 6. Integrity Verification

The final host-side audit ran `sha256sum -c --quiet checksums.sha256` from each canonical root. All seven commands returned exit 0. It also verified all 59 Runtime freeze entries and recomputed each of the four directory hashes; all matched section 4.

`git diff --check` returned exit 0. The git-visible path scan found no run/cache/model/key/secret material in the worktree. The completion audit records exact command outcomes, separately present research files, process state, and failed Git commit attempts.

Because the primary `.git` is read-only, a five-commit recovery series is also materialized in `/home/qcrs/statebus/work/contest_evidence_closure_commit_staging_20260720`. Its portable bundle, format-patch directory, and authoritative commit manifest use the fixed paths below:

```text
/home/qcrs/statebus/work/contest_evidence_closure_20260720.bundle
/home/qcrs/statebus/work/contest_evidence_closure_20260720_patches/
/home/qcrs/statebus/work/contest_evidence_closure_20260720_commit_series.txt
```

This recovery series excludes the separate KV/hidden research prompt edit, paper PDF, and design document. It does not make the primary worktree clean and is not a substitute for importing the commits after primary Git metadata becomes writable.

## 7. Claim Precedence

For 2026-07-20 contest claims, use the following precedence:

1. This evidence index and the final report.
2. Canonical E0-E6 manifests, summaries, audit slices, and checksum ledgers.
3. [completion audit](../improvement/25_contest_evidence_closure_20260720/01_completion_audit_20260720.md).
4. Earlier reports only as historical context.

Do not use a non-canonical run to replace a canonical count, and do not collapse matched text, semantic state, memory classes, or sandbox boundaries into stronger claims than the final report permits.
