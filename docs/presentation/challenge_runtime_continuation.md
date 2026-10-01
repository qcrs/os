# 技术难点二：计划写出来以后，怎样把任务继续跑下去

这一页讨论多步骤任务的运行时组织。它要说明 Planner 的计划怎样进入真正的执行过程，以及某个步骤出现变化时，Runtime 怎样保留已经完成的工作并继续安排后面的步骤。

## 这一页要回答的具体问题

建议把问题写成：

> **Planner 提出了一个方案，谁来把它变成真正能执行、能继续推进的任务？**

Planner 可以根据任务目标提出 Retriever、Executor 和 Summarizer 的步骤，但 Planner 的输出还不是运行时可以直接调用的命令。Runtime 还需要知道：由哪个角色执行、使用什么能力、依赖哪些输入、交付什么结果，以及下一步什么时候可以开始。

如果某一步失败，系统还要回答一个更实际的问题：已经完成的步骤是否保留？后面的步骤是否要全部重新执行？能不能在预算范围内换一条已经登记的执行路径？

## 为什么值得作为技术难点

这页解决的是多 Agent 系统能否完成“复杂任务”的问题。赛题要求至少三个 Agent、至少三类角色和一个多步骤任务。若 Planner 只是生成一段计划文本，Agent 各自运行一次，评委仍然看不到 Runtime 怎样把它们组成一项工作。

难点来自两种要求同时存在：

- Planner 需要有一定灵活性，能够根据任务提出步骤和依赖；
- 执行过程需要明确的能力、输入、输出和预算，后续角色不能凭猜测接收结果。

还要处理执行中的变化：能力调用可能失败，输入覆盖可能不足，某个候选执行路径可能需要换成已登记的 fallback。整条任务重新开始会重复已经完成的检索和状态准备，直接跳过又可能让下游拿不到合同规定的输入。

因此，这页的重点不是展示“失败处理很安全”，而是说明 Runtime 如何让一项工作在多个步骤之间保持连续。

## StateBus 怎样处理

StateBus 将 Planner 的建议和 Runtime 的执行计划分成两个对象：

```text
PlanProposal
    ↓ PlanPolicy + CapabilityRegistry
ApprovedPlan
    ↓ 每个 step 建立 attempt 和 CapabilityGrant
执行结果
    ↓ 结果接纳、状态更新和后续调度
下一步或有限调整
```

### PlanProposal：Planner 提出的步骤

每个计划步骤至少要表达：

```text
step_id
role
capability_id
goal
depends_on
input_ref_ids / input_ref_kinds
output_contract_version
completion_criteria
on_failure
```

这些字段描述了 Planner 想做什么和步骤之间的关系，但它们还要与当前任务允许的能力和输入对象对应起来。

### ApprovedPlan：Runtime 可以执行的计划

`PlanPolicyValidator` 根据当前 `AdaptiveTaskEnvelope` 和 `CapabilityRegistry` 检查计划：

- 步骤数量和角色数量是否满足任务合同；
- `capability_id` 是否已经登记，且 owner role 对应；
- 输入 Ref 类型能否满足能力要求；
- 依赖关系是否形成合法 DAG；
- 输出合同是否是当前任务允许的合同；
- 步骤数量和总 attempt 预算是否满足当前任务合同；Runtime 还会按任务 envelope 单独限制重规划次数。

检查通过后，Runtime 产生 `ApprovedPlan`。它记录计划策略报告、能力注册表摘要和总 attempt 预算。这样，后续 Worker 收到的不是 Planner 的原始文字，而是当前 Runtime 可以调度的步骤。

### attempt：每次实际执行的记录

同一个逻辑步骤可能因为重试或 fallback 产生多次执行。StateBus 用 `step_id` 表示计划中的逻辑步骤，用 `attempt_id` 表示这一次具体执行。

每次 attempt 都会绑定：

- 当前步骤和角色；
- 输入 Ref 和输入合同；
- `CapabilityGrant`；
- 独立的工作目录和执行记录；
- 结果、错误或超时状态。

这样，某次执行的晚到结果不会覆盖新的 attempt，已经结算的步骤也不会被重复接收。

### 失败或变化：只处理后面的部分

如果一个步骤失败，Runtime 可以根据步骤的 `on_failure` 和能力描述选择有限的处理方式：

- 重新尝试同一个步骤；
- 选择能力注册表中声明的确定性 fallback；
- 请求一次有限的 replan，只替换尚未执行的子图；
- 在达不到输出合同的情况下结束任务。

这里要讲清楚一个实现边界：当前实现支持有预算的 replan 和 fallback，不能说成“模型可以无限改变整个流程”。`AdaptiveTaskEnvelope` 对 `max_replans`、`max_retrieval_expansions` 和 `max_total_attempts` 都有约束。

