# StateBus v2 独立实现审计 / 竞赛可信度审计 / 创新性审计

## 1. 标题与元数据

- 审计日期：2026-07-05
- 审计类型：独立实现审计 + 竞赛可信度审计 + 创新性审计
- 审计范围：`/home/qcrs/statebus/project`
- 分支：`feat/statebus-v2-container-runtime`
- 提交：`f3dd0944eb5e6bbafc88d79eb2db24e0451b8a3e`
- 容器：`statebus-dev-qcrs`
- 容器进入方式：`docker exec -u 0 statebus-dev-qcrs bash`
- 激活脚本：`/usr/local/bin/activate_statebus_container.sh`
- 项目目录：`/workspace/statebus/project`
- Python：`/usr/bin/python3`
- 审计方法：先读代码与测试并建立独立模型，再跑容器内实验与 benchmark，再读 `docs/improvement`
- 文档约束遵守情况：代码阅读、pytest、preflight、benchmark、诊断命令均通过容器 root + 激活脚本执行
- 工作树状态：dirty；本次未修改实现代码，仅新增本审计文档

### 证据可用性矩阵

| role-path-mode | embedding-mode | preflight | 本次完成的主证据 | 证据等级 | 备注 |
|---|---|---:|---|---|---|
| `api` | `local` | 通过 | `formal`、`compare` 完成；`continuous-replay` 300s 超时 | strong | 当前最强证据源 |
| `api` | `deterministic` | 通过 | `continuous-replay --family ...` 300s 超时 | medium | 只有阻塞证据，无完成 replay 报告 |
| `deterministic` | `local` | 通过 | `continuous-replay` collection 完成 | medium | 完成了 replay collection，但不是最强模式 |
| `deterministic` | `deterministic` | 通过 | 本次未用作结论性 benchmark | weak | 仅保留为回退能力 |

### 关键环境可用性

| 项目 | 结果 | 证据 |
|---|---|---|
| API key | `set` | 容器内环境探测 |
| local embedding model | `set` | `/statebus/models/Qwen3-Embedding-0.6B` |
| CUDA for embedding | `cuda:0` | preflight 元数据 |
| 旧有改进文档 | 仅在独立分析完成后阅读 | 符合审计顺序要求 |

## 2. Executive Summary

1. `api + local` 在当前容器内真实可用，且完成了 `formal` 与 `compare` 两类强证据 benchmark。`continuous-replay` 的强证据路径在 300 秒内未完成，所以 replay 结论不能上调到 strong。
2. `formal` 8/8 质量通过是真实的，但 formal 任务族极窄：8 个 case 全是单指标、单季度、`compare_metric + table_retriever`。这更像精度锚点，不是广义多智能体难题。
3. `formal` 中的 prompt 节省主要来自 semantic pruning，不是 typed structured control 单独带来的节省。L0 到 L1 控制字节仅降 `736B`，而 `pruning_bytes_saved_vs_l0 = 6255B`；更重要的是 L1 token 反而高于 L0。
4. `compare` 的 fairness gate 在本次 `api + local` 强证据下通过，说明 external baseline 不是明显的 oracle baseline；但它仍然是 dev-only、候选受限、repo-local 数据集上的原型比较，不能拿来替代 formal claim。
5. `compare` 真实支持的结论是“StateBus 少 token / 少 prompt bytes / 少 control bytes”，不支持“端到端更快”。本次 `api + local` 下 StateBus 端到端慢约 `10.37s`，且主要是非 LLM runtime overhead。
6. benchmark 主路径里的 CodeAct 是“受控脚本生成与沙箱执行”，不是“LLM 在 benchmark 中实时写代码”。但 `bwrap` 沙箱在 formal 与 compare 强证据里确实真实发生了。
7. `validated replay` 当前更接近“降级执行目标下的策略/上下文复用”，不是“直接恢复旧答案”。代码、测试和 case artifact 都支持这个解释；名称与叙事现在比真实语义更激进。
8. `validated replay` 的 admissibility contract 仍然偏宽：它比较 task family / intent / tools / outputs / 参数形状，而不是更细的语义判别。这是 claim 风险，不是本次 medium 证据里已证实的错答 bug。
9. non-text state 的强证据是存在的，但只覆盖到 `shared_memory` 语义状态发布；`mmap` 发布、`memfd + SCM_RIGHTS`、`SubprocessExecutorTransport` 目前是 capability / test 级证据，不是 benchmark 级证据。
10. `ControlPlaneLoopbackServer` 使用真实 UDS framing，但 benchmark 默认仍是单进程顺序角色路径；“可迁移到多进程”成立，“已经在 benchmark 主路径里证明多进程优势”不成立。
11. `continuous-replay` 在 `deterministic + local` 下达成了完整 replay target round 覆盖，但这是 medium evidence，而且被一个 CLI bug 污染：`--family` 对 `continuous` / `continuous-replay` 实际无效。
12. `--family` bug 会让看似单 family 的 rerun 实际跑成默认 collection，直接影响复现实验、用时与报告路径，且现有测试没有抓到。
13. 当前测试套件对 contract、deterministic benchmark、report schema 的覆盖很强，但对 live API / live local / CLI 行为的覆盖明显不足。绿测不等于 strongest claim 已证实。
14. local embedding + fork 路径会在真实 benchmark stderr 中反复触发 `huggingface/tokenizers` 的 fork 警告，说明当前进程模型对本地 embedding 的操作系统层健壮性还不够干净。
15. 当前最有价值的创新点不是“所有东西都已被完整证明”，而是三个已经成型的系统方向：`typed control plane + prompt slicing`、`semantic state as first-class carrier`、`downgraded replay / strategy reuse with provenance`。
16. 当前最需要削弱的叙事不是“有风险的创新方向”，而是三类过头表述：`live benchmark CodeAct = LLM codegen`、`compare = formal superiority`、`validated replay = 安全答案复原`。
17. 相比已有 `docs/improvement`，本次独立审计发现两类过时判断：external revenue fallback 已修复；table retriever 的单行硬编码已不再是现状。也发现几类遗漏：`--family` bug、强 replay 证据缺失、以及 structured control 与 pruning 贡献被混淆。

