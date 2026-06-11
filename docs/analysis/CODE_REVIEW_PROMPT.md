# Code Review Prompt: feat/contest-hardening 分支

将此prompt粘贴给LLM code reviewer使用。

---

## 上下文

我们在 `feat/contest-hardening` 分支上（从 `main` @ `2e5085e` 分叉），对 StateBus 多Agent协作系统做了面向赛题的增强优化。

**项目背景**：StateBus是一个面向赛题的host-side原型系统，实现Planner/Retriever/Executor/Summarizer四Agent协作，支持text/protocol双模式通信，SQLite+FAISS共享记忆，以及完整的benchmark评测体系。赛题要求：低开销通信、非文本状态传递、共享记忆复用，5个评分维度共100分。

**分支改动量**：10个文件，+2,845行，-211行。

**详细变更说明文档**：`docs/analysis/BRANCH_CHANGES_REFERENCE.md`

**设计依据文档**（按优先级）：
- 赛题要求：`docs/reference/题目.md`
- 最终执行方案：`docs/analysis/final_adjusted_plan.md`
- 逐文件实现规格：`docs/analysis/implementation_manual.md`
- CASF架构设计：`docs/analysis/novel_design_content_addressed_state_fabric.md`
- Benchmark问题分析：`docs/analysis/benchmark_task_and_result_analysis.md`
- 第三方仓库分析：`docs/analysis/third_party_analysis_and_borrowable_patterns.md`
- 代码审计+解决方案：`docs/analysis/code_audit_competition_check_and_solution_roadmap.md`
- 变更日志：`docs/analysis/CHANGES.md`

---

## Review 任务

请对 `feat/contest-hardening` 分支的以下10个变更文件做全面code review，回答以下问题：

### 一、思路分析

1. **整体方向是否正确？** 赛题要求低开销通信+非文本状态传递+共享记忆复用。这10个改动是否都直接服务于赛题评分维度？有没有偏离赛题的改动？有没有过度设计的嫌疑？

2. **CASF内容寻址存储（statepool/store.py + protocol/messages.py的StepTree/TaskCommit/ExecutionDAG）在当前阶段是否合理？** 这些数据结构定义了但orchestrator尚未使用。作为"赛后演进方向"的预留是否恰当？还是应该删掉未使用的代码？

3. **多层改动之间的关系是否自洽？** 例如：B2的记忆多信号融合需要session_id→而session_id在MemoryQuery中刚加；B3的ChannelKind标注是metadata→不影响v1兼容；CodeAct runner是独立模块→不影响主路径。这些设计假设是否合理？

4. **受控benchmark+开放探索的分层策略是否正确？** PlannerAgent.execute_step现在对plan_source=llm的task真正工作，但对plan_source=yaml的task仍走build_plan。这种双轨制在benchmark公平性和系统完整性之间是否取得了正确的平衡？

### 二、代码分析

请逐文件检查以下方面：

5. **`statepool/store.py`的`ContentAddressedBlobStore`**：
   - `put()`的refcount逻辑是否有并发安全问题（benchmark是单线程，但设计上是否考虑）？
   - blob路径用hash前2字符分片是否合理（Git也用此方式）？
   - `_refcount`是内存dict，重启后丢失——是否应该持久化？当前设计有无问题？

6. **`protocol/messages.py`的CASF数据结构**：
   - `StepTree.compute_tree_hash()`使用msgpack序列化是否稳定（跨Python版本的确定性）？
   - `ExecutionDAG._structural_similarity()`的相似度算法是否合理？权重0.15/0.10的分配有无依据？
   - `TaskCommit.seal()`修改了commit_hash后，如果后续又改了其他字段，hash不一致——这是否是设计意图？

7. **`memory/store.py`的多信号融合**：
   - combined_score = base×tier + 0.25×bm25 + 0.20×tag + 0.10×recency。这些权重是否合理？是否有理论或实验依据？
   - `_compute_keyword_overlap()`的3字符token阈值是否合理？
   - `ordered_hits.sort(key=lambda h: h.faiss_score, reverse=True)` 将combined_score放入faiss_score字段——这是否语义混淆？应该新增一个字段吗？

8. **`runtime/executor_runtime.py`的ChannelKind标注**：
   - 使用裸字符串("last_value")而非枚举类是否合适？
   - `_channel_schema`放在构建函数的返回值中，但没有在schema注册时校验——是否需要校验？

9. **`runtime/contracts.py`的InvariantChecker**：
   - 循环检测算法使用DFS+visited/temp集合——是否正确处理了多入度节点的DAG？
   - `check_state_refs()`要求每个StateRef有source_agent_id——是否所有现有StateRef都满足？

10. **`runtime/codeact_runner.py`的CodeActRunner**：
    - 安全校验只检查import字符串——是否足够？能否通过`__import__('os')`绕过？
    - 环境变量清理只删了PYTHONPATH和PYTHONNOUSERSITE——是否足够隔离？

11. **`agents/sample_agents.py`的PlannerAgent.execute_step**：
    - LLM生成的Plan会被`_plan_from_llm_output`中的`_expected_plan_contract`严格校验——如果LLM生成的不是3-step结构，会直接raise。这意味着开放Planner仍然受限于3-step合同。这是否与"开放探索"的初衷冲突？
    - `_build_open_planner_prompt`的prompt没有明确告知LLM"必须生成3-step结构"——还是依赖下游校验来拒绝。这是否合理？

12. **`tasks/sample_benchmark.yaml`的task变更**：
    - 删除了session_chain（6 tasks）——这会导致和之前benchmark run的历史数据不可比。是否应该保留一个历史版本？
    - 新增的lexical_override task的`expected_route`字段（如"replica_drift"、"worker_stall"）是否对应ToolRegistry中实际注册的route名称？

13. **`eval/runner.py`的报告口径调整**：
    - Aggregate免责声明只在task_mode_counts不对称时出现——逻辑是否正确？
    - Protocol Compliance section写死了"InvariantChecker not yet enabled"——占位符是否正确？

### 三、改进建议

14. **哪些改动有明确的bug风险？** 如果有，请给出具体修复方案。

15. **哪些改动虽然正确但可以简化？** 过度设计的部分可以裁减什么？

16. **如果只能保留5个改动（当前有10个文件），应该保留哪5个？** 按赛题评分贡献排序。

17. **下一步最应该做什么？** 在"完善现有改动"和"新增功能"之间如何选择？

---

## 如何Review

```bash
# 查看分支
git branch -a | grep contest-hardening

# 查看所有改动
git diff main...feat/contest-hardening --stat

# 查看具体文件diff（示例）
git diff main...feat/contest-hardening -- statepool/store.py
git diff main...feat/contest-hardening -- protocol/messages.py
git diff main...feat/contest-hardening -- memory/store.py
git diff main...feat/contest-hardening -- runtime/contracts.py
git diff main...feat/contest-hardening -- runtime/executor_runtime.py
git diff main...feat/contest-hardening -- runtime/codeact_runner.py
git diff main...feat/contest-hardening -- agents/sample_agents.py
git diff main...feat/contest-hardening -- tasks/sample_tasks.py
git diff main...feat/contest-hardening -- tasks/sample_benchmark.yaml
git diff main...feat/contest-hardening -- eval/runner.py
```

**变更说明文档**：`docs/analysis/BRANCH_CHANGES_REFERENCE.md`（包含逐文件清单+设计来源+评分对应）

**设计文档目录**：`docs/analysis/`（包含7份分析文档，建议至少阅读`final_adjusted_plan.md`和`implementation_manual.md`）
