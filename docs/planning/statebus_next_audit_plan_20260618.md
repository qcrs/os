# StateBus Next Audit Plan After Headline Freeze

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

本文档是 `contest_honest_headline_v1` 冻结之后的下一批工作计划。它不是继续修改 current formal headline 的授权。

## 0. Two-Batch Split

Batch 1 已完成目标：

- freeze current formal headline evidence；
- write claim matrix；
- update final report/talk-track entry；
- mark old Goal2 current-state claims as superseded where necessary。

Batch 2 只做 audit / secondary，不改 frozen headline：

- external pure-text baseline；
- text helper ablation；
- route/corpus stress；
- S2 negative control；
- planner-open secondary；
- optional LangGraph-native/open comparison。

## 1. Global Audit Rules

所有 audit 必须遵守：

- 不改 `contest_honest_headline_v1` frozen task contract。
- 不把 audit result 直接并入 current formal headline。
- 每轮只选一个主变量。
- 先 deterministic / targeted test，再考虑 API。
- 同一 audit 没有新假设，不重复跑 benchmark。
- 真实 API 最多先 repeat=1 或 repeat=3；除非 audit 已经 clean 且需要 formal secondary，才考虑 repeat=10。
- 所有 run 必须新建 `--out` 目录，不覆盖 frozen artifacts。
- 不做 Docker、openEuler VM、nsjail、strong sandbox、hidden-state/KV、交付打包。

## 2. Recommended Order

推荐顺序：

1. S2 negative control audit
2. text helper ablation
3. external pure-text baseline audit
4. route/corpus stress
5. planner-open secondary
6. LangGraph-native/open comparison only if needed for report Q&A

理由：

- S2 negative control 最小、最直接保护 current memory/replay claim。
- text helper ablation 先回答内部 text comparator 是否依赖 StateBus helper path。
- external pure-text baseline 工程差异较大，应在 text helper 边界清楚后做。
- route/corpus stress 会动任务对象，应放在 headline freeze 之后作为独立 audit。
- planner-open 和 LangGraph-native 都不是主创新，只做 secondary/support。

## 3. Audit A: S2 Negative Control

核心问题：

> current-headline S2 replay 是否真的依赖 prior case / prior route / prior rejection，而不是硬标签 shortcut？

主变量：

- prior dependency validity。

建议对象：

- 新建 audit-only task rows 或 targeted tests；
- 不修改 frozen `contest_honest_headline_v1` rows。

必须覆盖：

- missing prior case；
- wrong prior route；
- missing required rejection；
- wrong rejected route；
- replay-compatible artifact absent；
- prior exists but task family mismatch。

通过标准：

- prior invalid 时 admissible action 不应升级到 validated tool；
- replay 不应触发；
- expected fallback 应是 collect_more_evidence 或 gate block；
- positive S2 row 仍然可通过。

产出：

- audit doc；
- targeted pytest；
- deterministic artifact if runner support is needed；
- can/cannot claim update。

## 4. Audit B: Text Helper Ablation

核心问题：

> `text_whole_lane` 的表现有多少来自 natural-language handoff，本身有多少来自同一 StateBus runtime 的 route/tool recovery helper？

主变量：

- text route/tool recovery helper on/off。

建议对象：

- audit-only path；
- 对 text side 禁用或收窄 executor/validate 的 route/tool feature recovery；
- protocol side 不变；
- 不改 current formal headline。

必须回答：

- 禁用 helper 后 text 是否仍能恢复 route/tool；
- correctness 是否明显下降；
- protocol compactness 是否仍成立；
- 当前 `text_whole_lane` 应被读成 internal comparator 还是更接近 external text。

通过标准：

- 不是要求 text 一定失败；
- 要求 artifact 能显示 helper 对结果的实际影响；
- 若 text 大幅下降，报告必须更强地标注 `text_whole_lane` 是 runtime-assisted internal comparator。

## 5. Audit C: External Pure-Text Baseline

核心问题：

> 如果不用 StateBus runtime helper path，一个更传统的 pure-text multi-agent baseline 与 current internal text comparator 的距离有多大？

