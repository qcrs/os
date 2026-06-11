# State Transfer Benchmark Redesign 2026-06-10

日期：`2026-06-10`

范围：

- 当前工作目录：`/home/qcrs/statebus/project`
- 当前 formal pack：`tasks/sample_benchmark.yaml`
- 当前最新 formal repeat 包：
  - `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/`

这份文档回答三个问题：

1. 当前 `state_transfer` benchmark 到底哪里不公平
2. 它对什么 claim 仍然有效
3. 下一版 benchmark 应该如何重设计

它不讨论：

- Docker / openEuler / VM 部署
- Planner 自由度扩张
- broad assist headline

---

## 1. 当前结论

当前 `state_transfer lane` 不是完全失效，而是 **比较对象选错了**。

它现在测到的不是：

- `natural text handoff`
- vs `typed non-text state handoff`

而更接近：

- `textualized typed packet`
- vs `typed non-text state handoff`

因此：

- 它可以支持 `typed non-text handoff is real` 这类真实性 claim
- 它不能直接支持 `structured non-text is cheaper than normal text handoff` 这类优越性 claim

---

## 2. 当前 formal benchmark 实际怎么比

当前 `state_transfer` lane 已经完成了一轮重要修正：

- 固定 `mode = protocol`
- 固定 `memory_policy = memory_off`
- 固定任务
- 只改 `transfer_strategy = text_brief vs state_ref`

对应文件：

- `tasks/sample_benchmark.yaml`
- `eval/runner.py`
- `runtime/contracts.py`

读者合同本身没有问题，问题在 baseline 语义。

### 2.1 executor 输入合同

当前 executor 输入合同是：

- `state_ref`
  - `DENSE_EVIDENCE`
  - `FEATURE_BUNDLE`
  - `TOOL_CANDIDATE_SET`
- `text_brief`
  - `DENSE_EVIDENCE`
  - `TOOL_ARTIFACT`

也就是说，`state_ref` 走的是显式 typed state，
而 `text_brief` 走的是文本中间包。

### 2.2 但 `text_brief` 不是自然文本

`text_brief` 不是“另一个 agent 自由写出来的自然语言摘要”，而是从同一个
`feature_bundle` 中把关键字段拼成字符串：

- `route`
- `tool_name`
- `route_source`
- `route_confidence`
- `route_provenance`
- `matched_signals`
- `matched_tags`
- `match_score`
- `hint_doc_ids`
- `hint_route`
- `hint_tool_name`
- `tool_candidates`
- `memory_assist_ids`
- `evidence_preview`

然后 executor 又把这段 brief 重新解析回一个 feature-like bundle。

因此当前 baseline 本质上是：

- **把我们自己的结构化 packet 先 stringify**
- **再 parse 回来**

它不是中立的自然文本 baseline。

---

## 3. 当前 repeat 包实际说明了什么

当前最新 formal repeat 包：

- `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/benchmark_report.md`

协议内 `state_transfer` 专用表显示：

- `text_brief`
  - `control_bytes = 4784.11`
  - `handoff_textual_bytes = 1803.33`
  - `handoff_nontext_bytes = 0`
  - `llm_total_tokens = 698.67`
  - `task_ms = 3578.97`
- `state_ref`
  - `control_bytes = 5753.44`
  - `handoff_textual_bytes = 751.00`
  - `handoff_nontext_bytes = 2992.33`
  - `llm_total_tokens = 751.00`
  - `task_ms = 3643.96`

这说明：

1. `state_ref` 确实减少了 textual handoff
2. `state_ref` 同时引入了更大的 non-text payload
3. 当前 rich `state_ref` 没有在端到端 token / time 上稳定胜出

把三组成对任务拆开看，问题更具体：

- `cache` pair：`state_ref` 更好
- `latency` pair：`state_ref` 略好
- `session` pair：`state_ref` 明显更差

也就是说，当前平均劣势不是 executor 普遍失败，而是：

- rich payload 固定成本
- 某些任务上的下游 summarization 代价

共同造成的。

---

## 4. 当前 benchmark 到底哪里不公平

### 4.1 公平的部分

对下面这个问题，它是公平的：

> 在 protocol mode、同任务、同 memory policy 下，
> `text-encoded packet` 和 `typed state packet`
> 哪种 executor handoff 更适合当前 runtime？

