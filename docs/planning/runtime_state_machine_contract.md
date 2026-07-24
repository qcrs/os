# Runtime State Machine Contract

日期：2026-06-26  
状态：`v2` 子合同草案  
作用：把 `StateBus v2` 的运行时控制语义从“文档描述”收紧成“可编码状态机”。

---

## 1. 目标

这份合同回答 7 个问题：

1. 一个 step 从创建到完成，正式经历哪些状态
2. `Planner`、`Runtime Supervisor`、`Worker` 各自拥有什么权力
3. `ACK / HEARTBEAT / CANCEL / TRAP` 这些控制语义如何定义
4. 重试预算归谁管
5. 共享状态与工作区的回收归谁管
6. 在当前仓库约束下，`MVP` 如何实现而不依赖更重的 daemon / container 基建
7. 在单容器 `Docker + openEuler` 目标下，状态机和资源回收语义如何正式落地

这份合同不讨论：

1. 任务语义规划算法优劣
2. 具体 retriever / executor 的业务逻辑
3. `KV cache` 之类模型内部状态

---

## 2. 为什么需要单独合同化

当前仓库已经有：

- `Plan / PlanStep / StepResult`
- `Ack / Error / Heartbeat`
- `runtime/orchestrator.py`
- `runtime/remote_executor.py`

但这些对象还没有组成一套明确的运行时责任边界。

如果这部分不先定死，后续会出现三类问题：

1. `Planner` 语义职责和 runtime 监督职责混在一起
2. worker 失败时，到底是“本地重试”、“上游重发”还是“整图回退”不清楚
3. `shared_memory`、workspace、临时状态在异常路径下容易泄漏

---

## 3. 核心角色分责

`v2` 不采用 “Planner 全能 master” 模式。

### 3.1 Planner

职责：

1. 解析用户目标
2. 生成或修复任务图
3. 决定回退路线
4. 决定是否允许 replay / assist / fallback

不负责：

1. heartbeat 监控
2. lease 到期处理
3. orphan state / orphan workspace 清理
4. worker 存活探测

### 3.2 Runtime Supervisor

职责：

1. 负责 step dispatch
2. 跟踪 step 生命周期
3. 维护 attempt 计数、超时、cancel、trap
4. 维护 task teardown 与资源回收
5. 做 orphan cleanup

在 `MVP` 中，它可以先是 `runtime/orchestrator.py` 内的一个明确子层，而不是独立常驻进程。

### 3.3 Worker

职责：

1. 接单并确认接收
2. 执行业务逻辑
3. 产出 `StepResult`
4. 通过外层 worker harness 发心跳

不负责：

1. 无限重试
2. 决定是否重新规划
3. 自己判断 exact replay 是否成立

---

## 4. Step 生命周期

每个 `step_id` 必须显式落在下面状态之一：

1. `PENDING`
2. `DISPATCHED`
3. `ACKED`
4. `RUNNING`
5. `COMPLETED`
6. `FAILED`
7. `TRAPPED`
8. `CANCELLED`
9. `GC_PENDING`
10. `GC_DONE`

### 4.1 状态含义

`PENDING`

- 已存在于计划中
- 还没派发到 worker

`DISPATCHED`

- supervisor 已发送执行请求
- 正等待 worker `ACK`

`ACKED`

- worker 已确认接单
- 尚未进入业务执行或尚未对外宣告 `RUNNING`

`RUNNING`

- worker 已进入业务执行
- lease 已开始计时

`COMPLETED`

- worker 成功返回 `StepResult.success=True`

`FAILED`

- 业务执行失败，但没有发生 supervisor 级 trap
- 例如代码报错、输入缺失、表格读取失败

`TRAPPED`

- 运行时级异常
- 例如 worker 崩溃、协议破损、lease 到期、无法 materialize 输入

`CANCELLED`

- supervisor 主动取消
- 例如上游失败、用户终止、回退路线切换

`GC_PENDING`

- step 已结束，等待统一资源回收

`GC_DONE`

- step 关联的临时资源已回收完成

---

## 5. 控制语义

### 5.1 推荐消息语义

当前协议对象可继续沿用：

- `PlanStep`
- `Ack`
- `Error`
- `Heartbeat`
- `StepResult`

但在语义层建议明确映射成：

1. `REQ_EXEC`
2. `ACK_RECV`
3. `RUN_START`
4. `HEARTBEAT`
5. `RES_SUCC`
6. `RES_ERR`
7. `CMD_CANCEL`
8. `TRAP_FATAL`
9. `CMD_GC`

`MVP` 应直接把这些语义冻结进 `v2` 的 typed Protobuf control plane。

允许的过渡做法是：

1. 少量扩展字段暂放在结构化 payload 中
2. 但正式控制总线不再采用“长期依赖 metadata 或 JSON blob 承载关键语义”的路线

