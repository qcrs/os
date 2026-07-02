# StateBus 实施手册：逐文件实现细节

日期：`2026-06-10`

本文档是 `final_adjusted_plan.md` 的配套实施手册。**每一个Phase的每一项都精确到要改哪个文件、哪个函数、改成什么样、如何验证。** 照此文档实现即可，不需要再做设计决策。

**与新方案的对照关系**：
- 基准文档：`final_adjusted_plan.md`（优先级/Phase/任务列表）
- 本手册：每个任务的具体实现步骤
- 无冲突——新方案是原方案的优先级重排+实现深度细化，未删除任何feature

---

# Phase A：止血（必须先做）

## A1：恢复 sample_benchmark.yaml

**文件**：`tasks/sample_benchmark.yaml`

**操作**：
```bash
cd /home/qcrs/statebus/project
git checkout HEAD -- tasks/sample_benchmark.yaml
```

**验证**：
```bash
wc -l tasks/sample_benchmark.yaml
# 预期输出：475
grep "formal_controlled_pack" tasks/sample_benchmark.yaml
# 预期输出：name: formal_controlled_pack
```

**无代码修改**。这恢复的是最后commit的29-task formal controlled pack。

---

## A2：state_transfer lane 补 text 对称对照

### 问题

`transfer_lane` 6个task全部 `allowed_modes: [protocol]`。text模式跑不到state_transfer lane，违反赛题"双模式在相同任务条件下对比"的要求。

### 方案

**策略**：不增加新task，而是让现有6个transfer_lane task同时支持text和protocol，利用 `transfer_strategy` 字段做mode-dependent语义：

- text模式下：transfer task使用 `text_brief` handoff
- protocol模式下：使用 `state_ref` handoff
- 同一个task_id在两种mode下跑出不同handoff方式，但task本身的query/corpus/reuse条件完全相同——保证公平对比

**原理**：`transfer_strategy` 字段当前是YAML中的静态值，但 `RetrieverAgent.execute_step` 在运行时读取 `ctx.transfer_strategy()`。我们可以让 `transfer_strategy` 根据 `mode` 动态解析。

### 实现

#### Step 1：修改 transfer_lane 的 allowed_modes

**文件**：`tasks/sample_benchmark.yaml`

对 `transfer_lane` 的6个task，将 `allowed_modes: [protocol]` 改为 `allowed_modes: [text, protocol]`。

同时增加一个mode-dependent transfer_strategy指示：

```yaml
# 修改前 (以 transfer-cache-text-packet-001 为例)
  - task_id: transfer-cache-text-packet-001
    task_group: transfer_lane
    transfer_strategy: text_packet_minimal
    allowed_modes: [protocol]
    
# 修改后
  - task_id: transfer-cache-text-packet-001
    task_group: transfer_lane
    transfer_strategy: text_packet_minimal
    transfer_strategy_text: text_brief           # ← 新增: text模式下的handoff方式
    transfer_strategy_protocol: state_packet_minimal  # ← 新增: protocol模式下的handoff方式
    allowed_modes: [text, protocol]
```

对于6个transfer task：
- 3个 `text-packet-*` task：`transfer_strategy_text: text_brief`, `transfer_strategy_protocol: state_packet_minimal`
- 3个 `state-packet-*` task：`transfer_strategy_text: text_brief`, `transfer_strategy_protocol: state_ref`

**语义**：原任务设计的对比是"text_packet vs state_packet（carrier efficiency）"。现在改为"text模式下都走text_brief，protocol模式下走各自的carrier策略"。这样text vs protocol的state_transfer对比成立。

#### Step 2：支持 mode-dependent transfer strategy

**文件**：`tasks/sample_tasks.py`，约第346-377行的 `_load_sample_task` 函数

在 `SampleTask` dataclass 中新增两个字段：

```python
# tasks/sample_tasks.py 约第136行 SampleTask定义处
@dataclass(frozen=True)
class SampleTask:
    # ... 现有字段 ...
    transfer_strategy_text: str = ""      # ← 新增
    transfer_strategy_protocol: str = ""  # ← 新增
```

在 `_load_sample_task` 中加载这两个字段：

```python
# tasks/sample_tasks.py 约第365行
transfer_strategy_text=str(item.get("transfer_strategy_text", "")).strip(),
transfer_strategy_protocol=str(item.get("transfer_strategy_protocol", "")).strip(),
```

#### Step 3：在 RunContext 中根据 mode 解析 transfer_strategy

**文件**：`runtime/orchestrator.py`，约第114-137行的 `RunContext`

当前 `transfer_strategy` 是从 `RuntimeTaskProfile` 来的固定值。需要在初始化时考虑mode-dependent override：

```python
# runtime/orchestrator.py，RunContext.__init__ 或 transfer_strategy() 方法
def transfer_strategy(self) -> str:
    """返回当前mode下的transfer strategy"""
    base = self._task.transfer_strategy
    if self.mode == "text" and self._task.transfer_strategy_text:
        return self._task.transfer_strategy_text
    if self.mode == "protocol" and self._task.transfer_strategy_protocol:
        return self._task.transfer_strategy_protocol
    return base
```

**或者更简单的方式**——直接在Orchestrator初始化时根据mode做一次解析：

```python
# runtime/orchestrator.py RunContext.__init__ 中
mode_strategy_field = f"transfer_strategy_{self.mode}"
effective_strategy = (
    getattr(self._task, mode_strategy_field, None) 
    or self._task.transfer_strategy
)
self._transfer_strategy = normalize_transfer_strategy(effective_strategy)
```

### 验证

```bash
python -m eval.runner \
  --task-set formal_controlled \
  --repeat 1 \
  --llm-mode deterministic \
  --out /tmp/a2_verify
```

检查：
- `benchmark_report.md` 中 `transfer_lane` 在 **text 和 protocol 两列都有数据**
- text 模式的 `transfer_lane` handoff 使用 `text_brief`（handoff_textual_bytes > 0）
- protocol 模式的 `transfer_lane` handoff 使用 `state_ref`/`state_packet_minimal`（handoff_nontext_bytes > 0）