因为它已经固定了：

- 同任务
- 同模式
- 同工具
- 同 memory policy
- lane 内只改 handoff strategy

### 4.2 不公平的部分

对下面这个问题，它不够公平：

> 结构化非文本 handoff 是否优于普通文本 agent 协作？

因为当前 `text_brief` baseline 已经吃到了我们自己的结构化设计红利：

- 先用 `feature_bundle` 做 route/tool/candidate 选择
- 再把这些字段序列化成固定模板文本
- executor 再按同一模板反解析回来

这不是“text agent baseline”，而是“structured packet 的 textual shadow”。

### 4.3 第二层不公平：端到端指标混入 summarize 差异

`handoff_textual_bytes` / `handoff_nontext_bytes` 是 executor-facing 指标，
这一点没有问题。

但 `llm_total_tokens` / `task_ms` 是 task-level 端到端指标。

当前 `state_ref` 与 `text_brief` 不仅影响 executor 输入，
还会通过 retrieve-side available refs 改变 summarize 侧可见上下文。

因此当前表里：

- `handoff_*`
  - 可以读成 executor handoff 指标
- `llm_total_tokens`
  - 不能读成纯 executor 成本
- `task_ms`
  - 不能读成纯 executor latency

---

## 5. 从相关仓库应该借什么，不该借什么

### 5.1 `langgraph`

本地参考：

- `third_party/langgraph/README.md`

upstream：

- `https://github.com/langchain-ai/langgraph`

值得借：

- stateful orchestration 的显式状态流
- durable execution / observability 的分层思路

不该借：

- 把 LangGraph 本身当作我们 benchmark 的 baseline runtime

因为它是 orchestration framework，不是这题要验证的数据面机制。

### 5.2 `langgraph-bigtool`

本地参考：

- `third_party/langgraph-bigtool/README.md`
- `third_party/langgraph-bigtool/langgraph_bigtool/graph.py`
- `third_party/langgraph-bigtool/langgraph_bigtool/tools.py`

upstream：

- `https://github.com/langchain-ai/langgraph-bigtool`

值得借：

- small candidate set first
- retrieve first, bind narrowed tools later
- 把“候选集”作为显式中间对象，而不是全量工具列表

不该借：

- 把 tool retrieval 本身写成 benchmark headline

### 5.3 `semantic-router`

本地参考：

- `third_party/semantic-router/README.md`

upstream：

- `https://github.com/aurelio-labs/semantic-router`

值得借：

- route object 的显式化
- threshold / abstain / no-match discipline

不该借：

- 用 semantic routing 替换当前 benchmark 对照对象

### 5.4 `MetaGPT`

upstream：

- `https://github.com/FoundationAgents/MetaGPT`

值得借：

- role / environment 分离
- role message passing 作为明确 runtime object

不该借：

- 把 SOP-style role prompt 当成本题 `text baseline`

### 5.5 `AutoGen`

upstream：

- `https://github.com/microsoft/autogen`

值得借：

- agent interaction trajectory 的可追踪性
- benchmark 时区分 conversation artifact 与 task success

不该借：

- 把多 agent chat transcript 直接当作公平文本对照

### 5.6 `CAMEL`

upstream：

- `https://github.com/camel-ai/camel`

值得借：

- agent society / message-driven 组织方式

不该借：

- 用长对话风格 baseline 去替代受控 benchmark baseline

### 5.7 `AgentBench` / `AutoGenBench` / `Tau-Bench`

upstream：

- `https://github.com/THUDM/AgentBench`
- `https://github.com/microsoft/autogenbench`
- `https://github.com/sierra-research/tau-bench`

真正值得借的是 benchmark discipline：

- blank-slate rerun
- 明确初始条件
- 区分 success metric 和 process metric
- 不把 richer scaffolding baseline 伪装成通用 baseline

---

## 6. 新 benchmark 设计：改成三层 state-transfer claim

下一版 `state_transfer` 不该只剩一张表。

应该拆成三层 claim。

### Layer A：Mechanism Authenticity

问题：

> typed non-text handoff 是否真实存在并被下游消费？

对照：

- `protocol + text_brief_structured_shadow + memory_off`
- `protocol + state_ref_rich + memory_off`

用途：

- 证明 typed state object family 真进入 formal path

允许的结论：