## 一页 PPT 的中心画法

页面不需要再放完整 Runtime 架构。建议画同一个任务在三个阶段的状态。

### 左侧：Planner 的计划建议

```text
PlanProposal
────────────────────
1. retrieve_evidence
2. extract_metric
3. compose_report
```

旁边标注：

```text
Planner 提出步骤和依赖
```

不要把这块画成已经可以直接运行的命令。

### 中间：Runtime 形成可执行步骤

从第二步抽出一张 `Approved step` 卡片：

```text
Approved step
────────────────────────
role: Executor
capability: extract_metric_series_v1
input: canonical_evidence_pack
output: metric_series.v1
depends_on: retrieve_evidence
attempt: A-02
```

这张卡片回答四个问题：谁执行、用什么能力、拿什么输入、产出什么结果。它比展示完整 `ApprovedPlan` 字段更容易让评委看懂 Runtime 的工作。

### 右侧：任务变化后怎样继续

```text
retrieve_evidence ✓
        ↓
extract_metric ✗
        ↓
保留已完成的 retrieve
替换未执行的后续分支
        ↓
fallback-extract → compose_report
```

旁边放一句：

> 已经完成的结果继续作为输入，调整范围限制在还没有执行的步骤。

页面主线由“计划建议 → 可执行步骤 → 继续推进”组成。失败只是为了说明为什么需要这套组织方式，不能占据页面大部分。

## 评委应当看到的重点

### 重点一：Planner 和 Runtime 分工清楚

Planner 负责提出任务步骤和目标，Runtime 负责把它们和实际能力、输入对象、输出合同接起来。这样可以解释为什么系统不是“让一个模型把所有 Agent 叫一遍”。

### 重点二：结果有明确的后续位置

步骤完成后，Runtime 不是只收一段返回文本，而是接收带有输出 Ref 和合同的结果。后续步骤根据依赖和输入要求取得这个结果。

### 重点三：变化不会让整条任务回到起点

当某一步失败或需要调整时，已完成的上游结果保留，新的 attempt 或后续计划继续使用它们。这个性质直接体现了 Runtime 对多步骤协作的组织作用。

## 不要在这页展开的内容

以下内容可以作为讲解时的追问材料，但不应成为主图：

- Protobuf、UDS 和消息帧格式；它们属于结构化协议页；
- DSL 的具体操作或 CodeAct 的 Python 生成；它们属于执行页；
- Logit 的概率阈值和 retry；它属于模型侧选择性取证；
- StateRef 的 shared memory 生命周期；它属于非文本状态页；
- GC、lease 和权限检查的完整字段；它们无法帮助评委先理解任务怎样继续。

页面可以用一句小字说明执行路径来自已登记能力：

```text
能力决定可用的执行方式；Runtime 决定当前步骤怎样接入任务。
```

## 和前后两页的边界

第一页讲角色拿到什么。第二页从角色已经拿到输入开始，讲任务怎样从一个步骤进入下一个步骤。

第三页讲历史工作怎样进入下一轮。第二页只讨论本轮任务内的步骤和 attempt，Memory 复用策略不在这里展开。

Embedding 和 Logit 可以在某个步骤中提供选择依据，但它们不构成这页的主线。第二页要说明的是 Runtime 如何消费步骤结果并安排后续，不是某一种状态如何计算。

## 源码和实验依据

可引用的实现位置包括：

- `src/statebus/contracts/adaptive.py`：`PlanProposal`、`ApprovedPlan`、`AdaptiveTaskEnvelope` 和 `PlanStepProposal`；
- `src/statebus/runtime/plan_policy.py`：计划检查和批准；
- `src/statebus/runtime/capability_registry.py`：能力登记与能力描述；
- `src/statebus/runtime/adaptive_runtime.py`：attempt、结果接纳、fallback 和 replan；
- `src/statebus/runtime/driver.py`：多步骤运行和状态推进；
- `tests/integration/runtime/test_adaptive_driver.py` 中的 `test_driver_replan_changes_only_unexecuted_subgraph`：`retrieve` 完成后，`extract` 失败，Runtime 改走 `fallback-extract`，随后继续 `report`。

实验和测试要分开表述：

- mainline 的 `48/48` 通过用于证明多角色、多步骤主流程可以完整运行；
- replan 集成测试用于证明已执行步骤保留、未执行子图替换；
- 两者不能合并成“48 个任务都发生了动态重规划”。

## 评委最后应该记住什么

建议讲解收束为：

> Planner 提出方案，Runtime 把它变成有输入、有能力、有输出合同的执行步骤。某一步发生变化时，已经完成的工作继续保留，后面的任务沿着新的步骤接着走。

这句话说明了 StateBus 作为 Runtime 的价值，也把前一页的角色输入和后一页的跨任务 Memory 接起来。
