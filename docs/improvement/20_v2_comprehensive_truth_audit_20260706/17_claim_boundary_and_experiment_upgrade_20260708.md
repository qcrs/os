# Claim 边界与实验升级计划

日期：2026-07-08
分支：`feat/local-hidden-kv-prototype`
依据：`13_artifact_mining_deep_analysis`、`14_diagnostic_artifact_mining_readout`、代码审查、`12_artifact_mining_readout`

---

## 一、当前可 Claim（有充分证据）

### 1.1 通信效率：prompt/total token reduction

| Claim 表述 | 证据来源 | 强度 |
|---|---|---|
| Full-registry 25/5 external compare 中 StateBus prompt tokens 降低 57.9% | `r01_07` formal compare report, fairness gate 25/25 | 强 |
| 同一 compare 中 total tokens 降低 49.7% | 同上 | 强 |
| Formal internal L2 相比 L0 prompt bytes 降低 45.2% | `r01_05` layer waterfall | 强 |
| Carrier compare structured 相比 text control bytes 降低 30665 | `r01_06` carrier compare | 中 |

推荐措辞：

> StateBus 在 full-registry 25-case / 5-family local+API formal external compare 中，通过 typed protocol、semantic StateRef/memfd 和 artifact-based numeric projection，将 prompt tokens 降低 57.9%，total tokens 降低 49.7%。External fairness gate 25/25 通过。

### 1.2 质量优势：quality-superiority gate

| Claim 表述 | 证据来源 | 强度 |
|---|---|---|
| StateBus 25/25 vs external 15/25，quality-superiority gate 通过 | `r01_07` report | 强 |
| External 失败集中在 metric_value_exact：anomaly 3/3、agg 4/4、trend 3/5 | family delta table | 强 |
| External fairness gate coverage=true, failed_case_count=0 | fairness metadata | 强 |

推荐措辞：

> 在同一 compare 中 StateBus 通过 quality-superiority gate（25/25 vs 15/25）。External baseline 在复杂数值聚合/异常检测任务中 metric_value_exact 不稳定，StateBus 通过结构化 evidence projection 保持数值正确性。

### 1.3 非文本中间状态传递

| Claim 表述 | 证据来源 | 强度 |
|---|---|---|
| Formal internal 25 次 semantic StateRef/memfd transfer，247076 bytes | `r01_05` layer waterfall | 强 |
| Flagship 5/6 claimable families 显示 StateRef prompt savings（21325 bytes） | `s01_10` stress summary | 强 |
| State materialization 类型为 EMBEDDING_STATE | state metadata diagnostics | 强 |

推荐措辞：

> StateBus 通过 embedding semantic state + typed refs + memfd data plane 实现非文本中间状态传递。Formal benchmark 中 25 次 semantic state transfer 真实发生，累计 247076 bytes；flagship 实验证明 5 个 claimable families 中 StateRef 相对 text handoff 有额外 prompt savings。传递对象是 embedding semantic state 和 hydration accounting，不是 KV tensor 或 hidden-state。

### 1.4 共享记忆/replay 复用

| Claim 表述 | 证据来源 | 强度 |
|---|---|---|
| Continuous-replay 18 validated / 2 exact replay | `r01_11` collection summary | 强 |
| answer_restoration_replay_count=0 | 同上 | 强 |
| L3 reuse_gain=20 | 同上 | 强 |
| Supplement flagship replay 3/3 headline families | `s01_10` continuous-replay | 强 |
| Continuous artifact reuse 50，history step reduction 13 | `r01_10` collection summary | 中 |

推荐措辞：

> 共享记忆/replay 在连续任务中真实发生：30 轮 continuous-replay 中 18 个 validated replay、2 个 exact replay，answer restoration 为 0。复用不是 answer restoration 伪装。Supplement flagship 证明 3/3 replay-headline families 可达。

### 1.5 系统完整性

| Claim 表述 | 证据来源 | 强度 |
|---|---|---|
| 4 agents（Planner/Retriever/Executor/Summarizer）协同 | `r01_05` 四角色各 25 次 API call | 强 |
| ≥10 轮连续任务稳定 | continuous 30 rounds × 3 families | 强 |
| CodeAct bwrap 5/5 | `s01_07` acceptance | 强 |
| UDS typed Protobuf control plane | tests 115 passed | 强 |
| pytest 115 + smoke + preflight all pass | base comprehensive | 强 |

