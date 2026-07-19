# StateBus v2：一个已登记任务怎样经过四个角色

> **本文的目标。** 这不是组件目录，也不是赛题完成度报告。它只沿着一个真实、已登记的长文档任务，回答新成员最容易追问的事：任务是谁定义的；四个角色分别收到了什么；Prompt 长什么样；它们的回答存到哪里；下一个角色为什么能继续；最终谁决定结果可信。
>
> **先读这一篇，再查细节。** 本文是按时间流动的入门主线。需要逐字段核验 `Protobuf`、`StateRef`、工作区、控制帧、失败状态机或 CodeAct 脚本时，再读配套的[结构化协议、控制层与 CodeAct 参考](statebus_v2_agent_controlplane_codeact_architecture_zh.md)。两篇文档不会把“模型看到的文本”“程序保存的 JSON”“Ref 指向的文件”混为同一种上下文。
>
> **代码口径。** 主调用入口是 `v2/runtime/smoke.py::run_smoke()`（约 1830 行起）。本文用 `long_doc_metric_replay_v1` 的第 2 轮 `replay-longdoc-002` 举例；任务登记在 `v2/benchmark/samples/continuous_task_families/long_doc_metric_replay/manifest.json`，其加载校验在 `v2/benchmark/continuous_task_family.py:204-330`。示例 JSON 只解释字段形状，不是假装来自某一次模型运行。

## 1. 先给结论：这四个角色怎样协作

StateBus v2 不是四个聊天机器人轮流接话，也不是 Planner 派发子任务的主从系统。当前主路径是一个**中心程序主导、角色职责受合同约束的流水线**：

```text
控制权（谁决定下一步）

run_smoke()  ──调用──> Planner LLM
     │                         │
     │                 只返回检索语义候选
     │                         v
     ├──运行──> 检索程序 ──调用──> Retriever LLM
     │                                      │
     │                            只从候选表选择 route/tool
     │                                      v
     ├────────────────────────────────> Executor LLM
     │                                      │
     │                            只复核同一候选表
     │                                      v
     ├──运行──> CodeActRunner（固定脚本 + 预置 Python 函数）
     │                                      │
     │                            写出候选结果文件
     │                                      v
     ├──调用──────────────────────────> Summarizer LLM
     │                                      │
     │                            只写摘要候选
     │                                      v
     └──调用──> validator / RuntimeDriver / commit gate
                    决定是否验证、保存、复用
```

这里有两个看似相近、实际不同的“控制器”。

| 名称 | 在本次任务中真正做什么 | 不做什么 |
| --- | --- | --- |
| `run_smoke()` | 主路径的**顺序编排者**：编译任务、调用四个角色、运行检索和 CodeAct、准备结果和验证输入 | 不把 Planner 的回答当作工作流命令；不允许角色自行跳步 |
| `RuntimeDriver` | 在角色和 CodeAct 已产生结果后，处理固定 workflow 的控制帧、状态/工件 Ref、会话、提交门和持久化 | 不实时指挥 Planner 决定“下一步叫谁”；不替 LLM 规划新 DAG |
| `RuntimeSupervisor` | 跟踪一个受控执行步骤的 `dispatched -> acked -> running -> completed/failed/trapped` 生命周期 | 不理解“收入、日志、长文档”等业务语义 |

因此，最准确的描述是：**四个角色通过 runtime 重新打包的结构化交接物协作；它们不是直接互相发消息、共享聊天历史或拥有相互调用权限。** `ROLE_GRAPH` 虽然记为 `planner->retriever->executor->summarizer`，但实际调用顺序由 Python 固定，见 `v2/runtime/role_contract.py:7-58` 与 `v2/runtime/smoke.py:1868-2585`。

**本节结论：** 角色提供的是受限的候选结果；`run_smoke()` 决定何时调用它们；校验器和 Driver 决定候选能否成为可信状态。不要把角色顺序箭头理解为 Agent 之间的直接调用。

## 2. 任务在进入四个角色前，已经怎样“登记”

### 2.1 “登记”不是一个运行时按钮，而是四处保持一致的代码合同

新成员常问：“只要把自然语言整理成 `CanonicalTaskSpec`，是不是任何任务就能进来？”答案是否定的。

`CanonicalTaskSpec` 可以直译为**规范任务合同**。它像一张由程序审核的工单，而不是模型随意写出的提示词。正式 benchmark 的 `BENCHMARK_STRICT` 模式甚至要求调用方已经提供这张工单；缺少它会立即拒绝，见 `v2/runtime/compiler.py:145-164`、`tests/v2/test_runtime_and_benchmark.py:130-176`。

当前没有一个“上传插件后自动注册新 Agent 能力”的通用注册服务。一个任务能力实际上要在下列位置对齐：

```text
样例/任务清单
  定义：原始请求、CanonicalTaskSpec、质量检查、预期事实、复用关系
       │
       v
TaskCompiler 的 allowlist
  接受：task_family / intent_op / required_outputs / required_tools
       │
       v
检索分发 + route/tool 目录
  知道：怎样读取这种数据；本轮允许模型从哪些 route/tool 中选择
       │
       v
CodeAct 数据任务分发
  知道：这个 intent 的预置 Python 实现是什么
       │
       v
validator
  知道：哪些字段、文件、事实或质量规则必须成立
```

这五层都不是纯文档约定：它们分别位于 `continuous_task_family.py`、`compiler.py`、`retrieval/pipeline.py` 与 `route_tool_catalog.py`、`runtime/codeact_data_tasks.py`、`runtime/smoke.py` 的校验函数。只填一个 JSON，通常只能通过其中最早的一层，不能让后面凭空获得读取数据、执行计算或判断答案的能力。

### 2.2 本文跟踪的真实登记任务

