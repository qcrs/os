# StateBus v2：一个真实任务如何流过四个 Agent

> 核对日期：2026-07-22
> 主例子：`semantic-holdout-s1`
> 证据来源：2026-07-20 的成功运行 artifact
> 文档定位：当前 v2 adaptive 主链的新人实现导读；代码与所列运行 artifact 才是事实依据

本例只讲这次 artifact 实际走通的路径：文本角色调用 + embedding semantic state +
CodeAct + 文本 Summarizer。当前分支中另有 latent-state 实验代码，但这份运行没有用它，
本文不会把它写成已经发生的 handoff。

这是一篇给第一次接触多 Agent、向量检索和 Runtime 的读者看的文档。阅读时不需要先
理解英文类名。本文会先使用中文名称，再在括号中标出代码名称。

本文只沿一条真实任务时间线回答五个问题：

1. `CanonicalTaskSpec` 和 `AdaptiveTaskEnvelope` 是什么关系？
2. 任务从什么时候开始结构化？
3. `step_id` 从哪里来，为什么叫 `execute-analysis`？
4. embedding 把哪段文本和哪段文本比较？
5. Retriever 到 Executor 到底传了什么，Executor 如何知道任务？

先给一句总答案：

> Controller 在任何 Agent 启动前建立任务语义、运行权限和权威数据；Planner 只提出
> DAG；Retriever 生成 query，Runtime 用 embedding 跨进程筛选证据；Executor 同时
> 使用任务合同、筛选后的证据和完整权威数据生成代码；Summarizer 最后消费已验证
> 结果和证据。

---

## 0. 阅读前先认识参与者

### 0.1 本项目中的 Agent 是什么

这里的 Agent 首先是一种“逻辑角色”，可以把它理解成：

~~~text
一套固定职责
+ 一份角色 prompt
+ 一组允许看到的输入
+ 一种规定好的输出格式
~~~

它不一定是一直运行的独立服务，也不表示四个 Agent 会互相建立网络连接。

一次角色调用通常是：

~~~text
Runtime 准备输入
  -> 调用该角色的 LLM
  -> LLM 返回 JSON 或代码
  -> Runtime 校验返回值
  -> Runtime 决定是否允许进入下一步
~~~

因此，图上写的“Retriever -> Executor”只是逻辑依赖。当前实现更准确的物理关系是：

~~~text
Retriever 返回结果
  -> Runtime 保存结果并登记 Ref
  -> Runtime 等待 Executor 变为 ready
  -> Runtime 给 Executor 签发 Grant
  -> Grant 中带上 Retriever 结果的 Ref
  -> Executor 通过 Runtime 读取该 Ref
~~~

Retriever 不会绕过 Runtime，直接把一段 Python 对象塞给 Executor。

### 0.2 四个 Agent 分别负责什么

| 角色 | 中文职能 | 它收到什么 | 它产生什么 | 它不负责什么 |
| --- | --- | --- | --- | --- |
| Planner | 规划员 | 任务目标、可选能力、角色数量、预算、允许使用的数据 Ref | 一份步骤草案 | 不检索、不执行代码、不调度步骤 |
| Retriever | 检索问题设计员 | 要找什么、允许查哪个 corpus、最多几条 query | 1 到 3 条检索问题 | 不直接给最终答案，不决定 Executor 怎么计算 |
| Executor | 执行员 | 具体目标、权威数据、筛选证据、输出规则 | Python 代码以及沙箱执行结果 | 不自行扩大数据权限，不决定结果是否可信 |
| Summarizer | 总结员 | 已验证执行结果、可引用证据 | 带引用的结论集合 | 不重新计算业务结果，不发明证据 |

下面逐个展开。

#### Planner：把任务拆成步骤

Planner 回答的是：

~~~text
需要哪几类步骤？
每一步选择哪个已注册能力？
谁必须等谁完成？
最终要输出哪种结果？
~~~

本例中它选择：

~~~text
先语义检索
  -> 再用受限 Python 分析
  -> 最后生成带引用的结论
~~~

Planner 的输出只是建议。Controller 会重建关键连线并进行检查。

#### Retriever：把任务改写成搜索问题

Retriever 回答的是：

~~~text
为了找到证据，应该问文档哪几个问题？
~~~

它本次输出三条英文 query。真正的文档切分、向量编码和相似度计算不是 LLM
Retriever 自己完成，而是本地 retrieval pipeline 完成。

#### Executor：根据受控输入完成计算或抽取

Executor 回答的是：

~~~text
在只能读取这些数据、只能写这个结果文件的条件下，
应该生成什么 Python 才能完成任务？
~~~

本例中它生成 Python，从七条权威 source row 中抽取两个事实。代码在
`bwrap` 沙箱执行，Runtime 再验证结果。

#### Summarizer：把结果写成可引用结论

Summarizer 回答的是：

~~~text
如何把已经验证的结果写成简洁结论？
结论引用哪个证据 ID、哪个原文位置、哪个执行产物？
~~~

它不能修改 Executor 已经验证的业务值。

### 0.3 哪些组件不是 Agent

| 组件 | 是不是 Agent | 作用 |
| --- | ---: | --- |
| Controller | 否 | 创建任务合同和权限边界，修正 Planner 连线，执行 policy 检查 |
| Runtime | 否 | 根据 DAG 调度、签发 Grant、登记和传播 Ref、记录 telemetry |
| retrieval pipeline | 否 | 切文档、调用 embedding 模型、构造候选 |
| selector worker | 否 | 在独立进程中读取向量矩阵并计算 top-k |
| sandbox | 否 | 在受限文件和系统权限下执行 Python |
| validator | 否 | 检查 schema、来源链、重算结果和引用是否合法 |

这里特别容易混淆：

> selector worker 虽然是独立进程，但它只是确定性计算组件，不是负责业务分析的
> Executor Agent。

### 0.4 先记住这些中文名称

后文会反复出现这些对象。先用中文理解即可：

| 本文中文名称 | 代码名称 | 一句话作用 |
| --- | --- | --- |
| 任务说明书 | `CanonicalTaskSpec` | 说明任务到底要做什么 |
| 运行许可证 | `AdaptiveTaskEnvelope` | 限制本次运行允许怎么做 |
| 数据提货单 | source `ExecutionArtifactRef` | 指向允许读取的权威数据 |
| 计划草案 | `PlanProposal` | Planner 提出的未批准步骤 |
| 批准计划 | `ApprovedPlan` | Controller 检查后 Runtime 可执行的 DAG |
| 单步通行证 | `CapabilityGrant` | 允许某一步在某次 attempt 中执行 |
| 检索请求单 | `EvidenceRequest` | 记录 query、检索范围和数量限制 |
| 向量状态提货单 | `SemanticStateRef` | 指向 shared memory 中的向量矩阵 |
| 证据包 | `CanonicalEvidencePack` | 保存选中的原文、分数和定位信息 |
| 执行结果提货单 | output `ExecutionArtifactRef` | 指向已验证的结果 JSON |
| 结论单 | `ClaimSet` | 保存最终结论及其证据引用 |

### 0.5 “传递”在代码中有四种不同形式

不要把所有箭头都理解成“发送一段文本”。

| 形式 | 传什么 | 本例 |
| --- | --- | --- |
| 同进程对象传递 | Python dataclass / dict | 任务说明书、运行许可证、批准计划 |
| LLM 请求与响应 | prompt 文本 + JSON/代码响应 | Planner、Retriever、Executor、Summarizer 调用 |
| Ref 传递 | 一个短 ID，真实数据由 Runtime 管理 | source Ref、EvidencePack Ref、artifact Ref |
| 跨进程二进制传递 | UDS 控制消息 + shared memory 数据 | 9 x 1024 float32 embedding 矩阵 |

#### Ref 到底是什么

Ref 可以理解为“受 Runtime 管理的提货单”。它不是数据本体。

例如：

~~~text
formal-source:semantic-holdout-s1
~~~

这个短字符串本身不包含七条 source row。Runtime 另外保存：

~~~text
这个 Ref 属于哪种对象
对象是否已经验证
对象存在哪里
对象应该有多大
对象内容的 hash 是什么
当前 step 是否有权读取它
~~~

接收方不能仅凭路径任意读文件，而是先提交 Ref；Runtime 验证类型、状态和授权后，
才解析到真实对象。

### 0.6 先看一遍不带字段的完整故事

~~~mermaid
flowchart TD
    U[任务：找运营区域和履约约束] --> C[Controller 准备任务说明书、运行许可证、数据提货单]
    C --> P[Planner 选择：检索 -> 执行 -> 总结]
    P --> V[Controller 修正连线并批准 DAG]
    V --> R[Retriever 生成 3 条搜索问题]
    R --> B[本地 pipeline 将问题和 8 个文档片段编码成向量]
    B --> W[独立 worker 从 shared memory 读取向量并选 top-3]
    W --> H[Runtime 把选中的 ID 恢复为 4 条唯一文本证据]
    H --> X[Executor 获得任务目标、权威数据和证据，生成并运行 Python]
    X --> Q[Runtime 验证结果，生成已验证结果提货单]
    Q --> S[Summarizer 使用结果和证据生成带引用结论]
~~~

后面的每一节只是把这张图中的一个箭头展开。

---

## 1. 先理清三个对象

`CanonicalTaskSpec`、`AdaptiveTaskEnvelope` 和 source
`ExecutionArtifactRef` 是 Controller 围绕同一任务创建的三个并列对象，不是
层层包含的关系。

~~~mermaid
flowchart LR
    M[原始任务记录] --> S[CanonicalTaskSpec<br/>要做什么]
    M --> E[AdaptiveTaskEnvelope<br/>本次允许怎么做]
    M --> A[ExecutionArtifactRef<br/>本次可以读什么]
    S --> H[spec_hash]
    H --> E
    H --> A
~~~

| 对象 | 回答的问题 | 主要字段 |
| --- | --- | --- |
| `CanonicalTaskSpec` | 任务要完成什么？ | `task_family`、`intent_op`、`required_outputs`、`arguments` |
| `AdaptiveTaskEnvelope` | 这次运行允许怎么完成？ | capability 白名单、角色数量、步骤/重试预算、风险等级 |
| source `ExecutionArtifactRef` | Executor 可以读哪份数据？ | artifact ID、路径、hash、验证状态 |

Envelope 不保存完整 Spec，只保存它的 hash：

~~~text
envelope.canonical_task_spec_hash == spec.spec_hash
~~~

`spec_hash` 不是 manifest 作者手写的答案字段，而是
`CanonicalTaskSpec.canonical_payload()` 确定后由代码计算出的 SHA-256。只要任务族、
输出字段或 `arguments` 中任一规范内容改变，hash 就会改变；原 Envelope 因而不能继续
冒充新任务的许可证。source artifact 的 manifest 也绑定同一份规范 payload。

