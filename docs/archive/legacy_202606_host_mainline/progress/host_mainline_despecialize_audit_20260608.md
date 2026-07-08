# StateBus Host-Mainline 去特化审计

日期：`2026-06-08`

适用范围：这份审计只讨论当前 `/home/qcrs/statebus/project` 的 host-mainline，不把 Docker、openEuler VM、`nsjail`、hidden-state/KV 传递拉回当前执行主线。

## 1. 结论先说

1. 当前阶段**不是只剩 tuning**。赛题 requirement closure 基本收口了，但还残留明显的赛题特化型结构问题。
2. 当前最该先修的仍然是**工具选择机制与检索/记忆分层**，不是继续扩工具表。
3. 当前检索链已经有分层雏形，但还不是成熟、诚实的分层 RAG：
   - corpus 检索
   - feature bundle / route 提炼
   - memory assist / replay 检索
   这三层还没有真正解耦。
4. 当前 memory gain 是真的，但 exact replay 仍然主要成立于**受控 replay contract**，不是自然泛化的跨任务复用。
5. 当前 executor 不是空壳，但更准确的定位仍然是 **route-aware playbook selector**，不是通用执行层。

## 2. 赛题要求逐项核对

| 要求 | 当前判断 | 证据/边界 |
| --- | --- | --- |
| 至少 3 个 Agent，覆盖规划/检索/执行/总结至少 3 类 | 已满足 | `Planner/Retriever/Executor/Summarizer` 已跑通；仍是单仓库 host-side pipeline |
| 结构化通信，不是纯自然语言直传 | 已满足 | `text/protocol` 双模式、protobuf 控制帧、握手/能力表都在 |
| 双模式同任务对比 | 已满足 | 当前 host-side benchmark 持续保留 `text/protocol` 对照 |
| 非文本中间状态传递 | 已满足 | `StateRef + FEATURE_BUNDLE + EMBEDDING + DENSE_EVIDENCE` 已是实际代码路径 |
| 共享记忆存储、检索、复用 | 已满足 | SQLite + FAISS + MemoryQuery/Commit 主线真实存在 |
| 至少 2 组关联连续任务 | 已满足 | 当前是 3 组 x 6 任务，共 18 个连续任务 |
| 性能展示：消息、控制开销、状态开销、时间、命中率、提升 | 已满足 | `eval.runner` 已输出这些指标 |
| 稳定执行不少于 10 轮连续任务 | host-side 已满足 | 当前 deterministic repeat-10 持续稳定；openEuler 最终复现还没做 |
| 最终 openEuler 24.03-LTS-SP3 交付 | 未满足，后续阶段 | 这是交付验证层对象，当前不能写成已完成 |

硬结论：

- **赛题实现主骨架已经完成。**
- **但“已经可以只做调参优化”这个说法仍然过头。**

## 3. 这轮确认并处理了什么

### 3.1 已直接修正

1. `Planner` 不再看到 benchmark reuse expectation、runtime replay contract、corpus doc filter、`replay_source_task_id` 这些 gold-field。
2. protocol/text planner prompt 现在只暴露任务语义骨架；真实 runtime params 由本地 expected contract 恢复。
3. tool selection 先补上了第一层显式 abstain：只有 `corpus metadata hint`、没有足够 lexical/tag 支撑时，不再直接选工具，而是回退到 `tool.collect_more_evidence`。
4. `Retriever` 不再把 `corpus_doc_ids` 当成硬过滤候选集；当前实现也不再先按 `task_group/task_theme` 预裁剪候选空间，而是先对全 repo-local corpus 做统一打分，再把 `task_group/task_theme` 与 `corpus_doc_ids` 都降成弱先验。
5. 针对这一步新增了定向回归：如果 hint 里没有目标文档，但文本/标签证据更强，hint 外文档现在可以真实胜出。
6. `build_plan()` 和 planner parser 不再把 `corpus_doc_ids`、`reuse_signature`、`runtime_reuse_contract` 写进 live `PlanStep.params`；这些字段现在退到 side-band `RuntimeTaskProfile`，由 runtime 在需要时读取。
7. 这一步同时把“planner 输出即使偷偷夹带这些字段也会被保留”的隐性泄漏堵上了：当前 parser 只保留 retrieve/summarize 的语义字段。
8. runtime memory query 现在不再把 `reuse_signature` 当主过滤条件；当前主线改成 `task_theme + semantic query + route/evidence gate`，`reuse_signature` 只保留为 metadata / diagnostic 字段。
9. 根路径 `pytest -q` 现在显式限定到本仓库 `tests/`，不再被 `third_party/` vendored 仓库的测试污染。
10. 当前共享记忆不再把 assist 和 replay 混成同一个 memory object：
    - `Summarizer` 现在会分别提交 `assist` 和 `replay` 两类 memory commit
    - live memory query 只看 `memory_purpose=assist`
    - `skip_execute` / `skip_retrieve_execute` 只看 `memory_purpose=replay`
    - semantic memory search 现在会先过采样候选，再按 metadata 过滤，再截回 `top_k`，避免 replay memory 抢掉 assist memory 的候选位
