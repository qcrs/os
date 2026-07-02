# StateBus V2 Container Refactor Bootstrap

日期：2026-06-27  
状态：`v2` 开发启动文档  
适用范围：准备在单容器 `Docker + openEuler` 内启动 `StateBus v2` 的 clean-room 大重构。

---

## 1. 目的

这份文档只做 5 件事：

1. 给出 `v2` 重构时必须参考的文档清单
2. 把赛题硬要求重新钉成开发边界
3. 收口目前已经冻结的 `v2` 实现决策
4. 列出当前仍然不能自作主张的未决问题
5. 给出一份可直接交给开发代理执行的 prompt、分阶段计划、Docker 启动和测试命令

这份文档不是 `v2` 架构蓝图本身。  
`v2` 的主蓝图仍然是 [statebus_v2_clean_room_rebuild_plan_20260625.md](/home/qcrs/statebus/project/docs/planning/statebus_v2_clean_room_rebuild_plan_20260625.md)。

---

## 2. 当前判断

### 2.1 关于开发环境

当前仓库的默认实现约束仍然是 `host-first`，见：

1. [AGENTS.md](/home/qcrs/statebus/project/AGENTS.md)
2. [current_host_and_migration.md](/home/qcrs/statebus/project/docs/constraints/current_host_and_migration.md)

但这次 `v2` 工作流是一个显式例外：

1. 你已经明确选择在容器内推进 `v2`
2. `v2` 主文档也已经明确把目标执行环境切成“单容器 openEuler”

因此这轮工作应理解为：

1. **不改写 `v1/mainline` 的 host-first 历史结论**
2. **在独立分支里启动 `v2` clean-room 重构**
3. **容器开发是 `v2` 的目标形态，不再只是后验验证**

### 2.2 关于代码策略

这不是一次“小修小补”，而是一次**带合同迁移的大范围重构**。

因此不建议：

1. 在当前工作分支上直接推平改
2. 把 `v2` 当成在 `v1` 代码里局部打补丁
3. 一上来就移动大量既有目录却没有先冻结边界

更稳的策略是：

1. 从当前包含 `v2` 文档与容器资产的工作树派生专用 `v2` 分支
2. 先冻结目录策略和合同对象
3. 再分阶段替换运行时、状态面、artifact 面、replay 面

---

## 3. 建议分支策略

### 3.1 推荐

由于当前工作树已经包含 `v2` 文档、Docker 资产与相关前置改动，建议：

1. 不再机械要求从历史 `main` 重新起步
2. 直接从当前 `HEAD` 派生一条独立 `v2` 分支
3. 只有在后续明确需要“更干净起点”时，再做定向 cherry-pick 或 rebase

推荐分支名：

```bash
git switch -c feat/statebus-v2-container-runtime
```

### 3.2 先不自动执行

这一步建议由你手动执行。  
当前文档只给建议，不直接替你切分支。

---

## 4. 必须参考的文档

## 4.1 一级权威源

这些文档决定 `v2` 的硬边界，必须优先读：

1. [题目.md](/home/qcrs/statebus/project/docs/reference/题目.md)
2. [statebus_v2_clean_room_rebuild_plan_20260625.md](/home/qcrs/statebus/project/docs/planning/statebus_v2_clean_room_rebuild_plan_20260625.md)
3. [three_way_system_audit_20260625.md](/home/qcrs/statebus/project/docs/review/three_way_system_audit_20260625.md)

## 4.2 七份核心合同

1. [runtime_state_machine_contract.md](/home/qcrs/statebus/project/docs/planning/runtime_state_machine_contract.md)
2. [semantic_provenance_and_hydration_contract.md](/home/qcrs/statebus/project/docs/planning/semantic_provenance_and_hydration_contract.md)
3. [replay_admissibility_contract.md](/home/qcrs/statebus/project/docs/planning/replay_admissibility_contract.md)
4. [canonical_evidence_pack_and_fan_in_contract.md](/home/qcrs/statebus/project/docs/planning/canonical_evidence_pack_and_fan_in_contract.md)
5. [execution_artifact_and_workspace_contract.md](/home/qcrs/statebus/project/docs/planning/execution_artifact_and_workspace_contract.md)
6. [telemetry_event_contract.md](/home/qcrs/statebus/project/docs/planning/telemetry_event_contract.md)
7. [ephemeral_neural_state_boundary_note.md](/home/qcrs/statebus/project/docs/planning/ephemeral_neural_state_boundary_note.md)