第 2 轮任务的自然语言请求是：从 ACME 的长文档里按季度提取 `revenue_musd`。正式执行前，清单已经给出了下面的合同（删去了和本节无关的外层字段）：

```json
{
  "task_id": "replay-longdoc-002",
  "request_text": "Replay-track metric triplet: extract ACME metric quarters ...",
  "canonical_task_spec": {
    "task_family": "continuous_long_doc_table_analysis",
    "intent_op": "extract_metric_series_generic",
    "required_outputs": [
      "metric_series_ref", "metric_name", "value_q1", "value_q2", "value_q3"
    ],
    "required_tools": ["table_retriever"],
    "arguments": {
      "dataset_id": "acme_ops_2026",
      "document_path": "v2/benchmark/samples/continuous_task_families/long_doc_table/acme_ops_report_2026.md",
      "metric": "revenue_musd",
      "quarters": ["2026Q1", "2026Q2", "2026Q3"]
    }
  },
  "quality_checks": [
    "artifact_exists:metric_series_ref", "exact:metric_name",
    "exact:value_q1", "exact:value_q3"
  ]
}
```

这里还有一个运行时细节：`quality_checks` 与 `expected_facts` 在 manifest 的外层，但连续任务 runner 会复制前者到执行用 spec 的 `arguments["quality_checks"]`，并将后者作为 `run_smoke(expected_facts=...)` 的独立参数传入。因此它们确实会到达 validator，而不是只停留在样例说明中，见 `v2/benchmark/continuous_runner.py:141-167、1113-1123` 与 `v2/runtime/smoke.py:2654-2669`。

先把每个英文键翻译成问题，而不是死记名字：

| 字段 | 中文问题 | 本例的含义 | 谁实际使用 |
| --- | --- | --- | --- |
| `task_family` | “这是哪一种数据和工作场景？” | 预期 Markdown 长文档加表格 | Compiler、RetrieverFanoutPipeline、CodeAct 分支 |
| `intent_op` | “在这个场景里做哪一个已登记动作？” | 提取一个可变指标的季度序列 | Compiler、route/tool 表、CodeAct 分支、validator |
| `required_outputs` | “交付结果必须包含哪些机器可检查的键？” | 一个序列文件引用、指标名、三个季度值 | CodeAct 写入前检查、最终 validator |
| `required_tools` | “这张工单声称依赖哪些能力？” | `table_retriever` | Compiler、候选表约束、审计 |
| `arguments` | “这一次任务的变量是什么？” | 文档位置、指标名、季度列表 | 数据读取器和预置执行函数 |
| `quality_checks` | “怎样判定这轮结果合格？” | 文件存在、字段精确匹配 | 运行时质量检查，不是 LLM 自报 |

一个容易混淆的点：`intent_op` 不等于 LLM 必须输出的 `route`。本例 `intent_op` 是 `extract_metric_series_generic`，而 route/tool 目录中的可见候选会使用类似 `extract_metric_series::table_retriever` 的名字。前者是**动作合同标识**，后者是**本轮给 Retriever/Executor 选择的处理路线标识**。候选目录的生成逻辑见 `v2/route_tool_catalog.py:190-247、267-362`。

### 2.3 登记时到底要满足什么要求

以当前代码为准，至少有这些硬条件：

1. 连续任务的 `manifest.json` 必须声明 schema 版本、至少十轮、存在的数据集、每轮唯一 `task_id`、非空原始请求、完整 `CanonicalTaskSpec`、非空输出/工具、只指向前序轮次的依赖、复用合同和质量检查。加载器逐项检查，见 `v2/benchmark/continuous_task_family.py:204-307`。
2. 严格编译器只接受五个 `task_family`、显式 allowlist 中的 `intent_op`、输出键和工具键；列表定义和校验分别在 `v2/runtime/compiler.py:20-143、260-294`。
3. 数据读取要有对应分支。本例长文档分支读取 `document_path`，而 CSV、incident log、跨期文档会走不同 resolver，见 `v2/retrieval/pipeline.py:1019-1079`。
4. 若动作需要真正产出，`build_candidate_output_payload()` 必须能分发到实现。本例由 `_build_long_doc_output_payload()` 读取 Markdown、解析已知表结构并写序列工件，见 `v2/runtime/codeact_data_tasks.py:435-658、772-830`。
5. 输出必须能被验证。工单上的 `required_outputs`、可选 `quality_checks` 和 benchmark 传入的 `expected_facts` 最终会由程序检查，见 `v2/runtime/smoke.py:2654-2669`。

所以，若新需求只是“同一种 Markdown 表格，换一个指标”，通常改 `arguments.metric` 即可；若需求是“任意 PDF 的重点摘要”，它会先卡在数据读取/证据结构，随后还会缺少执行动作和质量合同。第 12 节会把这些边界逐一拆开。

**本节结论：** 当前的“注册”是分散在任务清单、allowlist、数据 adapter、route/tool 目录、预置执行代码和 validator 的静态合同，不是一个把自然语言自动泛化为新能力的机制。

## 3. 先认识本流程里出现的对象

以下对象会反复出现。理解它们能避免把“存盘了”“被模型看见了”“被下一步消费了”误认为同一件事。

