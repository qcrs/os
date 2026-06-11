# `docs/analysis` 现状价值与当前赛题缺口审计

日期：`2026-06-10`

适用范围：审计当前 `docs/analysis/` 里的文档，到底还能不能帮助解决现在的赛题问题和当前代码问题，尤其是：

- benchmark 构造
- memory 设计与复用
- 结构化/状态传递

这份文档不是旧方案的复述，而是一次当前态交叉审计。结论基于四类证据一起看：

- 当前约束与主线文档
  - `README.md`
  - `docs/constraints/current_host_and_migration.md`
  - `docs/constraints/current_feature_scope.md`
  - `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`
  - `docs/planning/contest_object_benchmark_mechanism_plan_20260610.md`
  - `docs/reivew/review_0609_2313.md`
- 当前代码
  - `tasks/sample_benchmark.yaml`
  - `tasks/sample_tasks.py`
  - `runtime/task_profile.py`
  - `runtime/orchestrator.py`
  - `agents/sample_agents.py`
  - `runtime/executor_runtime.py`
  - `memory/store.py`
  - `statepool/store.py`
  - `eval/runner.py`
  - `runtime/contracts.py`
  - `runtime/codeact_runner.py`
- `docs/analysis/` 现有文档
- 已归档 formal run
  - `runs/host_goal_eval_20260610_phase5_formal_controlled_api_r1/benchmark_report.md`
  - `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/benchmark_report.md`
  - `runs/host_goal_eval_20260610_state_transfer_refresh_api_repeat3_serial/benchmark_report.md`

---

## 1. 先给结论

一句话判断：

> `docs/analysis/` 现在仍然有价值，但它更像“问题地图 + 历史推演 + 方案草图”，已经不能当“当前事实层主文档”来用。

更具体地说：

1. **有帮助的部分是真问题识别，不是旧执行细节。**
   - `benchmark_task_and_result_analysis.md` 对 benchmark 公平性、aggregate 误导、assist-only 边界的批评，今天仍然有价值。
   - `third_party_analysis_and_borrowable_patterns.md` 作为模式库有参考价值。
   - `code_audit_competition_check_and_solution_roadmap.md` 与 `final_adjusted_plan.md` 的价值主要在于“曾经把什么看成问题”，不是“现在应该照做什么”。

2. **最容易误导人的，是把这些文档当成当前代码真相。**
   - 很多文档写的是 `29-task`、`475 行`、`transfer lane 缺 text 对照`、`Planner 还没接上`、`要恢复某个 pack`。
   - 当前代码已经不是那个状态。
   - 但它也没有完全达到这些文档承诺的终点，所以“旧问题已完全解决”同样不成立。

3. **当前真正该看的不是旧 `docs/analysis`，而是“新计划文档 + 当前代码 + 最新重跑结果”。**
   - 现在的主线事实已经明显前移到：
     - `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`
     - `docs/planning/contest_object_benchmark_mechanism_plan_20260610.md`
     - `docs/reivew/review_0609_2313.md`
     - 当前 task pack / runner / orchestrator / memory / executor 代码

4. **就当前赛题问题而言，最大的真实缺口已经不是“没有想法”，而是“当前 formal 叙事仍然不够收口”。**
   - benchmark pack 还混了太多内部回归和开放探索对象
   - memory 的 headline 仍然窄，主要成立在 replay/skip 路线
   - state transfer 的真实性叙事比效率叙事更强，不能混说
   - 一些看起来很亮点的东西其实还没有真正进主路径

5. **比旧分析是否过时更严重的，是当前 formal 证据层自己也在漂。**
   - `26-task`、`29-task`、`38-task` 报告同时存在
   - 当前 `tasks/sample_benchmark.yaml` 又已经是 `30-task`
   - 所以今天最大的 benchmark 文档风险，不只是“旧分析旧了”，而是“当前 repo 自己也没有把 headline evidence 冻结成单一版本”

---

## 2. 哪些分析文档现在还有用，哪些应该降级

### 2.1 仍然值得保留的

#### `benchmark_task_and_result_analysis.md`

