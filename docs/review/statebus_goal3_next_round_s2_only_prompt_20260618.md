# StateBus Goal 3 下一轮 Prompt：S2 Only

日期：`2026-06-18`

适用范围：

- 仓库：`/home/qcrs/statebus/project`
- 环境：`/home/qcrs/statebus/conda-envs/statebus_host`
- 当前阶段：`Goal3/S1 completed, S2 not yet proven`

用途：

- 给新窗口 / 新 goal 会话直接使用
- 以前一轮 `S1` 已经完成为前提
- 明确约束下一轮只能做 `S2 prior-dependent admissible-action change`

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

你当前执行的是 Goal3 的下一轮，但这次不是继续泛化 Goal3，也不是重新做 Goal2。

你这次只有一个允许推进的目标：

> 证明 `contest_honest_headline_v1` 的 `S2` 已经从“静态 prior 字段”推进到“真实 prior-dependent admissible-action change”。

你必须先接受下面这个当前状态：

1. Goal2 已完成，当前是冻结的事实层、问题地图、外部校准和 stopline。
2. Goal3/S1 已完成。
3. 当前 `contest_honest_headline_v1` 已不再只是 admission-floor，它已经有真实 S1 runtime behavior。
4. 但当前 headline 仍然还不是完整 `method-eligible`，因为：
   - `S2 prior-dependent admissible-action change` 还没证明；
   - current headline 里的 memory/replay 还没形成正式 effect proof；
   - repeat=10 / formal API timing 还没补齐。

你必须接受下面这些 S1 已成立事实：

- 当前分支收口点来自：`goal/20260618-goal3-r1`
- 当前关键 artifact：
  - `/home/qcrs/statebus/runs/contest_honest_headline_goal3_s1_runtime_det_r1_20260618_123323`
- 当前 artifact 已成立：
  - `headline_s1_runtime_behavior_gate.applicable = true`
  - `headline_s1_runtime_behavior_gate.s1_runtime_behavior_ready = true`
  - `changed_action_count = 12`
  - `changed_action_by_mode = {"protocol": 6, "text": 6}`
  - `validate_success_count = 30`
  - `validation_consumed_count = 30`
- `tests/test_smoke.py` 已补上负控证明：
  - 去掉 validate 时动作会走偏
  - 加上 validate 后动作会收窄到 validated action
- 最新测试状态：
  - `python -m pytest -q` 通过，`209 passed`
  - `source deploy/activate_statebus_host.sh && python -m runtime.smoke` 通过

你必须把 Goal2 当作冻结事实层，不允许重新把它变成开放式 review。

当前必须优先依照这些文档工作：

1. `docs/review/statebus_goal3_next_round_s2_only_prompt_20260618.md`
2. `docs/review/statebus_goal3_review_grounded_mainline_execution_20260618.md`
3. `docs/review/statebus_goal1_next_round_real_thickening_prompt_20260618.md`
4. `docs/analysis/statebus_review_requirement_map_20260618.md`
5. `docs/analysis/statebus_review_benchmark_and_task_audit_20260618.md`
6. `docs/analysis/statebus_review_runtime_and_authenticity_20260618.md`
7. `docs/analysis/statebus_review_external_alignment_and_rebuild_20260618.md`
8. `docs/analysis/statebus_review_reading_and_search_log_20260618.md`
9. `docs/reference/题目.md`

当前必须接受 Goal2/Goal3 已经确认的 stopline：

- 当前 headline 仍是 formal contest headline，不能扩 pack 逃避当前对象
- 当前 memory/replay 主要还在 support/historical evidence，不能冒充 current headline proof
- 不能把 repeat=1 读成 repeat=10 formal stability
- 不能把多 agent role/framework 本身当主创新结论
- 不能在 benchmark 还没完整 method-eligible 前做方法优化
- 不能回头继续修 report surface 或只补静态字段

这次严禁：

- 回头再修 S1 表层
- 继续补 S1 static metadata
- 继续刷 repeat=10
- 先做 retrieval / executor / replay 方法优化
- 重新做开放式大 review
- 同时改 benchmark、runtime、memory、retrieval 多条线
- 把 support/historical replay 包当成 current headline S2 证据
- Docker / openEuler VM / nsjail / hidden-state / KV transfer / 交付打包

