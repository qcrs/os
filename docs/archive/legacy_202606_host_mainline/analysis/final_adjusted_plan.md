# StateBus 最终调整方案 & 可实现性分析

日期：`2026-06-10`

基于四份分析文档 + 四份参考文档 + 代码深度审计 + 沟通结论的综合调整方案。

---

## 一、现有文档清单

### 1.1 分析文档（`docs/analysis/`，共4份，2,356行）

| # | 文档 | 行数 | 定位 | 需要调整的部分 |
|---|------|------|------|-------------|
| 1 | `benchmark_task_and_result_analysis.md` | 507 | 29-task formal controlled pack的逐层实验分析 | 修正建议部分需更新优先级 |
| 2 | `third_party_analysis_and_borrowable_patterns.md` | 670 | 9个本地仓库+4个社区项目的可借鉴模式分析 | LangGraph部分需标注"不引入框架，只借模式" |
| 3 | `code_audit_competition_check_and_solution_roadmap.md` | 623 | 全代码审核+赛题核对+4 Phase解决方案 | **需要大幅调整**：删掉不切实际的项，聚焦高ROI的 |
| 4 | `novel_design_content_addressed_state_fabric.md` | 556 | CASF架构提案（原创设计） | 标注为"赛后演进方向"，不进入当前执行计划 |

### 1.2 参考文档（`docs/reference/`，共10份）

| # | 文档 | 关键结论 |
|---|------|---------|
| 5 | `题目.md` | 赛题权威需求源，唯一必须反向对齐的源头 |
| 6 | `PROJECT_STATUS_REPORT.md` | LangGraph能力审计：编排/Channel/Store顶级，但benchmark/protocol对比/记忆统计完全不提供 |
| 7 | `multi_agent_demo_report.md` | LangGraph demo实测：4 Agent跑通，但非文本状态传递❌、性能对比❌。**论证了StateBus自建的必要性** |
| 8 | `multi-agent-system-design.md` | 理想化设计稿（MessagePack+ChromaDB+CodeAct），**从未实现** |
| 9 | `statebus_architecture_and_implementation_plan.md` | StateBus三面模型(控制面/数据面/记忆面)+6 Phase实施计划 |
| 10 | `statebus_dual_plane_deep_design.md` | 边界、生命周期、事务、回滚设计 |
| 11 | `statebus_architecture_evolution_feasibility_report.md` | 架构演进行性报告 |
| 12 | `statebus_真实场景时序图消息表状态表.md` | 落地任务链、消息表、状态表 |
| 13 | `赛题9设计讲解压缩稿.md` | 答辩用讲解稿 |
| 14 | `s_memory_agent_design.md` | 目录结构和实验组织参考 |

### 1.3 项目中的参考仓库（`third_party/`，9个）

| 仓库 | 价值 | 当前使用状态 |
|------|------|-------------|
| langgraph | Channel模型、Pregel编排、Checkpoint | **不引入框架，只借鉴Channel/Typed状态模式** |
| mem0 | Provider插件架构、多信号检索融合、追加式记忆 | 借鉴多信号检索和append-only模式 |
| haystack | Typed socket、Pipeline引擎、连接类型校验 | 借鉴连接类型预校验 |
| semantic-router | 混合路由(dense+sparse)、threshold rejection | 借鉴RRF融合和threshold策略 |
| agent-memory-server | 双层记忆(working+long-term)、自动promotion | 借鉴双层记忆模型和recency reranking |
| memsearch | 文件为真源+SHA-256去重、三层递进检索 | 借鉴content-hash去重（CASF方案的灵感来源） |
| AgentRx | Trajectory IR、不变量检查、LLM-as-judge | 借鉴invariant checker和trajectory schema |
| evals | Eval注册表、CompletionFn抽象 | 借鉴声明式eval定义 |
| langgraph-bigtool | 工具语义检索、lazy capability loading | 借鉴工具检索模式 |

---

## 二、沟通结论对调整的影响

### 结论1：不引入LangGraph

**影响**：
- 文档3中所有"用LangGraph替换编排层"的隐含假设 → 删除
- 文档2中LangGraph的分析 → 从"可引入的框架"改为"可借鉴模式的参考库"
- Phase B的方案保持——因为它们都是增量改动，不依赖LangGraph

