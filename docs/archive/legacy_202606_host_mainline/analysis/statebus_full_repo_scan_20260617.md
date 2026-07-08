# StateBus 全量仓库扫描审计报告

日期：2026-06-17

扫描范围：`/home/qcrs/statebus/project` 全部文档、代码、测试、benchmark run 结果

文档定位：

- 本文档只承担“全量扫描 + 结构诊断 + benchmark 审计 + 主诊断”职责。
- 后续行动计划已拆出到：
  - `docs/review/statebus_reset_plan_from_full_scan_20260617.md`
- 读取顺序建议：
  1. 先读本文档，理解现状
  2. 再读 reset plan，决定是否执行

---

## 1. Repository Map（仓库地图）

### 1.1 代码模块地图

| 模块 | 目录 | 核心文件 | 规模 | 角色 |
|---|---|---|---|---|
| Agents | `agents/` | `sample_agents.py` (2205行) | 大 | Planner/Retriever/Executor/Summarizer 四角色实现 |
| Runtime | `runtime/` | `orchestrator.py` (2465行), `executor_runtime.py` (2190行), `contracts.py` (1024行), `llm.py` (799行), `langgraph_adapter.py` (479行) | 巨大 | 编排引擎、工具执行、契约校验、LLM 客户端、LangGraph 适配 |
| Protocol | `protocol/` | `messages.py` (1432行), `statebus.proto` (222行), `channels.py` (161行) | 中 | 消息定义、Protobuf 序列化、通道抽象 |
| StatePool | `statepool/` | `store.py` (612行) | 中 | mmap/SHM/CAS 三后端状态存储 |
| Memory | `memory/` | `store.py` (1313行) | 大 | SQLite + FAISS 混合记忆层 |
| Eval | `eval/` | `runner.py` (6359行), `metrics.py` (143行), `open_runner.py` (914行) | 巨大 | Benchmark 运行、指标采集、报告生成、外部对比 |
| Tasks | `tasks/` | `sample_tasks.py` (1067行), `local_corpus.py` (267行), `contest_family_spec.py` (241行) | 中 | 任务定义、语料检索、benchmark 包生成 |
| Tests | `tests/` | `test_smoke.py` (5780行), 4个辅助测试文件 | 大 | ~157 个测试，高度核心功能覆盖 |
| Scripts | `scripts/` | 21 个脚本 | 大 | 环境初始化、benchmark 启动、诊断扫描、结果重写 |

**不存在但文档提及的文件：** `runtime/registry.py`, `runtime/scheduler.py`, `runtime/graph_pruner.py`, `runtime/fsm.py` — 这些功能已内联到 `orchestrator.py` 和 `executor_runtime.py` 中。

### 1.2 文档分层地图

**权威需求源：**
- `docs/reference/题目.md` — 赛题题目原文，唯一必须反向对齐的源头

**当前有效主约束文档：**
- `docs/constraints/current_host_and_migration.md` — 环境策略与阶段划分
- `docs/constraints/current_feature_scope.md` — 功能边界与已完成/未完成项
- `docs/planning/implementation_plan.md` — 赛题拆解与架构规划（已注明不再是最新事实层）

**最新 Review/Execution Plan（有效）：**
- `docs/review/statebus_contest_first_refactor_execution_plan_20260617.md` — 最新竞品诚实头条重构计划
- `docs/review/statebus_full_restructure_execution_plan_20260616.md` — 六层重构计划（已被 06-17 计划窄化）
- `docs/review/statebus_contest_remaining_closure_plan_20260615.md` — 剩余问题 P0 清单（含具体行号证据）

**最新 Analysis（有效）：**
- `docs/analysis/honest_full_audit_20260617.md` — 最高证据密度的诚实审计
- `docs/analysis/mainline_repeat3_analysis_20260617.md` — 最新 run 分析

**部分历史但仍有参考价值：**
- `docs/analysis/host_full_api_repeat3_deep_analysis_20260616.md` — 揭示 text executor 结构化恢复路径（F-B1 问题的根源）
- `docs/analysis/statebus_deep_data_analysis_20260616.md` — 发现 executor 两条路径不对称的核心 bug
- `docs/analysis/statebus_deep_data_repair_plan_20260616.md` — 统一 lane policy 的修复方案

**历史/入门参考（过时但保留）：**
- `docs/reports/MASTER_PRESENTATION_GUIDE.md` — 2026-06-11，数据表已严重过时
- `docs/reference/statebus_architecture_and_implementation_plan.md` — 设计阶段产物
- `docs/reference/statebus_dual_plane_deep_design.md` — 设计阶段产物
- `docs/reference/multi-agent-system-design.md` — 辅助参考，技术栈已偏移
- `docs/reference/s_memory_agent_design.md` — 辅助参考，命名体系已偏移

**文档膨胀诊断：**
- `docs/review/` 目录包含 16 个文件，大部分是历史中间审查提示词/执行计划（如 `statebus_round3_audit_20260616.md`, `statebus_contest_aligned_review_20260614.md`, `statebus_v3_deep_review_memo_20260613.md` 等），它们曾是工作订单但现在变成历史包袱
- `docs/analysis/` 目录包含 30 个文件，其中约一半是中间诊断产物（如 `api_repeat1_smoke_analysis_20260616.md`, `api_repeat1_full_smoke_20260616.md` 等），仅对当时那一轮调查有效