## 3. Architecture Reality Map

### 3.1 Canonical task spec / contract path

- `v2/runtime/compiler.py:17-193`
  - `TaskCompiler.compile()` 在 `TaskMode.BENCHMARK_STRICT` 下要求 `precompiled_canonical_task_spec`。
  - benchmark 主路径不是自由文本规划后再猜 spec，而是严格消费样本中预编译的 `CanonicalTaskSpec`。
- `v2/runtime/compiler.py:210-258`
  - `CanonicalTaskSpec` 明确携带 `task_family`、`intent_op`、`required_outputs`、`required_tools`、`arguments`。
- 审计结论：
  - competition 里真正被 benchmark 主路径证明的是“typed task contract runtime”，不是开放式任务理解能力本身。

### 3.2 Planner -> Retriever -> Executor -> Summarizer 路径

- `v2/runtime/role_path.py:567-1006`
  - `RolePathRunner` 顺序执行四角色。
  - 默认 `handoff_mode = "structured_collaboration"`。
- `v2/runtime/role_path.py:206-223`
  - structured path 用 tagged JSON block 构造 prompt。
- `v2/runtime/role_path.py:190-203`
  - text path 也存在，但只是备选 / 对照。
- 审计结论：
  - 真实 benchmark 主路径是“四角色顺序调用 + structured prompt slicing”，不是四个并发 agent，更不是分布式 runtime。

### 3.3 Retrieval / corpus / table / semantic pipeline

- `v2/retrieval/pipeline.py:92-125`
  - `LexicalMetadataRetriever` 提供 hint 型候选。
- `v2/retrieval/pipeline.py:128-182`
  - `SemanticChunkRetriever` 默认 `top_k = 1`，通过 embedding 做 chunk 选择。
- `v2/retrieval/pipeline.py:185-252`
  - `TableStructureRetriever` 对 formal/cross-period 任务有极强的结构化偏向，常用 `metric_name` 精确命中。
- 审计结论：
  - formal family 的成功高度依赖表格结构检索。
  - long-doc / replay family 才更接近“semantic state + reuse”叙事。

### 3.4 Control plane / UDS / subprocess transport

- `v2/control/transport.py:53-177`
  - `ControlPlaneLoopbackServer` 使用真实 `AF_UNIX` + length framing。
- `v2/control/transport.py:178-257`
  - worker harness 会验证 `state_refs`、`artifact_refs`、contract 字段。
- `statepool/store.py:313-366`
  - `memfd` 的 FD passing / `SCM_RIGHTS` 能力已实现。
- 审计结论：
  - UDS framing 不是伪造的；但默认 benchmark 不是多进程 transport benchmark。

### 3.5 Non-text state / StateRef / semantic state / shared memory / mmap / memfd

- `v2/state/store.py:22-65`
  - `LayeredStoragePolicy` 对 `EMBEDDING_STATE` / `DENSE_SEMANTIC_STATE` 首选 `SHARED_MEMORY`。
- `v2/state/store.py:147-163`
  - `publish()` 真实 materialize semantic payload。
- `v2/runtime/driver.py:1399-1425`
  - 只要 `semantic_state_handle` 存在，就会打出 `STATE_PUBLISHED` telemetry。
- `statepool/store.py:20-27`
  - legacy `StatePool` 明确写着默认 benchmark backend 是 `mmap`；`shared_memory` / `memfd` 主要用于实验。
- 审计结论：
  - v2 benchmark 当前强证据里用到的是 `shared_memory` semantic state，不是 `memfd`，也不是持久化 `mmap` 发布。

### 3.6 Replay / exact replay / validated replay / history-backed reuse

- `v2/runtime/replay.py:349-365`
  - `validated_replay_contract_compatible()` 只看结构兼容。
- `v2/runtime/driver.py:722-777`
  - replay 降级路径会把 output / memory metadata 标记为 `downgraded_execution_goal=True`。
- `v2/runtime/driver.py:1189-1217`
  - telemetry 明确分开 `validated_replay_count` 与 `exact_replay_count`。
- `v2/runtime/codeact.py:427-457`
  - `downgraded_execution_goal` 会改变 CodeAct plan。
- `v2/runtime/codeact_data_tasks.py:661-769`
  - cross-period output 是按当前 request 重新计算，而不是直接吐历史值。
- 审计结论：
  - exact replay 是“恢复已验证输出”。
  - validated replay 目前更像“允许跳过部分步骤的策略复用 / 降级重执行”。

### 3.7 CodeAct / sandbox / helper path

- `v2/runtime/codeact.py:549-605`
  - benchmark 主路径会写脚本、跑沙箱、记录 CodeAct execution record。
- `v2/runtime/codeact.py:770-900`
  - 生成的脚本固定 import `v2.runtime.codeact_data_tasks.build_candidate_output_payload`。
- `v2/runtime/codeact_sandbox.py:62-134`
  - 支持 `auto / bwrap / resource / none`；`auto` 下优先 `bwrap`。
- 审计结论：
  - “真实代码执行 + 沙箱 + 审计轨迹”成立。
  - “benchmark 主路径里用 LLM 生成代码”不成立。

### 3.8 Benchmark reality

- `v2/benchmark/live_runner.py:218-303`
  - `preflight`、`formal`、`compare`、`continuous`、`continuous-replay` 都由同一入口派发。
- `v2/benchmark/comparator_runner.py:94-163`
  - compare suite 真正有 hard gate / fairness manifest。
- `v2/benchmark/external_text_baseline.py:349-424`
  - external baseline 是四角色纯文本 baseline，但不是无约束 agent。

## 4. Mode Truth Table

### 4.1 模式与 benchmark 覆盖