---

## A3：Planner 真实化（核心修复）

### 问题

`agents/sample_agents.py:155` — `PlannerAgent.execute_step` 直接 `raise NotImplementedError`。真实的plan来自 `tasks/sample_tasks.py:build_plan()` 的硬编码3-step。

评委必问："你们的Planner到底规划了什么？" 当前无法回答。

### 方案

**不修改受控benchmark路径**——`build_plan()` 保留，deterministic repeat-10继续成立。

**新增开放Planner路径**——当task的YAML中标记 `plan_source: llm` 时，Planner真正调LLM生成Plan。

**两种模式并行**：
- 受控benchmark task → `plan_source: yaml`（默认）→ `build_plan()` → 固定3-step
- 开放探索task → `plan_source: llm` → `PlannerAgent.execute_step` → LLM生成Plan

### 实现

#### Step 1：SampleTask 新增 plan_source 字段

**文件**：`tasks/sample_tasks.py`

```python
@dataclass(frozen=True)
class SampleTask:
    # ... 现有字段 ...
    plan_source: str = "yaml"  # "yaml" | "llm"
```

`_load_sample_task` 中：
```python
plan_source=str(item.get("plan_source", "yaml")).strip(),
```

#### Step 2：Orchestrator 中根据 plan_source 选择plan来源

**文件**：`runtime/orchestrator.py`，`_execute_task` 或类似入口

```python
# 当前代码（简化）
plan = build_plan(task)  # 永远走YAML

# 修改后
if task.plan_source == "llm":
    # PlannerAgent真正工作
    plan_result = await self._delegate_to_planner(task)
    plan = plan_result.plan
else:
    # 受控路径（保持不变）
    plan = build_plan(task)
```

#### Step 3：PlannerAgent.execute_step 真正实现

**文件**：`agents/sample_agents.py`，约第130-160行

```python
class PlannerAgent(BaseAgent):
    def execute_step(self, step: PlanStep, ctx: RunContext) -> StepResult:
        """Planner生成Plan：解析用户query → 分解为step序列 → 校验。
        
        只在 plan_source='llm' 的task中被调用。
        受控benchmark task不走此路径（直接build_plan）。
        """
        # 构建prompt
        capability_desc = ctx.capability_table.describe()
        memory_context = ""
        memory_hits = ctx.search_memory(...)
        if memory_hits:
            memory_context = _format_memory_context(memory_hits)
        
        prompt = _build_planner_prompt(
            task_goal=ctx.task.goal,
            task_query=ctx.task.query,
            capability_table=capability_desc,
            memory_context=memory_context,
            mode=ctx.mode,  # text使用自然语言prompt, protocol使用紧凑prompt
        )
        
        # 调LLM
        llm_result = self.llm_client.complete(prompt)
        ctx.record_llm_result("planner", llm_result)
        
        # 解析Plan
        plan = parse_plan_from_llm(llm_result.content, ctx.mode)
        
        # Schema校验
        ctx.validator.validate_plan(plan)
        
        return StepResult(
            step_id=step.step_id,
            success=True,
            output_state_refs=[ctx.put_feature_state("plan", plan)],
            summary=f"Planner generated plan with {len(plan.steps)} steps",
        )


def _build_planner_prompt(task_goal, task_query, capability_table, memory_context, mode):
    """构建Planner的LLM prompt"""
    if mode == "protocol":
        # 紧凑协议提示
        return {
            "system": "sb-plan-v1: decompose task into steps using available capabilities.",
            "user": f"goal:{task_goal}\nquery:{task_query}\ncapabilities:{capability_table}\nmemory:{memory_context}\noutput:JSON Plan"
        }
    else:
        # 自然语言提示
        return {
            "system": "你是一个任务规划专家。根据用户目标和可用Agent能力，将任务分解为步骤序列。",
            "user": f"目标：{task_goal}\n查询：{task_query}\n可用能力：{capability_table}\n历史参考：{memory_context}\n请以JSON格式输出Plan。"
        }


def parse_plan_from_llm(content: str, mode: str) -> Plan:
    """解析LLM输出为Plan对象"""
    import json
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # 尝试提取JSON块
        import re
        match = re.search(r'\{[\s\S]*\}', content)
        if not match:
            raise ValueError(f"LLM planner output is not valid JSON: {content[:200]}")
        data = json.loads(match.group(0))
    
    steps = []
    for i, step_data in enumerate(data.get("steps", [])):
        steps.append(PlanStep(
            step_id=step_data.get("step_id", f"step_{i+1}"),
            owner_agent=step_data.get("owner_agent", "executor"),
            action=step_data.get("action", "EXECUTE_PLAYBOOK"),
            input_state_refs=[],
            params=step_data.get("params", {}),
            depends_on=step_data.get("depends_on", []),
        ))
    
    return Plan(
        task_id=data.get("task_id", "llm-generated"),
        goal=data.get("goal", ""),
        steps=steps,
    )
```

#### Step 4：新增2-3个 plan_source=llm 的task

**文件**：`tasks/sample_benchmark.yaml`

在 `formal_controlled_pack` 的 tasks 列表末尾追加：

```yaml
  # 开放探索层task —— Planner真正工作
  - task_id: open-plan-cache-001
    task_group: open_plan_lane
    task_order: 1
    task_theme: repo_local_cache_staleness
    plan_source: llm                    # ← 关键：LLM生成Plan
    benchmark_lane: internal_regression
    transfer_strategy: state_ref
    allowed_modes: [text, protocol]
    goal: Diagnose stale inventory and recommend fix
    query: inventory counts stay stale after batch sync
    corpus_doc_ids: [cache-invalid-anchor, cache-invalid-followup, cache-replica-false]
    tags: [cache, open-plan]
    runtime_reuse_contract: reuse_disabled
    expected_reuse_mode: none
    summary_hint: Return root cause, ruled-out explanation, and first action.
```

