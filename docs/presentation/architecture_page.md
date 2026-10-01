# 第三页架构图：任务调度、对象交接与跨任务复用

本稿确定项目介绍第三页的架构图设计。前两页见 [introduction.md](introduction.md)：第一页提出多 Agent 协作中的重复传递、状态转换和历史复用问题；第二页说明 StateBus 的设计选择。本页把这些选择放到同一个系统中，说明谁负责推进任务、角色使用什么输入、结果怎样进入下一步和后续任务。

图按**控制层、对象层、执行层、模型层、记忆层**组织。五层用于划分职责；实际布局按任务阅读顺序安排，不代表五个独立进程，也不要求请求逐层穿过。本文从任务与对象的关系重新设计，不以现有 `statebus-architecture.svg` 为布局底稿。

## 1. 这页的中心与标题

建议页面标题：

> **StateBus 系统架构**

标题下的一行说明：

> Runtime 安排任务步骤，Agent 按引用取得输入，执行结果交给后续角色，可复用的方法进入 Memory。

这页首先要让评委看懂一次任务怎样完成。进一步看时，应当能回答三个问题：

1. Planner 提出计划后，谁把它变成实际调用？
2. 证据、数值状态和执行文件放在哪里，下一步怎样使用？
3. 模型计算与历史记忆在任务的哪些位置提供帮助？

图的主要特点应当来自这些关系。Runtime 内有具体的计划处理、调度和输入组织；角色下方有实际交付的对象；模型服务和 Memory 有明确的接入位置。增加模块时，必须同时说明它连接谁、传入或传出什么。

## 2. 五层怎样命名，怎样分工

图上保留简短的层名，并在旁边配一句职责说明。

| 层名 | 图上的职责说明 | 应当看得见的内容 |
| --- | --- | --- |
| 控制层 | 批准计划、安排步骤、组织输入 | 任务编译、能力目录、计划批准、步骤调度、角色投影、结果检查与衔接 |
| 对象层 | 保存证据、数值状态和执行产物 | `EvidencePack`、`StateRef`、`ArtifactRef`、来源定位，以及对象载体 |
| 执行层 | 规划、检索、执行、总结 | 四个角色；Executor 内的 DSL 与受限 CodeAct；状态消费组件的位置 |
| 模型层 | 提供推理、向量编码和上下文计算复用 | Embedding 编码器、角色请求适配、vLLM、显式 KV、APC |
| 记忆层 | 保存历史记录，供后续任务检索和使用 | Memory Store、检索、适用性判断、方法复用和结果写回 |

这里有两处需要在讲述前统一理解。

**对象层与模型层按“保存什么”和“怎样计算”区分。** Embedding 编码器属于模型层，生成的向量矩阵属于对象层，下游消费进程读取矩阵并选择证据。Logit 同样要区分概率的生成、保存和消费。KV 的实际内容由 vLLM Worker 管理，留在模型层，只通过 handle 与调用方关联。

**对象层与记忆层按使用时间和检索方式区分。** 对象层承接当前步骤需要的数据与产物；记忆层为后续任务保存摘要、来源、处理方法及产物引用。Memory 不需要复制一套全部执行文件，当前持久记录中的 Artifact 引用仍指向 workspace 中的实际文件。

## 3. 布局：任务居中，控制在上，对象在下

采用“左侧主体 + 右侧记忆栏”的布局。主体约占四分之三宽度，记忆栏约占四分之一。主体从上到下依次放控制层、执行层、对象层和模型层，右侧记忆层连接前后两次任务。

这样安排有明确的阅读理由：评委先看到中间的四个角色，向上能找到调度者，向下能找到它们交付的对象，再看到模型计算的接入点。记忆栏单独占一侧，表示它连接前后任务。

### 整体排布草案

下面只固定区域和对齐关系。具体连接线按第 5 节绘制，不能把所有相邻框都连起来。

