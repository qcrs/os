# StateBus 当前剩余问题收口方案与执行计划

日期：2026-06-15

适用范围：当前已提交树 `feat/contest-audit-hardening-20260615`，用于重新核对哪些问题已经落地、哪些问题仍然真实存在，以及后续如何继续收口。

前置文档：

- `docs/reference/题目.md`
- `docs/review/statebus_seven_issue_fix_plan_20260615.md`
- `docs/review/statebus_remaining_issues_and_solutions_20260615.md`
- `docs/review/statebus_remaining_issues_20260615.md`
- `docs/analysis/full_system_audit_20260615.md`
- `docs/analysis/implementation_manual.md`

---

## 一、结论先说

按“当前已提交树”重新核对后，之前很多问题已经不应该继续留在主问题清单里。

当前真正还没有闭合的问题，集中在两条主线：

1. `contest_dual_mode_controlled_v3` 的 formal headline benchmark 设计仍然不够硬。
2. formal retrieval / corpus 仍然只是“运行时 gate 禁止消费 hint”，不是“结构级完全去捷径化”。

换句话说，当前最需要继续做的，不是 planner / memory / typed-state 这些 support surface 的补丁，而是：

- 把 `contest` 的 task 设计重做到真的能让 protocol 的 structured state 在 correctness 上有展示空间；
- 把 formal retrieval 的候选空间和先验偏置进一步清掉，避免 formal headline 继续被 repo-private 元数据托着走。

如果这两件事不继续做，前面已经落地的 planner / memory / typed-state 收口只能算“支持面变干净了”，还不能把正式赛题 headline 讲硬。

---

## 二、已经落地、不该再算主问题的项

以下内容按当前树核对后，应从“主要遗留问题”中正式移除。

### 2.1 `memory_policy_controlled_v3` 不再只有一组 family

当前已经扩成 `checkout + auth` 两组，每组 4 个 policy 行，且测试已经锁住：

- `tasks/memory_policy_controlled_v3_benchmark.yaml:16`
- `tasks/memory_policy_controlled_v3_benchmark.yaml:204`
- `tests/test_smoke.py:1733`

当前事实：

1. `task_group` 已覆盖 `checkout_release_chain` 与 `auth_rotation_chain`
2. 每组都固定：
   - `mode=protocol`
   - `transfer_strategy=state_packet_minimal`
   - `handoff_profile=protocol_minimal_state_packet`
3. 每组都只改：
   - `runtime_reuse_contract`

因此，“memory formal surface 只剩 checkout 一组”的旧问题已经不成立。

### 2.2 `planner_support_v3` 缺 4-step validate 测试

当前已经补齐：

- LLM 行至少 2 个 4-step 任务：
  - `tasks/planner_support_v3_benchmark.yaml:513`
  - `tasks/planner_support_v3_benchmark.yaml:568`
- smoke 测试已经锁住：
  - `tests/test_smoke.py:3140`
  - `tests/test_smoke.py:3173`
- LangGraph 路径也验证了 `validate` 节点：
  - `tests/test_state_channels_and_graph.py:114`

因此，“planner support 缺少 4-step validate regression guard”的旧问题已经不成立。

### 2.3 typed-state 口径边界没有收紧

当前 `typed_state_mechanism_v3` 与 `typed_state_authenticity_v3` 的边界已经基本按计划收紧：

- `tasks/README.md:61`
- `tasks/README.md:63`
- `tasks/README.md:65`
- `tasks/README.md:66`
- `README.md:175`
- `README.md:179`
- `README.md:182`

当前读法已经明确：

1. `typed_state_mechanism_v3`
   - 是 active formal mechanism claim
   - 只读 protocol-only `natural_handoff_text` vs `state_packet_minimal`
2. `typed_state_authenticity_v3`
   - 只保留 legacy compatibility surface
   - 不再作为主机制 claim 入口
3. `memory_policy_controlled_v3`
   - 是唯一正式 memory attribution surface

因此，这条现在应读成“边界已收紧，但强度还可继续增强”，而不是“主问题尚未处理”。

