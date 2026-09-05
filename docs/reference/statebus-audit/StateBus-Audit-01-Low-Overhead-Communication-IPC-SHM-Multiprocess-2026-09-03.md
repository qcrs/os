# StateBus 全面系统审计 · Round 01
# 低开销通信、UDS / Protobuf、SHM / memfd 与多进程执行链深度审计

> **项目**：StateBus / `qcrs/os`  
> **审计日期**：2026-09-03  
> **源码基线**：`qcrs/os` `master`，审计时仓库 HEAD tree 对应当前主线  
> **本轮范围**：通信效率、Control Plane、Data Plane、Unix Domain Socket、Protobuf、Shared Memory、memfd、跨 PID State 消费、多进程 Worker 生命周期  
> **明确不展开**：Semantic Memory 算法、CodeAct Sandbox、外部 Benchmark 公平性、Adaptive Routing、Latent Hidden；这些进入后续独立 Round。  
>
> 本文不是“功能说明”，而是从赛题评分、Linux IPC 语义和当前源码事实出发，对 StateBus 的节点内通信路径进行源码级审计，回答：
>
> 1. 当前所谓“低开销通信”到底由哪些真实机制组成？
> 2. 哪些已经是强实现，应该保留？
> 3. 哪些仍是实验性路径，不能过度 claim？
> 4. 当前有哪些 correctness / lifecycle / integrity / performance 风险？
> 5. 应如何升级为真正适合比赛主线的 `Persistent Typed IPC Runtime`？
> 6. 哪些优化真正对 StateBus 有用，哪些只是为了“技术复杂”而复杂？

---

# 0. Executive Summary

本轮最核心的判断：

> **StateBus 的通信架构方向是正确的：小型 Control Message 走 typed Protobuf + UDS，大型状态不进控制消息，只传 Ref，由 SHM / mmap / memfd / workspace 承载。真正的问题不是“协议选错”，而是执行拓扑和数据面生命周期还没有完全匹配“低开销 Runtime”的目标。**

当前链路可以概括为：

```text
Runtime
   │
   │ small typed message
   ▼
Protobuf
   │
   ▼
AF_UNIX / SOCK_STREAM
   │
   ▼
Worker subprocess
   │
   │ RefHandle
   ▼
State sidecar / registry
   │
   ├── SharedMemory
   ├── mmap file
   ├── memfd
   └── workspace / CAS
```

其中几个设计值得直接保留：

```text
✅ Control Plane / Data Plane 分离
✅ Protobuf typed control message
✅ UDS 节点内通信
✅ RefHandle 不内联大型 payload
✅ task / step / attempt / trace identity
✅ ACK / RUN_START / HEARTBEAT / RESULT 生命周期
✅ SHM 跨 PID actual-use
✅ state hash / lease / contract 验证
✅ StorageKind 分层放置思想
✅ Telemetry 已区分 event / terminal snapshot
```

但当前存在 5 个最值得优先修的问题：

```text
P0-A
普通轻量 state operation 仍然 one-request-one-Python-process
→ fork/exec/import/startup 成本可能远大于 Protobuf/UDS 本身

P0-B
UDS frame length 没有显式 MAX_CONTROL_FRAME_BYTES
→ 本地错误 peer 可声明超大长度，形成阻塞/资源 DoS

P0-C
memfd 没有 MFD_ALLOW_SEALING / file seals
→ hash 后仍可修改，存在 TOCTOU / immutable-state contract 缺口

P0-D
Supervisor 当前按 step_id 存单个 StepRuntimeRecord
→ retry 注册同 step 时覆盖旧 attempt
→ 与“晚到旧 attempt 可独立诊断”的文档语义存在结构性冲突

P0-E
LayeredStateStore 对重复 ref_id 没有 reject / idempotent publish 规则
→ 旧 SHM/memfd handle 可能被覆盖并失去可清理引用
```

以及几个 P1：

```text
P1-A
SharedMemory resolve 为校验 hash 做 bytes(buffer)
→ 明确发生一次 full payload copy

P1-B
memfd consumer 使用单次 os.read(fd, length)
→ POSIX read 不承诺一次返回全部请求长度

P1-C
LayeredStateStore.release() 非幂等
→ 与文档“GC / release idempotent”目标不一致

P1-D
metadata sidecar 直接 write_text
→ 无 atomic temp+fsync+rename commit

P1-E
UDS 未验证 SO_PEERCRED
→ Runtime 只凭 socket endpoint 假定连接的是自己启动的 Worker

P1-F
server thread `except Exception: pass`
→ 真实 transport/deserialize 错误可能被掩盖成 timeout

P1-G
LayeredStateStore 内部 dict / SHM accounting 无同步
→ 一旦 Adaptive Runtime 引入并行 ready steps，存在并发一致性风险

P1-H
`.proto` 与 Python 动态 descriptor 同时维护
→ schema drift 风险
```

最终推荐架构不是换 gRPC、换 Cap'n Proto，也不是立即写 C++ IPC，而是：

# `PersistentWorkerBroker + Typed UDS + Sealed memfd/SHM Data Plane`

```text
                    StateBus Runtime
                           │
                  PersistentWorkerBroker
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
        Worker A       Worker B      Sandbox Worker
       persistent     persistent      ephemeral
             │             │
             └──── UDS typed session ───┘

Control Plane:
  bounded Protobuf frames
  task/step/attempt IDs
  grants / refs / receipts

Data Plane:
  immutable medium state
      → sealed memfd + SCM_RIGHTS

  named reusable shared matrix
      → SHM, controlled lifetime

  larger durable state
      → mmap / CAS

  execution artifact
      → workspace

High-risk CodeAct:
      → ephemeral isolated process/container
```

也就是说：

> **低开销路径与高隔离路径应该分开，而不是所有操作都为隔离付一次 Python process startup。**

---

# 1. 全项目后续审计拆分

为了不把问题混在一起，剩余系统审计建议固定为 6 Round。

| Round | 主题 | 主要问题 |
|---|---|---|
| **01** | **低开销通信 / IPC / SHM / 多进程** | 本文 |
| 02 | Semantic Shared Memory | memory unit、hybrid retrieval、replay compatibility、污染、跨任务复用 |
| 03 | CodeAct | LLM code generation、bounded Python、sandbox、权限、资源限制、artifact commit |
| 04 | Benchmark / Experiment | text vs structured、公平性、统计口径、连续任务、外部 benchmark |
| 05 | Protocol / Capability / Handshake | capability discovery、schema evolution、Grant、版本兼容、fallback |
| 06 | Reliability / Deployment | crash recovery、GC、resource leak、observability、openEuler、10+连续任务 |

Round 01 只回答：

> **“Agent 之间现在到底怎么传？是不是真的低开销？状态有没有真的跨进程？如果要强化，应该改哪里？”**

---

# 2. 赛题为什么把这条链放到最高优先级

赛题“通信效率”单项占：

```text
25 分
```

而状态创新：

```text
20 分
```

说明评审并不只关心：

```text
“你有没有 SHM”
```

更关心：

```text
Structured 模式是否真的比 Text 模式
减少：
token
字符
序列化
解析
重复上下文
端到端时延
```

题面还明确鼓励：

```text
IPC
共享内存
Socket
```

所以 StateBus 当前：

```text
UDS + Protobuf + Shared Memory + typed Ref
```

