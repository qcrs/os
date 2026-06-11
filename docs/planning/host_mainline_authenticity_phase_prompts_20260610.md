# StateBus 宿主机主线 Phase Prompt 集合

日期：`2026-06-10`

适用范围：给后续 Codex 窗口直接复制使用，用于按组推进

- 第一次：`Phase 0 -> Phase 1 -> Phase 2`
- 第二次：`Phase 3 -> Phase 4 -> Phase 5`
- 第三次：`Phase 6 -> Phase 7`

总控文档始终是：

- `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`

这份文件只是 prompt 集合，不替代总控计划。

---

## 1. 使用规则

1. 每次只复制一个 prompt。
2. 三次执行必须按顺序来，不能跳组。
3. 每次执行内部也必须按 phase 顺序推进，不能跳 phase。
4. 每完成一组后，都要求对方输出一段固定格式的“本轮完成追加说明”。
5. 如果某个 phase 的退出条件不满足，对方必须停下并报告，不能偷偷进入下一 phase。

---

## 2. Prompt A：第一次完成 `Phase 0 -> Phase 1 -> Phase 2`

```text
你现在工作在 `/home/qcrs/statebus/project`。

这次只做第一组连续 phase：
- `Phase 0`
- `Phase 1`
- `Phase 2`

总控文档：
- `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`

你的任务不是自由发挥，也不是整条路线全做完。
你的任务是严格按总控文档，顺序完成 `Phase 0 -> Phase 1 -> Phase 2`，并在每个 phase 结束时判断是否满足退出条件。

硬边界：
1. 只能在 host-side 主线内工作。
2. 不做 VM / Docker / openEuler / nsjail / 强沙箱 / hidden-state / KV / CodeAct 主路径。
3. 不允许跳 phase。
4. 如果 `Phase 0` 的退出条件未满足，不能进入 `Phase 1`。
5. 如果 `Phase 1` 的退出条件未满足，不能进入 `Phase 2`。
6. 不要把 `assist_only` 重新包装成 headline。
7. 当前目标是“让系统更诚实”，不是“让系统更开放”。

你必须先读：
- `AGENTS.md`
- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`

然后严格按总控文档要求：
1. 先读 `Phase 0` 的本地必读文件、第三方本地文件和 upstream repo。
2. 完成 `Phase 0` 范围内的工作。
3. 检查 `Phase 0` 退出条件是否满足。
4. 只有在满足时，才能进入 `Phase 1`。
5. 进入 `Phase 1` 前，必须重新汇报当前 phase、已读材料、明确不做项和计划验证。
6. 然后按同样方式推进 `Phase 1 -> Phase 2`。

每进入一个新 phase 前，都必须先输出这一段：

当前 phase：
本 phase 单一目标：
本 phase 已读本地文件：
本 phase 已读 third_party 本地文件：
本 phase 对应 upstream repo：
本 phase 明确不做：
本 phase 计划验证：

执行要求：
1. `Phase 0` 以冻结 stopline 和口径为主，除非总控文档明确允许，否则不要在这个 phase 先改代码。
2. `Phase 1` 只处理 benchmark contract / lane isolation / report contract，不顺手改 Retriever / Executor 算法。
3. `Phase 2` 只处理 object family 拆分，不把它扩成开放 schema 平台。
4. 每次引用第三方参考，必须写清：
   - 本地 `third_party/...` 文件
   - upstream repo
   - 借鉴机制
   - 为什么适合当前 phase
   - 为什么不照搬其余部分
5. 如果你发现总控文档某一点与当前代码事实冲突，可以质疑，但必须给出本地文件证据。

输出要求：
1. 用中文。
2. 过程里先做事，不要长篇空谈。
3. 最终必须明确说明：
   - `Phase 0` 是否完成
   - `Phase 1` 是否完成
   - `Phase 2` 是否完成
   - 哪个地方如果没有完成，是因为什么停下

最终输出必须包含这个固定小节：

本轮完成追加说明
- 本轮 phase 范围：`Phase 0 -> Phase 2`
- 完成状态：`已完成 / 部分完成 / 未完成`
- Phase 0 状态：`已完成 / 部分完成 / 未完成`
- Phase 1 状态：`已完成 / 部分完成 / 未完成`
- Phase 2 状态：`已完成 / 部分完成 / 未完成`
- 已完成项：
- 未完成项：
- 修改文件：
- 验证与结果：
- 本轮引用的 third_party 本地文件：
- 本轮对应的 upstream repo：
- 是否满足进入下一组 phase 的条件：`是 / 否`
- 若否则，阻塞是什么：
- 下一轮最小继续项：
- 本轮明确未涉及：

