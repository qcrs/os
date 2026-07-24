# StateBus 双平面深化设计与系统级评审稿



适配赛题：第三届中国研究生操作系统开源创新大赛暨开放原子大赛操作系统专项赛第 9 题“一种面向多智能体协作的低开销通信、状态传递与共享记忆机制”

基础方案：`statebus_architecture_and_implementation_plan.md`

目标定位：StateBus 不是 Agent 聊天框架，而是面向 openEuler 24.03-LTS-SP3 的多 Agent 协作运行时。它把多 Agent 协作拆成两个平面：

- 控制面：强类型控制帧、符号化动作、能力契约、DAG/FSM 调度、容错回滚。
- 数据面：`StateRef` 指针语义、预分配共享内存池、Unix Domain Socket FD 传递、租约和引用计数。

环境解耦声明：

- 当前本地设计/文档环境不等同于 openEuler 24.03-LTS-SP3 评测环境，本文不把当前环境中的 Python、Conda、NsJail、FAISS 版本视为最终约束。
- StateBus 的终态目标对齐 openEuler 24.03-LTS-SP3 的通用 Linux 能力：进程、Unix Domain Socket、`mmap`、POSIX SHM/memfd、SQLite WAL、namespaces、cgroups v2、seccomp-bpf、NsJail。
- 本文所称“零拷贝数据面”严格限定为通用 Linux 宿主机 Host 内存侧的多进程/多沙箱数据共享，不覆盖任何特定 AI 加速卡、设备显存或厂商运行时。

规格样例文件：



后续验证入口。本阶段只作为实现规格索引，不在架构报告阶段执行验证：


``

---

## 1. 针对 Agent 编排控制面与底层数据面的深度质疑、自查与死穴挖掘

### 1.1 控制面 Token 隐性膨胀：路由器如果还靠 LLM，就是披着协议外衣的文本系统

自查：原方案已经提出 Protobuf 和 `StateRef`，但没有规定“谁有权调用 LLM”。如果 Planner 之后的 Router、Critic、Executor 选择都继续把历史自然语言塞回模型，控制面仍会变成 token 黑洞。

曝光：典型坏路径是 `Planner -> Router(LLM) -> Executor(LLM) -> Router(LLM) -> Summarizer(LLM)`，每轮都把 `history` 和工具描述重放。系统调用层面看，`sendmsg(2)` 传输的虽然可能是二进制帧，但帧内字段仍可能携带巨大 `prompt/history`；应用层 telemetry 只统计 `protocol_bytes` 会掩盖真实 LLM token 成本。

破局：控制面必须改成 `Symbolic Action + FSM`。Planner 只在入口把自然语言任务编译成二进制 DAG，后续路由只使用 `ActionType`、`CapabilityItem`、`StepState` 和依赖拓扑，不再调用 LLM。实现机制是 `PlanStep.action in {RETRIEVE, EXECUTE, SUMMARIZE, MEMORY_QUERY}`，调度器用拓扑就绪队列和能力表匹配 Agent。Linux/库机制：`sendmsg(2)/recvmsg(2)` 只传控制帧，Protobuf 做 wire contract，`epoll(7)` 或 `asyncio` 做非阻塞事件循环，token 统计从 LLM usage 和 `text_chars` 双源记录。

### 1.2 能力发现与协议映射：异构 Agent 不做握手，后面所有 Schema 都是假设

自查：原方案有 `HELLO / CAPABILITY`，但没有定义输入输出 Schema 的拦截点，也没有定义异构 Prompt/工具格式如何变成统一契约。

曝光：一个 Agent 输出 `{"query": "...", "topK": 5}`，另一个期望 `{"q": "...", "k": 5}`；一个模型函数调用返回 OpenAI-style tool call，另一个返回 markdown JSON。若运行时直接把文本交给下游，错误会延迟到工具执行阶段，甚至污染共享记忆。

破局：接入必须先完成 `Hello -> CapabilityItem -> SchemaSpec -> ProtocolMapper`。运行时维护标准 Protobuf 契约，Agent 私有格式只能通过 adapter 进入。每个控制帧进入调度器前做 Schema 拦截：必填字段、动作类型、可消费 `StateKind`、是否支持 `prepare/commit`、是否支持 FD passing。核心库：Protobuf 做强类型帧，JSON Schema/Pydantic 做边界校验，`SCM_CREDENTIALS` 可用于 UDS 侧确认对端进程身份，`SO_PEERCRED` 可校验本机 Agent 进程的 uid/pid/gid。

### 1.3 异步非阻塞编排与状态死锁：DAG 并行不是简单 `asyncio.gather`

自查：原方案提出 Scheduler，但没有定义 DAG cycle 检测、就绪队列、StateRef 读写锁和超时取消语义。

曝光：并行分支 A/B 都持有某个 `StateRef` 的读租约，同时等待对方生成的新 `StateRef`；或者 Executor 在沙箱中阻塞，Summarizer 一直等待依赖完成。只用 `asyncio.gather()` 会把局部阻塞扩大成全图阻塞。

