这是一道极具深度且非常贴近当前 Agent 系统底层痛点的**“系统级/基础设施级”赛题。区别于常见的 Prompt Engineering 或简单的 API
编排，本赛题要求选手具备操作系统级思维（IPC、共享内存、进程调度）以及多智能体底层架构设计能力**。

针对在 openEuler 24.03-LTS-SP3 环境下的开发和评测要求，我为您设计了一套名为 “Co-AgentOS” (Collaborative
Agent Operating System) 的原型方案。以下是整体的方案设计、创新点、任务设计及实现路径建议：

一、 核心架构设计与创新点 (对应系统完整性与创新性)

本系统采用 “控制流与数据流分离” 的系统级架构，借鉴现代操作系统的设计理念：

1. 结构化通信协议 (解决：通信开销与解析冗余)

  - 设计理念：抛弃繁重的自然语言或臃肿的 JSON，采用基于 MessagePack 或 Protobuf 的二进制通信协议，并在底层使用 Unix
    Domain Sockets (UDS) 进行本地 Agent 进程间通信。
  - 协议结构：
      - Header: 包含消息 ID、Sender、Receiver、Action Type (如 REQUEST_PLAN,
        EXECUTE_CODE, STORE_MEM)。
      - Capability Registry: Agent 启动时向“调度中心”发送握手包，注册自身能力（如 {"role": "executor",
        "tools": ["python", "bash"]}）。
      - Payload: 参数传递不再使用大段文本，而是传递**“内存指针 (Memory Pointers)”** 或精简的参数键值对。

2. 非文本中间状态传递 (解决：State传递创新 20分)

  - 设计理念：基于 Linux 共享内存 (POSIX shm 或 mmap) 实现 Zero-copy（零拷贝）的状态传递。
  - 具体机制（Semantic Pointers）：
      - 生成：当【检索 Agent】从本地或网络获取海量文档时，不把文本发给其他 Agent，而是利用本地轻量级模型（如
        BGE-m3）将文档分块并提取为 Embeddings 矩阵（NumPy Array），存入共享内存。
      - 传递：检索 Agent 通过 UDS 仅向【总结 Agent】发送一个结构化信号：{ "action": "summarize",
        "shm_ptr": "shm_id_1024", "shape": [100, 768] }。
      - 接收与使用：【总结 Agent】直接读取该内存地址的向量数据，计算其与用户 Query 向量的余弦相似度，仅提取 Top-K
        对应的原始文本段进行大模型生成。
      - 进阶（隐藏状态传递）：如果底层对接本地开源模型（如 Qwen2-7B），可进一步截获推理引擎（如 vLLM）的 KV Cache
        并通过共享内存传递，让下游 Agent 继续推理，完全省去 Prefill 阶段的 Token 开销。

3. 共享记忆复用机制 (解决：记忆复用效果 20分)

  - 设计理念：构建一个基于 SQLite (元数据) + FAISS (向量索引) + 本地文件系统 的全局记忆黑板（Global Blackboard）。
  - 记忆单元 (Memory Unit) 定义：包含 Memory_ID, Source_Agent, Timestamp, Topic, Summary,
    Embedding_Ref, Raw_Data_Path。
  - 复用逻辑：任何 Agent 执行任务前，先将任务目标向量化，在 FAISS 中检索。若命中历史策略或中间结果，则直接跳过该子任务。

4. CodeAct 轻量沙箱执行

  - 引入轻量级容器（Docker 或 基于 openEuler 特性的 iSula / WASM沙箱）。
  - 【执行 Agent】生成 Python 代码后，在沙箱中运行并捕获 stdout/stderr。返回结果同样进行向量化并存入全局记忆。

二、 验证任务设计 (至少2组关联任务)

为了完美展示“结构化通信降低开销”和“记忆复用减少耗时”，我们需要设计存在前后文依赖的复杂数据分析任务。

  - Agent 角色配置 (4个)：
    1.  Planner (规划者)：拆解任务，调度其余 Agent。
    2.  Retriever (检索者)：负责搜索资料，生成向量和共享内存指针。
    3.  Code Executor (执行者)：CodeAct 模式，编写代码处理数据。
    4.  Summarizer (总结者)：汇总输出最终报告。

任务 1 (冷启动阶段)：深度调研与数据分析

  - 用户指令：“分析 2023 年全球新能源汽车销量的季度变化趋势，并给出核心驱动因素。”
  - 执行流程：
    1.  Planner 将任务拆分为“检索销量数据”、“编写代码画趋势图”、“总结驱动因素”。
    2.  Retriever 获取数十篇研报，提取 Embeddings 存入共享内存，并将“研报总结”及“销量数据表格”沉淀到 共享记忆库。
    3.  Code Executor 编写 Python 读取数据并计算，将经验（如“清洗缺失数据的 pandas 脚本”）存入记忆。
    4.  Summarizer 结合上述状态输出报告。
  - 效果：耗时较长，Token 消耗正常。但系统积累了大量的非文本状态和记忆。

任务 2 (关联复用阶段)：基于历史记忆的递进任务

  - 用户指令：“在 2023 年新能源汽车销量趋势的基础上，对比分析 2023 年与 2022 年第四季度的销量差异及原因。”
  - 执行流程：
    1.  Planner 收到指令，触发共享记忆检索，瞬间命中“2023年趋势数据”和“驱动因素摘要”。
    2.  Planner 直接复用记忆（甚至复用了 Code Executor 上次写的清洗代码），仅指令 Retriever
        去补充检索“2022年Q4”的数据。
    3.  通信时，大量上下文无需用纯文本传递，只需传递上一次任务的 Memory_ID。
  - 对比效果：由于跳过了 2023 年数据的检索、向量化和代码编写，单任务耗时大幅下降，大模型 Token 消耗骤减（预期节省 60%+）。

三、 A/B 测试与性能对比方案 (对应实验验证 15分)

系统必须内置两种运行模式的切换开关（--mode pure_text vs --mode structured_mem）。在 openEuler 上运行 10
轮自动化测试，收集并在前端 Dashboard 或报告中展示以下对比图表：

1.  通信开销 (Communication Overhead)：
      - 统计：Prompt Token 消耗量、网络/进程间传输的 Byte 大小。
      - 预期：结构化协议+指针传递将使传输字节下降 2-3 个数量级，Token 消耗降低 50% 以上。
2.  非文本状态传递监控：
      - 统计：共享内存交换次数、传递的 Tensor/Embedding 规模（MB）。证明确实使用了非文本机制。
3.  任务时延 (Task Latency)：
      - 统计：端到端完成任务的总秒数。
      - 预期：任务 2 在共享记忆加持下，耗时相比纯文本模式（每次重新塞入全部上下文）显著降低。
4.  共享记忆命中率 (Memory Hit Rate)：
      - 统计：检索命中的次数 / 总任务规划节点数。

四、 如何在 openEuler 24.03 上实现与技术栈建议

1.  底层通信与状态共享 (C/C++ 或 Rust 与 Python 混合)：
      - 利用 openEuler 的高效 IPC 机制。推荐使用 Python 的 multiprocessing.shared_memory
        模块，或者用 C++ 编写底层 Daemon，通过 Pybind11 暴露给 Agent 逻辑层。
      - 结构化协议使用 msgpack-python。
2.  多智能体运行时 (Multi-Agent Runtime)：
      - 可以基于异步非阻塞框架 asyncio 或 Ray (如果支持单机多核更好) 来管理 Agent 进程。
3.  共享记忆库：
      - 向量库：为了轻量化且不依赖复杂云服务，推荐直接使用 ChromaDB 或 FAISS 跑在本地。
      - 元数据：SQLite。
4.  大模型接入：
      - 推荐采用统一的网关（如 LiteLLM）。系统评测时可接入主流 API（如智谱、Qwen、DeepSeek 等），但在报告中要强调，节约的
        Token 等价于为企业节约了真金白银的 API 调用成本。
5.  CodeAct 沙箱：
      - 利用 openEuler 自带的 iSula 容器引擎（轻量级、启动快，非常适合作为评测亮点），或者简单使用 Python subprocess
        + chroot 进行资源隔离。

五、 答辩与报告的亮点包装 (加分项)

1.  操作系统视角的降维打击：不要把这个项目当成普通的 LangChain/MetaGPT 改进版。要在报告中强调：“我们将操作系统领域的
    IPC（进程间通信）、分页内存交换、缓存命中机制（Cache Hit）引入了多大模型协同网络”。
2.  解决“语义衰减”的痛点：传统纯文本协作（内部状态 -> 文本 ->
    内部状态）就像多国语言反复翻译，必定丢失信息。本系统传递高维向量（Embeddings），保留了最原始的语义特征。
3.  原生适配开源 OS：在部署文档中突出针对 openEuler 24.03 内核特性的优化（如通过 eBPF 监控 Agent
    之间的实际通信网络开销，作为实验验证的硬核数据支撑）。

这个方案直接击中赛题“低开销”、“非文本”、“共享记忆”三个核心痛点，且技术实现路径清晰，非常适合作为高分答卷提交。您可以根据团队在底层系统开发（C++/系统级Python）和上层
Agent 编排上的能力权重，对具体技术栈进行微调。


这是一个非常核心且极具拿分潜力的切入点。在当前的 AI 社区中，绝大多数开发者和研究者都是从“自然语言处理（NLP）”或“提示词工程（Prompt
Engineering）”的角度来做多智能体（Multi-Agent）。他们把 Agent 之间的协作看作是**“微信群聊”**——Agent A
发一大段话，Agent B 读完后再回一大段话。

如果你能在报告和答辩中提出：“我们抛弃了‘群聊模型’，而是将多智能体协作抽象为一个‘操作系统（OS）’，把大模型视为 CPU 计算单元，把 Agent
视为进程，用操作系统的底层机制来重构 Agent 的协作”，这在评委眼里就是典型的系统工程视角的降维打击。

