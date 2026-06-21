# StateBus 任务集与赛题需求对齐设计方案

日期：`2026-06-21`

适用范围：

- 当前仓库 `/home/qcrs/statebus/project`
- 用于回答“现有任务集是否贴合赛题、如何重构任务集、何时把设计并回旧计划文档”
- 这是 docs-only 设计方案，不是实现完成说明

状态：

- 基于赛题原文 `docs/reference/题目.md`
- 基于当前主执行合同：
  - `docs/planning/statebus_contest_requirement_first_split_execution_plan_20260621.md`
- 基于历史 guardrail：
  - `docs/planning/statebus_superiority_headline_execution_plan_20260621.md`
  - `docs/planning/statebus_contest_superiority_gate_contract_20260621.md`
- 基于当前任务定义与最新有效 artifact：
  - `tasks/contest_family_spec.py`
  - `tasks/contest_family_spec.yaml`
  - `tasks/sample_tasks.py`
  - `runs/contest_superiority_headline_v2_api_repeat3_stageb_hotpath/benchmark_report.md`

---

## 1. 核心结论

现在的问题不是“任务集太短，所以优化看不出来”。

更准确的判断是：

> 当前任务集对 `StateBus` 的赛题主证据来说发生了对象错位。
> 它并不短，但它把
> `LLM 开放规划 / 歧义消解 / 保守 abstain`
> 的成本放到了 headline 主轴上，
> 却没有把
> `结构化通信 / 非文本状态传递 / 共享记忆复用`
> 这三条机制收益自然暴露出来。

因此下一阶段不应继续只把问题读成：

- prompt 还不够好
- summarizer 还不够快
- task 再做厚一点可能就好了

下一阶段应先做一件更本质的事：

> 把任务集正式拆成
> `communication mainline`
> `memory mainline`
> `uncertainty audit`
> 三组，
> 让不同任务只回答对应的赛题问题，
> 不再让一个 headline pack 同时承担机制证明、整体 superiority 和 LLM 不确定性压力测试。

---

## 2. 赛题真实需求

从 `docs/reference/题目.md` 出发，赛题要求的不是“泛 benchmark 表现”，而是三条明确的系统层证据：

1. `低开销通信`
   - 对应评分主轴：`通信效率（25分）`
   - 直接比较对象应是：`纯文本协作` vs `结构化协议协作`
   - 最核心主指标是：
     - `llm_total_tokens`
     - `消息次数`
     - `控制面通信开销`

2. `非文本状态传递`
   - 对应评分主轴：`状态传递创新（20分）`
   - 重点不是“最终答得更对”，而是：
     - 非文本状态是否真实生成
     - 是否真实传递
     - 是否真实接收
     - 是否真实消费
   - 这更接近机制对象，而不是整体 superiority headline

3. `共享记忆复用`
   - 对应评分主轴：`记忆复用效果（20分）`
   - 重点不是“memory hit > 0”
   - 而是：
     - 是否减少重复步骤
     - 是否减少重复检索/重复执行
     - 是否降低任务时延

此外还有两个整体要求：

4. `系统完整性`
   - 至少 `3` 个 agent
   - 至少 `2` 组关联性连续任务
   - 稳定执行不少于 `10` 轮

5. `实验验证说服力`
   - 要有同任务条件下的 pure-text vs structured 对比
   - 不能把 engineering / audit surface 误写成 formal headline

结论：

- 赛题真正要的是“机制收益被任务自然放大并可复现实验读出来”
- 不是“让模型在更复杂的歧义任务上继续做更难的解释”

---

## 3. 当前任务集的真实问题

### 3.1 当前任务集不是太短，而是短而尖

当前 formal headline rows 并不属于 trivial task。

代码合同明确要求：

- `reasoning_hops_min >= 2`
- `S1 -> dependency_depth == 1`
- `S2 -> dependency_depth >= 2`
- 必须包含 `retrieve / validate / execute / summarize`

对应代码：

- `tasks/sample_tasks.py:1233`

当前 spec 的基础结构也不算太薄：

- `5` 个 family
- 每个 family 固定 `4` 个 case：
  - `clean`
  - `distractor`
  - `ambiguous`
  - `replay_reusable`
- 每个 case 使用 `4-5` 个文档角色
- 每个 case 的证据文本总量平均约 `973` 字符

因此，当前问题不能简单归结为：

- 任务短到不足以区分 text/protocol

