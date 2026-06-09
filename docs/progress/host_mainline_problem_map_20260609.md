# StateBus Host-Mainline Problem Map 2026-06-09

日期：`2026-06-09`

适用范围：这份文档只服务当前 `/home/qcrs/statebus/project` 的
host-mainline 审核与推进。它不把 Docker、openEuler VM、`nsjail`、
hidden-state/KV 传递或交付阶段对象重新拉回当前主线。

目的不是再写一份泛泛总结，而是把当前剩余主问题按
`P0 / P1 / P2 / STOP` 固定下来，让后续检索、实现、benchmark
和 claim 收口都能围绕同一张问题地图推进。

---

## 1. 当前总判断

先把当前已经成立的事实钉死：

1. 当前对象已经不是纯脚手架。
2. 当前对象也不是开放任务上的通用多 Agent runtime 完成态。
3. 当前正式 claim 边界已经收口到：
   - `communication`：成立
   - `state_transfer`：成立，但必须带 `text brief handoff` 范围
   - `memory`：只成立到 `replay_enabled / step-skipping reuse`
   - `assist_only`：仍不能写成优于 `memory_off`
4. 当前最需要继续收口的，不再是“是否偏题”的空泛争论，
   而是：
   - 剩余主问题到底是什么
   - 哪些值得继续推进
   - 哪些应该明确停住

这份 problem map 的结论也是：

> 当前最主要的问题已经不是 benchmark fairness 本身，
> 也不是继续盲加 executor 机制；
> 而是把当前 claim surface、去特化边界、
> retrieval / memory / execute 的剩余结构问题，
> 用更稳定的优先级和 stop-line 固定下来。

---

## 2. 分类总表

### `P0`

1. claim surface 与问题地图仍缺统一主文档
2. memory 主张边界仍容易被误读成 broad shared-memory gain

### `P1`

1. retrieval 去特化仍未完全收口
2. replay / memory reuse 仍主要成立于受控 contract
3. benchmark 解释面虽然已明显改善，但“fresh retrieval vs replay”
   的主口径仍需要继续固定

### `P2`

1. executor/tool selection 仍是 route-aware playbook selector
2. repo-local 静态知识层 / capability note 还不够明确
3. `mmap` vs `shared_memory` backend mixed 结果仍未形成更稳结论

### `STOP`

1. 当前不该继续把 `assist_only` 当 headline 追
2. 当前不该继续把 executor 机制 hardening 当默认主线
3. 当前不该继续重写 benchmark fairness
4. 当前不该把 sandbox / Docker / openEuler VM 抬回当前主线

---

## 3. 逐项问题图

## 3.1 `P0` claim surface 与问题地图仍缺统一主文档

类别：

- claim surface 收紧问题
- 文档与表述问题

现象：

1. 当前 repo 里已经有多份强相关结论文档：
   - `benchmark_fairness_audit_20260608.md`
   - `host_goal_26task_serialized_api_decision_20260608.md`
   - `host_mainline_despecialize_audit_20260608.md`
   - `host_mainline_next_step_decision_20260609.md`
2. 这些文档分别回答了：
   - benchmark 是否公平
   - formal lane 到底能 claim 什么
   - 去特化对象是什么
   - executor 现在为什么该停住
3. 但它们之前并没有收敛成一份显式 `P0/P1/P2/STOP`
   的主问题地图。

根因假设：

1. 这几轮工作先后在收口：
   - fairness
   - replay / memory boundary
   - executor observability
   - reporting closure
2. 每一轮都解决了一个局部问题，
   但缺少一份把“现在到底还剩什么”重新编排的总图。

当前证据：

1. `docs/progress/host_mainline_next_step_decision_20260609.md`
   已经明确：
   - executor mechanism hardening 不再是默认下一步
2. `docs/progress/benchmark_fairness_audit_20260608.md`
   已经明确：
   - `communication` 成立
   - `state_transfer` 只在 `text brief handoff` 范围内成立
   - `assist_only` 不成立为 headline
3. `docs/progress/executor_mainline_observability_reaudit_20260609.md`
   已经明确：
   - 当前没有足够证据继续沿 executor 主线盲加规则

还缺什么证据：

