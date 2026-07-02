# StateBus V2 Clean-Room Rebuild Plan

日期：2026-06-25  
状态：设计文档，面向新的 `v2` 重构路线，不等于当前 `main` 已实现状态。  
适用前提：本文在架构上采用 clean-room 视角，不继承 `v1/mainline` 的外壳；`v2` 的目标执行环境明确为 `Docker` 内的单容器 `openEuler`。因此所有实现合同都应默认基于“单容器、同 IPC 命名空间、同文件系统根、同进程命名空间内多进程协作”来设计，而不再沿用 `host-first` 运行前提。

---

## 0. 文档目的

这份文档回答四件事：

1. 为什么值得基于 [some_think.md](/home/qcrs/statebus/project/some_think.md) 启动一个更干净的 `v2`。
2. 哪些历史经验值得吸收，哪些历史前提应被丢弃。
3. `v2` 的系统分层、角色、通道、记忆、任务、评测和可视化应该怎么落地。
4. 为什么之前 `token` 节省不多，以及 `v2` 里真正的降本点应该放在哪里。

本文是一个面向实现的蓝图，不是答辩口号稿。所有内容都按三类标记：

- `MVP`：第一阶段必须落地
- `Conditional`：条件允许时增强
- `Future Work`：只保留接口和论述，不进入首版主线

---

## 1. 结论先行

### 1.0 关于执行环境前提的修正

`v2` 现在不再以宿主机直跑为目标执行形态，而是以 `Docker` 内的单容器 `openEuler` 为主运行环境。

这会带来两个直接变化：

1. 之前因为宿主机权限或跨容器边界而保守处理的能力，现在可以重新进入主线评估
2. 但所有实现都必须按“容器内真实语义”来设计，而不是假装自己仍在宿主机上

最重要的现实变化是：

1. `AF_UNIX / UDS` 在单容器内是自然成立的主路径
2. `multiprocessing.shared_memory` 在单容器多进程内是正式可用的数据面候选，而不再只是受限备选
3. `/dev/shm`、workspace、socket root、state root 都可以在单容器文件系统内统一管理
4. replay / artifact / workspace contract 应以容器内根目录和镜像版本为准，而不是宿主机目录

### 1.1 是否值得基于 `some_think.md` 重构

值得，但不能照抄。

`some_think.md` 最有价值的地方不在于它把所有技术都说得很重，而在于它把方向拉直了：

- 不再把多 Agent 理解成“群聊”
- 明确区分控制流和数据流
- 强调“真检索 + 真执行 + 真复用”
- 强调非文本状态不是装饰，而是为了在进入 LLM 之前完成本地筛选与复用
- 强调共享记忆如果只会“把旧文本再塞回 prompt”，收益会很有限

它的问题不是方向错，而是有几处承诺过早：

- 太早把动态消息总线、常驻 daemon、能力发现调度写成默认主线
- 太早把 KV Cache、iSula、容器化沙箱写成“首阶段已做”
- 容易把“structured vs pure text”讲成一个过宽的 baseline 对比

因此，推荐做法不是“否定 `some_think`”，而是：

- 把它当成 `v2` 的 north-star
- 用已有系统经验里的有效约束来给它收口，而不是继承旧实现外壳

### 1.2 `v2` 的核心主张

`v2` 不再围绕“一个固定四步图如何跑通”来设计，而是围绕三件基础设施问题来设计：

1. 控制面如何结构化，避免大段文本 handoff
2. 语义中间态如何以非文本形式跨角色传递，并在进入 LLM 前完成本地剪枝
3. 代码、表格、图像、结果文件如何作为一等公民沉淀、复用和回放

一句话概括：

> `v2` 要把 StateBus 从“带 typed state 的多 Agent workflow”升级成“以控制面、语义状态面、执行产物面为核心的 Agent runtime”。

### 1.3 面向单容器 openEuler 的直接设计结论

如果 `v2` 的目标环境是单容器 `openEuler`，那么应直接采用下面这些约束：

1. 控制面 socket、state root、workspace root、artifact root 都定义为容器内显式根目录
2. `UDS + structured protocol` 进入正式主线，而不是只当 host 样机
3. `mmap` 与 `shared_memory` 都可以作为正式状态面候选
4. 是否默认选 `mmap` 还是 `shared_memory`，应由：
   - benchmark 稳定性
   - replay/审计便利性
   - `/dev/shm` 容量约束
   来决定，而不是因为跨容器不可见性被提前否决
5. replay key 仍必须纳入：
   - container image digest 或 runtime environment version
   - extractor/tool/runtime 版本
6. 所有 artifact/state 定位默认仍应使用：
   - container-root-relative path
   - workspace-relative path
   - content hash
   而不是宿主机绝对路径

### 1.4 本轮冻结的实现决策

这一轮文档不再只停留在“应该有合同”，而是冻结下面这些可直接编码的方向：

1. `CanonicalTaskSpec`
   - 必须先于 replay 存在
   - `exact_replay` 只认 canonical JSON hash
2. `RuntimeCompatibilitySignature`
   - 优先用 openEuler release + Python version + dependency lock hash + tool registry version + extractor bundle digest
   - 不把 image digest 写成唯一事实
3. `ExecutionArtifactRef`
   - 正式作为与 semantic state 并列的一等对象
   - 生命周期与 replay 语义独立于 `SemanticStateRef`
   - 首轮就独立成 ref 类型与 registry entry，不再依赖过渡性 metadata 混写
4. `HydrateManifest`
   - 采用强类型 locator entry 列表
   - 不再允许 `dict[int, dict]` 这种弱类型表达长期存在
5. `CanonicalEvidencePack`
   - table facts 与 text contexts 分桶
   - text contexts 采用 rank-only RRF
6. `raw_evidence_bytes_seen_by_llm`
   - 只统计真正插入 prompt 的 hydrated external evidence bytes
   - 不含 system prompt 与任务指令
7. replay commit
   - 采用 `CANDIDATE -> VERIFIED -> INVALIDATED` 两段提交思路
8. 控制面正式格式
   - typed Protobuf over length-prefixed UDS
   - 不采用 `MessagePack` 作为正式控制总线主格式
   - 重构重点是清理 `JSON-in-Protobuf` 弱类型字段
9. 状态面存储分层
   - 短生命周期 semantic state 优先 `shared_memory`
   - replay-ready artifact 与长寿命对象优先 `mmap/CAS`
   - `/dev/shm` 预算压力下，新对象自动降级到 `mmap`
10. formal task family
   - 首版 formal benchmark 冻结为财报 / 经营数据分析
   - incident / repo audit 等场景保留为 demo tier
11. `KV cache`
   - 当前只允许定性为 `Engine-Local Prefix Reuse`
   - 不得与 memory/replay 混写

这些决策的目标不是“文档更硬核”，而是避免 `v2` 在第一轮编码时立刻分叉。

---

## 2. 为什么过去的实现里 Token 节省不多

这是 `v2` 设计的出发点之一，必须先讲清楚。

### 2.1 不是失败，而是比较对象和任务对象决定的

历史实现中的主比较对象不是外部传统纯文本系统，而是 StateBus 内部的：

- `text_whole_lane`
- `state_packet_minimal`

见 [docs/reader_guide/05_text_vs_statebus_comparison_methodology.md](/home/qcrs/statebus/project/docs/reader_guide/05_text_vs_statebus_comparison_methodology.md)。

这意味着当前比较更像：

- 同一个运行时内部
- 同一个任务合同下
- 用文本 handoff vs typed handoff 做对照

它能证明控制面和 typed handoff 有价值，但不会天然给出“极大 token 下降”。

### 2.2 既有 typed state 主要减少的是交接成本，不是全文摄入成本

既有实现已经有：

- `StateRef`
- `StatePool`
- `MemoryStore`
- `EXECUTOR_DECISION_PACKET`
- replay contract

但在很多任务中，下游仍然需要真正看到证据文本或工具结果文本，才能完成最终回答。也就是说：

- `typed state` 确实减少了 handoff 的解析和恢复成本
- 但它没有彻底消灭“LLM 仍需读文本证据”这件事

所以节省往往更像：

- 控制字节下降明显
- 角色间解析歧义下降
- 一部分 summarizer token 下降
- 但总 token 不会断崖式归零

### 2.3 既有任务家族不是长文档强剪枝型任务

既有主线最强的是证据纪律和公平比较，不是长文档 RAG 的极限降本。很多任务更接近：

- incident/playbook
- route/tool 选择
- controlled replay

这类任务的长文本负担本来就不算最重，因此 embedding 剪枝带来的收益空间也有限。

### 2.4 既有记忆最强的收益不是 assist，而是 replay

这是历史实现里最重要的经验之一。

当前仓库已经非常明确：

- `hit != benefit`
- `assist != replay`
- `replay != automatic overall superiority`

见：

- [runtime/reuse_contract.py](/home/qcrs/statebus/project/runtime/reuse_contract.py)
- [docs/reports/current_architecture_overview_20260622.md](/home/qcrs/statebus/project/docs/reports/current_architecture_overview_20260622.md)
- [docs/review/three_way_system_audit_20260625.md](/home/qcrs/statebus/project/docs/review/three_way_system_audit_20260625.md)

也就是说，之前 token 节省不大，一个关键原因是：