路线是非常贴题的。

真正需要加强的是：

```text
“这些机制是否组成了一条稳定、低固定成本的 Runtime fast path”
```

而不是继续增加更多 IPC 名词。

---

# 3. 当前通信架构逐层还原

根据源码和实现文档，当前节点内拓扑：

```text
┌──────────────── Runtime Process ──────────────────────┐
│                                                       │
│ Planner / Policy / Dispatcher / Supervisor / State    │
│                                                       │
└───────────────┬───────────────────────────────────────┘
                │
                │ ExecRequest / ACK / Heartbeat / Result
                │ Protobuf
                ▼
        Unix Domain Socket
                │
                ▼
┌──────────────── Worker Process ───────────────────────┐
│                                                       │
│ resolve Ref                                           │
│ execute semantic_select / logit_gate / generic op     │
│ produce Result / receipt                              │
│                                                       │
└───────────────┬───────────────────────────────────────┘
                │
                │ Ref points to payload
                ▼
     ┌─────────────────────────┐
     │ SHM / mmap / memfd      │
     │ workspace / CAS         │
     └─────────────────────────┘
```

这个拆分是正确的：

```text
Control Plane
只传：
identity
action
small params
refs
grant
receipt

Data Plane
承载：
matrix
tensor
artifact
large payload
```

最值得保留的一句话：

> **Ref 是逻辑身份，StorageKind 只是物理放置。**

这与后续 LatentState、DecisionState、MemoryRef 都兼容。

---

# 4. Control Protocol 审计

当前 `.proto` 中已经存在：

```text
ControlHeader
RefHandle
ReusePolicy
ExecRequest
AckReceived
RunStart
Heartbeat
SuccessResult
ErrorResult
CancelCommand
TrapFatal
GarbageCollectCommand
ControlEnvelope
```

`ControlHeader`：

```text
trace_id
task_id
step_id
attempt_id
target_role
timeout_ms
schema_version
event_type
```

这个设计非常正确。

为什么？

因为：

```text
Task
≠
Step
≠
Attempt
```

特别是重试：

```text
same step
new attempt
```

不能被混成一个 identity。

当前 protocol 本身已经表达了这点。

---

# 5. RefHandle 设计是当前通信层最大的优点之一

当前：

```text
ExecRequest
├── state_refs
├── artifact_refs
└── memory_refs
```

而不是：

```text
ExecRequest
└── 直接嵌一个 5MB Evidence / Matrix
```

这非常符合赛题。

理想消息：

```text
REQ_EXEC
task=t
step=s
capability=semantic_select
state_ref=state-abc
manifest=...
grant=...
```

而大型 payload：

```text
state-abc
→ SHM / memfd
```

这种设计本身比：

```text
Agent A:
“这里是我全部中间结果……”
```

更有说服力。

---

# 6. Protobuf 要不要换？

结论：

# 不建议换。

目前的问题不是：

```text
Protobuf 不够快
```

。

对 StateBus 这种：

```text
几百 B ~ 几 KB control frame
```

来说，Python process spawn、state validation、LLM、Tool execution 的成本远大于：

```text
Protobuf encode/decode
```

。

换：

```text
FlatBuffers
Cap'n Proto
gRPC
custom binary
```

会：

```text
增加复杂度
破坏已有 typed contract
降低可维护性
```

却未必改变 E2E。

正确优化顺序：

```text
Process topology
>
Payload copy
>
Lifecycle
>
Serialization micro-optimization
```

。

---

# 7. 但是 Protobuf Schema 有一个维护问题

当前仓库同时存在：

```text
statebus/control/statebus_control.proto
```

和：

```text
statebus/control/schema.py
```

。

后者用：

```python
descriptor_pb2
```

手工重新构造：

```text
相同 enum
相同 message
相同 field number
```

。

这是典型：

# Dual Source of Truth

风险：

```text
.proto 新增 field 17
schema.py 忘记改

或者
schema.py field number 改了
.proto 文档没改
```

。

如果测试没有完整 descriptor equivalence：

```text
两边可能静默漂移
```

。

---

# 8. Schema 推荐修改

推荐最终：

```text
statebus_control.proto
= 唯一 schema source
```

构建时：

```text
protoc / grpcio-tools
→ generated pb2
```

Python dataclass 可以继续存在：

```text
ControlHeader
ExecRequest
...
```

但转换目标使用 generated schema。

如果不想加入 codegen：

至少增加：

```text
test_proto_descriptor_matches_dynamic_schema()
```

比较：

```text
message names
field numbers
field types
oneof
enum values
```

。

优先级：

```text
P1
```

因为当前已经能工作，但长期非常容易埋兼容性问题。

---

# 9. UDS 选择是否合理

合理。

Linux `AF_UNIX` 本来就是：

```text
same-machine IPC
```

支持：

```text
SOCK_STREAM
SOCK_DGRAM
SOCK_SEQPACKET
SCM_RIGHTS FD passing
peer credentials
```

。

当前 StateBus 使用：

```text
AF_UNIX
SOCK_STREAM
```

配：

```text
4-byte big-endian frame length
+
protobuf bytes
```

这是完全正常的工程设计。

不需要为了“更系统”强行换 TCP localhost。

---

# 10. 当前 path shortening 是正确的

Linux：

```text
sockaddr_un.sun_path
```

长度有限。

当前：

```python
effective_unix_socket_path()
```

会：

```text
原 path 能放下
→ 原 path

否则：
sibling hashed path

再否则：
/tmp/statebus-uds-UID/<digest>.sock
```

而且测试覆盖：

```text
overlong path
```

。

这是真实的工程 hardening，不是 toy。

---

# 11. P0：Control Frame 没有最大长度

当前：

```python
header = _recv_exact(sock, 4)

payload_len = int.from_bytes(...)

payload = _recv_exact(sock, payload_len)
```

没有：

```python
if payload_len > MAX_CONTROL_FRAME_BYTES:
    reject
```

。

这意味着 peer 可以发：

```text
FF FF FF FF
```

即声明：

```text
4,294,967,295 bytes
```

。

当前 receiver 会尝试：

```text
不断 recv
直到收满
```

。

如果 peer 不发完：

```text
阻塞直到 socket timeout / connection close
```

如果 peer 真发大量数据：

```text
Python chunks list
+
最终 b"".join()
```

可能消耗大量内存。

---

# 12. 为什么这是 P0 而不是“安全洁癖”

因为 StateBus 的声明是：

```text
Control Plane = small messages
```

那么 Runtime 应该把这个不变量写进代码：

```text
MAX_CONTROL_FRAME_BYTES
```

。

否则：

```text
“控制面永远很小”
```

只是约定，不是 invariant。

---

# 13. 推荐 frame contract

例如：

```text
MAX_CONTROL_FRAME_BYTES = 1 MiB
```

实际正常消息大概率远低于此值。

接收：

```python
payload_len = ...

if payload_len <= 0:
    raise InvalidFrame

if payload_len > MAX_CONTROL_FRAME_BYTES:
    raise OversizedControlFrame
```

还应该限制：

```text
MAX_REFS_PER_REQUEST
MAX_ERROR_DETAIL_BYTES
MAX_STRING_FIELD_BYTES
```

防止：

```text
一个 message 合法 protobuf
但塞 100 万个 Ref
```

。

---

# 14. SOCK_SEQPACKET 要不要换？

