# StateBus 新窗口启动说明

日期：`2026-06-17`

定位：

- 这份文档是给“新开窗口/新会话”的启动说明。
- 目的不是复述全部历史，而是让新的协作者快速理解：
  - 这个项目当前到底卡在哪里
  - 为什么现在不能继续无边界修补
  - 当前第一优先级为什么是 benchmark 立项与流程，而不是直接改 runtime
  - 接下来第一阶段应该产出什么

---

## 1. 先说当前最重要的判断

当前项目的核心问题，不是某一个 benchmark 包的指标不够高，也不是某一个单点 bug。

当前最重要的问题是：

**项目的解释层已经开始比方法层更复杂。**

具体表现为：

1. benchmark pack 太多
2. 文档阶段太多
3. 太多“这个回答 A，不回答 B”的读法边界
4. 太多历史修补仍然挂在当前主视野里

这导致一个直接后果：

> 每次都像在修东西，但越来越难回答“这个项目现在主线到底是什么”。

所以当前最需要的，不是继续加动作，而是先重新建立一套更清楚的 benchmark 立项流程和主线判断框架。

---

## 2. 当前项目里其实混了两种目标

新的协作者必须先理解：当前仓库里其实混了两种不同目标。

### 2.1 目标一：证明机制真实成立

这条线关注：

- 多 Agent 真在协作
- protocol 真在传结构化信息
- typed state 真在生产 / 传递 / 消费
- replay 真在减少重复工作

这条线当前已经有不少真实进展。

### 2.2 目标二：证明 protocol 在 contest headline 上明显优于 text baseline

这条线关注：

- latency 更好
- token 更少
- correctness 更高
- 对比差异更明显

这条线当前还没有站稳。

### 2.3 当前痛苦的根源

最近的大量工作，其实主要在修：

- fairness
- headline object
- support surface 分离
- report 语义
- pack 读法边界

这些工作很重要，但它们更像是在让系统“更诚实、更可辩护”，而不是直接让方法“更强”。

所以当前的痛苦并不是错觉：

> 你用“想看到 protocol 明显优势”的期待，去看“一直在修解释层”的进展，自然会觉得做了很多但没有往前走。

---

## 3. 当前最可能的真实情况

从已有代码、审计文档和最新 run 来看，当前最接近事实的判断是：

1. 方法不是已经死了
2. 机制层确实有真实资产
3. 当前 headline 对象比以前诚实很多
4. 但当前任务对象太薄，差异没有被充分放大
5. 同时 text 侧并不是一个特别弱的消费者，所以 protocol 优势不会自动显著

所以“现在结果总是差不多”更像是在说明：

> 当前 benchmark 对象还不足以强区分两种协作方式的端到端收益。

这不等于方法无效，但也不能自动证明方法有效。

---

## 4. 当前最需要的判断顺序

新的协作者不要一上来就直接判断“方法有没有优势”。

正确顺序应该是：

1. 先判断 benchmark 是否回答了对的问题
2. 再判断 benchmark 是否单变量、公平、对象纯净
3. 再判断 benchmark 是否足够厚，能放大差异
4. 最后才判断方法是否真的没有形成优势

也就是说：

> 先排 benchmark 对象问题，再谈方法问题。

如果对象没立住，方法结论本身就是不可信的。

---

## 5. 当前第一优先级不是“继续改代码”

当前第一优先级是：

**建立一套可信 benchmark 的立项方案与判断流程。**

先把 benchmark 问题想清楚，再决定要不要进下一轮方法实现或 runtime 改造。

这意味着：

- 当前不要默认继续加新 pack
- 当前不要默认继续扩 benchmark surface
- 当前不要默认继续加新的 handoff variant
- 当前不要先去大改 orchestrator / executor 主逻辑

---

## 6. 当前应该怎么理解“创新点都不想放弃”

这点非常关键。

当前项目里有很多基于赛题要求的创新点，例如：

- typed-state mechanism
- memory replay
- richer typed-state
- planner openness
- open / LangGraph extension
- git 风格管理
- 其他潜在加分方向

当前正确的态度不是“放弃它们”，而是区分三件事：

1. `保留`
   - 有价值，不删
2. `主线化`
   - 进入当前主问题的核心裁决
3. `延后`
   - 先保留，但不进入本轮 headline 判断

当前仓库的一个重要问题，就是过去很多“值得保留”的东西，被一并挂进了“当前主线必须同时成立”的位置。

这会直接导致主线越来越重，最终无法判断：

- 到底是 benchmark 问题
- 还是方法问题

---

## 7. 当前主线建议

当前最合理的唯一主问题应当是：

> 在一个可信、单变量、足够厚的赛题 benchmark 上，structured protocol 是否比 pure-text handoff 更有优势？

围绕这个问题：

### 7.1 当前应进入主线裁决的资产

- contest headline object
- typed-state minimal mechanism
- memory replay（仅当它确实在主路径、且确实属于主问题）

### 7.2 当前可以保留但不进入本轮裁决的东西

- planner openness
- open extension
- LangGraph extension
- 更丰富 typed-state
- git 风格管理
- 其他赛题加分创新点

这不是放弃它们，而是为了先让主线变清楚。

---

## 8. 新窗口第一阶段必须先完成什么

新窗口第一阶段不要直接实现。

第一阶段必须先完成以下产出：

### 8.1 产出一份 benchmark 立项方案

至少明确：

1. 什么样的 benchmark 才算可信
2. 什么情况下判定 benchmark 不合格
3. 什么情况下判定 benchmark 合格但方法无优势
4. 什么情况下才允许说 protocol 有 headline 优势

### 8.2 产出一份 headline benchmark 最小对象定义

至少明确：

1. 最少几跳协作
2. 是否必须有跨任务依赖
3. 是否必须有竞争 route
4. text / protocol 两侧各自允许看到什么
5. 哪些能力双方都允许，哪些不允许

### 8.3 产出一份本轮不进入裁决的清单

明确哪些创新点保留但延后，不进入当前主问题裁决。

---

## 9. 新窗口必须优先阅读的文档

### 9.1 赛题与边界

- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`

### 9.2 当前认知与 benchmark 立项

- `docs/analysis/statebus_current_thinking_reset_20260617.md`
- `docs/review/statebus_benchmark_charter_20260617.md`

### 9.3 当前全局扫描与最新审计

- `docs/analysis/statebus_full_repo_scan_20260617.md`
- `docs/analysis/honest_full_audit_20260617.md`
- `docs/analysis/mainline_repeat3_analysis_20260617.md`

### 9.4 如需继续下钻的计划文档

- `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
- `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`

---

## 10. 新窗口第一任务

新窗口的第一任务不是直接改代码。

第一任务是：

> 基于上述文档，建立一套可信 benchmark 的方案和流程，先收 benchmark，再决定方法主线。

如果这一步做不好，后面继续做 runtime / task / pack 改动，只会继续把混乱往后推。