- 记忆命中了，但很多时候只是“把旧信息作为参考再喂回去”
- 而不是“真的跳过检索、跳过执行、跳过生成”

### 2.5 对 `v2` 的直接启示

如果 `v2` 还继续走“typed handoff 很精致，但长文档和执行链没有真正裁剪”的路线，token 节省依然不会大。

因此 `v2` 的大收益必须来自组合拳：

1. `Control Channel` 减少控制面冗余
2. `Semantic State Channel` 在进入 LLM 前完成长文档剪枝
3. `Execution Artifact Channel` 让代码和结果可以直接复用，而不是反复口述
4. `validated_replay / exact_replay` 让一部分步骤真实跳过

---

## 3. `some_think.md` 哪些合理，哪些要降级

### 3.1 应该直接吸收的部分

以下内容应当进入 `v2` 主线：

1. 控制流与数据流分离
2. `UDS + typed Protobuf` 的结构化控制面
3. `shared_memory / mmap` 承载 embedding、feature bundle、结构化中间态
4. `SQLite + FAISS` 组成的 L2 共享记忆
5. `CodeAct` 必须走“真执行”而不是伪执行
6. 任务必须换成长文档、真实数据、可复用代码模板的连续任务
7. 评测必须拆开通信、token、非文本状态、复用收益四条线

### 3.2 应该保留但降级的部分

以下内容适合作为增强项，不应写成 `MVP` 已实现主线：

1. 动态能力发现调度
2. 常驻 daemon + 消息总线微服务化
3. `iSula` 生产级容器沙箱
4. KV Cache 直接挂载
5. eBPF 级通信观测

这些并不是不重要，而是：

- 工程风险高
- 对首版可交付价值不是最高
- 很容易稀释“真检索、真执行、真复用”这三个更关键的建设目标

### 3.3 `some_think` 与当前仓库最大的结构差异

历史主线更像：

- 以 `Orchestrator + formal benchmark` 为核心
- 在固定角色图中验证 typed state、memory、fairness

而 `some_think` 指向的 `v2` 更像：

- 以 runtime planes 为核心
- 让 control/state/artifact 成为第一层对象
- 让 Planner 对步骤图进行编译和裁剪

这不是背道而驰，而是视角升级。

---

## 4. `v2` 的设计目标与非目标

## 4.1 目标

### `MVP`

1. `openEuler` 主开发环境可跑通
2. 四角色仍保留：`Planner / Retriever / Executor / Summarizer`
3. 运行路径不再固定必须线性经过四角色
4. 实现三条正式通道：
   - `Control Channel`
   - `Semantic State Channel`
   - `Execution Artifact Channel`
5. 实现真实检索、真实代码执行、真实结果产物沉淀
6. 实现 `SQLite + FAISS` 的 L2 共享记忆
7. 实现 `assist / validated_replay / exact_replay` 分层复用
8. 设计能真正拉开 token 和时延差距的连续任务

### `Conditional`

1. `ZeroMQ` 作为控制总线替代纯 `AF_UNIX` 点对点
2. 三类差异化 Retriever 并行 fan-out
3. `FastAPI + WebSocket` 可视化控制台
4. `iSula` 容器化执行

### `Future Work`

1. `Ephemeral Neural State` / KV Cache
2. 更强的 capability registry
3. 跨机多节点 runtime
4. eBPF 与更底层的性能采样

## 4.2 非目标

`v2` 首版不追求：

1. 一个通用的“万物 Agent 平台”
2. 一上来就替代所有 current repo 的 formal benchmark
3. 用过重的容器和调度系统遮蔽核心问题
4. 把 `KV Cache` 写成当前已落地事实
5. 混淆内部 comparator 与外部 pure-text baseline

---

## 5. `v2` 总体架构

`v2` 推荐按六层组织：

1. `Task Layer`
2. `Planner / Runtime Layer`
3. `Control Plane`
4. `Semantic State Plane`
5. `Execution Artifact Plane`
6. `Memory + Telemetry Plane`

推荐的主流程：

```text
User Task
  -> Planner compiles a task DAG
  -> Memory pre-check
  -> Retriever fan-out (0..N)
  -> local prune / evidence pack
  -> Executor (optional, only if task requires tools/code)
  -> Summarizer
  -> Memory commit + telemetry emit
```

关键变化不是把四角色删掉，而是：

- 允许某次任务不经过 Executor
- 允许某次任务并行触发多个 Retriever
- 允许 replay 后直接跳过 retrieve/execute

---

## 6. 角色模型与 Planner 设计

## 6.1 角色家族仍保留四类

`v2` 首版仍然保留固定角色家族：

1. `Planner`
2. `Retriever`
3. `Executor`
4. `Summarizer`

这样做的原因很简单：

- 赛题要求友好
- 分工明确
- 实现复杂度可控
- 与 `v1` 的命名和认知连续

### 但要改变的不是“角色集合”，而是“路径是否固定”

当前不再把主路径理解成：

```text
Planner -> Retriever -> Executor -> Summarizer
```

而是：

```text
Planner -> compile DAG
then runtime decides which nodes are actually needed
```

## 6.2 Planner 的真实职责

`v2` 中 Planner 不是“第一步先说两句”的 LLM 节点，而是四件事的组合：

1. 任务图编译器
2. L2 记忆命中决策器
3. 角色派发器
4. 失败后的重规划器

### Planner 的输入

- 用户任务
- task family schema
- memory match result
- corpus availability
- tool registry

### Planner 的输出

- 一个 task DAG
- 每个 step 的 role/capability/input_refs/output_contract
- 当前任务允许的 replay level

### Planner 的异常职责必须显式建模

这是 `v2` 必须补上的工程约束。

只要 `Executor` 进入真实 `CodeAct`，失败就不再是边缘情况，而是默认情况之一。因此 Planner 不能只是“编一次图然后等结果”，还必须处理运行时异常路由。

建议把这部分按“中断/陷入”思路建模：

1. 任意 step 失败后，都要通过 `Control Channel` 发出结构化 `SYS_ERROR` 或 `STEP_TRAP` 事件
2. 事件内容至少包含：
   - `trace_id`
   - `step_id`
   - `error_class`
   - `retry_count`
   - `last_artifact_refs`
   - `suggested_fallback`
3. Planner 收到 trap 后，需要决定：
   - 原步骤重试
   - 切到备用 capability
   - 截断后续子图
   - 编译 fallback DAG
   - 整体失败并返回受控解释

### 推荐的 fallback 规则

`MVP` 建议先支持三类 fallback：

1. `retry_same_step`
   - 适合临时执行错误、轻度格式错误
2. `downgrade_execution_goal`
   - 例如放弃画图，只做表格提取或文本总结
3. `skip_downstream_branch`
   - 例如某个分析分支失败，但主结果仍可继续生成

### 建议的 trap packet

```json
{
  "event": "SYS_ERROR",
  "trace_id": "task_20260626_17",
  "step_id": "execute_plot",
  "role": "executor",
  "error_class": "python_runtime_error",
  "retry_count": 3,
  "stderr_ref": "artifact_000301",
  "suggested_fallback": "downgrade_to_text_summary"
}
```

## 6.3 DAG 不必设计成庞大工作流系统

`v2` 里 DAG 只需要足够表达运行时编排即可。

建议的 step schema：

```json
{
  "step_id": "retrieve_semantic_chunks",
  "role": "retriever",
  "capability": "semantic_retrieve",
  "depends_on": ["plan_ok"],
  "inputs": ["task_query", "memory_match_result"],
  "outputs": ["evidence_bundle_ref", "embedding_matrix_ref"],
  "retry_policy": {"max_retries": 1},
  "can_skip_if": "memory.exact_replay_hit",
  "on_error": {
    "trap_to_planner": true,
    "fallback_action": "downgrade_or_replan"
  }
}
```

Planner 不需要编译任意图灵完备流程，只需要支持：

- fan-out
- fan-in
- optional step
- replay skip
- fallback

这已经足够覆盖赛题需要的复杂性。

---

## 7. 三通道模型

这是 `v2` 的核心。

## 7.1 为什么不是“一切都走 IPC”

`IPC` 只适合传控制信号和轻量引用，不适合直接承载所有业务对象。

因此三通道要分清：

- 控制消息放哪
- 语义中间态放哪
- 执行产物放哪

### 总原则

1. 小而频繁的对象走 `Control Channel`
2. 大而结构化的语义状态走 `Semantic State Channel`
3. 大而稳定、需要回放和展示的结果走 `Execution Artifact Channel`

## 7.2 Control Channel

### 职责

传“要做什么”。

### 内容

- `task_id`
- `trace_id`
- `step_id`
- `sender_role`
- `target_role`
- `capability`
- `action`
- `input_refs`
- `deadline_ms`
- `retry_policy`
- `priority`

### 推荐实现

`MVP`

- `AF_UNIX / UDS`
- `MessagePack` 或 `Protobuf`

`Conditional`

- `ZeroMQ`

### 为什么它能降本

因为角色之间不再通过文本说：

> 我找到一堆资料了，你帮我做个总结

而是直接发结构化动作：

```json
{
  "action": "summarize",
  "input_refs": ["artifact://result_20260625_001", "state://evidence_bundle_003"]
}
```

## 7.3 Semantic State Channel

### 职责

传“为了决策和筛选需要看的语义中间态”。

### 典型对象