这是当前 `docs/analysis/` 里最有保留价值的一篇。

原因不是它的数字永远最新，而是它抓住了三个长期有效的问题：

- aggregate 视图会误导
- 必须按 claim lane 看 benchmark
- `assist_only` 不能被包装成 headline

但它有两个明显漂移：

- 它基于 `29-task` formal pack 写，当前 `tasks/sample_benchmark.yaml` 头部已经写成 `30-task` pack，且 task 组成已变化
- 它把 state transfer 的问题写成“缺 text 对照”，这在当前代码里已经被 `mode_split_text_brief_vs_state_ref` 修过了

所以它现在的正确用途是：

- 当“问题来源说明”
- 当“为什么要做 benchmark fairness 收口”的依据

不是：

- 当当前 pack 的精确结构说明
- 当当前 runner/report 的精确行为说明

#### `third_party_analysis_and_borrowable_patterns.md`

它的价值在“借模式”，不在“给当前 repo 下硬执行命令”。

今天仍然值得保留的部分：

- 记忆分层
- 多信号检索
- route / typed channel / invariant 这些思路的比较框架

今天必须降级的部分：

- 任何把参考仓库模式直接当成“当前已实现能力”的表达
- 任何跳过 contest object 边界、直接追求架构花样的部分

#### `code_audit_competition_check_and_solution_roadmap.md`

这篇文档今天仍有价值，但只剩两层价值：

- 它把赛题要求和仓库模块做过一次系统对照
- 它保留了“哪些地方曾经被认为是 P0/P1 问题”的历史记忆

它现在已经不适合作为当前实施指南。

原因很简单：

- 它把很多“当时未落地”的事项当成待做
- 当前代码里其中一部分已经落地，一部分只落了一半，一部分则仍然只是文件级预留
- 如果今天还按它的 Phase 顺序直接推进，很容易重复做已经发生过的工作，或者把支线误当主线

### 2.2 现在应降级为“历史方案/草图”的

#### `final_adjusted_plan.md`

这篇文档最有价值的地方，是它把旧方案做过一次优先级压缩。

但它现在已经不适合当“当前执行计划”。

主要原因：

- 当前 repo 后续又出现了更强的主线约束文档
- 它仍然把很多今天已经偏离主线的对象留在计划里
- 它默认 formal pack、open-plan、memory、typed channel、delta、CodeAct 还能放在同一条连贯实施线上，这在今天已经过宽了

#### `implementation_manual.md`

这篇文档现在是最危险的。

原因不是它差，而是它太像“照着改就行”，但很多前提已经失真。

例如：

- 它前面还在写“恢复 `475` 行、`29-task` pack”
- 它把很多后来已落地的改动仍然写成未做事项
- 它把 `ChannelKind`、`DeltaPlanStep`、`CodeAct`、`InvariantChecker` 都写成主路径连续推进项，但今天这些对象在代码里的成熟度完全不同

它现在只能当：

- 历史实施记录
- 检查“曾经想改什么”的备忘

不能当：

- 当前实施真相
- 当前改动清单

#### `novel_design_content_addressed_state_fabric.md`

这篇文档对“赛后演进方向”有价值，对“解决当前 contest 交付问题”帮助很有限。

根因不是它思路差，而是它离当前主路径太远：

- 当前主路径仍然是 `StateRef + mmap/shared_memory + FEATURE_BUNDLE`
- CAS 相关接口虽然已经在 `statepool/store.py` 和 `protocol/messages.py` 里出现，但主运行时根本没把它当正式 handoff/data-plane
- 如果今天继续沿这条线展开，很容易把精力从 benchmark 收口、memory 边界、state-transfer 真实性，转移到一个未接主线的新架构上

### 2.3 现在主要是分支考古材料的

- `CHANGES.md`
- `BRANCH_CHANGES_REFERENCE.md`
- `CODE_REVIEW_PROMPT.md`

这几份文档对“理解 `feat/contest-hardening` 这条线想干什么”有帮助。

但对“今天该怎么解决当前赛题问题”帮助有限，甚至可能误导。