---

## 三、当前真正仍然存在的问题

下面这些问题，在当前树里仍然真实存在，而且会直接影响赛题 formal headline 的说服力。

### P0-1：`contest_dual_mode_controlled_v3` 的 query 仍然直接泄漏答案词

核心表现：

- clean 行 query 直接出现 route 指示词：
  - `checkout`：`connection pool waits / slow orders query`
    - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:31`
  - `auth`：`issuer mismatch / stale jwks`
    - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:396`
  - `inventory`：`dropped aggregate invalidation rate`
    - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:761`
  - `billing`：`growing queue depth / tls reload retries`
    - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1122`
  - `deploy`：`pool exhaustion / changed connection caps`
    - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1491`

为什么这是问题：

1. `ToolRegistry.retrieve_candidates()` 本身就会吃 `query_text` 的词法命中
   - `runtime/executor_runtime.py:103`
   - `runtime/executor_runtime.py:117`
   - `runtime/executor_runtime.py:123`
2. 当 query 已经把 route 词写出来时，text 侧 executor 不需要真正读 evidence，就能从 query 直接猜到 route。
3. 这会直接压缩 protocol 的 correctness 展示空间。

这和赛题要求的冲突点在于：

- 赛题要验证的是“结构化通信 + 非文本状态传递”是否在相同任务条件下带来改进
- 不是验证“query 里直接写答案时，executor 能不能查字典”

对应评分项：

- 通信效率 25 分
- 状态传递创新 20 分
- 实验验证 15 分

### P0-2：clean / reusable 行仍然是单 route task

当前 `contest` 的 clean 与 replay_reusable 行，`acceptable_routes` 仍然只有 1 个：

- checkout clean：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:61`
- checkout replay：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:335`
- auth clean：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:426`
- auth replay：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:700`
- inventory clean：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:791`
- inventory replay：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1061`
- billing clean：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1152`
- billing replay：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1430`
- deploy clean：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1521`
- deploy replay：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1791`

为什么这是问题：

1. clean 现在被定义成“单 family 明确证据”，但它不应该退化成“单 route 无竞争命中”。
2. replay_reusable 更不应该还是单 route；否则第二题没有任何“复用前题排除/验证结果”的必要。
3. protocol 的 `EXECUTOR_DECISION_PACKET`、route provenance、candidate ranking 都无法在这类 case 上体现价值。

这与修复计划原合同不一致：

- 原计划要求每题至少允许 2 个 route family 被词法命中
- 当前只有 distractor / ambiguous 做到了部分多 route，clean / reusable 没做到

### P0-3：`contest_release_regression_corpus.yaml` 的证据拓扑没有真正重做

当前 corpus 的变化主要是字段层：

- `route_hint/tool_name` 改成 `eval_route_label/eval_tool_label`
- 但文档正文结构基本还是原来的“主证据 + 同 family 弱干扰”

典型表现：

- checkout 主证据与 ambiguity 文档仍然明显偏向同一路线：
  - `tasks/contest_release_regression_corpus.yaml:1`
  - `tasks/contest_release_regression_corpus.yaml:233`
- auth 同样如此：
  - `tasks/contest_release_regression_corpus.yaml:79`
  - `tasks/contest_release_regression_corpus.yaml:246`
- billing / deploy 也还是同结构：
  - `tasks/contest_release_regression_corpus.yaml:259`
  - `tasks/contest_release_regression_corpus.yaml:344`

为什么这是问题：

1. 当前 corpus 仍然太容易被 query 和 family 内弱干扰带着走。
2. 没有形成“incident / metrics / logs / ambiguity / scope-validation / cross-family distractor”的完整鉴别拓扑。
3. formal headline 需要的不是“换了字段名的旧 corpus”，而是能让证据 provenance 真正决定 route 的 corpus。

### P0-4：formal corpus 只是“当前不消费 hint”，不是“结构级去 hint”

当前 formal runtime hint 的确被 gate 关掉了：

- `tasks/sample_tasks.py:250`
- `agents/sample_agents.py:1880`

测试也已经覆盖：

- `tests/test_smoke.py:1762`

但结构上仍然保留了完整 runtime hint 通道：

1. `CorpusDoc` 仍有 runtime 字段
   - `tasks/local_corpus.py:17`
   - `tasks/local_corpus.py:23`
   - `tasks/local_corpus.py:24`
2. loader 仍兼容旧字段
   - `tasks/local_corpus.py:68`
   - `tasks/local_corpus.py:69`
3. runtime hint extractor 仍可直接读它们
   - `tasks/local_corpus.py:171`
   - `tasks/local_corpus.py:199`
4. `candidate_ids` 仍会把 `preferred_doc_ids` 并进 shortlist
   - `tasks/local_corpus.py:147`
5. `retrieve_corpus_docs()` 仍用 theme/group/tag/doc-id 这些 repo-private 先验给 formal retrieval 塑形
   - `tasks/local_corpus.py:106`
   - `tasks/local_corpus.py:107`
   - `tasks/local_corpus.py:111`
   - `agents/sample_agents.py:298`
   - `agents/sample_agents.py:301`
   - `agents/sample_agents.py:302`
   - `agents/sample_agents.py:303`

为什么这比“hint 字段还在”更严重：

即使 `route_hint` 已经不消费，formal retrieval 仍然不是开放候选鉴别，而是：

1. 任务先通过 `task_group/task_theme/tags/corpus_doc_ids` 给出强先验
2. retrieval 再在这个被强塑形的局部空间里排序
3. text / protocol 最终都共享同一条高度受控的 route 候选空间

所以这条问题不能只写成“字段还在”，而应该写成：

> 当前 formal pack 只是 runtime-level gate safe，不是 structure-level retrieval clean。

### P0-5：contest 的 reusable 题仍然不是真正的跨任务依赖

当前 replay_reusable 行更像“同 family follow-up 改写”：

- checkout replay：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:306`
- auth replay：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:671`
- inventory replay：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1034`
- billing replay：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1403`
- deploy replay：
  - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml:1762`