| 模式 | 是否可用 | 本次 benchmark 覆盖 | 结论可用性 |
|---|---|---|---|
| `api + local` | 是 | `formal` 完成，`compare` 完成，`continuous-replay` 超时 | 可支撑 strong formal / compare；不能支撑 strong replay |
| `api + deterministic` | 是 | replay 尝试超时 | 只能说明 live API replay 仍有执行/耗时问题 |
| `deterministic + local` | 是 | replay collection 完成 | 可支撑 medium replay 行为判断 |
| `deterministic + deterministic` | 是 | 本次未作为主证据跑 benchmark | 不进入主要结论 |

### 4.2 功能路径 truth table

| 功能路径 | 当前状态 | benchmark 覆盖 | 证据等级 | 结论 |
|---|---|---|---|---|
| Loopback UDS control plane | 已实现并默认使用 | 是 | strong | 已证明 |
| `SubprocessExecutorTransport` | 已实现 | 否，只有测试/能力代码 | weak | capability-only |
| `shared_memory` semantic state | 已实现 | 是，formal/compare/replay medium | strong | 已证明 |
| `mmap` semantic publish | 已实现 | 当前审计未见主路径使用 | weak | capability-only |
| `memfd + SCM_RIGHTS` | 已实现 | 当前审计未见 benchmark 使用 | weak | capability-only |
| Exact replay | 已实现 | medium replay family 出现 | medium | 已证明存在，但非 strong |
| Validated replay | 已实现 | medium replay family 出现 | medium | 已证明存在，但语义需重命名/澄清 |
| LLM code generation in CodeAct | 有单独 demo/test | benchmark 主路径未使用 | weak | demo-only |
| `bwrap` sandboxed code execution | 已实现 | formal/compare 强证据触发 | strong | 已证明 |

## 5. Findings

### P0

- 本次未在强证据下证实“直接导致当前 benchmark 结果失真或错答的 P0 correctness bug”。
- 最严重问题集中在 benchmark 复现性、claim 语义和证据分层，而不是已复现的 catastrophic wrong answer。

### P1-1 `--family` 对 `continuous` / `continuous-replay` 实际无效

- Severity：P1
- Evidence Tier：medium
- Impact：benchmark 复现实验、报告命名、用时与 family 级结论都会被污染
- 代码位置：`v2/benchmark/live_runner.py:204-215`，`v2/benchmark/live_runner.py:247-303`
- 代码证据：
  - `_resolved_family_dir()` 会尊重 `args.family`
  - 但 `main()` 在 `continuous` / `continuous-replay` 分支里判断的是 `if args.family_dir is None`
  - 所以传 `--family` 时，虽然解析出了 `family_dir`，仍然走默认 collection 分支
- 测试 / benchmark 证据：
  - 本次命令：`timeout 300 /usr/bin/python3 -m v2.benchmark.live_runner --suite continuous-replay --family long_doc_metric_replay_v1 --benchmark-tier dev --role-path-mode deterministic --embedding-mode local --suite-id independent-codex-audit-20260705`
  - 结果实际产出的是 collection 报告：`/statebus/runs/v2-live/runtime/benchmark_reports/independent-codex-audit-20260705-continuous-replay.json`
  - 现有测试 `tests/v2/test_preflight_and_live_runner.py:488-709` 覆盖了 `--family-dir` 和默认 collection，但没有覆盖 `continuous-replay + --family`
- 为什么重要：
  - 审计者和评委现场 rerun 单 family 时，可能悄悄变成全 collection rerun
  - 会放大运行时、掩盖 family 级 bottleneck，并误导报告路径判断
- 修复建议：
  - `continuous` / `continuous-replay` 分支改为判断 `args.family is None and args.family_dir is None`
  - 新增两个 CLI regression tests：`continuous --family ...`、`continuous-replay --family ...`
- 对竞赛答辩的影响：
  - 这是很容易被现场复现戳穿的问题，应在任何公开 rerun 前修掉

### P1-2 `validated replay` 的名称和 admissibility contract 都比真实语义更激进

- Severity：P1
- Evidence Tier：medium
- Impact：replay claim 的可信度、可解释性与安全边界
- 代码位置：
  - `v2/runtime/replay.py:349-365`
  - `tests/v2/test_replay.py:208-262`
  - `v2/runtime/driver.py:722-777`
  - `v2/runtime/driver.py:1189-1217`
  - `v2/runtime/codeact.py:427-457`
  - `v2/runtime/codeact_data_tasks.py:661-769`
- 代码证据：
  - `validated_replay_contract_compatible()` 只校验 `task_family`、`intent_op`、`required_tools`、`required_outputs` 和参数形状
  - `tests/v2/test_replay.py:208-262` 明确允许不同 `metric` / `ticker` 仍判兼容
  - `driver.py` 在降级路径里显式写入 `downgraded_execution_goal=True`
  - `codeact_data_tasks.py` 的 cross-period 输出按当前 request 重算当前答案，而不是恢复历史答案
- 测试 / benchmark 证据：
  - medium replay `cross-period-002/004/006/008` 的 case artifact 全部是 `validated_replay`，并带 `downgraded_execution_goal=true`
  - 但输出值是当前轮正确值，如 `cross-period-006` 产出 `revenue_value = 87`
  - long-doc `replay-longdoc-003/008` 也体现同样模式
- 为什么重要：
  - 当前名字让人自然理解成“已经验证可直接 replay 答案”
  - 真实语义其实更接近“允许跳过部分步骤的降级复用 / strategy reuse”
  - 这不是纯粹的命名小问题；它决定 claim 是否会被质疑为过度包装
- 修复建议：
  - 对外叙事改为 `validated downgraded reuse` 或 `strategy-backed replay`
  - telemetry/report 中分离“答案恢复型复用”和“降级执行型复用”
  - 按 task family 引入更细的 compatibility key，而不是全局 shape-only
- 对竞赛答辩的影响：
  - 不建议把 validated replay 讲成“安全答案复原”
  - 建议讲成“有 provenance / gate / downgrade 的可控复用层”

### P1-3 formal 的 token 节省主要来自 pruning，不是 structured control 单独贡献

- Severity：P1
- Evidence Tier：strong
- Impact：核心创新叙事与 claim attribution
- 代码位置：
  - `v2/retrieval/pipeline.py:128-252`
  - `v2/runtime/driver.py:1390-1425`
  - formal suite 报告：`/statebus/runs/v2-live/runtime/benchmark_reports/independent-codex-audit-20260705-formal-suite.json`
