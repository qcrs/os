# 当前功能边界与迁移划分

更新时间：2026-06-07

适用范围：当前 `/home/qcrs/statebus/project` 实现仓库已经落地到什么程度，哪些能力可以在当前 Linux 宿主机继续做，哪些需要 Docker / openEuler VM / 更强系统权限后再做。

---

## 1. 结论先说

当前仓库已经不是“只有设计文档”的状态。

现在已经可以诚实宣称的能力是：

- 有 `text` / `protocol` 双模式可运行主链路
- 有 `.proto + pb2 + capability/schema hardening`
- 有 `StateRef + mmap/shared_memory + SQLite + FAISS`
- 有共享记忆命中、复用剪枝和 benchmark
- 有 repo-local `Executor` 工具注册 + 轻量子进程隔离 fallback
- 有 **外部多进程 `UDS` executor transport 样机**
- 有比单一 query embedding 更强的 `FEATURE_BUNDLE` 中间状态

但它还不是终态。

当前实现仍然**没有**：

- `nsjail` 级别的正式安全沙箱
- Docker / openEuler 终态复现链
- `SCM_RIGHTS`/FD 注入式共享内存数据面
- 真正的 LLM hidden state / KV cache 中间表示传递
- WASM / eBPF / 容器沙箱这些系统加分项的正式落地

---

## 2. 当前宿主机上已经可以做的

### 2.1 协议与控制面

当前代码已支持：

- `Protobuf` 控制帧
- `CapabilityTable` / `SchemaInterceptor`
- `protocol_bytes` 与 `text_bytes` 对照统计
- `RemoteStepRequest` / `RemoteStepResponse`
- `UDS` 上的外部多进程 executor 样机

实现位置：

- `protocol/messages.py`
- `protocol/statebus.proto`
- `runtime/uds_transport.py`
- `runtime/remote_executor.py`

边界说明：

- 这已经满足“不是纯自然语言透传”的主要求。
- 这已经让“外部多进程 transport”从文档概念变成真实代码路径。
- 但当前远端进程只覆盖 `Executor` 样机，不是全 Agent 都走外部进程。

### 2.2 状态传递

当前代码已支持：

- `MMAP_FILE` 正式默认路线
- `PY_SHARED_MEMORY` 可选 benchmark 路线
- `DENSE_EVIDENCE`
- `EMBEDDING`
- `TOOL_ARTIFACT`
- 新增 `FEATURE_BUNDLE`

实现位置：

- `statepool/store.py`
- `runtime/orchestrator.py`
- `runtime/executor_runtime.py`

`FEATURE_BUNDLE` 的定位：

- 它不是伪装成“真正 hidden state/KV”的宣传词；
- 它是一个更强的非文本中间态，里面放 route、signals、query_terms、reuse_signature、evidence hash 等结构化特征；
- 它通过 `StateRef` 传给 `Executor`，避免 `Executor` 只靠原始长文本做路由。

这条能力当前就可以做，而且对赛题“非文本状态传递”是有效加分。

### 2.3 Executor 工程化

当前 `Executor` 已不再只是硬编码 if/else playbook。

现在已有：

- `ToolRegistry`
- `ToolSpec`
- `LightweightSubprocessRunner`
- `runtime/tool_worker.py`
- repo-local playbook 工具分发

边界说明：

- 这是 **tool registry + subprocess fallback**
- 不是 `CodeAct + 安全沙箱终态`
- 不是工具市场，也不是外部插件生态

但它已经明显比“把执行逻辑直接写在 agent 里”更工程化。

### 2.4 shared_memory 正式性

当前不是“后端代码里有，但 benchmark 不算数”。

现在：

- benchmark CLI 已支持 `--statepool-backend shared_memory`
- embedding state 也支持 `--embed-state-backend shared_memory`
- 测试已经覆盖 shared-memory run path

仍然保留的工程判断：

