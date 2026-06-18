# StateBus Goal 1：沿当前主线继续推进的 Goal Prompt

日期：`2026-06-18`

适用范围：

- 仓库：`/home/qcrs/statebus/project`
- 环境：`/home/qcrs/statebus/conda-envs/statebus_host`
- 当前阶段：`contest_honest_headline_v1` 的 benchmark thickness / 方法评测准入阶段

---

## 1. 这份文档解决什么问题

这份文档专门解决两个混乱点：

1. 当前工作到底推进到哪一层了
2. 新窗口现在应该优先依照哪些文件工作

它不是旧阶段 correctness/object-purity 收口 prompt 的简单重写，而是当前阶段的执行入口。

---

## 2. 当前推进状态

当前状态不要再按 `2026-06-08` 左右那批 host-mainline prompt 去理解。

截至 `2026-06-18`，当前更准确的阶段判断是：

1. `benchmark correctness`：基本通过
2. `object purity`：基本通过
3. `task thickness`：当前未通过
4. `method strength`：当前还不能正式裁决

也就是说：

- 当前主问题已经不再是 hidden fallback、support surface 冒充 headline、row/report 主语义明显冲突这些问题。
- 当前主问题也不再是 recent validate-first / object-parity 兼容性 bug。
- 当前真正的主问题是：`contest_honest_headline_v1` 虽然已经更干净，但还不够厚，不足以正式裁决“当前方法是否真的有优势”。

---

## 3. 当前已经推进到什么程度

### 3.1 已经成立的

- host-side `Planner / Retriever / Executor / Summarizer` 主链路已实现。
- `text / protocol` 双模式、`StateRef`、`SQLite + FAISS memory`、`eval.runner` 已实现。
- 当前唯一 contest-facing headline 是 `contest_honest_headline_v1`。
- `contest_dual_mode_controlled_v3` 已降为内部 controlled surface，不再承担正式 contest headline。
- correctness/object-purity 相关主收口已经基本完成。

### 3.2 最近一轮已经修掉的

最近一轮 benchmark-thickness / validate-first 兼容性问题，已经收口到：

- deterministic `repeat=1` 不再卡 object/gate compatibility
- API `repeat=1` 不再卡 object/gate compatibility
- 当前 withheld 主因只剩 `contest_repeat_insufficient`
- `object_parity_gate.passed == true`
- `unexpected_task_failure_count == 0`

参考 run：

- `runs/contest_honest_headline_thickness_det_r1_fix4/`
- `runs/contest_honest_headline_thickness_api_r1_fix1/`

这意味着：

- 不要回头把“修 validate-first compatibility”当成当前主目标
- 当前应该转入“厚度合同 + 最小实现 + 准入门”阶段

### 3.3 当前还没推进完的

当前还没完成的是：

- thickness 合同是否已经静态落盘
- `S0 / S1 / S2` setting 是否清楚
- `contest_honest_headline_v1` 是否已经厚到足以评方法
- thickened headline 的 `repeat=3` / `repeat=10` 是否值得做、何时才允许做

---

## 4. 当前以哪个文件为准

如果文件之间有冲突，当前阶段按下面优先级理解：

### 4.1 当前阶段主合同

1. `docs/review/statebus_goal1_host_mainline_thickness_execution_20260618.md`
2. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
3. `docs/review/statebus_contest_honest_headline_thickening_plan_20260618.md`
4. `docs/review/statebus_external_benchmark_survey_20260618.md`

### 4.2 当前阶段的背景与判断框架

5. `docs/review/statebus_benchmark_charter_20260617.md`
6. `docs/review/statebus_new_window_guidance_20260617.md`
7. `docs/analysis/statebus_current_thinking_reset_20260617.md`
8. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
9. `docs/progress/contest_requirement_host_audit_20260607.md`

### 4.3 背景文档，只作参考，不作当前阶段主合同

10. `docs/planning/host_goal_mainline_dependency_20260607.md`
11. `docs/planning/host_goal_review_execution_plan_20260607.md`
12. `docs/planning/goal_prompt_host_mainline_despecialize_then_deepen_20260608.md`
13. `goal.md`
14. `docs/planning/implementation_plan.md`

这里最重要的一条是：

> 当前新窗口不应再把 `goal_prompt_host_mainline_despecialize_then_deepen_20260608.md` 或旧 `goal.md` 当作唯一执行入口；当前阶段已经进入 `2026-06-18` 的 thickness 合同链。

---

## 5. 当前阶段不该做什么

当前阶段明确不做：

- 不做 Docker
- 不做 openEuler VM
- 不做 `nsjail`
- 不做 hidden-state / KV 传递
- 不做交付打包
- 不新开 benchmark headline pack 来逃避当前 headline 厚化
- 不把 support/audit surface 升成 headline
- 不在厚度门没过前就大谈“方法本身不行”
- 不为了看起来推进很快而频繁跑真实 API benchmark

