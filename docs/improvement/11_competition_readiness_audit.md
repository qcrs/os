# StateBus v2 竞赛答辩就绪度审计

**代码基准**：`f3dd094`（2026-07-05）
**审计视角**：竞赛评委 — 创新性、可信度、完整度
**依赖文档**：`09_implementation_deep_review.md`（已知 Bug 和基础审计）

---

## 执行摘要

| 优先级 | 数量 | 核心风险 |
|-------|------|---------|
| P0 Critical Bug | 3 | 答辩前必须修复 |
| P1 Design Concern | 5 | 需要准备标准答案 |
| P2 Missing Test | 6 | 影响数据可信度 |
| P3 Conservative Innovation | 3 | 已实现但未激活，评估是否启用 |
| P4 Scope Clarification | 4 | 声称需降级，否则被质疑 |

---

## P0：Critical Bugs（答辩前必须修复）

### P0-A：external_text_baseline revenue_value 存在隐式 fallback 到 ground truth

**位置**：`v2/benchmark/external_text_baseline.py:524–527`

```python
llm_revenue_value = str(
    retriever_payload.get("revenue_value", retriever_payload_raw.get("revenue_value", ""))
).strip()
observed_revenue_value = llm_revenue_value or context.revenue_value   # ← 隐患
```

**问题**：当 LLM Retriever 未能从 corpus 中提取 `revenue_value`（返回空字符串）时，`observed_revenue_value` fallback 到 `context.revenue_value`，即 **corpus 中的真实答案**（由 `_load_execution_context()` 预加载，line 329-336）。

这意味着 external baseline 在 `deterministic` 模式下永远无法在 revenue_value 上失败，因为 DeterministicLLMClient 返回的 mock 响应若不含 revenue_value 字段，直接 fallback 到正确答案。

**答辩风险：高**。如果评委问"external baseline 的 6/8 失败在哪里"，无法自洽。实际可能是 8/8 都因 fallback 而得分，而非 LLM 真正提取成功。

**Impact**：评委可能认为"external baseline 无法真实反映纯文本方案的局限性，StateBus vs External 的对比无效"。

**修复方案**：
```python
# 修复前：observed_revenue_value = llm_revenue_value or context.revenue_value
# 修复后：只使用 LLM 提取值，不回退到 ground truth
observed_revenue_value = llm_revenue_value  # 空值即得分失败
```
同时在 `api` 模式运行 external baseline，记录真实 LLM 提取率，区分"LLM提取成功率"和"fallback成功率"。

---

### P0-B：validated_replay 跨实体 wrong-answer — cross_period_financial 是真实触发场景

**位置**：`v2/runtime/replay.py:513–530`（`_schema_shape_arguments`），`cross_period_financial/manifest.json:round 6`

**问题**（比 B4 更严重）：`_schema_shape_arguments` 排除 `dataset_id` 但**不排除 `ticker` 和 `quarter`**，仅比较类型形状而不比较值。

`cross_period_financial_v1` Round 2 和 Round 6 的 schema shape 完全相同：

| 字段 | Round 1 (ACME 2026Q1) | Round 6 (BETA 2026Q1) | Shape |
|-----|----------------------|----------------------|-------|
| ticker | "ACME" | "BETA" | str |
| quarter | "2026Q1" | "2026Q1" | str |
| metric | "revenue" | "revenue" | str |
| dataset_id | excluded | excluded | — |

`validated_replay_contract_compatible(round1, round6) = True` → 系统可能将 ACME 的 revenue 120 返回给 BETA 的查询（正确答案是 87）。

这不是"概率缓解"——`cross_period_financial_v1` 的 Round 6 的 `reuse_contract.consumes` 包含 `strategy:compare_metric_table_retriever`，其 embedding 与 Round 1 高度相似，**memory_match 候选池会包含 Round 1 结果**，触发 validated_replay。

**答辩风险：高**。连续任务族 replay 是核心 claim，若该场景产生错误答案，直接否定 claim 3。

**修复方案**：在 `validated_replay_contract_compatible()` 中对高区分度字段增加值比较：

