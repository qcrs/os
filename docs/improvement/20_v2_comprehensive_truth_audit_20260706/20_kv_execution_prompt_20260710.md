# KV Cache 研究执行 Prompt

**日期**: 2026-07-10  
**目标**: 严格按照已制定的计划执行 KV 研究实验  
**执行者**: Claude (新会话)

---

## 任务概述

你需要执行 StateBus v2 的 KV Cache 研究实验。所有的分析、规划、决策都已完成，你的任务是**严格按照文档执行**，不要偏离计划。

## 上下文文档（必读顺序）

### 1. 快速了解背景

**文件**: `docs/improvement/20_v2_comprehensive_truth_audit_20260706/19_kv_research_executive_summary.md`

**关键信息**:
- Non-KV baseline 已完成赛题三个核心维度（25/25 quality, -57.9% prompt token, 17% reuse gain）
- KV 是增量优化，定位是 Engine-Local Prefix Reuse
- GPU 资源充足：3× A100 80GB
- 执行时间预算：7-12 天

### 2. 完整执行计划

**文件**: `docs/improvement/20_v2_comprehensive_truth_audit_20260706/19_kv_research_comprehensive_analysis_and_roadmap_20260710.md`

**重点章节**:
- **第三部分**：本地部署与测试策略（Phase 1）
- **第四部分**：实验设计方案（Phase 3）
- **第五部分**：集成与落地计划（详细时间线）

### 3. 技术决策参考

**文件**: `docs/improvement/20_v2_comprehensive_truth_audit_20260706/19_kv_research_appendix_kv_tensor_feasibility.md`

**用途**: 如果遇到质疑"为什么不做真正的 KV tensor 传递"，参考此文档

---

## 执行原则

### ✅ 必须遵守

1. **严格按照文档执行**：不要自己发挥，不要跳步骤
2. **执行前先读文档**：每个 Phase 开始前，先读取对应章节
3. **记录实际结果**：每个步骤的实际输出都要记录
4. **遵守 go/no-go 判断**：如果某个 Phase 失败，立即停止并报告
5. **保持透明**：每个决策点都要明确说明依据

### ❌ 禁止行为

1. **不要自己决策**：所有决策都在文档中，不要自己改变
2. **不要跳过验证**：每个验证步骤都必须执行
3. **不要优化文档**：即使发现更好的方法，也先按文档执行
4. **不要混入其他优化**：只做 KV 相关的实验

---

## 当前系统状态

### Git 分支
```
当前分支: feat/local-hidden-kv-prototype
Non-KV baseline tag: v2-non-kv-baseline-20260710
```

### 可用模型
```
路径: /data/models/
当前先测: Qwen3-8B
后续质量验证: Qwen3-32B (优先 2-GPU tensor parallel: GPU 0,1；单卡空闲时也可走单卡 profile)
备选: Qwen2.5-14B-Instruct (fp16, 28GB)
```

### Conda 环境
```
路径: /home/qcrs/statebus/conda-envs/vllm-qwen-cu121
Python: 3.10+
CUDA: 12.1
```

### GPU 资源
```
3× NVIDIA A100 80GB PCIe
Driver: 565.57.01
可用显存: 80 GB per card
```

---

## Phase 1: 环境准备与验证（1-2天）

### 执行目标
验证本地 vLLM 环境可用，且模型质量 ≥ API baseline

### Step 1: 激活环境并安装依赖

```bash
# 1.1 激活 vLLM conda 环境
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate /home/qcrs/statebus/conda-envs/vllm-qwen-cu121

# 1.2 验证环境
which python
python --version
nvidia-smi

# 1.3 检查 vLLM 是否已安装
python -c "import vllm; print(vllm.__version__)"

# 1.4 当前服务器已验证的稳妥组合
python -c "import torch; print(torch.__version__, torch.version.cuda)"
```

**验证标准**:
- Python 3.10+
- vLLM 当前已装且可 import（当前已验证口径是 `0.7.3 + torch 2.5.1+cu121`）
- nvidia-smi 显示 3× A100

**go/no-go**: 如果环境验证失败，停止并报告问题。不要在当前服务器上直接把 vLLM 升到 CUDA 13 口径。

### Step 2: 启动 vLLM Server

```bash
# 2.1 先用 Qwen3-8B 打通链路；卡被占用时不要先抢 32B
cd /home/qcrs/statebus/project
CUDA_VISIBLE_DEVICES=1 \
STATEBUS_VLLM_PORT=53333 \
scripts/start_vllm_qwen3_8b_prefix_cache.sh
```

**验证标准**:
- `curl -sf http://127.0.0.1:53333/health` 返回 exit code `0`（当前 `vllm==0.7.3` 可能是 HTTP 200 + 空 body）
- `curl http://127.0.0.1:53333/v1/models` 返回 model 列表
- served model name 为 `qwen3-8b`

