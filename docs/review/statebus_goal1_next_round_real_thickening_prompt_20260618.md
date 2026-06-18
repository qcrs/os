# StateBus Goal 1 下一轮 Prompt：真实 Task-Behavior Thickening

日期：`2026-06-18`

适用范围：

- 仓库：`/home/qcrs/statebus/project`
- 环境：`/home/qcrs/statebus/conda-envs/statebus_host`
- 当前对象：`contest_honest_headline_v1`
- 当前阶段：`admission-floor completed, formal method proof not yet established`

用途：

- 给新窗口 / 新 goal 会话直接使用
- 以前一轮 thickness admission 已完成为前提
- 明确约束下一轮只能做真实 task-behavior thickening，不能继续修 report surface

---

```text
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

你的总目标不是继续修 report，也不是继续刷旧 benchmark 的 repeat 次数。

你当前唯一允许推进的主线是：

在 `contest_honest_headline_v1` 已经完成 admission-floor 的前提下，继续沿 host-mainline 方法推进，但这次必须把主变量切换为“真实 task-behavior thickening”：

1. 让 `S1` 从“静态厚度字段存在”推进到“真实 connected multihop 行为存在”
2. 让 `S2` 从“静态 prior dependency 字段存在”推进到“prior-dependent admissible-action change 真实存在”
3. 如果当前 headline 不足以支持这两点，允许后退一步重设 benchmark/task contract
4. 如果发现当前实现主线偏离赛题主问题，允许有限重构，但不能借此扩 scope

你必须接受下面这些当前上下文，不要重复把已经收掉的问题当主目标：

- host-side `Planner / Retriever / Executor / Summarizer`、`text/protocol`、`StateRef`、`SQLite + FAISS memory`、`eval.runner` 已实现
- 当前唯一 contest-facing headline 是 `contest_honest_headline_v1`
- correctness / object-purity 主收口已经基本完成
- 最新 deterministic artifact 在：
  - `/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix6_20260618_113224`
- 该 artifact 已成立的结论是：
  - `headline_thickness_admission_gate.applicable = true`
  - `static_contract_complete = true`
  - `runtime_shape_ready = true`
  - `admission_ready = true`
  - `withheld_headline_reason = contest_repeat_insufficient`
  - `object_parity_gate.passed = true`
  - `contest_formal_coverage_gate.surface_complete = true`
  - `matched_pair_count = 20`
  - `family_coverage = 5`
- 当前厚度字段已显式出现在 task rows：
  - `case_id`
  - `case_type`
  - `thickness_setting`
  - `reasoning_hops_min`
  - `dependency_depth`
  - `expected_intermediate_decisions`
  - `abstention_boundary`
  - `required_prior_case_ids`
  - `required_prior_rejections`
  - `required_prior_routes`
  - `required_plan_semantic_roles`
- 上述结论只说明：
  - “厚度准入合同已经显式落盘且 artifact 可见”
  - 还不说明“真实 runtime S1/S2 厚度已经成立”

你必须先接受下面这个当前阶段判断：

1. `benchmark correctness`：当前基本通过
2. `object purity`：当前基本通过
3. `task thickness contract`：当前 admission-floor 已通过
4. `real task-behavior thickness`：当前仍未证明
5. `method strength`：当前仍不能正式裁决

这次不允许再把主任务偷换成：

- 再修 report surface
- 再补厚度字段但不改变真实行为
- 再刷 `repeat=1/3/10` 试图替代对象厚化
- 再回头修最近已经收掉的 gate compatibility
- 再拿 deterministic 当正式 token/timing 证据

硬边界：

- 不做 Docker
- 不做 openEuler VM
- 不做 `nsjail` / 强沙箱终态
- 不做 hidden-state / KV 传递
- 不做交付打包
- 不新开 headline pack 来逃避当前 headline 厚化
- 不把 support surface 冒充 headline
- 不把 LangGraph 或其他框架整套替换成新主线
- 不允许为了指标把 text baseline 刻意做差
- 不允许频繁跑真实 API benchmark；真实 benchmark 必须 gated 且保留产物

如果文件之间有冲突，当前一律按下面优先级理解：

1. `docs/review/statebus_goal1_next_round_real_thickening_prompt_20260618.md`
2. `docs/review/statebus_goal1_host_mainline_thickness_execution_20260618.md`
3. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
4. `docs/review/statebus_contest_honest_headline_thickening_plan_20260618.md`
5. `docs/review/statebus_external_benchmark_survey_20260618.md`
6. `docs/review/statebus_benchmark_charter_20260617.md`
7. `docs/review/statebus_new_window_guidance_20260617.md`
8. `docs/analysis/statebus_current_thinking_reset_20260617.md`
9. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
10. `docs/progress/contest_requirement_host_audit_20260607.md`

你必须先读本地材料，不能一上来改代码，也不能一上来上网搜。

先按这个顺序读：

1. `AGENTS.md`
2. `README.md`
3. `docs/reference/题目.md`
4. `docs/review/statebus_goal1_next_round_real_thickening_prompt_20260618.md`
5. `docs/review/statebus_goal1_host_mainline_thickness_execution_20260618.md`
6. `docs/review/statebus_benchmark_thickness_execution_contract_20260618.md`
7. `docs/review/statebus_contest_honest_headline_thickening_plan_20260618.md`
8. `docs/review/statebus_external_benchmark_survey_20260618.md`
9. `docs/review/statebus_benchmark_charter_20260617.md`
10. `docs/review/statebus_new_window_guidance_20260617.md`
11. `docs/analysis/statebus_current_thinking_reset_20260617.md`
12. `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
13. `docs/progress/contest_requirement_host_audit_20260607.md`
14. `docs/constraints/current_host_and_migration.md`
15. `docs/constraints/current_feature_scope.md`

