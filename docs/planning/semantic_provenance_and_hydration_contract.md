# Semantic Provenance And Hydration Contract

日期：2026-06-26  
状态：`v2` 子合同草案  
作用：定义非文本状态的来源定位、可回填规则、统计口径和回收边界。

---

## 1. 目标

这份合同要把下面几件事定死：

1. `StateRef` 背后的真实来源怎么表示
2. 不同模态的证据如何统一溯源
3. 下游如何把非文本状态局部 hydrate 成真正给 LLM 看的证据
4. `raw_evidence_bytes_seen_by_llm` 如何数学可证
5. `StateRef`、`ArtifactRef`、memory evidence 之间如何保持一致

当前冻结语境下，首版 formal benchmark 默认围绕财报 / 经营数据分析任务家族，因此 provenance 合同必须优先稳定支持：

1. canonical text fragments
2. table cells / rows
3. executor 产出的 csv/json/png artifact

---

## 2. 为什么不能只写 “byte offset”

`byte offset` 对下面对象很好用：

1. `txt`
2. `csv`
3. `jsonl`
4. 稳定的 canonicalized plain text

但对下面对象不稳定：

1. `PDF`
2. OCR 结果
3. HTML 清洗后的文本
4. 表格抽取结果
5. extractor 版本会变的分块结果

因此，`v2` 不能把 provenance 合同写成 “统一 start_byte/end_byte 真理”。

正确做法是：

1. 定义统一的 `SourceLocator`
2. 由不同模态提供自己的 locator 变体

---

## 3. 核心原则

### 3.1 非文本状态不等于不可溯源

embedding 矩阵、feature bundle、canonical evidence pack 都必须能追溯到：

1. 输入文档或结构化数据
2. 使用的 extractor / chunker / parser 版本
3. 对应的原始片段或单元格

### 3.2 hydrate 是按需局部回填，不是全文重建

下游从 semantic state 恢复文本，不是把整个文档重新塞回 LLM，而是：

1. 选中的 row / cell / fragment
2. 按预算裁剪
3. 组装成最小 evidence slice

### 3.3 provenance 要区分 canonical source 与 derived surface

例如预抽取文档面：

1. `source_doc_hash` 指向原始来源文件
2. `extractor_version` 指向抽取器版本
3. `fragment_id` 指向抽取后的稳定片段

这三者缺一不可。

---

## 4. 建议对象模型

### 4.1 基础 locator

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class TextSpanLocator:
    locator_type: Literal["text_span"] = "text_span"
    source_doc_hash: str = ""
    canonical_text_id: str = ""
    start_char: int = 0
    end_char: int = 0
    extractor_version: str = ""

@dataclass(frozen=True)
class TableCellLocator:
    locator_type: Literal["table_cell"] = "table_cell"
    source_doc_hash: str = ""
    table_id: str = ""
    sheet_name: str = ""
    row_idx: int = 0
    col_idx: int = 0
    extractor_version: str = ""

@dataclass(frozen=True)
class FragmentLocator:
    locator_type: Literal["fragment"] = "fragment"
    source_doc_hash: str = ""
    fragment_id: str = ""
    extractor_version: str = ""
    page_no: int | None = None
```

### 4.2 统一 source locator

`HydrateManifest` 不再是简单的 `row -> byte span`，而是：

```python
SourceLocator = TextSpanLocator | TableCellLocator | FragmentLocator
```

### 4.3 Hydrate Manifest

```python
@dataclass
class HydrateManifestEntry:
    row_idx: int
    locator: SourceLocator
    stable_key: str
    byte_hint: int = 0

@dataclass
class HydrateManifest:
    manifest_id: str
    source_doc_hashes: list[str]
    entries: list[HydrateManifestEntry]
    canonicalizer_version: str
    extractor_version: str
    schema_version: str
    created_at_ns: int
