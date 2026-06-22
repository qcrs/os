# StateBus 赛题优先分层执行计划

日期：`2026-06-21`

适用范围：

- 当前仓库 `/home/qcrs/statebus/project`
- 用于汇总最新问题、最新对象分层和下一阶段执行顺序
- 这是当前推荐执行合同，不是历史结果报告

状态：

- 基于赛题原文 `docs/reference/题目.md`
- 基于当前实现与最新有效 artifact：
  - `runs/contest_superiority_headline_v2_api_repeat3_stageb_hotpath/benchmark_report.md`
  - `runs/contest_superiority_headline_v2_api_repeat3_stageb_hotpath/benchmark_results.json`
- 用于覆盖旧计划文档里已经被实现状态改写的部分
- `2026-06-22` 起，repo 内 taskset split 已经落地为：
  - `superiority_comm_v1`
  - `superiority_memory_v1`
  - `uncertainty_audit_v1`
- `contest_superiority_headline_v2` 现在只保留为历史过渡 scaffold / blocker reference，不再是当前主 API 对象
- `2026-06-22` 的 `superiority_comm_v1 repeat=3 post_gatefix` 已确认：
  - coverage false negative 已消失
  - 当前 formal blocker 仍只有 `contest_repeat_insufficient`
  - token 优势稳定，但 `task_ms` 仍是 protocol 略慢
  - planner repair 不再是主 latency blocker
  - 下一步只收 `summarizer` handoff / summary shape
  - 在 summarizer latency 没收平前，不进入 `repeat=10`，也不切到 memory / open 主线

---

## 1. 核心判断

现在的问题不是 `StateBus 没优势`，而是：

> 你们把
> `机制证明`
> 和
> `整体优势证明`
> 混进了同一套 benchmark，
> 导致赛题真正要的优势证据一直出不来。

因此，下一阶段主线不应再是“继续泛泛优化 v2”。

下一阶段只做一件事：

> 按赛题要求，
> 把 benchmark 正式拆成
> `能力证明组`
> 与
> `整体比较组`，
> 然后按
> `communication superiority -> memory superiority -> open/LangGraph 外部展示`
> 的顺序推进。

---

## 2. 赛题要求如何转成执行目标

赛题真正要求的不是单点机制存在，而是三条线同时成立：

1. 通信效率
   - 评分更接近 `相比纯文本协作的 token 节省效果`
   - 因此主指标必须是 `llm_total_tokens`
   - `control_bytes` 只能做机制解释，不能单独承担主结论

2. 状态传递创新
   - 要证明非文本状态真的被生成、传递、接收、消费
   - 这更适合由机制对象承担

3. 记忆复用效果
   - 不是“有 memory hit”就算过关
   - 必须证明真实减少步骤、减少重复计算或降低耗时

同时赛题还要求：

4. 系统完整性
   - 至少 3 个 agent
   - 连续任务
   - 不少于 10 轮稳定执行

5. 实验验证说服力
   - 必须是同任务条件下的纯文本 vs 结构化协议比较
   - 不能把 engineering smoke surface 或 open extension surface 冒充 formal headline

---

## 3. 当前最新事实

### 3.1 当前最接近赛题主问题的历史过渡对象

当前最接近赛题主问题、但已经降为历史过渡说明的对象是：

- `contest_superiority_headline_v2`

它已经满足：

- contest-facing
- single-variable
- `plan_source=llm`
- text / protocol 同任务 paired comparator

最新 artifact 明确显示：

- `Observed planner sources: llm`
- `Primary headline gate: superiority_scaffold_gate`
- `Reading boundary: admissible_match_rate stays a safety floor`
- `cross_lane_actual_parity` 已降为 diagnostic only

参考：

- `runs/contest_superiority_headline_v2_api_repeat3_stageb_hotpath/benchmark_report.md`

### 3.2 当前 v2 已经出现的正信号

在最新 `repeat=3` 包里：

