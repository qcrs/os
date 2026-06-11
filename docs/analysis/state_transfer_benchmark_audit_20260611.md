# State Transfer Benchmark 审计报告 2026-06-11

日期：`2026-06-11`

范围：

- 当前工作目录：`/home/qcrs/statebus/project`
- 当前 frozen formal pack：`tasks/sample_benchmark.yaml`
- 当前 latest formal repeat 包：
  - `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/`
- 当前已存在的 redesign 草案：
  - `docs/planning/state_transfer_benchmark_redesign_20260610.md`

这份文档只做审计，不改代码，不重跑 benchmark，不改 task YAML。

---

## 1. 审计结论先说

当前 `formal_controlled` pack 里的 `state_transfer` lane 不是作弊，也不是无效。

它当前真实测到的是：

- `hybrid_text_brief`
- vs `state_ref_typed_handoff`

它没有测到的是：

- `pure_text_handoff`
- vs `state_ref_typed_handoff`

所以当前最诚实的结论是三层：

1. 当前 benchmark **公平地比较了同一 protocol runtime 里的两种 executor handoff**。
2. 当前 benchmark **没有提供“纯文本 agent 协作” baseline**。
3. 当前 `state_transfer` lane 主要支撑 **typed-handoff authenticity**，不足以独自承担“普通文本 vs 非文本状态传递”的总 headline。

---

## 2. 当前 text mode 到底传了什么

先把对象链说清楚。

### 2.1 formal pack 的 state-transfer 任务合同

在 `tasks/sample_benchmark.yaml` 里，`transfer_lane` 的任务都写成：

- `benchmark_lane: state_transfer`
- `transfer_strategy: mode_split_text_brief_vs_state_ref`
- `runtime_reuse_contract: reuse_disabled`

对应 `runtime/task_profile.py` 的行为是：

- `text` mode 解析为 `text_brief`
- `protocol` mode 解析为 `state_ref`

所以 frozen formal pack 当前的 headline 读法，本质上是：

- `text / hybrid_text_brief`
- vs `protocol / state_ref_typed_handoff`

而不是：

- `text / pure_text_handoff`
- vs `protocol / state_ref_typed_handoff`

### 2.2 retrieve 阶段实际生成了什么

`agents/sample_agents.py` 的 `RetrieverAgent` 当前会先构造 repo-native 中间态：

- `DENSE_EVIDENCE`
- `FEATURE_BUNDLE`
- `TOOL_CANDIDATE_SET`
- `RANKED_EVIDENCE_BUNDLE`
- `REPLAY_ELIGIBILITY_BUNDLE`

其中真正和 executor 选择最相关的是：

- `FEATURE_BUNDLE`
- `TOOL_CANDIDATE_SET`

这两个对象已经带有明确的 route / tool / candidate / provenance 语义。

### 2.3 text 侧当前不是自然语言 handoff

当 `transfer_strategy == "text_brief"` 时，`agents/sample_agents.py` 会把上面的结构化特征重新拼成一个 `TOOL_ARTIFACT` 文本 brief，内容包括：

- `Suggested route`
- `Suggested tool`
- `Route source`
- `Route confidence`
- `Route provenance`
- `Matched signals`
- `Matched tags`
- `Match score`
- `Hint docs`
- `Hint route`
- `Hint tool`
- `Tool candidates`

然后 `runtime/executor_runtime.py` 又会把这段 brief 重新解析回 feature-like bundle。

因此当前 text 侧传的不是“另一位 agent 自由写出的自然语言交接”，而是：

> repo-native structured packet 的 textual shadow

### 2.4 summarize 阶段也不是“只看纯文本世界”

`SummarizerAgent` 在非 text mode 下还会基于 retrieve / execute 结果构造 `_build_protocol_summary_handoff(...)` 的摘要输入。

这意味着当前 `llm_total_tokens` 和 `task_ms` 读数，不只是 executor 输入格式的函数，还混入了 summarize 侧上下文塑形。

