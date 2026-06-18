# 文档 B：Benchmark / Task / Text 定义深度审计

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

## 1. 当前 benchmark 到底在测什么

当前 `contest_honest_headline_v1` 不是开放 agent benchmark。它测的是：

> 在同一 StateBus runtime、同一 release-regression family、同一 plan shape、同一 corpus/task contract 下，`text_whole_lane` 与 `state_packet_minimal` 两种 handoff object 的差异。

这个 benchmark 主要测到三件事：

1. protocol handoff 是否比 text whole-lane 更 compact；
2. typed state packet 是否真实传递给 executor；
3. S1/S2 validation/replay gates 是否能在 current headline 中稳定执行。

它不是在测：

- 任意外部 pure-text multi-agent system；
- 开放域多跳检索；
- 开放工具环境；
- LLM Planner 自主规划能力；
- LangGraph 动态图能力。

## 2. 当前 benchmark 的强处

### 2.1 Formal object 已经干净很多

最新 Goal3 repeat=10 包显示：

- `task_set_single_variable = true`
- `task_set_variable_axes = ["mode"]`
- `object_parity_gate.passed = true`
- `contest_formal_coverage_gate.passed = true`
- `formal_stability_gate.passed = true`
- `withheld_headline_reason = ""`

这说明 current headline 已经越过旧的 object purity / repeat insufficiency 阶段。

### 2.2 Text/protocol paired rows 成立

当前任务：

- 20 text rows；
- 20 protocol rows；
- 5 families；
- 4 complexity buckets；
- same release-regression task object。

这足以作为一个 contest-facing controlled comparison。

### 2.3 S1/S2 不再只是静态标签

S1:

- `headline_s1_runtime_behavior_gate.s1_runtime_behavior_ready = true`
- API repeat=10 `changed_action_count = 120`

S2:

- `headline_s2_prior_action_gate.s2_prior_action_ready = true`
- API repeat=10 `prior_dependent_action_change_count = 100`

Memory:

- `headline_memory_replay_effect_gate.memory_replay_effect_ready = true`
- API repeat=10 `actual_replay_row_count = 100`
- API repeat=10 `skipped_step_count = 100`

这已经修正了早期“只有静态 thickness fields”的问题。

## 3. 当前 benchmark 的真实局限

### 3.1 它主要仍是 route/playbook object

当前 release-regression family 仍围绕：

- route family；
- route/tool competition；
- corpus docs；
- playbook executor；
- validation gate。

这比旧的薄 query 更强，但仍不是外部多跳任务。它更像：

> controlled incident family routing + validation + replay benchmark

而不是：

> open-ended multi-agent reasoning benchmark

### 3.2 Task thickness 是 controlled thickness

当前 S1/S2 已经有 runtime gate，但整体计划仍固定：

```text
retrieve -> validate -> execute -> summarize
```

这不是错误。它是为了稳定比较 handoff mode 的设计。但这意味着：

- S1 是 validation-driven action refinement；
- S2 是 prior-dependent action boundary / validated replay；
- 还不是 connected open multihop retrieval/execution。

### 3.3 Corpus shaping 仍存在

`tasks/local_corpus.py` 在 formal clean retrieval 下关闭 preferred doc bias、theme/group bonus 和 runtime hints，但 corpus 本身仍有：

- `eval_route_label`
- `eval_tool_label`
- family-specific evidence roles
- route/tool competition design

`runtime/executor_runtime.py` 的 tool registry 也与这些 families 对齐。

这不再是 hidden leakage 问题；它是受控 benchmark 的对象边界问题。

## 4. 当前 text 到底是什么

必须把四种 text 分开：

1. `text_strict_pure_lane`
   - 旧 internal controlled lane；
   - 明确写 Route/Tool 等字段；
   - 不应承担 current formal headline。
2. `text_whole_lane`
   - current formal headline text object；
   - natural-language whole-lane handoff；
   - 不直接给 executor typed refs；
   - guard 阻止 slot leak。