| 中文名 | 源码名 | 用一句话说明 | 典型形态 |
| --- | --- | --- | --- |
| 任务合同 | `CanonicalTaskSpec` | 规定这轮允许做什么、必须交什么 | JSON；`inputs/canonical_task_spec.json` |
| 规划交接单 | `PlannerHandoff` | 记录 Planner 提议和程序最终采用的检索目标 | JSON；`inputs/planner_handoff.json` |
| 证据包 | `CanonicalEvidencePack` | 检索程序选出的表格事实、语义段落、结构化证据及来源 | JSON；`inputs/evidence_pack.json` |
| 证据定位表 | `HydrateManifest` | 说明证据在源文档的哪一段/单元格，可回查 | JSON；`inputs/hydrate_manifest.json` |
| 候选表 | `tc`，candidate surface | 本轮允许 LLM 选择的 route/tool 闭集 | Prompt 内紧凑 JSON，不是全局工具市场 |
| 角色证据片段 | `RolePromptSlice` | 某一个角色本轮真正看到的文本、表格、工件/记忆摘要 | 重新嵌入 Prompt，不自动暴露 workspace |
| 执行请求 | `CodeActRequest` | 给固定 CodeAct 执行器的参数、输出合同和已验证选择 | JSON；`inputs/*.codeact_bundle.json` |
| 执行工件引用 | `ExecutionArtifactRef` | 指向可审计结果文件，带 hash、状态、manifest | Ref；不内联整份文件 |

`CanonicalTaskSpec` 和 `PlannerHandoff` 的字段定义在 `v2/contracts/models.py:169-237`；证据包和 `ExecutionArtifactRef` 定义在 `v2/refs/models.py:105-233`；角色片段定义在 `v2/runtime/role_path.py:244-300`。

```text
同一条信息的三种形态，必须区分

原文中的 “2026Q1 revenue = 120”
      │  检索程序抽取
      v
evidence_pack.json 中的结构化证据（可审计、可定位）
      │  runtime 为某角色裁剪
      v
Prompt 的 e 字段中的少量文本（模型可读）
      │  CodeAct 物化
      v
outputs/result.json 和 ExecutionArtifactRef（下游可引用、可验证）
```

**本节结论：** 四个角色不靠同一个聊天窗口共享上下文；它们靠不同用途的 JSON、文件、Ref 和 Prompt 片段间接协作。

## 4. 一眼看完整条流：控制流、数据流和可见性

图中的实线 `=>` 是控制权，虚线 `..>` 是对象流。括号里的 `P:` 表示真正放进该角色 Prompt 的内容，不表示它能打开整个文件。

```text
图 1：从已登记任务到最终工件

manifest.json
  ..> request_text + CanonicalTaskSpec + quality_checks
  => run_smoke()
        |
        +=> TaskCompiler
        |     ..> 已校验 CanonicalTaskSpec
        |
        +=> Planner LLM
        |     P: goal, query, summary hint, allowed outputs, entity/time hints
        |     ..> 原始 JSON + effective semantic plan
        |
        +=> semantic-plan resolver
        |     ..> PlannerHandoff / retrieval objective
        |
        +=> RetrieverFanoutPipeline（纯程序检索）
        |     ..> evidence pack + hydrate manifest + query embedding + candidate pool
        |
        +=> Retriever LLM
        |     P: query + retrieved document IDs + tc + evidence slice (+ memory 摘要)
        |     ..> 已归一化 RetrieverRoleDecision
        |
        +=> Executor LLM
        |     P: Retriever route/tool + action contract + 同一 tc + table slice
        |     ..> 已归一化 ExecutorRoleDecision
        |
        +=> CodeActRunner
        |     ..> codeact bundle + 固定脚本 + candidate_result.json
        |
        +=> Summarizer LLM
        |     P: evidence slice + 执行结果摘要 + action handoff (+ memory 摘要)
        |     ..> summary_text 候选
        |
        +=> validator + RuntimeDriver
              ..> outputs/result.json + manifest + ExecutionArtifactRef + replay/memory records
```

```text
图 2：谁拥有控制权，谁只提供候选

[run_smoke()] ----控制----> [Planner]        Planner 不能调用任何角色
      |                         |
      |                 语义计划候选
      v                         v
[semantic resolver] ---> [RetrieverFanoutPipeline]
      |                          |
      |               证据包、候选表、embedding
      v                          v
             [Retriever] ----候选选择----> [Executor]
                    ^                         |
                    |                         | 已验证的 route/tool/action_contract
                    |                         v
                  没有直接消息              [CodeActRunner]
                                                  |
                                                  | 文件和候选结果
                                                  v
                                              [Summarizer]
                                                  |
                                                  | 摘要候选
                                                  v
                                     [validator / RuntimeDriver / commit gate]

实线控制权：只在中心 runtime / Driver 一侧
箭头数据：必须经过 parser、结构化字段、文件或 Ref；不是角色间私聊
```

**本节结论：** 把“控制谁下一步运行”和“把什么数据交给下游”分开，流程才不会显得神秘。当前只有中心程序拥有前一种权力。

## 5. 第 0 步：Compiler 先决定任务能不能进门

`run_smoke()` 构造 `TaskCompilerInput`，并固定使用 `TaskMode.BENCHMARK_STRICT`；在这一模式，原始 `request_text` 不是编译的唯一依据，`precompiled_canonical_task_spec` 才是必须存在的合同，见 `v2/runtime/smoke.py:1868-1878`。

```text
输入
  request_text: 给 Planner 的人类任务描述
  precompiled_canonical_task_spec: 给程序的结构化合同

Compiler 输出
  COMPILED + CanonicalTaskSpec
  或 REJECTED + compiler_errors
```

这一步没有 LLM 调用。它逐一检查：

```text
task_family       是否在 allowlist？
intent_op         是否在 allowlist？
required_outputs  是否全是已知输出键、且非空？
required_tools    是否全是已知工具键？
arguments         是否为 mapping？
```

通过后，runtime 将规范合同写入 `inputs/canonical_task_spec.json`。这个文件供审计和后续程序使用；**没有任何代码让某个 LLM 因为文件存在而自动读取它**。每个角色只会拿到从它派生的少数字段。