```

推荐的 wire-level JSON 结构：

```json
{
  "manifest_id": "manifest_001",
  "source_doc_hashes": ["sha256:doc_a"],
  "entries": [
    {
      "row_idx": 12,
      "stable_key": "text_span:doc_a:chunk_07:120:240",
      "byte_hint": 120,
      "locator": {
        "locator_type": "text_span",
        "source_doc_hash": "sha256:doc_a",
        "canonical_text_id": "chunk_07",
        "start_char": 120,
        "end_char": 240,
        "extractor_version": "chunker_v2"
      }
    }
  ],
  "canonicalizer_version": "canonical_text_v1",
  "extractor_version": "chunker_v2",
  "schema_version": "statebus.hydrate_manifest.v1",
  "created_at_ns": 1760000000
}
```

---

## 5. 与 `StateRef` 的绑定

`StateRef`、`HydrateManifest`、artifact manifest 在控制面/索引面/CAS sidecar 的正式落点，见：

1. [ref_registry_and_manifest_storage_contract.md](/home/qcrs/statebus/project/docs/planning/ref_registry_and_manifest_storage_contract.md)
2. [lifecycle_matrix.md](/home/qcrs/statebus/project/docs/planning/lifecycle_matrix.md)

当前仓库已有 [StateRef](/home/qcrs/statebus/project/protocol/messages.py:12)。

`v2` 不要求推翻 `StateRef`，而是要求在 `metadata` 内收紧 provenance 字段。

### 5.1 建议 metadata 字段

对于 `EMBEDDING`：

```json
{
  "channel_name": "semantic_state",
  "dtype": "float32",
  "shape": [1000, 384],
  "vector_dim": 384,
  "manifest_id": "manifest_001",
  "source_doc_hashes": ["sha256:..."],
  "extractor_version": "text_chunker_v2",
  "hydrate_mode": "locator_manifest"
}
```

对于 `DENSE_EVIDENCE` / `RANKED_EVIDENCE_BUNDLE`：

```json
{
  "channel_name": "semantic_state",
  "evidence_pack_id": "pack_001",
  "source_doc_hashes": ["sha256:..."],
  "locator_count": 12,
  "hard_fact_count": 4,
  "context_span_count": 8
}
```

对于 `TOOL_ARTIFACT`：

```json
{
  "channel_name": "execution_artifact",
  "artifact_type": "csv",
  "workspace_relpath": "outputs/result.csv",
  "artifact_root_id": "workspace_root",
  "source_evidence_pack_id": "pack_001",
  "tool_name": "python_execute",
  "route": "table_analysis"
}
```

---

## 6. Hydration 流程

### 6.1 生成阶段

由 producer 负责：

1. 切分文本或表格
2. 产出 embedding / bundle
3. 同时生成 `HydrateManifest`

### 6.2 传递阶段

控制面只传：

1. `StateRef`
2. 必要的 `manifest_id`
3. 预算提示与使用方式

### 6.3 消费阶段

consumer 读取非文本状态后：

1. 先完成本地筛选
2. 拿到选中的 row / item index
3. 通过 manifest 查 source locator
4. 局部 hydrate 成 text slice / table slice

### 6.4 进入 LLM 前的最终裁剪

只有这一步形成：

1. `llm_visible_evidence_text`
2. `llm_visible_table_excerpt`
3. `llm_visible_structured_facts`

因此，统计 `raw_evidence_bytes_seen_by_llm` 时，必须以这一步为准。

---

## 7. `raw_evidence_bytes_seen_by_llm` 统计合同

这是 `v2` 里最关键的指标之一。

### 7.1 指标定义

`raw_evidence_bytes_seen_by_llm`

= 本轮真正进入 LLM prompt 的原始证据总字节数

不包括：

1. 控制消息字节
2. `StateRef` 指针字节
3. 本地 embedding 矩阵字节
4. 没有被 hydrate 进 prompt 的候选证据
5. `system_prompt`
6. 工具说明、输出格式要求、任务指令本身

更严格地说，它统计的是：

```text
len(hydrated_evidence_text.encode("utf-8"))
```

这里的 `hydrated_evidence_text` 只包含外源知识片段，不包含控制性 prompt。

### 7.2 对文本 span 的统计

如果 locator 是 `TextSpanLocator`，则：

```text
bytes = len(canonical_text[start_char:end_char].encode("utf-8"))
```

### 7.3 对表格单元格的统计

如果 locator 是 `TableCellLocator`，则：

```text
bytes = len(rendered_fact_text.encode("utf-8"))
```

其中 `rendered_fact_text` 指的是最终插入 prompt 的那段结构化事实文本。

也就是说：

1. 如果你把单元格渲染成 `18.5%`，就按 `18.5%` 计
2. 如果你把它渲染成 `TSLA gross_margin=18.5%`，就按整段已插入文本计

不要一边按原始 cell value 计，一边往 prompt 里塞更长的 fact line。

### 7.4 对 fragment 的统计

如果 locator 是 `FragmentLocator`，则：

1. 从 canonicalized fragment surface 取文本
2. 统计该 fragment 真正拼入 prompt 的字节数

### 7.5 审计要求

每次向 LLM 发请求前，建议落一份简短审计结构：

```json
{
  "trace_id": "task_001",
  "step_id": "summarize_01",
  "raw_evidence_bytes_seen_by_llm": 5820,
  "evidence_locator_count": 7,
  "evidence_pack_id": "pack_001",
  "system_prompt_bytes": 0,
  "counting_scope": "hydrated_external_evidence_only"
}
```

---

## 8. GC 与所有权

### 8.1 所有权原则

producer 生成：

1. `StateRef`
2. `HydrateManifest`
3. 若干 locator-backed derived artifact

但统一回收应由 runtime supervisor 兜底。

### 8.2 异常路径

若 task 中途失败：

1. workspace 可以回收
2. shared memory 可以回收
3. manifest / canonical source 索引不一定立即删除

原因：

- provenance 索引常常还用于失败分析或 replay 审计

## 8.3 单容器 openEuler 下的路径纪律

如果 `v2` 运行在单容器 `openEuler` 内，这份合同必须明确：

1. provenance 里不能默认写宿主机绝对路径
2. artifact locator 默认应使用：
   - `artifact_root_id`
   - `workspace_relpath`
   - `blob_hash`
3. `StateRef.handle` 如果是本地文件路径，只能被解释为容器内路径

更稳的策略是：

1. 对外记录 `blob_hash + relpath`
2. 容器内部再通过固定 root 解析真实路径

这样 replay 和迁移到 openEuler 容器时才不会被宿主机路径绑死。

---

## 9. 与当前仓库对象的映射

当前可直接借用：

1. [StateRef](/home/qcrs/statebus/project/protocol/messages.py:12)
2. [StatePool](/home/qcrs/statebus/project/statepool/store.py:201)
3. CAS blob 的 `blob_hash / exact_replay_ready` 能力
4. `MemoryCommit.evidence_state_refs` 与 `MemoryHit.evidence_state_refs`

当前仍缺：

1. 正式 `HydrateManifest`
2. locator 分型
3. `raw_evidence_bytes_seen_by_llm` 的实现口径
4. provenance-aware canonical text surface

---

## 10. MVP 实现建议

### 10.0 `MVP` 数据面收口

首版 formal benchmark 优先只支持：

1. canonicalized plain text
2. `csv/json` 表格面
3. fragment-based 文本片段

也就是说，`MVP` 可以承认原始输入曾经是 PDF/HTML，但进入 `v2` 主链路时，优先消费已经冻结版本的 canonical surface，而不是把 PDF/OCR 解析本身放进主合同。

### 10.1 先支持 3 类 locator

`MVP` 只先落：

1. `TextSpanLocator`
2. `TableCellLocator`
3. `FragmentLocator`

不要一开始就引入图像框、多模态坐标等更重类型。

### 10.2 先以 repo-local 文本/CSV/JSON 语料为主

这和 formal benchmark 的 offline local corpus 要求一致。

这样可以先把：

1. `canonical_text_id`
2. `sheet_name/row_idx/col_idx`
3. `fragment_id`

跑通。

### 10.3 PDF 如需接入，先走 extract-then-canonicalize

对于 PDF，不直接承诺原 PDF byte offset。

先做：

1. 原 PDF 哈希
2. 抽取后 canonical text / fragment surface
3. fragment-based provenance

### 10.4 单容器目标下的 canonical surface 策略

如果目标是单容器 `Docker + openEuler`，建议：

1. canonical text surface
2. extracted table surface
3. hydrated evidence snippets

都优先落到容器内 workspace 或 state root 下的文件，再配合 hash/locator 解释。

原因：

1. 它比纯内存对象更利于 replay、审计和失败后复盘
2. 更利于 replay、审计和复现实验

---

## 11. 非目标与暂不承诺

当前不承诺：

1. OCR bbox 级精确定位
2. 图像块级像素回填
3. 跨 extractor 自动对齐
4. 任意外部网页 DOM 精准稳定回放

---

## 12. 验收建议

建议最小验收测试：

1. Retriever 生成 embedding matrix + hydrate manifest
2. Executor 或 summarizer 只根据 top-k row index hydrate 出少量证据
3. 统计 `raw_evidence_bytes_seen_by_llm`
4. 审计文件能反查到原始 source locator

建议后续补测试：

- `tests/state/test_hydrate_manifest_roundtrip.py`
- `tests/state/test_raw_evidence_bytes_accounting.py`
- `tests/state/test_locator_modalities.py`

---

## 13. 外部参考

- Python `shared_memory` 官方文档：<https://docs.python.org/3/library/multiprocessing.shared_memory.html>
- Python `mmap` 官方文档：<https://docs.python.org/3/library/mmap.html>