然后重点读这些代码 / task / eval 锚点：

- `tasks/sample_benchmark.yaml`
- `tasks/sample_tasks.py`
- `tasks/local_corpus.py`
- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`
- `eval/runner.py`
- `tests/test_smoke.py`
- 如果当前 headline 相关 spec 在别处，再继续读：
  - `tasks/contest_family_spec.py`
  - `tasks/contest_family_spec.yaml`

然后重点读这些 run / evidence：

- `runs/comprehensive_eval_20260607_131113/`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
- `runs/contest_honest_headline_thickness_det_r1_fix4/`
- `runs/contest_honest_headline_thickness_api_r1_fix1/`
- `/home/qcrs/statebus/runs/contest_honest_headline_thickness_det_r1_fix6_20260618_113224`

你必须先输出一份“执行前诊断”，再动代码。诊断里必须明确回答：

1. 当前还未成立的，究竟是 benchmark/object 问题，还是 runtime/task-behavior 问题
2. 这轮唯一最值得动的主变量是什么，只能选一个
3. 如果继续沿当前方法推进，下一层最可能拿到的结论是什么
4. 如果当前 headline 仍不支持真实 S1/S2 行为证明，应该后退到哪一层重设
5. 当前哪些工作明确不值得继续补，应该立即停止

然后才允许进入执行。执行分四个阶段，而且最多三轮有效迭代。

阶段 0：只读重建

- 只读 docs / code / runs / tests / 历史记录
- 输出：
  - requirement map
  - current status
  - artifact-confirmed truths
  - unresolved proof gaps
  - root-cause list
  - candidate actions
- 不改代码
- 不跑长 benchmark

阶段 1：最小验证 + 选主变量

- 只做最小 host 回归：

```bash
python -m pytest -q
python -m runtime.smoke
```

- 如果这里不过，先判断失败是否阻断当前真实 task-thickening 主线
- 如果是不相关旧 failure，允许记录为背景证据，但不要借机跑偏
- 如果通过，明确这一轮只改一个主变量
- 此阶段结束前，如果准备改代码，先建立 git 分支备份

git 规则：

- Round 0 结束前保持只读，不切分支
- 一旦确定要改代码，先：

```bash
git switch -c goal/20260618-real-thickening-r1
```

- 如果第二轮需要更明显的结构调整，再从当前 HEAD 另开：

```bash
git switch -c goal/20260618-real-thickening-r2
```

- 不得在脏工作树里回退用户已有改动
- 不得 `reset --hard`
- benchmark 产物一律新建 `--out` 目录，不覆盖旧目录

阶段 2：单变量推进

这次四选一，但必须优先顺序严格如下：

1. `S1 connected multihop behavior`
2. `S2 prior-dependent admissible-action change`
3. `benchmark/task contract reset`
4. `executor decision discipline / replay gate`

选择规则：

- 默认优先做 `S1`
- 只有当你证明 `S1` 已足够或被当前对象结构阻断时，才允许改 `S2`
- 如果 benchmark/task contract 本身阻断真实行为证明，优先后退重设 benchmark/task contract，不要提前做机制优化
- `executor/replay` 只能在你确认它对应真实方法弱点而不是 benchmark 假象时才允许选

如果你选 `S1`，必须满足：

- 至少一类 headline case 形成真实 connected multihop
- 去掉其中一跳后，route/tool/action 不成立
- 不只是多写字段，不只是增加 filler step

如果你选 `S2`，必须满足：

- prior rejection / prior route / prior scoped action 的缺失，真实改变后题 admissible action
- 不能只是“前题信息存在但后题其实照样能做”

如果你判断当前 headline 无法诚实承载上述变化，允许有限重构，但只能落在：

- `tasks/contest_family_spec.py`
- `tasks/contest_family_spec.yaml`
- 与其直接耦合的 task loader / static tests / minimal executor contract

不允许借此把 repo 变成新的大重构工程。

阶段 3：验证和判定

验证顺序固定：

1. `python -m pytest -q`
2. `python -m runtime.smoke`
3. deterministic `repeat=1` 或 targeted test
4. 只有前面都通过，才允许一次真实 API benchmark
5. 真实 API 先 `repeat=1` 或 `repeat=3`，不要直接 `repeat=10`
6. 只有在 row-level 可解释、object/gate clean、真实 S1/S2 行为确实出现后，才允许考虑 `repeat=10`

benchmark 纪律：

- deterministic 主要用来验逻辑、稳定性、gate、task-behavior 是否真实出现
- serialized API 才是 token/timing 正式证据层
- 同一轮没有新假设，不要重复跑 benchmark
- 同一轮最多一次正式 API benchmark
- 所有 benchmark 必须保留 `--out` 产物并写明本轮假设

外部检索要求：

只有在完成本地问题重建后，才允许上网检索，而且必须只围绕明确问题去搜。优先看论文、官方文档、官方 repo，不要先看二手博客。

至少覆盖这些方向：

- benchmark / 厚任务设计：
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

- structured communication / intermediate representation / memory reuse：
  - 只看与结构化通信、中间表示、memory reuse 直接相关的一手资料

外部检索产出不能只是“参考名单”，必须是 `borrow list`：

- 当前弱点是什么
- 看了哪个外部对象
- 借哪一个具体机制
- 为什么适合 StateBus 当前 host-mainline
- 为什么不照搬其余部分

停止条件必须严格执行：

- 同一个核心问题连续 3 轮仍无实质改进，停止
- 如果真实 S1/S2 行为仍证明不出来，且原因在 benchmark/object 不合格，停止继续调方法，转为 benchmark reset 结论
- 如果需要跨越当前 host-only 边界才能继续，停止
- 如果发现当前主线与赛题主问题明显偏离，停止小修小补，转为“建议重构/重设主线”结论

你最后必须交付的不是“做了很多事”，而是以下这些：

1. 当前这轮到底解决了什么，没解决什么
2. 这一轮的主变量和结果
3. 当前是否已从 admission-floor 推进到真实行为层
4. 是否应该进入下一轮
5. 如果进入下一轮，下一轮只允许处理哪一个问题
6. 如果不进入下一轮，为什么应停止，是否建议重构
7. 新增 benchmark/run artifact 的路径
8. git 分支名和保留理由
9. 外部检索形成的 `borrow list`
10. 如果仍未证明方法，应明确说明卡在 benchmark、task、runtime、还是方法本身
```