非 strict 的交互式分支确实有一个简单 heuristic：文本里出现 `compare` 或 `chart` 时映射到少数旧 intent；它不能创建新的 family、tool 或执行实现，见 `v2/runtime/compiler.py:296-323`。因此它不是通用自然语言任务编译器。

**本节结论：** 任务合同是后续协作的共同边界。它先限制“可以做什么”，再让每个角色在自己的小范围里工作；它不等于让任意自然语言需求获得执行能力。

## 6. 第 1 步：Planner 怎样知道自己是 Planner

### 6.1 谁调用它，输入从哪里来

`run_smoke()` 根据任务合同构造：目标 `goal`、任务查询 `query_text`、摘要提示 `summary_hint`、允许输出 `required_outputs`、实体和时间范围；随后调用 `RolePathRunner.plan_workflow()`，见 `v2/runtime/smoke.py:1897-1931`、`v2/runtime/role_path.py:1279-1348`。

虽然调用点临时创建了一个包含历史/文本信息的 Planner slice，`plan_workflow()` 随即显式 `del prompt_slice`。检索完成后 runtime 也把 Planner slice 置空。因此主路径的 Planner **看不到**长文档正文、表格、候选工具、memory 命中、Retriever/Executor 回复或完整 workspace，见 `v2/runtime/role_path.py:1297-1300`、`v2/runtime/smoke.py:1982-1986`。

### 6.2 Prompt 的固定模板和动态字段

实际请求是一个 user message，并非持久聊天会话里的 API `system` message。`RolePathRunner._render_prompt()` 通过 `compile_prefix_layout()` 组装它，`_complete_json_role()` 以 `purpose="planner"` 发给 LLM client，见 `v2/runtime/role_path.py:974-1085`。默认 `structured_collaboration` 模式的概念外壳是：

```text
You are the StateBus v2 planner role.

<固定 Planner 指令>

<sb-plan-v1>
{ "g": ..., "q": ..., "h": ..., "ao": [...], "en": [...], "ts": ... }
</sb-plan-v1>
```

若测试切换为 `text_collaboration`，同样的动态值不会放在 tagged JSON，而会渲染为 `Goal:`、`Task request:`、`Summary hint:`、`Allowed required outputs:` 等带标题文本段落。二者是并列比较模式，不会在同一默认 structured Prompt 中叠加，见 `v2/runtime/role_path.py:304-337、404-456`。

这里的缩写只是为了压缩 Prompt，并不是新的神秘协议：

| Prompt 键 | 中文 | 本例来源 |
| --- | --- | --- |
| `g` | 目标 | 由 `task_family + intent_op + arguments` 派生 |
| `q` | 查询/原始请求 | manifest 的 `request_text`，为空时回退到 spec query |
| `h` | 摘要提示 | runtime 从 spec 派生 |
| `ao` | 允许输出键 | `required_outputs` |
| `en` | 实体提示 | `target_entities` |
| `ts` | 时间范围提示 | `time_scope` |

固定 Planner 指令的实质是：只返回一个 JSON，其中的 `semantic_task_plan` 要分别给 lexical、semantic、table、memory 四类检索写查询和目标；`memory_reuse_intent` 只能是 `none/assist/artifact/strategy`；证据类型和输出键必须在已登记集合；**禁止输出 workflow steps、DAG、code、route、tool、candidate key、预期数值或最终答案**。原文在 `v2/runtime/role_path.py:998-1007`。

对本例，动态 JSON 的核心大致是：

```json
{
  "g": "Extract metric series for revenue_musd from ACME operations long document",
  "q": "Replay-track metric triplet: extract ACME metric quarters ...",
  "h": "acme_ops_2026 extract_metric_series_generic cited summary ready",
  "ao": ["metric_series_ref", "metric_name", "value_q1", "value_q2", "value_q3"]
}
```

这不是把整篇报告交给模型，而是让模型在既定任务类型内改善“检索该朝哪里找”。它真正能自主决定的是查询措辞、实体/时间描述、不同检索桶的目标和允许集合内的证据类型建议。

Planner 的成功回复必须长成下面这种**扁平计划字段被包在 `semantic_task_plan` 中**的结构；值只是解释性的例子，运行时不会信任其中任何新工具、数值或工作流声明：

```json
{
  "semantic_task_plan": {
    "goal": "extract the quarterly revenue_musd series",
    "entities": ["ACME", "revenue_musd"],
    "time_scope": "2026Q1 to 2026Q3",
    "lexical_query": "ACME revenue_musd metric table",
    "lexical_objective": "locate document and metric-table metadata",
    "semantic_query": "quarterly revenue evidence",
    "semantic_objective": "locate supporting narrative context",
    "table_query": "revenue_musd 2026Q1 2026Q2 2026Q3",
    "table_objective": "locate metric table cells",
    "memory_query": "ACME generic metric series",
    "memory_objective": "find reusable metric-table artifacts",
    "memory_reuse_intent": "assist",
    "required_evidence": ["table_cell", "table_schema"],
    "required_outputs": ["metric_series_ref", "metric_name", "value_q1", "value_q2", "value_q3"]
  }
}
```

### 6.3 Planner 输出如何变成下游可用信息

模型原始 JSON 是一个**不可信候选**。`resolve_semantic_task_plan()` 会：抽取 JSON、扫描被禁止的内容、限制文本长度、检查 retrieval objective、evidence type 和 required output 的 allowlist；无效时回退为 runtime 按任务合同生成的计划，有效时也可能把模型字段与 fallback 合并，见 `v2/runtime/semantic_plan.py:302-440、512-571`。

最终保存的是 `PlannerHandoff`，而不是“Planner 接管的任务图”：

