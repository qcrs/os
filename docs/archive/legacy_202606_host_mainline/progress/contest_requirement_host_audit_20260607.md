# StateBus 赛题核对与宿主机审计

日期：`2026-06-07`

适用范围：基于当前 `main` 主线、仓库内正式评测包与现有实现，对赛题要求、当前缺口、MVP 边界、宿主机可做范围、受管沙箱限制和后续优先级做一次评审式核对。

如果后续要把这份审计转成可执行实现主线，请继续读：

- `docs/planning/host_goal_mainline_dependency_20260607.md`

## 1. 直接结论

- 当前仓库已经不是 design-only；它已经是一个**可运行的 host-side 赛题化原型**。
- 当前最稳的正式口径不是“系统已经最终交付”，而是：
  - **宿主机 MVP 与 current-worktree formal evidence 已闭环**
  - **openEuler 最终交付未闭环**
  - **强沙箱 / CodeAct 正式链未闭环**
- 在当前 host-mainline 目标内，要求级别的缺口已经不再是“能不能跑”或“有没有 formal 包”：
  1. step-skipping replay 已有 fresh deterministic / serialized API repeat-10 证据
  2. 旧正式层、当前 refresh 层、以及 Docker / openEuler 后续层已经可以分开陈述
  3. 剩余的 host-side 工作更适合视为**可继续优化项**，不是当前主线收口阻塞项
- 当前实现**仍然带有明显赛题特定优化**。它是诚实的 contest prototype，不是通用 multi-agent runtime。

## 2. 证据基线

主要证据源：

- 赛题要求：`docs/reference/题目.md:7-41`
- 当前环境边界：`docs/constraints/current_host_and_migration.md:11-23`, `39-53`, `57-102`, `167-185`
- 当前功能边界：`docs/constraints/current_feature_scope.md:13-31`, `39-119`, `123-183`
- 当前仓库主说明：`README.md:15-25`, `104-172`, `176-210`
- 正式评测摘要：`runs/comprehensive_eval_20260607_131113/SUMMARY.md:32-113`
- 正式 API repeat-10 报告：`runs/comprehensive_eval_20260607_131113/api_repeat10_serial/benchmark_report.md:24-94`
- 正式 deterministic repeat-10 报告：`runs/comprehensive_eval_20260607_131113/deterministic_repeat10/benchmark_report.md:24-94`
- 当前 `18` 任务 deterministic 验证包：`runs/host_goal_eval_20260607_233858/deterministic_repeat1/benchmark_report.md`
- 当前 `18` 任务 API 串行验证包：`runs/host_goal_eval_20260607_233858/api_repeat1_serial/benchmark_report.md`
- 较早的 `18` 任务 deterministic repeat-10 稳定性包：`runs/host_goal_eval_20260608_002101/deterministic_repeat10/benchmark_report.md`
- 当前 `18` 任务 deterministic repeat-10 refresh 报告：`runs/host_goal_eval_20260608_032333_runtime_reuse_contract_refresh/deterministic_repeat10/benchmark_report.md`
- 当前 `18` 任务 current-worktree refresh 包：`runs/host_goal_eval_20260608_032333_runtime_reuse_contract_refresh/SUMMARY.md`
- 当前 `18` 任务最新完整 refresh 包：`runs/host_goal_eval_20260608_093111_planner_contract_refresh/SUMMARY.md`
- 当前 `18` 任务 serialized API repeat-10 正式包：`runs/host_goal_eval_20260608_093111_planner_contract_refresh/SUMMARY.md`
- 当前 `18` 任务 serialized API repeat-10 报告：`runs/host_goal_eval_20260608_093111_planner_contract_refresh/api_repeat10_serial/benchmark_report.md`
- 当前 provenance-aware replay gate 的 smoke + deterministic refresh 包：`runs/host_goal_eval_20260608_084835_provenance_gate_refresh/SUMMARY.md`
- 关键实现锚点：
  - `agents/sample_agents.py:86-202`
  - `agents/sample_agents.py:205-334`
  - `runtime/orchestrator.py:104-310`
  - `runtime/orchestrator.py:353-418`
  - `runtime/executor_runtime.py:53-320`
  - `runtime/remote_executor.py:14-80`
  - `tasks/sample_benchmark.yaml:1-180`
  - `tests/test_smoke.py:49-257`

