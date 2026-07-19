# StateBus v2 受限自适应 Runtime 与 LLM CodeAct 正式闭环优化实施计划

> 状态：待实施的新基线
>
> 日期：2026-07-17
>
> 适用范围：`v2/`、`tests/v2/`、`scripts/v2_diagnostics/` 与对应 benchmark/audit 入口
>
> 参考基线：
> - `docs/improvement/23_bounded_adaptive_agent_runtime_20260716/00_design_and_implementation_plan_zh.md`
> - `docs/improvement/23_bounded_adaptive_agent_runtime_20260716/01_implementation_prompt_zh.md`
>
> 本文不推翻 23 号方案。它基于 2026-07-17 的代码与运行产物重新核对完成度，专门解决“此前做了什么、为什么正式 25-case 没体现、接下来怎样把 adaptive 与 LLM CodeAct 接入真实主路径并形成可审计证据”。

## 1. 结论先说

此前增强并非没有实现。当前仓库已经完成了两组重要基础能力：

1. 第一阶段的受限自适应基础设施基本落地：
   - adaptive 合同、Capability Registry、Domain Pack；
   - Planner 提案与程序审批；
   - multi-query Retriever 与 coverage verifier；
   - adaptive ready-queue、CapabilityGrant、受限 replan；
   - Transform DSL、ClaimSet、StateConsumptionRecord；
   - 一次四角色 local-vLLM、local embedding、无 fallback 的 adaptive smoke。
2. 第二阶段的独立 LLM CodeAct 执行器已经落地：
   - 代码生成合同；
   - 代码提取与 AST policy；
   - 一次 repair；
   - bwrap readiness、非 root 执行、网络隔离和 fail-closed；
   - 输出 schema 检查、ArtifactRef 签发和独立 live smoke。

真正未完成的是最后一段正式接线：

```text
真实 EvidencePack
  -> 可追溯的结构化执行输入
  -> adaptive capability dispatcher
  -> DSL 或 LLM CodeAct
  -> capability 质量验证
  -> verified ArtifactRef
  -> ClaimSet
  -> benchmark / audit
```

当前 25-case Compare 仍走保留的 `strict_fixed` 路径，这是 23 号方案要求的兼容结果，不代表新增能力不存在。但它也意味着不能用该结果证明 adaptive DAG 或 LLM 生成代码。

本轮正确顺序不是“先重复跑大实验”，而是：

```text
冻结既有 strict 证据
  -> 先补可观测性与质量门
  -> 接通真实数据和正式 dispatcher
  -> 接入 LLM CodeAct
  -> 扩大有限决策空间
  -> 三任务轻量 live gate
  -> 小规模 adaptive 对照
  -> 最后才运行 formal 25-case 与 serialized repeats
```

## 2. 2026-07-17 当前实现复核

### 2.1 已经真实实现的内容

| 能力 | 当前代码 | 当前事实 |
| --- | --- | --- |
| Adaptive 合同 | `v2/contracts/adaptive.py` | `WorkflowMode`、Plan、Evidence、DSL、Claim、Grant 等合同已存在 |
| CodeAct 合同 | `v2/contracts/llm_codeact.py` | generation、policy、candidate、repair、execution record 已存在 |
| Capability Registry | `v2/runtime/capability_registry.py` | 注册、查询、公开 surface、digest 已存在 |
| Domain Pack | `v2/runtime/domain_packs.py` | `long_doc_analysis_v1` 及 DSL/LLM Python 能力已注册 |
| Plan Policy | `v2/runtime/plan_policy.py` | DAG、预算、类型、权限、completion criteria 与 LLM Python 开关已校验 |
| Adaptive Driver | `v2/runtime/adaptive_runtime.py`、`v2/runtime/driver.py` | ready-step、Grant、ACK、失败、replan、telemetry 已存在 |
| Adaptive Retriever | `v2/runtime/retrieval_adapter.py`、`v2/runtime/evidence_coverage.py` | multi-query、稳定 fan-in、coverage、一次扩展已存在 |
| Transform DSL | `v2/runtime/transform_dsl.py` | program 校验、解释执行、schema/quality gate、ArtifactRef 已存在 |
| Claim 验证 | `v2/runtime/claims.py` | 证据、locator、数值 artifact、task/session 绑定已存在 |
| State 消费审计 | `v2/runtime/state_consumption.py` | 读取字段、前后决策面和 behavioral effect 已存在 |
| Adaptive 角色 Prompt | `v2/runtime/role_path.py` | Planner、Retriever、Executor DSL、Summarizer 与 citation repair 已存在 |
| LLM CodeAct Runner | `v2/runtime/llm_codeact.py` | extract、AST、repair、bwrap、schema、cache、ArtifactRef 已存在 |
| LLM bwrap | `v2/runtime/codeact_sandbox.py` | readiness、最小挂载、无网络、非 root、fail-closed 已存在 |

当前相关的定向测试已经覆盖合同、Policy、Driver、Retriever、DSL、Claim、Prompt、CodeAct policy 和 bwrap。2026-07-17 复核时，两组容器内定向回归共通过 107 项测试；这说明基础模块不是空壳，但不等于正式端到端闭环已完成。

### 2.2 当前 live 证据实际证明什么