- `embedding_matrix`
- `feature_bundle`
- `topk_evidence_ids`
- `route_hint`
- `memory_match_result`
- `table_cell_candidates`
- `structured evidence pack`

### 推荐实现

`MVP`

- `file-backed mmap`
- Python `multiprocessing.shared_memory`
- 本地 `FAISS`

### 使用原则

这条通道的对象不是最终要给用户看的答案，而是：

- 用来做本地相似度计算
- 用来做 route/tool narrowing
- 用来决定是否需要 hydrate 原文
- 用来决定是否命中历史策略

### 为什么它是真正的非文本主线

如果上游检索拿到 10 万字文档，先切块并向量化，下游就可以在不调用 LLM 的情况下完成：

1. 语义粗排
2. top-k 证据筛选
3. memory match

最终只有最相关的小部分文本进入 LLM。

这就是 `v2` 里 token 节省的主要来源之一。

## 7.4 Execution Artifact Channel

### 职责

传“真正执行出来的产物”。

### 典型对象

- `analysis.py`
- `stdout.txt`
- `stderr.txt`
- `result.json`
- `table.csv`
- `plot.png`
- `extracted_table.json`
- `cleaned_dataset.parquet`

### 为什么它必须单独列出来

因为这些对象和 embedding/feature bundle 不是一类东西：

- 生命周期不同
- 消费者不同
- 安全风险不同
- 复用方式不同

例如：

- `embedding_matrix` 用来决定“该不该看”
- `plot.png` 用来决定“最终报告里怎么展示”
- `analysis.py` 用来决定“下次能不能直接复用代码模板”

如果不把它独立出来，系统会重新滑回“所有东西最后都变成 prompt 文本”的老路。

### 推荐实现

`MVP`

- 本地 artifact store
- 内容哈希命名
- `ArtifactRef` 通过控制面引用

`Conditional`

- 轻量 CAS

## 7.5 Ephemeral Neural State

### 状态

`Future Work`

### 内容

- `KV cache`
- `prefix state`
- 其他底层推理张量引用

### 结论

它应该被明确写成：

- 接口预留
- 报告增强点
- 非 `MVP` 主线

不要让它吞掉 `v2` 第一阶段的工程重心。

---

## 8. 引用模型：`StateRef`、`ArtifactRef`、`MemoryRef`

`v2` 不应只保留一个笼统的 `StateRef`。

建议拆成三类显式引用：

### 8.1 `StateRef`

用于 `Semantic State Channel`。

建议字段：

```json
{
  "ref_id": "state_000123",
  "kind": "embedding_matrix",
  "storage": "shared_memory",
  "handle": "psm_xxx",
  "shape": [1024, 384],
  "dtype": "float32",
  "checksum": "sha256:...",
  "producer_step": "retrieve_semantic_chunks"
}
```

### 8.2 `ArtifactRef`

用于 `Execution Artifact Channel`。

建议字段：

```json
{
  "ref_id": "artifact_000045",
  "kind": "plot_png",
  "path": "artifacts/20260625/task_17/plot.png",
  "mime": "image/png",
  "checksum": "sha256:...",
  "content_address": "sha256:...",
  "producer_step": "execute_plot"
}
```

### 8.3 `MemoryRef`

用于指向 L2 中已经验证过的策略、证据或回放对象。

建议字段：

```json
{
  "memory_id": "mem_20260625_014",
  "memory_type": "validated_replay",
  "score": 0.91,
  "replay_class": "validated_replay"
}
```

### 8.4 生命周期原则

1. `StateRef` 偏短生命周期
2. `ArtifactRef` 可跨任务保存
3. `MemoryRef` 必须可审计、可解释、可拒绝

### 8.5 内容寻址与全局去重

这里建议把 `checksum` 从“校验字段”升级成明确的 `CAS` 设计。

核心原则：

1. `Semantic State Plane` 与 `Execution Artifact Plane` 的大对象都以内容哈希命名
2. 相同内容只存一份
3. 引用层只传 `StateRef` / `ArtifactRef`

这意味着：

- 两个任务处理同一份财报并生成同一份 embedding matrix 时，不需要存两份
- 两个步骤产出相同的清洗后 CSV 时，不需要存两份
- replay 也可以更稳定地引用内容等价对象，而不是依赖脆弱的路径命名

这既是工程降本机制，也是答辩时很强的“系统级低开销”亮点。

---

## 9. L1 / L2 / L3 存储与记忆设计

`some_think` 中关于缓存层级的思路是对的，但 `v2` 需要更细。

## 9.1 L1：会话级工作集

### 内容

- 当前 DAG 的 step outputs
- 当前任务的 state refs
- 当前任务的 artifact refs
- 当前 memory match result

### 载体

- 进程内内存
- `mmap`
- `shared_memory`

### 特征

- 快
- 不要求长期持久化
- 服务于单次任务

## 9.2 L2：共享语义缓存

这是 `v2` 的主共享记忆层。

### 存储技术

- `SQLite`
- `FAISS`
- 本地文件系统

### 内部分三类子缓存

#### 1. Strategy Cache

存：

- task graph template
- plan fragments
- route/tool combos
- code templates
- prior successful strategies

#### 2. Semantic Evidence Cache

存：

- chunk refs
- embedding refs
- feature bundles
- evidence hashes
- extracted table signatures

#### 3. Execution Artifact Cache

存：

- code files
- stdout/stderr
- result.json
- csv/png
- replay-ready artifacts

### L2 提交必须受成功条件约束

这里必须补一个很关键的防坑规则：不是任何产生过的代码和结果都能进入 L2。

建议 `MVP` 明确两条提交门槛：

1. 只有 `success=true` 且 step 完成度满足合同要求的执行结果，才允许进入候选记忆
2. 只有最终被 Summarizer 采纳并进入最终 answer / final evidence 的策略与产物，才允许正式 `MemoryCommit`

也就是说，`L2` 不应该存“所有试错过程”，而应该区分：

- debug artifacts
- candidate artifacts
- committed artifacts

### 脏数据与缓存污染

如果第一次 `CodeAct` 产出的代码或表格是错的，而系统直接把它作为 `exact_replay` 依据保存，下次命中就会把错误放大。

因此建议给 `MemoryCommit` 增加有效性字段：

- `commit_status`: `candidate | committed | invalidated`
- `validation_status`: `unchecked | passed | failed`
- `answer_adopted`: `true | false`

只有满足：

- `commit_status=committed`
- `validation_status=passed`
- `answer_adopted=true`

的对象，才允许进入 `validated_replay` 或 `exact_replay` 检索面。

### 缓存失效与版本漂移

`Future Work` 可进一步增加：

1. 文档内容哈希
2. 任务 schema 版本
3. 工具链版本
4. 代码模板版本

只要下列任一项变化，就自动降低 replay 等级或直接失效：

- 底层文档哈希变化
- 关键工具输出结构变化
- 任务合同字段变化

这相当于 `v2` 的缓存失效协议。

## 9.3 L3：原始语料与大对象仓

### 内容

- 原始 `txt/html/csv/json` 语料
- 清洗后的表格与 canonical text surface
- 大体积中间文件

`PDF` 可以存在于 L3，但不应成为 `MVP` formal benchmark 的前置依赖。
更稳的首版策略是优先使用已经 canonicalize 完成的本地文本面和表格面，避免把 PDF 抽取稳定性混入主实验变量。

### 结论

L3 不是推理层，而是证据和大对象底座。  
L2 只保存复用所需的索引、模板、签名和引用。

## 9.4 复用等级沿用既有经验，但语义更清楚

这一点建议直接吸收既有经验。

### `assist`

- 命中历史经验
- 只作为参考，不跳步

### `validated_replay`

- 命中可复用策略或结果
- 跳过部分步骤，例如跳过 execute

### `exact_replay`

- 命中足够强的等价条件
- 跳过 retrieve + execute

### `v2` 必须继承的边界

1. `hit != benefit`
2. `assist` 命中不能自动包装为收益
3. 必须同时报告：
   - `skipped_step_count`
   - `reuse_gain`
   - `replay_class`

---

## 10. Retriever 设计

这是 `v2` 与很多 demo 最大的分水岭。

## 10.1 不能再接受“伪检索”

`v2` 的 Retriever 不能只是：

- 让 LLM 写一段像检索结果的文本
- 再把它交给下游

它必须至少连接一种真实知识源：

- 本地 `txt/html/csv/json` 语料库
- 本地结构化数据文件
- 预先 canonicalize 好的表格面与文本面

`MVP` 不把联网抓取、PDF 原位解析、OCR 作为 formal benchmark 前提。
这些能力可以保留给 demo 或后续增强，但首版评测最好锁定在离线本地、格式稳定、可重复抽取的语料上。

## 10.2 推荐的三类差异化 Retriever

如果要保留“三个 retriever 并行 fan-out”的设计，建议做成三类能力，而不是三个同质角色。

### Retriever-A：Lexical / Metadata Retriever

职责：

- 标题、元数据、时间、公司名、章节名、表格标题等快速过滤

适用：

- 先缩小候选文档集合

### Retriever-B：Semantic Chunk Retriever

职责：

- 文档切块
- embedding 生成
- 语义相似度 top-k

适用：

- 长文档证据筛选

### Retriever-C：Structure / Table Retriever

职责：

- 面向表格、数值字段、季度指标、列名模式的检索

适用：

- 财报、销量表、报表类任务