```text
inputs/planner_handoff.json
  task_id                         这轮任务是谁
  canonical_task_spec_hash        绑定哪张任务合同
  retrieval_objective             后续检索真正消费的有效目标
  planner_plan_payload            模型返回的规范化计划候选
  planner_scope_payload           runtime 生成的上下文摘要
  semantic_plan_audit             每个字段来自模型、fallback 或二者合并
  retriever_consumed_objective_hashes  检索程序实际使用了哪些目标
  planner_raw_output_hash         原始回复的审计 hash
```

`RetrieverFanoutPipeline.run()` 消费的是 effective objective，而不是 Planner 的一段自然语言解释，见 `v2/runtime/smoke.py:1932-1981`、`v2/retrieval/pipeline.py:1026-1038`。

**本节结论：** Planner 知道自己的角色，是因为每次请求的 role label、固定禁止项、动态任务字段和 JSON schema 都由 runtime 写入 Prompt。它的作用是受限检索语义规划，不是派工、拆 DAG 或直接求答案。

## 7. 第 2 步：程序先检索，Retriever LLM 后选择

“Retriever”在当前代码里有两层，不能混为一个全自主 Agent：

```text
RetrieverFanoutPipeline（程序）
  读取文档 -> 词法/语义/表格检索 -> 汇聚证据 -> 生成 query embedding 和候选池

Retriever LLM（角色）
  阅读被裁剪的证据与候选表 -> 从闭集选一个 route/tool
```

### 7.1 程序检索产生了什么

本例命中 `continuous_long_doc_table_analysis` 分支，读取 `document_path` 所指的 ACME Markdown；随后 lexical、semantic、table 三个检索器运行，见 `v2/retrieval/pipeline.py:1019-1120`。它产生：

| 产物 | 里面有什么 | 保存/使用位置 | 是否直接给 LLM |
| --- | --- | --- | --- |
| query embedding | 查询的数值向量及元数据 | state store / semantic retrieval / memory lookup | 否，模型不读取向量数组 |
| evidence pack | 表格事实、语义段落、结构化证据、来源 hash | `inputs/evidence_pack.json` | 仅经 slice 摘取部分文本 |
| hydrate manifest | 每条证据的 source locator、稳定键 | `inputs/hydrate_manifest.json` | 不直接；用于裁剪与回查 |
| retrieval log | 查询、候选、hash、审计数据 | `inputs/retrieval_log.json` | 不直接 |
| candidate pool | 检索到的候选事实/文档 | 生成候选 route/tool surface 的输入 | 不直接原样给 LLM |

embedding 是检索和 memory 相似度计算的非文本数据，不是“把上一 Agent 的隐藏状态传给下一模型”。在开启状态传递时，runtime 将 embedding 的 canonical JSON bytes 发布为 `EMBEDDING_STATE`，并创建 `SemanticStateRef`；后端可以是 `shared_memory`、`mmap` 或 `memfd`，见 `v2/runtime/smoke.py:1988-2007`、`v2/state/store.py`。存储方式影响 bytes 如何传输和审计，不会自动扩大 LLM 的可见范围。

### 7.2 角色证据片段：下游为何不需要共享聊天记录

runtime 从同一 evidence pack 构造不同 `RolePromptSlice`，规则在 `v2/runtime/smoke.py:1193-1282`：

```text
Planner      空 slice：只看任务语义字段
Retriever    语义段落 + 表格事实 + 结构化证据 + 最多少量记忆摘要
Executor     表格事实 + 结构化证据 + 最多少量记忆摘要
Summarizer   语义段落 + 表格事实 + 结构化证据 + 执行产物摘要 + 记忆摘要
```

所以“前一个角色怎样把上下文交给后一个角色”的准确答案是：**不是把原始 completion 接到 Prompt 尾部，而是 runtime 提取已验证字段，重新合成该角色唯一允许看到的 slice。** 例如 Executor 没有 Retriever 的完整推理文本；它只得到解析后的 route/tool、同一候选表和自己的证据片段。

### 7.3 Retriever Prompt、输出与校验

Retriever 的固定指令是“从可见候选中选择恰好一个；逐字复制 `candidate_key`、`route`、`tool_name`；不得编造标签；返回 JSON”。原文见 `v2/runtime/role_path.py:1010-1024`。它收到的动态 payload 是：

```json
{
  "q": "有效检索查询",
  "rd": ["已选源文档 hash"],
  "tc": [
    {"k": "extract_metric_series::table_retriever",
     "r": "extract_metric_series", "t": "table_retriever", "d": ["..."]}
  ],
  "pc": {"k": "...", "r": "...", "t": "..."},
  "e": "本角色允许看的表格事实和证据文本"
}
```

`tc` 是 **tool candidate surface** 的缩写，即“本轮可见候选表”。`k/r/t/d` 分别是候选键、route、tool、支持文档 ID；完整构造在 `v2/runtime/role_path.py:513-539`。`pc` 是可选的程序偏好候选/平局提示，不能越过 `tc` 创造新候选。

模型应返回：

```json
{
  "candidate_key": "extract_metric_series::table_retriever",
  "route": "extract_metric_series",
  "tool_name": "table_retriever",
  "supporting_doc_ids": ["sha256:..."],
  "reason": "table facts contain the requested quarterly values"
}
```

Python 再用 `_normalize_candidate_selection()` 将值匹配回 `tc`。local vLLM 时还会给 `candidate_key/route/tool_name` 生成 enum JSON schema；其他 client 可能忽略 response schema，因此程序仍做匹配。格式错误最多尝试三次；若选择候选表外的 route/tool，主路径 `allow_assisted_correction=False`，重试耗尽后抛错，而不是悄悄改成某个工具，见 `v2/runtime/role_path.py:546-578、1350-1470`、`v2/runtime/smoke.py:2411-2421`。