1. 不是再缺 benchmark 证据；
2. 而是缺一份统一的“问题 -> 优先级 -> stop-line”主文档。

若修复，影响哪条主张：

1. 不直接扩张任何赛题主张；
2. 但会直接提升：
   - 当前 claim 收口的稳定性
   - 后续实现方向的约束强度
   - benchmark 使用的克制程度

若不修，风险是什么：

1. 后续容易继续在已经停住的 executor 主线上反复横跳；
2. 也容易重新把 `assist_only`、sandbox、或者大框架检索重构抬回错误优先级。

当前建议：

> 现在就把主问题地图显式固定下来。

---

## 3.2 `P0` memory 主张边界仍容易被误读成 broad shared-memory gain

类别：

- claim surface 收紧问题
- memory reuse 机制问题

现象：

1. 当前 formal lane 已经很清楚：
   - `replay_enabled` 稳定优于 `memory_off`
   - `assist_only` 仍未稳定优于 `memory_off`
2. 但 memory 这个词本身太大，仍然容易被外部或后续写作误读成：
   - shared memory gain 已经普遍成立
   - assist-style reuse 已经是当前主线亮点

根因假设：

1. “shared memory / memory reuse” 天然带有比当前结果更大的语义外延；
2. 当前 replay gain 是真的，但它的成立条件仍较受控。

当前证据：

1. `docs/progress/benchmark_fairness_audit_20260608.md`
   已明确 `assist_only` 慢于 `memory_off`。
2. `docs/progress/host_goal_26task_serialized_api_decision_20260608.md`
   已明确：
   - `memory` 只成立到 `replay_enabled / step-skipping reuse`
   - `assist_only` 仍不能宣称更优
3. 新增 report 已可直接看到：
   - `Memory Policy Claim Surface`
   - `assist_only`
   - `replay_enabled`

还缺什么证据：

1. 不是缺更多 formal run；
2. 而是缺更固定、更统一的 wording 入口，
   让后续不再把“memory 已成立”写过头。

若修复，影响哪条主张：

1. 直接影响 `memory` claim 的诚实边界；
2. 间接保护 `structured vs text` 与 `replay reuse` 两条线不被混写。

若不修，风险是什么：

1. 后续很容易回到“为了 headline 追 assist_only gain”的旧问题；
2. 也容易把 replay 受控收益误包装成更广义的自然任务 memory gain。

当前建议：

> 当前 memory 线继续只允许 claim
> `replay_enabled / step-skipping reuse`，
> 不再默认把 `assist_only` 当优化主线。

---

## 3.3 `P1` retrieval 去特化仍未完全收口

类别：

- retrieval 去特化问题

现象：

1. 当前 retrieval 已经比更早阶段诚实得多：
   - 不再先按 `task_group/task_theme` 预裁剪候选
   - `corpus_doc_ids` 已退成弱先验
2. 但它仍然明显是：
   - repo-local corpus
   - benchmark-themed incident family
   - contest-shaped evidence router

根因假设：

1. 当前 retrieval 主对象仍然是 repo-local 任务证据，不是开放域检索；
2. 这本身并不偏题，但意味着“更泛化的检索能力”还没有真正成立。

当前证据：

1. `docs/progress/host_mainline_despecialize_audit_20260608.md`
   已明确：
   - 最强的预裁剪问题已经减弱
   - 但 retrieval 仍然偏 benchmark-shaped
2. `docs/progress/contest_requirement_host_audit_20260607.md`
   也把这条列为可继续做的 host-side 提升项。
3. `docs/progress/retrieval_replay_diagnostic_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_174900_retrieval_replay_diag_det_r1/`
   已经补上一层保留的 diagnostic artifact，直接证明：
   - stronger out-of-hint retrieval 可以胜出
   - `corpus_doc_ids` 现在更像弱先验，而不是硬裁剪
4. `docs/progress/retrieval_candidate_pool_refresh_20260609.md`
   与
   `runs/host_goal_eval_20260609_193900_retrieval_candidate_pool_det_r1/`
   又把 retrieval 端从单层总分排序收紧成
   `small candidate pool -> light rerank`，
   同时保持：
   - out-of-hint retrieval 胜出样例仍成立
   - retrieval refresh 没有把已存在 replay diagnostics 打坏