### 为什么这样设计更好

因为它们对应三种不同信号：

1. 元数据过滤
2. 语义内容过滤
3. 结构化数值过滤

这比三个完全同质的“都去找点文本”更能体现多 Agent 的真实分工。

## 10.3 Retriever 的标准输出

每个 Retriever 应输出：

1. `evidence_bundle_ref`
2. `embedding_matrix_ref` 或 `feature_bundle_ref`
3. `retrieval_log_ref`
4. `confidence / coverage / recall proxy`

Planner 或 fan-in 节点再决定：

- 是否需要 hydrate 原文
- 是否需要交给 Executor
- 是否直接进入 Summarizer

---

## 11. Executor / CodeAct 设计

`v2` 必须把当前“实验边上的 CodeAct”升级为主路径之一。

## 11.1 Executor 的职责

不是所有任务都要写代码，但一旦任务涉及：

- 数值计算
- 数据清洗
- 表格提取
- 绘图
- 文件转换

就必须优先走执行路径，而不是让 LLM 凭空口述结果。

## 11.2 标准执行流

```text
receive task + refs
  -> load filtered evidence / structured table
  -> ask model for code or reuse cached template
  -> materialize inputs into mounted workspace
  -> run code in sandbox
  -> capture stdout/stderr/files
  -> optional repair loop
  -> emit ArtifactRefs
```

## 11.3 为什么 `Execution Artifact Channel` 是关键

因为 `Executor` 产出的真正价值不是一句摘要，而是：

- 代码本身
- 执行日志
- 数据文件
- 图表
- JSON 结果

这些对象在 `v2` 中既是：

- 用户可见结果的一部分
- 后续任务可复用记忆的一部分

## 11.4 沙箱分阶段推进

### `MVP`

- `subprocess`
- `timeout`
- `tempdir`
- 资源限制
- 明确允许的依赖白名单

### 11.5 必须补上 VFS / 挂载协议

这是 `Execution Artifact Channel` 真正可运转的前提。

问题不是“代码能不能跑”，而是：

- 上游产物如何稳定进入沙箱
- 下游产物如何稳定离开沙箱
- 大模型如何知道输入输出路径约定

建议在 `v2` 中统一定义一个任务级工作区：

```text
Workspace_DIR/
  inputs/
  outputs/
  scratch/
  logs/
  manifest.json
```

执行协议如下：

1. 运行时为每个 task step 创建独立 `Workspace_DIR`
2. 将上游 `ArtifactRef` 或 `StateRef` hydrate 后写入 `inputs/`
3. 执行器只允许在该工作区内读写
4. 代码产出的所有结果必须写到 `outputs/`
5. 运行结束后由 artifact collector 扫描 `outputs/` 并生成新的 `ArtifactRef`

### 大模型代码提示必须强注入路径约束

Prompt 中必须固定注入类似系统规则：

> 你的所有输入文件都位于 `/data/inputs/`。你的所有输出文件必须写到 `/data/outputs/`。不要访问其他路径。

### `MVP` 与 `Conditional` 的挂载方式

`MVP`

- `subprocess` + `cwd=Workspace_DIR`
- 明确只允许相对路径或工作区内绝对路径

`Conditional`

- `iSula run -v Workspace_DIR:/data`
- 在容器内固定 `/data/inputs` 与 `/data/outputs`

这部分如果不先定义，后面 artifact path 会快速失控。

### 11.6 执行失败后的 repair loop 与 trap

执行器需要把失败视为结构化事件，而不是只打印 stderr。

建议规则：

1. 每次失败都产出 `stderr_ref`
2. 每次失败都递增 `retry_count`
3. 超过阈值后触发 `SYS_ERROR` 发回 Planner
4. Planner 决定继续修复、换模板、还是降级执行目标

### `Conditional`

- `chroot` / 更强隔离
- `iSula`

### `Future Work`

- 更强容器/微 VM 隔离

### 原则

不要因为“终极沙箱还没做完”就把 CodeAct 放回实验角落。

---

## 12. Summarizer 设计

`v2` 的 Summarizer 不能再作为“什么都喂给它，它负责写好看答案”的垃圾桶角色。

## 12.1 Summarizer 的输入应被压缩

优先读取：

- `result.json`
- `table.csv`
- `plot.png` 的说明信息
- 已裁剪的 evidence bundle
- `MemoryRef`

只在必要时 hydrate 原始文本。

## 12.2 Summarizer 的职责

1. 合成最终回答
2. 解释结果来源
3. 生成面向记忆的 summary
4. 触发 `MemoryCommit`

## 12.3 建议输出

- `final_answer.md`
- `evidence_summary.json`
- `memory_commit_candidate.json`

---

## 13. 历史经验的吸收边界

`v2` 是独立系统设计，不应被理解为对任何既有实现的线性升级。

### 13.1 可吸收的历史经验

以下内容属于“经验约束”，不是“必须继承的代码外壳”：

1. `StateRef / StatePool` 这类状态引用抽象是成立的
2. `mmap + shared_memory` 双后端思路是成立的
3. `SQLite + FAISS` 作为共享记忆底座是成立的
4. `assist / validated_replay / exact_replay` 的复用分层是成立的
5. `hit != benefit`
6. `internal comparator != external pure-text baseline`
7. claim 必须和 evidence 对齐

### 13.2 不继承的历史前提

以下内容不应被带入 `v2` 默认设计：

1. 固定线性四步图
2. incident/playbook 风格 sample tasks
3. 以 assist-style memory 注入为主要收益路径
4. host-first 作为长期主开发前提
5. 把当前 runtime 外壳视为必须延续的基础

### 13.3 `v2` 的独立决策原则

判断一个设计点是否进入 `v2`，优先级应当是：

1. 是否服务 `v2` 的目标系统模型
2. 是否能在 formal benchmark 中被稳定证明
3. 是否能在工程上形成清晰合同

而不是：

1. 既有代码里是否已经有类似模块
2. 旧目录结构是否方便复用
3. 历史实现是否容易平滑迁移

---

## 14. `v2` 推荐目录结构

建议在新分支或新实现目录里按下面方式组织：

```text
v2/
  agents/
    planner/
    retrievers/
      lexical.py
      semantic.py
      table.py
    executor/
    summarizer/
  runtime/
    planner_compiler.py
    dag_runtime.py
    scheduler.py
    control_bus.py
    replay_engine.py
  protocol/
    control_messages.py
    refs.py
    schemas.py
  state/
    state_pool.py
    embedding_store.py
    feature_bundle.py
  artifacts/
    artifact_store.py
    manifest.py
  memory/
    sqlite_store.py
    faiss_index.py
    strategy_cache.py
    replay_cache.py
  tasks/
    families/
    corpora/
    specs/
  eval/
    benchmark_runner.py
    comparators.py
    telemetry.py
  ui/
    backend/
    frontend/
  docs/
    ...
```

`v2/` 子目录是当前冻结方案的一部分。除非后续明确做完成替换，否则不建议把 `v2` clean-room 直接摊回当前顶层目录。

---

## 15. 任务设计：什么样的任务才能把 `v2` 的优势打出来

这是 `v2` 成败的关键之一。

## 15.1 任务设计原则

任务必须同时满足：

1. 有真实外部语料或本地文档
2. 有长文本或大表格，能体现 embedding 剪枝价值
3. 有代码执行环节，能体现 CodeAct 价值
4. 有连续任务，能体现 memory replay 价值
5. 结果可验证，不能只靠语言描述

### 还要再补三条“评审友好”原则

1. `高噪音`
   - 原始语料中必须存在大量无关内容，否则剪枝优势不明显
2. `强动作`
   - 至少一部分任务必须触发真实代码执行、真实表格处理或真实图表生成
3. `连续复用`
   - 后续任务必须能够清楚复用前一任务的策略、证据或产物，而不是只共享主题背景

### `MVP` 数据源收口建议

首版 formal benchmark 建议只依赖：

1. repo-local 或容器内挂载的 `txt/html/csv/json`
2. 预先抽取并冻结版本的 canonical text surface
3. 预先清洗并冻结 schema 的表格面

不建议把下面对象放进首版必要路径：

1. OCR
2. PDF 原位 byte-level 溯源
3. 联网抓取
4. 动态网页 DOM 回放

原因不是这些对象没价值，而是它们会把评测变量从“StateBus 机制”污染成“抽取器稳定性与外部环境稳定性”。

## 15.2 推荐任务家族 A：财报 / 经营数据分析

这是最推荐的主线。

### 任务 A1：冷启动

用户输入：

> 分析 TSLA 与 BYD 在 2023 年各季度毛利率，提取原始数值，计算年均差值，并生成折线图。

执行流：

1. Planner 拆成：
   - 检索财报文档
   - 提取表格证据
   - 代码计算
   - 总结输出
2. Retriever-A 先按公司/年份/季度定位文档
3. Retriever-B 对长文档切块并向量化
4. Retriever-C 定位表格与毛利率字段
5. Executor 写并执行数据提取/清洗/绘图代码
6. Summarizer 汇总结果
7. 系统沉淀：
   - 代码模板
   - 提取出的结构化表格
   - 任务 summary

### 任务 A2：增量复用

用户输入：

> 在刚才的分析基础上，把 NIO 的 2023 年毛利率也加进来，重算三者的方差，并更新图表。

预期复用：