### 1.3 Benchmark Pack 地图（13+1 个 v3 pack）

| Pack | 类型 | 任务数 | 模式 | 回答的问题 | 当前 gate 状态 |
|---|---|---|---|---|---|
| `contest_honest_headline_v1` | **formal-headline** | 40 | text+protocol | text_whole_lane vs state_packet_minimal | repeat=3 不足，waiting for repeat=10 |
| `contest_dual_mode_controlled_v3` | controlled composite（降级） | 40 | text+protocol | text_strict_pure_lane vs state_packet_minimal | 多个 withheld（hidden leak, guard incomplete） |
| `memory_dual_mode_fairness_v3` | audit-only | 40 | text+protocol | 双模式 object parity，不承担 replay proof | object parity gate passed |
| `typed_state_mechanism_v3` | **formal-secondary** | 8 | protocol-only | 机制真实性：typed state 是否真的生产/传递/消费 | state authenticity gate passed（唯一通过的机制门） |
| `memory_policy_controlled_v3` | formal-secondary | 4 | protocol-only | memory policy 单变量归因 | — |
| `memory_reuse_v3` | formal-secondary | (varies) | protocol-only | protocol-only replay proof | — |
| `planner_support_v3` | formal-secondary | 10 | protocol-only | yaml vs llm plan source | 报告有 bug（planner_one_shot_valid_rate 矛盾） |
| `typed_state_consumer_sensitivity_v3` | formal-secondary | 40 | protocol-only | 缺失/错误决策包的降级行为 | destructive controls pass |
| `external_text_baseline_audit_v3` | audit-only | — | 外部 | 外部纯文本 baseline audit | — |
| `text_definition_audit_v3` | audit-only | 40 | protocol-only | executor-boundary inline text 审计 | — |
| `typed_state_authenticity_v3` | legacy compatibility | — | protocol-only | 历史 legacy surface | — |
| `typed_state_full_rich_audit_v3` | audit-only | — | protocol-only | full-rich support/audit | — |
| `carrier_microbench_v3` | engineering audit | — | — | 工程审计 | — |
| `open_system_comparison_v1` | external comparison | — | 外部 | open engineering comparison | 由 `eval/open_runner.py` 生成 |

**读法边界（READ THIS FIRST）：**
- `contest_honest_headline_v1` 是唯一 contest-facing formal headline。
- `contest_dual_mode_controlled_v3` 已降级为内部 controlled composite。
- 不同 pack 回答不同问题，严禁交叉阅读。
- audit-only pack 不得升格为 headline claim。

### 1.4 脚本地图

**活跃入口（按优先级排列）：**

| 脚本 | 用途 | 活跃/归档 |
|---|---|---|
| `scripts/run_contest_plus_open_repeat3_suite.py` | **主套件启动器**，运行全部 StateBus + open packs | 活跃 |
| `scripts/run_statebus_mainline_repeat3_suite.sh` | StateBus 主线 repeat=3 | 活跃 |
| `scripts/run_open_extension_repeat3_suite.sh` | Open extension repeat=3 | 活跃 |
| `scripts/run_v3_comprehensive_check.py` | deterministic/local 综合检查（py_compile + pytest + smoke + 12 pack repeat=1） | 活跃 |
| `scripts/run_v3_next_stage_repeat3_suite.py` | 下一阶段 post-gate repeat suite（含 deterministic gate 前置） | 活跃 |
| `scripts/run_issue_discovery_smoke.py` | 问题发现快速扫描 | 活跃 |
| `scripts/run_v3_api_repeat3_suite.py` | v3 API repeat=3 | 活跃 |
| `scripts/generate_contest_family_yaml.py` | 从 family spec 重新生成 YAML | 活跃 |
| `scripts/rewrite_benchmark_outputs.py` | 原地重写 benchmark 报告 | 活跃 |
| `scripts/setup_host_dev_env.sh` | 环境初始化 | 活跃 |
| `scripts/run_v2_api_repeat3_suite.py` | v2 archived suite | **归档** |
| `scripts/run_v2_comprehensive_check.py` | v2 deterministic checker | **归档** |

**脚本膨胀诊断：** 21 个脚本中有多个近乎重复的包装器（.sh 包装 .py、不同 skip flag 组合），维护负担高。至少 3 个脚本是历史 v2 产物已归档。

### 1.5 主线热路径 vs 支线路径

**热路径（每次任务执行都经过）：**
- `runtime/orchestrator.py::Orchestrator.run_task()` → `_execute_plan()` — 编排主循环
- `agents/sample_agents.py::RetrieverAgent.execute_step()` — 检索 + 状态生成（~600行，最深热路径）
- `runtime/executor_runtime.py::execute_playbook_step()` — 工具执行调度
- `runtime/executor_runtime.py::build_feature_bundle()` — 特征提取
- `tasks/local_corpus.py::retrieve_corpus_docs()` — 混合检索
- `statepool/store.py::StatePool.put_bytes()/get_bytes()` — 状态存储
- `memory/store.py::MemoryStore.search()/replay_candidates()` — 记忆搜索
- `runtime/orchestrator.py::resolve_skip_retrieve_execute()/resolve_skip_execute()` — replay 判定
- `runtime/contracts.py::SchemaInterceptor.validate_result()` — 状态契约校验