下面为您详细展开这三个 OS 核心概念如何映射到多大模型协同网络，以及如何在报告中去包装和论述：

一、 核心视角的转换：从“群聊”到“操作系统”

在传统的 LangChain/AutoGen
模式下，系统瓶颈在于**“序列化/反序列化开销”**（即把大模型的内部高维状态变成人类可读的自然语言，发过去之后，另一个模型又要重新阅读理解，变成它的内部状态）。

我们的主张： 现代操作系统中，两个进程协作（比如数据库和 Web
服务器）绝对不会通过“写大段带修饰的英文”来通信。它们通过二进制协议、内存地址和信号量。Agent
也可以，并且应该这样做。

二、 概念一：将 IPC（进程间通信）引入 Agent 协作

对应赛题：结构化通信替代自然语言交互，降低 token 开销

  - 传统痛点（Prompt Chaining 的灾难）： Agent A（检索者）找到了数据，它必须在 Prompt
    里写：“你好，我是检索者，我找到了以下数据：[5000字的文本]，请你进行总结。” Agent B 接收后，消耗了大量的输入
    Token，而且还容易产生幻觉。
  - OS 视角的降维解法（Agent IPC）： 我们将 Agent 定义为 openEuler 上的独立进程（或协程）。它们之间的通信采用类似 RPC
    (Remote Procedure Call) 或 UDS (Unix Domain Sockets) 的机制。
      - 指令传递信号化：Agent 之间不再发问候语和冗长的指令，而是直接传递标准化的 “中断信号”与结构化结构体。
      - 包结构（Packet）：
        {
          "SYSCALL": "EXEC_SUMMARY",
          "SENDER_PID": "Agent_Retriever",
          "PRIORITY": 1,
          "PAYLOAD_REF": "MEMORY_ADDRESS_0x1A2B" // 注意：这里不传5000字文本！
        }
  - 报告包装话术：“我们将 Agent 通信从‘语义级的非结构化文本传递’，降维到了‘系统级的指令与参数传递’。这就好比用 gRPC
    替代了长篇大论的电子邮件，彻底消除了自然语言通信中的冗余寒暄、重复指令和解析歧义，使通信 Token 开销逼近理论最低值。”

三、 概念二：分页内存交换与零拷贝（Zero-Copy）引入状态传递

对应赛题：实现非文本中间状态传递机制（embedding/隐藏状态）

  - 传统痛点（语义损耗与延迟）： 文本是极度压缩的信息。大模型内部处理的是成百上千维的浮点数向量（Embeddings / KV
    Cache），为了发给下一个 Agent，它必须强行把高维特征解码成文字（生成耗时），下一个 Agent 收到文字后再编码回向量（Prefill
    耗时）。这是巨大的算力浪费。
  - OS 视角的降维解法（Shared Memory & Pointers）： 利用 Linux 操作系统的**共享内存（Shared Memory,
    shm 或 mmap）**机制。
      - 内存指针传递：当 Agent A 提取了文档的 Embedding 或中间状态的 Tensor 时，直接将其写入 openEuler
        的共享内存区域。
      - 零拷贝（Zero-Copy）：Agent A 只需通过上述的 IPC 协议，把共享内存的文件描述符（FD）或内存地址指针发给 Agent
        B。Agent B 瞬间读取内存中的高维向量，直接进入下游计算（如相似度计算或继续生成）。
  - 报告包装话术：“在传统框架中，跨 Agent 传递上下文需要经历 内部张量 -> 文本解码 (耗时) -> 网络传输 -> 文本编码 (耗时) ->
    内部张量 的漫长链路。我们借鉴了 Linux 的零拷贝（Zero-Copy）和内存映射（mmap）思想，实现了多 Agent
    间的‘状态共享存储’。数据不用动，传递的只是指针，不仅实现了非文本状态的无损传输，更将大块数据交换的时延降低了数个数量级。”

四、 概念三：缓存命中机制（Cache Hit）引入全局共享记忆

对应赛题：实现共享记忆模块，支持记忆复用和跨任务协同

  - 传统痛点（大模型的失忆症）： 面对稍微相似的任务，大模型通常会像没头苍蝇一样从零开始规划、重新检索、重新写一模一样的代码，导致高昂的延迟和重复计算。
  - OS 视角的降维解法（Semantic Cache Hierarchy）： 在计算机体系结构中，CPU 访问数据有 L1、L2、L3
    Cache，找不到才会去读内存（Page Fault）。我们为多 Agent 系统构建同样的**“语义缓存层级”**：
      - L1 Cache（会话级上下文）：当前任务的瞬时状态，存在 RAM 中。
      - L2 Cache（全局记忆黑板 / 共享记忆）：基于向量数据库和 SQLite 维护的历史经验、策略、代码片段。
      - Page Fault（缓存未命中机制）：当 Planner Agent 收到新任务时，它首先计算任务意图的 Embedding，去 L2
        Cache 中进行相似度检索。
          - 命中（Cache Hit）：发现昨天做过类似任务，直接提取历史策略（例如已经写好的 Python
            清洗脚本和参考证据），跳过检索和编码阶段，直接执行。
          - 未命中（Cache Miss / Page Fault）：触发缺页中断，系统才真正唤醒 Retriever Agent
            去干活，并将新结果写回 L2 Cache（记忆沉淀）。
  - 报告包装话术：“我们将大模型的推理视为极度昂贵的 CPU 计算，将外部环境探索视为耗时的 IO
    操作。通过构建基于语义相似度的‘多级记忆缓存系统’，我们的 AgentOS 在面对重复或关联任务时，能够触发‘语义缓存命中（Semantic Cache
    Hit）’。这种机制打破了任务间的隔离壁垒，让系统越用越快，完美达成了跨任务复用和算力卸载（Compute Offloading）的目标。”

五、 补充：进程调度与沙箱隔离（对应 CodeAct 和系统完整性）

如果你们队伍有精力，还可以加上一点关于**“进程调度器（Scheduler）”**的论述：

  - Planner Agent = OS Kernel / 调度器：它不再参与具体的文字生成，它只负责解析任务树（Task
    DAG），评估哪些子任务可以并行执行，然后将任务分发给空闲的 Worker Agents。
  - CodeAct = 容器化沙箱执行（Cgroups/Namespaces）：大模型写的代码是不可信的，就像运行 User-space 的未知程序。我们在
    openEuler 环境下调用轻量级沙箱（如 iSula 容器或 WASM），隔离执行大模型生成的 Python 代码，这体现了 OS
    级别的安全隔离思想。

总结：你的答辩PPT大纲（逻辑线）

1.  破题：当前多智能体协作是基于“拟人化通信”的，冗长、缓慢、且丢失高维信息。
2.  升维思路：回到计算机科学的本源，用现代操作系统的底层机制重构大模型协作。
3.  核心技术1：Agent IPC -> 解决通信开销（对应赛题：结构化通信，节约Token）。
4.  核心技术2：Zero-Copy 状态指针 -> 解决数据编解码时延（对应赛题：非文本状态直接传递）。
5.  核心技术3：Semantic Cache -> 解决重复任务的算力浪费（对应赛题：共享记忆复用）。
6.  实验证明：在 openEuler 24.03 上，展示 Token 消耗降低了 XX%，关联任务耗时下降了 XX%。

用这套叙事逻辑，你们的项目就不再是一个“套壳调用大模型API的玩具”，而是一个**“面向 AGI
时代的基础设施软件（Infra）”**。评委（通常是懂底层技术的资深工程师或研究员）会对这种既懂 AI 又懂底层系统的复合架构极度青睐。

关于任务设计 你可以详细说说 还有 这个text的对比如何设计 还有
有人提出一种有意思的创新你可以看看吗？我先把你最关心的“哪些地方是真的有问题，哪些只是定位不同”分开。接下来我会补几个关键交叉引用，避免把“看起来像功能”误认为“真正参与主流程”。

• 我补一个精确点：AgentRegistry 在主流程里基本没参与调度，只在 demo 脚本里打印能力摘要；messages
也主要是结果展示和指标统计，不是驱动图走向的输入。下面我直接按“你的问题 -> 结论 -> 为什么”来收束。

• 你的判断基本是对的：wmw
这套实现不是“完全没做”，而是“想法对、包装完整，但主流程里有几处关键能力其实比较弱，甚至带演示性质”。我按你的问题收束成一份判断。

先给总结 wmw 可以被理解成一个“赛题导向的概念验证版 demo”，不是一套已经打磨到很强说服力的系统实现。它的优点是：

  - 赛题要求几乎都能找到对应模块
  - 三通道都落了代码，不只是文档口号
  - 12 轮连续任务、双模式对比、共享记忆、非文本状态，这些都跑起来了

但它的主要问题也很清楚：

  - retriever 和 executor 的“真实专业分工”不强
  - 三通道里真正最扎实的只有 context_packet
  - hidden_state 更像研究性信号，不是强工程能力
  - 结构化消息和能力发现更多是“展示层”，不是“控制层”
  - 记忆复用是“喂回 prompt”，不是强复用

所以，如果你问“这实现漏洞多不多”，我的回答是：作为论文/答辩 demo 还行，作为强系统实现漏洞明显。

———

1.  为什么我一直说它是 demo，不是成熟系统 因为它很多关键模块是“看起来有”，但不是“真正主导系统行为”。

最典型的三个点：

  - AgentRegistry 只是预注册 4 个 agent 卡片，然后在 run_demo.py 里打印摘要。它没有参与主流程调度，不是“根据能力动态选
    agent”。

  - AgentMessage 在 structured 模式里每层都产 message，但图的走向并不是由 message 决定的。真正控制流是
    graph.py 里写死的： planner -> retriever -> executor -> summarizer

  - 任务系统 没有任务 DSL、没有通用 task contract、没有真正独立的评测运行时，只有脚本里手写 query 列表。