- TSLA/BYD 文档 embedding 直接复用
- 已跑通的提取与绘图代码模板复用
- 只新增 NIO 的文档检索与字段提取

### 任务 A3：递进分析

用户输入：

> 对比 TSLA 2023Q4 与 2022Q4 毛利率差异，并解释变化的可能原因。

预期复用：

- TSLA 2023 数据直接命中
- 已有图表与结构化表格直接复用
- 只补 2022Q4 相关材料

### 为什么它仍然是正式 benchmark 首选

虽然它没有“代码安全审计”那样戏剧化，但它更适合作为正式证据对象，因为：

1. 数据结构稳定
2. 结果可验证
3. 图表和数值结果容易复核
4. 更容易把“剪枝收益”和“回放收益”拆开归因

## 15.3 推荐任务家族 B：新能源销量与驱动因素

这是 `some_think` 里给出的路线，也可作为备选。

优点：

- 叙事自然
- 连续任务容易设计

缺点：

- 数据源和口径更容易漂
- 比财报类任务更难保证“结构化可验证”

因此建议：

- 作为答辩叙事可以保留
- 作为正式 benchmark 主线，优先财报/报表类任务

## 15.4 可作为 Demo 场景，但不建议直接做 formal headline 的任务

下面这些任务很适合作为现场展示或补充案例，但不建议一上来承担 formal headline：

### Demo-B1：本地代码仓审计

这个方向的优点很明显：

- 高噪音
- 强动作
- 与 `CodeAct` 高度契合
- exact replay 的可视化效果很强

但它的 formal 风险也更高：

- 评委容易质疑漏洞判定标准
- 结果正确性比财报/表格类任务更难标准化
- 如果设计成真实攻击 PoC，容易把展示带向不必要的安全争议

因此推荐改写为：

- 面向本地、受控、非联网的教学代码仓
- 以“规则复检 / 静态检查 / 单元测试复跑”作为主动作
- 避免把真实攻击脚本作为正式 benchmark 中心

### Demo-B2：大型文本文档面 + Excel/CSV 联合处理

这是非常好的第二展示场景：

- 能直观看到大对象和共享内存
- 能直观看到表格更新后图表瞬时刷新

但作为 formal headline 时要额外控制：

- canonical text 抽取口径
- 表格列名漂移
- 数据源版本锁定

如果后续确实要接 PDF，建议把 PDF 先离线抽取成 canonical text/fragment surface，再进入 `v2` 主链路，而不是让 formal benchmark 直接依赖 PDF 解析过程。

## 15.5 建议把任务分成两层

`v2` 最稳妥的做法不是只押一个任务家族，而是区分：

### Formal Benchmark Tier

用于报告、主表、claim release。

建议选择：

- 财报 / 报表 / 供应链表格类任务

要求：

- 数据稳定
- 可复验
- 指标口径清楚
- 不依赖评委主观理解

### Demo / Live Showcase Tier

用于答辩现场、Dashboard 展示、冲击感。

可以选择：

- 本地代码仓规则审计
- 大型文本文档面 + CSV 动态更新

要求：

- 强视觉反馈
- 强 replay 效果
- 强“系统在真干活”的感受

## 15.6 不推荐的主 benchmark 任务

1. 纯 incident/playbook route 任务
2. 没有真实外部语料的问答
3. 没有代码环节的纯总结任务
4. 高争议、难标准化判定正确性的开放式安全任务

这些任务不足以把 `v2` 的三条主线全部打出来。

---

## 16. A/B 对比设计

`v2` 必须从一开始就设计“比较什么、不比较什么”。

## 16.1 从简单 A/B 升级为可归因的消融梯度

这部分建议直接吸收“瀑布流消融实验”的思想。

正式 benchmark 不应只提供一个粗糙的二元 `text vs protocol` 表，而应提供 `L0 -> L3` 的分级运行合同，并明确每一层的收益归因。

### `L0`：Traditional Chatty Baseline

- 全文本通信
- 全量证据文本进入 LLM
- 无共享内存剪枝
- 无 replay
- 每次从零规划和生成代码

### `L1`：Structured Control Only

- 开启结构化控制面
- 仍然全量文本喂给 LLM
- 无本地语义剪枝
- 无 replay

目标：

- 证明控制面主要减少的是通信/调度开销，而不是 magically 节省了大部分 LLM token

### `L2`：Structured Control + Semantic Pruning

- 开启 `L1`
- 开启 embedding/shared-memory 剪枝
- 无 replay

目标：

- 证明 `raw_evidence_bytes_seen_by_llm` 和 prompt token 的主下降来自语义状态面

### `L3`：Full StateBus Runtime

- 开启 `L1 + L2`
- 开启 `assist / validated_replay / exact_replay`

目标：

- 证明进一步节省的是 completion token、规划成本和步骤数，而不是只省输入 token

### 为什么这个梯度更强

因为它把三个核心收益来源拆开了：

1. 控制面
2. 语义剪枝
3. 记忆回放

这样评委即使追问“到底是谁贡献了收益”，也可以直接给出归因结果。

## 16.2 至少要拆成三组对比

### 对比组 1：控制面与 handoff 对比

比较：

- `text_open_baseline`
- `structured_control + refs`

目标：

- 验证控制面字节数和 handoff 复杂度下降

### 对比组 2：非文本状态剪枝效果

比较：

- `full_text_feed`
- `embedding_prune_then_feed`

目标：

- 验证真正减少进入 LLM 的证据文本体量

### 对比组 3：记忆复用等级

比较：

- `reuse_disabled`
- `assist`
- `validated_replay`
- `exact_replay`

目标：

- 验证哪些复用真正带来跳步与收益

### 对比组 4：L0-L3 总梯度

比较：

- `L0`
- `L1`
- `L2`
- `L3`

目标：

- 形成答辩时可直接展示的总成本瀑布图和总收益拆解图

## 16.3 必须新增的指标

`v2` 建议至少统一统计：

1. `control_bytes`
2. `control_message_count`
3. `semantic_state_bytes`
4. `semantic_state_transfer_count`
5. `artifact_bytes`
6. `artifact_reuse_count`
7. `raw_evidence_bytes_seen_by_llm`
8. `llm_prompt_tokens`
9. `llm_completion_tokens`
10. `task_ms`
11. `memory_hit_rate`
12. `skipped_step_count`
13. `reuse_gain`
14. `replay_class_distribution`
15. `planner_replan_count`
16. `exact_replay_bypass_steps`
17. `estimated_api_cost_saved`

### 其中最关键的新指标

`raw_evidence_bytes_seen_by_llm`

因为它能直接回答：

> embedding 剪枝到底有没有减少真正进入 LLM 的文本量？

### 第二关键指标

`estimated_api_cost_saved`

它不应取代 token 指标，但它能把技术节省转换成更直观的工程和商业意义。

## 16.4 必须避免的误读

1. 不能把内部 `text_whole_lane` 直接说成 external pure-text baseline
2. 不能把 memory hit 直接说成收益
3. 不能把“有 shared memory 使用”直接说成“token 一定暴降”
4. 不能把 conditional/future work 写成已实现主线
5. 不能把 `L0` baseline 刻意设计成不公平的“弱智对手”

## 16.5 Baseline 公允性合同

这是正式报告里必须单独写清楚的内容。

### 原则 1

我们对标的不是“最差系统”，而是“最主流的群聊式多 Agent 做法”：

- 文本拼接
- 历史消息直接进入上下文
- 无共享内存
- 无本地向量剪枝
- 无 replay

### 原则 2

`L0` 不允许故意做蠢：

- 不能重复注入明显无关的大段文本
- 不能故意放大 prompt 模板
- 不能在明知可缓存的情况下人为增加重复读取

### 原则 3

剪枝收益应被解释为 `compute offloading`

也就是：

- 用便宜的 CPU/本地向量计算
- 替代昂贵的 LLM 上下文阅读

这不是作弊，而是工程上的算力分层。

---

## 17. 为什么 `Embedding + 剪枝` 够不够

这个问题需要直接回答。

## 17.1 仅靠 embedding，不够

如果只是：

1. 上游生成 embedding
2. 下游还是把大段原文全塞进 LLM

那它只减少了进程间传输字节，不会显著减少 LLM token。

## 17.2 但 `Embedding + 本地剪枝` 对 `MVP` 足够重要

只要任务满足“长文档、多 chunk、大量无关上下文”，那么：

1. 上游先切块向量化
2. 下游在本地算相似度
3. 只 hydrate top-k 小部分文本

就会显著减少：

- `raw_evidence_bytes_seen_by_llm`
- `llm_prompt_tokens`

对于首版 `v2`，这是完全足够成立的非文本主线。

## 17.3 真正的大收益来自组合

`v2` 的主要收益不是“只靠 embedding 一招鲜”，而是：

1. 结构化控制面减少文本 handoff
2. embedding 剪枝减少证据摄入
3. artifact 复用减少重复代码和重复结果生成
4. replay 减少步骤数量

## 17.4 KV Cache 的位置

KV Cache 不是 `v2` 首版必要条件。

正确表述应当是：

- 对黑盒 API：主打 `Embedding + pruning`
- 对本地模型：可以探索 `Ephemeral Neural State`

这样体系是完整的，但不会把 `v2` 的可交付性押在高风险特性上。

---

## 18. Dashboard / Telemetry 设计