---

## 二、当前不能 Claim（证据不足或事实不支持）

### 2.1 Latency/端到端速度优势

**不能 claim 的原因：**

- `serialized_latency_superiority_claim_allowed=false`（代码 gate）
- task_ms_delta=+73103.7，StateBus 更慢
- llm_ms_delta=+37201.9，LLM 侧更慢
- system_overhead_ms_delta=+35901.8，runtime 开销更高
- 只有单轮 serialized 测量，没有 repeat3 交替顺序

**差距到可 claim 的距离：** 远。即使做 serialized repeat rerun，StateBus 的 CodeAct/persist/telemetry/memfd 系统开销是结构性的，短期内不太可能翻转为 latency 优势。建议作为 future work。

### 2.2 Strict equal-quality efficiency superiority

**不能 claim 的原因：**

- `strict_equal_quality_comparison_valid=false`
- 原因是 quality_floor_pass_delta=10（StateBus 更高，不是更低）
- Strict 语义要求双方质量相等后才能比效率

**差距：** 逻辑上不可达。StateBus 质量更高时 strict equal-quality 就是 false。可以 claim quality-superiority + token reduction，不能 claim "同质量更高效"。

### 2.3 真实 vLLM prefix-cache hit / TTFT 优势

**不能 claim 的原因：**

- `STATEBUS_RUN_VLLM_PREFIX_PROBE=0`，probe skipped
- 没有 vLLM `/metrics` 中 `gpu_prefix_cache_hits_total` 数据
- 没有 streaming TTFT 测量
- 当前只有 estimate（corpus-level 2144 tokens，engine-local 2680 tokens）

**差距到可 claim 的距离：** 中。代码已实现 probe 脚本，需要本地 vLLM 服务 + 单次实验。

### 2.4 KV tensor / hidden-state transfer

**不能 claim 的原因：**

- 代码中没有 KV tensor 导出/传递/接收逻辑
- `neural_state.py` 是 control-plane metadata，不是 data-plane tensor
- AGENTS.md 明确约束为 Future Work
- Claim boundary 多处标注 `no_kv_tensor_export`

**差距：** 不可达。这需要修改 LLM 推理引擎内部机制，超出当前项目范围。

### 2.5 openEuler 24.03-LTS-SP3 最终验证

**不能 claim 的原因：**

- 所有证据在 Docker + Ubuntu host 上产出
- openEuler VM 验证阶段从未执行
- 赛题明确要求在 openEuler 上可运行

**差距：** 中。需要 VM 环境 + 依赖安装 + smoke/pytest 通过。

### 2.6 Universal flagship all-pass

**不能 claim 的原因：**

- Stress pass 5/6（supplement），base 曾只有 3/6
- `incident_diagnosis_v2` 是明确负例

**差距：** 低。1 个 diagnostic-only family 不影响 claimable scope。推荐直接承认负例边界。

### 2.7 Formal carrier compare（text vs protocol）全面优于

**不能 claim 的原因：**

- Structured side 24/25 quality，text side 25/25（少 1 个 pass）
- Structured total tokens 更高（+4161），task ms 更慢（+16836.6）
- `formal-trend-002` route miss

**差距：** 中。Route miss 是已知 selection 问题，可修。但 completion inflation 是结构性的。

---

## 三、Claim 升级路径

### 3.1 近期可落地（1-3 天）

| 目标 | 当前状态 | 需要补的实验 | 通过标准 |
|---|---|---|---|
| Formal text vs protocol 双模对比 | 代码已有 `r01_06` carrier compare 25/5 | 已有证据，只需要在 summary 中显式提取 protocol vs text token delta | `protocol_vs_text_prompt_token_delta < 0` |
| Carrier compare route miss 修复 | `formal-trend-002` route selection 问题已诊断 | 修 selection normalization + rerun carrier compare | structured side 25/25 quality |
| Replay missing target 修复 | `long_doc_metric_replay_v1` missing round 7 | 调试 round 7 的 route/quality gate → rerun continuous-replay | 3/3 replay headline families |
| Base + supplement 合并判定脚本 | 两组 artifact 独立存在 | 修复 base audit gate 脚本误报 + rerun | 无 false-negative gate |