#### Adaptive smoke

当前成功产物证明：

- Planner 由 `qwen3-32b` 生成计划，Policy 首次批准；
- Retriever 由模型生成 3 个 query；
- Executor 由模型生成 `select + sort` Transform DSL；
- Summarizer 由模型生成 ClaimSet；
- 三个 step 均由 Runtime 签发 Grant 并完成；
- local embedding 参与 rerank，`behavioral_effect=changed`；
- Planner、Retriever、Executor、Summarizer 均无 fallback。

它尚未证明：

- Executor 输入来自 Retriever 真实投影后的结构化数据；
- 模型能在多个合法 capability 之间稳定选择不同 DAG；
- LLM CodeAct 已成为 adaptive Executor 的一种正式 execution kind；
- 新路径已覆盖多任务或 25-case。

#### LLM CodeAct smoke

当前成功产物证明：

- local vLLM 确实返回 Python source；
- source 经过 AST policy；
- 代码在 bwrap 中以 UID/GID 65534 执行；
- sandbox backend 为 bwrap，无 resource/none fallback；
- 输出 JSON schema 合法并产生 verified ArtifactRef。

它尚未证明：

- `AdaptiveRuntimeEngine` 会依据 approved `LLM_BOUNDED_PYTHON` step 调用该 runner；
- 输出业务数值经过 capability 级复算；
- Prompt 不依赖可复制的完整代码模板；
- 多种任务产生不同代码并保持正确。

#### 25-case Compare

当前 25-case 结果真实证明：

- formal registry 25 cases / 5 families；
- StateBus 与 external pure-text comparator 均 25/25；
- StateBus prompt tokens、total tokens 和控制面 bytes 更低；
- memfd 语义状态传递与固定 CodeAct bwrap 路径运行成功。

它不证明 adaptive 或 LLM CodeAct，因为正式 Compare 仍调用 `RuntimeDriver.run()`、固定四步 workflow 和 `CodeActRunner`。保留 strict 路径本身是正确的；问题只是不能把 strict 证据归因给新 adaptive 改造。

### 2.3 当前最关键缺口

| 优先级 | 缺口 | 影响 |
| --- | --- | --- |
| P0 | adaptive smoke 的 Executor 输入仍由诊断脚本写死 | 不能证明 Retriever 到 Executor 的真实数据因果链 |
| P0 | LLM CodeAct schema 通过后直接标记 `output_quality_valid=True` | 格式正确但数值错误也可能成为 verified artifact |
| P0 | `LlmCodeActRunner` 没有正式 Runtime 调用者 | CodeAct 是独立能力，不是 Agent 工作流能力 |
| P1 | Adaptive Engine 依赖外部 `execute_step` callback，没有正式 capability dispatcher | 诊断脚本承担了本应属于 Runtime 的执行逻辑 |
| P1 | Planner smoke 只看到每个角色一个主要能力 | DAG 合法但决策空间接近唯一 |
| P1 | `--all` 不包含 LLM CodeAct stage | 完整 audit 不能一次验证第二阶段 |
| P2 | 当前 live CodeAct Prompt 给出完整可复制形状 | 只能证明链路，不能证明代码生成泛化 |
| P2 | 只有一个 adaptive live task 和一个 identity CodeAct task | 不能判断跨任务稳定性 |

### 2.4 优化前后到底改变什么

| 维度 | 当前实现 | 本计划完成后 | 仍然不允许 |
| --- | --- | --- | --- |
| Planner | 能生成合法 DAG，但 live surface 接近唯一解 | 在同一 Domain Pack 内从多个检索、DSL、Python、报告 capability 中提出 2–6 步计划 | 直接调 Agent、注册工具、修改权限和 validator |
| Retriever | 能生成 query 和 rerank，但执行输入没有正式由 EvidencePack 投影 | query、coverage、gap request 真实决定后续 typed Artifact，并保留逐行 locator | 扩大 corpus、实体、时间范围和预算 |
| Executor DSL | LLM 能生成 DSL，但 smoke 使用脚本写死的两行输入 | DSL 只读取已验证上游 Ref，程序和输入 hash 都进入 Artifact lineage | 任意文件、任意操作符和未注册输出合同 |
| Executor CodeAct | Runner、AST、repair、bwrap 和独立 smoke 已有 | approved Python step 经 Grant 和 Dispatcher 正式触发 Runner，输出再经业务复算 | shell、联网、安装依赖、宿主 Python fallback |
| Summarizer | 能生成 ClaimSet 并接受 citation 校验 | 只消费 verified Evidence/Artifact，数值必须与 quality report 一致 | 改写数值、伪造 locator、提交未验证工件 |
| Runtime | Adaptive Engine 依赖诊断脚本提供业务 callback | 正式 Dispatcher 按 `ExecutionKind` 执行注册 handler，诊断脚本只负责组装与启动 | 让模型成为权限签发者或副作用执行者 |
| 实验 | strict 25-case 证明效率；两个独立 smoke 证明局部机制 | strict 效率、adaptive 因果、CodeAct 接入分别形成可归因证据 | 用 strict 结果声称 adaptive/CodeAct 已提升 |