### 结论2：Retriever/Executor保持非LLM

**影响**：
- 文档3中"CodeAct"的重要性降级——从Phase B降到Phase C（加分项）
- 文档1中assist不work的分析需要更聚焦——根因不是"Retriever/Executor没LLM"，而是"记忆检索精度+summarizer overhead"

### 结论3：受控为主，开放为辅

**影响**：
- 文档3的Benchmark重构方案需要分层——保留受控主对比层，增加开放探索层
- Planner真实化（不raise NotImplementedError）提升到P0——这比任何feature都紧急

### 结论4：当前编排层够用，不替换

**影响**：
- CASF方案（文档4）标注为"赛后演进方向"
- 文档3的Phase C中删掉与编排层重构相关的项

---

## 三、调整后的执行计划

### 优先级重新分类

```
P0 (致命) — 不修赛题硬要求不成立
  ├── P0-1: Planner真实化 (不让它raise NotImplementedError)
  ├── P0-2: state_transfer lane补text对照
  └── P0-3: 恢复sample_benchmark.yaml到475行

P1 (严重影响评分) — 修了显著提升分数
  ├── P1-1: Benchmark lane配额优化 (62%内部回归→60%赛题主张)
  ├── P1-2: 双层记忆+多信号检索 (让assist变有用)
  ├── P1-3: FEATURE_BUNDLE加ChannelKind标注 (提升状态传递创新)
  └── P1-4: Communication lane扩充 (2 task→6 task, 1 domain→3 domain)

P2 (明显改进) — 修了增加亮点
  ├── P2-1: 增量协议帧 (DeltaPlanStep)
  ├── P2-2: Route多样性task (hint_consensus 100%→加入lexical_override)
  ├── P2-3: Task结构多样性 (2-step/4-step)
  └── P2-4: CodeAct兜底实现

P3 (赛后/交付)
  ├── P3-1: CASF架构 (文档4)
  ├── P3-2: openEuler VM验证
  └── P3-3: 文档/视频交付
```

### 简化后的Phase

```
Phase A (1-2天): 止血
  A1: git checkout -- tasks/sample_benchmark.yaml
  A2: state_transfer lane补text + protocol对称对照
  A3: Planner真实化 (真正调LLM生成Plan, 至少2-3个开放task)
  A4: 报告口径调整 (fresh_retrieval提前, aggregate免责声明)
  
Phase B (2-3天): 增强核心主张
  B1: Benchmark重构 (lane配额: 62%→60%+; communication 2→6 task)
  B2: 双层记忆+多信号检索 (working/long-term tier + semantic+BM25+entity+recency)
  B3: FEATURE_BUNDLE → ChannelKind标注 (不改变格式, metadata加channel_schema)
  B4: 增量协议帧 (DeltaPlanStep, 同chain节省15-25%)
  
Phase C (1-2天): 深化亮点
  C1: CodeAct兜底 (subprocess+timeout, 不引入nsjail)
  C2: Route多样性task (lexical_override × 3)
  C3: 协议InvariantChecker (静态不变量自动检查)
  C4: 最终benchmark重跑 + 报告生成
  
Phase D (1-2天): 交付
  D1: 系统设计文档更新
  D2: 实验报告
  D3: openEuler VM验证(如条件允许)
```

### 删除了什么

| 原方案中的项 | 删除原因 |
|------------|---------|
| 用LangGraph替换编排层 | 沟通结论：不引入，编排层不是瓶颈 |
| CASF完整实现 | 降为赛后演进方向（文档4保留为设计参考） |
| Trajectory IR完整实现 | 降为P3（工作量>收益，AgentRx的invariant checker更优先） |
| Typed Channel完整重写(schema v1→v2) | 改为轻量的ChannelKind标注（不破坏现有schema） |
| shared_memory backend story | 当前mmap主线已够用，不追mixed结论 |
| External UDS executor强化 | 已有样机，不需要继续堆 |
| 所有P3"赛后"项进入当前Phase | 聚焦赛题deadline |

---

## 四、可实现性逐项分析

### Phase A（止血）—— 可实现性：★★★★★

