# StateBus v2 受限自适应 Agent Runtime 设计与实施计划

> 状态：设计基线，尚未实现
>
> 日期：2026-07-16
>
> 适用范围：当前 `v2` 主路径及 `tests/v2`
>
> 实施原则：保留现有严格路径；第一阶段增强 Agent 决策与协作，但不执行 LLM 生成的 Python；第二阶段才引入受限 LLM CodeAct。

> 本文不是完成度审计，也不改写既有实验结论。文中“目标”“应新增”“计划修改”均表示待实现能力。

## 1. 为什么需要这次增强

当前 StateBus v2 已经具备类型化控制消息、`CanonicalTaskSpec`、证据包、状态引用、工作区、`ExecutionArtifactRef`、记忆和回放门等系统基础。问题不在于系统完全没有多 Agent 路径，而在于四个 LLM 角色对任务结构和执行结果的因果影响偏弱。

当前正式路径的实际顺序是：

```text
run_smoke()
  -> TaskCompiler 严格校验预编译 CanonicalTaskSpec
  -> Planner LLM 生成受限检索语义
  -> 程序 RetrieverFanoutPipeline 完成真实数据读取和检索
  -> 程序生成 route/tool 候选闭集
  -> Retriever LLM 从候选闭集中选择一项
  -> Executor LLM 在同一候选闭集中复核一项
  -> CodeActRunner 执行运行时生成的固定 Python 包装脚本
  -> codeact_data_tasks.py 按 task_family + intent_op 进入预置分支
  -> Summarizer LLM 为已生成结果撰写摘要
  -> RuntimeDriver 接收前面已经生成的检索、执行和总结结果
  -> Driver 记录生命周期、控制消息、验证、记忆和回放账本
```

源码依据：

- `v2/runtime/smoke.py::run_smoke()` 在调用 `RuntimeDriver` 前已完成 Planner、检索、Retriever/Executor 决策、CodeAct 和 Summarizer。
- `v2/runtime/driver.py::RuntimeDriverInput` 接收的已经是 `RetrievalBundle`、`output_payload`、`CodeActPlan`、验证结果和记忆结果，见 `v2/runtime/driver.py:100-159`。
- `v2/runtime/driver.py::build_default_workflow()` 固定生成 Planner -> Retriever -> Executor -> Summarizer，见 `v2/runtime/driver.py:207-241`。
- Planner Prompt 明确禁止输出 workflow、DAG、route、tool 和 code，见 `v2/runtime/role_path.py:998-1008`。
- Retriever 与 Executor 只能从可见 `tc` 候选中选择，见 `v2/runtime/role_path.py:1010-1040、1350-1642`。
- 当前主路径向两者传 `strict_surface=True` 和 `allow_assisted_correction=False`，见 `v2/runtime/smoke.py:2411-2462`。
- `CodeActRunner.build_plan()` 构造固定的 materialize/validate/write stages，见 `v2/runtime/codeact.py:428-513`。
- 真正的数据处理按 `task_family + intent_op` 进入预置 Python 分支，见 `v2/runtime/codeact_data_tasks.py:772-815`。

这带来四个具体问题：

1. Planner 名义上负责规划，实际只影响检索 query 和少量语义字段，不能提出任务步骤或依赖。
2. Retriever LLM 不负责构造检索任务；真实检索在它被调用前已经完成，它主要选择程序准备好的 route/tool。
3. Executor LLM 不生成执行配方，也不执行工具；它主要复核 Retriever 的闭集选择。
4. Runtime Driver 名义上是控制中心，但当前主路径的主要语义工作发生在 Driver 之前；Driver 更接近生命周期记录、执行边界和提交控制器。

因此，这次增强的目标不是把系统改造成无限制自治 Agent，而是让 LLM 对以下内容产生真实、可追溯、可拒绝的影响：

- 任务应拆成哪些有限步骤；
- 每一步需要什么证据和能力；
- 证据不够时是否进行一次补检索；
- Executor 如何组合已注册的数据变换；
- Summarizer 是否发现缺失引用或事实冲突；
- 记忆和非文本状态具体影响了哪一个后续决策。

### 本章结论

当前问题是 Agent 的决策面过窄，而不是控制和校验过多。应放宽“模型可以提出什么”，继续严格限制“模型的输出可以直接造成什么副作用”。

## 2. 本次架构决定

本计划作出以下明确决定，后续实现不再围绕这些问题反复摇摆。

### 2.1 Planner 是语义主 Agent，不是 Runtime 调度器

Planner 可以：

- 提出 2 至 6 个步骤；
- 为步骤选择已注册 capability；
- 声明依赖、输入 Ref 类型、输出合同和完成条件；
- 提出一次条件化补检索或局部重规划；
- 建议使用兼容记忆或确定性执行能力。

Planner 不可以：

- 直接向其他 Agent 建立连接或发送执行命令；
- 注册新工具、安装依赖或修改 capability registry；
- 传入任意文件路径、网络地址、shell 命令或 Python 代码；
- 修改任务的顶层输出合同和安全策略；
- 决定绕过 validator、replay gate、workspace 或 ledger；
- 无限新增步骤或重试。

Planner 输出的是 `PlanProposal`，不是 `ApprovedPlan`。只有程序 `PlanPolicyValidator` 可以把提案转成获批计划，只有 Runtime Driver/Supervisor 可以调度步骤。

### 2.2 保留现有严格路径，新增独立工作流模式

不得直接修改现有 `benchmark_strict` 的语义。新增运行时工作流模式：

| 模式 | 含义 | 是否影响现有实验 |
| --- | --- | --- |
| `strict_fixed` | 当前固定四步路径 | 保持原样，继续作为回归和正式比较基线 |
| `adaptive_shadow` | LLM 生成计划并校验，但实际仍执行固定路径 | 只记录计划质量，不改变结果 |
| `adaptive_bounded` | 执行获批的有限 DAG，允许一次补检索或局部重规划 | 新实验路径，不能与历史 strict 指标混写 |

工作流模式不应复用 `TaskMode`。`TaskMode` 当前表示 `benchmark_strict` 或 `interactive`，见 `v2/contracts/models.py:19-27`；新增 `WorkflowMode` 可以避免把“任务编译方式”和“运行时调度方式”混成一个概念。

第一阶段仍要求程序产生合法 `CanonicalTaskSpec`，不让 Planner 直接替代 Compiler。为了避免 adaptive 任务继续被一个极细的 `intent_op` 提前决定全部执行路径，可以在既有 task family 中新增少量宽领域 intent，例如 `analyze_document`、`analyze_table`。它们只表达任务类别和最终输出，不映射到唯一 route/tool；具体步骤由 Planner 在对应 domain pack 的 capability 闭包内提出。原有精确 intent 和 allowlist 全部保留给 strict 路径。

### 2.3 第一阶段不执行 LLM 生成的 Python

第一阶段 Executor 只能：

- 选择已注册的确定性 capability；
- 生成受限 `TransformProgram`，即声明式数据变换 DSL；
- 在工作区内运行由程序实现的 DSL 解释器；
- 产生候选 `ExecutionArtifactRef`，经过 schema 和质量校验后才能变为 verified。

现有确定性 `CodeActRunner` 保留为兼容和 fallback。LLM 生成 Python 放到第二阶段，且只有强沙箱可用时才允许执行。

### 2.4 Verifier 首先是程序职责，不新增第五个自由 LLM Agent

第一阶段新增以下程序校验器：

- `PlanPolicyValidator`：校验计划权限、DAG、合同和预算；
- `EvidenceCoverageVerifier`：检查证据类型、locator、实体、时间范围和冲突；
- `TransformProgramValidator`：检查 DSL 操作、列、类型和复杂度；
- 现有 artifact/input/quality validators：继续验证工件和最终质量。

只有程序规则无法判断的语义冲突，才可在后续增加受限 LLM verifier。这样避免为了“多一个 Agent”增加一次成本高、难复现的模型调用。

### 2.5 角色之间仍不直接互调

角色通过 Runtime 中介协作：

```text
Agent 输出候选合同或状态
  -> Driver 接收
  -> 程序校验
  -> Session/Ledger 持久化决定
  -> Supervisor 调度获批的下一步骤
  -> 下游 Agent 通过 Ref 和裁剪后的 Prompt 获取输入
```

这仍属于多 Agent 协作。赛题要求结构化协作和系统层机制，并未要求角色建立对等网络。集中调度可以保留权限、审计、预算、回放和公平实验边界。

### 本章结论

目标架构是“Planner 负责语义计划，Controller 负责审批和调度，角色负责受限执行，Validator 负责验收”。Planner 可以成为逻辑上的主 Agent，但不能成为绕过控制面的系统进程主控。

## 3. 需求与非目标

### 3.1 第一阶段功能需求

| 编号 | 需求 | 验收要点 |
| --- | --- | --- |
| FR-01 | Planner 可生成 2 至 6 步的结构化计划 | 计划包含角色、capability、依赖、输入、输出和完成条件 |
| FR-02 | 程序可以拒绝、修正或批准计划 | 非法能力、环、越权 Ref、超预算必须 fail closed |
| FR-03 | Driver 按获批依赖图调度 | 只调度依赖已完成的 ready step |
| FR-04 | Retriever 在程序检索前生成 `EvidenceRequest` | query、证据类型、实体和时间范围实际进入 Pipeline |
| FR-05 | 检索后产生结构化 coverage 与 gap | 可以触发一次补检索，不依赖 Retriever 自报 confidence |
| FR-06 | Executor 生成并运行受限 DSL | DSL 只能组合注册操作，不能执行任意表达式 |
| FR-07 | Summarizer 生成带证据 ID 的 ClaimSet | 无 locator/verified artifact 支持的事实不得提交 |
| FR-08 | Agent 可返回有限状态而不只是成功文本 | 支持不足证据、冲突、缺输入、验证失败、缺引用 |
| FR-09 | 状态和记忆的消费产生独立记录 | 能追踪 Ref、消费者、读取字段、决定和下游影响 |
| FR-10 | 保留 strict、shadow、adaptive 三种模式 | strict 回归不受 adaptive 代码影响 |