这里增加的是模型对“计划、检索表达、执行配方和代码”的决定权，不是对文件、网络、工具注册或验收规则的控制权。最终目标也不是提高 Python 使用率，而是证明：任务变化时，模型能够在多个合法方案中作出不同且有效的选择，这个选择真实改变下游产物，并能被控制层复算和审计。

## 3. 本次优化目标与非目标

### 3.1 必须实现的目标

1. 保留 `strict_fixed` 的现有行为和既有 benchmark 结论。
2. 让 adaptive bounded 模式从真实 EvidencePack 开始，形成完整数据因果链。
3. 将 `ExecutionKind` 变成正式 Runtime dispatcher 的实际分支，而不只停留在 registry 字段。
4. 将 `LlmCodeActRunner` 接入 approved plan、Grant、workspace、validator 和下游 Summarizer。
5. 先完成 capability 质量验证，再允许 LLM 代码产物成为 verified artifact。
6. 扩大模型在计划、检索和执行配方上的有限自由度，同时不扩大文件、网络、工具注册和沙箱权限。
7. 新增足够的 telemetry 和 artifact，使每个 LLM 决策是否影响下游可以被复算。
8. 先通过三个不同任务的轻量 live gate，再进入 formal 实验。

### 3.2 明确非目标

- 不把 Planner 改成可以直接调用其他角色的进程主控。
- 不允许模型动态注册 capability、安装依赖或改变 validator。
- 不开放 shell、网络、任意文件读取或工作区外写入。
- 不把 LLM CodeAct 强制用于所有任务；DSL 可表达时优先 DSL。
- 不改写历史 25-case 结果，不把新路径冒充为旧实验的一部分。
- 不在实现阶段自动运行 25-case、连续十轮或 serialized repeat 大实验。
- 不把 root+bwrap 开发 profile 宣称为生产级隔离。

## 4. 目标正式架构

```text
CanonicalTaskSpec
  -> AdaptiveTaskEnvelope（程序生成权限与预算）
  -> Planner LLM 生成 PlanProposal
  -> PlanPolicyValidator
  -> ApprovedPlan
  -> AdaptiveRuntimeEngine ready queue
       -> CapabilityGrant
       -> AdaptiveCapabilityDispatcher
            -> RETRIEVAL_ADAPTER
                 -> EvidenceRequest
                 -> RetrieverFanoutPipeline
                 -> EvidenceCoverageVerifier
                 -> verified EvidencePack
            -> TRANSFORM_DSL
                 -> EvidenceProjectionAdapter
                 -> TransformProgram
                 -> TransformDslInterpreter
                 -> capability quality validator
                 -> verified ExecutionArtifactRef
            -> LLM_BOUNDED_PYTHON
                 -> verified input ArtifactRef
                 -> CodeGenerationRequest
                 -> Executor LLM source
                 -> AST / repair / bwrap
                 -> schema + capability quality validator
                 -> verified ExecutionArtifactRef
            -> RUNTIME_BUILTIN
                 -> conflict / deterministic verifier / report helper
       -> Summarizer LLM 生成 ClaimSet
       -> ClaimSetValidator
       -> verified cited report
  -> telemetry / ledger / benchmark report
```

角色仍不互相直接调用。Planner 是语义计划者，Driver 是唯一调度者，Dispatcher 是 capability 执行边界，Validator 是最终事实裁决者。

## 5. 核心设计决定

### 5.1 先补证据能力，后补实验证据

“先补证据”分为两件事：

1. 先补可观测性、数据 lineage 和质量门，这是实现前置条件；
2. 后跑大实验，这是所有接线完成后的最后阶段。

当前不应先重复 formal Compare。否则只会再次证明 strict 路径，而不是新增自主性。

### 5.2 不新造第二套 Ref 类型

投影后的表格、CodeAct 输入和执行输出继续使用 `ExecutionArtifactRef`。`StateRef` 仍用于 embedding/语义状态，不与 ArtifactRef 合并。

建议新增的是小型报告合同，而不是新 Ref 大类：

- `EvidenceProjectionRequest`
- `EvidenceProjectionReport`
- `CapabilityQualityReport`
- `AdaptiveExecutionAudit`

### 5.3 自由度放在提案和配方，副作用继续受控

模型可以决定：

- 合法 capability 的组合；
- 2 至 6 个步骤及依赖；
- 检索 query、优先级和一次补检索建议；
- DSL 操作组合；
- 在被授权时生成 bounded Python；
- Claim 的组织和证据不足声明。

模型不能决定：

- capability 是否注册；
- 输入 Ref 是否 verified；
- sandbox backend；
- 文件和网络权限；
- validator 规则；
- budget、Grant 和重规划次数；
- 输出是否可以提交或进入记忆。

### 5.4 CodeAct 是可选执行能力，不是自治程度指标

对于 `select/group_by/aggregate/sort/join` 等标准操作，DSL 更稳定、更易复算。只有任务需要 DSL 未覆盖的纯计算时，Planner 才能提议 `LLM_BOUNDED_PYTHON`。

评估自主性应看模型是否在多个合法方案中作出影响下游的决定，而不是看是否每次都生成代码。

## 6. 新增与扩展合同

### 6.1 `EvidenceProjectionRequest`

建议字段：