因此两者的关系是“权限边界绑定到同一任务语义”，不是
`AdaptiveTaskEnvelope` 内嵌 `CanonicalTaskSpec`。

---

## 2. 第 0 步：任务何时结构化

答案是：

> 对这个 benchmark，任务在 Planner、Retriever、Executor、Summarizer 被调用前
> 就已经结构化。

### 输入

任务定义在：

~~~text
v2/benchmark/samples/semantic_holdout/manifest.json
~~~

它同时包含自然语言请求和预先编写的结构化任务。下面是关键字段摘录：

~~~json
{
  "task_id": "semantic-holdout-s1",
  "request_text": "From the complete Meridian network review, identify the named operating region and the binding fulfillment constraint. Return each fact with the section heading that locates it.",
  "canonical_task_spec": {
    "task_family": "continuous_long_doc_table_analysis",
    "intent_op": "extract_narrative_facts",
    "target_entities": ["Meridian network"],
    "time_scope": "spring planning cycle",
    "required_outputs": [
      "operating_region",
      "region_locator",
      "binding_constraint",
      "constraint_locator"
    ],
    "arguments": {
      "source_kind": "narrative_markdown",
      "source_path": "v2/benchmark/samples/semantic_holdout/meridian_network_review.md",
      "fact_selectors": [
        {
          "output_field": "operating_region",
          "locator_field": "region_locator",
          "section": "Market signal",
          "label": "The operating region"
        },
        {
          "output_field": "binding_constraint",
          "locator_field": "constraint_locator",
          "section": "Fulfillment constraint",
          "label": "The binding constraint"
        }
      ]
    }
  }
}
~~~

`request_text` 是给角色模型读的任务表达；`canonical_task_spec` 是 Controller
使用的任务合同。这个路径不是让 Planner 从自由文本推导 Spec。

把任务说明书逐字段翻译成中文：

| 代码字段 | 中文理解 | 本次值 | 后面谁会使用 |
| --- | --- | --- | --- |
| `task_family` | 任务属于哪一类 | 长文档分析 | adapter、兼容性检查、记忆检索 |
| `intent_op` | 这次要执行的标准动作 | 从叙述中抽取事实 | Controller 用它派生执行规则 |
| `target_entities` | 任务关注的实体 | Meridian 网络 | 约束检索范围 |
| `time_scope` | 任务涉及的时间范围 | 春季规划周期 | 约束检索和兼容性 |
| `required_outputs` | 最终必须出现哪些业务字段 | 区域、区域标题、约束、约束标题 | Planner、Executor schema、质量检查 |
| `required_tools` | 任务合同明确要求的工具 | 空 | 不是 capability 授权；只记录任务需要 |
| `arguments` | 该任务族特有的详细参数 | 源文件、输出类型、事实选择器 | source adapter 和 Executor 合同 |
| `schema_version` | 这份任务说明书按哪个合同版本解释 | `statebus.canonical_task_spec.v1` | 防止新旧代码误读 |
| `spec_hash` | 对以上规范内容计算的摘要 | `d8b1...dfeef` | 将 Envelope、Runtime session 和 memory 查询绑定到同一任务 |

`arguments` 不是“随便塞参数”的垃圾桶。本例中最重要的子字段是：

| 子字段 | 中文含义 | 本次作用 |
| --- | --- | --- |
| `source_path` | Controller 允许读取的仓库内源文件 | 找到 Meridian Markdown |
| `source_kind` | 源文件应按什么格式解析 | 按叙述型 Markdown 解析 |
| `output_schema` | 每个输出字段必须是什么类型 | 四个字段都必须是字符串 |
| `fact_selectors` | 每个结果从哪个小节、哪个标签抽取 | 指定 Market signal 和 Fulfillment constraint |

此处的“结构化”就是：任务不再只剩一句自然语言，而是已经明确了任务类型、输出字段、
源数据类型和公开抽取规则。

### 处理

在第一个 Agent 调用前，代码按以下顺序执行：

~~~text
manifest JSON
  -> semantic_holdout._canonical_spec()
  -> CanonicalTaskSpec
  -> adapt_formal_sample()
  -> source schema / output schema / operation semantics
  -> _source_artifact()
  -> verified source ExecutionArtifactRef
  -> _run_adaptive_case()
  -> AdaptiveTaskEnvelope
  -> 调用 Planner
~~~

Markdown source 被转为七条 `narrative_section` row。例如：

~~~json
{
  "row_kind": "narrative_section",
  "section": "Market signal",
  "text": "The operating region was North Coast corridor. ...",
  "locator": "meridian_network_review.md#section-1"
}
~~~

七行数据被写入 `source/source_rows.json` 并注册为 VERIFIED Ref：

~~~text
formal-source:semantic-holdout-s1
~~~

数据提货单中的主要字段如下：

| 代码字段 | 中文理解 | 本次值或作用 |
| --- | --- | --- |
| `artifact_id` | 这份数据在 Runtime 中的唯一名字 | `formal-source:semantic-holdout-s1` |
| `task_id` | 它属于哪个任务 | `semantic-holdout-s1` |
| `step_id` | 哪个步骤绑定了它 | `formal-source-binding`，这是 Controller 步骤 |
| `artifact_type` | 文件内容类型 | JSON |
| `root_id + relpath` | 受控根目录和相对路径 | source 根目录下的 `source_rows.json` |
| `blob_hash` | 文件内容摘要 | 读取后会重新核对，防止文件被替换 |
| `size_bytes` | 文件应有多大 | 用于完整性和预算检查 |
| `produced_by` | 谁生成了它 | `formal_registry_adapter` |
| `verification_state` | 当前是否允许下游使用 | VERIFIED，表示已验证 |
| `metadata` | 会话、attempt、schema 等审计信息 | 证明它是 Controller 绑定的 source |

这里传给下游的不是裸路径。Executor 先拿到 `artifact_id`；Runtime 验证状态和 hash
后，才把真实内容准备到受控 workspace。

### 输出

此任务的 Spec hash 是：

~~~text
d8b1b3cca4a27271162cdeae23b9a8071312bc7f9ba5b81a9512f31b662dfeef
~~~

本次运行许可证的关键限制是：

| 代码字段 | 中文理解 | 本次值 | 它限制什么 |
| --- | --- | --- | --- |
| `task_id` | 许可证属于哪个任务 | `semantic-holdout-s1` | 不能拿去执行别的任务 |
| `canonical_task_spec_hash` | 绑定哪份任务说明书 | `d8b1...dfeef` | Spec 改变后旧许可证失效 |
| `workflow_mode` | 使用哪种工作流规则 | 有界自适应 | Planner 可选能力，但不能越过边界 |
| `domain_pack_id` | 使用哪套能力集合 | 通用自适应分析 v2 | 决定公开 capability surface |
| `allowed_capability_ids` | 允许选择哪些已注册能力 | 两种检索、两种执行、两种总结 | Planner 不能创造新工具 ID |
| `allowed_output_contracts` | 允许产生哪些输出合同 | 证据包、分析结果、带引用报告 | 防止返回任意对象 |
| `role_cardinality` | 每种角色最少和最多几个 | 1 Retriever、1-2 Executor、1 Summarizer | 限制 DAG 形状 |
| `max_plan_steps` | DAG 最多几个节点 | 4 | 防止无限拆步骤 |
| `max_replans` | 失败后最多重新规划几次 | 0 | 本例不允许重新规划 |
| `max_retrieval_expansions` | 证据不足时最多扩检几次 | 0 | 本例不允许扩大检索 |
| `max_total_attempts` | 全任务最多尝试多少次 | 4 | 控制总资源消耗 |
| `allow_llm_python` | 是否允许模型生成 Python | 是 | 允许选择 bounded Python capability |
| `risk_class` | 本次允许的最高副作用级别 | 受限代码 | 仍必须在 sandbox 内执行 |

运行许可证不告诉 Executor “North Coast corridor” 是答案；它只规定谁能做、能用什么
能力、最多做几步。

### 交给下一步

Planner 得到的是 Controller 对上述对象的受限投影：

- 任务目标
- 允许输入的 source Ref
- capability surface
- 角色数量
- 预算

这些对象此时都在 Controller/Runtime 的 Python 内存中。Controller 将需要给 Planner
看的字段渲染成 prompt；Planner 看不到 source 文件正文，只知道存在一个允许使用的
source Ref、source schema 和任务参数。

`gold.json` 不进入角色 prompt，只在 Runtime 完成后做外部评测。运行记录明确为：

~~~text
benchmark_oracle_visible_to_roles = false
~~~

---

## 3. 第 1 步：Planner 生成 DAG

### 输入

Planner 看到的核心 authority 是：

| 角色 | 可选择 capability |
| --- | --- |
| Retriever | `retrieve_semantic_evidence_v1`、`retrieve_table_evidence_v1` |
| Executor | `execute_analysis_dsl_v2`、`execute_bounded_python_v2` |
| Summarizer | `compose_claim_set_v2`、`compose_risk_memo_v1` |

它还看到：

~~~text
任务目标
允许的 source Ref
source schema
required output schema
角色数量
max_steps = 4
~~~

Planner prompt 要求它只提出 DAG 候选，不调度、不执行、不生成代码，并使用短且稳定的
step ID。

### 处理

Planner 本次真实输出是：

| Planner step ID | role | capability | 原始依赖 |
| --- | --- | --- | --- |
| `retriever_0` | retriever | `retrieve_semantic_evidence_v1` | 无 |
| `executor_0` | executor | `execute_bounded_python_v2` | `retriever_0` |
| `summarizer_0` | summarizer | `compose_claim_set_v2` | `executor_0` |

这是 `PlanProposal`，中文可以叫“计划草案”。它的外层字段只做三件事：

| 字段 | 中文含义 | 本次值或作用 |
| --- | --- | --- |
| `proposal_id` | Planner 给草案起的名字 | `meridian_analysis_plan_v1` |
| `task_id` | 草案属于哪个任务 | `semantic-holdout-s1`；由 Controller 绑定，不让模型改 |
| `steps` | 草案中的步骤列表 | 上表三个步骤 |
| `final_output_contract_version` | 最后希望得到哪种对象 | `statebus.cited_report.v1`，即带引用报告 |
| `requested_memory_policy` | 本次是否请求复用历史记忆 | `none`，本例不复用 |
| `planner_notes` | Planner 对选择理由的简短说明 | 因为需要自定义文本抽取，所以选择 bounded Python |
| 模型、token、耗时、原始响应 hash | 调用审计信息 | 证明是哪次模型调用产生了这份草案，不参与业务计算 |

草案里的每一个节点是一个 `PlanStepProposal`。以 Planner 原始的 Executor 节点为例：

