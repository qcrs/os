# StateBus Host Mainline Goal Prompt: De-specialize Then Deepen

把下面整段 prompt 交给新的 Codex goal 窗口使用。

```text
你现在工作在 `/home/qcrs/statebus/project`。

这次 goal 不是重新证明“host-side 是否已经能跑”，也不是去做 Docker、openEuler VM、`nsjail`、强沙箱终态、hidden-state/KV 传递、交付镜像或部署资产。

这次 goal 的前提判断已经固定：

- 基于 `docs/reference/题目.md`、`runs/host_goal_eval_20260608_093111_planner_contract_refresh/`、`docs/progress/contest_requirement_host_audit_20260607.md` 和当前代码锚点，host-side 这一层除最终 openEuler 交付外，赛题完成度已经基本收口。
- `093111` 包已经把先前 text-mode `9/10` 的 planner wobble 收口成 `10/10`，所以当前问题不再是“goal 没完成”。
- 但这不等于现在只剩纯 tuning。当前真正没收口的是：
  - 真实性 / 泛化性
  - 去赛题特化
  - 检索与记忆分层解耦
  - 工具选择机制去 playbook 化

因此，这次 goal 的总原则是：

> 先去特化，再深化；先修结构问题，再做性能优化。

## 一、范围约束

这次 goal 必须停在下面这些东西前面：

- 不做 Docker 相关实现
- 不做 openEuler VM 相关实现
- 不做交付镜像、容器、部署资产
- 不做 `nsjail` / 容器沙箱 / hidden-state / KV 传递
- 不为了未来 VM / Docker / 沙箱交付而提前重构与当前 host 主线无关的路径

可以提这些对象，但只能作为：

- 后续阶段边界
- 当前不纳入项
- 未来验证层对象

不能把它们当当前执行主线。

## 二、当前固定判断

这次执行必须接受下面这些前提，而不是重新从零争论：

1. 赛题完成度问题基本收口了。
2. 当前更重要的问题不是“多注册工具”，而是“怎么选工具”。
3. 当前 `Executor` 还是明显偏 route-to-playbook；在这种结构下继续加工具，往往只会把赛题特化菜单做得更厚。
4. 当前检索链可以说“有分层”，但还不是成熟、诚实的分层 RAG：
   - 一层是 corpus 检索
   - 一层是 route / feature bundle 提炼
   - 一层是 memory assist / replay 检索
5. 当前更该优先修的是：
   - planner / task contract 的 gold-field leakage
   - 检索候选集预裁剪
   - memory 与 retrieval 未真正解耦
   - executor 工具选择仍过度依赖固定 route

## 三、你必须先读的本地材料

先读本仓库，不要一上来就去看 `third_party/`。

必读：

- `AGENTS.md`
- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`
- `docs/planning/host_goal_mainline_dependency_20260607.md`
- `docs/planning/host_goal_review_execution_plan_20260607.md`
- `docs/planning/goal_prompt_host_mainline_execute_20260608.md`
- `docs/progress/contest_requirement_host_audit_20260607.md`
- `docs/progress/host_mainline_deep_audit_20260608.md`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/SUMMARY.md`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/COMMANDS.md`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/deterministic_repeat10/benchmark_report.md`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/api_repeat10_serial/benchmark_report.md`

重点检查这些实现区域：

- `agents/`
- `runtime/`
- `protocol/`
- `statepool/`
- `memory/`
- `eval/`
- `tasks/`
- `tests/`
- `deploy/`
- `scripts/`

必须特别核对这些锚点：