- 默认 benchmark 主线仍建议 `mmap`
- `shared_memory` 现在是**可验证备选路径**
- 不是当前论文/报告里的唯一主线

---

## 3. 当前环境下能写代码，但本机受管 sandbox 不一定能现场验证的

### 3.1 UDS

`UDS` 代码路径当前已实现，并且已经在真实宿主机权限下验证通过。

但当前 Codex 受管 sandbox 对 `AF_UNIX` / pathname socket 可能直接拒绝，所以：

- 仓库测试里会自动探测；
- 如果当前环境禁止 Unix socket，就 `skip`；
- 这不代表代码不可用，只代表此沙箱不允许验证。

这类能力的正确口径是：

> 当前 Linux 宿主机可做，当前受管 sandbox 可能不可直接验证。

### 3.2 远端 executor 输出为什么固定回 `mmap`

当前 `UDS` 远端 executor 会把返回 artifact 固定写成 `mmap` 文件，而不是跨进程 `shared_memory`。

原因不是“做不到”，而是当前阶段先避免两类问题：

- 远端进程创建 `shared_memory` 的生命周期与清理归属
- benchmark 里把跨进程 SHM 清理问题混进主线指标

这属于**当前阶段刻意收敛**，不是 bug。

---

## 4. 明确需要延后的项

### 4.1 必须等更强环境或迁移阶段

这些不要写成“当前仓库已经实现”：

- `nsjail` 正式沙箱链
- Docker 终态复现环境
- openEuler VM 最终兼容性验证
- eBPF / `bpftrace` / 更高权限性能观测
- 容器内安全 CodeAct 执行链
- `SCM_RIGHTS` / FD passing 数据面

原因分别是：

- 需要额外安装或系统权限
- 需要与当前宿主机策略解耦
- 需要交付环境复现，而不是当前研发环境先上

### 4.2 当前不该假装已经做了的“状态传递创新”

以下内容当前仍是后续增强，而不是现状：

- LLM hidden state 直传
- KV cache / prefill state 直传
- 跨模型共享 latent / activation cache
- 真正的后端消费者按神经网络内部表示继续推理

当前仓库最诚实的表述应是：

> 已实现 `embedding + feature bundle + state ref` 这一级的非文本中间态；更强的 hidden-state / KV 级表示属于后续对象。

### 4.3 当前不该假装已经完成的系统加分项

这些都还是加分项候选，不是主线已完工：

- WASM sandbox
- eBPF telemetry
- 容器沙箱
- 多进程全角色分布式 Runtime
- 工具市场 / 通用插件市场

---

## 5. 当前推荐的落地顺序

当前环境下，如果继续推进，建议顺序固定为：

1. 把 host-side `text/protocol + StateRef + memory + benchmark` 做得更稳
2. 保持 `mmap` 主线，同时保留 `shared_memory` 备选验证
3. 把 `UDS executor` 当作“外部多进程 transport 已有样机”
4. 继续把 `Executor` 做成更清晰的 tool-first / optional CodeAct fallback
5. 等 VM / Docker / 权限条件成熟后，再补 `nsjail`、容器、eBPF、FD passing

---

## 6. 对外口径建议

如果要答辩或写实验报告，当前最稳的说法是：

### 可以说“已经做了”的

- 结构化协议工程化
- capability/schema hardening
- 双模式 benchmark
- `StateRef` 非文本状态传递
- `mmap/shared_memory` 双后端
- SQLite + FAISS 共享记忆
- 共享记忆驱动的 reuse
- 外部多进程 `UDS` executor 样机
- 轻量 subprocess executor fallback
- `FEATURE_BUNDLE` 非文本特征态

### 应说“已做样机，但不是终态”的

- 外部多进程 transport
- lightweight sandbox
- shared_memory benchmark 路线

### 应明确说“后续增强项”的

- `nsjail`
- CodeAct 正式安全链
- Docker/openEuler 终态复现
- hidden-state/KV 级状态传递
- eBPF/WASM/容器类加分项