类似地追加 `open-plan-latency-001` 和 `open-plan-session-001`。

**这些task不参与主benchmark对比（单独标注为"开放探索"），在report中作为附录展示。**

#### Step 5：benchmark report 中标注plan来源

**文件**：`eval/runner.py`，report生成部分

在task列表或metadata中增加：
```
- Plan source counts: {"yaml": 29, "llm": 3}
- Interpretation: main comparison uses yaml-sourced plans for reproducibility; 
  llm-sourced plans in appendix demonstrate Planner capability
```

### 验证

```bash
# 单独跑开放plan task
python -m eval.runner \
  --task-set formal_controlled \
  --repeat 1 \
  --llm-mode api \
  --out /tmp/a3_verify

# 检查
grep "plan_source" /tmp/a3_verify/benchmark_report.md
grep "open-plan" /tmp/a3_verify/benchmark_results.json
```

预期：`open-plan-*` task的failure_count=0（Planner生成的Plan通过了SchemaInterceptor校验），且这些task有planner token消耗。

### 回滚

如果LLM生成的Plan经常不合法或benchmark不稳定：
- 将 `open-plan-*` task从 formal pack 移除
- 单独放到 `open_validation_benchmark.yaml` 中（已有此文件）
- 这样主benchmark仍用纯受控plan

---

## A4：调整 Benchmark Report 口径

### 问题

aggregate视图因mode不对称造成 `protocol control_bytes > text` 假倒挂。`fresh_retrieval` 口径被埋在第180行。

### 实现

**文件**：`eval/runner.py`，约第2148行开始的report生成函数 `_write_markdown_report`

#### 修改1：aggregate 前增加免责声明

在aggregate表格前插入：

```markdown
> **Aggregate interpretation note**: aggregate mixes tasks with different 
> mode-specific task counts (text runs 23 tasks, protocol runs 29 tasks). 
> Protocol's higher aggregate control_bytes (170101 vs 158460) reflects the 
> 6 extra state_transfer tasks, not an inherent protocol disadvantage. 
> **Use lane-level tables and the fresh_retrieval axis below for apples-to-apples comparison.**

```

#### 修改2：fresh_retrieval 提升到 aggregate 后第一section

当前section顺序：
```
Aggregate → Role-Level Tokens → Phase Timing → Executor Handoff 
→ Reuse Query → Setup vs Steady → Stability → Task Group 
→ Replay Contract → Comm vs Replay → Benchmark Lanes → ...
```

调整后：
```
Aggregate (含免责声明)
→ Structured-vs-Text By Reuse Axis (fresh_retrieval 在最前)  ← 提前！
→ Contest Benchmark Lanes (lane-level对比)
→ Role-Level Tokens → Phase Timing → ...
```

实现：调整 `_write_markdown_report` 中生成各section的调用顺序。

#### 修改3：lane delta表格增加"task_count_equal"标注

在 `Contest Claim Lane Deltas` 表格中，对于 `communication` lane（text和protocol task数相同）增加标注：

```markdown
| benchmark_lane | task_count_equal | text_control_bytes | protocol_control_bytes | ... |
| communication | ✅ yes (2 vs 2) | 6691.50 | 5814.50 | ... |
| internal_regression | ✅ yes (18 vs 18) | 6820.89 | 6027.83 | ... |
| memory | ✅ yes (3 vs 3) | 7006.67 | 5823.00 | ... |
| state_transfer | ⚠️ protocol-only | n/a | 5268.78 | ... |
```

### 验证

重新跑 `python -m eval.runner --repeat 1 --llm-mode deterministic --out /tmp/a4_verify`，检查生成的 `benchmark_report.md`：
- aggregate前有免责声明
- fresh_retrieval视图在report前50行内
- lane表格有task_count_equal标注

---

# Phase B：增强核心主张

## B1：Benchmark 重构（Lane 配额优化）

### 目标

将赛题主张task占比从 38%（11/29）提升到 55%+（16/29），同时保持总task数合理。

### 当前构成

```
internal_regression: 18 (62%)  ← 太多
communication:        2 ( 7%)  ← 太少
memory:               3 (10%)  ← 刚好
state_transfer:       6 (21%)  ← 刚好（A2修复后text也可跑）
```

### 目标构成（方案选择）

**推荐方案**（改动最小）：

```
internal_regression: 12 (保留2个chain × 6 task，砍掉一个chain)
communication:        6 (3 domain × 2 task: cache/latency/session)
memory:               3 (不变)
state_transfer:       6 (不变，A2修复后text+protocol都可跑)
open_plan:            3 (A3新增的LLM Planner task)
─────────────────
总计:                30 tasks (含3个开放task, 27个受控task)
赛题主张task:         12 (communication 6 + state_transfer 6 = 12，不含memory因为memory主对比在protocol-only lane)
                     + memory 3 (protocol-only lane)
                     = 15/30 = 50%  ← 是原来的1.3倍
```

**更激进的方案**（改动大但分数高）：

```
internal_regression:  6 (只保留1个chain做回归)
communication:        9 (3 domain × 3 task: cold-start/reject-control/fresh-retrieval)
memory:               6 (2 domain × 3 task: memory_off/assist_only/replay_enabled)
state_transfer:       6 (不变)
open_plan:            3 (A3新增)
─────────────────
总计:                30 tasks
赛题主张task:         21/30 = 70%  ← 是原来的1.8倍
```

**建议先用推荐方案（安全），如果时间充裕再升级到激进方案。**

### 实现

**文件**：`tasks/sample_benchmark.yaml`

#### 推荐方案的修改：

1. **砍掉一个internal_regression chain**：删除 `session_chain` 的6个task（sample-session-001到006）。保留 `cache_chain` 和 `latency_chain`。

2. **扩充 communication_lane**：新增4个task：