这部分值得做，因为它能把基础设施层优势可视化。

## 18.1 后端建议

`MVP`

- `FastAPI`
- `WebSocket`
- telemetry aggregator

FastAPI 官方文档明确支持 WebSocket 端点、`accept()`、循环收发消息以及多连接管理，适合做实时 telemetry 推送。  
参考：<https://fastapi.tiangolo.com/advanced/websockets/>

## 18.2 前端建议

优先级：

1. `React/Vue + ECharts`
2. 如果前端资源有限，退化到 `Streamlit`

## 18.3 页面建议按三平面展示

### 控制面

- 当前 task DAG
- 正在执行的 step
- control bytes / message count
- agent topology

### 语义状态面

- 共享内存对象数
- embedding matrix 大小
- top-k 剪枝前后对比
- memory match result

### 执行产物面

- 当前代码
- stdout/stderr
- 结果表格
- 图表预览
- 复用命中情况

### 指标看板

- token 曲线
- latency 曲线
- replay 命中
- `raw_evidence_bytes_seen_by_llm`
- API 成本节省估算
- 计算卸载量估算

### 18.3.1 强烈建议增加“成本瀑布图”

如果前端精力够，最值得增加的不是再多一张折线图，而是一张 `Waterfall Chart`。

它用于展示：

- `L0` 的总成本
- `L1` 因控制面减少的那一小段
- `L2` 因语义剪枝减少的最大一段
- `L3` 因 replay 和代码模板复用再减少的一段

这样可以一眼看出：

- 通信节省贡献多少
- 剪枝节省贡献多少
- 回放节省贡献多少

这比单纯贴四行对比表更有说服力。

### 18.4 推荐的视觉事件

如果要把 Dashboard 做成真正的“评审级作品”，推荐把以下事件显式动画化：

1. `Semantic Page Fault`
   - 当系统只从长文档中 hydrate top-k chunk 时触发
2. `Validated Replay Hit`
   - 命中部分回放时显示黄色或蓝绿色高亮
3. `Exact Replay Hit`
   - 命中完整回放时显示明显绿色脉冲
4. `Planner Replan`
   - trap 触发后显示 DAG 被截断并重编译

### 18.4.1 可做但必须降级为“展示增强”的元素

下面这些内容很适合做炫酷展示，但不能在文档里暗示它们比正式 benchmark 更重要：

1. 十六进制共享内存 dump 视图
2. 动态光点拓扑流
3. 极客风格地址指针动画

正确定位应是：

- `demo enhancer`
- `telemetry surface`
- 不替代 formal metrics

### 18.5 商业化指标

除系统指标外，建议增加一组直观但不夸张的换算指标：

1. `estimated_api_cost_saved`
2. `estimated_prompt_tokens_avoided`
3. `compute_offload_ratio`

其中 `estimated_api_cost_saved` 必须基于明确价格假设，并在 UI 上写清口径，避免伪精确。

---

## 19. 技术选型建议

## 19.1 首选组合

### `MVP`

- 控制面：`UDS + typed Protobuf`
- 状态面：`mmap + multiprocessing.shared_memory`
- 记忆：`SQLite + FAISS`
- 执行：`subprocess` 受限执行
- UI：`FastAPI + WebSocket`
- 对象存储：本地内容寻址 artifact/state store

### `Conditional`

- 控制总线：`ZeroMQ`
- 容器化执行：`iSula`

## 19.2 选型理由

### `multiprocessing.shared_memory`

Python 官方文档明确说明它支持“shared memory for direct access across processes”，并强调共享内存可以避免通过 socket 或磁盘传输数据时的序列化/反序列化与拷贝成本。  
参考：<https://docs.python.org/3/library/multiprocessing.shared_memory.html>

在单容器 `openEuler` 目标下，这条能力应重新升格为正式候选，而不是先验降级项。

但仍需注意：

1. 它依赖容器内 `/dev/shm` 容量，Docker 的 `--shm-size` 会直接影响可用性
2. 它更适合短生命周期、高吞吐、多进程共享的 embedding/state bundle
3. 如果后续需要更强 replay/审计/持久化，`mmap` 仍有天然优势
4. Python 官方文档还说明对于 standalone Python 进程场景，若已有其他进程负责共享内存生命周期管理，可考虑 `track=False`，否则 resource tracker 可能在第一个相关进程退出时提前删除共享内存块

### `ZeroMQ`

ZeroMQ 官方文档强调其 socket 抽象本质上是异步消息队列，并提供 request-reply、pub-sub、pipeline 等模式；对 `v2` 的消息总线很适合作为增强项。  
参考：<https://zeromq.org/socket-api/>

### `iSula`

`iSulad` 官方仓库将其描述为轻量级容器引擎，适合 openEuler 环境下的增强型执行隔离，但这不应成为首版前置依赖。  
参考：<https://gitee.com/openeuler/iSulad>

### `CAS`

虽然 `CAS` 不依赖单一外部产品，但设计上建议直接采用：

- 内容哈希作为存储键
- manifest 记录 ref 与 producer/consumer 关系
- dedup 作为默认行为

这样能同时服务：

- artifact 去重
- state 去重
- replay 引用稳定性
- 失效判断

---

## 20. 分阶段实施路线

## 20.1 Phase 0：Clean-room 骨架

输出：

1. 新 runtime 目录骨架
2. `ControlMessage / StateRef / ArtifactRef / MemoryRef`
3. 基础 DAG schema
4. 最小任务 runner
5. trap / fallback message schema

验收：

- 单机上四角色空跑
- 控制面消息可追踪

## 20.2 Phase 1：Control Plane + Semantic State Plane

输出：

1. `UDS + typed Protobuf` 控制面
2. `mmap/shared_memory` 状态面
3. embedding 生成与传递
4. 本地 top-k 剪枝

验收：

- 能看见非文本状态真实传递
- 能统计 `raw_evidence_bytes_seen_by_llm`

## 20.3 Phase 2：真实 Retriever

输出：

1. 本地文档语料接入
2. 三类差异化 Retriever
3. fan-out / fan-in
4. evidence bundle 规范
5. `raw_evidence_bytes_seen_by_llm` 计量闭环

验收：

- 不再依赖伪检索文本
- 多 Retriever 输出可汇合

## 20.4 Phase 3：真实 Executor / CodeAct

输出：

1. 代码生成与执行闭环
2. stdout/stderr 捕获
3. artifact store
4. repair loop
5. workspace/VFS 约束
6. planner trap / fallback 联动

验收：

- 能从真实 canonical text surface 与 `csv/json` 表格面中得到结构化结果和图表
- 更稳的首版口径应收紧为：能从真实 `txt/html/csv/json` 或预抽取 canonical surface 中得到结构化结果和图表

## 20.5 Phase 4：L2 Memory + Replay

输出：

1. `Strategy Cache`
2. `Semantic Evidence Cache`
3. `Execution Artifact Cache`
4. `assist / validated_replay / exact_replay`
5. commit validity / invalidation rules

验收：

- 至少一个连续任务家族出现非零 `skipped_step_count`
- `reuse_gain` 可稳定观察

## 20.6 Phase 5：Benchmark + Dashboard + openEuler 收口

输出：

1. 三组对比 benchmark
2. telemetry dashboard
3. openEuler 运行文档
4. 结果报告

验收：

- 能向评委清楚展示：
  - 通信降本
  - 非文本状态
  - 真实执行
  - 记忆复用

---

## 21. 外部与历史参考的使用原则

### 21.1 历史经验只作为素材库

如果要快速推进 `v2`，最值得吸收的不是旧外壳，而是这些经验：

1. claim 和 evidence 必须绑定
2. comparator boundary 必须清楚
3. `hit != benefit`
4. replay 等级必须分层
5. 状态与记忆最好有明确合同和测试

### 21.2 技术材料可参考，但不默认继承

可以参考的技术材料包括：

1. 既有 `StateRef` 设计思路
2. 既有 `mmap/shared_memory` 实现经验
3. 既有 `SQLite + FAISS` 组合经验
4. 既有 replay contract 的测试思路
5. 既有 benchmark 指标组织方式

这些都属于：

- `design material`
- `implementation hints`
- `pitfall archive`

不属于：

- `v2` 的必须继承主壳
- `v2` 的默认 runtime
- `v2` 的强绑定目录结构

---

## 22. 参考实现 `yzm...` 可借什么

目录 [yzmxdzntxzddkxtxztcdygxjyjz](/home/qcrs/statebus/project/yzmxdzntxzddkxtxztcdygxjyjz) 可以作为参考，但只能借结构，不应直接借核心实现。

## 22.1 可借

1. 模块分层方式
2. 把 protocol/runtime/agent/memory/eval 分开组织的习惯
3. 通过 demo 展示三模式对比的表达方式

## 22.2 不可借

1. 伪检索
2. 伪执行
3. 过度乐观的 benchmark 数字
4. 把展示层当控制层

## 22.3 关于“三个 Retriever”

这个思路本身值得保留，但必须改成差异化能力，而不是三个同质 worker。

---

## 23. 风险与未决问题

## 23.1 语料准备风险

如果没有一套干净、可复验、结构稳定的长文档任务语料，`v2` 的优势很难被展示出来。

## 23.2 Memory 误命中风险

如果 `L2` 检索过宽，系统会出现：

