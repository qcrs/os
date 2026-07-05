# New Session Deep Review Prompt

以下是给新 Claude 窗口的完整 prompt，可直接复制粘贴。

---

## PROMPT START

你是 StateBus v2 项目的代码审计工程师。

**工作目录**：`/home/qcrs/statebus/project`
**当前分支**：`feat/statebus-v2-container-runtime`
**Python 环境**：`/opt/miniconda` Python 3.12

---

## 背景速览

StateBus v2 是一个多 agent 协作框架，用于验证：
1. 类型化通信协议（Protobuf UDS）是否比纯文本协议更高效
2. 非文本 StateRef 传递（embedding + mmap/memfd）是否节省 LLM prompt bytes
3. 跨轮次记忆复用（exact_replay/validated_replay）是否真正加速

**读 git 历史了解本次会话做了什么**：

```bash
git log --oneline -10
# 关键 commits:
# d11b88d fix: remove duplicate case arm in run_v2_failed_stage_rerun_and_merge.sh
# bb81e63 feat: add cross_period_financial_v1 continuous task family
# bea207f fix: lazy import faiss in _build_faiss_index — avoid SIGKILL in bwrap sandbox
```

**修改概要**（不用重新实现，已完成）：
- `v2/memory/store.py`：faiss lazy import（P0 fix）、SQL LIKE 预过滤（B1 fix）、FAISS IndexFlatIP 后端（C1）
- `tests/v2/test_memory_store.py`：新增 SQL prefilter 和 FAISS 测试
- `v2/benchmark/live_runner.py` + `cross_period_financial/`：新增 10 轮连续任务族

---

## 你的任务：深度代码审计

读以下文件，回答每个问题。**先读文件，再回答，不要凭猜测**。

### 问题 1：Planner 的真实职责

读 `v2/runtime/smoke.py`（Planner 调用部分）和 `v2/benchmark/external_text_baseline.py`（`_planner_prompt` 函数）。

- Planner 在 `deterministic` 模式下调用 LLM 了吗？
- Planner 在 `api` 模式下调用了哪个 LLM？
- Planner 的输出（`PlannerHandoff`）对下游有什么影响？
- StateBus Planner vs external baseline Planner：设计是否对称？
- **答辩口径**：Planner 的价值是什么，如何回应"Planner 只是 hardcoded routing"的质疑？

### 问题 2：Embedding 裁剪后质量如何

读 `v2/retrieval/pipeline.py`（`SemanticChunkRetriever` 和 `_rerank_candidate_pool`）。

- `SemanticChunkRetriever` 默认 `top_k` 是多少？有没有被覆盖过？
- `hard_fact`/`semantic_context`/`lexical_hint` 三个 bucket 的评分逻辑是什么？
- 裁剪后的 evidence bundle 是否会导致 LLM 得不到正确答案？
- formal 8/8 是因为用的是 `TableRetriever`（hard_fact）还是 semantic？
- **风险**：在 incident_diagnosis 任务（日志语义检索）中，top_k=1 是否足够？

### 问题 3：外部 baseline 对比公平性

读 `v2/benchmark/external_text_baseline.py`（`_retriever_prompt` 函数）。

- external Retriever 接收的是完整 corpus 还是裁剪后的？
- StateBus Retriever 接收的是什么？
- 这个不对称是否对 StateBus 不利？还是对 StateBus 有利？
- `text_whole_lane` 与 `external baseline` 有什么区别？哪个才是"公平对比"？
- `comparison_valid=False` 的真正含义是什么，是 bug 还是设计？

### 问题 4：结构化协议真实链路

读 `v2/control/transport.py`（或 `v2/control/__init__.py`）。

- UDS + Protobuf 是真实 socket I/O 还是函数调用模拟？
- 控制帧的 wire format 是什么（4-byte header + payload？）
- formal benchmark 中 4 个角色是同进程顺序执行，还是真的多进程？
- `SubprocessExecutorTransport` 存在吗？它在哪种场景下激活？

