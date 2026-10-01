# 答辩亮点：结构化通信协议

这份文档为“项目亮点”中的结构化通信协议准备一页内容。它先固定这一页要证明什么，再说明协议规则、Runtime 投影、Protobuf/UDS 和对象存储各自负责什么，最后给出一页 PPT 的展示安排和讲解稿。

这页不负责讲完整的 Runtime、非文本 State、Memory 或执行机制。它说明一次交接从哪里开始、请求里带什么、Runtime 怎样准备输入、结果怎样返回：

> 能力怎样被选中，请求怎样发出，输入怎样准备，结果怎样交给下一步？

## 1. 这一页的主题

页标题：

> **结构化通信：从能力选择到结果交付**

副标题：

> **Runtime 用一条请求说明操作、输入引用和输出合同。**

这一页的核心句是：

> StateBus 把一次 Agent 交接拆成四步：选择能力、发送请求、准备角色输入、返回结果。

这句话要放在讲述中心。Protobuf、UDS 和 shared memory 说明这套交接怎样落到进程间运行，协议本身要讲的是能力、请求、输入和结果之间的关系。

## 2. 为什么结构化协议是亮点

赛题要求系统能够表达动作、参数、结果和能力，并用这些信息完成 Agent 协作。固定格式的 JSON 只能解决表示问题，字段由谁提供、如何使用、怎样接上下一步仍需要另外定义。

普通的 Agent 交接经常把几件事混在一段说明里：

```text
请根据上面的资料完成计算，并把结果告诉我。
```

接收方需要判断哪些内容是输入、这次要做什么、结果应当满足什么格式，以及结果怎样交给下一步。把这段话改成 JSON，只改变了表示形式；如果字段含义仍写在提示词里，接收方仍然要自行解释和组织输入。

StateBus 把这次交接拆成几个 Runtime 能够处理的部分：

```text
能力目录 → 执行请求 → 运行状态 → 结果引用
```

Planner 提出计划后，Runtime 从计划中取出能力、输入引用和输出要求，形成执行请求并交给相应的 Worker。Worker 返回执行状态和结果引用，Runtime 再把结果交给后续步骤。

这一页要突出的是下面这些内容如何连在一次交接中：

| 协作问题 | StateBus 的回答 |
| --- | --- |
| 谁能做什么 | `CapabilityRegistry` 中的能力描述 |
| 这次要做什么 | `operation`、步骤目标和输入输出合同 |
| 用哪些已有内容 | `StateRef`、`ArtifactRef`、`MemoryRef` 等引用 |
| 接收方实际看到什么 | Runtime 根据角色和步骤生成的输入投影 |
| 结果怎样交给下一步 | `SuccessResult` / `ErrorResult` 和结果引用 |

Runtime 根据这些字段安排步骤、组织角色输入、连接结果，并记录一次执行对应的任务、步骤和尝试。

Protobuf、RPC 和能力注册本身不承担这一页的创新结论。StateBus 的做法是：Runtime 用能力描述生成执行请求，用同一套 Ref 传递 State、Artifact 和 Memory，并用结果回执连接后续步骤。

## 3. 协议到底规定了什么

这一页按三个动作讲协议：先发现能力，再发送请求，最后交付结果。输入投影放在请求和 Worker 之间。

### 3.1 先发现能力

Runtime 先登记能力，并向 Planner 提供能力的公共描述。描述至少包括：

- `capability_id`：能力的稳定名称；
- `owner_role`：由哪个角色负责；
- 接受哪些输入对象类型；
- 产生哪些输出对象类型；
- 输入和输出合同版本；
- 执行方式和可复用属性。

答辩中可以展示当前源码中实际存在的一个能力作为示意：

```text
CapabilityDescriptor
────────────────────────────────
capability_id:          compare_periods_v1
owner_role:             executor
accepts:                execution_artifact / canonical_evidence_pack
produces:               execution_artifact
input_contract:         statebus.metric_series.v1
output_contract:        statebus.comparison.v1
execution_kind:         TRANSFORM_DSL
```