- `Observed planner sources: llm`
- `Planner one-shot valid rate = 1.00`
- `Planner repair attempts = 0 / 120`
- `protocol llm_total_tokens < text`
- `control_bytes` 继续更低
- `wrong_family_rate = 0.00`
- `exact_match_rate = 0.80`
- `admissible_match_rate = 1.00`，但已明确只读作 safety floor

这说明：

- v2 不是坏对象
- superiority 主线已经开始被回答
- planner contract failure 已不再是当前主 blocker
- 但 communication superiority 还没有闭合

当前它只保留两个用途：

- 解释为什么 repo 需要从单一 headline pack 正式拆到三对象
- 保留 hotpath blocker 的历史来源，不再作为当前 formal API 主对象

### 3.2 当前 repo 内已经落地的主对象

当前 repo 的主对象已经迁移为：

1. `superiority_comm_v1`
   - 当前唯一 communication mainline
   - 只回答 `llm_total_tokens / task_ms / quality floor`
   - 保持 `plan_source=llm`

2. `superiority_memory_v1`
   - 当前 formal-secondary memory scaffold
   - 保持 `plan_source=llm`
   - 只读作 memory mainline scaffold，不读作 overall superiority closure

3. `uncertainty_audit_v1`
   - 当前 audit-only uncertainty surface
   - 不进 headline
   - 不重新抬成 blocker

### 3.3 当前 v2 的五个结构性缺口

#### 缺口 A：它不能回答 memory superiority

当前 `contest_superiority_headline_v2` 在任务生成时就写死了：

- `expected_reuse_mode = "none"`
- `runtime_reuse_contract = "reuse_disabled"`

因此它天然不能回答：

- `共享记忆复用是否带来真实收益`

代码位置：

- `tasks/contest_family_spec.py`

这不是“结果暂时还没出来”，而是：

- `对象设计上就没让它回答 memory gain`
- 当前 `repeat=3` 结果里这条线也是空的：
  - `memory_hits = 0`
  - `reuse_apply_rate = 0`
  - `reuse_gain = 0`
  - `validated_reuse_task_count = 0`

#### 缺口 B：cross-lane actual parity 发散证明的是行为分叉，不是公平性被破坏

当前 `cross_lane_actual_parity` 比较的核心字段是：

- `actual_tool_candidates`
- `actual_corpus_scope`

这些值直接来自 retriever / executor 的真实选择痕迹，而不是 fairness hard gate 元数据。

代码位置：

- `agents/sample_agents.py`
- `runtime/orchestrator.py`
- `eval/runner.py`

因此当前 diagnostic 的含义应固定为：

- `open planner 下 text/protocol 的实际行为路径会稳定分叉`

而不是：

- `benchmark fairness 已经失效`

最新 `repeat=3` 包里，这个 diagnostic 没有自然收敛：

- mismatch task ids = `10`
- mismatch counts = `corpus_scope: 20, tool_candidates: 4`
- role mismatch counts = `executor: 12, retriever: 12`

因此它现在更像：

- `行为分叉与高不确定性 case 的 LLM 解释成本共同出现`

#### 缺口 C：非文本传输机制成立，但效率叙事没有闭合

当前不能说“非文本传输不行”，因为机制面已经成立：

- `typed_executor_any_consumption_rate = 1.00`
- `typed_executor_minimal_expected_consumption_rate = 1.00`
- `executor_expected_kind_match_rate = 1.00`
- `executor_unexpected_kind_seen_rate = 0.00`

但当前也不能说“结构化通信整体更轻”，因为 protocol 的 handoff 负担并不更低：

- `handoff_wire_bytes`: `407.75 > 222.25`
- `handoff_payload_bytes`: `5273.47 > 2929.03`
- `handoff_nontext_bytes`: `3495.77 > 0`

因此当前诚实读法只能是：

- `LLM token / control plane 更省`
- `总 handoff 负担尚未证明更轻`