所以它更像： 把赛题要求都映射成一个可演示原型 而不是： 做出一个通用的多 Agent 协作平台

———

2.  ResearchState 怎么理解 你可以把 ResearchState 理解成：

这张 LangGraph 图的共享工作区 / 总线上的公共状态

这个理解比“普通变量”更贴近实际。

它的作用是：

  - 上游节点把结果写进去
  - 下游节点从里面取自己要的字段
  - 并行 retriever 的输出会在某些字段上自动聚合

所以它有点像“总线上的状态包”，但不是低层 IPC 总线，更像 LangGraph 的共享 blackboard。

尤其是这些字段：

  - documents/context_packets/embedding_payloads/hidden_state_payloads/messages
    都是并行 retriever 写入后自动累加的

  - 这是靠 Annotated[list, operator.add] 实现的

所以“LangGraph channel 承载真实状态流转”可以这样理解：

  - AgentMessage 是展示给人看的协议壳
  - ResearchState 里的字段才是系统真正拿来传递和消费的数据

也就是：

  - message 更像“日志化的协议对象”
  - state fields 更像“真正的数据总线”

———

3.  retriever 的定位是不是有问题 是的，这是 wmw 最核心的弱点之一。

你现在的理解是对的：

  - 它不是传统检索器
  - 它本质是让 LLM 直接生成一段“像检索结果的文本”
  - 再把这段文本当 document 存起来

所以它更准确的名字其实不是 retriever，而像：

  - subquery writer
  - subquery analyst
  - synthetic retriever

这会带来两个后果：

1.  它没有真正连接外部知识源 所以“检索增强”这件事很弱，更多是模型自答。

2.  下游 executor 验证的对象，其实是“上游模型自己写的文档” 而不是“外部知识库召回的材料”

所以你会觉得“中间两层定位缺失”，原因就在这：

  - retriever 没有体现出“找资料”的专业性
  - executor 也就很难体现出“基于外部证据做裁决”的专业性

———

4.  executor 的定位是不是也偏弱 你的判断也是对的，但要分开说。

executor 在代码行为上是成立的，它确实做了几件事：

  - 汇总多个 retriever 候选
  - 用三通道排序
  - 做 packet 校验
  - 必要时从 Store 补原文
  - 最后让 LLM 产出 analysis + evidence

所以从流程上说，它是个“选择器 + 分析器”。

但它的问题是：

  - 它分析的证据，大部分仍来自上游 LLM 生成文本
  - 它没有强工具执行，没有真正的 code/tool/action 执行层
  - evidence 虽然结构化了，但不是很强的外部可验证证据链

所以更准确地说，executor 在 wmw 里不是“执行器”，而更像：

  - rank-and-analyze node
  - evidence synthesizer

这也是为什么你会感觉“retrieval / execute 的真正作用没有体现”。

本质上两层都偏“文字加工”，没有拉开真正角色差异。

———

5.  三个子问题和三条通道有没有关系 没有直接关系。

这是一个很容易混淆的点。

  - 3 个 sub_query 对应的是 3 个并行 retriever

  - 3 条通道 对应的是每个 retriever 产物可以附带的 3 类中间状态

所以关系是：

  - 横向：3 个 retriever 分头处理 3 个子问题
  - 纵向：每个 retriever 的输出，可以走文本压缩、embedding、hidden state 这三种载荷

不是：

  - 一个子问题走一个通道

而是：

  - 每个子问题都可能同时产出三种通道数据

———

6.  为什么要 3 个 retriever 这里主要是为了满足两个目标：

7.  赛题要求至少 3 个 agent / 多角色协作

8.  让 planner 的拆分结果能并行 fan-out，再由 executor fan-in

所以 3 个 retriever 的价值更多是：

  - 体现并行协作
  - 给 executor 制造多个候选
  - 给三通道排序提供比较空间

如果只有 1 个 retriever：

  - 就没有明显的“路由/选择”问题
  - hidden state 和 embedding 排序的意义会大幅下降

所以 3 个 retriever 不是因为业务上一定需要 3 个，而是为了让“并行 + 汇合 + 选择”这套机制站得住。

———

7.  为什么 planner 要先搜 summary，还要把 plan 写进记忆 这件事分两半看。

先搜 summaries：

  - 因为 summary 是最浓缩的历史知识
  - planner 需要的是“对任务怎么拆”的先验
  - 所以用历史 summary 给 planner 提供高层背景，是合理的

把 plan 写进 plans：

  - 因为作者想把每一层产物都沉淀进记忆
  - 这满足赛题“中间结果、策略、经验可沉淀”的要求

但你的疑问也成立： 在主流程里，NS_PLANS 几乎没有被再用回来。 也就是说：

  - 写 plan 到记忆：有意义，但更偏“完整性”
  - 它不是当前主流程里最关键的复用来源

真正被回查的主要是：

  - planner 查 summaries
  - retriever 查 docs
  - executor 查 analysis

所以 plans 更像“留档”，不是主复用面。

———

8.  context_packet 为什么会 reliable = 0，但系统还能跑 这是你抓得最准的一个问题，这恰恰暴露了它实现上的短板。

流程是：

1.  retriever 从 doc_text 里抽证据片段，做成 packet
2.  executor 重新校验 packet
3.  如果 packet 不够可靠，就 rehydrate，从 Store 把原文片段补回来

结果里出现：

  - context_packets_reliable = 0
  - context_packets_rehydrated = 24

意思就是：

  - 它做出来的压缩包，大多数没有直接通过严格校验
  - 最后主要靠 fallback 补救

这说明什么？

  - context_packet 设计方向是对的
  - 但当前证据抽取 / coverage / reliable gate 还不够稳
  - 它能工作，靠的是“压缩失败后还能回原文”

所以这条通道是： 有实际价值，但还不够强健。

———

9.  embedding 和 hidden_state 的关系怎么定 你前面已经抓住核心了，我再更工程化地说一次。

  - context_packet 是“传输对象”

  - embedding 是“内容语义排序信号”

  - hidden_state 是“上游意图排序信号”

所以它们不是三种平行的“状态表示”，而是分层关系：

1.  先有候选文本对象 document / context_packet

2.  再有两个排序信号 embedding score + hidden score

3.  executor 用它们混合决定保留谁

所以三者关系应该理解成：

  - context_packet 解决通信压缩
  - embedding 解决内容相关性
  - hidden_state 解决意图一致性

其中 hidden_state 的定位确实更弱，因为它只做 rerank，不做真正的神经状态续传。

———

10. “hidden state 没有真正喂进下一个模型内部继续推理”怎么理解 这句话是对的，而且非常关键。

真正强一点的“跨 Agent 非文本状态传递”可能会做：

  - 共享 KV cache
  - 共享 prefix embedding
  - 共享 encoder hidden states
  - 直接注入 attention / cache / latent

但 wmw 没做这些。

它做的是：

1.  抓 hidden state
2.  序列化成向量
3.  下游拿它算 cosine similarity
4.  用于选包、裁剪 prompt

所以它不是：

上游模型内部状态 -> 下游模型内部状态

而是：

上游模型内部状态 -> 一个外部向量特征 -> 下游控制逻辑

这就是为什么我一直强调它是：

hidden-state-based routing signal

而不是：

真正的跨 Agent 神经状态续传

———

11. 记忆命中是不是也有水分 有，而且是统计口径上的水分，不一定是故意造假。

memory_reuse_hits 的问题在于：

  - 它统计的是“搜索命中次数”
  - 不是“任务层面的成功复用次数”
  - 更不是“复用后带来多少真实收益”

所以你看到：

  - 12 attempts
  - 68 hits

这不表示记忆系统神奇到 566% 命中率，而是表示：

  - 一个任务里，planner/retriever/executor 多处都可能各命中一次
  - 命中就累加

因此这套记忆模块可以说：

  - memory store 做到了
  - memory retrieval 做到了
  - memory reuse effect evaluation 做得很弱

———

12. 你说“retrieval / execute 的真正作用没有体现”，这是核心批评点 我同意，而且这是你后面如果要给别人讲 wmw，最应该抓住的一句。

更准确地说：

  - retriever 没有体现真实检索
  - executor 没有体现真实执行
  - 两者都更像“围绕 LLM 文本进行二次加工”

所以 wmw 的角色命名是“赛题友好”的，但角色实质是“demo 友好”的。

你完全可以这样概括：

  - planner 比较像真的 planner
  - retriever 更像 LLM 子问题写手，不像检索器
  - executor 更像候选选择 + 结构化分析器，不像执行器
  - summarizer 是正常的总结器

这是很公平的评价。

———

13. 最后给你一个结论版判断 如果你要把这些问题梳理给团队，我建议直接分成三类。

A. 真正做到了的

  - 固定多 Agent 图跑通了
  - text / structured 双模式跑通了
  - 共享记忆存取和持久化做到了
  - 三通道都有代码落地
  - 12 轮连续任务和指标统计做到了

B. 做到了，但实现偏弱的

  - context_packet 有价值，但可靠性不足，靠 rehydrate 补救
  - embedding 真参与排序，但只是 rerank
  - hidden_state 是研究性 routing signal，不是强状态续传
  - 记忆复用是 prompt 注入式复用，不是强 replay

C. 名字大于实质的

  - retriever 不是真检索
  - executor 不是真执行
  - AgentRegistry 不是真动态调度
  - AgentMessage 不是真消息驱动控制流
  - runtime 更像 LangGraph 固定图，而不是独立运行时中台

如果你愿意，我下一步可以把你这整套笔记整理成一版更适合汇报的文档结构，按： 赛题要求 -> wmw 对应实现 -> 满足程度 -> 主要问题
做成一份可以直接拿去讲的提纲。