## 3. 当前正式结果

### 3.1 主机与测试有效性

- 当前正式评测包明确记录：
  - `pytest` 全量通过：`28 passed`
  - `runtime.smoke` 完成
  - 宿主机 `AF_UNIX` 可用
  - `nsjail` 缺失
  - Docker CLI 存在，但当前用户无法访问 `/var/run/docker.sock`
- 见：`runs/comprehensive_eval_20260607_131113/SUMMARY.md:34-42`
- 当前 provenance-aware deterministic refresh 包还归档了新的宿主机回归门：
  - `pytest`：`36 passed`
  - `runtime.smoke`：完成且 stdout 已真实归档
  - 见：`runs/host_goal_eval_20260608_093111_planner_contract_refresh/pytest_q.txt`, `runs/host_goal_eval_20260608_093111_planner_contract_refresh/runtime_smoke.txt`

### 3.2 正式 API repeat-10

当前要把两个 formal API repeat-10 包分开看，而不是再只看旧综合包。

#### 旧综合包的 formal API repeat-10

当前最重要的历史综合结果仍然是 `runs/comprehensive_eval_20260607_131113/api_repeat10_serial/`，不是早先并发启动的 `api_repeat10/`。

- `protocol` 对比 `text`：
  - 控制面字节：`61635.70 -> 51286.90`，下降 `16.79%`
  - LLM 总 token：`14786.20 -> 11053.90`，下降 `25.24%`
  - 端到端耗时：`51651.73 ms -> 41593.21 ms`，下降 `19.47%`
  - 两边 `failure_count = 0`
  - 两边 `expectation_match_rate = 1.00`
- 见：`runs/comprehensive_eval_20260607_131113/api_repeat10_serial/benchmark_report.md:24-65`

结论：

- **结构化协议降低通信与 token 开销**这件事，当前是有正式结果支撑的。
- 在真实 API 模式下，这个收益已经转化成了**真实时延收益**。

#### 当前 replay-aware `18` 任务主线的 formal API repeat-10

`runs/host_goal_eval_20260608_093111_planner_contract_refresh/api_repeat10_serial/`
现在把 provenance-aware replay gate cleanup 之后、再经过 planner-contract
parser tolerance 修正的同一条 replay-aware 主线，重新落成了
current-worktree serialized API repeat-10 正式包。

- `protocol` 对比 `text`：
  - 控制面字节：`103503.10 -> 88789.80`
  - LLM 总 token：`24384.40 -> 16625.90`
  - 端到端耗时：`81184.06 ms -> 60776.34 ms`
  - 两边 `failure_count = 0`
  - 两边 `expectation_match_rate = 1.00`
  - 两边继续保持：
    - `skipped_step_count = 9`
    - `reuse_gain = 0.17`
    - `memory_hit_rate = 0.83`
  - 三个 `skip_retrieve_execute` 任务继续稳定跳过
  - 先前 `084835` API 诊断包里 text-mode `sample-cache-006` 的 planner
    numeric `step_id` 失败已被收口；这次 `10/10` 重新稳定命中

结论：

- **结构化协议降低通信、token 与 live API wall-clock 开销**这件事，现在不再只停留在旧 assist-only 综合包。
- 当前 `18` 任务 replay-aware 主线在 provenance-aware route gate cleanup 之后，也已经重新拿到了干净的 repeat-10 正式 API timing 证据。

### 3.3 正式 deterministic repeat-10

- `protocol` 对比 `text`：
  - 控制面字节：`95263.00 -> 85809.00`，下降 `9.92%`
  - 端到端耗时没有变好，反而略慢：`5717.76 ms -> 5794.76 ms`
  - 两边 `memory_hit_rate = 0.75`
  - 两边 `skipped_step_count = 0`
- 见：`runs/comprehensive_eval_20260607_131113/deterministic_repeat10/benchmark_report.md:24-61`

结论：