- `agents/sample_agents.py`
- `tasks/sample_tasks.py`
- `tasks/local_corpus.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `runtime/reuse_contract.py`
- `tests/test_llm_runtime.py`

## 四、什么时候才看 `third_party/`

`third_party/` 不是一开始就去抄的灵感池。

只有在你完成本仓库问题重建之后，才允许看 `third_party/`，并且必须带着明确问题去看。

允许去看的触发条件只有这几类：

1. 你已经确认本仓库有结构性问题，但本地材料没有给出足够清晰的下一步形态。
2. 你准备修改接口或分层，需要找一个“可借鉴但不照搬”的实现思路。
3. 你在两个局部方案之间拿不准，想用成熟仓库帮助做取舍。
4. 你需要为“深度优化”找机制思路，而不是为了堆参考名单。

不允许的行为：

- 还没把本仓库问题读清，就先去看 `third_party/`
- 把第三方仓库的大框架整套搬进来
- 因为某个仓库很强，就把当前 repo 的 host-first 边界改掉

## 五、当前本地 `third_party/` 仓库的用途

当前本地已 clone 的参考仓库，只能按下面方式使用：

- `third_party/langgraph`
  - 借：运行态状态 vs 长期记忆分离、durable execution、checkpoint 观念
  - 不借：整套框架替换 StateBus
- `third_party/langgraph-bigtool`
  - 借：tool metadata indexing、先检索工具再执行
  - 不借：为了追求“很多工具”而先扩工具表
- `third_party/semantic-router`
  - 借：route layer、abstain/threshold、可调优的路由阈值
  - 不借：把当前 route 全部外包成独立新框架
- `third_party/haystack`
  - 借：检索、路由、记忆、生成显式分节点的透明 pipeline 思路
  - 不借：引入过重生态来替换当前 host 主线
- `third_party/memsearch`
  - 借：Markdown/source-of-truth vs vector shadow index、progressive retrieval、多层记忆
  - 不借：整套跨平台插件体系
- `third_party/AgentRx`
  - 借：trajectory IR、invariants、failure localization、诊断报告层
  - 不借：把当前 goal 转成重型诊断平台建设

你必须把第三方参考转成“借鉴清单”，格式固定为：

1. 当前仓库的哪个具体弱点
2. 对应看了哪个 `third_party/...`
3. 借鉴哪一个具体机制
4. 为什么适合 StateBus 当前 host-mainline
5. 为什么不照搬剩余部分

如果做不到这五点，就不要引用它。

## 六、你必须先给出的判断

在动代码前，你必须先明确写出：

1. 当前阶段不是只剩 tuning，而是先去特化再深化。
2. 当前最该先修的是工具选择机制，不是工具数量。
3. 当前检索链虽然有分层，但还不是成熟的分层 RAG。
4. 当前 memory gain 虽然真实存在，但 exact replay 仍偏受控复放。
5. 当前 executor 已经不是空壳，但仍更接近 route-aware playbook selector，而不是通用执行层。

如果你读完代码后判断这些前提里有一条不成立，你可以推翻它，但必须给出具体文件和理由，不能泛泛改口。

## 七、当前最主要的问题对象

你必须把下面这些问题作为当前主线，而不是把它们降级成“以后优化”：

### 问题 1：Planner 可见的 gold fields 太多

`Planner` 现在仍直接看到：

- `corpus_doc_ids`
- `expected_reuse_mode`
- `runtime_reuse_contract`
- `replay_source_task_id`

这会导致 plan 和 reuse 判断过于赛题化。

### 问题 2：Task contract 深度参与 runtime 主链

`tasks/sample_tasks.py` 当前不仅描述 benchmark，还直接把：

- `corpus_doc_ids`
- `reuse_signature`
- `runtime_reuse_contract`

塞进主执行 plan step。

这说明 benchmark contract 还没有退回到“旁路评测层”。

### 问题 3：Retriever 候选集还在预裁剪

当前候选集还会先吃：

- `corpus_doc_ids`
- `task_group`
- `task_theme`

所以它更像受控语料证据打包器，而不够像更诚实的分层检索。

### 问题 4：Memory / retrieval 还没有真正解耦

exact replay 仍然强依赖：

- `reuse_signature`
- 同 query
- 同 doc-set
- route / provenance 匹配

这条线是成立的，但偏“受控复放”，不是更自然的跨任务复用。

### 问题 5：Executor 仍然过度 route-to-playbook

当前更应先修“如何选工具”，而不是“多注册工具”。

如果在这种结构下继续扩工具，只会把赛题特化做得更厚。

## 八、执行总顺序

这次 goal 必须尽量按下面顺序走。

### 第一阶段：题目与当前弱点重建

你要先重建：

1. 赛题 requirement map
2. 当前 host-side 已经闭合了什么
3. 当前还不诚实或不够通用的地方是什么
4. 当前哪些问题属于“必须先修”，哪些才属于“后续优化”

这一阶段的产出必须明确写出：

- 为什么不是只剩 tuning
- 为什么先去特化
- 为什么不优先扩工具表

### 第二阶段：最小必要 host 回归确认

只跑最小必要验证：

```bash
cd /home/qcrs/statebus/project
source deploy/activate_statebus_host.sh
export STATEBUS_EMBED_DEVICE=cuda:0
python -m pytest -q
python -m runtime.smoke
```

如果这一步不过，先修主链路，不要提前做分层重构。

### 第三阶段：带问题看 `third_party/`

只有在第一阶段问题对象已经明确后，才允许去看本地 `third_party/`。

推荐读取顺序：

1. `third_party/semantic-router`
   - 用来想 route layer、abstain、threshold
2. `third_party/langgraph-bigtool`
   - 用来想工具检索而不是 route 直连工具
3. `third_party/memsearch`
   - 用来想 source-of-truth memory 和 shadow index 分层
4. `third_party/langgraph`
   - 用来想 working memory / long-term memory / checkpoint
5. `third_party/haystack`
   - 用来想透明 pipeline 分节点
6. `third_party/AgentRx`
   - 用来想后续 failure invariant 和诊断层

你必须先做“借鉴清单”，不能直接动代码。

### 第四阶段：去特化主线修正

这部分是当前 goal 的核心，不是可选项。

按下面顺序推进：

1. 先缩掉 planner 可见的 gold fields
   - 优先减少 `expected_reuse_mode`
   - 逐步减少 `runtime_reuse_contract`
   - 不再让 planner 直接依赖完整 `corpus_doc_ids`
2. 再把检索改成更诚实的两到三层
   - `broad recall`
   - `rerank / route`
   - `memory / replay`
3. 再拆记忆层
   - `summary / episode memory`
   - `route / evidence memory`
   - `tool artifact memory`
4. 再修 executor 去特化
   - 从固定 route -> fixed playbook
   - 逐步变成 capability / tool metadata 检索

注意：

- 这一步不要求一次做成“通用 agent runtime”
- 但要求把最明显的赛题化硬编码往后退

### 第五阶段：深度优化

只有第四阶段已过关，才进入深度优化。

允许的深度优化方向：

1. route threshold / abstain 优化
   - 借鉴 `semantic-router`
2. tool metadata indexing + retrieve-tools path
   - 借鉴 `langgraph-bigtool`
3. memory source-of-truth 与 shadow index 明确化
   - 借鉴 `memsearch`
4. working memory / long-term memory / run checkpoint 分层
   - 借鉴 `langgraph`
5. retrieval pipeline 显式节点化与 trace 化
   - 借鉴 `haystack`
6. replay / planner / route 失配的 invariant-style 诊断
   - 借鉴 `AgentRx`

这一步才允许你加入自己的技术判断、比较不同实现形态、决定哪条优化更值得留下。

### 第六阶段：证据与文档回写

每完成一类实质改动，都要决定是否需要：

1. 补新的 `runs/...` 证据包
2. 更新：
   - `README.md`
   - `docs/constraints/current_feature_scope.md`
   - `docs/progress/contest_requirement_host_audit_20260607.md`
   - `docs/progress/host_mainline_deep_audit_20260608.md`
   - `docs/planning/implementation_plan.md`
3. 明确哪些旧包降级为：
   - 历史正式层
   - 诊断层
   - 过渡层

## 九、你需要自己思考和判断的地方

我不要你机械照 prompt 执行。

你必须自己判断：

1. 哪些赛题特化值得立即移除，哪些可以先保留为受控 benchmark scaffold
2. 哪些第三方思路适合当前 repo，哪些只是看起来先进但会把项目带偏
3. 哪些深度优化会真正让系统更通用，哪些只是让 benchmark 更好看
4. 当前修改是否会伤到 `093111` 已经拿到的正式证据面

如果你判断某条“优化”只会让系统更复杂、却不提升真实性或泛化性，直接停止，不要温和包装。

## 十、Git 与工作区纪律

你必须遵守：

1. 从 `main` 当前 worktree 开始，不切回旧 baseline 做新开发。
2. 不回滚用户已有改动。
3. 小步提交式思维，但不要为了形式强行切碎；一次改动应对应一个明确问题对象。
4. 新 benchmark 永远进新的 `runs/...` 目录，不覆盖旧正式包。
5. 如果你引用 `third_party/` 思路，必须在文档里写明“借了什么、没借什么”。
6. 不要把第三方大框架 vendoring 进主实现。
7. 不要为了以后 VM / Docker 验证而提前做无关铺垫。

## 十一、明确不推荐的路线

当前不要优先做：

- 多注册一批 incident-family 变体工具
- 继续堆更厚的 route-to-playbook 菜单
- 先做 `shared_memory` headline 优化
- 先做 prompt 压缩、token 微调、字节微调
- 先做 Docker/openEuler/`nsjail`

因为这些都排在“去特化与分层解耦”之后。

## 十二、输出要求

1. 用中文。
2. 先给结论，再给动作，再给证据。
3. 每次都明确你当前处于哪一阶段：
   - `题目与弱点重建`
   - `宿主机回归确认`
   - `参考仓库借鉴清单`
   - `去特化主线修正`
   - `深度优化`
   - `证据与文档回写`
4. 如果你判断某条路线不值得继续，直接说。
5. 如果你认为某个第三方思路不适合当前 StateBus，也直接说。
6. 不要停在分析；在范围内应持续推进到：
   - 当前主线更少赛题特化
   - 分层更清楚
   - 深化项有实质落点
   - 文档与证据同步
   - 剩下的真正只属于 VM / Docker / openEuler / 沙箱后续阶段

最终目标不是“继续把项目讲得更像完成态”，而是：

> 基于当前已完成的 host-side requirement closure，继续把 StateBus 从 contest prototype 往更诚实、更可泛化的 host-mainline 系统推进一步，并明确停在 VM / Docker / openEuler / 强沙箱之前。
```