配套说明：

8. [kv_cache_and_embedding_interaction_note.md](/home/qcrs/statebus/project/docs/planning/kv_cache_and_embedding_interaction_note.md)

## 4.3 五份跨合同文档

1. [task_compiler_contract.md](/home/qcrs/statebus/project/docs/planning/task_compiler_contract.md)
2. [runtime_compatibility_signature_contract.md](/home/qcrs/statebus/project/docs/planning/runtime_compatibility_signature_contract.md)
3. [ref_registry_and_manifest_storage_contract.md](/home/qcrs/statebus/project/docs/planning/ref_registry_and_manifest_storage_contract.md)
4. [lifecycle_matrix.md](/home/qcrs/statebus/project/docs/planning/lifecycle_matrix.md)
5. [benchmark_quality_floor_contract.md](/home/qcrs/statebus/project/docs/planning/benchmark_quality_floor_contract.md)

## 4.4 只作背景参考，不作为 `v2` 新实现的主依据

1. [README.md](/home/qcrs/statebus/project/README.md)
2. [current_feature_scope.md](/home/qcrs/statebus/project/docs/constraints/current_feature_scope.md)
3. [implementation_plan.md](/home/qcrs/statebus/project/docs/planning/implementation_plan.md)

这些文件更偏 `v1/mainline` 的已实现事实与历史路线，不应覆盖 `v2` clean-room 的容器内前提。

---

## 5. 赛题硬要求

`v2` 开发期间，下面这些要求必须一直作为验收边界：

1. 至少 3 个 Agent，建议保留 `Planner / Retriever / Executor / Summarizer`
2. 同时支持 `text` 与 `structured protocol` 两种协作模式
3. 结构化通信协议必须覆盖动作、参数、结果、能力描述、握手/发现
4. 必须实现非文本中间状态传递
5. 必须实现共享记忆的存储、检索、复用
6. 至少两组连续任务，用于验证通信、状态、记忆复用
7. 必须统计消息数、文本开销、非文本状态规模、耗时、记忆命中率、整体提升
8. 必须能稳定执行不少于 10 轮连续任务
9. 最终交付要能在 `openEuler 24.03-LTS-SP3` 上编译、运行、测试

---

## 6. 目前已经冻结的 `v2` 决策

以下内容可以直接作为编码前提：

### 6.1 环境与进程模型

1. `v2` 目标环境是**单容器 `Docker + openEuler`**
2. 默认是**同文件系统根、同 IPC 命名空间、同进程命名空间内多进程协作**
3. `UDS` 是正式控制面主路径
4. `shared_memory` 在单容器里是正式候选，但只作为短生命周期状态主载体
5. `mmap/CAS` 继续承担 replay-ready、manifest 和长寿命对象

### 6.1.1 控制面正式定稿

1. 正式 wire contract 采用**typed Protobuf over length-prefixed UDS**
2. 不再把 `MessagePack` 作为 `v2` 控制面主格式
3. `MessagePack` 只保留给：
   - 本地 feature bundle / hashing payload
   - 非正式调试对象
   - 不进入正式控制总线的大型内部负载
4. `v2` 的重构重点不是“从 Protobuf 换成 MessagePack”，而是把当前 `JSON-in-Protobuf` 收紧为真正的 typed control plane

### 6.2 角色与职责

1. `Planner` 负责语义规划、回退、重规划
2. `Runtime Supervisor` 负责 dispatch、lease、heartbeat、cancel、GC、orphan cleanup
3. `Worker` 负责接单、执行、返回结果

### 6.3 三条正式主线

`MVP` 只做三条通道：