### 5.2 ACK 规则

默认要求：

1. supervisor 派发 step 后，worker 必须在 `ack_timeout_ms` 内返回 `ACK`
2. 超时则视为 `DISPATCHED -> TRAPPED`
3. 是否重派由 supervisor 决定

默认值建议：

- `ack_timeout_ms = 250`

这只是默认参数，不写成架构常数。

### 5.3 HEARTBEAT 规则

关键纪律：

1. heartbeat 不能依赖业务脚本本身
2. heartbeat 应由 worker 外层 harness 或 wrapper 发出

原因很简单：

- 如果业务脚本卡死，脚本内 heartbeat 会一起失效

默认参数建议：

- `heartbeat_interval_ms = 2000`
- `lease_timeout_ms = 6000`

依旧只作为默认值。

### 5.4 CANCEL 规则

以下情况 supervisor 可发 `CMD_CANCEL`：

1. 上游依赖失败且当前 step 已无继续价值
2. task 进入 fallback 路径
3. 用户终止任务
4. lease 即将超时且需要主动清理子进程

### 5.5 TRAP 规则

满足任一条件，step 进入 `TRAPPED`：

1. `ACK` 超时
2. heartbeat 超时
3. worker 进程异常退出
4. 输入 materialization 失败
5. 协议反序列化失败
6. 资源回收失败且影响下一步运行

### 5.6 推荐冻结为正式事件字段

建议在现有消息对象之上，至少冻结下面这些 wire-level 必填字段。

`REQ_EXEC`

1. `trace_id`
2. `task_id`
3. `step_id`
4. `attempt_id`
5. `target_role`
6. `timeout_ms`
7. `runtime_reuse_contract`
8. `state_refs`
9. `artifact_refs`

`ACK_RECV`

1. `task_id`
2. `step_id`
3. `attempt_id`
4. `worker_id`
5. `worker_pid`
6. `received_at_ns`

`RUN_START`

1. `task_id`
2. `step_id`
3. `attempt_id`
4. `worker_id`
5. `worker_pid`
6. `started_at_ns`

`RES_ERR`

1. `task_id`
2. `step_id`
3. `attempt_id`
4. `error_code`
5. `stderr_preview`
6. `retryable`

`TRAP_FATAL`

1. `task_id`
2. `step_id`
3. `attempt_id`
4. `error_code`
5. `worker_id`
6. `worker_pid`
7. `traceback_ref` 或 `traceback_preview`

`CMD_GC`

1. `task_id`
2. `resource_handles`
3. `workspace_dirs`
4. `issued_at_ns`

这些字段不一定都要对应新的 protobuf 类型，但必须在 payload schema 层冻结下来。

---

## 6. 重试与重规划

### 6.1 谁拥有重试预算

重试预算归 `Runtime Supervisor`，不是 worker。

建议字段：

- `max_attempts_per_step = 2` 或 `3`

### 6.2 何时只重试当前 step

以下情况允许直接重试同一步：

1. 瞬时 I/O 抖动
2. 远端 UDS 连接被短暂打断
3. 代码执行路径可通过上一次 stderr 直接修复

### 6.3 何时需要回到 Planner 重规划

以下情况应交回 `Planner`：

1. 连续重试耗尽预算
2. 当前工具链与输入不相容
3. 预期输出 contract 已无法满足
4. 必须切换路线，例如从“画图”降级为“只出文本总结”

---

## 7. 资源所有权与清理

### 7.1 基本原则

正常路径上采用：

1. producer 创建资源
2. supervisor 记录资源归属
3. task teardown 时由 supervisor 统一回收

原因：

- 只让 worker 自己清理，异常路径会泄漏

### 7.2 需要登记的资源

至少包括：

1. `shared_memory` handle
2. `mmap` 临时文件
3. workspace 目录
4. sandbox 输入/输出映射
5. 临时生成的 script / csv / png / json

### 7.3 异常路径兜底

运行时启动时必须具备：

1. orphaned workspace 扫描
2. orphaned shared memory 扫描
3. 过期 task resource 强制回收

这部分在 `MVP` 中先做 best-effort 清理，不要求复杂分布式 GC。

### 7.4 单容器 openEuler 下的正式约束

如果 `v2` 明确运行在单容器 `openEuler` 内，需要额外明确：

1. supervisor 与 worker 默认处于同容器、同 IPC namespace、同文件系统根
2. cancel/heartbeat 默认通过容器内 UDS 或进程内监督路径传递
3. 共享状态可以合法选择：
   - `/dev/shm` 上的 `shared_memory`
   - 容器内文件系统上的 `mmap` 文件
4. UDS socket 路径直接定义为容器内 `socket_root`

更合理的默认策略变成：

