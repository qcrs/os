# Retrieval Candidate Pool Refresh 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前
`/home/qcrs/statebus/project`
围绕 `P1 retrieval` 剩余缺口做的一次很窄的 host-side 实现刷新。
它不是新的 formal benchmark，也不改写当前
`communication` / `state_transfer` / `memory`
三条正式 claim 的边界。

## 1. 这轮为什么值得做

在补完 replay contract-drift diagnostics 之后，
`P1 replay` 的最小边界已经比较清楚了。
当前更值得继续推进的一点，反而回到了 retrieval：

> repo-local retrieval 仍然更像单层总分排序，
> 还缺一层更明确的小候选生成结构。

所以这轮不是再补 replay 任务，
而是把 retrieval 端做成一个更清楚的小候选池流程。

## 2. 这轮具体改了什么

文件：

- `tasks/local_corpus.py`

变化：

1. 不再只对全量文档做一次性 `combined_score` 排序
2. 现在先分开形成：
   - semantic top window
   - lexical top window
   - tag-overlap top window
   - baseline combined-score top window
3. 再把这些结果并成一个小候选池
4. 最后只在这个候选池里做一次轻量 rerank

这一步借用的是：

1. `memsearch` 的 overfetch -> rerank 顺序
2. `langgraph-bigtool` 的 small candidate set first 结构

但它仍然保持当前 StateBus 的 host-mainline 边界：

1. 不引外部向量库
2. 不改 replay gate
3. 不改 live control plane

## 3. 这轮现在能证明什么

新的 preserved diagnostic artifact：

- `runs/host_goal_eval_20260609_193900_retrieval_candidate_pool_det_r1/`

它说明：

1. `diag-retrieval-out-of-hint-001`
   仍然成立，强 hint 外文档还能胜出
2. `diag-replay-no-doc-pref-002`
   仍然成立，exact replay 仍不依赖当前任务 doc preference
3. `diag-replay-tag-drift-001`
   仍然成立，exact replay 仍不依赖当前任务 tags/reuse_signature
4. `diag-replay-theme-drift-001`
   仍然成立，task theme 仍然是 replay 硬边界

也就是说：

> 这轮 retrieval side refresh
> 没有把前面已经收紧出来的 replay 边界打坏。

## 4. 当前最诚实的结论

这轮新增价值应记成：

> retrieval small-candidate-pool refresh

它更像是：

1. retrieval mechanism clarification
2. candidate-generation honesty refresh

而不是：

1. retrieval 已经开放域泛化
2. 新的 formal headline
3. replay gain 被这一步显著放大