```text
StateBus 系统架构
Runtime 安排任务步骤，Agent 按引用取得输入，结果继续交给后续角色。

                  当前任务                                  后续任务

┌─ 控制层：StateBus Runtime ────────────────────┐  ┌─ 记忆层 ─────────┐
│ 任务编译     能力目录与计划批准                │  │ Memory Store     │
│ 步骤调度     角色输入投影     结果检查与衔接    │  │ 摘要 / 来源      │
│ 请求：动作、参数、Ref    返回：状态、结果引用  │  │ recipe / 产物引用│
└──────────────────────────────────────────────┘  │                  │
                     请求与结果                   │ 关键词 / 标签    │
┌─ 执行层 ─────────────────────────────────────┐  │ 向量检索         │
│ ① Planner   ② Retriever  ③ Executor  ④ Summarizer│ │       ↓          │
│ 提出计划     整理证据      执行计算     组织结论│  │ 判断本轮是否适用 │
│                           DSL / CodeAct       │  │       ↓          │
└──────────────────────────────────────────────┘  │ 参考做法         │
                     读取与交付                   │ 或在新数据上重算 │
┌─ 对象层 ─────────────────────────────────────┐  │                  │
│ 证据 EvidencePack   执行产物 ArtifactRef      │  │ 写入本轮可保留的 │
│ 数值状态 StateRef   来源 locator / manifest   │  │ 结果、来源和方法 │
│ Ref 解析与对象访问                            │  │                  │
│ shared memory / mmap、CAS / workspace        │  │ SQLite + JSON    │
└──────────────────────────────────────────────┘  └──────────────────┘

┌─ 模型层 ─────────────────────────────────────────────────────────┐
│ Embedding 编码器   角色请求适配 → vLLM 推理与候选概率             │
│                    公共前缀适配 → APC 缓存复用                   │
│                    parent / suffix → 显式 KV continuation       │
│                    APC 与显式 KV 按运行模式选择                 │
└─────────────────────────────────────────────────────────────────┘

运行记录与评测：消息次数与字节 / 状态消费 / 模型请求 / 任务耗时 / 记忆使用
运行环境：openEuler / Linux 应用运行时；宿主机 vLLM 模型服务
```

正式图中，四个角色按列对齐，对象尽量放在生产者下方。`PlanProposal` 放在 Planner 与计划批准之间；`ClaimSet` 放在 Summarizer 的结果出口。它们不用再挤进对象存储区成为两个大框。

模型层横向展开，是为了容纳“编码器、请求适配、引擎”之间的关系。它与上方区域的连接集中从少数标明用途的接口进入，避免从每个角色各画一条长线到底部。

## 4. 各层具体放什么

### 4.1 控制层：让 Runtime 的工作可见

控制层标题写 `StateBus Runtime`。内部保留以下六项，按准备任务、执行任务两行安排：

| 位置 | 页面文字 | 具体含义 |
| --- | --- | --- |
| 上行左侧 | 任务编译 | 将任务目标、数据范围和输出要求整理成 `CanonicalTaskSpec` |
| 上行中间 | 能力目录 | 记录可调用能力、所属角色及输入输出要求，供规划和计划批准使用 |
| 上行右侧 | 计划批准 | 接收 `PlanProposal`，核对能力、依赖和输入输出约定，形成 `ApprovedPlan` |
| 下行左侧 | 步骤调度 | 根据已批准计划和完成状态选择下一步，创建本次执行 attempt |
| 下行中间 | 角色输入投影 | 按本步要求准备证据、数据行、产物和可用记忆，并保留来源关系 |
| 下行右侧 | 结果检查与衔接 | 接收执行结果，检查输出，向后续步骤提供可用对象 |

下行应有一条很短的回线：`结果检查 → 下一步调度`。它表明 Runtime 持续参与多步任务，不会在发出第一条请求后退出。

控制层与角色之间只展示一组交互说明：

```text
下发：role / operation / parameters / input refs / output contract
返回：执行状态 / result refs
```

这里不展开所有事件、授权字段和失败分支。能力目录必须保留，因为它解释 Planner 的方案怎样与实际可执行能力对应。投影也必须保留，因为它解释对象引用怎样变成角色能使用的输入。

`PlanProposal → ApprovedPlan` 是图中一条重要关系：提案来自 Planner，批准发生在 Runtime。不要把 Runtime 画成先批准计划、之后才调用 Planner。

### 4.2 执行层：四种角色和共同交付方式

角色卡片使用中文动作加英文名称，避免只有缩写：

