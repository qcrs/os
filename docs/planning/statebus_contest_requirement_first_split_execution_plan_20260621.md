# StateBus 赛题优先分层执行计划

日期：`2026-06-21`

适用范围：

- 当前仓库 `/home/qcrs/statebus/project`
- 用于汇总最新问题、最新对象分层和下一阶段执行顺序
- 这是当前推荐执行合同，不是历史结果报告

状态：

- 基于赛题原文 `docs/reference/题目.md`
- 基于当前实现与最新有效 artifact：
  - `runs/contest_superiority_headline_v2_api_repeat3_20260621_192847/api_repeat3_superiority_v2/benchmark_report.md`
- 用于覆盖旧计划文档里已经被实现状态改写的部分

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

### 3.1 当前最接近赛题主问题的对象

当前最接近赛题主问题的对象是：

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

- `runs/contest_superiority_headline_v2_api_repeat3_20260621_192847/api_repeat3_superiority_v2/benchmark_report.md`

### 3.2 当前 v2 已经出现的正信号

在最新 `repeat=3` 包里：

- `protocol llm_total_tokens < text`
- `control_bytes` 继续更低
- `wrong_family_rate = 0.00`
- `exact_match_rate = 0.78`
- `admissible_match_rate = 1.00`，但已明确只读作 safety floor

这说明：

- v2 不是坏对象
- superiority 主线已经开始被回答
- 但它还没有闭合

### 3.3 当前 v2 的三个结构性缺口

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

#### 缺口 C：protocol 的 wall-time 被当前 prompt / handoff 形状放大

当前 protocol lane 的慢，不应直接理解成 “typed-state 本身拖慢系统”。

更接近根因的是：

1. planner prompt 更压缩，但也更格式敏感
2. summarizer handoff 仍然带着嵌套结构
3. protocol summarizer 不是直接看扁平文本，而是先拿结构化 summary packet，再整体 `json.dumps` 成字符串，再嵌进 tagged JSON

这会带来一种典型现象：

- token 稍低
- 但模型解析 wall-time 更高

当前热点代码位置：

- `agents/sample_agents.py`

---

## 4. 当前哪些结论可以诚实说

### 4.1 可以说的

1. 机制成立
   - 结构化 carrier 存在
   - typed-state minimal packet 被真实消费
   - planner-open superiority scaffold 已经存在

2. 局部 superiority 信号存在
   - 在当前 planner-open paired comparator 上，protocol 的 `control_bytes` 和 `llm_total_tokens` 方向更优

### 4.2 现在不能说的

1. 不能说 `StateBus 已整体优于 pure-text`
2. 不能说 `v2 已经覆盖 memory superiority`
3. 不能说 `总通信负担更低`
4. 不能说 `open/LangGraph comparison 已经能当 formal 主证据`

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
2. 后续实现和最新 artifact 已经明确把 v2 缩窄成：
   - `planner-open overall superiority scaffold only`
   - `memory reuse remains a formal-secondary object`

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

- `contest_superiority_headline_v2` 只能诚实承担 `superiority_comm scaffold`
- `superiority_memory` 仍未形成正式 paired object

### 6.3 外部开放比较组

用途：

- 展示开放 runtime / LangGraph 等外部比较
- 证明工程可扩展性与泛化展示

当前边界：

- `open_system_comparison_v1` 是 `open engineering comparison only`
- 不进入当前 formal contest headline

---

## 7. 最新推荐执行顺序

## Phase 0：冻结边界

目标：

- 先把什么不做写死，避免 benchmark 再次混读

本阶段结论必须统一为：

1. `contest_honest_headline_v1 = mechanism object`
2. `contest_superiority_headline_v2 = superiority_comm scaffold`
3. `memory superiority` 需要单独对象
4. `open_system_comparison_v1` 不进 formal 主证据
5. 当前不进 `repeat=10`

本阶段产出：

- 文档层 stopline
- 对旧计划文档的 historical note

允许改动：

- `docs/planning/*`
- 必要时 `README.md` 中的 object reading boundary

通过标准：

- 团队内部不再把一个对象同时读成 communication + memory + open comparison

## Phase 1：先把 communication superiority 收干净

目标：

- 先把当前 `contest_superiority_headline_v2` 收成一个可信的 `superiority_comm scaffold`

当前要解决的不是“所有性能问题”，而是两类最会污染赛题判断的问题：

1. planner repair 残余
2. protocol planner / summarizer wall-time 偏高

### Phase 1A：planner prompt 收口

目标：

- 降低 protocol planner 的格式脆弱性
- 保持 single-variable 边界不变

重点文件：

- `agents/sample_agents.py`

执行要求：

- 保留 text/protocol 都是 `plan_source=llm`
- 不放宽 DAG 合同
- 只减少 prompt 的格式敏感性和 repair 触发概率