- deterministic 模式证明了**协议压缩是真实的**；
- 但 deterministic 模式不构成“协议带来时延提升”的主证据。

### 3.4 共享记忆当前到底证明了什么

需要把四层证据分开看。

#### 旧 repeat-10 综合包证明了什么

当前旧正式结果里，共享记忆证明的是：

- 记忆检索在工作
- 命中 / 拒绝 / assist 决策在工作
- 预期复用任务与控制任务的判断是对齐的

当前正式结果**没有证明**的是：

- 记忆复用让下游步骤被跳过
- 记忆复用直接带来可测的 runtime gain

证据：

- `memory_hit_rate = 0.75`
- `reuse_apply_rate = 0.50`
- `skipped_step_count = 0.00`
- `reuse_gain = 0.00`
- 见：`runs/comprehensive_eval_20260607_131113/SUMMARY.md:91-98`

硬结论：

> 共享记忆这条线当前是“可用且被验证”，但还是 assist-only，不是 prune-and-skip。

#### 新 `18` 任务 host-goal 验证包又新增证明了什么

`runs/host_goal_eval_20260607_233858/` 证明了当前 worktree 已经不再是 assist-only。

- deterministic repeat-1：
  - 两边 `skipped_step_count = 9`
  - 两边 `reuse_gain = 0.17`
  - 两边 `expectation_match_rate = 1.00`
- serialized API repeat-1：
  - `text`:
    - `llm_total_tokens = 22850.00`
    - `task_ms = 86594.07`
  - `protocol`:
    - `llm_total_tokens = 16822.00`
    - `task_ms = 72173.55`
  - 两边仍保持：
    - `skipped_step_count = 9`
    - `reuse_gain = 0.17`

因此，当前最新判断应改成：

> 旧 repeat-10 综合包仍是 assist-only 基线；但当前 `18` 任务 replay-aware 主线已经有新的宿主机证据，说明 step skip 与 runtime gain 路径都已真实进入当前代码与 benchmark。

#### 新 deterministic repeat-10 稳定性包又新增证明了什么

`runs/host_goal_eval_20260608_002101/deterministic_repeat10/` 继续把同一条 replay-aware 主线升格成 repeat-10 稳定性证据。

- deterministic repeat-10：
  - 两边 `failure_count = 0`
  - 两边 `expectation_match_rate = 1.00`
  - 两边继续保持：
    - `skipped_step_count = 9`
    - `reuse_gain = 0.17`
  - `protocol` 继续降低总控制字节：
    - `147701.00 -> 133167.00`
  - 报告现在还显式拆出了：
    - `cold_start`
    - `reject_control`
    - `assist`
    - `validated_replay`
    - `exact_replay`
    - 以及 `fresh_retrieval` / `step_skipping` 两条汇总轴

#### current-worktree deterministic repeat-10 refresh 包又新增证明了什么

`runs/host_goal_eval_20260608_032333_runtime_reuse_contract_refresh/deterministic_repeat10/`
把同一条 replay-aware 主线在当前 `runtime_reuse_contract` cleanup 之后重新对准了
当前 worktree。

- deterministic repeat-10：
  - 两边 `failure_count = 0`
  - 两边 `expectation_match_rate = 1.00`
  - 两边继续保持：
    - `skipped_step_count = 9`
    - `reuse_gain = 0.17`
    - `memory_hit_rate = 0.83`
  - `protocol` 继续降低总控制字节：
    - `145936.00 -> 131623.00`
  - deterministic wall-clock 现在也略低于 `text`：
    - `7250.02 ms -> 7200.02 ms`

因此，当前更准确的判断应再收紧一步：

> 当前 replay-aware 路线不只是“历史上有 deterministic repeat-10 稳定包”，而是对当前 dirty worktree 也已有 fresh deterministic repeat-10 证据落盘。

#### provenance-aware deterministic refresh 包又新增证明了什么

`runs/host_goal_eval_20260608_084835_provenance_gate_refresh/deterministic_repeat10/`
把同一条 replay-aware 主线在 provenance-aware route gate cleanup 之后再次
对准了当前 worktree。

