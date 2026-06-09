# Retrieval Replay Override Cross-Family Artifact 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
为 `P1 replay` 再补的一层
cross-family lexical-override route-provenance evidence。
它不是新的 formal benchmark，
也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得补

上一轮 override artifact
已经证明：

1. auth family 里
   `lexical_override`
   provenance 仍然 replay eligible

但那还只是一条 single-family 证据。
主线里真正剩下的问题是：

> 这条 lexical-led provenance 边界
> 是 auth family 的偶然现象，
> 还是至少已经跨到另一个 incident family？

这轮最值得补的不是硬凑第三个 family，
而是先把第二个自然 family
补成最小 cross-family preserved artifact。

## 2. 新增 artifact

新包：

- `runs/host_goal_eval_20260609_222900_retrieval_replay_override_cross_family_det_r1/`

运行形态：

- `task_set = tasks/retrieval_replay_override_cross_family_tasks.yaml`
- `repeat = 1`
- `modes = text,protocol`
- `llm_mode = deterministic`

family 结构：

1. auth family:
   - `diag-replay-override-anchor-001`
   - `diag-replay-override-validated-001`
   - `diag-replay-override-exact-001`
2. cache family:
   - `diag-replay-override-cache-anchor-001`
   - `diag-replay-override-cache-validated-001`
   - `diag-replay-override-cache-exact-001`

## 3. 这包现在直接证明什么

### 3.1 lexical-override provenance 不再只停在 auth family

六个任务在 `text/protocol` 两侧都显示：

1. `feature_route_source = lexical_override`
2. `feature_route_provenance = ["lexical", "corpus_metadata_conflict"]`

并且：

1. auth family:
   - validated replay 成立
   - exact replay 成立
2. cache family:
   - validated replay 成立
   - exact replay 成立

这说明：

> 当前 replay gate 对更宽 lexical-led provenance
> 的支持不再只停在单一 auth family；
> 至少在 auth / cache 两个 repo-local incident family 里，
> conflicting metadata hint 下的 replay
> 仍然可以自然成立。

### 3.2 exact replay 仍然继续沿最近 eligible anchor 复用

这包里两个 family 的 exact replay
都没有回到最早 cold anchor，
而是分别命中：

1. auth:
   - `mem-diag-replay-override-validated-001-replay`
2. cache:
   - `mem-diag-replay-override-cache-validated-001-replay`

这说明：

> cross-family lexical-override replay
> 也仍然继续受 recent eligible anchor ordering
> 影响，而不是脱离当前 candidate surface。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> replay cross-family lexical-led provenance closure

它现在支持的说法是：

1. replay gate 当前真正要求的是
   lexical-led route evidence，
   而不是必须 `hint_consensus`
2. 这条边界当前已经至少跨到
   auth / cache
   两个 repo-local family
3. replay 仍继续受 recent eligible anchor ordering
   影响

它仍然不支持的说法包括：

1. replay 已经摆脱 route-evidence alignment
2. 这已经等价于更广 theme / provenance 的 matched benchmark
3. lexical-led provenance 已经对所有 family 自然泛化