| 卡片 | 卡片内文字 | 输出标在何处 |
| --- | --- | --- |
| Planner | 提出步骤与能力需求 | 向上返回 `PlanProposal`，接入 Runtime 计划批准 |
| Retriever | 查找资料，整理证据与来源 | 向下交付 `EvidencePack`；启用语义状态时发布对应向量状态 |
| Executor | 使用本步输入完成计算 | 向下交付 `ArtifactRef`，经结果检查后供后续步骤使用 |
| Summarizer | 根据结果与来源组织结论 | 向右输出 `ClaimSet + 产物`，形成任务结果 |

在四个卡片上方放编号和细线，说明典型任务的阅读顺序；线旁统一写“步骤由 Runtime 调度”。这条顺序线表示职责衔接，实际请求从上方 Runtime 发出。

Executor 内部画两条短支路即可：

```text
已定义的变换 → DSL ──────────┐
需要编写程序 → 受限 CodeAct ─┴→ Artifact
```

CodeAct 的启用由计划与能力配置决定。图上表现两种执行方式的共同出口；具体的选择、修复和执行限制留给执行亮点页。

状态消费组件放成角色下沿的小标签：Retriever 与 Executor 之间写“向量选择 → 取回原文”，Executor 附近写“概率判断 → 继续 / 补查”。它们对应实际的消费与决策路径，不额外编号成第五、第六个 Agent。

### 4.3 对象层：先画内容，再标载体

对象层不能只有 `shared memory / mmap / workspace`。这些是保存方式，评委需要先知道里面是什么。

对象主体分三组：

| 组 | 图上的对象与说明 | 主要关系 |
| --- | --- | --- |
| 证据 | `EvidencePack`：片段、表格信息、来源定位 | Retriever 生成，Runtime 组织为后续角色输入 |
| 数值状态 | `SemanticStateRef / LogitStateRef`：向量矩阵、候选概率 | 发布后由消费组件读取，返回选择或决策结果 |
| 执行产物 | `ArtifactRef`：计算表、文件、程序结果 | Executor 生成，通过检查后交给 Summarizer 或后续执行步骤 |

三组下面放一条“Ref 解析与对象访问”横带。载体再放到横带下方：

```text
shared memory：短期数值状态
mmap / CAS：证据、manifest 等可回放对象
workspace：本次执行的输入和产物文件
```

这些是当前使用的载体分工，同一类型的状态也可以按配置使用其他受支持载体。图上不为每种 Ref 固定唯一的存储方式。

来源关系只需标出 `locator / manifest`，并保留“证据 → 执行结果 → 结论”的关联。具体表格行号、hash 和 manifest 字段由后续页面展开。

对象层接回控制层的投影入口，角色使用投影后的输入或按约定读取状态对象。这样可以讲清楚：引用用于找到对象，投影负责组织本步实际使用的内容；下游模型仍会接收必要的文本与数据。

### 4.4 模型层：区分状态生成、状态使用和缓存管理

这一层采用三个相邻区域：`Embedding 编码器`、`StateBus 请求适配`、`vLLM 模型服务`。Embedding 编码器与 vLLM 分开画，避免把 CPU embedding 路径画成 vLLM 的内部功能。

四项专项在总图中各留一条用途说明：

| 项目 | 图上短标签 | 应连接的位置 |
| --- | --- | --- |
| Embedding | 查询与候选编码 | Retriever 准备候选后调用编码器；矩阵发布到对象层，消费者选择后取回原文 |
| Logit | 候选概率参与执行判断 | vLLM 返回 choice token 概率；形成 `LogitStateRef` 后，由决策组件向 Runtime 返回动作 |
| 显式 KV | 后续角色加载 parent KV | StateBus 调用适配连接同一 vLLM Worker 内的 capture、registry 与 load |
| APC | 对齐公共前缀，复用引擎缓存 | StateBus 请求适配连接 vLLM APC；支持的连续任务路径读取命中反馈并调整待执行顺序 |

**Embedding 和 Logit 的数值对象仍画在对象层。** 模型层负责展示它们从哪里来，消费标签负责展示它们用到哪里。两个区域之间用同名标签对应，避免把四种机制全部塞进模型服务框。

**显式 KV 的内容画在 vLLM Worker 内。** 模型服务内部可以放一个小框：

```text
显式 KV 模式
capture parent → Worker-local registry → load parent
                    EngineLocalKVHandle
```