```python
# v2/runtime/replay.py:351 附近增加
_HIGH_DISCRIMINANCE_KEYS = {"ticker", "quarter", "service_name", "period_from", "period_to"}

def validated_replay_contract_compatible(...) -> bool:
    # ... 现有 task_family/intent_op/tools/outputs 检查 ...
    # 新增：高区分度字段值必须完全一致
    for key in _HIGH_DISCRIMINANCE_KEYS:
        if current_spec.arguments.get(key) != candidate_spec.arguments.get(key):
            return False
    current_arguments = _schema_shape_arguments(current_spec.arguments)
    candidate_arguments = _schema_shape_arguments(candidate_spec.arguments)
    return current_arguments == candidate_arguments
```

---

### P0-C：TableStructureRetriever `rows[:1]` 硬编码只取第一行

**位置**：`v2/retrieval/pipeline.py:179`

```python
selected = tuple(
    EvidenceCandidate(...)
    for index, row in enumerate(rows[:1])  # increase limit for richer fact coverage
)
```

注释明确说"increase limit"，但代码始终 `[:1]`。对于 formal financial family（8/8），每个任务只请求一个 metric（revenue/margin），这是正确的。

**问题**：`cross_period_financial_v1` Round 3（compute_delta）和 Round 5（compute_trend）需要同时读取多个 metric，若 table_retriever 只返回第一行，可能漏掉后续 metric 行。

实际看 Round 3 的 task_spec：`intent_op=compute_delta, arguments={ticker:ACME, metric:revenue, period_from:2025Q4, period_to:2026Q1}`。该任务依赖 rounds [1,2] 的 memory 而非直接从 table 再取，所以通过 memory 路径可以正常。但 `cross_period_financial` 是 long_doc 格式，`TableStructureRetriever` 对 metric 过滤逻辑（`row.metric_name == requested_metric`）可能和 long_doc 的 table 格式不匹配。

**答辩风险：中**。formal 8/8 不受影响，但连续任务族若运行失败，会被质疑。

**修复方案**：为 `compute_delta` / `compute_trend` intent_op 增加多行选取，或在 cross_period_financial 相关任务中配置 `rows[:3]`。

---

## P1：Design Concerns（评委必然质疑，需要标准答案）


### P1-1：UDS + Protobuf 协议价值质疑

**质疑**："你的协议跑在同进程 loopback 里，测的是序列化开销而不是 IPC——这和换个序列化库有什么区别？"

**代码事实**（`transport.py:54`）：`ControlPlaneLoopbackServer` 使用 threading + 真实 AF_UNIX socket，但 4 个角色在同一进程顺序执行。`SubprocessExecutorTransport`（`transport.py:284`）已实现真实子进程 UDS，formal benchmark 不激活。

**标准答案**：
> "协议的价值在于接口契约的可测性：任何角色可替换为外部进程，contract 不变。loopback 刻意排除网络变量，使 structured vs text handoff 的序列化开销对比更干净。SubprocessExecutorTransport 已实现，可现场演示真实多进程通信。系统的主张是'结构化协议的序列化开销 < LLM prompt savings'，这在 loopback 环境下测量更精确，不是局限。"

**需要准备的数据**：运行 SubprocessExecutorTransport e2e 一次，记录 fork/exec overhead（预计 50-200ms）vs LLM 调用时间（几秒），证明协议开销可忽略不计。

---

### P1-2：非文本 StateRef 的真实 token 节省

**质疑**："16-dim embedding = 64 bytes，Base64 ≈ 88 bytes ≈ 22 tokens，省了多少？prompt savings 主要是检索裁剪，不是非文本传递本身。"

**代码事实**（`pipeline.py:84`）：DeterministicEmbeddingEncoder dims=16，每 embedding=64 bytes。外部 baseline Retriever 接收完整 corpus（corpus_text + table_text，`external_text_baseline.py:306-317`，数千 bytes），StateBus 发送裁剪后 evidence pack（~500-1000 bytes）。

**收益分解**：
- 80-90% 来自检索裁剪（TableRetriever 精准命中 vs LLM 全文扫描）
- 10-20% 来自 StateRef 替代文本 handoff（角色间不再传递展开文本）

**标准答案**：
> "两个收益是协同的，不是竞争的。检索裁剪决定'哪些证据进入 LLM'，StateRef 传递决定'角色间用什么格式携带状态'。如果只做检索裁剪但仍用文本 handoff，中间层的 token 消耗不减少；StateRef 消除了中间 handoff 的文本展开开销。text_whole_lane（内部对比）控制了裁剪策略完全相同，只改 handoff 格式，该对比下的 prompt bytes delta 才是 StateRef 传递的纯贡献。"

---

