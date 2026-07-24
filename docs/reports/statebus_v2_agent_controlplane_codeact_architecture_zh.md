# StateBus v2：结构化协议、控制层与 CodeAct 参考

> **本文是什么。** 这是 [一个已登记任务怎样经过四个角色](statebus_v2_agent_task_flow_zh.md) 的技术参考册。前一篇按一个真实任务解释时间顺序；本文按“对象合同 -> Prompt -> 控制层 -> CodeAct -> 失败/边界”的顺序，回答字段到底代表什么、由谁写、谁读、怎样验证。
>
> **本文不是什么。** 它不把 `Planner / Retriever / Executor / Summarizer` 夸大为平等自治网络，也不把 embedding、Prefix 或 memory 写成 Agent 间隐藏状态直传。每项结论都标明它属于实际主路径、测试/诊断探针还是设计/接口能力。
>
> **主路径口径。** `v2.benchmark.live_runner` 与 `minimal_runner` 最终调用 `v2/runtime/smoke.py::run_smoke()`；后者是本文所说的实际单任务路径。`RuntimeDriver`、UDS/Protobuf 控制帧和 subprocess transport 是同一任务的生命周期与 transport 层，但不能据此改写为“每个 LLM 通过 UDS 相互对话”。

## 1. 先建立三条边界

### 1.1 三个问题，三个不同答案

| 要问的问题 | 当前代码中的答案 | 容易产生的错误理解 |
| --- | --- | --- |
| 谁决定下一步？ | `run_smoke()` 按固定顺序调用角色和 CodeAct；Driver 固化 lifecycle workflow | “Planner 输出 plan，所以它在调度” |
| 下游从哪里得到上游信息？ | runtime 解析上游候选后，以 JSON 字段、证据 slice、文件或 Ref 重组给下游 | “四个角色共享完整聊天历史” |
| 谁相信最终结果？ | parser、候选闭集、CodeAct、validator、commit gate 和 Ref 状态 | “Summarizer 写得通顺，所以答案已验证” |

`run_smoke()` 的顺序调用在 `v2/runtime/smoke.py:1868-2585`；固定 workflow 的声明在 `smoke.py:1794-1827` 与 `v2/runtime/driver.py:207-242`；角色图常量在 `v2/runtime/role_contract.py:7-58`。

### 1.2 三种信息形态

源码里的英文对象较多，但所有交接物可以先放进三个篮子：

```text
1. 给模型读的文本：Prompt 内的任务字段、tc 候选表、e 证据片段
   - 短、按角色裁剪、每次重新生成

2. 给程序读的结构化合同：CanonicalTaskSpec、PlannerHandoff、CodeActRequest、validator report
   - JSON/dataclass、可 hash、可检查

3. 给存储/传输层读的引用：StateRef、ExecutionArtifactRef、RefHandle、manifest hash
   - 指向 bytes 或文件；通常不把内容内联到 Prompt
```

一个对象可以同时落盘和被程序读取，却不等于 LLM 能打开它。例如 `inputs/evidence_pack.json` 存在于 workspace，但 Retriever 看见的只是 runtime 从中挑出的 `e` 文本；Executor 看见的又是另一份 slice。

### 1.3 新成员应先记住的缩写

| 短写 | 中文解释 | 不应误解为 |
| --- | --- | --- |
| `tc` | **本轮可见候选表**（tool candidate surface） | 全局工具目录或模型能调用的一切工具 |
| `pc` | 程序给出的**偏好候选**，用于平局提示 | 绕过 `tc` 的隐藏命令 |
| `e` | 这个角色允许看的**证据文本片段** | 完整 evidence pack / 完整历史对话 |
| `r` / `t` / `a` | route / tool / action contract，即路线、工具、动作合同 | 可执行 shell 命令 |
| `Ref` | 指向状态或工件的带身份引用 | 引用内容自动进入模型上下文 |
| `hash` | 内容或规范 JSON 的摘要，用于绑定和审计 | 对内容正确性的数学证明 |

**本章结论：** 阅读 v2 时先区分文本、结构化合同和引用；再区分调用顺序、数据传递和最终授权。大多数“Agent 怎么知道上下文”的困惑来自把它们混为一谈。

## 2. 结构化交接物总图

下面是实际主路径中最重要的对象流。粗箭头是程序控制，不是 LLM 自行发送 RPC。

```text
任务清单 / 调用方
  │  request_text + precompiled CanonicalTaskSpec
  v
TaskCompiler ──────> CanonicalTaskSpec
  │                       │
  │                       ├──写入 inputs/canonical_task_spec.json
  │                       └──派生 goal/query/outputs/arguments
  v
Planner Prompt ─────> Planner 原始 JSON
  │                       │
  v                       v
semantic-plan resolver -> effective semantic plan -> PlannerHandoff
                                                    │
                                                    ├──写入 inputs/planner_handoff.json
                                                    v
RetrieverFanoutPipeline -> EvidencePack + HydrateManifest + embedding + candidate pool
                              │               │                    │
                              │               │                    └──可选 StateRef
                              │               └──写入 inputs/hydrate_manifest.json
                              └──写入 inputs/evidence_pack.json
                                           │
       RolePromptSlice + tc 候选表 <──────┘
             │                         │
             v                         v
        Retriever decision          Executor decision
             │                         │
             └──────> CodeActRequest <─┘
                              │
                              v
            CodeAct bundle + 固定脚本 + candidate output + execution record
                              │
                              v
       artifact slice -> Summarizer decision -> output JSON -> validator reports
                              │                         │
                              v                         v
                    MemoryCommit / ReplayLedger    ExecutionArtifactRef
```

下面的矩阵是“谁向谁传什么”的精确读法。`直接可见给 LLM` 只回答“是否会被 Prompt 文本化”，不回答对象是否持久化。

