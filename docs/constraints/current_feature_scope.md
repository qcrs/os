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
- 当前 route/tool 选择会优先消费 repo-local corpus 文档里的 metadata hint，再回退到 lexical/tag signal matching；
- 当前 route/tool 选择还会先生成一个小的 ranked `tool_candidates` 集合，但这个候选集合只保留在 `FEATURE_BUNDLE` 里，不再回灌进 execute payload；
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
- 现在也已经有 matched backend matrix 生成入口：
  - `scripts/run_statepool_backend_matrix.py`
  - 当前 deterministic `repeat=1` 预跑包：`runs/statepool_backend_matrix_20260608_012235/`
  - 当前 serialized API `repeat=3` 验证包：`runs/statepool_backend_matrix_20260608_013044_api_repeat3/`

仍然保留的工程判断：

- 默认 benchmark 主线仍建议 `mmap`
- `shared_memory` 现在是**可验证备选路径**
- 已有 matched compare 路线，也已有 serialized API 验证包
- 但当前结果是 backend- and mode-dependent：
  - `protocol` 下 `shared_memory` 更快
  - `text` 下 `shared_memory` 更慢
- 所以它还不是统一方向的 formal backend headline
- 不是当前论文/报告里的唯一主线

### 2.5 当前共享记忆语义边界

当前要把四层事实分开写：

1. `runs/comprehensive_eval_20260607_131113/`
   - 这是当前 repeat-10 稳定性基线
   - 其中共享记忆仍是 assist-only
2. `runs/host_goal_eval_20260607_233858/`
   - 这是当前 `18` 任务 replay-aware 主线的验证包
   - 其中已经出现：
     - `skip_execute`
     - `skip_retrieve_execute`
     - 非零 `skipped_step_count`
     - 非零 `reuse_gain`
3. `runs/host_goal_eval_20260608_002101/`
   - 这是同一条 replay-aware 主线的 deterministic repeat-10 稳定性包
   - 它继续证明：
     - `18` 任务链在 deterministic repeat-10 下稳定
     - `expectation_match_rate = 1.00`
     - runtime gate 已显式写入 manifest：
       - `allow_memory_assist = 12`
       - `allow_execute_prune = 3`
       - `allow_exact_replay = 3`
     - 报告已拆出 `cold_start / reject_control / assist / validated_replay / exact_replay`
4. `runs/host_goal_eval_20260608_004449/`
   - 这是 replay-aware 主线在当前 exact-replay cleanup 之前的早期 serialized API repeat-10 正式包
   - 它证明 replay-aware `18` 任务主线已经不再只是 deterministic 证据
5. `runs/host_goal_eval_20260608_021820_runtime_exact_replay_det_repeat10/`
   - 这是当前 exact replay runtime-evidence cleanup 的 deterministic repeat-10 regression 包
   - 它继续证明：
     - `18` 任务链在 deterministic repeat-10 下仍稳定
     - 三个 `skip_retrieve_execute` 任务不再需要显式 `replay_source_task_id`
     - 当前 exact replay 已经能靠 stored query + route + doc-set 匹配成立
6. `runs/host_goal_eval_20260608_022627_runtime_exact_replay_api_repeat10/`
   - 这是同一条 exact replay runtime-evidence cleanup 的较早 serialized API repeat-10 正式包
   - 它继续证明：
     - `18` 任务链在 live API repeat-10 下稳定
     - 两边 `failure_count = 0`
     - 两边 `expectation_match_rate = 1.00`
     - 两边继续保持：
       - `skipped_step_count = 9`
       - `reuse_gain = 0.17`
       - `memory_hit_rate = 0.83`
     - `protocol` 继续降低：
       - 控制面字节：`103525.30 -> 89380.80`
     - live API total tokens：`24986.20 -> 17995.00`
     - 端到端耗时：`93830.97 ms -> 77792.77 ms`
     - 这说明当前 runtime-exact-replay cleanup 不只是 deterministic 回归成立，live API repeat-10 也已经正式落盘
7. `runs/host_goal_eval_20260608_032333_runtime_reuse_contract_refresh/`
   - 这是对当前 dirty worktree 上 `runtime_reuse_contract` cleanup 的 fresh proof bundle
   - 它重新归档了当前宿主机回归门：
     - `pytest -q`：`34 passed`
     - `runtime.smoke`：完成
   - 它继续证明：
     - deterministic repeat-10 仍稳定：
       - `failure_count = 0`
       - `expectation_match_rate = 1.00`
       - `skipped_step_count = 9`
       - `reuse_gain = 0.17`
       - `memory_hit_rate = 0.83`
       - `protocol` 控制面字节：`145936.00 -> 131623.00`
     - serialized API repeat-10 也仍稳定：
       - `failure_count = 0`
       - `expectation_match_rate = 1.00`
       - `skipped_step_count = 9`
       - `reuse_gain = 0.17`
       - `memory_hit_rate = 0.83`
       - `protocol` 控制面字节：`100489.60 -> 86541.20`
       - live API total tokens：`23747.70 -> 17461.00`
       - 端到端耗时：`86936.37 ms -> 74073.41 ms`
   - 这说明当前代码层的 runtime-contract cleanup 不只是旧包里“曾经成立”，而是对当前 worktree 仍然成立