Linux `SOCK_SEQPACKET` 可以：

```text
保持 message boundary
可靠
有序
connection-oriented
```

理论上可以免除：

```text
自定义 4-byte framing
```

。

但是当前不建议换。

原因：

```text
现有 framing 很简单
已有测试
SOCK_STREAM 可移植性更好
SCM_RIGHTS 也支持
```

。

当前真正缺的是：

```text
bounded frame
```

，不是：

```text
message boundary API
```

。

所以：

```text
SOCK_SEQPACKET
= optional micro-optimization
不是 P0
```

。

---

# 15. 当前最大的性能结构问题：one request = one subprocess

`SubprocessExecutorTransport.exchange_sequence()` 每次：

```text
1. 创建 UDS server
2. 起 Python thread
3. subprocess.Popen(
     python -m statebus.control.subprocess_worker
   )
4. Python interpreter startup
5. import StateBus modules
6. Worker connect
7. 收一个 ExecRequest
8. ACK
9. RUN_START
10. HEARTBEAT
11. Result
12. Worker exit
13. wait / cleanup
```

。

这意味着：

> **你虽然把单条通信从“大文本”优化成了“几百字节 Protobuf”，但每条 lightweight runtime operation 仍可能支付一次完整 Python process startup。**

对：

```text
semantic_select
logit_gate
small state routing
```

这非常不划算。

---

# 16. 为什么这会直接影响比赛的“低开销通信”叙事

如果 baseline：

```text
Text
→ same resident process
```

而 Structured：

```text
Protobuf
→ spawn Python process
→ UDS
```

最终可能出现：

```text
wire bytes 大幅下降
但 E2E latency 没下降
甚至上升
```

。

评审会问：

> 既然是低开销 Runtime，为什么每个 Agent 状态操作都重新拉一个 Python 进程？

这是必须提前解决的。

---

# 17. 不是所有 Worker 都应该 persistent

另一个极端也不对：

```text
所有东西都常驻
```

。

例如：

```text
CodeAct untrusted Python
```

就值得：

```text
ephemeral isolated process/container
```

。

所以真正应该区分：

```text
Fast trusted state operations
vs
High-risk execution
```

。

---

# 18. 推荐 Process Isolation Mode

增加：

```text
WorkerIsolationMode

PERSISTENT
EPHEMERAL
SANDBOXED
```

。

### PERSISTENT

用于：

```text
semantic_select
Decision gate
small transforms
trusted deterministic worker
```

。

### EPHEMERAL

用于：

```text
rare high-isolation operation
diagnostic worker
```

。

### SANDBOXED

用于：

```text
CodeAct
untrusted generated code
```

。

---

# 19. 推荐 `PersistentWorkerBroker`

目标：

```text
Runtime 启动
↓
WorkerBroker
↓
预启动少量 Worker
↓
一次 UDS handshake
↓
持续处理多个 ExecRequest
```

。

结构：

```text
Runtime
  │
  ├─ Worker-Selector
  │     persistent
  │
  ├─ Worker-Decision
  │     persistent
  │
  └─ Worker-Sandbox
        ephemeral
```

。

这样：

```text
进程启动固定成本
```

从：

```text
per request
```

降为：

```text
per worker lifetime
```

。

---

# 20. Persistent Worker 不等于取消 attempt identity

Connection：

```text
长期存在
```

但每个 request 仍带：

```text
task_id
step_id
attempt_id
trace_id
grant
```

所以：

```text
Worker process lifetime
≠
Step attempt lifetime
```

。

这是非常重要的分层。

---

# 21. Persistent Worker 需要增加什么

第一版：

```text
HELLO / WORKER_READY
```

建立：

```text
worker_id
pid
uid
supported_operations
protocol_version
capability_digest
```

然后：

```text
ExecRequest #1
Result #1

ExecRequest #2
Result #2
...
```

。

后续才考虑：

```text
multiplex multiple in-flight attempts
```

。

第一版甚至可以：

```text
一个 worker connection 串行处理
```

先把 spawn cost 去掉。

---

# 22. UDS Peer 身份目前没有显式验证

当前 Runtime：

```text
bind socket
listen
spawn worker
accept first connection
```

但 `accept()` 后没有：

```text
SO_PEERCRED
```

检查。

Linux `SO_PEERCRED` 可以得到连接 peer 的：

```text
PID
UID
GID
```

。

因此 Runtime 可以验证：

```text
peer pid == spawned worker pid
peer uid == runtime uid
```

。

---

# 23. 为什么这对 StateBus 有价值

因为 StateBus 已经非常强调：

```text
producer_pid
consumer_pid
actual-use receipt
```

那么：

```text
PID
```

不应该只来自 peer 自己在 Result 里声称。

更强的是：

```text
Kernel says:
this socket peer PID = X
```

然后再交叉验证：

```text
SuccessResult.consumer_pid == X
```

。

这会让：

# Cross-PID Actual Use Proof

可信度更高。

---

# 24. UDS pathname permission 也应 harden

当前：

```python
socket_path.parent.mkdir(..., mode=0o700)
```

这在：

```text
目录第一次创建
```

时很好。

但是：

```text
目录已经存在
```

时 `mode=0o700` 不会自动把它 chmod 成 0700。

socket 本身权限也依赖：

```text
umask
```

。

推荐：

```text
verify owner uid
chmod directory 0700
chmod socket 0600
```

或者至少 fail closed：

```text
if directory owner != runtime uid:
    reject
```

。

---

# 25. `except Exception: pass` 是不应该存在的

当前 UDS server thread：

```python
except Exception:
    pass
```

。

这会把：

```text
protobuf decode error
broken invariant
unexpected internal exception
```

都吞掉。

主线程最终只看到：

```text
没有 terminal result
→ subprocess_timeout
```

。

这让：

```text
真实 bug
```

伪装成：

```text
timeout
```

。

---

# 26. 推荐 transport error channel

server thread 应捕获：

```text
exception class
message
phase
```

写入：

```text
thread-safe result/error slot
```

主线程 join 后：

```text
如果 server error:
→ ErrorResult(
    error_code="transport_server_failure",
    phase=...
  )
```

并 Telemetry：

```text
CONTROL_TRANSPORT_FAILED
```

。

不要 silent pass。

---

# 27. 当前 memfd 机制到底是什么

当前：

```text
LayeredStateStore
→ os.memfd_create
→ ftruncate
→ write payload
→ fd 保存在 Runtime
```

当启动 subprocess：

```text
pass_fds=(fd,)
```

然后：

```text
RefHandle
state-id
```

重写成：

```text
memfd_fd:<fd>:<length>:<state_id>
```

子进程继承该 fd。

这个 mechanism proof 是成立的。

---

# 28. 但是当前 memfd 不是“正式 Dense Semantic 主链”

源码 policy 已经明确：

```text
DENSE_SEMANTIC_STATE
在 memfd mode 下仍优先：
SHARED_MEMORY
→ MMAP
```

原因注释也写：

```text
dense semantic state
需要另一个 PID 通过 registry resolver 消费
所以保留 named backend
```

。

因此：

> **当前 formal SemanticState 的真实跨 PID 主链主要还是 SharedMemory，不是 memfd。**

memfd E2E test 目前证明：

```text
FD 能通过 subprocess inheritance 到达 worker
```

但不是证明：

