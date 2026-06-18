# StateBus Goal 3 下一轮 Prompt：Formal Stability / Repeat Closure Only

日期：`2026-06-18`

适用范围：

- 仓库：`/home/qcrs/statebus/project`
- 环境：`/home/qcrs/statebus/conda-envs/statebus_host`
- 当前阶段：`S1 completed + S2 completed + memory/replay effect completed + formal stability not yet closed`

用途：

- 给新窗口 / 新 goal 会话直接使用
- 以前面 benchmark/task object 整理、`S1`、`S2`、memory/replay effect 都已成立为前提
- 明确约束下一轮只能做 `formal stability / repeat closure`

---

```text
你现在进入 goal 模式。

工作目录固定为：
`/home/qcrs/statebus/project`

环境进入后先执行：
```bash
source deploy/activate_statebus_host.sh
cd /home/qcrs/statebus/project
```

你当前执行的是 Goal3 的下一轮，但这次不是重新做 Goal2，不是继续整理 benchmark/task object，也不是去做方法优化。

你这次只有一个允许推进的目标：

> 关闭 `contest_honest_headline_v1` 的 formal stability / repeat closure。

你必须先接受下面这个当前状态：

1. Goal2 已完成，当前是冻结的事实层、问题地图、外部校准和 stopline。
2. Goal3/S1 已完成。
3. Goal3/S2 已完成。
4. Goal3/current-headline memory/replay effect 已完成。
5. 当前 headline 已具备：
   - 真实 `S1 connected multihop behavior`
   - 真实 `S2 prior-dependent admissible-action change`
   - current headline 同一 run 内的真实 memory/replay effect
6. 当前剩余的唯一主阻塞是：
   - `formal_stability_gate.required_repeat = 10`
   - 当前还只有 repeat=1 层证据
   - `withheld_headline_reason = contest_repeat_insufficient`

你必须接受下面这些当前事实：

- 当前 S1 关键 artifact：
  - `/home/qcrs/statebus/runs/contest_honest_headline_goal3_s1_runtime_det_r1_20260618_123323`
- 当前 S2 关键 artifact：
  - `/home/qcrs/statebus/runs/contest_honest_headline_goal3_s2_runtime_det_r1_20260618_134109`
- 当前 memory/replay effect 关键 artifact：
  - `/home/qcrs/statebus/runs/contest_honest_headline_goal3_memory_runtime_det_r1_20260618_143231`
- 当前 memory artifact 已成立：
  - `headline_memory_replay_effect_gate.memory_replay_effect_ready = true`
  - `s2_row_count = 10`
  - `expected_replay_row_count = 10`
  - `actual_replay_row_count = 10`
  - `actual_replay_by_mode = {"protocol": 5, "text": 5}`
  - `skipped_step_count = 10`
  - `reuse_gain_positive_count = 10`
  - `expected_reuse_mode_counts = {"none": 30, "skip_execute": 10, ...}`
  - `memory_policy_counts = {"memory_off": 30, "validated_replay": 10, ...}`
- 当前 headline 仍未正式闭合：
  - `formal_stability_gate.passed = false`
  - `repeat_satisfied = false`
  - `required_repeat = 10`
  - `withheld_headline_reason = contest_repeat_insufficient`

你必须把 Goal2 当作冻结事实层，不允许重新把它变成开放式 review。

当前必须优先依照这些文档工作：

1. `docs/review/statebus_goal3_next_round_formal_stability_prompt_20260618.md`
2. `docs/review/statebus_goal3_next_round_memory_replay_effect_prompt_20260618.md`
3. `docs/review/statebus_goal3_next_round_s2_only_prompt_20260618.md`
4. `docs/review/statebus_goal3_review_grounded_mainline_execution_20260618.md`
5. `docs/analysis/statebus_review_requirement_map_20260618.md`
6. `docs/analysis/statebus_review_benchmark_and_task_audit_20260618.md`
7. `docs/analysis/statebus_review_runtime_and_authenticity_20260618.md`
8. `docs/analysis/statebus_review_external_alignment_and_rebuild_20260618.md`
9. `docs/analysis/statebus_review_reading_and_search_log_20260618.md`
10. `docs/reference/题目.md`

当前必须接受 Goal2 / Goal3 已经确认的 stopline：

- 当前 headline 仍是唯一 formal contest headline，不能扩 pack 逃避当前对象
- 不能把 support/historical replay 包当成 current headline proof
- 不能把 deterministic repeat=1 读成 formal stability
- 不能把 prior-dependent action change 直接说成 repeat closure
- 不能把 memory/replay effect 直接说成 repeat=10 证明
- 不能在 formal stability 没闭合前做方法优化
- 不能回头继续修 S1/S2/memory effect 表层

这次严禁：

- 回头再修 S1
- 回头再修 S2 action boundary
- 回头再修 memory/replay effect object
- 继续改 benchmark/task contract，除非它直接阻断 repeat closure 且能被明确证明
- 先做 retrieval / executor / replay 方法优化
- 重新做开放式大 review
- 同时改 benchmark、runtime、memory、retrieval 多条线
- Docker / openEuler VM / nsjail / hidden-state / KV transfer / 交付打包

你必须先读，不允许一上来改代码，也不允许一上来上网搜。

先读：

- `AGENTS.md`
- `README.md`
- `docs/reference/题目.md`
- `docs/review/statebus_goal3_next_round_formal_stability_prompt_20260618.md`
- `docs/review/statebus_goal3_next_round_memory_replay_effect_prompt_20260618.md`
- `docs/review/statebus_goal3_review_grounded_mainline_execution_20260618.md`
- `docs/analysis/statebus_review_requirement_map_20260618.md`
- `docs/analysis/statebus_review_benchmark_and_task_audit_20260618.md`
- `docs/analysis/statebus_review_runtime_and_authenticity_20260618.md`
- `docs/analysis/statebus_review_external_alignment_and_rebuild_20260618.md`
- `docs/analysis/statebus_review_reading_and_search_log_20260618.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`

然后重点读这些代码 / task / eval 锚点：

- `tasks/sample_benchmark.yaml`
- `tasks/sample_tasks.py`
- `tasks/local_corpus.py`
- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `eval/runner.py`
- `tests/test_smoke.py`
- 如果 headline spec 在别处，再读：
  - `tasks/contest_family_spec.py`
  - `tasks/contest_family_spec.yaml`

然后重点读这些 run / evidence：

- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_s1_runtime_det_r1_20260618_123323`
- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_s2_runtime_det_r1_20260618_134109`
- `/home/qcrs/statebus/runs/contest_honest_headline_goal3_memory_runtime_det_r1_20260618_143231`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`

