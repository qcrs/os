A previous agent produced the plan below to accomplish the user's task. Implement the plan in a fresh context. Treat the plan as the source of user intent, re-read
  files as needed, and carry the work through implementation and verification.

  # StateBus Contest P0 Closure

  ## Summary

  以 `docs/review/statebus_contest_remaining_closure_plan_20260615.md` 作为唯一主合同，当前仓库重新核对后的真实 P0 仍是三件事：

  1. `tasks/contest_dual_mode_controlled_v3_benchmark.yaml` 仍存在 query leakage，且 checkout/auth/inventory/deploy 的 `clean` 与 `replay_reusable` 仍是单 route，formal
  dual-mode headline 还不够硬。
  2. `tasks/contest_release_regression_corpus.yaml` 仍主要是“主证据 + 同 family 弱干扰”，没有形成真正的多文档证据拓扑。
  3. `tasks/local_corpus.py` 仍保留 formal pack 可复用的结构性捷径：`runtime_route_hint/runtime_tool_name` 字段兼容、`preferred_doc_ids` 直接并入候选池、theme/group
  bonus 继续托举 repo-private 偏置。

  外部资料可抽象成统一设计原则，不直接搬数据集：
  - HotpotQA / MuSiQue：问题文本不直接泄漏答案，正确性依赖跨文档 supporting facts 组合。
  - BRIGHT：不能让 lexical overlap 本身决定检索结果，必须有强负例和跨族干扰。
  - LongMemEval：把“可答/不可答、需要更多证据、复用前题结论”作为显式合同，而不是默认总能单跳命中。
  - MoreHopQA / ToolRet：可借鉴为“多跳约束 + 工具/route 竞争集”设计参考。

  ## Remaining Issues

  - `contest_dual_mode_controlled_v3`：
    - checkout/auth/inventory/deploy 的 `clean` query 直接包含 route 词。
    - checkout/auth/inventory/deploy 的 `replay_reusable` 仍写成单 route 单解，不能证明复用前题 dependency。
    - billing 已部分更硬，但 distractor/reusable 的竞争集仍可继续统一收紧。
  - `contest_release_regression_corpus.yaml`：
    - 每个 family 需要从“incident/metrics/logs/runbook-or-config/scope/ambiguity”升级为“主证据 + 跨 family 强干扰 + scope validation + reusable follow-up dependency”。
    - reusable doc 现在更像重复同义证据，不像“必须继承前题已排除结论后才能安全收敛”的 follow-up。
  - `tasks/local_corpus.py`：
    - `CorpusDoc` 仍保留 runtime hint shape。
    - `load_corpus_docs()` 仍兼容 `route_hint/tool_name`。
    - `retrieve_corpus_docs()` 在 formal pack 下虽然关掉了 `allow_preferred_doc_bias`，但结构上仍保留 preferred doc 直入 shortlist 的路径。
    - theme/group bonus 仍在 formal pack 上工作，属于 sample-family scaffold，不是 structure-level clean。
  - `SampleTask` / replay contract：
    - `replay_source_task_id` 已非主依赖；当前更需要的是为 reusable case 显式补“prior dependency / required prior elimination / prior case reference”这类评测合同字段，供
  后续 runner/tests 验证。
  - tests：
    - 现有测试只锁住“formal pack 不消费 runtime hints”，还没锁住“formal corpus 无 runtime hint 字段 / clean+reusable 至少双 route / reusable 依赖 prior elimination /
  formal retrieval 不吃 preferred doc shortlist 注入”。

  ## Phase Plan

  ### Phase 1: Rebuild formal benchmark contract first
  - 重写 `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`，优先处理 checkout/auth/inventory/deploy，billing 同步对齐风格。
  - 对每个 family 的 `clean`：
    - 改 query，使其只描述症状与场景，不出现 route 答案词。
    - `acceptable_routes` 至少包含主 route + 1 个强竞争 route。
    - 保留 `primary_expected_route/tool` 作为评测主解，不把 clean 改成开放题。
  - 对每个 family 的 `replay_reusable`：
    - 改成“复用前题已排除结论后，才可安全执行 scoped action”的 follow-up。
    - `acceptable_routes` 至少双 route；若前题未被复用，应允许 `collect_more_evidence` 或保留竞争 route，不再默认单解。
    - 必要时给 `SampleTask` 增加 `prior_case_id`、`required_prior_case_ids`、`required_prior_eliminations` 或等价字段。
  - 保持 headline 不引入 memory 主变量，不把 planner/open surface 抬回 formal。

  ### Phase 2: Rebuild corpus topology, not wording-only refresh
  - 重写 `tasks/contest_release_regression_corpus.yaml`，按 family 建完整证据拓扑：
    - incident：只给症状与影响面。
    - metrics：给主要支持信号。
    - logs：给近因或关键机制信号。
    - config/runbook/rotation/flag-diff：给结构性因果锚点。
    - cross-family distractor：来自竞争 route，表面相似但关键 supporting facts 不同。
    - scope note：限定 blast radius，约束“最安全 first action”。
    - ambiguous note：保留两条 admissible route，支持 abstain/control。
    - reusable follow-up note：必须引用前题已确认的排除项或 scope 收敛，避免变成同义重答。
  - 目标不是把文本写长，而是让 route 决策依赖多文档支持事实组合。

  ### Phase 3: Make formal retrieval structure-level clean
  - 调整 `tasks/local_corpus.py`：
    - formal corpus `CorpusDoc` 去掉 runtime hint 作为一等字段；formal path只保留 `eval_route_label/eval_tool_label`。
    - `load_corpus_docs()` 对 formal contest corpus 禁止回退读取 `route_hint/tool_name`。
    - `retrieve_corpus_docs()` 在 formal pack 下彻底移除 `preferred_doc_ids` 注入 shortlist；preferred doc 只可用于 audit/support pack。
    - formal pack 关闭或显著削弱 theme/group bonus，避免 sample-family scaffold 决定 top-k。
    - 保留 sample/audit corpus 的 hint 兼容，但按 pack metadata 明确分流。
  - 若需要最小侵入实现：
    - 用 task-set metadata 驱动 retrieval policy，新增类似 `formal_structure_clean_retrieval=true`。
    - Retriever 调用处按 pack metadata 传递 retrieval policy，而不是仅复用 `runtime_hint_allowed`。

  ### Phase 4: Wire prior dependency into tasks and runtime-facing metadata
  - 在 `tasks/sample_tasks.py` 中补充可序列化字段，用于 reusable case 的正式合同：
    - `required_prior_case_ids`
    - `required_prior_routes`
    - `required_prior_rejections`
    - 或一个压缩版 `prior_dependency_contract`
  - 这些字段先进入 task object / manifest / eval payload。
  - 本轮不要求直接重做 replay engine；先把 benchmark/task contract 说清，并保证 tests 能锁住。

  ### Phase 5: Regression tests and wording closure
  - 补 `tests/test_smoke.py` 为主，必要时少量补 `tests/test_state_channels_and_graph.py`：
    - formal contest corpus docs 的 `runtime_route_hint/runtime_tool_name` 必须为空且 loader 不回退旧字段。
    - `contest_dual_mode_controlled_v3` 中 `clean` 与 `replay_reusable` 每个 family 至少双 route。
    - `clean` query 不得包含直接 route-leak 关键词集合。
    - `replay_reusable` 必须带 prior dependency 合同字段。
    - formal retrieval 在该 pack 下不允许 preferred-doc shortlist 注入。
    - ambiguous/reusable 若证据不足，允许 `collect_more_evidence` 作为 formal-safe control。
  - 收口 `tasks/README.md` 和 `README.md` 的 wording：
    - 明确 contest headline 已改为 stronger multi-route formal contract。
    - 明确 formal retrieval 是 structure-level clean，不再只是 runtime gate safe。
    - 不改动 memory/planner headline 边界。

  ## Acceptance / Verification

  - 静态核对：
    - `contest_dual_mode_controlled_v3_benchmark.yaml` 的 20 个 formal rows 中，clean/reusable 不再出现单 route family。
    - query 文本不直接包含 route 答案词。
    - reusable rows 带 prior dependency 合同字段。
    - `contest_release_regression_corpus.yaml` 每个 family 至少具备 incident/metrics/logs/structural-anchor/cross-family distractor/scope/reusable support。
  - 单测：
    - `python -m pytest -q tests/test_smoke.py`
    - 如涉及 graph/runtime metadata，再跑 `python -m pytest -q tests/test_state_channels_and_graph.py`
  - 冒烟：
    - `python -m runtime.smoke`

  - 本轮按主合同优先，不再把 `memory_policy_controlled_v3`、`planner_support_v3`、typed-state 口径边界当主阻塞。
  - `contest_dual_mode_controlled_v3` 仍是 dual-mode formal headline；不引入 external pure-text baseline，不把 planner openness 或 memory 改成 headline 主变量。
  - `billing_queue_chain` 视为已部分硬化，但会顺手统一到同一 formal contract 标准。