| 项 | 工作量 | 依赖 | 风险 | 验证方式 |
|----|--------|------|------|---------|
| A1: git checkout | 1分钟 | 无 | 无 | wc -l = 475 |
| A2: state_transfer对称化 | 2-3小时 | A1 | text模式transfer task可能解析失败 | deterministic preflight |
| A3: Planner真实化 | 3-4小时 | 无 | LLM生成的Plan格式不一致，解析失败 | 2-3个开放task的plan解析测试 |
| A4: 报告口径 | 1小时 | A2 | 无 | benchmark_report.md检查 |

**A3的详细实现方案**：

当前问题：
```python
# agents/sample_agents.py:155
class PlannerAgent(BaseAgent):
    def execute_step(self, step, ctx):
        raise NotImplementedError("Planner receives plan externally")
```

修复方案（最小改动）：
```python
class PlannerAgent(BaseAgent):
    def execute_step(self, step: PlanStep, ctx: RunContext) -> StepResult:
        """Planner真正调用LLM生成Plan（用于开放探索层task）。
        受控benchmark层的task仍走build_plan()绕过。"""
        if ctx.task.get("plan_mode") == "controlled":
            # 受控模式：plan由YAML提供，Planner只做校验
            return StepResult(...)
        
        # 开放模式：Planner真正工作
        prompt = build_planner_prompt(
            task=ctx.task,
            capability_table=ctx.capability_table,
            memory_hits=ctx.search_memory(...),
        )
        llm_response = self.llm_client.complete(prompt)
        plan = parse_plan_from_llm(llm_response)
        return StepResult(
            step_id=step.step_id,
            success=True,
            output_state_refs=[put_feature_state("plan", plan)],
        )
```

关键设计：
- 不修改受控benchmark的plan生成路径（保持deterministic repeat-10）
- 新增2-3个`plan_mode: open`的task，Planner在这些task上真正调LLM
- Benchmark report中标注：主对比实验在受控plan下完成，附录展示开放plan结果
- 如果LLM生成的plan不符合Schema → SchemaInterceptor拦截 → 重试或回退到default plan

### Phase B（增强核心主张）—— 可实现性：★★★★☆

| 项 | 工作量 | 依赖 | 风险 | 验证方式 |
|----|--------|------|------|---------|
| B1: Benchmark重构 | 3-4小时 | A1+A2 | 新task定义错误→失败率高 | deterministic preflight全task |
| B2: 双层记忆+多信号 | 4-6小时 | 无 | recency权重过大→检索变差 | 用历史数据grid search最佳权重 |
| B3: ChannelKind标注 | 2-3小时 | 无 | 改变schema格式→向下兼容问题 | v1 consumer忽略新字段 |
| B4: 增量协议帧 | 3-4小时 | 无 | delta有bug→接收方不完整 | SchemaInterceptor校验+unit test |

**B2的详细实现方案**（基于已有代码）：

当前 `memory/store.py:397-403` 的 `search()`：
```python
def search(self, query: MemoryQuery) -> list[MemoryHit]:
    results = self._search_semantic(query)  # 纯cosine
    if not results:
        results = self._search_keyword(query)  # FTS5 fallback
    return results[:query.top_k]
```

修改方案（在`_search_semantic`内部，不改变接口）：
```python
def _search_semantic(self, query: MemoryQuery) -> list[MemoryHit]:
    # ---- 现有逻辑 ----
    candidates = self._vector_index.search(query.embedding, top_k * 8)
    
    # ---- 新增：多信号融合 ----
    for candidate in candidates:
        base_score = candidate.semantic_score  # 现有cosine
        
        # BM25 term overlap (利用已有FTS5)
        bm25 = self._bm25_overlap(query.query_text, candidate.summary)
        
        # Entity/tag boosting
        tag_overlap = len(set(query.tags) & set(candidate.tags)) / max(len(query.tags), 1)
        
        # Recency decay (λ=0.0001)
        age_hours = (time.time() - candidate.created_at) / 3600
        recency = math.exp(-0.0001 * age_hours * 3600)
        
        # Memory tier boost (working memory: 同session → ×1.5)
        tier = 1.5 if candidate.session_id == query.session_id else 1.0
        
        candidate.combined_score = (
            base_score * tier +      # semantic + tier weight
            0.25 * bm25 +            # BM25
            0.20 * tag_overlap +     # tag match
            0.10 * recency           # recency
        )
    
    candidates.sort(key=lambda c: -c.combined_score)
    return candidates[:query.top_k]
```