### 3.2 中期可落地（3-7 天）

| 目标 | 当前状态 | 需要补的实验 | 通过标准 |
|---|---|---|---|
| Full-registry 25/5 external compare 覆盖确认 | 代码已升级 adapter，`local_api_20260708_084458` 已跑通 | 已有证据（本轮 `r01_07` scope = `formal_registry_25case_5family_compare`） | 确认新 artifact scope label |
| Serialized timing rerun | 未执行 | `STATEBUS_LOCAL_API_REPEAT=3` serialized rerun | 如果 task_ms_delta 仍为正，明确写 latency 不可 claim |
| openEuler VM validation | 未执行 | VM 中跑 smoke + targeted pytest | exit 0 + 日志归档 |
| KV prefix vLLM metrics probe | 代码和数据集已就绪 | 启动 local vLLM + `STATEBUS_RUN_VLLM_PREFIX_PROBE=1` | metrics delta > 0，TTFT 改善可测量 |
| 演示视频制作 | 未开始 | 录制 3-5 分钟 demo | 覆盖系统架构、实验运行、结果展示 |

### 3.3 只能作为 Future Work

| 目标 | 差距原因 | 描述方式 |
|---|---|---|
| KV tensor / hidden-state 跨 Agent 传递 | 需要修改 LLM 推理引擎内部，超出项目范围 | "Engine-Local Prefix Reuse：控制面已实现，数据面 tensor 传递作为 Future Work" |
| Cross-engine / cross-model KV sharing | 不同模型 KV 格式不兼容 | "当前方法限定为单引擎单模型范围内的 prefix cache 利用" |
| Latency superiority | 结构性系统开销（CodeAct/persist/telemetry）不可能通过调参消除 | "当前优势是 token/quality，不是 latency；系统开销是可审计性的成本" |
| nsjail production sandbox | 未安装，不可用 | "当前使用 bwrap 轻量沙箱；生产级沙箱需要后续验证" |
| Subprocess benchmark stage | 只有单测 | "subprocess transport 实现存在，正式 benchmark 中使用 loopback harness" |

---

## 四、KV Prefix 专项：从 estimate 到真实 vLLM metrics 的详细路径

**调整说明：** 基于文档4 review 发现，KV prefix vLLM probe 已从 P1 调整为独立验证项目。本章节提供详细的技术参考和决策依据。

### 4.1 当前实现的四个层级（代码交叉验证）

| 层级 | 核心组件 | 实现位置 | 证据状态 | Claim 边界 |
|------|----------|----------|----------|------------|
| **Control Plane** | `NeuralPrefixIdentity`<br>`EngineLocalPrefixRegistry`<br>`PrefixLayoutPlan`<br>`compile_prefix_layout` | `v2/runtime/neural_state.py`<br>`v2/runtime/role_path.py` | 单测通过<br>KV demo 10/10 | ✅ 可 claim：control-plane prototype 已实现 |
| **Schedule Plane** | `kv_prefix_schedule.py`<br>`build_kv_prefix_schedule_plan`<br>Manifest `schedule_hint` | `v2/benchmark/kv_prefix_schedule.py`<br>Task family manifest | 单测通过<br>`corpus_prefix_hash_reuse_count=8` | ✅ 可 claim：cache-aware scheduling 已验证 |
| **Estimate Plane** | `estimate_engine_local_prefix_reuse`<br>`KVCacheFootprintEstimate` | `v2/runtime/neural_state.py`<br>`v2/runtime/kv_budget.py` | Corpus-level: 2144 tokens<br>Engine-local: 2680 tokens | ✅ 可 claim：estimate 方法已实现 |
| **Mechanism Plane** | `kv_prefix_experiment.py`<br>vLLM metrics probe<br>TTFT measurement | `v2/benchmark/kv_prefix_experiment.py` | **代码存在但未执行**<br>`STATEBUS_RUN_VLLM_PREFIX_PROBE=0` | ❌ 不能 claim：无真实 vLLM metrics |