- deterministic repeat-10：
  - 两边 `failure_count = 0`
  - 两边 `expectation_match_rate = 1.00`
  - 两边继续保持：
    - `skipped_step_count = 9`
    - `reuse_gain = 0.17`
    - `memory_hit_rate = 0.83`
  - `protocol` 继续降低总控制字节：
    - `148142.00 -> 133875.00`
  - archived exact-replay payload 现在记录：
    - `feature_route_source = hint_consensus`
    - `feature_route_provenance = ["corpus_metadata", "lexical"]`
  - `runtime_smoke.txt` 也终于不是空文件

因此，当前更准确的判断应再收紧一步：

> 当前 replay-aware 路线不只是“历史上有 deterministic repeat-10 稳定包”，而是对当前 dirty worktree 在 provenance-aware replay gate 收紧之后也仍有 fresh deterministic repeat-10 证据落盘。

#### 新 serialized API repeat-10 正式包又新增证明了什么

`runs/host_goal_eval_20260608_093111_planner_contract_refresh/api_repeat10_serial/`
把同一条 replay-aware 主线在 planner-contract parser 容错修正之后进一步
落成了 fresh live API repeat-10 正式证据。

- serialized API repeat-10：
  - 两边 `failure_count = 0`
  - 两边 `expectation_match_rate = 1.00`
  - 两边继续保持：
    - `skipped_step_count = 9`
    - `reuse_gain = 0.17`
    - `memory_hit_rate = 0.83`
  - `protocol` 继续降低：
    - 控制面字节：`103503.10 -> 88789.80`
    - LLM 总 token：`24384.40 -> 16625.90`
    - 端到端耗时：`81184.06 ms -> 60776.34 ms`

因此，当前更准确的判断应改成：

> assist-only 仍只属于旧综合包；`18` 任务 replay-aware 主线现在已经同时具备 repeat-1 过渡证据、deterministic repeat-10 稳定性证据，以及 current-worktree serialized API repeat-10 正式 timing evidence。

## 4. 赛题逐项核对

| 赛题要求 | 当前状态 | 证据 | 真实边界 |
| --- | --- | --- | --- |
| 不少于 3 个 Agent，覆盖规划/检索/执行/总结 | 已实现 | `agents/sample_agents.py:65-334` | 当前是 4 角色主线，但仍是单仓库内 staged pipeline，不是通用分布式多 Agent runtime |
| 结构化通信协议、握手、能力发现、不能只靠长文本透传 | 已实现 | `runtime/orchestrator.py:353-418`, `README.md:141-149` | 当前主线是 protobuf 控制帧；但远端 transport 只覆盖 executor 样机 |
| 同时支持 `text` / `protocol` 双模式并对比 | 已实现 | `README.md:118-137`, `tests/test_smoke.py:49-86`, 正式评测包 | 当前 formal 对比主轴成立 |
| 非文本中间状态传递 | 已实现 | `runtime/orchestrator.py:189-236`, `agents/sample_agents.py:145-186`, `tests/test_smoke.py:167-225` | 已实现的是 `EMBEDDING + FEATURE_BUNDLE + StateRef`，不是 hidden state / KV cache |
| 共享记忆存储与元数据 | 已实现 | `agents/sample_agents.py:291-327`, `runtime/orchestrator.py:287-289`, `memory/store.py:init_schema` | SQLite + FAISS 主线成立 |
| 按关键词/标签/语义相似度检索历史记忆并复用 | 已实现 | `runtime/orchestrator.py`, `agents/sample_agents.py`, `runs/host_goal_eval_20260607_233858/`, `runs/host_goal_eval_20260608_002101/`, `runs/host_goal_eval_20260608_021820_runtime_exact_replay_det_repeat10/`, `runs/host_goal_eval_20260608_093111_planner_contract_refresh/` | 当前复用已覆盖 assist / reject / `skip_execute` / `skip_retrieve_execute`，并且 exact replay 已开始从显式 source-task pointer 收敛到 runtime evidence 匹配 |
| 至少 2 组关联连续任务 | 已实现 | `tasks/sample_benchmark.yaml` | 当前任务集已扩成 3 组链路、每组 6 任务，共 18 连续任务 |
| 展示消息数、token/字符、非文本状态次数与规模、耗时、记忆命中率、整体提升 | 已实现 | `eval/runner.py`, 两套 benchmark 包 | 通信和时延提升已证明；当前 `18` 任务验证包里记忆“整体提升”也已由非零 `reuse_gain` 证明 |
| 架构包含 runtime / 协议 / 状态交换 / 共享记忆 / 评测，并稳定执行 10 轮 | 已实现 | `README.md:86-96`, `SUMMARY.md:46-63`, `49-53` | 宿主机 repeat-10 已闭环；openEuler 终态未闭环 |
| 完整源码、设计文档、部署文档、实验报告、演示视频、openEuler 最终可运行 | 部分实现 | 当前仓库 docs + runs 存在 | 最终演示视频、openEuler 编译/运行/测试、终态部署验证未闭环 |
| 鼓励 CodeAct + 轻量沙箱 | 未作为正式主线实现 | `docs/reference/题目.md:25-26`, `runtime/executor_runtime.py:244-320` | 当前只有 lightweight subprocess fallback，不是 CodeAct + 安全沙箱正式链 |