**如果启动失败**:
```bash
# 查看日志
tail -50 /home/qcrs/statebus/logs/*

# 常见问题:
# - 端口占用: 改用其他端口
# - 8B 显存仍不足: 降级到 Qwen2.5-14B-Instruct
# - 模型路径错误: 检查 /data/models/Qwen3-8B 是否存在
```

**go/no-go**: 如果 8B 启动失败，优先尝试 Qwen2.5-14B-Instruct；如果仍失败，停止并报告

### Step 3: 在 root 容器里做 StateBus smoke

```bash
# 3.1 确保 root 容器按当前 compose 口径使用 host network
docker compose -f docker/compose.yaml up -d --force-recreate

# 3.2 推荐先 source 8B profile；后续切换到 32B 时只需要重新 source 另一个 profile
source deploy/activate_statebus_local_vllm_profile.sh qwen3-8b

# 3.3 使用 root 容器执行 helper；它会：
#   - 生成临时 local_vllm 配置
#   - 为 Qwen3 关闭 thinking（chat_template_kwargs.enable_thinking=false）
#   - source /usr/local/bin/activate_statebus_container.sh
#   - 在 statebus-dev-qcrs 中执行 smoke
scripts/run_v2_local_vllm_container_check.sh
```

**预期结果**:
- Exit code: 0
- 输出包含 "ok=true"

**如果失败**:
```bash
# 检查 host vLLM
curl http://127.0.0.1:53333/health

# 再次运行容器 helper，并改成 verbose smoke
scripts/run_v2_local_vllm_container_check.sh \
  /usr/bin/python3 -m v2.runtime.smoke --role-path-mode local_vllm --verbose
```

**go/no-go**: 如果 smoke test 失败，先修复配置问题；如果无法修复，停止并报告

### Step 4: 质量验证 - Mini Formal (5 cases)

```bash
# 4.1 在 root 容器里跑隔离 mini formal bundle
STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID=v2-local-vllm-qwen3-8b-dev-mini5 \
STATEBUS_LOCAL_VLLM_FORMAL_MAX_CASES=5 \
scripts/run_v2_local_vllm_formal_suite.sh
```

**预期结果**:
- 5/5 quality pass
- 或至少 4/5 quality pass

**记录实际结果**:
```bash
# 查看 summary
jq '.layers[] | {layer, quality_floor_pass_count}' \
  /home/qcrs/statebus/runs/v2-local-vllm-qwen3-8b-dev-mini5/formal_suite.summary.json
```

**go/no-go 判断**:
- ✅ 如果 ≥ 4/5: 继续 Step 6
- ⚠️ 如果 3/5: 考虑换更大模型或降低质量要求
- ❌ 如果 ≤ 2/5: 停止，模型质量不足

### Step 5: 32B Full Formal（当前不是第一优先）

只有在 32B 所需 GPU 资源空出来之后，才切换到 `Qwen3-32B` 做 full formal。当前 GPU 被占用时，不要把 32B full formal 当成 Phase 1 的先决条件。若 GPU 0 和 GPU 1 可用，优先使用 2-GPU tensor parallel profile。

```bash
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b-2gpu
scripts/start_vllm_qwen3_32b_prefix_cache.sh
```

如果改回单卡，只使用原单卡 profile：

```bash
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b
```

如果需要手动覆盖多卡设备，必须同时覆盖 tensor parallel size：

```bash
export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES=0,1
export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE=2
```

然后直接沿用同一套 formal wrapper，无需再手改 `base_url` / `model` / `port`。

### Step 6: Full Formal (25 cases, 仅 32B 阶段执行)

```bash
# 6.1 运行 full formal
STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID=v2-local-vllm-qwen3-32b-formal \
STATEBUS_LOCAL_VLLM_FORMAL_BENCHMARK_TIER=formal \
STATEBUS_LOCAL_VLLM_FORMAL_MAX_CASES= \
scripts/run_v2_local_vllm_formal_suite.sh
```

**预期时间**: 约 3 小时

**预期结果**: ≥ 24/25 quality pass

**记录实际结果**:
```bash
# 查看详细结果
jq '.layers[] | {layer, quality_floor_pass_count}' \
  /home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-formal/formal_suite.summary.json

# 如果有失败 case，查看是哪些
jq '.comparison_summary' \
  /home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-formal/formal_suite.summary.json
```

**go/no-go 判断**:
- ✅ 如果 ≥ 24/25: **Phase 1 成功**，进入 Phase 2
- ⚠️ 如果 22-23/25: 可以继续，但降低 KV claim 级别为 "mechanism probe"
- ❌ 如果 < 22/25: **Phase 1 失败**，停止 KV 研究，回退到 Non-KV baseline

### Phase 1 完成标准

