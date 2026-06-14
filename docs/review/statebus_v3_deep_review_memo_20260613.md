# StateBus V3 深度 Review Memo

日期：`2026-06-13`

定位：这份文档是当前 v3 after-cutover 的主 review memo。它替代旧 `benchmark_v2_*` 规划文档承担当前判断职责。

## 1. 赛题契合度审计

已满足：

- 至少 3 个 Agent：当前主链路已有 `Planner / Retriever / Executor / Summarizer`。
- 双模式：已有 `text` 与 `protocol` 两条可运行路径。
- 结构化通信：`protocol` 路径已有结构化控制面与 `StateRef` 数据面。
- 共享记忆模块：已有 memory 存储、检索与 replay/assist 区分。

部分满足但证据弱：

- 非文本状态生成-传递-接收-使用：`state_ref` 生产与传递已成立，但 rich typed-state 的真实消费仍需机制审计，不能直接强 claim。
- 两组关联连续任务与正式赛题 headline：对象已经切到 v3 pack，但 `contest_dual_mode_controlled_v3` 目前仍是 seed pair coverage。
- 10 轮稳定性：仓库已有历史 repeat evidence，但当前 formal v3 surface 还缺专门的主测试门面承接。

当前不满足或不能正式宣称：

- 不能把当前 `contest_dual_mode_controlled_v3` 直接读成正式赛题结论。
- 不能把当前 `typed_state_authenticity_v3` 直接读成“rich typed state 已被完整真实利用”的正式结论，除非 consumer truth test 过关。

## 2. Benchmark 设计问题

- 当前最关键的旧问题是 object / claim 错配，而不是能不能跑。
- `typed_state_authenticity_v3` 的真实对象应是 `protocol_natural_handoff_text vs protocol_rich_typed_state`。
- `carrier_microbench_v3` 只应比较 `text_packet_minimal vs state_packet_minimal`，不得被包装成正式 text-vs-structured headline。
- `text_definition_audit_v3` 只应回答 executor boundary，不应回流成 whole-lane text 结论。
- `contest_dual_mode_controlled_v3` 只有在 family / query / corpus / plan source / repeat contract 都形成充分 matched pair 集后，才配得上正式赛题 headline。

## 3. 当前系统实现问题

- `state_ref` 路径当前承载的不只是单一非文本对象，而是 rich typed-state 组合：`FEATURE_BUNDLE`、`CHANNEL_SNAPSHOT`、`TOOL_CANDIDATE_SET`、`RANKED_EVIDENCE_BUNDLE`、`REPLAY_ELIGIBILITY_BUNDLE` 等。
- 这本身不是问题；问题在于这些对象是否真的被 consumer 使用，而不是只让 lane 变重。
- `natural_handoff_text` 当前是 evidence-only natural handoff，不再显式携带 route/tool 快捷字段。
- `text_packet_minimal` 则仍是有意做强的 minimal text packet；它的定位必须固定在 carrier audit，而不是自然文本公平基线。

## 4. 为什么 text 可能优于 statebus

当前证据支持三类可能性并存：

- benchmark object 更胖：rich typed-state lane 自带更多对象，天然更重。
- consumer 未真实利用 richer state：对象存在，但 executor/summarizer 未从中换来 route/tool/correctness 优势。
- text baseline 被做强：`text_packet_minimal` 是强基线，只适合 carrier audit，不适合拿来代表自然文本模式。

当前不能提前把因果归因锁死到单一来源。

## 5. 必补测试清单

- `typed_state_authenticity_v3` consumer truth test：检查 rich typed-state 是否被 executor/summarizer 真实消费。
- `state_ref consumer sensitivity`：逐类关闭 `FEATURE_BUNDLE / CHANNEL_SNAPSHOT / TOOL_CANDIDATE_SET / RANKED_EVIDENCE_BUNDLE / REPLAY_ELIGIBILITY_BUNDLE`，看 executor visibility 与 route/tool/case correctness 是否变化。
- `text baseline strength audit`：锁定 `text_packet_minimal` 的可见字段范围，并确认 `natural_handoff_text` 不含结构化捷径。
- `contest_dual_mode_controlled_v3` pair coverage gate：不足 coverage 时必须 withheld。
- formal `10-run` 连续稳定性测试：输出消息数、state transfer、memory hit、failure count。

## 6. 可说 / 必须 withheld

当前可以保留：

- 仓库已有双模式、多 Agent、结构化通信、非文本状态与共享记忆主链路。
- v3 surface 已经比旧 mixed pack 更干净，object 边界更清楚。

当前必须 withheld：

- `contest_dual_mode_controlled_v3` 的正式赛题 headline。
- `typed_state_authenticity_v3` 的正式真实性 headline，如果 rich typed-state 真实消费证据不足。
- 任何把 `carrier_microbench_v3` 或 `text_definition_audit_v3` 聚合包装成“纯文本优于/劣于结构化”的总表述。

结论：当前最诚实的状态不是“v3 已经全部证明完成”，而是“surface 已切干净，headline 继续按 stopline 受限，直到 object/consumer 根因测试补齐”。
