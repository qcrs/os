# P2：KV Cache / hidden-state 实现路径

**优先级**：P2（赛题加分创新项，不阻塞核心 claim）
**目标**：在不修改 LLM 推理引擎的前提下，先实现估算型证明；后续接入本地 vLLM 实现机制验证

---

## 一、问题分析

### 1.1 两个独立维度

| 维度 | 描述 | 实现难度 | 依赖 |
|---|---|---|---|
| 单任务内：4 Agent prefix inheritance | 后一个 Agent 的 prompt 前缀 = 前一个 Agent 的完整 prompt，形成链式 prefix | 低（只改 prompt 构造合同） | 不依赖本地 vLLM |
| 跨任务：corpus-level KV 共享 | 相同文档作为静态 prefix，不同任务共享 KV cache | 中（需要本地 vLLM + prefix cache 启用） | 依赖本地 vLLM |

### 1.2 API 模式的限制

- API 模式下无法控制推理引擎的 KV cache 行为
- 无法直接测量 `prefix_cache_hit_rate` 或 `ttft_ms`
- 但可以做**估算型证明**：统计"理论上可以节省多少 KV 计算"

### 1.3 本地模型的能力评估

如果使用 Qwen3-32B + vLLM：
- AWQ 4-bit：约 20GB VRAM，推荐 A100 或 2×4090
- float16：约 64GB VRAM，需要 A100 80GB

如果资源受限，Qwen3-14B 是更好的选择：
- float16：约 28GB VRAM
- AWQ 4-bit：约 8GB VRAM（单个 3090/4090 可运行）
- 对 StateBus 的结构化任务（route/tool 选择、数值提取）能力足够

---

## 二、阶段一：估算型证明（不需要本地 vLLM）

### 2.1 corpus_prefix_hash 追踪

在 `SemanticStateRef.metadata` 中加入 `corpus_prefix_hash` 字段：

```python
# 计算方法：
corpus_prefix_hash = sha256(
    sys_prompt_version +
    sorted(corpus_doc_hashes)  # 排序确保稳定性
)
```

然后在 continuous benchmark 中统计：

```python
@dataclass
class KVSavingsEstimate:
    total_tasks: int
    corpus_unique_count: int           # 不同 corpus 的数量
    corpus_reuse_count: int            # 相同 corpus 被复用的次数
    estimated_corpus_tokens: int       # 每个 corpus 的平均 token 数
    estimated_kv_savings_tokens: int   # 理论节省的 KV 编码 tokens

    @property
    def savings_ratio(self) -> float:
        total_corpus_tokens = self.total_tasks * self.estimated_corpus_tokens
        return self.estimated_kv_savings_tokens / total_corpus_tokens if total_corpus_tokens > 0 else 0.0
```

**统计逻辑**：
- 第一次遇到某个 `corpus_prefix_hash`：需要计算 KV（1次 corpus 编码）
- 后续相同 hash 的任务：如果有 prefix cache，可以跳过 corpus 编码
- `estimated_kv_savings_tokens += corpus_tokens_count`（对每次复用累加）

### 2.2 在 continuous runner 中集成

在 `v2/benchmark/continuous_runner.py` 的报告中加入 KV 估算字段：

```python
kv_estimate = {
    "corpus_prefix_hash_unique_count": len(seen_prefix_hashes),
    "corpus_prefix_hash_reuse_count": reuse_count,
    "estimated_kv_savings_tokens": estimated_savings,
    "estimated_savings_ratio": savings_ratio,
    "note": "theoretical estimate assuming prefix cache hit on shared corpus; actual savings require local vLLM with prefix caching enabled"
}
```

### 2.3 ReplayClass × KV 理论分层

在 replay 报告中加入理论 KV 分析：

```
KV Reuse Analysis (theoretical):
┌──────────────────┬──────────────┬─────────────────────────────┐
│ ReplayClass      │ rounds       │ KV 理论节省说明              │
├──────────────────┼──────────────┼─────────────────────────────┤
│ exact_replay     │ 3            │ 100% LLM tokens 节省         │
│                  │              │ （直接从 CAS 恢复，跳过 LLM） │
├──────────────────┼──────────────┼─────────────────────────────┤
│ validated_replay │ 13           │ corpus prefix KV 可复用      │
│                  │              │ （相同文档，不同查询）        │
│                  │              │ 估算节省 ~corpus_tokens × N  │
├──────────────────┼──────────────┼─────────────────────────────┤
│ assist           │ 4            │ system prefix KV 可复用      │
│                  │              │ （system prompt 跨任务复用）  │
├──────────────────┼──────────────┼─────────────────────────────┤
│ cold_start       │ 0            │ 全量计算                     │
└──────────────────┴──────────────┴─────────────────────────────┘
```