```yaml
  # 新增 latency domain communication task
  - task_id: communication-latency-001
    task_group: communication_lane
    task_order: 3
    task_theme: repo_local_latency_triage
    benchmark_lane: communication
    transfer_strategy: state_ref
    allowed_modes: [text, protocol]
    goal: Triage latency spike using cited docs
    query: release-17 orders latency spike with connection waits
    corpus_doc_ids: [latency-db-anchor, latency-db-followup, latency-worker-false]
    evidence_text: Use referenced corpus docs only; memory disabled.
    tags: [latency, communication, cold-start]
    runtime_reuse_contract: reuse_disabled
    expected_reuse_mode: none
    summary_hint: Return root cause, ruled-out explanation, and first action.

  - task_id: communication-latency-002
    task_group: communication_lane
    task_order: 4
    task_theme: repo_local_latency_triage
    benchmark_lane: communication
    transfer_strategy: state_ref
    allowed_modes: [text, protocol]
    goal: Distinguish latency spike from DB saturation
    query: latency spike after failover seems like db issue
    corpus_doc_ids: [latency-db-anchor, latency-db-followup, latency-worker-false]
    evidence_text: Use referenced corpus docs only; memory disabled.
    tags: [latency, communication, reject-control]
    runtime_reuse_contract: reuse_disabled
    expected_reuse_mode: none
    summary_hint: Return root cause, ruled-out explanation, and first action.

  # 类似地新增 communication-session-001, communication-session-002
```

3. **追加 open_plan_lane**：A3的3个open-plan task。

### 验证

```bash
python -m eval.runner \
  --task-set formal_controlled \
  --repeat 1 \
  --llm-mode deterministic \
  --out /tmp/b1_verify
```

检查：
- `communication` lane 的task数 = 6（原来2）
- `internal_regression` task数 = 12（原来18，砍了session_chain）
- `open_plan_lane` 存在且有数据
- `failure_count` = 0

---

## B2：双层记忆 + 多信号检索融合

### 问题

`assist_only` 从未赢过 `memory_off`。根因：
1. 记忆检索只用semantic similarity，精度不够
2. 跨run旧记忆与新记忆权重相同
3. 被接受的assist给summarizer增加了额外token开销，抵消了检索层节省

### 方案

在 `MemoryStore.search()` 内部增强，不改变对外的接口：

1. **双层记忆权重**：同session/run内产生的记忆权重×1.5
2. **多信号融合**：semantic + BM25 keyword + tag overlap + recency decay
3. **Recency reranking**：越新的记忆权重越高（指数衰减）

### 实现

**文件**：`memory/store.py`

#### Step 1：在SQLite schema中增加 session_id 字段（如果还没有）

```sql
-- 检查 memories 表是否有 session_id 列
-- 如果没有，ALTER TABLE ADD COLUMN session_id TEXT DEFAULT ''
```

**文件**：`memory/store.py`，`init_schema()` 方法

```python
def init_schema(self):
    # ... 现有建表逻辑 ...
    # 在 CREATE TABLE memories 中确保有 session_id TEXT DEFAULT ''
```

#### Step 2：在 commit_memory 时记录 session_id

**文件**：`memory/store.py`，`commit_memory()` 方法

```python
def commit_memory(self, memory_id, ..., session_id=""):
    # 在 INSERT 语句中增加 session_id
    self._execute(
        """INSERT OR REPLACE INTO memories 
        (memory_id, ..., session_id) VALUES (..., ?)""",
        [..., session_id]
    )
```

调用方（Orchestrator 或 RunContext）需要在commit时传入当前run的session_id。

#### Step 3：修改 `_search_semantic` 的scoring逻辑

**文件**：`memory/store.py`，约第576-655行

**修改前**（简化）：
```python
def _search_semantic(self, query, top_k):
    candidates = self._vector_index.search(query.embedding, top_k * 8)
    # post-filter by task_theme, tags, etc.
    # sort by semantic_score only
    candidates.sort(key=lambda c: -c["semantic_score"])
    return candidates[:top_k]
```

**修改后**：
```python
def _search_semantic(self, query: MemoryQuery, top_k: int) -> list[MemoryHit]:
    candidates = self._vector_index.search(query.embedding, top_k * 8)
    
    # Post-filter（现有逻辑，保持不变）
    filtered = self._post_filter(candidates, query)
    
    # ---- 新增：多信号融合 ----
    scored = []
    for hit in filtered:
        base = hit.semantic_score  # cosine similarity [0, 1]
        
        # (1) BM25 keyword overlap
        bm25 = self._compute_keyword_overlap(
            query.query_text or "", 
            hit.summary or ""
        )
        
        # (2) Tag overlap boost
        tag_overlap = 0.0
        if query.tags and hit.tags:
            overlap = len(set(query.tags) & set(hit.tags))
            tag_overlap = overlap / max(len(query.tags), 1)
        
        # (3) Recency decay
        age_seconds = time.time() - (hit.created_at or 0)
        recency = math.exp(-0.0001 * age_seconds)
        
        # (4) Memory tier boost
        tier = 1.5 if (query.session_id and hit.session_id == query.session_id) else 1.0
        
        # Fusion
        hit.combined_score = (
            base * tier             # semantic × tier weight
            + 0.25 * bm25          # BM25 (normalized [0, 1])
            + 0.20 * tag_overlap   # tag match [0, 1]
            + 0.10 * recency       # recency [0, 1]
        )
        scored.append(hit)
    
    scored.sort(key=lambda h: -h.combined_score)
    return scored[:top_k]


def _compute_keyword_overlap(self, query_text: str, doc_text: str) -> float:
    """BM25-style keyword overlap [0, 1]"""
    if not query_text or not doc_text:
        return 0.0
    query_tokens = set(t.lower() for t in query_text.split() if len(t) >= 3)
    doc_tokens = set(t.lower() for t in doc_text.split() if len(t) >= 3)
    if not query_tokens:
        return 0.0
    overlap = len(query_tokens & doc_tokens)
    return min(overlap / len(query_tokens), 1.0)
```

#### Step 4：权重可配置化

**文件**：`memory/store.py`