- 代码证据：
  - retrieval pipeline 同时存在 semantic chunk、table structure 和 pruning profile
  - state publish 与 retrieval pruning 都在 driver telemetry 里有独立指标
- 测试 / benchmark 证据：
  - strong formal：
    - `control_bytes_delta_l0_to_l1 = 736`
    - `pruning_bytes_saved_vs_l0 = 6255`
    - L0 `llm_total_tokens = 14277`
    - L1 `llm_total_tokens = 14659`
    - L2 `raw_evidence_bytes_seen_by_llm = 9297`，明显低于 L0 的 `15552`
  - 这说明：
    - structured control 的 control bytes 节省存在
    - 但 prompt/token 的主要变化是 evidence pruning 带来的
    - L1 甚至可能让 token 更高
- 为什么重要：
  - 如果把全部 token 节省都归因于 typed protocol，论证会被轻易击穿
  - 更强、更真实的叙事是“三件事协同”：typed control、semantic pruning、non-text state handoff
- 修复建议：
  - 报告中显式拆分三类收益
  - 把协议收益更多放在 `carrier compare` / `text same semantic selection` 类对照里
- 对竞赛答辩的影响：
  - 这不是削弱创新，反而是让创新点更精确、更难被反驳

### P1-4 `compare` 强证据支持效率差分，不支持端到端速度优势

- Severity：P1
- Evidence Tier：strong
- Impact：对外性能 claim
- 代码位置：
  - `v2/benchmark/comparator_runner.py:49-91`
  - `v2/benchmark/comparator_runner.py:94-163`
  - compare 报告：`/statebus/runs/v2-live/runtime/benchmark_reports/independent-codex-audit-20260705-cold-start-compare.json`
  - compare diagnostics：`/statebus/runs/v2-live/audit_outputs/compare_api_local_diagnostics/independent-codex-audit-20260705-cold-start-compare-20260705_070925/summary.json`
- 代码证据：
  - comparator runner 会独立计算 prompt / token / control / end-to-end / system overhead 差分
- 测试 / benchmark 证据：
  - fairness gate：通过
  - `comparison_valid = true`
  - `llm_total_tokens_delta = -1092`
  - `prompt_bytes_delta = -5056`
  - `control_bytes_delta = -603`
  - 但：
    - `llm_ms_delta = +2270ms`
    - `end_to_end_ms_delta = +10365ms`
    - `system_overhead_ms_delta = +8095ms`
  - diagnostics 结论：`runtime_non_llm_overhead_dominates`
- 为什么重要：
  - 当前 strongest performance story 不是“更快”
  - 是“更少 bytes / tokens，但 today 的 runtime stack 还更重”
- 修复建议：
  - 对外改成“通信效率更高，端到端延迟仍受 runtime overhead 主导”
  - 如果要讲速度，只能讲内部 carrier 对照或未来优化方向
- 对竞赛答辩的影响：
  - 这是必须提前澄清的口径，否则非常容易被 benchmark 图反打

### P2-1 benchmark 主路径里的 CodeAct 不是 live LLM code generation

- Severity：P2
- Evidence Tier：strong
- Impact：CodeAct 创新 claim 的真实性
- 代码位置：
  - `v2/runtime/codeact.py:424-509`
  - `v2/runtime/codeact.py:549-605`
  - `v2/runtime/codeact.py:770-900`
  - `v2/runtime/codeact_data_tasks.py:661-769`
  - `tests/v2/test_bounded_llm_codeact_demo.py:89-176`
- 代码证据：
  - benchmark 主路径写出的脚本固定 import `build_candidate_output_payload`
  - cross-period / long-doc / incident 的 candidate output 来自 repo 内 helper 逻辑
  - LLM 代码生成能力只存在于 bounded demo / diagnostics，不在 runtime mainline benchmark path
- 测试 / benchmark 证据：
  - strong formal：`codeact_sandbox_bwrap_count = 8`
  - strong compare：`codeact_sandbox_bwrap_count = 3`
  - bounded demo 测试证明了 API 生成、repair、fallback 机制存在，但那是 demo path
- 为什么重要：
  - 当前真正被 benchmark 证明的是：
    - structured executable artifact path
    - sandboxed execution
    - execution audit / caching
  - 不是“LLM 在比赛主路径里稳定写代码”
- 修复建议：
  - benchmark 主叙事降级为 `sandboxed executable artifact path`
  - LLM CodeAct 保留为独立 demo / supplementary evidence
- 对竞赛答辩的影响：
  - 建议把“可证明的系统工程亮点”和“还在展示级别的 codegen 亮点”分开讲

### P2-2 强 replay 证据缺失，当前 replay headline 只能算 medium

- Severity：P2
- Evidence Tier：strong for blockage, medium for replay behavior
- Impact：replay / memory reuse claim 的置信度
- 代码位置：`v2/benchmark/live_runner.py:275-303`
- 测试 / benchmark 证据：
  - strong replay attempt：
    - `timeout 300 /usr/bin/python3 -m v2.benchmark.live_runner --suite continuous-replay --benchmark-tier dev --role-path-mode api --embedding-mode local ...`
    - 结果：超时，未产出完整 suite artifact
  - medium-strong replay attempt：
    - `api + deterministic` 也超时
  - medium replay completed：
    - `deterministic + local` collection 完成，`validated_replay_count = 17`，`exact_replay_count = 3`
- 为什么重要：
  - replay 是系统主叙事之一，但 strongest mode 没有完成
  - 如果不标注证据降级，就会把 medium evidence 误包装成 strongest claim
- 修复建议：
  - 修复 `--family` bug
  - 做一个能在 `api + local` 300s 内跑完的 replay slice
  - 单独提供 strong replay artifact，而不是只依赖 det+local collection
- 对竞赛答辩的影响：
  - replay 仍值得保留，但必须诚实标注为“目前 strongest proof 不完整”

### P2-3 本地 embedding + fork 路径存在明确的进程模型警告