Executor 和 Summarizer 的模型请求由适配组件连接这条路径。这里传递的是同一 Worker 能解析的 handle，图上不连向 shared memory 存储区。

**APC 单独画一条模式分支。** StateBus 一侧写“公共前缀对齐”，vLLM 一侧写“APC blocks”。如果保留反馈小回线，文字写“命中反馈 → 待执行队列调整（连续任务路径）”。当前反馈重排由特定连续任务 runner 接入，不应画成所有 Runtime 请求都会自动重排。

APC 与显式 KV 之间标注“按运行模式选择”。当前显式 KV Worker 要求关闭 APC；两者都出现在系统总图中，表示系统具备两条计算复用路径。

这页显示接入关系即可。前缀排列、KV 页块、Logit 公式和向量 top-k 都留给专项页。

### 4.5 记忆层：画出写入和再次使用

右侧记忆栏分为三个小区，按“保存内容、如何找到、如何使用”排列：

```text
Memory Store
摘要、来源、处理方法、Artifact 引用
              ↓
关键词 / 标签 / 向量检索
              ↓
判断是否适用于本轮任务
              ↓
参考历史做法 / 在当前输入上执行历史 recipe
```

栏外只连两条主线：

- **写入线**：从本轮结果提交处进入 Memory，标“保存结果、来源和方法”。
- **读取线**：从 Memory 返回 Runtime 的输入准备处，标“后续任务检索后使用”。

读取线到达投影与调度处后，再由 Runtime 为具体步骤组织记忆输入。当前最值得说明的消费者是 Executor：拿历史 recipe，在本轮输入上重新计算并生成新的 Artifact。

Memory 检索可在当前 Retriever 路径中由查询、标签和 query embedding 提供线索。总图将这些线索归入“任务准备时查询”，不画成 Planner 在所有任务开始前固定读取全部记忆。

记忆栏底部小字写：

> SQLite 元数据与全文索引 + JSON 记忆和向量记录；Artifact 文件保存在 workspace。

三种复用等级、RRF 排序公式和拒绝条件留给 Memory 页。总图只表达“找到记录以后还要判断本轮怎么用”。

## 5. 任务路径和连线怎样画

### 主路径必须能单独读通

讲解时，按照以下顺序指图：

```text
任务输入 → 编译任务 → Planner 提出计划 → Runtime 批准计划
                                                   ↓
Retriever 形成证据 → Runtime 准备执行输入 → Executor 产出 Artifact
                                                   ↓
                         结果检查 → Summarizer → 结论与产物
```

这是用于说明系统的典型任务路径。实际批准计划可以包含多个检索或执行步骤，图中的一个角色框表示该类职责，不限制它只能调用一次。

### 正式绘图保留的连接

| 连接 | 线旁文字 | 绘制方式 |
| --- | --- | --- |
| 任务入口 → 任务编译 | 目标、数据范围、输出要求 | 主线，短实线 |
| Runtime ↔ Planner | 任务与能力 / `PlanProposal` | 单独画清，计划回到批准节点 |
| 计划批准 → 调度 | `ApprovedPlan` | 控制层内部短线 |
| 调度 ↔ 角色 | 请求 / 执行状态与结果引用 | 使用共用控制横线，再向各角色短接 |
| Retriever、Executor → 对象层 | `EvidencePack` / `ArtifactRef` | 对齐对应对象后垂直短接 |
| 对象层 → 输入投影 → 当前角色 | Ref 解析 / 本步输入 | 画一条代表性回路，标“按步骤发生” |
| Artifact → 结果检查 → Summarizer | 可用结果及来源 | 主线，保留结果检查的位置 |
| Summarizer → 任务出口 | `ClaimSet + 产物` | 主线，放在最右端 |
| 结果提交 → Memory → 后续任务输入 | 保存 / 检索后使用 | 沿右侧边缘回接 |
| 模型适配 ↔ 模型服务 | 推理请求 / 生成结果与概率 | 普通实线，与专项虚线区分 |
| State 消费、KV、APC 接入 | 标具体用途 | 可选路径用细虚线，长连线可改为同名接口标签 |

主任务使用粗实线，控制交互和对象访问使用细实线，可选专项使用虚线。角色的阅读顺序用编号和浅色引导线表示，不能与实际消息线路使用同样的样式。