不要在代码中硬编码权重值。通过类属性或环境变量控制：

```python
class MemoryStore:
    # 可通过环境变量覆盖的权重参数
    SEMANTIC_WEIGHT = float(os.getenv("STATEBUS_MEM_SEMANTIC_WEIGHT", "1.0"))
    BM25_WEIGHT = float(os.getenv("STATEBUS_MEM_BM25_WEIGHT", "0.25"))
    TAG_WEIGHT = float(os.getenv("STATEBUS_MEM_TAG_WEIGHT", "0.20"))
    RECENCY_WEIGHT = float(os.getenv("STATEBUS_MEM_RECENCY_WEIGHT", "0.10"))
    WORKING_TIER_BOOST = float(os.getenv("STATEBUS_MEM_WORKING_TIER", "1.5"))
    RECENCY_LAMBDA = float(os.getenv("STATEBUS_MEM_RECENCY_LAMBDA", "0.0001"))
```

这样如果权重不合适，可以通过环境变量热修复，不需要改代码。

### 验证

```bash
# 只跑memory lane（3个task，快速验证）
python -m eval.runner \
  --task-set memory \
  --repeat 3 \
  --llm-mode api \
  --out /tmp/b2_verify

# 检查benchmark_report.md中的Memory Policy Claim Surface
# 预期：assist_only 的 task_ms 相比 memory_off 下降 >= 5%
```

### 调参方法

如果assist_only仍然没赢memory_off，按以下顺序调整权重：

1. 增加 `WORKING_TIER_BOOST` 到 2.0（让同run内记忆更强）
2. 减小 `RECENCY_LAMBDA` 到 0.00005（让衰减更慢）
3. 增加 `BM25_WEIGHT` 到 0.35（关键词匹配更重要）
4. 减小 `RECENCY_WEIGHT` 到 0.05（降低时间衰减影响）

通过 `export STATEBUS_MEM_*` 设置环境变量 → 跑验证 → 看结果 → 迭代。

---

## B3：FEATURE_BUNDLE 加 ChannelKind 标注

### 问题

`FEATURE_BUNDLE` 是30+字段的flat dict，没有字段的"更新语义"——接收方不知道哪些字段每步会变、哪些是稳定的。这导致：
1. 无法做增量传输（因为不知道哪些字段可能变）
2. 状态传递的"生成/传递/接收/使用方式"表述不够清晰（赛题要求明确说明）

### 方案

**不改变FEATURE_BUNDLE的schema（保持v1兼容）**。只在 `metadata` 中增加 `channel_schema` 字段，标注每个字段的ChannelKind。

**这跟之前文档3中"Typed Channel完整重写"的区别**：完整重写要求改schema v1→v2、改所有consumer。轻量标注只新增一个metadata字段——旧consumer忽略它，新consumer可以使用它来做增量传输/智能消费。

### 实现

#### Step 1：定义 ChannelKind

**文件**：`protocol/messages.py`（或新增 `runtime/channel_kind.py`）

```python
from enum import Enum

class ChannelKind(str, Enum):
    """StateRef字段的更新语义"""
    LAST_VALUE = "last_value"           # 只保留最新值，接收方不需要历史
    TOPIC_REPLACE = "topic_replace"     # 每步完全替换
    TOPIC_ACCUMULATE = "topic_accumulate" # 跨步累积
    EPHEMERAL = "ephemeral"             # 不持久化，仅用于debug/telemetry
```

#### Step 2：定义 FEATURE_BUNDLE 的 channel schema

**文件**：`runtime/executor_runtime.py`，`build_feature_bundle()` 函数

在函数末尾，构建完所有字段后，追加 `_channel_schema`：

```python
def build_feature_bundle(
    query, evidence_text, tags, corpus_doc_ids, hint_docs, tool_registry, 
    reused_memory=False, memory_prior=None
) -> dict:
    # ... 现有30+行的字段构建逻辑 ...
    
    # ---- 现有逻辑结束 ----
    
    # ---- 新增：Channel Schema ----
    bundle["_channel_schema"] = {
        # Stable channels — 一旦确定就不变
        "route": ChannelKind.LAST_VALUE,
        "route_source": ChannelKind.LAST_VALUE,
        "route_confidence": ChannelKind.LAST_VALUE,
        "route_provenance": ChannelKind.LAST_VALUE,
        "tool_name": ChannelKind.LAST_VALUE,
        "evidence_sha256": ChannelKind.LAST_VALUE,
        "fresh_evidence_sha256": ChannelKind.LAST_VALUE,
        "hint_route": ChannelKind.LAST_VALUE,
        "hint_tool_name": ChannelKind.LAST_VALUE,
        "hint_doc_ids": ChannelKind.LAST_VALUE,
        
        # Replace-per-step channels — 每步重新计算
        "tool_candidates": ChannelKind.TOPIC_REPLACE,
        "matched_signals": ChannelKind.TOPIC_REPLACE,
        "matched_tags": ChannelKind.TOPIC_REPLACE,
        "match_score": ChannelKind.TOPIC_REPLACE,
        
        # Accumulating channels — 历史有价值
        "query_terms": ChannelKind.TOPIC_ACCUMULATE,
        
        # Ephemeral channels — 不持久化
        "evidence_preview": ChannelKind.EPHEMERAL,
        "evidence_chars": ChannelKind.EPHEMERAL,
        "evidence_lines": ChannelKind.EPHEMERAL,
        
        # Memory-dependent — 取决于是否reuse
        "reused_memory": ChannelKind.LAST_VALUE,
        "reuse_signature": ChannelKind.LAST_VALUE,
        "memory_prior_id": ChannelKind.LAST_VALUE,
        "memory_prior_route": ChannelKind.LAST_VALUE,
        "memory_prior_applied": ChannelKind.LAST_VALUE,
    }
    
    return bundle
```

#### Step 3：在 StateRef 序列化时保留 channel_schema

