# StateBus 新窗口工作指引

日期：`2026-06-17`

定位：

- 这不是单一 benchmark 文档。
- 这不是某个 pack 的审计结论。
- 这是一份给“新窗口/新会话/新协作者”的高层工作指引。

这份文档的目标是先把当前项目的混乱来源、真正问题、当前重心、第一阶段任务和工作顺序讲清楚，避免新窗口一上来就继续陷入局部修补。

---

## 1. 当前最核心的问题是什么

当前项目最核心的问题，不是“再修一个 bug”或“再跑一轮 repeat=3”。

当前最核心的问题是：

**项目的认知地图已经落后于项目本身的复杂度。**

具体表现：

1. 太多 benchmark pack
2. 太多历史阶段文档
3. 太多“这个回答 A、不回答 B”的解释边界
4. 太多历史修补仍挂在当前主视野
5. 太多“值得保留”的创新点同时挤在当前主线里

这会导致：

- 每个局部看起来都合理
- 但整体越来越难回答“这个项目现在主线到底是什么”
- 每做一步都像在推进，但主线感越来越弱

所以当前必须先做的，不是继续无边界推进，而是先重新建立工作顺序、判断框架和主线边界。

---

## 2. 当前项目里混了两种不同目标

新窗口必须先区分这两种目标，否则后面一定会再次混乱。

### 2.1 目标一：证明机制真实性

这条线关注：

- 多 Agent 真实协作
- protocol 真实传递结构化信息
- typed-state 真实生产、传递、消费
- replay 真实减少重复工作

这条线当前已经做出了不少真实资产。

### 2.2 目标二：证明 protocol 在正式 contest headline 上明显优于 text baseline

这条线关注：

- latency 更低
- token 更少
- correctness 更高
- 端到端差异更明显

这条线当前还没有站稳。

### 2.3 当前痛苦的根源

最近大量工作主要在修：

- fairness
- headline object
- support surface 分离
- report 语义
- benchmark 读法边界

这些工作非常重要，但它们更像是在让系统“更诚实、更可辩护”，而不是直接让方法能力变得明显更强。

所以当前的感受“做了很多，但方法没有明显变强”不是错觉。

---

## 3. 当前更像是哪里出了问题

当前不应直接下结论说“方法无效”，也不应直接下结论说“只是 benchmark 坏了”。

当前更接近事实的判断是：

1. 方法有真实机制价值
2. 当前 headline 对象比以前诚实很多
3. 当前任务对象太薄，差异没有被充分放大
4. text 侧不是特别弱的消费者，所以 protocol 优势不会自动显著
5. 现阶段更该优先怀疑 benchmark 对象、任务厚度、裁决边界，而不是先判方法死刑

因此当前“结果差不多”更像是在说明：

> 当前正式对象还不足以强区分两种协作方式的端到端收益。

这不等于方法无效，但也不足以证明方法已经强到可以直接 headline claim。

---

## 4. 当前最大的混乱不是代码，而是对象和叙事

代码当然有 monolith / 石山化信号，但当前更严重的问题其实在：

1. benchmark 对象太多
2. 文档阶段太多
3. 主线和支线长期混读
4. support surface 和 headline 曾长期纠缠
5. “值得保留”与“应该主线化”没有分开

所以新窗口不要把问题简单理解为：

- “代码太乱所以要重构代码”

当前更准确的理解是：

- “对象、文档、benchmark、叙事边界太乱，导致任何代码讨论都会飘”

---

## 5. 当前必须先建立的工作顺序

新窗口必须遵守下面这个顺序。

### 5.1 先判断 benchmark 是否回答了对的问题

先问：

- 这个对象是不是赛题允许的对象
- 这个比较是不是我们真正想裁决的问题

### 5.2 再判断 benchmark 是否单变量、公平、对象纯净

先排：

- object purity
- single-variable
- support surface 混入
- hidden fallback
- report 与 row-level 不一致

### 5.3 再判断 benchmark 是否足够厚，能放大差异

先问：

- 协作跳数是否足够
- 是否有跨任务依赖
- 是否有 route 竞争
- 是否有足够空间让 protocol 的结构化优势复利

### 5.4 最后才判断方法本身是否没形成优势

只有在前三层都过关后，才能正式判断方法问题。

这一步顺序必须固定，不能倒过来。

---

## 6. 当前最重要的框架：保留 / 主线化 / 延后

