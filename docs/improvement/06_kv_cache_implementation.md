# P2：KV Cache / hidden-state 实现路径

**优先级**：P2（赛题加分创新项，不阻塞核心 claim）
**目标**：在不修改 LLM 推理引擎的前提下，先实现估算型证明；后续接入本地 vLLM 实现机制验证

**当前实现状态（2026-07-08）**：

- 已恢复本文档并落地估算型主链路：
  - `v2/runtime/neural_state.py`
    - `build_corpus_prefix_hash`
    - `build_evidence_prefix_hash`
    - `build_neural_prefix_identity`
    - `NeuralStateHandle`
    - `EngineLocalPrefixRegistry`
    - `PrefixReuseScheduleHint`
    - `order_prefix_schedule_hints`
    - `estimate_engine_local_prefix_reuse`
  - `v2/benchmark/kv_analysis.py`
    - `ReplayClass × KV` 理论分层
    - corpus prefix hash 复用统计
    - engine-local prefix reuse 估算聚合
  - `v2/benchmark/kv_prefix_experiment.py`
    - local vLLM OpenAI-compatible prefix alignment probe
    - streaming TTFT 采集
    - `/metrics` prefix cache delta 读取
  - `v2/runtime/role_path.py`
    - 默认关闭的 `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix`
    - 支持四角色 prompt 先写入相同 evidence prefix，再追加角色后缀
    - shared-prefix 模式下 role suffix 去重 evidence，避免 prefix 与 suffix 双写同一段证据
  - `v2/retrieval/models.py`、`v2/retrieval/pipeline.py`
    - `EvidencePruningHint`
    - input-level pruning profile
    - estimated KV/prefill token savings
  - `v2/runtime/kv_budget.py`
    - 从 HF config 估算 KV bytes/token
    - 支持 bf16/fp16 与目标 KV dtype 的容量收益估算
  - `scripts/inspect_vllm_kv_budget.py`
    - 不启动模型即可估算 Qwen3-8B/32B KV footprint
  - `docs/setup/local_vllm_qwen.md`
    - 记录当前 cu121 + vLLM 0.7.3 部署路线、模型选择和边界
  - `v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/manifest.json`
    - `kv_prefix_reuse_v1` mechanism probe family
    - 暂不注册进默认 formal/continuous runner

**仍然不宣称**：

- 没有导出、传递或重写模型内部 KV tensor。
- 没有实现跨模型、跨 engine、跨进程 KV tensor sharing。
- 当前实现是 `Engine-Local Prefix Reuse` 的 StateBus 策略层、估算层和观测层。
- 本地 vLLM 只有启用 prefix caching 且 metrics 能读到 hit 时，才可作为机制验证证据。

**定位结论**：

StateBus 的 KV 方向不是"把模型内部 KV tensor 从一个 Agent 直接搬给另一个 Agent"。当前可落地、可验证、也更适合本项目的定位是：

> StateBus 作为 **Cache-Aware Agent Runtime**，在 LLM engine 外部提供 prefix 编译、corpus-aware 调度、input-level pruning、prefix lease 记录和可观测 probe，让 vLLM 这类本地推理引擎的 automatic prefix caching 从被动命中变成可规划、可解释、可度量的系统能力。

因此 KV 相关能力按三层划分：

| 层级 | 是否属于当前实现 | StateBus 做什么 | 不能说成什么 |
|---|---:|---|---|
| Agent 内部 | 间接相关 | 单个角色 prompt 中减少无关 evidence，降低 prefill/KV token | 不是模型内部 KV 剪枝算法 |
| 跨 Agent，同一任务 | 策略层已实现，机制验证待 GPU 跑证据 | 让 Planner/Retriever/Executor/Summarizer 共享相同 evidence prefix，再追加角色后缀 | 不是把 Planner 的 KV tensor 传给 Executor |
| 跨任务，同一 corpus | 估算层已实现，调度数据集待补 | 用 `corpus_prefix_hash` 识别相同文档/证据前缀，连续调度同 corpus 任务，提高 APC 命中概率 | 不是跨 engine 或跨模型 KV sharing |
| 跨进程/跨模型 KV tensor | 不实现 | 只记录兼容性、估算收益和观测指标 | 不能 claim 支持 |