### 4.2 Control Plane 详细组成（已实现）

#### 4.2.1 Prefix Identity 计算

**代码位置：** `v2/runtime/neural_state.py:24-62`

**核心函数：**
- `build_corpus_prefix_hash(corpus_id, corpus_metadata)` - 计算语料库级别的 prefix identity
- `build_evidence_prefix_hash(evidence_pack_hash, pruning_profile_hash)` - 计算证据级别的 prefix identity
- `build_neural_prefix_identity(task_spec, corpus_hash, evidence_hash)` - 组合成完整的 neural prefix identity

**验证方式：**
```python
# 单测验证
pytest tests/v2/test_kv_prefix_control_plane.py::test_prefix_identity_stable
pytest tests/v2/test_kv_prefix_control_plane.py::test_corpus_evidence_separation
```

#### 4.2.2 Engine-Local Prefix Registry

**代码位置：** `v2/runtime/neural_state.py:64-120`

**数据结构：**
```python
@dataclass(frozen=True)
class NeuralStateHandle:
    prefix_identity: str
    lease_id: str
    lease_metadata: dict[str, object]
```

**Registry 功能：**
- `lease_prefix(prefix_identity, metadata)` - 申请 prefix lease
- `release_prefix(lease_id)` - 释放 prefix
- `query_prefix_reuse(prefix_identity)` - 查询是否可复用

**验证方式：**
```python
pytest tests/v2/test_kv_prefix_control_plane.py::test_registry_lease_release
pytest tests/v2/test_kv_prefix_control_plane.py::test_registry_metadata_update
```

#### 4.2.3 Prefix Layout Compiler

**代码位置：** `v2/runtime/role_path.py:24-48`

**数据结构：**
```python
@dataclass(frozen=True)
class PrefixLayoutPlan:
    corpus_prefix_tokens: int
    evidence_prefix_tokens: int
    role_context_tokens: int
    total_prefix_tokens: int
    alignment_mode: str
```

**Compiler 功能：**
- `compile_prefix_layout(task_spec, corpus_metadata, evidence_metadata)` - 编译 prefix layout plan
- 根据 `STATEBUS_PREFIX_ALIGNMENT_MODE` 决定是否启用 prefix alignment（默认 off）

**当前状态：** 代码完整但默认关闭，单测通过

### 4.3 Schedule Plane 详细组成（已实现）

#### 4.3.1 Cache-Aware Scheduling

**代码位置：** `v2/benchmark/kv_prefix_schedule.py:12-89`

**核心函数：**
- `build_kv_prefix_schedule_plan(rounds, mode)` - 生成 cache-friendly 或 cache-hostile schedule
- `order_prefix_schedule_hints(hints, mode)` - 对 prefix schedule hints 排序

**Mode 类型：**
- `cache_friendly`：相同 corpus 的 rounds 连续排列，最大化 prefix reuse
- `cache_hostile`：相同 corpus 的 rounds 分散排列，最小化 prefix reuse
- `manifest_order`：按 task family manifest 声明的顺序

**验证方式：**
```python
pytest tests/v2/test_kv_prefix_control_plane.py::test_schedule_cache_friendly
pytest tests/v2/test_kv_prefix_control_plane.py::test_schedule_cache_hostile
```

**Demo 证据：**
```bash
# KV demo 10/10 pass，corpus_prefix_hash_reuse_count=8
# 说明 cache-friendly schedule 下确实有 8 个 round 可复用 corpus prefix
```

#### 4.3.2 Manifest Schedule Hint

**示例：** `v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/manifest.json`

```json
{
  "schedule_hint": "corpus_locality",
  "rounds": [
    {
      "round": 1,
      "corpus_id": "financial_reports_2025Q3",
      "evidence_selection": "quarter_summary"
    },
    {
      "round": 2,
      "corpus_id": "financial_reports_2025Q3",
      "evidence_selection": "detailed_metrics"
    },
    {
      "round": 3,
      "corpus_id": "financial_reports_2025Q4",
      "evidence_selection": "quarter_summary"
    }
  ]
}
```