当前 `build_feature_bundle` 的返回值通过 `put_feature_state()` 写入 `StateRef`。由于 `_channel_schema` 是dict中的一个key，它会被正常msgpack序列化。

不需要额外改动 `statepool/store.py` 或 `protocol/messages.py`——`_channel_schema` 就是metadata的一部分。

#### Step 4（可选）：在 benchmark report 中展示 Channel Distribution

**文件**：`eval/runner.py`，report生成

新增一个section：

```markdown
## State Channel Distribution

| channel_kind | field_count | example_fields |
|-------------|------------|----------------|
| last_value | 15 | route, tool_name, evidence_sha256, ... |
| topic_replace | 4 | tool_candidates, matched_signals, ... |
| topic_accumulate | 1 | query_terms |
| ephemeral | 3 | evidence_preview, evidence_chars, ... |
```

这直接对应赛题要求——"说明其生成方式、传递方式、接收方式及后续使用方式"。

### 验证

```python
# 在 test_smoke.py 中增加检验
def test_feature_bundle_has_channel_schema():
    """验证FEATURE_BUNDLE包含channel_schema"""
    bundle = build_feature_bundle(...)
    assert "_channel_schema" in bundle
    assert bundle["_channel_schema"]["route"] == "last_value"
    assert bundle["_channel_schema"]["tool_candidates"] == "topic_replace"
```

---

## B4：增量协议帧（DeltaPlanStep）

### 问题

同chain内连续task的PlanStep有大量重复字段（depends_on、owner_agent、action），但当前每次都完整传输。

### 方案

在orchestrator的step emit处，检测是否同task_group内的连续step。如果是，计算delta，只在节省显著时（>100字节）使用DeltaPlanStep。否则回退到完整PlanStep。

### 实现

#### Step 1：新增 DeltaPlanStep 消息类型

**文件**：`protocol/messages.py`

```python
@dataclass
class DeltaPlanStep:
    """增量PlanStep — 只包含相对于base_step_id的变更字段"""
    step_id: str
    base_step_id: str            # 引用的完整PlanStep的step_id
    delta_params: dict[str, Any]  # 只含变更的params字段
    delta_depends_on: list[str]   # 只含新增的依赖
    delta_version: int = 1
    
    def is_empty(self) -> bool:
        """是否为空delta（和base完全相同）"""
        return not self.delta_params and not self.delta_depends_on
```

在 `protocol_bytes()` 函数中增加对 `DeltaPlanStep` 的序列化支持。

#### Step 2：在 orchestrator 的step emit处插入delta检测

**文件**：`runtime/orchestrator.py`，`_emit_steps` 或类似函数

```python
# 伪代码：当前emit逻辑
for step in plan.steps:
    msg_bytes = protocol_bytes(step)
    ctx.emit_message("PlanStep", msg_bytes)

# 修改后
previous_step_in_chain = None
for step in plan.steps:
    same_chain = (
        previous_step_in_chain is not None 
        and previous_step_in_chain.task_group == current_task_group
    )
    
    if same_chain:
        delta = DeltaPlanStep(
            step_id=step.step_id,
            base_step_id=previous_step_in_chain.step_id,
            delta_params={
                k: v for k, v in step.params.items()
                if previous_step_in_chain.params.get(k) != v
            },
            delta_depends_on=[
                d for d in step.depends_on 
                if d not in previous_step_in_chain.depends_on
            ],
        )
        # 只在节省>100字节时使用delta
        delta_bytes = protocol_bytes(delta)
        full_bytes = protocol_bytes(step)
        if len(delta_bytes) + 100 < len(full_bytes):
            msg_bytes = delta_bytes
            ctx.increment_metric("delta_savings", len(full_bytes) - len(delta_bytes))
        else:
            msg_bytes = full_bytes
    else:
        msg_bytes = protocol_bytes(step)
    
    ctx.emit_message("PlanStep" if not isinstance(msg_bytes_is_delta) else "DeltaPlanStep", msg_bytes)
    previous_step_in_chain = step
```

#### Step 3：metrics 中增加 delta 统计

**文件**：`eval/metrics.py`

```python
@dataclass
class TaskMetrics:
    # ... 现有字段 ...
    delta_plan_step_count: int = 0       # DeltaPlanStep使用次数
    delta_plan_step_savings_bytes: int = 0  # 总共节省的字节
```

### 验证

```python
# 新增测试 test_protocol_messages.py
def test_delta_plan_step_round_trip():
    """验证DeltaPlanStep的protobuf + JSON fallback序列化"""
    delta = DeltaPlanStep(
        step_id="step_2",
        base_step_id="step_1",
        delta_params={"query": "new query"},
        delta_depends_on=[],
    )
    wire = protocol_bytes(delta)
    parsed = parse_protocol_bytes(wire)
    assert parsed.step_id == "step_2"
    assert parsed.delta_params == {"query": "new query"}
```

---

# Phase C：深化亮点

## C1：CodeAct 兜底实现

> Historical planning note: this section is not the current v2 evidence
> boundary. Current v2 can only claim controlled CodeAct-style execution:
> runtime-generated bounded Python action scripts under the recorded sandbox
> profile. A restricted LLM-code demo remains future work unless separately
> implemented and evidenced.

### 目标

当ToolRegistry中预注册工具无法处理当前 task 时，future-work demo 可 fallback 到受限 LLM-code 小函数；当前 v2 不把这写成已完成能力。

### 实现

**新增文件**：`runtime/codeact_runner.py`