一句话：**KV 在这里不是 StateBus 的数据面对象，而是本地 LLM engine 内部的短生命周期缓存；StateBus 创新点是围绕它做控制面、调度面和证据面。**

**核心创新点命名**：

1. **Prefix Layout Compiler**
   - 把多 Agent prompt 编译成稳定共享前缀和角色后缀两段：
     ```text
     [SYSTEM + STATIC CORPUS/EVIDENCE PREFIX] + [ROLE-SPECIFIC SUFFIX]
     ```
   - 价值：普通多 Agent prompt 经常结构不同，vLLM APC 只能偶然命中；StateBus 主动制造 token-level 相同前缀。

2. **Corpus-Aware KV Scheduling**
   - 基于 `corpus_prefix_hash` 把同 corpus 任务排在同一个时间窗口：
     ```text
     preferred: ACME-1 -> ACME-2 -> ACME-3 -> BETA-1
     weaker:    ACME-1 -> BETA-1 -> ACME-2
     ```
   - 价值：把 multi-agent runtime 的调度问题和 LLM engine prefix cache 驻留时间关联起来，避免缓存被无关 corpus 插队挤掉。

3. **Prefix-Preserving Evidence Pruning**
   - `EvidencePruningHint` 不只做 relevance pruning，还要区分：
     - 是否是 hard fact；
     - 是否会被多个角色复用；
     - 是否适合进入 shared prefix；
     - token 成本是否超过收益。
   - 价值：这是 input-level KV 等价压缩，不修改 engine，但减少 engine 需要 prefill 的 token。

4. **Neural Prefix Lease**
   - `NeuralStateHandle` / `EngineLocalPrefixRegistry` 记录 prefix 在哪个 engine/model/tokenizer/session 下可复用：
     ```json
     {
       "engine_id": "local-vllm",
       "model_id": "qwen3-32b",
       "tokenizer_id": "qwen3",
       "prefix_hash": "...",
       "prefix_token_count": 4096,
       "cache_hit_count": 2
     }
     ```
   - 价值：不暴露 KV tensor，但给调度器一个 cache 控制平面视图。

5. **ReplayClass × KV Reuse Pyramid**
   - 把 StateBus 已有的 replay 分层映射到 KV 成本：
     - `exact_replay`：跳过 LLM，KV 成本约为 0；
     - `validated_replay`：复用 corpus prefix，只重算 task suffix；
     - `assist`：可能只复用 system/short prefix；
     - `cold_start`：全量 prefill。
   - 价值：把共享记忆复用和本地 LLM prefill 成本放到同一套指标体系里。

**当前推荐工程路线**：

1. `Qwen3-8B`：打通 local API、StateBus local_vllm、prefix probe、metrics 与部署脚本。
2. `Qwen3-32B`：单卡 A100 80G 做真实质量验证，先 4096，再 8192，`max_num_seqs=1`。
3. 暂不优先 `/data/models/Qwen3.5-27B`：该目录是 `Qwen3_5ForConditionalGeneration` / hybrid config，不适合当前 cu121 + vLLM 0.7.3 稳定验证。
4. 量化先从两层区分：
   - `weight quantization`：用于让 32B/更大模型更舒服部署，但会引入格式兼容风险；
   - `KV cache quantization`：用于提升 KV 容量/并发，属于 vLLM engine 参数或未来引擎验证对象；
   - StateBus 当前创新点优先放在 `input-level evidence pruning + prefix alignment + measurable engine-local APC`，不假装已经做了模型内部 KV 压缩。

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