| 上游 | 下游 | 中介 | 具体对象/字段 | 形态 | 直接可见给 LLM | 谁校验 |
| --- | --- | --- | --- | --- | --- | --- |
| manifest / 调用方 | TaskCompiler | Python 参数 | `request_text`、预编译 `CanonicalTaskSpec` | 文本 + dataclass | 仅 `request_text` 会进入 Planner Prompt | Compiler allowlist |
| Compiler | Planner | runtime 参数 | `goal`、`query_text`、`summary_hint`、outputs、entity/time hints | Prompt JSON | 是，字段被压缩为 `g/q/h/ao/en/ts` | JSON parser + semantic resolver |
| Planner | Retriever pipeline | `PlannerHandoff` / effective plan | 四类 retrieval objectives、审计 hash | JSON 文件 + 内存对象 | 否；pipeline 消费结构化字段 | semantic-plan resolver |
| Retriever pipeline | Retriever LLM | `RolePromptSlice` + `tc` | query、document IDs、证据文本、候选 route/tool | Prompt JSON + 文本 | 是，只有 slice | closed-set parser |
| Retriever LLM | Executor LLM | 归一化 decision + runtime 重组 | `route`、`tool_name`、支持 doc IDs；同一 `tc` | dataclass -> Prompt | route/tool 与 Executor slice 可见 | candidate matching |
| Executor LLM | CodeAct | `CodeActRequest` | route/tool/action、spec、参数、必需输出、证据 hash | JSON bundle | 否，CodeAct 是程序/脚本 | 固定脚本 + required-output 检查 |
| CodeAct | Summarizer LLM | artifact slice + action handoff | route/tool、metric、值、doc IDs、少量证据 | Prompt 文本 | 是，摘要而非完整文件 | Summary JSON parser；事实另验 |
| output + reports | Driver / registry | `ExecutionArtifactRef`、manifest、validator reports | `relpath/blob_hash/status/replay_ready` 等 | 文件 + Ref | 否 | RuntimeCommitGate |
| verified output | memory/replay | `MemoryCommit`、`ReplayLedgerEntry` | summary、来源、合同 hash、artifact ref、replay class | 结构化持久化 | 仅受控摘要可进入后续 role slice | Memory store + replay gate |

对象定义的主要入口：`CanonicalTaskSpec`/`PlannerHandoff` 在 `v2/contracts/models.py:169-237`；证据与 artifact Ref 在 `v2/refs/models.py:105-233`；CodeAct 请求在 `v2/runtime/codeact.py:139-204`；控制消息在 `v2/control/messages.py:25-133`。

**本章结论：** 所有“角色间传递”都可落到一张合同、一个字段、一个 workspace 文件或一个 Ref。没有“上游模型的隐含想法自动流入下游模型”的通道。

## 3. 任务合同与任务登记：系统最早的边界

### 3.1 `CanonicalTaskSpec` 的字段和来源

`CanonicalTaskSpec` 是 immutable dataclass，含 `task_family`、`intent_op`、`target_entities`、`time_scope`、`required_outputs`、`required_tools`、`arguments`、`schema_version`，并可产生稳定的 `spec_hash`，见 `v2/contracts/models.py:178-204`。

| 字段 | 程序语义 | 为什么要有 |
| --- | --- | --- |
| `task_family` | 数据/场景的处理族 | 选择 document/csv/log resolver 和可用 route profile |
| `intent_op` | 在该族内的登记动作 | 选择 CodeAct 数据任务分支与输出语义 |
| `target_entities` / `time_scope` | 任务限定词 | 供 Planner 构造检索语义，非自由事实 |
| `required_outputs` | 必须存在的结果键 | 让固定脚本和 validator 有机器可检查的交付标准 |
| `required_tools` | 声明所需能力 | 限制候选表与记录合同依赖 |
| `arguments` | 本轮参数 | 如文档路径、指标、季度、服务名 |
| `spec_hash` | canonical payload 的 sha256 | 绑定 handoff、memory/replay 与审计对象 |

严格模式的 `TaskCompiler` 不从任意一句话猜出一个新任务。它要求调用方给 `precompiled_canonical_task_spec`，随后校验四个 enum 面，见 `v2/runtime/compiler.py:145-164、260-294`。可接受 family、intent、outputs、tools 都直接写在 `TaskCompiler` 的元组里，见 `compiler.py:20-143`。

### 3.2 “注册一个新任务”在当前代码中意味着什么

当前没有单一 `register_task()` API。新增能力需要按实际变化补齐下面的组合：

| 若改变的是 | 必须核对/新增的位置 | 失败时的表现 |
| --- | --- | --- |
| 新 task family 或 intent | `TaskCompiler` allowlist、样例 manifest | strict compiler `REJECTED` |
| 新数据形态 | `RetrieverFanoutPipeline.run()` 的 resolver、证据提取与 locator | 无法读取、证据不可靠或进入默认 corpus |
| 新 route/tool | `v2/route_tool_catalog.py` profile | LLM 的 `tc` 中永远看不到它 |
| 新计算/文件产物 | `codeact_data_tasks.py` 的预置分支和工件写入 | 固定脚本无实现或 required output 缺失 |
| 新结果语义 | 输出 allowlist、quality check、expected-fact/test | 即使执行出内容也无法稳定验收 |

这解释了为什么“把输入变成正确格式”不足以得到泛化：合同只解决第一步的命名与边界，不会凭空实现 parser、工具、算法、依赖策略或验收规则。

### 3.3 任务清单与正式运行的区别

连续任务清单 loader 检查 manifest schema、十轮要求、数据集存在、依赖只向后、复用合同和质量检查是否齐全，见 `v2/benchmark/continuous_task_family.py:204-307`。它保证“实验任务描述完整”，但不替代运行时 Compiler、retrieval 或 CodeAct 的实现检查。

相反，`tests/v2/test_runtime_and_benchmark.py:130-256` 证明了 strict compiler 对缺少预编译合同、非法 intent、若干已登记样例的接受/拒绝行为；它不证明任意自然语言任务已被理解或可执行。