这三个问题问得非常尖锐，尤其是关于 Embedding 的质疑，直接触及了目前多智能体系统的底层痛点，也是很多评委在答辩时一定会问的“死穴”。

下面我逐一为你拆解，并提供在架构设计和答辩时的“完美防御/反击策略”。

一、 关于 CodeAct：必须要用，且要设计真实的“代码任务”

你问是否可以考虑做些代码任务？答案是：必须做，而且这是拉开与“玩具系统”差距的关键。

我们在前面批评了 baseline（如 wmw）的 Executor 是“伪执行”（只是在玩文字游戏）。CodeAct（LLM
写入沙箱执行并拿回结果）就是打破这个伪执行的唯一利器。

  - 如何设计任务：不要做简单的“写个贪吃蛇代码”。要做数据流转任务。
      - 例子：任务是“分析某公司 2023 年财务报表并生成收益率走势图”。
      - 角色 1 (Retriever)：负责从海量研报中提取出包含“2023年各季度收益率”的非结构化文本表格。
      - 角色 2 (Code Executor, 采用 CodeAct)：接收到文本表格，自动编写一段 Python + Pandas
        代码。代码的功能是：清洗这些乱七八糟的文本，转换为标准 DataFrame，计算方差，并调用 matplotlib 生成一张
        trend.png。
      - 角色 3 (Summarizer)：拿到图表路径和方差数据，写出最终报告。
  - 亮点：在这个过程中，Code Executor 真正调用了外部环境（Python
    解释器），生成了非文本产物（图片），且代码执行的报错日志（stderr）可以作为反馈让大模型自我修正。这完美契合了“低延迟、可隔离的代码执行与结果回传”的赛题要求。

二、 需要引入 LangGraph 固定四个角色的节点吗？

千万不要！ 如果你用 LangGraph 把 Planner -> Retriever -> Executor -> Summarizer
写死成一个静态的有向无环图（DAG），那你又退回到了“工作流编排”的老路，这违背了赛题“系统层机制”的初衷。

如何把这套逻辑解释清楚：

  - 传统做法（被动执行）：LangGraph 里的节点是死板的。数据流到 A，A 就执行，执行完传给 B。如果 Planner
    决定这次不需要检索，在静态图中处理起来就很臃肿（需要写各种条件边 conditional_edges）。
  - 我们的创新（OS 总线模式 / Actor 模型）： 我们把系统设计成一个 “消息总线 (Message Bus)”。
    1.  四个 Agent 是在 openEuler 上常驻的独立进程/协程 (Daemon
        Workers)。它们启动时，向总线“注册”自己的能力（Capability
        Registry）。
    2.  Planner 是调度器 (Scheduler)。它不把任务“扔给下一个节点”，而是向总线广播结构化指令包（比如：{"Action":
        "Need_Data", "Topic": "TSLA_2023"}）。
    3.  Retriever 监听总线，发现这个指令匹配自己的能力，就接单执行。执行完后，把结果（指针）通过总线发回给 Planner。
    4.  Planner 再根据当前状态，决定下一步是派发代码任务给 Executor，还是派发总结任务给 Summarizer。
  - 答辩话术：“我们抛弃了 LangGraph 写死的管道模式，采用了基于发布-订阅（Pub/Sub）和能力发现机制的动态路由。Agent
    不再是图上的静态节点，而是微服务化的执行单元。这使得我们的系统能够灵活应对各种不可预见的复杂任务，而不是只能按设定好的剧本演戏。”

三、 针对“Embedding 下游还要退回文本”的质疑（核心重点！）

提出这个质疑的人非常懂行！这是一个极其经典的反问： “你上游 Retriever 传了一个 768 维的 Embedding 向量给下游 Agent。但下游的
Agent 核心是一个大语言模型（LLM），LLM 的 API 只吃文本。所以下游 Agent 拿到向量后，还不是得去数据库里把对应的原始文本查出来，塞进
Prompt 里发给 LLM？如果是这样，LLM 的 Token 消耗一滴都没省，你省的仅仅是两个 Python 进程之间的通信字节而已啊！”

如何细化和反驳？这里必须抛出我们的“两级降本”理论，分层次解决：

层次 1：工程优化级防线（语义剪枝 / Semantic Pruning）

不要说“把整个文档的 Embedding 直接喂给模型”，这不现实。我们的解释是：Embedding 是作为一种“高密度的控制信号”，在到达下游 LLM
之前，先进行了“物理隔离的过滤”。

  - 解释：如果上游用纯文本发了 10000 字给下游 Agent。下游 Agent 为了知道哪些有用，只能把 10000 字全塞给 LLM
    读，消耗 10000 Token。
  - 非文本状态设计的收益：上游 Retriever 传递的是 100 块文本的 Embedding 矩阵（通过共享内存）。下游 Agent（比如
    Executor）拿到这个矩阵后，不调用 LLM，而是用一段几毫秒的本地 Python 代码，计算当前执行目标与这 100 个 Embedding
    的余弦相似度。
  - 结果：下游 Agent 在本地直接剪枝 (Prune) 掉了 90 个无关块，最后只从库里提取出最相关的 10 块文本（1000字）塞给大模型。
  - 回应质疑：“是的，最终输入给 LLM 的必须是文本。但因为我们在 Agent 通信层传递了向量（非文本状态），使得下游 Agent 具备了在进入 LLM
    前置进行本地精确筛选的能力。我们通过向量相似度计算拦截了 90% 的冗余上下文，从而真实地节省了 90% 的 Token 开销！”

层次 2：系统架构级绝杀防线（KV Cache 共享机制）

如果你想拿最高分，光有层次 1 不够。既然你们运行在 openEuler 上，可以假定（或实际部署）底层对接的是本地开源大模型（如
Qwen2、Llama3）加上 vLLM 等推理框架。

  - 什么是真正的非文本状态传递：大模型处理文本分为两步：Prefill（预填充，即阅读阶段，把文本变成内部张量 KV Cache，极度耗时且算
    token）和 Decode（解码，生成新词）。
  - 我们的终极创新：上游 Retriever 读了一篇长文章，模型内部产生了这个文章的 KV Cache（这就是最完美的隐藏状态 Hidden
    State）。我们不要把它丢掉！
  - 传递方式：我们通过系统底层的 共享显存/内存 IPC，把这段 KV Cache 的指针保留在状态总线上。
  - 接收方式：当下游 Summarizer 被唤醒时，它向底层推理引擎（vLLM）发送结构化指令，要求直接挂载（Mount）这块 KV Cache。
  - 结果惊人：下游 Agent 的 LLM 根本不需要重新阅读那篇文章的文本（0 Prefill Token, 0 首字延迟），它直接基于内存中的
    Hidden State 开始续写（Decode）总结。
  - 回应质疑：“质疑者之所以认为无法节省 Token，是因为他的思维还局限在‘调用第三方闭源
    API’的黑盒模式。而本赛题是针对操作系统的系统级创新。我们通过传递底层推理框架的 KV Cache（真正的 Hidden
    State），让下游模型直接继承了上游模型的‘记忆张量’。这不仅彻底消除了重复的文本输入，还将长文本的预处理耗时降低到了 0，这才是赛题要求的‘非文本中间状态传递’的终极奥义！”

总结你的答辩子弹：

1.  关于代码：我们深度整合了 CodeAct，让 Executor 真正驱动 Python 解释器处理真实数据流，彻底粉碎 LLM 的“自言自语/伪执行”。
2.  关于 LangGraph：我们摒弃了硬编码的 DAG，采用“能力注册 + 消息总线”的 OS 调度模式，实现真正的动态协作。
3.  关于非文本/Embedding 降本：对于外部 API 模式，我们利用向量传递实现了“前置语义剪枝过滤”，切断冗余
    Token；对于本地部署模式，我们探索了“KV Cache 张量直接挂载”，实现了 100% 的上下文 Token
    免除。这证明我们的创新既有工程落地性，又有前沿探索深度。

带着这套逻辑，无论是设计系统还是写报告，都能保证逻辑严密，无惧任何硬核评委的拷问。

这是一个非常关键的架构决策问题。

关于**“是否保留三通道，还是只用 KV Cache”**，我的核心建议是：不要把鸡蛋全放在 KV Cache
这一只篮子里，我们需要重新定义“三通道”，构建一个“分级递进”的状态传递体系。

如果只做 KV Cache，工程风险极高（极度依赖底层推理引擎如 vLLM 的定制开发），且不具备跨任务长效保存的能力（KV Cache
存在显存里，任务一停就清空了）。

在此，我将之前所有的推演、剖析和创新点，整合成一份**【Co-AgentOS
原型系统最终设计与答辩蓝图】**。这不仅是你们的开发指南，更是你们面对评委时的“剧本”。

Co-AgentOS：基于操作系统内核机制的多智能体协同框架

核心主张（答辩开场白）

“当前的多智能体框架（如 LangChain、主流赛题 baseline）普遍陷入了‘伪协作’的陷阱：基于静态 DAG
图的流程硬编码、基于长文本序列化的‘群聊式’通信、以及仅停留在文字游戏层面的‘伪执行’。
我们将摒弃这种应用层的玩具做法，引入现代操作系统的**进程间通信（IPC）、零拷贝（Zero-Copy）、分页缓存（Cache
Hierarchy）**机制，在 openEuler 操作系统上重构真正的多智能体底层基础设施。”

一、 架构设计：重新定义的“三通道”状态传递

我们不再使用之前 baseline 中那种平行且冗余的三通道（都是为了最后拼 prompt），而是构建面向不同生命周期和用途的“三级状态存储与传递机制”：

