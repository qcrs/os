# Document Source Map

This map treats documents as evidence leads, not facts. Claims were cross-checked against source, tests, git history, and fresh benchmark JSON.

## Current source-of-truth set

| Document | Status | Resolution |
|---|---|---|
| `README.md` | Current orientation | Valid for repo overview, but not sufficient as claim evidence. |
| `docs/constraints/current_host_and_migration.md` | Current constraint | Keep v1 host posture and v2 exception path separate. |
| `docs/constraints/current_feature_scope.md` | Current constraint | Valid for feature scope and planned-vs-real language. |
| `docs/planning/implementation_plan.md` | Current planning context | Valid as implementation plan, not proof of v2 completion. |
| `docs/reference/题目.md` | Current contest reference | Valid for contest objective framing. |
| `docs/improvement/artifacts/17_final_system_audit/17f_safe_claim_language.md` | Current safe-claim authority | Still valid and conservative. This audit reinforces its limits. |
| `docs/improvement/19_claim_upgrade_completion_report_20260706.md` | Partially valid | Correctly reports formal internal upgrade and no formal external upgrade. It should not be read as external superiority proof. |

## Claim-upgrade documents

| Document | Status | Evidence and action |
|---|---|---|
| `docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md` | Historical execution prompt; locally dirty before this audit | Useful for intended work. It is not proof. Pre-existing dirty prompt edits were not staged by this audit. |
| `docs/improvement/18_claim_upgrade_execution_plan.md` | Partially implemented plan | 25-case registry, formal families, state-pool mode, and memfd telemetry were implemented. Formal external compare and stronger validators remain incomplete. |
| `docs/improvement/17_final_system_audit_20260706.md` | Historical audit baseline | Useful problem source. Some findings were fixed by later commits; unresolved findings were merged into `05_merged_issue_ledger.md`. |
| `docs/improvement/19_claim_upgrade_completion_report_20260706.md` | Completion report with limits | Supported for internal formal and memfd claims. Not evidence for external formal superiority. |
| `docs/improvement/PROMPT_FOR_V2_COMPREHENSIVE_TRUTH_AUDIT.md` | Current audit prompt; untracked before this audit | Used as execution requirements. Not staged because it was pre-existing user work. |

## Artifact directories

| Directory / file group | Status | Resolution |
|---|---|---|
| `docs/improvement/artifacts/15_fairness_gate_propagation/*` | Historical but still relevant | Fairness gate propagation was real code work. It remains dev/fixed-answer evidence, not formal external superiority. |
| `docs/improvement/artifacts/16_deep_contest_audit/*` | Historical issue source | Important for unresolved risk tracking. Superseded by 17/19 for current safe claims. |
| `docs/improvement/artifacts/17_final_system_audit/17a_evidence_table.md` | Partially stale | Evidence table predates claim-upgrade implementation. Use as before-state comparison. |
| `17b_code_review_findings.md` | Partially stale | Several findings fixed by commits `e20b8e9` and `3738f34`; remaining issues merged into this audit. |
| `17c_benchmark_json_analysis.md` | Partially stale | Fresh artifacts in this directory supersede old formal internal fields. External API gap remains. |
| `17d_issue_ledger.md` | Partially resolved | Issue IDs are merged and deduplicated in `05_merged_issue_ledger.md`. |
| `17e_remediation_plan.md` | Partially implemented | Important: it expected `answer_restoration_replay_count=0`; this audit fixed the code/test mismatch. |
| `17f_safe_claim_language.md` | Current safe language | Still the best claim boundary. |
| `17_final_system_audit/worklog.md` | Historical worklog | Useful trace only, not final source of truth. |

## Older improvement docs

Docs `01_p0_critical_fixes.md` through `14_full_validation_rollup_20260706.md` are historical implementation and validation records. They should not be deleted because they preserve evidence, but newer documents and fresh benchmark artifacts supersede their claim wording where they discuss:

- CodeAct LLM generation stability.
- external superiority.
- speed advantage.
- openEuler compatibility.
- broad replay or answer-restoration claims.

## Local worktree note

Before this audit's edits, the worktree already contained:

- `M docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md`
- `?? docs/improvement/PROMPT_FOR_V2_COMPREHENSIVE_TRUTH_AUDIT.md`

Those files are treated as pre-existing user work and are not part of the audit commit.
