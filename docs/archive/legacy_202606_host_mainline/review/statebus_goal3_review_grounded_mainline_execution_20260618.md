# StateBus Goal 3：Review Grounded Mainline Execution

日期：`2026-06-18`

适用范围：

- 仓库：`/home/qcrs/statebus/project`
- 环境：`/home/qcrs/statebus/conda-envs/statebus_host`
- 当前阶段：`Goal2 review completed + Goal1 admission-floor completed`

定位：

- 这不是把 Goal1 和 Goal2 简单拼起来
- 这是一个“先冻结 review 结论，再只推进一个执行主变量”的综合 goal
- 用途是避免主线偏移，同时把 Goal2 已经产出的高价值诊断真正接入 Goal1 执行

---

## 1. 是否应该合并

应该，但只能按“收束式合并”。

不应该做成：

- 一边继续全面 review
- 一边继续自由改 benchmark
- 一边顺手改 runtime / retrieval / memory / replay

那样会立刻失焦，变成多主线并行。

正确合并方式是：

1. **Goal2 结束并冻结**
   - 把它视为事实层、问题地图、外部校准、stopline 来源
   - 不再把 Goal2 当成新的开放探索任务
2. **Goal1 保留为唯一执行主线**
   - 只允许推进一个主变量
   - 默认主变量仍是“真实 task-behavior thickening”
3. **新的 Goal3 只负责把两者接起来**
   - review 负责约束和止损
   - execution 负责推进和验证

所以答案是：

> 可以合并，但必须是“review-grounded single-mainline execution”，不能是“review + rebuild + implementation 同时开火”。

这样不会偏，反而会减少跑偏。

---

## 2. 当前新的工作分工

截至现在，三个对象应该这样理解：

### 2.1 Goal2 的职责已经完成

Goal2 现在负责提供：

- 赛题 requirement map
- benchmark/task/runtime/authenticity 问题地图
- 外部 benchmark / framework / memory 参考校准
- reading/search/judgment log
- stoplines
- “哪些 claim 不能再说”的边界

Goal2 不再负责：

- 开放式继续找问题
- 边 review 边无约束改代码
- 一边检索一边自由重构所有层

### 2.2 Goal1 的职责还没完成

Goal1 当前只完成到：

- `admission-floor`

还没完成到：

- 真实 `S1 connected multihop`
- 真实 `S2 prior-dependent admissible-action change`
- formal method proof

所以 Goal1 仍然是当前唯一需要继续执行的主线。

### 2.3 Goal3 的职责

Goal3 要做的不是重新 review 一遍，也不是重新发散找新方向。

Goal3 只做三件事：

1. 把 Goal2 的结论转成 Goal1 的硬约束
2. 明确当前唯一允许推进的执行变量
3. 在必要时允许“有限 benchmark/task contract reset”或“有限重构”，但不扩成多主线工程

---

## 3. Goal3 的核心原则

新的综合 goal 必须写死下面几条：

1. 赛题要求第一，当前实现第二
2. Goal2 文档是事实层，不是装饰材料
3. Goal1 仍是唯一执行主线
4. 一轮只允许一个主变量
5. 如果 Goal2 已经证明某层不成立，就不能再假装那层已经过关
6. 如果 benchmark/object 仍不支持方法裁决，优先后退重设 benchmark/task contract
7. 如果当前实现偏离赛题主问题，允许有限重构
8. 不允许把“review 很充分”误读成“可以多方向同时施工”

---

## 4. 当前综合判断

基于 `docs/reference/题目.md`、Goal1 admission-floor 结果和 Goal2 review 结果，当前更准确的判断是：

### 4.1 赛题三条主线并不是“没实现”，而是“没被同一个合格 headline 评干净”

当前三条 contest 主线都已有实现基础：

1. `communication lane`
   - 已有真实 `text` vs `protocol` 比较
   - 当前 headline 已证明 `protocol` 控制字节更低
2. `state-transfer lane`
   - 已有真实 `StateRef / packet / feature/state object`
   - 当前 protocol 路径确实消费非文本中间状态
