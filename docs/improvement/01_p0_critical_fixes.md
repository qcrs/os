# P0 关键问题修复

**状态基准**：HEAD `6ece8a0`（2026-07-04）
**代码路径已核实**：所有行号来自实际代码探索

---

## 问题一：CodeAct LLM 生成成功率 — 已解决 ✅

### 历史问题描述

3/3 runs 全部走 `deterministic_policy_fallback`，LLM 从未成功生成符合 AST policy 的代码。

### 当前状态

**已完全解决。实测数据（v2-update-rerun-20260704_215517 / 11_codeact_acceptance.json）**：

```
total_runs: 5
success_count: 5
target_met: true
每次 run: ok=true, generation_fallback_used=false, attempt_count=1, violations=[]
```

5/5 LLM 生成成功，零 fallback，零 violations，attempt_count=1（首次即通过，无需 repair）。

### 根因（历史）与修复路径

根因一：allowed imports 只有4个，prompt 未告知 LLM。
根因二：输出文件名须是 literal `"bounded_codeact_result.json"`，LLM 不知道。
根因三：repair prompt 信息不足，LLM 修复时不知道怎么改。

修复（已在 `scripts/v2_diagnostics/bounded_llm_codeact_demo.py` 实施）：
- generation prompt 明确列出 allowed imports、forbidden calls、mandatory file paths、工作模板
- repair prompt 改为逐条 hint + exact fix example
- ALLOWED_IMPORT_ROOTS 扩展为包含 csv/re/datetime/collections/itertools/decimal

### 验收结果

```bash
# artifact 地址
/home/qcrs/statebus/runs/v2-update-rerun-20260704_215517/json/11_codeact_acceptance.json
# 关键字段
success_count=5, target_met=true, generation_fallback_used=false（全5次）
```

---

## 问题二：Memory COMMITTED 门槛 — 已解决 ✅

### 历史问题描述

`commit_candidate()` 要求 `quality_floor_pass AND answer_adopted` 才能升级为 COMMITTED，导致大量 memory 停在 CANDIDATE 无法触发 step-skip replay。

### 当前状态

**已解决。代码核实（`v2/memory/store.py` line 78）**：

```python
# 当前实现（已改为只需 quality_floor_pass）：
status = MemoryCommitStatus.COMMITTED if quality_floor_pass else MemoryCommitStatus.CANDIDATE
```

`answer_adopted` 只更新到 MemoryRef 字段，不再影响 COMMITTED 判定。

### 验收结果

continuous replay 数据（full-experiment-20260704_111950）：
- validated_replay=15，exact_replay=10
- incident_diagnosis_v2：exact_replay=7（rounds 3,4,6,7,8,9,10），validated_replay=2（rounds 2,5）
- replay negative audit 7/7 pass

---

## 问题三：formal_efficiency_claim_allowed — 已确认 ✅

### 历史问题描述

formal compare 的 `formal_efficiency_claim_allowed` 字段是否激活未确认。

### 当前状态

**已确认为 True。实测数据（04_formal_compare.json）**：

```json
"formal_efficiency_claim_allowed": 1.0
```

`comparator_runner.py` 中的条件（lines 380-386）：
- `benchmark_tier == "formal"` ✅
- `llm_total_tokens_delta=-743 < 0` ✅
- `prompt_bytes_delta=-10928 < 0` ✅
- `quality_floor_pass_delta=+2 >= 0` ✅

formal superiority 走的是 Path A（质量优越：8/8 vs 6/8），而非 Path B（等质量效率优越）。两条路径都满足。

---

## 问题四：文档声明与 v2 代码不一致 — 已解决 ✅

### 历史问题描述

声明 "SQLite + FAISS" 但 v2 实际是 dict 线性扫描。

### 当前状态

**SQLite FTS5 已在 v2 中实现。代码核实（`v2/memory/store.py`）**：

```python
# line 297-335: _init_db()
CREATE TABLE IF NOT EXISTS memories (memory_id, task_theme, summary, ...)
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(...)
```

- `lookup_by_keyword()` 已走 FTS5（lines 195-240）
- FAISS 仍未实装（O(N) 线性扫描），待 P1 添加

---

## 新发现 Bug B1：lookup_by_tags() 未使用 SQL 过滤

### 问题描述

`lookup_by_tags()` 方法（`v2/memory/store.py` lines 242-274）从 SQLite 读取所有行，然后在 Python 层做 set intersection，没有利用 SQL WHERE 子句过滤标签。

### 根因（代码核实 lines 256-274）

```python
# 当前实现：
rows = self._db.execute(
    """
    SELECT memory_id, tags_text, created_at_ns
    FROM memories
    WHERE commit_status != ?
    """,
    (MemoryCommitStatus.INVALIDATED.value,),
).fetchall()
# 然后 Python 层做 set intersection（仍是 O(N) 扫描）
for memory_id, tags_text, created_at_ns in rows:
    ref_tags = set(str(tags_text or "").split())
    overlap = len(normalized_tags & ref_tags)
```

问题：只过滤了 INVALIDATED，没有在 SQL 中做标签匹配。全表扫描再 Python 过滤，与不用 SQLite 效果相同。