如果没有完成，也必须如实写，不要粉饰。
```

---

## 3. Prompt B：第二次完成 `Phase 3 -> Phase 4 -> Phase 5`

```text
你现在工作在 `/home/qcrs/statebus/project`。

这次只做第二组连续 phase：
- `Phase 3`
- `Phase 4`
- `Phase 5`

总控文档：
- `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`

前提：
1. `Phase 0 -> Phase 2` 已经完成，或至少已经有清楚的完成/阻塞说明。
2. 如果你发现 `Phase 2` 的退出条件其实未满足，必须先停下报告，不能直接硬做 `Phase 3`。

你的任务是严格按总控文档，顺序完成 `Phase 3 -> Phase 4 -> Phase 5`。

硬边界：
1. 只能在 host-side 主线内工作。
2. 不做 VM / Docker / openEuler / nsjail / 强沙箱 / hidden-state / KV / CodeAct 主路径。
3. 不允许跳 phase。
4. `Phase 3` 不完成，不能进入 `Phase 4`。
5. `Phase 4` 不完成，不能进入 `Phase 5`。
6. 当前仍然不允许把工作改写成开放平台演化项目。
7. `Phase 5` 的 memory 分层必须服务赛题，不服务“大而全 memory intelligence”叙事。

你必须先读：
- `AGENTS.md`
- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`

然后严格按总控文档要求：
1. 先补读 `Phase 3` 的本地必读文件、第三方本地文件和 upstream repo。
2. 完成 `Phase 3` 范围内的工作。
3. 检查 `Phase 3` 退出条件。
4. 满足后，再进入 `Phase 4`。
5. 再按同样方式推进到 `Phase 5`。

每进入一个新 phase 前，都必须先输出这一段：

当前 phase：
本 phase 单一目标：
本 phase 已读本地文件：
本 phase 已读 third_party 本地文件：
本 phase 对应 upstream repo：
本 phase 明确不做：
本 phase 计划验证：

执行要求：
1. `Phase 3` 只补 typed handoff contract，不新增 agent 角色，不做开放状态市场。
2. `Phase 4` 只处理 Retriever / Executor 合同性真实性，不扩开放域 corpus，不大规模加工具。
3. `Phase 5` 只处理 memory 分层与 replay contract 强化，不重新追 `assist_only` headline。
4. 每次引用第三方参考，必须写清：
   - 本地 `third_party/...` 文件
   - upstream repo
   - 借鉴机制
   - 为什么适合当前 phase
   - 为什么不照搬其余部分
5. 如果你发现前置 phase 的退出条件其实没闭合，必须直接说。

输出要求：
1. 用中文。
2. 不要把“下一步可以做”写成“已经完成”。
3. 最终必须明确说明：
   - `Phase 3` 是否完成
   - `Phase 4` 是否完成
   - `Phase 5` 是否完成
   - 如果停下，是卡在哪个退出条件

最终输出必须包含这个固定小节：

本轮完成追加说明
- 本轮 phase 范围：`Phase 3 -> Phase 5`
- 完成状态：`已完成 / 部分完成 / 未完成`
- Phase 3 状态：`已完成 / 部分完成 / 未完成`
- Phase 4 状态：`已完成 / 部分完成 / 未完成`
- Phase 5 状态：`已完成 / 部分完成 / 未完成`
- 已完成项：
- 未完成项：
- 修改文件：
- 验证与结果：
- 本轮引用的 third_party 本地文件：
- 本轮对应的 upstream repo：
- 是否满足进入下一组 phase 的条件：`是 / 否`
- 若否则，阻塞是什么：
- 下一轮最小继续项：
- 本轮明确未涉及：

如果没有完成，也必须如实写，不要粉饰。
```

---

## 4. Prompt C：第三次完成 `Phase 6 -> Phase 7`