### 3.2 当前 headline pack 把 memory 轴直接关掉了

`contest_superiority_headline_v2` 任务生成时写死：

- `expected_reuse_mode = "none"`
- `runtime_reuse_contract = "reuse_disabled"`

对应代码：

- `tasks/contest_family_spec.py:100`
- `tasks/contest_family_spec.py:221`

这意味着：

- 当前 `v2` 根本不回答 memory superiority
- `replay_reusable` 在这里被跑成“带 prior dependency 的高上下文难题”
- 而不是“真实共享记忆复用题”

所以当前 memory 轴的失败不是：

- 方法没有记忆收益

而是：

- 任务对象根本没让这条线发生

### 3.3 当前 headline pack 过度强调不确定性任务

当前 `5 x 4` 的 case 结构里：

- `10` 个是 `bounded_alternative`
- `10` 个是 `abstention_allowed`

对应代码/数据：

- `tasks/sample_tasks.py:165`
- `tasks/contest_family_spec.yaml`

这会让主 benchmark 更多地测这些东西：

- route competition collapse
- competing explanation handling
- abstain boundary
- prior rejection understanding

而不是优先测：

- structured handoff 是否减少下游解释开销
- typed packet 是否减少无谓文本编解码
- memory 是否减少重复步骤

### 3.4 当前 protocol 的慢，和任务形状是耦合的

最新 `repeat=3` artifact 里：

- `protocol llm_total_tokens < text`
- 但 `protocol task_ms > text`
- 差额主要在：
  - `planner_ms`
  - `summarize_ms`
- 不在：
  - `retrieve_ms`
  - `execute_ms`

对应 artifact：

- `runs/contest_superiority_headline_v2_api_repeat3_stageb_hotpath/benchmark_report.md:101`

这说明当前测到的主问题不是：

- typed-state I/O 太慢
- statepool 太慢

而是：

- 任务要求模型在 protocol lane 上做更多关系重建

### 3.5 当前 structured protocol 已经降 token，但还没降认知负担

当前 protocol summarizer 路径已经从旧的双层 `json.dumps` 退出，
但新的 `_render_protocol_summary_input_text()` 仍然是字段清单式 handoff。

对应代码：

- `agents/sample_agents.py:3007`

这类 handoff 的问题不是“太短”，而是：

- 信息压缩了
- 但证据竞争、路由结论、保守边界、动作理由之间的关系没有自然表达出来

这会导致：

- token 更低
- wall-time 仍更高

尤其在这些 case 上更明显：

- `ambiguous`
- `replay_reusable`
- `distractor`
- `abstention_allowed`

---

## 4. 当前任务集哪些地方应保留

当前任务集不是全部推倒重来。

以下元素仍然有价值，应尽量保留：

1. `family` 主题设计
   - `auth_rotation_chain`
   - `billing_queue_chain`
   - `checkout_release_chain`
   - `deployment_config_chain`
   - `inventory_rollout_chain`

2. `same family / same evidence universe / same scorer / same query` 的 paired comparator 思路

3. `clean / distractor / ambiguous / replay_reusable` 这四类 case 模板本身

4. `required_prior_case_ids` / `required_prior_rejections` 这类连续任务依赖合同

5. `reasoning_hops_min` / `dependency_depth` / `expected_intermediate_decisions` 这类厚度合同

需要改的不是这些基础积木，
而是：

- 哪些积木进 formal headline
- 哪些积木移到 audit
- 哪些积木单独服务 memory axis

---

## 5. 新的任务集分层设计

### 5.1 总体原则

新的任务集不按“旧对象名”拆，而按赛题问题拆。

正式分成三组：

1. `communication mainline`
2. `memory mainline`
3. `uncertainty audit`

读法固定：

- `communication mainline`
  - 回答：结构化通信相对 pure-text 是否更省 token，且 task_ms 不恶化

- `memory mainline`
  - 回答：共享记忆是否带来真实步骤/时间收益

- `uncertainty audit`
  - 回答：open planner 在复杂歧义场景下，text/protocol 的行为分叉和稳定性问题

这三组不再混写成一个 headline。

### 5.2 Communication Mainline

目标：

- 回答赛题第一轴：`通信效率`
- 辅助回答第二轴中“非文本状态被消费后的协作效率”

主读法：

- `llm_total_tokens`
- `task_ms`
- `wrong_family_rate`
- `exact_match_rate`