- Severity：P2
- Evidence Tier：strong
- Impact：容器可移植性、稳定性、性能可预期性
- 代码位置：
  - local embedding 与 subprocess / sandbox 交互路径
  - `v2/runtime/codeact.py:558-569`
  - `v2/runtime/codeact_sandbox.py:62-134`
- 测试 / benchmark 证据：
  - 本次补跑命令：
    - `timeout 120 /usr/bin/python3 -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode api --embedding-mode local --suite-id codex-stderr-probe > /tmp/codex_compare_stdout.txt 2> /tmp/codex_compare_stderr.txt`
  - stderr 明确出现多次：
    - `huggingface/tokenizers: The current process just got forked... Disabling parallelism to avoid deadlocks...`
- 为什么重要：
  - 这不是纯噪声，它说明 tokenizer 已在 fork 前初始化，child process 需要禁并行规避死锁
  - 在不同容器、不同负载、不同 worker 策略下都可能演化为更难 debug 的问题
- 修复建议：
  - 显式设置 `TOKENIZERS_PARALLELISM=false`
  - 避免在 fork 前初始化 tokenizer / embedding stack
  - 或改用更稳定的 worker 生命周期模型
- 对竞赛答辩的影响：
  - 如果现场要求解释 local mode 稳定性，这会是一个真实的 OS 工程弱点

### P2-4 non-text state 的真实 benchmark 证据只覆盖 shared memory，不覆盖 memfd/subprocess/mmap

- Severity：P2
- Evidence Tier：strong for shared memory, weak for memfd/subprocess/mmap
- Impact：创新点表述边界
- 代码位置：
  - `v2/state/store.py:22-65`
  - `v2/runtime/driver.py:1399-1425`
  - `statepool/store.py:20-27`
  - `statepool/store.py:245-342`
  - `statepool/store.py:369-408`
- 代码证据：
  - v2 layered state store 对 semantic state 首选 `SHARED_MEMORY`
  - legacy statepool 仍保留 `mmap` / `shared_memory` / `memfd` 分层
  - memfd + `SCM_RIGHTS` 的实现是存在的
- 测试 / benchmark 证据：
  - strong formal：
    - L2 `semantic_state_transfer_count = 8`
    - L2 `shared_memory_publish_count = 8`
    - L2 `mmap_publish_count = 0`
  - strong compare：
    - `semantic_state_transfer_count = 3`
    - `shared_memory_publish_count = 3`
    - `mmap_publish_count = 0`
- 为什么重要：
  - `semantic state` 作为创新方向是真实的
  - 但“完整 Linux data plane 已 benchmark 证明”不真实
- 修复建议：
  - 保留分层架构叙事
  - 但把 `memfd/subprocess` 标成 implemented capability 或 demo path
  - 未来单独做 benchmark/diagnostic 激活
- 对竞赛答辩的影响：
  - 不该放弃这个亮点；应该更精准地讲“已证实到哪一层”

### P2-5 formal task family 过窄，8/8 不能外推为一般多智能体能力

- Severity：P2
- Evidence Tier：strong
- Impact：benchmark 可信度与覆盖范围
- 代码位置：
  - `v2/benchmark/samples/formal_financial_family/*.json`
  - `v2/retrieval/pipeline.py:193-240`
- 代码证据：
  - 8 个 formal case 全是 `compare_metric`
  - 全部 `expected_tool_name = table_retriever`
  - `TableStructureRetriever` 对 `metric_name` 做结构化匹配，通常仅选 1 行
- 测试 / benchmark 证据：
  - formal 8 个请求实际就是 revenue / gross_margin / operating_income 的单点读取
- 为什么重要：
  - 8/8 很适合作为“精确数值任务正确性”证据
  - 但不适合作为“多角色复杂协作、开放式 long doc reasoning、通用工具使用”证据
- 修复建议：
  - 保留 formal family 作为 precision anchor
  - 另加更强的 second formal family 或把 replay / incident 作为主叙事补强
- 对竞赛答辩的影响：
  - 主动承认 formal 范围，会比被动挨打更稳

### P2-6 测试更偏 deterministic contract，遗漏 live CLI / live benchmark 行为

- Severity：P2
- Evidence Tier：strong
- Impact：测试绿线与实际 claim 之间的鸿沟
- 代码位置：
  - `tests/v2/test_preflight_and_live_runner.py:488-709`
  - `tests/v2/test_continuous_runner.py:204-260`
  - `tests/v2/test_bounded_llm_codeact_demo.py:89-176`
  - `tests/v2/test_minimal_benchmark.py:223,295`
- 代码证据：
  - replay 系列测试大量使用 deterministic role path
  - `--family` 的连续 suite 行为未被测到
  - live API / live local 的测试点很少
- 测试 / benchmark 证据：
  - 本次 pytest：
    - `71 passed`
    - `18 passed`
    - `21 passed`
  - 但 live CLI 仍出现了 `--family` bug；strong replay 仍超时
- 为什么重要：
  - 说明当前测试更擅长保护 schema / contract / deterministic expectations
  - 不足以保护 strongest operational claims
- 修复建议：
  - 增加 `api + local` 小规模 smoke
  - 增加 `--family` CLI regression
  - 增加 `SubprocessExecutorTransport` e2e
- 对竞赛答辩的影响：
  - 可以说“tests 很全”，但不能把它讲成“所有主 claim 都已经 live-verified”

### P3-1 history-backed reuse 的一部分指标仍带启发式 / bookkeeping 成分

- Severity：P3
- Evidence Tier：medium
- Impact：reuse telemetry 的解释精度
- 代码位置：`v2/runtime/smoke.py:786-839`
- 代码证据：
  - `history_step_reduction_count` 由 task family / intent / artifact count 的硬编码规则推断
  - `history_reuse_gain` 只是 `step_reduction_count > 0` 的布尔化结果
- 测试 / benchmark 证据：
  - 该逻辑更多服务于 `runtime.smoke` / older summary，而不是本次 strongest v2 compare/formal 主路径