1. `Control Channel`
2. `Semantic State Channel`
3. `Execution Artifact Channel`

### 6.4 非主线能力的定性

1. `KV cache / Ephemeral Neural State` 只保留为 `Future Work`
2. 它的正式定位是 `Engine-Local Prefix Reuse`
3. 它不是 memory，不是 replay，不是跨任务持久资产

### 6.5 Replay 纪律

1. `assist != validated_replay != exact_replay`
2. `exact_replay` 只认 `CanonicalTaskSpec + input hashes + compatibility signature + output contract`
3. embedding 只用于召回，不进入 exact replay key
4. replay commit 使用 `CANDIDATE -> VERIFIED -> INVALIDATED`

### 6.6 Provenance 与 hydration

1. provenance 不能写成 `byte offset only`
2. `HydrateManifest` 必须使用强类型 locator
3. `raw_evidence_bytes_seen_by_llm` 只统计真正进入 prompt 的 external evidence bytes

### 6.7 Evidence fan-in

1. fan-in 是 deterministic runtime stage，不是新 Agent
2. 文本相关候选采用 rank-only RRF
3. `hard_facts` 与 `text_contexts` 分桶，不混为一个模糊列表

### 6.8 执行层

1. `Artifact` 是一等对象，不再只是 stdout 附属品
2. workspace 必须任务级隔离
3. 执行输入输出必须落入固定目录合同
4. `subprocess + workspace contract` 是 `MVP` 主线
5. `ExecutionArtifactRef` 首轮就作为独立对象与独立 registry entry 落地，不再依赖“先塞进 StateRef.metadata 再说”

### 6.9 Benchmark 纪律

1. 首版 formal benchmark 锁定 offline local corpus
2. 不把联网抓取、PDF 原位解析、OCR 作为 `MVP` 前提
3. 成本优势只在 `quality_floor_pass == true` 后才允许进入 headline
4. 第一批 formal task family 冻结为**财报 / 经营数据分析**
5. 正式比较采用 `L0 -> L3` 分层消融，而不是只做二元 `text vs protocol`

---

## 7. 本轮已经拍板的实现边界

以下问题本轮不再视为未决。

### 7.1 `v2` 目录策略

1. `v2` 采用新的 `v2/` 子树并行开发
2. 不直接覆盖当前顶层 `runtime/ protocol/ statepool/ memory/ eval`
3. `v2/` 是 clean-room 主壳，后续是否替换顶层入口属于后置决定

### 7.2 控制面正式编码格式

1. `MVP` 正式采用 typed Protobuf
2. 不采用 `MessagePack` 作为控制面主格式
3. 重构目标是移除 `JSON-in-Protobuf` 弱类型负担，而不是把强类型控制面降级为弱 schema 二进制字典

### 7.3 状态面默认后端

1. 默认不是“全局二选一”，而是按对象种类分层
2. `EMBEDDING_STATE`、短命 dense semantic state 默认 `shared_memory`
3. `FEATURE_BUNDLE` 默认小对象 inline，大对象 `mmap`
4. `HydrateManifest`、`CanonicalEvidencePack`、verified artifact、replay-ready 对象默认 `mmap/CAS`
5. `/dev/shm` 预算压力下，新对象自动降级到 `mmap`

### 7.4 `ExecutionArtifactRef` 的落地方式

1. 第一轮就建立独立 `ExecutionArtifactRef` 类型与 registry
2. 不再把它视作“塞了更多 metadata 的 StateRef”

### 7.5 TaskCompiler 的运行边界

1. formal benchmark 首轮使用预编译 `CanonicalTaskSpec` 与 `benchmark_strict`
2. `interactive opaque_freeform` 允许存在，但不进入 `validated_replay / exact_replay`

### 7.6 RuntimeCompatibilitySignature 的权威输入

1. `dependency_digest` 以容器构建锁定物或 build manifest 为准，缺失时再退化到环境采集
2. `tool_registry_digest` 以工具声明清单为准，不直接拼源码
3. `prompt_bundle_digest` 必须覆盖 role prompt、输出合同模板、固定工具规则模板
4. `extractor_bundle_digest` 进入正式签名组成