同时，`SampleTask` 虽然已经支持 `replay_source_task_id`：

- `tasks/sample_tasks.py:295`

但当前 contest rows 并没有把它用成明确依赖合同。

为什么这是问题：

1. 第二题并不要求使用第一题的排除结论或验证门。
2. 第二题也不要求消费前题形成的 scoped action。
3. 这会削弱赛题“至少 2 组具有关联性的连续任务”和“记忆复用效果 20 分”的说服力。

### P1-1：当前 planner support 已不是“没做”，但仍然偏显式提示触发

这一条不再是主遗留问题，但仍值得记录为“还不够强”：

1. 现在的 4-step validate case 基本是通过 goal/query 显式写入
   - `tasks/planner_support_v3_benchmark.yaml:524`
   - `tasks/planner_support_v3_benchmark.yaml:579`
2. 当前测试只证明“它已经能跑、能产出 4-step”
   - `tests/test_smoke.py:3154`
   - `tests/test_smoke.py:3173`

因此它当前的正确读法是：

- “已实现并有 regression guard”
- 不是“仍缺失”
- 但也不是“planner-sensitive taxonomy 已经足够自然”

---

## 四、为什么这些问题必须继续做

赛题原文要求的不是“系统里存在这些对象”，而是“通过可复现实验验证该机制相较传统纯文本协作方式在通信开销、任务时延和记忆复用方面的改进效果”。

对应 `docs/reference/题目.md`，当前剩余问题直接卡住了 3 个评分项：

1. 通信效率 25 分
   - 如果 query 直接泄漏答案，protocol 的结构化 route 传递无法解释 correctness
2. 状态传递创新 20 分
   - 如果 task 不存在 route/tool 竞争，`EXECUTOR_DECISION_PACKET` 的机制价值就只能停留在“存在性”
3. 实验验证 15 分
   - 如果 corpus / retrieval 仍带强 repo-private 先验，formal headline 的说服力会明显不足