```text
formal semantic selector 已通过 memfd 零拷贝消费 matrix
```

。

文档 / Demo claim 要区分。

---

# 29. P0：memfd 当前没有 sealing

当前：

```python
flags = MFD_CLOEXEC
os.memfd_create(name, flags=flags)
```

没有：

```text
MFD_ALLOW_SEALING
```

。

也没有：

```text
F_SEAL_WRITE
F_SEAL_GROW
F_SEAL_SHRINK
F_SEAL_SEAL
```

。

Linux 官方 memfd 设计里：

```text
file sealing
```

正是用来解决 shared-memory payload 在消费者使用过程中被修改的 TOCTOU 风险。

---

# 30. 为什么 hash 不足以替代 seal

当前：

```text
Producer:
write payload
hash payload
publish contract
```

如果之后某个持 fd 的 process：

```text
修改 payload
```

Consumer：

```text
hash verify
```

可以发现。

但是：

```text
verify
↓
开始读取 / compute
↓
另一个 peer 再修改
```

仍有：

```text
TOCTOU
```

。

如果用 sealed memfd：

```text
write
↓
seal
↓
publish
```

Kernel 保证：

```text
之后不能修改
不能 grow
不能 shrink
```

Consumer 可以安全 mmap read-only。

---

# 31. 推荐 sealed memfd publish

Linux 路径：

```text
memfd_create(
    name,
    MFD_CLOEXEC | MFD_ALLOW_SEALING
)

ftruncate
write_all
fsync not required for RAM semantics
lseek

fcntl(
  F_ADD_SEALS,
  F_SEAL_WRITE |
  F_SEAL_GROW |
  F_SEAL_SHRINK |
  F_SEAL_SEAL
)
```

Consumer：

```text
F_GET_SEALS
```

验证 expected seal set。

---

# 32. Persistent Worker 下 pass_fds 不够用了

当前：

```text
Popen(pass_fds=...)
```

只适合：

```text
创建子进程时
把 FD 一次性继承进去
```

。

如果 Worker 已经 persistent：

```text
新的 state fd
```

无法通过：

```text
pass_fds
```

动态注入。

所以需要：

# `SCM_RIGHTS`

Linux AF_UNIX 原生支持：

```text
sendmsg()
ancillary data
SCM_RIGHTS
```

把 open FD 复制到另一个进程。

---

# 33. 推荐 StateBus 的 memfd 正式模型

```text
Producer / StateStore
     ↓
sealed memfd
     ↓
StateRef:
logical identity
hash
size
contract

Dispatch
     ↓
UDS Protobuf control frame
+
SCM_RIGHTS(fd)
     ↓
Persistent Worker
     ↓
mmap(PROT_READ)
     ↓
verify seals / hash / contract
     ↓
actual use
```

这会比：

```text
SHM name
→ sidecar
→ open by global name
```

更 capability-like。

因为：

```text
拥有 fd
```

本身就是 Linux 内核对象能力。

---

# 34. SHM 仍然有存在价值

不要变成：

```text
memfd 好
所以删 SHM
```

。

SHM 更适合：

```text
多个已知 Consumer
反复打开同一 matrix
producer 生命周期独立
```

例如：

```text
Semantic candidate matrix
多个角色读
```

。

memfd 更适合：

```text
immutable bounded state
point-to-point / few-consumer handoff
```

。

---

# 35. 推荐物理载体策略 v2

```text
Tiny metadata
< few KB
→ INLINE / Protobuf fields

Immutable medium tensor/state
few KB ~ few MB
→ sealed memfd + SCM_RIGHTS

Shared reusable dense matrix
→ SHM read-only-by-contract

Large local durable object
→ mmap / CAS

Execution artifact
→ workspace

Very large future neural state
→ benchmark before choosing backend
```

不要用一个统一 threshold 粗暴决定全部对象。

应该结合：

```text
size
mutability
consumer_count
lifetime
persistence
```

。

---

# 36. P1：SharedMemory resolve 不是严格 zero-copy

当前 `resolve_dense_semantic_state()`：

```python
buffer = shared.buf[...]

payload = bytes(buffer)

sha256_digest(payload)
```

然后：

```python
np.ndarray(
    ...,
    buffer=buffer
)
```

所以计算本身：

```text
NumPy matrix
```

确实直接 view SHM。

但是完整消费过程存在：

```text
SHM
→ Python bytes full copy
```

用于 hash。

所以不能说：

```text
end-to-end zero-copy
```

。

更准确：

```text
zero-copy compute view
+
one full integrity-validation copy
```

。

---

# 37. 如何去掉 hash copy

Python `hashlib` 能接受 buffer protocol。

增加：

```python
def sha256_byteslike(buf: Buffer) -> str:
    h = hashlib.sha256()
    h.update(buf)
    return ...
```

于是：

```text
memoryview
→ hashlib
```

不会先构造同尺寸 `bytes`。

注意：

```text
仍然要扫一遍内存
```

因为 SHA256 必须读取 payload。

只是避免：

```text
额外 allocation + memcpy
```

。

---

# 38. 当前 Semantic consumer 还有多个 full-memory pass

resolve：

```text
Pass 1:
SHA256

Pass 2:
np.isfinite(matrix).all()

Pass 3:
np.linalg.norm(matrix, axis=1)
```

之后 selection：

```text
Pass 4:
matrix[1:] @ matrix[0]
```

。

对小 matrix 无所谓。

但如果未来：

```text
10000 candidates × 4096 dims
```

验证本身会很贵。

---

# 39. 怎样降低 validation overhead

不能简单删检查。

正确：

### Producer commit-time

验证：

```text
finite
normalized
shape
```

然后发布：

```text
immutable sealed payload
+
validation receipt
```

。

### Consumer

验证：

```text
seal
hash
contract
lease
producer receipt hash
```

如果 payload 在发布后 kernel-guaranteed immutable：

```text
不必每个 Consumer 重做全部 finite/norm scan
```

。

这又是 sealed memfd 的系统价值：

> 它不只是数据传输优化，也能降低重复 validation。

---

# 40. Named SHM 的问题在于它仍然是 mutable shared region

SharedMemory：

```text
Consumer A
Producer
其他拥有 name/权限的 process
```

理论上都可能打开。

当前 StateBus：

```text
Consumer NumPy view
flags.writeable = False
```

只限制：

```text
这个 Python ndarray view
```

并不能把底层 POSIX SHM 变成：

```text
kernel immutable
```

。

因此 SharedMemory 路径需要保留：

```text
consumer hash verification
```

或者：

```text
copy-on-resolve
```

才能在不完全信任 peer 时安全。

---

# 41. P1：Python SharedMemory resource tracker 使用方式需要更新

当前 subprocess consumer 有：

```python
resource_tracker.unregister(shared._name, "shared_memory")
```

这是：

```text
private implementation API
```

。

Python 3.13 已正式提供：

```python
SharedMemory(..., track=False)
```

来解决：

```text
subprocess / independently-started process
拥有独立 resource tracker
其中一个退出时提前 unlink
```

的问题。

---

# 42. 为什么这件事与你当前拓扑高度相关

你当前：

```text
Runtime
→ subprocess.Popen
→ independent Python interpreter
```

并不是：

```text
multiprocessing common ancestor
```

统一管理的 SharedMemory graph。

Python 官方已经明确：

```text
subprocess 或 standalone Python
如果已有其他进程负责生命周期
应考虑 track=False
```