5. `docs/progress/retrieval_hint_diagnostic_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_201200_retrieval_hint_diag_det_r1/`
   又把 retrieval 端的 weak-hint 边界补成 matched diagnostics，直接显示：
   - `diag-retrieval-no-tags-001` 说明 out-of-hint 胜出
     不依赖当前任务 tags
   - `diag-retrieval-misleading-tags-001` 说明 misleading invalidation tags
     也不足以把 route 拉回 hinted invalidation docs
   - `diag-retrieval-invalidation-control-001` 说明 retrieval refresh
     没有塌成 generic replica bias
6. `docs/progress/retrieval_hint_cross_family_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_203500_retrieval_hint_cross_family_det_r1/`
   又把这条 weak-hint 边界从单一 `cache` family
   扩成了 `cache / latency / session`
   三个 repo-local incident family 的 matched diagnostics，直接显示：
   - `diag-retrieval-latency-no-tags-001` 与
     `diag-retrieval-session-no-tags-001`
     说明 out-of-hint 胜出不再只停在 `cache` family
   - `diag-retrieval-latency-misleading-tags-001` 与
     `diag-retrieval-session-misleading-tags-001`
     说明 misleading tags 被更强 query evidence 压下去
     也不再只停在单一 family
   - 三个 family 的 negative control
     都还保留着自己的正常 route，而不是塌成 generic bias
7. `docs/progress/retrieval_context_diagnostic_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_123900_retrieval_context_diag_det_r1/`
   又把 retrieval 的剩余 context-prior 边界补成 matched diagnostics，直接显示：
   - wrong-family `task_group / task_theme / preferred docs`
     也不再是 retrieval 命中的硬边界
   - `diag-retrieval-session-context-rate-limit-001`
     `diag-retrieval-latency-context-worker-001`
     `diag-retrieval-cache-context-replica-001`
     说明 query evidence 仍能把正确 family 的 route 顶出来
   - 对应的 session / latency / cache control
     也都还保留着各自的 same-query-family route，
     而不是一旦脱离当前 task context 就随机漂移
8. `docs/progress/retrieval_mixed_docset_diagnostic_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_235900_retrieval_mixed_docset_diag_det_r1/`
   又把 retrieval 的 widened preferred-doc-set 边界补成 matched diagnostics，直接显示：
   - wrong-family `task_group / task_theme`
     再叠加 mixed family `corpus_doc_ids`
     之后，
     `diag-retrieval-mixed-latency-worker-001`
     `diag-retrieval-mixed-cache-replica-001`
     `diag-retrieval-mixed-session-rate-limit-001`
     仍然能把正确 family route 顶出来
   - 对应的
     `diag-retrieval-mixed-latency-db-control-001`
     `diag-retrieval-mixed-cache-invalidation-control-001`
     `diag-retrieval-mixed-session-drift-control-001`
     也都还保留着各自 same-family control route
   - 这说明 widened mixed doc set
     当前也还不足以把 retrieval 拉回错误 family
     或压扁成 generic route bias
9. `docs/progress/retrieval_weak_route_diagnostic_artifact_20260610.md`
   与
   `runs/host_goal_eval_20260610_001800_retrieval_weak_route_diag_det_r1/`
   又把 retrieval 的 weak-route 边界补成 matched diagnostics，直接显示：
   - 在
     `diag-retrieval-weak-route-latency-db-001`
     /
     `diag-retrieval-weak-route-latency-worker-001`
     这类成对任务里，
     同一个薄 query
     在只切换 in-family preferred doc 时
     route 会跟着翻转
   - cache / session family
     也各自出现了同类成对翻转
   - 这说明当前 retrieval
     在 clear query evidence 下已能压过
     wrong-family context 与 widened doc set，
     但在 weak-route 条件下
     仍然明显受 in-family preferred route
     牵引

还缺什么证据：

1. 当前不再缺“是否完全只能靠当前 hint doc 或当前 tags 才能命中”
   的最小反例；
2. 当前 weak-hint 侧已经有了跨 family 的 matched diagnostics；
3. 当前 even wrong-family `task_group / task_theme / preferred docs`
   也已经有了 repo-local matched diagnostics；