Round 1-2 共享相同 corpus，cache-friendly schedule 会连续执行它们。

### 4.4 Estimate Plane 详细组成（已实现）

#### 4.4.1 KV Budget Estimation

**代码位置：** `v2/runtime/kv_budget.py:8-48`

**数据结构：**
```python
@dataclass(frozen=True)
class KVCacheModelProfile:
    num_hidden_layers: int
    num_key_value_heads: int
    head_dim: int
    dtype_bytes: int = 2  # FP16

    def kv_bytes_per_token(self) -> int:
        return (self.num_hidden_layers * 2 *
                self.num_key_value_heads *
                self.head_dim *
                self.dtype_bytes)
```

**Qwen3-8B 示例：**
```python
profile = KVCacheModelProfile(
    num_hidden_layers=28,
    num_key_value_heads=4,
    head_dim=128,
    dtype_bytes=2
)
# kv_bytes_per_token = 28 * 2 * 4 * 128 * 2 = 57344 bytes/token
```

#### 4.4.2 Reuse Estimation

**代码位置：** `v2/runtime/neural_state.py:122-178`

**核心函数：**
```python
def estimate_engine_local_prefix_reuse(
    rounds: list[RoundSpec],
    model_profile: KVCacheModelProfile
) -> dict[str, object]:
    corpus_reuse_tokens = sum(...)
    evidence_reuse_tokens = sum(...)
    return {
        "corpus_level_prefill_saved_tokens_estimate": corpus_reuse_tokens,
        "engine_local_prefill_saved_tokens_estimate": corpus_reuse_tokens + evidence_reuse_tokens,
        ...
    }
```

**KV demo 实测：**
- Corpus-level estimate: 2144 tokens
- Engine-local estimate: 2680 tokens
- 差值 536 tokens 来自 evidence prefix reuse

### 4.5 Mechanism Plane 缺失部分（未执行）

#### 4.5.1 需要的组件

| 组件 | 代码状态 | 部署状态 | 数据状态 |
|------|----------|----------|----------|
| Local vLLM service (`--enable-prefix-caching`) | 部署文档已有 | **未部署** | N/A |
| `kv_prefix_experiment.py` streaming TTFT probe | 代码已实现 | 未执行 | 无数据 |
| vLLM `/metrics` prefix_cache_hits_total 采集 | 代码已实现 | 未执行 | 无数据 |
| Cache-friendly vs cache-hostile 对照实验 | Scheduler 已实现 | 未执行 | 无数据 |
| Quality floor 验证（确保 cache 不影响质量） | Demo 10/10 | 需在 vLLM 下重新验证 | 无数据 |

#### 4.5.2 缺失的 Metrics

**需要从 vLLM `/metrics` 端点采集：**
- `vllm:gpu_prefix_cache_queries_total`（总查询数）
- `vllm:gpu_prefix_cache_hits_total`（命中数）
- `vllm:gpu_prefix_cache_hit_rate`（命中率，可能需要计算）
- Per-request TTFT（Time To First Token，streaming API）

**当前状态：** 代码中有采集逻辑，但因为 `STATEBUS_RUN_VLLM_PREFIX_PROBE=0` 所以从未执行

#### 4.5.3 预期的 Mechanism Evidence

**如果 vLLM probe 通过，应该得到：**

```json
{
  "cache_friendly": {
    "hit_rate": 0.75,
    "ttft_p50_ms": 42.3,
    "quality_floor_pass_rate": 1.0
  },
  "cache_hostile": {
    "hit_rate": 0.12,
    "ttft_p50_ms": 89.7,
    "quality_floor_pass_rate": 1.0
  },
  "delta": {
    "hit_rate_improvement": 0.63,
    "ttft_improvement_ms": -47.4,
    "quality_maintained": true
  }
}
```

**这会把 claim 从 "estimate" 升级到 "mechanism verified"**

### 4.6 从 Estimate 到 Mechanism 的 5 步路径（可执行指南）

**步骤1：部署本地 vLLM 服务**
```bash
python3 -m vllm.entrypoints.openai.api_server \
  --model $HOME/statebus/models/Qwen3-8B \
  --enable-prefix-caching \
  --max-model-len 8192 \
  --max-num-seqs 1 \
  --host 127.0.0.1 --port 8000

# 验证
curl http://127.0.0.1:8000/metrics | grep prefix_cache
```