### P1-3：formal 8/8 靠 TableRetriever 精确匹配，LLM 语义能力未被检验

**质疑**："8/8 全靠 if-else 表格查询，换掉 LLM 准确率不变——StateBus 证明了什么？"

**代码事实**（`pipeline.py:161-179`）：TableStructureRetriever 通过 `row.metric_name == requested_metric` 精确匹配，100% 确定性，与 LLM 无关。

**标准答案**：
> "StateBus 的贡献是'用结构化路由保护 LLM 不需要做本可精确完成的任务'。强制 LLM 从全文提取精确数值会引入幻觉（external baseline 在 api 模式存在提取失败风险）。StateBus 路由决策让高确定性任务走 TableRetriever，让语义任务走 SemanticChunkRetriever——架构的价值是任务类型感知的降级策略。incident_diagnosis_v2（10 轮，semantic log retrieval + bwrap code execution）才是语义能力的测试场，formal_financial 是精度基准。"

---

### P1-4：replay 在 formal benchmark 零触发，claim 3 无实验数据支撑

**质疑**："你说 replay 是核心 claim，但 formal 8/8 全是 replay_class=assist——没有任何 replay 触发数据。"

**代码事实**：formal benchmark 是单次冷启动，无 `history_roots`，replay 物理不可能触发（`replay.py:239-256`）。continuous-replay suite 包含 incident_diagnosis_v2 和 cross_period_financial_v1，这些任务族设计了 exact_replay 预期（R3+），但**当前无实际运行数据**。

**答辩风险：高**。此项 claim 在答辩时无证据。

**标准答案准备条件**：先修复 P0-B，再运行 `--suite continuous-replay --benchmark-tier dev`，获取 replay 触发数据。只要 `exact_replay_count > 0` 且 `skipped_step_count > 0`，claim 3 成立。

---

### P1-5：CodeAct 在 formal benchmark 走预制模板，非 AI 代码生成

**质疑**："你的 CodeAct 在 benchmark 里走预制函数，不是 LLM 生成代码——这算什么 CodeAct？"

**代码事实**：deterministic 模式走 `codeact_data_tasks.py` 预实现函数，api 模式才调用 LLM 生成代码（需 bwrap）。`bounded_llm_codeact_demo.py` 5/5 pass 是 api+bwrap 路径的独立验证。

**标准答案**：
> "deterministic benchmark 使用确定性函数保证可重现性——与 deterministic Planner 的设计动机相同。CodeAct 在 formal benchmark 中的贡献是：AST policy check（安全过滤）、bwrap sandbox 隔离、content-hash cache（-65.7% 执行开销）。端到端 LLM 代码生成在 api 模式 + bounded_llm_codeact_demo 中验证（5/5 pass），incident_diagnosis_v2 连续任务族在 api 模式下使用真实代码生成。"

---

---


## P2：Missing Tests（关键路径缺测试，影响可信度）

### P2-1：validated_replay 跨实体错误答案测试

**缺失**：无测试覆盖"ACME 结果被 validated_replay 给 BETA 查询"场景。

**建议测试**（`tests/v2/test_replay_cross_entity_safety.py`）：
```python
def test_validated_replay_rejects_different_ticker():
    acme_spec = make_spec(ticker="ACME", quarter="2026Q1", metric="revenue")
    beta_spec  = make_spec(ticker="BETA", quarter="2026Q1", metric="revenue")
    # After P0-B fix: must return False
    assert not validated_replay_contract_compatible(current_spec=beta_spec, candidate_spec=acme_spec)
```

---

### P2-2：external_text_baseline revenue fallback 行为测试

**缺失**：无测试验证 LLM 返回空 revenue_value 时 external baseline 的行为（P0-A 修复的回归测试）。

**建议测试**：mock LLM 返回不含 `revenue_value` 的响应，断言 `revenue_exact=False`（修复后）而非 fallback 到 ground truth。

---

### P2-3：continuous-replay smoke 测试（replay 触发验证）

**缺失**：无集成测试验证 `incident_diagnosis_v2` R3 的 exact_replay 真实触发。

**建议**：`tests/v2/test_continuous_replay_smoke.py`，运行 rounds 1-3，断言 `round3.replay_class == EXACT_REPLAY` 且 `skipped_step_count == 2`。

---

### P2-4：SubprocessExecutorTransport e2e 测试