Planner 读取能力表后选择下一步操作，同时知道该能力接受什么输入、会交付什么结果。

这一页展示能力选择所需的字段。风险等级、validator 列表和完整的完成条件属于执行合同和质量检查，放到实现或难点部分。

### 3.2 再按规则发起请求

能力被选中后，Runtime 为具体的任务步骤形成 `ExecRequest`。这里展示有叙事价值的字段即可：

```text
ExecRequest
────────────────────────────────
task / step / attempt
operation:                  compare_periods
artifact_refs:              [<metric-series-ref>]
state_refs / memory_refs:   [按需]
output_contract_version:    statebus.comparison.v1
```

这三个字段分别回答：

```text
做什么       operation
拿什么做     input refs
交付什么     output contract
```

赛题中的“参数”在当前实现中由 `operation`、输入 Ref、输入 manifest、能力合同和少量类型化字段共同表达，例如 `semantic_top_k`、`evidence_budget_bytes` 或 `hydrate_manifest_id`。源码中没有承载任意 JSON 的通用 `parameters` 字段，页面上可以把这些内容概括为“操作及其参数要求”。

请求还带有 `task_id`、`step_id` 和 `attempt_id` 等上下文。这些字段把请求、运行状态和返回结果对应到同一次执行。

### 3.3 按协议返回结果

跨进程 Worker 的控制消息有明确的事件类型。PPT 不需要列出所有消息，只要展示一条简化的交互顺序：

```text
ExecRequest
     ↓
AckReceived
     ↓
RunStart
     ↓
SuccessResult / ErrorResult
```

成功结果可以只保留下面的内容：

```text
SuccessResult
────────────────────────
output_refs: [<comparison-artifact-ref>]
output_contract: statebus.comparison.v1
```

这条顺序让 Runtime 能知道 Worker 是否接收并开始执行，完成后交付了哪些对象，以及下一步骤可以继续消费什么。

`Heartbeat`、`CancelCommand`、`TrapFatal` 和 `GarbageCollectCommand` 属于完整运行生命周期。它们可以在实现文档或技术难点中说明，不要和这一页的主线抢空间。

## 4. 投影：引用之后，角色实际拿到什么

如果这一页只展示：

```text
ExecRequest → Worker → SuccessResult
```

这只能说明一次 RPC。StateBus 还要说明 Runtime 如何把引用的对象组织成当前角色的输入。

建议在 `input_refs` 和 Worker 之间加入一个小的投影框：

```text
<metric-series-ref>
          ↓
Runtime projection
          ↓
Executor input
需要的字段 + 数据行 + 来源定位
```

配一句解释：

> Ref 提供对象 ID 和类型。Runtime 根据当前角色和步骤，从对象中组织出需要的字段、数据和来源定位。

投影只处理当前角色的输入组织：Runtime 从当前任务已有的证据、状态和产物中，按输入合同整理出角色视图。需要模型阅读的证据可以渲染成文本；可以直接处理的表格或状态，则以相应对象形式提供。

因此，协议和投影的关系是：

- 协议规定这次可以交接什么；
- 投影决定这个角色这次实际拿到什么。

这使得发送方、Runtime 和接收方各自承担清楚的工作：发送方给出能力和引用，Runtime 组织输入，接收方执行合同中的操作。

## 5. 一页 PPT 应该展示什么

### 5.1 页面层次

页面视觉重点是一条从能力到结果的横向流程，分成四个区域：

```text
能力规则 → 请求合同 → Runtime 投影 → Worker 结果
```

具体安排如下：

**顶部：核心判断**

```text
一条交接包含：能力、请求、输入投影和结果
```

下面用一行较小的字说明：

```text
Runtime 用一条请求说明操作、输入引用和输出合同。
```

**左侧：能力目录**

展示 `CapabilityDescriptor` 的精简卡片，使用 `compare_periods_v1` 作为实际能力示例。只保留 owner、输入类型、输出类型和合同版本。