破局：编译期做 DAG cycle 检测；运行期用 Kahn 拓扑排序维护 ready queue，只调度入度为 0 的 step。数据面采用单写多读规则：`PREPARING` 阶段申请输出 slot，`RUNNING` 阶段写私有 provisional buffer，`COMMITTING` 后将 `StateRef.read_only=true` 发布给读者。应用层 refcount 不跨 step 持锁，只保留租约 token。Linux/库机制：`eventfd(2)` 可做状态就绪通知，`futex(2)` 支撑用户态锁，`timerfd(2)` 或 `asyncio.wait_for` 做超时，`mmap(2)` 只暴露只读映射给消费者。

### 1.4 动态重规划与事务级回滚：共享内存污染比 Python Exception 更难清

自查：原方案提到 `pending -> active`，但没有把 SHM 状态、SQLite 记忆、FAISS 索引纳入同一事务边界。

曝光：Executor 先写入 SHM，再写 SQLite，最后 FAISS add 崩溃。此时下游 Agent 可能已拿到 `StateRef`，SQLite 可能有 pending 行，FAISS 可能没有向量，重启后状态三分裂。沙箱异常如果只返回 `ERROR`，无法知道该释放哪些 provisional refs。

破局：引入 “2PC for Memory”。`PREPARE`：申请 SHM slot、写 provisional state、SQLite 插入 `pending` 和 outbox；`COMMIT`：校验 checksum、切 `StateRef` 为 immutable、SQLite 改 `active`、Proxy Writer 异步写 FAISS；`ROLLBACK`：释放 provisional refs、SQLite 回滚到 snapshot、outbox 标记 canceled。机制：SQLite `BEGIN IMMEDIATE` + WAL；`memfd_create(2)` + `fcntl(F_ADD_SEALS)` 可防止提交后写入；`madvise(2)` 可回收已取消页；`unlink(2)` 延迟到 refcount 归零。

### 1.5 Hidden State 异构消费：“传了向量”不等于“下游真的能用”

自查：赛题要求支持 embedding、语义向量、隐藏状态特征或其他中间表示。原方案没有回答异构模型不能接收 hidden state 时怎么办。

曝光：Qwen 本地推理引擎的 hidden state 无法直接喂给 OpenAI API；同一维度 embedding 也可能来自不同 encoder，cosine 分数不可比较。若只把向量存在 SHM，再让下游忽略它，它就是摆设向量。

破局：把非文本状态分成三类消费闭环。第一类是 `DENSE_EVIDENCE`：向量只用于检索和 rerank，最终输出 `evidence_ids + short summary`。第二类是 `EMBEDDING`：只在同 encoder family 内做相似检索，`StateRef.meta.encoder_id` 必填。第三类是 `KV_PREFILL/HIDDEN_STATE`：只允许同模型、同 tokenizer、同推理后端消费，能力契约必须声明 `accepted_state_kinds=KV_PREFILL`。机制：dtype/shape/checksum/encoder_id/version 放进 `StateRef`；不兼容时走 adapter，把 hidden state 降级为 evidence summary 或 retrieval handle。

### 1.6 SHM 碎片化与内核墙：频繁 create/unlink 会把 benchmark 做成内存管理压力测试

自查：原方案从 `multiprocessing.shared_memory` 起步，但连续 10 轮复杂任务下，如果每个大张量都 `create/unlink`，会产生物理页分配抖动、页表抖动和 VMA 数量膨胀。

曝光：`shm_open(3)/ftruncate(2)/mmap(2)/munmap(2)/shm_unlink(3)` 高频调用会让 openEuler 24.03 的 Linux 6.6 内核不断处理页表和 tmpfs 对象。大对象释放后未必马上形成可复用连续页，`/proc/<pid>/maps` 和 `smaps` 会显示 VMA 增多，`perf` 中可能出现 page fault 和 TLB miss 上升。

破局：StateBus daemon 启动时预分配固定大小 slab pool：例如 4KB/64KB/1MB/16MB/64MB class，写入只从 free list 分配 slot。大对象用 `memfd_create` 或 `tmpfs` 下 mmap 文件，长寿命对象复用，不在热路径 unlink。机制：`mmap(MAP_SHARED)`、`madvise(MADV_DONTNEED)`、`posix_fallocate(3)`、可选 `mremap(2)`；高端优化可试 `hugetlbfs` 或透明大页，但 MVP 不依赖。

### 1.7 FAISS 并发写冲突：C++ 索引不是 Python dict，不能多进程随便 add

自查：原方案建议单写者后台线程，但需要把它提升成强约束。FAISS FAQ 明确指出 CPU concurrent search 支持，但 concurrent search/add 或 add/add 不支持，需要调用方加锁。

曝光：多个 Agent 进程同时 `index.add_with_ids()`，Python GIL 不能保护 C++ 内部结构。轻则索引和 SQLite id 不一致，重则段错误。并发 add/search 混跑时，索引内部结构修改与查询读取之间没有天然事务边界。

破局：FAISS 只允许 Memory Proxy Writer 单进程持有写句柄。其他 Agent 只能写 SQLite WAL outbox：`memory_events(event_type='faiss_add_pending')`。Proxy Writer 顺序消费 outbox，完成后把 memory 状态从 `pending` 改为 `active`。读路径可以多进程连接 SQLite，但向量检索通过 Proxy RPC 或只读索引快照。机制：SQLite WAL 支持读写并发但仍是单 writer；`flock(2)`/`fcntl(2)` 文件锁保护索引快照替换；FAISS 索引文件用 `rename(2)` 原子发布。