**本节结论：** 当前“检索”主要是程序的检索与证据构造；Retriever LLM 的关键作用是依据证据在一个受限候选闭集里做选择。它不联网、不自建数据源，也不新增工具。

## 8. 第 3 步：Executor 复核选择，CodeAct 才真正执行

### 8.1 Executor LLM 看见什么、能改什么

Executor 的输入不是 Retriever 的完整对话，而是 runtime 已归一化后的：

```text
route            Retriever 已选路线
tool_name        Retriever 已选工具
action_contract  固定为 materialize_validated_artifact
tc               与 Retriever 相同的候选表
pc               可选程序偏好候选
e                Executor 专属表格/结构化证据片段
```

对应 Prompt 的压缩键为 `r/t/a/tc/pc/e`。固定指令要求它只在可见 `tc` 内验证或重选一个 route/tool，返回 `candidate_key/route/tool_name/action_contract/reason` JSON，见 `v2/runtime/role_path.py:1026-1039、1472-1642`。它同样最多重试三次，且主路径禁止“模型选错后由程序替它随意修正”。

一个形状正确的 Executor 回复如下；`action_contract` 即使模型省略，也会由代码回退到调用方给定的 `materialize_validated_artifact`，而不是让模型定义任意命令：

```json
{
  "candidate_key": "extract_metric_series::table_retriever",
  "route": "extract_metric_series",
  "tool_name": "table_retriever",
  "action_contract": "materialize_validated_artifact",
  "reason": "the visible table evidence contains the requested quarter values"
}
```

这一步的真实价值是一个独立、受相同证据闭集约束的选择/复核点；它**不是**一个能够自由运行 shell、打开任意文件、安装依赖或生成主路径 Python 的 Code Agent。

### 8.2 交给 CodeAct 的不是自然语言，而是结构化请求

通过 Executor 复核后，`run_smoke()` 构造 `CodeActRequest`，见 `v2/runtime/smoke.py:2471-2510`。关键字段及含义如下：

| 字段 | 解释 | 来源 |
| --- | --- | --- |
| `task_id/step_id/attempt_id` | 哪一轮、哪个步骤、哪次尝试 | runtime |
| `task_family/intent_op/spec_arguments` | 要走哪个预置数据任务分支、变量是什么 | 任务合同 |
| `required_outputs/quality_checks` | 必须写哪些键、后续怎样验 | 任务合同 |
| `route/tool_name/action_contract` | 已验证的执行选择 | Executor decision |
| `selected_doc_hashes/supporting_doc_ids` | 使用哪份证据/源文档 | retrieval + Retriever decision |
| `evidence_pack_hash/retrieval_log_hash` | 绑定到哪个检索证据和审计记录 | retrieval |
| `history_runtime_roots/reuse_contract` | 允许使用哪些历史运行目录与复用声明 | 连续任务合同 |

这个请求和固定计划一起写入：

```text
inputs/step-execute.attempt-1.codeact_bundle.json
```

**本节结论：** Executor LLM 的输出是 CodeAct 的一部分输入，但不是可直接执行的命令。真正执行前，route/tool/action contract 仍会被固定脚本检查。

## 9. 第 4 步：CodeAct 的真实路径，不要把它理解成自由写代码

### 9.1 真正运行了什么

`CodeActRunner.build_plan()` 对常规任务固定生成三阶段：准备执行上下文、验证选择、写候选结果，见 `v2/runtime/codeact.py:428-513`。`run()` 写入 bundle 和一个由 `_build_script()` 生成的固定 Python 脚本，随后启动这个脚本，见 `v2/runtime/codeact.py:515-645、774-930`。

```text
CodeActRequest
  -> 固定 CodeActPlan
  -> 固定脚本 run_executor.py
  -> build_candidate_output_payload(request, workspace_root)
  -> tmp/candidate_result.json
  -> tmp/...codeact_result.json（含每阶段结果与 hash）
  -> 运行时验证
```

这个脚本确实是 Python，也确实在受控子进程里运行；但它由 runtime 模板产生，导入的是仓库已有的 `v2.runtime.codeact_data_tasks.build_candidate_output_payload`。核心主路径没有“LLM 输出一段 Python -> 提取代码块 -> AST 审核 -> 执行模型代码”这一环。

### 9.2 本例到底做了哪种处理

`task_family=continuous_long_doc_table_analysis` 使脚本调用 `_build_long_doc_output_payload()`；`intent_op=extract_metric_series_generic` 让它读取指定 Markdown、解析预期的指标表、按 `arguments.metric` 和 `quarters` 写出：

```json
{
  "metric_series_ref": ".../metric_series.json",
  "metric_name": "revenue_musd",
  "value_q1": "120",
  "value_q2": "132",
  "value_q3": "145",
  "route": "extract_metric_series",
  "tool_name": "table_retriever"
}
```

其中 `metric_series_ref` 是一个指向工作区内序列工件的**文本引用字段**；它不意味着所有下游模型都自动打开该文件。实现分支见 `v2/runtime/codeact_data_tasks.py:435-658、772-830`。

### 9.3 sandbox、缓存和它们的边界

`CodeActSandboxRunner` 优先尝试 `bwrap`；不可用时（当前宿主机往往如此）退回 resource-limit 子进程；也可显式为 `none`，见 `v2/runtime/codeact_sandbox.py:58-152`。resource fallback 限制 CPU、地址空间、文件大小、文件数和进程数，但它不是完整文件系统隔离。因此不能把它描述为“任意模型代码的强安全沙箱”。

`CodeActRunner` 有进程内 deterministic cache，key 是 request 和固定 plan 的 hash；命中时物化缓存的脚本、结果和工件，见 `v2/runtime/codeact.py:647-726`。这是对相同受控执行的加速，不是让 Agent 自己学习新算法。