当前不是要放弃创新点，而是要先分层。

### 6.1 保留

表示它有价值，不删。

### 6.2 主线化

表示它现在就要进入当前核心叙事、核心 benchmark、核心实现路径。

### 6.3 延后

表示它先保留，但不进入当前主问题裁决。

当前项目一个非常关键的问题，就是过去很多“值得保留”的东西，被一起放进了“当前主线必须同时成立”的位置。

这会直接导致：

- 主线越来越重
- 难以判断到底是 benchmark 问题还是方法问题

---

## 7. 当前建议的唯一主问题

如果新窗口要帮当前项目重新建立秩序，建议围绕这一句作为唯一主问题：

> 在一个可信、单变量、足够厚的赛题 benchmark 上，structured protocol 是否比 pure-text handoff 更有优势？

这句话有几个好处：

1. 不否认机制真实性的重要性
2. 不预设方法已经赢
3. 强制把 benchmark 立项放在前面
4. 强制把“对象是否可信”与“方法是否足够强”分开

---

## 8. 当前应进入主线裁决的资产

当前这轮主问题里，只建议保留最少量资产进入主线裁决：

1. contest headline object
2. typed-state minimal mechanism
3. memory replay（仅当它确实在主路径、且确实属于主问题）

---

## 9. 当前可以保留但不进入本轮裁决的东西

这些东西可以保留，但不应混入当前主问题的 headline 裁决：

1. planner openness
2. open extension
3. LangGraph extension
4. 更丰富 typed-state
5. git 风格管理
6. 其他赛题加分创新点

这不是放弃，而是为了防止主线再次发散。

---

## 10. 当前第一阶段应该先产出什么

新窗口第一阶段不要直接改代码。

第一阶段应该先产出三样东西：

### 10.1 一份可信 benchmark 立项方案

至少明确：

1. 什么样的 benchmark 才算可信
2. 什么情况下 benchmark 直接判不合格
3. 什么情况下 benchmark 合格但方法无优势
4. 什么情况下才允许说方法有 headline 优势

### 10.2 一份 headline benchmark 最小对象定义

至少明确：

1. 最少几跳协作
2. 是否必须有跨任务依赖
3. 是否必须有竞争性 route
4. text / protocol 两侧各自允许看到什么
5. 哪些能力双方都允许，哪些不允许

### 10.3 一份本轮不进入裁决的支线清单

把“保留但延后”的东西明确写死，避免再次把所有创新点一起拖进主线。

---

## 11. 当前成功标准和失败标准应该如何理解

### 11.1 成功标准

当前至少要允许以下几种结论：

1. benchmark 不合格
2. benchmark 合格，但方法没显出优势
3. benchmark 合格，方法有局部优势
4. benchmark 合格，方法有稳定 headline 优势

### 11.2 失败标准

以下情况不能直接被读成“方法失败”：

1. benchmark 对象不纯
2. 任务太薄
3. report 聚合 bug
4. row-level 与 headline 不一致
5. support surface 被误读成 headline

---

## 12. 当前最需要警惕的事情

新窗口必须避免以下几类错误动作：

1. 一上来继续扩新 pack
2. 一上来继续改 runtime 主逻辑
3. 一上来继续堆更多解释性文档
4. 把“值得保留”误当成“必须主线化”
5. 在 benchmark 没立住前就下方法结论

---

## 13. 新窗口必读文档

### 13.1 赛题与边界

- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`

### 13.2 当前认知与 benchmark 立项

- `docs/analysis/statebus_current_thinking_reset_20260617.md`
- `docs/review/statebus_benchmark_charter_20260617.md`
- `docs/review/statebus_new_window_bootstrap_20260617.md`

### 13.3 当前全局扫描与最新审计

- `docs/analysis/statebus_full_repo_scan_20260617.md`
- `docs/analysis/honest_full_audit_20260617.md`
- `docs/analysis/mainline_repeat3_analysis_20260617.md`

### 13.4 当前收口计划与主线讨论

- `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
- `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`

---

## 14. 给新窗口的第一任务

新窗口的第一任务不是直接进入实现。

第一任务应当是：

> 基于上述文档，先建立一套可信 benchmark 的方案和流程，并重新梳理当前主线与支线边界，再决定是否进入代码级重构。

如果这一步做不好，后续无论是改 benchmark、改 runtime、还是补创新点，都会继续在混乱中打转。