- 为什么重要：
  - 如果把这些 smoke 指标讲成精确的 runtime step elimination 证据，会过头
- 修复建议：
  - 区分“observed runtime skip”与“inferred history utility”
- 对竞赛答辩的影响：
  - 这是低优先级问题，但要避免把 smoke heuristic 讲成 benchmark ground truth

## 6. Fairness & Benchmark Audit

### 6.1 external baseline 的公平性结论

- 当前实现比“纯 strawman baseline”更认真。
- `v2/benchmark/external_text_baseline.py:111-167`
  - 有动态 fairness gate：
    - `no_typed_state_used`
    - `no_metadata_leakage`
    - `llm_only_decisions`
    - `visible_candidate_only`
- `v2/benchmark/external_text_baseline.py:349-424`
  - planner 不看全文
  - retriever 是唯一看全文的角色
  - executor / summarizer 只看压缩过的信息
- 但它仍然不是完全对称：
  - route/tool 是候选受限的
  - `candidate notes` 中会公开 `support_terms` 与 `source_doc_hashes`
  - 数据集与 route profiles 都是 repo-local、contest-facing构造

### 6.2 compare suite 的当前可信边界

- strong compare 在本次审计下有效：
  - hard gate 通过
  - `comparison_valid = true`
  - 两边质量都 3/3
- 但它的 `claim_level` / `claim_restriction` 明确是：
  - `prototype`
  - `dev_fixed_answer_external_fairness_only_not_formal_financial_superiority`
- 结论：
  - compare 适合证明“在相同 dev fixed-answer 框架里，StateBus 通信/提示负担更低”
  - 不适合被扩展成“formal superiority”

### 6.3 formal family 的公平性

- formal 不是 baseline unfairness 的问题，主要是任务太简单、太结构化。
- 8 个任务全是单指标单季度提取；StateBus 的结构化 table path 自然占优。
- 这不等于 formal 无效，只是意味着它证明的是“精确 structured retrieval 系统价值”，不是通用 reasoning superiority。

### 6.4 deterministic 与真实模式偏差

- preflight 证明 `api + local` 可用，但 replay strongest mode 没跑完。
- medium replay collection 在 `deterministic + local` 下：
  - `llm_total_tokens = 0`
  - 说明 role path 的 live LLM 成本并未进入 replay headline
- 审计结论：
  - deterministic 结果可以证明 contract 和 operational path
  - 不能独自证明真实 LLM 条件下的 replay 价值

## 7. Replay & Memory Audit

### 7.1 exact replay

- 当前语义最清晰。
- 依赖完整 exact key、runtime signature、input artifact hash。
- medium evidence：
  - `long_doc_metric_replay_v1` 出现 `exact_replay_count = 3`
  - 典型 case：`replay-longdoc-005`、`replay-longdoc-010`

### 7.2 validated replay

- 当前不应再讲成“安全恢复旧答案”。
- 更准确的描述：
  - admissibility gate 允许选择历史候选
  - runtime 改成 `downgraded_execution_goal`
  - helper 用当前 request + 可消费历史 ref 重新产出当前轮结果
- 这其实是一个值得保留的创新方向：
  - 它比“要么完全 exact replay，要么完全重跑”更细粒度
  - 但叙事必须从 `answer replay` 改成 `degraded reusable execution`

### 7.3 assist / history-backed reuse

- medium replay collection 里：
  - `L3_artifact_reuse_count = 39`
  - `L3_history_step_reduction_count = 12`
- 这说明系统确实有“历史对象 + 策略 ref”级别的复用
- 但当前最稳的表达仍然应是：
  - `artifact / strategy reuse with replay admissibility`
  - 而不是直接说“memory solved the task”

### 7.4 该收紧什么，不该收紧什么

- 应收紧：
  - validated replay 的命名
  - family-specific compatibility 判据
  - replay claim 的证据等级标注
- 不应过度收紧：
  - 不必把 validated replay 全删掉再只剩 exact replay
  - 不必因为有风险就放弃“中间态复用”这条创新路线
- 最好的方向：
  - 保留这个层次
  - 但把它定义成“受 gate 控制的降级复用层”

## 8. CodeAct Audit

### 8.1 benchmark 主路径是否真的走 LLM code generation

- 结论：否。
- 原因：
  - benchmark 脚本由 `CodeActRunner._build_script()` 固定生成
  - 实际执行逻辑来自 `v2.runtime.codeact_data_tasks`

### 8.2 benchmark 主路径里什么是真的

- 真正成立的部分：
  - 真实脚本落盘
  - 真实子进程运行
  - `bwrap` 沙箱
  - execution record / audit / cache
- strong evidence：
  - formal：`codeact_sandbox_bwrap_count = 8`
  - compare：`codeact_sandbox_bwrap_count = 3`

### 8.3 fallback / demo 路径

- `tests/v2/test_bounded_llm_codeact_demo.py:89-176`
  - 证明 bounded LLM codegen、repair、fallback、AST policy 都存在
- 但这是 demo / diagnostics 证据，不是 benchmark runtime 主证据

### 8.4 当前 CodeAct 该怎么讲

- 应强化：
  - `sandboxed executable artifact path`
  - `auditable execution provenance`
  - `bwrap actually used on benchmark path`
- 应降级：
  - `benchmark already proves live LLM code writing`

## 9. Retrieval / State / Transport Audit

### 9.1 Retrieval

- `TableStructureRetriever` 对 formal family 高度匹配。
- `SemanticChunkRetriever` 默认 `top_k = 1`，对 long-doc/semantic 任务更重要。
- 结论：
  - retrieval 设计本身不差
  - 但 formal tasks 明显偏向 table exact-hit，对 StateBus 有利

### 9.2 Non-text state

- 强证据已证明：
  - semantic state 不是纸面 feature
  - `shared_memory` 真实被 publish / hydrate
- 仍未证明：
  - memfd path 的 benchmark 收益
  - mmap publish 在当前 v2 benchmark 的实际价值

### 9.3 UDS / subprocess / memfd / mmap 的真实价值

- UDS typed framing：
  - 真实存在
  - benchmark 使用 loopback path