**支线路径（只在特定条件下激活）：**
- `runtime/langgraph_adapter.py` — 仅在 `engine="langgraph"` 时走
- `runtime/uds_transport.py` + `runtime/remote_executor.py` — 仅在 `executor_transport="uds"` 时走
- `runtime/codeact_runner.py` — 当前标注为 experimental，未进入主路径
- `eval/open_runner.py` + `eval/text_open_baseline.py` — 仅在 open extension benchmark 时走
- `protocol/channels.py` — 仅用于给 state ref 附加 channel 元数据，不是关键路径

---

## 2. Evolution Analysis（版本演化分析）

### 2.1 项目起点

赛题要求（`docs/reference/题目.md`）的核心是三个维度：
1. **低开销通信** — 结构化协议替代自然语言交互
2. **非文本状态传递** — embedding/语义向量/中间表示的直接交换
3. **共享记忆复用** — 跨任务的知识积累和协同增强

评分权重：通信效率 25分、状态传递创新 20分、记忆复用效果 20分、系统完整性 20分、实验验证 15分。

### 2.2 关键转折与主线路演化

**Phase 0-2（2026-06-06 前）：从设计到 MVP**
- 从 0 到可运行的 text + protocol 双模式
- 实现 Protobuf 控制帧、能力表、schema 校验
- 4 Agent（Planner/Retriever/Executor/Summarizer）骨架落地

**Phase 3-4（2026-06-07~09）：StateRef + 共享记忆**
- `StateRef + mmap/shared_memory + FEATURE_BUNDLE` 状态传递落地
- SQLite + FAISS 共享记忆落地
- replay-aware 主线建立（`runs/host_goal_eval_*` 系列 12 个包记录了渐进式收缩过程）
- `06-08` 连续完成多轮 runtime-contract cleanup：从 `reuse_signature` 查询过滤中移除、`reuse_tags` 预过滤移除、`PlanStep.params` 退到 side-band `RuntimeTaskProfile`

**Phase 5（2026-06-13~15）：Audit Hardening**
- v3 benchmark surface 建立（13 个 pack 的 formal 读法边界）
- `contest_dual_mode_controlled_v3` 成为当时的 formal headline
- D1-D11 修改：typed-state 边界收口、memory policy 单变量化、planner 支持 validate-first
- `planner_validate_closure_verification_20260616.md` 确认验证优先实现了真实的检查/阻断/报告

**Phase 6（2026-06-15）：Remaining Issues 识别**
- `statebus_contest_remaining_closure_plan_20260615.md`：识别 5 个 P0 问题
  - P0-1：query 文本泄漏 route 答案词
  - P0-2：clean/reusable 行只有 single route（无竞争）
  - P0-3：corpus 证据拓扑未真正重建
  - P0-4：formal corpus 只是 gate-level safe，不是 structure-level clean
  - P0-5：reusable 任务不是真正的跨任务依赖

**Phase 7（2026-06-16）：Deep Data Analysis**
- 发现**核心不对称 bug**：text executor 有独立 `build_feature_bundle()` 恢复路径，protocol executor 的 `del registry` 导致盲信决策包。这等价于 text vs protocol 对比不公平。
- 提出 lane policy 统一方案

**Phase 8（2026-06-17）：Honest Headline Refactor**
- 创建 `contest_honest_headline_v1`：text side 使用 `text_whole_lane`（纯自然语言），正确通过 `whole_lane_text_guard`（pass_rate=1.00, hidden_field_leak=0.00）
- `contest_dual_mode_controlled_v3` 降级为内部 controlled composite
- `contest_honest_headline_v1` 获得最干净的 headline：single_variable=yes, variable_axes=mode, llm_tokens 几乎对称（text 415 vs protocol 416, delta=+0.2%），control_bytes -23.3%（text 8657 vs protocol 6641）
- 唯一 withheld 原因：`contest_repeat_insufficient`（repeat=3，需要 repeat=10），不是结构性问题

### 2.3 关键文档状态矩阵

| 文档 | 日期 | 当前状态 | 结论是否仍成立 |
|---|---|---|---|
| `implementation_plan.md` | 06-06 | **历史参考** | 架构规划仍大致正确，但 Docker/openEuler 终态描述已过时 |
| `MASTER_PRESENTATION_GUIDE.md` | 06-11 | **严重过时** | 数据表全部标为 scoped/audit，未反映 06-17 headline |
| `task_design_and_mode_comparison.md` | 06-13 | **当前有效** | pack 地图基本准确，但未包含 contest_honest_headline_v1 |
| `statebus_remaining_issues_and_solutions_20260615.md` | 06-15 | **部分历史** | Issues 2/3/7 仍完全有效，Issue 6 已被澄清 |
| `statebus_contest_remaining_closure_plan_20260615.md` | 06-15 | **仍有效** | P0-1 到 P0-5 仍是当前所有文档的基础问题目录 |
| `statebus_full_restructure_execution_plan_20260616.md` | 06-16 | **被窄化** | 六层重构野心被 06-17 计划窄化为仅 contest headline refactor |
| `statebus_deep_data_analysis_20260616.md` | 06-16 | **部分历史** | 核心发现（executor 不对称）的结论仍有效，但 lane policy 已进行部分修正 |
| `honest_full_audit_20260617.md` | 06-17 | **当前有效** | 最高证据密度的审计，结论最新 |
| `statebus_contest_first_refactor_execution_plan_20260617.md` | 06-17 | **当前有效** | 最新行动计划 |