固定边界：

- `memory reuse` 不在本组内 claim
- `cross_lane_actual_parity` 只做 diagnostic
- `handoff_payload_bytes` 不读成 token 节省

建议 case 组成：

1. 主体保留 `clean`
2. 主体保留 `distractor`
3. 少量保留 `ambiguous`
4. `replay_reusable` 从主线迁出

推荐配比：

- `clean`: `40%`
- `distractor`: `40%`
- `ambiguous`: `20%`
- `replay_reusable`: `0%`

原因：

- `clean/distractor` 更容易暴露结构化通信和 typed handoff 的收益
- `ambiguous` 只保留最少覆盖，避免整个 headline 被 abstain-style 推理主导
- `replay_reusable` 不应继续在 memory 关闭时留在 comm headline 里

实现要求：

- 仍保留 `plan_source=llm`
- 仍保留 `text_whole_lane` vs `state_packet_minimal`
- 保持 paired comparator 公平边界不变

候选对象命名：

- `superiority_comm_v1`

### 5.3 Memory Mainline

目标：

- 回答赛题第三轴：`共享记忆复用效果`

主读法：

- `reuse_gain`
- `skipped_step_count`
- `task_ms`
- `wrong_family_rate`
- `exact_match_rate`

固定边界：

- 不允许 replay override 式预塑形成功
- 不允许“memory hit 了但没有省任何东西”也算通过
- 不允许用 `communication mainline` 代替它

建议 case 组成：

1. 保留 `replay_reusable`
2. 为每个 family 明确一条 prior -> follow-up 依赖链
3. 必要时增加第三步 follow-up，而不是只停在两步

推荐结构：

- `seed task`
  - 产生可沉淀结论/拒绝/摘要/证据标签

- `follow-up task`
  - 需要复用 seed 结论才能安全少走一步

- 可选 `third task`
  - 验证复用是否能继续累计，而不是一次性命中

关键点：

- 这组任务可以比 communication 组更“长”
- 但长的是连续性和 prior dependency
- 不是开放歧义程度

候选对象命名：

- `superiority_memory_v1`

### 5.4 Uncertainty Audit

目标：

- 保留当前 `ambiguous / replay_reusable / actual parity divergence` 的诊断价值
- 但不再阻塞 formal headline

主读法：

- `cross_lane_actual_parity`
- `decision_outcome_parity`
- planner/summarizer wall-time tail
- abstention behavior difference

建议保留 case：

- `ambiguous`
- `replay_reusable`
- 最难的 `distractor`

这组用途：

- 帮助你们找 protocol 在高不确定性任务上的短板
- 帮助解释为什么 communication headline 没闭合

但它不再承担：

- 赛题 formal superiority 主证据

---

## 6. 修改什么、修改到什么程度

### 6.1 第一阶段：docs-only 冻结

目标：

- 先把任务集分层原则冻结

允许修改：

- `docs/planning/statebus_contest_requirement_first_split_execution_plan_20260621.md`
- 新增本文件

本阶段不改：

- `tasks/*`
- `eval/*`
- `agents/*`

通过标准：

- 团队内部不再把“任务太短”和“对象错位”混成一件事
- 三组任务的职责边界写清楚

### 6.2 第二阶段：任务定义最小重构

目标：

- 把当前单一 `contest_superiority_headline_v2` 任务面拆开

允许修改文件：

- `tasks/contest_family_spec.py`
- `tasks/contest_family_spec.yaml`
- 必要时 `tasks/sample_tasks.py`

修改程度：

1. 新增 communication mainline 生成入口
2. 新增 memory mainline 生成入口
3. 保留 uncertainty audit 入口，必要时可沿用现有 `v2` 做过渡
4. 不在这一阶段碰 open / external

不该做的事：

- 不先重写大规模 corpus
- 不先扩 family 数量
- 不先做更开放的外部 baseline

### 6.3 第三阶段：runner 读法收口

目标：

- 让不同任务组被正确读取

允许修改文件：

- `eval/runner.py`

修改程度：

1. `superiority_comm_v1`
   - 主读 `llm_total_tokens / task_ms / quality floor`

2. `superiority_memory_v1`
   - 主读 `reuse_gain / skipped_step_count / task_ms / quality floor`

3. `uncertainty audit`
   - 只读 diagnostic，不进 headline blocker

不该做的事：