记忆复用 20 分当前不再是主 headline 问题，因为 `memory_policy_controlled_v3` 已经承担了正式 memory attribution surface；但 contest reusable 题如果继续太弱，会影响整套系统叙事的一致性。

---

## 五、修复思路：不是最小改动，而是重做 contest formal contract

本轮后续工作建议遵循下面的原则。

### 5.1 不动的决策

以下决策建议继续保持，不再来回摇摆：

1. `contest_dual_mode_controlled_v3`
   - 继续作为唯一 formal headline
2. `plan_source_default`
   - contest 保持 `yaml`
   - planner 证据继续单独放 `planner_support_v3`
3. memory
   - 不重新塞回 contest dual-mode headline
   - 正式 memory attribution 继续由 `memory_policy_controlled_v3` 承担
4. open surface
   - 继续保持 audit-only
   - 不并入 formal headline

### 5.2 必须重做的对象

必须重做的不是 support surface，而是下面 3 个对象：

1. `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`
2. `tasks/contest_release_regression_corpus.yaml`
3. `tasks/local_corpus.py`

### 5.3 修复目标

目标不是简单“把 hint 清空”，而是做到下面 4 点：

1. query 不能单跳猜中
2. evidence 必须跨文档组合
3. distractor 必须足够强，最好跨 family
4. reusable 必须显式消费前题的排除/验证结果

---

## 六、外部资料：本轮必须读什么

本轮不建议直接套用外部数据集，但建议明确借鉴它们的构造原则。

下面这些资料建议分成“必须读”和“建议读”。

### 6.1 必须读

#### 1. HotpotQA

资料：

- Yang et al., *HotpotQA: A Dataset for Diverse, Explainable Multi-hop Question Answering*
- arXiv: `1809.09600`
- 链接：<https://arxiv.org/abs/1809.09600>

必须读的原因：

1. 它最适合学“supporting facts 必须跨文档组合”
2. 它明确把“答案”和“支撑证据”同时定义出来
3. 对 StateBus 的映射最直接：
   - supporting facts -> contest corpus 主证据链
   - sentence-level supervision -> provenance-aware route justification

本轮重点借鉴：

1. 多文档支撑事实
2. comparison / bridge 结构
3. 不能单靠一个局部片段猜对

#### 2. MuSiQue

资料：

- Trivedi et al., *MuSiQue: Multihop Questions via Single-hop Question Composition*
- arXiv: `2108.00573`
- 链接：<https://arxiv.org/abs/2108.00573>

必须读的原因：

1. 它最适合学“如何反 shortcut”
2. 它强调 compositional、connected reasoning
3. 对当前 StateBus 最重要的启发是：
   - query 不能泄漏单一跳答案
   - 第二步必须依赖第一步

本轮重点借鉴：

1. connected reasoning
2. bottom-up question composition
3. 用结构设计避免 lexical shortcut

#### 3. BRIGHT

资料：

- Su et al., *BRIGHT: A Realistic and Challenging Benchmark for Reasoning-Intensive Retrieval*
- arXiv: `2407.12883`
- 链接：<https://arxiv.org/abs/2407.12883>

必须读的原因：

1. 它最适合学“检索难度如何做得现实而不是表面 keyword 匹配”
2. 它强调高相似候选中的鉴别性检索
3. 这正对应当前 contest 的核心短板：
   - query lexical hit 太强
   - distractor 太弱

本轮重点借鉴：

1. reasoning-intensive retrieval
2. difficult negatives
3. similarity-high but provenance-different candidates

#### 4. LongMemEval

资料：

- Wu et al., *LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory*
- arXiv: `2410.10813`
- 链接：<https://arxiv.org/abs/2410.10813>

必须读的原因：

1. 它最适合学“后续问题如何真正依赖前文记忆”
2. 它把 memory 问题拆成 retrieval / reading / temporal reasoning / update / abstention
3. 对当前 StateBus 的 reusable 题重做很有参考价值

本轮重点借鉴：

1. multi-session reasoning
2. temporal / scoped follow-up
3. 后续问题必须消费历史上下文

### 6.2 建议读

#### 5. MoreHopQA