**本章结论：** `CanonicalTaskSpec` 是必要的统一入口，不是通用能力生成器。当前能力登记是静态、分层且需要代码实现配合的。

## 4. Prompt：角色如何知道职责、可见范围和输出格式

### 4.1 四个请求共享的外壳

`RolePathRunner._render_prompt()` 调用 `compile_prefix_layout()`；结构化协作模式最终呈现为：

```text
You are the StateBus v2 <role> role.
<该角色的固定 instruction>

<sb-<role>-v1>
{该次调用的紧凑 JSON payload}
</sb-<role>-v1>
```

代码构造位置为 `v2/runtime/role_path.py:304-337、404-479、974-996`。之后 `_complete_json_role()` 将它作为**单个 user message**发送，附带 `purpose` 和可选 response schema；不存在每个角色保持一个携带历史的常驻 chat session，见 `role_path.py:1054-1108`。

`text_collaboration` 模式会把相同信息用带标题的自然文本段落写出；`structured_collaboration` 则用 tagged JSON。若启用 `shared_evidence_prefix`，同一证据会置于 `<statebus-shared-prefix-v1>`，以对齐 Prompt 前缀；这只是 Prompt 布局/可能的引擎内 prefix reuse 观测，代码明示不导出 KV tensor，见 `v2/runtime/role_path.py:26-30、340-379`。

### 4.2 固定指令逐角色解释

下表先给“指令所施加的权限边界”，再给“模型真正承担的认知工作”。这里的英文 key 是源码实际要求，后列立即给出中文解释。

| 角色 | 固定 instruction 的关键要求 | 动态 payload | 模型真正做什么 | 明确不做什么 |
| --- | --- | --- | --- | --- |
| Planner | 返回一个 `semantic_task_plan`；只能使用登记的 evidence/output；禁止 workflow/DAG/code/route/tool/答案 | `g/q/h/ao/en/ts` | 为词法、语义、表格、记忆四种检索写不同目标 | 不派工、不选候选、不写程序、不读原文事实 |
| Retriever | 从一个 `tc` 项逐字复制 `candidate_key/route/tool_name`，不得发明标签 | `q/rd/tc/pc/e` | 结合证据判断可见 route/tool 哪一个最合适 | 不新建数据源、工具或 route |
| Executor | 在同一个 `tc` 内验证 route/tool，返回 action contract | `r/t/a/tc/pc/e` | 二次复核选择和证据是否一致 | 不直接执行 shell/Python，不改任务合同 |
| Summarizer | 只给紧凑 JSON；正常模式 `summary/reusable_steps/confidence/tags`，摘要少于 80 词 | `tf/h/t/r/e/a` | 把已给证据与执行摘要组织成人可读短结论 | 不改数值、工件、Ref 状态或 memory commit |

固定 instruction 原文位置：Planner `v2/runtime/role_path.py:998-1007`；Retriever `1010-1024`；Executor `1026-1040`；Summarizer `1042-1052`。这四段规定的是模型的**行为提示**，不是唯一安全边界；后面还有 schema、parser 和程序校验。

为了让读者能直接判断模型被要求做什么，下面保留四段固定模板的实质内容。`[pc tie-break]` 是只有存在偏好候选时才替换进去的一句平局规则；其余文字是当前源码的固定约束，不随这轮文档、指标或记忆内容改变。

```text
Planner
Return exactly one JSON object containing semantic_task_plan with these exact
flat keys: goal, entities, time_scope, lexical_query, lexical_objective,
semantic_query, semantic_objective, table_query, table_objective, memory_query,
memory_objective, memory_reuse_intent, required_evidence, required_outputs.
Give lexical, semantic, table, and memory different retrieval goals.
memory_reuse_intent must be none, assist, artifact, or strategy.
required_evidence may only contain lexical_metadata, semantic_context,
table_cell, table_schema, artifact_summary, memory_artifact, memory_strategy,
or citation. Use only allowed required outputs. Do not emit workflow steps,
DAGs, code, case IDs, routes, tools, candidate keys, expected facts, values,
or answers.

Retriever
Select exactly one visible route/tool candidate. Copy candidate_key, route, and
tool_name exactly from a single visible tc item. [pc tie-break: when enabled,
prefer pc only when evidence does not clearly contradict it; otherwise choose
independently from complete tc.] Do not invent labels or use placeholders such
as 'tool' or 'route'. Return a JSON object (starting with { and ending with })
with keys candidate_key, route, tool_name, supporting_doc_ids, and reason.

Executor
Validate the chosen route/tool within the visible candidate set. Copy
candidate_key, route, and tool_name exactly from a single visible tc item.
[pc tie-break: when enabled, prefer pc only when evidence does not clearly
contradict it; otherwise validate only Retriever-selected route/tool against
complete tc.] Do not invent labels or use placeholders such as 'tool' or
'route'. Return a JSON object (starting with { and ending with }) with keys
candidate_key, route, tool_name, action_contract, and reason.

Summarizer（正常模式）
Return exactly one compact JSON object and no prose. Use keys summary,
reusable_steps, confidence, and tags. Keep summary under 80 words.
reusable_steps must contain at most 2 short generic step names.
```

这不是完整运行时 Prompt：完整请求还会在它后面或 tagged JSON 中加入本节其他表格解释的动态字段；也不应把它误读为 API 的 `system` message。它的作用是让同一个 LLM client 在每次调用时得到明确角色边界，而 parser/schema/validator 负责把“提示”变成不可绕过的程序约束。

### 4.3 Planner 的 Prompt、输出和 fallback

Planner payload 的字典：

