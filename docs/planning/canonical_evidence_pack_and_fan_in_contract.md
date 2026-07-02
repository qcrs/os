# Canonical Evidence Pack And Fan-in Contract

日期：2026-06-26  
状态：`v2` 子合同草案  
作用：定义多路 Retriever 输出如何 deterministic 地合并、去重、排序并组装成统一 evidence pack。

---

## 1. 目标

这份合同要解决：

1. 多个 Retriever 返回不同形式证据时如何合并
2. 什么算重复证据
3. 什么算冲突证据
4. 最终给 Executor / Summarizer 的统一输入长什么样
5. 证据预算如何控制

---

## 2. 为什么不把它做成新 Agent

Fan-in 看起来像一个“第五个智能体”，但不应该这么做。

原因：

1. 它本质上是 deterministic runtime logic
2. 如果再加一个 LLM merge agent，会把可验证 merge 逻辑再次变成黑盒
3. 这部分更像 `evidence_fuser.py` 或 `data_prep` 阶段

因此：

- `v2` 不新增 `Fusion Agent`

---

## 3. 输入来源

建议的 3 类 Retriever：

1. `Lexical Retriever`
2. `Semantic Retriever`
3. `Table Retriever`

这里的“异构”体现在能力差异，而不是三个同质 worker 并发乱搜。

当前冻结语境下，首版 formal benchmark 默认围绕财报 / 经营数据分析任务家族，因此：

1. `Table Retriever` 与 `Semantic Retriever` 是首轮主路径
2. `Lexical Retriever` 主要承担实体、季度、指标别名与 route hint 补强

### 3.1 Lexical Retriever

适合：

1. 关键词强约束
2. 精准命名实体
3. 路线 hint 补全

### 3.2 Semantic Retriever

适合：

1. 长文语义相关段
2. 背景原因
3. 解释性上下文

### 3.3 Table Retriever

适合：

1. 数值
2. 表格字段
3. 单元格级 hard facts

---

## 4. 合并策略总原则

Fan-in 采用三层漏斗。

### 4.1 第一层：同模态内去重

分别对：

1. text span
2. table cell
3. metadata hint

做各自的去重。

### 4.2 第二层：跨模态优先级排序

建议优先级：

1. `hard_facts`
2. `structured_evidence`
3. `semantic_context`
4. `lexical_hints`

### 4.3 第三层：组装 canonical evidence pack

输出一个统一的、可预算裁剪的结构。

### 4.4 文本相关候选采用 RRF，硬事实不采用

这部分是 `v2` 当前推荐的确定性策略。

1. `table_cell_fact` / `hard_facts`
   - 不参与 RRF 混排
   - 先按主键去重，再按稳定主键排序
   - 在 budget 允许时优先保留
2. `text_span_context`
   - 对 lexical/semantic 两路召回结果按 rank 做 RRF
3. `route_tool_hint`
   - 可按低权重 RRF 或规则分排序

推荐公式：

```text
rrf_score = sum(1 / (k + rank_i))
```

其中：

1. `k` 推荐固定为 `60`
2. 只使用 rank，不使用原始相似度绝对值
3. 同分时必须按稳定 tiebreak key 排序

---

## 5. 同模态去重规则

### 5.1 文本 span 合并

只在满足以下条件时允许区间合并：

1. 同一 `source_doc_hash`
2. 同一 `canonical_text_id`
3. 同一 `extractor_version`

此时可用经典 interval merge。

### 5.2 表格单元格去重

主键建议：

```text
source_doc_hash + table_id + sheet_name + row_idx + col_idx + extractor_version
```

### 5.3 metadata hint 去重

对 route/tool/tag/doc_id 之类 hint，可按规范化 key 去重：

```text
hint_type + normalized_value
```

---

## 6. 冲突证据处理

“冲突”不一定要立刻丢弃。

建议分 3 类：

### 6.1 互补

例如：

1. table cell 给数值
2. semantic span 给原因说明

这类应同时保留。

### 6.2 重复

例如：

1. lexical 和 semantic 都命中同一段文本

这类应合并为一个 canonical item。

### 6.3 冲突

例如：

1. 两个表格版本给出不同数值
2. metadata hint 和 lexical signal 路线相反

这类不应隐式覆盖，必须在 canonical pack 中显式标记冲突。

---

## 7. Canonical Evidence Pack Schema

建议：

```python
from dataclasses import dataclass, field

@dataclass
class CanonicalEvidencePack:
    pack_id: str
    task_id: str
    source_doc_hashes: list[str]
    hard_facts: list[dict] = field(default_factory=list)
    structured_evidence: list[dict] = field(default_factory=list)
    semantic_contexts: list[dict] = field(default_factory=list)
    lexical_hints: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    budget_meta: dict = field(default_factory=dict)
    pack_hash: str = ""
    schema_version: str = "statebus.canonical_evidence_pack.v1"
```