。

所以：

### Python >=3.13

使用：

```python
SharedMemory(name=name, track=False)
```

。

### Python <3.13

封装 compatibility adapter：

```text
不要在业务逻辑里散落
resource_tracker.unregister(...)
```

。

---

# 43. P1：memfd read 使用单次 `os.read`

当前 worker：

```python
data = os.read(fd, length)
```

。

虽然对 memfd regular-file 场景经常一次读满，但 API 不应该依赖这个假设。

已有 Producer 写入其实使用了：

```text
_write_all()
```

循环写。

读取也应该：

```text
_read_exact_fd(fd, length)
```

或者更好：

```text
mmap(fd, length, ACCESS_READ)
```

。

---

# 44. `LayeredStateStore.load()` 同样有这个问题

MEMFD：

```python
return os.read(fd, handle.size_bytes)
```

也应改。

这是：

```text
latent correctness bug
```

而不是只是 micro optimization。

---

# 45. P0：重复 `ref_id` publish 可能泄漏旧资源

当前：

```python
handle = self._materialize(...)
self.materializations[ref_id] = handle
```

没有：

```text
if ref_id already exists:
    reject
```

。

SHM path `_shared_segments[ref_id]` 也会被新对象覆盖。

例如：

```text
publish("state-1", payload A)
→ shm_A

publish("state-1", payload B)
→ shm_B
→ dict 里只剩 B
```

此时：

```text
shm_A handle
```

可能失去可追踪引用，直到进程退出/resource tracker。

---

# 46. 正确的 Ref Identity 规则

StateBus 本来就是：

```text
immutable state identity
```

所以第一原则：

```text
同一个 ref_id
绝不能悄悄指向不同 payload
```

。

建议：

```python
if ref_id exists:
    if existing.blob_hash == new_hash
       and contract equal:
        return existing   # idempotent publication
    else:
        raise DuplicateRefConflict
```

。

这个修改同时提高：

```text
correctness
lifecycle
replay determinism
```

。

---

# 47. P1：release() 当前不是幂等

当前：

```python
handle = self.materializations.pop(ref_id)
```

第二次：

```text
KeyError
```

。

但文档声称：

```text
GC / cleanup idempotent
```

。

应改：

```python
handle = self.materializations.pop(ref_id, None)

if handle is None:
    return ReleaseReceipt(
       already_released=True
    )
```

。

---

# 48. 为什么 release 幂等很重要

在真实多进程 Runtime：

```text
normal result
→ release

timeout handler
→ release

finally block
→ release

GC replay
→ release
```

重复清理非常正常。

如果：

```text
第二次 release
本身报错
```

会让 recovery path 变复杂。

所以 lifecycle API 必须：

```text
idempotent by contract
```

。

---

# 49. P1：metadata sidecar 不是 atomic commit

当前：

```python
metadata_path.write_text(...)
```

。

如果 process：

```text
写到一半
→ crash / kill -9
```

Consumer 可能看到：

```text
partial JSON
```

。

当前 resolve 会：

```text
json decode failed
→ corrupt
```

虽然 fail-closed，但仍可能留下 orphan payload。

---

# 50. 推荐 Atomic Sidecar Commit

```text
payload materialize
↓
hash
↓
write metadata.tmp
↓
flush
↓
fsync(tmp)
↓
rename(tmp, metadata.json)
↓
fsync(metadata dir)
↓
publish visible
```

。

消费者：

```text
只认最终 metadata.json
```

。

如果 crash 在 rename 前：

```text
state never committed
```

。

GC 可以回收：

```text
orphan payload / *.tmp
```

。

---

# 51. StateStore 并发安全目前没有明确保障

当前：

```text
materializations dict
_shared_segments dict
_memfd_fds dict
shared_memory_bytes_used
```

全部无 lock。

如果 Runtime 永远：

```text
单线程 sequential
```

问题不大。

但你已经规划：

```text
Adaptive DAG
multiple ready steps
future persistent workers
```

很可能并发：

```text
publish
release
fallback
```

。

---

# 52. 典型 race

```text
Thread A:
shared_memory_bytes_used = 60MB
decide new 8MB
→ fallback

Thread B:
同时 release 32MB
```

或者：

```text
A release ref-X

B get/load ref-X
```

。

如果没有明确状态机：

```text
行为不确定
```

。

---

# 53. 推荐 `StateLeaseRegistry`

不要只在 `LayeredStateStore` 一个 dict 里解决全部生命周期。

建议逻辑层：

```text
StateLeaseRegistry
```

记录：

```text
ref_id
publication_state
storage_handle
producer
allowed consumers
open_consumer_count
lease_expiry
released
```

锁粒度可以非常简单：

```text
RLock
```

第一版足够。

---

# 54. Store 只负责物理载体

未来职责：

```text
StateLeaseRegistry
    logical lifecycle

LayeredStateStore
    materialization backend
```

。

这样：

```text
Ref state machine
```

不会和：

```text
SHM/mmap implementation
```

耦在一起。

这对 LatentState 很有帮助。

---

# 55. Supervisor 的 Attempt 模型存在结构性不一致

这是本轮最值得重视的 correctness seam 之一。

当前：

```python
class RuntimeSupervisor:
    steps: dict[str, StepRuntimeRecord]
```

key：

```text
step_id
```

。

`register()`：

```python
self.steps[step_id] = record
```

。

所以：

```text
step-1 attempt-1
```

注册后：

```text
steps["step-1"] = attempt-1
```

重试：

```text
step-1 attempt-2
```

：

```text
steps["step-1"] = attempt-2
```

旧 attempt-1 从 Supervisor 中消失。

---

# 56. 但是 Session 层其实已经有正确的 Attempt Ledger

`RuntimeTaskSession`：

```text
attempt_records: tuple[StepAttemptRecord, ...]
```

`append_attempt_record()`：

```text
不断 append
```

`update_attempt_record(attempt_id=...)`：

```text
按 attempt_id 更新
```

。

这说明：

> **作者已经意识到 Attempt 必须是一等对象。**

问题是：

```text
Session ledger
```

和：

```text
Supervisor active state
```

的 key model 不一致。

---

# 57. 为什么这不应该直接断言为“现在必然 crash 的 Bug”

如果 driver 当前严格保证：

```text
旧 attempt 彻底结束 / GC
之后
才 register new attempt
```

那么大部分 happy path 没问题。

所以当前更准确的判断：

# P0 architecture/correctness gap

而不是：

```text
已证明会复现的数据 corruption bug
```

。

但是文档已经声明：

```text
旧 Worker 的晚到结果进入诊断记录
```

如果真的允许：

```text
attempt-1 late result
和
attempt-2 active
```

同时存在，那么单 `steps[step_id]` 模型不够。

---

# 58. 正确 Supervisor key

建议：

```text
AttemptKey(
    task_id,
    step_id,
    attempt_id
)
```

。

结构：

```text
attempts: dict[AttemptKey, StepRuntimeRecord]

active_attempt_by_step:
    dict[(task_id, step_id), attempt_id]
```

。

这样：

```text
attempt-1
late result
```

可以：

```text
写 diagnostic
但不能覆盖 active attempt-2
```

。

---

# 59. 必须增加的 Retry / Late Result Test

测试：