#### 缺口 D：protocol 的 wall-time 回退不是偶发抖动，而是当前 communication hot path 的结构性 blocker

当前 protocol lane 的慢，不应直接理解成 “typed-state 本身拖慢系统”，因为主要差额不在 retrieve / execute，而是在 LLM 侧。

最新 `repeat=3` pairwise 统计是：

- `60` 个 text/protocol 成对样本里，protocol 慢了 `45 / 60`
- `task_ms_delta mean = +346.42ms`
- `task_ms_delta median = +395.42ms`
- 分 run 均值分别是：
  - `run0: +216.28ms`
  - `run1: +396.41ms`
  - `run2: +426.58ms`

phase 级差额几乎全堆在：

- `planner_ms_delta mean = +117.01ms`
- `summarize_ms_delta mean = +231.61ms`
- `retrieve_ms_delta mean = +2.24ms`
- `execute_ms_delta mean = +1.28ms`

因此当前主 blocker 不是：

- typed-state I/O
- retrieval path
- execute path

而是：

- `planner + summarizer` 的 LLM wall-time

#### 缺口 E：当前结构化协议已经降 token，但还没有降高不确定性任务上的语义重建成本

这里需要和旧问题区分开：

- 旧的 protocol summarizer 双层 `json.dumps` handoff 已经在 Stage B 中移除
- 当前剩余问题不是“还有那条旧嵌套路径没改”，而是：
  - `_render_protocol_summary_input_text()` 现在仍是字段清单式 handoff
  - 它比旧版省 token
  - 但在 `ambiguous / replay_reusable / distractor / abstention_allowed` 这类高不确定性 case 上，仍要求模型重建证据竞争、保守决策和动作结论之间的关系

这就是为什么会出现：

- token 下降
- 但 wall-time 尤其 `summarize_ms` 仍系统性更高

当前最重的长尾 case 也支持这个判断：

- `rr-cache-replay_reusable`: `+752.7 / +596.4 / +1476.5 ms`
- `rr-billing-ambiguous`: `+1234.2 / +684.3 / +329.3 ms`
- `rr-auth-replay_reusable`: `+17.7 / +662.3 / +1237.1 ms`
- `rr-checkout-distractor`: `+727.3 / +639.3 / +471.3 ms`

按 case type 看：

- `abstention_allowed`: 平均 `+420.24ms`
- `bounded_alternative`: 平均 `+272.60ms`

按 task group 看：

- `inventory_rollout_chain`: 平均 `+534.86ms`
- `billing_queue_chain`: 平均 `+412.95ms`
- `checkout_release_chain`: 平均 `+376.44ms`

当前热点代码位置：

- `agents/sample_agents.py`
  - `_planner_messages()`
  - `_build_protocol_summary_input_packet()`
  - `_render_protocol_summary_input_text()`

### 3.4 当前阶段判断

当前阶段结论应固定为：

1. Stage A 已完成
   - 对象分层和 headline 边界已经冻结

2. taskset split 已完成首轮实现
   - `superiority_comm_v1 / superiority_memory_v1 / uncertainty_audit_v1` 已在 task/bundle/runner surface 落地
   - `contest_superiority_headline_v2` 不再承担当前主对象角色

3. split consistency fix 已完成
   - `superiority_memory_v1` 已统一到 planner-open
   - memory gate 已要求真实 effect
   - `uncertainty_audit_v1` payload / bundle surface 已同构

4. 当前还不能 freeze communication superiority
   - 历史 `repeat=3` 仍不能诚实读成 communication superiority 已闭合
   - 这也是为什么下一轮只允许最小 `superiority_comm_v1 repeat=1`

5. 当前不允许进入
   - `superiority_comm_v1 repeat=3`
   - `repeat=10`
   - `superiority_memory_v1` API 主线

---

## 4. 当前哪些结论可以诚实说

### 4.1 可以说的

1. 机制成立
   - 结构化 carrier 存在
   - typed-state minimal packet 被真实消费
   - planner-open superiority scaffold 已经存在