**本节结论：** 当前核心 CodeAct 是“结构化请求 + 固定脚本 + 预置处理函数”的混合执行器。它能对已实现的数据任务换参数运行，但不是主路径的开放式 LLM 编程平台。

## 10. 第 5 步：Summarizer 怎样使用前面结果

CodeAct 成功后，runtime 从 candidate output 只摘出 route、tool、metric 名和值、selected/supporting document IDs，组成 `artifact_slice_text`；它不会把脚本、stdout、stderr 或整个 workspace 全塞进 Prompt，见 `v2/runtime/smoke.py:2515-2585`。

Summarizer 的 payload 是：

```json
{
  "tf": "continuous_long_doc_table_analysis",
  "h": "... cited summary ready",
  "t": ["table_retriever"],
  "r": ["retrieve", "execute"],
  "e": "证据片段 + 执行结果的小型 JSON 摘要",
  "a": "route=...\ntool=...\naction_contract=..."
}
```

`tf/h/t/r/e/a` 分别代表任务大类、摘要提示、标签、可复用步骤提示、可见证据、动作交接。固定 Prompt 要求紧凑 JSON；正常模式只能给 `summary/reusable_steps/confidence/tags`，`summary` 少于 80 词，见 `v2/runtime/role_path.py:1042-1052、1644-1720`。

其正常输出形状如下。`confidence` 是模型自报字段，不参与把 artifact 判为正确；`reusable_steps` 也只是短提示，不是新的执行计划：

```json
{
  "summary": "The report's revenue_musd series is 120, 132, and 145 for Q1-Q3.",
  "reusable_steps": ["retrieve", "execute"],
  "confidence": 0.9,
  "tags": ["table_retriever"]
}
```

它的 `summary_text` 会覆盖最终 JSON 里的摘要字段，但不会改动 CodeAct 写出的 `value_q1`、工件 hash、route、tool 或验证状态。也就是说，Summarizer 在这里承担的是**面向人的受限表述和复用提示**，不是事实裁判。

**本节结论：** Summarizer 知道前面发生了什么，是因为 runtime 提供了经过选择的证据和执行摘要；它没有完整对话史，也没有修改可验证事实和提交状态的权力。

## 11. 最后谁相信结果，文件实际落在哪里

正常运行会在任务工作区中形成以下可审计对象：

```text
<workspace>/<task_id>/
  inputs/canonical_task_spec.json                 任务合同
  inputs/planner_handoff.json                     规划交接单
  inputs/evidence_pack.json                       证据包
  inputs/hydrate_manifest.json                    证据定位表
  inputs/retrieval_log.json                       检索审计
  inputs/step-execute.attempt-1.codeact_bundle.json  CodeAct 请求与计划
  script/step-execute.attempt-1.run_executor.py   runtime 生成的固定脚本
  tmp/candidate_result.json                        CodeAct 候选结果
  tmp/step-execute.attempt-1.codeact_result.json  阶段结果、hash、stdout/stderr 元数据
  outputs/result.json                             最终结果 JSON
  manifest/...                                    输入/输出 manifest、validator report
  logs/...                                        执行 stdout/stderr 工件
```

`WorkspaceManager` 负责稳定路径、内容 hash 和 manifest；其布局与写入实现见 `v2/runtime/workspace.py:24-129、300-456`。最终的信任链如下：

```text
LLM 原始文本
  -> JSON 提取与 schema/闭集检查
  -> Planner fallback/hybrid 或 Retriever/Executor 的候选匹配
  -> 固定 CodeAct 的 route/tool/action 合同检查
  -> required_outputs 是否齐全
  -> quality_checks / expected_facts / artifact manifest 验证
  -> RuntimeCommitGate
  -> ExecutionArtifactRef 标为 candidate、verified 或 invalidated
```

`ExecutionArtifactRef` 的 `verification_state`、`blob_hash`、`manifest_hash`、`relpath` 和 `replay_ready` 才是下游可审计的执行结论；它和仅表示状态 bytes 的 `StateRef` 是两种不同引用，见 `v2/refs/models.py:105-134`。一段流畅的 Summary 不能跳过这些检查。

**本节结论：** 系统最后相信的是“文件、hash、合同和校验报告共同满足”的结果，不是某个 Agent 的自信声明。

## 12. memory、embedding、Ref 在四个角色关系中的位置

这些机制重要，但它们不会改变“谁调度谁”。

| 机制 | 当前用于什么 | 是否直接给 LLM 看 | 是否是 Agent 直接通信 |
| --- | --- | --- | --- |
| embedding / `SemanticStateRef` | 语义检索、memory 相似度、可选非文本状态传输 | 否，LLM 只可能看到由它检索出的文本证据 | 否，由 state store 和 runtime 管理 |
| evidence pack / hydrate manifest | 证据定位、角色视图裁剪、可复核 | 只给角色 slice 中的文本部分 | 否，runtime 重新组装 |
| `ExecutionArtifactRef` | 指向结果和 manifest，用于后续引用/replay | 只有 runtime 摘取的 artifact text 进入 Summary Prompt | 否，引用由控制层管理 |
| memory commit / memory match | 保存摘要、任务主题、来源与复用等级；查询历史相似任务 | 当前最多将少量 summary/score 等放入角色 slice | 否，MemoryIndexStore 管理 |
| replay | 在合同、输入 hash、runtime signature、历史 verified 输出兼容时减少步骤 | 不由 LLM “记得了”触发 | 否，是 gate 的程序决策 |