4. 当前 widened mixed-doc-set
   也已经有了 repo-local matched diagnostics，
   不再只是终端 probe 或散落单测；
5. 当前 weak-route
   也已经有了 repo-local matched diagnostics，
   不再只是 probe 或推断；
6. 但仍缺更系统的“更广义 theme drift”
   matched 对照，
   用来回答：
   - gain 还有多少依赖当前 incident family 和 route family
7. 当前也还没有新的 formal 包专门回答这件事。

若修复，影响哪条主张：

1. 不会直接改写 `communication`；
2. 会主要影响：
   - retrieval 的诚实定位
   - memory / replay 的泛化解释强度

若不修，风险是什么：

1. 当前对象会长期停留在“更诚实的 benchmark-specific retriever”上；
2. 虽不致命，但会限制后续 claim 的外延。

当前建议：

> retrieval 仍值得做，但应作为 `P1` 去特化对象，
> 不是当前 `P0` claim 收口之前的默认主线。

---

## 3.4 `P1` replay / memory reuse 仍主要成立于受控 contract

类别：

- memory reuse 机制问题

现象：

1. 当前 replay gain 是真的；
2. 但 exact replay 仍然强依赖：
   - query
   - route
   - retrieved doc set
   - evidence consistency
3. 这意味着当前更像：
   - 受控 runtime evidence gate
   而不是自然泛化的 memory reuse。

根因假设：

1. 当前系统为了保持 honest replay，必须把 gate 收得比较紧；
2. tight gate 保护了 correctness，但也缩窄了可 claim 的 reuse 范围。

当前证据：

1. `docs/progress/host_mainline_despecialize_audit_20260608.md`
   已明确：
   - replay 仍是受控 replay
2. `docs/progress/host_goal_26task_serialized_api_decision_20260608.md`
   已明确：
   - 真正成立的是 `replay_enabled / step-skipping reuse`
3. `docs/progress/retrieval_replay_diagnostic_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_174900_retrieval_replay_diag_det_r1/`
   已经把这条边界落成保留 artifact，直接显示：
   - `diag-replay-no-doc-pref-002` 可以在没有当前任务
     `corpus_doc_ids` 的情况下 `skip_retrieve_execute`
   - `diag-replay-query-drift-001` 会在 query drift 下拒绝误跳
   - `diag-replay-no-doc-pref-001` 的 assist 期待仍然落空，
     因而 `assist_only` 继续只是诊断层对象
4. `docs/progress/retrieval_replay_contract_drift_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_190500_retrieval_replay_contract_drift_det_r1/`
   又把剩余 contract 依赖补得更清楚，直接显示：
   - `diag-replay-tag-drift-001` 说明当前任务
     `tags / reuse_signature` 已不是 exact replay 必需条件
   - `diag-replay-theme-drift-001` 说明 `task_theme`
     仍然是 replay 的硬边界
5. `docs/progress/retrieval_replay_docset_drift_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_125200_retrieval_replay_docset_drift_det_r1/`
   又把 validated replay 的剩余 gate 补得更清楚，直接显示：
   - `diag-replay-validated-docset-drift-001`
     说明即使 query/theme/route 继续对齐，
     只要 fresh retrieval 落到不同的 same-route evidence/doc-set slice，
     `skip_execute` 现在仍然会被挡住
   - 这说明 replay gate 仍不只是看 route 名字对齐，
     而是继续依赖 fresh doc-set / evidence consistency
6. `docs/progress/retrieval_replay_multi_anchor_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_130100_retrieval_replay_multi_anchor_det_r1/`
   又把 replay candidate ordering 的剩余边界补得更清楚，直接显示：
   - 当多个 same-query same-route replay anchors 并存时，
     `diag-replay-multi-anchor-exact-001`
     会稳定复用更近的
     `mem-diag-replay-multi-anchor-b-001-replay`
   - 这说明 exact replay 仍然受当前 replay candidate surface
     与 candidate ordering 影响，而不是与具体 memory anchor 脱钩