2. 局部 superiority 信号存在
   - 在当前 planner-open paired comparator 上，protocol 的 `control_bytes` 和 `llm_total_tokens` 方向更优
3. 非文本状态传递机制成立
   - minimal typed packet 已真实生产、传递、消费

### 4.2 现在不能说的

1. 不能说 `StateBus 已整体优于 pure-text`
2. 不能说 `v2 已经覆盖 memory superiority`
3. 不能说 `总通信负担更低`
4. 不能说 `当前 structured protocol 已经稳定更快`
5. 不能说 `当前 comparator 已经是 external traditional pure-text 主证据`
6. 不能说 `open/LangGraph comparison 已经能当 formal 主证据`

---

## 5. 旧计划文档现在如何使用

以下两份旧文档仍有参考价值：

- `docs/planning/statebus_superiority_headline_execution_plan_20260621.md`
- `docs/planning/statebus_contest_superiority_gate_contract_20260621.md`

但它们现在只能读作：

- `为什么要退出旧 headline`
- `为什么 superiority 不能乱 claim`
- `哪些 stopline 仍然有效`

它们不能再直接当当前唯一执行合同，原因有二：

1. 它们把 `contest_superiority_headline_v2` 讲得过大，默认它要同时回答 communication + memory
2. 后续实现已经把当前 repo 主对象正式拆成：
   - `superiority_comm_v1`
   - `superiority_memory_v1`
   - `uncertainty_audit_v1`
3. `contest_superiority_headline_v2` 现在只保留为：
   - `historical superiority scaffold`
   - `hotpath blocker reference`

---

## 6. 新的正式分层

### 6.1 能力证明组

用途：

- 回答赛题“机制真的存在且稳定”

对象：

- `contest_honest_headline_v1`
- `contest_dual_mode_controlled_v3`
- `typed_state_mechanism_v3`
- `typed_state_consumer_sensitivity_v3`
- `memory_policy_controlled_v3`
- 必要时 `memory_reuse_v3`

固定读法：

- structured communication 成立
- non-text state transfer 成立
- replay / memory mechanism 成立
- purity / stability / repeat gate 成立

禁止读法：

- 不把这组对象偷读成整体 superiority headline

### 6.2 整体比较组

用途：

- 回答赛题“相比 pure-text，到底有没有更优”

这组必须进一步拆成两条：

1. `superiority_comm`
   - 回答：
     - `llm_total_tokens`
     - `task_ms`
     - `quality floor`

2. `superiority_memory`
   - 回答：
     - `reuse_gain`
     - `skipped_step_count`
     - `task_ms`
     - `quality floor`

当前状态：

- `superiority_comm_v1` 已是当前 communication mainline
- `superiority_memory_v1` 已是当前 formal-secondary memory scaffold
- `uncertainty_audit_v1` 已是当前 audit-only surface
- `contest_superiority_headline_v2` 只保留历史过渡说明价值

### 6.3 外部开放比较组

用途：

- 展示开放 runtime / LangGraph 等外部比较
- 证明工程可扩展性与泛化展示

当前边界：

- `open_system_comparison_v1` 是 `open engineering comparison only`
- 不进入当前 formal contest headline

---

## 7. 最新推荐执行顺序

## Phase 0：保持 split 边界冻结

目标：

- 先把什么不做写死，避免 benchmark 再次混读

本阶段结论必须统一为：

1. `contest_honest_headline_v1 = mechanism object`
2. `contest_superiority_headline_v2 = historical scaffold only`
3. `superiority_comm_v1 = communication mainline`
4. `superiority_memory_v1 = formal-secondary memory scaffold`
5. `uncertainty_audit_v1 = audit only`
6. `open_system_comparison_v1` 不进 formal 主证据
7. 当前不进 `repeat=10`

本阶段产出：

- 文档层 stopline
- 对旧计划文档的 historical note

允许改动：