资料：

- *MoreHopQA: More Hops, More Thoughts, More Complex Answers for Multi-hop QA*
- arXiv: `2406.13397`
- 链接：<https://arxiv.org/abs/2406.13397>

建议读的原因：

1. 它强调在已有 multi-hop 上继续增加真实推理深度
2. 对“contest reusable 不是同义改写，而是新增约束条件后的 follow-up”很有参考价值

#### 6. ToolRet

资料：

- Shi et al., *Retrieval Models Aren't Tool-Savvy: Benchmarking Tool Retrieval for Large Language Models*
- arXiv: `2503.01763`
- 链接：<https://arxiv.org/abs/2503.01763>

建议读的原因：

1. 当前 StateBus contest 不只是 route 选择，还有 tool 分支选择
2. ToolRet 对“tool retrieval 不该靠预注解小候选集”这一点很有启发

---

## 七、具体修复方案

下面给出一版可直接执行的修改方案。

### 7.1 重做 `contest_dual_mode_controlled_v3_benchmark.yaml`

#### 目标

让 contest formal headline 真正回答：

1. protocol 的 structured handoff 是否降低通信成本
2. protocol 的 typed-state handoff 是否在困难任务上带来 correctness 空间

#### 修改原则

1. 保持外层合同不变：
   - `public_surface = formal_headline`
   - `plan_source_default = yaml`
   - `runtime_reuse_contract = reuse_disabled`
   - `variable_axes = [mode, handoff_object]`
2. 保持总结构不变：
   - 5 family × 4 complexity × 2 mode = 40 行
3. 彻底改写每个 family 的四类 case 语义：
   - `simple`
   - `distractor`
   - `ambiguous`
   - `reusable`

#### 新的 case 设计合同

##### `simple`

不是“单 route 无竞争”，而是：

1. query 至少词法命中 2 个 route family
2. 但 evidence provenance 明确偏向一个主 family
3. `acceptable_routes` 至少 2 个
4. `acceptable_tools` 至少 2 个

##### `distractor`

1. query 同样命中多个 route family
2. 至少引入 1 个跨 family 强 distractor doc
3. distractor 文档质量不能只是弱回忆片段，必须是“真竞争解释”

##### `ambiguous`

1. 主路径与竞争路径都要有实质证据
2. 允许：
   - bounded alternative
   - 合法 abstain
3. 必须靠 provenance / scope / validation 选择下一步，而不是只靠词法

##### `reusable`

1. 第二题必须显式依赖前题产出的排除项或验证结论
2. query 不直接复述第一题答案
3. 建议新增字段：
   - `replay_source_task_id`
   - `required_prior_conclusion`
   - `required_prior_scope`
4. 如果不想新增太多字段，至少要在 case contract 层显式声明：
   - 第二题只有在知道第一题已排除某竞争路线时才能正确回答

#### 修改建议

建议把每个 family 重写成下面这种结构：

1. `simple`
   - “同一 rollout slice 上同时出现 A/B 两类表面症状，但 scope-validation 只支持 A”
2. `distractor`
   - “另一个 family 的旧 incident 文档与当前症状高度相似”
3. `ambiguous`
   - “两个 family 都有部分证据成立，且允许 collect-more-evidence”
4. `reusable`
   - “沿用前题已确认的 rollout slice / validation gate / ruled-out hypothesis，要求 scoped follow-up”

### 7.2 重做 `contest_release_regression_corpus.yaml`

#### 目标

让 corpus 真正支撑 `contest` 的多候选鉴别，而不是继续当作“写了 eval label 的轻量样本文本”。

#### 每个 family 推荐的文档拓扑

每个 family 至少 6 类文档：

1. `incident`
2. `metrics`
3. `logs`
4. `scope_validation`
5. `ambiguity`
6. `cross_family_distractor`

#### 具体要求

1. `incident`
   - 提供现象，但不要直接把 root cause 说死
2. `metrics`
   - 提供定量信号
3. `logs`
   - 提供过程性信号
4. `scope_validation`
   - 提供 canary shard / tenant slice / rollout region 等 scope 约束