- 命中很多
- 真正复用很少
- 甚至 assist 让 prompt 更长

因此 `replay` 条件必须严格。

## 23.3 过度动态化风险

太早上 capability registry、全动态路由和 daemon 化，会让首版难以收口。

## 23.4 沙箱安全风险

CodeAct 必须逐步增强，不要在没有资源隔离和白名单时直接放开任意执行。

## 23.5 仍然模糊、必须继续定死的区域

下面这些点已经被文档点到，但还没有细化到可以直接实现的程度。

### A. Runtime State Machine 仍不够具体

当前已经有 trap/replan 思路，但还缺：

1. step 生命周期枚举
2. ACK / timeout / retry / cancel 的正式状态机
3. scheduler 和 planner 的边界
4. 幂等语义
5. 多进程下的 lease / ownership 合同

如果不先定死，后面实现出来的 bus、worker、planner 会各说各话。

### B. Semantic Object Schema 仍偏概念级

当前文档已经有：

- `StateRef`
- `ArtifactRef`
- `MemoryRef`

但还缺：

1. `hydrate_manifest` 的正式字段结构
2. chunk 与原文 span 的绑定方式
3. state producer / consumer / owner / GC 合同
4. `raw_evidence_bytes_seen_by_llm` 的统计口径实现
5. backend-neutral schema 与 backend-specific metadata 的分层

### C. Replay Admissibility 还需要精确合同

`assist / validated_replay / exact_replay` 已经有方向，但还缺：

1. strict exact replay key 组成
2. validated replay 的规则边界
3. 哪些 drift 会降级为 assist
4. 哪些 drift 会直接 invalidate
5. replay 和 artifact/state CAS 的关系

### D. Retriever Fan-in / Canonical Evidence Pack 还没定型

当前有三类 Retriever，但还缺：

1. merge policy
2. 去重策略
3. 优先级策略
4. canonical evidence pack schema
5. 冲突证据如何仲裁

这部分如果不定，整个 replay、executor 输入和 metrics 都会漂。

### E. CodeAct 的“受限执行”仍然只有方向，没有完整合同

当前已经有：

- `Workspace_DIR`
- 输入输出目录
- 白名单/隔离方向

但还缺：

1. 允许的 import/package 列表
2. stdout/stderr 截断策略
3. 文件大小上限
4. 资源限制的具体实现
5. 网络限制的口径
6. subprocess MVP 与 container conditional 的能力边界

### F. Telemetry Event Schema 还没正式化

Dashboard 已经很具体，但后端事件流还不够具体。

还需要明确：

1. telemetry event type
2. trace_id / step_id / span_id 结构
3. 实时事件和聚合指标的分层
4. 落盘格式
5. Waterfall Chart 的数据来源计算方式

### G. KV Cache / Ephemeral Neural State 仍然最模糊

这是当前文档里最容易被误读、也最该被严格降级的一块。

当前正确结论仍然是：

- 它不是 `MVP`
- 它不是首版 formal benchmark 必需项
- 它不是当前主实现承诺

但如果后面要继续研究，需要先回答至少这些问题：

1. 它服务的是同任务内接力，还是跨任务复用
2. 它是本地模型限定特性，还是要兼容 API 模式
3. 与 `Embedding + pruning` 的关系是替代还是叠加
4. 引用对象是 KV pages、prefix cache 还是别的中间态
5. 生命周期与显存/内存回收怎么做
6. 怎样定义 “0 prefill token saved” 的测量口径

在这些问题没定死前，`KV cache` 只能放在：

- `Future Work`
- `experimental appendix`
- `architecture horizon`

不能进入主路线叙述。

### I. 单容器 openEuler 目标实现会改变取舍

这不是一句“放到 Docker 里就行了”的部署问题，而是会改变 `v2` 的主线选型。

最关键的变化包括：

1. `shared_memory`
   - 在单容器同 IPC namespace 条件下，它现在是正式主线候选
   - 不再需要因为跨容器可见性被先验降级
2. `/dev/shm` 容量
   - 仍需要显式管理 `--shm-size`
   - 否则 embedding matrix 或大表格仍可能在容器内失败
3. PID 1 / signal / 子进程回收
   - 容器内仍建议通过 `--init` 或等价方式处理 zombie reaping
4. 路径可见性
   - 所有状态与产物都应以容器内根目录解释
   - 不能再沿用宿主机绝对路径语义

### J. 已有对象与 `v2` 合同之间还存在“半对齐”空洞

当前仓库并不是一片空白，但一些现有对象离 `v2` 合同化目标还差最后一层收口。

最典型的空洞包括：

1. `protocol/messages.py` 里的 `StateRef`
   - 已有 `kind / storage / handle / metadata / compatibility`
   - 但还没有正式纳入：
     - `manifest_id`
     - `artifact_root_id`
     - `workspace_relpath`
     - `source_locator_count`
     - `output_contract_version`
2. `runtime/reuse_contract.py`
   - 已把 `assist / validated_replay / exact_replay` 的名字收紧
   - 但还没有把 admissibility 依赖对象正式化成：
     - `canonical_task_spec`
     - `runtime_compatibility_signature`
     - `input_artifact_hashes`
3. `statepool/store.py`
   - 已支持 `mmap / shared_memory / CAS`
   - 但还没有定义：
     - 哪些 `kind` 必须 replay-restorable
     - 哪些 `kind` 只允许短生命周期
     - GC 和 replay-ready 之间的关系
4. `runtime/codeact_runner.py`
   - 仍保留旧的 `host-only / experimental` 叙事
   - 与 `v2` 单容器执行合同尚未完全对齐

这些不是“以后再说”的文档问题，而是会直接导致实现分叉的对象问题。

### K. 已冻结、但仍需协议化落地的 6 个核心名词

下面这些名字现在已经在子文档中有了第一版结构，但还没有全部进入主协议或主代码对象：

1. `CanonicalTaskSpec`
   - 已冻结方向
   - 还缺：
     - task compiler 输入输出合同
     - 规范化字段的最终枚举
2. `RuntimeCompatibilitySignature`
   - 已从 `runtime_image_digest` 收口为应用层签名思路
   - 还缺：
     - dependency lock 的权威来源
     - tool registry version 的生成规则
3. `HydrateManifest`
   - 已有 wire-level entry 结构
   - 还缺：
     - 最终 protobuf/JSON 载体
     - locator union 的代码侧类型实现
4. `CanonicalEvidencePack`
   - 已有 item/hash/RRF 方向
   - 还缺：
     - conflict item 最终 schema
     - pack 落盘格式
5. `ExecutionArtifactRef`
   - 已冻结为独立正式对象
   - 还缺：
     - 进入主协议的最终字段
     - 与 manifest 的最终边界
6. `TelemetryEvent`
   - Dashboard 依赖它
   - 已有单独合同文档，仍缺最终字段实现

### L. “只有 embedding 剪枝够吗” 的结论已经清楚，但文档还需要继续防误读

当前可以明确写死的判断是：

1. 不够
2. 但它仍然是必要层

原因要继续在文档里收口成三层：

1. embedding 剪枝
   - 解决 evidence ingress / prefill 入口规模
2. replay / strategy reuse
   - 解决 codegen / planning 重复开销
3. execution artifact reuse
   - 解决结果文件、表格、图表的重复物化开销

如果只做第 1 层：

1. `raw_evidence_bytes_seen_by_llm` 会下降
2. `llm_prompt_tokens` 可能下降
3. 但 `completion tokens`
4. `planner latency`
5. `codegen latency`
6. `artifact regeneration cost`

都不一定显著下降。

所以文档的主叙事必须继续坚持：

- embedding 剪枝是必要条件
- 不是全链路降本的充分条件

### M. `KV cache` 如果未来真的要接，当前最模糊的不是“值不值得”，而是“对象在哪一层”

现在最危险的误区不是高估它的收益，而是没有先回答它到底属于哪一层：

1. engine-local prefix reuse
2. agent-visible neural handoff
3. replay-like session resume

这三者不是一回事。

如果对象层次没先定死，后面会同时出现三种混乱：

1. 指标混乱
   - 到底记 `prefill_saved_ms` 还是 `token_saved`
2. 生命周期混乱
   - 到底跟 step 绑定、跟 task 绑定还是跟 engine session 绑定
3. 控制面混乱
   - 到底是 `StateRef` 风格引用，还是 engine-private handle

所以当前对 `KV cache` 最合理的推进顺序不是“尽快接入”，而是先把它的对象层级讲清楚。

这几项会直接影响：

1. runtime state machine
2. semantic provenance
3. replay admissibility
4. artifact channel
5. benchmark reproducibility

### H. Formal Benchmark Contract 还可再收紧

当前已有：

- offline local corpus
- `L0-L3`
- baseline fairness

但还需要进一步明确：

1. prompt invariants
2. model invariants
3. tool invariants
4. retry budget invariants
5. failure accounting
6. quality floor contract

否则消融实验仍可能被质疑为“能力面在变，而不只是机制面在变”。

## 23.6 下一步不是再加新概念，而是冻结 7 份核心合同 + 6 份跨合同文档

`v2` 现在最缺的已经不是“再想一个更酷的系统概念”，而是把几个最容易漂的地方写成单独合同。

因此，后续文档推进必须切换成下面这条路线：