### 2.4 历史包袱来源

1. **文本对比对象的迭代**：从 `text_strict_pure_lane`（携带 Route:/Tool: 结构化字段，hidden leak rate=1.0）→ `text_whole_lane`（纯自然语言，guard pass）→ 仍未是真正的 external traditional pure-text multi-agent baseline（`external_text_baseline_audit_v3` 仅 audit-only）
2. **Pack 膨胀**：从 v1/v2 的少数几个 pack（carrier_controlled_v2, semantic_retention_v2 等）膨胀到 v3 的 13+1 个 pack，其中约一半是 audit-only/support surface，不能用于 headline claim
3. **多轮 runtime contract 收缩**：从 `reuse_signature` 的显式查询过滤 → 移除 → `reuse_tags` 预过滤移除 → `corpus_doc_ids` 退到 side-band → `reuse_signature` 从 plan 参数中移除（共 9+ 轮 `host_goal_eval_*` run 记录了每轮收缩）
4. **文档链式引用**：`docs/review/` 和 `docs/analysis/` 共 46 个文件，大部分相互引用形成树状依赖，新读者难以找到入口

---

## 3. Innovation Audit（创新点落地审计）

### 3.1 创新点清单与落地状态

| 创新点 | 状态 | 代码证据 | 测试证据 | 是否热路径 | 赛题影响 |
|---|---|---|---|---|---|
| **结构化通信协议** | ✅ 已完整落地 | `protocol/messages.py:1-1432`, `protocol/statebus.proto:1-222`, `orchestrator.py` 中 text/protocol 模式切换 | `test_protocol_messages.py` 6 个测例，`test_smoke.py` 大量双模式测试 | ✅ 热路径 | 25分通信效率的主要项目 |
| **StateRef 非文本状态传递** | ✅ 已完整落地 | `statepool/store.py:1-612` (mmap/SHM/CAS 三后端), `orchestrator.py` 中 prepare_step_input_refs() | `test_smoke.py` 中有专门的 StatePool/mmapped embedding/msgpack feature bundle 测试 | ✅ 热路径 | 20分状态传递创新的主要项目 |
| **FEATURE_BUNDLE** | ✅ 已部分实现 | `executor_runtime.py:388-661` build_feature_bundle() | `test_smoke.py` 中 ~12 个 feature bundle 行为测试 | ✅ 热路径 | 对非文本状态传递是有效加分 |
| **EXECUTOR_DECISION_PACKET** | ✅ 已落地 | `executor_runtime.py:2018-2113` 严格验证代码 | `test_smoke.py::test_missing_decision_packet_fails_executor` | ✅ 热路径（protocol mode） | 非文本状态传递的创新加分 |
| **共享记忆 (SQLite+FAISS)** | ✅ 已完整落地 | `memory/store.py:1-1313` commit_memory(), search(), replay_candidates() | `test_memory_store.py` 8 个测例 | ✅ 热路径 | 20分记忆复用效果的主要项目 |
| **记忆复用驱动的 step-skipping** | ✅ 已落地 | `orchestrator.py:1187-1996` resolve_skip_retrieve_execute() / resolve_skip_execute() | `test_smoke.py` 中 ~15 个 replay 相关测试 | ✅ 热路径 | 直接回答记忆复用效果 |
| **git 风格/增量 state 管理 (CAS)** | ✅ 已落地 | `statepool/store.py:392-612` ContentAddressedBlobStore with SHA-256 dedup | `test_state_channels_and_graph.py::test_content_addressed_blob_store` | ⚠️ 仅 replay restore 时激活 | 系统完整性加分 |
| **richer typed-state 体系** | ✅ 已部分实现 | 15+ StateContract 类型（DENSE_EVIDENCE, FEATURE_BUNDLE, CHANNEL_SNAPSHOT, TOOL_CANDIDATE_SET, REPLAY_ELIGIBILITY_BUNDLE, EXECUTOR_DECISION_PACKET, VALIDATION_GATE_PACKET, TOOL_ARTIFACT×5 variants 等） | `test_smoke.py` 中大量 state contract 测试 | ⚠️ 部分类型仅在 audit/support 路径 | 状态传递创新的丰富性 |
| **planner openness (yaml+llm)** | ✅ 已落地 | `agents/sample_agents.py:300-350` plan_task() 两条路径 | `test_smoke.py::test_planner_support_v3_end_to_end` | ✅ `plan_source=llm` 时为热路径 | 系统完整性中覆盖规划角色 |
| **open / LangGraph extension** | ⚠️ 有代码但不完整 | `runtime/langgraph_adapter.py:1-479` (真实 LangGraph 集成), `eval/open_runner.py:1-914` 外部对比运行时 | `test_state_channels_and_graph.py` 2 个 LangGraph 测例 | ⚠️ 仅在 opt-in 或 open extension 时走 | 实验验证的补充 |
| **pure text 定义分离** | ✅ 已实现 | `text_whole_lane` in contest_honest_headline_v1, `text_strict_pure_lane` in controlled | `test_smoke.py::test_whole_lane_text_guard_pass` | ✅ headline 热路径 | 实验验证的公平性关键 |
| **validate-first planner checks** | ✅ 已落地 | `executor_runtime.py` VALIDATION_GATE_PACKET 逻辑 | `test_smoke.py` 专门验证 | ✅ validate 步骤若存在则为热路径 | 系统完整性的创新加分 |
| **multi-process UDS executor** | ⚠️ 有代码但仅在特定模式 | `runtime/uds_transport.py:1-45`, `runtime/remote_executor.py:1-87` | `test_smoke.py::test_benchmark_uds_executor_transport` | ⚠️ 仅在 UDS mode 时走 | 加分项样机 |

