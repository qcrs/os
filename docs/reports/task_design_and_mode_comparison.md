# StateBus V3 Benchmark Surface

日期：`2026-06-13`

## 一、正式 Pack 地图

当前正式 benchmark surface 只保留 11 个 v3 对象：

| pack | 类型 | task数 | mode | 只回答什么 | 不回答什么 |
| --- | --- | ---: | --- | --- | --- |
| `contest_dual_mode_controlled_v3` | formal-headline | 40 | text+protocol | text_strict_pure_lane vs state_packet_minimal 的同任务对照 | 不回答 inline boundary 或 carrier microbench；当前 coverage 仍不足时必须 withheld |
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

## 二、state-transfer 读法边界

- `contest_dual_mode_controlled_v3`：formal dual-mode headline。`text` 的正式定义是 `text_strict_pure_lane`。
- `memory_dual_mode_fairness_v3`：kept pack；只读 dual-mode fairness/object parity，不承担 replay proof。
- `typed_state_mechanism_v3`：只读 protocol-side `natural_handoff_text` vs `state_packet_minimal` 机制真实性，不读成 dual-mode headline、external text baseline 或 replay。
- `external_text_baseline_audit_v3`：只读独立 external text baseline 审计，不并入当前正式 headline。
- `text_definition_audit_v3`：只读 protocol-side `inline_text_handoff` 的 executor boundary，不读成 formal contest pure-text headline。
- `typed_state_authenticity_v3`：legacy compatibility only；正式机制 claim 优先读 `typed_state_mechanism_v3`。
- `typed_state_full_rich_audit_v3`：只读 full-rich support/audit，不读成生产默认路径。
- `carrier_microbench_v3`：只读 minimal packet engineering audit，不读成 formal benchmark headline。
- `memory_policy_controlled_v3`：只读 protocol + state_packet_minimal 固定后的 memory policy 单变量归因。
- `planner_support_v3`：只读 planner openness/support，不读成 `text vs protocol`、state-transfer 或 memory-reuse 证据。

## 三、当前 stopline

- formal v3 surface 已切干净，但机制真实性仍在审计中。
- `typed_state_mechanism_v3` 只有在 `state_packet_minimal` 的 `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` 被 executor 真实消费且未出现非预期 kind 时才能保留机制真实性结论。
- `contest_dual_mode_controlled_v3` 只有在 contest pair coverage 不再只是 seed pack 时才能保留正式赛题 headline。
- `memory_dual_mode_fairness_v3` 只有在 text restore 兼容性与 object parity gate 同时通过时才能保留 audit fairness surface。
- `carrier_microbench_v3`、`text_definition_audit_v3` 与 `external_text_baseline_audit_v3` 都不得被 aggregate 文本包装成“纯文本 vs structured”总结论。

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