~~~json
{
  "step_id": "executor_0",
  "role": "executor",
  "capability_id": "execute_bounded_python_v2",
  "goal": "Extract the operating region and binding constraint ...",
  "depends_on": ["retriever_0"],
  "input_ref_ids": ["formal-source:semantic-holdout-s1"],
  "input_ref_kinds": ["execution_artifact"],
  "output_contract_version": "statebus.analysis_result.v2",
  "completion_criteria": {
    "min_rows": 2,
    "required_fields": [
      "binding_constraint",
      "constraint_locator",
      "operating_region",
      "region_locator"
    ]
  }
}
~~~

逐字段理解这条记录：

| 字段 | 不看英文时可以理解成 | 本例如何使用 |
| --- | --- | --- |
| `step_id` | 这一步的临时名字 | Planner 起名 `executor_0`；Controller 后面改成稳定 ID |
| `role` | 哪类 Agent 承担 | `executor`，因此走 Executor 的处理路径 |
| `capability_id` | 从能力注册表选择哪种已实现能力 | 选择“让模型生成受限 Python”而不是声明式 DSL |
| `goal` | 这一步具体要完成什么 | 抽取区域、约束，并把两者映射到小节标题 |
| `depends_on` | 必须先等哪些步骤结束 | 等 Retriever；它表达执行顺序和数据依赖来源 |
| `input_ref_ids` | 除上游结果外，还明确允许读哪些已有对象 | 本例明确绑定 source 数据提货单 |
| `input_ref_kinds` | 上述 Ref 分别是什么类型 | source Ref 是执行产物类型，Runtime 据此做类型检查 |
| `output_contract_version` | 这一步必须交出哪种结构 | 分析结果 v2，不能临时改成自由文本 |
| `completion_criteria` | 至少满足哪些验收条件 | 结果对象必须含四个指定字段 |
| `on_failure` | 本步失败后怎么办 | 属于 Controller 恢复策略；最终为 `fail` |
| `required_input_fields` | 多级 Executor 时，下一级明确依赖上一级哪些字段 | 本例只有一个 Executor，所以为空 |

这里最容易混淆的是 `depends_on` 和 `input_ref_ids`：

~~~text
depends_on    = “等谁完成，并接收谁随后真正产生的输出 Ref”
input_ref_ids = “DAG 启动前就已经存在、明确绑定给本步的 Ref”
~~~

所以 `execute-analysis` 的 source Ref 来自 `input_ref_ids`，Retriever 的 EvidencePack
Ref 则是在 Retriever 完成后沿 `depends_on` 自动加入；Planner 此时不可能提前知道后者的
完整 Ref ID，因为 attempt 还没有开始。

当前 `PlanStepProposal` 代码还带有 `handoff_intent`，中文是“希望优先采用哪种交接形式”，
默认值为 `auto`。2026-07-20 的这份运行 artifact 尚未把它序列化出来，本例也没有靠它
改变数据路径，不能从这次运行中推导出额外的 latent/hidden-state 交接。

计划草案仍是不可信候选。原始候选漏掉了 Summarizer 对 Retriever evidence 的依赖，
所以原始 policy report 拒绝了这份连线。

Controller 的 `_compile_formal_controller_wiring()` 保留模型选择的角色目标和
capability，但重建由 Controller 负责的 ID、依赖、输入 Ref 和输出合同：

| Planner ID | 最终 Runtime ID |
| --- | --- |
| `retriever_0` | `retrieve-evidence` |
| `executor_0` | `execute-analysis` |
| `summarizer_0` | `compose-report` |

这不是简单改名。真实改写如下：

| 内容 | Planner 原始草案 | Controller 批准后的值 | 为什么由 Controller 决定 |
| --- | --- | --- | --- |
| Retriever ID | `retriever_0` | `retrieve-evidence` | 形成稳定的运行时和审计 ID |
| Executor ID | `executor_0` | `execute-analysis` | 同上 |
| Summarizer ID | `summarizer_0` | `compose-report` | 同上 |
| Executor 目标 | 只有分析策略 | 原始任务目标 + 分析策略 | 防止改写时丢掉用户要求 |
| Executor 显式输入 | source Ref | 保留 source Ref | 权威数据只能由 Controller 绑定 |
| Executor 依赖 | Retriever | Retriever | bounded Python 允许读取检索上下文 |
| Summarizer 依赖 | 只有 Executor | Retriever + Executor | 总结既需要结果，也需要引用证据 |
| Executor `min_rows` | 2 | 1 | 本任务输出形状是一个 JSON 对象，不是两行表 |
| Executor 必需字段 | 四字段，顺序由模型给出 | 按任务说明书的四字段重建 | 最终 schema 属于任务合同 |
| 失败策略 | 模型响应中没有合法权限 | `fail` | 恢复策略不交给 Planner 自行扩大 |

因此权责边界是：Planner 选择“用哪类能力、目标是什么”；Controller 决定“真实 ID、
真实连线、真实数据 Ref、输出合同和失败策略”。

运行摘要中的 `planner_schema_normalization_used=true` 指的就是这次确定性的 Controller
编译；`planner_policy_repair_used=false` 表示没有再调用 Planner 让模型重写计划。二者
不是同一件事。

### 输出

最终通过 policy 的图是：

~~~mermaid
flowchart LR
    SRC[formal-source:semantic-holdout-s1]
    R[retrieve-evidence]
    X[execute-analysis]
    S[compose-report]
    SRC --> X
    R --> X
    R --> S
    X --> S
~~~

其中 source Ref 是显式数据输入；另外三条边是 DAG step 依赖。

### `step_id` 为什么是 `execute-analysis`

`step_id` 是 DAG 节点标识，不是业务动作本身。当前 formal compiler 的命名规则是：

~~~text
第一个 Executor  -> execute-analysis
第二个 Executor  -> execute-analysis-2
~~~

它用于依赖引用、ready 判断、attempt 和 telemetry。真正决定行为的是：

~~~text
role          = executor
capability_id = execute_bounded_python_v2
step.goal     = 本任务的具体目标
~~~

此前出现的：

~~~json
{"step_id": "analyze"}
~~~

是旧文档虚构的示意值，不是这次运行中的真实值。

### 交给下一步

Controller 再次运行 `PlanPolicyValidator`。通过后产生 `ApprovedPlan`；Runtime
只执行 ApprovedPlan，不直接执行 Planner 原始 JSON。

---

## 4. 第 2 步：DAG 如何变成实际输入

### 输入

Runtime 持有：

- `ApprovedPlan`
- 初始 source Ref
- capability registry
- Envelope
- Ref registry / runtime context

### 处理

一个 step 的所有依赖完成后才会 ready。Runtime 为每次 ready step 签发一次性
`CapabilityGrant`。

它不是新的任务说明书，而是一张“只允许这一步、这一次执行”的单步通行证。字段逐一
解释如下：

| Grant 字段 | 中文含义 | 谁写入、接收方怎么用 |
| --- | --- | --- |
| `grant_id` | 通行证自己的唯一编号 | Runtime 按任务、step、attempt 生成，用于审计 |
| `task_id` | 只能用于哪个任务 | Runtime 绑定；handler 拒绝跨任务对象 |
| `session_id` | 属于哪一次完整运行 | 将 evidence、artifact 和当前运行会话绑定 |
| `step_id` | 授权执行哪个 DAG 节点 | Dispatcher 检查它与当前 step 一致 |
| `attempt_id` | 这是该节点第几次实际尝试 | 本例依次是 `adaptive-attempt-1/2/3` |
| `capability_id` | 允许调用哪个能力实现 | 决定进入 retrieval、CodeAct 或 summarizer handler |
| `capability_version` | 能力按哪个版本解释 | 防止注册表版本悄悄变化 |
| `input_ref_ids` | 这次明确允许读取的对象 ID | handler 只能解析列表内的 Ref |
| `output_contract_version` | 本次只允许产出哪类对象 | 校验输出类型，防止返回任意结构 |
| `workspace_root_id` | 可以写入哪个受控工作区 | CodeAct 只能在该范围内物化输入和输出 |
| `max_runtime_ms` | 最长运行时间 | 超时则本 attempt 失败 |
| `issued_at_ns`、`expires_at_ns` | 签发和过期时刻 | 过期 Grant 不能继续使用 |
| `approved_plan_hash` | 绑定哪份批准计划 | 计划一旦变化，旧 Grant 不再匹配 |
| `grant_nonce` | 每次签发都不同的一次性随机量 | 让两张字段相似的 Grant 也不能被当成同一张重放 |
| `schema_version` | 按哪个 Grant 合同解析 | 防止新旧 Runtime 误读字段 |
| `grant_hash` | 对以上字段计算的摘要 | Runtime、handler 和 telemetry 用它核对同一张 Grant |

输入 Ref 的计算规则是：

~~~text
step 显式 input_ref_ids
+ 每个 depends_on 上游实际产生的 output_refs
= Grant.input_ref_ids
~~~

这条规则就是 Agent 间“传递”的核心。Runtime 维护：

~~~text
produced_refs_by_step[上游 step_id] = 上游成功后返回的 output_refs
~~~

它不会把 Planner 写的 `depends_on` 字符串直接交给下游当数据，而是先查到那个上游
attempt 真正产生且已登记的 Ref，再把 Ref 放入新 Grant。

### 输出

本次三张 Grant 和真实 Ref 流动是：

| step / attempt | Grant 中的 capability | Grant 中的输入 Ref | 成功后登记的输出 Ref |
| --- | --- | --- | --- |
| `retrieve-evidence` / attempt 1 | semantic evidence retrieval | 无 | `evidence:semantic-holdout-s1:retrieve-evidence:adaptive-attempt-1` |
| `execute-analysis` / attempt 2 | bounded Python | source Ref + evidence-pack Ref | `llm-codeact-semantic-holdout-s1-execute-analysis-adaptive-attempt-2` |
| `compose-report` / attempt 3 | compose claim set | evidence-pack Ref + Executor artifact Ref | `claimset-semantic-holdout-s1-compose-report-adaptive-attempt-3` |

看第二行就能理解为什么 Executor 知道可读什么：

~~~text
ApprovedPlan 显式绑定：formal-source:semantic-holdout-s1
Retriever attempt 1 输出：evidence:...:adaptive-attempt-1
                         ↓ Runtime 合并并去重
Executor attempt 2 Grant.input_ref_ids = [source Ref, evidence Ref]
~~~

Executor 的 execution record 明确记录：

~~~json
{
  "input_ref_ids": [
    "formal-source:semantic-holdout-s1",
    "evidence:semantic-holdout-s1:retrieve-evidence:adaptive-attempt-1"
  ]
}
~~~

### 交给下一步