7. `docs/progress/retrieval_replay_route_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_131600_retrieval_replay_route_det_r1/`
   又把 replay route-eligibility 的剩余边界补得更清楚，直接显示：
   - `diag-replay-route-weak-exact-001`
     在 query/theme 继续对齐时，仍会因为
     `generic_triage / low_confidence_abstain`
     保持 `reuse_mode = none`
   - `diag-replay-route-clear-exact-001`
     则会在 clear route /
     `hint_consensus` 条件下继续
     `skip_retrieve_execute`
   - 这说明 replay gate 仍然不只是看
     query/theme 名义对齐，
     也继续受 route clarity / route provenance
     约束
8. `docs/progress/retrieval_replay_route_provenance_contract_20260609.md`
   又把 replay gate 的更细实现条件补成 contract-level regression，直接显示：
   - `_route_is_replay_eligible`
     不只要求 route confidence 过阈值，
     还要求 provenance 含 `lexical`
   - metadata-only route
     即使 route 名非 generic、confidence 看起来足够，
     也仍然不是 replay eligible
   - 但这层当前只成立到 contract/regression level，
     还不是新的 matched benchmark artifact
9. `docs/progress/retrieval_replay_override_artifact_20260609.md`
   与
   `runs/host_goal_eval_20260609_215400_retrieval_replay_override_det_r1/`
   又把更宽的 route-provenance 边界补成 preserved diagnostic artifact，直接显示：
   - `lexical_override`
     / `["lexical", "corpus_metadata_conflict"]`
     provenance 下，
     validated replay 和 exact replay
     都仍然可以自然成立
   - `diag-replay-override-exact-001`
     会命中最近的 eligible replay memory
     `mem-diag-replay-override-validated-001-replay`
     而不是最早的 cold anchor
   - 这说明 replay gate 当前真正要求的是
     lexical-led route evidence，
     不是必须限定在 `hint_consensus`
10. `docs/progress/retrieval_replay_override_cross_family_artifact_20260609.md`
    与
    `runs/host_goal_eval_20260609_222900_retrieval_replay_override_cross_family_det_r1/`
    又把这条 lexical-led provenance 边界
    从 single-family 扩成了 auth / cache
    两个 repo-local incident family 的 preserved artifact，直接显示：
    - conflicting metadata hint 下的
      `lexical_override`
      replay 不再只停在 auth family
    - auth / cache
      两个 family 的 validated replay 和 exact replay
      都能自然成立
    - exact replay 在两个 family 里
      也都继续沿最近 eligible anchor 复用
11. `docs/progress/retrieval_replay_override_theme_drift_artifact_20260609.md`
    与
    `runs/host_goal_eval_20260609_230600_retrieval_replay_override_theme_drift_det_r1/`
    又把这条 lexical-led provenance
    补成更像 matched benchmark 的 cross-family negative control，直接显示：
    - auth / cache
      两个 family 里，
      fresh route 即使继续保持
      `lexical_override`
      / `["lexical", "corpus_metadata_conflict"]`
    - 只要 `task_theme` 改成 variant，
      exact replay 就会一起掉回 `none`
    - 这说明 lexical-led replay gain
      当前仍然是 task-theme scoped，
      不是 broad replay freedom
12. `docs/progress/retrieval_replay_override_matched_artifact_20260609.md`
    与
    `runs/host_goal_eval_20260609_233900_retrieval_replay_override_matched_det_r1/`
    又把前两轮分散的 lexical-led provenance
    正负对照收成了一个单包 matched-style deterministic artifact，直接显示：
    - auth / cache
      两个 family 的六个 task
      都继续保持
      `feature_route_source = lexical_override`
    - same-theme exact replay
      在 auth / cache
      两个 family 里都继续成立
    - 对应的 theme-drift task
      在 auth / cache
      两个 family 里都稳定掉回 `reuse_mode = none`
    - 这说明当前 lexical-led provenance gain
      已经至少有了一组 auth / cache
      cross-family matched-style deterministic package，
      但仍然是 task-theme scoped reuse

还缺什么证据：

1. 当前不再缺“exact replay 是否绝对依赖当前 doc preference
   或当前任务 `tags / reuse_signature`”的最小证据；
2. 当前 validated replay 的 fresh doc-set / evidence gate
   也已经有了最小诊断证据；
3. 当前多 eligible replay anchors 下的 selection 行为
   也已经有了最小诊断证据；