```text
register step S attempt A1
dispatch A1
run A1

A1 heartbeat timeout
trap A1

register step S attempt A2
dispatch/run A2

然后模拟：
A1 late SUCCESS
```

必须证明：

```text
A2 state 不变
A1 late result 标记 stale
A1 artifact 不 commit
A1 resource 可以 GC
```

。

当前已有 session test 只覆盖：

```text
一个 attempt
```

没有这个场景。

---

# 60. Current tests 证明了什么

当前测试已经不错地证明：

```text
Protobuf round trip
typed refs preserved

UDS overlong path handling

memfd pass_fds E2E

subprocess valid/invalid request

utf8_text carrier

SHM preferred under budget

SHM → mmap fallback

memfd fallback

orphan SHM finalizer cleanup

run_smoke teardown
```

这些是：

# Functional Correctness Tests

。

---

# 61. 当前测试没有证明什么

仍缺：

```text
frame oversize rejection

UDS peer credential

duplicate ref publication

idempotent release

memfd seals

payload tamper-after-publish

short read

atomic metadata crash

concurrent publish/release

persistent worker repeated requests

worker crash + reconnect

late result vs new attempt

socket hijack

SHM resource_tracker subprocess race

no leaked:
  /dev/shm
  memfd
  socket path
  child process
```

。

这些才是：

# Systems Runtime Tests

。

---

# 62. 通信 Benchmark 现在的计量基础其实已经存在

`ExecutorTransportAudit` 有：

```text
carrier
backend

driver_pid
worker_pid

request_frame_count
response_frame_count

request_wire_bytes
response_wire_bytes
total_wire_bytes
```

。

这很好。

说明你已经可以做：

```text
protobuf
vs
utf8 text
```

wire-level comparison。

---

# 63. 但是当前 transport A/B 不能直接等价为比赛 Text vs Structured

`_default_text_exec_handoff()` 当前示例本质是：

```text
StateBus matched pure-text executor handoff.
Trace...
Task...
...
No inline evidence was supplied...
```

。

它适合：

```text
transport codec test
```

不等于：

```text
真实 Text-MAS baseline
```

。

比赛正式 A/B 必须保证：

```text
相同语义内容
相同任务
相同模型
相同工具
```

。

这部分在 Round 04 Benchmark Audit 再详细拆。

---

# 64. 但本轮应该补 IPC Microbenchmark

与完整 LLM benchmark 分开。

### Benchmark IPC-1：Control RTT

```text
payload:
256B
1KB
4KB
16KB

mode:
loopback
ephemeral subprocess
persistent subprocess
```

指标：

```text
p50
p95
p99

encode_ns
connect_ns
spawn_ns
first_ack_ns
round_trip_ns
```

。

---

# 65. Benchmark IPC-2：Process Startup Cost

单独测：

```text
python -m statebus.control.subprocess_worker
```

：

```text
cold start
warm filesystem cache
```

100 次。

比较：

```text
ephemeral
persistent
```

。

这能直接回答：

> Structured 模式时延为什么可能没降？

---

# 66. Benchmark IPC-3：State Transfer

Payload：

```text
4 KiB
64 KiB
512 KiB
8 MiB
64 MiB
```

载体：

```text
SharedMemory

sealed memfd + SCM_RIGHTS

mmap
```

指标：

```text
publish latency

handoff latency

map/open latency

validation latency

compute access latency

release latency

RSS delta

copy bytes estimate
```

。

---

# 67. Benchmark IPC-4：连续 1000 次 lightweight operation

例如：

```text
Decision Gate
```

不调用 LLM。

比较：

```text
spawn-per-request
vs
persistent worker
```

。

如果 persistent 没有明显收益：

```text
说明优化没必要
```

。

不要凭感觉提交大重构。

---

# 68. Benchmark IPC-5：资源泄漏

执行：

```text
1000 publish
1000 consume
1000 release
```

期间随机：

```text
kill worker
timeout
cancel
duplicate GC
```

最后检查：

```text
/dev/shm
/proc/<pid>/fd
socket directory
state metadata tmp
child processes
```

。

目标：

```text
0 leaked resources
```

。

这对系统完整性非常有价值。

---

# 69. 一个很值得考虑的 openEuler-specific Future Backend

openEuler 24.03 LTS SP3 官方 Release Notes 当前明确列出：

```text
Cross-process zero-copy data transfer
```

基于 Linux 6.6，允许：

```text
把源进程虚拟内存关联页面
直接映射到目的进程虚拟地址空间
```

并支持：

```text
PTE 小页
PMD 大页
```

。

内核实现相关工作名：

```text
PAGEATTACH / zcopy
```

。

---

# 70. 为什么这个方向对比赛很有吸引力

题目要求：

```text
openEuler 24.03-LTS-SP3
```

又鼓励：

```text
IPC / shared memory
```

。

如果后续可以做一个 optional backend：

```text
StorageKind.OPENEULER_PAGEATTACH
```

用于：

```text
large immutable local tensor
```

可以形成非常强的：

# openEuler-native System Optimization

而不是简单在 openEuler 上跑 Python。

---

# 71. 但 PAGEATTACH 现在绝对不是 P0

原因：

```text
需要确认：
kernel config
user-space API
权限
部署环境真实可用性
Python binding
兼容 fallback
```

。

如果为了这个功能破坏：

```text
portable SHM/memfd path
```

不值得。

推荐：

```text
P2 Experimental Backend
```

前提：

```text
standard persistent UDS + memfd/SHM
已经稳定
```

。

---

# 72. 为什么不推荐现在上 io_uring IPC

io_uring 很强，但当前：

```text
control message 极小
worker operation 很粗粒度
```

真正瓶颈更可能：

```text
process startup
LLM
hash
state scan
```

而不是：

```text
send/recv syscall
```

。

只有 profiling 证明：

```text
UDS syscall / context switch
真的成为瓶颈
```

再考虑。

---

# 73. 为什么不推荐现在做 eBPF IPC

同理。

eBPF 很适合：

```text
observability
policy
networking
```

但用来传 Agent state：

```text
不自然
```

。

可以 future：

```text
用 eBPF trace UDS / scheduling / process latency
```

而不是：

```text
把控制面搬进 eBPF
```

。

---

# 74. 为什么不推荐 Redis / message queue 作为节点内 fast path

当前：

```text
single container
same host
```

。

为了 Agent 本机通信再引入：

```text
Redis
NATS
Kafka
```

会增加：

```text
daemon
serialization
socket hop
deployment
```

。

它们适合：

```text
distributed / durable messaging
```

不是当前低开销节点内 fast path。

---

# 75. 推荐的目标架构 v2

```text
┌──────────────────────────── StateBus Runtime ─────────────────────────┐
│                                                                       │
│ Planner / AdaptiveRuntime / Policy / Supervisor / StateLeaseRegistry │
│                                                                       │
│                    PersistentWorkerBroker                             │
└─────────────┬─────────────────────┬───────────────────────────────────┘
              │                     │
     typed Protobuf / UDS      typed Protobuf / UDS
              │                     │
              ▼                     ▼
     ┌────────────────┐     ┌─────────────────┐
     │ State Worker   │     │ Decision Worker │
     │ persistent     │     │ persistent      │
     └───────┬────────┘     └────────┬────────┘
             │                       │
             │ SCM_RIGHTS            │ SHM / small state
             ▼                       ▼
        sealed memfd              StateStore
             │
             ▼
       read-only mmap


                    High-risk execution
                           │
                           ▼
               ┌─────────────────────┐
               │ CodeAct Sandbox     │
               │ ephemeral / jailed  │
               └─────────────────────┘
```