| 字段 | 含义 |
| --- | --- |
| `task_id/session_id/step_id` | 绑定当前执行 |
| `evidence_pack_ref_id` | 已验证证据包 |
| `requested_fields` | capability 允许提取的字段 |
| `allowed_evidence_types` | table/semantic_context 等闭集 |
| `required_locator` | 是否要求 locator |
| `output_contract_version` | 投影数据合同 |
| `projection_policy_version` | 稳定版本 |

### 6.2 `EvidenceProjectionReport`

至少记录：

- 输入 EvidencePack hash；
- 实际读取的 EvidenceItem ID；
- 每行来源 EvidenceItem 与 locator；
- 输出字段、行数、类型；
- 缺失字段、冲突和拒绝原因；
- 输出 ArtifactRef；
- report hash。

### 6.3 `CapabilityQualityReport`

至少记录：

- capability ID 与 validator ID；
- input artifact hashes；
- output artifact hash；
- schema pass；
- recomputation pass；
- provenance pass；
- completion criteria pass；
- 错误码和数值差异；
- 最终 `verified/invalidated`。

### 6.4 `AdaptiveExecutionAudit`

用于连接模型决策和下游结果：

- proposal hash 与 approved plan hash；
- selected capability IDs；
- query/program/source hashes；
- Grant hashes；
- evidence -> input artifact -> output artifact -> claim set hash 链；
- fallback、repair、replan；
- `model_decision_behavioral_effect`。

所有合同必须稳定序列化，并有 schema version、round-trip 与 digest 测试。

## 7. 分阶段实施计划

## P0：冻结基线并补齐因果指标

### 目标

不改变行为，先使后续新路径能够被识别和复算。

### 代码修改

| 文件 | 修改 |
| --- | --- |
| `v2/contracts/adaptive.py` 或新审计合同文件 | 增加 projection/quality/execution audit 合同 |
| `v2/runtime/telemetry.py` | 增加 adaptive/CodeAct 事件和聚合字段 |
| `v2/runtime/session.py` | 保存 plan、Grant、projection、quality、source 和 claim hash |
| `v2/benchmark/report.py` 及聚合位置 | 输出 workflow/execution kind/CodeAct 指标 |

### 必须新增的指标

```text
adaptive_plan_model_used
adaptive_plan_changed_execution
adaptive_selected_capability_count
adaptive_capability_grant_count
adaptive_replan_count
retriever_model_query_count
retriever_query_changed_candidate_set_count
evidence_projection_count
evidence_projection_failure_count
dsl_execution_count
llm_codeact_generation_count
llm_codeact_repair_count
llm_codeact_execution_count
llm_codeact_verified_count
llm_codeact_quality_rejected_count
llm_codeact_sandbox_fallback_count
model_fallback_count
```

### 测试

- 指标默认值不改变 strict report；
- adaptive event 聚合稳定；
- source hash 或 plan hash 缺失时不能标记 model-path success；
- strict 历史 JSON loader 仍兼容。

### 完成门

旧 strict 单测全部通过；还不运行 live 或 benchmark。

## P1：真实 EvidencePack 到执行输入的投影

### 目标

移除 adaptive smoke 中写死的两行收入数据，使 Executor 输入只能来自已验证 EvidencePack 或上游 ArtifactRef。

### 建议新增文件

```text
v2/runtime/evidence_projection.py
tests/v2/test_evidence_projection.py
```

### 输入

- 当前 task/session；
- verified EvidencePack；
- capability descriptor；
- approved step；
- Grant；
- requested fields。

### 处理逻辑

1. 校验 EvidencePack task、session、hash 和 Ref 状态。
2. 只读取 capability 允许的 EvidenceItem 类型。
3. 使用结构化字段或正式 parser 提取表格，禁止在 dispatcher 中用临时字符串切分。
4. 将每行绑定到 EvidenceItem ID 与 locator。
5. 统一类型，发现冲突时生成明确错误。
6. 写入 attempt workspace 的固定输入路径。
7. 生成 candidate ArtifactRef。
8. schema、lineage 和 completion criteria 通过后标记 verified。

### 输出

- typed rows artifact；
- EvidenceProjectionReport；
- consumed evidence IDs；
- projection hash。

### 测试

- 修改样本文档中的数值后输出同步变化；
- 缺字段、错误类型、无 locator、跨 task Ref、冲突值全部拒绝；
- 输出排序和 hash 稳定；
- 诊断脚本不再出现预期收入常量。

### 完成门

使用 deterministic role stub 跑通 Retriever -> projection -> DSL -> Artifact，且输出由样本文件决定。

## P2：Capability Validator Registry

### 目标

避免 LLM CodeAct “格式正确即 verified”，并让 DSL 与 Python 共享同一业务质量门。

### 建议新增文件

```text
v2/runtime/capability_validators.py
tests/v2/test_capability_validators.py
```

### 第一批 validator

| Validator | 检查内容 |
| --- | --- |
| metric series | 行数、字段、数值来源、时间键唯一 |
| period comparison | 差值、比率、增长率复算 |
| aggregation | 从输入重新 group/aggregate |
| join | join key、输入覆盖、重复键策略 |
| anomaly | 阈值、基线统计量与异常集合复算 |
| conflict | 冲突数与来源证据一致 |
| cited report | numeric field、ArtifactRef、EvidenceItem、locator 一致 |