### 3.2 第二阶段功能需求

| 编号 | 需求 | 验收要点 |
| --- | --- | --- |
| FR2-01 | LLM 可为获批 capability 生成完整 Python 文件 | 不是片段，不允许自由工具调用 |
| FR2-02 | 代码经过提取、语法、AST、路径和依赖策略检查 | 任一检查失败不得执行 |
| FR2-03 | 只在强沙箱中执行 | `bwrap` 不可用或失败时 fail closed，退回 DSL/确定性能力 |
| FR2-04 | 输出必须通过现有工件和质量合同 | 代码成功退出不等于任务成功 |
| FR2-05 | 最多一次代码修复 | 修复失败进入确定性 fallback，不无限循环 |
| FR2-06 | 代码、策略、执行和验证均可审计 | 保存 source hash、policy report、sandbox backend 和 artifact hash |

### 3.3 非功能需求

- 可复现：所有模型提案、程序归一化、批准结果和调度结果有稳定 hash。
- 低开销：控制消息只传小型字段或 Ref；计划、证据和工件大对象存放在工作区/CAS/状态后端。
- 可回退：任意 adaptive 失败可以回到已知确定性能力，不能让任务悬空。
- 可测试：核心校验器必须使用确定性 stub 测试，不依赖在线模型。
- 可观测：区分模型提案、程序修正、实际消费和最终效果。
- 向后兼容：现有 `CanonicalTaskSpec`、`ExecutionArtifactRef`、memory/replay 和 strict benchmark 不被隐式改义。
- 安全：Prompt 限制不是权限边界；真正边界必须由 schema、policy、workspace 和 sandbox 强制。

### 3.4 明确非目标

第一阶段不实现：

- 任意自然语言自动发现和安装工具；
- Agent 之间的自由聊天、广播、投票或竞争性黑板；
- Planner 直接调用 shell、网络或 Python；
- 任意网页、外部 API 和宿主机文件访问；
- 通用软件工程 Agent 或长时间自主代码迭代；
- 把 embedding、StateRef 或引擎 prefix cache 描述为 Agent 间 KV/隐藏状态迁移；
- 用 adaptive 实验覆盖或改写既有 strict 实验结论。

### 本章结论

第一阶段要证明的是“模型可以在已注册能力闭包内改变任务图、检索目标和执行配方”，不是证明模型可以处理任意世界任务。

## 4. 目标架构与控制权

### 4.1 总体结构

```text
                         只提供候选语义决定
                 +----------------------------------+
                 |                                  |
                 v                                  |
用户请求 -> TaskCompiler -> AdaptiveTaskEnvelope -> Planner LLM
                              |                       |
                              | capability surface    v
                              +------------------ PlanProposal
                                                       |
                                                       v
                                            PlanPolicyValidator
                                              | reject/repair
                                              | approve
                                              v
                                             ApprovedPlanRef
                                                       |
                                                       v
                       +---------------- Runtime Driver/Supervisor ----------------+
                       |                     调度权                                  |
                       |                                                            |
                       +-> Retriever Step -> EvidenceRequest -> Retrieval Pipeline  |
                       |                         |                                  |
                       |                         v                                  |
                       |               EvidencePack + Coverage                     |
                       |                         | gap                              |
                       |                         +----> bounded replan -------------+
                       |                                                            |
                       +-> Executor Step -> TransformProgram -> DSL Runtime          |
                       |                                      |                     |
                       |                                      v                     |
                       |                              Candidate Artifact             |
                       |                                      |                     |
                       |                                      v                     |
                       |                               Artifact Validator            |
                       |                                                            |
                       +-> Summarizer Step -> ClaimSet -> Claim Validator -> Report  |
                       |                                                            |
                       +-> Session / Ledger / Telemetry / StateConsumptionRecord <---+
```

图中控制权只属于 Driver/Supervisor。LLM 输出均为候选，不直接产生进程、网络、文件或调度副作用。

### 4.2 为什么要把 adaptive 调度移入 Driver

当前 `run_smoke()` 在调用 `RuntimeDriver.run()` 前已完成主要语义和执行工作。若只让 Planner 多输出几个步骤，但仍由 `run_smoke()` 按固定顺序执行，那么“动态计划”只是文档字段，控制权并未变化。

目标实现固定采用 `RuntimeDriver.run_adaptive()`：保留现有 `run()` 作为 strict 入口，在同一个控制中心增加 adaptive 入口；计划解析、ready queue 和角色 adapter 等复杂逻辑下沉到 `v2/runtime/adaptive_runtime.py`，避免继续扩大 `driver.py` 的内部复杂度。

1. 接收尚未执行的 `AdaptiveRuntimeRequest`，而不是已经完成的 `RetrievalBundle` 和 `output_payload`。
2. Driver 调用 Planner，校验提案并持久化 `ApprovedPlanRef`。
3. Driver 根据依赖寻找 ready steps。
4. Driver 调用对应 role adapter 和 capability executor。
5. Driver 在每步后更新 Supervisor、Session、Ledger 和 telemetry。
6. Driver 完成 artifact、memory、replay 和最终提交。

`run_smoke()` 在 adaptive 模式中只负责：

- 构造依赖服务；
- 编译或接收 `CanonicalTaskSpec`；
- 创建 workspace/runtime roots；
- 调用 `run_adaptive()`；
- 汇总返回值供 benchmark 使用。

现有 `RuntimeDriver.run(RuntimeDriverInput)` 保持不变，继续服务 strict 路径。

### 4.3 三层授权

每一步必须同时满足三层授权：

| 层 | 对象 | 负责回答 |
| --- | --- | --- |
| 任务层 | `AdaptiveTaskEnvelope` | 本任务允许哪些能力、预算和输出 |
| 计划层 | `ApprovedPlan` | 本轮具体批准哪些步骤和依赖 |
| 执行层 | `CapabilityGrant` | 某次 attempt 可读取哪些 Ref、写什么输出、运行多久 |

即使 Planner 在计划中选择了合法 capability，Executor 也必须拿到该 attempt 的 `CapabilityGrant` 才能运行。Grant 应包含 `task_id`、`step_id`、`attempt_id`、`capability_id`、输入 Ref allowlist、输出合同、workspace root ID、超时和过期时间，并产生稳定 hash。

控制面只传小型合同或 Ref。建议为 Protobuf 增加以下 typed body，而不是把完整计划 JSON 放入 `runtime_reuse_contract` 等字符串字段：

| 消息 | 关键字段 | 发送者 -> 接收者 |
| --- | --- | --- |
| `PlanRequest` | header、task_spec_ref、capability_surface_ref、budget_ref | Driver -> Planner adapter |
| `PlanResult` | header、plan_proposal_ref、model_usage_ref | Planner adapter -> Driver |
| `StepRequest` | header、approved_plan_ref、capability_grant_ref、input_refs | Driver -> 角色 worker |
| `StepResult` | header、step_status、output_refs、validator_report_refs、error_code | 角色 worker -> Driver |
| `ReplanRequest` | header、approved_plan_ref、failed_step_ref、remaining_budget_ref | Driver -> Planner adapter |

较大的 `PlanProposal`、`ApprovedPlan`、`CapabilitySurface`、EvidencePack 和 validator report 先写工作区/CAS，再在消息中传 `RefHandle`。UDS 消息负责生命周期和定位，不负责搬运大文本。

### 本章结论

要让计划真正生效，不能只改 Prompt。adaptive 模式必须把“计划批准、ready-step 选择和角色调度”移入 Runtime 控制中心，同时保留 strict Driver 的兼容入口。

## 5. 新增合同设计

建议新增 `v2/contracts/adaptive.py`，将以下合同与现有 `CanonicalTaskSpec` 分开，避免修改现有 spec hash 和 replay key。

### 5.1 `WorkflowMode`

```python
class WorkflowMode(StrEnum):
    STRICT_FIXED = "strict_fixed"
    ADAPTIVE_SHADOW = "adaptive_shadow"
    ADAPTIVE_BOUNDED = "adaptive_bounded"
```

### 5.2 `AdaptiveTaskEnvelope`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `task_id` | `str` | 当前任务 |
| `canonical_task_spec_hash` | `str` | 绑定已有任务规格 |
| `workflow_mode` | `WorkflowMode` | strict/shadow/adaptive |
| `domain_pack_id` | `str` | 能力域，例如 `long_doc_analysis_v1` |
| `allowed_capability_ids` | `tuple[str, ...]` | 本任务能力闭集 |
| `allowed_output_contracts` | `tuple[str, ...]` | 可交付合同闭集 |
| `max_plan_steps` | `int` | 默认 6 |
| `max_replans` | `int` | 默认 1 |
| `max_retrieval_expansions` | `int` | 默认 1 |
| `max_total_attempts` | `int` | 全任务硬预算 |
| `risk_class` | enum | `read_only`、`workspace_write`、`bounded_code` |
| `policy_version` | `str` | 计划校验版本 |