### 3.2 仅停留在文档层的创新点（⚠️ 未落地或危险）

| 创新点 | 状态 | 文档声称 | 代码真相 |
|---|---|---|---|
| **LLM hidden state / KV cache 直传** | ❌ 未实现 | `current_feature_scope.md` 明确标注为"后续增强项" | 代码中不存在。当前只有 embedding + feature bundle + state ref 级别 | 
| **SCM_RIGHTS / FD passing 数据面** | ❌ 未实现 | `current_feature_scope.md` 明确标注为"延后项" | 代码中不存在 |
| **nsjail 正式安全沙箱** | ❌ 未实现 | `current_feature_scope.md` 明确标注为"延后项" | 当前只有 `LightweightSubprocessRunner`（subprocess + temp dir + env 清洗），**不是安全沙箱** |
| **eBPF / WASM / 容器沙箱** | ❌ 未实现 | `current_feature_scope.md` 标注为"加分项候选" | 代码中不存在 |
| **跨任务更强的 reusable dependency 合同** | ⚠️ 仅部分 | 文档计划中有 `required_prior_case_ids` 和 `required_prior_rejections` | `tasks/contest_family_spec.py` 定义了 dependency，但 `SampleTask` 中对应的 runtime enforcement 有限 |

### 3.3 关键诚实约束

`docs/constraints/current_feature_scope.md` 明确列出"当前不该假装已经做了的"，这些约束在全部代码和测试扫描中得到确认：
- LLM hidden state / KV cache：未实现
- nsjail 沙箱：未实现
- Docker/openEuler 终态复现：未实现
- eBPF：未实现
- 多进程全角色分布式 Runtime：未实现

---

## 4. Architecture Audit（架构审计）

### 4.1 当前架构评估

**架构是否清晰：基本清晰，但存在明显的石山化信号。**

三面模型（控制面/数据面/记忆面）概念清晰。4 Agent 职责明确：Planner(LLM) → Retriever(no LLM) → Executor(no LLM) → Summarizer(LLM)。data flow 文件（`docs/reports/architecture_and_data_flow.md`）描述准确。

**但以下信号表明石山化风险：**

1. **单文件巨型类：** `eval/runner.py` 6359行，`test_smoke.py` 5780行，`orchestrator.py` 2465行，`executor_runtime.py` 2190行，`agents/sample_agents.py` 2205行。这些是 monolith，不是 modular。

2. **alias 堆积：** `transfer_strategy` 有 8 个字符串值，`handoff_profile` 有 9 个字符串值，`benchmark_lane` 有多个字符串值。每层都通过字符串匹配进行 dispatch，而非类型系统。

3. **pack/surface 膨胀：** 13+1 个 v3 pack，每个有 `public_surface`、`evidence_tier`、`benchmark_version`、`pack_type` 等元数据标签。读法边界需要 20+ 句"不应读成"来定义。

4. **边界不清：**
   - `text_definition_audit_v3` 只审计 executor-boundary inline text，"不负责 formal headline"
   - `typed_state_authenticity_v3` "只保留 legacy compatibility surface"
   - `carrier_microbench_v3` "engineering audit only, 不读成正式 headline"
   - `external_text_baseline_audit_v3` "先做 audit-only，不并入 contest headline"
   - 这种"什么不是"的否定列表本身就是复杂性的信号

5. **概念重复包装：**
   - `DENSE_EVIDENCE` + `FEATURE_BUNDLE` + `RANKED_EVIDENCE_BUNDLE` + `REPLAY_ELIGIBILITY_BUNDLE` + `EXECUTOR_DECISION_PACKET` + `VALIDATION_GATE_PACKET` — 6 种不同的 typed state 都在回答"如何把信息从 retriever 传给 executor"，但各自只覆盖一个特殊场景
   - `CHANNEL_PATCH` + `CHANNEL_SNAPSHOT` — 通道抽象在实际热路径中几乎不用（`channels.py` 仅用于附加元数据）
   - 9 种 `transfer_strategy` + 9 种 `handoff_profile` — 每个策略都有自己独立的 text 解析器和 handoff builder

6. **report 为了修解释又叠一层：** 在 `eval/runner.py` 中有大量 audit/payload 函数（`_whole_lane_text_guard_payload()`, `_inline_text_boundary_guard_payload()`, `_reuse_artifact_payload()`, `_runtime_integrity_payload()` 等）专门用于在报告中额外写入解释性元数据，以补偿指标本身的语义不足。