原因：

- 它们把分支目标、已落地事项、未接主路径的预留能力写在一起
- 某些数字已经和当前代码不一致
  - 例如 task 数、pack 结构、某些功能是否真正进入 run path
- 它们更像变更叙事，不像当前事实层

---

## 3. benchmark 构造：哪些分析还有帮助，哪些已经过时

## 3.1 现在仍然成立的好判断

旧分析里有三条 benchmark 判断今天仍然正确：

1. **不能拿 aggregate 当 headline。**
2. **必须按 communication / state_transfer / memory 分 lane 读。**
3. **assist_only 不能包装成已经成立的正式收益。**

这三条现在不仅还对，而且已经写进当前代码/报告口径：

- `eval/runner.py:2345-2348`
- `eval/runner.py:2638-2641`
- `eval/runner.py:2285`

说明旧分析至少在 benchmark honesty 这件事上，方向是对的。

## 3.2 当前代码里 benchmark 已经比旧分析先进了什么

这部分必须说清楚，否则会误判今天的代码还停在旧问题上。

当前 repo 已经出现了四个重要进步：

1. **task pack 已经被显式拆型。**
   - `tasks/sample_tasks.py:25-61`
   - 当前不是只有一个 pack，而是：
     - `formal_controlled`
     - `state_transfer_authenticity`
     - `state_transfer_carrier`
     - `state_transfer_natural_support`
     - `communication`
     - `memory`
     - `open_validation`

2. **formal pack 里的 state transfer 已不是“纯 protocol-only carrier 对比”。**
   - `tasks/sample_benchmark.yaml:225-275`
   - `runtime/task_profile.py:99-103`
   - `runtime/orchestrator.py:546-547`
   - 当前通过 `mode_split_text_brief_vs_state_ref`，text 模式会走 `text_brief`，protocol 模式会走 `state_ref`

3. **report 已经显式把 protocol-only state-transfer 子结论单独拿出来。**
   - `eval/runner.py:2226-2256`
   - `eval/runner.py:2688-2723`

4. **formal report 已经承认 state-transfer 的 headline 应该从 dedicated handoff metrics 读，不该从 aggregate state_bytes 读。**
   - `eval/runner.py:2347-2348`

换句话说，旧文档中“benchmark 完全没分开”的批评，已经不再是今天的真实状态。

但这也不是说当前拆型已经完全收口。

- `communication` 的 dedicated pack 仍然只有 `2` 个 cache task：
  - `tasks/communication_benchmark.yaml:1-44`
- 而当前 formal pack 里的 communication lane 已经扩成 `6` 个跨 domain task：
  - `tasks/sample_benchmark.yaml:279-431`

这说明现在的 pack split 是“方向对了”，不是“已经统一成一个干净证据体系了”。

## 3.3 但当前 benchmark 仍然有三个硬伤

### 硬伤 1：formal pack 还是混得太杂

当前 `tasks/sample_benchmark.yaml` 头部仍自称：

- `Controlled 30-task ... formal communication, state_transfer, and replay-scoped memory claims`
  - `tasks/sample_benchmark.yaml:1-6`

但实际 task 构成仍然是：

- `internal_regression`: `18`
- `communication`: `6`
- `state_transfer`: `3`
- `memory`: `3`

这意味着：

- `60%` 的 formal pack 仍然不是 headline claim task
- 其中还混入了：
  - `lexical_override` 回归任务
    - `tasks/sample_benchmark.yaml:433-485`
  - `open-plan-*` LLM 规划任务
    - `tasks/sample_benchmark.yaml:487-533`

问题不在于这些任务“不能存在”，而在于：

> 它们不该和 formal headline pack 绑在一起。

因为这会导致 formal pack 同时承担三种角色：

- 赛题 headline 对照
- route 回归验证
- planner 开放探索

这会让报告和答辩口径很难收。

### 硬伤 2：runner 口径比旧版诚实了，但还不够彻底

当前 report 虽然加了很多 boundary note，但第一页仍然先给 `Aggregate`。

对应代码：

