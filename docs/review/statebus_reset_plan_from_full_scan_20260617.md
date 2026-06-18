# StateBus 收口计划（基于全量扫描）

日期：2026-06-17

来源文档：

- `docs/analysis/statebus_full_repo_scan_20260617.md`

定位：

- 本文档不是全量扫描报告。
- 本文档只承担“基于扫描结论形成的收口计划”职责。
- 如果要判断这些计划是否值得执行，必须先读扫描报告，而不是直接读本计划。

---

## 1. 核心判断

当前项目不是已经发散到无法收口，但也不在最优轨道上。

当前最核心的问题不是“再加一个新 surface”或“继续补一个小 bug”，而是：

1. 解释成本已经偏高
2. benchmark surface 膨胀过快
3. 局部修补积累多于系统性收口

因此更合理的路线不是继续发散，而是：

`收缩 benchmark surface -> 修已确认 report bug -> 跑 formal repeat=10 -> 再决定是否厚化任务`

---

## 2. 收口主线

目标：

- 将当前 13+1 个活跃/半活跃 pack 收缩到 5-6 个真正回答赛题核心问题的 pack
- 修掉已经确认的 report / metric 语义错误
- 先把正式 headline 所需的稳定性证据补齐
- 在此之前不继续增加新 surface

---

## 3. Phase A：收缩 Benchmark Surface

目标：

- 降低解释成本
- 降低维护成本
- 让仓库对外只保留真正有主线意义的 surface

建议动作：

1. 移除或归档以下 pack 的“活跃主套件默认运行资格”
   - `typed_state_authenticity_v3`
   - `typed_state_full_rich_audit_v3`
   - `carrier_microbench_v3`
   - `text_definition_audit_v3`
2. 重新判断 `external_text_baseline_audit_v3`
   - 如果不能升级成真实 baseline，就保持 audit-only，且不进主套件 headline 解读
3. 保留以下 pack 为主线：
   - `contest_honest_headline_v1`
   - `typed_state_mechanism_v3`
   - `memory_policy_controlled_v3`
   - `memory_reuse_v3`
   - `typed_state_consumer_sensitivity_v3`
   - `planner_support_v3`
4. 将 `contest_dual_mode_controlled_v3` 明确固定为 internal regression gate，不再承担对外 headline 解释

边界：

- 只减不增
- 不新增 benchmark pack
- 不新增 handoff_profile
- 不新增 transfer_strategy

---

## 4. Phase B：修已确认 Report Bug

目标：

- 先修结论表达层的硬错误
- 防止后续 repeat=10 结果继续被错误报表污染

必须先修的两项：

1. `planner_one_shot_valid_rate` 聚合错误
   - 来源：`planner_support_v3`
   - 症状：header 与 table 矛盾，row-level 与 aggregate 矛盾
2. `memory_dual_mode_fairness_v3` 的空 case contract 被标成 `mismatch`
   - 应改为 `not_evaluated` 或等价语义

当前执行状态补充：

- 这两项应优先于新的 benchmark 扩张。
- 修复完成后，只需要用 deterministic `repeat=1` 验证报表与 row-level 一致，不把这一步读成新的 formal evidence。

建议验证：

- 跑 deterministic repeat=1
- 只验证报表语义是否与 row-level 一致

边界：

- 不借此扩展新指标
- 不新增新的解释性 payload/guard

---

## 5. Phase C：补正式 Stability Gate

目标：

- 不再让“repeat=3 的诚实 headline”长期停留在半正式状态

建议只跑少数关键 pack：

1. `contest_honest_headline_v1`
2. `typed_state_mechanism_v3`
3. `memory_policy_controlled_v3`

输出目标：

- 三份正式 repeat=10 稳定性证据

边界：

- 不要求所有 13+1 pack 都跑 repeat=10
- 不在这一步做架构改造

---

## 6. Phase D：厚化任务对象（可选后续）

只有在 Phase A-C 完成后，才建议考虑这一步。

目标：

- 解决“结果总是差不多”的根因之一：任务太薄，protocol 优势无法复合

建议方向：

1. 增加真正多跳 collaborative family
2. 增加真正跨任务依赖
3. 让 structured handoff 在多轮 agent 交接中产生复利优势

边界：

- 这一步是对象重整，不是为了硬拉指标
- 不允许通过 hidden fallback、pack-specific override 或 support surface 包装 headline 来“修结果”

---

## 7. 当前不建议启动的路线

在收口阶段，不建议启动：

1. Docker / openEuler / nsjail
2. CodeAct 主路径改造
3. 新的 richer typed-state variant
4. 新的 report guard / audit / payload 继续膨胀
5. 新 benchmark pack 的继续扩张

---

## 8. 读法说明

如果只是想理解“项目当前到底出了什么问题”，先读：

- `docs/analysis/statebus_full_repo_scan_20260617.md`

如果已经接受扫描结论，想判断“下一条主线该怎么收”，再读：

- 本文档