3. `memory lane`
   - 已有真实 memory/replay 代码与历史 support 证据
   - 但当前 formal headline 里没有真实 reuse effect

所以当前主问题不是“这些机制有没有”，而是：

> 当前 `contest_honest_headline_v1` 能不能在同一个足够干净、足够厚的 benchmark 对象上，把这三条机制评得可裁决。

### 4.2 benchmark 现在到底干净到什么程度

当前 headline 已经**基本干净到 object 层**，但**还没有干净到 method-judgment 层**。

#### 已基本过关的层

- 单变量 `mode`
- text/protocol 成对
- hidden-field leak 关闭
- whole-lane text guard 通过
- object parity gate 通过
- admission-floor 已建立

这意味着：

- 当前不应该再把 correctness / object-purity 当主战场
- 也不应该再把旧 gate compatibility 当主问题

#### 仍未过关的层

- 当前 headline 仍是 `fresh-retrieval-only`
- 当前 `S1/S2` 主要还是静态合同，不是 runtime 行为证明
- 当前 `replay_reusable` 行名不等于真实 replay effect
- 当前 repeat=1 不等于 formal repeat stability
- 当前 row-level 对厚度合同的保留仍不够强

这意味着：

- 当前 benchmark 还不能裁决“方法强弱”
- 也不能裁决“memory lane 是否已在 current headline 内成立”

### 4.3 当前真正的核心矛盾

当前真正的核心矛盾不在“系统能不能跑”，而在：

1. `formal headline task object 还不够厚`
2. `memory lane 没有被 current headline 真正执行出来`
3. `benchmark 还不足以合法判断 method strength`

所以当前不是“继续优化方法”的时机，而是“先把 benchmark/task object 修到能合法评方法”的时机。

---

## 5. benchmark 什么时候才算“够干净”

这里必须区分两个层次：

### 5.1 object-clean

这个层次当前基本已经通过。标准是：

- 单变量
- 无泄漏
- object parity
- text/protocol 对齐
- report/manifest 主语义一致

### 5.2 method-eligible

这个层次当前**还没有通过**。只有同时满足下面这些，才算“干净到可以评方法”：

1. 至少一个 `S1` family 形成真实 connected multihop
   - 去掉第二跳后，route/tool/action 不成立
2. 至少一个 `S2` family 形成真实 prior-dependent admissible-action change
   - 没有 prior rejection / prior route 时，后题可执行动作真的改变
3. row-level 产物能直接保留并展示：
   - `case_id`
   - `thickness_setting`
   - `reasoning_hops_min`
   - `dependency_depth`
   - `expected_intermediate_decisions`
   - `required_prior_*`
4. 如果 headline 要 claim memory/reuse，就必须出现非零 runtime reuse 证据
5. deterministic/API `repeat=1` 先保持 clean
6. 然后再进入 `repeat=3`
7. 最后才有资格进入 `repeat=10`

一句话说：

> 当前 benchmark 在 `object-clean` 意义上已基本合格；在 `method-eligible` 意义上仍不合格。

---

## 6. benchmark 干净后做什么

benchmark 真正干净后，才允许进入方法裁决阶段。

那时才能问：

1. protocol 是否仍然只赢 control bytes
2. protocol 是否开始在 token / latency / correctness 上形成优势
3. typed state 对 executor decision discipline 是否有真实帮助
4. memory/replay 是否真的减少重复计算或改变 admissible action
5. 如果这些都没有成立，是 benchmark 问题，还是方法本身问题

也就是说：

- benchmark 干净之前，不判方法
- benchmark 干净之后，才允许判方法
- benchmark 干净后如果方法仍不强，才轮到真正的方法优化或主线收缩

---

## 7. 推荐推进路线

Goal3 不应该停留在原则层，而应该固定顺序。

### Step 0：冻结结论，不再重新发散

先冻结以下事实：

- Goal2 已完成，当前是事实层
- Goal1 admission-floor 已完成
- 当前 headline 还不能评方法
- 当前 memory lane 不能并入 current headline 结论