- `eval/runner.py:2345-2348`
- `eval/runner.py:2636-2641`

这比旧版好多了，但仍有一个现实问题：

> 评委首先看到的还是 aggregate 表，而不是 fair claim surface。

如果真的要为比赛读者优化，现在更合理的顺序应该是：

1. `Structured-vs-Text By Reuse Axis`
2. `Contest Claim Lane Deltas`
3. `Protocol-Only Typed-Handoff Authenticity` / carrier / natural support
4. 最后才是 aggregate

否则仍然会出现“口头上说 aggregate 不能直接读，但视觉上还是先展示它”的矛盾。

### 硬伤 3：旧 run 证据和当前 pack 已经漂移

`benchmark_task_and_result_analysis.md` 以及被它引用的 formal run，主要还是围绕旧的 `29-task` 结构写的。

但当前 `tasks/sample_benchmark.yaml` 已经是 `30-task` 版本：

- `tasks/sample_benchmark.yaml:1-6`

而且 task 族已经变成：

- 两条 replay chain
- 三个 state_transfer 比较 task
- 六个 communication task
- 三个 memory task
- 三个 lexical override
- 三个 open-plan

这意味着：

> 旧分析的“问题识别”还能用，旧分析的“数字结论”和“pack 结构结论”不能直接当今天真相。

所以现在最缺的不是再写一篇分析，而是：

- 以当前 `30-task` pack 重跑
- 或者更进一步，把 formal headline pack 继续拆窄后重跑

## 3.4 现在更麻烦的是：formal artifact 自己也已经多版本漂移

如果只是“旧 `29-task` 分析落后于今天代码”，问题还没这么大。

更大的问题是：当前 repo 里并排放着多套都像“formal 主证据”的报告，但它们对应的对象其实不同。

### 版本 A：`26-task`

- `runs/host_goal_eval_20260610_phase5_formal_controlled_api_r1/benchmark_report.md`
- 特征：
  - `Repeat: 1`
  - `Continuous tasks per run: 26`
  - text / protocol task 数对称
  - `state_transfer` 已经有 text 侧
- 它更像：
  - 一个较新的 phase checkpoint
  - 不是稳定性足够的 headline formal package

### 版本 B：`29-task`

- `runs/host_goal_eval_20260610_113710_controlled_api_repeat3_serial/benchmark_report.md`
- 特征：
  - `Repeat: 3`
  - `Continuous tasks per run: 29`
  - text=`23` / protocol=`29`
  - `state_transfer` 仍然是 protocol-only 旧口径
- 它更像：
  - 旧 formal repeat-3 读数
  - 不是今天代码状态的直接镜像

### 版本 C：`38-task`

- `runs/host_goal_eval_20260610_state_transfer_refresh_api_repeat3_serial/benchmark_report.md`
- 特征：
  - `Repeat: 3`
  - `Continuous tasks per run: 38`
  - text=`23` / protocol=`38`
  - `state_transfer` 被扩成 `15` 个 task，并把 authenticity / carrier / natural support 都并进 formal report
- 它的问题是：
  - state-transfer 叙事更细了
  - 但 aggregate 和 protocol 总体开销又被大幅污染了
  - 它更像一次 state-transfer 刷新试验，不像稳定的 headline pack

### 版本 D：当前代码 `30-task`

- `tasks/sample_benchmark.yaml:1-533`
- 特征：
  - `30-task`
  - formal pack 内混有 `lexical_override`
  - formal pack 内混有 `open-plan-*`
  - 这版 YAML 还没有对应的 repeat-3 headline report 被明确立起来

### 这件事为什么严重

这已经不是简单的“analysis doc 有点旧”，而是：

> 当前 repo 里的 formal benchmark 叙事本身没有冻结成单一对象。

直接后果是：

1. `README.md` 里的 “latest” 很容易被误读成“当前代码对应的最新主证据”。
2. `docs/analysis` 任何引用 benchmark report 的段落，如果不先注明 `26 / 29 / 38 / 30` 中到底是哪一个对象，就会把不同对象混读。
3. 当前 pack 里新加的 `lexical_override` 期望与 `open-plan` 任务，根本没有出现在那些旧 formal 报告的 misfire / route-source 统计里。