### `LlmCodeActRunner` 修改

`execute()` 必须接收或从 registry 取得 validator，执行顺序改为：

```text
output file gate
  -> JSON/schema/type/finite
  -> capability validator
  -> provenance validator
  -> completion criteria
  -> verified ArtifactRef
```

禁止在没有质量报告的情况下设置 `output_quality_valid=True`。

### 测试

- 正确 schema、错误数值必须 invalidated；
- 正确聚合通过；
- 缺 provenance 拒绝；
- validator 未注册时 fail-closed；
- DSL 与 LLM Python 对同一输入使用相同 validator，结果一致。

### 完成门

新增“格式正确、答案错误”的回归测试，并证明不会产生 verified ArtifactRef。

## P3：正式 `AdaptiveCapabilityDispatcher`

### 目标

把当前诊断脚本中的 `execute_step` 业务分支迁入 Runtime 所有的正式 dispatcher。

### 建议新增文件

```text
v2/runtime/adaptive_dispatcher.py
v2/runtime/adaptive_execution.py
tests/v2/test_adaptive_dispatcher.py
```

### Dispatcher 输入

- `AdaptiveTaskEnvelope`；
- `ApprovedPlan` 当前 step；
- `CapabilityGrant`；
- registry snapshot；
- verified input refs；
- task/session workspace；
- role adapter；
- validator registry。

### Dispatcher 分支

```text
RETRIEVAL_ADAPTER  -> AdaptiveRetrievalAdapter
TRANSFORM_DSL      -> EvidenceProjectionAdapter + Executor LLM + DSL interpreter
LLM_BOUNDED_PYTHON -> EvidenceProjectionAdapter + Executor LLM + LlmCodeActRunner
RUNTIME_BUILTIN    -> developer-registered deterministic handler
```

### 关键规则

- Dispatcher 不自行选择 capability，只执行 approved step。
- 每个 handler 在产生副作用前重新校验 Grant。
- 输入只来自 Grant allowlist 和已完成依赖的 output refs。
- handler 返回统一的 `AdaptiveStepResult`。
- 诊断脚本只构造 task、registry 和 role client，不保留业务执行逻辑。

### 测试

- 四种 execution kind 的 dispatch；
- 未知 execution kind、错误角色、过期 Grant、跨 attempt Ref 在副作用前拒绝；
- Runtime ready queue 与 dispatcher 集成；
- replan 只替换未执行子图；
- strict `RuntimeDriver.run()` 不经过 dispatcher。

### 完成门

原 adaptive smoke 改为调用正式 dispatcher，诊断脚本中不再有按 role 手写的执行主体。

## P4：LLM CodeAct 正式接线

### 目标

让 approved `LLM_BOUNDED_PYTHON` step 真正触发 Executor LLM 生成代码并进入 `LlmCodeActRunner`。

### 正式调用链

```text
PlanProposal 选择 registered llm capability
  -> Policy 检查 allow_llm_python、risk、budget、fallback
  -> ApprovedPlan
  -> Runtime 签发 Grant
  -> Dispatcher 构造 CodeGenerationRequest
  -> role_path Executor 生成 source
  -> LlmCodeActRunner
  -> AST / repair / bwrap
  -> capability validator
  -> ArtifactRef
```

### 启用条件

必须同时满足：

- descriptor 为 `LLM_BOUNDED_PYTHON`；
- envelope risk class 为 `BOUNDED_CODE`；
- `allow_llm_python=True` 来自程序配置，不来自模型；
- bwrap readiness 通过；
- capability validator 已注册；
- 输入 Ref 全部 verified；
- fallback capability 已注册；
- attempt workspace 为空且独立。

### Prompt 修改

保留输入/输出路径别名、schema、允许模块和禁用行为，但移除完整可复制答案模板。Prompt 只给：

- 任务目标；
- 输入 schema 和小型非答案示例；
- 输出 schema；
- quality constraints；
- 固定路径别名；
- 允许库和禁止行为。

### Fallback

- AST/repair/quality 失败：只允许回退到 descriptor 指定的 DSL/确定性 capability；
- bwrap 不 ready：不执行 LLM 代码；
- 禁止回退 resource、none 或宿主 Python；
- fallback 也必须重新签发对应 capability 的 Grant，不能复用 Python Grant。

### 测试

- approved Python step 的真实 dispatcher 调用；
- policy disabled、risk 不符、validator 缺失、bwrap 不 ready 全部 fail-closed；
- repair 最多一次；
- fallback 重新授权；
- source、policy、sandbox、quality、artifact hash 全链可追踪。

### 完成门

一个 deterministic LLM stub 集成测试和一个 local-vLLM live smoke 都必须从 `RuntimeDriver.run_adaptive()` 进入 `LlmCodeActRunner`，不能直接调用 runner 冒充 Runtime 接入。

## P5：扩大有限决策空间

### 目标

让 Planner 和 Executor 面对多个真实合法选择，而不是每个角色只有一个 capability。

### Domain Pack 扩展

第一批仍限定离线财报、经营指标、长文档表格：