### 4.2 复杂度来源分析

**根本来源：#1：为了控制变量而不得不制造的 surface 复杂性**
- 为了证明"结果来自 handoff object 而非 transfer strategy 的副产品"，需要多个 pack 逐个隔离变量
- 每个 pack 需要自己的 task definition YAML、handoff_profile、transfer_strategy、benchmark_lane 组合
- 这导致 pack 数量从可管理的 3-4 个膨胀到需手动管理的 13+1 个

**根本来源：#2：text 对比对象的诚实性问题**
- 项目花费了大量精力（从 D6 到 contest_honest_headline_v1）来建立"纯文本到底应该是什么样的"的定义
- `text_strict_pure_lane` → `text_whole_lane` 的迁移就涉及多个 guard 测试、boundary audit pack、hidden field leak detection 等
- 这不是系统核心能力的迭代，而是解释表面的迭代

**根本来源：#3：多轮 runtime contract 收缩的堆积**
- 从 2026-06-08 到 2026-06-09 连续 9+ 轮 contract cleanup run：每一步移除一个特定的查询过滤或预过滤条件
- 每一步都需要新的 run package 来证明"移除后 benchmark 仍然稳定"
- 累积导致 runs/ 目录拥有 15+ 个历史验证包，文档篇幅膨胀

### 4.3 石山化风险评分

| 维度 | 评分 (1-5) | 说明 |
|---|---|---|
| 单文件巨型类 | **5/5** 严重 | 3 个文件 >2000 行，2 个文件 >5000 行 |
| alias/枚举堆积 | **4/5** 高 | transfer_strategy, handoff_profile, benchmark_lane 都是 string enum |
| surface 膨胀 | **4/5** 高 | 13+1 pack 需手动管理，读法边界越来越长 |
| 边界不清 | **3/5** 中 | 用否定列表定义什么是"无"，正在累积 |
| 概念重复 | **3/5** 中 | 6 种 typed state 桥接 retriever → executor |
| 报表层修补 | **4/5** 高 | 大量 guard/audit/payload 函数仅为报告解释而存在 |
| 文档膨胀 | **4/5** 高 | 46 个 review/analysis 文件，新手入口成本高 |
| 总石山化风险 | **3.9/5** | 当前尚可运行，但继续在现有结构上修补而非收口，趋势会恶化 |

---

## 5. Benchmark Audit（Benchmark 审计）

### 5.1 当前 Benchmark 是否过度复杂？

**是，且复杂性集中在解释表面，而非测量核心。**

13+1 个 pack 的读法边界（见 Section 1.3）建立了一套复杂的"什么能读、什么不能读"的嵌套规则。大部分 pack 是 audit-only 或 formal-secondary，只有 `contest_honest_headline_v1` 是唯一的 contest-facing formal headline — 而它又因为 repeat=3（需要 repeat=10）而不能给出正式结论。

**对比对象的纯度问题：**
1. `contest_honest_headline_v1` 对比 `text_whole_lane` vs `state_packet_minimal` — **这是当前最纯净的对比**。single_variable=yes, variable_axes=mode。但 text executor 仍有 `build_feature_bundle()` 结构化恢复路径（F-B1，见 honest_full_audit）。
2. `contest_dual_mode_controlled_v3` 对比 `text_strict_pure_lane` vs `state_packet_minimal` — **不纯净**。text side 有 structured field leak（hidden_field_leak_rate=1.0），且 object parity gate 失败。
3. `typed_state_mechanism_v3` 对比 `natural_handoff_text` vs `state_packet_minimal` — 单变量（handoff format），但 natural_handoff_text 使用 StatePool 句柄而 state_packet_minimal 使用 typed bytes，导致 protocol 侧 bytes **更多**（+3%），与 headline 结论矛盾。这说明机制包回答的不是 carrier 效率问题。

### 5.2 为什么 Text vs Protocol 结果总是接近？

五个因素，按重要性排序：

**1. 任务太薄（F-C1，核心原因）：** 当前 contest 任务是单跳 agent 通信（retrieve → execute → summarize）。protocol 在一次 handoff 中节省约 2000 bytes 控制面开销，但 StatePool 的 mmap 开销（~50-100ms）把节省吃掉了。只有多跳任务才能让 protocol 的 communication savings 复合。

**2. 正确性天花板一致（F-D2）：** 双方 admissible_match 均为 1.00，exact_match 均为 0.70。正确性不是差异指标。在单 route 任务（无 route 竞争）中，protocol 的精确 route/tool 选择优势无用武之地。

**3. Text executor 有结构化恢复路径（F-B1）：** text_whole_lane executor 通过 `build_feature_bundle()` 进行 NL 解析 + 词汇匹配，不是盲目的 NL-only 消费者。如果声明"text executor 没有结构化恢复路径" → 不成立。应诚实记录而非修改代码（per honest_full_audit 建议）。

**4. LLM token 对称（F-D3）：** text 415.0 vs protocol 415.9 tokens（delta +0.2%）。两种模式下 planner 和 summarizer 的 LLM 调用本质上相同。protocol **不会节省 LLM token**，这是事实。