**中间：一次执行请求**

展示 `ExecRequest` 卡片，突出 `operation`、`input_refs`、`output_contract_version`，并在角落保留 `task / step / attempt`。

**中下部：输入投影**

从 `input_refs` 引出 `Runtime 输入投影`，再指向 `Executor input`。用“需要的字段 + 数据行 + 来源定位”说明投影结果，页面上同时保留 `projection` 这个实现术语。

**右侧：结果和状态**

展示 `Ack → RunStart → SuccessResult/ErrorResult`，末端放 `output_refs`。这样能力、请求、运行状态和结果都能在一页中闭合。

**底部：实现方式**

用一条窄栏说明实现边界：

```text
跨进程控制：ControlEnvelope / Protobuf over UDS
对象内容：Ref → shared memory / mmap / workspace
```

这条底栏说明协议在 Linux 进程间的落地方式，视觉重点仍放在上面的交接流程。

### 5.2 页面可以使用的完整示意

下面是逻辑草图，版式还可以调整：

```text
┌─────────────────────────────────────────────────────────────────────┐
│ 结构化通信：从能力选择到结果交付                                  │
│ Runtime 用一条请求说明操作、输入引用和输出合同                      │
├──────────────┬────────────────────┬──────────────────┬───────────────┤
│ 能力目录      │ 执行请求            │ Runtime 投影       │ 结果交付       │
│              │                    │                  │               │
│ compare_     │ ExecRequest        │ input Ref         │ Ack            │
│ periods_v1   │ operation           │       ↓          │   ↓           │
│              │ input_refs          │ 角色需要的输入    │ RunStart       │
│ accepts:     │ output_contract     │ 字段/数据/定位    │   ↓           │
│ artifact     │ task/step/attempt   │                  │ SuccessResult  │
│ + evidence   │                    │                  │ output_refs    │
│ produces:    │                    │                  │               │
│ artifact     │                    │                  │               │
├──────────────┴────────────────────┴──────────────────┴───────────────┤
│ ControlEnvelope: Protobuf over UDS    Ref → shared memory/mmap/workspace│
└─────────────────────────────────────────────────────────────────────┘
```

这张图不需要同时放完整的四角色拓扑。介绍页已经解释 Planner、Retriever、Executor 和 Summarizer 的分工；结构化协议页只剖开一次交接，避免内容变成模块清单。

### 5.3 这一页不放什么

本页暂不展开下面内容：

- 完整的 `ControlHeader` 和所有 Protobuf 字段；
- 所有事件类型的列表；
- `heartbeat`、lease、GC、validator 和授权细节；
- Embedding、Logit、KV 的具体数据布局；
- 四个 Agent 都通过 UDS 连接的拓扑图；
- 主实验的 token、时延和消息数字。

这些内容分别属于运行机制、非文本 State、技术难点或测试页面。本页只说明它们怎样接入主线：协议中的引用可以指向这些对象，跨进程 Worker 通过 UDS 收发控制消息。

## 6. UDS、IPC、shared memory 各自应该怎么说

这几项必须区分层次：

| 名称 | 在这页承担的角色 | 说法 |
| --- | --- | --- |
| IPC | 系统层概念 | Runtime 和 Worker 之间存在跨进程协作 |
| UDS | 控制消息通道 | `ControlEnvelope` 通过 `AF_UNIX/SOCK_STREAM` 传递 |
| Protobuf | 控制消息编码 | `oneof` 区分请求、运行状态和结果事件 |
| shared memory / mmap | 状态对象载体 | 某些 StateRef 指向跨进程共享的数值状态 |
| workspace / artifact root | 产物载体 | ArtifactRef 指向执行产生的文件或表格 |

可以用一句话说明这层关系：

> UDS 传控制消息，Ref 指向对象内容。大对象留在 Ref 对应的存储中。

当前系统的主链中既有进程内 typed object，也有 Dispatcher 通过 UDS + Protobuf 调用角色 Worker；语义状态消费也有独立的跨进程路径。答辩时把 UDS 标为“跨进程 Worker 路径”，不要画成所有 Agent 之间的统一连接。

