# StateBus 宿主机主线审查与修正执行计划

日期：`2026-06-07`

适用范围：在不改变当前外部约束的前提下，对当前 `/home/qcrs/statebus/project` 的赛题对齐情况、主线方案、证据层次和实现顺序做一次收口式审查，并据此给出后续执行顺序。

约束保持不变：

- 仍然是 host-first
- 仍然不把 Docker / openEuler VM / `nsjail` 当当前主线前提
- 仍然不把强沙箱终态、hidden-state / KV 传递当本轮必须闭合项

## 1. 结论先说

当前项目最值得继续推进的一条主线，不是继续扩设计，也不是先补 Docker / VM / CodeAct，而是：

> 先把宿主机内已经存在的赛题主链路，按照“正式证据层”和“当前推进层”重新分层，然后优先把共享记忆从 assist-only 或任务合同驱动，收敛成更诚实的 runtime-evidence-driven gain。

当前判断如下：

1. 赛题主骨架已经存在，不是 design-only。
2. `protocol` 相对 `text` 的通信压缩与 API 时延收益，已经有正式证据。
3. 当前最弱的一环不是通信，而是共享记忆收益的口径与证据。
4. 当前实现已经进入 `18` 个连续任务、`skip_execute` / `skip_retrieve_execute` 的推进层，但正式评测包仍停在 `12` 任务、assist-only。
5. 这说明当前真正的问题不是“能不能跑”，而是：
   - 正式证据层落后于当前 worktree
   - replay / reuse 语义仍偏任务合同驱动
   - `Retriever` / `Executor` 仍明显贴合当前样本任务

本轮唯一推荐方向：

> 先收口 memory gain 证据与 runtime 语义，再补 matched benchmark 和文档口径；不要先去纠缠 Docker / openEuler / `nsjail`。

## 2. 赛题 Requirement Map

### 2.1 必须闭合的 requirement

1. 至少 `3` 个 Agent，覆盖规划 / 检索 / 执行 / 总结中的至少 `3` 类。
2. 同时支持 `text` 与 `protocol` 两种协作模式，并在同任务条件下做可复现实验对比。
3. 实现结构化通信，至少包含动作、参数、结果、能力描述，并有握手 / 能力发现或协议映射。
4. 实现非文本中间状态传递，并说明生成、传递、接收、使用方式。
5. 实现共享记忆模块，带统一元数据，并支持关键词 / 标签 / 语义检索与跨任务复用。
6. 至少 `2` 组关联连续任务，验证减少重复计算、降低协作开销和提升任务效率。
7. 统计消息次数、文本 token/字符开销、非文本状态次数与规模、总耗时、共享记忆命中率与整体提升。
8. 架构至少包含 runtime / 协议解析与调度 / 状态交换 / 共享记忆 / 评测，并稳定执行不少于 `10` 轮连续任务。
9. 最终交付要能在 openEuler 24.03-LTS-SP3 上编译、运行、测试。

### 2.2 当前状态判断

- `Agent`、`protocol`、`StateRef`、`memory`、`eval` 主骨架：`已实现`
- `text` vs `protocol` 正式对比：`已实现`
- 非文本状态传递：`已实现`
  - 但当前是 `EMBEDDING + FEATURE_BUNDLE + StateRef`
  - 不是 hidden-state / KV
- 共享记忆检索与复用：`已实现`
  - 但正式证据层仍主要是 assist-only
- 关联连续任务：`已实现`
  - 正式包是 `12` 任务
  - 当前 worktree 已扩到 `18` 任务
- 稳定性与 repeat-10：`宿主机已实现`
- openEuler 最终交付验证：`后验验证未闭环`

### 2.3 当前真正缺口

赛题最容易被追问的不是“有没有 memory module”，而是：

> 当前 memory reuse 到底有没有减少步骤、减少重复计算、减少时间。

如果这个问题不能用新的正式 benchmark 包正面回答，那么“记忆复用效果”这一评分面仍然偏弱。

## 3. 当前问题定义与主线方案分析

### 3.1 当前主线定义基本是对的

当前主线应定义为：

1. `Planner` / `Summarizer` 用 API LLM
2. `Retriever` 从 repo-local corpus 检索 fresh evidence
3. 共享记忆作为跨任务复用层，而不是替代 fresh evidence 的默认真源
4. `Executor` 根据非文本中间态选工具 / playbook
5. `StateRef + mmap/shared_memory` 承担状态交换
6. `eval.runner` 统一做 `text` / `protocol` 对比和复用统计

这个问题定义是贴题的，因为题目考的是多 Agent 协作机制，而不是模型部署或容器编排本身。

### 3.2 当前阶段顺序也大体对

当前仍然应该坚持：

1. host-side 闭环
2. 协议与双模式 benchmark
3. `StateRef` 与状态池
4. 共享记忆与复用
5. 再去做 VM / 终态交付验证

这一点不应被改写。

## 4. 当前方案的问题