- `docs/planning/*`
- 必要时 `README.md` 中的 object reading boundary

通过标准：

- 团队内部不再把一个对象同时读成 communication + memory + open comparison

## Phase 1：先做 split/doc sync 与归因隔离

目标：

- 让文档、taskset、runner 与测试都承认 split 后边界
- 不把 hotpath 脏改动混进 split checkpoint
- 不在归因不干净时提前跑 API

本阶段要求：

1. `contest_superiority_headline_v2` 明确退到历史过渡说明
2. `superiority_comm_v1` 明确成为当前唯一 communication mainline
3. `superiority_memory_v1` 明确保持 formal-secondary memory scaffold
4. `uncertainty_audit_v1` 明确保持 audit-only
5. split/doc checkpoint 不混入 `agents/sample_agents.py` / `tests/test_llm_runtime.py`

通过标准：

- 文档合同与实现边界一致
- split 改动可单独 checkpoint
- hotpath 改动继续隔离

## Phase 2：本地验证

目标：

- 在 host 环境下确认 split/mainline 改动本地干净
- 不先跑 API

验证顺序固定：

1. `source deploy/activate_statebus_host.sh && python -m pytest -q tests/test_taskset_mainline_split.py tests/test_smoke.py`
2. `source deploy/activate_statebus_host.sh && python -m pytest -q`
3. `source deploy/activate_statebus_host.sh && python -m runtime.smoke`

通过标准：

- split regression 通过
- smoke 通过
- `superiority_comm_v1` surface 没被 split 修补破坏

## Phase 3：最小 communication API

目标：

- 在归因干净前提下，只允许最小 `superiority_comm_v1 repeat=1`
- 不自动推进到 `repeat=3`

验证顺序固定：

1. `source deploy/activate_statebus_host.sh && python -m eval.runner --task-set superiority_comm_v1 --repeat 1 --modes text,protocol --llm-mode api --llm-config deploy/statebus_llm.yaml.local --out runs/superiority_comm_v1_api_repeat1_post_split_docsync --quiet-progress`

### Repeat=1 通过线

- `Observed planner sources: llm`
- planner token 非零
- `protocol llm_total_tokens < text`
- `protocol task_ms` 不显著更差
- `wrong_family_rate = 0`
- `exact_match_rate` 不明显塌陷

读法边界：

- 只读 communication mainline
- 不从这里读取 memory superiority
- `cross_lane_actual_parity` 继续只读作 diagnostic
- repeat=1 正结果不自动升级成 repeat=3/10 readiness

## Phase 4：communication repeat=3 以后再说

只有在 `superiority_comm_v1 repeat=1` 方向正确、且归因继续干净时，才允许重新讨论 `repeat=3`。

## Phase 5：memory mainline 继续保持 scaffold

当前固定读法：

- `superiority_memory_v1` 是 planner-open 的 formal-secondary memory scaffold
- 它要求真实 effect
- 它当前不是 overall superiority closure

## Phase 6：最后才做 open / LangGraph 外部比较

目标：

- 用于对外展示工程泛化，不用于当前赛题 formal 主裁决

原因固定为：

1. `README.md` 已明确 `open_system_comparison_v1` 是 open engineering surface
2. `eval/open_runner.py` 下的 `langgraph_native_text_open` 目前还是工程 runtime，不是赛题级正式 paired comparator

因此当前定位必须固定为：

- `外部展示组`
- `不并入 contest formal headline`

通过标准：

- 单独报告
- 单独标题
- 明确写出 `open engineering comparison only`

---

## 8. 当前最推荐的提交顺序

1. `docs-only`
   - 内容：
     - 新分层
     - stopline
     - 最新对象边界

2. `comm-hotpath`
   - 内容：
     - summarizer-first hot path 收口
     - 仅保留 planner contract 守护
     - 必要时最小 parity 诊断补充

3. `comm-validation`
   - 内容：
     - 先只允许 `superiority_comm_v1 repeat=1`
     - 不自动升级到 `repeat=3`