```text
retrieve_semantic_evidence_v1
retrieve_table_evidence_v1
retrieve_memory_assist_v1

extract_metric_series_v1
compare_periods_v1
aggregate_metrics_v1
join_metric_tables_v1
detect_anomaly_v1
detect_conflict_v1
bounded_metric_python_v1

compose_cited_report_v1
compose_comparison_report_v1
compose_risk_memo_v1
```

### Planner 自由度

允许 Planner 决定：

- 2 至 6 个步骤；
- table/semantic/memory 检索组合；
- 是否增加 compare、aggregate、join、anomaly、conflict；
- DSL 或 bounded Python；
- 依赖和 completion criteria；
- 一次补检索建议。

不要再要求每个可见 capability 都出现。任务级 required roles 可以保留，但应给同一角色多个合法 capability。

### Retriever 自由度

- 1 至 4 个 query；
- query 优先级；
- table/semantic evidence 类型；
- 一次 gap query；
- approved corpus 内重排策略。

实体、时间范围、corpus 和最大预算继续由 Controller 注入。

### Executor 自由度

- DSL 路径允许 select、filter、sort、group_by、aggregate、join、derive、compare、anomaly_check；
- Python 路径允许在固定 schema 内选择算法；
- 不允许改变输出合同、输入 Ref 或 validator。

### Summarizer 自由度

- 组织 fact/inference/risk；
- 在证据不足时返回 `missing_citation`；
- 提出一次补证据需求，但由 Controller 决定是否执行；
- 不修改 verified 数值。

### 测试

- 同一任务至少存在两个合法 plan；
- 不同任务选择不同 capability/DAG；
- Policy 拒绝不必要的 Python 或越权路径；
- DSL 足够时允许选择 DSL，不以 Python 使用率作为成功门。

### 完成门

三个轻量任务至少产生两个不同 approved plan hash、两个不同执行配方，并全部通过质量门。

## P6：三任务轻量 live gate

### 任务设计

| 任务 | 主要能力 | 目的 |
| --- | --- | --- |
| 两期指标比较 | retrieve + extract + compare + cited report | 验证多步 DAG 和数值复算 |
| 分组经营指标聚合 | retrieve + aggregate + comparison report | 验证 DSL 组合 |
| 异常检测 | retrieve + bounded Python 或 anomaly DSL + risk memo | 验证 LLM CodeAct 正式接入 |

### 约束

- 输入必须来自 repo-local formal/dev 样本；
- 预期答案不能进入 Prompt；
- oracle 只在 validator 侧使用；
- local embedding 固定；
- local vLLM 固定；
- 每个任务保存完整 role request、plan、Grant、projection、source/program、quality report 和 ClaimSet。

### 严格通过条件

- 三个任务全部完成；
- Planner/检索/执行/总结模型 fallback 为 0；
- sandbox fallback 为 0；
- output quality 全部通过；
- 至少两个不同 source/program hash；
- StateConsumptionRecord 至少有一个 `changed`；
- 任一错误数值扰动会被 validator 拒绝；
- CodeAct 任务必须从 Runtime dispatcher 进入，而不是独立 runner。

### 失败处理

失败时只修合同、Prompt、Policy、adapter 或 validator。不要通过把预期答案、真实文件路径或固定完整代码塞进 Prompt 来消除 fallback。

## P7：Audit 脚本与小规模对照

### Audit stage

扩展 `scripts/v2_diagnostics/run_v2_local_vllm_audit_gpu1.sh`：

```text
--preflight
--adaptive
--llm-codeact
--adaptive-matrix
--formal
--compare
--replay
--negative
--all
```

`--llm-codeact` 必须验证 Runtime 接线路径，不再只运行独立 identity smoke。

### 小规模模式矩阵

先运行 3 至 5 cases：

| 模式 | 用途 |
| --- | --- |
| `strict_fixed` | 稳定基线 |
| `adaptive_shadow` | 只看 Planner 提案质量 |
| `adaptive_bounded_dsl` | 验证计划、检索和 DSL 自主性 |
| `adaptive_bounded_codeact` | 验证受限 Python 接入 |

### 报告必须分开回答

1. 质量是否相同；
2. LLM 决策是否改变下游；
3. StateRef 是否改变决策；
4. CodeAct 是否生成并执行不同代码；
5. 开销增加在哪里；
6. fallback、repair 和拒绝率；
7. 哪些结果可以用于赛题主 claim，哪些只是机制证明。

### 完成门

小矩阵通过后才允许进入 P8；任何模式不得借用其他模式的产物冒充成功。

## P8：正式实验，必须最后执行

### 赛题核心效率实验

继续使用：

```text
StateBus strict_fixed vs external pure text
```

它负责证明结构化通信、StateRef 和 token/bytes 优势，不负责证明 adaptive 或 CodeAct。

### Adaptive 因果实验

对同一任务集比较：

```text
strict_fixed
adaptive_shadow
adaptive_bounded_dsl
adaptive_bounded_codeact
adaptive_bounded_with_model_decisions_replaced_by_deterministic_controls
```

### 必须增加的消融