1. 控制面 socket 放到容器内显式 `run/` 目录
2. 数据面同时支持 `mmap` 与 `shared_memory`
3. 两者由 benchmark 和回放需求决定主默认值，而不是由跨容器限制决定

---

## 8. 建议的数据结构

建议新增明确的 runtime 内部记录对象。

```python
from dataclasses import dataclass, field

@dataclass
class StepAttemptRecord:
    task_id: str
    step_id: str
    attempt_id: str
    owner_role: str
    state: str
    dispatched_at_ns: int = 0
    acked_at_ns: int = 0
    running_at_ns: int = 0
    completed_at_ns: int = 0
    heartbeat_at_ns: int = 0
    attempt_index: int = 0
    worker_id: str = ""
    cancel_reason: str = ""
    trap_reason: str = ""
    resource_handles: list[str] = field(default_factory=list)
    workspace_dirs: list[str] = field(default_factory=list)
```

建议新增 runtime 配置对象：

```python
@dataclass(frozen=True)
class RuntimeLeaseConfig:
    ack_timeout_ms: int = 250
    heartbeat_interval_ms: int = 2000
    lease_timeout_ms: int = 6000
    max_attempts_per_step: int = 2
    teardown_grace_ms: int = 1000
```

---

## 9. 与当前仓库对象的映射

当前仓库可直接复用：

1. [protocol/messages.py](/home/qcrs/statebus/project/protocol/messages.py:12) 中的 `Ack`、`Error`、`Heartbeat`、`PlanStep`、`StepResult`
2. [runtime/orchestrator.py](/home/qcrs/statebus/project/runtime/orchestrator.py:1) 作为 `Planner + Runtime Supervisor` 仍混合存在的宿主
3. [runtime/remote_executor.py](/home/qcrs/statebus/project/runtime/remote_executor.py:1) 作为多进程 worker transport 样机
4. [statepool/store.py](/home/qcrs/statebus/project/statepool/store.py:73) 中已有的 shared memory cleanup 能力

当前仓库仍缺：

1. 显式 `StepAttemptRecord`
2. supervisor 级 lease 记录
3. orphan cleanup 启动路径
4. `ACK / RUN_START / RES_ERR / TRAP_FATAL` 的正式状态转移表

---

## 10. MVP 实现方案

### 10.1 不新增 daemon

`MVP` 不强制引入常驻 Bus Daemon。

先做：

1. `runtime/orchestrator.py` 内部抽出 `RuntimeSupervisor`
2. 对本地/远端 worker 都走统一 attempt record
3. 给 `remote_executor` 增加可观测的 ack / run / finish 事件

### 10.2 不要求全量 agent 外进程化

`MVP` 可只先让 `Executor` 走外进程 transport，其他角色保持进程内调用。

原因：

1. 能先把最关键的 `UDS + StatePool` 路径验证清楚
2. 不会过早陷入全量 agent daemon 化

### 10.3 心跳先做 wrapper，不做脚本内上报

`CodeAct`、tool worker 或远端 executor 的业务脚本不直接承担 heartbeat。

先做：

1. 外层 wrapper 定时上报
2. wrapper 观察业务子进程状态

### 10.4 单容器目标下的实现修正

如果 `v2` 直接以单容器 `openEuler` 为主环境，`MVP` 应明确：

1. `runtime_root / socket_root / workspace_root / state_root` 都是容器内正式根目录
2. `shared_memory` 不再只是“将来可选”，而应进入 benchmark matrix
3. 容器启动仍建议带 `--init`，避免 PID 1 不回收僵尸子进程
4. 取消逻辑优先以协议级 `CMD_CANCEL` + wrapper kill 实现

---

## 11. 非目标与暂不承诺

当前不承诺：

1. 分布式多机 supervisor
2. 抢占式调度
3. 优先级反转处理
4. 容器编排级 lease 恢复
5. 真实 OS kernel 风格 signal handling 全复刻

---

## 12. 验收建议

最小验收测试建议：

1. 派发一个远端 executor step
2. 能看到 `PENDING -> DISPATCHED -> ACKED -> RUNNING -> COMPLETED`
3. 人为卡死 worker，能触发 heartbeat timeout
4. timeout 后 step 进入 `TRAPPED`
5. teardown 后共享内存与 workspace 被回收

建议后续补测试文件：

- `tests/runtime/test_runtime_state_machine.py`
- `tests/runtime/test_runtime_lease_and_cancel.py`
- `tests/runtime/test_runtime_orphan_cleanup.py`

---

## 13. 外部参考

这些资料只用于约束实现边界，不直接决定 `v2` 架构：

- Python `shared_memory` 官方文档：<https://docs.python.org/3/library/multiprocessing.shared_memory.html>
- Python `asyncio.subprocess` 官方文档：<https://docs.python.org/3/library/asyncio-subprocess.html>
- Python `mmap` 官方文档：<https://docs.python.org/3/library/mmap.html>