---

## 三、阶段二：本地 vLLM 机制验证（需要 GPU 资源）

### 3.1 环境准备

**推荐模型选择**：

| 模型 | VRAM 需求（4-bit） | VRAM 需求（fp16） | 适用场景 |
|---|---|---|---|
| Qwen3-14B | ~8GB | ~28GB | GPU 受限，单 3090/4090 |
| Qwen3-32B | ~20GB | ~64GB | 标准实验，A100 或 2×4090 |
| Qwen3-72B | ~40GB | OOM | 高质量，需要多卡 |

**推荐**：Qwen3-14B AWQ 4-bit（最容易部署，质量对 StateBus 任务足够）

**vLLM 启动命令**：

```bash
# 安装 vLLM（在容器内或 host）
pip install vllm>=0.4.0

# 启动 Qwen3-14B（AWQ 4-bit）
python3 -m vllm.entrypoints.openai.api_server \
  --model /statebus/models/Qwen3-14B-AWQ \
  --quantization awq \
  --enable-prefix-caching \          # 启用 prefix cache
  --max-model-len 8192 \
  --host 0.0.0.0 \
  --port 8000 \
  --served-model-name qwen3-14b

# 或者使用 fp16（需要足够 VRAM）
python3 -m vllm.entrypoints.openai.api_server \
  --model /statebus/models/Qwen3-14B \
  --enable-prefix-caching \
  --max-model-len 8192 \
  --host 0.0.0.0 \
  --port 8000
```

**获取 prefix cache metrics**：

vLLM 的 metrics 端点（Prometheus 格式）：

```bash
curl http://localhost:8000/metrics 2>/dev/null | grep -E "prefix_cache|cache_hit"
```

关键指标：
- `vllm:gpu_prefix_cache_queries_total` - 总查询次数
- `vllm:gpu_prefix_cache_hits_total` - 命中次数
- `vllm:gpu_prefix_cache_hit_rate` - 命中率

### 3.2 StateBus 接入本地 vLLM

在 `deploy/statebus_llm.yaml.local` 中配置本地 vLLM endpoint：

```yaml
llm_provider: openai_compatible
base_url: http://localhost:8000/v1
api_key: "local-no-auth"
model: "qwen3-14b"
role_path_mode: local_vllm
```

在 `runtime/llm.py` 中，`role_path_mode = "local_vllm"` 时使用这个配置。

### 3.3 Prefix Alignment 实验设计

**实验 A：4 Agent 链式 prefix inheritance**

对比两种 prompt 构造方式：

**方式 1（当前）**：每个 Agent 独立构造 prompt
```
Planner prompt:  [SYS] + [TASK]                    = 500 tokens
Retriever prompt: [SYS] + [TASK] + [EVIDENCE]      = 2000 tokens
Executor prompt:  [SYS] + [TASK] + [EVIDENCE]      = 2000 tokens
Summarizer prompt:[SYS] + [TASK] + [EVIDENCE]      = 2000 tokens
```
（SYS 前缀相同，但 TASK/EVIDENCE 组织方式不同）

**方式 2（链式 prefix）**：
```
Planner prompt:    [SYS] + [TASK] + [PLANNER_INST]             = 600 tokens
Retriever prompt:  [SYS] + [TASK] + [PLANNER_INST] + [P_OUT] + [RETRIEVER_INST] = 800 tokens
Executor prompt:   [SYS] + [TASK] + [PLANNER_INST] + [P_OUT] + [RETRIEVER_INST] + [R_OUT] + [EXEC_INST] = 1100 tokens
Summarizer prompt: [SYS] + [TASK] + ... + [EXEC_OUT] + [SUM_INST]  = 1400 tokens
```
（每个 Agent 的 prompt 是前一个的超集，共享前缀）

**对比指标**：
- `prefix_cache_hit_rate`（从 vLLM metrics 获取）
- `ttft_ms`（每个 Agent 调用的 Time-to-First-Token）
- `total_tokens`（注意：方式2 的 total tokens 会增加，但 KV 计算量减少）

**实验 B：Corpus-Level 跨任务 KV 共享**

选取 3 个引用相同 corpus 的任务（ACME 2026Q1 的不同指标分析），连续运行：