主变量：

- runtime helper availability / external baseline object。

建议对象：

- 新建 `external_pure_text_baseline_audit_*`；
- text-only；
- 不消费 StateRef；
- 不消费 typed packets；
- 不读取 hidden route/tool slots；
- 不使用 StateBus executor 的 structured decision helper 作为恢复捷径。

建议先做小样本：

- 1 到 2 个 family；
- simple + ambiguous + reusable 各一类；
- deterministic repeat=1；
- 若 clean，再 API repeat=1 或 repeat=3。

通过标准：

- 能明确说明 external baseline 与 `text_whole_lane` 的关系；
- 能解释当前 headline 为什么不把 external baseline 当正式对照；
- 不要求 external baseline 一定弱，也不允许为了赢而刻意做差。

可能结果：

- external baseline 接近 internal text：增强报告说服力；
- external baseline 明显弱：说明 current internal comparator 是更公平但更受控的 baseline；
- external baseline 难以稳定定义：说明赛题 baseline 本身不清楚，必须作为 audit-only。

## 6. Audit D: Route / Corpus Stress

核心问题：

> 当前优势是否依赖 release-regression family、route labels、tool taxonomy 和 local corpus shaping？

主变量：

- corpus/task taxonomy stress。

可做 stress：

- 替换 distractor corpus；
- 隐去或扰动 route-aligned wording；
- 增加相邻 family 混淆；
- 换一个小 family taxonomy；
- 保持 expected answer contract 不变，改变 evidence surface。

通过标准：

- protocol/text 两侧都不应依赖 hidden label；
- route/tool accuracy 下降时要能定位是 retrieval、validation、executor 还是 task ambiguity；
- 不把 stress 结果反向覆盖 current headline。

## 7. Audit E: Planner-Open Secondary

核心问题：

> Planner 在当前系统里是否只是 role/contract compiler，还是能在 secondary surface 中提供开放 planning 价值？

主变量：

- `plan_source`: yaml vs llm。

建议对象：

- `planner_support_v3` 或新 secondary pack；
- protocol-only first；
- 不混入 text-vs-protocol headline；
- 不把 planner-open 结果写成 mainline win。

必须回答：

- LLM planner 是否生成不同 semantic roles；
- validate-first 任务是否被严格保留；
- 计划差异是否改善 correctness、steps、tokens 或 failure recovery；
- planner failure 是否可被 parser/gate 拦住。

通过标准：

- 至少有 paired yaml/llm rows；
- row-level plan differences 可解释；
- failures 不污染 current headline。

## 8. Audit F: LangGraph-Native / Open Comparison

核心问题：

> LangGraph 在当前系统中是 substrate；如果做 LangGraph-native/open comparison，它到底能回答什么？

建议定位：

- Q&A / support audit only；
- 不作为 current headline；
- 不用它替代 StateBus mainline。

可比较：

- StateBusGraphRunner fixed graph；
- LangGraph-native text/tool routing baseline；
- same task subset；
- same model budget where practical。

必须边界：

- 如果 LangGraph-native 表现好，只说明 orchestration baseline strong；
- 如果 StateBus 表现好，也不能说 LangGraph 本身弱；
- 该 audit 只用于说明 StateBus 的创新不等于 LangGraph。

## 9. Stop Conditions

任一 audit 遇到以下情况应停止：

- 需要改变 frozen headline 才能继续；
- 需要 Docker/openEuler/nsjail/strong sandbox 才能回答；
- 无法定义 single variable；
- 三轮仍无法产生可解释 artifact；
- API cost/latency 被用来替代 object clarity；
- 发现 audit object 不可公平定义。

## 10. Deliverable Template For Each Audit

每个 audit 完成后必须交付：

- audit objective；
- single variable；
- why it does not mutate frozen headline；
- code/test changes if any；
- artifact path；
- row-level evidence summary；
- what can now be claimed；
- what still cannot be claimed；
- whether the audit should be promoted, repeated, or stopped。