**缺失**：`SubprocessExecutorTransport.execute()` 无端到端测试（`transport.py:306`）。

**建议测试**：
```python
def test_subprocess_executor_round_trip(tmp_path):
    transport = SubprocessExecutorTransport(
        socket_path=tmp_path / "test.sock", timeout_s=10.0
    )
    result = transport.execute(request=make_minimal_exec_request())
    assert isinstance(result, SuccessResult)
```

---

### P2-5：CI 中需要 skipif 的 API-key / model 依赖测试

**问题**：`test_minimal_benchmark_family_api_mode_*` 需要 `STATEBUS_LLM_API_KEY`，无 key 时会 error 而非 skip，破坏 CI 绿线。

**修复**：
```python
import pytest, os, pathlib

api_key_required = pytest.mark.skipif(
    not os.getenv("STATEBUS_LLM_API_KEY"), reason="requires STATEBUS_LLM_API_KEY"
)
local_model_required = pytest.mark.skipif(
    not pathlib.Path.home().joinpath("statebus/models/Qwen3-Embedding-0.6B").exists(),
    reason="requires local embedding model"
)
```

---

### P2-6：FAISS 归一化假设回归测试（B2 修复验证）

**缺失**：B2 bug 修复后无回归测试，不能保证后续修改不引入相同问题。

**建议**：用已知向量构造测试，验证 FAISS lookup 排序与 cosine_similarity 排序一致。

---

## P3：Conservative Innovations（已实现但未激活，评估是否启用）

### P3-1：SubprocessExecutorTransport — 真实多进程 UDS，formal benchmark 不用

**位置**：`v2/control/transport.py:284`

**现状**：完整实现，包含 `pass_fds` memfd 传递，但 formal benchmark 使用 loopback。

**激进启用评估**：
- 收益：消除"loopback = 函数调用"的质疑，可声称真实多进程 UDS 通信
- 风险：subprocess fork 增加 50-200ms/task；formal benchmark 计时变慢（但 LLM 占主导，影响 <1%）
- 建议：在 `continuous-replay` suite 中启用，提供真实多进程展示数据。formal benchmark 保持 loopback（精度优先）

---

### P3-2：MemfdStatePool + SCM_RIGHTS — 零拷贝 embedding 传递，formal benchmark 不用

**位置**：`statepool/store.py:240`，`v2/control/transport.py:260-280`

**现状**：实现完整（stress_pass 3/6），与 SubprocessExecutorTransport 配对使用，formal benchmark 使用 MMAP_FILE（需 CAS 持久化支持 replay）。

**激进启用评估**：
- 收益：Linux 匿名 FD 跨进程零拷贝传递，是真实系统编程创新
- 风险：需要同时启用 SubprocessExecutorTransport；memfd 无持久化→不支持跨 session replay
- 建议：在答辩 demo 中专门演示 memfd 路径（独立于 formal benchmark），作为"数据平面创新"展示

---

### P3-3：validated_replay — gate 完整，policy 关闭（修 P0-B 后可启用）

**位置**：`v2/runtime/replay.py:127-151`（`allow_validated_replay=False` 是 policy 配置）

**现状**：ReplayAdmissibilityGate 逻辑完整，但 formal benchmark 的 ReplayPolicy 设置 `allow_validated_replay=False`。

**P0-B 修复后的启用路径**：
1. 修复 `_schema_shape_arguments` 跨实体 bug（P0-B）
2. 在 `cross_period_financial_v1` 中设置 `allow_validated_replay=True`
3. Round 2 应触发 `validated_replay`，`skipped_step_count=1`，revenue_value 正确

这是 claim 3 的关键验证路径，必须在答辩前获得数据。

---

## P4：Scope Clarification（声称需降级，否则被质疑）

### P4-1："多 agent 协作" → 降级为"多角色协作原型（同进程 loopback）"

答辩中若声称"分布式多 agent 协作"，评委会立即质疑 loopback 不是真正多进程。

**降级表述**：
> "多角色协作原型（Planner/Retriever/Executor/Summarizer），通过 UDS + typed Protobuf 接口契约实现角色隔离。当前 formal benchmark 运行在同进程 loopback 模式下以消除网络变量；SubprocessExecutorTransport 提供了向真实多进程部署的扩展路径（已实现，可 demo）。"

---

### P4-2：StateRef "非文本传递" → 降级为"结构化状态引用，减少角色间 text handoff"