### 7.1 `hard_facts`

承载：

1. 表格单元格
2. 数值字段
3. 可直接引用的 structured facts

### 7.2 `structured_evidence`

承载：

1. 小型 JSON facts
2. 表格行摘要
3. tool-extracted records

### 7.3 `semantic_contexts`

承载：

1. 长文背景
2. 原因解释
3. 低噪上下文片段

### 7.4 `lexical_hints`

承载：

1. route hint
2. tool hint
3. entity alias
4. 特定关键词证据

### 7.5 建议的 item 正规化字段

`CanonicalEvidencePack` 里的每个 item，建议至少具备：

```python
{
  "item_id": "text_span:doc_a:chunk_07:120:240",
  "bucket": "semantic_context",
  "locator": {...},
  "rendered_text": "...",
  "rendered_bytes": 184,
  "rank_sources": {"lexical": 3, "semantic": 1},
  "rrf_score": 0.0323,
  "stable_sort_key": "semantic_context|doc_a|chunk_07|120|240"
}
```

原则：

1. `item_id` 必须可重复计算
2. `rendered_bytes` 必须是预算裁剪使用的真实字节数
3. `stable_sort_key` 必须独立于 Python dict 顺序

### 7.6 `pack_hash` 计算范围

建议：

```text
pack_hash = SHA256(canonical_json(pack_without_runtime_ephemera))
```

不进入 `pack_hash` 的字段：

1. 运行时临时日志
2. 非决定性的 wall-clock 时间戳
3. 仅用于前端展示的瞬时颜色/样式字段

进入 `pack_hash` 的字段：

1. bucket 内容
2. locator
3. rendered text
4. rendered bytes
5. 排序结果
6. budget contract

---

## 8. Budget 合同

Canonical pack 不应无限增长。

### 8.1 推荐预算字段

```json
{
  "max_hard_fact_count": 12,
  "max_semantic_context_bytes": 4000,
  "max_total_locator_count": 32,
  "max_conflict_count": 8
}
```

### 8.2 裁剪顺序

建议：

1. 先保留 `hard_facts`
2. 再保留 `structured_evidence`
3. 再保留最相关 `semantic_contexts`
4. 最后只保留少量 `lexical_hints`

### 8.3 最后一个文本 context 的裁剪规则

为了同时保证：

1. 字节预算严格可证
2. 输出仍可被 LLM 正常读取

推荐：

1. 优先按 item 粒度裁剪
2. 如果最后一个 `semantic_context` 超出剩余 budget，允许对该 item 做 UTF-8 安全截断
3. 不要求句子级完整，但必须保证编码安全和计量确定性

---

## 9. 与 replay 的关系

Canonical evidence pack 是 replay 的关键桥梁。

原因：

1. validated replay 需要稳定的 evidence shaping contract
2. exact replay 需要稳定的 pack hash / evidence hash

因此建议：

1. `pack_hash` 可作为 replay admissibility 的辅助字段
2. pack 内各 item 都带 provenance locator

---

## 10. 与当前仓库对象的映射

当前仓库已有：

1. `FEATURE_BUNDLE`
2. `RANKED_EVIDENCE_BUNDLE`
3. `MemoryHit.evidence_state_refs`
4. route/tool/retrieved_doc_ids/fresh_evidence_sha256

这些都说明仓库已经有 fan-in 的影子，但还没正式合同化。

当前仍缺：

1. `CanonicalEvidencePack` 正式 schema
2. 分模态 merge 逻辑
3. 冲突证据表示
4. evidence budget contract

---

## 11. MVP 实现建议

### 11.1 先不做新 agent

先增加一个 deterministic module：

- `runtime/evidence_fuser.py`

### 11.2 先支持 3 种 item

`MVP` 先支持：

1. `table_cell_fact`
2. `text_span_context`
3. `route_tool_hint`

### 11.3 先支持 rule-based merge

不引入 LLM merge。

---

## 12. 非目标与暂不承诺

当前不承诺：

1. 全自动事实真伪裁判
2. 跨文档知识图谱融合
3. 复杂推理级证据辩论系统

---

## 13. 验收建议

建议最小验收：

1. 三个 Retriever 分别产出异构结果
2. Fan-in 做同模态去重
3. 生成 canonical evidence pack
4. 控制预算后仍保留最关键 hard facts
5. replay 侧可以读取 pack hash / locator 信息

建议后续补测试：

- `tests/evidence/test_text_span_merge.py`
- `tests/evidence/test_table_cell_dedup.py`
- `tests/evidence/test_canonical_evidence_pack_budget.py`