### 1.8 FD 传递泄漏与 in-flight 上限：零拷贝不是无限传句柄

自查：原方案提到 `SCM_RIGHTS`，但没有设计 FD 生命周期。FD 传递失败或接收方不 `close()` 会在高并发下耗尽 `RLIMIT_NOFILE`。

曝光：UNIX domain socket 的 `SCM_RIGHTS` 语义是把 open file description 的引用复制到接收进程 FD table。Linux 会统计 in-flight FD；接收端 ancdata buffer 太小会截断，多余 FD 可能被内核关闭，调试非常困难。

破局：控制面中 `StateRef.fd_slot` 只是 SCM_RIGHTS ancillary fd list 的索引，不把整数 FD 序列化成长期 handle。发送端必须等待 `ACK_RECV_FD` 后才能降低本地引用；接收端必须注册 lease 并在完成后 `close(2)`。机制：`sendmsg(2)/recvmsg(2)` + `SCM_RIGHTS`，`RLIMIT_NOFILE` 压测，`SOCK_SEQPACKET` 保持控制帧边界，`CMSG_SPACE()` 正确分配 ancdata。

### 1.9 NsJail 与共享内存边界：开了 namespace 后，宿主机路径不是天然可见

自查：原方案有 NsJail 命令，但没有说明沙箱如何读取宿主机共享内存，也没有区分命名 FD 和 bind-mounted mmap 文件。

曝光：如果 Agent 在宿主机 `/dev/shm` 创建对象，而沙箱进入新的 mount namespace/chroot，路径名可能不可见。若 `clone_newnet` 没开，CodeAct 代码可能联网；若 seccomp 过严，Python 启动都失败；若过松，沙箱没有意义。

破局：两条路径二选一。低延迟路径是父进程预先通过 `SCM_RIGHTS` 或 NsJail `pass_fd` 把 memfd 注入沙箱，沙箱只 `mmap(PROT_READ)`。可调试路径是在宿主机固定 `/dev/shm/statebus`，通过 NsJail bind mount 到 `/statebus_shm`，只读挂载。机制：`clone_newuser/newns/newpid/newnet`、read-only bind mount、tmpfs `/tmp`、seccomp-bpf/Kafel 白名单、`rlimit_as/cpu/nofile/nproc`。

### 1.10 控制面背压缺失：二进制协议也会被快生产者打爆

自查：原方案没有描述队列长度、超时、重试和降级。高并发下，Retriever 可能产生大量 `StateRef`，Executor 消费速度跟不上。

曝光：UDS send buffer 满后，发送端阻塞；若所有 Agent 都在等待发送 ACK，会形成控制面级死锁。即使使用 gRPC over UDS，也需要理解 HTTP/2 flow control，不是换成 gRPC 就自动解决。

破局：每个 Agent 配额化：`max_inflight_steps`、`max_state_bytes`、`max_fd_inflight`、`max_control_queue_len`。调度器对 ready queue 做 credit-based admission；超过阈值时不再调度新 step，而是让上游进入 `BACKPRESSURE` 状态。机制：`SO_SNDBUF/SO_RCVBUF`、`poll/epoll` 可写事件、gRPC stream flow control、`asyncio.Queue(maxsize=N)`。

### 1.11 Host 内存侧零拷贝边界：不要把系统目标泛化到设备显存

自查：原方案容易把“零拷贝”说成泛化口号。对本赛题而言，StateBus 的创新点应聚焦在通用 Linux Host 内存侧的进程间状态共享，而不是承诺覆盖设备显存、特定硬件运行时或厂商私有统一内存。

曝光：如果文档宣称跨硬件零拷贝，评审会追问不同设备 runtime 的句柄导出、进程上下文、IOMMU、显存一致性和安全边界。这个问题会把赛题从“多 Agent 通信、状态传递、共享记忆机制”带偏到硬件平台适配，增加不可控风险。

破局：本文明确边界：StateBus 零拷贝只指 Host 内存中的 `mmap/MAP_SHARED`、POSIX SHM、memfd、UDS `SCM_RIGHTS` FD 传递和只读映射复用。`StateRef.storage` 只覆盖 `MEMFD/POSIX_SHM/MMAP_FILE/EXTERNAL_URI` 等通用 Linux 存储句柄。任何设备侧拷贝、显存驻留、加速卡 runtime 适配都不进入本阶段设计范围，也不进入核心评测指标。

---

## 2. 检索并融合 GitHub 顶尖开源项目底层设计

### 2.1 LangGraph：StateGraph 的可借鉴点是“编译后执行图”，不是它的应用层状态对象

源码定位：

- `langgraph/graph/state.py`
- 参考链接：https://raw.githubusercontent.com/langchain-ai/langgraph/main/libs/langgraph/langgraph/graph/state.py

关键机制：