---

# 76. Control Plane Contract v2

保持：

```text
ControlHeader
ExecRequest
Result
Heartbeat
Cancel
GC
```

增加 runtime invariants：

```text
max frame size

protocol compatibility

peer pid / uid

worker instance id

connection generation

request sequence id

attempt identity
```

。

Persistent connection 时：

```text
request_sequence
```

很重要。

---

# 77. Data Plane Contract v2

统一抽象：

```text
StateMaterializationDescriptor
```

：

```text
storage_kind
size
hash
immutability
consumer_count_hint
lifetime
```

但具体打开信息：

```text
SHM name
mmap path
FD
```

不应该全部塞在公共逻辑 Ref。

---

# 78. 推荐 Physical Handle 分离

逻辑：

```text
LatentStateRef
SemanticStateRef
DecisionStateRef
```

。

物理：

```text
PhysicalStateHandle
├── backend
├── local locator
├── fd capability
└── materialization generation
```

Consumer：

```text
Ref
+
Grant
→ Registry
→ PhysicalHandle
```

。

这样未来换：

```text
SHM
→ memfd
→ PAGEATTACH
```

不会改上层语义 Contract。

---

# 79. Storage Policy 不应只看 `object_kind`

当前：

```text
object_kind
→ preference tuple
```

第一版可以。

未来更合理：

```text
PlacementRequest
├── object_kind
├── size
├── mutability
├── expected_consumers
├── reuse_count
├── lifetime
├── persistence
└── security_class
```

然后：

```text
StatePlacementPolicy
```

选择 backend。

这与你前面已经冻结的：

```text
State Placement
```

独立 routing plane 完全一致。

---

# 80. P0 / P1 / P2 修改清单

## P0 — 必须优先验证 / 修

### IPC-P0-1

`MAX_CONTROL_FRAME_BYTES`

涉及：

```text
statebus/control/transport.py
messages.py
tests
```

。

### IPC-P0-2

Duplicate Ref Publication Guard

涉及：

```text
statebus/state/store.py
```

。

### IPC-P0-3

Supervisor AttemptKey

涉及：

```text
runtime/supervisor.py
runtime/session.py
driver/adaptive runtime callers
```

先写 failing late-attempt test，再改。

### IPC-P0-4

memfd sealing

涉及：

```text
statebus/state/store.py
```

先做 standalone sealed memfd tests。

### IPC-P0-5

Persistent Worker Probe

不要直接替换主链。

新增：

```text
PersistentSubprocessExecutorTransport
```

跑 benchmark 后再决定切换。

---

# 81. P1 — 高价值 hardening

```text
SO_PEERCRED

socket chmod / owner verify

SCM_RIGHTS

hash memoryview without bytes copy

_read_exact_fd

idempotent release

atomic sidecar

StateStore lock

transport exception propagation

SharedMemory track=False compatibility adapter

proto schema single source
```

。

---

# 82. P2 — 只有 profiling / 平台条件成立才做

```text
openEuler PAGEATTACH backend

SOCK_SEQPACKET

worker multiplex

zero-copy protobuf tricks

io_uring

advanced CPU affinity
```

。

---

# 83. 不应该做的优化

明确：

```text
❌ 不重写 Protobuf

❌ 不自己造新的 serialization format

❌ 不把所有大 payload 塞 UDS

❌ 不为了“共享内存”把所有 state 都放 SHM

❌ 不立即引入 Redis/NATS/Kafka

❌ 不立即引入 C++ daemon

❌ 不让 CodeAct 与 trusted state worker 共进程

❌ 不把 openEuler 特性当 mandatory backend

❌ 不先改再 benchmark
```

。

---

# 84. 推荐的实施 Slice

## IPC-R0 — Safety Invariants

只做：

```text
frame max

duplicate ref guard

idempotent release

read_exact_fd

transport error propagation
```

不改架构。

Acceptance：

```text
旧测试全部 PASS

新增：
oversize frame rejected
duplicate conflicting publish rejected
double release safe
short read simulated
transport internal error visible
```

。

---

# 85. IPC-R1 — Immutable memfd

新增：

```text
MFD_ALLOW_SEALING

seal set

seal verify

read-only mmap
```

。

测试：

```text
after publish:
write → EPERM

truncate → EPERM

grow → EPERM

consumer verifies seals
```

。

仍保留：

```text
SHM fallback
```

。

---

# 86. IPC-R2 — Persistent Worker Probe

不要一开始改 AdaptiveRuntime。

新增实验性：

```text
PersistentWorkerBroker
```

支持一个 operation：

```text
semantic_select_v1
```

或：

```text
logit_gate_v1
```

。

比较：

```text
100
1000
requests
```

。

Gate：

```text
如果 p50/p95 和 CPU time
无明显改善
→ 不替换主链
```

。

---

# 87. IPC-R3 — SCM_RIGHTS

如果 R2 证明 persistent worker 值得：

```text
memfd
从 pass_fds
升级 SCM_RIGHTS
```

。

这时：

```text
sealed memfd
+
persistent worker
```

正式打通。

---

# 88. IPC-R4 — Attempt Model Hardening

Supervisor：

```text
AttemptKey
```

。

加入：

```text
stale result rejection
worker generation
```

。

确保：

```text
old attempt
永远不能 commit new attempt output
```

。

---

# 89. IPC-R5 — StateStore Transactionality

加入：

```text
StateLeaseRegistry

atomic metadata commit

concurrency lock

orphan sweep
```

。

这个和后续：

```text
LatentState
```

接入非常相关。

建议 Latent 之前至少完成：

```text
R0
R1
R5 的 identity/atomicity 子集
```

。

---

# 90. 最终比赛应该怎么讲“低开销通信”

不要：

> “我们用了 Protobuf 和 SHM，所以低开销。”

更好的：

> **StateBus 将 Agent 协作拆为 typed Control Plane 与 zero/low-copy State Data Plane。控制消息仅传递 action、typed arguments、CapabilityGrant 和 immutable StateRef，通过 Unix Domain Socket 交换；Embedding/Decision/Latent 等大型状态由 shared-memory / sealed-memfd 等节点内载体承载，Consumer 直接映射读取而不是重新序列化为文本。Runtime 通过 task/step/attempt identity、lease、hash、peer credentials 和 actual-use receipt 约束状态生命周期，并通过 persistent workers 摊销进程启动成本。**

这才是完整的系统故事。

---

# 91. 与 Text Baseline 的真正差异应该分三层

```text
Layer 1
Semantic payload
Text words/tokens
vs
typed fields / refs

Layer 2
Wire transport
UTF-8 bytes
vs
Protobuf

Layer 3
Large state
serialize into text
vs
map SHM/memfd
```

如果只测：

```text
JSON vs Protobuf size
```

价值有限。

真正强的是：

```text
Agent A internal state
不用 encode 成大段 text
```

。

---

# 92. 一个重要审计判断：现有实现并不弱

这一轮不是发现：

```text
“当前 IPC 是假的”
```

。

恰恰相反：

```text
UDS 是真的
Protobuf 是真的
Subprocess 是真的
SHM 跨 PID 是真的
memfd FD inheritance 是真的
StateRef 是真的
hash / lease / actual-use receipt 是真的
```