- subprocess transport：
  - 真实存在
  - 未 benchmark
- memfd：
  - 真实实现
  - 未 benchmark
- mmap：
  - 在 legacy statepool / replay persistence 设计中重要
  - 本次强证据未看到 v2 semantic publish 走 mmap

### 9.4 值得继续强化的创新点

- `typed control plane` 作为 prompt slicing carrier
- `semantic state ref` 作为角色间非展开状态
- `execution artifact + replay ledger + provenance`

## 10. Innovation Audit

### 10.1 真实创新点

1. `typed control plane + prompt slicing`
   - 不是简单“换个序列化库”
   - 是把 role handoff 变成可计量、可裁剪、可审计对象
2. `semantic state as first-class carrier`
   - 当前 strong 证据已证明 shared-memory 语义状态 handoff
3. `replay with admissibility + downgrade semantics`
   - 方向是对的
   - 当前问题在命名和证据，而不是方向本身
4. `execution provenance / artifact ledger / replay ledger`
   - 这是系统工程价值，不是普通 RAG 的自然延伸

### 10.2 伪创新 / 包装性叙事

- “benchmark 已证明 LLM CodeAct 主路径”
- “compare 已证明 formal superiority / latency superiority”
- “memfd/multi-process data plane 已被主 benchmark 证明”

### 10.3 应该降级的叙事

- `validated replay = 可靠答案恢复`
- `formal 8/8 = 通用多智能体复杂协作能力`
- `token savings mostly from protocol`

### 10.4 应该强化的叙事

- `structured carrier + semantic pruning + non-text state` 是一套协同系统，而不是单点 trick
- `downgraded reusable execution` 是比“纯 cache hit”更有系统味道的创新方向
- `bwrap sandbox + artifact audit` 是真实可展示的工程亮点

### 10.5 方向对了但证据不够

- `api + local` replay
- `SubprocessExecutorTransport`
- `memfd + SCM_RIGHTS` data plane headline

## 11. Tests & Experiments Actually Run

### 11.1 环境与 preflight

- `git branch --show-current && git rev-parse HEAD && git status --short && git diff --stat`
- `echo API_KEY=${STATEBUS_LLM_API_KEY:+set}`
- `test -d /statebus/models/Qwen3-Embedding-0.6B`
- 四种 preflight：
  - `/usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode api --embedding-mode local`
  - `/usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode api --embedding-mode deterministic`
  - `/usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode deterministic --embedding-mode local`
  - `/usr/bin/python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode deterministic --embedding-mode deterministic`
- 结果：4/4 通过
- Evidence Tier：环境可用性 strong

### 11.2 pytest

- `/usr/bin/python3 -m pytest -q tests/v2/test_replay.py tests/v2/test_continuous_runner.py tests/v2/test_fixed_answer_and_external_baseline.py tests/v2/test_preflight_and_live_runner.py tests/v2/test_compare_diagnostics.py -x`
  - 结果：`71 passed`
- `/usr/bin/python3 -m pytest -q tests/v2/test_subprocess_executor.py tests/v2/test_control_plane.py tests/v2/test_bounded_llm_codeact_demo.py -x`
  - 结果：`18 passed, 100 warnings`
- `/usr/bin/python3 -m pytest -q tests/v2/test_smoke.py tests/v2/test_minimal_benchmark.py -x`
  - 结果：`21 passed`
- Evidence Tier：测试覆盖 strong，但不是 strongest claim 的替代物

### 11.3 runtime smoke

- `/usr/bin/python3 -m runtime.smoke`
- 结果：
  - `text` 与 `protocol` mode 均跑通
  - 可用于旧路径 sanity，不作为 v2 主结论
- Evidence Tier：weak

### 11.4 strong benchmarks

- formal:
  - `timeout 300 /usr/bin/python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode api --embedding-mode local --suite-id independent-codex-audit-20260705`
  - 结果：完成
  - 关键报告：`/statebus/runs/v2-live/runtime/benchmark_reports/independent-codex-audit-20260705-formal-suite.json`
- compare:
  - `timeout 300 /usr/bin/python3 -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode api --embedding-mode local --suite-id independent-codex-audit-20260705`
  - 结果：完成
  - 关键报告：`/statebus/runs/v2-live/runtime/benchmark_reports/independent-codex-audit-20260705-cold-start-compare.json`
- Evidence Tier：strong

### 11.5 replay benchmarks

- strong replay attempt:
  - `timeout 300 /usr/bin/python3 -m v2.benchmark.live_runner --suite continuous-replay --benchmark-tier dev --role-path-mode api --embedding-mode local --suite-id independent-codex-audit-20260705`
  - 结果：超时
- medium-strong replay attempt:
  - `timeout 300 /usr/bin/python3 -m v2.benchmark.live_runner --suite continuous-replay --family long_doc_metric_replay_v1 --benchmark-tier dev --role-path-mode api --embedding-mode deterministic --suite-id independent-codex-audit-20260705`
  - 结果：超时
- medium replay completed:
  - `timeout 300 /usr/bin/python3 -m v2.benchmark.live_runner --suite continuous-replay --family long_doc_metric_replay_v1 --benchmark-tier dev --role-path-mode deterministic --embedding-mode local --suite-id independent-codex-audit-20260705`
  - 结果：完成，但因 `--family` bug 实际跑成 collection
  - 报告：`/statebus/runs/v2-live/runtime/benchmark_reports/independent-codex-audit-20260705-continuous-replay.json`
- Evidence Tier：medium

### 11.6 额外 stderr probe

- `timeout 120 /usr/bin/python3 -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode api --embedding-mode local --suite-id codex-stderr-probe > /tmp/codex_compare_stdout.txt 2> /tmp/codex_compare_stderr.txt`
- 结果：
  - 运行完成
  - stderr 含重复 `huggingface/tokenizers ... got forked ... Disabling parallelism ...`
- Evidence Tier：strong

### 11.7 未能运行或未完成的项