这个对象由程序根据 `CanonicalTaskSpec` 和人工配置生成，不由 Planner 修改。

### 5.3 `CapabilityDescriptor`

现有 `RouteToolProfile` 只有 route、tool、关键词和偏好，见 `v2/route_tool_catalog.py:59-77`。adaptive 模式需要更完整的能力合同：

| 字段 | 含义 |
| --- | --- |
| `capability_id` | 稳定能力 ID |
| `owner_role` | Planner/Retriever/Executor/Summarizer 中谁可执行 |
| `description` | 给 Planner 的短能力说明，不含实现细节和敏感路径 |
| `input_ref_kinds` | 接受的 Ref 类型 |
| `input_contract_version` | 输入 schema |
| `output_ref_kinds` | 可能产生的 Ref 类型 |
| `output_contract_version` | 输出 schema |
| `execution_kind` | `runtime_builtin`、`retrieval_adapter`、`transform_dsl`、`llm_python` |
| `side_effect_class` | `read_only`、`workspace_write`、`isolated_code` |
| `max_runtime_ms` | 单步时间预算 |
| `supports_replay` | 是否可进入 replay gate |
| `validator_ids` | 执行后必须通过的 validator |
| `fallback_capability_id` | 失败时允许的确定性 fallback |

第一阶段 `execution_kind=llm_python` 一律不可授权。第二阶段再按 sandbox readiness 开启。

### 5.4 `PlanStepProposal`

```json
{
  "step_id": "retrieve-risk-evidence",
  "role": "retriever",
  "capability_id": "retrieve_semantic_evidence_v1",
  "goal": "找到报告中支持主要经营风险的段落和引用",
  "depends_on": [],
  "input_ref_ids": ["state:query-embedding"],
  "output_contract_version": "statebus.evidence_pack.v2",
  "completion_criteria": {
    "required_evidence_types": ["semantic_context", "citation"],
    "min_locator_count": 2
  },
  "on_failure": "request_replan"
}
```

禁止自由条件表达式。`completion_criteria` 只能使用已注册的键和标量值；`on_failure` 必须来自 enum。

### 5.5 `PlanProposal` 与 `ApprovedPlan`

`PlanProposal` 保存模型原始语义：

- `proposal_id`；
- `task_id`；
- `steps`；
- `final_output_contract_version`；
- `requested_memory_policy`；
- `planner_notes`，只用于审计，不参与执行；
- `model_id`、token、latency 和 `raw_output_hash`；
- `schema_version`。

`ApprovedPlan` 保存程序决定：

- 归一化后的 steps；
- 被删除、替换或补全的字段；
- `plan_policy_report_hash`；
- 最终 step order；
- capability registry digest；
- 总预算；
- `approved_plan_hash`。

不得用同一个对象同时表示模型提案和程序批准，否则审计时无法回答“这个字段是谁决定的”。

### 5.6 `PlanPolicyReport`

建议结果状态：

- `APPROVED`：原提案无需语义修改；
- `NORMALIZED`：只做 ID、顺序、缺省值等安全归一化；
- `REPAIR_REQUIRED`：存在模型可修复问题，可重试一次；
- `REJECTED`：越权、无效 DAG、未知能力或超预算；
- `FALLBACK_FIXED_PLAN`：修复失败，使用确定性计划。

报告必须逐条保存：`error_code`、`step_id`、`field_path`、`proposed_value_hash` 和 `resolution`。不得把原始敏感内容复制进日志。

### 5.7 Retriever 合同

`EvidenceRequest`：

- `request_id`、`task_id`、`step_id`；
- `queries`，最多 3 个；
- `evidence_types`；
- `target_entities`；
- `time_scope`；
- `corpus_scope_ids`；
- `memory_policy`；
- `max_candidates`、`max_prompt_visible_bytes`；
- `required_locator`；
- `source_plan_step_id`。

`EvidenceCoverageResult`：

- `status`：`COMPLETE`、`INSUFFICIENT_EVIDENCE`、`CONFLICTING_EVIDENCE`；
- `covered_evidence_types`；
- `missing_evidence_types`；
- `entity_coverage`、`time_scope_coverage`；
- `locator_count`；
- `conflict_item_ids`；
- `consumed_state_ref_ids`；
- `evidence_pack_hash`；
- `coverage_policy_version`。

coverage 由程序根据 EvidencePack 和计划完成条件计算，不直接相信 LLM 自报 confidence。

### 5.8 Executor DSL 合同

第一阶段新增 `TransformProgram`：

```json
{
  "program_id": "program-task-17-step-3",
  "input_artifact_refs": ["artifact:table-evidence-17"],
  "operations": [
    {"op": "select", "columns": ["quarter", "revenue_musd"]},
    {"op": "filter_in", "column": "quarter", "values": ["2026Q1", "2026Q4"]},
    {"op": "sort", "columns": ["quarter"]},
    {"op": "pct_change", "column": "revenue_musd", "output": "growth_pct"}
  ],
  "output_contract_version": "statebus.metric_series.v1"
}
```

第一批允许操作建议限制为：

- `select`；
- `rename`；
- `filter_eq`、`filter_in`、`filter_range`；
- `sort`；
- `group_by`；
- `aggregate`，仅 `count/sum/mean/min/max`；
- `join`，仅已授权输入 Ref；
- `difference`、`ratio`、`pct_change`；
- `iqr_outlier`；
- `project_claim_fields`。

禁止：

- 任意表达式字符串；
- Python `eval` 或动态函数名；
- 任意文件路径；
- 任意 module/import；
- 网络、shell、子进程；
- 无上限 join、循环或递归。

DSL interpreter 根据 `CapabilityGrant` 解析已物化的输入，而不是接受模型提供的路径。

### 5.9 Summarizer 合同

`ClaimSet` 中每条 claim 必须包含：

- `claim_id`；
- `claim_text`；
- `claim_type`：fact/inference/risk/recommendation；
- `supporting_evidence_item_ids`；
- `supporting_artifact_ref_ids`；
- `citation_locators`；
- `numeric_fields`，如有数值必须来自 verified artifact；
- `uncertainty_note`；
- `status`。

Summarizer 可以返回：

- `READY`；
- `MISSING_CITATION`；
- `FACT_CONFLICT`。

`MISSING_CITATION` 只能触发一次由 Controller 审批的补检索，不允许 Summarizer 直接调用 Retriever。

### 5.10 状态消费合同

新增 `StateConsumptionRecord`，解决当前只有 publish/hydrate、无法证明影响决策的问题：

| 字段 | 含义 |
| --- | --- |
| `state_ref_id` | 被消费的 Ref |
| `consumer_role` | 消费者 |
| `consumer_step_id` | 对应步骤 |
| `operation` | `rerank_candidates`、`select_prompt_slice`、`memory_match` 等 |
| `read_field_ids` | 消费的对象/字段 ID，不记录原始大载荷 |
| `input_decision_surface_hash` | 消费前候选面 |
| `output_decision_surface_hash` | 消费后候选面 |
| `selected_ids` | 最终保留项 |
| `behavioral_effect` | 候选、计划或结果是否变化 |
| `downstream_ref_ids` | 受影响的 Evidence/Artifact Ref |
| `policy_version` | 消费算法版本 |

该记录说明的是“状态参与了哪个程序决定”，不是声称 LLM 直接读取向量或 KV。

### 本章结论

新增合同必须把“模型提案、程序批准、实际调度、状态消费和最终工件”拆成不同对象。只有这样，Agent 自由度增加后仍能回答谁决定、谁校验和谁承担副作用。

## 6. Capability Registry 与 Domain Pack

### 6.1 为什么不能只扩展 `intent_op`

继续为每个新任务增加 `intent_op -> Python if/elif`，会维持当前 Executor 特化问题。反过来，允许 Planner 生成任意工具名又会失控。

折中方案是“能力闭包”：开发者注册一组可组合 capability，Planner 可以在闭包内组合，但不能创造闭包外能力。

### 6.2 建议文件

- `v2/contracts/adaptive.py`：能力和计划合同；
- `v2/runtime/capability_registry.py`：注册、查询、digest 和权限过滤；
- `v2/runtime/domain_packs.py`：按任务族装配允许能力；
- 保留 `v2/route_tool_catalog.py`，为 strict 路径继续生成 `tc`；adaptive registry 可以为旧 profile 提供兼容 adapter。

### 6.3 第一批 Domain Pack

优先实现 `long_doc_analysis_v1`，因为它最能体现规划、检索、补证据、执行和带引用总结的完整协作。

建议能力：

| capability | owner | 输入 | 输出 | 实现 |
| --- | --- | --- | --- | --- |
| `retrieve_semantic_evidence_v1` | Retriever | EvidenceRequest | EvidencePackRef | 复用 SemanticChunkRetriever |
| `retrieve_table_evidence_v1` | Retriever | EvidenceRequest | EvidencePackRef | 复用 TableStructureRetriever |
| `retrieve_memory_assist_v1` | Retriever | query embedding Ref | MemoryMatchRef | 复用 MemoryIndexStore |
| `verify_evidence_coverage_v1` | Runtime | EvidencePackRef + criteria | CoverageResultRef | 新程序 validator |
| `extract_metric_series_v1` | Executor | table evidence | verified metric artifact | DSL |
| `compare_periods_v1` | Executor | metric artifact | verified comparison artifact | DSL |
| `detect_conflict_v1` | Executor | evidence/artifact refs | conflict report | 程序/DSL |
| `compose_cited_report_v1` | Summarizer | verified refs | ClaimSet + report | LLM + claim validator |

