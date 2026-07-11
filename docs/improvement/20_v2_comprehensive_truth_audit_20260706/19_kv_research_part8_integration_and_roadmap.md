# 第五部分：集成与落地计划

## 1. 代码集成方案

### 1.1 参数控制方式

**推荐方案**: 配置文件 + CLI 参数 + 环境变量（三层）

#### 配置文件（推荐用于稳定配置）

**文件**: `deploy/statebus_llm.yaml.local`

```yaml
# KV 相关配置
kv_optimization:
  # 是否启用 prefix alignment（默认关闭）
  prefix_alignment_enabled: false
  prefix_alignment_mode: shared_evidence_prefix
  
  # 是否启用 evidence pruning（默认关闭）
  evidence_pruning_enabled: false
  evidence_pruning_threshold: 0.6
  
  # 是否启用 corpus-aware scheduling（默认关闭）
  corpus_scheduling_enabled: false
  corpus_scheduling_mode: cache_friendly
  
  # vLLM metrics 采集
  vllm_metrics_url: http://localhost:8000/metrics
  ttft_measurement_enabled: false
```

#### CLI 参数（推荐用于单次实验）

```bash
python -m v2.benchmark.live_runner \
  --suite formal \
  --role-path-mode local_vllm \
  --enable-kv-prefix-alignment \          # 启用 prefix alignment
  --enable-kv-corpus-scheduling \         # 启用 corpus scheduling
  --enable-kv-evidence-pruning \          # 启用 evidence pruning
  --kv-schedule-plan cache_friendly       # 指定 schedule plan
```

#### 环境变量（兼容旧代码）

```bash
export STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix
export STATEBUS_EVIDENCE_PRUNING_THRESHOLD=0.6
export STATEBUS_KV_CORPUS_SCHEDULING=cache_friendly
```

**优先级**: CLI 参数 > 环境变量 > 配置文件 > 代码默认值

### 1.2 Benchmark Suite 划分

**推荐方案**: 不新增 suite，使用 explicit family + flag 控制

#### 现有 Suite（保持不变）

```bash
# Non-KV baseline（默认）
python -m v2.benchmark.live_runner --suite formal

# KV 机制验证（explicit family）
python -m v2.benchmark.live_runner \
  --family kv_prefix_reuse_v1 \
  --enable-kv-prefix-alignment
```

#### 不推荐的方案

❌ **不推荐**: 新增 `--suite kv_formal`

**理由**:
1. KV 和 Non-KV 共享相同的 task family
2. 只是运行时配置不同，不是不同的 suite
3. 新增 suite 会导致维护负担

### 1.3 Git 分支策略

**当前分支**: `feat/local-hidden-kv-prototype`

**推荐策略**: 继续使用当前分支，完成后 tag 固化

#### Phase 1-3: 在当前分支开发

```bash
# 当前分支
git checkout feat/local-hidden-kv-prototype

# 每个 phase 完成后 commit
git add .
git commit -m "phase1: complete local vllm deployment and validation"
```

#### Phase 4: Tag 固化

```bash
# 如果 KV 实验成功
git tag v2-kv-baseline-20260710
git push origin v2-kv-baseline-20260710

# 如果 KV 实验失败，回退到 non-KV tag
git checkout v2-non-kv-baseline-20260710
```

#### 不推荐的方案

❌ **不推荐**: 新开 `feat/kv-v2` 分支

**理由**:
1. 当前分支已包含完整 KV 代码
2. 新开分支会导致 non-KV 和 KV 代码分离
3. 增加合并复杂度

---

## 2. 报告结构建议

### 2.1 Non-KV 基础章节（已有内容）

**章节结构**（保持不变）:

```markdown
# StateBus v2 系统报告

## 第一部分：系统概述
- 赛题要求对照
- 三个核心维度完成情况

## 第二部分：低开销通信
- Prompt token reduction: -57.9%
- Protocol control plane: 0.5%
- 证据：r01_07 formal compare

## 第三部分：非文本状态传递
- Semantic StateRef transfer: 25/25
- Backend: memfd + shared_memory
- 证据：formal internal reports

## 第四部分：共享记忆复用
- Validated replay: 18
- Reuse gain: 17%
- 证据：x27/x28 continuous collection

## 第五部分：系统完整性
- CodeAct acceptance: 5/5
- Artifact audit: 2373 sidecars
- Quality gates
```