```bash
# 测试顺序1：相同 corpus 任务连续执行
Task A（ACME 2026Q1 revenue）→ Task B（ACME 2026Q1 operating_cost）→ Task C（ACME 2026Q1 net_income）

# 测试顺序2：随机顺序（corpus 不连续）
Task A（ACME 2026Q1）→ Task D（BETA 2026Q1）→ Task B（ACME 2026Q1）
```

对比两种顺序下的 `ttft_ms`，预期：顺序1 在 Task B、C 时有更低的 TTFT（corpus KV cache 命中）。

### 3.4 EvidencePruningHint 实验设计

在 Retriever 输出中加入 importance_score：

```python
@dataclass
class EvidenceChunkWithScore:
    chunk_id: str
    text: str
    token_count: int
    importance_score: float    # embedding cosine similarity to query
    keep_in_budget: bool       # importance_score > threshold

PRUNING_THRESHOLD = 0.6  # 可调参数
```

对比有/无 pruning 的：
- `prompt_tokens`（Retriever 传给 Executor 的 evidence tokens）
- `quality_floor_pass`（确保压缩后质量不下降）
- `estimated_kv_tokens_saved`（被丢弃的 chunk tokens）

---

## 四、答辩中的 KV Cache 呈现策略

### 4.1 两阶段呈现

**阶段一（当前可做）**：

> "StateBus 通过 `CanonicalTaskSpec` 的 corpus 标识符（ticker + quarter）追踪 corpus prefix hash。在 continuous benchmark 中，20 轮中有 13 轮为 validated/exact replay，这 13 轮的 corpus prefix hash 与第一轮相同。理论上，如果接入支持 prefix cache 的本地推理引擎，这 13 轮可以跳过 corpus 部分的 KV 重编码，节省约 `corpus_tokens × 13` 次 KV 计算。"

**阶段二（接入 vLLM 后）**：

> "实测数据：使用 vLLM + prefix cache 后，同 corpus 的连续任务中 TTFT 从 X ms 降低到 Y ms（降低 Z%），prefix cache hit rate 为 N%。"

### 4.2 不能宣称的边界

| 不能宣称 | 原因 |
|---|---|
| 实现了 KV 激活在 Agent 间直接传递 | 这需要推理引擎支持跨请求 KV sharing，当前不可行 |
| 跨模型 KV 共享 | 不同模型的 KV 格式不同，完全不可行 |
| KV 压缩（SnapKV 等） | 需要修改推理引擎，当前实现是 input-level pruning |
| API 模式下的 prefix cache 效果 | API 是黑盒，无法控制 |

---

## 五、实现顺序

```
Step 1：corpus_prefix_hash 追踪（估算型，不需要本地 vLLM）
  文件：v2/runtime/smoke.py，v2/benchmark/continuous_runner.py
  产出：KV savings estimate 写入 continuous 报告

Step 2：ReplayClass × KV 理论分层写入报告
  文件：v2/benchmark/reporting.py（或新增 kv_analysis.py）
  产出：带 KV 分析的 replay 报告

Step 3（需要 GPU）：本地 vLLM 部署
  前提：服务器有 ≥8GB VRAM（Qwen3-14B AWQ 4-bit）
  命令：见 3.1 节

Step 4（需要 GPU）：prefix alignment 实验
  文件：v2/benchmark/kv_prefix_experiment.py（新建）
  产出：prefix_cache_hit_rate, ttft_ms delta

Step 5（需要 GPU）：EvidencePruningHint 实验
  文件：v2/retrieval/pipeline.py（加入 importance_score）
  产出：pruning_ratio, token_savings, quality_floor_pass
```

---

## 六、赛题加分项对齐

| 赛题描述 | 对应实现 | 当前状态 |
|---|---|---|
| 鼓励 IPC/共享内存 | StateBus 已有 SemanticStateRef + mmap/shared_memory | 已实现 |
| 鼓励 Socket | UDS executor transport 已有样机 | 已实现（样机） |
| 鼓励向量数据库 | SQLite + FAISS 共享记忆 | 已实现 |
| 鼓励容器沙箱 | bwrap sandbox in openEuler Docker | 已实现（高权限） |
| 鼓励 CodeAct | bounded CodeAct demo | 已实现（deterministic fallback） |
| **创新加分** | **KV cache prefix alignment + corpus reuse** | **待实现（估算型可先做）** |
| **创新加分** | **EvidencePruningHint + input-level KV 等价压缩** | **待实现** |
| **创新加分** | **ReplayClass × KV Cache 统一分层模型** | **设计已完成，待落地** |