| 键 | 意义 | 值来源 |
| --- | --- | --- |
| `g` | goal，目标 | `_goal_from_spec()` |
| `q` | query，原始请求或 fallback query | `request_text` / `_query_text_from_spec()` |
| `h` | summary hint，摘要提示 | `_summary_hint_from_spec()` |
| `ao` | allowed outputs，允许输出 | spec.required_outputs |
| `en` | entity hints，实体提示 | spec.target_entities |
| `ts` | time scope，时间范围 | spec.time_scope |

`plan_workflow()` 刻意删除传入的 `prompt_slice`，所以 Planner 不消费 corpus、候选表或 memory 命中，见 `v2/runtime/role_path.py:1279-1330`。模型返回的 JSON 会被 canonicalize 后交给 `resolve_semantic_task_plan()`：后者限制字段长度、检查 allowlist、扫描禁止词/字段，必要时用 runtime fallback 或 hybrid 合并，见 `v2/runtime/semantic_plan.py:302-440、512-571`。

这说明 Planner 的输出地位是：**可影响检索目标的候选语义，不是下一步的命令。** 其持久化交接物 `PlannerHandoff` 的关键字段如下：

| 字段 | 为什么保存 | 实际消费者 |
| --- | --- | --- |
| `canonical_task_spec_hash` | 保证计划绑定当前任务 | replay/audit |
| `retrieval_objective` | 最终有效检索查询和目标 | RetrieverFanoutPipeline |
| `planner_plan_payload` | 原始规范化计划候选 | 审计、CodeAct metadata |
| `semantic_plan_audit` | 哪些字段来自模型/fallback/hybrid | telemetry/audit |
| `retriever_consumed_objective_hashes` | 证明检索实际消费了哪些目标 | telemetry/replay |
| `planner_raw_output_hash` | 保留原始回复的可比身份 | 审计 |

### 4.4 Retriever 与 Executor 的闭集选择为何可信度更高

候选表由 route/tool catalog 和 retrieval candidate pool 生成，`tc` 的紧凑每项形式是：

```json
{
  "k": "route::tool_name",
  "r": "route",
  "t": "tool_name",
  "d": ["supporting source-document hashes"]
}
```

该 compact 形式来自 `v2/runtime/role_path.py:513-539`。route profile 不只是名称清单：它含 issue terms、rationale、偏好证据桶和稳定合同版本，见 `v2/route_tool_catalog.py:24-78、190-362`。

模型回复后，程序按如下层次处理：

```text
先抽取一个 JSON object
  -> response schema（local_vLLM 可强制枚举；其他 client 可忽略）
  -> 将 candidate_key/route/tool_name 映射回当前 tc
  -> 不可见或矛盾：追加 selection retry instruction
  -> 最多三次仍失败：抛 RoleSelectionError
```

response schema 只对支持它的 client 产生强约束，源码也明确说明外部 client 可忽略；因此不可把 schema 当作唯一防线，见 `v2/runtime/role_path.py:546-578`。`run_smoke()` 对 Retriever 和 Executor 都传 `strict_surface=True`、`allow_assisted_correction=False`，见 `v2/runtime/smoke.py:2411-2462`。

这里的“协作”是：Retriever 给出一个已归一化选择，Executor 看到该选择和同一可见 surface，做独立复核；双方都不能创造 surface 之外的动作。这种限制降低幻觉工具调用的影响面，但也降低开放式自主性。

### 4.5 Summarizer 的输入不是完整执行日志

CodeAct 后，runtime 将 route、tool、metric 名/值、selected/supporting doc IDs 摘成 `artifact_slice_text`，再加角色 slice 与 action handoff 给 Summarizer，见 `v2/runtime/smoke.py:2515-2585`。它的输出被解析为 `SummarizerRoleDecision`；只有 `summary_text` 被写进最终 output，其余事实仍来自 CodeAct。`SummarizerRoleDecision` 字段定义在 `v2/runtime/role_path.py:165-176`。

**本章结论：** 角色身份来自每次 runtime 重建的 Prompt，而不是模型天然知道自己是谁。四份 Prompt 的固定规则约束自由度，动态字段提供这一次任务的必要上下文；输出仍要经过程序转换，才能影响下游。

## 5. 证据、候选、工作区：结构化信息如何真正落地

### 5.1 `CanonicalEvidencePack` 不是“上下文”这个模糊词

证据包的字段是 `hard_facts`、`structured_evidence`、`semantic_contexts`、`lexical_hints`、`conflicts`、`source_doc_hashes`、`budget_meta`，见 `v2/refs/models.py:191-233`。

| bucket | 通俗说明 | 本例中的典型用途 | 谁可能在 Prompt 中看到 |
| --- | --- | --- | --- |
| `hard_facts` | 表格单元格、数值等硬事实 | 季度收入值 | Retriever、Executor、Summarizer 的受控片段 |
| `semantic_contexts` | 叙事段落的语义候选 | 风险、原因、行动叙述 | Retriever、Summarizer 的受控片段 |
| `structured_evidence` | 已结构化的表/工件/历史线索 | 表结构、artifact 摘要 | 依 slice 而定 |
| `lexical_hints` | 词法匹配线索 | 检索审计和候选生成 | 通常不直接给所有角色 |
| `conflicts` | 需要审计的冲突证据 | 保留冲突而不静默覆盖 | 依具体 slice/validator 而定 |

`HydrateManifest` 记录每条证据的 `SourceLocator`、稳定键、字节提示和源文档 hash，见 `v2/refs/models.py:137-176`。它让 runtime 可以从证据包生成不同角色片段，而不必给每个 LLM 重复整份文档。

### 5.2 四个角色的可见性边界

`_build_role_hydrated_slices()` 显式为角色选 bucket：Retriever 取语义和表格，Executor 取表格，Summarizer 取语义和表格；随后主路径把 Planner slice 清空，见 `v2/runtime/smoke.py:1193-1282、1982-1986`。