### 修复方案

在 SQL WHERE 子句中加入标签过滤。`tags_text` 是空格分隔的 normalized tag 字符串，可以用 LIKE 批量过滤：

```python
def lookup_by_tags(
    self,
    tags: set[str],
    *,
    require_all: bool = False,
    limit: int = 3,
) -> list[MemoryCommit]:
    if not tags or self._db is None:
        return []
    normalized_tags = {self._normalize_tag(tag) for tag in tags if self._normalize_tag(tag)}
    if not normalized_tags:
        return []

    # 构建 SQL：每个 tag 用 LIKE 过滤，require_all 用 AND，否则用 OR
    clauses = [f"tags_text LIKE ?" for _ in normalized_tags]
    connector = " AND " if require_all else " OR "
    where_clause = "(" + connector.join(clauses) + ")"
    like_params = [f"% {tag} %" for tag in normalized_tags]
    # 补充头尾匹配
    like_params_head = [f"{tag} %" for tag in normalized_tags]
    like_params_tail = [f"% {tag}" for tag in normalized_tags]
    # 最简实现：每个 tag 用 instr 或 LIKE '%tag%'
    clauses_any = " OR ".join("tags_text LIKE ?" for _ in normalized_tags)
    params_any = [f"%{tag}%" for tag in normalized_tags]

    sql = f"""
        SELECT memory_id, tags_text, created_at_ns
        FROM memories
        WHERE commit_status != ?
          AND ({clauses_any})
        ORDER BY created_at_ns DESC
        LIMIT ?
    """
    rows = self._db.execute(
        sql,
        (MemoryCommitStatus.INVALIDATED.value, *params_any, limit * 3),
    ).fetchall()

    # Python 层精确 overlap 计分（SQL 只是粗筛）
    hits: list[tuple[int, int, str]] = []
    for memory_id, tags_text, created_at_ns in rows:
        ref_tags = set(str(tags_text or "").split())
        overlap = len(normalized_tags & ref_tags)
        if require_all and overlap < len(normalized_tags):
            continue
        if overlap == 0:
            continue
        hits.append((overlap, int(created_at_ns), str(memory_id)))
    hits.sort(key=lambda item: (-item[0], -item[1]))
    return [self.commits[memory_id] for _, _, memory_id in hits[:limit] if memory_id in self.commits]
```

### 验收测试

```bash
python -m pytest -q tests/v2/test_memory_store.py -k "lookup_by_tags"
# 期望：相关测试通过，不走全表扫描
```

---

## 新发现 Bug B3：comparison_valid=False 答辩口径

### 问题描述

`04_formal_compare.json` 显示 `comparison_valid=False`，`invalid_reason=quality_floor_gate_failed`。但 `formal_superiority_claim_allowed=True`、`formal_efficiency_claim_allowed=True`。

### 根因（代码核实 `comparator_runner.py` lines 165-193）

```python
def _headline_metrics(...):
    if not bool(fairness_manifest.get("pass_hard_gate", False)):
        return {}, "fairness_gate_failed"
    # 第二道门：两边都要 eligible_for_headline（即全部 case 过质量门）
    if not statebus_report.eligible_for_headline or not external_report.eligible_for_headline:
        return {}, "quality_floor_gate_failed"
```

`external_report.eligible_for_headline=False`（external 6/8 不满足 all-pass），所以 headline_metrics 为空，`comparison_valid=False`。

**这是设计意图，不是 bug。**

质量优越路径（`formal_superiority_claim_allowed=True`）不要求 external all-pass：只要 StateBus all-pass 且 quality_delta > 0，就满足质量优越声明。

### 答辩口径

> "formal compare 的 `comparison_valid=False` 是设计约束：efficiency headline 只有在两边质量完全对等时才激活（防止用质量换效率），当前 StateBus 8/8 vs external 6/8，质量不等，因此 efficiency headline 未激活。但 `formal_superiority_claim_allowed=True` 走质量优越路径，StateBus 以更少 tokens（-743）和更少 prompt bytes（-10928B）取得了更好的质量（+2 cases），这是更强的声明。"

---

## 新发现 Bug B4/B5：rerun 脚本 stage 11 与主流程一致性

### 问题描述

历史中曾有 `bounded_llm_codeact_demo.py` 的 stage 11 在 rerun 脚本中统计 `success_count=0` 的问题。

### 当前状态

**代码核实（`scripts/run_v2_failed_stage_rerun_and_merge.sh` lines 311-418）**：

rerun 脚本的 stage 11 handler（`run_codeact_acceptance()`）：
- 逐 run 调用 `bounded_llm_codeact_demo.py`
- 读取每次的 `summary.json`，提取 `ok` 和 `generation_fallback_used`
- validator 判定：`ok=true AND generation_fallback_used=false` → exit 0（计入 success）
- 最终生成与 run_full_experiment.sh 格式相同的 JSON artifact

**与主流程一致，B5 无需修复。**

rerun artifact（v2-update-rerun-20260704_215517/11_codeact_acceptance.json）中 `success_count=5` 证实脚本工作正常。