Grant 是“本次允许做什么、允许读什么”的授权，不是完整任务说明。Dispatcher 调用
handler 时同时传入：

~~~text
ApprovedPlan 中的 step
+ CapabilityGrant
+ Runtime context
~~~

所以后续角色同时拥有工作目标和受控数据权限。

在当前主链中，Runtime 创建的是 Python `CapabilityGrant` 对象，Dispatcher 用它组装
角色输入。只有当 Runtime 再启动独立 selector worker 时，才会把 Grant 的 hash、签名
token 和绑定的 Ref 投影到 UDS + Protobuf 控制消息。不要把“所有 Agent 调用”和“向量
worker 的跨进程调用”误认为同一种物理传输。

---

## 5. 第 3 步：Retriever 生成三个 query

### 输入

Retriever prompt 只暴露：

~~~json
{
  "task": {
    "goal": "从完整 Meridian network review 找出命名运营区域、约束及小节标题"
  },
  "step": {
    "id": "retrieve-evidence",
    "goal": "找出运营区域和履约约束，并返回对应小节标题"
  },
  "corpus_scope": ["formal-registry-source"],
  "evidence_types": ["semantic_context"],
  "authority": {
    "target_entities": [],
    "time_scope": "",
    "controller_injects_target_entities_and_time_scope": true
  },
  "gap_context": null,
  "limits": {
    "max_queries": 3,
    "max_candidates": 12
  }
}
~~~

`task.goal` 保留整个用户任务，防止 Retriever 只围绕一个模糊局部短语搜索；
`step.goal` 说明当前检索节点的具体责任。`authority` 是只读约束，Retriever response
schema 根本不允许模型回写或扩大实体、时间范围。`gap_context=null` 表示这不是一次
“证据不足后的扩检”，而是首次检索。

它不能返回答案、路径、代码或新数据源，只能提出 bounded evidence request。

### 处理

Retriever LLM 本次生成：

~~~text
Q1: What is the named operating region in the Meridian network review?

Q2: What is the binding fulfillment constraint in the Meridian network review?

Q3: Which section headings in the Meridian network review document contain
    information about the operating region and fulfillment constraints?
~~~

这里的 query 是“用于检索的自然语言搜索句”，不是向量，也不是答案。

### 输出

Controller 校验 LLM 响应后，将它封装为 `EvidenceRequest`。这里要区分“模型选择的
字段”和“系统绑定的字段”：

| 字段 | 中文含义 | 本次真实值 | 谁决定、后面怎么用 |
| --- | --- | --- | --- |
| `request_id` | 这张检索请求单的编号 | `evidence-semantic-holdout-s1-retrieve-evidence` | Controller 生成，供审计和去重 |
| `task_id` | 属于哪个任务 | `semantic-holdout-s1` | Controller 绑定，不能由 Retriever 改 |
| `step_id` | 哪个 DAG 节点发起 | `retrieve-evidence` | Controller 绑定到当前 Grant |
| `queries` | 真正用于检索的自然语言问题 | Q1、Q2、Q3 | Retriever LLM 生成；pipeline 逐条执行 |
| `evidence_types` | 想拿哪一类证据 | `semantic_context`，即语义文本片段 | LLM 只能从允许集合中选择 |
| `corpus_scope_ids` | 只允许在哪个语料范围查 | `formal-registry-source` | LLM 复制已批准值；Runtime 拒绝新语料库 |
| `target_entities` | 额外限定的目标实体 | 空数组 | Controller 字段；本次调用未注入额外约束 |
| `time_scope` | 额外限定的时间范围 | 空字符串 | Controller 字段；本次调用未注入额外约束 |
| `memory_policy` | 是否同时查历史记忆 | `none` | 本次不允许记忆复用 |
| `max_candidates` | 请求最多保留多少候选 | 12 | LLM 在 1 到 12 内选择；这是请求上限，不等于最终四条证据 |
| `max_prompt_visible_bytes` | 最多让后续 prompt 看多少证据文本 | 16384 bytes | 合同默认预算，防止证据无限膨胀 |
| `required_locator` | 每条证据是否必须带原文位置 | `true` | 没 locator 的候选不能满足引用要求 |
| `source_plan_step_id` | 这张请求源自哪个批准步骤 | `retrieve-evidence` | 保留计划到检索请求的来源链 |
| `schema_version` | 按哪个请求合同解释 | `statebus.evidence_request.v1` | 版本兼容检查 |

Retriever LLM 实际只返回了 `queries`、`evidence_types`、`corpus_scope_ids` 和
`max_candidates`。任务 ID、step ID、记忆策略、定位要求和字节预算不是模型自行扩大的。

三条 query 的分工也很直观：Q1 专门找区域，Q2 专门找约束，Q3 找承载两类信息的
小节标题。query 本身不会“传给 Executor 当答案”；它先驱动下一节的向量筛选。

### 交给下一步

`AdaptiveRetrievalAdapter` 逐条执行 query。Retriever LLM 到此已经完成；后面的文本
切分、embedding 和 top-k 是本地 pipeline 与 Runtime 的确定性工作。

---

## 6. 第 4 步：embedding 精确比较哪些文本

### 输入

`OfflineMarkdownLongDocCorpus` 按 `##` 标题切分源文档。标题前的导言也保留，
因此得到八个 fragment：

| candidate ID | fragment.text 的内容 |
| --- | --- |
| `ctx-section-1` | 文档标题 + 开头导言 |
| `ctx-section-2` | `Market signal` 标题和正文 |
| `ctx-section-3` | `Commercial backdrop` 标题和正文 |
| `ctx-section-4` | `Fulfillment constraint` 标题和正文 |
| `ctx-section-5` | `Inventory observation` 标题和正文 |
| `ctx-section-6` | `Causal chain` 标题和正文 |
| `ctx-section-7` | `Risk response` 标题和正文 |
| `ctx-section-8` | `Audit note` 标题和正文 |

每条 query 都单独进行下面的比较：

~~~text
Qn 的完整字符串
    vs
8 个 fragment 各自的完整 fragment.text
~~~

它没有拿 query 去和这些对象比较：

~~~text
CanonicalTaskSpec
AdaptiveTaskEnvelope
source_rows JSON 整体
其他 query
Executor 输出
~~~

### 处理：编码和相似度

先把 embedding 用一句不带术语的话说明白：

> embedding 模型把一段文本转换成一排固定长度的数字，使意思相近的文本在数字空间中
> 方向更接近。

它不是关键词列表，也不是把答案藏进某个可读字段。本例每段文本变成 1024 个
`float32` 数字。例如，Q1 变成一个长度为 1024 的向量，`Market signal` 整段正文也
变成另一个长度为 1024 的向量。人不直接读这些数字；程序只比较两排数字的方向。

本次真实 encoder 是：

~~~text
sentence-transformers:Qwen3-Embedding-0.6B
dimension = 1024
dtype     = little-endian float32
~~~

query 和八个 fragment 都由同一个模型编码并做 L2 normalize：

~~~text
v_normalized = v / ||v||2
~~~

“归一化”表示把每个向量的总长度缩放为 1，但保留方向。这样两个向量的点积就可以
直接当作余弦相似度：分数越大，模型认为语义越接近。它只回答“像不像”，不回答
“事实是否正确”，也不检查文本是否真的包含最终答案。

每条 query 形成一个矩阵：

~~~text
row 0    = query embedding
row 1..8 = 8 个 candidate embedding
shape    = [9, 1024]
bytes    = 9 * 1024 * 4 = 36,864
~~~

因为每行已归一化，所以点积等于 cosine similarity。worker 的实际代码是：

~~~python
scores = matrix[1:] @ matrix[0]
~~~

这行计算等价于连续做八次比较：

~~~text
score[1] = fragment 1 的 1024 个数 · query 的 1024 个数
score[2] = fragment 2 的 1024 个数 · query 的 1024 个数
...
score[8] = fragment 8 的 1024 个数 · query 的 1024 个数
~~~

然后按分数从高到低排序，并在 `top_k` 和证据字节预算内保留候选。本例每条 query
最终保留 3 条。

三条 query 总计：

~~~text
embedding encode count = 3 * (1 + 8) = 27
semantic state bytes   = 3 * 36,864 = 110,592
~~~

### 处理：跨进程非文本传递

Runtime 中承担 Retriever producer 的进程把矩阵作为二进制 bytes 发布到 shared
memory，并生成 `SemanticStateRef`。以 Q1 为例，这张“向量状态提货单”的字段是：

| 字段 | 中文含义 | Q1 的值或用途 |
| --- | --- | --- |
| `state_id` | 这块向量状态的唯一 ID | `semantic-semantic-holdout-s1-retrieve-evidence-adaptive-attempt-1-1` |
| `state_kind` | 数据是什么 | `DENSE_SEMANTIC_STATE`，即稠密语义向量矩阵 |
| `storage_kind` | 二进制本体放在哪里 | `shared_memory` |
| `length` | 二进制长度 | 36,864 bytes |
| `blob_hash` | 对矩阵原始 bytes 的摘要 | worker 映射后重新计算，防止读到另一块数据 |
| `manifest_id` | 哪张行号映射表解释矩阵 | `semantic-manifest-semantic-holdout-s1-q1` |
| `channel` | 这张 Ref 属于哪类通道 | `semantic_state` |
| `source_doc_hashes` | 向量候选来自哪份文档 | Meridian Markdown 的规范文档 hash |
| `compatibility_hint` | 编码器兼容签名 | 本次为 `ff416d...6803`；模型、维度或归一化规则变了就不匹配 |
| `exact_replay_ready` | 能否直接当作长期精确重放对象 | 本例为否；这是短生命周期状态 |
| `metadata` | 解释 bytes 所需的详细合同 | shape、dtype、byte order、encoder、manifest hash、租约、producer PID 等 |

Ref 中最关键的是“身份 + 完整性 + 解释方法”，而不是业务正文。Q1 的磁盘 sidecar
另外记录了：

~~~text
shared_memory_name = psm_d2139944
shape              = [9, 1024]
dtype              = float32
byte_order         = little
row_layout         = query_then_candidates
normalized         = true
producer_pid       = 308338
~~~

其中 `shared_memory_name` 是 Runtime 的存储元数据，不是 LLM prompt 字段。`manifest`
则逐行记录：矩阵第几行对应哪个 candidate ID、原文字符范围和预计文本字节数。

一次真实跨进程选择按下面六步发生：

~~~text
1. producer 将 36,864 bytes 写入 shared memory
2. Runtime 保存 SemanticStateRef、sidecar 和 hydrate manifest
3. Runtime 通过 UDS 发送 Protobuf ExecRequest
4. selector worker 按 Ref 读取 sidecar，再映射同一块 shared memory
5. worker 校验 hash / shape / encoder / lease，计算 top-k
6. worker 通过 UDS 返回 candidate ID、score、row index 和 PID
~~~