## 5. 当前主线到底是什么

当前真正的主线是：

1. `Planner` 与 `Summarizer` 走 API LLM
2. `Retriever` 从 repo-local corpus 检索，再查共享记忆
3. `Retriever` 产出三类中间态：
   - `DENSE_EVIDENCE`
   - `FEATURE_BUNDLE`
   - `EMBEDDING`
4. `Executor` 根据 `FEATURE_BUNDLE.route` 选 playbook/tool；当前 route 会优先吃 corpus metadata hint，再回退到 lexical/tag matching
5. `skip_retrieve_execute` 当前优先靠 stored query + route + doc-set 这类 runtime evidence 匹配，而不是只靠显式 `replay_source_task_id`
6. `Summarizer` 写回 `MemoryCommit`
7. `eval.runner` 对 `text` / `protocol` 做连续任务 repeat 对比

实现锚点：

- 检索与复用接受/拒绝逻辑：`agents/sample_agents.py:86-202`
- 执行路径与 UDS 样机：`agents/sample_agents.py:205-246`, `runtime/remote_executor.py:14-80`
- 记忆提交：`agents/sample_agents.py:249-334`
- 状态与记忆统计：`runtime/orchestrator.py:123-310`

这条主线已经能跑，也有正式 benchmark。

但要诚实地说：

- 这条链路还是**赛题化 host-side prototype**
- 不是“通用多 Agent 系统基础设施已经完成”

## 6. MVP 与未完成项

### 6.1 当前已经算 MVP 的部分

当前宿主机 MVP 已经具备：

- `text` / `protocol` 双模式
- 4 角色协作链
- `StateRef` + `mmap` 主线
- `shared_memory` 可选路径
- SQLite + FAISS 共享记忆
- 3 组连续任务、18 任务 benchmark
- repeat-10 稳定性
- formal API repeat-10 协议收益
- 当前 `18` 任务 replay-aware memory gain 验证包
- 当前 `18` 任务 replay-aware deterministic repeat-10 稳定性包
- 当前 `18` 任务 replay-aware serialized API repeat-10 正式包

### 6.2 还可以继续做的 host-side 提升项，但不阻塞当前主线收口

优先级建议：

1. **降低 `Retriever` / `Executor` 的赛题特化**
   - `tasks/sample_benchmark.yaml` 是强引导任务集
   - `runtime/executor_runtime.py` 现在虽然已经是 registry-driven，且 route hint 已开始转移到 corpus metadata，但 route profile 仍高度贴合当前 incident family
   - 当前这条 retrieval-side 去特化和 replay runtime cleanup 已经有新的 deterministic repeat-10 regression 包：`runs/host_goal_eval_20260608_021820_runtime_exact_replay_det_repeat10/`
   - 这让当前实现更像 route-specific prototype
2. **继续把 replay-aware gain 从“受控合同成立”往“更少任务族特化”收口**
   - `repeat=10` 的 serialized API 正式包现在已经有了
   - 当前真正剩下的不是“缺包”，而是 gain 仍主要来自受控 replay scaffold，虽然 explicit source-task pointer 已经去掉
   - 下一步应继续减少 task-family 依赖，而不是继续堆同类型 benchmark