- StateRef 正常、关闭、扰动 embedding；
- Planner proposal 正常、固定 fallback plan；
- Retriever model query、固定 query；
- Executor model program/code、确定性 program；
- CodeAct enabled、DSL-only；
- memory assist 正常、关闭。

### 运行要求

- 先 5-case；
- 再 25-case；
- latency claim 至少 serialized repeat 3；
- 每次 run 使用独立目录；
- 不并发启动 formal API run；
- 质量门不通过的 run 不进入效率 headline；
- completion token 增加必须单独披露。

## 8. 详细文件修改表

| 文件/目录 | 动作 | 主要内容 |
| --- | --- | --- |
| `v2/contracts/adaptive.py` | 扩展 | projection、quality、execution audit 合同或导出对应新文件 |
| `v2/contracts/llm_codeact.py` | 扩展 | 绑定 validator、completion criteria、quality report |
| `v2/runtime/evidence_projection.py` | 新增 | EvidencePack 到 typed Artifact 的正式 adapter |
| `v2/runtime/capability_validators.py` | 新增 | DSL/Python 共享的业务质量 validator registry |
| `v2/runtime/adaptive_dispatcher.py` | 新增 | 按 ExecutionKind 调度正式 handler |
| `v2/runtime/adaptive_execution.py` | 新增或合并 | handler context、Ref 解析、统一 StepResult |
| `v2/runtime/adaptive_runtime.py` | 修改 | 接入 dispatcher，不内置业务逻辑 |
| `v2/runtime/driver.py` | 小改 | 保留 strict；adaptive 接收正式 dispatcher/context |
| `v2/runtime/llm_codeact.py` | 修改 | 质量 validator、provenance、fallback 重新授权 |
| `v2/runtime/transform_dsl.py` | 扩展 | group/aggregate/join/derive/anomaly 等受限操作 |
| `v2/runtime/domain_packs.py` | 扩展 | 多个真实合法 capability 与 validator ID |
| `v2/runtime/role_path.py` | 修改 | 扩大 surface；CodeAct Prompt 去答案模板；保留 schema |
| `v2/runtime/session.py` | 修改 | 保存完整 hash 链与执行审计 |
| `v2/runtime/telemetry.py` | 修改 | 新事件、新指标 |
| `v2/benchmark/live_runner.py` | 扩展 | adaptive 小矩阵入口，默认 strict 不变 |
| `scripts/v2_diagnostics/run_adaptive_agent_smoke.py` | 收缩 | 只构造任务和调用正式 Runtime，删除写死数据与业务分支 |
| `scripts/v2_diagnostics/run_llm_codeact_smoke.py` | 改造 | 改为正式 Runtime 接线 smoke，保留独立 runner probe 可另命名 |
| `scripts/v2_diagnostics/run_v2_local_vllm_audit_gpu1.sh` | 扩展 | 新增 llm-codeact/adaptive-matrix stage |
| `tests/v2/` | 新增/扩展 | projection、validator、dispatcher、runtime CodeAct、benchmark 指标 |

## 9. 测试环境：不可省略的执行条件

### 9.1 所有仓库 Python 和 pytest 必须在 Docker 中执行

目标容器：

```text
statebus-dev-qcrs
```

禁止在宿主机直接运行仓库 Python、pytest、diagnostic 或 benchmark。宿主机只负责：

- 编辑 bind-mounted 源码；
- Docker compose/exec/inspect；
- vLLM 服务；
- `curl`、`nvidia-smi` 和只读检查。

标准测试形式：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q TEST_PATHS
'
```

每次 Python 命令前都必须 source 激活脚本。

### 9.2 root+bwrap 容器基线

如容器不是 root+bwrap profile，使用：

```bash
cd /home/qcrs/statebus/project
docker compose \
  -f docker/compose.yaml \
  -f docker/compose.root.yaml \
  -f docker/compose.bwrap.yaml \
  up -d --force-recreate statebus-dev
```

外层 Runtime 可为 root；LLM 代码必须在 bwrap 内以 UID/GID 65534 运行。每次 live CodeAct 前执行真实 readiness，不得只检查 `which bwrap`。

### 9.3 local embedding

固定配置：

```text
STATEBUS_EMBEDDING_MODE=local
STATEBUS_EMBED_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B
STATEBUS_EMBED_DEVICE=cuda:0
```

宿主物理 GPU 通过 wrapper 的 `CUDA_VISIBLE_DEVICES` 映射后，容器内统一使用 `cuda:0`。不要在报告里把容器逻辑 GPU 编号和宿主物理 GPU 编号混写。

### 9.4 local vLLM

固定服务：

```text
STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1
STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b
```

Docker 使用 host network，容器可访问该地址。实现 Agent 不应擅自启动、停止或升级 vLLM；先只读检查：

```bash
curl -fsS http://127.0.0.1:53334/health
curl -fsS http://127.0.0.1:53334/v1/models
```

health 不可用时，确定性测试继续；live smoke 标记未运行，不能用 stub 冒充 live 成功。

### 9.5 GPU 分配

当前推荐：

- vLLM 使用用户已经启动的物理 GPU；
- embedding 由 audit wrapper 映射一张独立可用 GPU 到容器 `cuda:0`；
- 运行前检查显存；
- 不在实现阶段并发启动多个正式 local-vLLM benchmark。

具体物理 GPU 以用户当前服务和 `nvidia-smi` 为准，不把历史 GPU 编号硬编码进 Runtime。

## 10. 测试节奏与命令

### 10.1 每个子阶段

只运行对应单测，例如：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q \
    tests/v2/test_evidence_projection.py \
    tests/v2/test_capability_validators.py \
    tests/v2/test_adaptive_dispatcher.py \
    tests/v2/test_adaptive_codeact_integration.py
'
```

