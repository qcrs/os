# feat/contest-hardening 分支完整对照

**分支**: `feat/contest-hardening`（从 `main` @ `2e5085e` 分叉）
**改动量**: 10个文件，+2,845行，-211行
**用途**: `git diff main...feat/contest-hardening` 可查看相对main的完整变更

---

## 一、参考文档索引

本分支的设计依据和理论基础来自以下文档：

| 文档 | 路径 | 作用 |
|------|------|------|
| 赛题要求 | `docs/reference/题目.md` | 唯一权威需求源 |
| LangGraph审计 | `docs/reference/PROJECT_STATUS_REPORT.md` | 论证为何不引入LangGraph |
| LangGraph demo | `docs/reference/multi_agent_demo_report.md` | 证明基于框架可行但不提供benchmark |
| 设计稿(未实现) | `docs/reference/multi-agent-system-design.md` | 理想化设计参考 |
| 实施计划 | `docs/planning/implementation_plan.md` | Phase 0-6规划 |
| 问题地图 | `docs/progress/host_mainline_problem_map_20260609.md` | P0/P1/P2/STOP分类 |
| 赛题审计 | `docs/progress/contest_requirement_host_audit_20260607.md` | 逐项核对 |
| 深度审计 | `docs/progress/host_mainline_deep_audit_20260608.md` | 代码层问题发现 |
| **最终方案** | `docs/analysis/final_adjusted_plan.md` | 沟通后的优先级+可实现性评估 |
| **实施手册** | `docs/analysis/implementation_manual.md` | 逐文件逐函数的实现规格 |
| Benchmark分析 | `docs/analysis/benchmark_task_and_result_analysis.md` | 29-task实验结果逐层分析 |
| 第三方分析 | `docs/analysis/third_party_analysis_and_borrowable_patterns.md` | 9个仓库可借鉴模式 |
| 代码审计+方案 | `docs/analysis/code_audit_competition_check_and_solution_roadmap.md` | 全代码审核+赛题核对 |
| CASF设计 | `docs/analysis/novel_design_content_addressed_state_fabric.md` | 内容寻址架构 |
| 变更说明 | `docs/analysis/CHANGES.md` | 本分支每次变更的说明 |

---

## 二、逐文件变更清单

### 2.1 `statepool/store.py` (+112行) — CASF内容寻址存储

**新增类**: `ContentAddressedBlobStore`
- Git-style blob路径: `blobs/<hash[0:2]>/<hash[2:]>`
- `put()`: SHA-256去重 + refcount
- `get_bytes_by_hash()`, `has_blob()`, `blob_refcount()`

**StatePool facade 新增方法**:
- `put_cas()`, `put_or_dedup_bytes()`, `get_by_hash()`, `has_blob()`, `cas_refcount()`

**设计来源**: `novel_design_content_addressed_state_fabric.md` §3

---

### 2.2 `protocol/messages.py` (+151行)

**CASF数据结构**:
- `StateRef.blob_hash`属性（checksum别名）
- `StateRef.is_cas`属性（`storage == "CAS_BLOB"`判定）
- `StepTree` dataclass — 一个step的输入输出blob快照，含`compute_tree_hash()`
- `TaskCommit` dataclass — 一个task的执行快照，含`seal()`和`compute_commit_hash()`
- `ExecutionDAG` dataclass — 完整执行轨迹，含`verify_integrity()`和`find_similar_subtree()`

**其他**:
- `DeltaPlanStep` dataclass — 增量协议帧（预留，orchestrator未接）
- `MemoryQuery.session_id`字段 — 双层记忆的前置条件

**设计来源**: CASF设计文档 + LangGraph Channel模型

---

### 2.3 `memory/store.py` (+62行)

**多信号检索融合**（在`_search_semantic`内部）:
- BM25 keyword overlap (`_compute_keyword_overlap`)
- Tag overlap boosting
- Recency decay (`exp(-λ × age)`)
- Memory tier boost（同session ×1.5）
- 可配置权重（环境变量`:STATEBUS_MEM_*`）

**新增辅助函数**:
- `_compute_keyword_overlap()`, `_row_session_id()`, `_env_optional_float()`

**设计来源**: mem0多信号融合 + agent-memory-server双层记忆

---

### 2.4 `runtime/executor_runtime.py` (+484行)

**FEATURE_BUNDLE增加`_channel_schema`**:
- 26个字段标注为`last_value`/`topic_replace`/`topic_accumulate`/`ephemeral`
- 不改变v1 schema（元数据字段，旧consumer忽略）

**设计来源**: LangGraph Channel模型（LastValue/Topic/EphemeralValue）

---

### 2.5 `runtime/contracts.py` (+571行)

**新增类**: `InvariantChecker`
- `check_plan()` — 9项静态不变量（task_id/goal/steps/unique_ids/owner/action/deps/dag/cycle）
- `check_state_refs()` — source_agent_id + created_at
- `check_results()` — step-result对应关系 + error_on_failure

**设计来源**: AgentRx invariant checking

---

### 2.6 `runtime/codeact_runner.py` (新文件, +98行)

**新增类**: `CodeActRunner`
- 安全校验：禁止os/subprocess/socket/ctypes等import
- subprocess + timeout(10s) + PYTHONPATH清理
- 返回`CodeActResult`(success/stdout/stderr/exit_code/time/hash)

---

### 2.7 `agents/sample_agents.py` (+290行)

**PlannerAgent.execute_step真实实现**:
- 不再`raise NotImplementedError`
- 当`task.plan_source == "llm"`时调LLM生成Plan
- 新增`_build_open_planner_prompt()`函数
- `plan_task()`保持不变（受控路径）

---

### 2.8 `tasks/sample_tasks.py` (+71行)

**SampleTask新增字段**:
- `plan_source: str = "yaml"` — 控制plan来源

**_load_sample_task加载plan_source**

---

### 2.9 `tasks/sample_benchmark.yaml` (+274行)

**恢复**: 从HEAD恢复`formal_controlled_pack`(475行/26 tasks)

**新增**:
- 4个communication lane task (latency×2 + session×2) → 扩到6 tasks
- 3个lexical_override task (cache/latency/session各1)
- 3个open-plan task (`plan_source: llm`)

**删除**:
- 6个session_chain task (sample-session-001至006) → internal_regression从18减到12

**最终**: 36 tasks, 6 groups

---

### 2.10 `eval/runner.py` (+433行)

**报告口径调整**:
- Aggregate前增加免责声明（当text/protocol task数不对称时）
- Protocol Compliance section（InvariantChecker结果占位）

---

## 三、与赛题评分的对应

| 评分维度(分值) | 本分支改动 | 预期提升 |
|-------------|-----------|---------|
| 通信效率(25) | A4报告口径消除假倒挂 | +2 |
| 状态传递创新(20) | B3 ChannelKind标注 + CASF内容寻址 | +3 |
| 记忆复用效果(20) | B2多信号检索融合 + 双层记忆 | +3 |
| 系统完整性(20) | C1 CodeAct + C3 InvariantChecker + CASF DAG | +4 |
| 实验验证(15) | B1 lane配额优化 + C2 route多样性 | +2 |
| **合计(100)** | | **~72 → ~86** |
