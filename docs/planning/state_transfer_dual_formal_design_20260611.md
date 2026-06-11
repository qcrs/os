# State Transfer 双正式 Benchmark 设计 2026-06-11

日期：`2026-06-11`

范围：

- 当前工作目录：`/home/qcrs/statebus/project`
- 当前 frozen formal pack：`tasks/sample_benchmark.yaml`
- 当前 redesign 草案：`docs/planning/state_transfer_benchmark_redesign_20260610.md`
- 当前关键代码锚点：
  - `runtime/task_profile.py`
  - `runtime/contracts.py`
  - `agents/sample_agents.py`
  - `runtime/executor_runtime.py`
  - `protocol/messages.py`

这份文档定义下一版正式口径，但本轮不实现、不改 YAML、不改 report 代码。

---

## 1. 设计目标

把 `state_transfer` 的 formal 读法拆成两个并列对象：

1. `typed_handoff_authenticity formal pack`
2. `pure_text_vs_state formal pack`

原则不是“为了公平削弱 state side”，而是：

- 让 `text` 真正成为 `text`
- 让 `state_ref` 保持方法真实性
- 两边共享任务、证据、工具、memory policy、成功标准
- 只改变 agent 间 handoff 机制

---

## 2. 三个 baseline 名称先冻结

后续文档、task YAML、report 表头统一只使用这三个名字：

1. `hybrid_text_brief`
2. `pure_text_handoff`
3. `state_ref_typed_handoff`

解释如下。

### 2.1 `hybrid_text_brief`

定义：

- retrieve 侧先构造 repo-native typed semantics
- 再把关键字段 stringify 成 `TOOL_ARTIFACT`
- executor 再按模板恢复结构化意图

定位：

- 它是 `structured shadow text`
- 不是 pure text baseline

### 2.2 `pure_text_handoff`

定义：

- agent 间交接对象是自然文本消息
- 不共享 repo-native typed packet
- executor 只能从文本中恢复 route / tool / action

定位：

- 它才是题目语义下的纯文本协作 baseline

### 2.3 `state_ref_typed_handoff`

定义：

- retrieve 侧保留 `StateRef` / typed state / local payload
- executor 显式消费 typed state

定位：

- 它是当前方法侧的真实性 baseline

---

## 3. 双 formal pack 各自回答什么问题

### 3.1 `typed_handoff_authenticity formal pack`

对象：

- `hybrid_text_brief`
- vs `state_ref_typed_handoff`

回答的问题：

> 在当前 repo-native runtime 里，typed handoff 是否真实存在，且是否被 executor 作为显式 typed 中间态消费？

它承担的 claim：

- `typed_handoff_authenticity`
- `mechanism reality`

它不承担的 claim：

- `pure text vs non-text state transfer`
- `low-overhead superiority headline`

### 3.2 `pure_text_vs_state formal pack`

对象：

- `pure_text_handoff`
- vs `state_ref_typed_handoff`

回答的问题：

> 在同任务、同证据、同工具、同 memory policy、同成功标准下，
> 纯文本 agent 协作与 typed state handoff 相比，
> 在 communication / end-to-end 上各自表现如何？

它承担的 claim：

- `pure_text_vs_state`
- 面向赛题主叙事的“相对纯文本协作”比较

它不承担的 claim：

- memory headline
- planner openness headline

---

## 4. `pure_text_handoff` baseline 合同

这是本设计文档最需要冻结的部分。

### 4.1 text side 允许什么

`pure_text_handoff` 允许：

1. retrieve 产出自然语言证据摘要或交接文本；
2. 交接文本可以包含：
   - query 重述
   - 证据摘要
   - 候选解释之间的自然语言比较
   - 建议的 first action
3. executor 可以从这段自然文本里恢复 route / tool / action；
4. summarize 只看到文本证据和文本执行结果。

### 4.2 text side 禁止什么

`pure_text_handoff` 明确禁止：

1. 复用 `FEATURE_BUNDLE` 字段模板后再 stringify；
2. 复用 `TOOL_CANDIDATE_SET` 结构再 stringify；
3. 把 `StateRef` 指针当作 agent 间 handoff headline；
4. 把 `EXECUTOR_DECISION_PACKET` 或等价 typed packet 作为 text 侧语义支撑；
5. 把 embedding / replay bundle / typed route packet 的内部字段直接暴露给 text baseline；
6. 用固定 key-value schema 强迫 executor 按 repo-native parser 还原同一份 typed semantics。

### 4.3 纯文本的最低自然性要求

`pure_text_handoff` 不要求“完全自由发挥”，但要求：

- 交接文本读起来像 agent 对 agent 的自然文字交接；
- 可以有简洁模板；
- 不能是 repo-native route packet 的字段镜像。

允许的模板应接近：

> 我查到的证据更支持数据库连接池耗尽，而不是 worker stall。先执行数据库等待画像工具，再确认慢查询是否与 release-17 相关。

不允许的模板应接近：

> Route: db_pool_saturation; Tool: inspect_db_waits; Route source: hint_consensus; Tool candidates: ...

---

## 5. `state_ref_typed_handoff` side 合同

为了公平，不削弱当前方法。

### 5.1 state side 保留什么

`state_ref_typed_handoff` 继续允许：

- `StateRef`
- `FEATURE_BUNDLE`
- `TOOL_CANDIDATE_SET`
- repo-local typed payload
- executor-side direct typed consumption
- protocol / local payload / structured provenance

### 5.2 state side 不需要为“对称美观”被阉割