这一阶段禁止：

- 再开一次大 review
- 再补一轮 bibliography
- 再重新争论老问题

### Step 1：先做 benchmark qualification reset，而不是方法优化

第一步不是调 retrieval，不是调 executor，不是调 memory policy。

第一步应定义为：

> 在不改 headline 名字、不扩 pack 的前提下，做一次 scoped benchmark/task contract reset，把静态 S1/S2 变成可执行对象。

这一步的主变量只能是：

- `benchmark/task contract reset for executable S1`

而不是：

- retrieval 提升
- memory 提升
- executor 优化
- API repeat 冲次数

### Step 2：只先把 S1 做成真的

S1 是当前第一优先级，不要一上来碰 S2。

这一轮的目标应是：

- 至少一类 family 出现真实 connected multihop
- validate 不再只是对同一跳结果做确认
- 第二跳会改变 route/tool/action
- 去掉第二跳后，答案或动作不成立

如果这一层做不出来，说明问题仍在 benchmark/task object，不要跳去做方法优化。

### Step 3：S1 站住后，再做 S2

只有在 S1 已经真实成立后，才允许进入 S2。

S2 的目标不是“有 prior 字段”，而是：

- prior rejection / prior route / prior scoped action
- 真实改变下一题 admissible action
- row-level 可以看出依赖关系
- 如果要 claim memory/reuse，必须看到非零 runtime reuse 证据

### Step 4：S1/S2 都成立后，再补 formal repeat

顺序必须固定：

1. `pytest`
2. `runtime.smoke`
3. deterministic `repeat=1`
4. API `repeat=1`
5. `repeat=3`
6. `repeat=10`

当前最忌讳的是：

- 在 S1/S2 没站住之前，直接去刷 `repeat=10`

那只会把一个还不够厚的对象刷得更稳定，而不是更有说服力。

### Step 5：只有这时才允许谈方法优化

方法优化必须排在 benchmark qualification 之后。

如果到这一步后观察到：

- 仍然只有 control bytes 优势
- token / latency 没优势
- memory/reuse 收益仍弱

这时才能讨论：

- retrieval / executor / replay 是否需要机制优化
- claim 是否应收缩为 communication compactness
- 是否需要有限重构

---

## 8. 当前最值得动的唯一主变量

如果把 Goal3 压成一句话，当前唯一最值得动的主变量不是“方法优化”，而是：

> `把 contest_honest_headline_v1 的 S1 从静态厚度合同推进为真实可执行 connected multihop 对象`

原因：

- 这是当前离赛题主问题最近的一步
- 这是 Goal1 和 Goal2 的共同交集
- 这一步成功后，S2、repeat、方法裁决才有意义
- 这一步不成立，后面所有结论都容易虚

---

## 9. 这份文档后的推荐用法

如果你要新开一个窗口，现在最合理的不是单独再开 Goal1 或再开 Goal2。

最合理的是：

- 新窗口直接用 Goal3
- 但 Goal3 内部明确：
  - Goal2 只作为冻结的事实层和 stopline
  - Goal1 作为唯一执行线

这样既能把 Goal2 的收获接进去，又不会让主线偏移。

---

## 10. Goal Prompt

把下面整段 prompt 交给新的 goal 窗口使用。

