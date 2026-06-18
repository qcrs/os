# StateBus 新窗口 Prompt：Benchmark 厚化阶段

日期：`2026-06-18`

用途：

- 给新窗口 / 新会话 / 新协作者的当前推荐 prompt
- 适用于“correctness/object purity 已基本收口，当前进入 task thickness 阶段”的状态
- 这是当前阶段的唯一推荐启动 prompt

---

```text
你现在在 `/home/qcrs/statebus/project` 工作。

你必须只在本地 host 环境下工作：
- cwd: `/home/qcrs/statebus/project`
- conda: `/home/qcrs/statebus/conda-envs/statebus_host`
- activate: `source deploy/activate_statebus_host.sh`

硬边界：
- 不做 Docker
- 不做 openEuler / VM
- 不做 nsjail
- 不做系统外部署
- 不扩 benchmark pack 数量
- 不先做 runtime 主链路重构

你这次的任务不是重新审 correctness/object purity，也不是继续跑更多旧 benchmark。
你当前唯一主线是：

把 `contest_honest_headline_v1` 从“对象基本合格但任务偏薄”的状态，推进到“厚度合同明确、可以开始正式评方法”的状态。

你必须先接受下面这个阶段判断：

1. `benchmark correctness`：当前基本通过
2. `object purity`：当前基本通过
3. `task thickness`：当前还没通过
4. `method strength`：当前还不能正式裁决

因此：
- 当前不能把已有 `repeat=10` 读成“主线已经结束”
- 当前不能把“protocol 只有 bytes 优势、时延没拉开”直接读成方法结论
- 当前必须先回答：benchmark 还要修到什么程度，什么时候才允许评方法

你必须把当前工作阶段固定为：

- 先把 benchmark 厚度做成静态合同
- 再把厚化实现落到 `contest_honest_headline_v1`
- 再做最小验证
- 最后才决定是否进入下一轮方法评测

====================
一、必须先读的文档
====================

按下面顺序读：

1. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
2. `docs/review/statebus_external_benchmark_survey_20260618.md`
3. `docs/review/statebus_benchmark_charter_20260617.md`
4. `docs/review/statebus_new_window_guidance_20260617.md`
5. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
6. `docs/analysis/statebus_full_repo_scan_20260617.md`
7. `docs/analysis/mainline_repeat3_analysis_20260617.md`
8. `README.md`
9. `docs/reference/题目.md`
10. `docs/constraints/current_host_and_migration.md`
11. `docs/constraints/current_feature_scope.md`

如果需要继续下钻，再读：

12. `tasks/contest_family_spec.py`
13. `tasks/contest_family_spec.yaml`
14. `eval/runner.py`
15. `tests/test_smoke.py`

====================
二、当前唯一主问题
====================

你必须只围绕下面这句工作：

“在一个可信、单变量、足够厚的赛题 benchmark 上，structured protocol 是否比 pure-text handoff 更有优势？”

当前不要把这个问题偷换成：

- typed-state 机制是否真实
- planner openness 是否成立
- memory replay 是否独立更强
- open extension 是否更先进

这些都可以保留，但不进入当前 headline 裁决。

====================
三、当前你要先回答的问题
====================

你必须先回答并落成文档/计划：

1. 当前 benchmark 还差哪些厚度条件
2. benchmark 到底要修到什么程度才算“可开始评方法”
3. 现有 `contest_honest_headline_v1` 的哪些部分保留、哪些部分要厚化
4. 如何只在现有 headline 对象上做 `S0 / S1 / S2` setting 对比，而不是继续膨胀 pack
5. 外部 benchmark 参考里，哪些原则已经明确要借，哪些明确不借
6. 下一轮实现之前，哪些静态测试必须先补
7. 什么结果才允许从 `S0` 进入 `S1`，再从 `S1` 进入 `S2`

====================
四、你现在允许做的事
====================

当前阶段只允许：

- benchmark 厚度合同设计
- family spec / task contract 设计
- external benchmark reference 映射
- static thickness tests 设计
- `S0 / S1 / S2` comparison protocol 设计
- 本地文档、计划、测试护栏设计
- 只针对 `tasks/contest_family_spec.py` 与 `tasks/contest_family_spec.yaml` 的厚化设计
- 为厚化设计补静态测试，不先扩 runtime

当前阶段不允许：

- 再跑更多当前 `S0` 的重型 repeat 套件
- 直接开始方法优化
- 先重构 runtime 再说
- 把 support/audit surface 升格成 headline
- 用新增 pack 逃避现有 headline 厚化
- 把外部 benchmark 直接导入为新的 headline 数据集
- 在 `S1/S2` 合同没落盘前继续堆 API 重跑

====================
五、你必须产出的 deliverables
====================

这轮至少要产出：

1. 一份“benchmark 厚化执行方案”
   - `S1` 怎么设计
   - `S2` 怎么设计
   - 每一步改什么字段、什么 family、什么测试

2. 一份“方法评测准入门”
   - 哪些 gate 过了才允许评方法
   - 哪些情况下仍只能说 benchmark 不合格

3. 一份“外部 benchmark 到 StateBus 的映射表”
   - 参考谁
   - 借什么
   - 不借什么

4. 一份“setting comparison protocol”
   - `S0 current_honest_floor`
   - `S1 within_case_multihop`
   - `S2 dependency_thickened`
   - 每个 setting 允许读成什么，不允许读成什么

5. 一份“下一轮实施顺序”
   - 先文档
   - 再 contract
   - 再 static tests
   - 再 deterministic/API repeat=1
   - 再决定是否进入 repeat=3 / repeat=10

6. 一份“进入下一轮的 admission gate”
   - 哪些文档必须已更新
   - 哪些静态测试必须已通过
   - 哪些最小运行命令必须已通过

====================
六、输出要求
====================

你的输出必须区分：

1. 已证明的
2. 未证明的
3. 当前 benchmark 缺口
4. 当前最急需落地的修改
5. 什么时候才允许评方法

不要把“当前对象更干净了”写成“benchmark 已经没问题了”。
不要把“现在 protocol 只有局部优势”写成“方法已经不行了”。
不要把“参考了外部 benchmark”写成“已经落实厚化实现”。

====================
七、第一原则
====================

当前第一原则不是“证明方法赢”，而是：

先把 benchmark 修到能合法评方法的程度。

如果 benchmark 还没过厚度门：
- 继续修 benchmark
- 不判方法

====================
八、执行顺序
====================

如果你开始真正落地，顺序固定为：

1. 先读合同与调研文档
2. 先写出 `S1/S2` 厚化方案，不直接改代码
3. 先给出字段级改动清单：
   - 改哪些 family
   - 加哪些 thickness 字段
   - 哪些 case 保留为 `S0`
   - 哪些 case 升到 `S1`
   - 哪些 dependency 升到 `S2`
4. 先补 static tests
5. 再改 `tasks/contest_family_spec.py` 与 `tasks/contest_family_spec.yaml`
6. 再跑 deterministic/API `repeat=1`
7. 只有最小验证通过，才允许讨论 `repeat=3` / `repeat=10`

====================
九、你最终交付的答案格式
====================

你的最终答案必须至少包含：

1. 当前阶段判断
   - 已证明什么
   - 未证明什么
2. benchmark 厚化缺口
3. `S1` 设计
4. `S2` 设计
5. 静态测试方案
6. 最小验证命令
7. 是否允许进入下一轮
```