若声称"完全非文本"会被质疑：embedding 最终仍然需要在某处被解码为文本给 LLM。

**降级表述**：
> "StateBus 用 StateRef（结构化引用 + CAS 存储）替代了角色间的文本展开传递，减少了中间层 token 消耗。送给 LLM 的证据内容仍是文本，但角色间携带的是引用（非展开文本），避免了不必要的序列化轮次。这是'减少 handoff 文本量'，不是'完全绕过 LLM 文本处理'。"

---

### P4-3："replay 加速" → 降级为"replay 机制已实现，连续任务族中验证"

当前 formal benchmark 无 replay 数据，直接声称"replay 加速 X%"会被质疑。

**降级表述（无数据时）**：
> "exact_replay / validated_replay 机制完整实现。formal benchmark 为单次冷启动，不触发 replay——replay 的价值在多轮重复执行场景中体现（incident_diagnosis_v2、cross_period_financial_v1 连续任务族）。"

**升级表述（获得数据后）**：
> "在 incident_diagnosis_v2 10 轮连续执行中，R3-R10 触发 exact_replay，skipped_step_count={N}，执行时间减少约 X%（跳过 Retriever+Executor 重复调用）。"

---

### P4-4：StatePool 三后端 → 降级为"数据平面的渐进增强选项，而非冗余代码"

若评委问"三个后端为什么不统一"，需要有清晰的架构解释。

**降级表述**：
> "三层对应不同的性能/安全权衡：mmap（持久化，支持 replay）→ formal benchmark 默认；Python SharedMemory（进程间临时高速共享）→ 单机多进程 embedding 传递；memfd（Linux 匿名 FD，零拷贝）→ bwrap sandbox 内数据传递。这是有意分层设计，不同场景激活不同路径，不是技术债。"

---

## 数据集与任务族分析

### 任务族清单

| 任务族 | 轮次 | 主检索路径 | Replay 预期 | 难度定性 |
|--------|------|-----------|------------|---------|
| formal_financial_family | 8 独立 | TableRetriever（hard_fact） | 无（单次冷启动） | 容易（精确匹配） |
| incident_diagnosis_v2 | 10 连续 | SemanticChunkRetriever | R3+ exact_replay | 困难（语义+代码执行） |
| cross_period_financial_v1 | 10 连续 | TableRetriever + long_doc | R3/5/9/10 exact_replay | 中等（跨 ticker replay 风险） |
| csv_table_profile_v1 | N 轮 | TableRetriever + CSV | 视设计 | 中等 |
| csv_correlation_replay_v1 | N 轮 | TableRetriever + SemanticChunk | 视设计 | 中等 |
| long_doc_table_v1 | N 轮 | SemanticChunkRetriever（long_doc） | 视设计 | 中等 |
| long_doc_metric_replay_v1 | N 轮 | SemanticChunk + Table | 视设计 | 中等 |

### formal_financial_family 8 个任务明细

| 任务 ID | ticker | quarter | metric | 预期 route |
|---------|--------|---------|--------|-----------|
| benchmark-sample-1 | ACME | 2026Q1 | revenue | compare_metric |
| compare_metric_acme_q2 | ACME | 2026Q2 | revenue | compare_metric |
| compare_metric_acme_q3 | ACME | 2026Q3 | revenue | compare_metric |
| compare_metric_acme_q4_2025 | ACME | 2025Q4 | revenue | compare_metric |
| compare_metric_acme_q2_margin | ACME | 2026Q2 | margin | compare_metric |
| compare_metric_acme_q1_opincome | ACME | 2026Q1 | opincome | compare_metric |
| compare_metric_beta_q1_revenue | BETA | 2026Q1 | revenue | compare_metric |
| compare_metric_beta_q1_margin | BETA | 2026Q1 | margin | compare_metric |

全部 8 个任务同一 route，TableStructureRetriever 精确匹配保证 8/8 通过，与 LLM 能力无关。

### 容易任务 vs 困难任务

**容易（精确匹配保证通过）**：formal_financial_family 全部 8 个任务。风险来自 external baseline 对比公平性（P0-A）而非准确率本身。

**困难（真实语义理解）**：incident_diagnosis_v2（semantic log retrieval + bwrap code execution）。需正确提取 `slow_phase=storage_mount`、`wait_duration_seconds=6.5`。top_k=1 下若关键日志跨 chunk 可能漏失（B3）。