1. 终极性能层：KV Cache 挂载（对应“Hidden State”的涅槃）

  - 用途：同一次任务中，Agent 之间的极速上下文接力。
  - 机制：当 Retriever 阅读完长文档后，其底层的 vLLM 推理引擎生成了该文档的 KV Cache 张量。我们通过系统层将这个张量的
    ID（或显存指针）存入总线。下游 Summarizer 接手时，不传递原始文本，而是发送挂载指令，直接基于该 KV Cache 开始
    Decode（生成总结）。
  - 收益：Prefill Token 消耗直接降为 0，首字延迟（TTFT）逼近物理极限。

2. 语义路由层：Embedding 共享内存指针（对应“Embedding”）

  - 用途：进入大模型前的精确剪枝，以及跨任务的全局记忆检索。
  - 机制：KV Cache 无法长久保存，因此 Retriever 在处理海量外部数据时，会将其切块并生成轻量级的 Embedding 矩阵，存入
    Linux 的 /dev/shm（共享内存）。
  - 防守逻辑（解答之前的质疑）：当下游 Executor 需要数据时，它收到的只是一个内存指针 shm_ptr。Executor 在外部通过极低开销的
    Python 脚本计算余弦相似度，拦截掉 90% 的无关数据。最终只有最核心的 10% 文本被送入 LLM。这证明了 Embedding
    通道确实真实地节省了 90% 的冗余 Token 输入。

3. 结构化控制流层：精简通信协议（对应“Context Packet”的升级）

  - 用途：替代自然语言，作为驱动多 Agent 流转的“系统调用（Syscall）”。
  - 机制：完全剥离业务文本。通信包仅包含：Header (任务ID、发送者)、Action (动作类型)、Payload_Refs (指向上述 KV
    Cache 或 Embedding 的内存地址指针)。
  - 收益：Agent 间的通信开销从几 MB 的长文本骤降到几十 Byte 的控制信号。

二、 动态运行时：抛弃 LangGraph 固定图

  - 痛点：固定 DAG 图缺乏灵活性，无法应对复杂任务树。
  - 创新：实现 “能力发现 + 消息总线（Message Bus）”。
      - 系统总线：部署一个轻量级消息队列（可基于 openEuler 的 UDS UNIX 域套接字）。
      - 角色常驻：Planner、Retriever、Executor、Summarizer 就像系统的后台 Daemon 进程。
      - 动态派发：Planner 解析任务后，向总线广播结构化任务包（如 {"req_capability": "python_execute",
        "data_ptr": "0xABC"}）。Executor 监听到匹配自身能力的任务，主动接单执行。这实现了真正的动态微服务调度。

三、 任务设计：真实数据验证与 CodeAct 沙箱

为了彻底碾压 baseline 中“模型自导自演生成假报告”的伪执行，我们设计强依赖真实环境的连环任务：

  - 场景：宏观经济与财务数据分析

  - 任务 A（冷启动）：“检索 2023 年特斯拉（TSLA）的各季度财报 PDF，提取毛利率数据，并绘制趋势图。”

      - 真检索：Retriever 调用真实的文件读取/爬虫工具，下载 PDF，切割并生成 Embedding。
      - 真执行 (CodeAct)：Executor 接收到 Planner 生成的 Python 代码，在 openEuler 的 iSula
        轻量容器/沙箱 中真实执行 pandas 计算和 matplotlib 绘图。
      - 记忆沉淀：任务完成后，除了最终报告，系统将**“清洗财报的 Python 代码策略”、“TSLA 财报的 Embedding
        矩阵”**存入全局记忆库（L2 Cache）。

  - 任务 B（关联复用测试）：“对比分析 2023 年特斯拉（TSLA）与比亚迪（BYD）的毛利率差异。”

      - 语义缓存命中（Semantic Cache Hit）：Planner 收到任务后，在全局记忆库中进行向量匹配。
      - 强复用发生：系统发现 TSLA 的数据和处理逻辑已存在。直接复用上次的 Python 代码模板，仅替换变量名为 BYD，并派发单一指令去检索
        BYD 数据。
      - 证明收益：对比发现，任务 B 的耗时、通信频次、大模型 Token 消耗，相较于任务 A 大幅缩减（预期降低 60% 以上）。

四、 对比实验设计（系统性能展示的杀手锏）

为了证明我们的架构优越性，系统必须实现一个“一键切换模式”的开关，运行自动化 A/B 测试：

  - 模式 A（纯文本基线模式 - 模拟传统应用层）： 所有 Agent 通过完整 JSON
    传递大段文本，无共享内存，无全局缓存命中。每次任务重新读文档、重新写代码。
  - 模式 B（Co-AgentOS 系统级模式）： 开启指针通信、共享内存、Embedding 剪枝与 L2 Cache 记忆复用。
  - 展示的硬核 Dashboard 数据指标：
    1.  通信字节流对比：模式A (MB 级) vs 模式B (KB 级)。
    2.  Prompt Token 节省量：精确统计通过 Embedding 前置剪枝和记忆命中带来的 Token 节省。
    3.  大块内存交换次数/大小：通过 /dev/shm 传递的非文本状态数据量。
    4.  端到端时延（Latency）对比：任务 B 在开启记忆复用后的断崖式时间下降。

五、 最终总结（为什么这个方案能赢？）

1.  立意极高：没有停留在“如何把提示词写好”的 Prompt Engineering 层面，而是真正回答了赛题中“多智能体协作的基础设施问题”。
2.  漏洞封堵完美：
      - 针对“复用只起安慰剂作用”的质疑 -> 我们设计了代码级与中间态数据的强复用。
      - 针对“Embedding 还是要退回文本”的质疑 -> 我们提出了前置语义剪枝 + KV Cache 挂载的两级防线。
      - 针对“伪执行” -> 我们强制引入 CodeAct + 沙箱处理真实外部文件。
3.  技术栈深度契合操作系统：深度利用 Linux / openEuler 的 IPC、shm、沙箱技术，完美贴合平台赛题的底层要求。

团队执行建议： 在有限的时间内，KV Cache 共享 如果实现难度过大，可以在代码实现中重点发力 “Embedding 剪枝 +
共享内存传递”，但在系统设计文档和答辩 PPT 中，必须把 KV Cache
作为你们架构的“终极一环/未来规划”重点讲出来，这代表了你们对非文本状态传递的最深刻理解。仅靠真检索、真代码执行和内存指针通信，就已经足以在工程实现上对其他平庸方案形成降维打击了。

这不仅完全可以并存，而且将它们设计为**“互补的分级状态传递机制”**，正是让你们的架构从“优秀”走向“完美”的画龙点睛之笔！

如果你在答辩和系统设计中提出**“自适应、分级梯度的多模态状态传递架构”**，这会极大地展现你们的系统工程成熟度。

下面详细为你拆解：如何让“KV Cache”和“Embedding 剪枝”并存？如果同时开启，它们在业务流中是如何完美互补的？以及如何处理本地模型 vs API
调用的情况。

一、 核心设计理念：宏观过滤与微观加速的互补

不要把这两个机制看作是“二选一”的替代品，它们在多 Agent 协作中解决的是不同维度的问题：

  - Embedding 剪枝 = 宏观过滤（粗排，解决“找什么”的问题）
      - 适用场景：面对海量外部数据、跨任务的历史记忆检索。
      - 特点：极度轻量、可持久化保存（存入向量数据库）、不依赖特定大模型。
  - KV Cache 共享 = 微观加速（精排与执行，解决“怎么传”的问题）
      - 适用场景：同一次任务内，两个高频互动 Agent 之间（如 Planner 传给 Executor）的瞬时上下文接力。
      - 特点：极度快速（Zero Prefill Token）、包含最深度的语义信息、但无法长久保存（存在显存里），且强依赖底层推理引擎。

绝佳的比喻（可以在答辩时用）：

“Embedding 就像是图书馆的检索目录。当你面对一万本书时，你需要 Embedding 帮你瞬间找到最相关的 3 本书。但这 3
本书你依然需要用眼睛去读。 而 KV Cache 就像是大脑的神经突触。当 Agent A 读完这 3 本书并在脑海中形成了理解后，它直接把脑电波（KV
Cache 指针）传给 Agent B，Agent B 瞬间就懂了，完全不需要再读一遍文字。”

二、 业务流演练：同时开启时，它们如何完美配合？

假设我们执行那个复杂的宏观经济数据任务。系统同时开启了双通道，这是数据的流转过程：

1.  阶段一：Embedding 担纲（海量数据降维）

      - Retriever Agent 去外部抓取了 50 篇长达十万字的研报。
      - Retriever 将其切块，生成 Embedding 矩阵，存入共享内存（SHM）。
      - 此时 KV Cache 不出场，因为显存装不下 50 篇研报，且大部分是废话。
      - Executor 拿到 SHM 指针，在外部执行余弦相似度，剪枝掉 95% 的废话，只保留了最核心的 5000 字有效文本。
      - 收益：拦截了 95,000 个冗余 Token。

2.  阶段二：KV Cache 接管（瞬时状态接力）

      - Executor 将这精简后的 5000 字输入给底层的本地大模型，模型生成了一段核心的数据分析逻辑和提纲。
      - 此时触发 KV Cache 共享。Executor 不把这段提纲变成纯文本发给下游。它向总线发送指令：{"Action":
        "Summarize", "KV_Cache_Ptr": "0xGPU_MEM_88"}。
      - 下游 Summarizer 接收到指令，直接挂载该显存地址。
      - Summarizer 的大模型在完全没有重新阅读那 5000 字上下文的情况下（0
        Prefill），直接开始吐出最终的总结报告（Decode）。
      - 收益：消除了 5000 个 Prefill Token 的时延，实现了真正的神经元级别状态续传。

结论：在这个流程中，Embedding 负责从 100 降到 1，KV Cache 负责让 1 到 1 的传递实现零损耗。两者无缝衔接，堪称完美。