第二个 Domain Pack 再实现 `csv_analysis_v1`，复用 profile、聚合、异常和清洗逻辑。事件诊断可作为第三个包。任意代码迭代不作为第一阶段任务族。

### 6.4 能力发现给 Planner 看什么

Planner 只看到短表面：

```json
{
  "id": "extract_metric_series_v1",
  "role": "executor",
  "description": "从已验证的表格证据中提取指标时间序列",
  "accepts": ["canonical_evidence_pack"],
  "produces": ["execution_artifact"],
  "output_contract": "statebus.metric_series.v1",
  "side_effect": "workspace_write"
}
```

Planner 不看到 Python 类名、真实路径、命令、依赖环境、凭据和 sandbox 参数。完整 descriptor 只存在于控制器。

### 本章结论

泛化边界应从“预置 intent 分支”扩大到“可组合的已注册能力”，而不是扩大到任意工具。这样能增加同一任务族内的新组合能力，又保持可审计和可测试。

## 7. 四个角色的新 Prompt 与代码逻辑

本章给出 Prompt 的组成和输出处理逻辑。实现时不应把大段自然语言合同复制到每个请求中；公共规则应版本化并计入 prompt manifest。

### 7.1 Planner

#### 输入

- 任务目标、实体、时间范围；
- `CanonicalTaskSpec` 的允许输出，不提供 expected facts；
- `AdaptiveTaskEnvelope` 的步骤、重规划和成本预算；
- 本任务可见的 compact capability surface；
- 可选的兼容 memory strategy 摘要和 Ref ID；
- 已完成步骤摘要，仅在局部 replan 时提供；
- 触发重规划的结构化错误，不提供无关日志全文。

#### 系统 Prompt 核心规则

```text
你是 StateBus Planner。你只提出计划，不执行、派工或注册工具。
只能从 capability_surface 复制 capability_id。
生成 2 至 max_plan_steps 个有向无环步骤。
每个步骤必须声明 owner role、依赖、输入 Ref 类型、输出合同和完成条件。
不得输出路径、shell、网络、Python、未列出的工具或新的最终输出字段。
只返回符合 statebus.plan_proposal.v1 的 JSON。
```

#### 动态 Payload

```json
{
  "task": {"goal": "...", "entities": ["..."], "time_scope": "..."},
  "allowed_outputs": ["..."],
  "capability_surface": [{"id": "...", "role": "...", "accepts": [], "produces": []}],
  "budgets": {"max_steps": 6, "max_replans": 1},
  "available_input_refs": [{"id": "...", "kind": "..."}],
  "replan_context": null
}
```

#### 输出处理

1. JSON 提取和 response schema；
2. dataclass 解析；
3. ID、长度、枚举和列表上限检查；
4. `PlanPolicyValidator` 检查能力、DAG、Ref、输出和预算；
5. 可修复错误最多重试一次；
6. 失败时使用 domain pack 的确定性计划；
7. 原始提案和批准结果分别持久化。

#### 真正可自主决定的内容

- 选择哪些已注册能力；
- 先取文本证据还是表格证据；
- 是否需要比较、冲突检测或记忆辅助；
- 步骤依赖与有限分支；
- 在失败后修改尚未执行的剩余步骤。

#### 不能决定的内容

- 实际调度、权限、超时、沙箱、输出验收和记忆提交；
- 修改已经完成的步骤和已验证工件；
- 跳出当前 domain pack。

### 7.2 Retriever

当前顺序是程序先检索、Retriever LLM 后选 route/tool。adaptive 模式应调整为：

```text
Approved retrieve step
  -> Retriever LLM 生成 EvidenceRequest
  -> 程序校验 query 数量、corpus scope 和 evidence types
  -> RetrieverFanoutPipeline 执行 lexical/semantic/table/memory 检索
  -> EvidenceCoverageVerifier 评估结果
  -> COMPLETE / INSUFFICIENT / CONFLICTING
```

#### Retriever 输入

- 获批步骤的 evidence goal；
- 允许的 corpus IDs 和 retriever capability；
- 实体、时间范围、证据类型和预算；
- 可选 memory/state Ref 的小型元数据；
- 补检索时提供缺失证据类型和已命中 locator 摘要。

#### Prompt 核心规则

```text
你是 Retriever。你负责提出有限检索请求，不负责执行文件、网络或代码操作。
只能使用给定 corpus_scope 和 evidence_type。
最多返回 3 个 query；query 之间应覆盖不同证据目标。
不得返回答案、工具名、路径或未授权数据源。
只返回 EvidenceRequest JSON。
```

#### Retriever 输出

- 1 至 3 个 query；
- query 对应的 evidence types；
- entity/time filters；
- max candidates；
- 是否允许 memory assist；
- 不再输出 `route/tool` 作为核心职责。

strict 模式继续保留当前 `choose_retrieval_candidate()`。adaptive 模式新增 `build_evidence_request()`，不改变旧方法语义。

#### coverage 与补检索

证据不足由程序得出，不依赖模型自评。补检索请求必须：

- 只补 `missing_evidence_types`；
- 不重复完全相同 query hash；
- 仍在同一 corpus scope；
- 全任务最多一次；
- 新旧 EvidencePack 通过稳定 fan-in 合并并保留来源。

### 7.3 Executor

#### Executor 输入

- 获批 execution step；
- `CapabilityGrant`；
- 可读取的 verified Evidence/Artifact Ref；
- 每个输入的 schema、列/字段摘要，不提供任意路径；
- DSL operation catalog；
- 输出合同和质量检查；
- 上一步 coverage/conflict 结果。

#### Prompt 核心规则

```text
你是 Executor。你生成声明式 TransformProgram，不生成 Python、shell 或文件路径。
只能使用 operation_catalog 中的 op。
只能读取 authorized_input_refs 中的字段。
最终字段必须完全匹配 output_contract。
不确定或输入不足时返回 NEEDS_ADDITIONAL_INPUT，不得猜测数值。
只返回 TransformProgram 或结构化失败状态。
```

#### 执行逻辑

1. 解析模型 JSON；
2. `TransformProgramValidator` 校验 operation、输入 Ref、字段、类型、上限和输出；
3. 修复一次，仅允许修改 DSL，不扩大权限；
4. DSL interpreter 从 workspace/input manifest 加载已授权输入；
5. 将候选输出写入 `tmp/`；
6. 使用现有 `WorkspaceManager` 物化输出；
7. 创建 candidate `ExecutionArtifactRef`；
8. 运行 artifact validator 和质量检查；
9. 通过后 `mark_verified()`；失败则 invalidated 并进入 fallback/replan。

现有工作区和 artifact 生命周期可复用，见 `v2/runtime/workspace.py:301-497` 和 `v2/refs/models.py:106-134`。

### 7.4 Summarizer

#### 输入

- verified `ExecutionArtifactRef` 摘要；
- EvidencePack 中获准进入 Prompt 的文本片段；
- claim 所需 locator；
- 输出风格和长度；
- memory 中只提供通过兼容检查的策略/摘要；
- 不提供 invalidated 工件、未经验证数值或原始代码 stderr 全文。

#### Prompt 核心规则

```text
你是 Summarizer。先构造 ClaimSet，再生成报告。
事实和数值必须引用 evidence_item_id 或 verified artifact_ref_id。
推理、风险和建议必须与事实区分。
缺少引用时返回 MISSING_CITATION；证据冲突时返回 FACT_CONFLICT。
不得改变 verified artifact 中的数值。
只返回 statebus.claim_set.v1 JSON。
```

#### 输出处理

1. 校验 claim ID 和引用 ID 存在；
2. 数值字段与 artifact payload 对比；
3. citation locator 必须属于本轮 HydrateManifest/EvidencePack；
4. 失败时要求修复一次；
5. 仍失败则使用确定性 artifact summary 或明确失败，不提交幻觉 claim；
6. 只有 valid ClaimSet 可以生成最终 report artifact 和 memory commit。

### 本章结论

增强后的四个角色分别控制计划、证据请求、变换配方和引用化表达。每个角色都有会影响下游的决定，也都有清晰的不可越过边界。

## 8. 计划校验与调度算法

### 8.1 `PlanPolicyValidator` 校验顺序

建议固定顺序，确保错误码稳定：

1. schema 和版本；
2. step ID 唯一性；
3. step 数量；
4. role 枚举；
5. capability 是否存在；
6. capability owner 是否匹配 role；
7. capability 是否在任务 allowlist；
8. input Ref 是否存在且类型兼容；
9. output contract 是否允许；
10. dependency 是否引用已知 step；
11. DAG 是否有环；
12. 是否存在从起点到最终输出的完整路径；
13. side effect 与 task risk class 是否兼容；
14. 单步和全局预算；
15. fallback/replan 条件是否合法。

不要自动把未知工具替换成“最接近工具”。未知 capability 必须拒绝。可以自动归一化的内容仅限大小写、排序、空值和安全缺省值。

### 8.2 ready-step 调度

```python
while not plan_terminal:
    ready = pending steps whose dependencies are COMPLETED
    if not ready:
        fail if pending remains, otherwise finish
    for step in stable_topological_order(ready):
        grant = issue_capability_grant(step)
        result = dispatch_and_wait(step, grant)
        validate_result(result)
        update_session_ledger_telemetry(result)
        handle_status_or_fallback(result)
```