### 2.2 KV 增量章节（新增内容）

**插入位置**: 第五部分之后

**章节结构**:

```markdown
## 第六部分：KV Cache 优化（增量验证）

### 6.1 KV 优化定位

**不是什么**:
- 不是跨 Agent KV tensor 传递
- 不是跨进程 KV 共享
- 不是模型内部 KV 剪枝

**是什么**:
- Engine-Local Prefix Reuse 控制面
- Cache-Aware Agent Runtime
- Prefix alignment + Corpus scheduling + Evidence pruning

### 6.2 创新点

#### 6.2.1 Prefix Layout Compiler
- 多 Agent prompt 编译成 shared prefix + role suffix
- 主动构造 token-level 相等性
- 证据：PrefixLayoutPlan audit

#### 6.2.2 Corpus-Aware Scheduling
- 基于 corpus_prefix_hash 调度任务顺序
- 提高 cache 驻留时间
- 证据：cache-friendly vs cache-hostile 对比

#### 6.2.3 ReplayClass × KV Reuse Pyramid
- 统一记忆复用和 KV prefill 成本
- 4 层优化金字塔
- 证据：kv_analysis report

### 6.3 实验结果

#### 6.3.1 机制验证（kv_prefix_reuse_v1）
- Cache hit rate: X% (baseline) → Y% (KV enabled)
- TTFT: Z ms → W ms (-A%)
- Quality: 10/10 maintained

#### 6.3.2 真实场景验证（cross_period_financial_v1）
- Cache hit rate: X% → Y%
- TTFT: Z ms → W ms (-A%)
- Quality: N/M (≥ baseline - 1)

#### 6.3.3 增量收益分析
- Prefix alignment 贡献: +X% hit rate
- Corpus scheduling 贡献: +Y% hit rate
- Evidence pruning 贡献: -Z% tokens

### 6.4 与 Non-KV 的关系

**KV 是增量优化，不是替代方案**:
- Non-KV baseline 已完成赛题三个核心维度
- KV 优化在 Non-KV 基础上进一步提升性能
- 如果 KV 失败，Non-KV 仍是完整方案

### 6.5 技术边界

**当前实现边界**:
- Engine-local: KV cache 在 vLLM engine 内部
- Observability: 通过 `/metrics` 采集，不导出 KV tensor
- Control-plane only: registry 只记录 metadata，不持有 KV

**Future Work**:
- Prefix delta compression
- Multi-model KV compatibility
- 跨引擎 KV lease 协调
```

### 2.3 如何呈现 KV 作为 optional 增强

**关键原则**:

1. **Non-KV 先讲完整**
   - 第一到五部分独立成章
   - 赛题三个核心维度全部在 Non-KV 中完成

2. **KV 作为第六部分**
   - 明确标注"增量验证"
   - 强调"Engine-Local Prefix Reuse"
   - 数据对比用本地环境公平对比（Non-KV vs KV，same model）

3. **答辩时的呈现顺序**
   - 主讲: Non-KV 完成赛题要求（10 分钟）
   - 补充: KV 作为创新加分（5 分钟）
   - 如果被问: 详细解释 KV 机制（5 分钟）

4. **Slides 结构建议**

```text
Slide 1-5:   系统概述 + 赛题对照
Slide 6-10:  Non-KV 三个核心维度
Slide 11-15: 系统完整性 + 评测方法
Slide 16-18: KV 增量优化（可选讲）
Slide 19-20: 总结 + Q&A
```

---

## 3. 风险隔离措施

### 3.1 如何确保 KV 代码不影响 Non-KV baseline

#### 措施 1: 默认关闭

**代码检查清单**:
```python
# ✅ 正确：默认关闭
if os.getenv("STATEBUS_PREFIX_ALIGNMENT_MODE") == "shared_evidence_prefix":
    # KV path
else:
    # Non-KV path (default)

# ❌ 错误：默认打开
if os.getenv("STATEBUS_PREFIX_ALIGNMENT_MODE") != "disabled":
    # KV path (default)
```

**验证命令**:
```bash
# 不设置任何 KV 环境变量，应该走 Non-KV path
python -m v2.benchmark.live_runner --suite formal --role-path-mode api

# 检查 report 中不应出现 KV 相关字段
grep -r "prefix_alignment_enabled" runs/*/benchmark_reports/*.json
# 预期: 无输出或 false
```