4. 当前更弱 route / abstained route
   也已经有了最小诊断证据，
   不再是完全未验证边界；
5. 当前更细的 route-provenance gate
   也已经有了 contract-level closure，
   但还没有对应 matched benchmark；
6. 当前更宽的 lexical-led provenance
   也已经有了 preserved diagnostic artifact，
   不再只停在 contract-level closure；
7. 当前这条 lexical-led provenance
   也已经至少有了 auth / cache
   两个 family 的 preserved diagnostic artifact；
8. 当前这条 lexical-led provenance
   也已经有了 auth / cache
   两个 family 的 theme-drift negative control；
9. 当前这条 lexical-led provenance
   现在也已经有了一组 auth / cache
   的 matched-style deterministic package，
   不再只是分散正例和负对照；
10. 但仍缺一组“更广义 theme / 更宽 route-evidence provenance”
    约束下的 matched benchmark；
11. 如果这样一做 gain 明显塌掉，也需要正式承认。

若修复，影响哪条主张：

1. 直接影响 `memory` claim 的强度；
2. 也会影响后续是否值得继续做 replay gate 深化。

若不修，风险是什么：

1. 当前 replay gain 会长期停留在“受控成立但解释外延有限”；
2. 这并不推翻当前主线，但会限制进一步的 memory claim 扩张。

当前建议：

> 继续把 replay 视为 `P1` 主线问题，
> 但要先以“更少 contract 依赖”为目标，
> 而不是继续堆同类 repeat 数。

---

## 3.5 `P1` benchmark 解释面虽然已明显改善，但 fresh-retrieval 主口径仍需继续固定

类别：

- benchmark fairness / metrics 解释问题

现象：

1. 当前 report 已经比早期强很多：
   - lane
   - transfer handoff
   - role-level tokens
   - phase timing
   - executor observability
   - claim-surface audit views
2. 但当前最值得优先引用的主口径，
   仍需要更明确固定成：
   - `fresh_retrieval`
   - `cold_start / reject_control`
   这一级，而不是 aggregate。

根因假设：

1. aggregate 天然会混 replay / reuse；
2. 即使 report 里已经能看见更细视图，
   后续写作仍可能偷懒回到 aggregate headline。

当前证据：

1. `docs/progress/structured_vs_text_comparison_analysis_20260608.md`
   已明确：
   - 结构化优势应优先看 `fresh_retrieval`
2. 这轮新增 report 已经把：
   - `Structured-vs-Text By Reuse Axis`
   直接写进 `benchmark_report.md`

还缺什么证据：

1. 不再缺 telemetry；
2. 主要缺后续文档和正式写作统一按这套口径引用。

若修复，影响哪条主张：

1. 主要影响 `communication` 与 `structured vs text` 的解释质量；
2. 不直接扩张 formal claim。

若不修，风险是什么：

1. 当前更细的证据层仍可能被 aggregate 叙事覆盖；
2. 造成 communication 优势与 replay gain 被重新混写。

当前建议：

> benchmark 解释面继续作为 `P1` 说明层工作，
> 不必再扩 telemetry，
> 但后续正式写作应优先引用 fresh-retrieval / lane 口径。

---

## 3.6 `P2` executor/tool selection 仍是 route-aware playbook selector

类别：

- execute/tool selection 去特化问题

现象：

1. 当前 executor 仍不是开放式 action runtime；
2. 更准确定位仍然是：
   - feature route / evidence
   - ranked tool candidates
   - abstain or fixed playbook

根因假设：

1. 当前 contest-shaped runtime 本来就不是要先做广义 CodeAct；
2. route-aware playbook selector 是当前对象的合理中间态。

当前证据：

1. `docs/progress/executor_mainline_observability_reaudit_20260609.md`
   已明确：
   - 当前没有足够强的新证据支持继续沿 mechanism 层盲加规则
2. `docs/progress/host_mainline_next_step_decision_20260609.md`
   已明确：
   - executor mainline 应先停在现有边界

还缺什么证据：

1. 如果未来要重开这条线，
   需要先出现新的误路由/误执行证据；
2. 当前没有。

若修复，影响哪条主张：

