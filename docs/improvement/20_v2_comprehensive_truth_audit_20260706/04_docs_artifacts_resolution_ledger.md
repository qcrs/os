# Docs And Artifacts Resolution Ledger

## Item: Claim-upgrade execution prompt

Source document: `docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md`

Claim / issue: Directed implementation of formal families, state-pool mode, memfd evidence, external compare, and safe claims.

Expected fix: Real code/tests/benchmarks, not just docs.

Current evidence: Formal families and state-pool mode landed. External formal compare did not. File had pre-existing dirty edits.

Status: partially solved

Priority: P1

Recommended action: Keep as historical prompt; do not use as source of truth.

## Item: Claim-upgrade plan

Source document: `docs/improvement/18_claim_upgrade_execution_plan.md`

Claim / issue: Planned 25-case formal benchmark, stronger validators, memfd, external compare.

Expected fix: Implement and verify all stages.

Current evidence: 25 cases and memfd verified. Validators are not primary runner validators. External formal compare absent.

Status: partially solved

Priority: P1

Recommended action: Track validator integration and formal external compare as remaining work.

## Item: Final system audit

Source document: `docs/improvement/17_final_system_audit_20260706.md`

Claim / issue: Identified unsafe claims and implementation gaps.

Expected fix: Merge issues into current ledger.

Current evidence: Later commits fixed some gaps; this audit merged remaining issues.

Status: partially solved

Priority: P1

Recommended action: Use this audit's merged ledger as current tracker.

## Item: Evidence table

Source document: `docs/improvement/artifacts/17_final_system_audit/17a_evidence_table.md`

Claim / issue: Before-state evidence matrix.

Expected fix: Replace stale benchmark facts with fresh artifacts.

Current evidence: Fresh formal artifacts in this directory supersede internal formal fields.

Status: stale for formal internal benchmark; useful historical reference

Priority: P2

Recommended action: Cite only as pre-upgrade baseline.

## Item: Code review findings

Source document: `17b_code_review_findings.md`

Claim / issue: Source-level implementation gaps.

Expected fix: Implement real changes.

Current evidence: Formal registry and statepool observability fixed; answer restoration overclaim fixed in this audit.

Status: partially solved

Priority: P1

Recommended action: Keep open items in `05_merged_issue_ledger.md`.

## Item: Benchmark JSON analysis

Source document: `17c_benchmark_json_analysis.md`

Claim / issue: Earlier benchmark JSON was insufficient for several claims.

Expected fix: Rerun formal and extract fields.

Current evidence: Fresh formal JSON artifacts added. No formal external JSON.

Status: partially solved

Priority: P1

Recommended action: Add formal external compare artifact when available.

## Item: Issue ledger

Source document: `17d_issue_ledger.md`

Claim / issue: Prior issue tracking.

Expected fix: De-duplicate into one current ledger.

Current evidence: Done in `05_merged_issue_ledger.md`.

Status: solved for merge; issues remain by status

Priority: P1

Recommended action: Use merged ledger going forward.

## Item: Remediation plan

Source document: `17e_remediation_plan.md`

Claim / issue: Included explicit requirement that answer restoration not be inflated.

Expected fix: `answer_restoration_replay_count` should remain zero absent real feature.

Current evidence: Fixed in `v2/runtime/driver.py`, `v2/benchmark/continuous_runner.py`, and tests.

Status: solved for answer restoration; partially solved overall

Priority: P1

Recommended action: Continue remaining plan items as staged work.

## Item: Safe claim language

Source document: `17f_safe_claim_language.md`

Claim / issue: Conservative wording for current evidence.

Expected fix: Keep docs aligned to safe claims.

Current evidence: Still valid. This audit adds CodeAct warning to older experiment summary.

Status: current effective source

Priority: P0

Recommended action: Use as claim boundary until formal external/API evidence changes.

## Item: Claim-upgrade completion report

Source document: `docs/improvement/19_claim_upgrade_completion_report_20260706.md`

Claim / issue: Reports completed upgrade and limitations.

Expected fix: Verify that reported implementation exists and limits are honest.

Current evidence: Internal formal and memfd claims verified. Formal external superiority remains absent as the report says.

Status: partially valid

Priority: P1

Recommended action: Do not strengthen beyond its own limitations.

## Item: Fairness gate artifacts

Source document: `docs/improvement/artifacts/15_fairness_gate_propagation/*`

Claim / issue: External fairness gate propagation.

Expected fix: Ensure fairness failures propagate.

Current evidence: Historical commits show real fairness work. Scope remains dev/fixed-answer unless formal compare rerun.

Status: solved for historical fairness propagation; not formal superiority

Priority: P2

Recommended action: Keep as historical dev evidence.

## Item: Deep contest audit artifacts

Source document: `docs/improvement/artifacts/16_deep_contest_audit/*`

Claim / issue: Broad contest risks and issue list.

Expected fix: Fold into current ledger.

Current evidence: Relevant items merged into this audit.

Status: partially superseded

Priority: P2

Recommended action: Keep archived; use current ledger for action.
