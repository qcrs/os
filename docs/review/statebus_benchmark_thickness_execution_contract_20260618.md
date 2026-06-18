# StateBus Benchmark 厚化与方法评测准入合同

日期：`2026-06-18`

适用范围：

- 仓库：`/home/qcrs/statebus/project`
- 环境：host + 本地 conda
- 主对象：`contest_honest_headline_v1`

定位：

- 回答“到底是不是先改 benchmark、要改到什么程度、什么时候才能开始评方法”
- 这是当前阶段的执行合同，不是历史回顾

---

## 1. 结论先说

是的，当前必须先改 benchmark。

但不是重新回到“benchmark correctness / object purity”那一轮，而是进入下一层：

1. `benchmark correctness`
2. `object purity`
3. `task thickness`
4. `method strength`

截至当前状态：

- `contest_honest_headline_v1` 在 `correctness + object purity` 上已经基本过关
- 但它**还没有过 `task thickness`**
- 所以现在还**不能**把它当成判断“方法本身有没有问题”的最终 benchmark

---

## 2. 当前已经证明了什么

当前已经能稳定确认：

1. `contest_honest_headline_v1` 是唯一 contest-facing headline
2. 它已经是 single-variable `mode`
3. `whole-lane text guard`、`hidden field leak`、`object parity gate`、`formal stability gate` 已经通过
4. report / row-level / gate 的主语义目前没有明显打架

这意味着：

- 当前 benchmark 不再主要卡在 hidden fallback、support surface 冒充 headline、report bug 这类问题

---

## 3. 当前还没有证明什么

当前还没有证明：

1. headline task 已经足够厚
2. protocol 的结构化优势已经获得足够展开空间
3. 当前“protocol 只有 bytes 优势、时延没拉开”是方法问题而不是 benchmark 厚度问题

当前最关键的反证是：

- fresh retrieval 下每个 case 仍基本收缩为很短的固定链路
- 当前 headline 仍主要是 `bounded_alternative` 式受控分流
- 还不够接近“connected multihop + cross-task dependency + explicit abstention boundary”

---

## 4. Benchmark 现在到底要修到什么程度

当前 headline 只有满足下面四层，才允许进入方法评测：

### 4.1 第一层：correctness

必须继续保持：

- `contest_honest_headline_v1` 仍是唯一 headline
- `single_variable = true`
- `variable_axes = [mode]`
- text / protocol case 数完全配对
- `formal_structure_clean_retrieval = true`

### 4.2 第二层：object purity

必须继续保持：

- `whole-lane text guard = 1.00`
- `hidden_field_leak = 0.00`
- `summarizer typed visibility = 0.00`
- `object parity gate = pass`
- report / json / row-level 一致

### 4.3 第三层：task thickness

这是当前**尚未通过**的一层。要通过，至少满足：

1. **Connected multihop**
   - headline 主 slice 不能再全部是固定的短三步链
   - 至少一类 headline case 需要两个连续依赖的中间决策
   - 删掉其中一跳后，route/tool/action 就会不成立

2. **Cross-task dependency**
   - `replay_reusable` 不只是“上一题答过”
   - prior rejection / prior scoped action 必须实质改变下一题的 admissible action

3. **Real route/tool competition**
   - `distractor` 和 `ambiguous` 必须保留至少两个真实竞争分支
   - 不是 query 一眼就把正确 route/tool 暗示出来

4. **Explicit abstention boundary**
   - 至少一部分 case 必须存在被允许的 abstain / collect-more-evidence 边界
   - 且这个边界是 score-valid 的，不是文案装饰

5. **Depth is explicit**
   - 厚度不能只靠主观解释
   - 必须在 case contract 或 family contract 里显式写出深度/依赖信息

### 4.4 第四层：method strength

只有前三层都过关后，才允许正式判断：

- protocol 是否只是 bytes 更低
- 还是 correctness / latency 也形成稳定优势
- 如果没有优势，到底该判 benchmark 问题还是方法问题

---

## 5. 厚度层的具体衡量标准

当前需要的不只是“更难”，而是“更可解释地更厚”。

建议把厚度 gate 写成下面五条硬标准：

### 5.1 结构标准

每个 headline family 仍保留：

- `clean`
- `distractor`
- `ambiguous`
- `replay_reusable`

但要补充显式厚度字段，建议最少新增：

- `reasoning_hops_min`
- `dependency_depth`
- `route_competition_min`
- `tool_competition_min`
- `abstention_boundary`
- `expected_intermediate_decisions`

这一步的目标是让“任务厚不厚”先成为**静态可检查对象**。

### 5.2 轨迹标准