三、 架构设计的退路：自适应的回退机制（Fallback Mechanism）

在实际工程中，由于评测环境的不确定性，你们必须设计一套**“感知底层环境的自适应机制”**。这也是评委非常看重的“健壮性（Robustness）”。

你们可以在系统设计文档中提出：“Co-AgentOS 具备环境感知的自适应状态协议（Adaptive State Protocol）”。

  - 如果部署在纯本地环境（如 openEuler + vLLM/SGLang 等开源推理引擎）：
      - 系统检测到底层支持 Tensor 共享。
      - 自动开启 Tier-1 模式（全功率）：海量数据用 Embedding 剪枝 + 节点接力用 KV Cache 共享挂载。性能拉满。
  - 如果部署在云端 API 环境（如调用 OpenAI / 智谱 / DeepSeek 的黑盒 API）：
      - 系统检测到底层是封闭的 HTTP API，无法获取 KV Cache 显存指针。
      - 自动触发降级（Graceful Degradation），回退到 Tier-2 模式。
      - 关闭 KV Cache 共享，全面依赖 Embedding 剪枝 + 共享内存传递。
      - 向评委解释：“即便在黑盒 API 时代，我们的系统依然可以通过共享内存传递向量，并在端侧完成本地相似度剪枝，依然能为企业节约海量的 API
        Token 计费成本。”

四、 如何在代码落地与答辩中分配精力？

1.  代码实现优先级（务实路线）：

      - 必须 100% 跑通的是：Embedding 剪枝 + 共享内存（SHM）传递。因为这个完全可以通过 Python 的
        multiprocessing.shared_memory 和本地轻量模型（如 Sentence-Transformers 或
        BGE）搞定，不挑大模型 API，非常稳定，且满足赛题要求。
      - KV Cache 作为“探索性特性（Experimental Feature）”或“Demo 亮点”：如果你们队伍有熟悉 vLLM
        PagedAttention 机制的人，可以做一个小 Demo
        跑通。如果实在做不出来，就在代码框架里留下接口定义（Stub），并在报告里重点阐述设计思想。

2.  答辩 PPT 的呈现策略（高举高打）：

      - 画一张非常清晰的**“双漏斗架构图”**。
      - 上层漏斗标明：外部知识海 -> Embedding 共享内存剪枝 -> 过滤掉 90% 噪音（解决信息过载和长程记忆）。
      - 下层漏斗标明：精简上下文 -> KV Cache 指针接力传递 -> 0 耗时状态续传（解决节点间通信延迟和重复计算）。
      - 旁白标注：具备智能降级机制，兼容本地推理引擎与云端黑盒 API。

按照这个逻辑去圆，质疑你们“Embedding 还要退回文本”的评委，不仅会被你们的前置剪枝逻辑说服，还会被你们“KV Cache 与 Embedding
互补并存、根据环境优雅降级”的庞大系统视野彻底折服。

这是一个非常务实的推进。在明确了“OS 降维打击”和“双漏斗状态传递”的宏观理念后，我们现在需要把它们落地为可执行的代码架构和严密的评测剧本。

以下是为你们量身定制的【任务设计剧本】与【核心模块详细设计说明】。

第一部分：任务设计剧本（如何完美展示赛题要求的“降本增效”）

赛题要求“至少设计 2
组具有关联性的连续任务”，我们要设计一个**“增量式数据分析与图表生成”**任务。这个场景能完美倒逼出“真检索”、“真执行（CodeAct）”和“强记忆复用”。

核心场景：新能源车企 2023 年财务数据深度分析

前置环境：准备几个包含真实数据的 PDF/CSV 文件（模拟外部知识库，如特斯拉、比亚迪、蔚来的财报），并配置好 Python 执行沙箱。

🥊 任务 1：冷启动与知识拓荒（打底与沉淀）

  - 用户输入：“请分析特斯拉（TSLA）和比亚迪（BYD）2023 年各季度的毛利率（Gross
    Margin）数据，编写代码计算两者的年均差值，并绘制出折线对比图。”
  - 系统执行流（Co-AgentOS 模式）：
    1.  Planner：收到任务，查全局记忆（L2 Cache），未命中（Cache Miss）。拆解任务发布到系统总线。
    2.  Retriever：接单，读取 TSLA 和 BYD 的长篇财报文档。利用本地小模型（如
        BGE）将数万字文档切块并向量化，存入共享内存（SHM）。向总线返回指针。
    3.  Executor (CodeAct)：拿到指针。在沙箱内运行 Python，先用余弦相似度剪枝掉 90%
        的废话，提取出含有“毛利率”的表格数据。然后 LLM 生成 Python pandas/matplotlib 代码，执行计算并画图。
    4.  Summarizer：基于计算结果输出最终报告。
    5.  🌟 记忆沉淀（重点）：任务结束时，系统将以下三样东西打包存入 SQLite + 向量库：
          - 数据记忆：TSLA 和 BYD 财报的核心 Embedding 矩阵。
          - 策略/代码记忆：“提取毛利率并画对比图”的 Python 模板代码。
          - 结论记忆：2023 年两者的年均差值文本。

🥊 任务 2：关联复用与效率爆发（见证奇迹的时刻）

  - 用户输入：“在刚才的对比中，把蔚来（NIO）2023 年的各季度毛利率也加进去，重新计算三者的方差，并更新对比图。”
  - 系统执行流（效率降维打击）：
    1.  Planner：将用户意图向量化，去全局记忆库检索。🌟 触发语义缓存命中（Semantic Cache Hit）！ 发现了任务 1
        的数据和代码。
    2.  Retriever：Planner 告诉 Retriever：“TSLA 和 BYD 已经有了，你只需要去查 NIO
        的财报。”（避免了重复检索）。
    3.  Executor：Planner 直接从记忆库提取出任务 1 的 Python 代码模板发给 Executor。Executor
        的大模型发现只需在代码里加一行 NIO 的变量即可。
    4.  通信层：Planner 传给 Executor 的指令极短，因为 TSLA/BYD 的数据无需用文本重发，直接传历史记忆池的 Memory_ID
        即可。
  - A/B 测试展示结果： 相比于纯文本模式（每次任务重头把三家公司文章读一遍、重新从零构思写代码），我们的模式在任务 2 中：耗时骤降 70%，Token
    消耗骤降 80%，网络字节流降至 1% 以内。评委看到这个数据对比，直接满分。

第二部分：各核心模块详细设计说明（系统架构拆解）

我们要向评委展示的系统架构图，必须像现代操作系统的架构图：分离“控制平面（Control Plane）”与“数据平面（Data Plane）”。

模块一：System Bus (底层通信与状态总线) —— 对应“通信创新”

  - 定位：系统的神经网络，替代 LangGraph 的静态边。
  - 控制平面（结构化指令传递）：
      - 技术栈：基于 openEuler 的 Unix Domain Sockets (UDS) 或轻量级消息队列（如 Redis/ZeroMQ）。
      - 数据格式：采用 MessagePack (比 JSON 更快更小的二进制格式)。
      - 包结构：包含 TaskID, Sender, ActionType, Capability_Req，绝对不包含大段业务文本。
  - 数据平面（非文本状态传递）：
      - 技术栈：Python multiprocessing.shared_memory (底层调用 POSIX shm_open)。
      - 机制：大块的 Numpy Arrays（如 Embedding 矩阵、长篇 CSV 数据）直接写入内存。控制平面只负责传递诸如
        shm_name="agent_data_9527" 的指针。

模块二：Agent Runtime (多智能体运行时) —— 对应“角色与调度”

所有 Agent 都是独立运行的进程，基于事件驱动（监听总线）。

1.  Planner Agent (调度内核)
      - 职责：解析人类输入 -> 查 L2 记忆缓存 -> 生成有向无环图 (DAG) -> 将子任务广播到总线。
      - 核心逻辑：它不管具体怎么干活，只管“派单”。
2.  Retriever Agent (I/O 与向量引擎)
      - 职责：处理外部输入，降维转换。
      - 内部组件：集成一个极轻量的本地 Embedding 模型（如
        sentence-transformers/all-MiniLM-L6-v2，CPU 都能跑得飞快）。
      - 产出：文本块及其对应的 768 维特征矩阵（存入 SHM）。
3.  Executor Agent (CodeAct 执行沙箱) —— 亮点模块
      - 职责：基于 LLM 生成代码，并在隔离环境中运行。
      - 沙箱技术：在 openEuler 环境下，使用 subprocess 加 chroot，或者直接调用 iSula / Docker
        容器启动一个包含 pandas/matplotlib 的干净 Python 环境。
      - 执行流：LLM 编写 Python -> 写入沙箱文件 -> 运行 -> 捕获 stdout (数据结果) 和 stderr (报错则喂回
        LLM 重试) -> 输出结果指针。
4.  Summarizer Agent (显示与呈现)
      - 职责：将零散的最终数据（图表路径、数值）整合成自然语言发给用户。

模块三：Semantic Memory (全局共享记忆) —— 对应“记忆复用”

这是打破“同任务复用假象”，实现“跨任务真正复用”的核心。

  - 技术栈：SQLite (存元数据与关系) + FAISS 或 ChromaDB (存向量索引供语义检索)。
  - 记忆单元 (Memory Unit) 定义：
    {
      "memory_id": "MEM_2023_TSLA",
      "source_agent": "Executor",
      "task_intent_embedding": "[0.12, -0.45, ...]", // 记录当时的任务意图，用于下次命中
      "strategy_code": "def calc_margin(): ...",    // 经验复用：保存跑通的代码
      "data_shm_ref": "shm_tsla_data",              // 证据链：指向特征数据的引用
      "summary": "TSLA 2023 margin is 18.2%"        // 结论复用
    }
  - 复用机制（Cache Hit）：新任务到来时，先用新任务的意图计算向量，去 FAISS 里做最近邻搜索。如果相似度 > 0.85，则触发复用。