Embedding 写入 shared memory 的过程放到下一页非文本 State 中。本页用 `StateRef → shared memory/mmap` 说明协议能够引用这种状态。

## 7. 建议讲解稿

可以按下面的顺序讲，约一分钟：

> 这一页展示 StateBus 的一次结构化交接。Runtime 先登记能力，Planner 从能力目录中选择下一步操作。比如 `compare_periods_v1` 明确了它由 Executor 执行，接受什么类型的输入，最后产生什么类型的产物。
>
> 选定能力后，Runtime 形成一条 `ExecRequest`，明确这次做什么、使用哪些输入引用，以及结果要满足什么合同。数据不会全部重新塞进控制消息，Runtime 会根据 Executor 的角色和当前步骤，把引用的对象投影成需要的字段、数据和来源定位。
>
> Worker 接收到请求后，按 `Ack`、`RunStart` 和结果消息返回执行状态。成功时交付 `ArtifactRef` 或 `StateRef`，下一步可以继续读取。跨进程路径中，控制请求使用 Protobuf over UDS，大对象由 Ref 指向 shared memory、mmap 或 workspace。
>
> 这里的重点是四个具体动作：能力发现、任务请求、对象交接和结果返回。Protobuf 负责编码控制消息，Runtime 负责把这些动作接起来。

最后停在这句话：

> **StateBus 用能力描述、输入引用和结果合同，连接起一次 Agent 任务。**

## 8. 和前文及后续亮点的关系

介绍中已经说过：StateBus 用明确的指令交接任务，把数据和结果单独保存，通过引用读取。这一页把这句话拆成了可展示的规则：

| 介绍中的说法 | 本页展开 |
| --- | --- |
| 明确的指令 | 能力目录、`operation`、输入输出合同 |
| 数据和结果单独保存 | State、Artifact、Memory 的 Ref |
| 通过引用读取 | Runtime 解析 Ref 并组织角色投影 |
| 后续继续使用 | Worker 返回结果引用，下一步继续消费 |

下一页非文本 State 可以直接从这里接出：

> 如果 `StateRef` 指向 embedding 或 Logit 数值状态，StateBus 怎样生成、传递、接收和使用它？

Memory 和执行部分也不需要重新发明通信逻辑。它们可以继续沿用本页已经建立的对象引用和结果合同：MemoryRef 表示可查询的历史对象，ArtifactRef 表示执行产物，StateRef 表示短生命周期的中间状态。

## 9. 事实边界与证据

这一页说明设计价值，性能数字放在测试部分。主实验给出的是完整配置的整体结果，不能拆成协议单项结果。

- 主实验比较的是完整的 `SB-FULL` 与 `P-TEXT` 配置，整体收益不能全部归因于 Protobuf 或 UDS。
- 主实验的主要角色交接包含进程内 typed object；跨进程 UDS 证据应按 Worker/control/semantic 路径描述。
- 控制消息携带 Ref 和小型类型化字段，较大的状态、证据和产物留在引用指向的载体中。
- `StateRef` 的含义取决于具体状态类型。Embedding、Logit 和 KV 的生成与消费方式要在非文本 State 专项中分别说明。
- 结果消息带有输出 Ref 和执行信息，最终产物还要经过 Runtime 的对象、schema、来源和质量处理；这些支撑机制放在实现和难点部分。

可引用的实现材料：

- [能力描述](../../src/statebus/contracts/adaptive.py)
- [控制协议定义](../../src/statebus/control/statebus_control.proto)
- [控制消息实现](../../src/statebus/control/messages.py)
- [Runtime 调用与 UDS 说明](../implementation/runtime.md#protobuf-与-uds-控制协议)
- [一次任务的角色 Worker 流程](../implementation/README.md#一次任务)
- [State、Ref 与存储](../implementation/state.md)
- [项目介绍叙事](./introduction.md)