- `StateGraph` 是 builder，节点读写共享 state；`compile()` 会 validate graph、准备 channels、attach node/edge/branch，最后产出可执行 `CompiledStateGraph`。
- `checkpointer` 被定义成 fully versioned short-term memory，可用于 pause/resume/replay。
- 状态字段可带 reducer，用于多个节点更新同一 key 时聚合。

StateBus 借鉴：

- 借鉴 `builder -> compile -> executable graph`，但编译结果不能是 Python 对象图，而要是可序列化 `Plan{steps, depends_on}`。
- 借鉴 checkpoint/replay，但 StateBus checkpoint 不能只存逻辑 state，还要存 `StateRef` lease、SQLite txn id、outbox offset。
- 借鉴 branch attach，但路由必须落到 `ActionType` 枚举，不让分支节点反复问 LLM。

### 2.2 OpenAI Swarm：最小 handoff 证明了符号化交接可以很薄

源码定位：

- `swarm/types.py`
- `swarm/core.py`
- 参考链接：https://raw.githubusercontent.com/openai/swarm/main/swarm/types.py
- 参考链接：https://raw.githubusercontent.com/openai/swarm/main/swarm/core.py

关键机制：

- `Agent` 包含 `name/model/instructions/functions/tool_choice/parallel_tool_calls`。
- `Result` 可携带 `value`、`agent`、`context_variables`。
- `handle_function_result()` 如果函数返回 `Agent`，就封装成 `Result(agent=agent)`；`run()` 中如果 `partial_response.agent` 存在，就切换 `active_agent`。

StateBus 借鉴：

- 把 handoff 从自然语言“请你接手”降成 `Result{next_agent, context_delta}` 风格的符号动作。
- StateBus 不照搬 Swarm 的 stateless loop，而是把 handoff 编译成 `PlanStep.owner_agent_id` 变更和 `StepState` 转移。
- Swarm 的函数 schema 可以作为 Capability 的生成入口，但必须由 StateBus runtime 做 Schema 拦截。

### 2.3 MetaGPT：Pub-Sub/SOP 有组织性，但要避免让 LLM 决定每次状态跳转

源码定位：

- `metagpt/environment/base_env.py`
- `metagpt/roles/role.py`
- 参考链接：https://raw.githubusercontent.com/FoundationAgents/MetaGPT/main/metagpt/environment/base_env.py
- 参考链接：https://raw.githubusercontent.com/FoundationAgents/MetaGPT/main/metagpt/roles/role.py

关键机制：

- `Environment.publish_message()` 根据 routing address 把 Message 分发到 Role 的私有 buffer。
- `RoleContext` 有 `msg_buffer/memory/working_memory/state/watch`，Role 通过 `_watch` 订阅关心的 action/message。
- `RoleReactMode` 支持 react、by_order、plan_and_act；`_think` 会让 LLM 在多个 stage 中选状态。

StateBus 借鉴：

- 借鉴“环境承载角色、消息投递到私有队列、Role 只观察订阅消息”的结构。
- SOP 映射成可审计的 `CapabilityItem + PlanStep.action`，而不是 prompt 内的文字 SOP。
- StateBus 不能让 `_think` 每步 LLM 选状态；应该让 Planner 入口编译一次，然后 runtime FSM 确定性流转。

### 2.4 Apache Arrow Plasma / Ray Core：对象存储的本质是 immutable shared object + object ref

资料定位：

- Plasma in-memory object store：https://arrow.apache.org/blog/2017/08/08/plasma-in-memory-object-store/
- Ray serialization/object store：https://docs.ray.io/en/latest/ray-core/objects/serialization.html

关键机制：

- Plasma 把 immutable object 放在 shared memory 中，让多个 client 跨进程 map 同一段内存。
- Ray 对 NumPy array 做 object store read-only sharing，同节点 worker 可 zero-copy read；写入必须 copy。
- Plasma 创建对象分两阶段：create buffer，写完后 seal，使对象不可变并对其他 client 可见。

StateBus 借鉴：

- `StateRef` 等价于轻量 ObjectRef，但要加入 Agent 运行时字段：`kind/dtype/shape/checksum/lease/ref_count/fd_slot`。
- `PREPARE -> COMMIT` 等价于 Plasma create/seal；提交后只读，避免读者看到半写入状态。
- Ray 的 read-only 限制要直接写进 StateBus 契约：消费者不得原地修改共享 tensor；需要修改必须 copy-on-write 生成新 `StateRef`。

### 2.5 gRPC over UDS：适合控制面 RPC，但不要用它搬大张量

资料定位：

- gRPC name syntax：https://github.com/grpc/grpc/blob/master/doc/naming.md

关键机制：

- gRPC 支持 `unix:path` 和 `unix:///absolute_path` 作为 Unix domain socket target。
- UDS 下可以复用 gRPC stream、deadline、status code、backpressure、binary metadata。

StateBus 借鉴：

- 控制面可以提供两种 transport：raw UDS frame 和 gRPC over UDS。评测时 raw UDS 更好统计字节，工程集成时 gRPC 更好接入多语言。
- gRPC 只承载 `ControlFrame` 和 `StateRef`，大对象仍走 memfd/mmap/SCM_RIGHTS。