3. **做一组 matched `mmap` vs `shared_memory` 正式对比**
   - 现在已经有 repo-local 生成入口：`scripts/run_statepool_backend_matrix.py`
   - 当前 deterministic `repeat=1` 预跑包也已经落盘：`runs/statepool_backend_matrix_20260608_012235/`
   - 当前 serialized API `repeat=3` 验证包也已经落盘：`runs/statepool_backend_matrix_20260608_013044_api_repeat3/`
   - 但它目前给出的结论是 mixed：
     - `protocol` 下 `shared_memory` 更快
     - `text` 下 `shared_memory` 更慢
   - 所以它还不是统一方向的 formal headline
4. **把旧正式基线与新 replay-aware 正式层继续分开**
   - `UDS` 已经是真实宿主机可用
   - 但它仍是 executor sample transport，不是最终 runtime 架构闭环
5. **收尾交付面**
   - openEuler 24.03-LTS-SP3 最终编译/运行/测试
   - 终态部署说明
   - 演示视频

这里要把边界写清楚：

> 前 4 条是当前宿主机主线之上的可继续优化项；第 5 条才属于 Docker / VM / openEuler 交付阶段对象。

## 7. 当前环境边界

### 7.1 当前 Linux 宿主机能继续做

- repo-local 开发与测试
- `pytest` / `runtime.smoke`
- deterministic repeat-10
- API repeat-10 串行正式 benchmark
- `mmap`
- Python `shared_memory`
- SQLite + FAISS
- UDS executor host validation

依据：`docs/constraints/current_host_and_migration.md:57-74`, `README.md:118-172`, `SUMMARY.md:32-113`

### 7.2 当前 Linux 宿主机做不了或当前不该作为主线

- 依赖 Docker daemon 的开发流程
- `nsjail` 正式隔离验证
- root 级 `perf` / `bpftrace` / eBPF
- openEuler 最终兼容性结论

依据：`docs/constraints/current_host_and_migration.md:80-100`

### 7.3 我这个受管 Codex 沙箱不一定能现场完成，但你的宿主机其实能做

- `AF_UNIX` / pathname socket 的 UDS 路径
- live API benchmark 的联网调用

这类情况不应被算作“项目当前环境做不了”，而应算作：

> 真实宿主机可做，但受管沙箱未必可直接验证。

### 7.4 需要你提权或批准后，我才能帮你直接执行的事

- 访问 `/var/run/docker.sock`
- 安装 `nsjail`、`podman`、系统级依赖
- root 级 `perf` / `bpftrace` / eBPF
- 如果当前受管沙箱拦截了网络或 Unix socket，而你又要我在这个会话里直接重跑 live API / UDS 路径，则需要 unsandboxed 执行批准
- openEuler VM 内的系统级安装、环境改动、最终交付链路验证

## 8. 争议点澄清

### 8.1 `Retriever` 现在是不是“真正检索”

是检索，但还是**受限于 repo-local 样本语料**。

- 它不是只包一段写死 YAML 文本了
- 但它也不是开放域检索
- 目前是：
  - repo-local corpus 检索
  - 再查共享记忆
  - 再根据 fresh evidence 决定是否接受 memory assist

证据：`agents/sample_agents.py:88-143`, `tasks/sample_benchmark.yaml:1-180`

### 8.2 `Executor` 现在是不是沙箱执行

不是正式沙箱。

当前只有两条执行路径：

- 本地 `tool registry + lightweight subprocess`
- 外部多进程 `UDS executor` 样机

这两条都**不是**：

- `nsjail`
- 容器沙箱
- CodeAct 正式链

证据：`runtime/executor_runtime.py:244-320`, `runtime/remote_executor.py:14-80`, `README.md:154-157`

### 8.3 当前实现是不是赛题特化

是，且特化点很清楚：