### 问题 5：非文本状态传递的多实现关系

读 `statepool/store.py`。

- `FileBackedStatePool`、`SharedMemoryStatePool`、`MemfdStatePool` 三者关系是替代还是互补？
- formal benchmark 实际走哪条路径？
- `semantic_state_transfer_count=8` 中的"传递"具体指什么操作？
- MemfdStatePool 何时激活？为什么 formal 不用它？

**同时**读 `v2/memory/store.py`（`MemoryIndexStore`）。

- `MemoryIndexStore`（SQLite + FAISS）和 `StatePool`（mmap/shm/memfd）是两个独立系统吗？
- 各自存储什么内容？它们的数据会重复吗？

### 问题 6：FAISS vs 线性扫描

读修改后的 `v2/memory/store.py`（`_build_faiss_index`、`_faiss_score_map`、`lookup`）。

- FAISS 和线性扫描是并行跑还是 fallback 关系？
- FAISS `IndexFlatIP`（Inner Product）和 `cosine_similarity` 什么时候等价？
- 当 `embedding-mode=deterministic`（BoW hash 向量，未归一化）时，FAISS IP 和 cosine similarity 结果是否相同？
- `_faiss_dirty` 标志：什么时候 index 会重建？concurrent `put_embedding` 是否有问题？

### 问题 7：CodeAct 真实代码执行

读 `v2/runtime/codeact_sandbox.py` 和 `v2/runtime/codeact.py`。

- LLM 生成的 Python 代码真的在 bwrap sandbox 里运行了吗？
- bwrap 的隔离边界是什么（网络、文件系统、进程）？
- `deterministic_policy_fallback` 是什么？它和 LLM 生成路径有什么区别？
- formal pipeline（financial 8/8）走的是哪条路径？
- `bounded_llm_codeact_demo.py` 测试的是什么？5/5 成功的含义？

### 问题 8：Replay 正确性保证

读 `v2/runtime/replay.py`（`replay_exact_key`、`validated_replay_contract_compatible`、`select_history_replay_candidate`）。

- `replay_exact_key` 包含哪些字段？`input_artifact_hashes` 覆盖了哪些内容？
- 如果 Planner 在两次运行中给出不同的 `retrieval_objective`，exact_replay 会被触发吗？
- `validated_replay` 复用的是"策略"（route+tool）还是"答案"（具体数值）？
- 能否构造一个场景，让 validated_replay 给出错误答案？

### 问题 9：Bug 与待优化点

基于以上阅读，总结：

1. **B2**：FAISS IndexFlatIP 在未归一化向量下的正确性问题（`embedding-mode=deterministic`）— 影响范围和修复方案
2. **B3**：`SemanticChunkRetriever top_k=1` 对语义检索场景的影响 — 需要修复吗？
3. **测试缺口**：哪些关键路径没有测试覆盖？

### 问题 10：答辩时最可能遇到的硬问题

基于上述分析，准备5个最难回答的评委问题和标准回答。

---

## 参考文档

以下文档已由前一会话写好，可作为参考：

```
docs/improvement/01_p0_critical_fixes.md
docs/improvement/02_competition_claim_hardening.md
docs/improvement/03_agent_role_and_task_redesign.md
docs/improvement/04_codeact_and_sandbox_hardening.md
docs/improvement/05_memory_and_replay_complete_design.md
docs/improvement/07_non_text_state_transfer_audit.md
docs/improvement/08_performance_and_overhead_breakdown.md
docs/improvement/09_implementation_deep_review.md  ← 本次新增，包含初步分析
```

---

## 开始步骤

1. 先运行 `git log --oneline -5` 确认当前代码状态
2. 按问题顺序逐一读文件回答
3. 对每个问题，明确说明"读了哪个文件的哪几行"
4. 发现新问题或 bug，记录在 `docs/improvement/09_implementation_deep_review.md`

## PROMPT END