#### 措施 2: 独立 flag 控制

**CLI 参数设计**:
```bash
# Non-KV（默认）
python -m v2.benchmark.live_runner --suite formal

# KV（显式启用）
python -m v2.benchmark.live_runner --suite formal --enable-kv-optimization
```

**实现建议**:
```python
@click.option("--enable-kv-optimization", is_flag=True, default=False)
def main(enable_kv_optimization: bool):
    if enable_kv_optimization:
        # Load KV config
        kv_config = load_kv_config()
    else:
        # Skip KV entirely
        kv_config = None
```

#### 措施 3: Separate report section

**Report 结构**:
```json
{
  "schema_version": "statebus.benchmark_report.v2",
  "core_metrics": {
    "quality": 25,
    "prompt_tokens": 52743,
    // Non-KV 核心指标
  },
  "kv_optimization": {
    "enabled": false,  // 默认 false
    "prefix_alignment": null,
    "corpus_scheduling": null,
    // KV 相关字段只在 enabled=true 时填充
  }
}
```

### 3.2 如何快速回退（如果 KV 实验失败）

#### 回退步骤

**Step 1: 停止 KV 实验**
```bash
# 杀掉 vLLM server
pkill -f vllm.entrypoints.openai.api_server

# 清理实验产物
rm -rf experiments/kv_*
```

**Step 2: 切换到 Non-KV tag**
```bash
git checkout v2-non-kv-baseline-20260710
```

**Step 3: 验证 Non-KV 仍然可用**
```bash
python -m v2.runtime.smoke --role-path-mode api
# 预期: exit 0
```

**Step 4: 更新报告**
```markdown
# 删除或注释 KV 章节
## ~~第六部分：KV Cache 优化~~

# 在 Future Work 中提及
### Future Work
- Engine-Local Prefix Reuse（初步探索，需要进一步验证）
```

#### 回退决策点

**触发回退的条件**:

1. **Phase 1 失败**: 本地模型质量 < API 质量 - 2
   - 回退到 Non-KV API baseline
   - KV 改为 "mechanism exploration only"

2. **Phase 2 失败**: 代码审查发现严重缺陷
   - 回退到 Non-KV
   - 记录技术债务，Future Work

3. **Phase 3 失败**: KV 无增量收益或损失质量
   - 回退到 Non-KV
   - KV 改为 "negative finding: prefix alignment does not improve cache hit rate in our scenario"

**不触发回退的情况**:

- KV 收益小但不为负（如 hit rate +5%，TTFT -10%）
  - 保留 KV 章节，诚实报告收益范围

- 部分 family 有收益，部分无收益
  - 保留 KV 章节，明确适用边界

### 3.3 如何保持 v2-non-kv-baseline-20260710 tag 的稳定性

#### 原则

**Tag 是不可变的**:
- 一旦 tag 创建，不允许修改
- 任何修改都应该是新 commit + 新 tag

#### 保护措施

**Step 1: Tag 后立即验证**
```bash
git tag v2-non-kv-baseline-20260710
git push origin v2-non-kv-baseline-20260710

# 立即在另一个目录 checkout 验证
cd /tmp
git clone /home/qcrs/statebus/project statebus-verify
cd statebus-verify
git checkout v2-non-kv-baseline-20260710
python -m v2.runtime.smoke
```

**Step 2: 归档 artifact roots**
```bash
# 压缩保存关键 runs
tar -czf archives/v2-non-kv-baseline-20260710-runs.tar.gz \
  runs/v2-local-api-non-kv-20260709_002546-core \
  runs/v2-local-api-non-kv-followup-20260709_083750-*

# 归档 deep mining 产物
tar -czf archives/v2-non-kv-baseline-20260710-mining.tar.gz \
  docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_api_non_kv_followup_20260709_083750/deep_mining
```