11. live runtime artifacts 现在不再回写 benchmark-side reuse contract 和 current-task corpus-doc hints：
    - `FEATURE_BUNDLE` 不再写 `runtime_reuse_contract`
    - `FEATURE_BUNDLE` / `DENSE_EVIDENCE` / committed memory metadata 不再写 `candidate_corpus_doc_ids` / `preferred_corpus_doc_ids`
    - 这让 side-band benchmark contract 不再顺着运行时状态流继续泄漏
12. executor tool selection 又继续收紧了一步：
    - 当 top-1 和 top-2 lexical tool candidate 分属不同 route、分数足够接近、且两边都有真实 signal 支撑时
    - 当前不再默认“top-1 wins”
    - 而是显式 abstain 到 `tool.collect_more_evidence`
    - 这让 executor 从“默认 top-ranked playbook selector”又往前退了一步

### 3.2 新增证据

- 新回归包：
  - `runs/host_goal_eval_20260608_104349_despecialize_prompt_hint_refresh/`
  - `runs/host_goal_eval_20260608_110733_despecialize_doc_hint_preference_refresh/`
  - `runs/host_goal_eval_20260608_112452_plan_sideband_runtime_profile_refresh/`
  - `runs/host_goal_eval_20260608_113845_runtime_drop_reuse_signature_query_refresh/`
  - `runs/host_goal_eval_20260608_120619_executor_candidate_tool_refresh/`
  - `runs/host_goal_eval_20260608_122921_exact_replay_drop_doc_preference_refresh/`
  - `runs/host_goal_eval_20260608_124900_runtime_profile_trim_refresh/`
  - `runs/host_goal_eval_20260608_130836_runtime_drop_reuse_tags_refresh/`
  - `runs/host_goal_eval_20260608_145300_retrieval_despecialize_refresh/`
  - `runs/host_goal_eval_20260608_154800_executor_ambiguity_abstain_refresh/`
- 当前包内结果：
  - `pytest -q`：`49 passed`
  - `python -m runtime.smoke`：stdout 非空，并明确写明只验证 host sanity check
  - deterministic `repeat=10`：
    - `text/protocol` 都是 `task failure = 0`
    - `expectation_match_rate = 1.00`
    - `skipped_step_count = 9`
    - `reuse_gain = 0.17`
    - `memory_hit_rate = 0.80`
  - 与 `145300` 的 retrieval 去特化包相比，这一轮 executor ambiguity abstain 没有把 headline 打塌：
    - control bytes 仍保持：`306038 -> 290780`
    - deterministic task time 还略有收紧：`13016.83 -> 12949.40 ms`
    - `memory_hit_rate` 维持在 `0.80`
  - 这说明：
    - plan/runtime artifact 去特化确实开始反映到控制面与检索命中形态
    - 更诚实的 corpus retrieval 会让 assist hit rate 从旧线 `0.83` 回落到 `0.80`
    - 但 replay headline 仍然没有塌
    - executor 再加一层 close-call abstain 后，也没有把当前 host-mainline 稳定性打穿
  - executor candidate-tool 这一轮也已经闭环：
    - `tool_candidates` 只保留在 `FEATURE_BUNDLE`
    - execute payload 不再回灌 `tool_candidates`
    - 当前 repeat-10 仍稳定：`failure_count = 0`，`expectation_match_rate = 1.00`
  - executor ambiguity abstain 这一轮新增了两类定向回归：
    - close-call cross-route candidate 时应回退 `tool.collect_more_evidence`
    - 单一路径证据足够强时，不应被新 abstain 误伤
  - memory layer 这一轮虽然还没有单独归档成新的 formal `runs/...` 包，但当前 worktree 已完成定向回归：
    - `tests/test_memory_store.py` 新增 `memory_purpose` 分层筛选验证
    - `tests/test_smoke.py` 的 reuse / repeat-10 路径继续保持通过
    - 当前完整宿主机回归门更新为：
      - `pytest -q`：`49 passed`
      - `python -m runtime.smoke`：继续通过
  - exact replay gate 也进一步去特化：
    - current-task `preferred_corpus_doc_ids` 不再参与 `skip_retrieve_execute`
    - gate 只依赖 memory-archived query / route / evidence consistency
  - runtime profile 也进一步收窄：
    - `corpus_doc_ids` 已退成 task-level corpus hint
    - `RuntimeTaskProfile` 现在只保留 `runtime_reuse_contract`
  - runtime memory lookup 也进一步去 benchmark tag 化：
    - `reuse_tags` 不再参与 live memory query 预过滤
    - 新 deterministic repeat-10 仍稳定：`failure_count = 0`，`expectation_match_rate = 1.00`
    - control bytes 继续保持 `132735 -> 119008`（`text -> protocol`）