### 10.2 第一轮回归

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q \
    tests/v2/test_adaptive_contracts.py \
    tests/v2/test_adaptive_planner_policy.py \
    tests/v2/test_adaptive_driver.py \
    tests/v2/test_adaptive_retrieval.py \
    tests/v2/test_transform_dsl.py \
    tests/v2/test_adaptive_claims.py \
    tests/v2/test_adaptive_role_prompts.py \
    tests/v2/test_llm_codeact_policy.py \
    tests/v2/test_llm_codeact_sandbox.py
'
```

### 10.3 bwrap gate

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py
'
```

### 10.4 轻量 live gate

只在 vLLM health 正常后运行三个任务的 adaptive/CodeAct smoke。实现阶段不得自动运行 formal 25-case、连续十轮、replay 全套或 serialized repeats。

### 10.5 完整回归

所有轻量 gate 通过后再运行：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q tests/v2
'
```

正式大实验命令只在最终实施报告中给出，由用户决定何时运行。

## 11. 真实性与安全验收清单

### 数据真实性

- [ ] adaptive Executor 输入不含诊断脚本写死的业务答案；
- [ ] 修改样本数据会改变投影、Artifact 和 Claim；
- [ ] 每行能够追溯到 EvidenceItem 和 locator；
- [ ] 错误 schema 和错误数值均不能 verified。

### Agent 自主性

- [ ] Planner 面对多个合法 capability；
- [ ] 至少三个任务产生两个不同 plan；
- [ ] Retriever query hash 改变候选或覆盖结果；
- [ ] Executor DSL/source hash 真实进入 Artifact lineage；
- [ ] Summarizer ClaimSet 受 Evidence/Artifact 约束；
- [ ] 模型决定被固定控制替换后，下游行为差异可测。

### CodeAct

- [ ] `LlmCodeActRunner` 有正式 Runtime 调用路径；
- [ ] CodeAct step 由 ApprovedPlan 和 Grant 触发；
- [ ] Prompt 不包含完整答案代码；
- [ ] AST、repair、bwrap、schema、quality 全部可审计；
- [ ] bwrap 内 UID/GID 非 0、无网络；
- [ ] resource/none fallback 为 0；
- [ ] validator 未注册时 fail-closed；
- [ ] fallback 必须重新授权 DSL capability。

### 兼容性

- [ ] strict 默认路径不变；
- [ ] historical report loader 不回归；
- [ ] ExecutionArtifactRef 与 StateRef 继续分离；
- [ ] formal benchmark 默认仍是 offline financial/operating-metric tasks；
- [ ] 不修改或覆盖历史 runs。

## 12. 停止条件与风险控制

遇到以下情况必须停止当前子阶段并修复，不能靠扩大权限绕过：

- 输入无法从 EvidencePack 稳定投影；
- validator 无法独立复算结果；
- CodeAct 需要 repo 全量可写挂载；
- bwrap readiness 不稳定；
- 模型只有在看到完整答案模板时才能通过；
- adaptive 接入导致 strict 行为或质量回归；
- benchmark 无法区分 strict、adaptive、DSL 和 CodeAct。

回滚路径始终保留：

```text
adaptive_bounded_codeact
  -> adaptive_bounded_dsl
  -> strict_fixed
```

回滚不删除证据，不改写历史结果，只切换 workflow/capability policy。

## 13. 最终交付要求

实施完成后必须提交一份实现报告，至少包含：

1. 当前计划每个 P0-P8 阶段的完成状态；
2. 实际修改文件与关键调用链；
3. strict、adaptive、DSL、LLM CodeAct 的清晰边界；
4. 数据 lineage 与质量 gate 如何落地；
5. 所有容器内测试命令和结果；
6. live smoke 的 artifact 路径；
7. 未运行的大实验及用户可执行命令；
8. 仍未解决的风险和不能 claim 的内容。

不得只报告“测试通过”。必须回答：

- 模型具体决定了什么；
- 决定如何进入 Runtime；
- 哪个 validator 接受或拒绝了结果；
- 结果存在哪里；
- 如何证明没有使用写死答案或 fallback；
- 哪些提升属于 strict StateBus，哪些属于 adaptive/CodeAct。

## 14. 最终判断

此前改造的价值在于已经搭好了受限自适应控制平面和安全 CodeAct 执行内核，避免了从零开始。当前工作的重点不是重新设计四个 Agent，而是完成四个闭环：

```text
真实数据闭环
权限与调度闭环
CodeAct 质量闭环
实验归因闭环
```

完成这四个闭环后，系统才可以诚实地宣称：LLM 不只是填固定字段，而是在受控范围内提出计划、改变检索、生成执行配方或代码，并由 StateBus Runtime 审批、执行、验证和审计。