### 2.6 Google NsJail：隔离要服务于数据面，而不是把 SHM 隔离到不可见

源码定位：

- README：https://raw.githubusercontent.com/google/nsjail/master/README.md
- config.proto：https://raw.githubusercontent.com/google/nsjail/master/config.proto

关键机制：

- NsJail 提供 namespace、chroot/pivot_root、read-only bind mount、tmpfs、rlimit、seccomp-bpf/Kafel、cgroup v1/v2。
- 配置文件是 Protobuf，`MountPt` 支持 bind mount、rw/ro、mandatory；`NsJailConfig` 支持 `pass_fd`、`clone_new*`、`seccomp_string`。

StateBus 借鉴：

- CodeAct Executor 必须在 `clone_newuser/newns/newpid/newnet` 下运行，默认无网络。
- 共享状态只通过受控 bind mount 或 FD 注入暴露给沙箱。
- 沙箱输出只能是 `StepResult` 和可登记的 artifact `StateRef`，不能直接写共享记忆。

---

## 3. 重构后的 StateBus 控制面与数据面双层架构设计

### 3.1 总体边界

```text
                 Control Plane
  +------------------------------------------------+
  | Agent Registry / Capability Table              |
  | Protocol Mapper / Schema Interceptor           |
  | DAG Compiler / FSM Scheduler / 2PC Coordinator |
  | Telemetry / Backpressure / Failure Detector    |
  +-----------------------+------------------------+
                          |
                          | ControlFrame + StateRef only
                          v
                   Data Plane
  +------------------------------------------------+
  | StatePool Daemon                               |
  | memfd/mmap/slab pool/lease/refcount/checksum   |
  | UDS SCM_RIGHTS FD broker                       |
  +-----------------------+------------------------+
                          |
                          v
  +------------------------------------------------+
  | Memory Store                                   |
  | SQLite WAL metadata + outbox + FAISS proxy     |
  +------------------------------------------------+
```

硬边界：

- 控制面不搬运大 payload，只搬 `ControlFrame` 和 `StateRef`。
- 数据面不理解任务语义，只负责对象生命周期、FD/映射、checksum、lease/refcount。
- 共享记忆不是“Agent 随便写数据库”，只能由 Memory Proxy 通过事务写入。

### 3.2 控制面：基于符号化动作和协议状态机

控制面状态机：

```text
REGISTERING
  -> READY
  -> PLANNING
  -> DAG_COMPILED
  -> DISPATCHING
  -> PREPARING_STEP
  -> RUNNING_STEP
  -> PREPARED_STEP
  -> COMMITTING_STEP
  -> COMMITTED_STEP
  -> DONE

RUNNING_STEP -> FAILED_STEP -> ROLLING_BACK -> REPLAN_PENDING -> DISPATCHING
RUNNING_STEP -> TIMEOUT -> ROLLING_BACK -> FAILED_TASK
```

符号动作集合：

- `PLAN`：只允许 Planner 入口使用 LLM，把自然语言目标编译成 DAG。
- `MEMORY_QUERY`：运行时自动插入，查询历史策略/证据。
- `RETRIEVE`：返回 evidence refs，不返回长文本。
- `EXECUTE`：工具或 CodeAct 沙箱执行。
- `SUMMARIZE`：生成短摘要和 memory candidate。
- `MEMORY_COMMIT`：进入 2PC，不由普通 Agent 直接落库。
- `REPLAN`：只在失败、低置信度或依赖缺失时触发；重规划输入是结构化失败帧和 DAG 残图，不是全量自然语言历史。

确定性路由规则：

```text
next_steps = all steps where dependencies are COMMITTED
for step in next_steps:
    candidates = capability_table[action=step.action]
    filter by accepted_state_kinds/input_schema/max_concurrency/labels
    choose least-loaded candidate or configured affinity
    dispatch without LLM
```

异构 Agent 接入：

1. Agent 启动后发送 `Hello`：`agent_id/role/protocol_version/supported_transports/capabilities`。
2. 每个 `CapabilityItem` 声明 `actions/input_schema/output_schema/accepted_state_kinds/produced_state_kinds/supports_prepare_commit/supports_fd_passing`。
3. `ProtocolMapper` 为 Agent 注册 adapter，把私有 JSON/tool-call/markdown 输出转换成标准 `PlanStep` 或 `StepResult`。
4. `SchemaInterceptor` 在帧进入调度器前校验字段和类型，失败直接返回 `Error{retryable=false}`，不污染 DAG。
5. 控制帧统一落 Protobuf `ControlFrame`；调试模式可以镜像 JSON，但 JSON 不是正式 wire contract。

### 3.3 数据面：StateRef 的指针语义和生命周期

`StateRef` 最小语义：

```text
state_id: 逻辑对象 ID，不等于地址/FD
kind: EMBEDDING/HIDDEN_STATE/DENSE_EVIDENCE/TOOL_ARTIFACT/KV_PREFILL
storage: MEMFD/POSIX_SHM/MMAP_FILE/EXTERNAL_URI
handle: 对 StatePool 有意义的 opaque handle
offset/length: 对象在 pool 或文件内的位置
dtype/shape: tensor 解释方式
checksum_sha256: 脏读和错误定位
lease_id/lease_deadline_ns: 生命周期租约
ref_count_hint: 控制面估算的消费者数量
fd_slot: 本次 SCM_RIGHTS ancillary fd list 中的索引
read_only: 提交后必须为 true
```