你必须先输出“执行前诊断”，再动代码。诊断必须明确回答：

1. 当前 formal closure 缺的是 run count、API reproducibility，还是某个隐藏对象问题。
2. 为什么这轮只能做 formal stability / repeat closure，不能回头继续做 S1/S2/memory object，也不能做方法优化。
3. 当前要判 formal stability 成立，最小必要证据是什么。
4. 如果 repeat closure 做不通，原因是 benchmark object 问题、API 环境问题、还是方法/实现稳定性问题。
5. 当前哪些工作明确禁止继续投入。

执行最多三轮有效迭代。

Round 0：只读重建

- 只读 docs / code / runs / tests / 历史 artifact
- 输出：
  - formal stability proof target
  - current blocker list
  - run-plan proposal
  - failure classification table
- 不改代码
- 不跑长 benchmark

Round 1：最小回归 + deterministic repeat closure

先只跑：

```bash
python -m pytest -q
python -m runtime.smoke
```

如果通过，再锁定这一轮唯一主变量，并在改代码前开分支：

```bash
git switch -c goal/20260618-goal3-repeat-r1
```

Round 1 只允许做：

- deterministic formal repeat closure
- 与 formal closure 直接耦合的最小 runner / reporting / reproducibility 修正

Round 1 不允许做：

- 回头修改 S1
- 回头修改 S2
- 回头修改 memory/replay effect object
- 方法优化
- 扩成新 headline
- 多主变量并行修改

Round 1 的达标标准必须同时满足：

1. current headline 在 deterministic 目标 repeat 下保持：
   - `object_parity_gate.passed = true`
   - `headline_s1_runtime_behavior_gate.s1_runtime_behavior_ready = true`
   - `headline_s2_prior_action_gate.s2_prior_action_ready = true`
   - `headline_memory_replay_effect_gate.memory_replay_effect_ready = true`
2. `formal_stability_gate` 在 deterministic 层不再只是 repeat=1
3. 所有产物保留为新 `--out` 目录

Round 2：API repeat closure

只有 deterministic closure clean 后，才允许进入 API。

Round 2 顺序固定：

1. API `repeat=1`
2. 如果 clean，再做 API `repeat=3`
3. 如果 repo/规则要求正式 closure 必须到 `repeat=10`，只有前面都 clean 时才允许继续

Round 2 只允许做：

- API formal stability / repeat closure
- 与 API reproducibility / artifact integrity 直接耦合的最小修正

Round 2 不允许做：

- 方法优化
- 对 benchmark/task object 重新设计
- 借 API 波动重新打开 S1/S2/memory object 工程

Round 2 的达标标准必须明确写出：

1. object/gate 仍 clean
2. row-level 解释不崩
3. S1/S2/memory effect gate 不因 repeat 扩大而失效
4. 如果失败，必须分类是：
   - API 环境噪声
   - 稳定性不足
   - 隐藏对象问题

Round 3：formal closure final judgment

Round 3 只能做判定，不默认继续施工：

- 如果 repeat closure 已成立，明确 current headline 是否已达到 formal method-eligible closure
- 如果只差更高 repeat 次数，明确是否值得继续
- 如果 closure 失败，明确失败类型与停止建议

真实 benchmark 纪律：

- 同一轮最多一次新的正式 API 套件
- 所有产物必须新建 `--out`
- 不覆盖旧目录
- 没有新假设，不重复跑 benchmark
- 若已有 artifact 足以回答当前问题，不再无意义重跑

停止条件必须严格执行：

- 同一个核心问题连续 3 轮无实质改进，停止
- 如果 repeat closure 仍做不通，且原因不是简单 run-count 不足，停止并转为稳定性/对象问题结论
- 如果推进需要跨 host-only 边界，停止
- 如果发现 formal closure 失败暴露的是更深的对象问题，再决定是否回到 benchmark reset，但不要在本轮偷改主线

最终必须交付：

1. 这一轮到底解决了什么，没解决什么
2. formal stability / repeat closure 是否已成立
3. current headline 是否已达到 formal closure
4. 当前是否允许结束 benchmark 主线
5. 如果继续，下一轮只允许处理哪一个问题
6. 如果不继续，为什么停止，属于 run-count 问题、API 环境问题，还是稳定性/对象问题
7. 新增 artifact 路径
8. git 分支名与保留理由
```