**Step 3: 文档固化**
```bash
# 创建 snapshot 文档
cat > docs/snapshots/v2-non-kv-baseline-20260710-README.md << 'EOD'
# v2-non-kv-baseline-20260710 Snapshot

## 核心 Claim
- Low-overhead communication: prompt token -57.9%
- Non-text state transfer: 25/25 semantic transfer
- Shared memory reuse: validated replay 18, reuse gain 17%

## 关键证据
- Core r01_07: 25/25 vs 16/25, prompt -63268, total -67989
- Formal internal: memfd + shared_memory both 25/25
- Continuous x28: validated replay 18, exact replay 2

## Git Reference
- Tag: v2-non-kv-baseline-20260710
- Commit: <commit_hash>
- Branch: feat/local-hidden-kv-prototype

## Artifact Roots
- Core run: /home/qcrs/statebus/runs/v2-local-api-non-kv-20260709_002546-core
- Follow-up runs: /home/qcrs/statebus/runs/v2-local-api-non-kv-followup-20260709_083750-*

## 报告路径
- Deep analysis: docs/improvement/.../14_local_api_non_kv_followup_deep_analysis_20260709.md
- Review: docs/improvement/.../15_local_api_non_kv_followup_review_20260709.md
- Decision: docs/improvement/.../16_phase_transition_decision_kv_readiness_20260710.md
EOD
```

---

## 4. 详细执行步骤（时间线）

### Phase 1: 环境准备与验证（1-2 天）

#### Day 1 Morning: vLLM 部署

**任务清单**:
- [ ] 安装 vLLM 0.8.0+
- [ ] 下载 Qwen3-32B fp16 模型（或验证已有模型）
- [ ] 启动 vLLM server with `--enable-prefix-caching`
- [ ] 验证 `/health` 和 `/v1/models` endpoints

**执行命令**:
```bash
pip install vllm==0.8.0
python -m vllm.entrypoints.openai.api_server \
  --model /home/qcrs/statebus/models/Qwen3-32B \
  --dtype float16 \
  --enable-prefix-caching \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 1 \
  --host 0.0.0.0 \
  --port 8000 \
  --served-model-name qwen3-32b
```

**验证**:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/v1/models
```

**Go/No-go**: 如果 vLLM 启动失败或模型加载失败 → 检查 CUDA/driver 版本

#### Day 1 Afternoon: Smoke Test

**任务清单**:
- [ ] 配置 `statebus_llm.yaml.local` 添加 local_vllm 配置
- [ ] 运行 StateBus smoke test
- [ ] 验证 vLLM metrics 可采集

**执行命令**:
```bash
python -m v2.runtime.smoke --role-path-mode local_vllm
curl http://localhost:8000/metrics 2>/dev/null | grep prefix_cache
```

**Go/No-go**: 如果 smoke test 失败 → 检查模型质量或 StateBus 配置

#### Day 2: 质量验证

**任务清单**:
- [ ] Mini formal (5 cases)
- [ ] 对比 local vs API 质量
- [ ] Full formal (25 cases) 如果 mini 通过

**执行命令**:
```bash
# Mini formal
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier dev \
  --role-path-mode local_vllm \
  --max-cases 5

# Full formal（如果 mini 通过）
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier formal \
  --role-path-mode local_vllm
```

**Go/No-go**:
- Mini ≥ 4/5 → 继续 full formal
- Full ≥ 24/25 → Phase 1 成功，进入 Phase 2
- Full < 24/25 → 考虑换更大模型或降级 KV claim

---

### Phase 2: 代码审查与增强（2-3 天）

#### Day 3: 修复技术债务

**任务清单**:
- [ ] P1.1: 补充单元测试（`test_neural_state.py`, `test_kv_analysis.py`）
- [ ] P1.3: 补充 kv_prefix_reuse_v1 corpus 数据文件
- [ ] P2.1: 配置文件支持（可选）

**执行步骤**:
```bash
# 补充单元测试
vi tests/v2/test_neural_state.py
pytest tests/v2/test_neural_state.py -v