```text
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
```text
Planner prompt:  [SYS] + [TASK]                    = 500 tokens
Retriever prompt: [SYS] + [TASK] + [EVIDENCE]      = 2000 tokens
Executor prompt:  [SYS] + [TASK] + [EVIDENCE]      = 2000 tokens
Summarizer prompt:[SYS] + [TASK] + [EVIDENCE]      = 2000 tokens
```
（SYS 前缀相同，但 TASK/EVIDENCE 组织方式不同）

**方式 2（链式 prefix）**：
```text
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

## 四、KVPrefixBench 数据集设置

现有 `cross_period_financial_v1` 和 `long_doc_metric_replay_v1` 能产生 corpus prefix 复用估算信号，但它们的主目标是 replay/semantic-state，不是专门隔离 APC。因此需要新增一个小而明确的机制验证数据集：`kv_prefix_reuse_v1`。

### 4.1 数据集目标

`kv_prefix_reuse_v1` 只回答一个问题：

> 当 StateBus 主动控制 prompt prefix layout 和任务顺序时，本地 vLLM 的 automatic prefix caching 是否能在同质量约束下带来更高 hit rate、更低 TTFT、更少 prefill token。

这不是正式替代现有 continuous benchmark，而是一个 **mechanism probe family**。在没有真实 vLLM metrics 前，claim tier 应为 `demo_secondary`；只有拿到稳定本地 metrics 和质量门后，才可升为 `formal_secondary`。

### 4.2 数据源

优先复用仓库内已有样本，避免引入不可复现外部数据：

| corpus | 文件 | 用途 |
|---|---|---|
| Orion factory operations | `v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/orion_factory_ops_report_2026.md` | 制造业运营报告，同 corpus 多指标任务 |
| Nova retail logistics | `v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/nova_retail_ops_report_2026.md` | 物流履约运营报告，第二个独立 corpus |

两份报告使用相同 metric table schema，但实体、叙述、数值、文件 hash 都不同。这样 `corpus_prefix_hash` 会形成两个真实 cache-affinity group，同时 deterministic fact checks 仍可稳定验证。

### 4.3 任务编排

建议 10 轮，分成 contiguous 与 interleaved 两组：

```text
Round 1: Orion warmup / build semantic index
Round 2: Nova warmup / build semantic index
Round 3: Orion revenue_musd
Round 4: Orion gross_margin_pct
Round 5: Orion operating_expense_musd
Round 6: Orion on_time_delivery_pct
Round 7: Nova revenue_musd
Round 8: Nova gross_margin_pct
Round 9: Nova operating_expense_musd
Round 10: Nova on_time_delivery_pct
```

对照实验不是换任务内容，而是换执行顺序：

```text
Schedule A / cache-friendly:
Orion warmup -> Orion metrics -> Nova warmup -> Nova metrics

Schedule B / cache-hostile:
Orion warmup -> Nova warmup -> Orion metric -> Nova metric -> Orion metric -> Nova metric
```

### 4.4 需要采集的指标

| 指标 | 来源 | 意义 |
|---|---|---|
| `kv_corpus_prefix_hash_reuse_count` | continuous report | StateBus 是否识别出可复用 corpus |
| `kv_corpus_level_prefill_saved_tokens_estimate` | `kv_analysis.py` | 理论 prefill/KV 节省 |
| `vllm_prefix_cache_queries_total_delta` | `/metrics` | 本地 engine 查询 APC 的次数 |
| `vllm_prefix_cache_hits_total_delta` | `/metrics` | 本地 engine 实际命中 APC 的次数 |
| `vllm_prefix_cache_hit_rate_window` | probe 计算 | 同一实验窗口内的实际命中率 |
| `ttft_ms_p50/p95` | streaming probe | prefill 是否转化成首 token 延迟收益 |
| `quality_floor_pass_rate` | deterministic validator | 证明 prefix/pruning 没有牺牲正确性 |
| `prompt_tokens` / `prompt_visible_total_bytes` | LLM telemetry | 识别收益来自 APC 还是单纯 prompt 变短 |