### 7.7 第一批 formal task family

1. 第一批 formal task family 冻结为财报 / 经营数据分析
2. incident / code-repo audit 类任务保留为 demo / live showcase tier，不承担首版 formal headline

### 7.8 `KV cache` 在首轮代码里保留到什么程度

1. 首轮只允许接口占位与文档边界
2. 不允许写出会被误读成“已经完成 neural handoff”的路径

### 7.9 正式 benchmark 比较梯度

1. `L0`: pure text cold baseline
2. `L1`: typed control only
3. `L2`: typed control + semantic pruning
4. `L3`: full replay stack
5. 正式报告必须可把收益归因到控制面、语义状态面和 replay 三层

---

## 8. 分阶段重构计划

## 8.1 Phase 0：分支与骨架冻结

目标：

1. 新建 `v2` 分支
2. 冻结 `v2` 目录策略
3. 冻结 `MVP` 的正式 wire format、state backend 默认策略、首任务家族
4. 建立 `tests/v2/` 基础测试目录

交付物：

1. `v2` 目录骨架
2. `v2` 入口模块
3. 最小 README / bootstrap 文档
4. 基础 import smoke test

冻结前提：

1. 第 7 节中的目录、wire format、state 分层、artifact ref 决策已冻结并写入文档

## 8.2 Phase 1：合同对象与 registry

目标：

1. 落 `CanonicalTaskSpec`
2. 落 `RuntimeCompatibilitySignature`
3. 落 `RefRegistryEntry`
4. 落 `HydrateManifest`
5. 落 `ExecutionArtifactRef`
6. 落 `CanonicalEvidencePack`

交付物：

1. Pydantic/dataclass schema
2. 序列化与哈希函数
3. SQLite registry 表与 sidecar layout
4. 单元测试

退出条件：

1. 所有 schema 可 round-trip
2. 所有 hash/signature 可稳定复现
3. registry 能从 `ref_id` 找到 manifest

## 8.3 Phase 2：Runtime Supervisor 与状态机

目标：

1. 明确 `PENDING -> ... -> GC_DONE` 生命周期
2. 把 `ACK / HEARTBEAT / CANCEL / TRAP` 变成正式 runtime 事件
3. 把 worker harness 与 supervisor 分责落地

交付物：

1. supervisor 子层
2. step state ledger
3. attempt / timeout / cancel / GC 行为
4. runtime 状态机测试

退出条件：

1. 能跑 dummy worker
2. ACK/heartbeat 超时能进入正确 trap
3. teardown 能清理短生命周期对象

## 8.4 Phase 3：Semantic State、provenance、fan-in

目标：

1. 落 locator-aware provenance
2. 落 hydrate manifest
3. 落 lexical/semantic/table retriever 输出统一 fan-in
4. 组装 `CanonicalEvidencePack`

交付物：

1. locator schema
2. hydrator
3. deterministic fan-in module
4. `raw_evidence_bytes_seen_by_llm` 统计逻辑

退出条件：

1. 可以从 selected rows/cells 局部 hydrate
2. text/table evidence 可 deterministic 排序
3. evidence bytes 统计可测试

## 8.5 Phase 4：Execution Artifact 与 workspace

目标：

1. 建立 task workspace 布局
2. 建立 inputs/outputs/logs manifest
3. 让 executor 产出 replay-ready artifact candidate

交付物：

1. workspace manager
2. artifact scanner
3. output manifest
4. `ExecutionArtifactRef` lookup

退出条件：

1. step 输出文件可被正式发现
2. candidate artifact 不会误进入 replay
3. teardown 能清理 workspace 非持久对象

## 8.6 Phase 5：Memory / replay / commit gate

目标：

1. 落 `assist / validated_replay / exact_replay`
2. 落 `CANDIDATE -> VERIFIED -> INVALIDATED`
3. 把 quality floor 接到 commit gate

交付物：

1. replay ledger
2. admissibility evaluator
3. validator hooks