最典型的症状就是：

- 当前 YAML 已经声明了 `expected_route` / `expected_route_source` 的 lexical override task
  - `tasks/sample_benchmark.yaml:433-485`
- 但多个 formal 报告里仍然显示：
  - `Artifact expectation tasks per run: 0`
  - `Route Source Distribution` 依然 `100% hint_consensus`

这说明今天最该被批评的 benchmark 问题之一就是：

> 代码、pack、report 三者已经不是一个版本面。

---

## 4. memory 设计：旧分析说中了什么，今天还差什么

## 4.1 旧分析真正说中的点

旧分析对 memory 的一个核心判断今天仍然成立：

> 当前 memory 最强的正式收益，不是 assist，而是 replay/step-skipping。

这个边界现在已经被当前 runner 明写出来：

- `eval/runner.py:2285`
- `eval/runner.py:2639`

说明旧分析没有误判方向。

## 4.2 当前 memory 主路径的真实形态

今天的 memory 主路径大致是：

1. 语义检索优先，失败再 keyword fallback
   - `memory/store.py:398-404`
2. 语义检索里加入了 session bonus、lexical overlap、tag overlap、recency
   - `memory/store.py:636-689`
3. 但检索仍然先被 `task_theme` 精确约束
   - `memory/store.py:617-618`
4. replay/skip 路径仍然需要 route/doc-set/query/hash/confidence 多重匹配
   - `runtime/orchestrator.py:960-1055`
   - `runtime/orchestrator.py:1068-1137`

这条路的优点是：

- 很诚实
- 很可验证
- 不容易把“误命中 memory”包装成能力

但它也直接带来了当前 memory story 的局限。

## 4.3 当前 memory 的三个现实短板

### 短板 1：共享记忆的“共享范围”其实还很窄

`memory/store.py:617-618` 直接要求：

- `row["task_theme"] == query.task_theme`

这意味着当前 memory 主要成立在：

- 同一 incident family
- 同一 task theme
- 同一受控任务族

它当然算 memory reuse，但它更像：

> family-internal reusable memory

而不是更一般的：

> cross-family shared memory

如果文档把它说成“跨任务共享记忆已经成熟”，就会过头。

### 短板 2：assist 路径本身还带有结构性反作用

Retriever 在接受 assist hit 后，会把 assist hint 拼接进 evidence 文本：

- `agents/sample_agents.py:252-262`

而真正传给 summarizer 的 `DENSE_EVIDENCE` 也是这个拼接后的文本：

- `agents/sample_agents.py:264-276`

这意味着 assist 的代价并不只发生在检索阶段，它会把成本转移给 summarize：

- prompt 更长
- 读入更多 hint
- 解释链更重

所以当前 assist-only 不够强，不只是“检索精度不够”。

它还有一个更深的机制问题：

> assist 当前仍然偏向“把旧记忆附加给当前任务”，而不是“让下游真的少做事”。

这也是为什么 replay 能更稳定地产生收益，而 assist 不容易。

### 短板 3：当前的多信号融合还是 heuristic，不是已验证机制

代码自己已经写得很诚实：

- `memory/store.py:637`
  - `These weights are heuristics, not benchmark-validated constants.`

这句话非常关键。

因为这意味着：

- 当前 memory 检索增强已经不是纯语义相似度
- 但也还不能把这套加权说成“已经通过 formal benchmark 验证的检索策略”

所以 `docs/analysis` 中凡是把“多信号融合 + working tier”说成已经解决 assist 问题的，都应该降级。

## 4.4 当前 memory 真正该做的不是“再发明新架构”

当前最现实的 memory 主线不是去做更复杂的 memory 架构，而是先把三件事收口：

1. 明确 formal headline 只认 `replay_enabled / step-skipping`
2. 把 assist 保留为诊断层，不再强行包装
3. 如果要继续提升 assist，重点是：
   - 降低 downstream summarizer 负担
   - 而不是只继续往 retrieval score 里加因子