### 4.5 数据集当前实现状态

| 项目 | 当前状态 | 后续动作 |
|---|---|---|
| 复用估算字段 | 已在 continuous evidence pack 中聚合 | 保留 |
| vLLM metrics probe | 已有独立脚本 | 接入 `kv_prefix_reuse_v1` 产物 |
| 专用 family manifest | 已实现，暂未注册 | 保持独立，等需要机制验证时显式接入 |
| cache-friendly/cache-hostile schedule | 已在 manifest 中声明；runtime 有 schedule hint 工具 | 后续接 runner 或独立 probe 的 `--schedule` |
| 正式 benchmark 接入 | 暂不接入 | 等用户允许跑测试链路后再接入 |

---

## 五、当前实现需要修复/加深的点

### 5.1 拆分 `corpus_prefix_hash` 与 `evidence_prefix_hash`

当前已拆分。旧 `build_corpus_prefix_hash` 保留兼容参数，但 corpus identity 只使用 `source_doc_hashes + system_prompt_version + prefix_contract_version`。严格 evidence prefix 由 `build_evidence_prefix_hash` / `build_neural_prefix_identity` 生成。

建议拆成：

```text
corpus_prefix_hash   = hash(system_prompt_version + sorted(source_doc_hashes))
evidence_prefix_hash = hash(corpus_prefix_hash + evidence_pack_hash + hydrate_manifest_hash)
```

用途区分：

| hash | 用途 |
|---|---|
| `corpus_prefix_hash` | 跨任务调度、cache-friendly ordering |
| `evidence_prefix_hash` | 角色 prompt 共享前缀、严格机制 probe |

### 5.2 shared-prefix 模式去重 evidence

当前已在 `_render_prompt` 中去重：`STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix` 打开时，同一段 evidence 会放入 shared prefix；role suffix 中删除重复的 `e` payload / evidence section，并写入轻量 `sp` 引用。

目标 prompt：

```text
[shared evidence prefix]
[role suffix: instruction + compact refs + expected JSON schema]
```

不要变成：

```text
[shared evidence prefix]
[role suffix: instruction + same evidence again]
```

### 5.3 增加 prefix lease 的生命周期字段

`NeuralStateHandle` 已扩展 `engine_id/model_id/tokenizer_id/session_id/prefix_hash` 之外的 control-plane 字段：

- `last_observed_hit_ns`
- `last_observed_query_ns`
- `estimated_resident_until_ns`
- `eviction_risk`
- `schedule_priority`

这些字段不表示 StateBus 持有 KV tensor，只表示调度器对 engine-local cache residency 的估计。

### 5.4 将 vLLM probe 输出并入 evidence pack

`kv_prefix_experiment.py` 当前是独立 probe。后续应把输出标准化为：

```text
artifacts/kv_prefix_probe/cache_friendly.json
artifacts/kv_prefix_probe/cache_hostile.json
artifacts/kv_prefix_probe/summary.md
```

再把 summary 引入 continuous collection report，但不默认进 pytest/benchmark 链路。

---

## 六、答辩中的 KV Cache 呈现策略

### 6.1 两阶段呈现

**阶段一（当前可做）**：

> "StateBus 通过 `CanonicalTaskSpec` 的 corpus 标识符（ticker + quarter）追踪 corpus prefix hash。在 continuous benchmark 中，20 轮中有 13 轮为 validated/exact replay，这 13 轮的 corpus prefix hash 与第一轮相同。理论上，如果接入支持 prefix cache 的本地推理引擎，这 13 轮可以跳过 corpus 部分的 KV 重编码，节省约 `corpus_tokens × 13` 次 KV 计算。"

**阶段二（接入 vLLM 后）**：

> "实测数据：使用 vLLM + prefix cache 后，同 corpus 的连续任务中 TTFT 从 X ms 降低到 Y ms（降低 Z%），prefix cache hit rate 为 N%。"

### 6.2 推荐表述

推荐说法：

