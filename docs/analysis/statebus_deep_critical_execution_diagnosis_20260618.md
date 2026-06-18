# StateBus 深度质疑式 Review：执行前诊断

日期：2026-06-18

范围：`/home/qcrs/statebus/project`

指定环境：`/home/qcrs/statebus/conda-envs/statebus_host`

本文件是进入详细文档 A/B/C/D 之前的诊断层。它不是最终裁决，也不是问题清单逐条 FAQ；它先建立判断框架，明确哪些旧问题已经闭合，哪些深层怀疑仍然成立。

## 0. 当前必须更新的事实

本轮不能继续沿用 2026-06-18 早些时候 Goal2 文档里的旧状态作为主判断。最新 Goal3 包已经改变了事实基础：

- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_api_r10_20260618_151845/`
- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_repeat_runtime_det_r10_20260618_145812/`
- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_memory_runtime_det_r1_20260618_143231/`
- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_s2_runtime_det_r1_20260618_134109/`
- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_s1_runtime_det_r1_20260618_123323/`

使用指定 Python 读取上述 `benchmark_results.json` 后，当前事实是：

| 项 | API repeat=10 | deterministic repeat=10 |
| --- | ---: | ---: |
| `task_pack_type` | `contest_honest_headline_v1` | `contest_honest_headline_v1` |
| `repeat` | 10 | 10 |
| `withheld_headline_reason` | empty | empty |
| formal stability | pass | pass |
| object parity | pass | pass |
| text rows / protocol rows | 20 / 20 | 20 / 20 |
| complexity buckets | simple/distractor/ambiguous/reusable all covered | same |
| S1 runtime behavior | ready | ready |
| S2 prior action | ready | ready |
| headline memory replay effect | ready | ready |

关键数值：

- API repeat=10:
  - text control bytes mean: `223741.2`
  - protocol control bytes mean: `192935.2`
  - text task ms mean: `70684.29`
  - protocol task ms mean: `68850.85`
  - both modes `expectation_match_rate = 1.0`
  - S2 replay rows: `actual_replay_row_count = 100`, `skipped_step_count = 100`
- deterministic repeat=10:
  - text control bytes mean: `258874.0`
  - protocol control bytes mean: `193835.0`
  - text task ms mean: `3782.60`
  - protocol task ms mean: `3752.27`
  - both modes `expectation_match_rate = 1.0`
  - S2 replay rows: `actual_replay_row_count = 100`, `skipped_step_count = 100`

因此，旧判断中这些内容已经过时：

- `contest_honest_headline_v1` 仍然只到 repeat=1 或 repeat=3；
- current headline 仍然没有 memory/replay effect；
- S2 只是静态 prior 字段；
- 当前主问题仍是 object purity、hidden field leak、formal coverage、repeat insufficiency。

这些旧问题不能再当本轮 blocker。

## 1. 当前最强的真实主创新对象

当前最强、最能作为赛题主提交对象的创新不是 Planner，也不是 LangGraph，而是：

> `structured control plane + typed state packet + StateRef-backed handoff`

更具体地说：

- text side：`text_whole_lane`
- protocol side：`state_packet_minimal`
- protocol primary state：`DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET`
- execution substrate：LangGraph 固定图调用 Orchestrator
- benchmark object：同一 release-regression contest family 下的 paired mode rows

这条主线直接对齐赛题的低开销通信和非文本状态传递要求。它也已经在 current headline 中挂上了 S1/S2 和 replay effect，但 memory/replay 仍应被谨慎读成受控 S2 replay proof，而不是广义长期记忆 agent 已成立。

当前第二强对象是：

> `current-headline S2 prior-dependent action + validated replay`

它比旧 memory support 包更强，因为它已经进入 current headline；但它仍是受控同 family / prior case / task-commit 语境里的 replay，不应膨胀成开放世界 memory。

## 2. 已闭合、不要继续拿来阻塞的问题

### 2.1 Repeat 和 formal stability

API 与 deterministic 都有 repeat=10 包，`formal_stability_gate.passed = true`，`withheld_headline_reason = ""`。

因此，继续说 current headline “repeat 不足”已经错误。只有更开放或新 object 才需要重新 repeat。

### 2.2 Object purity / text leak

current headline 的 `object_parity_gate.passed = true`，并且：

- `text_hidden_field_leak_zero = true`
- `text_template_slot_leak_zero = true`
- `text_typed_visibility_zero = true`
- `text_memory_restore_compat_ok = true`

因此，旧的 `text_strict_pure_lane` route/tool slot leak 不能再投射到 current headline。

### 2.3 S1 runtime behavior

S1 不再只是 task schema 字段。最新 repeat 包里：

- `headline_s1_runtime_behavior_gate.s1_runtime_behavior_ready = true`
- API repeat=10 `changed_action_count = 120`
- both modes 都有 validation decision source

但它仍是固定 `retrieve -> validate -> execute -> summarize` shape 里的 validation behavior，不是开放 planner 多跳。

### 2.4 S2 prior-dependent action

S2 不再只是 `required_prior_*` 静态字段。代码里 `_headline_s2_prior_action_boundary()` 会查询 `task_commit` memory，并基于 prior case / rejected route / chosen route 改变 admissible action。最新 repeat 包：

- `headline_s2_prior_action_gate.s2_prior_action_ready = true`
- API repeat=10 `prior_dependent_action_change_count = 100`
- deterministic repeat=10 同样为 `100`

### 2.5 Current-headline memory/replay effect

current headline 已有 replay effect：

- expected reuse mode counts: `none = 30`, `skip_execute = 10`
- memory policy counts: `memory_off = 30`, `validated_replay = 10`
- both modes aggregate `skipped_step_count = 5` per repeat
- repeat=10 累计 `actual_replay_row_count = 100`

因此，不能再说 memory 只在历史 support 包里存在。

## 3. 当前最值得警惕的深层问题

### P1. `text_whole_lane` 不是 external pure-text baseline

它是 StateBus runtime 内部的 natural-language whole-lane comparator。它不直接消费 typed state refs，但仍共享：

- repo-local retrieval；
- feature/tool route machinery；
- validation gate；
- playbook executor；
- memory/replay compatible runtime。

这是一个可辩护的内部 fair comparator，不是传统外部 pure-text multi-agent framework。

### P2. Planner 在 headline 中不是主创新

headline 默认 `plan_source_default = yaml`。Planner role 存在，plan contract 明确，但在主 headline 里更像 contract compiler，而不是开放式 adaptive planner。Planner 的强弱应交给 `planner_support_v3` 或后续 secondary，不应混入 communication/state headline。

### P3. LangGraph 是真实 substrate，但不是方法对象

`runtime/langgraph_adapter.py` 使用真实 `StateGraph`，节点和条件边都存在。但每个节点主要调用 Orchestrator 的语义方法。换成简单 DAG runner 后，StateBus 的核心 claim 仍会保留：protocol、StateRef、validation、memory/replay。LangGraph 不应作为主创新点。

### P4. Benchmark 仍是 route/corpus/playbook shaped

当前 object 很诚实，但仍偏窄：

- 任务家族是 release-regression route families；
- corpus docs 带 eval labels；
- retrieval 和 tool selection 仍围绕 route/tool taxonomy；
- Executor 是 repo-local playbook registry，不是开放工具环境。

这不是 bug，但限制 claim 泛化。

### P5. Memory/replay 仍是受控 replay proof

current headline 的 memory effect 已经成立，但它证明的是：

- S2 rows 中 prior task commit 可影响 admissible action；
- validated replay 可跳过 execute；
- replay gain 在当前 controlled object 内非零。

它没有证明：

- 长期开放记忆；
- 跨开放域任务复用；
- agent 自主发现 reusable abstraction；
- hidden-state/KV 级复用。

## 4. 受控 benchmark 的自然代价，不应误判为缺陷

以下设计是为了形成可复现 contest object，不应简单批成 bug：

- 20 text + 20 protocol paired rows；
- fixed `retrieve -> validate -> execute -> summarize` plan shape；
- repo-local corpus；
- release-regression task family；
- route/tool taxonomy；
- strict gate；
- YAML plan source；
- text side 共享同一 execution engine；
- memory replay 只在 S2 reusable rows 打开。

这些代价说明当前 object 是受控主提交对象，不是开放世界 agent benchmark。

## 5. 如果不处理会继续造成叙事失真的问题

必须在后续报告和答辩里阻止以下过度叙事：

1. 把 `text_whole_lane` 叫成 external traditional pure-text baseline。
2. 把 current headline 的胜利写成 StateBus 全面优于 text。
3. 把 LangGraph 说成 StateBus 的创新核心。
4. 把 headline YAML planner 写成开放规划能力。
5. 把受控 S2 replay 写成通用长期记忆 agent。
6. 把 protocol control bytes 下降等同于所有 token/latency/任务成功维度全面领先。
7. 把 route/playbook benchmark 写成开放 agent benchmark。

## 6. 当前是否应维护主线，还是分包 / 降级 / 重构

本轮判断：

> 维护 current headline 作为受控赛题主提交对象；同时分包和降级过宽 claim。

推荐结构：

- Mainline:
  - `contest_honest_headline_v1`
  - claim: structured control + typed state handoff in a controlled contest task object
- Secondary:
  - memory replay / S2 prior-dependent action
  - planner support
  - typed-state consumer sensitivity
- Audit:
  - external pure-text baseline
  - LangGraph-native/open baseline
  - route/corpus shaping stress test

不建议：

- 推倒 StateBus 主线；
- 把 LangGraph 或 Planner 强行升级成主创新；
- 为了更像开放 benchmark 而扩大到 Docker/openEuler/nsjail/CodeAct；
- 用更多 carrier variants 掩盖核心 object 边界。

一句话：

> 当前 StateBus 已经足够作为一个受控但可辩护的 contest mainline prototype；真正需要重建的是叙事分层和下一阶段审计边界，而不是把 current headline 当成“全面系统胜利”。
