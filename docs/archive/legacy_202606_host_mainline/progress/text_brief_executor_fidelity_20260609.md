# Text Brief Executor Fidelity 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project`
在 `state_transfer` text-side baseline 上做的一次保真度收紧。它回答的是
“text brief 是否把 Retriever 已经做出的 executor 决策语义忠实交给了 Executor”，
不是新的 contest headline。

## 1. 这轮为什么值得做

前一轮 executor 主线已经收紧了：

- `small candidate set`
- `ambiguous / metadata-only / low-confidence abstain`
- `collect_more_evidence` fallback

但 `state_transfer` lane 的 text-side baseline 还留着一个解释缝：

> Retriever 明明已经生成了 `route / route_source / route_confidence / tool_candidates`
> 这类 executor 决策快照，但 `text_brief` 只把其中一小部分转成文本 brief，
> 其余语义在 Executor 侧又依赖本地重建。

这不会直接让任务跑错，但会让 `text brief handoff` 的 baseline 更像
“只传 route 名 + 一段 evidence preview”，而不是
“把 Retriever 已决定的 executor 输入用文本形式交过去”。

如果不收紧这点，当前 `state_transfer` lane 虽然仍可用，但 text-side baseline 的
executor handoff 语义还不够完整。

## 2. 这轮实际改了什么

只做了 host-mainline 内的一小步：

- `agents/sample_agents.py`
  - `text_brief` 现在会额外写入：
    - `Suggested tool`
    - `Route confidence`
    - `Route provenance`
    - `Match score`
    - `Matched tags`
    - `Hint docs / route / tool`
    - `Tool candidates`
- `runtime/executor_runtime.py`
  - `text_brief` 消费侧现在会把这些字段解析回 feature bundle
  - 优先保留 Retriever 已经做出的 executor 决策快照，而不是只靠执行侧再次隐式重算
- `tests/test_smoke.py`
  - 新增 round-trip 与 runtime task 级回归，锁住 text-side brief 的 executor 语义保真

没有改：

- protocol `state_ref` 主线
- tool registry 主骨架
- 新的 tool / route 规则
- Docker / openEuler / `nsjail`

## 3. 现在多了什么证据

### 3.1 单测 / 回归层

新增并通过：

- `test_transfer_brief_round_trip_preserves_executor_snapshot`
- `test_state_transfer_text_brief_preserves_retriever_executor_snapshot`

它们证明：

- text brief 不再只保留 route 名
- Retriever 已经做出的 executor 决策快照，可以在 text brief 上做 round-trip

### 3.2 受控 benchmark 层

新增 deterministic 证据包：

- `runs/host_goal_eval_20260609_100100_text_brief_fidelity_det_r1/`

它显示：

- `state_transfer` text-side 任务结果没有偏离
- text-side `transfer-cache / latency / session` 三个任务仍与 protocol side 保持同 route / tool 结果
- 但 `state_transfer` text-side `handoff_textual_bytes` 从旧包的
  `1377.33` 升到 `1790.33`

这正符合这轮修改的性质：

> text brief 现在更完整地携带了 executor 决策快照，所以 text baseline 变得更诚实，
> 而不是更便宜。

## 4. 这轮没有证明什么

这轮**没有**证明：

1. `state_transfer` headline 变强了
2. `protocol` 相对 `text` 的优势扩大了
3. 应该马上重写 serialized API 正式 headline

更准确地说：

- 这轮主要是 fairness closure
- 它让 `text brief handoff` baseline 更接近“文本形式的 executor handoff”
- 它并不是一条新的性能优化

## 5. 当前最诚实的结论

当前可以新增的判断是：

> `state_transfer` lane 的 text-side baseline 现在更完整地保留了 Retriever
> 已产生的 executor 决策语义，不再只把 route 名和 evidence preview 交给 Executor。

而当前最该保留的限制仍然是：

> `state_transfer` claim 依然只能写成
> `text brief handoff` 对 `state_ref` handoff 的 scoped comparison。

这轮做的是 baseline fidelity hardening，不是新的 benchmark headline。