模块四：Evaluator & Profiler (评测探针) —— 对应“对比实验”

为了满足赛题的“展示性能对比”，我们需要在系统中挂载探针。

  - 功能：在代码入口处设计开关：--mode baseline_text vs --mode agent_os。
  - 监控指标收集：
    1.  Token Counter：拦截 LLM API 的返回体，统计 Prompt / Completion Tokens。
    2.  IPC Monitor：统计通过总线发送的字节数（展示通信降级）。
    3.  Latency Tracker：记录各个节点的绝对时间戳。
    4.  SHM Tracker：记录非文本状态（共享内存）被读取的次数和体积。
  - 最终交付物：在系统运行完毕后，不仅输出任务结果，还要在终端打印一张漂亮的 A/B 性能对比 Markdown 表格（甚至可以写个简单的前端
    Dashboard 展示折线图）。

总结：你的开发路线图（Roadmap）

建议队伍按以下顺序推进开发，稳扎稳打：

1.  Phase 1: 基础设施搭建（1-2周）
      - 不碰大模型。先用 Python multiprocessing 写好基于 UDS 的消息总线和基于 /dev/shm 的共享内存读写工具类。
      - 实现 4 个 Agent 进程的互相“空包打招呼”（Ping-Pong 测试）。
2.  Phase 2: 接入 LLM 与 CodeAct 沙箱（2周）
      - 接入大模型 API 或本地模型。
      - 重点攻坚 Executor：跑通 LLM 写 Python 代码并在 openEuler 隔离环境下安全执行并获取结果的闭环。
3.  Phase 3: Embedding 剪枝与记忆系统（1.5周）
      - 集成本地 BGE 向量模型。
      - 实现 SQLite + FAISS 的 L2 Cache 记忆黑板。跑通任务 1 到任务 2 的“Cache Hit”逻辑。
4.  Phase 4: 评测大盘与实验报告（1周）
      - 打磨 A/B 测试模式，跑出极其漂亮、断崖式下降的 Token/延迟对比图表。
      - 撰写《架构设计与实验验证报告》。

这个设计不仅完全契合赛题，而且在工程品味上碾压了当前绝大多数的“玩具级 Agent”。按照这个蓝图施工，你们一定能打造出一个令评委惊艳的作品。

没问题，我们把颗粒度降到**“代码级/架构级”**，把每一个模块到底“长什么样”、“用什么技术栈”、“怎么运行”彻底落实。

你可以把这份说明直接作为你们团队的**《系统详细设计说明书 (Detailed Design Document)》**。

1. 结构化通信设计 (Structured Communication)

目的：彻底消灭自然语言“群聊”，将 Agent 交互变成“系统调用 (System Call)”。

  - 技术栈：Python dataclass / Pydantic + MessagePack (序列化)。

  - 具体落实： 以前纯文本模式下，Agent A 发给 Agent B 的内容是： ❌
    “你好，我是检索器，我找到了特斯拉的财报，内容是[10000字]...请你总结。”

    在我们的系统中，定义一个标准的 SysCallMessage 结构体：

    class SysCallMessage(BaseModel):
        msg_id: str               # 唯一追踪ID
        sender_pid: str           # 比如 "Agent_Retriever"
        target_role: str          # 比如 "Executor"
        action_type: str          # 动作宏：如 "COMPUTE_MATH", "SUMMARIZE"
        args: dict                # 极简参数，如 {"company": "TSLA", "year": "2023"}
        state_pointers: list      # 核心创新：非文本数据的指针列表，如 ["shm_tsla_01"]

  - 如何体现降本：结构化消息序列化后仅有大约 100-200 字节，而纯文本模式动辄几 MB。这在实验数据中是几十万倍的降幅。

2. IPC 设计 (进程间通信与 Zero-Copy)

目的：解决大块非文本状态（如数据表格、特征向量）在多个 Agent 进程间传递时的序列化耗时。

  - 技术栈：openEuler 本地环境。
      - 控制流：Unix Domain Sockets (UDS) -> 极速传上述的 SysCallMessage。
      - 数据流：Python multiprocessing.shared_memory (底层是 Linux /dev/shm) -> 传大块数据。
  - 具体落实（代码级逻辑）：
    1.  写内存：Retriever 抓取了 5MB 的 CSV 数据，将其转化为 Numpy Array。
        from multiprocessing import shared_memory
        import numpy as np

        data_array = np.array(...) # 5MB 的特征矩阵
        shm = shared_memory.SharedMemory(create=True, size=data_array.nbytes)
        # 将数据拷贝到共享内存
        np.ndarray(data_array.shape, dtype=data_array.dtype, buffer=shm.buf)[:] = data_array[:]
        print(shm.name) # 例如输出 'wnsm_a1b2' (这就是指针)
    2.  发指针：Retriever 把 'wnsm_a1b2' 塞进 SysCallMessage 的 state_pointers，通过 UDS 发给
        Executor。
    3.  读内存：Executor 收到消息，直接挂载内存，瞬间读出数据，全程 0 网络开销，0 文本反序列化开销。
        existing_shm = shared_memory.SharedMemory(name='wnsm_a1b2')
        # 直接读取，零拷贝
        data = np.ndarray(shape, dtype=dtype, buffer=existing_shm.buf)

3. Embedding 状态传递与剪枝设计

目的：解答“到底怎么省 LLM Token”的终极疑问。

  - 技术栈：本地轻量级向量模型 sentence-transformers/all-MiniLM-L6-v2 (加载极快，不需要调用外部 API) +
    Numpy。
  - 具体落实（核心业务流）：
    1.  生成态 (Retriever)：拿到 50 篇共十万字的研报。使用本地 MiniLM 模型，将十万字切成 1000 块，生成一个形状为
        (1000, 384) 的 Embedding 矩阵。
    2.  传递态：按上述 IPC 方法，将这个矩阵存入共享内存，传指针给 Executor。
    3.  使用态 (Executor 本地剪枝 - 省 Token 的关键)：
          - Executor 收到指针并读取了 1000 个向量。
          - 当前任务是“找特斯拉的毛利率”。Executor 不用大模型，而是再次用本地 MiniLM 将“特斯拉毛利率”这句话变成 1 个 384
            维的查询向量。
          - 用纯 Python (Numpy) 计算这 1 个向量与那 1000 个向量的余弦相似度。
          - 剪枝：只取相似度最高的前 5 个文本块（约 500 字）。
          - 最后一步：将这精挑细选的 500 字发给真正的大模型 API（如 Qwen/DeepSeek）进行运算。
  - 结论：通过 Embedding 非文本状态的传递，把原本需要消耗 100,000 Token 的任务，在本地降维拦截，最终只消耗了 500 Token。

4. 共享记忆模块设计 (Semantic Memory)

目的：实现跨任务的“强复用”，避免大模型重新思考和重新写代码。

  - 技术栈：SQLite3 (存元数据与大段文本) + FAISS 本地向量库 (做相似度匹配)。
  - 具体落实：
      - 存储结构 (在 SQLite 中建表)： ID | Task_Query (原始任务) | Strategy_Code
        (当时跑通的Python代码) | Evidence_SHM_ID (依赖的底层数据) | Summary
      - 如何存：每次任务圆满结束后，系统截获 Executor 写的最终版 Python 代码，以及任务结论，写入 SQLite。并将
        Task_Query 转化为向量存入 FAISS。
      - 如何用（Cache Hit 逻辑）：
        1.  来了新任务：“分析比亚迪 2023 毛利率”。
        2.  Planner 将其向量化，去 FAISS 检索。
        3.  FAISS 发现它和昨天做的“分析特斯拉 2023 毛利率”向量相似度高达 0.92。
        4.  触发复用：Planner 不再让模型重新从零思考怎么写爬取和分析代码。直接从 SQLite 调出昨天的 Strategy_Code。
        5.  Planner 用小模型或正则替换把代码里的 TSLA 换成 BYD，直接丢给执行器运行。
          - 省掉了什么？ 省掉了大模型复杂的 Task Planning (任务分解) 和 Code Generation (代码生成)
            两个最耗时的推理步骤。

5. 对比实验设计 (A/B Testing) - 评委最看重的部分

目的：用铁一样的数据证明你们的方案碾压了传统方案。

  - 具体落实：在系统入口写一个启动参数 --mode。

  - Mode A (Baseline 纯文本模式)：

      - 关闭 IPC 共享内存，所有 Numpy 数组用 json.dumps(array.tolist()) 强转成超长字符串。
      - 通信用普通的 TCP Socket 发送超长 JSON。
      - 关闭 FAISS 记忆检索，每次强制大模型从头分解任务。
      - 不执行本地 Embedding 剪枝，把所有 Retriever 获取的文本塞入 LLM Prompt。

  - Mode B (Co-AgentOS 模式)：

      - 全功率开启上述的 1、2、3、4 模块。

  - 探针 (Profiler) 埋点设计： 在核心函数上加装饰器 @profiler.track，收集 4 个关键数据：

    1.  Total_Network_Bytes: 统计通过 Socket 发送的字节总数。
    2.  LLM_Prompt_Tokens: 统计发送给大模型 API 的 Token 消耗总量。
    3.  State_Transfer_Time: 统计 Agent A 生成结果到 Agent B 开始处理的时间差（体现 JSON 序列化 vs
        Zero-copy 的差距）。
    4.  Task_E2E_Latency: 任务端到端总耗时。

  - 剧本演示 (必须体现在答辩 PPT 中)： 针对之前设计的“连续任务 1（查特斯拉） -> 连续任务 2（查比亚迪）”。
    生成如下表格直观对比（预期数据）：

    | 指标               | 纯文本模式 (任务2) | AgentOS模式 (任务2) | 提升效果         | 核心原因                   |
    | :--------------- | :---------- | :-------------- | :----------- | :--------------------- |
    | **进程间通信量**       | 4.2 MB      | 256 Bytes       | ⬇️ **99.9%** | 指针替代全量文本流              |
    | **LLM Token 消耗** | 85,000      | 1,200           | ⬇️ **98.5%** | Embedding本地剪枝 + 代码记忆复用 |
    | **状态解析延迟**       | 1250 ms     | \< 1 ms         | ⬇️ **99.9%** | 共享内存 Zero-Copy         |
    | **任务端到端耗时**      | 45 秒        | 6 秒             | ⬇️ **86.6%** | Cache Hit，跳过代码生成环节     |