- [ ] vLLM 启动成功
- [ ] Smoke test 通过
- [ ] Mini formal ≥ 4/5
- [ ] Full formal ≥ 24/25

**如果 Phase 1 成功**，输出一份报告：

```markdown
# Phase 1 完成报告

**日期**: YYYY-MM-DD
**执行时间**: X 小时

## 环境配置
- 模型: Qwen3-32B / Qwen2.5-14B-Instruct
- vLLM 版本: X.Y.Z
- Conda 环境: vllm-qwen-cu121

## 质量验证结果
- Smoke test: ✅ Pass
- Mini formal (5 cases): X/5
- Full formal (25 cases): X/25

## Go/No-go 判断
- ✅ 本地模型质量充分，可以进入 Phase 2

## 产物路径
- Run directory: runs/v2-local-vllm-YYYYMMDD_HHMMSS-formal
- Summary: runs/.../summary.json
- Benchmark reports: runs/.../benchmark_reports/

## 下一步
进入 Phase 2: 代码审查与增强
```

---

## Phase 2: 代码审查与增强（2-3天）

**重要**: Phase 2 开始前，再次阅读文档：
- `19_kv_research_comprehensive_analysis_and_roadmap_20260710.md` 第一部分（代码审查）
- `19_kv_research_part5_updated_new_directions.md`（创新点实现计划）

### Phase 2 目标

1. 修复 P1 技术债务（必须）
2. 实施优化方向 1: Budget-Aware Dynamic Pruning（必须）
3. 可选: 实施优化方向 2: Multi-Level Prefix Hierarchy

### Step 1: 修复 P1.3 - 补充 kv_prefix_reuse_v1 corpus 数据

**问题**: Manifest 引用的数据文件不存在

```bash
# 1.1 检查数据文件是否存在
ls v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/

# 1.2 如果文件不存在，读取 manifest 了解数据需求
cat v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/manifest.json | jq '.rounds[0]'
```

**创建数据文件**（如果不存在）:

参考文档中的说明，创建两个 corpus 文件：
- `orion_factory_ops_report_2026.md` (制造业运营报告)
- `nova_retail_ops_report_2026.md` (零售物流报告)

**要求**:
- 两份报告使用相同 schema（方便 corpus prefix 复用）
- 包含明确的数值数据（用于 deterministic validation）
- 文件大小适中（建议 2-3KB，约 1000 tokens）

**验证**:
```bash
# 验证文件存在
ls v2/benchmark/samples/continuous_task_families/kv_prefix_reuse/*.md

# 验证 manifest 可以加载
python -c "
from v2.benchmark.family_loader import load_family_manifest
manifest = load_family_manifest('kv_prefix_reuse_v1')
print(f'Loaded {len(manifest.rounds)} rounds')
"
```

**go/no-go**: 如果数据文件无法创建或 manifest 加载失败，Phase 2 无法继续

### Step 2: 实施优化方向 1 - Budget-Aware Dynamic Pruning

**严格按照文档执行**:
参考 `19_kv_research_part5_updated_new_directions.md` 中的详细步骤

#### Step 2.1: 创建 pruning.py

```bash
# 2.1.1 创建文件
touch v2/retrieval/pruning.py

# 2.1.2 复制文档中的代码
# 打开文档: 19_kv_research_part5_updated_new_directions.md
# 找到 "Step 2: 实现动态阈值计算函数"
# 复制完整代码到 v2/retrieval/pruning.py
```

#### Step 2.2: 扩展 EvidencePruningHint

```bash
# 编辑 v2/retrieval/models.py
# 按照文档添加新字段
```

#### Step 2.3: 单元测试

```bash
# 2.3.1 创建测试文件
touch tests/v2/test_dynamic_pruning.py

# 2.3.2 复制文档中的测试代码

# 2.3.3 运行测试
pytest tests/v2/test_dynamic_pruning.py -v
```

**预期**: 所有测试通过

**go/no-go**: 如果测试失败，修复后再继续

#### Step 2.4: 集成到 benchmark

```bash
# 2.4.1 更新配置文件
# 在 deploy/statebus_llm.yaml.local 添加 pruning 配置

# 2.4.2 验证集成
python -m v2.runtime.smoke --role-path-mode local_vllm
```

**预计时间**: 4 小时

### Step 3: 可选 - Multi-Level Prefix Hierarchy

**决策点**: 仅当以下条件满足时才实施

1. Step 1-2 在预算时间内完成
2. 有 3-4 小时剩余时间
3. 愿意承担 vLLM 验证风险

**如果不实施**: 直接进入 Phase 3

### Phase 2 完成标准

- [ ] P1.3 债务修复（corpus 数据文件）
- [ ] 优化方向 1 实施完成（dynamic pruning）
- [ ] 单元测试通过
- [ ] Smoke test 仍然通过