否则会一直出现一个错误路线：

> 以为 assist 不行是检索不够强，实际上它也可能是后处理和 summarizer 接口设计的问题。

---

## 5. 结构化通信 / 状态传递：旧文档哪里仍有帮助，哪里已经失真

## 5.1 当前状态传递主线已经比旧文档更清楚

当前代码中的 state-transfer 叙事，已经比很多旧文档更收敛：

1. transfer strategy 已明确分成多种：
   - `state_ref`
   - `text_brief`
   - `text_packet_minimal`
   - `state_packet_minimal`
   - `natural_handoff_text`
   - `mode_split_text_brief_vs_state_ref`
   - `runtime/task_profile.py:15-22`

2. executor 对这些 handoff 确实走不同消费路径：
   - `runtime/executor_runtime.py:841-899`

3. dedicated state-transfer packs 也已拆开：
   - `tasks/state_transfer_authenticity_benchmark.yaml`
   - `tasks/contest_release_regression_carrier_benchmark.yaml`
   - `tasks/state_transfer_natural_support_benchmark.yaml`

这说明旧分析里那种“state transfer 只有一种说法”的阶段已经过去了。

## 5.2 但当前 state-transfer 还有四个必须直说的不足

### 不足 1：`text_brief` 不是自然文本 baseline，而是结构化影子文本

`text_brief` 会被重新解析回 feature bundle：

- `runtime/executor_runtime.py:841-850`

而 `_feature_bundle_from_transfer_brief()` 解析的内容本身就带有强结构影子：

- route
- tool
- route source
- route confidence
- tool candidates
- hint docs

见：

- `runtime/executor_runtime.py:1218-1316`

所以当前 `text_brief vs state_ref` 真正回答的问题不是：

> “自然文本 handoff vs 非文本状态 handoff 哪个更好？”

而是：

> “结构化影子文本 handoff vs rich structured state handoff，在 executor 真实性上差多少？”

这仍然是有价值的问题，但必须如实命名。

如果旧分析或后续答辩把它包装成“自然文本基线”，就会失真。

### 不足 2：`_channel_schema` 现在主要是描述，不是执行语义

当前 `FEATURE_BUNDLE` 里确实已经带了 `_channel_schema`：

- `runtime/executor_runtime.py:548-572`

但全 repo 搜索下来，除了生产它，没有任何主路径在消费它。

这意味着它今天的真实状态是：

- 有描述
- 有概念
- 有文档价值

但还不是：

- 运行时强制语义
- 增量传输驱动器
- channel-aware scheduler

所以把它写成“Typed Channel 已经进入主路径能力”仍然偏早。

### 不足 3：CAS / content-addressed state 现在还没进入主运行时

`statepool/store.py` 里已经有：

- `put_cas()`
- `get_by_hash()`
- `put_or_dedup_bytes()`
- `ContentAddressedBlobStore`

见：

- `statepool/store.py:222-255`
- `statepool/store.py:308-381`

`protocol/messages.py` 里也给了：

- `StateRef.blob_hash`
- `StateRef.is_cas`

但 repo 里没有任何主路径调用这些 CAS 方法：

- 主运行时仍然走 `put_bytes()` / `put_text_state()` / `put_feature_state()`
- 主消费侧也没有真正按 `blob_hash` 做 lazy fetch

所以 CASF 方向今天的正确定位只能是：

> 已有代码预留，不是当前 contest 主线能力。

这意味着：

- `novel_design_content_addressed_state_fabric.md` 不能当“当前状态传递已实现说明”
- `CHANGES.md` / `BRANCH_CHANGES_REFERENCE.md` 里凡是把 CAS 讲得像当前主路径，都要降级理解

### 不足 4：当前 state-transfer 的真实性叙事强于效率叙事

当前 dedicated report 逻辑其实已经把这件事说出来了：

- `eval/runner.py:2236-2244`
- `eval/runner.py:2707-2723`

也就是：

- `state_ref` 更像 typed-handoff authenticity 证据
- 它并没有天然证明自己更省

如果从机制上看，这很合理：