5. `ambiguity`
   - 保留竞争解释，不直接 overturn 主路线
6. `cross_family_distractor`
   - 来自其他 family 的相似旧事故，且表面非常像

#### 重要要求

1. 文档正文中避免过强的 route label wording
2. 把判断逻辑放在证据组合里，而不是单个 doc 的一句话里
3. 文档之间应该形成：
   - 主证据组合
   - 竞争解释组合
   - scope / validation 排除点

### 7.3 清理 `tasks/local_corpus.py` 的 formal retrieval 偏置

#### 目标

从“formal 不消费 route_hint”升级到“formal retrieval 不依赖 repo-private runtime shortcut”。

#### 建议修改

##### 1. `CorpusDoc` 拆分 runtime-only 与 eval-only 字段

当前：

- `tasks/local_corpus.py:17`

建议改成：

1. formal 主路径只保留：
   - `eval_route_label`
   - `eval_tool_label`
2. runtime hint 字段只在 audit/training 兼容层保留
3. 最好增加显式参数：
   - `allow_legacy_runtime_hints`

##### 2. formal path 去掉 `preferred_doc_ids` 参与 shortlist

当前：

- `tasks/local_corpus.py:147`

建议：

1. formal path 下不要把 `preferred_doc_ids` 并进 `candidate_ids`
2. 最多只保留 eval side 对 doc coverage 的核对，不进入 runtime retrieval

##### 3. formal path 下压低或关闭 group/theme/tag bonus

当前：

- `tasks/local_corpus.py:106`
- `tasks/local_corpus.py:107`

建议：

1. formal contest pack 增加 retrieval contract：
   - `retrieval_bias_mode: evidence_first`
2. 在这个模式下：
   - `theme_bonus = 0`
   - `group_bonus = 0`
   - tag overlap 权重显著降低
3. 保留 audit/training pack 的旧行为

##### 4. `extract_corpus_feature_hints()` 仅限 audit path

当前：

- `tasks/local_corpus.py:171`

建议：

1. 不删除兼容逻辑
2. 但 formal path 读 loader 后根本不生成 runtime hint 字段
3. `resolve_corpus_feature_hint()` 应只在 audit/training 调用中有意义

### 7.4 强化 reusable / replay 依赖合同

#### 目标

把 reusable 从“换个说法的 follow-up”升级成“必须消费前题结论的 follow-up”。

#### 建议新增字段

在 `SampleTask` 上增加以下 eval-only / runtime-contract 字段：

1. `required_prior_case_id`
2. `required_prior_route_exclusion`
3. `required_prior_validation_gate`
4. `required_prior_scope`

如果不想一次加太多字段，最少也要加：

1. `required_prior_case_id`
2. `required_prior_conclusion`

建议位置：

- `tasks/sample_tasks.py:281`

#### 运行时读法

1. contest formal pack 仍然 `reuse_disabled`
2. 但 benchmark case contract 应显式要求：
   - 第二题正确答案必须引用第一题已经确认或排除的事实
3. memory formal pack 再把同构语义投影到：
   - `assist_allowed`
   - `validated_replay`
   - `exact_replay`

### 7.5 继续保留 `planner_support_v3`，但可增强 taxonomy

这一条不是当前主 blocking issue，但如果继续增强，建议方向是：

1. 不再只靠 query 里显式写：
   - `validate the route before execution`
2. 增加更自然的 planner-sensitive task 类型：
   - `validate-first`
   - `competing-hypothesis`
   - `scope-then-execute`

---

## 八、具体修改计划

下面给出一版按文件拆开的执行计划，优先级按 P0 -> P1 排。

### Phase 1：先把 contest 合同重写

#### 文件

- `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`

#### 动作

1. 重写 5 个 family 的 query
2. 每个 family 的 clean / reusable 行都改成多 route 命中
3. 每个 family 的 reusable 行都改成显式前题依赖
4. 补充：
   - `acceptable_routes`
   - `acceptable_tools`
   - `disallowed_families`
   - 必要的 prior-dependency 合同字段