Memory 通过 SQLite 元数据、可选 FAISS 或余弦相似度查询；candidate/未验证记忆会降为 assist，见 `v2/memory/store.py:27-229`。exact replay 的准入还要求任务合同、输入 artifact hash、运行时签名和输出合同一致，见 `v2/runtime/replay.py:82-167`。这意味着“后续 Agent 有记忆”在当前实现中通常是收到一小段受控摘要或触发程序复用，不是共享一个无限上下文窗口。

**本节结论：** 非文本状态、memory 和 Ref 是 runtime 管理的中介层；它们帮助减少重复检索或支持审计，但不赋予角色相互读取隐藏状态、相互调用或无边界记忆的权限。

## 13. 当前系统哪里固化，哪里可以泛化

下面的五道门比“输入是不是 JSON”更能说明当前边界：

```text
自然语言需求
  │
  ├─ 门 1：能否写成并通过 CanonicalTaskSpec？
  │        TaskCompiler / manifest / allowlist
  │
  ├─ 门 2：能否读取该数据并形成可靠证据？
  │        retriever adapter / parser / evidence schema
  │
  ├─ 门 3：是否有本轮可选的 route/tool 合同？
  │        route_tool_catalog / candidate surface
  │
  ├─ 门 4：是否已有实际执行实现？
  │        CodeAct helper / executor / 环境与安全策略
  │
  └─ 门 5：是否知道怎样验证结果？
           required_outputs / quality_checks / expected facts / commit gate
```

| 想要的新能力 | 最先遇到的主要边界 | 为什么不能只改输入 |
| --- | --- | --- |
| 同格式长文档，换公司/指标/季度 | 边界较小，主要是 `arguments` | adapter、表解析、动作和输出合同仍相同 |
| 长文档“挑重点并总结” | 门 1、4、5 | 需定义 `intent_op`、重点证据的产物格式、执行/筛选逻辑和何为合格 |
| 分析陌生 PDF、网页、扫描件 | 门 2 | 当前 Markdown/CSV/log resolver 和证据 locator 不保证能读或可复核 |
| 自由迭代写程序、安装库、调用外部 API | 门 4 | 当前 CodeAct 主线没有模型代码入口、依赖解析、权限和开放式验收 |
| 分析未知代码库 bug | 门 1、2、4、5 | 需要代码库索引/诊断工具、可运行测试、补丁合同和 bug 修复验证 |
| 多个子任务并行、失败后改计划再委派 | 门 1 之外的调度层 | Planner/Driver 没有动态任务图、权限、依赖、冲突解决和结果验收循环 |

因此不能简单说“Executor 是唯一问题”。对**开放式执行**，Executor/CodeAct 是最大限制；对**新任务进门**，Compiler/任务登记最先限制；对**新数据格式**，retrieval adapter 与证据 schema 最关键；对**自主协作**，Planner 与 Driver 缺少动态分解和再调度能力。

### “分析长文本、挑重点、梳理总结”能不能做？

作为架构形态可以做，而且四角色可保持不变：Planner 把 focus 转成检索目标；Retriever 找候选段落与定位；Executor 物化有证据的 `key_points` 工件；Summarizer 只根据该工件写总结。但当前代码里的 `retrieve_narrative_evidence`、`draft_risk_memo`、`final_cited_report` 都是已写好的样例分支，不能宣传为对任意文档的通用理解。

为了把这个需求变成真实能力，至少要显式增加：

```text
intent_op = extract_key_points
arguments = document_path, focus, max_points
required_outputs = key_points_ref, evidence_refs, summary_text
```

再补同格式数据 adapter（若原 Markdown 格式不变可复用）、预置筛选/工件函数、候选 route/tool、质量检查和测试任务。模型仍可负责“focus 如何表达、哪些候选证据更相关、怎样组织摘要”，而程序负责可定位事实与最终验收。

**本节结论：** StateBus v2 有参数级泛化，也有在既定数据/动作合同内的模型选择自由；它还没有跨数据格式、跨工具和跨验证逻辑的通用任务执行能力。输入结构化是必要条件，但远远不是充分条件。

## 14. 最终回答：四个 Agent 到底是什么，不是什么

它们是四个有独立 Prompt、输入可见性、输出合同和有限决策空间的**受限角色步骤**：

| 角色 | 真正承担的作用 | 交给下游的核心物 | 不承担的作用 |
| --- | --- | --- | --- |
| Planner | 用 LLM 改善已登记的检索目标 | 经 resolver 校验的 `PlannerHandoff` | 子任务分派、DAG 编排、工具选择、最终答案 |
| Retriever | 用 LLM 在已生成候选表中选择 route/tool | 归一化 `RetrieverRoleDecision` | 自行搜索新数据、添加工具、直接执行 |
| Executor | 用 LLM 复核同一闭集里的选择与动作合同 | 归一化 `ExecutorRoleDecision` | 任意 shell/Python、改任务合同、自由修复 |
| Summarizer | 用 LLM 将已给证据和执行摘要写成短说明 | `summary_text`、标签和复用提示 | 改写数值/文件、验证 artifact、直接提交 memory |

它们协作的核心不在“模型之间说了很多话”，而在以下链条：

```text
合同限制输入与输出
  -> 程序把证据变成每角色可见 slice
  -> LLM 在该 slice 和 schema 内给候选
  -> parser/validator 把候选转为可信结构化状态
  -> 下游只读取所需字段、文件或 Ref
```

这使当前系统适合比较低开销结构化交接、非文本状态和受控 memory/replay 的效果；代价是角色自主性和跨任务泛化能力都被刻意限制。它不是一个可以仅靠一句自然语言需求就自动发明工具、写任意程序、协商任务图并可靠验收的通用多 Agent 平台。

**本节结论：** 当前 StateBus v2 是“中心化控制下、以结构化合同和证据中介协作的四角色 runtime”。这既是它的可复现性来源，也是它最重要的能力边界。