3. external traditional pure-text baseline
   - 当前不是 formal headline；
   - 只能作为 audit 或 future baseline。
4. text + same StateBus runtime comparator
   - 当前 `text_whole_lane` 实际更接近这一类。

因此当前正确读法是：

> StateBus internal natural-language whole-lane comparator vs StateBus protocol minimal typed-state packet.

错误读法是：

> external pure-text multi-agent framework vs StateBus.

## 5. Text 是否“为了公平而增强”

是，但这是受控比较的自然代价。

`text_whole_lane` 没有直接吃 typed state refs，但它仍然共享：

- same Retriever；
- same Executor tool registry；
- same validation gate；
- same summarizer；
- same memory/replay scaffolding；
- same repo-local corpus。

Executor/validate 会从 natural-language handoff 和 evidence 中恢复 route/tool feature。这让 text side 不至于被故意做弱。

判断：

- 如果目标是 internal fair comparator：当前可接受；
- 如果目标是 external pure-text baseline：当前不够。

因此，报告必须写清楚 comparator 层级，不能把 internal fairness 误写成 external realism。

## 6. 是否仍有 route/corpus shaping

有，而且应承认。

当前 shaping 不是一条隐藏字段 bug，而是对象定义：

- 任务是 release-regression incident family；
- corpus 是人工组织的 local evidence universe；
- route/tool 都是 repo-local taxonomy；
- replay 依赖 prior case / task commit / rejected route；
- validation gate 按 task contract 检查。

这使 benchmark 可复现、可对齐赛题，但也限制泛化。

## 7. Task thickness：真厚度与 contract 厚度

### 真厚度

当前已经有这些真实 runtime behavior：

- validation gate 被消费；
- S1 action 发生 refinement；
- S2 prior dependency 查询 task commit；
- S2 prior-dependent action change；
- validated replay skip execute；
- repeat=10 下稳定。

### Contract 厚度

仍然偏 contract 的地方：

- reasoning hops 是任务元数据，不等于开放 multihop graph；
- dependency depth 是 controlled prior relation，不是任意历史依赖；
- route/tool competition 是 family schema 内竞争；
- validation gate 不等于 Planner 自主发现新步骤。

结论：

> 当前 benchmark 已从 static contract 进入 controlled runtime thickness，但还不是 open connected multihop benchmark。

## 8. 当前 benchmark 是否需要改，还是冻结

本轮建议：

> 冻结 current headline 作为受控主提交对象；不要为追求开放性继续大改 current headline。

理由：

- current headline 已经 repeat=10 closed；
- object purity 和 S1/S2/replay gates 已闭合；
- 再大改会破坏一个已经可提交的 formal object；
- 更开放的 external baseline / route stress 应作为 audit 或 next-stage secondary。

但要加三个明示边界：

1. `text_whole_lane` 是 internal comparator；
2. route/corpus shaped；
3. memory replay 是 controlled S2 replay。

## 9. 缺失的消融和解释实验

这些不是 current submission blocker，但应分层：

### Submission 可不补

- LangGraph substrate on/off；
- external pure-text full baseline；
- large tool universe；
- open web/domain retrieval；
- hidden-state/KV comparison。

### Secondary 值得补

- planner-open vs yaml planner；
- validation gate on/off；
- S2 prior missing negative control；
- text recovery helper ablation；
- packet granularity ablation；
- route/corpus stress test。

### Audit 最值得补

- external pure-text baseline audit；
- same task without StateBus runtime helper path；
- new family taxonomy to test route-shaping sensitivity。

## 10. B 文档结论

当前 benchmark 是一个受控但已经闭合的 contest mainline object。它最真实地证明：

- protocol control compactness；
- typed-state packet consumption；
- controlled S1 validation behavior；
- controlled S2 prior/replay behavior。

它没有证明：

- external pure-text baseline win；
- open-world agent benchmark；
- broad memory agent；
- adaptive Planner method；
- LangGraph innovation。

建议冻结 current headline，新增审计层，而不是继续把 current headline 改到承担所有问题。