。

真正问题是：

> **现有实现比较像一套“强验证型 prototype”，每个机制都为了证明真实存在而独立做了较重的验证和隔离；下一阶段需要从 Verification Prototype 收敛成 Low-Overhead Runtime Fast Path。**

这是合理的项目演进，不是推倒重做。

---

# 93. 最值得保持的设计哲学

当前 StateBus 有一点一定不要丢：

```text
不因为优化性能
就删除：
identity
contract
hash
lease
receipt
```

。

很多“零拷贝 IPC demo”快，是因为：

```text
只共享一个 pointer/name
不做 correctness/security
```

。

StateBus 真正有价值的是：

```text
Low-copy
+
Typed
+
Governed
+
Auditable
```

。

所以优化目标：

```text
减少重复 copy / startup / parse
```

而不是：

```text
绕过 Runtime governance
```

。

---

# 94. Round 01 最终结论

本轮可以冻结成：

### KEEP

```text
Protobuf
UDS
Ref-based Control/Data separation
SharedMemory backend
mmap/CAS/workspace separation
task/step/attempt header
ACK/heartbeat/result lifecycle
actual-use audit
```

。

### FIX NOW

```text
bounded frame
duplicate ref identity
attempt-key correctness
memfd immutability
idempotent lifecycle
```

。

### BENCHMARK THEN BUILD

```text
persistent worker
SCM_RIGHTS
hash-copy removal
```

。

### FUTURE OPTIONAL

```text
openEuler PAGEATTACH zero-copy backend
```

。

### DO NOT BUILD

```text
new custom serialization
distributed message bus
complex io_uring/eBPF transport
```

除非 profiling 给出证据。

---

# 95. 下一 Round：Shared Semantic Memory

Round 02 将单独审：

# `Shared Memory / Cross-Task Reuse`

注意它与本轮：

```text
SharedMemory = OS IPC storage
```

不是一回事。

Round 02 的 `Shared Memory` 指赛题中的：

```text
Semantic Memory
```

主要会逐文件读：

```text
statebus/memory/*
MemoryRef
MemoryCommit
MemoryQuery
MemoryIndexStore
hybrid retrieval
exact replay
validated replay
assist
compatibility decision
memory commit gate
memory invalidation
replay ledger
```

重点回答：

```text
1. 当前 Memory 是真的跨任务复用还是 benchmark scaffolding？

2. query / commit compatibility 是否过度绑定 CanonicalTaskSpec？

3. exact replay 是否可能错误复用？

4. semantic retrieval 是否可能把错误历史注入当前任务？

5. memory quality floor / validator 到底够不够？

6. private benchmark gold 是否可能通过 Memory 泄漏？

7. MemoryRef / MemoryCommit / ReplayLedger 是否职责重复？

8. metadata / FTS / vector 三路 hybrid retrieval 怎么评分？

9. stale memory / model version / schema version 怎么 invalidation？

10. 如何设计连续任务，真正证明“记忆越用越有价值”而不是提前准备答案？
```

然后会再检索：

```text
MemGPT / Letta
Mem0
LangGraph memory
LongMemEval-V2
enterprise agent memory
cache/replay consistency research
```

但只借真正适合 StateBus 的机制。

---

# Appendix A. 本轮核心源码

```text
docs/reference/题目.md

statebus/control/statebus_control.proto
statebus/control/schema.py
statebus/control/messages.py
statebus/control/transport.py
statebus/control/subprocess_worker.py

statebus/state/store.py
statebus/state/semantic_state.py

statebus/runtime/supervisor.py
statebus/runtime/session.py

tests/test_control_plane.py
tests/test_subprocess_executor.py
tests/test_state_materialization.py
tests/test_runtime_session_and_ledger.py

docs/implementation/architecture/process-and-storage.md
docs/implementation/runtime/protobuf-and-uds.md
docs/implementation/runtime/worker-lifecycle.md
docs/implementation/operations/telemetry-and-metrics.md
```

---

# Appendix B. 外部依据

## Linux Unix Domain Socket

`unix(7)`

https://man7.org/linux/man-pages/man7/unix.7.html

关键依据：

```text
AF_UNIX same-machine IPC
SO_PEERCRED
SCM_RIGHTS
SOCK_SEQPACKET
pathname permission semantics
```

。

## Linux memfd / sealing

`memfd_create(2)`

https://man7.org/linux/man-pages/man2/memfd_create.2.html

`F_GET_SEALS / F_ADD_SEALS`

https://man7.org/linux/man-pages/man2/F_GET_SEALS.2const.html

关键依据：

```text
MFD_ALLOW_SEALING
F_SEAL_WRITE
F_SEAL_GROW
F_SEAL_SHRINK
F_SEAL_SEAL
```

以及 Linux 官方对：

```text
shared-memory TOCTOU
```

风险的说明。

## Python SharedMemory

Python 3.13+:

https://docs.python.org/3/library/multiprocessing.shared_memory.html

重点：

```text
track=False
```

适合：

```text
subprocess / standalone Python consumers
```

由另一个进程负责生命周期的场景。

## openEuler 24.03 LTS SP3

Key Features:

https://docs.openeuler.org/en/docs/24.03_LTS_SP3/server/releasenotes/releasenotes/key_features.html

明确包含：

```text
Linux Kernel 6.6
cross-process zero-copy data transfer
```

相关 kernel work：

```text
PAGEATTACH / zcopy
```

---

# Appendix C. 建议新增测试清单

```text
test_control_frame_rejects_oversize

test_control_frame_rejects_zero_or_invalid_length

test_uds_peer_credentials_match_spawned_worker

test_duplicate_ref_same_payload_is_idempotent

test_duplicate_ref_different_payload_rejected

test_state_release_is_idempotent

test_memfd_is_sealed_after_publication

test_memfd_write_after_publish_fails

test_memfd_truncate_after_publish_fails

test_memfd_consumer_requires_expected_seals

test_memfd_read_exact_handles_short_reads

test_semantic_hash_memoryview_no_copy

test_atomic_sidecar_crash_before_rename_not_visible

test_state_store_concurrent_publish_release

test_shared_memory_subprocess_track_behavior

test_persistent_worker_handles_100_requests

test_persistent_worker_recovers_after_request_error

test_worker_peer_pid_bound_to_transport_audit

test_old_attempt_late_success_does_not_replace_new_attempt

test_old_attempt_artifact_never_committed

test_repeated_gc_has_no_error

test_runtime_shutdown_leaves_no_shm

test_runtime_shutdown_leaves_no_socket

test_runtime_shutdown_leaves_no_worker
```

---

# Appendix D. 推荐实现顺序最终版

```text
IPC-R0
Safety / lifecycle invariants

    ↓

IPC-R1
Sealed memfd

    ↓

IPC-R2
Persistent worker experiment

    ↓
如果收益成立

IPC-R3
SCM_RIGHTS

    ↓

IPC-R4
Attempt / stale-result hardening

    ↓

IPC-R5
StateStore transactionality / concurrency

    ↓

Optional
openEuler PAGEATTACH
```

这条路线的关键不是“做更多 IPC”，而是：

# **把已经真实存在的 StateBus IPC，从机制证明升级成一个可持续、低固定成本、可验证的节点内多 Agent Runtime。**