# 补充 corpus 数据（创建或复制）
vi v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/orion_factory_ops_report_2026.md
vi v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/nova_retail_ops_report_2026.md
```

**验证**:
```bash
pytest tests/v2/ -k neural_state
ls v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/*.md
```

#### Day 4-5: 实施 P1 优化（可选）

**任务清单**:
- [ ] Budget-Aware Dynamic Pruning
- [ ] Multi-Level Prefix Hierarchy（如果时间允许）

**代码位置**:
- `v2/retrieval/models.py`: 添加 `dynamic_pruning_threshold`
- `v2/runtime/role_path.py`: 扩展 `compile_prefix_layout` 支持多层

**验证**:
```bash
pytest tests/v2/ -v
python -m v2.runtime.smoke --role-path-mode local_vllm
```

**Go/No-go**: 如果优化引入 bug → 回退，Phase 2 只完成债务修复

---

### Phase 3: 实验执行（3-5 天）

#### Day 6: Tier 1 机制验证

**任务清单**:
- [ ] E1-E4: kv_prefix_reuse_v1（4 个实验）
- [ ] 采集 vLLM metrics delta
- [ ] 生成 KV summary report

**执行命令**:
```bash
bash scripts/run_kv_experiment.sh E1 kv_prefix_reuse_v1 configs/local_non_kv.yaml
bash scripts/run_kv_experiment.sh E2 kv_prefix_reuse_v1 configs/local_kv_alignment.yaml
bash scripts/run_kv_experiment.sh E3 kv_prefix_reuse_v1 configs/local_kv_cache_friendly.yaml
bash scripts/run_kv_experiment.sh E4 kv_prefix_reuse_v1 configs/local_kv_cache_hostile.yaml
```

**预期**:
- E2 cache hit rate > E1
- E3 TTFT < E4
- All quality ≥ 9/10

**Go/No-go**: 如果 E2/E3 无增量收益 → Phase 3 失败，回退到 Non-KV

#### Day 7-8: Tier 2 真实场景验证

**任务清单**:
- [ ] E5-E7: cross_period_financial_v1（3 个实验）
- [ ] 对比 KV vs Non-KV 增量收益
- [ ] 质量门验证

**执行命令**:
```bash
bash scripts/run_kv_experiment.sh E5 cross_period_financial_v1 configs/local_non_kv.yaml
bash scripts/run_kv_experiment.sh E6 cross_period_financial_v1 configs/local_kv_alignment.yaml
bash scripts/run_kv_experiment.sh E7 cross_period_financial_v1 configs/local_kv_full.yaml
```

**预期**:
- E6 TTFT < E5 (目标 -15% to -30%)
- E6 quality ≥ E5 - 1
- E7 cache hit rate > E6

**Go/No-go**: 如果质量损失 > 1 → KV 只能作为 mechanism probe

#### Day 9-10: Tier 3 全量验证（可选）

**任务清单**:
- [ ] E8-E9: Full formal 25（2 个实验）
- [ ] 生成最终对比报告

**执行命令**:
```bash
bash scripts/run_kv_experiment.sh E8 formal configs/local_non_kv.yaml
bash scripts/run_kv_experiment.sh E9 formal configs/local_kv_full.yaml
```

**预期**:
- E8 ≥ 24/25
- E9 ≥ 23/25
- E9 avg TTFT < E8

---

### Phase 4: 报告集成与答辩准备（1-2 天）

#### Day 11: 报告集成

**任务清单**:
- [ ] 将 KV 实验结果写入报告第六部分
- [ ] 生成可视化图表（cache hit rate, TTFT 对比）
- [ ] 更新 README 和 CLAUDE.md

**产出文件**:
- `docs/reports/kv_optimization_results_20260710.md`
- `docs/reports/figures/kv_cache_hit_rate_comparison.png`
- `docs/reports/figures/kv_ttft_comparison.png`

#### Day 12: 答辩准备

**任务清单**:
- [ ] 准备答辩 slides（KV 部分 5 页）
- [ ] 模拟预期质疑 + 标准回答
- [ ] 最终 review

**Slides 内容**:
- Slide 1: KV 优化定位（Engine-Local Prefix Reuse）
- Slide 2: 三个创新点（Prefix Compiler, Corpus Scheduling, Pyramid）
- Slide 3: 实验设计（对照组 + 数据集）
- Slide 4: 实验结果（cache hit rate, TTFT, quality）
- Slide 5: 与 Non-KV 的关系（增量优化）

---

### 总预算确认

| Phase | 最少天数 | 最多天数 | 关键产出 |
|-------|---------|---------|---------|
| Phase 1 | 1 | 2 | 本地 vLLM 可用，质量 ≥ 24/25 |
| Phase 2 | 2 | 3 | 技术债务清理，P1 优化（可选） |
| Phase 3 | 3 | 5 | Tier 1+2 实验完成，KV 增量收益明确 |
| Phase 4 | 1 | 2 | 报告集成，答辩准备 |
| **总计** | **7** | **12** | **KV 研究完成或回退到 Non-KV** |

**关键里程碑**:
- Day 2 end: Phase 1 go/no-go
- Day 5 end: Phase 2 go/no-go
- Day 8 end: Phase 3 go/no-go
- Day 12 end: 报告和答辩材料完成