#### 验收

1. clean / reusable 行不再只有 1 个 acceptable route
2. query 不再直接出现单一路由直指词
3. 至少存在跨 family distractor case

### Phase 2：重写 corpus 证据拓扑

#### 文件

- `tasks/contest_release_regression_corpus.yaml`

#### 动作

1. 每个 family 统一补齐 6 类文档角色
2. 新增跨 family distractor 文档
3. 强化 ambiguity / scope-validation 文档
4. 避免在单文档文本里直接写死 root cause

#### 验收

1. 每个 family 都有：
   - incident
   - metrics
   - logs
   - scope_validation
   - ambiguity
   - cross_family_distractor
2. corpus 可以支撑：
   - multi-route lexical hit
   - evidence provenance disambiguation

### Phase 3：清理 formal retrieval 偏置

#### 文件

- `tasks/local_corpus.py`
- `agents/sample_agents.py`
- 如有必要：`tasks/sample_tasks.py`

#### 动作

1. formal path 下移除 runtime hint 可见面
2. formal path 下关闭 preferred doc bias
3. formal path 下引入 `evidence_first` retrieval bias contract
4. 将 runtime hint 兼容逻辑收缩到 audit/training surface

#### 验收

1. formal loader 只暴露 eval label
2. formal runtime hint 返回空
3. formal retrieval shortlist 不再自动并入 preferred doc ids
4. formal retrieval 不再依赖 task_group/task_theme 的强 bonus

### Phase 4：把 replay 依赖写成显式合同

#### 文件

- `tasks/sample_tasks.py`
- `tasks/contest_dual_mode_controlled_v3_benchmark.yaml`
- `tasks/memory_policy_controlled_v3_benchmark.yaml`

#### 动作

1. 给 reusable follow-up 新增 prior-dependency 字段
2. 让 contest reusable 明确依赖前题排除项 / validation gate
3. 让 memory policy pack 的第 2/3/4 行显式消费第 1 行产出的 replay-eligible context

#### 验收

1. contest reusable 不再是纯改写 query
2. memory policy pack 的 2/3/4 行不再只是同 query 重跑

### Phase 5：补 regression tests

#### 文件

- `tests/test_smoke.py`
- 如需要：`tests/test_state_channels_and_graph.py`

#### 必补测试

1. contest query leakage regression
   - clean / reusable 行 query 不得包含 route 直指词白名单
2. contest multi-route contract
   - clean / reusable 行至少 2 个 acceptable routes
3. contest cross-family distractor contract
   - 至少存在跨 family distractor case
4. formal retrieval cleanliness
   - formal path runtime hint 为空
   - formal path preferred doc bias 关闭
   - formal path 不再自动并入 preferred doc ids
5. replay dependency contract
   - reusable 行必须声明 prior dependency
6. planner support 继续保留当前 4-step regression guard

---

## 九、推荐的最终执行顺序

建议按下面顺序推进，而不是穿插小修小补：

1. 先改 `contest_dual_mode_controlled_v3_benchmark.yaml`
2. 再重写 `contest_release_regression_corpus.yaml`
3. 然后改 `tasks/local_corpus.py` 的 formal retrieval contract
4. 再补 `SampleTask` 的 reusable dependency 字段
5. 最后统一补 tests 和文档 wording

原因很简单：

1. contest 合同不先改，后面的 retrieval 清理没有明确目标
2. corpus 不先改，query 去 leakage 也只会变成“换个说法的旧题”
3. retrieval contract 不改，formal 仍然会被 repo-private 先验托着走

---

## 十、一句话定性

当前真正还没做完的，不是 planner / memory / typed-state support surface，而是：

> `contest formal headline` 的 task/corpus/retrieval 设计还没有重构到足以支撑正式赛题结论。

如果这条不继续做，当前树只能诚实地说：

1. formal surface 边界比以前干净了
2. planner / memory / typed-state 的 supporting evidence 更完整了
3. 但 contest headline 仍然需要继续重构，才能成为真正可讲硬的正式赛题主结论