**可行性**：所有依赖数据（tags、created_at、summary text）已经在SQLite schema中存在，不需要改表结构。BM25 overlap复用已有的FTS5分词能力。风险可控（通过权重参数可调）。

**B4的详细实现方案**：

修改`runtime/orchestrator.py`的PlanStep emit逻辑——在`_emit_steps`中插入delta检测：

```python
def _maybe_emit_delta(self, step, previous_step, same_chain):
    if not same_chain or not previous_step:
        return protocol_bytes(step)  # 完整传输
    
    delta = {
        k: v for k, v in step.params.items()
        if previous_step.params.get(k) != v
    }
    new_deps = [d for d in step.depends_on if d not in previous_step.depends_on]
    
    if not delta and not new_deps:
        # 完全相同 → 只传DeltaPlanStep(几乎为空帧)
        msg = DeltaPlanStep(step_id=step.step_id, 
                           base_step_id=previous_step.step_id,
                           delta_params={}, delta_depends_on=[])
        return protocol_bytes(msg)
    
    if sum(len(str(v)) for v in delta.values()) + len(str(new_deps)) + 100 < len(protocol_bytes(step)):
        # 节省>100字节才用delta
        msg = DeltaPlanStep(step_id=step.step_id,
                           base_step_id=previous_step.step_id,
                           delta_params=delta, delta_depends_on=new_deps)
        return protocol_bytes(msg)
    
    return protocol_bytes(step)  # 回退完整传输
```

**可行性**：纯增量改动（新增一个消息类型+emit时判断），不影响现有协议帧格式。向后兼容：DeltaPlanStep通过`base_step_id`引用，接收方可lazy fetch完整PlanStep。

### Phase C（深化亮点）—— 可实现性：★★★☆☆

| 项 | 工作量 | 依赖 | 风险 | 验证方式 |
|----|--------|------|------|---------|
| C1: CodeAct兜底 | 3-4小时 | 无 | LLM生成代码有bug | subprocess+timeout+禁止危险import |
| C2: Route多样性task | 2-3小时 | B1 | 新task定义复杂 | deterministic验证 |
| C3: InvariantChecker | 2-3小时 | 无 | 不变量定义过多，误报 | 先在diagnostic pack上验证 |
| C4: 最终benchmark重跑 | 2-3小时(运行时间) | B1+B2+B3+B4+C1+C2 | API波动影响结果 | serialized API repeat-3 |

### Phase D（交付）—— 可实现性：★★★★☆

| 项 | 工作量 | 依赖 | 风险 |
|----|--------|------|------|
| D1: 设计文档更新 | 3-4小时 | Phase A+B+C完成 | 文档与代码不一致 |
| D2: 实验报告 | 2-3小时 | C4完成 | 数据解读偏差 |
| D3: openEuler验证 | 2-4小时 | 独立 | 依赖安装失败 |

---

## 五、与参考文档和参考仓库的对齐

### 5.1 参考文档对齐

| 参考文档 | 对当前方案的影响 |
|---------|----------------|
| `题目.md` | Phase A的P0项都是直接修复违反赛题要求的问题 |
| `PROJECT_STATUS_REPORT.md` | 确认LangGraph不引入——因为缺失的（benchmark/protocol对比/记忆统计）恰好是赛题核心 |
| `multi_agent_demo_report.md` | 确认非文本状态传递需要自建——LangGraph不支持，文档3的Phase B3就是做这个 |
| `multi-agent-system-design.md` | 设计的理想（开放的Planner/动态任务分解）作为Phase A3的参考——Planner真实化就做这个 |
| `implementation_plan.md` | Phase 0-4已闭环，当前在Phase 5-6之间 |
| 讲解压缩稿 | Phase D的答辩材料参考 |

### 5.2 参考仓库对齐