1. 更可能影响“内部链路是否更合理”；
2. 不会直接改变当前 formal contest claim。

若不修，风险是什么：

1. 对外定位仍然偏 contest-shaped；
2. 但这当前是可接受的边界，不是立即 blocker。

当前建议：

> executor 现阶段降为 `P2`，
> 保留现有 claim-boundary / observability closure，
> 不再默认继续叠 mechanism hardening。

---

## 3.7 `P2` repo-local 静态知识层 / capability note 还不够明确

类别：

- retrieval 去特化问题
- 文档与表述问题

现象：

1. 当前 `Retriever` 实际上已经不只是 memory lookup；
2. 但 repo-local 静态知识层、tool usage note、capability note
   还没有更明确沉淀成独立对象。

根因假设：

1. 当前主线先解决了 runtime / benchmark / claim surface；
2. 静态知识层的对象分离还没成为独立工作项。

当前证据：

1. `docs/progress/host_mainline_review_closure_20260608.md`
   已明确：
   - repo-local corpus
   - 共享记忆
   - 工具/能力说明层
   其实是三个不同对象。

还缺什么证据：

1. 不是缺 formal run；
2. 而是缺更明确的 repo-local artifact 设计与约束。

若修复，影响哪条主张：

1. 主要影响 retrieval / executor 的说明层清晰度；
2. 也会帮助 future borrow-list 和 capability note 更稳定。

若不修，风险是什么：

1. 后续仍容易把 Retriever 简化成“只查共享记忆”；
2. 或把静态知识层和 memory store 混写。

当前建议：

> 静态知识层可作为 `P2` 明确化对象，
> 但不值得现在扩成新的外部 RAG 系统。

---

## 3.8 `P2` `mmap` vs `shared_memory` backend mixed 结果仍未形成更稳结论

类别：

- benchmark fairness / metrics 解释问题
- 后端工程选择问题

现象：

1. 当前 shared-memory 已经不是 dormant backend；
2. 但当前 matched compare 结论仍是 mixed：
   - `protocol` 下更快
   - `text` 下更慢

根因假设：

1. backend 成本与 mode/transport/prompt 结构有交互；
2. 当前结果还不足以支持统一 headline。

当前证据：

1. `docs/constraints/current_feature_scope.md`
   已明确：
   - `shared_memory` 是可验证备选路径
   - 但不是当前统一方向的 formal backend headline

还缺什么证据：

1. 若未来要升优先级，需要更 matched 的 formal compare；
2. 当前不是最值得先做的事。

若修复，影响哪条主张：

1. 主要影响 backend 工程选择；
2. 不直接改变当前三条主张边界。

若不修，风险是什么：

1. 当前 backend 结论只能保持 mixed；
2. 但这不阻塞 host-mainline 当前主线。

当前建议：

> `shared_memory` 继续保留为 `P2`，
> 不把它硬抬成当前 formal headline。

---

## 3.9 `STOP` 当前不该继续把 `assist_only` 当 headline 追

类别：

- 暂不值得做的问题

现象：

1. 当前 formal lane 已经反复显示：
   - `assist_only` 不稳定优于 `memory_off`

根因假设：

1. assist-style memory hit 本身并不自动转化为端到端收益；
2. summarizer / downstream prompt 成本仍然可能吃掉这点收益。

当前证据：

1. `docs/progress/benchmark_fairness_audit_20260608.md`
2. `docs/progress/host_goal_26task_serialized_api_decision_20260608.md`
3. 当前 report 中的 `Memory Policy Claim Surface`

还缺什么证据：

1. 不缺“是否该继续追”的证据；
2. 当前 stop-line 已足够清楚。

若修复，影响哪条主张：

1. 如果强行追，只会增加 headline 风险；
2. 当前不应作为正向扩张对象。

若不修，风险是什么：

1. 会回到“为了 headline 调 benchmark / 调 prompt”的旧问题。

当前建议：

> 直接停。

---

## 3.10 `STOP` 当前不该继续把 executor mechanism hardening 当默认主线

类别：

- 暂不值得做的问题

现象：

1. executor 这条线最近已经补了：
   - low-confidence abstain
   - thin-support abstain
   - conflict-thin override abstain
   - out-of-band observability
   - report-level observability closure