1. 先冻结总文档中的系统边界与分层叙事
2. 再把关键实现边界拆成独立合同文档
3. 每份合同都必须回答：
   - 目标是什么
   - 不解决什么
   - 最小 schema 是什么
   - 生命周期与责任边界是什么
   - `MVP` 如何在当前仓库约束下实现
   - 哪些内容只能保留为 `Conditional` 或 `Future Work`

本轮应优先冻结的 7 份核心子文档如下：

1. [runtime_state_machine_contract.md](/home/qcrs/statebus/project/docs/planning/runtime_state_machine_contract.md)
2. [semantic_provenance_and_hydration_contract.md](/home/qcrs/statebus/project/docs/planning/semantic_provenance_and_hydration_contract.md)
3. [replay_admissibility_contract.md](/home/qcrs/statebus/project/docs/planning/replay_admissibility_contract.md)
4. [canonical_evidence_pack_and_fan_in_contract.md](/home/qcrs/statebus/project/docs/planning/canonical_evidence_pack_and_fan_in_contract.md)
5. [ephemeral_neural_state_boundary_note.md](/home/qcrs/statebus/project/docs/planning/ephemeral_neural_state_boundary_note.md)
6. [execution_artifact_and_workspace_contract.md](/home/qcrs/statebus/project/docs/planning/execution_artifact_and_workspace_contract.md)
7. [telemetry_event_contract.md](/home/qcrs/statebus/project/docs/planning/telemetry_event_contract.md)
8. 配套说明：[kv_cache_and_embedding_interaction_note.md](/home/qcrs/statebus/project/docs/planning/kv_cache_and_embedding_interaction_note.md)

此外，下面这些问题跨越 replay、runtime、provenance、artifact、benchmark 多条线，不适合硬塞进单一合同，建议作为跨合同文档单独维护：

1. [task_compiler_contract.md](/home/qcrs/statebus/project/docs/planning/task_compiler_contract.md)
2. [runtime_compatibility_signature_contract.md](/home/qcrs/statebus/project/docs/planning/runtime_compatibility_signature_contract.md)
3. [ref_registry_and_manifest_storage_contract.md](/home/qcrs/statebus/project/docs/planning/ref_registry_and_manifest_storage_contract.md)
4. [lifecycle_matrix.md](/home/qcrs/statebus/project/docs/planning/lifecycle_matrix.md)
5. [benchmark_quality_floor_contract.md](/home/qcrs/statebus/project/docs/planning/benchmark_quality_floor_contract.md)

### 23.6.1 对“7 核心合同 + 6 配套文档”的批判性接收结论

这套方向是对的，价值在于“把边界定死”；危险在于“过早把某些实现细节绝对化”。

#### 直接采纳

1. Runtime 必须有显式状态机，而不是隐式散落在 worker 逻辑里
2. Semantic state 必须有 provenance / hydration 合同，而不是只靠 state kind 名字猜
3. Replay 必须有 deterministic admissibility，而不是由 LLM 凭感觉决定能否复用
4. Fan-in 必须 deterministic，而不是再加一个模糊的 LLM merge 层
5. `KV cache / ephemeral neural state` 必须严格降级到 `Future Work`

#### 修改后采纳

1. `Planner` 不应是全能 master  
   更合理的是：
   - `Planner` 负责语义规划、重规划、回退路径
   - `Runtime Supervisor` 负责 dispatch、lease、heartbeat、cancel、GC、orphan cleanup
2. provenance 不能写成 `byte-offset only`  
   更合理的是：
   - 文本、表格、JSON、抽取片段分别定义 locator
   - `HydrateManifest` 统一表达 “row / item -> source locator”
3. exact replay key 不应包含 embedding 浮点向量  
   更合理的是：
   - embedding 只用于 assist 检索或 replay 候选召回
   - exact replay 只建立在离散、可审计的规范化 task spec 与输入签名上
4. fan-in 不应再升格成一个新 agent  
   更合理的是：
   - 它是 deterministic runtime stage / module
   - 例如 `evidence_fuser.py` 或 `data_prep` 阶段

#### 当前仓库下的实现纪律

1. formal benchmark 不再采用“单一默认后端”叙事，而是按对象种类分层：短命 dense state 默认 `shared_memory`，长命 replay-ready 对象默认 `mmap/CAS`
2. 正式 benchmark 仍锁定 offline local corpus，不引入外网检索噪声
3. `CodeAct` 仍先按单容器内 `subprocess + workspace contract` 推进，不提前写成强沙箱已完成
4. `KV cache / iSula / fully dynamic daemon bus` 继续只放增强层，不回灌成首版主叙事

### 23.6.2 7 份合同分别要解决什么

#### A. Runtime State Machine Contract

把：

- 谁派单
- 谁 ACK
- 谁发 heartbeat
- 谁做 cancel
- 谁负责 step attempt 生命周期
- 谁做 teardown 和 orphan cleanup

全部从隐式代码行为提升为正式语义。

#### B. Semantic Provenance And Hydration Contract

把：

- `StateRef` 背后的真实来源
- embedding / evidence / artifact 的溯源方式
- 非文本状态如何局部回填成 LLM 真正需要看到的证据
- `raw_evidence_bytes_seen_by_llm` 如何可证统计

全部定成可审计合同。

#### C. Replay Admissibility Contract

把：

- `assist`
- `validated_replay`
- `exact_replay`

之间的分界从“经验判断”变成 deterministic rule set。

#### D. Canonical Evidence Pack And Fan-in Contract

把多路 Retriever 的结果如何：

- 去重
- 排序
- 折叠
- 预算裁剪
- 组装成统一输入

写成 deterministic 数据面逻辑。

#### E. Ephemeral Neural State Boundary Note

把 `KV cache / prefix state / neural handoff` 的：

- 适用范围
- 生命周期
- 不进入 `MVP` 的原因
- 与 semantic state / memory replay 的关系

提前讲清楚，避免后续叙事跑偏。

#### F. Execution Artifact And Workspace Contract

把 CodeAct / tool execution 相关的：

- workspace 根目录
- inputs / outputs / logs / tmp 的固定布局
- artifact 命名与定位
- stdout/stderr 截断
- 文件大小与数量限制
- task teardown 与 artifact 回放关系

正式写成执行层合同。

#### G. Telemetry Event Contract

把：

- runtime 事件类型
- data plane 事件类型
- 聚合指标对象
- 落盘格式
- Dashboard 与 benchmark 的共享数据源

收口成一套正式 telemetry schema。

---

## 24. 最终建议

如果要做 `v2`，建议采用下面这条原则：

1. 在思想上，以 `some_think.md` 为北极星
2. 在工程上，以历史经验中已经成立的约束为素材，而不是继承旧实现外壳
3. 在范围上，先把 `Embedding + pruning + real CodeAct + L2 replay` 做扎实
4. 在表述上，把 `KV Cache / iSula / fully dynamic bus` 降为增强项
5. 在评测上，把正式 benchmark、消融实验和 live demo 三层分开
6. 在推进方法上，先写清 7 份合同，再开始大规模编码

### 24.1 对这轮新建议的批判性接收结论

#### 直接采纳

1. `L0-L3` 分级消融
2. 成本瀑布图
3. 高噪音、强动作、连续复用的任务设计原则
4. baseline 公允性合同

#### 修改后采纳

1. 代码审计场景
   - 采纳为 demo tier
   - 不直接承担 formal headline
2. 极客化 Dashboard
   - 采纳为展示增强
   - 不替代 formal evidence
3. 商业化成本指标
   - 采纳
   - 但必须清楚标注价格假设

#### 明确拒绝

1. 把任何炫酷可视化当作主证据
2. 把攻击性安全 PoC 设计成正式 benchmark 中心
3. 让 `L0` baseline 故意失真，只为了放大 `v2`

最值得追求的不是“做得最像一个炫目的 OS 论文”，而是：

> 做出一套真正能证明控制面降本、非文本状态可用、真实执行有效、共享记忆能跳步的 Agent runtime。

这条路线和 `some_think` 并不冲突。更准确地说，它是把 `some_think` 从一篇强叙事设计稿，收束成一套可交付的 `v2` 实施蓝图。

---

## 25. 参考资料

### 本地文档

- [some_think.md](/home/qcrs/statebus/project/some_think.md)
- [README.md](/home/qcrs/statebus/project/README.md)
- [docs/review/three_way_system_audit_20260625.md](/home/qcrs/statebus/project/docs/review/three_way_system_audit_20260625.md)
- [docs/reports/current_architecture_overview_20260622.md](/home/qcrs/statebus/project/docs/reports/current_architecture_overview_20260622.md)
- [docs/reader_guide/05_text_vs_statebus_comparison_methodology.md](/home/qcrs/statebus/project/docs/reader_guide/05_text_vs_statebus_comparison_methodology.md)
- [runtime/reuse_contract.py](/home/qcrs/statebus/project/runtime/reuse_contract.py)
- [statepool/store.py](/home/qcrs/statebus/project/statepool/store.py)
- [memory/store.py](/home/qcrs/statebus/project/memory/store.py)

### 外部官方资料

- Python shared memory: <https://docs.python.org/3/library/multiprocessing.shared_memory.html>
- FastAPI WebSockets: <https://fastapi.tiangolo.com/advanced/websockets/>
- ZeroMQ socket API: <https://zeromq.org/socket-api/>
- iSulad official repository: <https://gitee.com/openeuler/iSulad>