---

## 3. 当前 benchmark 哪里公平

对下面这个问题，当前 lane 是公平的：

> 在同任务、同 corpus、同工具、同 memory-off、同 runtime 下，
> 将 retrieve 侧结构化选择结果用文本 brief 交给 executor，
> 和直接用 typed `StateRef` 交给 executor，
> 哪种更接近当前 repo 的真实 handoff 机制？

公平点有四个：

1. 同任务：
   `transfer-cache-001`、`transfer-latency-001`、`transfer-session-001` 共三组对象在两边共享。
2. 同证据：
   `corpus_doc_ids`、`evidence_text` 合同一致。
3. 同工具与同 route 选择逻辑：
   两边都先经过同一套 repo-local retrieve / feature construction。
4. 同 memory policy：
   `runtime_reuse_contract: reuse_disabled`，不让 replay/memory 进入这个 lane。

因此它不是“故意给 text 挖坑”的不公平比较。

---

## 4. 当前 benchmark 哪里不公平

### 4.1 headline 对象不公平：text baseline 不是真正的 pure text

当前 `text_brief` baseline 继承了我们自己的结构化语义：

- 先有 `FEATURE_BUNDLE`
- 再有 `TOOL_CANDIDATE_SET`
- 然后 stringify
- executor 再按模板 parse 回来

这不是题目要求里的“纯文本协作模式”，因为 text 侧并没有真的只靠自然语言交接去恢复 route / tool / action。

### 4.2 读法不公平：carrier 指标与 end-to-end 指标被混读

当前 `benchmark_report.md` 里的 `Protocol-Only State-Transfer Handoff Delta` 表混合了两类指标：

- carrier / executor-facing：
  - `handoff_textual_bytes`
  - `handoff_nontext_bytes`
- end-to-end：
  - `llm_total_tokens`
  - `task_ms`

前者可以读成 handoff 载体差异。
后者不能直接读成“仅由 handoff 机制造成的净成本”。

### 4.3 state side 的 rich payload 包含了不该被 headline 混读的内容

当前 `state_ref` 侧除了 executor 主要消费的 `FEATURE_BUNDLE` 和 `TOOL_CANDIDATE_SET`，还伴随：

- `RANKED_EVIDENCE_BUNDLE`
- `REPLAY_ELIGIBILITY_BUNDLE`
- `EMBEDDING`

其中一部分对象是 runtime 内部真实性的合理组成部分，但它们不是“纯粹 state-transfer carrier”的唯一等价物。

所以当前结果可以证明：

- rich typed handoff 真实存在

但不应顺手外推成：

- rich typed handoff 已经在所有任务上是更低开销的 carrier

---

## 5. 当前 repeat=3 formal 包到底说明了什么

来自 `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/benchmark_report.md` 的 protocol-only state-transfer 表：

| handoff_strategy | control_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| `text_brief` | 4784.11 | 1803.33 | 0.00 | 698.67 | 3578.97 |
| `state_ref` | 5753.44 | 751.00 | 2992.33 | 751.00 | 3643.96 |
| `delta(state_ref - text_brief)` | 969.33 | -1052.33 | 2992.33 | 52.33 | 64.99 |

这组数最稳妥的读法是：

1. `state_ref` 的确显著减少了 textual handoff。
2. `state_ref` 同时引入了更大的 typed / non-text payload。
3. 在这组三任务上，`state_ref` 没有形成稳定的 token / time 优势。
4. 所以当前 formal lane 更像 **mechanism-true authenticity evidence**，而不是 **efficiency win evidence**。

---

## 6. 当前 claim surface 还能保留什么

### 6.1 `communication`

可以继续作为 headline。

原因：

- 当前 communication lane 读法已经与 `state_transfer`、`memory` 分开；
- 它回答的是控制面/协作通信的总体节省；
- 不依赖把 `text_brief` 误称为纯文本 baseline。