| 参考仓库 | 借鉴的模式 | 在方案中的落点 |
|---------|-----------|-------------|
| langgraph | Channel语义(LastValue/Topic/Ephemeral) | Phase B3 (ChannelKind标注) |
| langgraph | DeltaChannel增量checkpoint | Phase B4 (DeltaPlanStep) |
| agent-memory-server | 双层记忆(working/long-term) + recency | Phase B2 |
| mem0 | 多信号检索融合 + append-only记忆 | Phase B2 |
| semantic-router | 混合路由(dense+sparse) + RRF融合 | Phase B2 (BM25 term overlap) |
| memsearch | SHA-256内容去重 | 文档4 (CASF, 赛后) |
| AgentRx | 不变量检查 + Trajectory IR | Phase C3 (InvariantChecker) |
| evals | 声明式eval定义 | 现有benchmark YAML已采用 |

---

## 六、最终可实现性总评估

```
                     乐观估计      保守估计     置信度
Phase A (止血)        1天          2天         ★★★★★
Phase B (增强)        2天          3天         ★★★★☆
Phase C (深化)        1.5天        2.5天       ★★★☆☆
Phase D (交付)        1.5天        2天         ★★★★☆
─────────────────────────────────────────
总计                   6天          9.5天
```

**关键路径**：A2 → B1 → C4 → D2（state_transfer对称化 → benchmark重构 → 最终重跑 → 实验报告）

**最大的不确定性**：
1. A3 Planner真实化：LLM生成的Plan格式稳定性不确定 → 需要fallback到受控plan
2. C1 CodeAct：LLM生成的代码质量不确定 → subprocess+timeout作为安全网
3. C4 API benchmark重跑：API波动 → 用serialized api repeat-3来保证稳定性

**不会阻塞的因素**：
- B2/B3/B4互相独立，可以并行开发
- C1/C2/C3互相独立，可以并行开发
- D3（openEuler）与D1/D2并行

---

## 七、修改文件清单（最终版）

### 必须修改（P0+P1）

| 文件 | 改动内容 | 行数 |
|------|---------|------|
| `tasks/sample_benchmark.yaml` | git checkout恢复475行 + lane配额调整 + state_transfer对称化 | ~100行改动 |
| `agents/sample_agents.py` | PlannerAgent.execute_step真实实现 + ChannelKind标注 | ~80行 |
| `memory/store.py` | 双层记忆+多信号检索融合 | ~100行 |
| `runtime/orchestrator.py` | DeltaPlanStep emit逻辑 + 报告口径 | ~80行 |
| `protocol/messages.py` | DeltaPlanStep消息类型 + ChannelKind枚举 | ~60行 |
| `eval/runner.py` | 报告口径调整(fresh_retrieval提前) | ~30行 |

### 建议修改（P2）

| 文件 | 改动内容 | 行数 |
|------|---------|------|
| `runtime/codeact_runner.py` | **新增** CodeAct执行模块 | ~120行 |
| `runtime/contracts.py` | InvariantChecker + ChannelKind注册 | ~80行 |
| `eval/metrics.py` | delta/invariant相关metric | ~20行 |

### 不修改（明确排除）

| 文件 | 原计划改动 | 排除原因 |
|------|-----------|---------|
| `runtime/orchestrator.py` 编排引擎替换 | 引入LangGraph重写 | 沟通结论：不引入框架，编排层不是瓶颈 |
| `statepool/store.py` | SHA-256内容去重 | 降为赛后（文档4 CASF） |
| `tasks/sample_tasks.py` | build_plan支持可变step数 | 保留受控3-step主线，开放task走Planner真实化 |

**总计改动**：约470行新增 + 100行修改 + 0行删除核心逻辑

---

## 八、文档使用指南

| 你要做什么 | 看哪份文档 |
|-----------|-----------|
| 理解当前benchmark问题 | `benchmark_task_and_result_analysis.md` |
| 找可借鉴的模式 | `third_party_analysis_and_borrowable_patterns.md` |
| 开始写代码实现 | **本文档**（最终调整方案） |
| 理解赛题要求 | `docs/reference/题目.md` |
| 了解为什么不用LangGraph | `docs/reference/PROJECT_STATUS_REPORT.md` + `multi_agent_demo_report.md` |
| 答辩材料参考 | `docs/reference/赛题9设计讲解压缩稿.md` |
| 赛后演进方向 | `novel_design_content_addressed_state_fabric.md` |
| 设计原理 | `docs/reference/statebus_architecture_and_implementation_plan.md` |