第 3 步的 `ExecRequest` 控制消息只发送：

~~~text
Ref ID / Ref kind
hydrate manifest ID 和 hash
top_k
evidence byte budget
encoder signature
CapabilityGrant 绑定
~~~

在 Protobuf 中，这些内容分别落在 `state_refs`、`state_root`、
`hydrate_manifest_id`、`semantic_top_k`、`evidence_budget_bytes`、
`expected_encoder_signature`、`capability_grant_hash/token` 等字段。它不把 36,864
字节矩阵内联进 Protobuf。worker 返回的 `SuccessResult` 才带：

~~~text
consumed_state_ref_id
selected_candidate_ids
selected_scores
selected_row_indices
selected_evidence_bytes
consumer_pid / producer_pid
encoder_signature
~~~

所以这里有两条物理通路：

| 通路 | 载体 | 放的内容 |
| --- | --- | --- |
| 控制面 | UDS 上的 typed Protobuf | “读哪张 Ref、选几条、预算多少、如何校验” |
| 数据面 | OS shared memory | 真正的 9 x 1024 float32 矩阵 |

独立 selector worker 根据 Ref 映射 shared memory 后计算 top-k。它不是通过 UDS 收到
矩阵副本，而是根据受控元数据打开同一块共享内存。

真实 PID 是：

| query state | producer PID | consumer PID |
| --- | ---: | ---: |
| Q1 | 308338 | 308651 |
| Q2 | 308338 | 308717 |
| Q3 | 308338 | 308783 |

producer 和 consumer 不同，说明矩阵确实被另一个进程消费。

### 输出：真实 top-3

| query | selected candidates | scores |
| --- | --- | --- |
| Q1 | `ctx-section-1`、`ctx-section-2`、`ctx-section-5` | 0.714316、0.487581、0.367006 |
| Q2 | `ctx-section-1`、`ctx-section-4`、`ctx-section-5` | 0.628946、0.532598、0.426670 |
| Q3 | `ctx-section-1`、`ctx-section-2`、`ctx-section-5` | 0.689843、0.497448、0.462439 |

Q1 找到了包含运营区域的 `Market signal`，Q2 找到了包含履约约束的
`Fulfillment constraint`。但标题导言三次都排第一，`Inventory observation`
也三次入选。

这说明 embedding 是相似度排序器，不是事实判定器。

本地 semantic retriever 在构造每个 query 的矩阵前，已经按该 query 的初步相似度形成
候选顺序；selector worker 从二进制矩阵重新计算并执行受控 top-k。因此这次三个状态都
返回 `selected_row_indices=[1,2,3]`。它只表示“该 query 矩阵中的前三个 candidate
row”，绝不是源文档第 1、2、3 节。Hydrate manifest 才负责：

~~~text
matrix row -> candidate ID -> source locator
~~~

### 交给下一步：水合成 EvidencePack

worker 返回 candidate ID、score、row index 和 byte count，不返回正文。Runtime
根据 candidate map 将 ID 水合回 `EvidenceItem`，再对三条 query 稳定去重。

“水合”不是再调用一次 LLM，也不是重新搜索文档。它只是做受控映射：

~~~text
selected row index
  -> manifest 中的 candidate ID 和 locator
  -> 当前 retrieval bundle 中同 ID 的候选对象
  -> 恢复该候选已经切好的 rendered_text
~~~

以 `ctx-section-4` 为例，恢复出的 `EvidenceItem` 可以这样读：

| 字段 | 中文含义 | 本例 |
| --- | --- | --- |
| `item_id` | 证据片段的稳定 ID | `ctx-section-4` |
| `bucket` | 证据属于哪一类 | `semantic_context`，语义上下文 |
| `locator` | 原文中精确在哪里 | 文档 hash + `section-4` + 字符起止位置 + parser 版本 |
| `rendered_text` | 真正可给下游阅读的原文片段 | `Fulfillment constraint` 标题及其正文 |
| `source_name` | 来源文档名 | Meridian network review |
| `rank` | 在该 query 结果中的名次 | Q2 中入选 top-3 |
| `score` | query 与该片段的相似度 | Q2 中为 0.532598 |
| `metadata` | parser、候选来源等补充审计信息 | 不作为业务答案字段 |

`locator` 和 `rendered_text` 分工不同：正文让 Executor/Summarizer 看内容，locator 让
Runtime 知道这段话在原文什么位置。只有正文而没有 locator，就无法形成可验证引用。

最终唯一候选是：

~~~text
ctx-section-1  标题导言
ctx-section-2  Market signal
ctx-section-4  Fulfillment constraint
ctx-section-5  Inventory observation
~~~

它们被封装成 `CanonicalEvidencePack`：

~~~text
Ref ID:
evidence:semantic-holdout-s1:retrieve-evidence:adaptive-attempt-1

pack_hash:
8317412f74084ce69dcadcbc9662dd605d67d840548767b13b85f6ae0da55851
~~~

证据包本体的字段如下：

| 字段 | 中文含义 | 本例如何填写 |
| --- | --- | --- |
| `pack_id` | 证据包内部 ID | `pack-semantic-holdout-s1-multi-query` |
| `task_id` | 证据属于哪个任务 | `semantic-holdout-s1` |
| `source_doc_hashes` | 所有证据来自哪些源文档 | 本例只有 Meridian Markdown |
| `hard_facts` | 必须保留的硬事实证据 | 本例没有这类条目 |
| `structured_evidence` | 表格等结构化证据 | 本例没有 |
| `semantic_contexts` | embedding 选中的语义文本 | 去重后的四个 fragment |
| `lexical_hints` | 关键词检索提示 | 本例最终业务输入不依赖它 |
| `conflicts` | 相互冲突、需显式保留的证据 | 本例为空 |
| `budget_meta` | 查询数和 fan-in 方式 | `query_count=3`、`fan_in=stable` |
| `pack_hash` | 对整个规范证据包计算的摘要 | `831741...5851` |
| `schema_version` | 证据包对象本身按哪个 schema 解释 | `statebus.canonical_evidence_pack.v1` |

这里有两个容易混淆的版本号：批准步骤的
`output_contract_version=statebus.evidence_pack.v2` 表示 capability 对外承诺交付哪类
结果；包内的 `schema_version=statebus.canonical_evidence_pack.v1` 表示当前 Python 数据
模型如何序列化字段。一个约束步骤接口，一个约束对象布局，不能相互替代。

`pack_id`、EvidencePack Ref ID 和 `pack_hash` 也不要混淆：

~~~text
pack_id   = 对象内部叫什么
Ref ID    = Runtime 下游拿什么 ID 来提取这个对象
pack_hash = 对象内容是否还是原来的内容
~~~

Executor 的 Grant 里放的是 Ref ID。Runtime 用这个 Ref 找到 pack，再核对 `pack_hash`
和会话范围，最后才把允许可见的 `EvidenceItem` 文本投影给 Executor。

三条 query 的 top-3 文本量相加为 2,084 bytes，去重后真正可见的四个 fragment
合计 954 bytes。

因此 Retriever 到 Executor 传的是：

> `CanonicalEvidencePack` 的 typed Ref。Pack 内有选中的 ID、fragment 文本、
> score 和 locator；原始 embedding 矩阵不会直接进入 Executor LLM。

更严格地说，Retriever handler 先把证据包登记在 Runtime context 中，然后返回这个 Ref
作为 step output；Runtime 再沿 DAG 依赖把 Ref 写进 Executor Grant。Retriever Agent
没有直接连接 Executor Agent。

### 这算非文本吗

算，但准确范围是：

> 跨进程传递和消费的是 float32 向量矩阵及其 Ref；它决定保留哪些文本证据。

这里的“非文本”只描述中间载荷的编码形式：shared memory 中是 110,592 bytes 的数值
矩阵，selector worker 对数值做点积，没有解析自然语言字符串。它不是 hidden state、
KV cache，也不是端到端完全无文本。query 和 fragment 起初仍是文本，top-k 后也会
水合回文本；任务结束后三个 `SemanticStateRef` 被释放。

---

## 7. 第 5 步：Executor 如何知道任务

Executor 不是从一个神奇字段中获得全部任务，而是组合五类受控输入：

| 来源 | 本次内容 | 作用 |
| --- | --- | --- |
| `step.goal` | 找出区域、约束和对应标题 | 做什么 |
| `grant.capability_id` | `execute_bounded_python_v2` | 用哪种 handler |
| source Ref | `formal-source:semantic-holdout-s1` | 权威业务数据 |
| EvidencePack Ref | Retriever 输出 | 筛选后的语义上下文和 provenance |
| Controller contract | schema、fact selectors、抽取规则、completion criteria | 怎样做、输出什么、如何验收 |

先把“Executor”分成三个层次，就不会混淆谁看到了什么：

~~~text
层 1：Executor handler
      收到 ApprovedPlan step + CapabilityGrant + Runtime context
             |
             | 解析 Ref、校验权限、组装请求
             v
层 2：代码生成 LLM
      收到 CodeAct prompt，输出 Python 源码
             |
             | policy 审计通过后
             v
层 3：bwrap 中的 Python
      读取 inputs/task.json，写 outputs/result.json
~~~

LLM 不是直接拿 Grant 自己解析文件；沙箱 Python 也不会收到整个 prompt。Runtime 在
三层之间只投影各层真正需要的内容。

### 输入

两个 Ref 进入 Executor 的方式不同。

**数据面：**

source artifact 的七条完整 row 被写入 sandbox：

~~~text
inputs/task.json
~~~

生成的 Python 从这里读取业务值。

**代码生成上下文：**

EvidencePack 被水合为 `retrieval_context`，放入 CodeAct prompt：

~~~json
{
  "item_id": "ctx-section-4",
  "bucket": "semantic_context",
  "locator": "TextSpanLocator(...)",
  "text": "Fulfillment constraint\n\nThe binding constraint was ..."
}
~~~

因此：

~~~text
embedding 矩阵              不直接进入 Executor LLM
embedding 选中的证据文本    进入代码生成 prompt
完整 verified source rows  进入 sandbox 的 task.json
~~~

把这两条路径从头连起来：

~~~text
source Ref
  -> Runtime 校验 artifact 状态、task/session、path 和 blob hash
  -> 读取七条 source row
  -> 作为 input_files["inputs/task.json"] 交给 CodeActRunner
  -> CodeActRunner 在本 attempt 工作区物化只读输入
  -> 沙箱 Python 读取

EvidencePack Ref
  -> Runtime 校验 pack hash、coverage 状态和 session scope
  -> 取最多 8 条允许可见的 EvidenceItem
  -> 只投影 item_id / bucket / locator / text
  -> 写入 CodeGenerationRequest.retrieval_context
  -> 渲染到代码生成 prompt