4. `memory-scaffold`
   - 内容：
     - `superiority_memory_v1` scaffold 继续收口

5. `memory-validation`
   - 内容：
     - memory superiority 结果

6. `open-comparison`
   - 内容：
     - open / LangGraph 单独展示

---

## 9. 当前阶段明确不做的事

1. 不继续抢救 `contest_honest_headline_v1` 为整体 superiority headline
2. 不把 `open_system_comparison_v1` 当 formal 主证据
3. 不优先修 external baseline 主线
4. 不先扩大任务厚度
5. 不先做 openEuler 终态包装
6. 不在 communication superiority 还没稳定前进入 `repeat=10`

---

## 10. 一句话执行路线

先把 benchmark 正式拆成：

- `能力证明组`
- `communication superiority 组`
- `memory superiority 组`
- `open / LangGraph 外部展示组`

然后严格按：

`comm -> memory -> open`

的顺序推进。

在这之前，不再让任何单一对象同时证明：

- 机制成立
- 通信优势
- 记忆优势
- 外部开放比较

因为这正是当前赛题证据一直出不清的主因。

---

## 11. 赛题交付口径

如果按当前计划顺利推进，最终对外口径应分三层，不允许混写。

### 11.1 主结论

只允许回答：

1. `StateBus` 在 contest-facing paired comparator 下，相对 pure-text 是否在 `llm_total_tokens / task_ms / quality floor` 上形成 communication superiority
2. `StateBus` 在连续关联任务下，相对 pure-text 是否在 `reuse_gain / skipped_step_count / task_ms` 上形成 memory superiority

### 11.2 次结论

只允许回答：

1. structured carrier / typed-state handoff / replay mechanism 是否成立
2. 不少于 `10` 轮是否稳定
3. control plane 是否更紧凑

### 11.3 展示层

只允许回答：

1. open / LangGraph 外部 runtime 下的工程表现
2. 更开放协作形态下的展示性结果

禁止混写：

- 不把展示层结果回填成 formal 主结论
- 不把 mechanism/support surface 偷读成 superiority win

---

## 12. 阶段通过表

### Stage A：对象分层冻结

必须同时满足：

- `contest_honest_headline_v1` 不再承担 overall superiority
- `contest_superiority_headline_v2` 被明确缩窄成 communication scaffold
- `superiority_memory` 被确认为单独对象

### Stage B：communication hot path 收口

必须同时满足：

- planner repair 已明显下降
- protocol summarizer handoff 已从旧嵌套路径退出
- 高不确定性 case 的 summarizer 语义 handoff 已被重写得更接近 text lane narrative
- `wrong_family_rate = 0`
- `protocol llm_total_tokens < text` 仍成立

当前状态：

- 部分通过
- 剩余 blocker：`summarize_ms / task_ms` 仍系统性偏高

### Stage C：superiority_comm_v1 repeat=1

必须同时满足：

- `Observed planner sources: llm`
- planner token 非零
- `protocol llm_total_tokens < text`
- `protocol task_ms` 不显著更差
- `wrong_family_rate = 0`
- `exact_match_rate` 不明显塌陷
- `cross_lane_actual_parity` 继续只读作 diagnostic

当前状态：

- 待运行
- 前置条件是：
  - split/doc checkpoint 已完成
  - 本地验证已通过
  - hotpath 脏改动未混入 split 归因

### Stage D：superiority_comm_v1 repeat=3

只有在 Stage C 已通过、且 repeat=1 方向正确时才允许进入。

### Stage E：memory superiority object 成形

必须同时满足：

- `superiority_memory_v1` scaffold 已存在
- reuse 不再是 override 造出来的结果
- 指标已能直接读 `reuse_gain / skipped_step_count / task_ms`

### Stage F：open / LangGraph 外部展示

只有在：

- communication superiority 至少达到 `repeat=3` 稳定
- memory superiority 对象已成形

后，才建议推进。