**步骤2：运行 cache-friendly probe**
```bash
export STATEBUS_RUN_VLLM_PREFIX_PROBE=1
export STATEBUS_VLLM_BASE_URL=http://127.0.0.1:8000/v1
export STATEBUS_VLLM_METRICS_URL=http://127.0.0.1:8000/metrics

python -m v2.benchmark.kv_prefix_experiment \
  --family kv_prefix_reuse_v1 \
  --mode cache_friendly \
  --output /tmp/cache_friendly.json
```

**步骤3：重启 vLLM（清空 cache）**
```bash
# Kill and restart vLLM service
```

**步骤4：运行 cache-hostile probe**
```bash
python -m v2.benchmark.kv_prefix_experiment \
  --family kv_prefix_reuse_v1 \
  --mode cache_hostile \
  --output /tmp/cache_hostile.json
```

**步骤5：生成对比报告**
```bash
python -m v2.benchmark.kv_prefix_experiment \
  --mode compare \
  --friendly /tmp/cache_friendly.json \
  --hostile /tmp/cache_hostile.json \
  --output /tmp/summary.json
```

**通过标准：**
- Friendly hit rate >= 0.5
- Hit rate delta >= 0.3
- TTFT improvement >= 20ms
- Quality maintained (both 1.0)

**详细执行计划见：** 文档2 `16_executable_fix_plan.md` 的 "KV-1 独立验证" 章节

### 4.7 当前 Claim 边界的精确描述

#### 4.7.1 可以 Claim（有充分证据）

**Control-Plane Prototype：**
> StateBus 实现了 Engine-Local Prefix Reuse 的 control-plane prototype，包括：
> - Neural Prefix Identity 计算（corpus + evidence 两级 hash）
> - Engine-Local Prefix Registry（lease/release/query 机制）
> - Prefix Layout Compiler（支持 alignment mode 配置）
> - 单测 9/9 通过，control-plane 逻辑验证完整

**Cache-Aware Scheduling：**
> 实现了 cache-friendly vs cache-hostile scheduling，通过调整 corpus-locality 顺序影响 prefix reuse。KV demo 10/10 质量通过，corpus_prefix_hash_reuse_count=8，证明 scheduling 逻辑正确。

**Estimate 方法：**
> 基于 KVCacheModelProfile 实现 engine-local prefix reuse 的 token-level estimate。Qwen3-8B 上 corpus-level 可节省 2144 tokens，engine-local 可节省 2680 tokens。

#### 4.7.2 不能 Claim（证据不足）

**真实 vLLM Prefix Cache Hit：**
> 不能说"在 vLLM 上实现了 X% 的 prefix cache hit rate"——因为没有执行 vLLM probe。

**TTFT 改善：**
> 不能说"cache-friendly schedule 比 cache-hostile 快 X ms"——因为没有 streaming TTFT 测量数据。

**KV Tensor 传递：**
> 不能说"实现了 KV tensor 在 Agent 间的直接传递"——当前只是控制面 metadata，没有 data-plane tensor export。

#### 4.7.3 推荐的答辩表述

**当前状态（无 vLLM probe）：**
> StateBus 作为 Cache-Aware Agent Runtime，实现了 Engine-Local Prefix Reuse 的 control-plane prototype。通过 Neural Prefix Identity 计算、Engine-Local Prefix Registry 和 cache-aware scheduling，使 LLM 推理引擎的 automatic prefix caching 从随机命中提升为系统可规划的优化方向。Control-plane estimate 显示 engine-local 可节省 2680 tokens，KV demo 10/10 质量通过且 corpus reuse count=8，证明方法可行。Mechanism validation（vLLM metrics probe）作为下一步工作。

**升级后（如果 vLLM probe 通过）：**
> StateBus 作为 Cache-Aware Agent Runtime，实现了 Engine-Local Prefix Reuse 并通过 vLLM 验证。在 cache-friendly schedule 下，prefix cache hit rate 达到 X%，TTFT 相比 cache-hostile schedule 降低 Y ms，同时保持质量不变（quality floor pass rate 100%）。Control-plane scheduling 使 LLM 推理引擎的 automatic prefix caching 从随机命中提升为系统可规划的优化。