~~~

因此 source Ref 是“业务值的权威来源”，EvidencePack Ref 是“帮助模型理解要找什么以及
引用来自哪里的语义上下文”。即使 EvidencePack 文本中碰巧出现答案，生成代码仍被要求
从 `inputs/task.json` 读取并计算输出值。

### 处理

Dispatcher 先创建 `CodeGenerationRequest`，中文可叫“代码生成请求单”。它把不同来源
收敛到一个可审计对象中。关键字段如下：

| 字段 | 中文含义 | 本例中的内容和用途 |
| --- | --- | --- |
| `task_id`、`step_id`、`attempt_id` | 哪个任务、哪一步、哪次尝试 | `semantic-holdout-s1` / `execute-analysis` / attempt 2 |
| `session_id` | 属于哪次完整运行 | `adaptive-session-semantic-holdout-s1` |
| `approved_plan_hash` | 绑定哪份批准 DAG | 防止请求脱离本次计划 |
| `capability_grant_hash` | 绑定哪张单步通行证 | 防止拿同一请求绕开当前授权 |
| `capability_id` | 允许走哪种执行能力 | `execute_bounded_python_v2` |
| `input_ref_ids` | 这次获准读取哪些对象 | source Ref + EvidencePack Ref |
| `input_manifest_digest` | 对所有输入 hash 的汇总摘要 | source、evidence、memory、参数任一改变，请求身份都改变 |
| `task_goal` | 代码最终要完成什么 | 原始任务要求 + Planner 的分析策略 |
| `operation_semantics` | 公开且确定的计算/抽取规则 | 两个 `fact_selectors` 和 labeled-fact 抽取算法 |
| `completion_criteria` | 结果最低验收条件 | 至少一个结果对象，且含四个必需字段 |
| `output_schema` | 每个输出字段叫什么、是什么类型 | 四个字段都为 string |
| `expected_output_shape` | 最外层 JSON 是对象还是数组 | `object` |
| `output_contract_version` | 结果按哪个业务合同解释 | `statebus.analysis_result.v2` |
| `validator_id` | 结果交给哪个确定性验证器 | formal analysis validator |
| `quality_constraints` | 额外质量规则 | 由 capability contract 提供，不由 LLM 自报通过 |
| `authorized_input_schema(s)` | 每个输入 JSON 可用哪些字段 | `locator`、`row_kind`、`section`、`text` |
| `retrieval_context` | 允许给模型看的证据切片 | 四条去重语义片段的 ID、位置和正文 |
| `provenance_item_ids` | 输出来源链允许引用哪些证据项 | 来自 verified source/evidence 的 item ID |
| `memory_inputs` | 本次可用的历史记忆 | 空；`memory_policy=none` |
| `policy` | 代码能 import 什么、读写什么、运行多久 | 固定输入路径、唯一输出路径、模块白名单、bwrap 要求等 |
| `model_signature` | 哪类模型执行面生成代码 | `adaptive_executor` |
| `runtime_signature` | 当前 Envelope/运行环境摘要 | 环境或权限边界改变后不能视为同一请求 |
| `prompt_signature` | 最终渲染 prompt 的摘要 | prompt 生成后回填，用于审计 |
| `schema_version` | 按哪个请求合同解释 | `statebus.code_generation_request.v1` |

这里同样存在“对象字段”和“给 LLM 可见文本”的区别。`approved_plan_hash`、Grant hash、
input manifest 等主要由 Runtime 校验和审计；`build_code_generation_prompt()` 选择其中与
写代码有关的字段渲染给模型：

~~~text
Task goal
Operation semantics
Completion criteria
Output schema / output contract
Authorized input schema
Retrieved semantic context
Allowed imports and fixed paths
~~~

这些英文标题逐项翻译就是：

| prompt 标题 | 模型获得的实际信息 |
| --- | --- |
| `Task goal` | 要找运营区域、履约约束及各自小节标题 |
| `Operation semantics` | 应到哪类 row 找、按哪个 label 和正则规则抽取 |
| `Completion criteria` | 四个字段必须齐全，输出一个对象 |
| `Output schema / contract` | 字段名和 string 类型，合同为 analysis result v2 |
| `Authorized input schema` | `task.json` 每行只有 locator、row_kind、section、text |
| `Retrieved semantic context` | embedding 选中的四段原文及定位 |
| `Allowed imports and fixed paths` | 只能使用白名单模块，只读固定输入，只写固定输出 |

Controller-owned operation semantics 还给出公开的 `fact_selectors` 和抽取算法：

~~~text
找到 section == "Market signal" 的 row
  -> 匹配 "The operating region" 后面的 was/is
  -> 截取到下一个句号前的短语
  -> 写 operating_region
  -> 将 section 写入 region_locator

对 "Fulfillment constraint" 和 "The binding constraint" 重复该过程
~~~

这不是 gold 泄漏：合同给出公开的 section、label 和抽取规则，但没有直接提供
`North Coast corridor` 或 `limited cold-storage dock availability` 两个值。
值必须从授权 source rows 读取。

本次 Executor LLM 生成的核心代码是：

~~~python
for row in task_data:
    section = row.get("section")
    text = row.get("text")

    if section == "Market signal":
        output["operating_region"] = extract_fact(
            text, "The operating region"
        )
        output["region_locator"] = section

    elif section == "Fulfillment constraint":
        output["binding_constraint"] = extract_fact(
            text, "The binding constraint"
        )
        output["constraint_locator"] = section
~~~

代码通过 policy 后在非 root `bwrap` sandbox 执行，实际 UID/GID 都是 65534。

完整执行顺序是：

~~~text
LLM 返回 Python
  -> 解析 JSON/code fence
  -> AST 与路径 policy 审计
  -> 在 attempt 专属目录写入 generated source 和 input files
  -> bwrap 以 UID/GID 65534 运行
  -> 读取 result.json
  -> 检查 JSON shape 和四字段 schema
  -> 根据授权 source rows 与公开 semantics 确定性重算
  -> 全部通过后才把 artifact 从 CANDIDATE 标记为 VERIFIED
~~~

### 输出

`outputs/result.json` 是：

~~~json
{
  "operating_region": "North Coast corridor",
  "region_locator": "Market signal",
  "binding_constraint": "limited cold-storage dock availability",
  "constraint_locator": "Fulfillment constraint"
}
~~~

Runtime 检查 schema、required fields、provenance、sandbox 状态和基于授权输入的重算。
全部通过后才生成 VERIFIED `ExecutionArtifactRef`：

~~~text
llm-codeact-semantic-holdout-s1-execute-analysis-adaptive-attempt-2
~~~

这张执行结果提货单逐字段是：

| 字段 | 中文含义 | 本次值或作用 |
| --- | --- | --- |
| `artifact_id` | Runtime 中唯一结果 ID | 上述 `llm-codeact-...attempt-2` |
| `task_id` | 属于哪个任务 | `semantic-holdout-s1` |
| `step_id` | 由哪个步骤产生 | `execute-analysis` |
| `artifact_type` | 文件格式 | `json` |
| `root_id` | 受控 artifact 根目录 | attempt 2 的 CodeAct 工作区 |
| `relpath` | 根目录内的相对路径 | `outputs/result.json` |
| `blob_hash` | 结果文件内容摘要 | `61e53b...159f` |
| `size_bytes` | 结果文件字节数 | 191 bytes |
| `produced_by` | 哪个角色产生 | `executor` |
| `verification_state` | 是否通过验证 | `VERIFIED` |
| `replay_ready` | 是否达到可登记为已验证产物的状态 | 验证后为 true；是否实际复用还受 memory/replay gate 控制 |
| `workspace_relpath` | 工作区审计相对路径 | `outputs/result.json` |
| `manifest_hash` | 生成它时绑定的输入 manifest 摘要 | 防止结果脱离原输入解释 |
| `metadata` | 补充审计信息 | source hash、quality report hash、session、attempt、schema |

`ExecutionArtifactRef` 和上一节的 `SemanticStateRef` 必须分开理解：前者指向一个经过
验证、可保留的执行结果文件；后者指向短生命周期的 float32 语义状态。两者的存储、
生命周期和下游用途都不同，不能统一叫成一个含糊的 “StateRef”。

### 交给下一步

`compose-report` 同时依赖 Retriever 和 Executor，所以它得到：

~~~text
EvidencePack Ref
+ VERIFIED ExecutionArtifactRef
~~~

必须诚实说明：embedding 的跨进程选择是真实的，也影响了 CodeAct prompt，但完整
source rows 仍是权威数据输入。因此不能说“Executor 只靠 embedding 算出答案”。

---

## 8. 第 6 步：Summarizer 生成 ClaimSet

### 输入

Summarizer 看到两张受控“表”：

| 输入 | 内容 |
| --- | --- |
| artifact catalog | verified artifact ID 和 verified result row |
| evidence catalog | evidence ID、TextSpanLocator 和选中 fragment 文本 |

它们仍然来自 `compose-report` 的 Grant，而不是 Executor 或 Retriever 直接发消息：

~~~text
Grant.input_ref_ids = [
  evidence:semantic-holdout-s1:retrieve-evidence:adaptive-attempt-1,
  llm-codeact-semantic-holdout-s1-execute-analysis-adaptive-attempt-2
]
~~~

Summarizer handler 先做两类检查：EvidencePack 必须属于当前 task/session 且 coverage
状态完整；Executor artifact 必须是当前 Grant 范围内的 VERIFIED artifact。然后才投影
成给 Summarizer LLM 看的 reference catalog。

artifact catalog 中的真实业务行是：

~~~json
{
  "artifact_ref_id": "llm-codeact-semantic-holdout-s1-execute-analysis-adaptive-attempt-2",
  "status": "verified",
  "verified_rows": [
    {
      "operating_region": "North Coast corridor",
      "region_locator": "Market signal",
      "binding_constraint": "limited cold-storage dock availability",
      "constraint_locator": "Fulfillment constraint"
    }
  ]
}
~~~

evidence catalog 的每行只含三类值：

~~~text
evidence_id       = ctx-section-4
citation_locator  = TextSpanLocator(...section-4, start_char=736, end_char=980...)
evidence_text     = Fulfillment constraint 标题和正文
~~~

这相当于给模型三个严格分列的“下拉选项”：证据 ID 列、原文位置列、artifact ID 列。
模型只能从对应列复制值，不能把看起来容易懂的小节标题放到需要精确 locator 的列中。

### 处理

它生成 `ClaimSet`，中文叫“结论单”。外层字段很少：