```text
完整 source document / full evidence pack
                  |
                  | runtime 选择 locator、hydrate、裁剪
                  v
Planner:    任务字段；没有 evidence 文本
Retriever:  semantic + table slice，tc，少量 memory 摘要
Executor:   table/structured slice，已选 route/tool，同一 tc，少量 memory 摘要
Summarizer: evidence slice + 仅含关键字段的 artifact slice + action handoff
```

`RolePromptSlice` 还把 text/table/artifact/memory 分开计数和计字节，字段见 `v2/runtime/role_path.py:244-300`。这是实验中测量不同协作层 Prompt 可见字节的基础，而不是把全部内部对象序列化给模型。

### 5.3 workspace 是审计材料，不是 LLM 共享盘

`WorkspaceManager` 的任务根目录固定有 `inputs/outputs/logs/tmp/script/manifest`，见 `v2/runtime/workspace.py:24-46、300-355`。它将规范 JSON 写入稳定相对路径，并保存 sha256 与 size；输入/输出 manifest 分别描述逻辑名、类型、路径、hash 和引用来源，见 `workspace.py:49-129、357-456`。

务必区分两个事实：

1. CodeAct 子进程可以按受控环境变量访问 workspace 的固定目录。
2. 四个 LLM 没有“读取 workspace 的工具调用”能力；只有 runtime 抽取文本后才会进入各自 Prompt。

**本章结论：** evidence pack 负责保存完整、可定位的证据；`RolePromptSlice` 负责角色可见性；workspace 负责审计和执行输入输出。三者配合，而非同义。

## 6. 控制层：它控制什么，不理解什么

### 6.1 两层控制不要混淆

```text
语义执行编排层（run_smoke）
  - 编译任务、调用四个角色、调用 retrieval/CodeAct、准备 validator 输入
  - 直接决定正常路径的调用顺序

生命周期与 transport 控制层（RuntimeDriver / Supervisor / Session / UDS）
  - 固定 workflow、尝试、ACK/heartbeat/timeout、Ref 注册、artifact 提交、持久化和审计
  - 不理解业务语义，不让 LLM 自由改 DAG
```

在实际 `run_smoke()` 中，CodeAct 已在约 2471 行运行，Summarizer 已在约 2574 行运行；之后才把 `PlannerHandoff`、retrieval、output、validator reports 等整体交给 `RuntimeDriver.run()`，见 `v2/runtime/smoke.py:2743-2824`。这意味着：**当前 RuntimeDriver 是主路径的控制/持久化层，不是一个先发 control frame 再让远端 LLM 依次完成四个角色的实时总调度器。**

### 6.2 每个控制组件的责任

| 组件 | 事实职责 | 明确不负责 |
| --- | --- | --- |
| `RuntimeDriver` | 建固定 workflow，管理 executor transport、Ref/manifest、artifact lifecycle、session、memory/replay/commit 结果 | 解释任务业务、让 Planner 发明下一张 DAG |
| `RuntimeSupervisor` | 每个执行步骤的合法状态转移、ACK/lease timeout、trap/cancel/GC | 决定哪个工具最适合业务问题 |
| `RuntimeSessionManager` | 保存一轮任务的 workflow、attempt、replan、Ref ID、状态和 hash | 保存 LLM 私有思维链 |
| `ReplayLedger` | 记录为什么允许/拒绝/降级 replay，绑定合同、artifact、runtime signature | 作为可自由修改的模型记忆 |
| `WorkspaceManager` | 布局、物化 JSON、manifest、hash | 决定模型能看到哪些文件 |

`RuntimeSupervisor` 的允许状态转移在 `v2/runtime/supervisor.py:45-205`；`RuntimeTaskSession` 和尝试/replan 字段在 `v2/runtime/session.py:23-250`；`ReplayLedgerEntry` 字段在 `v2/runtime/ledger.py:10-65`。

### 6.3 UDS + Protobuf 的真实作用

控制面将 `ControlHeader`、`ExecRequest`、`AckReceived`、`RunStart`、`Heartbeat`、`SuccessResult`、`ErrorResult`、取消/GC/trap 等编码为 Protobuf，再以四字节长度前缀 framing 在 UDS 上发送，见 `v2/control/messages.py:12-220、318-332`。

`ExecRequest` 包含的不是大段证据，而是：

```text
trace/task/step/attempt/target_role/timeout
reuse_policy
state_refs / artifact_refs / memory_refs
runtime_reuse_contract
output_contract_version
workspace_root
input_manifest_hash
```

`SubprocessExecutorTransport` 的协议是 `ExecRequest -> Ack -> RunStart -> Heartbeat -> Success/Error`，见 `v2/control/transport.py:283-380`。它说明正式类型化控制帧和 executor subprocess transport 代码存在；`tests/v2/test_subprocess_executor.py:21-83` 证明了有效/无效请求 round trip。它**不证明**四个 LLM 各自是通过 UDS 微服务相互协商，也不替代前述 `run_smoke()` 的角色调用。

### 6.4 集中控制的收益和代价

| 方面 | 得到什么 | 失去什么 |
| --- | --- | --- |
| 可复现性/实验公平性 | 相同合同、候选面、校验和步骤可比较 | 不能展示开放式自主分解 |
| 调试与审计 | 每步输入、hash、Ref、失败原因可定位 | 控制器和合同代码较重 |
| 成本/延迟 | 闭集选择和 slice 降低无界 Prompt/工具调用 | 固定四步有时会做不必要的角色调用 |
| 安全 | 模型不直接得到 shell/任意文件权限 | 对新的开放工具需求扩展较慢 |
| 错误影响范围 | 幻觉 route/tool 通常在 parser 前被拒绝 | 若程序 adapter/validator 本身错误，中心化缺陷影响整条路径 |

**本章结论：** 控制层主要解决可执行合同、生命周期、状态引用、故障处理和审计；它不是业务语义 planner，也不是四个自治 Agent 的消息总线。

## 7. CodeAct：真实实现、自由度与泛化边界

### 7.1 核心路径是固定计划和固定脚本