颜色只区分少量关系：深灰用于任务和控制，绿色用于对象读写，另一种低饱和颜色用于跨任务记忆。可选路径主要靠虚线识别，不给每个模块分配一种颜色。

## 6. UDS、IPC 和评测放在哪里

### 通信实现贴着对应关系标注

在控制层与执行层之间的小字写：

> 进程内 typed object；跨进程 Worker 使用 Protobuf over UDS。

在对象层载体旁边写：

> 数值状态通过 shared memory / mmap 读取，执行文件从 workspace 读取。

IPC 可以作为两处实现注释的统称，写“进程间通信与状态访问”。UDS 是控制消息通道，shared memory 是状态载体，不需要再单独加一个大号 IPC 组件。

这两处足以表明系统有真实的跨进程实现，同时保留当前混合调用方式。四个角色不需要各画成一个操作系统进程。

### 运行记录与评测用底部窄条

赛题要求架构包含评测模块。图底部增加一条公共支撑区，标题为“运行记录与评测”，不再增加第六层。

窄条内容：

```text
Telemetry / Ledger → 同任务对照与结果汇总
消息次数与字节 · 文本开销 · 状态消费 · 模型请求 · 任务耗时 · 记忆使用
```

从 Runtime 运行记录出口引一条细线即可，不从所有节点各拉一条采集线。纯文本与结构化模式的具体对照、任务数量和结果曲线放在测试部分。

环境标注写“openEuler / Linux 应用运行时；宿主机 vLLM”。它用于说明应用运行与模型服务的位置，不需要把本页变成容器部署拓扑。

## 7. 一页内的信息取舍

这张图可以比简单角色流程图丰富，但主次必须明确。

| 视觉级别 | 保留什么 | 阅读目的 |
| --- | --- | --- |
| 第一眼 | Runtime、四个角色、任务入口与结果出口 | 看懂谁安排任务，谁完成工作 |
| 顺着主线阅读 | `PlanProposal`、`ApprovedPlan`、`EvidencePack`、`ArtifactRef`、`ClaimSet`，以及投影与结果衔接 | 看懂每一步交付什么，下一步拿什么继续 |
| 进一步查看 | State 对象、模型适配、KV/APC 模式、Memory 回接、UDS 与载体 | 找到各项特色机制的系统位置 |
| 讲解补充 | 原始类名、字段细节、阈值、生命周期与实验数字 | 用后续页面或答问解释 |

图中文字以中文动作为主，关键对象名为辅。模块主标签尽量一行，说明不超过两行。控制层的六项不全部再加英文类名；源码符号放在文档依据中供查阅。

空间不足时，先缩短物理载体说明、合并模型模式的内部细节、用接口标签代替长连线。应优先保留计划回到 Runtime、证据经过投影、产物交给总结、Memory 回到后续任务这四处关系。

## 8. 与前后页面怎样衔接

第二页已经说明了协议、对象、执行和记忆的设计选择。进入架构图时可以说：

> 下面把这些设计放进一次任务里。先看中间四个角色，再看上面的 Runtime 怎样安排步骤，下面的对象怎样承接每一步结果。

这页只负责建立位置关系。后续页面各自展开一个具体问题：

| 后续内容 | 在本图中的入口 | 后续才展开的细节 |
| --- | --- | --- |
| 结构化协议 | 能力目录、控制请求与结果回执 | 能力发现、字段、交互规则和输入投影 |
| Embedding / Logit | 对象层的数值状态与消费标签 | 如何生成、传递、消费并影响后续处理 |
| 显式 KV / APC | 请求适配与 vLLM 内的两种模式 | KV 加载、前缀对齐与命中反馈 |
| DSL / CodeAct | Executor 内两条执行路径 | 如何选择路径，如何产出同类 Artifact |
| Memory | 右侧保存、检索与回接 | 排序、适用性判断和实际复用 |
| 三个技术问题 | 投影、调度、记忆使用 | 角色输入如何整理、任务如何继续、历史记录何时能复用 |
| 实验 | 底部运行记录与评测 | 同条件对照、逐任务结果与总体收益 |

接亮点总览时可以说：

> 系统的位置关系已经明确。下面从交接开始，看请求怎样说明任务、中间状态怎样被使用，以及这次形成的方法怎样留给下一次任务。

## 9. 建议讲解稿