| 字段 | 中文含义 | 本次值 |
| --- | --- | --- |
| `claim_set_id` | 这一组结论的内部 ID | `claims-adaptive-attempt-3` |
| `task_id` | 属于哪个任务 | `semantic-holdout-s1` |
| `claims` | 一条或多条结论 | 本次只有一条 |
| `status` | 整组是否可交付 | `ready` |
| `schema_version` | 按哪个结论合同解释 | `statebus.claim_set.v1` |

为什么四个 Executor 输出字段最后只有一条 claim？因为本例的输出 shape 是一个对象，
Summarizer 合同要求“每个 verified output row 生成一条 compact claim”。四个字段共同描述
同一件事，所以合并成一句话，而不是机械拆成四句。

一条 `Claim` 的字段如下：

| 字段 | 中文含义 | 本次如何填写 |
| --- | --- | --- |
| `claim_id` | 结论的稳定 ID | `North-Coast-corridor-cold-storage-dock-availability` |
| `claim_text` | 给人阅读的结论句 | North Coast corridor 的约束是冷库月台可用性有限 |
| `claim_type` | 事实、推断还是风险 | `fact` |
| `supporting_evidence_item_ids` | 哪些 EvidenceItem 支持这句话 | 最终为 `ctx-section-4`、`ctx-section-5` |
| `supporting_artifact_ref_ids` | 哪个已验证计算结果支持这句话 | Executor 的 `llm-codeact-...attempt-2` |
| `citation_locators` | 支持证据在原文中的精确位置 | 与上述证据对应的两个 `TextSpanLocator` |
| `numeric_fields` | 结论中的结构化数值 | 空；本例输出全是字符串 |
| `uncertainty_note` | 必须披露的不确定性 | 空字符串 |
| `status` | 这一条是否可交付 | `ready` |
| `factual_fields`、`field_support` | v2 新合同可做逐字段支持绑定 | 这份 v1 运行产物未填写 |

其中三个引用字段的类型不能串列：

- evidence ID 放进 `supporting_evidence_item_ids`
- locator 放进 `citation_locators`
- artifact ID 放进 `supporting_artifact_ref_ids`

还要区分两个名字很像、实际完全不同的“位置”：

~~~text
region_locator = "Market signal"
  这是 Executor 业务结果中的一个字段，值是用户要求返回的小节标题。

citation_locators = ["TextSpanLocator(...)", ...]
  这是 provenance，包含文档 hash、规范 section ID、字符起止位置和 parser 版本。
~~~

本次第一次输出正是混淆了两者，把 `"Fulfillment constraint"` 和
`"Market signal"` 两个普通小节标题放进 `citation_locators`。Runtime 校验发现它们
不在 reference catalog 的 locator 列中，因此拒绝该引用并执行一次 citation-only
repair。

修复 prompt 只允许返回：

~~~text
原 claim_id
+ supporting_evidence_item_ids
+ supporting_artifact_ref_ids
+ citation_locators
~~~

它明确禁止返回或修改 `claim_text`、业务值、数值、claim 类型、状态，也不能新增
claim。因此这是“把引用列填对”，不是让模型借修复机会重写答案。

### 输出

最终 claim 是：

~~~text
The binding fulfillment constraint in the North Coast corridor is
limited cold-storage dock availability.
~~~

最终支持关系是：

~~~text
claim
  ├─ evidence: ctx-section-4
  │    -> Fulfillment constraint 原文 span
  ├─ evidence: ctx-section-5
  │    -> Inventory observation 原文 span
  └─ artifact: llm-codeact-...adaptive-attempt-2
       -> verified result.json
~~~

这里 `ctx-section-5` 的正文也提到 North Coast，所以修复后的组合引用支持整条复合句；
它并不等同于 Executor 业务字段 `region_locator="Market signal"`。业务 locator 与引用
locator 分别按各自合同校验。

最终 Ref 是：

~~~text
claimset-semantic-holdout-s1-compose-report-adaptive-attempt-3
~~~

Runtime 先用 ClaimSetValidator 校验内存中的候选；通过后才写 attempt 3 的
`outputs/claim_set.json`。artifact lifecycle 随后仍执行一次明确的
`CANDIDATE -> VERIFIED` 状态转换。该文件为 1,076 bytes，内容 hash / claim set hash
是：

~~~text
183176a37c66a1bea477f043efb9af77e3f875b5e08c08434a35cea8092d0101
~~~

### 交给下一步

Runtime 校验 ClaimSet 后结束任务。随后 benchmark 才用隐藏 gold 检查四个字段，本次
全部通过。`memory_policy=none`，所以这次没有提交共享记忆。

注意隐藏 gold 检查发生在四个 Agent 和 Runtime 主链完成之后，且运行记录明确标记
`benchmark_oracle_visible_to_roles=false`。它用来评价结果，不是生成 query、代码或
claim 的输入。

---

## 9. 一张完整流程图

先记住图中只有 Runtime 掌握全局状态。Agent 只看到 Runtime/Controller 为当前角色
投影出的局部输入。

~~~mermaid
sequenceDiagram
    participant B as Benchmark Loader
    participant C as Controller
    participant RT as Runtime
    participant P as Planner
    participant R as Retriever
    participant V as Embedding Pipeline
    participant W as Selector Subprocess
    participant E as Executor LLM
    participant X as bwrap Sandbox
    participant S as Summarizer

    B->>C: request_text + structured task + source path
    C->>C: create Spec + Envelope + verified source Ref
    C->>P: task goal + capability allowlist + budgets
    P-->>C: PlanProposal JSON
    C->>C: compile IDs, Refs and dependencies; approve DAG
    C->>RT: ApprovedPlan + Envelope + source Ref registry
    RT->>R: retrieve step projection from Grant
    R-->>RT: EvidenceRequest with Q1 + Q2 + Q3
    loop each query
        RT->>V: one query + 8 fragment texts
        V-->>RT: SemanticStateRef + shared-memory matrix
        RT->>W: UDS Protobuf ExecRequest with Ref + top-k + budget
        W-->>RT: UDS Protobuf SuccessResult with IDs + scores
    end
    RT->>RT: hydrate text + stable fan-in + register EvidencePack Ref
    RT->>E: CodeAct prompt with goal + rules + evidence text
    E-->>RT: generated Python
    RT->>X: Python + materialized inputs/task.json
    X-->>RT: outputs/result.json
    RT->>RT: policy/schema/recomputation gates; register VERIFIED artifact Ref
    RT->>S: verified artifact catalog + evidence catalog
    S-->>RT: ClaimSet candidate
    alt citation columns invalid
        RT->>S: citation-only repair request
        S-->>RT: repaired typed references only
    end
    RT->>RT: ClaimSet validation; register final artifact Ref
    RT-->>B: output rows + refs + audit summary
    B->>B: compare with hidden gold after role flow completes
~~~

从“对象如何变形”的角度再压缩一次：

~~~text
任务语义：manifest -> CanonicalTaskSpec ------------------------------+
运行边界：manifest + registry -> AdaptiveTaskEnvelope                 |
权威数据：Markdown -> source rows -> verified source ArtifactRef       |
                                                                        v
规划：三者的受限投影 -> PlanProposal -> ApprovedPlan -> per-step Grant

检索：EvidenceRequest -> 3 个向量矩阵 -> 3 组 selected IDs
                    -> 水合/去重 -> CanonicalEvidencePack -> evidence Ref

执行：step goal + source Ref + evidence Ref + contract
                    -> CodeGenerationRequest -> Python -> result.json
                    -> VERIFIED ExecutionArtifactRef

总结：evidence Ref + result ArtifactRef -> ClaimSet -> final ArtifactRef
~~~

---

## 10. 按时间排序的完整交接表

下面的“发送”包括同进程函数调用、文件物化和跨进程消息，不等于网络发送。

| 时刻 | 发送方 -> 接收方 | 交接对象和关键内容 | 物理载体或存放位置 | 接收方如何使用 |
| ---: | --- | --- | --- | --- |
| 0 | 样例 loader -> Controller | 原始请求、预写结构化任务、source path | repo 中的 manifest JSON | 创建本次任务上下文 |
| 1 | Controller -> Controller | `CanonicalTaskSpec`：任务族、意图、四个输出、参数、spec hash | Python dataclass；摘要进入 summary | 固定“要做什么” |
| 2 | source adapter -> Runtime registry | 七条 source row + `formal-source:semantic-holdout-s1` | `source/source_rows.json` + `ExecutionArtifactRef` | 固定“可以读什么” |
| 3 | Controller -> Controller | `AdaptiveTaskEnvelope`：capability 白名单、DAG/attempt 预算、风险等级 | Python dataclass | 固定“本次允许怎么做” |
| 4 | Controller -> Planner | 任务目标、source Ref/schema、capability surface、角色数量、预算 | 角色 prompt；本次经本地 OpenAI-compatible vLLM API | 只提出步骤草案 |
| 5 | Planner -> Controller | `PlanProposal` JSON：三个角色、能力、目标和候选依赖 | LLM JSON 响应；完整审计在 `planner_trace.json` | 当作不可信候选解析 |
| 6 | Controller compiler -> Runtime | `ApprovedPlan`：稳定 ID、真实依赖、source Ref、输出合同 | 同进程 typed dataclass；trace/summary 留痕 | Runtime 只调度这张批准图 |
| 7 | Runtime -> Retriever handler | step + attempt 1 Grant + corpus/type/数量边界 | 同进程对象，再投影为 Retriever prompt | 知道“要找什么”和“只能去哪找” |
| 8 | Retriever LLM -> Runtime | 三条 query 及受限类型、corpus、候选数 | LLM JSON -> `EvidenceRequest` | 逐条启动确定性检索流程 |
| 9 | corpus -> embedding pipeline | 一条 query + 八个完整 fragment.text | 同进程字符串对象 | 用同一 encoder 生成 9 个向量 |
| 10 | embedding producer -> `LayeredStateStore` | `[9,1024]` little-endian float32 矩阵 | shared memory；sidecar 在 `runtime/state/metadata` | 按 v2 StatePool 数据面策略登记 `SemanticStateRef` |
| 11 | Runtime -> selector worker | state Ref、manifest、top-k、字节预算、encoder 签名、Grant token | UDS 上的 typed Protobuf `ExecRequest` | 定位并校验共享内存，不接收正文 |
| 12 | selector worker -> Runtime | selected IDs、scores、row indices、bytes、PIDs | UDS 上的 typed Protobuf `SuccessResult` | 确认跨进程 top-k 结果 |
| 13 | Runtime -> Runtime | 三次选择水合、稳定去重后的四个 `EvidenceItem` | Runtime candidate map + manifest | 构造 `CanonicalEvidencePack` |
| 14 | Retriever step -> Runtime registry | evidence Ref `evidence:...attempt-1` | Runtime context 中的 pack + typed Ref；summary 保留 hash | 作为 Retriever 的正式 step output |
| 15 | Runtime -> Executor handler | approved step + attempt 2 Grant；输入为 source Ref + evidence Ref | 同进程 typed objects | 校验 Ref 并创建 `CodeGenerationRequest` |
| 16 | Executor handler -> Executor LLM | 任务目标、抽取规则、schema、证据正文、固定路径和代码 policy | CodeAct prompt；本次经本地 vLLM API | 生成只读固定输入、只写固定输出的 Python |
| 17 | Executor LLM -> CodeActRunner | Python 源码 | LLM 响应；保留为 `executor_initial_raw.txt` 和 generated source | 做 AST/path policy 审计 |
| 18 | CodeActRunner -> bwrap sandbox | 审计后的 Python + 七行 `inputs/task.json` | attempt 2 workspace 的文件；受限 mount/UID/GID | 从权威 row 抽取四个业务值 |
| 19 | sandbox -> Runtime validators | `outputs/result.json` | 191-byte workspace JSON | 校验 schema、provenance，并按授权输入重算 |
| 20 | validators -> Runtime registry | VERIFIED Executor `ExecutionArtifactRef` | result file + typed Ref + quality hashes | 成为 Executor 正式 step output |
| 21 | Runtime -> Summarizer handler | attempt 3 Grant；evidence Ref + Executor artifact Ref | 同进程 typed objects | 解析成 evidence/artifact 两张 catalog |
| 22 | Summarizer handler <-> LLM | task goal、verified row、证据 ID/locator/text；必要时引用修复 | 首次 ClaimSet JSON + citation-only repair JSON | 只能组合结论并从指定列复制引用 |
| 23 | Runtime -> final registry | 已验证 `ClaimSet` 和 `claimset-...attempt-3` | `outputs/claim_set.json` + VERIFIED artifact Ref | 标记 Runtime workflow 完成 |
| 24 | Runtime -> benchmark evaluator | 四个输出字段、claim、refs 和审计记录 | `summary.json` | 主链结束后才与隐藏 gold 比较 |