8. `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/`
   - 这是 provenance-aware replay gate cleanup 之后的最新宿主机 smoke +
     deterministic repeat-10 refresh 包
   - 它重新归档了当前宿主机回归门：
     - `pytest -q`：`35 passed`
     - `python -m runtime.smoke`：有真实 stdout，`runtime_smoke.txt` 非空
   - 它继续证明：
     - deterministic repeat-10 仍稳定：
       - `failure_count = 0`
       - `expectation_match_rate = 1.00`
       - `skipped_step_count = 9`
       - `reuse_gain = 0.17`
       - `memory_hit_rate = 0.83`
       - `protocol` 控制面字节：`148142.00 -> 133875.00`
   - exact replay 的归档 route 现在不再写成 metadata-only：
     - `feature_route_source = hint_consensus`
     - `feature_route_provenance = ["corpus_metadata", "lexical"]`
   - 这说明 host-mainline 已经开始把 hint 降成 provenance-aware 候选信号，
     而不是继续把 `corpus_metadata` 当作硬路由主证据
9. `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
   - 这是 provenance-aware worktree 在 planner-contract parser tolerance
     修正之后的最新完整 refresh 包
   - 它重新归档了当前宿主机回归门：
     - `pytest -q`：`36 passed`
     - `python -m runtime.smoke`：stdout 继续非空
   - 它继续证明：
     - deterministic repeat-10 仍稳定：
       - `failure_count = 0`
       - `expectation_match_rate = 1.00`
       - `skipped_step_count = 9`
       - `reuse_gain = 0.17`
       - `memory_hit_rate = 0.83`
       - `protocol` 控制面字节：`148142.00 -> 133875.00`
     - serialized API repeat-10 也重新干净落盘：
       - `failure_count = 0`
       - `expectation_match_rate = 1.00`
       - `skipped_step_count = 9`
       - `reuse_gain = 0.17`
       - `memory_hit_rate = 0.83`
       - `protocol` 控制面字节：`103503.10 -> 88789.80`
       - live API total tokens：`24384.40 -> 16625.90`
       - 端到端耗时：`81184.06 ms -> 60776.34 ms`
   - 它还说明：
     - 先前 `084835` API 诊断包里的 text-mode planner numeric `step_id`
       wobble 已经通过 parser 容错收口
     - `sample-cache-006` 这类 exact replay 任务在 live API repeat-10 下
       重新恢复为 `10/10` 稳定命中
10. `runs/host_goal_eval_20260608_112452_plan_sideband_runtime_profile_refresh/`
   - 这是把 `corpus_doc_ids` / `reuse_signature` / `runtime_reuse_contract`
     从 live `PlanStep.params` 退到 side-band `RuntimeTaskProfile` 之后的
     最新宿主机 refresh 包
   - 它重新归档了当前宿主机回归门：
     - `pytest -q`：`38 passed`
     - `python -m runtime.smoke`：stdout 继续非空
   - 它继续证明：
     - deterministic repeat-10 仍稳定：
       - `failure_count = 0`
       - `expectation_match_rate = 1.00`
       - `skipped_step_count = 9`
       - `reuse_gain = 0.17`
       - `memory_hit_rate = 0.83`
     - steady-state 控制面字节明显下降：
     - `text/protocol`：`148883 -> 134942` 进一步降到 `133572 -> 120351`
     - deterministic task time 略有回升：
       - `6713/6769 ms -> 6954/7018 ms`
11. `runs/host_goal_eval_20260608_113845_runtime_drop_reuse_signature_query_refresh/`
   - 这是把 `reuse_signature` 从 runtime memory query 主过滤条件里拿掉之后的
     最新宿主机 refresh 包
   - 它重新归档了当前宿主机回归门：
     - `pytest -q`：`38 passed`
     - `python -m runtime.smoke`：stdout 继续非空
   - 它继续证明：
     - deterministic repeat-10 仍稳定：
       - `failure_count = 0`
       - `expectation_match_rate = 1.00`
       - `skipped_step_count = 9`
       - `reuse_gain = 0.17`
       - `memory_hit_rate = 0.83`
     - steady-state 控制面字节继续下降：
       - `text/protocol`：`133572 -> 120351` 进一步降到 `132306 -> 119081`
     - deterministic task time 也从上一轮小幅回落：
       - `6954/7018 ms -> 6773/6736 ms`
12. `runs/host_goal_eval_20260608_130836_runtime_drop_reuse_tags_refresh/`
   - 这是把 `reuse_tags` 从 live memory query 预过滤里拿掉之后的
     最新宿主机 refresh 包
   - 它重新归档了当前宿主机回归门：
     - `pytest -q`：`41 passed`
     - `python -m runtime.smoke`：stdout 继续非空
   - 它继续证明：
     - deterministic repeat-10 仍稳定：
       - `failure_count = 0`
       - `expectation_match_rate = 1.00`
       - `skipped_step_count = 9`
       - `reuse_gain = 0.17`
     - `memory_hit_rate = 0.83`
     - control bytes 继续保持：
       - `text/protocol`：`132735 -> 119008`
13. `runs/host_goal_eval_20260609_085938_text_brief_fidelity_api_repeat10_serial/`
   - 这是在 `state_transfer` text-side brief 收紧为更完整 executor handoff
     之后，当前 `26` 任务 fairness surface 的最新正式 serialized API
     `repeat=10` 包
   - 它重新证明：
     - 两侧都完成 `run_count = 10`
     - 两侧 `failure_count = 0`
     - 两侧 `expectation_match_rate = 1.00`
   - aggregate 仍继续偏向 `protocol`：
     - 控制面字节：`150876.20 -> 128743.80`
     - live API total tokens：`29727.80 -> 19882.30`
     - 端到端耗时：`127173.46 ms -> 100976.55 ms`
   - 这包更重要的 lane-level 含义是：
     - `communication`
       - `5838.25 -> 4944.60`
       - `1140.25 -> 727.70`
       - `5133.40 ms -> 3907.84 ms`
     - `state_transfer`
       - text-side baseline 仍然必须写成 `text brief handoff to executor`
       - 但当前 text-side brief 已比旧 formal 包更完整
       - handoff textual bytes：`1725.00 -> 738.00`
       - handoff non-text bytes：`0.00 -> 1704.67`
       - total tokens：`1116.07 -> 698.53`
       - task ms：`4840.01 -> 3804.30`
     - `memory`
       - `assist_only` 仍然没有打赢 `memory_off`
       - `replay_enabled` 仍然才是当前稳定成立的 memory gain
   - 这说明：
     - `state_transfer` 的正式 claim 仍成立
     - 但它现在建立在一个更诚实、更完整的 text-side brief baseline 上
     - 因此这轮应被理解为 fairness / claim-surface hardening，而不是新的
       performance headline

当前代码层的语义也进一步收敛了：

- runtime 现在优先消费单一 `runtime_reuse_contract`，而不是把
  `allow_memory_assist` / `allow_execute_prune` / `allow_exact_replay`
  三个开关继续当作主要执行面；
- `expected_reuse_mode` 继续保留，但它更明确地属于 benchmark expectation /
  validation 这一层，而不是 runtime 决策主字段。
- live `PlanStep.params` 现在只保留语义字段；benchmark-derived
  `corpus_doc_ids` / `reuse_signature` / `runtime_reuse_contract`
  已退到 side-band `RuntimeTaskProfile`，不再冒充 plan 语义。
- runtime memory query 现在也不再要求 `required_metadata.reuse_signature`
  命中；当前主线更依赖：
  - `task_theme`
  - semantic query match
  - fresh route / evidence gate
- validated replay 现在还会比较 canonical fresh-evidence hash；
  exact replay 则要求更强的 route provenance / confidence，而不是只靠
  query + doc-set + metadata route 就直接跳过

这意味着当前最诚实的口径应是：

> 当前仓库已经具备可运行、deterministic repeat-10 稳定、且当前 host-mainline
> 已开始用 provenance-aware route gate 收紧 replay 触发条件的 step-skipping
> replay path；旧综合评测包则保留 assist-only 历史基线，而最新 formal live API
> timing 现在应分两层看：
> - `18` 任务 replay-aware current-worktree formal 包仍以
>   `runs/host_goal_eval_20260608_093111_planner_contract_refresh/` 为准
> - `26` 任务 contest fairness surface 的最新 formal lane 包现在以
>   `runs/host_goal_eval_20260609_085938_text_brief_fidelity_api_repeat10_serial/`
>   为准。

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
4. 当前 executor 主线先停在已完成的 claim-boundary / observability closure，
   不再默认继续叠 mechanism hardening
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