`CodeActRequest` 已含任务合同、执行选择、所需输出、检索/证据 hash、历史路径和 quality checks。`CodeActRunner.build_plan()` 对非 replay 降级任务固定生成：

```text
stage-materialize : prepare_execution_context
stage-validate    : validate_selection
stage-execute     : write_candidate_summary_json
```

见 `v2/runtime/codeact.py:428-513`。`CodeActRunner.run()`：

1. 将 request 和 plan 写进 `inputs/<step>.<attempt>.codeact_bundle.json`；
2. 通过 `_build_script()` 生成 `script/<step>.<attempt>.run_executor.py`；
3. 让 sandbox runner 启动这个脚本；
4. 读取 `tmp/...codeact_result.json` 和 `tmp/candidate_result.json`；
5. 生成 `CodeActExecutionRecord`，记录 exit code、hash、各阶段结果、sandbox 选择；
6. 成功时放入 request+plan hash 的 deterministic cache。

实现见 `v2/runtime/codeact.py:515-645、647-726`。

固定脚本导入 `build_candidate_output_payload`，只认识三种 action kind；对连贯 CSV、长文档、跨期财务、incident family 分发给预写函数，见 `v2/runtime/codeact.py:774-930`、`v2/runtime/codeact_data_tasks.py:772-830`。这就是核心结论：

> 主路径中的“generated code”是 runtime 模板生成的受控脚本；它不是 LLM 为每项任务自由生成的 Python。

### 7.2 代码限制来自三层，而不是只靠 Prompt

| 层 | 在核心 CodeAct 中如何限制 | 影响 |
| --- | --- | --- |
| 任务合同 | `task_family/intent_op/arguments/required_outputs` 指定动作和交付 | 不能从无合同的自然语言自由决定任务 |
| 程序实现 | 固定 plan、固定 action kind、预置 `build_candidate_output_payload` 分支 | 不能调用未实现算法、任意库或新工具 |
| 执行环境 | 输出必须在 `tmp/`；sandbox backend、资源上限、workspace 环境变量 | 不可把任意路径和资源视为已授权 |
| validator | required outputs、文件、质量/事实检查、commit gate | 模型/脚本写了 JSON 也不一定被接受 |

核心请求没有用于生成代码的 LLM Prompt，故也没有核心路径上的“模型代码提取、AST 检查、代码修复”流程。不能把辅助诊断脚本当成主实现。

### 7.3 LLM 生成代码在哪里，为什么它只是探针

仓库另有 `scripts/v2_diagnostics/bounded_llm_codeact_demo.py` 和 `tests/v2/test_bounded_llm_codeact_demo.py`。它会要求模型输出单个完整 Python 文件，提取 fenced/JSON code，做 AST policy audit，失败后发 repair prompt，最终可回退确定性代码。测试证明它会拒绝 `subprocess`、`open()` 等禁止项，也覆盖语法修复和 fallback，见 `tests/v2/test_bounded_llm_codeact_demo.py:19-175`。

它的边界同样很窄：固定输入 `inputs/task.json`、固定输出 `outputs/bounded_codeact_result.json`、受限标准库/AST 策略、明确的 repair 轮数。更重要的是，`run_smoke()` 并不调用这个 demo。因此它是**测试/开发探针**，不能作为“主 runtime 已支持自由 LLM CodeAct”的证据。

### 7.4 sandbox 的实际状态

`CodeActSandboxRunner` 的 backend 行为：

```text
requested auto/bwrap 且 bwrap 可用 -> bwrap（网络、PID、IPC、UTS namespace 等隔离）
requested auto 但 bwrap 缺失/失败 -> resource-limit subprocess
requested resource -> resource-limit subprocess
requested none -> 普通 subprocess
requested bwrap 但缺失 -> 明确 bwrap_missing 结果
```

见 `v2/runtime/codeact_sandbox.py:58-152、154-240`。resource fallback 有 CPU、地址空间、文件大小、文件描述符和进程数限制，但没有 bwrap 那种完整 namespace/file-system isolation。当前不能把 fallback 写成对不受信任 LLM 代码的强沙箱。

### 7.5 自由度分级

| 维度 | 等级 | 代码证据 | 原因 |
| --- | --- | --- | --- |
| 输入自由度 | **中** | `arguments` 可变；family/intent strict allowlist | 同一已支持动作可换文档路径、指标、季度；不能随意新定义任务 |
| Planner 检索语义自由度 | **低到中** | semantic plan schema + fallback/hybrid | 可改有限 query/objective，不能改 workflow/工具/答案 |
| Retriever/Executor 工具选择自由度 | **低** | `tc` closed set、strict matching | 只能从当前候选表选 route/tool |
| 代码生成自由度（核心） | **低** | `_build_script()` 固定模板 | LLM 不生成主路径 Python |
| 文件访问自由度 | **低** | workspace 根、固定 data adapter、sandbox env | 数据路径由 contract 和 helper 决定，LLM 无文件工具 |
| 依赖使用自由度 | **低** | 预置 helper + sandbox | 无安装依赖、无运行时包解析 |
| 输出自由度 | **低** | `required_outputs`、validator | 必须有指定键/工件，摘要也受 JSON/长度约束 |
| 跨任务泛化 | **低到中** | 多个预置 family/intent 分支 | 在同族参数变化中可复用；跨数据/算法/验证合同需新增代码 |

### 7.6 CodeAct 的真实泛化范围

它能在已实现 handler 所覆盖的场景中做参数级变化，例如同结构长文档抽不同 `metric`、连续 CSV 选不同列、固定 incident log 分析不同已登记参数。它不能仅依靠 `CanonicalTaskSpec` 泛化到：任意网页抓取、任意代码库 bug 修复、迭代写应用、训练模型、安装包、自由外部 API 调用或不可预先验证的开放式报告。