```text
你现在工作在 `/home/qcrs/statebus/project`。

这次只做第三组连续 phase：
- `Phase 6`
- `Phase 7`

总控文档：
- `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`

前提：
1. `Phase 0 -> Phase 5` 已经完成，或至少已有明确完成/阻塞说明。
2. 如果你发现 `Phase 5` 的退出条件未满足，必须先停下报告，不能直接进入 `Phase 6`。

你的任务是严格按总控文档，顺序完成 `Phase 6 -> Phase 7`。

硬边界：
1. 只能在 host-side 主线内工作。
2. 不做 VM / Docker / openEuler / nsjail / 强沙箱 / hidden-state / KV / CodeAct 主路径。
3. 不允许把 `Phase 6` 改成开放 DAG planner 项目。
4. `Phase 7` 只能在前面 phase 已收口的前提下做 artifact closure。
5. 不允许在 artifact 未落盘前改 headline。
6. 不允许把 formal controlled 与 open validation 混写。

你必须先读：
- `AGENTS.md`
- `README.md`
- `docs/reference/题目.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/host_mainline_authenticity_execution_plan_20260610.md`

然后严格按总控文档要求：
1. 先补读 `Phase 6` 的本地必读文件、第三方本地文件和 upstream repo。
2. 完成 `Phase 6` 范围内的工作。
3. 检查 `Phase 6` 退出条件。
4. 满足后，再进入 `Phase 7`。
5. `Phase 7` 严格按总控文档要求的验证顺序推进。

每进入一个新 phase 前，都必须先输出这一段：

当前 phase：
本 phase 单一目标：
本 phase 已读本地文件：
本 phase 已读 third_party 本地文件：
本 phase 对应 upstream repo：
本 phase 明确不做：
本 phase 计划验证：

执行要求：
1. `Phase 6` 只允许把 Planner 做成 bounded compiler，不允许把它扩成开放 planner。
2. `Phase 7` 必须严格区分：
   - formal controlled pack
   - open validation pack
3. `Phase 7` 必须按验证顺序执行：
   - `pytest -q`
   - `python -m runtime.smoke`
   - deterministic targeted rerun
   - deterministic repeat-10
   - serialized API repeat-10
   - open validation refresh
4. 每次引用第三方参考，必须写清：
   - 本地 `third_party/...` 文件
   - upstream repo
   - 借鉴机制
   - 为什么适合当前 phase
   - 为什么不照搬其余部分
5. 如果 `Phase 6` 的 bounded fields 没有真实消费路径，不能假装已完成。

输出要求：
1. 用中文。
2. 最终必须明确说明：
   - `Phase 6` 是否完成
   - `Phase 7` 是否完成
   - formal 证据层是否已干净收口
   - open validation 是否仍保持 support-only

最终输出必须包含这个固定小节：

本轮完成追加说明
- 本轮 phase 范围：`Phase 6 -> Phase 7`
- 完成状态：`已完成 / 部分完成 / 未完成`
- Phase 6 状态：`已完成 / 部分完成 / 未完成`
- Phase 7 状态：`已完成 / 部分完成 / 未完成`
- 已完成项：
- 未完成项：
- 修改文件：
- 验证与结果：
- 本轮引用的 third_party 本地文件：
- 本轮对应的 upstream repo：
- formal controlled 是否已干净收口：`是 / 否`
- open validation 是否仍保持 support-only：`是 / 否`
- 若未完成，阻塞是什么：
- 后续剩余最小项：
- 本轮明确未涉及：

如果没有完成，也必须如实写，不要粉饰。
```

---

## 5. Prompt D：单独要求他补“本轮完成追加说明”

如果某一轮已经做完，但你只想让他补一段规范收尾说明，可以再单独发下面这个 prompt。

```text
基于你刚才这一轮在 `/home/qcrs/statebus/project` 的实际工作，现在不要继续开发，不要扩 scope，只补一段“本轮完成追加说明”。

要求：
1. 严格基于你本轮实际读过的文件、实际改过的文件、实际跑过的验证和实际得到的结果。
2. 不能把计划写成完成项。
3. 不能把 worktree 中未验证方向写成正式结论。
4. 如果本轮只完成了一部分，就直接写“部分完成”。
5. 如果某个 phase 退出条件没满足，就直接写“未满足”。

输出格式固定为：

本轮完成追加说明
- 本轮 phase 范围：
- 完成状态：`已完成 / 部分完成 / 未完成`
- 各 phase 状态：
- 已完成项：
- 未完成项：
- 修改文件：
- 验证与结果：
- 本轮引用的 third_party 本地文件：
- 本轮对应的 upstream repo：
- 是否满足进入下一轮的条件：`是 / 否`
- 若否则，阻塞是什么：
- 下一轮最小继续项：
- 本轮明确未涉及：
```

---

## 6. 推荐使用顺序

1. 第一次发 `Prompt A`
2. 第二次发 `Prompt B`
3. 第三次发 `Prompt C`
4. 如果某次结果不够规整，再补发 `Prompt D`

这样后续多轮窗口会始终被约束在：

- 总控计划
- phase 顺序
- 必读材料
- 本地第三方参考
- upstream repo 对应
- 固定收尾说明

不会轻易漂回“泛泛谈方案”或“顺手扩 scope”。
