# StateBus V3 Benchmark Surface

日期：`2026-06-13`

> 2026-06-18 update: `contest_honest_headline_v1` 已冻结为 current formal headline。
> 主证据为 `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`。
> 该 artifact 已通过 API repeat=10、formal stability、object parity、S1 runtime behavior、S2 prior action、headline memory replay effect。
> 后续解释优先读取 `docs/reports/final_claim_matrix_and_freeze_20260618.md`。

## 一、正式 Pack 地图

当前 active benchmark surface 只保留 13 个 v3 对象：

| pack | 类型 | task数 | mode | 只回答什么 | 不回答什么 |
| --- | --- | ---: | --- | --- | --- |
| `contest_honest_headline_v1` | frozen formal-headline | 40 | text+protocol | text_whole_lane vs state_packet_minimal 的 contest-facing 同任务对照；API repeat=10 下证明 control compactness、typed-state handoff、S1/S2/replay runtime behavior | 不回答 external traditional pure-text baseline、open-world agent benchmark、LangGraph innovation、open Planner ability |
| `contest_dual_mode_controlled_v3` | formal-secondary controlled | 40 | text+protocol | text_strict_pure_lane vs state_packet_minimal 的内部受控 mainline handoff 对照 | 不回答 contest-facing pure-text headline |
| `memory_dual_mode_fairness_v3` | audit-only | 40 | text+protocol | text_whole_lane vs state_packet_minimal 的 dual-mode fairness/object parity | 不回答 typed-state authenticity，也不单独证明 replay |
| `typed_state_mechanism_v3` | formal-secondary | 8 | protocol-only | natural_handoff_text vs state_packet_minimal 的 protocol-only 机制真实性 | 不回答 dual-mode headline、external text baseline 或 replay |
| `external_text_baseline_audit_v3` | audit-only | 4 | text-only | 独立 external text baseline surface | 不并入 contest headline 或 typed-state mechanism |
| `text_definition_audit_v3` | formal-audit | 40 | protocol-only | inline boundary 与 whole-lane pure text 的定义分离 | 不进正式 dual-mode headline |
| `typed_state_authenticity_v3` | legacy-compat | 40 | protocol-only | 兼容旧引用的自然文本 vs minimal state packet surface | 正式机制 claim 不再优先读它 |
| `typed_state_full_rich_audit_v3` | support-only | 40 | protocol-only | full-rich audit 对象是否仍可显式恢复 | 不进 formal headline |
| `carrier_microbench_v3` | audit-only | 40 | protocol-only | minimal text/state packet 的 engineering 差异 | 不回答纯文本 vs structured 正式 headline |
| `memory_reuse_v3` | formal-secondary | 4 | protocol-only | 固定 state_packet_minimal 后 replay-aware memory reuse 是否真实减少重复工作 | 不回答 text vs protocol |
| `memory_policy_controlled_v3` | formal-secondary | 4 | protocol-only | 固定 `state_packet_minimal` 后 memory policy 单变量归因 | 不回答 text vs protocol |
| `planner_support_v3` | formal-secondary | 10 | protocol-only | yaml vs llm plan source 的独立 planner 支撑面 | 不与 medium/state claim 混读；不作为赛题主 headline |
| `typed_state_consumer_sensitivity_v3` | formal-secondary support | 40 | protocol-only | minimal `EXECUTOR_DECISION_PACKET` 是否被真实消费，且缺包/错包是否触发 destructive-control 降级 | 不升格为 typed-state 机制主 headline |

## 二、state-transfer 读法边界

- `contest_honest_headline_v1`：contest-facing formal dual-mode headline。`text` 的正式定义是 `text_whole_lane`。
- `contest_dual_mode_controlled_v3`：internal controlled composite surface。`text` 的正式定义是 `text_strict_pure_lane`，不读成赛题 pure-text headline。
- `memory_dual_mode_fairness_v3`：kept pack；只读 dual-mode fairness/object parity，不承担 replay proof。
- `typed_state_mechanism_v3`：只读 protocol-side `natural_handoff_text` vs `state_packet_minimal` 机制真实性，不读成 dual-mode headline、external text baseline 或 replay efficiency。
- `external_text_baseline_audit_v3`：只读独立 external text baseline 审计，不并入当前正式 headline。
- `text_definition_audit_v3`：只读 protocol-side `inline_text_handoff` 的 executor boundary，不读成 formal contest pure-text headline。
- `typed_state_authenticity_v3`：legacy compatibility only；正式机制 claim 优先读 `typed_state_mechanism_v3`。
- `typed_state_full_rich_audit_v3`：只读 full-rich support/audit，不读成生产默认路径。
- `carrier_microbench_v3`：只读 minimal packet engineering audit，不读成 formal benchmark headline。
- `memory_policy_controlled_v3`：只读 protocol + state_packet_minimal 固定后的 memory policy 单变量归因。
- `planner_support_v3`：只读 planner openness/support，不读成 `text vs protocol`、state-transfer 或 memory-reuse 证据。
- `typed_state_consumer_sensitivity_v3`：只读 minimal decision packet 的 consumer sensitivity / negative-control support，不与机制主 claim 混读。

## 三、当前 stopline

- `contest_honest_headline_v1` 当前已满足 contest pair coverage、whole-lane text guard、formal stability gate、S1/S2 runtime gate 和 headline memory replay effect gate。它应冻结为 current formal headline，而不是继续随意改动。
- `typed_state_mechanism_v3` 仍可作为 secondary/audit 机制真实性 surface，但 current 主线 claim 优先读取 frozen headline 的 API repeat=10 artifact。
- `contest_dual_mode_controlled_v3` 不再承担 contest-facing headline；它只保留内部 controlled composite 解释面。
- `memory_dual_mode_fairness_v3` 只有在 text restore 兼容性与 object parity gate 同时通过时才能保留 audit fairness surface。
- `carrier_microbench_v3`、`text_definition_audit_v3` 与 `external_text_baseline_audit_v3` 都不得被 aggregate 文本包装成“纯文本 vs structured”总结论。

冻结后的 stopline：

- 不把 `text_whole_lane` 说成 external traditional pure-text baseline。
- 不把 S2 replay 说成 broad long-term memory agent。
- 不把 LangGraph 说成主创新。
- 不把 Planner 说成 headline 中的开放自适应规划证明。
- 不把 protocol control bytes win 扩大成所有 token/latency/correctness 维度全面胜利。

## 四、V3 Contract

所有正式 v3 task 都显式写 case-level contract：

- `case_id`
- `case_type`
- `eval_scope`
- `expected_family`
- `primary_expected_route`
- `primary_expected_tool`
- `acceptable_routes`
- `acceptable_tools`
- `disallowed_families`
- `abstention_allowed`
- `allowed_abstain_tool`
- `abstain_only_when`

正式主表读法固定为：

- `route_exact_rate`
- `tool_exact_rate`
- `exact_match_rate`
- `admissible_match_rate`
- `abstention_rate`
- `wrong_family_rate`

`task_match_rate` 不再是正式 headline 指标。

## 五、Archive 边界

旧 benchmark pack 仍可通过显式文件路径读取，用于历史回放或归档对照：

- 不再有默认 alias
- 不再进入默认 CLI
- 不再进入正式 README
- 不再进入正式 v3 smoke / report surface