原因不是“LLM 完全没有作用”，而是当前系统有意把模型作用放在受控的检索语义、候选选择和摘要上；而数据读取、计算、文件写入和验收交给预置 Python 和合同。开放泛化首先需要新增 adapter、权限/依赖模型、工具目录、动态任务图和可接受的质量判据。

**本章结论：** 核心 CodeAct 是受控执行器，而非自由代码 Agent。它的泛化主要是“同一预置动作换参数”，不是“任何需求都由模型写程序解决”。

## 8. State、Memory、Replay：只说明它们怎样影响角色关系

### 8.1 StateRef 和 ArtifactRef 的职责不同

| 引用 | 指向什么 | 产生/使用位置 | 与 LLM 的关系 |
| --- | --- | --- | --- |
| `SemanticStateRef` / state ref | embedding 等非文本 bytes，带 storage kind、hash 等 | retrieval 后 publish 到 layered state store | 不直接塞向量给 LLM；用于检索、控制请求/审计 |
| `ExecutionArtifactRef` | workspace 内的结果文件，带 `relpath/blob_hash/verification_state/manifest_hash` | CodeAct/输出 materialization 后，Driver 注册/结算 | LLM 最多看到 runtime 摘出的 artifact slice |
| `MemoryRef` | 一条可检索记忆的元数据和来源关联 | Summarizer/commit 路径生成，MemoryIndexStore 存储 | 只把少量 summary/score/类别转成 slice |

`ExecutionArtifactRef` 的结构在 `v2/refs/models.py:105-134`；state storage policy 在 `v2/state/store.py:25-261`。二者不能合并为一个含混的“状态 ID”。

### 8.2 embedding 和 memory 没有让角色获得额外隐藏上下文

Retriever pipeline 编码 query embedding，并可能将其发布为 `EMBEDDING_STATE`。它主要驱动 semantic retrieval 和 memory similarity；模型看到的是检索后的段落/表格文本，不是 embedding 数值。MemoryIndexStore 持久化 embedding 与 commit，查询时使用 FAISS（可用时）或余弦相似度；candidate 未通过质量门时在查询中被限制为 assist，见 `v2/memory/store.py:27-229`。

当前正常路径最多将少量 memory summary 加入 Retriever、Executor、Summarizer slice。Planner 主路径没有 evidence/memory slice。因而 memory 是 runtime 管理的历史提示或程序复用输入，不是每个 Agent 无条件可读的共同记忆。

### 8.3 replay 的控制权在 gate，不在 LLM

`ReplayAdmissibilityGate.decide()` 依据：当前 compiler 结果、policy、历史 verified output、合同、输入 artifact hashes、runtime signature、输出合同和 exact key，决定 `DISALLOWED/ASSIST/VALIDATED_REPLAY/EXACT_REPLAY`，见 `v2/runtime/replay.py:82-167`。

```text
LLM 说“我记得这件事”        -> 不触发 replay
Memory 相似度命中             -> 至多成为 assist 候选
合同/输入/hash/运行环境兼容     -> 程序才可能允许 validated/exact replay
```

这保护复现性，但也意味着 replay 不能代替任务理解或开放式学习。

**本章结论：** State、memory 和 replay 是控制器管理的间接状态；它们减少重复和支持审计，但不会把 Agent 关系改造成共享隐藏状态或自由黑板系统。

## 9. 失败、重试、回退：候选在何处被拒绝

| 失败点 | 典型原因 | 当前处理者 | 当前结果 |
| --- | --- | --- | --- |
| Compiler | family/intent/output/tool 不登记，或 strict 没有 spec | `TaskCompiler` | `REJECTED`；不启动角色链 |
| Planner JSON/语义 | 非 JSON、未登记 evidence/output、包含 DAG/code/tool 等禁止内容 | RolePathRunner + semantic resolver | JSON 格式最多重试三次；语义转 fallback/hybrid |
| Retriever/Executor JSON | 非 JSON 或选择 `tc` 外的候选 | RolePathRunner | 格式/选择重试；严格面耗尽后 `RoleSelectionError` |
| CodeAct request/plan | 输出路径不在 `tmp/`、route/tool/action 缺失 | CodeActRunner 固定脚本 | 抛出错误；不形成有效候选产物 |
| sandbox | bwrap 缺失/失败、超时、子进程错误 | CodeActSandboxRunner | 记录 backend/fallback reason；可能退到 resource 或失败 |
| candidate output | 缺 required output、文件不存在、脚本未写 result envelope | CodeActRunner + validator | 不形成可验证 artifact |
| 最终质量 | expected facts、quality checks、manifest/输入检查不通过 | validator + `RuntimeCommitGate` | artifact candidate/invalidated，memory/replay 不获完全授权 |
| executor lifecycle | ACK/heartbeat 超时、trap/cancel | Supervisor + Driver | 状态转 trapped/cancelled，执行 fallback/replan 记录 |

`_complete_json_role()` 的 JSON retry 在 `v2/runtime/role_path.py:1054-1108`；selection retry 在 `630-642`；Supervisor 生命周期在 `v2/runtime/supervisor.py:45-205`；CodeAct 的 result-envelope/输出存在检查在 `v2/runtime/codeact.py:515-610`。

“fallback”也必须分清：Planner fallback 是检索语义的程序回退；selection retry 是要求模型重选可见项；sandbox fallback 是 bwrap 到 resource；replay fallback 是复用等级降级。这些都不是模型获得更大权限后自行尝试的循环。

**本章结论：** 输出格式、候选合法性、执行结果和生命周期分别有不同的拒绝点。当前的错误恢复以程序预定义的重试/降级为主，而非 Agent 自主重规划。

## 10. 对三种协作架构的事实比较