- richer state handoff 本来就可能更重
- 它的价值是减少语义重建和角色错配
- 不是自动变成 carrier-efficient

所以现在真正诚实的说法应当是：

> 当前 state transfer 的正式强项是“机制真实性”，不是“全面低开销”。

## 5.3 额外的角色语义提醒：`open-plan` 是真实能力，但不是 planner step 进入主执行图

这一点旧分析文档也很容易写歪，所以这里单独说明。

今天的 `plan_source` 确实已经是行为真实的：

- `runtime/orchestrator.py:817-826`
- `agents/sample_agents.py:161-177`

也就是说：

- `plan_source: yaml` 会走 `build_plan(task)`
- `plan_source: llm` 会走 `PlannerAgent.plan_task()`

但与此同时：

- `PlannerAgent.execute_step()` 仍然明确 `raise NotImplementedError`
  - `agents/sample_agents.py:155-158`

这意味着当前 `open-plan-*` 真正验证的是：

> 一个 bounded 的 task-to-plan 编译入口是否真实存在

它验证的不是：

> planner 已经像 retrieve / execute / summarize 那样，作为普通 step owner 进入同一张执行图里被 benchmark

这点非常重要，因为它决定了：

1. 把 `open-plan-*` 放进 formal pack，会同时混入另一层对象变化。
2. 旧文档里“Planner 真实化”如果被理解成“planner agent 完整进入主运行时 step 语义”，那已经不是今天代码的准确描述。
3. 当前更诚实的说法应该是：
   - planner pre-pass 已经真实
   - planner-as-ordinary-step 仍然不是主线对象

---

## 6. 当前 `docs/analysis` 最大的问题不是“没价值”，而是“层次混了”

当前目录里至少混了四种不同类型的文档：

1. **问题诊断**
   - `benchmark_task_and_result_analysis.md`
   - `code_audit_competition_check_and_solution_roadmap.md`

2. **实施计划**
   - `final_adjusted_plan.md`
   - `implementation_manual.md`

3. **架构想象 / 演进提案**
   - `novel_design_content_addressed_state_fabric.md`
   - `third_party_analysis_and_borrowable_patterns.md`

4. **分支/评审辅助材料**
   - `CHANGES.md`
   - `BRANCH_CHANGES_REFERENCE.md`
   - `CODE_REVIEW_PROMPT.md`

目录本身没有把这四层严格分开。

这会导致两个直接问题：

### 问题 1：读者很难判断“这是不是当前事实”

例如：

- `implementation_manual.md` 长得最像“当前应该照着做”
- 但它恰恰最容易过时

### 问题 2：容易把“提案”误读成“主线能力”

例如：

- CASF
- channel schema
- invariant checker
- CodeAct

这些对象在 repo 里的成熟度完全不同，但在 `docs/analysis` 里经常被并列叙述。

---

## 7. 对当前赛题问题的直接判断

如果问题是：

> “这些分析文档能不能帮我解决现在的赛题问题和代码问题？”

我的判断是：

### 能帮的地方

1. **帮你识别哪些 claim 不能乱说。**
2. **帮你识别 benchmark 最核心的公平性问题。**
3. **帮你保住当前 repo 的 honesty 边界。**
4. **帮你知道哪些第三方模式值得借，哪些不该照搬。**

### 帮不了，甚至会拖偏的地方

1. **不能直接告诉你当前代码已经是什么状态。**
2. **不能直接当今天的实施清单。**
3. **不能替代当前 pack 重跑。**
4. **不能替代对 current code path 的逐段核对。**

---

## 8. 我对当前不足的明确批评

这部分不做温和表述，直接给当前最该面对的不足。

### 8.1 benchmark 侧

1. **formal pack 仍然不够“formal”。**
   - 18/30 个 task 仍是 `internal_regression`
   - 里面还混了 `lexical_override` 和 `open-plan`
   - 这不是一个一句话就能对评委解释干净的 headline pack

2. **aggregate 仍然太靠前。**
   - 文本解释已经变诚实
   - 但视觉顺序仍然没有完全服务最关键的公平比较