第一阶段可以串行执行 ready steps，以保证可复现和简化资源核算。DAG 支持并行不等于第一阶段立即并行；并行调度可在功能稳定后单独设计和测试。

### 8.3 局部重规划

触发条件只允许：

- `INSUFFICIENT_EVIDENCE`；
- `CONFLICTING_EVIDENCE`；
- `UNSUPPORTED_TRANSFORM`；
- `MISSING_CITATION`；
- capability runtime 失败且确定性 fallback 不适用。

重规划输入包含：

- 原 `ApprovedPlanRef`；
- 已完成步骤及 verified output refs；
- 失败步骤和结构化 error code；
- 剩余预算；
- 仍可用 capability surface。

Planner 只能返回 `PlanPatchProposal`：替换失败步骤及其未执行后继，不能修改已完成步骤、已签发工件或顶层输出合同。

`PlanPolicyValidator` 再次校验 patch；全任务默认最多一次 replan。`RuntimeReplanRecord` 已有触发状态、原因、fallback action、selected capability 和 DAG hash，可扩展使用，见 `v2/runtime/session.py:98-128`。

### 8.4 失败处理

| 失败 | 程序动作 | 是否再调用 LLM |
| --- | --- | --- |
| Planner JSON 格式错误 | response schema + 修复 Prompt 一次 | 是，最多一次 |
| Planner 未知 capability | 拒绝并返回精确错误 | 是，最多一次 |
| 计划仍无效 | 使用 domain pack 固定计划 | 否 |
| Retriever query 越界 | 拒绝该请求 | 是，最多一次 |
| 证据不足 | 一次补检索或局部 replan | 可选一次 |
| DSL 非法 | 返回 validator 错误 | 是，最多一次 |
| DSL 执行失败 | invalidated artifact，确定性 fallback 或 replan | 视错误类型 |
| Summarizer 缺引用 | 一次补检索 | 可选一次 |
| Summarizer 改写数值 | 拒绝 ClaimSet，修复一次 | 是，最多一次 |
| 超预算/超时 | Supervisor trap/cancel | 否 |

现有 Supervisor 状态机和 ACK/heartbeat/lease 语义继续使用，见 `v2/runtime/supervisor.py:45-205`。现有 `FallbackDag` 可继续表达 retry、downgrade 和 skip，见 `v2/runtime/fallback.py:10-119`，但需要增加与 adaptive error code 的映射。

### 本章结论

动态计划必须有确定性校验顺序、稳定拓扑调度和严格重规划预算。否则“自主性”会直接变成不可复现和不可审计。

## 9. 非文本状态和记忆如何进入新流程

### 9.1 StateRef 的正确作用

模型本身不直接读取 embedding bytes。合理路径是：

```text
Retriever 产生 query embedding / candidate feature state
  -> LayeredStateStore publish
  -> SemanticStateRef
  -> 控制消息传 RefHandle
  -> 下游本地 adapter 水合
  -> 程序进行 rerank、裁剪或 memory match
  -> 产生 EvidencePack/PromptSlice
  -> LLM 只看到裁剪后的证据文本或结构化事实
```

新流程必须在执行本地 adapter 后写 `StateConsumptionRecord`，将 Ref 与候选面变化、选中 evidence IDs 和后续 artifact 关联起来。

### 9.2 三组状态对照

每个 adaptive 任务至少支持：

| 变体 | 状态 |
| --- | --- |
| `state_off` | 使用相同检索逻辑，但不传 StateRef，使用文本或本地重算 |
| `state_normal` | 正常 publish、hydrate、consume |
| `state_perturbed` | 对 embedding 排序输入做可复现扰动，验证消费链能观察到候选变化 |

扰动实验的目标不是让质量必然下降，而是证明状态真的进入了下游计算。必须记录输入状态 hash、候选面 hash、选中项和最终质量。

### 9.3 记忆的正确作用

记忆不能只是拼接进所有 Agent Prompt。建议区分：

- `memory_strategy_ref`：为 Planner 提供兼容的步骤策略摘要；
- `memory_evidence_ref`：为 Retriever 提供历史证据候选；
- `memory_artifact_ref`：经 replay gate 后供 Executor 复用；
- `memory_summary_ref`：供 Summarizer 辅助表达，但不能覆盖本轮 verified facts。

Planner 只能请求 `none/assist/artifact/strategy`，最终是否采用仍由 replay/memory policy 决定。复用后必须记录：

- 命中的 memory ID；
- 兼容性判定；
- 哪个步骤消费；
- 是否减少检索、执行或 LLM 调用；
- 被跳过步骤；
- 输出/工件 hash 一致性；
- 实际 token、字符、时间和工具差额。

### 本章结论

这次增强不能只增加 Agent 对话。它必须让 StateRef 和 memory Ref 成为计划、检索或执行的受控输入，并留下可扰动、可对照的消费证据。

## 10. 第一阶段实施方案：受限自适应协作

### 10.1 代码修改总表

| 文件/目录 | 动作 | 具体内容 |
| --- | --- | --- |
| `v2/contracts/constants.py` | 修改 | 新 schema version 常量 |
| `v2/contracts/adaptive.py` | 新增 | WorkflowMode、TaskEnvelope、Capability、Plan、Evidence、DSL、Claim、Consumption 合同 |
| `v2/contracts/__init__.py` | 修改 | 导出新合同 |
| `v2/runtime/compiler.py` | 修改 | strict 行为不变；为 adaptive domain pack 增加宽领域 intent 的显式校验 |
| `v2/runtime/capability_registry.py` | 新增 | 能力注册、过滤、digest、legacy profile adapter |
| `v2/runtime/domain_packs.py` | 新增 | long_doc/csv 能力集合和确定性 fallback plan |
| `v2/runtime/plan_policy.py` | 新增 | PlanProposal 校验、DAG、预算、repair errors、批准计划 |
| `v2/runtime/adaptive_runtime.py` | 新增 | adaptive 计划解析、ready queue、角色 adapter 和调度辅助逻辑 |
| `v2/runtime/driver.py` | 修改 | 保留 `run()`；新增 `run_adaptive()`，掌握 adaptive 唯一调度权 |
| `v2/runtime/role_path.py` | 修改 | 保留旧方法；新增 propose_plan/build_evidence_request/build_transform_program/build_claim_set |
| `v2/runtime/retrieval_adapter.py` | 新增 | EvidenceRequest 到现有 Pipeline 的适配和 fan-in |
| `v2/retrieval/pipeline.py` | 修改 | 接受多 query/证据目标/预算，返回消费记录所需字段 |
| `v2/runtime/evidence_coverage.py` | 新增 | deterministic coverage/conflict evaluator |
| `v2/runtime/transform_dsl.py` | 新增 | DSL schema validator 与 interpreter |
| `v2/runtime/state_consumption.py` | 新增 | StateConsumptionRecord 构建与 telemetry |
| `v2/runtime/session.py` | 修改 | 关联 proposal/approved plan/grant/coverage/consumption refs |
| `v2/runtime/ledger.py` | 修改 | 新增计划和决策账本；ReplayLedger 继续保持独立 |
| `v2/runtime/supervisor.py` | 修改 | ready-step dispatch、按 step_id/attempt_id 管理动态步骤 |
| `v2/runtime/fallback.py` | 修改 | adaptive error 到 retry/replan/downgrade 的稳定映射 |
| `v2/control/statebus_v2.proto` | 修改 | 增加 plan/grant/result Ref 或扩展通用 Ref 用法；不内联大对象 |
| `v2/runtime/smoke.py` | 修改 | 加 workflow mode；adaptive 时只 bootstrap 并调用新 Driver |
| `v2/runtime/codeact.py` | 第一阶段小改 | 接收已验证 DSL 结果或继续作为确定性 fallback，不接 LLM codegen |
| `v2/benchmark/` | 修改 | 新增 adaptive task cases、模式和指标 |

### 10.2 不建议直接改动的内容

- 不删除 `choose_retrieval_candidate()`、`validate_execution_choice()` 和当前 Planner semantic plan；strict 仍使用。
- 不改变已有 `CanonicalTaskSpec.canonical_payload()`，避免所有历史 spec hash 改变。
- 不把 `ExecutionArtifactRef` 与 `SemanticStateRef` 合并。
- 不让 capability registry 覆盖当前 route/tool catalog；先通过 adapter 共存。
- 不在第一阶段把诊断脚本直接 import 进 Runtime。

### 10.3 分步落地

#### P1-A：合同和注册表

实现新 dataclass、enum、schema version、registry 和 domain pack。此阶段不调用模型、不改变 smoke。

完成条件：

- 合同 canonical payload/hash 稳定；
- registry 拒绝重复 ID 和不完整 descriptor；
- domain pack 只能引用已注册能力；
- legacy `RouteToolProfile` 可以只读映射为 descriptor；
- 所有单测不依赖环境变量和模型。

#### P1-B：Planner shadow mode

新增 Planner `propose_plan()` 和 `PlanPolicyValidator`，在 `adaptive_shadow` 中生成并校验提案，但继续执行固定路径。

记录：

- model proposal；
- policy report；
- approved/fallback plan；
- 与 default workflow 的 step/capability 差异；
- 无效原因、修复次数和 token。

完成条件：

- shadow 计划不会改变任务结果；
- 所有越权提案被拒绝；
- 确定性 stub 能覆盖 approve/normalize/repair/reject/fallback；
- strict 指标和工件合同保持兼容。