| 维度 | 当前：中心控制 + 固定角色链 | Planner 主从 | 平等协作/黑板 |
| --- | --- | --- | --- |
| 谁分解任务 | 任务清单/Compiler 与固定 Python | Planner 动态产生子任务 | 各角色发布和修正假设 |
| 当前代码是否已实现 | 是 | 否 | 否 |
| Planner 所需新能力 | 无额外 | task graph、依赖、权限、子任务合同、验收、预算 | 还需消息主题、订阅、冲突解决、版本与共识 |
| 结果可复现性 | 高，任务/候选/验证闭集 | 较低，依赖模型分解稳定性 | 更低，消息时序和冲突策略也影响结果 |
| 定位错误 | 较直接，按阶段/manifest/hash | 需先判断分解是否错 | 需判断谁的结论胜出、何时覆盖 |
| 适用场景 | 已知离线数据、可比较实验、确定处理链 | 真正异构且需要动态子任务的复杂工作 | 多观点审查、探索、协商性研究 |
| 当前改造成本 | 已实现 | 高 | 很高 |

当前 Planner 没有读取完整证据、没有修改 workflow 的 API、Prompt 又显式禁止 DAG/route/tool/code，因此它不具备成为“主 Agent + 调度者”的必要信息和权限。把它提升为主从调度器不只是改一段 Prompt，还需要：可执行 task graph schema、每个子任务的输入/输出合同、资源与数据权限、候选工具发现、失败重试/终止、冲突解决、子任务产物验收和全局预算。当前代码中不存在这套闭环。

对于现阶段主要目标（可比较的结构化交接、非文本状态、memory/replay），保持固定主链是合理约束；若目标改成开放式代码维护、复杂研究或多源诊断，首先应针对具体任务族建立新合同与 executor，而不是仅让 Planner 自由发指令。

**本章结论：** 当前四角色协作满足“有不同角色、结构化中介、可观察的多步骤处理”，但不等于动态委派或平等协商。是否需要更自治的架构，取决于目标任务是否真的需要动态分解，而不是角色数量。

## 11. 测试、探针与不能据此宣称的能力

| 代码/测试 | 它能证明什么 | 不能证明什么 |
| --- | --- | --- |
| `tests/v2/test_runtime_and_benchmark.py` | strict compiler、注册样例、runtime/benchmark 的若干合同路径 | 任意自然语言或任意文档可处理 |
| `tests/v2/test_role_contract_audit.py` | 四角色图和 telemetry 约定可审计 | 四个 Agent 自主协商或真实动态派工 |
| `tests/v2/test_subprocess_executor.py` | UDS + Protobuf executor request/result round trip | 所有角色均分布式远程执行 |
| `tests/v2/test_bounded_llm_codeact_demo.py` | 诊断 demo 的 AST policy、修复、fallback | 主 runtime 已运行自由 LLM 代码 |
| `scripts/v2_diagnostics/` | 审计/探针可生成独立诊断材料 | 每个诊断脚本是 benchmark 主路径 |

同样，`role_contract.py` 是角色合同与审计的实现；它的文字可较宽泛，但对“真实 Prompt 里哪些字段可见、主路径到底调用了什么”必须以 `smoke.py`、`role_path.py`、`codeact.py` 为准。

**本章结论：** 测试证明的是被测试的合同与探针行为。它们不能自动扩大到通用 Agent、自主协商、KV 直传或自由 CodeAct 的主路径结论。

## 12. 阅读路线与最终清单

### 12.1 新成员最短源码路线

1. 先读配套主线文档中的一个任务，再打开 `v2/benchmark/samples/continuous_task_families/long_doc_metric_replay/manifest.json`。
2. 看 `v2/runtime/compiler.py:145-294`，理解任务为什么会被接受或拒绝。
3. 看 `v2/runtime/smoke.py:1830-2087`，确认 Planner、检索、workspace 的实际顺序。
4. 看 `v2/runtime/role_path.py:998-1108、1279-1719`，确认四个 Prompt 和 JSON 处理。
5. 看 `v2/retrieval/pipeline.py:1019-1120` 与 `v2/route_tool_catalog.py:190-362`，确认数据 adapter 和候选表。
6. 看 `v2/runtime/codeact.py:428-645、774-930` 与 `codeact_data_tasks.py`，确认执行到底是模板还是模型代码。
7. 最后看 `v2/runtime/smoke.py:2654-2824`、`driver.py`、`supervisor.py`、`session.py`，理解验证、Ref、控制帧和提交。

### 12.2 事实结论

- `run_smoke()` 固定调用 Planner、程序检索、Retriever、Executor、CodeAct、Summarizer；Planner 不分发其他角色。
- 每个 LLM 的身份、输入范围和 JSON 输出都由 runtime 在每次 Prompt 中显式构造；没有共享聊天历史。
- Retriever/Executor 的模型选择被限制在程序构造的 `tc` 候选闭集；其输出必须再匹配回候选表。
- 核心 CodeAct 运行的是固定模板脚本和预写数据任务函数，不执行 LLM 自由生成的 Python。
- embedding/state、memory、artifact 都通过 runtime 管理的文件/Ref/摘要间接影响角色，不是隐藏状态在 Agent 间直接传递。
- UDS + Protobuf 是 typed control/transport 实现，不是四个 LLM 的点对点协商协议。

### 12.3 架构判断

- 当前架构更准确地说是**中心化、合同约束的多角色协作 runtime**，不是平等自治 Agent 社会。
- 对可重复 benchmark 和低开销结构化交接，固定链条是合理的；对开放式任务泛化，它同时是主要限制。
- 最大的泛化阻塞点取决于变化类型：新任务是 Compiler/合同，新数据是 adapter/证据 schema，新工具/计算是 Executor/CodeAct，新自主协作是 Planner+Driver 的动态调度能力。

**最终结论：** StateBus v2 的专业价值不在于声称“模型无边界地协作”，而在于把协作中的控制、可见性、结构化状态、工件和记忆复用做成可检查的合同。它已经能在登记任务族内让四个角色各做有限但可审计的工作；它还不是面向任意任务的通用多 Agent 或自由 CodeAct 平台。