> StateBus 没有把 KV tensor 当作跨 Agent 数据包传输，而是把多 Agent runtime 变成 LLM engine prefix cache 的控制平面。它通过 prefix layout compiler、corpus-aware scheduling、prefix-preserving pruning 和 neural prefix lease，让 engine-local APC 从偶然命中变成系统可规划的优化对象。

不推荐说法：

> StateBus 实现了跨 Agent KV cache 传递。

### 6.3 不能宣称的边界

| 不能宣称 | 原因 |
|---|---|
| 实现了 KV 激活在 Agent 间直接传递 | 这需要推理引擎支持跨请求 KV sharing，当前不可行 |
| 跨模型 KV 共享 | 不同模型的 KV 格式不同，完全不可行 |
| KV 压缩（SnapKV 等） | 需要修改推理引擎，当前实现是 input-level pruning |
| API 模式下的 prefix cache 效果 | API 是黑盒，无法控制 |

---

## 七、实现顺序

```text
Step 1：corpus_prefix_hash 追踪（估算型，不需要本地 vLLM）
  文件：v2/runtime/smoke.py，v2/benchmark/continuous_runner.py
  状态：已落地到 SemanticStateRef metadata、case metrics 和 continuous 聚合

Step 2：ReplayClass × KV 理论分层写入报告
  文件：v2/benchmark/kv_analysis.py
  状态：已落地，continuous evidence pack 按 layer 汇总

Step 3（需要 GPU）：本地 vLLM 部署
  前提：当前服务器 driver 适配 cu121；vLLM 0.7.3 可跑，Qwen3 走 Transformers fallback
  状态：部署文档已更新，见 docs/setup/local_vllm_qwen.md

Step 4（需要 GPU）：prefix alignment 实验
  文件：v2/benchmark/kv_prefix_experiment.py
  状态：已落地独立 probe；role_path 已有默认关闭的 shared_evidence_prefix contract；暂不接入测试链路

Step 5：EvidencePruningHint / input-level KV 等价剪枝
  文件：v2/retrieval/models.py，v2/retrieval/pipeline.py
  状态：已落地 profile/hint/estimated_kv_tokens_saved；暂不接入测试链路

Step 6：KV budget / quantization sizing
  文件：v2/runtime/kv_budget.py，scripts/inspect_vllm_kv_budget.py
  状态：已落地 config-based sizing；不等同于运行时 vLLM allocation measurement
```

---

## 八、赛题加分项对齐

| 赛题描述 | 对应实现 | 当前状态 |
|---|---|---|
| 鼓励 IPC/共享内存 | StateBus 已有 SemanticStateRef + mmap/shared_memory | 已实现 |
| 鼓励 Socket | UDS executor transport 已有样机 | 已实现（样机） |
| 鼓励向量数据库 | SQLite + FAISS 共享记忆 | 已实现 |
| 鼓励容器沙箱 | bwrap sandbox in openEuler Docker | 已实现（高权限） |
| 鼓励 CodeAct | bounded CodeAct demo | 已实现（deterministic fallback） |
| **创新加分** | **KV cache prefix alignment + corpus reuse** | **估算层已实现；local vLLM probe 已实现，待正式跑证据** |
| **创新加分** | **EvidencePruningHint + input-level KV 等价压缩** | **策略层已实现；暂未接测试链路** |
| **创新加分** | **ReplayClass × KV Cache 统一分层模型** | **已实现到 kv_analysis / continuous evidence pack** |

---

## 九、外部参考

- vLLM Automatic Prefix Caching: <https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/>
- vLLM prefix caching design: <https://docs.vllm.ai/en/stable/design/prefix_caching/>
- vLLM Quantized KV Cache: <https://docs.vllm.ai/en/stable/features/quantization/quantized_kvcache/>
- Scissorhands KV cache compression: <https://arxiv.org/abs/2305.17118>
- ChunkKV semantic-preserving KV cache compression: <https://arxiv.org/abs/2502.00299>