- 不在这一步重新打开旧 headline 抢救
- 不在这一步把 audit surface 升格为 headline

### 6.4 第四阶段：验证梯度

固定顺序：

1. `pytest -q`
2. `python -m runtime.smoke`
3. `API repeat=1`
4. `API repeat=3`
5. `API repeat=10`

限制：

- `communication mainline` 未通过 `repeat=3` 前，不进 `repeat=10`
- `memory mainline` 未形成前，不允许继续说“整体 superiority”

---

## 7. 参考哪些文档

### 7.1 必须参考

1. `docs/reference/题目.md`
   - 唯一赛题需求来源

2. `docs/planning/statebus_contest_requirement_first_split_execution_plan_20260621.md`
   - 当前主执行合同

3. `docs/planning/statebus_contest_superiority_gate_contract_20260621.md`
   - 四行判题表与读法边界

4. `runs/contest_superiority_headline_v2_api_repeat3_stageb_hotpath/benchmark_report.md`
   - 当前 communication scaffold 的最新反例和正信号

### 7.2 作为历史 guardrail 参考

1. `docs/planning/statebus_superiority_headline_execution_plan_20260621.md`
   - 用来保留“为什么旧 headline 不能继续当整体 superiority”的背景
   - 不再作为当前唯一执行合同

2. `README.md`
   - 用来保持对外口径一致

---

## 8. 什么时候合并、合并到什么程度

你的问题里特别提到：

- 是否把内容合并回 `docs/planning/statebus_superiority_headline_execution_plan_20260621.md`

我的建议是：

### 8.1 现在不要把本文件整体并回旧 execution plan

原因：

`statebus_superiority_headline_execution_plan_20260621.md`
现在主要价值是历史转向记录：

- 为什么退出 `contest_honest_headline_v1`
- 为什么要建立 superiority 主对象
- 为什么先冻结 gate contract

如果把这份新的任务集对齐设计整体塞回去，会把两个层面重新混在一起：

1. `旧 headline 退出逻辑`
2. `新任务集如何按赛题重构`

这会让旧文档再次承担“当前唯一执行合同”的角色，不利于阅读。

### 8.2 现在应该怎么处理

当前建议：

1. 旧 execution plan 保留为历史设计起点
2. 当前主执行合同仍是：
   - `statebus_contest_requirement_first_split_execution_plan_20260621.md`
3. 本文作为：
   - `任务集与赛题需求对齐设计附录`

### 8.3 何时合并回旧 execution plan

只有在以下条件满足时，才建议把本文件的部分内容折叠回旧 execution plan：

1. `communication mainline` 与 `memory mainline` 的对象名、入口名、读法已经冻结
2. `tasks/*` 的最小重构已经落地
3. `runner` 的读法已经和任务分层一致
4. 当前主合同不再频繁变化

### 8.4 合并到什么程度

届时只建议合并两类内容，不要全文并回：

1. 合并回旧 execution plan 的“最终版对象分层摘要”
   - `communication mainline`
   - `memory mainline`
   - `uncertainty audit`

2. 合并回旧 execution plan 的“任务设计 stopline”
   - 不再让 memory 关闭的 `replay_reusable` 进入 communication headline
   - 不再让 uncertainty audit 直接承担 formal superiority

不建议合并回去的内容：

- 本文的完整问题分析
- 当前 `repeat=3` 的阶段性详细诊断
- 过多的实现阶段门细节

这些更适合留在当前主合同和附录文档里。

---

## 9. 推荐的文档组织方式

当前建议保留三层：

1. `docs/planning/statebus_superiority_headline_execution_plan_20260621.md`
   - 历史转向与旧 headline 退出理由

2. `docs/planning/statebus_contest_requirement_first_split_execution_plan_20260621.md`
   - 当前主执行合同

3. `docs/planning/statebus_taskset_requirement_alignment_design_20260621.md`
   - 任务集重构与赛题对齐设计

这种组织方式比“把一切都并回一个 execution plan”更清晰。

---

## 10. 一句话执行建议

下一步不要先争论“任务是不是太短”，也不要先继续只修 prompt。

下一步应先：

> 冻结任务集分层设计，
> 把当前单一 `contest_superiority_headline_v2`
> 拆成
> `communication mainline`
> `memory mainline`
> `uncertainty audit`，
> 然后再分别实现和验证。

这才是从赛题要求出发、又能更清晰体现 `StateBus` 方法价值的路线。