### 四个 Agent 最终各自看到了什么

| Agent | 真正可见的主要内容 | 明确看不到或不负责的内容 | 它交出的东西 |
| --- | --- | --- | --- |
| Planner | 任务目标、schema、source Ref 名称、能力白名单、预算 | source 正文、gold、真实 attempt 输出 Ref；不执行步骤 | 未批准的 `PlanProposal` |
| Retriever | 任务/检索目标、批准 corpus、证据类型、query/candidate 上限 | gold、最终答案、任意新路径；不亲自做矩阵 top-k | query 候选，随后被封装为 `EvidenceRequest` |
| Executor LLM | 任务目标、公开抽取规则、输出 schema、证据正文、固定文件路径 | embedding 矩阵、gold、任意文件权限；不直接判定自己输出已验证 | Python 源码 |
| Summarizer | verified result row、证据 ID、精确 locator、证据正文 | hidden gold、未验证 artifact、任意引用；不重新计算业务值 | `ClaimSet` 候选及必要的引用修复 |

---

## 11. 两套 section 编号不要混用

本例有两个 parser：

| parser | 是否保留标题导言 | `Market signal` 的编号 | `Fulfillment constraint` 的编号 |
| --- | --- | --- | --- |
| source-row adapter | 否 | source `section-1` | source `section-3` |
| semantic corpus | 是 | `ctx-section-2` | `ctx-section-4` |

所以：

~~~text
source row 的 section-1 != semantic candidate 的 ctx-section-1
~~~

业务代码使用明确的 `section` 字符串，不假设两套数字 ID 相同。

---

## 12. 关键英文术语

| 英文 | 本文中的准确含义 |
| --- | --- |
| canonical | 规范化后由系统认可的唯一表达 |
| envelope | 一次运行的权限和预算边界 |
| capability | 注册并可被授权执行的一类能力 |
| DAG | 用有向无环边表达步骤顺序和依赖 |
| Grant | 某一步某次 attempt 的临时授权 |
| Ref | 指向受管理对象的 typed reference |
| attempt | 某个 step 的一次实际执行尝试；重试会有新的 attempt |
| handler | Runtime 中负责实现某类 capability 的处理函数 |
| dispatcher | 根据 role/capability 把已授权 step 交给对应 handler 的分发器 |
| prompt | Runtime 最终发送给角色模型的指令和受控输入文本 |
| schema | 一个对象允许有哪些字段、各字段是什么类型 |
| contract | 上下游共同遵守的输入、输出和校验约定，范围通常比 schema 更广 |
| query | Retriever 生成、用于查找证据的自然语言搜索问题 |
| corpus | 已批准可检索的文档或数据集合 |
| fragment | parser 从文档切出的一段连续文本 |
| candidate | 检索阶段尚待筛选的候选片段 |
| embedding | 文本经 encoder 得到的稠密数值向量 |
| cosine similarity | 两个归一化向量的点积相似度 |
| top-k | 按分数排序后保留前 k 个候选 |
| manifest | 用于解释另一个对象的清单；本例把矩阵行映射到证据 ID 和位置 |
| hydrate | 按 manifest 将 ID 恢复成证据对象 |
| locator | 证据在源文档中的可验证位置 |
| evidence pack | 包含证据 ID、文本、score、locator 的规范对象 |
| fan-in | 将多条 query 的结果按稳定规则汇合、去重 |
| artifact | 写入受控工作区、带 hash 和验证状态的执行产物 |
| workspace | 某任务或 attempt 允许读写的受控目录 |
| claim | Summarizer 输出的一条人类可读结论及其支持关系 |
| provenance | 数据来源和处理链 |
| CodeAct | 模型生成代码，再由受限环境执行 |

---

## 13. 关键代码和运行证据

### 四份角色 prompt 在哪里组装

| 角色调用 | 当前实现入口 | prompt 的主要输入 | 模型必须返回 |
| --- | --- | --- | --- |
| Planner | `v2/runtime/role_path.py:2169` 的 `propose_plan()`；角色 instruction 从 `:2268` 开始 | 任务目标、允许输入 Ref、能力表、角色数量、预算、输出合同 | `PlanProposal` JSON |
| Retriever | `v2/runtime/role_path.py:2409` 的 `build_evidence_request()`；角色 instruction 从 `:2435` 开始 | task/step goal、批准 corpus、证据类型、实体/时间 authority、query/candidate 上限 | query、证据类型、corpus、候选上限 JSON |
| Executor CodeAct | `v2/runtime/llm_codeact.py:88` 的 `build_code_generation_prompt()` | `CodeGenerationRequest` 中的任务规则、schema、证据文本、固定路径和 policy | 一份 Python 文件或严格的 `{"code": "..."}` |
| Summarizer | `v2/runtime/role_path.py:2570` 的 `build_claim_set()`；角色 instruction 从 `:2645` 开始 | verified result rows + evidence ID/locator/text catalog + task goal | `ClaimSet` JSON |
| Summarizer 引用修复 | `v2/runtime/role_path.py:2759` 的 `repair_claim_citations()`；修复 instruction 从 `:2784` 开始 | 原 claim ID、校验错误、三列允许引用值 | 只能包含三个引用字段的 repair JSON |

这里说“prompt 在某行”是指 Python 在运行时拼装 prompt 的入口，不表示仓库里有五个
独立 `.txt` 文件。角色 instruction、结构化 payload 和 response schema 会在调用时合并。

### 数据对象和运行时入口

按本文时间线阅读：

| 内容 | 位置 |
| --- | --- |
| 样例任务 | `v2/benchmark/samples/semantic_holdout/manifest.json` |
| JSON 转 `CanonicalTaskSpec` | `v2/benchmark/semantic_holdout.py:35` |
| `CanonicalTaskSpec` | `v2/contracts/models.py:181` |
| source/schema adapter 与 operation semantics | `v2/benchmark/adaptive_formal.py:626`、`:472` |
| `AdaptiveTaskEnvelope` | `v2/contracts/adaptive.py:139` |
| Envelope 构造 | `v2/benchmark/adaptive_formal_mainline.py:895` |
| `PlanStepProposal` / `PlanProposal` | `v2/contracts/adaptive.py:209`、`:248` |
| Controller 编译 step wiring | `v2/benchmark/adaptive_formal_mainline.py:469` |
| Runtime 传播 Ref / 签发 Grant | `v2/runtime/adaptive_runtime.py:820`、`:836` |
| `CapabilityGrant` | `v2/contracts/adaptive.py:747` |
| `EvidenceRequest` | `v2/contracts/adaptive.py:360` |
| Markdown corpus / fragment 切分 | `v2/retrieval/corpus.py:692`、`:859` |
| query/candidate embedding | `v2/retrieval/pipeline.py:275` |
| 三 query fan-out / evidence fan-in | `v2/retrieval/pipeline.py:1427` |
| dense matrix / publish / top-k | `v2/state/semantic_state.py:139`、`:161`、`:398` |
| UDS Protobuf `ExecRequest` / `SuccessResult` | `v2/control/statebus_v2.proto:62`、`:116` |
| 跨进程消费和水合选择 | `v2/runtime/adaptive_dispatcher.py:733`、`v2/retrieval/pipeline.py:1645` |
| `SemanticStateRef` / `ExecutionArtifactRef` | `v2/refs/models.py:53`、`:218` |
| `EvidenceItem` / `CanonicalEvidencePack` | `v2/refs/models.py:297`、`:309` |
| Executor 输入和 `CodeGenerationRequest` 组装 | `v2/runtime/adaptive_dispatcher.py:2005`、`:2156` |
| `CodeGenerationRequest` 合同 | `v2/contracts/llm_codeact.py:78` |
| Summarizer dispatch | `v2/runtime/adaptive_dispatcher.py:2478` |
| `Claim` / `ClaimSet` | `v2/contracts/adaptive.py:618`、`:651` |

真实运行目录：

~~~text
/home/qcrs/statebus/runs/contest_evidence_closure_20260720/
e4_semantic_holdout_final4_20260720_175430/runtime/semantic-holdout/
semantic_holdout_20260720_095449_678020029/cases/semantic-holdout-s1
~~~

最有用的证据文件：

| 文件 | 能验证什么 |
| --- | --- |
| `planner_trace.json` | Planner 原始 ID、Controller 编译后的 ID 和依赖 |
| `summary.json` | 三条 query、向量选择、Ref、输出和质量结果 |
| `runtime/state/metadata/*.json` | 9 x 1024、float32、shared memory、PID |
| `source/source_rows.json` | Executor 的完整权威数据 |
| `executor_initial_raw.txt` | Executor LLM 生成的 Python |
| `runtime/.../outputs/result.json` | sandbox 真实输出 |
| `runtime/.../outputs/claim_set.json` | Summarizer 最终 ClaimSet |