### 6.2 `state_transfer / hybrid`

可以保留，但要改口径。

当前能保留的是：

- `hybrid_text_brief vs state_ref_typed_handoff authenticity`

当前不能直接保留的是：

- `pure text vs non-text state transfer superiority`

### 6.3 `state_transfer / low-overhead`

当前不能只靠 frozen formal pack 直接成立。

原因：

- `state_ref` 在 protocol-only lane 上没有稳定胜出；
- `text_brief` 不是 pure text baseline；
- carrier 与 end-to-end 指标被混在一起读容易误导。

### 6.4 `memory`

仍然只到：

- `replay_enabled`
- `step-skipping`

不能把 `assist_only` 包装成强 headline。

---

## 7. 为什么原 formal pack 仍应保留

原 formal pack 不该废弃，理由有三点。

### 7.1 它保留了当前方法的真实性对象

当前 repo 的方法本来就不是“只传一段自然文本”。

它真实的方法链包含：

- explicit route choice
- candidate narrowing
- typed state handoff
- executor-side structured consumption

`formal_controlled` pack 里的 `text_brief vs state_ref` 正好把这个真实性对象固定住了。

### 7.2 它已经形成可复读的 frozen artifact

当前 headline artifact 已经明确冻结到：

- `tasks/sample_benchmark.yaml`
- `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/benchmark_report.md`

在没有新 formal rerun 之前，直接废弃它只会让 claim surface 更漂。

### 7.3 它回答的是“typed handoff 是否真实存在”

这仍然是赛题要求的一部分，而且是当前 repo 的强项之一。

该做的不是撤掉它，而是：

- 降级它的 headline 范围
- 明确它是 `typed_handoff_authenticity formal pack`
- 另起一个并列的 `pure_text_vs_state` 正式对象

---

## 8. 与本地第三方参考的设计边界

### 8.1 `langgraph` / upstream `langchain-ai/langgraph`

可借：

- 显式 stateful orchestration
- durable execution / observability 分层

不可借：

- 把 orchestration framework 本身当作我们的 text baseline

### 8.2 `langgraph-bigtool` / upstream `langchain-ai/langgraph-bigtool`

可借：

- 先缩小 candidate set，再绑定下游工具
- “候选集”作为显式中间对象

不可借：

- 让 text baseline 共享同一候选包再简单转成字符串，然后还宣称它是 pure text

### 8.3 `semantic-router` / upstream `aurelio-labs/semantic-router`

可借：

- route object 显式化
- route layer 与后续执行层分离

不可借：

- 让两边共享同一路由对象语义后，再把其中一边命名成“普通文本”

### 8.4 `evals`

可借：

- benchmark contract 要先定义任务和评测读法
- 不同 eval object 要分开，不用一个 aggregate 替代所有问题

不可借：

- 用一个混合 aggregate headline 代替 lane-specific 解读

### 8.5 `haystack + mem0`

可借：

- retrieval / memory store / writer / retriever 的分层合同
- memory 不应伪装成 communication baseline

不可借：

- 把 memory/retrieval internals 混入 state-transfer headline，导致对象不清

---

## 9. 最终审计判断

当前 benchmark 的问题不是“造假”，而是“headline 命名过宽”。

最简洁的审计结论如下：

1. 当前 text mode 在 `state_transfer` lane 里传的是 `hybrid_text_brief`，不是 `pure_text_handoff`。
2. 当前 benchmark 在 lane 内部是公平的，但 headline 对象不是纯文本协作。
3. 当前 `state_transfer` 结果继续有效，但有效对象应收紧为：
   `typed_handoff_authenticity`
4. 当前 `communication` claim 仍可继续 headline。
5. 当前 `memory` claim 仍只到 `replay_enabled / step-skipping`。
6. 下一步不是推翻原 formal pack，而是并列新增一个真正的 `pure_text_vs_state` formal 设计对象。