内部工程通过线：

- `planner one-shot valid rate >= 0.99`
- `repeat=3` 下 planner repair 尽量压到 `0-1`
- 不新增 correctness failure

### Phase 1B：protocol summarizer handoff 收口

目标：

- 解决当前 token 下降但 wall-time 不稳的问题

重点文件：

- `agents/sample_agents.py`

执行要求：

- 扁平化 protocol summarizer handoff
- 不再把完整 summary packet 先 `json.dumps` 再嵌套传给 summarizer
- 去掉重复语义字段
- 保持 typed-state minimal consumption contract 不变

内部工程通过线：

- `protocol summarize_ms` 收敛
- `protocol llm_total_tokens < text` 继续成立
- `task_ms` 不再系统性更差

### Phase 1C：parity 诊断重构

目标：

- 保留 diagnostic 价值，但不再被中间行为痕迹带偏

当前保留：

- `cross_lane_actual_parity`

新增建议：

- `decision_outcome_parity`

新诊断只比较：

- `semantic_selected_route`
- `semantic_selected_tool_name`
- 最终 correctness / exact / wrong_family

而不再拿以下中间痕迹作为 superiority stopline：

- `actual_corpus_scope`
- `actual_tool_candidates`

重点文件：

- `eval/runner.py`
- 必要时 `runtime/orchestrator.py`

通过标准：

- actual parity 继续保留为 diagnostic
- outcome parity 能帮助判断“分叉是否伤害结果”

## Phase 2：communication superiority 验证梯度

目标：

- 只在对象热路径收口后再扩大 repeat

验证顺序固定：

1. `source deploy/activate_statebus_host.sh && python -m pytest -q`
2. `source deploy/activate_statebus_host.sh && python -m runtime.smoke`
3. API `repeat=1`
4. API `repeat=3`
5. API `repeat=10`

### Repeat=1 通过线

- `Observed planner sources: llm`
- planner token 非零
- `protocol llm_total_tokens < text`
- `protocol task_ms` 不显著更差
- planner repair 尽量为 0
- `wrong_family_rate = 0`

### Repeat=3 通过线

- token 优势方向稳定
- `task_ms` 不再系统性慢
- `exact_match_rate` 不明显塌陷
- `wrong_family_rate = 0`
- planner repair 已很低
- actual parity 仍只读作 diagnostic

### Repeat=10 前置条件

只有以下条件同时满足，才进入 `repeat=10`：

1. `repeat=3` 无 correctness failure
2. planner repair 已很低
3. planner / summarizer wall-time 未继续系统性偏高
4. communication superiority 的方向已经稳定

## Phase 3：单独形成 memory superiority

目标：

- 正式补上赛题第三轴

当前禁止做法：

- 继续假装 `contest_superiority_headline_v2` 已经覆盖 memory gain

必须新增：

- 一个真正的 `superiority_memory` paired object

设计要求：

1. 同 family
2. 同 scorer
3. 同 planner-open
4. 同 text / protocol carrier 对照
5. 启用真实连续任务 reuse
6. 不允许 override 式“预塑造 replay 成功”

重点文件：

- `tasks/contest_family_spec.py`
- `tasks/sample_tasks.py`
- 必要时 `eval/runner.py`

主指标：

- `reuse_gain`
- `skipped_step_count`
- `task_ms`
- `exact_match_rate`
- `wrong_family_rate`

通过标准：

- 非零 reuse 证据
- 对应真实时间或步骤下降
- 不是“命中记忆但没省任何东西”

## Phase 4：最后才做 open / LangGraph 外部比较

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
     - planner prompt 收口
     - summarizer handoff 扁平化
     - parity 诊断重构

3. `comm-validation`
   - 内容：
     - `repeat=1 -> repeat=3`
     - 最新 verdict

4. `memory-scaffold`
   - 内容：
     - `superiority_memory` 正式对象

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
- protocol summarizer handoff 已扁平化
- `wrong_family_rate = 0`
- `protocol llm_total_tokens < text` 仍成立

### Stage C：communication superiority repeat=3

必须同时满足：

- `repeat=3` 无 correctness failure
- `task_ms` 不再系统性恶化
- `exact_match_rate` 不明显塌陷
- `cross_lane_actual_parity` 继续只读作 diagnostic

### Stage D：communication superiority repeat=10

只有在 Stage C 已通过后才允许进入。

### Stage E：memory superiority object 成形

必须同时满足：

- paired object 已存在
- reuse 不再是 override 造出来的结果
- 指标已能直接读 `reuse_gain / skipped_step_count / task_ms`

### Stage F：open / LangGraph 外部展示

只有在：

- communication superiority 至少达到 `repeat=3` 稳定
- memory superiority 对象已成形

后，才建议推进。
