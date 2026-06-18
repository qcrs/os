# StateBus Goal 与新窗口执行 Prompt

日期：`2026-06-17`

状态说明：

- 这份文档对应 `2026-06-17` 的 correctness/object-purity 收口阶段。
- 如果当前任务已经进入“benchmark 厚度合同 + 方法评测准入门”阶段，优先使用：
  - `docs/review/statebus_new_window_benchmark_thickness_prompt_20260618.md`
  - `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`

适用范围：

- 仓库：`/home/qcrs/statebus/project`
- 环境：`/home/qcrs/statebus/conda-envs/statebus_host`
- 激活：`source deploy/activate_statebus_host.sh`

本文件的用途：

- 给 `goal` 命令直接复用
- 给新窗口 / 新协作者直接复用
- 保证后续执行始终基于赛题与当前主线，不重新发散

---

## 1. 当前唯一主线

当前只做一件事：

> 基于 `docs/review/statebus_benchmark_design_and_testing_20260617.md`，把 StateBus benchmark 主线收口成可信、单变量、可复现、可解释的赛题 benchmark。

这条主线的当前事实是：

- `contest_honest_headline_v1` 是唯一 contest-facing headline
- `contest_dual_mode_controlled_v3` 只保留为内部 controlled surface
- `planner_support_v3` 只回答 `plan_source=yaml vs llm`
- `memory_dual_mode_fairness_v3` 只回答 dual-mode fairness/object parity，不承担 replay headline
- 所有 report 语义都必须回到 row-level

---

## 2. 硬约束

必须遵守：

- 只在本地 host + conda 环境工作
- 只以本仓库代码、测试、文档、benchmark 结果为准
- 赛题要求高于现有方法叙事
- 先 benchmark contract，再 report，再测试，再决定是否进入下一轮

明确不做：

- 不做 Docker / openEuler / nsjail
- 不做系统外部署
- 不新开 benchmark pack
- 不把 audit / support surface 升格成 headline
- 不在 benchmark 没立住前做大规模 runtime 重构
- 不先跑重型 API 套件来代替本地语义收口

---

## 3. 每轮执行顺序

每一轮都按下面顺序执行：

1. 先读主合同文档  
   - `docs/review/statebus_benchmark_design_and_testing_20260617.md`
   - `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`
   - `README.md`
   - `docs/reference/题目.md`

2. 先做执行前备份  
   - 保存当前 `git status --short`
   - 保存当前 `git diff`
   - 记录本轮目标、命令、结果目录

3. 只改当前轮明确允许的对象  
   - benchmark contract
   - report semantics
   - tests / gates

4. 先跑本地门禁  
   - `python -m pytest -q`
   - `python -m runtime.smoke`

5. 再跑针对性 benchmark 回归  
   - headline
   - planner
   - fairness

6. 记录结果，决定是否进入下一轮

---

## 4. 备份规则

每轮开始前创建一个运行目录，建议格式：

```bash
RUN_DIR=/home/qcrs/statebus/runs/goal_$(date +%Y%m%d_%H%M%S)_benchmark_round
mkdir -p "$RUN_DIR"
git status --short > "$RUN_DIR/git_status.txt"
git diff > "$RUN_DIR/git_diff.patch"
```

每轮至少保存：

- `git_status.txt`
- `git_diff.patch`
- `COMMANDS.md`
- `SUMMARY.md`
- 本轮测试日志
- 本轮 benchmark 输出目录路径

如果这一轮改了 benchmark 语义或测试：

- 必须把最小回归命令写进 `COMMANDS.md`
- 必须把通过 / 失败原因写进 `SUMMARY.md`

---

## 5. 当前轮允许做的事

优先级固定如下：

1. `contest_honest_headline_v1` 合同与 headline 读法
2. `planner_support_v3` 的 row-level / report 一致性
3. `memory_dual_mode_fairness_v3` 的 `not_evaluated` 语义与汇总
4. `formal_structure_clean_retrieval`、pairing、reusable dependency 这类静态 contract 检查
5. 本地测试与定向回归

当前轮不做：

- 不扩 task 厚度
- 不加新 family
- 不重写 orchestrator 主链路
- 不扩大 open surfaces

---

## 6. 什么时候进入下一轮

只有同时满足下面条件，才允许进入下一轮：

1. 本地门禁通过  
   - `python -m pytest -q`
   - `python -m runtime.smoke`