总结团队分工建议：

要实现这套方案，你们可以将队伍分为三条线并行开发：

1.  基础设施同学 (1人)：专攻底层的 IPC 设计（UDS + 共享内存）和结构化消息总线。不涉及 AI，只确保两个 Python 进程能秒传 10MB
    的矩阵数据。
2.  AI & RAG 同学 (1人)：专攻 Retriever 和 记忆系统。把 Sentence-Transformer 和 FAISS/SQLite
    跑通，实现 Embedding 的生成、剪枝和 Cache Hit 匹配逻辑。
3.  Agent 编排与沙箱同学 (1人)：专攻 Planner 和 Executor。实现 CodeAct 逻辑，让大模型能写代码，并使用
    subprocess 或容器在本地安全运行并拿到结果。最后整合 A/B 测试的探针模块。

这是一个极其明智的决定！在系统级/底层创新的赛题中，评委往往没有时间去一行行看你的核心代码。一个极具“极客感”和“监控感”的前后端
Dashboard（控制台界面），是将你们底层技术（零拷贝、状态传递、命中率）具象化、可视化的最强武器。

为了让你和团队能够直接开干，我将内容分为两部分：第一部分是底层模块的“落地级”技术选型与伪代码；第二部分是专属定制的“AgentOS 控制台”前后端设计方案。

第一部分：底层细节“硬核落地”指南

不要用普通的 Python 函数调用去做 Agent，这体现不出“OS 级别”。

1. 结构化总线与 IPC（落地技术选型：ZeroMQ + SharedMemory）

  - 为什么用 ZeroMQ (ZMQ)？ 它是介于 Socket 和 消息队列（如 RabbitMQ）之间的极轻量级 C 库（有 Python 绑定
    pyzmq）。非常符合操作系统底层的气质，支持发布-订阅（Pub/Sub）模式，速度极快。
  - 落地设计：
      - 创建一个 Bus_Daemon 进程，绑定一个本地端口（如 ipc:///tmp/agent_bus.ipc）。
      - 所有 Agent 启动时，连接这个 IPC 地址。
      - 代码级体现：
        # Agent 发送结构化控制指令 (不到 100 Bytes)
        import zmq
        import msgpack
        context = zmq.Context()
        socket = context.socket(zmq.PUB)
        socket.bind("ipc:///tmp/agent_bus.ipc")

        payload = {
            "task_id": "T-101",
            "action": "EXECUTE_CODE",
            "shm_ptr": "shm_matrix_992" # 仅传指针
        }
        socket.send(msgpack.packb(payload))

2. CodeAct 沙箱隔离执行（落地技术选型：openEuler iSula 或 本地受限 subprocess）

  - 落地设计：不要直接 eval() 或 exec() 大模型的代码，这在评审时是大忌。
  - 最佳方案：由于你们需要在 openEuler 24.03 上运行，强烈建议调用 openEuler 原生的轻量级容器引擎 iSula（如果嫌麻烦，用
    Docker 或带 resource 限制的 subprocess）。
  - 执行流逻辑：
    1.  Executor Agent 将 LLM 写的代码存为 /tmp/task_101.py。
    2.  调用沙箱执行：isula run -v /tmp:/tmp python_env python /tmp/task_101.py。
    3.  代码里强制要求大模型将结果（图表或 JSON）写到共享挂载目录。
    4.  捕获日志。如果报错，截取 stderr 发回给 LLM 说：“代码运行报错了，错误是 XXX，请修改并重试”。（这种自我纠错能力是
        CodeAct 的灵魂）。

3. 记忆系统检索复用（落地技术选型：FAISS + SQLite 联合查询）

  - 落地设计：
    # 1. 意图检索 (FAISS)
    current_intent_emb = get_embedding("分析比亚迪2023毛利率")
    D, I = faiss_index.search(current_intent_emb, k=1)

    if D[0][0] > 0.85: # 相似度阈值，触发 Cache Hit
        memory_id = sqlite_ids[I[0][0]]
        
        # 2. 策略提取 (SQLite)
        cursor.execute("SELECT strategy_code FROM memory WHERE id=?", (memory_id,))
        cached_code = cursor.fetchone()[0]
        
        # 3. 模板替换并直接进入 CodeAct (跳过 LLM 生成代码)
        new_code = cached_code.replace("TSLA", "BYD")
        execute_in_sandbox(new_code)

第二部分：“AgentOS 控制台”前后端设计方案 (The Dashboard)

你们的界面不能像 ChatGPT 那样只有一个对话框。它必须像一个**“操作系统的任务管理器 + 性能监控大屏”**。

1. 前后端技术选型

  - 后端：FastAPI。提供两个核心功能：
      - REST API：接收前端的任务提交。
      - WebSocket：将系统总线（ZMQ）上的底层日志、监控探针数据，实时推送到前端（实现屏幕上的数字疯狂跳动，极具视觉冲击力）。
  - 前端：Vue3 或 React + ECharts (图表库)。
      - 备选降级方案：如果队伍里没人会写前端，直接使用 Python 的 Streamlit 或
        Gradio。虽然定制化稍差，但足够拼凑出一个分栏监控界面。

2. UI 界面布局设计（四象限布局）

整个屏幕划分为深色科技风的四个区域：

  - ↖️ 左上：任务控制台 (Command Terminal)

      - UI 元素：一个类似终端的输入框，用于输入任务指令（如“对比特斯拉与比亚迪财报”）。
      - 核心开关（杀手锏）：在这里放一个极其醒目的 Toggle 开关：[ 纯文本传统模式 ] <---> [ OS底层优化模式
        ]。评委点这个开关对比运行，高下立判。

  - ↗️ 右上：系统总线与 Agent 拓扑流 (System Bus Monitor)

      - UI 元素：动态网络图。
      - 交互：展示 Planner、Retriever、Executor、Summarizer 四个节点。当底层 ZMQ
        总线有消息传递时，节点之间会有光点飞来飞去。
      - 亮点：在这个图的连线上，实时悬浮显示传递的数据大小。
          - 传统模式：连线上显示 Transmission: 2.5 MB。
          - OS 模式：连线上显示 Transmission: 128 Bytes (Pointer only)。

  - ↙️ 左下：实时性能探针看板 (Telemetry & Metrics)

      - UI 元素：四块动态仪表盘 (ECharts) 或数字看板。

    1.  Token 消耗表：累计 Token 消耗走势图（对比 A/B 模式下的断崖式差距）。
    2.  Zero-Copy 拦截率：展示通过共享内存指针避免的序列化字节数。
    3.  L2 Cache (记忆) 命中率：当前任务是否触发了记忆复用（高亮显示 CACHE HIT!）。
    4.  任务延迟时钟：实时的任务执行秒表。

  - ↘️ 右下：CodeAct 与 记忆黑板视窗 (Execution Sandbox & Memory)

      - UI 元素：分 Tab 页的代码编辑器样式。
      - Tab 1 (沙箱)：实时滚动大模型写的 Python 代码，以及终端执行的 stdout 输出（比如正在打印 pandas
        数据清洗过程）。最后弹出一张生成的图片。
      - Tab 2 (共享内存)：以 Hex/矩阵 的形式象征性地展示 /dev/shm 里存的 Embedding
        向量数据（给评委看“非文本状态”确实在内存里）。

3. 前后端联动逻辑（WebSocket 数据流）

为了让前端“动”起来，FastAPI 后端需要开启一个挂载在 ZMQ 总线旁边的监听器，将拦截到的探针数据通过 WebSocket 发给前端：

# FastAPI 后端伪代码 (探针数据推送)
from fastapi import FastAPI, WebSocket
import asyncio

app = FastAPI()

@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # 模拟监听底层总线
    while True:
        # 从 ZMQ 或 Profiler 获取实时数据
        metrics = get_system_metrics() 
        
        payload = {
            "active_agent": "Executor",
            "current_mode": "OS_Mode",
            "tokens_saved": 8500,
            "ipc_payload_size": "85 Bytes",
            "shm_active": True,
            "logs": "Executing CodeAct Sandbox..."
        }
        await websocket.send_json(payload)
        await asyncio.sleep(0.5) # 每半秒刷新前端

总结：为什么这个可视化方案能拿高分？

评委在一天内要看很多个项目，绝大部分项目都是黑框框跑脚本，或者粗糙的 Chat 界面。

如果你们的项目一打开，是一个深色主题、满屏仪表盘、带有微服务拓扑图、代码沙箱在实时滚动、数字在飞速对比计算的“系统控制中心”，并且评委可以亲手点击那个
“切换模式” 的开关，看着 Token 消耗量在 OS 模式下瞬间停止增长（因为触发了 Embedding
剪枝和内存命中），这种视觉和技术上的双重降维打击，将直接锁定胜局。

行动建议： 如果队伍前端能力不强，立刻让一名队员去学习 Streamlit 的 st.columns, st.metric, st.line_chart 和
st.code。用 Python 只需 200 行代码，就能把上述四个象限的仪表盘拼凑出来，性价比极高！