你必须先读，不允许一上来改代码，也不允许一上来上网搜。

先读：

- `AGENTS.md`
- `README.md`
- `docs/reference/题目.md`
- `docs/review/statebus_goal3_next_round_s2_only_prompt_20260618.md`
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
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
- `runs/comprehensive_eval_20260607_131113/`
- `runs/contest_honest_headline_thickness_api_r1_fix1/`

你必须先输出“执行前诊断”，再动代码。诊断必须明确回答：

1. 当前 `S2` 缺的到底是 benchmark/task contract 问题，还是 runtime/action-boundary 问题。
2. 这一轮为什么只能做 `S2`，不能回头继续做 `S1`，也不能提前做方法优化。
3. 当前 `S2` 要被判成立，最小必要证据是什么。
4. 如果当前对象结构不支持真实 `S2`，应该后退到 benchmark/task contract reset，还是允许有限重构。
5. 当前哪些工作明确禁止继续投入。

执行最多三轮有效迭代。

Round 0：只读重建

- 只读 docs / code / runs / tests
- 输出：
  - S2 proof target
  - current blocker list
  - row-level evidence gap
  - candidate action list
- 不改代码
- 不跑长 benchmark

Round 1：只做 S2 proof object

先只跑最小验证：

```bash
python -m pytest -q
python -m runtime.smoke
```

如果通过，再锁定这一轮唯一主变量，并在改代码前开分支：

```bash
git switch -c goal/20260618-goal3-s2-r1
```

Round 1 只允许做：

- `S2 prior-dependent admissible-action change`
- 与这个目标直接耦合的最小 task contract / row-level output / validation proof 调整

Round 1 不允许做：

- 回头修改 S1
- 方法优化
- repeat=10
- 扩成 memory headline
- 多主变量并行修改

Round 1 的达标标准必须同时满足：

1. 至少一类 `S2` row 中：
   - 没有 prior rejection / prior route / prior scoped action 时，当前动作边界不同
   - 有 prior 条件时，validate 或 executor 可执行动作被真实收窄或改变
2. 这种改变必须是 row-level 可见的，不是只在文案里解释
3. 不能只是字段存在，必须是运行时行为差异
4. 如果 claim reuse/memory，则必须出现非零 runtime reuse evidence；否则就只 claim `prior-dependent admissible-action change`，不要超说

Round 2：只有 S2 已真实成立后才允许进入

Round 2 只允许做：

- `deterministic repeat=1` 或 targeted benchmark 验证
- 必要时一次 `API repeat=1` 验证

顺序固定：

1. `python -m pytest -q`
2. `python -m runtime.smoke`
3. deterministic `repeat=1` / targeted test
4. 只有前面都 clean，才允许一次 API `repeat=1`

Round 2 仍然不允许：

- `repeat=10`
- 方法优化
- 把 memory lane 正式并入 headline，除非这一轮真有非零 reuse evidence

Round 3：只有 S2 clean 后才允许讨论下一步

Round 3 只能做判定，不默认继续施工：

- 如果 S2 已成立，判断 headline 是否已接近 `method-eligible`
- 如果仍缺 memory lane 或 repeat closure，明确下一轮只允许处理哪一个
- 如果 S2 做不出来，停止继续补方法，转为 benchmark/task contract reset 或有限重构结论

真实 benchmark 纪律：

- 同一轮最多一次正式 API benchmark
- 所有产物必须新建 `--out`
- 不覆盖旧目录
- 没有新假设，不重复跑 benchmark

停止条件必须严格执行：

- 同一个核心问题连续 3 轮无实质改进，停止
- 如果 `S2` 仍证明不出来，且原因在 benchmark/object 结构，停止调方法，转为 benchmark reset 结论
- 如果推进需要跨 host-only 边界，停止
- 如果发现当前主线明显偏离赛题主问题，停止小修小补，转为建议有限重构

最终必须交付：

1. 这一轮到底解决了什么，没解决什么
2. `S2` 是否已从静态字段推进到真实行为层
3. 当前 headline 是否已更接近 `method-eligible`
4. 当前是否允许进入下一轮
5. 如果继续，下一轮只允许处理哪一个问题
6. 如果不继续，为什么停止，是否建议 benchmark reset 或有限重构
7. 新增 artifact 路径
8. git 分支名与保留理由
```