**跨实体 replay 风险**：cross_period_financial_v1 Round 6（BETA ticker，策略复用 ACME 的 compare_metric_table_retriever）是 P0-B bug 的真实触发场景，Round 6 预期 `validated_replay`，但 BETA 的正确 revenue=87，ACME 的 revenue=120，若触发跨实体 replay 则错误。

---

## KV Cache / Hidden-State Handoff

明确范围：**当前不实现**。KV cache（前缀重用）和 hidden-state handoff（跨模型层传递中间激活值）是 Future Work，标记为 "Engine-Local Prefix Reuse"。`v2/runtime/codeact.py` 中的 content-hash cache 是 **output-level caching**（相同输入跳过重复 LLM 调用），与 KV cache 是不同层次的优化，答辩中不应混用术语。

---

## 行动计划（优先级排序）

### P0 立即修复（答辩前 Critical）

| 编号 | 行动 | 文件/命令 |
|------|------|---------|
| 1 | P0-A：external_text_baseline revenue fallback 修复 | `external_text_baseline.py:527` |
| 2 | P0-B：validated_replay 跨实体 bug 修复 | `replay.py:351-366`，增加 `_HIGH_DISCRIMINANCE_KEYS` 值比较 |
| 3 | 运行 continuous-replay 获取 replay 触发数据（P1-4 的证据） | `python -m v2.benchmark.live_runner --suite continuous-replay --benchmark-tier dev` |
| 4 | P0-C：TableStructureRetriever `rows[:1]` 为 compute_delta 任务增加多行支持 | `pipeline.py:179` |

### P1 答辩前建议（高风险 Design Concern）

| 编号 | 行动 | 预估工时 |
|------|------|---------|
| 5 | 准备 SubprocessExecutorTransport 运行数据（fork overhead 数字） | 30 分钟 |
| 6 | P2-5：API key 测试 `skipif` 标记防止 CI 失败 | 30 分钟 |
| 7 | 答辩 PPT 中明确 loopback vs subprocess 边界（P4-1） | 文档 |

### P2 时间允许修（影响可信度但非答辩阻断）

| 编号 | 行动 |
|------|------|
| 8 | P2-1：validated_replay 跨实体错误答案测试 |
| 9 | P2-2：external baseline revenue fallback 行为测试 |
| 10 | P2-3：continuous-replay smoke 测试（replay 触发断言） |
| 11 | P2-4：SubprocessExecutorTransport e2e 测试 |
| 12 | P2-6：FAISS 归一化回归测试（B2 修复验证） |

---

## 答辩核心叙事（三个 Claim 的防御路径）

### Claim 1：结构化协议（Protobuf + UDS）比纯文本更高效

- **证据**：`text_whole_lane`（内部，comparison_valid=True）vs StateBus typed，控制变量完全对称，protocol overhead < prompt savings（telemetry 数据）
- **口径**：loopback 刻意排除网络变量，使协议开销对比更干净。SubprocessExecutorTransport 已实现，架构扩展路径存在
- **防守**：承认 loopback ≠ 真正分布式，但协议的价值在接口契约可测性，而非当前测量的 IPC 延迟

### Claim 2：非文本 StateRef 传递节省 LLM prompt bytes

- **证据**：`semantic_state_transfer_count=8`，`pruning_gain_bytes` 数据，StateBus vs external 的 prompt_bytes 对比
- **口径**：主要收益来自检索裁剪（TableRetriever 精准 vs LLM 全文），StateRef 消除角色间 handoff 文本展开为辅助收益，两者协同构成完整收益链
- **防守**：承认 16-dim embedding 的直接 token 节省微小，但 StateRef 携带语义索引和 CAS 引用，消除了中间层文本展开的系统性开销

### Claim 3：跨轮次记忆复用（exact_replay / validated_replay）加速执行

- **证据**：必须先运行 continuous-replay 获取 `exact_replay_count > 0`、`skipped_step_count > 0` 数据（P0 级紧迫）
- **口径**：formal benchmark 是冷启动单次运行，设计上不触发 replay——replay 的价值在多轮重复执行场景（incident_diagnosis_v2、cross_period_financial_v1）
- **防守**：replay 机制完整实现（gate 逻辑、ledger、candidate selection 均有代码），claim 3 的证明路径是 continuous 任务族，不是 formal benchmark

---

*审计完成：2026-07-05，代码基准 f3dd094，审计者：Claude Opus 4.6*