生命周期：

```text
ALLOCATED
  -> WRITING
  -> PREPARED
  -> SEALED
  -> PUBLISHED
  -> RETAINED_BY_CONSUMER
  -> RELEASED_BY_CONSUMER
  -> GC_ELIGIBLE
  -> RECLAIMED

ALLOCATED/WRITING/PREPARED -> ROLLED_BACK -> RECLAIMED
PUBLISHED -> LEASE_EXPIRED -> QUARANTINED -> RECLAIMED
```

内存安全规则：

- 单写者：一个 `StateRef` 只有创建 step 可写。
- 多读者：提交后所有消费者只读 `mmap(PROT_READ)`。
- 不跨 step 持锁：依赖通过 `StepState.COMMITTED` 触发，不通过持有写锁等待。
- refcount 是应用层逻辑引用，FD 引用由内核维护；两者都归零才回收。
- lease 是兜底回收，不是正常释放路径；lease 过期先隔离，不立即复用，避免慢读者 use-after-free。
- checksum 在提交时计算，在消费者读取前可选校验；大对象可分块 checksum。

### 3.4 共享记忆模型

SQLite 表核心：

```sql
CREATE TABLE memories (
  embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id TEXT NOT NULL UNIQUE,
  source_agent_id TEXT NOT NULL,
  created_at_ns INTEGER NOT NULL,
  task_theme TEXT NOT NULL,
  summary TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  confidence REAL NOT NULL,
  reuse_count INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  parent_memory_id TEXT,
  status TEXT NOT NULL CHECK(status IN ('pending','active','superseded','rejected','deleted')),
  embedding_state_id TEXT,
  evidence_refs_json TEXT,
  checksum TEXT,
  updated_at_ns INTEGER NOT NULL
);

CREATE TABLE memory_embeddings (
  embedding_id INTEGER PRIMARY KEY,
  memory_id TEXT NOT NULL UNIQUE,
  vector_dim INTEGER NOT NULL,
  encoder_id TEXT NOT NULL,
  state_ref_json TEXT,
  faiss_status TEXT NOT NULL CHECK(faiss_status IN ('pending','active','failed')),
  FOREIGN KEY(memory_id) REFERENCES memories(memory_id)
);

CREATE TABLE memory_outbox (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  embedding_id INTEGER NOT NULL,
  op TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','done','canceled','failed')),
  created_at_ns INTEGER NOT NULL
);
```

写入流程：

```text
Summarizer -> MemoryCommit(candidate)
MemoryProxy BEGIN IMMEDIATE
  insert memories(memory_id UUID, status='pending') and get embedding_id
  insert memory_embeddings(embedding_id, faiss_status='pending')
  insert memory_outbox(embedding_id, op='faiss_add')
COMMIT SQLite
Proxy Writer sequentially updates FAISS with int64 embedding_id
MemoryProxy marks memory_embeddings.faiss_status and memories.status as active
```

---

## 4. 核心场景的端到端方案流程

### 4.1 场景 A：复杂任务的异步并行编排与零拷贝状态投递

步骤拓扑：

```text
UserTask
  -> Planner.PLAN
  -> DAG_COMPILED
  -> Runtime.MEMORY_QUERY
  -> Retriever.RETRIEVE ----------------+
  -> Executor.EXECUTE ------------------+-> Summarizer.SUMMARIZE
                                        +-> MemoryProxy.MEMORY_COMMIT
```

详细流程：

1. 用户输入复杂任务，例如“分析 openEuler 上某服务启动慢的根因并给出优化建议”。
2. Planner 只调用一次 LLM，输出二进制 DAG：`Plan{task_id, steps=[retrieve_logs, retrieve_docs, run_probe, summarize]}`。
3. Scheduler 编译 DAG：校验 step id 唯一、依赖存在、无环；为每个 step 绑定 `CapabilityItem`。
4. Runtime 自动插入 `MEMORY_QUERY`，查询是否已有相似任务策略；若低置信度则正常执行原 DAG。
5. `retrieve_logs`、`retrieve_docs`、`run_probe` 入度为 0，可并行进入 ready queue。
6. Retriever 把 embedding/evidence 写入预分配 SHM/memfd pool，提交后返回 `StateRef{kind=DENSE_EVIDENCE, fd_slot=0, checksum, lease}`。
7. Executor 在 NsJail 中运行 CodeAct：父进程通过 UDS `SCM_RIGHTS` 或 `pass_fd` 注入只读 fd；沙箱内 `mmap(PROT_READ)` 读取 evidence，不通过自然语言复制大 payload。
8. 控制面只流转 `StepResult{output_refs=[StateRef...]}`，telemetry 记录 `protocol_bytes/state_bytes/fd_count/task_ms`。
9. Summarizer 消费多个 `StateRef`，生成短摘要、证据链 ID、策略记忆候选。
10. MemoryProxy 执行 2PC：SQLite pending + outbox，FAISS 单写者更新索引，最终 active。
11. 所有消费者 ACK release 后，StatePool refcount 归零；lease 过期对象进入 quarantine，再回收到 slab free list。