### 4.1 `implementation_plan.md` 已经不再是当前事实层主文档

它仍保留 design-first、实现覆盖接近 `0` 的旧口径，已经和当前 README、约束文档、测试、benchmark 包不一致。

这不是小瑕疵，而是会直接误导后续实现者的问题：

- 它把“当前已经能跑的东西”写回成“只有设计”
- 它会让 requirement audit 和当前代码现实错位

处理原则：

> 不再把 `docs/planning/implementation_plan.md` 当当前实现状态主文档；它最多保留为早期设计参考。

### 4.2 正式证据层与当前推进层混得还不够开

当前正式包仍然是：

- `12` 个连续任务
- assist-only memory 口径
- `skipped_step_count = 0`

当前 worktree 则已经在推进：

- `18` 个连续任务
- `skip_execute`
- `skip_retrieve_execute`
- 对应 smoke 断言已经要求 `reuse_gain > 0`

这两层现在必须明确写成两层事实，而不能混成“当前已经正式证明”。

### 4.3 memory gain 路径仍然偏任务合同驱动

当前 `expected_reuse_mode`、`replay_source_task_id`、固定任务链设计，对复用路径有明显合同驱动色彩。

这并不等于实现是错的，但意味着当前最诚实的说法应是：

> 现在已经有受控 replay / reuse benchmark scaffold，但要升格成更强的赛题证据，仍需要进一步把 reuse 决策收敛到 runtime evidence，而不是主要靠任务预设。

### 4.4 `Retriever` / `Executor` 的赛题特化仍然偏强

当前实现已经不是硬编码 demo，但仍明显贴合当前样本：

- `Retriever` 依赖 repo-local corpus 和当前任务链
- `FEATURE_BUNDLE.route` 规则对当前三个主题高度适配
- `Executor` 仍是 route-to-playbook 映射主导

这不影响它作为 contest prototype 成立，但不应包装成通用 multi-agent runtime 完成态。

### 4.5 `text` vs `protocol` 比较轴成立，但边界要讲清

当前 `text` vs `protocol` 的 formal 结论可以成立，但它更接近：

- 文本 handoff vs 紧凑结构化 handoff
- prompt / control payload 压缩收益

而不是：

- 完整分布式 runtime 的多机 transport 对照

所以这条证据可用，但口径不能过头。

### 4.6 `shared_memory` 与 `UDS` 还不是 headline

它们现在是：

- 宿主机可行路径
- benchmark capability check
- executor sample transport

不是：

- 当前正式性能 headline
- 最终 runtime 终态

## 5. 修正后的执行计划

### 5.1 第一优先级：先把当前推进层转成正式证据层

立即执行顺序：

1. 跑 `pytest` 和 `runtime.smoke`，确认当前推进层没有破主链路。
2. 跑当前 deterministic benchmark，确认 `18` 任务与 skip 路径是否真实闭环。
3. 如果 deterministic 层成立，再决定是否生成新的正式 benchmark 包。

这里的关键不是“跑一次就算证明”，而是先确认：

- 当前 worktree 的 skip 语义真的跑通
- 当前报告、测试、任务集三者是一致的

### 5.2 第二优先级：收敛 replay / reuse 语义

后续代码调整应优先做这一类，而不是去扩新功能：

1. 尽量把 reuse 决策从 `expected_reuse_mode` 这类任务标签，收敛到 runtime evidence。
2. 把“benchmark expectation”与“runtime gate”分离。
3. 让最终文档能诚实说明：
   - 哪些 skip 来自受控 replay contract
   - 哪些是 fresh evidence 验证后触发的 reuse

### 5.3 第三优先级：补 matched comparison

在 memory gain 收口后，再补：

1. `mmap` vs `shared_memory` 同条件 matched comparison
2. `UDS` executor 的 host-feasible 补证据

但这两条都排在 memory gain 之后。

### 5.4 第四优先级：再处理交付尾部

只有当前面几条闭环后，才值得进入：

1. openEuler VM 后验验证
2. 最终部署文档
3. 演示视频和交付面材料

## 6. 本轮执行纪律

本轮后续所有命令、代码修改和 benchmark，都应遵守：

1. 不把 Docker / `nsjail` / openEuler VM 当当前阻塞项。
2. 不把当前 worktree 成功一次，直接写成正式 README 结论。
3. 新 benchmark 必须进新的 `runs/...` 目录，不覆盖旧正式包。
4. 文档必须明确区分：
   - 当前正式证据层
   - 当前推进层
   - host-feasible 样机
   - 后续增强项

## 7. 当前唯一推荐方向

如果只选一个方向继续做，应该是：

> 先把当前 `18` 任务 replay / reuse 主线验证清楚，收口成新的正式证据包，并同步修正 runtime gate 与文档口径。

不推荐当前优先做的方向：

- Docker 化
- openEuler 提前迁移
- `nsjail` / 强沙箱闭环
- hidden-state / KV 传递
- 新增更重系统加分项
