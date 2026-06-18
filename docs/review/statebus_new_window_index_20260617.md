# StateBus 新窗口阅读入口索引

日期：`2026-06-17`

用途：

- 给以后新开窗口 / 新会话快速建立上下文
- 避免每次重新手工组织文档入口

---

## 1. 如果只想快速启动新窗口

当前最新推荐：

- `docs/review/statebus_new_window_benchmark_thickness_prompt_20260618.md`

适用情况：

- `contest_honest_headline_v1` 的 correctness/object purity 基本收口后
- 当前要处理的是 `task thickness`、外部 benchmark 参考映射、方法评测准入门

上一阶段的完整长 prompt 仍保留在：

- `docs/review/statebus_new_window_super_long_prompt_20260617.md`

---

## 1.1 如果当前是 benchmark 厚化阶段

优先再读：

1. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
2. `docs/review/statebus_external_benchmark_survey_20260618.md`

用途：

- 明确 benchmark 还要修到什么程度
- 明确什么时候才允许开始评方法
- 明确外部 benchmark 参考已经落到什么程度

---

## 1.2 如果只想回看上一阶段的新窗口材料

直接使用这份长 prompt：

- `docs/review/statebus_new_window_super_long_prompt_20260617.md`

这是上一阶段最完整的版本，包含：

- 环境边界
- 赛题约束
- 当前混乱来源
- 必读文档顺序
- 必看代码与 run
- 第一阶段必须先产出的 deliverables

---

## 2. 新窗口建议阅读顺序

### 第一步：先理解“为什么现在会乱”

先读：

1. `docs/review/statebus_new_window_guidance_20260617.md`
2. `docs/review/statebus_new_window_bootstrap_20260617.md`
3. `docs/analysis/statebus_current_thinking_reset_20260617.md`

用途：

- 理解当前不是单点 bug，而是认知地图落后于复杂度
- 理解为什么当前第一阶段不能直接改代码
- 理解为什么要先 benchmark、再主线

### 第二步：再理解 benchmark 该如何立项

接着读：

4. `docs/review/statebus_benchmark_charter_20260617.md`
5. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`

用途：

- 明确可信 benchmark 的硬条件
- 明确当前的收口主线
- 明确哪些东西该保留，哪些先不进裁决

### 第三步：再读当前最完整的扫描与审计

再读：

6. `docs/analysis/statebus_full_repo_scan_20260617.md`
7. `docs/analysis/honest_full_audit_20260617.md`
8. `docs/analysis/mainline_repeat3_analysis_20260617.md`

用途：

- 看当前项目全局地图
- 看最新的高证据密度审计
- 看最新主 run 的解释

### 第四步：最后回到赛题与仓库边界

最后再读：

9. `README.md`
10. `docs/reference/题目.md`
11. `docs/constraints/current_host_and_migration.md`
12. `docs/constraints/current_feature_scope.md`
13. `docs/planning/implementation_plan.md`
14. `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`

用途：

- 重新对齐赛题
- 确认 host 本地边界
- 确认当前实现范围

---

## 3. 这些文档各自回答什么

### `statebus_new_window_guidance_20260617.md`

回答：

- 当前项目真正为什么乱
- 当前两种目标如何混在一起
- 为什么第一阶段必须先做 benchmark 方案与主线边界

### `statebus_new_window_bootstrap_20260617.md`

回答：

- 新窗口必须先知道的前因后果
- 为什么不能继续无边界修补
- 当前第一任务应该是什么

### `statebus_current_thinking_reset_20260617.md`

回答：

- 当前最该看清的几件事
- 当前更像是解释层复杂，而不是方法已经死了

### `statebus_benchmark_charter_20260617.md`

回答：

- 什么叫可信 benchmark
- 成功标准 / 失败标准 / 对象纯净 / 任务厚度 / 一票否决项

### `statebus_reset_plan_from_full_scan_20260617.md`

回答：

- 如果接受当前扫描结论，下一条收口主线怎么走

### `statebus_full_repo_scan_20260617.md`

回答：

- 当前仓库全局地图
- benchmark pack 地图
- 创新点落地状态
- 架构与 benchmark 复杂度诊断

### `honest_full_audit_20260617.md`

回答：

- 当前最细致、证据密度最高的局部审计结论
- 哪些是 report bug
- 哪些是对象问题
- 哪些是 fairness 问题

### `mainline_repeat3_analysis_20260617.md`

回答：

- 当前最新主 run 的结果解释
- `contest_honest_headline_v1` 当前到底证明了什么、没证明什么

---

## 4. 推荐给新窗口的第一任务

第一任务不要直接改代码。

第一任务应该是：

1. 基于上述文档建立一套可信 benchmark 方案
2. 重新划定当前主线 / 支线 / 延后项
3. 给出第一阶段应产出的 deliverables
4. 只有在 benchmark 和主线边界站稳后，才讨论代码级实现

---

## 5. 当前最推荐的 prompt

如果要直接开新窗口，优先使用：

- `docs/review/statebus_new_window_benchmark_thickness_prompt_20260618.md`

如果新窗口需要先知道“为什么之前会混乱、上一阶段怎么收 correctness/object purity”，再补读：

- `docs/review/statebus_new_window_super_long_prompt_20260617.md`

如果只是想让对方快速理解背景，也可以先给：

- `docs/review/statebus_new_window_guidance_20260617.md`

---

## 6. 当前边界提醒

新窗口必须记住：

- 当前只看 host 本地代码、文档、测试、benchmark 结果
- 当前环境是 `(/home/qcrs/statebus/conda-envs/statebus_host)`
- 当前不涉及真实 VM / openEuler / Docker / nsjail
- 当前第一原则是：先建立可信 benchmark 和主线边界，再判断方法