退出条件：

1. bad artifact 不会升格为 `VERIFIED`
2. exact replay 只在 deterministic 等价下触发
3. validated replay 能复用旧策略但重新执行

## 8.7 Phase 6：Benchmark / telemetry / report

目标：

1. 把 runtime/data/artifact/replay 事件统一 telemetry
2. 建立 `text vs protocol`、`cold vs assist vs replay` 的正式对照
3. 建立质量底线 gate

交付物：

1. telemetry schema
2. benchmark runner
3. quality floor validator
4. report output

退出条件：

1. run manifest 完整
2. quality floor pass/fail 可解释
3. repeat-10 有正式可读输出

---

## 9. 可直接使用的开发 Prompt

下面这段 prompt 可以直接给新的开发代理使用。

```text
你正在 /home/qcrs/statebus/project 中推进 StateBus v2 的 clean-room 重构。

目标：
1. 在单容器 Docker + openEuler 环境内，重建一个符合赛题要求的 StateBus v2。
2. 这不是对 v1/mainline 的局部修补，而是基于现有 v2 文档合同进行大范围重构。
3. 优先实现可编码合同，而不是继续扩展新概念。

必须先读的文档，按优先级顺序：
1. docs/reference/题目.md
2. docs/planning/statebus_v2_clean_room_rebuild_plan_20260625.md
3. docs/review/three_way_system_audit_20260625.md
4. docs/planning/runtime_state_machine_contract.md
5. docs/planning/semantic_provenance_and_hydration_contract.md
6. docs/planning/replay_admissibility_contract.md
7. docs/planning/canonical_evidence_pack_and_fan_in_contract.md
8. docs/planning/execution_artifact_and_workspace_contract.md
9. docs/planning/telemetry_event_contract.md
10. docs/planning/ephemeral_neural_state_boundary_note.md
11. docs/planning/kv_cache_and_embedding_interaction_note.md
12. docs/planning/task_compiler_contract.md
13. docs/planning/runtime_compatibility_signature_contract.md
14. docs/planning/ref_registry_and_manifest_storage_contract.md
15. docs/planning/lifecycle_matrix.md
16. docs/planning/benchmark_quality_floor_contract.md
17. docs/planning/statebus_v2_container_refactor_bootstrap_20260627.md

赛题硬要求：
1. 至少 3 个 Agent，建议保留 Planner / Retriever / Executor / Summarizer
2. 必须同时支持 text 与 structured protocol 两种协作模式
3. 必须实现结构化通信、非文本状态传递、共享记忆复用
4. 必须有至少两组连续任务
5. 必须有消息数、文本开销、非文本状态规模、任务耗时、记忆命中率、整体提升指标
6. 必须能做 repeat-10 稳定性验证
7. 最终目标环境是 openEuler 24.03-LTS-SP3

当前已冻结的实现方向：
1. v2 目标环境是单容器 Docker + openEuler
2. MVP 只做 Control Channel、Semantic State Channel、Execution Artifact Channel
3. 控制面正式采用 typed Protobuf over UDS，不采用 MessagePack 作为正式主 wire format
4. KV cache / Ephemeral Neural State 只保留为 Future Work，不进入 MVP 主线
5. Planner 负责语义规划；Runtime Supervisor 负责 dispatch、lease、heartbeat、cancel、GC
6. replay 只接受 assist / validated_replay / exact_replay 三层正式语义
7. exact replay 不得使用 embedding 作为 key 本体
8. provenance 必须 locator-aware，不得简化成 byte-offset only
9. fan-in 必须 deterministic，不新增 Fusion Agent
10. artifact 是一等对象，workspace 合同必须显式化，`ExecutionArtifactRef` 首轮独立落地
11. formal benchmark 默认 task family 是财报 / 经营数据分析
12. quality floor 未通过的 run 和产物，不得进入正式 headline 或 VERIFIED replay

工作方式要求：
1. 先冻结边界，再写代码
2. 先搭 v2 骨架和合同对象，再替换 runtime 主链路
3. 优先建立 tests/v2，按合同写单元测试和 smoke
4. 优先做 strict benchmark path；interactive runtime 可后补
5. 不要把 v1 的历史实现细节当作 v2 的自动继承前提

严禁自作主张的点：
1. 只有当现有冻结决策与代码现实直接冲突时，才允许重新提未决项
2. 不要把已冻结的目录、控制面、artifact ref、task family 重新打开讨论

如果碰到这些未决点：
1. 不要自行拍板后继续大范围改代码
2. 先输出“问题、影响范围、备选项、你的推荐默认值”
3. 等待确认后再继续

建议交付顺序：
1. v2 目录骨架
2. schema / registry / manifest / hashing
3. runtime supervisor / step FSM
4. provenance / hydrator / evidence fan-in
5. workspace / artifact / executor wrapper
6. replay admissibility / commit gate
7. telemetry / benchmark / report

完成每一阶段后，都要给出：
1. 代码变更摘要
2. 新增测试
3. 执行过的命令
4. 仍未解决的问题
```