#### P1-C：Retriever 前置请求和 coverage

在 adaptive 模式中调整 Retriever 顺序，让 LLM 在 Pipeline 前生成 EvidenceRequest。扩展 Pipeline 支持最多 3 个 query，结果通过稳定规则合并。

完成条件：

- 不同 evidence goal 实际改变 consumed objective hash；
- coverage 能检测缺失 evidence type、locator 和时间范围；
- 一次补检索有独立 request/result Ref；
- 重复 query 不会无限循环；
- strict Pipeline 行为不变。

#### P1-D：动态 Driver

实现 ready-step 串行调度、grant、Supervisor 生命周期、Session 更新和 replan。先只执行 long_doc domain pack。

完成条件：

- Driver 执行 `ApprovedPlan` 而不是固定函数顺序；
- 每个 dispatch 都有 grant hash；
- 未获批 capability 不可能进入 executor；
- 依赖失败时后继不会被误调度；
- replan 只能修改未执行子图；
- max replan/attempt budget 生效。

#### P1-E：Executor DSL

实现 TransformProgram validator/interpreter，将现有长文档指标提取和跨期比较的一部分从 `intent_op if/elif` 转为可组合 DSL。

完成条件：

- 支持首批 operations；
- 对未知 op、未知列、类型错误、超大 join、任意表达式 fail closed；
- 同一输入和 program hash 产生稳定输出；
- 输出进入现有 workspace/artifact validator；
- 确定性 fallback 与旧实现结果一致。

#### P1-F：ClaimSet 和状态消费

让 Summarizer 返回 ClaimSet；补 StateConsumptionRecord 和 memory consumption。

完成条件：

- 无引用 claim 被拒绝；
- 修改 verified 数值被拒绝；
- `state_off/state_normal/state_perturbed` 都能完整执行并生成消费账本；
- memory assist 与 replay 路径可区分；
- 最终报告仍是可读 Markdown/JSON artifact。

### 本章结论

第一阶段按“合同 -> shadow -> Retriever -> Driver -> DSL -> Claim/状态消费”推进。不能先改 Prompt 再补控制合同，否则会产生无法审计的中间状态。

## 11. 第二阶段实施方案：LLM 生成 CodeAct

### 11.1 启用前提

只有以下条件全部满足，`llm_bounded_python` 才能启用：

- 第一阶段 adaptive 和 DSL 路径稳定；
- `bwrap` 在目标 Docker/openEuler 环境真实可用；
- 网络 namespace 隔离、只读 project bind 和 workspace 单独写入已验证；
- LLM code path 在 `bwrap` 不可用时 fail closed；
- AST policy、输出 schema、资源限制和 artifact validator 测试通过；
- 有明确的威胁模型和不支持能力清单。

当前 `CodeActSandboxRunner` 在 `auto` 下可能从 bwrap 退到 resource backend，见 `v2/runtime/codeact_sandbox.py:76-99`；这对运行时生成的可信固定脚本可以接受，但对不受信任 LLM 代码不够。第二阶段必须新增“LLM code 不允许 resource fallback”的独立策略。

### 11.2 正式路径

```text
Approved executor step
  -> CapabilityDescriptor.execution_kind == llm_python
  -> CodeGenerationRequest
  -> Executor LLM 返回完整 Python source
  -> 提取 raw / fenced / {code: ...}
  -> ast.parse
  -> AST/依赖/路径/复杂度 policy
       -> 可修复：一次 repair prompt
       -> 不可修复或再次失败：DSL/确定性 fallback
  -> bwrap readiness gate
       -> 不可用：不执行代码
  -> 写 generated/source.py 和 policy report
  -> bwrap 执行
  -> 固定 outputs/result.json
  -> schema / numerical / artifact validators
  -> candidate ExecutionArtifactRef
  -> verified 或 invalidated
  -> Ledger / telemetry / memory gate
```

### 11.3 新合同

- `CodeGenerationRequest`：任务、输入 schema、固定路径别名、允许库、输出 schema、代码预算；
- `GeneratedCodeProposal`：source、model、source hash、attempt；
- `CodePolicyReport`：AST 节点数、import、call、path、违规和 policy version；
- `CodeRepairRequest`：只包含违规码、行号和固定修复规则；
- `SandboxExecutionReport`：requested/actual backend、timeout、returncode、stdout/stderr hash；
- `CodeValidationReport`：输出 schema、数值/质量、artifact hash；
- `CodeActFallbackRecord`：为何退回 DSL/确定性执行。

### 11.4 Prompt 设计

诊断脚本 `scripts/v2_diagnostics/bounded_llm_codeact_demo.py` 已展示以下可复用思路：允许 import roots、禁止 call/name roots、固定输入和输出 literal、AST repair 和确定性 fallback，见该文件 `:23-37、145-230、380-452`。

正式 Prompt 不应只给一个可复制固定模板，因为那仍然难以证明 CodeAct 泛化。建议给：

- 输入 JSON schema 和一个小型示例，不给真实答案；
- 允许库和禁止行为；
- 固定逻辑路径别名，例如 `inputs/task.json` 和 `outputs/result.json`；
- 输出字段和质量条件；
- 代码长度、AST 节点、循环和文件大小上限；
- 要求完整文件、无 Markdown、无解释；
- 不提供宿主机真实路径。

代码自由度放在“如何完成纯计算”，不放在“能访问什么”和“能产生什么副作用”。

### 11.5 AST policy 的边界

AST allowlist 只能过滤静态语法，不是完整沙箱。正式策略至少检查：

- import root allowlist；
- 禁止 `eval/exec/compile/__import__/input`；
- 禁止 `os/sys/subprocess/socket/requests/urllib/http/shutil`；
- 禁止 dunder attribute 和动态 getattr/setattr；
- 禁止 `Path.cwd()`、`__file__`、绝对路径和 `..`；
- 只允许固定输入/输出 literal；
- 限制 AST 节点数、嵌套层数、循环数和 comprehension；
- 禁止类定义、async、线程、multiprocessing、signal；
- 禁止 pickle、marshal 和动态反序列化；
- 禁止任意 SQL/正则灾难性输入时应另有复杂度限制。

即使 AST 通过，仍必须在 bwrap 和 resource limit 下运行。

### 11.6 缓存与重放

当前 `CodeActRunner` 有确定性 cache，见 `v2/runtime/codeact.py:397-414、647-728`。LLM code cache key 必须至少包含：

- `CanonicalTaskSpec` hash；
- Approved executor step hash；
- input artifact hashes；
- capability descriptor digest；
- code policy version；
- model ID 和 prompt manifest hash；
- generated source hash；
- output contract version；
- runtime compatibility signature。

只有代码、输入、环境和输出合同都兼容，才允许复用 verified artifact。不能只按自然语言 query 命中并执行旧代码。

### 本章结论

第二阶段的 CodeAct 是“受限纯计算代码生成”，不是通用终端 Agent。安全边界由 policy、强沙箱和输出验证共同构成；Prompt 只是第一层引导。

## 12. 测试计划

### 12.1 新增单元测试文件

| 测试文件 | 覆盖内容 |
| --- | --- |
| `tests/v2/test_adaptive_contracts.py` | canonical payload、hash、schema 和 enum |
| `tests/v2/test_capability_registry.py` | 重复 ID、过滤、digest、domain pack、legacy adapter |
| `tests/v2/test_plan_policy.py` | 合法 DAG、环、越权能力、Ref 类型、输出、预算、repair/fallback |
| `tests/v2/test_adaptive_role_prompts.py` | 每个角色 Prompt 可见字段、禁止字段和 response schema |
| `tests/v2/test_evidence_request_and_coverage.py` | query 上限、corpus scope、coverage、conflict、补检索 |
| `tests/v2/test_transform_dsl.py` | 每个 op、类型、未知字段、资源上限、稳定输出 |
| `tests/v2/test_adaptive_runtime.py` | ready queue、依赖、grant、step result、replan、budget |
| `tests/v2/test_state_consumption.py` | off/normal/perturbed 和 behavioral effect |
| `tests/v2/test_claim_set.py` | 引用、数值一致性、缺引用和冲突 |
| `tests/v2/test_llm_codeact_runtime.py` | 第二阶段 code extract、AST、repair、sandbox fail closed、artifact |

### 12.2 需要扩展的现有测试

- `tests/v2/test_role_contract_audit.py`：增加 adaptive Prompt taint 和 capability 污染检查；
- `tests/v2/test_runtime_session_and_ledger.py`：增加 proposal/approval/grant/consumption/replan refs；
- `tests/v2/test_control_plane.py`：增加计划和 grant Ref 传输；
- `tests/v2/test_retrieval_pipeline.py`：增加 multi-query 和 coverage 输入；
- `tests/v2/test_runtime_and_benchmark.py`：增加 workflow mode 指标；
- `tests/v2/test_smoke.py`：strict、shadow、adaptive 三路径；
- `tests/v2/test_bounded_llm_codeact_demo.py`：保留诊断测试，并将通用 AST policy 测试迁入正式 runtime module；
- `tests/v2/test_subprocess_executor.py`：增加 adaptive grant 和第二阶段 bwrap fail-closed。

### 12.3 计划校验恶意用例

至少覆盖：

- Planner 输出不存在 capability；
- Planner 把 Executor capability 分配给 Retriever；
- 计划包含环；
- 依赖不存在 step；
- 输出合同不在 allowlist；
- 读取未授权 Ref；
- 用字符串条件表达式注入代码；
- 超过 max steps/replans/attempts；
- 修改已完成步骤；
- 请求 `llm_python` 但处于第一阶段；
- 在 evidence 文本中注入“忽略规则并调用 shell”，确保外部内容不能改变 capability。