2. benchmark 语义门禁通过  
   - `contest_honest_headline_v1` 仍是唯一 headline
   - `planner_support_v3` 的 `planner_one_shot_valid_rate` 与 row-level 一致
   - `memory_dual_mode_fairness_v3` 的空 contract 显示为 `not_evaluated`

3. 定向回归通过  
   - headline 相关测试通过
   - planner report 相关测试通过
   - fairness 语义相关测试通过

4. 结果已备份  
   - 当前轮日志和 diff 已落盘

如果以上四项没有同时满足：

- 不进入下一轮
- 不谈“继续优化方法”
- 只继续收口当前轮 benchmark 语义

---

## 7. 下一轮之后才允许做什么

只有当前轮 benchmark 语义和本地门禁全部通过后，才允许考虑：

- `contest_honest_headline_v1` 的 `repeat=1` benchmark rerun
- 再之后的 `repeat=10` formal headline 验证
- 任务厚化
- correctness / latency 的下一轮优化

也就是说：

> 先把 benchmark 做成可信对象，再做方法优化；不能反过来。

---

## 8. Goal Prompt

下面这段可以直接给 `goal` 命令使用：

```text
你现在在 `/home/qcrs/statebus/project` 工作。

你必须只在本地 host 环境下执行：
- conda: `/home/qcrs/statebus/conda-envs/statebus_host`
- activate: `source deploy/activate_statebus_host.sh`

你的唯一目标是：

基于 `docs/review/statebus_benchmark_design_and_testing_20260617.md`，把 StateBus 当前 benchmark 主线继续落地执行，只收口 benchmark contract、report semantics、tests/gates，不扩 runtime 主链路，不扩 benchmark pack，不扩部署范围。

你必须遵守：

1. 赛题要求高于现有方法叙事。
2. `contest_honest_headline_v1` 是唯一 contest-facing headline。
3. `contest_dual_mode_controlled_v3` 只保留为内部 controlled surface。
4. `planner_support_v3` 只回答 planner support，不读成 text-vs-protocol。
5. `memory_dual_mode_fairness_v3` 只回答 fairness/object parity，不承担 replay headline。
6. 所有 report 语义必须能回到 row-level。
7. 不做 Docker/openEuler/nsjail，不做系统外部署。
8. 不新增 benchmark pack，不把 audit/support surface 升格成 headline。
9. 每轮开始前必须先备份 `git status --short`、`git diff`、命令和结果摘要。

本轮执行顺序固定为：

1. 先读：
   - `docs/review/statebus_benchmark_design_and_testing_20260617.md`
   - `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`
   - `README.md`
   - `docs/reference/题目.md`
2. 先备份当前状态到新的 `runs/goal_*` 目录。
3. 只修改 benchmark contract / report semantics / tests。
4. 先跑本地门禁：
   - `python -m pytest -q`
   - `python -m runtime.smoke`
5. 再跑定向 benchmark 回归。
6. 只有当本地门禁、语义门禁、定向回归、结果备份四项同时通过，才允许进入下一轮。

当前轮的重点检查项：

- `contest_honest_headline_v1` 的 headline contract 是否仍然唯一且单变量
- `planner_support_v3` 的 `planner_one_shot_valid_rate` 是否严格按 row-level 聚合
- `memory_dual_mode_fairness_v3` 的空 contract 是否统一显示为 `not_evaluated`
- report / benchmark_results / tests 三者是否同义

如果发现问题，优先修 benchmark 语义，不要先做更大范围优化。
如果本轮门禁没过，不要进入下一轮。
```

---

## 9. 新窗口 Prompt

下面这段给新窗口 / 新协作者：