- 任务集是强引导的连续任务链：`tasks/sample_benchmark.yaml:1-180`
- route 判定仍绑定当前语料族；只是它现在会优先消费 retrieved corpus metadata hint，而不是只靠 runtime lexical rule：`runtime/executor_runtime.py:270-339`
- tool registry 是当前 incident family 的 playbook 集：`runtime/executor_runtime.py:53-98`

所以当前最准确的说法不是“通用能力已经完成”，而是：

> 当前主线是一个更诚实的赛题化 host-side prototype。

### 8.4 为什么最新结果里 memory hit rate 两边看起来相同

这更像**对比设计导致的结果相同**，不是第一优先级 bug。

原因：

1. 两个模式跑的是同一批任务链
2. 复用策略是 runtime-fixed 的，不随 mode 切换
3. 复用判断依赖 query/tags/fresh route，而这些主逻辑并不是 `text` / `protocol` 的比较轴
4. 当前 benchmark 本来就把 memory 设计成“assist/reject 对照”，不是“mode 决定记忆质量”

证据：

- 当前任务集中每轮固定有 `12` 个预期复用任务：
  - `assist`
  - `skip_execute`
  - `skip_retrieve_execute`
- `Retriever` 两种模式都统一走 `ctx.search_memory(...)`：`agents/sample_agents.py:109-133`
- 在当前 current-worktree refresh 包里，两边仍大致对齐：
  - `memory_hit_rate` 约 `0.83`
  - `reuse_apply_rate = 0.67`
  - `skipped_step_count = 9.00`
  - 见：`runs/host_goal_eval_20260608_032333_runtime_reuse_contract_refresh/api_repeat10_serial/benchmark_report.md`

补充说明：

- 报表里具体选中的 memory id 并非完全相同，说明实现并不是“硬编码同一条记忆”；
- 但 aggregate 指标仍接近，说明这个 benchmark 现在主要用来比较**通信模式**，不是比较**记忆机制在不同模式下的差异**。

结论：

> 这首先是 benchmark 比较轴设计问题，不是当前最核心的实现 bug。

## 9. 目前最主要的后续优化点

按严重度排序：

1. **记忆复用收益已经形成 formal 包，但泛化仍弱**
   - 这个问题到当前已经不再是“没有证据”
   - 现在的真实问题是：gain 已有 formal 包，但仍主要建立在受控 replay contract 上
2. **`Executor` 仍偏 playbook selector**
   - 通用 action execution 还不够强
   - CodeAct 不在正式主线
3. **`Retriever` / `FEATURE_BUNDLE` 仍高度任务族特化**
   - 真实应用泛化性不足
4. **`shared_memory` 还缺 matched formal comparison**
   - 当前已经不只是 capability check
   - 也已经不只是 deterministic 预跑
   - 现在真正缺的是更强稳定性或更清晰的 backend story，而不是“有没有 matched route”
5. **强沙箱与终态交付未闭环**
   - `nsjail` 未装
   - Docker 无权限
   - openEuler 最终可运行尚未正式验收

## 10. 除了 VM / Docker / openEuler 镜像外，下一步最该做什么

最优先建议只有一条：

> 先把 `Retriever` / `Executor` 去特化，并把当前 replay-aware gain 从“受控合同成立”继续往“更少任务族特化的 runtime 证据”推进。

理由：

- 通信效率这条已经有正式结果
- 状态传递这条已经基本满足赛题下限
- 当前 `18` 任务 replay-aware memory gain 现在也已经有了 serialized API repeat-10 正式包
- 当前最弱的反而是“通用性”和“受控合同之外的泛化”
- 继续把时间花在 Docker / VM 之前，先把这两条补强，收益最高

## 11. 对 openRuler / Docker 的当前判断

基于当前仓库文档和主线结果：

- **没有 repo-local 证据表明 openRuler 镜像是当前 MVP 的前置条件**
- 如果后续为了交付或官方环境复现要接 openEuler / 容器镜像，那属于：
  - 后验验证
  - 终态交付检查
  - 不是当前 host-side 主链路缺口本身

硬结论：

> 现在不是“非得先去 Docker / openRuler 才能继续”，而是“当前宿主机主线已经能继续，而且更应该先补去特化与 replay-aware 泛化问题”。