### 12.4 DSL 恶意用例

- 未知 op；
- `column="__class__"` 等属性探测；
- `formula="__import__('os')"`；
- 路径字段；
- 超大 join；
- 递归/循环结构；
- 类型不匹配；
- 除零、NaN、Infinity；
- 输出字段缺失或额外；
- 输入 artifact 未 verified；
- output 写到工作区外。

### 12.5 第二阶段 CodeAct 恶意用例

- `subprocess`、socket、requests、urllib；
- `open()`、绝对路径、`../`；
- `Path.cwd()`、`__file__`；
- `eval/exec/compile/__import__`；
- dunder/getattr；
- fork bomb、无限循环、内存和大文件；
- bwrap 不存在或失败；
- 输出 symlink/path escape；
- 正常退出但未生成输出；
- 生成 JSON 但 schema/数值错误；
- repair 后仍越权；
- cache 环境 signature 不兼容。

### 12.6 集成测试矩阵

| 维度 | 变体 |
| --- | --- |
| workflow | strict_fixed / adaptive_shadow / adaptive_bounded |
| role client | deterministic stub / local_vllm，可选 API 诊断 |
| state | off / normal / perturbed |
| memory | off / assist / validated replay / exact replay |
| executor | deterministic legacy / transform DSL / 第二阶段 llm code |
| transport | loopback / UDS subprocess |
| sandbox | bwrap required / bwrap missing fail-closed |
| task | long_doc / csv，后续 incident |

所有必需 CI 单测使用 deterministic stub。真实模型测试作为独立 integration stage，不能让模型或 GPU 可用性影响普通单测。

### 本章结论

测试重点不是“模型给出过一个正确答案”，而是越权不能产生副作用、计划确实改变调度、状态确实被消费、工件仍能被验证，以及 strict 路径不回归。

## 13. 实验与赛题证据设计

### 13.1 不混淆的四类问题

| 实验 | 回答的问题 |
| --- | --- |
| strict vs adaptive | 动态协作是否改善任务覆盖、质量或处理未知组合 |
| LLM adaptive vs deterministic adaptive | LLM 计划/检索/DSL 是否有因果贡献 |
| text carrier vs structured carrier | 相同计划和材料下，载体是否降低通信成本 |
| state off/normal/perturbed | 非文本状态是否被消费并影响后续处理 |

四类实验必须分开，不能用一次总系统比较同时回答全部问题。

### 13.2 文本与结构化的公平对比

动态规划会引入随机性。建议先生成并冻结一个 `ApprovedPlan`，再分别通过：

- 文本载体：将同一计划和中间结果渲染为纯文本；
- 结构化载体：通过 Protobuf + Ref 传递同一计划和对象。

两侧固定：任务、模型、ApprovedPlan、证据、工具、输出 validator、memory policy、缓存策略和顺序。这样差异才可归因于通信载体。

### 13.3 LLM 因果消融

至少比较：

1. `adaptive_llm`：Planner/Retriever/Executor/Summarizer 使用真实模型；
2. `adaptive_deterministic`：同一合同，用确定性策略生成计划、query 和 DSL；
3. `planner_disabled`：使用固定计划，其余相同；
4. `retriever_request_disabled`：使用固定 query，其余相同；
5. `executor_dsl_disabled`：使用旧 intent 分支，其余相同；
6. `summarizer_template`：使用确定性摘要，其余相同。

记录：质量、覆盖率、计划有效率、分支触发率、重规划率、模型调用数、token、prompt bytes、总时延、执行时延、错误和 fallback。

### 13.4 连续任务

建议两组：

#### A. 长文档证据分析 10 轮

- 前几轮提取不同指标和风险；
- 中间轮出现证据缺口或冲突，触发一次补检索；
- 后续轮复用策略、Evidence/Artifact Ref；
- 最终生成带引用综合报告。

#### B. CSV 分析 10 轮

- profile、过滤、聚合、异常、相关性、清洗；
- 使用 DSL 组合而不是每轮单独 intent 分支；
- 后续轮复用 validated strategy/artifact；
- 最终统计真实跳过步骤和执行节省。

### 13.5 通过标准

第一阶段必须满足：

- strict 现有单测和质量门不回归；
- adaptive 至少在一个任务中执行与固定四步不同的获批 DAG；
- 至少一次 evidence gap 实际触发补检索并改善 coverage；
- 任意越权计划 0 次进入 dispatch；
- 每个 adaptive dispatch 都能追溯到 ApprovedPlan 和 CapabilityGrant；
- 每个最终 factual claim 都能追溯到 EvidenceItem 或 verified ArtifactRef；
- `STATE_CONSUMED` 事件非零，并能给出 off/normal/perturbed 对照；
- LLM 角色消融有独立结果，不能只报告总系统 token；
- 不提前声明时延优势，除非匹配实验支持。

第二阶段额外必须满足：

- LLM 代码只在 bwrap 后端执行；
- sandbox fallback 到 resource 的次数为 0；
- 所有恶意代码测试均未产生工作区外副作用；
- 代码成功不绕过 artifact/quality validator；
- repair 和确定性 fallback 均有可追踪记录。

### 本章结论

新架构的实验必须分别证明 Agent 决策、结构化载体、非文本状态和记忆复用。只有这样，能力增强不会反过来削弱赛题证据的可归因性。

## 14. 配置、迁移与回滚

### 14.1 建议配置

```text
STATEBUS_WORKFLOW_MODE=strict_fixed|adaptive_shadow|adaptive_bounded
STATEBUS_ADAPTIVE_DOMAIN_PACK=long_doc_analysis_v1
STATEBUS_MAX_PLAN_STEPS=6
STATEBUS_MAX_REPLANS=1
STATEBUS_MAX_RETRIEVAL_EXPANSIONS=1
STATEBUS_EXECUTION_MODE=legacy|transform_dsl|llm_bounded_python
STATEBUS_LLM_CODEACT_REQUIRE_BWRAP=1
```

环境变量只是部署入口，解析后必须形成不可变 runtime config 并写入 runtime signature。测试中优先直接传 dataclass，不依赖全局环境。

### 14.2 默认值

- 默认 `strict_fixed`；
- 开发期 adaptive 先默认 `adaptive_shadow`；
- `adaptive_bounded` 只在指定 task/domain pack 启用；
- 第一阶段默认 `transform_dsl`；
- 第二阶段 `llm_bounded_python` 默认关闭；
- LLM code 路径强制 bwrap，不允许 `auto -> resource`。

### 14.3 回滚

任何 adaptive 故障都可以通过切换 `STATEBUS_WORKFLOW_MODE=strict_fixed` 回到当前路径。新增 schema 使用新版本和新文件，不覆写已有 strict artifact。adaptive memory 进入 replay 前必须带 workflow mode、approved plan hash 和 capability registry digest，防止被 strict 错误复用。

### 14.4 历史证据边界

实现后必须新建实验目录和报告，不得把新代码结果写回 2026-07-15 的历史 P0/P1 审计。历史 strict 结果仍只描述当时代码。新 adaptive 结果应明确 commit、配置、模型、domain pack、registry digest 和 workflow mode。

### 本章结论

新能力必须以并行模式接入，并能一键回到严格路径。只有这样才能在增强 Agent 的同时保护已有实现和证据。

## 15. 风险与控制措施

| 风险 | 影响 | 控制措施 |
| --- | --- | --- |
| Planner 生成看似合法但无意义的 DAG | 增加成本且不改善任务 | completion criteria、domain fallback、shadow 统计、消融 |
| 动态步骤造成 token/时延上升 | 与低开销目标冲突 | 步骤/重规划预算；简单任务直接 fixed fast path |
| capability 描述泄漏实现和路径 | Prompt injection 扩大攻击面 | 只给 compact surface，执行 descriptor 留在 Controller |
| Retriever 反复补检索 | 无限循环 | query hash 去重、最多一次 expansion |
| LLM 自报 coverage 不可靠 | 错误进入执行 | coverage 由程序计算 |
| DSL 逐渐演变为通用语言 | 重建一个不安全解释器 | 小型 op allowlist、无表达式、复杂度上限 |
| Summarizer 引入新数值 | 最终答案失真 | ClaimSet 数值与 verified artifact 对比 |
| StateRef 有记录但未影响行为 | 赛题证据仍弱 | StateConsumptionRecord + off/perturbed A/B |
| 记忆污染和 Prompt injection | 跨任务放大错误 | replay gate、来源/兼容性、只读结构化摘要、隔离未验证 memory |
| LLM CodeAct 逃逸 | 宿主机风险 | 第二阶段、bwrap required、AST + workspace + resource + output gate |
| adaptive 与 strict 指标混写 | 结论不可归因 | workflow mode 和实验目录强隔离 |
| Driver 重构过大 | 回归和排错困难 | 新入口、shadow 先行、按 P1-A 到 P1-F 小步合并 |

### 本章结论

最大的工程风险不是模型返回格式错误，而是模型提案被错误地当成已授权动作。所有实现审查都应围绕“候选何时变成授权、授权何时变成副作用”展开。

## 16. 实施检查清单

### 第一阶段