- `state_ref` 机制成立
- non-text handoff 真被 executor 消费

不允许的结论：

- 它更省
- 它更接近真实文本 agent 协作

### Layer B：Carrier Efficiency

问题：

> 在保持相同 executor decision payload 的前提下，
> text carrier 和 non-text carrier 谁更轻？

对照必须改成：

- `protocol + text_packet_minimal + memory_off`
- `protocol + state_packet_minimal + memory_off`

关键要求：

- 两边必须共享同一个最小 payload schema
- 差别只能是 carrier：
  - one side text serialization
  - one side binary / msgpack / StateRef

这才是真正公平的 carrier benchmark。

建议最小 payload 只包含：

- `route`
- `tool_name`
- `route_confidence`
- `route_provenance`
- `top_k_tool_candidates`
- `evidence_doc_ids`
- `evidence_sha`

不应包含：

- full ranked evidence bundle
- replay eligibility bundle
- embedding state

因为这些不是 executor minimal decision payload。

### Layer C：Natural Text Baseline

问题：

> 对真实自然文本 handoff，typed state 有什么收益或代价？

对照：

- `protocol + natural_handoff_text + memory_off`
- `protocol + state_packet_minimal + memory_off`

这里的 `natural_handoff_text` 必须满足：

- 不允许直接由 `feature_bundle` 模板化导出
- 必须只基于：
  - 原 query
  - evidence text
  - task goal
- 由 retriever 或一个固定 summarizer prompt 生成自由文本 handoff

这条线才接近“自然文本 agent 协作”。

注意：

- 这条线更接近真实对照
- 但噪声也更大
- 所以应该作为 support claim，不是第一 headline

---

## 7. 下一版正式任务集结构

建议把 `state_transfer` 任务拆成两个正式子包，一个 support 子包。

### 7.1 Formal A: structured-shadow vs rich-state

保留当前 3 对任务，但重新命名口径：

- 不再叫 `formal state transfer headline`
- 改叫 `formal typed handoff authenticity`

### 7.2 Formal B: minimal text packet vs minimal state packet

新增 3 对任务：

- 同 query
- 同 doc set
- 同 route/tool semantics
- 只改 packet carrier

这应该成为下一版真正的 `formal state_transfer headline`。

### 7.3 Support C: natural text vs minimal state

新增 3 对 support-only 任务：

- natural free-text handoff
- minimal state packet

用途：

- 说明“真实文本协作”的相对代价
- 不进入主 headline 平均表

---

## 8. 指标也要改

当前指标不够区分 carrier 层和 end-to-end 层。

下一版建议至少分成两组。

### 8.1 Carrier metrics

- `handoff_ref_count`
- `handoff_textual_bytes`
- `handoff_nontext_bytes`
- `executor_decode_ms`
- `executor_redecode_count`
- `executor_missing_field_count`

### 8.2 End-to-end metrics

- `llm_total_tokens`
- `planner_total_tokens`
- `summarizer_total_tokens`
- `retrieve_ms`
- `execute_ms`
- `summarize_ms`
- `task_ms`
- `success_rate`

并且报告里必须明确写：

- carrier metrics 用于 `state_transfer` 主结论
- end-to-end metrics 只用于说明总体 tradeoff

---

## 9. 修改顺序

不要直接重写大 benchmark。

顺序应该是：

1. 保留当前 lane 结果，但降级口径
   - `state_transfer` -> `typed handoff authenticity`
2. 新增 minimal payload schema
   - `EXECUTOR_DECISION_PACKET` 或同等对象
3. 新增 `text_packet_minimal`
   - 同 schema 的文本序列化版本
4. 新增 `natural_handoff_text`
   - 不允许从 `feature_bundle` 模板化导出
5. 重写 report
   - 把三层 claim 分开

---

## 10. 当前最该说的正式口径

截至当前 worktree，最诚实的表述是：

> 当前 benchmark 已经足够证明 `typed non-text handoff` 在 formal path 中真实存在，
> 但当前 `state_transfer` headline 仍不够中立，因为 text baseline 是
> `structured packet` 的文本化投影，而不是自然文本 handoff；
> 因此下一版 benchmark 应拆成 `authenticity / carrier efficiency / natural text support`
> 三层，而不应继续用一张 `text_brief vs state_ref` 表承担全部结论。