**5. Protocol 有线格式开销：** protocol mode 需要序列化/反序列化 typed packets（StateRef lite 约 50-80 bytes/ref），text mode 无此开销。这在 thin tasks 中占可感知比例。

### 5.3 是否存在 Metric 语义错误？

**是，至少两个已确认的 P0 报告 bug：**

**F-A1：`planner_one_shot_valid_rate: 0.00` 是聚合公式 bug。** Row-level data 显示全部 11 个 task rows 的 `planner_one_shot_valid=1.0` 且 `repair_attempt_count=0`。聚合层计算出 0.00 是错误的。报告 header 声称 `Planner one-shot valid rate: 1.00` 而 body table 写 `0.00` — 自相矛盾。

**F-A2：memory fairness pack `correctness_label` 全部是 `mismatch`。** 40 个 memory fairness 行没有 case contract（`primary_expected_route`/`primary_expected_tool` 为空），因此不应标 `mismatch`，应标 `not_evaluated`。

### 5.4 哪些 Pack 仍然值得保留？

| Pack | 推荐 | 理由 |
|---|---|---|
| `contest_honest_headline_v1` | ✅ 保留为唯一 headline | 最干净的 single-variable 对比。唯一 withheld 原因只是 repeat 不足 |
| `typed_state_mechanism_v3` | ✅ 保留为机制证明 | state_authenticity_gate 唯一通过的 pack。回答"typed state 是否真实生产/传递/消费" |
| `memory_policy_controlled_v3` | ✅ 保留为 replay 归因 | 单变量 memory policy 对比 |
| `typed_state_consumer_sensitivity_v3` | ✅ 保留 | destructive controls 干净验证，negative controls 全部正确 |
| `planner_support_v3` | ⚠️ 保留但需修复报告 | yaml vs llm 比较有价值，但 bug F-A1 必须先修复 |
| `memory_dual_mode_fairness_v3` | ⚠️ 保留为内部 parity gate | object parity gate 有用，但不承担 replay proof |
| `memory_reuse_v3` | ⚠️ 保留为 protocol-only replay proof | 独立回答 replay 效果 |
| `contest_dual_mode_controlled_v3` | 🟡 降级为内部 dev regression gate | 已在 README 和所有报告中标为降级。不再承担 contest-facing headline |
| `text_definition_audit_v3` | 🟡 灵活保留 | 仅审计 executor 边界 inline text |
| `external_text_baseline_audit_v3` | 🟡 灵活保留 | audit-only 外部基线 |
| `typed_state_authenticity_v3` | 🟡 可考虑移除 | legacy compatibility surface，机制问题已被 typed_state_mechanism_v3 替代 |
| `typed_state_full_rich_audit_v3` | 🟡 可考虑移除 | audit-only，不进 formal headline |
| `carrier_microbench_v3` | 🟡 可考虑移除 | engineering audit only |

---

## 6. Main Diagnosis（主诊断）

### 6.1 赛题要什么？

赛题要求：
1. 结构化通信替代自然语言交互（通信效率 25分）
2. 非文本中间状态传递（状态传递创新 20分）
3. 共享记忆存储/检索/复用（记忆复用效果 20分）
4. 至少 3 个 Agent 覆盖规划/检索/执行/总结（系统完整性 20分）
5. 可复现的 text vs protocol 对比实验（实验验证 15分）

### 6.2 当前真正做到了什么？

| 赛题要求 | 完成度 | 证据 |
|---|---|---|
| 4 Agent 协同运行（>3个角色） | ✅ 高 | Planner(LLM) + Retriever(rule) + Executor(rule) + Summarizer(LLM)，全部测试通过 |
| 结构化通信机制 | ✅ 高 | Protobuf + capability/schema hardening + 17 种 wire message types |
| 双模式 text vs protocol | ✅ 高 | contest_honest_headline_v1 对比 `text_whole_lane` vs `state_packet_minimal`，single_variable=yes |
| 非文本状态传递 | ✅ 中高 | StateRef + mmap/SHM/CAS + FEATURE_BUNDLE + EXECUTOR_DECISION_PACKET 已落地。但不是 LLM hidden state / KV cache 级。严格符合赛题"embedding、语义向量或其他中间表示"的描述 |
| 共享记忆 | ✅ 高 | SQLite + FAISS 落地，exact_replay 下 reuse_gain=0.67，task 时间-50% |
| 2 组连续任务 | ✅ 中 | 18-task chain（`host_goal_eval` 系列）和 5-family 4-bucket contest 任务。但 contest reusable 是 same-family 重写而非真正跨任务依赖 |
| 10 轮连续任务稳定性 | ⚠️ | deterministic repeat-10 成立。API repeat-10 仅在历史上部分 run 中成立（`host_goal_eval_20260608_093111`），当前 headline repeat-3 成立但未正式通过 repeat=10 gate |
| 性能指标采集 | ✅ 高 | 70+ 个 metric 字段，50+ 个 benchmark CSV 字段，涵盖消息计数/token/bytes/时延/记忆命中率等全部要求 |

### 6.3 当前没有做到什么？

