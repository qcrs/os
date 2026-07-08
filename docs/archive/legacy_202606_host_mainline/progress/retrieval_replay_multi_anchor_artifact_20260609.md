# Retrieval Replay Multi-Anchor Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 replay` 再补的一层
multi-anchor exact replay 行为边界。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

前面的 replay artifact 已经证明：

1. exact replay 不再依赖当前任务 `doc preference`
2. validated replay 仍受 fresh doc-set / evidence gate 约束
3. replay 仍然是 tight runtime evidence gate

但 replay 主线里还剩一个没被单独隔离的问题：

> 当同一个 query / theme / route
> 已经积累出多个 eligible replay anchor 时，
> exact replay 到底怎么选？

这轮最值得补的不是再改 runtime，
而是把这个 multi-anchor 行为先变成 repo-local diagnostic evidence。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_130100_retrieval_replay_multi_anchor_det_r1/`

运行形态：

- `task_set = tasks/retrieval_replay_multi_anchor_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

任务结构：

1. `diag-replay-multi-anchor-a-001`
   - 建第一个 replay anchor
   - fresh docs = `[cache-invalid-anchor, cache-invalid-replay]`
2. `diag-replay-multi-anchor-b-001`
   - 建第二个 replay anchor
   - fresh docs = `[cache-invalid-anchor, cache-invalid-followup]`
3. `diag-replay-multi-anchor-exact-001`
   - exact replay
   - 看最终复用哪个 anchor

## 3. 这包现在直接证明什么

### 3.1 exact replay 在多 eligible anchors 下会选最近的合格 replay memory

`diag-replay-multi-anchor-exact-001`
在 `text/protocol` 两侧都显示：

1. `reuse_mode = skip_retrieve_execute`
2. `retrieved_doc_ids = [cache-invalid-anchor, cache-invalid-followup]`
3. `reused_from_memory_id = mem-diag-replay-multi-anchor-b-001-replay`

而前两个 anchor 明确是：

1. `diag-replay-multi-anchor-a-001`
   - fresh docs = `[cache-invalid-anchor, cache-invalid-replay]`
2. `diag-replay-multi-anchor-b-001`
   - fresh docs = `[cache-invalid-anchor, cache-invalid-followup]`

这说明：

> 当前 exact replay 在多 same-query same-route anchors 并存时，
> 会选更近的、仍然合格的 replay memory，
> 而不是任意随机命中更早的 anchor。

### 3.2 replay 仍然是 ordered candidate reuse，不是无条件泛化

这层新证据和前面的 doc-set/theme/query 边界拼起来，
现在更完整地说明了：

1. replay 候选不是只有一个“抽象 route”
2. 当前 exact replay 会沿当前 replay candidate ordering
   去选最近的合格 memory
3. 所以 replay gain 仍然深受当前 repo-local memory candidate surface 约束

## 4. 当前最诚实的结论

这轮新增价值应记成：

> replay multi-anchor selection boundary

它现在支持的说法是：

1. current exact replay 在多 eligible anchors 下
   存在稳定的 anchor selection 行为
2. 这个行为当前更像
   “选最近合格 replay memory”
3. replay gain 仍然受 candidate ordering / candidate surface 影响

它仍然不支持的说法包括：

1. replay 已经自然泛化
2. 多 anchor 并存下 replay 已经与具体 memory candidate 无关
3. deterministic diagnostic artifact
   已足够替代新的 formal matched benchmark