3. **旧分析太依赖旧 run。**
   - 当前代码和旧 run 已经漂移
   - 不重跑，就很难说现在的 doc 批评和现在的结果还是一一对应

4. **formal evidence hierarchy 已经失控到 `26 / 29 / 38 / 30` 四套对象并存。**
   - 这不是小的文档同步问题
   - 这是 benchmark 主对象没有冻结
   - 继续拿“latest”泛指，只会放大误读

### 8.2 memory 侧

1. **当前 memory 仍然更像受控 replay 机制，不像宽泛共享记忆系统。**
2. **assist 的问题不只是 recall/score，不解决 summarize 接口，继续调权重也可能收益有限。**
3. **exact `task_theme` gating 让“共享”这件事天然偏窄。**

### 8.3 state-transfer 侧

1. **typed handoff authenticity 已经能讲，但 carrier efficiency 不能顺手一起讲。**
2. **`text_brief` 基线仍然带有结构化影子，不是自然文本。**
3. **CAS 和 channel schema 目前都还没真正进入主运行时语义。**

### 8.4 文档体系侧

1. **`docs/analysis` 缺少一份明确的“当前真相索引”。**
2. **旧计划、旧实现手册、分支叙事、架构提案放在一起，当前读者很容易误读。**
3. **当前 repo 还缺一张“artifact 版本面地图”。**
   - 哪个报告是 `26-task`
   - 哪个是 `29-task`
   - 哪个是 `38-task`
   - 当前代码又是哪一个
   - 这件事如果不单独写清楚，后续所有 benchmark 讨论都会串线

---

## 9. 建议的当前使用方式

如果今天还要继续推进这条线，我建议把文档使用方式硬性改成下面这样：

1. **当前事实层**
   - `README.md`
   - `docs/constraints/current_host_and_migration.md`
   - `docs/constraints/current_feature_scope.md`
   - `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`
   - `docs/planning/contest_object_benchmark_mechanism_plan_20260610.md`
   - 当前代码
   - 最新重跑 artifact

2. **问题地图层**
   - `docs/analysis/benchmark_task_and_result_analysis.md`
   - `docs/analysis/code_audit_competition_check_and_solution_roadmap.md`

3. **模式参考层**
   - `docs/analysis/third_party_analysis_and_borrowable_patterns.md`

4. **历史/提案层**
   - `docs/analysis/final_adjusted_plan.md`
   - `docs/analysis/implementation_manual.md`
   - `docs/analysis/novel_design_content_addressed_state_fabric.md`
   - `docs/analysis/CHANGES.md`
   - `docs/analysis/BRANCH_CHANGES_REFERENCE.md`
   - `docs/analysis/CODE_REVIEW_PROMPT.md`

---

## 10. 最后给一个当前优先级判断

如果只从“解决现在的赛题问题和当前代码问题”出发，我的判断是：

1. **第一优先级不是再写新方案，而是把 formal headline pack 继续收窄。**
   - 至少把 `open-plan-*` 从 formal pack 拿出去
   - `lexical_override` 更适合 diagnostic/support，而不是 headline formal pack

2. **第二优先级是先冻结一个唯一 headline object，再基于它重跑。**
   - 不要继续同时保留 `26 / 29 / 38 / 30` 四套 formal 叙事
   - `README`、task YAML、report、analysis 引用必须指向同一个对象

3. **第三优先级是基于冻结后的当前 pack 结构重跑，而不是继续复述旧 `29-task` 分析。**

4. **第四优先级是把 memory 叙事收窄到真实成立的边界。**
   - replay headline
   - assist diagnostic
   - 不要继续把 assist 当“再调调就能变 headline”的默认对象

5. **第五优先级才是考虑是否继续推进 channel/CAS/CodeAct 这些亮点。**
   - 这些东西不是没价值
   - 但它们今天都排在 benchmark 收口和 claim honesty 后面

最核心的判断只有一句：

> 现在最缺的不是“更多设计”，而是“把当前已经有的机制、pack、报告边界，收成一个评委不会轻易抓住破绽的正式叙事”。