2. 重新审计后，没有足够新证据支持继续盲加规则。

根因假设：

1. 当前最早看起来像“机制问题”的一部分，
   实际上是 observability 缺口；
2. 补完后，继续加规则的边际收益已经很低。

当前证据：

1. `docs/progress/executor_mainline_observability_reaudit_20260609.md`
2. `docs/progress/host_mainline_next_step_decision_20260609.md`

还缺什么证据：

1. 只有新的真实失败模式，才值得重开。

若修复，影响哪条主张：

1. 当前不会直接扩张 formal claim；
2. 更可能只是内部机制更复杂。

若不修，风险是什么：

1. 继续动这条线，最容易重新引入：
   - 不必要 abstain
   - fairness 扰动
   - 为去特化而去特化

当前建议：

> 停在当前边界上。

---

## 3.11 `STOP` 当前不该继续重写 benchmark fairness

类别：

- 暂不值得做的问题

现象：

1. fairness 主问题已经完成：
   - lane
   - handoff metrics
   - text-brief baseline wording
   - claim-surface report views
2. 再继续在同一层改，只会把主线再次打散。

根因假设：

1. 当前更细的问题已经从“benchmark 定义有错”
   转成“如何诚实解释与引用已有证据”。

当前证据：

1. `docs/progress/benchmark_fairness_audit_20260608.md`
2. `docs/progress/structured_vs_text_claim_surface_report_20260609.md`

还缺什么证据：

1. 不再缺 fairness closure 本身的证据。

若修复，影响哪条主张：

1. 当前继续重写不会显著扩张任何主张；
2. 更可能只是重复劳动。

若不修，风险是什么：

1. 会拖慢真正还值得做的 `P1` 问题。

当前建议：

> 停止继续重写 fairness 层。

---

## 3.12 `STOP` 当前不该把 sandbox / Docker / openEuler VM 拉回当前主线

类别：

- 暂不值得做的问题

现象：

1. host runnable path 已经存在；
2. 当前最主要弱点不在“完全无法隔离执行”。

根因假设：

1. 当前 goal 明确是 host-mainline；
2. Docker / VM / `nsjail` 是后验验证或交付层对象。

当前证据：

1. `docs/constraints/current_host_and_migration.md`
2. `goal.md`
3. `docs/progress/host_mainline_next_step_decision_20260609.md`

还缺什么证据：

1. 当前不是缺这层证据；
2. 是主线边界本身就要求现在不要做。

若修复，影响哪条主张：

1. 不会帮助当前 `communication` / `state_transfer` / `memory`
   三条主张更诚实成立。

若不修，风险是什么：

1. 会让主线目标再次偏移。

当前建议：

> 继续停在 host-mainline 前面，不回灌到当前实现主线。

---

## 4. 当前最值得做的一步

如果现在必须给出一个单一步骤，我的判断是：

> 当前最值得做的一步，
> 不是再加 executor 规则，
> 也不是再追 assist-only gain，
> 而是把 `P0/P1/P2/STOP` 这张问题地图固定下来，
> 然后只围绕 `P1` 中最值得的一项继续做定向检索或小步实现。

在这张地图下，下一步最合理的候选顺序是：

1. `P1` replay / retrieval 去特化的 matched evidence
2. `P1` fresh-retrieval 口径下的正式引用和说明层继续统一
3. `P2` 静态知识层 / capability note 明确化

而不是：

1. 重开 executor mechanism hardening
2. 重追 `assist_only`
3. 重写 fairness
4. 把 sandbox / Docker / VM 拉回当前主线

---

## 5. 当前最诚实的收口

这份文档最重要的价值不是提出更多可能性，
而是明确 stop-line：

1. 当前主线已经不是“缺 formal 证据”
2. 当前主线也不是“必须再救 executor”
3. 当前剩余问题里，真正值得继续推进的是：
   - 去特化
   - replay/retrieval 解释边界
   - claim surface 统一收口

如果后续工作没有带来更强新证据，
当前最诚实的位置仍然是：

> 保留现有三条主张的成立边界，
> 不为了 headline 强推更大的 memory 或 executor claim，
> 让后续实现只服务于更少特化、更稳解释，而不是更大包装。