当前 `planned_step_count = 3` 基本可以视为过薄 floor。

下一轮厚化后，headline 的 `fresh_retrieval` 主 slice 应至少满足：

- 不再整体塌成固定三步
- 至少存在可稳定跑出的 `>= 5` step thickened cases
- 且这些额外 step 不是无意义的 filler，而是中间判定 / 证据补充 / 依赖承接

### 5.3 依赖标准

`replay_reusable` 的合格线应提升为：

- prior case 的 rejection / scoped action 缺失时，下一题应改变 admissible action
- 不能只是“上一题相似，所以可以重用”

### 5.4 竞争标准

下一轮厚化后：

- `clean` 不允许是几乎无竞争的一眼题
- `distractor` 必须有强竞争但仍可排除
- `ambiguous` 必须有保留分支，允许通过额外 evidence 或 abstention 收口

### 5.5 验证标准

厚度通过前，不能只看 headline 表。

必须同时通过：

- static contract tests
- row-level pairing / dependency tests
- deterministic repeat=1
- API repeat=1

---

## 6. 什么时候才能开始用 benchmark 测方法

只有同时满足下面四条，才允许把 benchmark 用来裁决方法：

1. `correctness` 继续绿
2. `object purity` 继续绿
3. `task thickness` 的静态合同已经落盘并通过测试
4. thickened headline 在 deterministic/API repeat=1 下没有新引入的对象污染

如果还没有同时满足：

- 不能因为 `repeat=10` 跑完了就开始判方法
- 不能因为 protocol 目前只有局部 bytes 优势就判方法弱

---

## 7. 当前建议的设置对比方式

不要继续新开 headline pack。

当前建议只比较三个 setting，且都围绕**同一个 headline 主对象**：

| setting | 目的 | 当前状态 | 允许得出的结论 |
| --- | --- | --- | --- |
| `S0 current_honest_floor` | correctness + object purity floor | 已存在 | 只能说明对象干净，不足以判方法 |
| `S1 within_case_multihop` | 增加 connected multihop，不引入更强跨任务依赖 | 待设计 | 用来判断“多跳本身”是否放大 protocol 优势 |
| `S2 dependency_thickened` | 在 `S1` 基础上强化 cross-task dependency / reusable contract | 待设计 | 用来判断“依赖与重用”是否进一步放大 protocol 优势 |

比较规则：

- `S0` 不是最终方法 benchmark，只是 object floor
- `S1` 与 `S2` 共享同一 scoring / loader / logging
- 只允许一次改变一个主维度

---

## 8. 当前最该借的外部 benchmark 参考

当前厚化阶段最该直接吸收的参考顺序：

1. `MuSiQue`
   - connected multihop
2. `HotpotQA`
   - supporting facts + distractor setting
3. `BRIGHT`
   - reasoning-before-retrieval
4. `AgentEscapeBench`
   - dependency depth / explicit DAG
5. `LongMemEval-V2`
   - history-to-evidence memory gathering
6. `BenchAgent`
   - normalized loader / logging contract
7. `τ-bench`
   - end-state verifier + reliability

详细映射见：

- `docs/review/statebus_external_benchmark_survey_20260618.md`

---

## 9. 当前最急需解决的问题

按优先级排序：

1. **旧 prompt 仍停留在 correctness/object-purity 收口阶段**
   - 会让新窗口误以为只要 `repeat=10` 通过就能评方法

2. **没有厚度层的静态合同**
   - 现在“任务太薄”还是解释，不是 contract

3. **没有保存过的外部 benchmark 调研**
   - 每次都在重新回忆和争论

4. **没有统一的 setting comparison protocol**
   - 很容易把 `S0` 与 `S1/S2` 混读

5. **没有方法评测准入门**
   - 导致 benchmark 还没合格时，就开始争论方法是否有问题

---

## 10. 可执行工作顺序

当前最合理的顺序是：

1. 先更新 prompt 与阅读入口
2. 先落“厚化与方法评测准入合同”
3. 先落外部 benchmark 调研文档
4. 再设计 `S1/S2` 的 family spec 变化
5. 先做 static tests
6. 再做 deterministic/API repeat=1
7. 只有厚化后的 canonical headline 确定后，才重新进入 repeat=3 / repeat=10

---

## 11. 当前明确不做

- 不新开 permanent headline pack
- 不先做 runtime 优化
- 不继续对当前 `S0` 做更多重型 repeat 套件
- 不把 `planner_support_v3` / `memory_dual_mode_fairness_v3` 拉回 headline 裁决
- 不把 WebArena / SWE-bench 这类环境级 benchmark 直接并进当前主线

