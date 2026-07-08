# Retrieval and Replay Diagnostic Surface 2026-06-09

日期：`2026-06-09`

适用范围：这份短文档只记录当前 `/home/qcrs/statebus/project`
为 `P1` retrieval / replay 去特化问题补的一组最小诊断任务。
它不是新的 formal benchmark，也不改写当前三条正式 claim 的边界。

## 1. 这轮为什么值得做

当前 retrieval / replay 主线已经不是“没有逻辑”，而是：

1. 关键去特化判断主要分散在单元测试和多份审计文档里
2. 还缺一组像 `executor_diagnostic` 那样可独立复查的诊断任务
3. 因此 `P1` 里两个最关键的问题仍然太依赖手工串联：
   - stronger out-of-hint retrieval 是否真的能胜出
   - exact replay 是否真的不再依赖当前任务的 doc preference
   - exact replay 到底还依赖哪些 runtime contract，哪些已经不是必需条件

所以这轮最值得补的不是再改 runtime 机制，
而是把这两点升格成独立 diagnostic artifact。

## 2. 这轮具体补了什么

1. `tasks/retrieval_replay_diagnostic_tasks.yaml`
   - `diag-retrieval-out-of-hint-001`
   - `diag-replay-no-doc-pref-001`
   - `diag-replay-validated-001`
   - `diag-replay-no-doc-pref-002`
   - `diag-replay-tag-drift-001`
   - `diag-replay-query-drift-001`
   - `diag-replay-theme-drift-001`
2. `tests/test_smoke.py`
   - 新增 retrieval/replay diagnostic benchmark 回归

这组任务只复用现有 sample corpus 和现有 runtime 规则，
不新增新的机制假设。

## 3. 这组诊断现在能直接证明什么

### 3.1 retrieval 去特化的最小证据

`diag-retrieval-out-of-hint-001` 直接验证：

1. 当前 `corpus_doc_ids` 只是弱先验
2. 更强的 hint 外文档现在可以胜出
3. 胜出后 execute 路径也会跟着转到正确 playbook

### 3.2 exact replay 去 doc-preference 的最小证据

`diag-replay-no-doc-pref-002` 直接验证：

1. exact replay 可以在当前任务没有 `corpus_doc_ids` 的情况下成立
2. retrieve / execute 可以真实 skip
3. reused retrieve payload 不再回写 `preferred_corpus_doc_ids`
   或 `candidate_corpus_doc_ids`

### 3.3 exact replay 仍然是受控 replay，而不是自然泛化

`diag-replay-tag-drift-001` 直接验证：

1. 当前 exact replay 不再依赖当前任务的 `tags`
2. 当前 exact replay 也不再依赖当前任务的 `reuse_signature`
3. 只要 query、theme 和 archived replay evidence 仍然对齐，
   retrieve / execute 仍然可以真实 skip

### 3.4 exact replay 仍然保留 task-theme 边界

`diag-replay-theme-drift-001` 直接验证：

1. 当前 `task_theme` 仍然是 replay 候选过滤的一条硬边界
2. 即使 query 仍然保持和 archived replay query 一致
3. 只要 task theme 漂移，exact replay 现在仍然不会误跳

### 3.5 exact replay 仍然是受控 replay，而不是自然泛化

`diag-replay-query-drift-001` 直接验证：

1. 当前 `exact replay` 并不是“只要 contract 允许就会跳”
2. 当当前 query 明显偏离 archived replay query 时
3. retrieve / execute 现在仍然会回到正常 fresh path，而不是误跳 exact replay

## 4. 这组诊断不能证明什么

它不能证明：

1. retrieval 已经开放域泛化
2. replay 已经摆脱受控 contract
3. 这已经足够替代新的 matched formal benchmark
4. `task_theme` 也已经可以随意漂移而不影响 replay

它的价值更准确地说是：

> 为当前 `P1` retrieval / replay 去特化问题，
> 补上一层独立、可复查、比散落单元测试更接近 benchmark artifact
> 的诊断证据面。

## 5. 当前最诚实的结论

这轮变化应记成：

> retrieval / replay diagnostic surface closure

而不是：

1. 新的 formal headline
2. replay 泛化已经成立
3. retrieval 已经脱离 benchmark-shaped 对象
4. replay 已经不再受 query / theme 这类 runtime gate 约束