失败路径：

```text
Executor.TIMEOUT
  -> Scheduler.Rollback(txn_id)
  -> StatePool.release(provisional_refs)
  -> SQLite.restore(snapshot)
  -> if allow_replan: Planner.REPLAN(structured_error + remaining_dag)
  -> dispatch fallback Executor
```

### 4.2 场景 B：跨任务记忆复用与编排图剪枝

步骤拓扑：

```text
NewTask
  -> Runtime.MEMORY_QUERY
  -> MemoryProxy.FAISS_SEARCH + SQLite_FILTER
  -> ReuseDecision
      -> high_confidence: GraphPruning
      -> low_confidence: Full Planner
  -> Execute pruned DAG
  -> reuse_gain telemetry
```

详细流程：

1. 新任务启动，例如“继续分析另一个服务启动慢问题，但环境相同”。
2. Runtime 在 Planner 前拦截任务主题，构造 `MemoryQuery{task_theme, query_text, tags, top_k, min_confidence}`。
3. MemoryProxy 用同一 encoder 生成 query embedding，FAISS 查 topK，再用 SQLite 过滤 `status=active`、`theme_match`、`confidence`、`recency`。
4. 若命中高置信度策略记忆，返回 `MemoryHit{memory_id, evidence_refs, reusable_steps, confidence}`。
5. GraphPruner 把原始 DAG 中被历史成功路径覆盖的 `PLAN/RETRIEVE` 节点替换成 `REUSE_STATE` 或直接注入 `StateRef`。
6. 调度器跳过重复检索和重复规划，只执行与新输入相关的 `EXECUTE/SUMMARIZE`。
7. Telemetry 显式计算：

```text
reuse_gain.token = 1 - protocol_mode_tokens_with_reuse / protocol_mode_tokens_without_reuse
reuse_gain.latency = 1 - task_ms_with_reuse / task_ms_without_reuse
reuse_gain.steps = pruned_step_count / original_step_count
```

8. 若复用失败或输出验证低置信度，`reuse_count` 不增加，记忆事件写 `reuse_rejected`，后续降权。

---

## 5. 落地级伪代码与核心数据结构定义

### 5.1 Protobuf Schema

完整文件：`zuoye/statebus_specs/statebus.proto`

核心对象：

- `Hello`：Agent 握手，包含角色、协议版本、传输方式、能力列表。
- `CapabilityItem`：动作集合、输入输出 Schema、可消费/生产的状态类型、并发度、是否支持 2PC/FD passing。
- `PlanStep`：符号动作、拓扑依赖、目标能力、输入 `StateRef`、超时、重试、是否允许重规划。
- `StateRef`：可通过 Linux FD 传递的指针语义对象，包含 `fd_slot`、`lease_id`、`checksum`、`dtype/shape`。
- `ControlFrame`：统一控制帧，承载 `Hello/Plan/PlanStep/StepResult/Prepare/Commit/Rollback/MemoryQuery/MemoryCommit`。

后续实现阶段的编译入口：

```bash
protoc --proto_path=zuoye/statebus_specs --python_out=/tmp zuoye/statebus_specs/statebus.proto
```

### 5.2 编排运行时代码

完整文件：`zuoye/statebus_specs/statebus_scheduler.py`

已实现能力：

- Kahn 拓扑排序和 DAG cycle 检测。
- `asyncio.Queue` ready queue + `asyncio.wait(FIRST_COMPLETED)` 异步并行调度。
- `CapabilityItem` 能力绑定和 `ProtocolMapper` 异构参数适配。
- `StatePool` 的 lease/refcount shell。
- `MemoryStore` 的 snapshot/restore/outbox shell。
- step 级 `prepare -> run -> commit` 和异常 rollback。
- 每 Agent `asyncio.Semaphore(max_concurrency)` 控制并发。

后续实现阶段的调度器入口：

```bash
/home/qcrs/.conda/envs/kv_quant/bin/python3 zuoye/statebus_specs/statebus_scheduler.py
```

预期语义：

```json
{"commit": "COMMITTED", "execute": "COMMITTED", "retrieve": "COMMITTED", "summarize": "COMMITTED"}
```

生产化补齐项：

- 把 mock `MemoryStore` 替换成 SQLite WAL + Proxy Writer。
- 把 mock `StatePool` 替换成 memfd/mmap slab pool。
- 把 handler mock 替换成 UDS/gRPC Agent RPC。
- 增加 telemetry hook：`sendmsg_count/recvmsg_count/protocol_bytes/state_bytes/fd_inflight/task_ms/token_usage`。

### 5.3 数据面 FD 传递代码

完整文件：`zuoye/statebus_specs/fd_passing.py`

关键函数：

```python
def send_fd(sock: socket.socket, fd: int, payload: bytes) -> None:
    header = struct.pack("!I", len(payload))
    ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))]
    sock.sendmsg([header, payload], ancillary)


def recv_fd(sock: socket.socket, max_payload: int = 65536) -> tuple[int, bytes]:
    fds = array.array("i")
    msg, ancdata, _flags, _addr = sock.recvmsg(4 + max_payload, socket.CMSG_SPACE(fds.itemsize))
    ...
```