## 4. 还剩哪些结构问题

### 4.1 Task contract 不再直接写进 live plan；side-band profile 也已经缩小一层

这一步之前的问题是：

- `tasks/sample_tasks.py`
- `agents/sample_agents.py`

会把这些字段直接写进 live `PlanStep.params`：

- `corpus_doc_ids`
- `reuse_signature`
- `runtime_reuse_contract`

当前这条泄漏已经缩掉了：

1. planner prompt 不再看这些字段；
2. `build_plan()` 不再把这些字段塞进 live step params；
3. parser 即使收到带这些字段的 planner 输出，也只保留语义字段。
4. `skip_retrieve_execute` 现在也不再要求当前任务的 `preferred_corpus_doc_ids`。

但它还没有完全退回纯评测层，因为：

- `eval.runner` 仍会把 benchmark-derived `RuntimeTaskProfile` 和 task-level `corpus_doc_ids` 放进 `RunContext`
- 当前 `RuntimeTaskProfile` 虽然还会被挂进 `RunContext`，但 live agent 路径已经不再消费 `runtime_reuse_contract`
- `preferred_corpus_doc_ids` 现在已经退成 task-level 输入，当前主要只剩 retriever 的弱偏好先验

所以更准确的判断是：

> 当前已经从“plan-level gold leakage”退到“eval side-band + task-level weak hints”。
>
> 这是明显改进，但还不是完全泛化的 runtime。

### 4.2 Retriever 已不再做预裁剪，但检索层仍然偏 benchmark-shaped

`tasks/local_corpus.py` 现在不再先按：

- `task_group`
- `task_theme`

做候选集预裁剪；`task_group` / `task_theme` / `corpus_doc_ids` 现在都只剩弱加分。

所以这里的判断要更新成：

1. 先前最强的结构问题已经明显减弱。
2. 但当前检索仍然不是更一般化的 memory/retrieval 层。
3. 它仍更像 repo-local、benchmark-themed 的证据路由器，因为：
   - corpus 仍是 repo-local 样本集
   - route/tool families 仍是固定 contest playbook
   - negative controls 仍围绕既定 incident family 组织

### 4.3 exact replay 仍是受控 replay

`runtime/orchestrator.py` 里的 exact replay 仍要求：

- 同 `task_theme`
- 同 query
- 同 retrieved doc set
- route provenance / confidence 达标

这是合理的 host-side 诚实收缩，但也说明它还不是自然泛化的 memory reuse。

补充一点：

- 当前 assist memory 与 replay memory 已经显式分层
- 这一步让“fresh retrieval + memory assist”和“validated/exact replay 候选”终于不再共用同一个命中池
- 但 replay 仍然强依赖 route / query / doc-set / evidence 一致性，所以它还不是自然泛化的跨任务复用

### 4.4 executor 仍然主要是 route-to-playbook，但已经不再默认 top-1 即真

`runtime/executor_runtime.py` 里的 registry 仍对应固定 incident family。现在执行层已经多了一层小候选工具集检索，也多了一层 close-call abstain，但它总体仍然是：

> feature route / evidence -> ranked tool_candidates -> abstain or 固定工具 / playbook

所以当前最值得继续借鉴的方向已经从“补 playbook”转成“继续收紧候选工具检索”，而不是继续加 playbook。