- `api + local` replay suite：300 秒内未完成
- `api + deterministic` replay suite：300 秒内未完成
- 未对 `memfd + subprocess transport` 做 benchmark 级单独激活

## 12. Comparison With docs/improvement

### 12.1 一致项

- `docs/improvement/07_non_text_state_transfer_audit.md`
  - 正确看到 memfd 是 capability，formal benchmark 主路径未激活
- `docs/improvement/08_performance_and_overhead_breakdown.md`
  - 正确强调 runtime overhead 会吞掉协议层节省
- `docs/improvement/11_competition_readiness_audit.md`
  - 正确指出 CodeAct 主 benchmark path 与 live LLM codegen 需要分开讲
  - 正确指出 loopback UDS 与 subprocess transport 的差别是答辩重点

### 12.2 冲突项 / 过时项

- `docs/improvement/11_competition_readiness_audit.md` 的 external revenue fallback 判断已过时
  - 当前代码 `v2/benchmark/external_text_baseline.py:526-532` 已不再回退到 `context.revenue_value`
- `docs/improvement/11_competition_readiness_audit.md` 的 table retriever `rows[:1]` 判断已过时
  - 当前代码 `v2/retrieval/pipeline.py:227-230` 已按 intent / family 调整 `row_limit`
- `docs/improvement/11_competition_readiness_audit.md` 把 validated replay 主要写成“跨实体 wrong-answer replay bug”，与当前代码和 case artifact 不完全一致
  - 当前 medium evidence 更支持“降级重执行 + 语义/命名风险”
- `docs/improvement/README.md`、`01_*`、`02_*` 仍保留较强的旧实验口径
  - 包含 formal superiority / efficiency / latency 数字与本次审计报告不一致
  - 当前 audited strong compare 是 dev-only、prototype-scope，且 StateBus 更慢

### 12.3 遗漏项

- 没有现有文档抓到 `live_runner --family` bug
- 没有现有文档明确把“replay strongest mode 超时”写成证据分层问题
- 现有文档普遍低估了“structured control 节省”和“semantic pruning 节省”必须拆开讲的重要性
- 没有现有文档把 tokenizer fork 警告记录为 local mode 的 OS 层工程问题

## 13. Action Plan

1. `bug fix`：修复 `live_runner.py` 中 `continuous` / `continuous-replay` 的 `--family` 判定，并补回归测试。
2. `narrative correction`：把 `validated replay` 对外改名或至少改解释，明确它是 `downgraded reusable execution`，不是“安全恢复旧答案”。
3. `benchmark fix`：做一个 `api + local` 可在 300 秒内跑完的 replay slice，补强 strongest replay evidence。
4. `fairness fix`：把 dev compare 的 claim scope 和 formal family 的 claim scope 分开写，禁止把 compare headline 迁移成 formal superiority 叙事。
5. `innovation strengthening`：在主报告中显式拆分 `structured control`、`semantic pruning`、`non-text handoff` 三类收益。
6. `test coverage fix`：新增 `--family` live CLI test、`api + local` smoke、`SubprocessExecutorTransport` e2e、replay strong-path smoke。
7. `runtime fix`：处理 local embedding + fork 的 tokenizer 警告，避免更难 debug 的 deadlock / perf 风险。
8. `innovation strengthening`：将 `bwrap sandboxed executable artifact path` 上升为正式亮点，把 LLM CodeAct 放为补充展示。
9. `benchmark fix`：扩展 formal task family，至少加入一个 cross-period / multi-step structured family，避免 formal 只等于 table exact-hit。
10. `innovation strengthening`：单独做 `SubprocessExecutorTransport + memfd` 展示性 benchmark，作为 Linux 系统层亮点，而不是继续让它停在 capability-only。

## 14. Appendix

### 14.1 关键报告路径

- formal suite：
  - `/statebus/runs/v2-live/runtime/benchmark_reports/independent-codex-audit-20260705-formal-suite.json`
- compare suite：
  - `/statebus/runs/v2-live/runtime/benchmark_reports/independent-codex-audit-20260705-cold-start-compare.json`
- compare diagnostics：
  - `/statebus/runs/v2-live/audit_outputs/compare_api_local_diagnostics/independent-codex-audit-20260705-cold-start-compare-20260705_070925/summary.json`
- replay collection：
  - `/statebus/runs/v2-live/runtime/benchmark_reports/independent-codex-audit-20260705-continuous-replay.json`
- long-doc replay family：
  - `/statebus/runs/v2-live/runtime/long_doc_metric_replay/benchmark_reports/independent-codex-audit-20260705-continuous-replay-long_doc_metric_replay.json`
- cross-period replay family：
  - `/statebus/runs/v2-live/runtime/cross_period_financial/benchmark_reports/independent-codex-audit-20260705-continuous-replay-cross_period_financial.json`

### 14.2 关键 JSON 字段摘录

```json
{
  "formal_comparison_summary": {
    "control_bytes_delta_l0_to_l1": 736.0,
    "pruning_bytes_saved_vs_l0": 6255.0
  },
  "compare_mode_headline_metrics": {
    "llm_total_tokens_delta": -1092.0,
    "prompt_bytes_delta": -5056.0,
    "control_bytes_delta": -603.0,
    "end_to_end_ms_delta": 10365.952605999999,
    "system_overhead_ms_delta": 8095.857421000001
  },
  "replay_collection_summary": {
    "validated_replay_count": 17.0,
    "exact_replay_count": 3.0,
    "replay_target_round_count": 20.0,
    "replay_observed_round_count": 20.0
  }
}
```

### 14.3 关键 artifact 级观察

- `cross-period-006`
  - `replay_class = validated_replay`
  - `downgraded_execution_goal = true`
  - `revenue_value = 87`
- `replay-longdoc-005`
  - `replay_class = exact_replay`
  - `restored_replay_class = exact_replay`
- `codex-stderr-probe`
  - stderr 含多次 tokenizer fork warning

### 14.4 repo 内配套 artifact 目录

- 本次未额外复制 `/statebus/runs/...` 报告到 repo 内
- 审计引用的 primary artifacts 保持在 `/statebus/runs/v2-live/...`