实现细节：

- 优先使用 `os.memfd_create`。
- 当前 Python 构建若没有 `os.memfd_create`，用 `ctypes` 直接走 `syscall(SYS_memfd_create)`。
- 平台仍不支持时降级到 `TemporaryFile`，保证样例可运行。
- 使用 `SOCK_SEQPACKET` socketpair 保持一帧一个消息。

后续实现阶段的 FD 传递入口：

```bash
/home/qcrs/.conda/envs/kv_quant/bin/python3 zuoye/statebus_specs/fd_passing.py
```

预期语义：

```text
{"state_id":"demo","length":15}
zero-copy-state
```

### 5.4 NsJail 配置

完整文件：`zuoye/statebus_specs/nsjail.cfg`

设计点：

- `mode: ONCE`，适合单次 CodeAct 执行。
- `clone_newuser/newns/newpid/newnet/newcgroup` 开启，默认无网络。
- `/opt/statebus_jail` 作为只读 root。
- `/dev/shm/statebus` 只读 bind 到 `/statebus_shm`，用于调试路径；生产优先 FD 注入。
- `/tmp` 是 64MB tmpfs，允许沙箱写临时文件。
- `rlimit_as/cpu/nofile/nproc` 限制资源。
- `seccomp_string` 白名单 Python 最小运行 syscalls，显式拒绝 socket/fork/mount/ptrace。

后续实现阶段的运行形式：

```bash
nsjail --config zuoye/statebus_specs/nsjail.cfg
```

工程注意：

- openEuler 的动态库路径、Python venv、`/opt/statebus_jail` rootfs 需要按部署机实际路径准备。
- 如果 Python 启动触发 seccomp kill，应先用 `strace -f` 在非隔离环境记录 syscall，再最小增补白名单。
- 若采用 FD 注入，NsJail `config.proto` 支持 `pass_fd`；也可以由父进程保持 UDS socket，沙箱内通过已传入 fd 接收 `SCM_RIGHTS`。

### 5.5 评测闭环

后续评测阶段应组织的对照实验：

```bash
python -m statebus.eval --mode text --task-set tasks.yaml --rounds 10 --out runs/text
python -m statebus.eval --mode protocol --task-set tasks.yaml --rounds 10 --out runs/protocol
python -m statebus.eval.compare runs/text runs/protocol --out reports/statebus_ablation.md
```

指标：

- `message_count`
- `text_tokens`
- `text_chars`
- `protocol_bytes`
- `state_ref_count`
- `state_bytes`
- `fd_pass_count`
- `task_ms`
- `memory_query_count`
- `memory_hit_rate`
- `pruned_step_count`
- `reuse_gain.token`
- `reuse_gain.latency`
- `rollback_count`
- `lease_expired_count`

评审表述：

StateBus 的核心创新不是“用了共享内存”，而是把多 Agent 协作的成本模型从“自然语言全文复制”改成“符号控制帧 + 可租约的数据引用”。只要评测能证明 protocol 模式在同任务、同模型、同工具链、同随机种子下减少 token/字符开销、减少重复检索、并在 10 轮连续任务中不泄漏 SHM/FD/SQLite pending 状态，就对齐第 9 题评分项。

---

## 参考资料

- openEuler 24.03 LTS SP3：官方下载页说明该版本基于 Linux Kernel 6.6，https://www.openeuler.org/en/download/archive/detail/?version=openEuler+24.03+LTS+SP3
- LangGraph `StateGraph`：https://raw.githubusercontent.com/langchain-ai/langgraph/main/libs/langgraph/langgraph/graph/state.py
- OpenAI Swarm `Agent/Result`：https://raw.githubusercontent.com/openai/swarm/main/swarm/types.py
- OpenAI Swarm handoff loop：https://raw.githubusercontent.com/openai/swarm/main/swarm/core.py
- MetaGPT Environment/Role：https://raw.githubusercontent.com/FoundationAgents/MetaGPT/main/metagpt/environment/base_env.py
- MetaGPT Role：https://raw.githubusercontent.com/FoundationAgents/MetaGPT/main/metagpt/roles/role.py
- Apache Arrow Plasma：https://arrow.apache.org/blog/2017/08/08/plasma-in-memory-object-store/
- Ray object serialization and zero-copy reads：https://docs.ray.io/en/latest/ray-core/objects/serialization.html
- gRPC name syntax / Unix domain sockets：https://github.com/grpc/grpc/blob/master/doc/naming.md
- NsJail README：https://raw.githubusercontent.com/google/nsjail/master/README.md
- NsJail config proto：https://raw.githubusercontent.com/google/nsjail/master/config.proto
- Python socket `SCM_RIGHTS` docs：https://docs.python.org/3/library/socket.html
- Linux `unix(7)` SCM_RIGHTS：https://man7.org/linux/man-pages/man7/unix.7.html
- SQLite WAL：https://www.sqlite.org/wal.html
- FAISS FAQ concurrency：https://github.com/facebookresearch/faiss/wiki/FAQ