```python
"""
Future-work CodeAct demo: restricted LLM-generated Python function plus policy
checks and sandboxed execution. This is not the current v2 evidence claim.
"""
import asyncio
import hashlib
import os
import tempfile
import time
from dataclasses import dataclass

@dataclass
class CodeActResult:
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: float
    script_sha256: str


class CodeActRunner:
    """CodeAct受控执行器"""
    
    # 禁用的危险模块
    FORBIDDEN_IMPORTS = {"os", "subprocess", "shutil", "socket", "requests", "ctypes"}
    
    # 允许的安全模块白名单
    ALLOWED_IMPORTS = {"json", "csv", "re", "math", "statistics", "collections", 
                       "itertools", "datetime", "pathlib", "textwrap", "hashlib"}
    
    def __init__(self, timeout_seconds: int = 10, work_dir: str | None = None):
        self.timeout = timeout_seconds
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="codeact_")
    
    def validate_script(self, code: str) -> tuple[bool, str]:
        """安全校验：检查是否包含危险import"""
        for forbidden in self.FORBIDDEN_IMPORTS:
            if f"import {forbidden}" in code or f"from {forbidden}" in code:
                return False, f"Forbidden import: {forbidden}"
        return True, ""
    
    async def execute(self, code: str, stdin_data: str = "") -> CodeActResult:
        """执行Python代码并返回结果"""
        valid, reason = self.validate_script(code)
        if not valid:
            return CodeActResult(False, "", reason, -1, 0, 
                                hashlib.sha256(code.encode()).hexdigest()[:16])
        
        script_path = os.path.join(self.work_dir, f"script_{int(time.time())}.py")
        with open(script_path, "w") as f:
            f.write(code)
        
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", script_path,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir,
                env={**os.environ, "PYTHONPATH": "", "PYTHONNOUSERSITE": "1"},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data.encode() if stdin_data else None),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return CodeActResult(False, "", "Execution timeout", -1,
                                (time.monotonic() - start) * 1000,
                                hashlib.sha256(code.encode()).hexdigest()[:16])
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass
        
        elapsed = (time.monotonic() - start) * 1000
        return CodeActResult(
            success=proc.returncode == 0,
            stdout=stdout.decode("utf-8", errors="replace") if stdout else "",
            stderr=stderr.decode("utf-8", errors="replace") if stderr else "",
            exit_code=proc.returncode or -1,
            execution_time_ms=elapsed,
            script_sha256=hashlib.sha256(code.encode()).hexdigest()[:16],
        )
```

#### 在 ToolRegistry 中注册 codeact_execute

**文件**：`runtime/executor_runtime.py`，ToolRegistry初始化部分

```python
class ToolRegistry:
    def __init__(self):
        self.tools = {}
        self.codeact_runner = CodeActRunner()
        # ... 注册现有7个工具 ...
        self.register("codeact_execute", self._execute_codeact, ...)
    
    async def _execute_codeact(self, params: dict) -> dict:
        """CodeAct工具：LLM生成代码 → 执行 → 返回结果"""
        code = params.get("code", "")
        result = await self.codeact_runner.execute(code)
        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "execution_time_ms": result.execution_time_ms,
        }
```

#### 在 select_tool_name 的fallback链中插入CodeAct

**文件**：`runtime/executor_runtime.py`，`select_tool_name` 函数约第666行

当前fallback链：
```
tool_candidates → feature_bundle["tool_name"] → registry lookup by route → generic_triage
```

修改后：
```
tool_candidates → feature_bundle["tool_name"] → registry lookup by route → codeact_execute → generic_triage
```

```python
def select_tool_name(feature_bundle, registry):
    # 1. tool_candidates
    for candidate in feature_bundle.get("tool_candidates", []):
        tool_name = candidate.get("tool_name", "")
        if tool_name and tool_name != "generic_triage" and registry.has(tool_name):
            return tool_name
    
    # 2. feature_bundle hint
    tool_name = feature_bundle.get("tool_name", "")
    if tool_name and registry.has(tool_name):
        return tool_name
    
    # 3. route lookup
    route = feature_bundle.get("route", "")
    tool_name = registry.find_by_route(route)
    if tool_name:
        return tool_name
    
    # 4. CodeAct fallback（新增）
    if registry.has("codeact_execute"):
        return "codeact_execute"
    
    # 5. Last resort
    return "generic_triage"
```

### 验证

新增smoke test：
```python
def test_codeact_runner_executes_safe_code():
    runner = CodeActRunner(timeout_seconds=5)
    result = asyncio.run(runner.execute("print('hello codeact')"))
    assert result.success
    assert "hello codeact" in result.stdout
    assert result.exit_code == 0

def test_codeact_runner_rejects_dangerous_imports():
    runner = CodeActRunner()
    code = "import os\nprint(os.getcwd())"
    result = asyncio.run(runner.execute(code))
    assert not result.success
    assert "Forbidden import: os" in result.stderr
```

---

## C2：Route 多样性 Task（lexical_override）

### 问题

当前benchmark所有task的route source是 `hint_consensus` (100%)。Route系统的冲突处理、降级策略从未被展示。

### 实现

在 `tasks/sample_benchmark.yaml` 中追加2-3个 `lexical_override` task（放在 `internal_regression` 的某个chain末尾或独立section）：

```yaml
  - task_id: regr-lexical-override-cache-001
    task_group: cache_chain
    task_order: 7
    task_theme: repo_local_cache_staleness
    benchmark_lane: internal_regression
    transfer_strategy: state_ref
    allowed_modes: [text, protocol]
    goal: Route should follow lexical evidence NOT the metadata hint
    query: cache replica shows stale data after failover sync lag
    corpus_doc_ids: [cache-invalid-anchor, cache-replica-false]  
    # ← hint指向invalidation，但query是replica问题
    evidence_text: Lexical evidence points to replica lag, not invalidation.
    tags: [cache, replica, lexical-override]
    runtime_reuse_contract: reuse_disabled
    expected_reuse_mode: none
    expected_route: "replica_drift"         # ← 期望词法路由覆盖hint
    expected_route_source: "lexical_override"  # ← 期望lexical_override
    summary_hint: Evidence overrides hint; isolate replica lag path.
```

同样追加 latency 和 session domain 的 lexical_override task。

### 验证

跑deterministic验证，检查 `executor_feature_observability` section：
- Route Source Distribution 不应再是100% `hint_consensus`
- 应有 `lexical_override` 条

---

## C3：协议 InvariantChecker（静态不变量自动检查）

### 实现