---

## 10. Docker 启动命令

推荐先在宿主机执行：

```bash
git switch feat/statebus-v2-container-runtime

export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=core

docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d
docker exec -it statebus-dev-qcrs bash
```

进入容器后：

```bash
source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project
python3 --version
python3 -c "import numpy, pydantic, orjson, msgpack; import google.protobuf; import langgraph; print('core ok')"
```

如果进入 `Phase 3+` 需要做 embedding / FAISS，再补：

```bash
python3 -m pip install -r requirements-container-embed.txt
```

或者在宿主机重新构建完整镜像：

```bash
export STATEBUS_INSTALL_EMBED_STACK=1
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d
```

---

## 11. 分层测试命令

不要一上来跑当前全量 `pytest -q`，因为当前仓库的很多测试仍是 `v1/mainline` 语义。

建议采用分层测试：

### 11.1 容器与环境 smoke

```bash
source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project
python3 -m runtime.smoke
```

### 11.2 `v2` 新增单测目录

建议从第一天开始建立：

```text
tests/v2/
```

然后按阶段逐步执行：

```bash
python3 -m pytest -q tests/v2/test_schema_roundtrip.py
python3 -m pytest -q tests/v2/test_task_compiler.py
python3 -m pytest -q tests/v2/test_runtime_signature.py
python3 -m pytest -q tests/v2/test_ref_registry.py
python3 -m pytest -q tests/v2/test_runtime_state_machine.py
python3 -m pytest -q tests/v2/test_hydration_and_fanin.py
python3 -m pytest -q tests/v2/test_workspace_artifacts.py
python3 -m pytest -q tests/v2/test_replay_admissibility.py
python3 -m pytest -q tests/v2/test_quality_floor.py
```

### 11.3 `v2` benchmark smoke

等 `Phase 6` 再增加：

```bash
python3 -m pytest -q tests/v2/test_benchmark_smoke.py
python3 -m pytest -q tests/v2/test_repeat10_contract.py
```

### 11.4 当前仓库已有的环境验证

如果需要顺手确认 `langgraph` 路径没坏，可跑：

```bash
python3 -m pytest -q tests/test_state_channels_and_graph.py::test_langgraph_adapter_runs_existing_statebus_graph_path
```

但这不是 `v2` 合同是否完成的正式 gate。

---

## 12. 本轮建议结论

建议先做的，不要跳步：

1. 先在 `feat/statebus-v2-container-runtime` 上冻结文档与目录策略
2. 先按已拍板的 wire format、state 分层、artifact ref、task family 建 `v2/` 与 `tests/v2`
3. 先落 schema / registry / FSM / workspace 合同对象
4. 再进 retriever / replay / benchmark 主链路

当前最不该做的事：

1. 直接在当前分支平推 `v1` 目录
2. 在 `KV cache` 上先花大力气
3. 在 formal task family 未定前就写大量 benchmark 逻辑
4. 把 typed Protobuf control plane、state 分层、artifact ref 独立性等核心边界留到编码中途再决定