1. **Protocol 不降低端到端 latency**（甚至略高 +3%）。通信节省被 StatePool 开销抵消。需要多跳任务才能证明优势。
2. **Protocol 不降低 LLM token 消耗**（text 415 vs protocol 416, delta=0.2%）。
3. **Protocol 不提高 correctness**（双方相等：admissible=1.00, exact=0.70）。
4. **缺乏 repeat=10 的 formal stability gate**。当前 headline 停在 repeat=3。
5. **contest reusable 任务不是真正的跨任务依赖**。仍是 same-family follow-up 而非 consume-prior-conclusion。
6. **没有真实的外部 pure-text multi-agent baseline 对比**。`external_text_baseline_audit_v3` 只 audit-only。`eval/open_runner.py` 使用 task 的 `primary_expected_route`（oracle 式），不是真实检索。
7. **CodeAct 没有进入主路径**。`runtime/codeact_runner.py` 标为 experimental。
8. **nsjail / Docker / openEuler / eBPF 全部未实现**。文档中诚实标注为"后续"。

### 6.4 当前最应停止什么？

1. **停止在已有 pack 上继续修补 benchmark 对象定义。** 13+1 个 pack 已经过多。不要新增 audit surface、不要拆分更多的 sub-surface、不要再加新的 handoff_profile variant。
2. **停止在旧有 `contest_dual_mode_controlled_v3` 上修"fairness"。** 它已经是内部 dev regression gate。资源应投入 `contest_honest_headline_v1`。
3. **停止在没有 repeat=10 证据时继续往外扩散 surface。** 先把 headline pack 的 repeat=10 跑通。
4. **停止增加新的 report guard/audit/payload 函数仅为了解释已有指标。** F-A1 和 F-A2 是两个已确认的报告 bug，应先修 bug 再谈新功能。
5. **不急于启动 Docker/openEuler/nsjail 或 CodeAct 主路径**。这些在当前文档中都已正确标注为"后续阶段"。

### 6.5 当前最应保留的主线

1. **`contest_honest_headline_v1` 是唯一 contest-facing headline。** 保持其 text_whole_lane vs state_packet_minimal 的定义不变。
2. **`typed_state_mechanism_v3` 是 typed-state 机制证明。** 这是唯一通过 state_authenticity_gate 的 pack。
3. **memory replay（exact_replay reuse_gain=0.67, task time -50%）是真实的。** 保留其为记忆面的核心证据。
4. **三面模型（控制面/数据面/记忆面）是清晰的架构概念。** 不要推翻。

---

## 7. 证据索引

### 文档依据
- 赛题需求：`docs/reference/题目.md:1-41`
- 环境约束：`docs/constraints/current_host_and_migration.md:1-219`
- 功能边界：`docs/constraints/current_feature_scope.md:1-481`
- 最新审计：`docs/analysis/honest_full_audit_20260617.md`
- 最新分析：`docs/analysis/mainline_repeat3_analysis_20260617.md`
- P0 问题清单：`docs/review/statebus_contest_remaining_closure_plan_20260615.md`
- 重构计划（窄化版）：`docs/review/statebus_contest_first_refactor_execution_plan_20260617.md`

### 代码路径
- Agent 实现：`agents/sample_agents.py:300-1487`
- 编排引擎：`runtime/orchestrator.py:837-2465`
- 工具执行：`runtime/executor_runtime.py:907-1141`
- 特征提取：`runtime/executor_runtime.py:388-661`
- LLM 配置：`runtime/llm.py:37-799`
- 协议消息：`protocol/messages.py:1-1432`
- 状态存储：`statepool/store.py:85-612`
- 记忆存储：`memory/store.py:202-900`
- Benchmark：`eval/runner.py:3618-6359`
- 任务定义：`tasks/sample_tasks.py:282-1067`
- 语料检索：`tasks/local_corpus.py:94-191`

### 测试路径
- 主力集成测试：`tests/test_smoke.py` (~157 测例)
- LLM 运行时：`tests/test_llm_runtime.py` (20 测例)
- 通道与图：`tests/test_state_channels_and_graph.py` (8 测例)
- 记忆存储：`tests/test_memory_store.py` (8 测例)
- 协议消息：`tests/test_protocol_messages.py` (6 测例)

### Run 结果路径
- 当前主 run：`/home/qcrs/statebus/runs/statebus_mainline_repeat3_suite_20260617_141158/`
- 关键 benchmark reports：
  - `benchmarks/contest_honest_headline_v1/benchmark_report.md` — contest headline
  - `benchmarks/contest_dual_mode_controlled_v3/benchmark_report.md` — internal controlled
  - `benchmarks/memory_dual_mode_fairness_v3/benchmark_report.md` — memory fairness
  - `benchmarks/typed_state_mechanism_v3/benchmark_report.md` — state mechanism
  - `benchmarks/typed_state_consumer_sensitivity_v3/benchmark_report.md` — destructive controls
  - `benchmarks/planner_support_v3/benchmark_report.md` — planner comparison
  - `benchmarks/text_definition_audit_v3/benchmark_report.md` — text boundary audit

---

*全量扫描完成时间：2026-06-17。扫描覆盖：46 个 review/analysis 文档、21 个脚本文件、5 个测试文件（~157 测例）、25+ 个核心代码文件（合计 ~30,000 行）、14 个 benchmark pack 报告。*