### 4.8 技术风险和缓解方案

#### 风险1：vLLM 版本兼容性

**风险：** vLLM prefix caching 在不同版本中 API 和 metrics 名称可能不同

**缓解：**
- 提前测试 vLLM 版本（推荐 v0.4.0+）
- 检查 `/metrics` 端点的实际字段名
- 代码中增加 version detection 和 fallback logic

#### 风险2：Prefix alignment 精度要求

**风险：** vLLM APC 要求 block-level（16 tokens）精确匹配，token-level 不对齐会导致 miss

**缓解：**
- 在 `compile_prefix_layout` 中增加 block alignment padding
- 检查 corpus/evidence prefix 是否在 block boundary 上对齐
- 如果 hit rate 为 0，首先检查 alignment

#### 风险3：Cache capacity 不足

**风险：** vLLM cache capacity 设置过小，导致频繁 eviction

**缓解：**
- 启动 vLLM 时配置足够大的 cache（`--gpu-memory-utilization 0.9`）
- 监控 vLLM 日志中的 cache eviction 消息
- 必要时减少并发请求数（`--max-num-seqs 1`）

#### 风险4：Quality 下降

**风险：** vLLM prefix caching 可能改变 generation behavior（理论上不应该，但需验证）

**缓解：**
- 对照 control-plane demo 的 10/10 质量
- 如果 quality 下降，检查是否是 vLLM sampling 配置问题
- 考虑关闭 prefix caching 重新跑对照组

### 4.9 决策建议

**推荐做 vLLM probe，如果：**
1. 本地 vLLM 环境容易搞定（< 2h）
2. 有 3-4 小时连续时间进行环境调试
3. 核心交付项（P0）已完成
4. 想在答辩中有更强的创新加分

**推荐暂缓 vLLM probe，如果：**
1. vLLM 环境复杂（GPU driver/CUDA 版本问题）
2. 时间紧张，P1 核心项目还没完成
3. 答辩重点是 quality-superiority + token reduction，KV 是锦上添花
4. 可以在答辩后补充 validation

**无论做不做，都要：**
1. 在答辩材料中说明 control-plane 已实现（有代码+单测+demo）
2. 准备回答"为什么没有 vLLM metrics"（环境约束 or 优先级选择）
3. 强调方法论正确、实现路径清晰、只是工程落地问题

---

## 五、面向赛题评分的 Claim 对齐

### 5.1 通信效率（25分）

**当前可写：**
- Prompt tokens 降低 57.9%，total tokens 降低 49.7%（full-registry 25/5 external compare）
- Formal internal L2 vs L0 prompt bytes 降低 45.2%
- Carrier compare structured vs text control bytes 降低 30665

**不能写：**
- Latency/速度优势
- Total-token efficiency superiority（strict equal-quality 不成立）

**升级需要：**
- Serialized repeat rerun（如果想写 latency）
- V2 formal text vs protocol 双模 token delta（加强通信效率维度证据）

### 5.2 状态传递创新（20分）

**当前可写：**
- Embedding semantic state + memfd data plane 25 次 transfer
- StateRef/hydration accounting 使下游 role 看到的 visible evidence 减少
- Flagship 5 个 claimable families 中 StateRef 有额外 prompt savings
- Engine-Local Prefix Reuse：control-plane + schedule + estimate 已实现

**不能写：**
- KV tensor transfer
- Hidden-state 跨 Agent 传递
- Raw evidence 完全不进 prompt
- Universal 所有任务都受益

**升级需要：**
- vLLM prefix probe 通过（从 estimate 升级为 mechanism evidence）
- Evidence pack non-text materialization stage（如果要写 evidence 不进 prompt）

### 5.3 记忆复用效果（20分）

**当前可写：**
- 18 validated replay / 2 exact replay
- answer_restoration=0（不是 answer restoration 伪装）
- L3 reuse_gain=20（continuous-replay）
- History artifact reuse 50，step reduction 13
- Replay negative audit 7/7 pass