```text
你现在在 `/home/qcrs/statebus/project` 工作。

只允许使用本地 host 环境：
- conda: `/home/qcrs/statebus/conda-envs/statebus_host`
- activate: `source deploy/activate_statebus_host.sh`

当前任务不是自由分析，也不是大规模重构。
当前任务是沿着既有主线，继续把 benchmark 收口到可信、单变量、可复现、可解释。

前因后果你必须先知道：

1. 这个项目之前混杂了太多 benchmark surface、support surface、audit surface 和历史文档。
2. 当前第一优先级已经明确不是扩 runtime，也不是扩 benchmark pack。
3. 当前第一优先级是先把 benchmark 主线收口：
   - `contest_honest_headline_v1` 是唯一 contest-facing headline
   - `contest_dual_mode_controlled_v3` 只保留为内部 controlled surface
   - `planner_support_v3` 和 `memory_dual_mode_fairness_v3` 只能按 row-level 语义读
4. 当前主线判断来自赛题，而不是方法偏好。

你必须严格先读：

1. `docs/review/statebus_benchmark_design_and_testing_20260617.md`
2. `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`
3. `README.md`
4. `docs/reference/题目.md`
5. `docs/constraints/current_host_and_migration.md`
6. `docs/constraints/current_feature_scope.md`

你必须只围绕下面这个主问题工作：

“在一个可信、单变量、足够厚的赛题 benchmark 上，structured protocol 是否比 pure-text handoff 更有优势？”

当前阶段允许你做的事只有：

- benchmark contract 收口
- report semantics 收口
- tests / gates 收口
- 本地门禁与定向回归

当前阶段不允许你做：

- Docker / openEuler / nsjail
- 外部部署
- 新 benchmark pack
- 把 support/audit surface 升格成 headline
- 在 benchmark 没立住前做大规模 runtime 重构

执行规则：

1. 每轮先备份 `git status --short`、`git diff`、命令、结果摘要到 `runs/goal_*`
2. 修改只限 benchmark contract / report semantics / tests
3. 本地门禁固定为：
   - `python -m pytest -q`
   - `python -m runtime.smoke`
4. 通过后再做定向 benchmark 回归
5. 没过门禁时，不进入下一轮

你最终要输出的不是泛泛建议，而是：

- 当前轮做了什么
- 哪些 benchmark 语义已经闭环
- 哪些门禁已经通过
- 是否允许进入下一轮
- 如果允许，下一轮只做什么
```

---

## 10. 建议的当前轮命令

```bash
source deploy/activate_statebus_host.sh

RUN_DIR=/home/qcrs/statebus/runs/goal_$(date +%Y%m%d_%H%M%S)_benchmark_round
mkdir -p "$RUN_DIR"
git status --short > "$RUN_DIR/git_status.txt"
git diff > "$RUN_DIR/git_diff.patch"

python -m pytest -q
python -m runtime.smoke
```

如果只跑当前主线的最小定向回归：

```bash
source deploy/activate_statebus_host.sh
python -m pytest -q tests/test_smoke.py -k "contest_honest_headline_v1 or planner_support_v3 or memory_dual_mode_fairness_v3"
```

如果要按当前 benchmark 主线做分层回归，建议顺序如下：

```bash
source deploy/activate_statebus_host.sh

# 1) headline 语义与 report
python -m eval.runner --task-set contest_honest_headline_v1 --repeat 1 --llm-mode deterministic --out /tmp/statebus_headline_det_r1 --quiet-progress

# 2) planner support 单变量与 row-level report
python -m eval.runner --task-set planner_support_v3 --repeat 1 --llm-mode deterministic --out /tmp/statebus_planner_det_r1 --quiet-progress

# 3) fairness / object parity 语义
python -m eval.runner --task-set memory_dual_mode_fairness_v3 --repeat 1 --llm-mode deterministic --out /tmp/statebus_fairness_det_r1 --quiet-progress
```

如果你要跑当前主线的 API 小回归，只建议先跑 headline 和 planner：

```bash
source deploy/activate_statebus_host.sh
python -m eval.runner --task-set contest_honest_headline_v1 --repeat 1 --llm-mode api --out /tmp/statebus_headline_api_r1 --quiet-progress
python -m eval.runner --task-set planner_support_v3 --repeat 1 --llm-mode api --out /tmp/statebus_planner_api_r1 --quiet-progress
```

如果本地门禁全部通过，再考虑进入：

```bash
python -m eval.runner --task-set contest_honest_headline_v1 --repeat 1 --llm-mode deterministic --out /tmp/statebus_headline_det_r1 --quiet-progress
```

`repeat=10` 只在本地门禁、定向回归、结果备份都完成后才进入。

如果确实需要跑当前已有的 repeat=3 主线脚本，它只是较大范围回归入口：

```bash
source deploy/activate_statebus_host.sh
bash scripts/run_statebus_mainline_repeat3_suite.sh
```

但当前 benchmark 收口阶段的默认建议仍然是：

- 先本地门禁
- 再三条最小定向回归
- 最后才决定是否进入 repeat=3 / repeat=10
