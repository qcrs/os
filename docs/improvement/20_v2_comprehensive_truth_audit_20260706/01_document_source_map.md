# 文档 Source Map

本文件把文档当作证据线索，而不是事实本身。所有 claim 都回到源码、测试、git history 和 fresh benchmark JSON 做交叉验证。

## 当前 source-of-truth 集合

| 文档 | 状态 | 处理结论 |
|---|---|---|
| `README.md` | 当前 orientation | repo overview 有效，但不能单独作为 claim 证据。 |
| `docs/constraints/current_host_and_migration.md` | 当前约束 | v1 host posture 与 v2 exception path 必须分开。 |
| `docs/constraints/current_feature_scope.md` | 当前约束 | 用于功能边界和 planned-vs-real 语言。 |
| `docs/planning/implementation_plan.md` | 当前 planning context | 可作为实现计划，不是 v2 完成证明。 |
| `docs/reference/题目.md` | 当前竞赛参考 | 用于 contest objective framing。 |
| `docs/improvement/README.md` | 当前 improvement 入口 | 指向仍保留的 truth audit、local+api 深挖和下一步修复顺序。 |
| `docs/improvement/20_v2_comprehensive_truth_audit_20260706/00_executive_summary.md` | 当前 safe-claim 入口 | 本轮审计后的 claim 边界入口。 |
| `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_163354/` | 当前 full `RUN_FLAGSHIP=1` passing local+api comprehensive artifact | 13 stages clean、formal internal 25/25、formal compare 8-case strict equal-quality、continuous replay、replay negative、flagship stage exit 0 和 diagnostics bundle 的最新证据；flagship stress 为 3/6，不是 all-pass。 |
| `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260707_091807/` | 历史 passing local+api comprehensive core artifact | required stages clean，但 flagship 显式关闭。 |
| `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_20260706_191835/deep_dive_analysis_and_fix_plan_zh.md` | historical local+api 深挖 | formal compare gate、8-case scope、external metric schema 的问题定位。 |

## Claim-upgrade 相关文档

| 文档 | 状态 | 证据和动作 |
|---|---|---|
| `docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md` | 历史 execution prompt，已从 active docs tree 清理 | 只作为 git 历史中的意图线索，不是证明。 |
| `docs/improvement/18_claim_upgrade_execution_plan.md` | 历史计划，已从 active docs tree 清理 | 25-case registry、formal families、state-pool mode、memfd telemetry 已实现；未完成项已并入当前 issue ledger。 |
| `docs/improvement/17_final_system_audit_20260706.md` | 历史 audit baseline，已从 active docs tree 清理 | 部分发现已修复；未解决项已合并进 `05_merged_issue_ledger.md`。 |
| `docs/improvement/19_claim_upgrade_completion_report_20260706.md` | 历史 completion report，已从 active docs tree 清理 | internal formal 和 memfd claims 的有效结论由本审计与 fresh artifacts 接管。 |
| `docs/improvement/PROMPT_FOR_V2_COMPREHENSIVE_TRUTH_AUDIT.md` | 历史 audit prompt，已从 active docs tree 清理 | 只作为 git 历史中的执行要求线索。 |

## 证据 Artifact 目录

| 目录 / 文件组 | 状态 | 处理结论 |
|---|---|---|
| `docs/improvement/artifacts/15_fairness_gate_propagation/*` | 历史 artifacts，已从 active docs tree 清理 | fairness gate propagation 是真实代码工作，但当前 evidence 入口由本审计和 retained JSON 接管。 |
| `docs/improvement/artifacts/16_deep_contest_audit/*` | 历史 issue source，已从 active docs tree 清理 | unresolved risk tracking 已并入 `05_merged_issue_ledger.md`。 |
| `docs/improvement/artifacts/17_final_system_audit/17a_evidence_table.md` | 历史 before-state table，已从 active docs tree 清理 | 早于 claim-upgrade implementation；需要追溯时从 git 历史读取。 |
| `17b_code_review_findings.md` | 部分过时 | 多个 finding 已由 `e20b8e9` 和 `3738f34` 修复；剩余问题合并到本审计。 |
| `17c_benchmark_json_analysis.md` | 部分过时 | 本目录 fresh artifacts 替代旧 internal formal 字段。external API gap 仍存在。 |
| `17d_issue_ledger.md` | 部分解决 | issue IDs 已在 `05_merged_issue_ledger.md` 合并去重。 |
| `17e_remediation_plan.md` | 部分实现 | 重要：它要求 `answer_restoration_replay_count=0`；本审计修复了代码/测试不一致。 |
| `17f_safe_claim_language.md` | 历史 safe language | 有用边界已迁移到当前 truth audit 与 issue ledger。 |
| `17_final_system_audit/worklog.md` | 历史 worklog | 只作 trace，不作最终 source of truth。 |

## 更早 improvement docs

`01_p0_critical_fixes.md` 到 `19_claim_upgrade_completion_report_20260706.md` 是历史实现和验证记录。它们已经从 active docs tree 清理，避免继续影响当前判断；需要追溯时从 git 历史读取。当它们涉及以下内容时，应由 newer docs 和 fresh benchmark artifacts 覆盖：

- CodeAct LLM generation stability。
- external superiority。
- speed advantage。
- openEuler compatibility。
- broad replay 或 answer-restoration claims。

## 本地 worktree 说明

本轮审计开始前，worktree 曾有：

- `M docs/improvement/PROMPT_FOR_CLAIM_UPGRADE_EXECUTION.md`
- `?? docs/improvement/PROMPT_FOR_V2_COMPREHENSIVE_TRUTH_AUDIT.md`

这些文件在后续文档整理中已从 active docs tree 清理，不再作为当前阅读入口。