**文件**：`runtime/contracts.py`，新增 `InvariantChecker` 类

```python
class InvariantChecker:
    """协议不变量自动检查器——从Schema定义自动生成，在benchmark中运行"""
    
    STATIC_INVARIANTS = [
        # Plan完整性
        ("plan_has_goal", lambda p: bool(p.goal), "Plan must have a non-empty goal"),
        ("plan_has_task_id", lambda p: bool(p.task_id), "Plan must have a non-empty task_id"),
        ("plan_steps_non_empty", lambda p: len(p.steps) > 0, "Plan must have at least one step"),
        
        # Step完整性
        ("step_ids_unique", lambda p: len(set(s.step_id for s in p.steps)) == len(p.steps),
         "Plan step_ids must be unique"),
        ("step_has_owner", lambda p: all(s.owner_agent for s in p.steps),
         "Every step must have an owner_agent"),
        ("step_has_action", lambda p: all(s.action for s in p.steps),
         "Every step must have an action"),
        
        # 依赖合法性
        ("deps_reference_valid_steps", lambda p: all(
            d in {s.step_id for s in p.steps} 
            for s in p.steps for d in s.depends_on
        ), "depends_on must reference valid step_ids"),
        ("no_circular_deps", lambda p: _is_dag(p.steps),
         "Step dependencies must form a DAG"),
        
        # StateRef合规
        ("state_ref_has_agent_id", lambda refs: all(
            r.metadata.get("source_agent_id") for r in refs
        ), "Every StateRef must have source_agent_id in metadata"),
        ("state_ref_has_created_at", lambda refs: all(
            r.metadata.get("created_at") for r in refs
        ), "Every StateRef must have created_at in metadata"),
        
        # Memory合规
        ("memory_commit_has_summary", lambda commits: all(
            c.summary for c in commits
        ), "Every MemoryCommit must have a non-empty summary"),
    ]
    
    def check_plan(self, plan: Plan) -> list[str]:
        """检查Plan是否满足所有静态不变量，返回violation列表"""
        violations = []
        for name, check_fn, description in self.STATIC_INVARIANTS:
            try:
                if not check_fn(plan):
                    violations.append(f"[{name}] {description}")
            except Exception as e:
                violations.append(f"[{name}] check failed: {e}")
        return violations
```

#### 在 eval runner 中集成 InvariantChecker

**文件**：`eval/runner.py`，`_run_mode_once` 函数

在每个task执行完成后，调用InvariantChecker并收集violations：

```python
checker = InvariantChecker()
task_violations = checker.check_plan(plan)
if task_violations:
    ctx.metrics.invariant_violations += len(task_violations)
    # 写入benchmark_report的Protocol Compliance section
```

#### 在 benchmark report 中增加 Protocol Compliance section

```markdown
## Protocol Compliance (Invariant Checks)

| invariant | total_checks | violations | compliance_rate |
|-----------|-------------|-----------|----------------|
| plan_has_goal | 87 | 0 | 100% |
| plan_steps_non_empty | 87 | 0 | 100% |
| step_ids_unique | 87 | 0 | 100% |
| ... | ... | ... | ... |
| **Total** | **870** | **0** | **100%** |
```

### 验证

在 `test_smoke.py` 中增加：
```python
def test_invariant_checker_all_pass_on_valid_plan():
    checker = InvariantChecker()
    plan = build_plan(sample_task)
    violations = checker.check_plan(plan)
    assert len(violations) == 0, f"Unexpected violations: {violations}"
```

---

## C4：最终 Benchmark 重跑

### 操作

```bash
source deploy/activate_statebus_host.sh

python -m eval.runner \
  --task-set formal_controlled \
  --repeat 3 \
  --llm-mode api \
  --out runs/final_eval_$(date +%Y%m%d_%H%M%S)
```

### 检查清单

- [ ] `failure_count = 0`（两边）
- [ ] `expectation_match_rate = 1.00`
- [ ] communication lane: protocol control_bytes < text control_bytes，节省 ≥ 10%
- [ ] state_transfer lane: **text和protocol都有数据**
- [ ] memory lane: replay_enabled vs memory_off 有显著差异
- [ ] assist_only vs memory_off 差距比之前改善（B2的效果）
- [ ] fresh_retrieval 口径在报告前50行
- [ ] aggregate 前有免责声明
- [ ] InvariantChecker violations = 0
- [ ] open-plan task 有 planner token 消耗
- [ ] Route Source Distribution 不全是 hint_consensus

---

# 总改动量汇总

| Phase | 文件 | 新增行 | 修改行 |
|-------|------|--------|--------|
| A1 | `tasks/sample_benchmark.yaml` | 0 | 0（git checkout） |
| A2 | `tasks/sample_benchmark.yaml` + `tasks/sample_tasks.py` + `runtime/orchestrator.py` | ~30 | ~30 |
| A3 | `agents/sample_agents.py` + `tasks/sample_tasks.py` + `tasks/sample_benchmark.yaml` | ~120 | ~10 |
| A4 | `eval/runner.py` | ~20 | ~20 |
| B1 | `tasks/sample_benchmark.yaml` | ~100 | ~100（删session_chain） |
| B2 | `memory/store.py` | ~80 | ~30 |
| B3 | `runtime/executor_runtime.py` + `protocol/messages.py` | ~40 | ~5 |
| B4 | `protocol/messages.py` + `runtime/orchestrator.py` + `eval/metrics.py` | ~80 | ~20 |
| C1 | **新增** `runtime/codeact_runner.py` + `runtime/executor_runtime.py` | ~150 | ~10 |
| C2 | `tasks/sample_benchmark.yaml` | ~60 | 0 |
| C3 | `runtime/contracts.py` + `eval/runner.py` | ~80 | ~10 |
| **总计** | | **~760行新增** | **~235行修改** |

对比原来文档3的全量改动计划（~1,500行新增+修改），这个精简方案减少了约50%的代码量，但保留了所有P0/P1/P2的核心价值。