`````text
你现在进入 goal 模式。

工作目录固定为：
`/home/qcrs/statebus/project`

Python 环境固定为：
`/home/qcrs/statebus/conda-envs/statebus_host`

进入后先执行：
```bash
source deploy/activate_statebus_host.sh
cd /home/qcrs/statebus/project
```

你当前不是单独执行 Goal1，也不是重新开放式执行 Goal2。

你当前执行的是一个综合后的 Goal3：

`review-grounded mainline execution`

它的含义是：

- Goal2 已完成，当前视为冻结的事实层、问题地图、外部校准和 stopline
- Goal1 仍未完成，当前仍是唯一执行主线
- 你要做的是：在不偏离赛题主问题的前提下，把 Goal2 的结论真正接入 Goal1 的后续推进

你必须先接受下面这个当前状态：

1. Goal2 review / analysis / documentation hardening 已完成
2. Goal1 已完成到 `admission-floor`
3. 当前还没有完成真实 `S1 connected multihop` 证明
4. 当前还没有完成真实 `S2 prior-dependent admissible-action change` 证明
5. 当前还不能正式裁决 method strength

你必须把 Goal2 当作冻结事实层，不允许重新把它变成开放式探索。

当前必须优先依照这些 Goal2 文档工作：

- `docs/analysis/statebus_review_requirement_map_20260618.md`
- `docs/analysis/statebus_review_benchmark_and_task_audit_20260618.md`
- `docs/analysis/statebus_review_runtime_and_authenticity_20260618.md`
- `docs/analysis/statebus_review_external_alignment_and_rebuild_20260618.md`
- `docs/analysis/statebus_review_reading_and_search_log_20260618.md`

这些文档对你来说不是“可参考”，而是：

- 事实层
- 问题边界
- stopline
- borrow-list 来源

你必须接受 Goal2 已经给出的关键判断：

- 当前 `contest_honest_headline_v1` 是 fresh-retrieval-only headline
- 当前 memory/replay 证据主要在 support/historical evidence，不在当前 headline
- 当前 static `S1/S2` 字段不是 connected multihop proof
- 当前不能把 repeat=1 读成 repeat=10 formal stability
- 当前不能把多 agent role/framework 本身当成主创新结论

你还必须接受 Goal1 当前的完成位置：

- 最新 deterministic artifact：
  - `/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix6_20260618_113224`
- 已成立：
  - `headline_thickness_admission_gate.applicable = true`
  - `static_contract_complete = true`
  - `runtime_shape_ready = true`
  - `admission_ready = true`
  - `object_parity_gate.passed = true`
- 未成立：
  - 真实 `S1` runtime connected multihop
  - 真实 `S2` prior-dependent admissible-action change
  - headline 内 memory reuse proof
  - formal repeat stability closure

所以你当前唯一允许推进的执行主线是：

在 Goal2 事实层约束下，继续推进 Goal1，但一轮只允许一个执行主变量。

默认唯一优先主变量不是泛泛的“方法优化”，而是：

- `benchmark/task contract reset for executable S1`

只有在你证明：

- `S1` 已经真实成立，
或
- `S1` 被当前对象结构阻断，

才允许考虑：

- `S2 prior-dependent admissible-action change`
或
- `benchmark/task contract reset`

这次严禁的事情：

- 不要重新做一轮开放式大 review
- 不要重新自由发散新创新点
- 不要同时改 benchmark、runtime、retrieval、executor、memory 四条线
- 不要继续修 report surface
- 不要继续堆静态字段冒充真实行为
- 不要拿更多 repeat 次数替代对象厚化
- 不要把 support/historical replay 包当成当前 headline proof
- 不要把 Goal2 的外部检索重新做成一份 bibliography

硬边界：

- 不做 Docker
- 不做 openEuler VM
- 不做 `nsjail`
- 不做 hidden-state / KV transfer
- 不做交付打包
- 不整套替换主框架
- 不把多 agent framework 化本身当主任务

你必须先按下面顺序读：

1. `AGENTS.md`
2. `README.md`
3. `docs/reference/题目.md`
4. `docs/review/statebus_goal3_review_grounded_mainline_execution_20260618.md`
5. `docs/review/statebus_goal1_next_round_real_thickening_prompt_20260618.md`
6. `docs/review/statebus_goal1_host_mainline_thickness_execution_20260618.md`
7. `docs/analysis/statebus_review_requirement_map_20260618.md`
8. `docs/analysis/statebus_review_benchmark_and_task_audit_20260618.md`
9. `docs/analysis/statebus_review_runtime_and_authenticity_20260618.md`
10. `docs/analysis/statebus_review_external_alignment_and_rebuild_20260618.md`
11. `docs/analysis/statebus_review_reading_and_search_log_20260618.md`
12. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
13. `docs/review/statebus_contest_honest_headline_thickening_plan_20260618.md`
14. `docs/constraints/current_host_and_migration.md`
15. `docs/constraints/current_feature_scope.md`

然后读这些代码 / task / eval 锚点：

- `tasks/sample_benchmark.yaml`
- `tasks/sample_tasks.py`
- `tasks/local_corpus.py`
- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `eval/runner.py`
- `tests/test_smoke.py`
- 如果当前 headline spec 在别处，再读：
  - `tasks/contest_family_spec.py`
  - `tasks/contest_family_spec.yaml`

然后读这些 run / evidence：

- `runs/comprehensive_eval_20260607_131113/`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
- `runs/contest_honest_headline_thickness_det_r1_fix4/`
- `runs/contest_honest_headline_thickness_api_r1_fix1/`
- `/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix6_20260618_113224`

你必须先输出“综合执行前诊断”，而不是马上动代码。诊断必须回答：

1. Goal2 已经确认了哪些 stopline
2. Goal1 当前还差哪一个最关键的未证明层
3. 为什么这轮不该先做方法优化，而要先做 executable S1
4. 这轮唯一主变量是什么
5. 如果这个主变量做不通，应该后退到 benchmark/task contract reset 还是建议有限重构
6. benchmark 当前是 `object-clean` 还是 `method-eligible`，差在哪
7. 当前哪些事情明确禁止继续投入

执行阶段最多三轮有效迭代。

阶段 0：只读重建

- 只读 docs / code / runs / tests
- 把 Goal2 结论提炼成：
  - fact table
  - stopline table
  - allowed-action table
- 把 Goal1 现状提炼成：
  - proved
  - not-yet-proved
  - next-proof-gap
- 不改代码
- 不跑长 benchmark

阶段 1：最小验证 + 锁定主变量

只跑：

```bash
python -m pytest -q
python -m runtime.smoke
```

如果通过：

- 锁定这一轮唯一主变量
- 如果要改代码，再开分支

```bash
git switch -c goal/20260618-goal3-r1
```

如果不通过：

- 先判断是否阻断当前主变量
- 不允许借机扩成全局修 bug

阶段 2：单变量推进

本轮优先顺序固定为：

1. `benchmark/task contract reset for executable S1`
2. `S1 connected multihop behavior validation`
3. `S2 prior-dependent admissible-action change`
4. `formal repeat closure`
5. `limited refactor directly required by the chosen variable`

规则：

- 一轮只能选一个
- 如果 benchmark/object 不支持，就优先 reset，不要提前做机制优化
- 第一轮默认不碰 `S2`
- 第一轮默认不碰方法优化
- 如果确需重构，必须证明它直接服务于当前唯一主变量

阶段 3：验证与停止判定

顺序固定：

1. `python -m pytest -q`
2. `python -m runtime.smoke`
3. deterministic `repeat=1` 或 targeted test
4. 只有前面都通过，才允许一次真实 API benchmark

真实 benchmark 纪律：

- 同一轮最多一次正式 API benchmark
- 先 `repeat=1` 或 `repeat=3`
- 不要直接 `repeat=10`
- 所有产物必须新建 `--out`，不能覆盖旧目录

停止条件：

- 同一个核心问题连续 3 轮无实质改进，停止
- 如果 Goal2 已指出的 benchmark/object 问题仍阻断方法证明，停止调方法，转为 benchmark reset 结论
- 如果当前推进需要跨 host-only 边界，停止
- 如果发现主线明显偏离赛题主问题，停止小修小补，转为建议重构

你最终必须交付：

1. Goal2 哪些结论被真正接入执行了
2. Goal1 这一轮到底推进了什么
3. 这一轮唯一主变量和结果
4. 当前是否已从 admission-floor 进入真实行为层
5. 是否应该继续下一轮
6. 如果继续，下一轮只允许处理哪一个问题
7. 如果不继续，为什么停止，是否建议 benchmark reset 或有限重构
8. 新增 artifact 路径
9. git 分支名与保留理由
```