## 5. GitHub 借鉴清单

### 5.1 `langgraph-bigtool`

1. 当前弱点：tool selection 仍然偏静态 route-to-playbook。
2. 对应仓库：`langgraph-bigtool`
3. 可借机制：把工具描述单独建索引，先做 `retrieve_tools`，再把小候选集交给执行层。
4. 为什么适合 StateBus：很适合当前 host-mainline，本地就能做，不需要改动 StatePool/MemoryStore 的主骨架。
5. 为什么不照搬：不需要把整个运行时换成 LangGraph，也不需要为“更多工具”先扩工具生态。

### 5.2 `langgraph`

1. 当前弱点：working state、checkpoint、长期记忆边界还不够清楚。
2. 对应仓库：`langgraph`
3. 可借机制：durable execution、checkpoint/persistence、short-term vs long-term memory 的明确分层。
4. 为什么适合 StateBus：当前已有 `RunContext + StatePool + MemoryStore`，很容易沿着这个边界继续收紧。
5. 为什么不照搬：不需要把 StateBus 改写成另一个图框架。

### 5.3 `semantic-router`

1. 当前弱点：route 还缺少更显式的 abstain / threshold discipline。
2. 对应仓库：`semantic-router`
3. 可借机制：route layer、no-match abstain、threshold optimization。
4. 为什么适合 StateBus：正好对应 `feature_route_confidence` 和 replay gate 的 host-side 收紧。
5. 为什么不照搬：不需要把全部 route 决策外包给新框架；StateBus 已经有自己的 feature bundle。

### 5.4 `haystack`

1. 当前弱点：retrieval / routing / memory / generation 的边界虽然存在，但对外解释和内部度量还不够透明。
2. 对应仓库：`haystack`
3. 可借机制：把检索、路由、记忆、生成做成显式 pipeline node，并保持 traceable 中间产物。
4. 为什么适合 StateBus：能帮助当前 benchmark 把“通信收益”和“复用收益”进一步拆开。
5. 为什么不照搬：生态过重，不值得替换当前 host-mainline。

### 5.5 `memsearch`

1. 当前弱点：memory true source 与向量索引的边界还不够清楚。
2. 对应仓库：`memsearch`
3. 可借机制：source-of-truth vs shadow index、progressive retrieval、hash-based dedup。
4. 为什么适合 StateBus：StateBus 很适合进一步把 SQLite/summary 视为真源，把 FAISS 视为可重建影子索引。
5. 为什么不照搬：跨平台代理插件体系与当前目标无关。

### 5.6 `AgentRx`

1. 当前弱点：replay misfire / false reuse 的定位还比较手工。
2. 对应仓库：`AgentRx`
3. 可借机制：trajectory IR、invariants、checker、failure report。
4. 为什么适合 StateBus：可以给 replay gate、negative control、route drift 做更审计化的诊断层。
5. 为什么不照搬：不应把当前 goal 变成重型诊断平台建设。

## 6. 当前阶段的诚实判断

如果必须二选一，我的判断是：

> **不是“现在只剩 tune/deepen”。**
>
> 更准确的说法是：**赛题 requirement closure 基本完成，但仍需先继续去特化，再进入深化。**

和这份审计前半段相比，判断有一个重要更新：

> `corpus_doc_ids` 的“硬过滤”问题已经不再是当前最主要 blocker。
>
> 现在更主要剩下的是：runtime 仍读取运行时合同 + task-level corpus hints，
> exact replay 仍偏受控、executor 仍主要是 route-to-playbook。

当前最合理的下一条主线只有一条：

1. 继续把 task-level corpus hints 和 runtime contract 分层，而不是再把这些字段塞回 plan。
2. 把 exact replay 的 gate 和 benchmark expectation 再拆开一层。
3. 继续把 executor 的候选工具检索做窄，而不是扩更多固定 playbook。
4. 把 structured vs text 的正式比较再拆成 control bytes / tokens / task_ms 三条线，并把“结构化优势”与“replay 优势”分开报。
5. 再做 matched negative controls，确认去特化之后 gain 没有完全塌掉。

补充：

- 关于“结构化 vs 文本怎样更诚实地显示速度和 token 优势”，当前已经单独落了一份分析：
  - `docs/progress/structured_vs_text_comparison_analysis_20260608.md`

在这几步之前，把项目描述成“主要只剩调优”，我认为不诚实。