> 中间是规划、检索、执行和总结四类角色。任务先交给 Runtime 整理，Planner 根据任务和可用能力提出计划，Runtime 再把计划变成可以调度的步骤。每一步开始前，它准备当前角色需要的输入；这一步完成后，它检查输出并连接下一步。
>
> 下面是这些角色交付的对象。Retriever 留下带来源的证据，数值状态单独保存，Executor 通过 DSL 或受限 Python 生成产物。控制请求带着动作、参数和引用，具体证据、矩阵和文件在需要时读取。Summarizer 使用执行结果和来源形成结论。
>
> 模型层提供向量编码和角色推理，也接入两种长上下文复用方式：APC 使用对齐的公共前缀，显式 KV 在同一 Worker 中加载已经计算的 parent 状态。它们按任务和运行模式接入。
>
> 右边的 Memory 把本次形成的结果、来源和方法保存下来。后续任务检索到适用记录后，可以参考历史做法，也可以在新数据上重新执行已有方法。底部的运行记录为通信、时延和复用效果的对照实验提供数据。

讲完后，评委应当能够复述：**Runtime 负责步骤，角色负责处理，对象承接交接，模型适配减少重复计算，Memory 把方法留给后续任务。**

## 10. 绘图前的事实核对与依据

五层是答辩图的职责组织方式，不改变源码模块归属或进程部署。制作正式图时，以下关系需要保持准确：

- Planner 先产生提案，Runtime 再批准和调度。
- Ref 关联对象；送入模型的必要文本和数据仍由角色输入路径准备。
- Semantic / Logit 状态有独立消费路径；KV 由同一 vLLM Worker 管理；APC 缓存由引擎管理。
- 当前显式 KV 模式要求关闭 APC，两者在总图中作为可选择路径出现。
- APC 反馈重排接入特定连续任务 runner，主图用小字注明该位置。
- Memory 保存记录和引用；历史 recipe 在当前输入上执行，生成本轮结果。
- 角色是职责划分；进程内调用和跨进程 Worker 路径同时存在。

| 本稿判断 | 实现或说明入口 |
| --- | --- |
| 任务编译、能力目录与计划批准 | [compiler.py](../../src/statebus/runtime/compiler.py)、[plan_policy.py](../../src/statebus/runtime/plan_policy.py) |
| 步骤调度、结果衔接与角色调用 | [adaptive_runtime.py](../../src/statebus/runtime/adaptive_runtime.py)、[adaptive_dispatcher.py](../../src/statebus/runtime/adaptive_dispatcher.py)、[driver.py](../../src/statebus/runtime/driver.py) |
| 证据转为执行输入并保留来源 | [evidence_projection.py](../../src/statebus/runtime/evidence_projection.py) |
| 控制消息与 UDS | [messages.py](../../src/statebus/control/messages.py)、[transport.py](../../src/statebus/control/transport.py) |
| 数值状态与对象载体 | [store.py](../../src/statebus/state/store.py)、[semantic_state.py](../../src/statebus/state/semantic_state.py)、[logit_state.py](../../src/statebus/state/logit_state.py) |
| 公共前缀与角色请求适配 | [prefix_identity.py](../../src/statebus/runtime/prefix_identity.py)、[role_path.py](../../src/statebus/runtime/role_path.py) |
| APC 反馈与待执行任务重排 | [prefix_feedback.py](../../src/statebus/runtime/prefix_feedback.py)、[continuous_runner.py](../../src/statebus/benchmark/continuous_runner.py) |
| Worker 内显式 KV 与运行条件 | [worker_extension.py](../../src/statebus/integrations/vllm_kv/worker_extension.py)、[registry.py](../../src/statebus/integrations/vllm_kv/registry.py) |
| Memory 保存格式、检索和使用 | [memory/store.py](../../src/statebus/memory/store.py)、[memory_reuse.md](memory_reuse.md) |
| 运行记录与实验取数 | [telemetry.py](../../src/statebus/runtime/telemetry.py)、[ledger.py](../../src/statebus/runtime/ledger.py)、[experiments_overview.md](experiments_overview.md) |
| 答辩主线与赛题要求 | [introduction.md](introduction.md)、[highlights_overview.md](highlights_overview.md)、[赛题原文](/home/qcrs/statebus/project/docs/reference/题目.md) |