不做下面这些事：

- 不强制删掉 `StateRef`
- 不强制把 typed semantics 改写成纯文本
- 不为了和 text 对称而把本方法降成不自然弱版本

公平的实现路径应是：

- 让 text 真正变成 text
- 不是把 state side 改成半文本

---

## 6. 双正式设计下的指标读法

后续 report 必须把四条读法分开。

1. `communication`
2. `typed_handoff_authenticity`
3. `pure_text_vs_state`
4. `memory`

### 6.1 哪些指标属于 carrier 读法

下面这些指标只能读 carrier / handoff：

- `handoff_textual_bytes`
- `handoff_nontext_bytes`
- 后续若新增：
  - `handoff_ref_wire_bytes`
  - `handoff_payload_bytes_by_kind`

这些指标回答的是：

- handoff 主要靠文本还是 typed payload
- 文本 carrier 和 non-text carrier 分别承载了多少

### 6.2 哪些指标属于 end-to-end 读法

下面这些指标只能读 end-to-end：

- `control_bytes`
- `llm_total_tokens`
- `task_ms`
- `failure_count`
- `expectation_match_rate`

这些指标回答的是：

- 完整任务闭环的代价和稳定性

不能把它们简单等同为“单一 handoff 机制成本”。

---

## 7. 对 task pack 和 report 的最低接口要求

本轮不实现，但先冻结未来接口要求。

### 7.1 task pack 最低要求

同一任务族需要支持两条 formal `state_transfer` lane：

1. `typed_handoff_authenticity`
2. `pure_text_vs_state`

同一对象族要共享：

- `goal`
- `query`
- `corpus_doc_ids`
- `evidence_text`
- `tags`
- `runtime_reuse_contract`
- success criteria

只允许变化：

- `transfer_strategy`
- 必要的 mode / report label

### 7.2 transfer strategy 最低要求

`runtime/task_profile.py` 层后续至少需要稳定支持：

- `hybrid_text_brief`
- `pure_text_handoff`
- `state_ref_typed_handoff`

实现时可以保留内部 alias，但对文档和 report 名称必须稳定。

### 7.3 report 最低要求

report 层必须：

1. 按 lane 分开出表；
2. 不把 `hybrid_text_brief` 代称为“普通文本 baseline”；
3. 显式区分：
   - `hybrid`
   - `pure_text`
   - `typed_state`
4. 对 `state_transfer` 表同时给出：
   - carrier 指标
   - end-to-end 指标
5. headline 叙述不得把 `typed_handoff_authenticity` 偷换成 `pure_text_vs_state`。

---

## 8. 实现前的对等约束

未来实现双 formal pack 时，必须同时满足下面四个约束：

1. 同任务；
2. 同 doc set；
3. 同工具；
4. 同 memory policy；
5. 同 success criteria。

额外硬约束：

- `pure_text_handoff` 侧不允许 `StateRef` / typed packet 进入 executor-facing handoff；
- `state_ref_typed_handoff` 侧不因公平而删除本方法自然优势；
- memory lane 仍单独读，不混入 state-transfer headline。

---

## 9. 本地与 upstream 参考：借什么 / 不借什么

### 9.1 `langgraph`

本地：

- `third_party/langgraph/README.md`

upstream：

- `https://github.com/langchain-ai/langgraph`

借什么：

- 显式 stateful orchestration
- 运行状态与 observability 分层

不借什么：

- 不把 orchestration framework 当作 baseline 对象

### 9.2 `langgraph-bigtool`

本地：

- `third_party/langgraph-bigtool/README.md`

upstream：

- `https://github.com/langchain-ai/langgraph-bigtool`

借什么：

- 先检索后缩小工具候选集
- 候选集作为显式中间对象

不借什么：

- 不让 text baseline 共享同一 `tool_candidates` 语义再文本化

### 9.3 `semantic-router`

本地：

- `third_party/semantic-router/README.md`

upstream：

- `https://github.com/aurelio-labs/semantic-router`

借什么：

- `Route` 作为显式对象
- route layer 与后续执行层解耦

不借什么：

- 不让 text baseline 继承同一路由对象后只换 carrier 名字

### 9.4 `evals`

本地：

- `third_party/evals/README.md`

upstream：

- `https://github.com/openai/evals`

借什么：

- benchmark contract 先行
- 一个 eval object 对应一个清晰问题

不借什么：

- 不用一个 aggregate headline 混写多个问题

### 9.5 `haystack` / `mem0`

本地：

- `third_party/haystack/docs-website/reference_versioned_docs/version-2.21/integrations-api/mem0.md`

upstream：

- `https://github.com/deepset-ai/haystack`
- `https://github.com/mem0ai/mem0`

借什么：

- retriever / writer / store 分层
- memory 以独立合同存在

不借什么：

- 不把 memory/retrieval internals 伪装成 communication 或 pure-text baseline 的一部分

---

## 10. 推荐的后续落地顺序

1. 先保留现有 `formal_controlled` 作为 `typed_handoff_authenticity` 冻结对象；
2. 再定义新的 `pure_text_vs_state` task pack；
3. 再补 report lane 与命名修正；
4. 最后才决定哪个 lane 作为对外 primary headline。

在新 rerun 前，对外最安全的口径应是：

> 当前 formal `state_transfer` headline 读作 `hybrid_text_brief vs state_ref_typed_handoff authenticity`；
> 真正的 `pure_text_vs_state` formal comparison 已在设计上冻结，待单独实现与重跑。