---

## 6. 当前阶段唯一正确主线

当前唯一正确主线是：

> 在不回退 correctness/object-purity 收口成果的前提下，把 `contest_honest_headline_v1` 从 `S0 current_honest_floor` 推进到“厚度合同明确、可以开始正式评方法”的状态。

换句话说：

- 当前先修 benchmark 厚度，不先判方法
- 当前先补静态合同和最小验证，不先跑更多旧 benchmark
- 当前先把“什么时候才允许评方法”写清楚，再决定要不要进下一轮

---

## 7. Goal Prompt

把下面整段 prompt 交给新的 goal 窗口使用。

`````text
你现在进入 goal 模式。

工作目录固定为：
`/home/qcrs/statebus/project`

Python 环境固定为：
`/home/qcrs/statebus/conda-envs/statebus_host`

进入后先执行：
```bash
source /home/qcrs/statebus/conda-envs/statebus_host/bin/activate
cd /home/qcrs/statebus/project
source deploy/activate_statebus_host.sh
```

你这次不是重新审 correctness/object purity，也不是继续跑更多旧 benchmark。

你当前唯一主线是：

把 `contest_honest_headline_v1` 从“对象基本合格但任务偏薄”的状态，推进到“厚度合同明确、可以开始正式评方法”的状态。

你必须接受下面这个当前阶段判断：

1. `benchmark correctness`：当前基本通过
2. `object purity`：当前基本通过
3. `task thickness`：当前还没通过
4. `method strength`：当前还不能正式裁决

你还必须接受下面这些当前进展：

- host-side `Planner / Retriever / Executor / Summarizer`、`text/protocol`、`StateRef`、`SQLite + FAISS memory`、`eval.runner` 已实现
- 当前唯一 contest-facing headline 是 `contest_honest_headline_v1`
- `contest_dual_mode_controlled_v3` 已降为内部 controlled surface
- 最近一轮厚化 / validate-first 兼容性问题已经修到：
  - deterministic `repeat=1` 不再卡 object/gate compatibility
  - API `repeat=1` 不再卡 object/gate compatibility
  - 当前 withheld 主因只剩 `contest_repeat_insufficient`
  - `object_parity_gate.passed == true`
  - `unexpected_task_failure_count == 0`
- 这说明你当前不要回头把 gate compatibility 修复当主任务

如果文件之间有冲突，当前一律按下面优先级工作：

1. `docs/review/statebus_goal1_host_mainline_thickness_execution_20260618.md`
2. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
3. `docs/review/statebus_contest_honest_headline_thickening_plan_20260618.md`
4. `docs/review/statebus_external_benchmark_survey_20260618.md`
5. `docs/review/statebus_benchmark_charter_20260617.md`
6. `docs/review/statebus_new_window_guidance_20260617.md`
7. `docs/analysis/statebus_current_thinking_reset_20260617.md`
8. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
9. `docs/progress/contest_requirement_host_audit_20260607.md`

下面这些只作背景，不是当前主合同：

- `docs/planning/host_goal_mainline_dependency_20260607.md`
- `docs/planning/host_goal_review_execution_plan_20260607.md`
- `docs/planning/goal_prompt_host_mainline_despecialize_then_deepen_20260608.md`
- `goal.md`
- `docs/planning/implementation_plan.md`

硬边界：

- 不做 Docker
- 不做 openEuler VM
- 不做 `nsjail` / 强沙箱终态
- 不做 hidden-state / KV 传递
- 不做交付打包
- 不新开 headline pack
- 不把 support surface 冒充 headline
- 不做“为了看起来有进展”的盲目近轮次迭代
- 不允许为了指标把 text baseline 刻意做差
- 不允许频繁跑真实 API benchmark；真实 benchmark 必须 gated 且保留产物

你必须先读本地材料，不能一上来就改代码，也不能一上来就上网搜。

先按这个顺序读：

1. `docs/review/statebus_goal1_host_mainline_thickness_execution_20260618.md`
2. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
3. `docs/review/statebus_contest_honest_headline_thickening_plan_20260618.md`
4. `docs/review/statebus_external_benchmark_survey_20260618.md`
5. `docs/review/statebus_benchmark_charter_20260617.md`
6. `docs/review/statebus_new_window_guidance_20260617.md`
7. `docs/analysis/statebus_current_thinking_reset_20260617.md`
8. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
9. `docs/progress/contest_requirement_host_audit_20260607.md`
10. `README.md`
11. `docs/reference/题目.md`
12. `docs/constraints/current_host_and_migration.md`
13. `docs/constraints/current_feature_scope.md`

然后重点读这些代码 / task / eval 锚点：

- `tasks/sample_benchmark.yaml`
- `tasks/sample_tasks.py`
- `tasks/local_corpus.py`
- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `eval/runner.py`
- `tests/test_smoke.py`

然后重点读这些 run / evidence：

- `runs/comprehensive_eval_20260607_131113/`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
- `runs/contest_honest_headline_thickness_det_r1_fix4/`
- `runs/contest_honest_headline_thickness_api_r1_fix1/`

你必须先输出一份“执行前诊断”，再动代码。诊断里必须回答：

1. 当前主要问题到底是 benchmark 问题、task 设计问题、实现问题，还是方法收益问题
2. 这轮最值得动的一件事是什么，只能选一个主变量
3. 如果继续沿当前方法推进，最可能拿到的下一层结论是什么
4. 如果当前 benchmark/object 仍不合格，应该后退到哪一层重设
5. 当前哪些东西已经不值得再补，应该明确停止

然后才允许进入执行。执行分四个阶段，而且最多三轮有效迭代。

阶段 0：只读重建

- 只读 docs / code / runs / tests / 历史记录
- 输出 requirement map、current status、root-cause list、候选动作列表
- 不改代码
- 不跑长 benchmark

阶段 1：最小验证 + 选主变量

- 只做最小 host 回归

```bash
python -m pytest -q
python -m runtime.smoke
`````

- 如果这里不过，先修主链路，不做结构优化
- 如果这里通过，明确这一轮只改一个主变量
- 此阶段结束前，如果准备改代码，先建立 git 分支备份

git 规则：

- Round 0 结束前保持只读，不切分支
- 一旦确定要改代码，先：

```bash
git switch -c goal/20260618-<short-slug>
```

- 如果第二轮需要明显更大的结构调整，再从当前 HEAD 另开：

```bash
git switch -c goal/20260618-<short-slug>-r2
```

- 不得在脏工作树里回退用户已有改动
- 不得 `reset --hard`
- benchmark 产物一律新建 `--out` 目录，不覆盖旧目录

阶段 2：单变量推进

只允许下面四类主变量四选一，不得混改：

- benchmark/object contract
- task thickness / task set
- retrieval / candidate generation
- executor decision discipline / replay gate

如果你选 retrieval / executor / replay，必须先判断：

- 这是在修 benchmark 假象，还是在修真实方法弱点
- 如果 benchmark 本身不合格，优先修 benchmark，不要提前做机制优化

阶段 3：验证和判定

验证顺序固定：

1. `pytest -q`
2. `python -m runtime.smoke`
3. deterministic `repeat=1` 或 targeted test
4. 只有在前面都通过时，才允许一次真实 API benchmark
5. 真实 API 先 `repeat=1` 或 `repeat=3`，不要直接 `repeat=10`
6. 只有在 object/gate clean、row-level 可解释、`repeat=3` 稳定后，才允许考虑 `repeat=10`

benchmark 纪律：

- deterministic 主要用来验逻辑、稳定性、gate
- serialized API 才是 token/timing 正式证据层
- 同一轮没有新假设，不要重复跑 benchmark
- 同一轮最多一次正式 API benchmark
- 所有 benchmark 必须保留 `--out` 产物并写明本轮假设

外部检索要求：

只有在完成本地问题重建后，才允许上网检索，而且必须只围绕明确问题去搜。优先看论文、官方文档、官方 repo，不要先看二手博客。至少覆盖这些方向：

- benchmark / 任务厚度：
  - HotpotQA
  - MuSiQue
  - BRIGHT
  - LongMemEval
- tool routing / abstain / threshold：
  - semantic-router
  - LangGraph BigTool
- memory / replay / layered retrieval：
  - Mem0
  - MemSearch
  - AgentRx
  - Haystack
- 多 agent 结构化通信 / memory 机制：
  - 只看与 structured communication、intermediate representation、memory reuse directly 相关的一手资料

外部检索产出不能是“参考名单”，必须是 borrow list：

- 当前弱点是什么
- 看了哪个外部对象
- 借哪一个具体机制
- 为什么适合 StateBus 当前 host-mainline
- 为什么不照搬其余部分

停止条件必须严格执行：

- 同一个核心问题连续 3 轮仍无实质改进，停止
- 如果 benchmark 仍不满足 single-variable / object-pure / task-thick，停止继续调方法，转为 benchmark reset 结论
- 如果需要跨越当前 host-only 边界才能继续，停止
- 如果发现当前主线与赛题主问题明显偏离，停止小修小补，转为“建议重构/重设主线”结论

你最后必须交付的不是“做了很多事”，而是这几项：

1. 当前这轮到底解决了什么，没解决什么
2. 这一轮的主变量和结果
3. 是否应该进入下一轮
4. 如果进入下一轮，下一轮只允许处理哪一个问题
5. 如果不进入下一轮，为什么应停止，是否建议重构
6. 新增 benchmark/run artifact 的路径
7. git 分支名和保留理由
```