- [ ] 新增 adaptive contracts 和 schema versions。
- [ ] 实现 capability registry 与 long_doc domain pack。
- [ ] 保留 strict route/tool catalog 和旧角色方法。
- [ ] 实现 Planner PlanProposal Prompt、解析和一次 repair。
- [ ] 实现 PlanPolicyValidator 和确定性 fallback plan。
- [ ] 完成 adaptive_shadow，确认不影响 strict 结果。
- [ ] 实现 Retriever EvidenceRequest 前置生成。
- [ ] 扩展 Pipeline 支持 multi-query 和稳定 fan-in。
- [ ] 实现 EvidenceCoverageVerifier 和一次补检索。
- [ ] 实现 adaptive Driver ready queue 和 CapabilityGrant。
- [ ] 实现局部 replan，限制为一次且只改未执行子图。
- [ ] 实现 TransformProgram validator/interpreter。
- [ ] 将至少一个长文档执行动作迁移到 DSL。
- [ ] 实现 ClaimSet 和 citation/numeric validator。
- [ ] 实现 StateConsumptionRecord 和 memory consumption。
- [ ] 新增单测、恶意用例和三模式集成测试。
- [ ] 运行 strict 回归、adaptive 消融和状态扰动实验。

### 第二阶段

- [ ] 从诊断脚本提取通用 code extraction/AST policy 到正式 runtime 模块。
- [ ] 定义 CodeGenerationRequest、Policy、Sandbox、Validation 合同。
- [ ] 实现完整 Python 生成 Prompt 和一次 repair。
- [ ] 为 LLM code 增加 bwrap-required fail-closed runner。
- [ ] 校验固定输入/output path 和 artifact schema。
- [ ] 实现 source/policy/runtime signature cache key。
- [ ] 补齐安全、资源、路径和 sandbox 故障测试。
- [ ] 只在目标 Docker/openEuler profile 验证后启用正式实验。

## 17. 新成员的建议阅读与实施顺序

1. 先读 `docs/reference/题目.md`，理解赛题重点是通信、状态、记忆和实验，而不是无限 Agent 自治。
2. 读 `docs/reports/statebus_v2_agent_task_flow_zh.md`，理解当前固定任务如何流动。
3. 读 `docs/reports/statebus_v2_agent_controlplane_codeact_architecture_zh.md`，核对当前 Prompt、控制层和 CodeAct 边界。
4. 读 `v2/runtime/smoke.py::run_smoke()`，确认当前主要工作发生在 Driver 前。
5. 读 `v2/runtime/role_path.py` 的四个角色方法和 Prompt。
6. 读 `v2/runtime/driver.py::build_default_workflow()` 与 `RuntimeDriver.run()`。
7. 读 `v2/runtime/session.py`、`supervisor.py`、`fallback.py`，复用已有生命周期和重规划记录。
8. 读 `v2/retrieval/pipeline.py`、`refs/models.py` 和 `workspace.py`，不要另造证据/工件体系。
9. 读 `v2/runtime/codeact.py` 与 `codeact_data_tasks.py`，理解当前 CodeAct 是确定性包装。
10. 第二阶段再读 `scripts/v2_diagnostics/bounded_llm_codeact_demo.py` 和对应测试。

实施时严格按 P1-A 到 P1-F 顺序。每一步都应先用 deterministic stub 建立合同和失败语义，再接真实 LLM。

## 18. 最终设计结论

这次增强不是把 StateBus v2 改成一个“模型想做什么就做什么”的通用 Agent 框架，而是把当前受限过强的 LLM 角色升级为真正参与决策的受控协作者：

- Planner 可以提出有限任务图，但不能调度；
- Retriever 可以决定如何找证据，但不能越过数据源边界；
- Executor 可以组合新的数据变换，但第一阶段不能执行任意代码；
- Summarizer 可以发现证据缺口并构造可引用结论，但不能修改验证事实；
- Driver/Supervisor 始终掌握权限、预算、调度和终止；
- Validator 始终决定候选能否成为已验证状态或工件；
- StateRef 和 memory 通过程序消费记录影响下游，不被夸大为模型隐藏状态传递；
- 第二阶段才引入 LLM Python CodeAct，并采用强沙箱 fail-closed。

这一方案相较当前固定流水线增加了有意义的 LLM 因果贡献，相较 Planner 直接分发任务保留了可复现、安全、审计和赛题实验边界。它应当作为后续实现和测试的维护基线；若代码实现与本文产生差异，应先更新设计决定和原因，再修改实验 claim。

## 19. 2026-07-16 可实施性复核与环境决定

### 19.1 复核结论

本方案可以在当前 v2 上增量实施，且比直接放开四个 Agent 更合理。成立的依据是：

- `RuntimeWorkflowStep`、`RuntimeTaskSession`、`RuntimeReplanRecord` 已能承载步骤、依赖、重试和重规划记录；
- `RuntimeSupervisor` 已有稳定生命周期、ACK、heartbeat、timeout、trap 和 cancel；
- `FallbackDag` 已能表达 retry、downgrade 和 skip；
- `WorkspaceManager`、`ExecutionArtifactRef` 和现有 validators 已提供候选输出到 verified artifact 的边界；
- `RetrieverFanoutPipeline`、memory/replay、StateRef 和 telemetry 可以作为 adaptive capability 的执行基础；
- 当前角色 Prompt、Driver 输入和固定 CodeAct 的限制均有清晰源码位置，可以保留 strict 路径并新增独立 adaptive 入口。

因此，不需要重写 v2，也不应删除当前固定链。正确做法是按 P1-A 至 P1-F 增加合同、shadow、adaptive Driver、DSL 和消费审计，再进入第二阶段 CodeAct。

### 19.2 必须遵守的四个实施条件

1. 现有 `RuntimeDriver.run()` 和 strict benchmark 行为保持兼容；adaptive 使用新增 `run_adaptive()`。
2. Planner 只产生 proposal，实际 dispatch 必须来自 policy-approved plan 和 capability grant。
3. 第一阶段只运行确定性 capability 和 Transform DSL，不执行 LLM Python。
4. 第二阶段 LLM Python 必须通过真实 bwrap readiness probe；只有 root 用户并不足够。

### 19.3 当前容器事实

静态与轻量诊断得到：

- 容器 `statebus-dev-qcrs` 当前以 `user=0:0` 运行；
- 容器使用 host network，因此宿主机 vLLM 的 `http://127.0.0.1:53334/v1` 在容器内可达；
- local embedding 模型 `/statebus/models/Qwen3-Embedding-0.6B` 存在；
- `STATEBUS_EMBED_DEVICE=cuda:0` 的 local embedding preflight 通过；
- 当前容器安装了 bubblewrap 0.8.0，但没有通过 `docker/compose.bwrap.yaml` 获得 namespace capability；
- 当前容器中执行 bwrap 返回 `Creating new namespace failed: Operation not permitted`。

所以第二阶段 live CodeAct 不能在当前 core 容器直接运行。必须从宿主机使用：

```bash
docker compose \
  -f docker/compose.yaml \
  -f docker/compose.root.yaml \
  -f docker/compose.bwrap.yaml \
  up -d --force-recreate statebus-dev
```

然后以 root 进入并激活：

```bash
docker exec -it -u 0 statebus-dev-qcrs bash
source /workspace/statebus/project/docker/activate_statebus_container.sh
```

### 19.4 第二阶段 sandbox 的最终决定

短期实现使用“root 外层容器 + bwrap 内层降权”：

- 外层容器使用仓库已有 root+bwrap compose profile；
- Runtime 不以 `shutil.which("bwrap")` 作为 ready 结论，而要执行最小 namespace probe；
- LLM code path 设置 `require_bwrap=True`；probe 或执行失败时不回退 resource/none；
- bwrap 内使用独立 user namespace，并将生成代码进程降到非 root UID/GID；
- bwrap 内禁止网络、清空环境、只读系统运行时、只挂载当前 attempt workspace；
- LLM 生成代码不挂载整个项目源码；确需公共 helper 时只挂载版本化、只读、最小 helper 包；
- attempt workspace 在执行前由 root Runtime 创建并赋予 sandbox UID 必要的最小写权限；
- 输出仍必须经过 AST、路径、schema、artifact 和质量 validator。

若 bwrap 内降权与当前 workspace 权限发生冲突，优先修正 per-attempt 目录 owner/mode，不允许因此让生成代码保持 root 身份。

长期更强方案是把 CodeAct executor 拆成独立 sandbox worker/service，让主 Runtime 保持普通用户和无额外 capability。该拆分不作为本轮第一、第二阶段的前置条件，但应作为生产化后续工作；不得把 root+bwrap 开发 profile宣传为完整生产隔离。

### 19.5 GPU 和模型分配

当前宿主机 GPU 2 空闲度最高，且 `/data/models/Qwen3-32B` 存在。建议：

- vLLM Qwen3-32B：宿主机物理 GPU 2，端口 53334；
- StateBus local embedding：容器 `cuda:0`，避免与 GPU 2 上的 vLLM 争用；
- vLLM base URL：`http://127.0.0.1:53334/v1`；
- health URL：`http://127.0.0.1:53334/health`；
- metrics URL：`http://127.0.0.1:53334/metrics`；
- served model：`qwen3-32b`。

### 本章结论

方案有效，但第二阶段的真实安全门槛是“root+bwrap compose capability + namespace probe + sandbox 内降权”，而不是简单判断当前用户是否为 root。第一阶段可以在现有容器完成；第二阶段代码可以先实现和做确定性测试，live LLM CodeAct 只在重建后的 bwrap profile 中验收。