**Phase 2 完成后**，输出报告并提交代码:

```bash
# Commit
git add .
git commit -m "phase2: complete P1 debt fix and dynamic pruning implementation

- Fix P1.3: add kv_prefix_reuse_v1 corpus data files
- Implement Budget-Aware Dynamic Pruning
- Add unit tests for dynamic threshold calculation
- Update configuration for pruning support

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3: 实验执行（3-5天）

**重要**: Phase 3 开始前，再次阅读文档第四部分（实验设计方案）

### Phase 3 目标

执行 KV vs Non-KV 对比实验，采集数据，验证增量收益

### Tier 1: 机制验证 (kv_prefix_reuse_v1)

**必须完成**，这是 KV 研究的核心证据

#### 实验 E1: Baseline (Non-KV)

```bash
# E1: 本地 Non-KV baseline
python -m v2.benchmark.live_runner \
  --family kv_prefix_reuse_v1 \
  --role-path-mode local_vllm

# 采集 vLLM metrics (before/after)
curl -s http://localhost:8000/metrics > experiments/E1_metrics_before.txt
# 运行 benchmark
curl -s http://localhost:8000/metrics > experiments/E1_metrics_after.txt
```

**记录**:
- Run directory
- Quality: X/10
- Cache hit rate (from metrics)
- TTFT (if available)

#### 实验 E2: Treatment 1 (Prefix Alignment)

```bash
# E2: 启用 prefix alignment
export STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix

python -m v2.benchmark.live_runner \
  --family kv_prefix_reuse_v1 \
  --role-path-mode local_vllm
```

**预期**:
- Quality: 保持 ≥ E1 - 1
- Cache hit rate: > E1
- TTFT: < E1 (降低 15-30%)

#### 实验 E3-E4: Cache-Friendly vs Cache-Hostile

```bash
# E3: Cache-friendly scheduling
python -m v2.benchmark.live_runner \
  --family kv_prefix_reuse_v1 \
  --role-path-mode local_vllm \
  --task-schedule-plan cache_friendly

# E4: Cache-hostile scheduling
python -m v2.benchmark.live_runner \
  --family kv_prefix_reuse_v1 \
  --role-path-mode local_vllm \
  --task-schedule-plan cache_hostile
```

**预期**: E3 TTFT < E4 TTFT (≥ 20% 差异)

**Tier 1 go/no-go**:
- ✅ 如果 E2 cache hit rate > E1，且 E3 TTFT < E4: Tier 1 成功
- ❌ 如果 E2 无增量收益: **Phase 3 失败**，KV 机制无效，回退到 Non-KV

### Tier 2: 真实场景验证 (cross_period_financial_v1)

**推荐完成**，证明 KV 在真实场景有效

按照文档执行 E5-E7，记录实际结果

### Tier 3: 全量验证 (可选)

仅当时间允许时执行

### Phase 3 完成标准

- [ ] Tier 1 (E1-E4) 完成
- [ ] Tier 1 实验证明 KV 有增量收益
- [ ] Tier 2 (E5-E7) 完成（推荐）
- [ ] 所有实验数据已记录

---

## Phase 4: 报告集成（1-2天）

将 KV 实验结果写入报告第六部分，准备答辩材料

---

## 关键决策点总结

| Phase | Go 条件 | No-go 条件 | 行动 |
|-------|---------|-----------|------|
| Phase 1 | Full formal ≥ 24/25 | < 22/25 | 停止，回退 Non-KV |
| Phase 2 | P1.3 修复 + 单元测试通过 | 测试失败无法修复 | 停止，报告问题 |
| Phase 3 | E2 cache hit rate > E1 | E2 无增量收益 | 停止，KV 无效 |

---

## 执行检查清单

在每个 Phase 结束时，检查：

- [ ] 所有步骤都已执行
- [ ] 实际结果已记录
- [ ] go/no-go 判断已做出
- [ ] 产物已保存（run directory, logs, reports）
- [ ] 下一步计划明确

---

## 需要帮助时

如果遇到问题：

1. **首先查看文档**: 99% 的问题文档中都有答案
2. **检查日志**: vLLM logs, benchmark console.log
3. **报告问题**: 说明在哪个 Phase、哪个 Step、实际结果是什么、预期是什么
4. **不要自己决策**: 等待指导

---

## 最终产物

Phase 4 完成后，应该有：

1. 完整的实验数据（所有 run directories）
2. 对比报告（KV vs Non-KV）
3. 更新的文档（报告第六部分）
4. 答辩材料（slides 草稿）
5. Git commit history

---

## 开始执行

现在开始执行 Phase 1，从 Step 1 开始。

**重要提醒**: 
- 严格按照文档执行
- 每个步骤都要验证
- 遇到 go/no-go 判断点立即停止并报告
- 不要跳步骤

祝执行顺利！