**不能写：**
- 3/3 replay headline families（base 只有 2/3，supplement 关闭缺口但需合并判定）
- Generic answer restoration
- All-family quality headline

**升级需要：**
- 修复 `long_doc_metric_replay_v1` missing round 7 + rerun
- Base + supplement 合并判定脚本

### 5.4 系统完整性（20分）

**当前可写：**
- 4 agents 协同，API 四角色路径
- 30 轮连续任务稳定
- CodeAct bwrap 5/5
- UDS typed Protobuf control plane
- pytest 115 + smoke + formal + continuous all pass

**不能写：**
- openEuler 24.03 最终验证
- nsjail production sandbox
- Subprocess benchmark 验证

**升级需要：**
- openEuler VM smoke + pytest pass（交付阻塞）

### 5.5 实验验证（15分）

**当前可写：**
- Full-registry 25/5 formal compare 有完整 artifact
- Fairness gate 25/25，token split schema v1
- Continuous 30 rounds × 3 families × 2 modes
- Replay negative 7/7
- CodeAct 5/5
- KV prefix demo 10/10

**不能写：**
- Latency 对比数据
- Serialized repeat rerun 证据
- openEuler 验证
- vLLM mechanism 验证

**升级需要：**
- Serialized repeat rerun（即使结果不利也要跑，说明系统开销来源）
- openEuler validation
- vLLM probe（如果想增加创新分）

---

## 六、执行优先级总结

### P0（交付阻塞，必须在答辩前完成）

| # | 任务 | 预计耗时 | 依赖 |
|---|---|---|---|
| 1 | openEuler VM validation | 2-4h | VM 环境可用 |
| 2 | 演示视频制作 | 3-5h | 主要实验 artifact 就位 |

### P1（显著影响评分，强烈建议完成）

| # | 任务 | 预计耗时 | 提升维度 |
|---|---|---|---|
| 3 | Carrier compare route miss 修复 + rerun | 2-3h | 通信效率 |
| 4 | Replay missing round 修复 + rerun | 2-3h | 记忆复用 |
| 5 | Serialized timing rerun（即使负结果） | 4-6h | 实验验证（至少排除疑点） |
| 6 | vLLM prefix probe | 3-5h | 状态传递创新 |
| 7 | Formal text vs protocol token delta 提取并写入 summary | 1h | 通信效率 |

### P2（锦上添花，有时间就做）

| # | 任务 | 预计耗时 | 提升维度 |
|---|---|---|---|
| 8 | Flagship stress family-level 修复 | 4-8h | 状态传递创新 |
| 9 | Subprocess benchmark stage | 3-5h | 系统完整性 |
| 10 | Base + supplement 合并判定脚本 | 2h | 实验验证 |
| 11 | Memfd fallback stage | 2h | 系统完整性 |

---

## 七、答辩中的注意事项

### 7.1 必须主动承认的负面结果

1. **Latency 更慢**：StateBus 比 external pure-text 更慢，原因是 CodeAct/persist/telemetry/memfd/strict JSON 的系统开销。这是可审计性的成本，不是设计缺陷。
2. **Completion tokens 上升 80.5%**：严格 JSON role surface 的代价。但 prompt 和 total tokens 都下降。
3. **Flagship 不是 all-pass**：`incident_diagnosis_v2` 是负例，说明方法不是万能的。
4. **KV prefix 只是 estimate**：没有 vLLM metrics 前不能说"命中"。

### 7.2 如何转化负面结果为加分

1. Latency：说明系统选择了可审计/可复现/可追踪而不是速度；真实系统需要这些能力。
2. Completion inflation：换来了 scorer 和 replay 的稳定性；结构化输出是系统工程必需。
3. 负例 family：说明系统有自我诊断能力，不会所有任务都强行 claim 成功。
4. KV estimate：说明方法论正确（control-plane + scheduling），证据积累路径清晰。

### 7.3 绝对不要说的

- "StateBus 更快"
- "KV tensor 在 Agent 间传递"
- "hidden-state handoff 已实现"
- "所有任务都受益"
- "openEuler 上验证通过"（除非真的跑了）
- "效率全面优于纯文本"
