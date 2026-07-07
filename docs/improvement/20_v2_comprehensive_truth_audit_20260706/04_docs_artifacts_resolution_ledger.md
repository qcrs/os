# 文档与 Artifacts Resolution Ledger

注：本 ledger 记录的是本轮审计当时读取过的历史来源。后续文档整理已把 prompt、01-19 中间态 improvement 文档和 15-17 artifacts 从 active docs tree 清理；如需追溯这些来源，请从 git 历史读取。当前 source-of-truth 以本审计、保留的 fresh JSON artifacts 和 local+api 深挖文档为准。

## 条目：Claim-upgrade execution prompt

来源文档：`docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md`

声明 / 问题：指示实现 formal families、state-pool mode、memfd evidence、external compare 和 safe claims。

预期修复：真实代码、测试和 benchmark，而不是只改文档。

当前证据：formal families 与 state-pool mode 已落地。post-fix targeted external compare 和 `local_api_20260707_163354` full comprehensive 已覆盖 formal financial 8 cases / 1 family strict equal-quality；full formal registry 25 cases / 5 families compare 仍未完成。该文件有本轮前已存在的 dirty edits。

状态：partially solved

优先级：P1

建议动作：已从 active docs tree 清理；不要作为 source of truth。

## 条目：Claim-upgrade plan

来源文档：`docs/improvement/18_claim_upgrade_execution_plan.md`

声明 / 问题：计划 25-case formal benchmark、更强 validators、memfd、external compare。

预期修复：实现并验证所有 stages。

当前证据：25 cases 与 memfd 已在 `local_api_20260707_163354` 验证。Validators 不是 primary runner validators。post-fix formal external compare 只覆盖 8 cases / 1 family；full 25/5 external compare 缺失。

状态：partially solved

优先级：P1

建议动作：继续跟踪 validator integration 与 formal external compare。

## 条目：Final system audit

来源文档：`docs/improvement/17_final_system_audit_20260706.md`

声明 / 问题：识别 unsafe claims 和 implementation gaps。

预期修复：把 issues 合并到当前 ledger。

当前证据：后续 commits 修复了部分 gaps；本审计合并了剩余问题。

状态：partially solved

优先级：P1

建议动作：使用本审计 merged ledger 作为当前 tracker。

## 条目：Evidence table

来源文档：`docs/improvement/artifacts/17_final_system_audit/17a_evidence_table.md`

声明 / 问题：before-state evidence matrix。

预期修复：用 fresh artifacts 替换过时 benchmark facts。

当前证据：本目录 fresh formal artifacts 替代 internal formal fields。

状态：对 formal internal benchmark 已 stale；仍可作为历史参考

优先级：P2

建议动作：仅作为 pre-upgrade baseline 引用。

## 条目：Code review findings

来源文档：`17b_code_review_findings.md`

声明 / 问题：源码级 implementation gaps。

预期修复：真实实现变更。

当前证据：formal registry 与 statepool observability 已修复；answer restoration overclaim 在本审计修复。

状态：partially solved

优先级：P1

建议动作：开放项保留在 `05_merged_issue_ledger.md`。

## 条目：Benchmark JSON analysis

来源文档：`17c_benchmark_json_analysis.md`

声明 / 问题：早期 benchmark JSON 不足以支撑多个 claims。

预期修复：重跑 formal 并抽取字段。

当前证据：已添加 fresh formal JSON artifacts。没有 formal external JSON。

状态：partially solved

优先级：P1

建议动作：有条件时补 formal external compare artifact。

## 条目：Issue ledger

来源文档：`17d_issue_ledger.md`

声明 / 问题：之前的问题追踪。

预期修复：去重合并到一个当前 ledger。

当前证据：已在 `05_merged_issue_ledger.md` 完成。

状态：merge 已解决；具体 issues 按状态继续跟踪

优先级：P1

建议动作：后续使用 merged ledger。

## 条目：Remediation plan

来源文档：`17e_remediation_plan.md`

声明 / 问题：包含 answer restoration 不得膨胀的明确要求。

预期修复：在没有真实 feature 前，`answer_restoration_replay_count` 应保持 zero。

当前证据：已在 `v2/runtime/driver.py`、`v2/benchmark/continuous_runner.py` 和测试中修复。

状态：answer restoration 已解决；整体仍部分解决

优先级：P1

建议动作：继续推进 plan 的剩余项。

## 条目：Safe claim language

来源文档：`17f_safe_claim_language.md`

声明 / 问题：当前证据下的保守表述。

预期修复：保持 docs 与 safe claims 对齐。

当前证据：仍然有效。本审计对旧 experiment summary 增加 CodeAct warning。

状态：current effective source

优先级：P0

建议动作：在 formal external/API 证据变化前，继续作为 claim boundary。

## 条目：Claim-upgrade completion report

来源文档：`docs/improvement/19_claim_upgrade_completion_report_20260706.md`

声明 / 问题：报告 upgrade 完成情况与限制。

预期修复：验证 report 中的实现是否存在，限制是否诚实。

当前证据：internal formal 与 memfd claims 已验证。formal external superiority 缺失，且报告本身也这样说明。

状态：partially valid

优先级：P1

建议动作：不要超出它自己的限制去强化 claim。

## 条目：Fairness gate artifacts

来源文档：`docs/improvement/artifacts/15_fairness_gate_propagation/*`

声明 / 问题：External fairness gate propagation。

预期修复：确保 fairness failures 能传播。

当前证据：历史 commits 显示真实 fairness work。post-fix targeted formal compare 已重跑 8-case financial scope；`local_api_20260707_163354` 中该 scope fairness 8/8、strict equal-quality gate 通过；full registry compare 仍缺失。

状态：历史 fairness propagation 已解决；不是 formal superiority

优先级：P2

建议动作：作为历史 dev evidence 保留。

## 条目：Deep contest audit artifacts

来源文档：`docs/improvement/artifacts/16_deep_contest_audit/*`

声明 / 问题：宽范围 contest risks 与 issue list。

预期修复：合入当前 ledger。

当前证据：相关项已合并到本审计。

状态：partially superseded

优先级：P2

建议动作：继续归档；行动项以当前 ledger 为准。
