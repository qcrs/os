# KV Cache 研究延续与优化规划 Prompt

## 任务目标

分析当前 StateBus v2 的 KV cache 实现状态，结合赛题要求和已完成的 non-KV 实验结果，制定详细的 KV 研究优化方案、实验设计和落地计划。

---

## 上下文文档（请按顺序阅读）

### 1. 赛题要求
- **路径**: `/home/qcrs/statebus/project/docs/reference/赛题9设计讲解压缩稿.md`
- **关注点**: 三个核心评分维度（低开销通信、非文本状态传递、共享记忆复用）+ 创新加分项

### 2. Non-KV Baseline 实验结果
- **深度分析**: `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/14_local_api_non_kv_followup_deep_analysis_20260709.md`
- **工程判断**: `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/15_local_api_non_kv_followup_review_20260709.md`
- **决策文档**: `/home/qcrs/statebus/project/docs/improvement/20_v2_comprehensive_truth_audit_20260706/16_phase_transition_decision_kv_readiness_20260710.md`
- **关键结论**:
  - Quality superiority: 25/25 vs 16/25
  - Token reduction: prompt -57.9%, total -49.7%
  - Non-text StateRef: 25/25 semantic transfer
  - Memory reuse: validated replay 18, exact replay 2, reuse gain 17%
  - 赛题三个核心维度已完成，KV 是增量优化

### 3. KV Cache 实现计划
- **路径**: `/home/qcrs/statebus/project/docs/improvement/06_kv_cache_implementation.md`
- **当前状态**:
  - ✅ 估算层已实现（corpus_prefix_hash 追踪、ReplayClass × KV 理论分层）
  - ✅ 策略层已实现（PrefixLayoutPlan、shared_evidence_prefix 模式、EvidencePruningHint）
  - ✅ 观测层已实现（vLLM metrics probe、TTFT 采集、kv_prefix_experiment.py）
  - ✅ 数据集已设计（kv_prefix_reuse_v1 family）
  - ⚠️ 默认关闭，未接入正式 benchmark
  - ❌ 本地 vLLM 实验证据未跑

### 4. 代码实现文件
- `v2/runtime/neural_state.py` - Neural prefix 管理
- `v2/runtime/role_path.py` - Prefix layout compiler
- `v2/benchmark/kv_analysis.py` - KV 理论分析
- `v2/benchmark/kv_prefix_experiment.py` - vLLM probe
- `v2/benchmark/kv_prefix_schedule.py` - Cache-friendly scheduling
- `v2/retrieval/models.py`, `v2/retrieval/pipeline.py` - Evidence pruning
- `v2/runtime/kv_budget.py` - KV 容量估算
- `scripts/inspect_vllm_kv_budget.py` - 不启动模型的 KV footprint 估算

### 5. 系统能力边界
- **路径**: `/home/qcrs/statebus/project/docs/constraints/current_feature_scope.md`
- **关键约束**:
  - 本地开发环境 Linux，无 Docker socket 访问
  - GPU 资源受限（需要评估）
  - Non-KV baseline 已固化为 v2-non-kv-baseline-20260710

---

## 核心分析任务

### 1. 当前 KV 实现状态审查

**需要分析：**
- 已实现的代码质量如何？有无明显问题或遗留 TODO？
- 估算层、策略层、观测层三层架构是否合理？
- 默认关闭的设计是否正确？（避免混入 non-KV baseline claim）
- 代码与文档描述是否一致？

**输出：**
- 当前实现的优点和不足清单
- 需要修复/增强的技术债务列表

### 2. 创新点深化与差异化

**当前创新点（需要评估是否足够新颖）：**
1. Prefix Layout Compiler - 将多 Agent prompt 编译成共享前缀 + 角色后缀
2. Corpus-Aware KV Scheduling - 基于 corpus_prefix_hash 调度任务顺序
3. Prefix-Preserving Evidence Pruning - input-level KV 等价压缩
4. Neural Prefix Lease - 记录 prefix 在 engine/model 下的复用信息
5. ReplayClass × KV Reuse Pyramid - 统一记忆复用和 KV 成本分层

**需要思考：**
- 这些创新点与学术界/工业界已有方案的差异在哪？
- 是否可以引入新的优化维度？例如：
  - **KV 剪枝**：是否可以在 StateBus 层面决策哪些 evidence 保留在 prefix？
  - **动态压缩**：是否可以根据任务相似度动态调整 evidence 粒度？
  - **预测式调度**：是否可以根据历史 cache hit pattern 预测最优任务顺序？
  - **分层 prefix**：system prefix（全局）+ corpus prefix（同文档）+ task prefix（同任务）三层？
  - **Budget-aware pruning**：结合 KV cache 容量上限，动态裁剪 evidence？

**输出：**
- 当前创新点的新颖性评估（与 vLLM APC、SnapKV、ChunkKV 等对比）
- 新增创新方向建议（优先级排序）
- 每个建议的实现难度、预期收益、实验验证方法

### 3. 本地模型部署决策

**关键问题：**
- 本地 GPU 资源情况如何？（需要确认：单卡/多卡、显存大小、型号）
- 应该部署什么模型？
  - Qwen3-8B（~16GB VRAM, fp16）vs Qwen3-14B（~28GB fp16, ~8GB AWQ 4-bit）vs Qwen3-32B（~64GB fp16）
  - 是否需要量化？AWQ 4-bit vs fp16 的质量损失多大？
- **全局策略选择**：
  - **选项 A**: 所有测试都在本地完成（API + 本地 vLLM）
    - 优点：KV 和 non-KV 在同一环境验证，公平对比
    - 缺点：本地模型质量可能不如 API（取决于模型选择）
  - **选项 B**: Non-KV 测试在 API 完成，KV 测试在本地完成
    - 优点：Non-KV 用最强模型，KV 用本地 probe
    - 缺点：对比不公平，需要额外说明
  - **选项 C**: 双轨验证（API 完成主要测试，本地补充 KV probe）
    - 优点：保留 API 高质量结果，本地只做增量验证
    - 缺点：实验设计复杂

**需要分析：**
- 本地模型的质量是否足够复现 non-KV 的 25/25 quality superiority？
- 如果本地模型质量低于 API，如何设计实验才能公平对比？
- KV 实验是否需要全量跑 25 cases，还是只跑 kv_prefix_reuse_v1 的 10 轮？

**输出：**
- 推荐的模型选择（型号 + 量化方案）
- 推荐的全局测试策略（选项 A/B/C，附理由）
- 模型质量验证方案（如何确保本地模型足够）

### 4. 实验设计优化

**当前 kv_prefix_reuse_v1 数据集：**
- 10 轮任务，2 个 corpus（Orion factory、Nova retail）
- Cache-friendly vs cache-hostile 两种调度顺序
- 指标：corpus_prefix_hash_reuse_count、ttft_ms、prefix_cache_hit_rate、quality_floor_pass

**需要思考：**
- 这个数据集是否太小？10 轮是否足够证明 KV 收益？
- 是否需要在已有 formal 数据集上也跑 KV 对比？
  - cross_period_financial_v1（5 families, 18 tasks）
  - long_doc_metric_replay_v1（已有 corpus prefix 复用信号）
- 如何设计对照实验？
  - Baseline 1: API 模式（无 KV 观测）
  - Baseline 2: 本地 vLLM，不启用 prefix cache
  - Treatment 1: 本地 vLLM + prefix cache，不启用 StateBus prefix alignment
  - Treatment 2: 本地 vLLM + prefix cache + StateBus prefix alignment
  - Treatment 3: 本地 vLLM + prefix cache + prefix alignment + evidence pruning
- 如何避免 KV 实验混入 non-KV headline？

**输出：**
- 优化后的实验设计方案（数据集选择、对照组设置、指标采集）
- 实验规模估算（预计运行时间、GPU 资源消耗）
- Claim 边界定义（什么可以说、什么不能说）

### 5. 与 non-KV 实现的集成策略

**关键问题：**
- KV 代码目前是独立模块，如何与主流程集成？
- `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix` 默认关闭，何时打开？
- kv_prefix_reuse_v1 不进入默认 formal collection，如何控制？
- 如何确保 KV 实验失败时，non-KV baseline 不受影响？

**需要思考：**
- 是否需要新增 `--enable-kv-probe` 参数？
- 是否需要新的 benchmark suite（kv_formal vs non_kv_formal）？
- 报告中如何呈现 KV 作为增量优化？
- Git 分支策略：继续在 feat/local-hidden-kv-prototype 还是新开分支？

**输出：**
- 代码集成方案（参数控制、配置文件、分支策略）
- 报告结构建议（non-KV 基础章节 + KV 增量章节）
- 风险隔离措施（确保 KV 失败不影响 non-KV）

---

## 预期输出物

请按以下结构输出完整的分析报告和执行计划：

### 第一部分：当前实现审查与问题诊断

1. **代码实现质量评估**
   - 已实现功能清单（逐个文件检查）
   - 发现的问题和技术债务
   - 需要修复的优先级排序

2. **架构合理性分析**
   - 三层架构（估算/策略/观测）是否合理
   - 模块边界是否清晰
   - 与主流程的集成点是否正确

3. **文档与代码一致性**
   - 文档描述与实际代码的差异
   - 遗留的 TODO 和 FIXME
   - 需要补充的文档

### 第二部分：创新点深化方案

1. **当前创新点评估**
   - 每个创新点与学术/工业界方案的对比
   - 新颖性评分（1-5 分）
   - 技术难度和实现完成度

2. **新增优化方向建议**
   - 3-5 个具体的优化方向
   - 每个方向的：
     - 技术可行性分析
     - 预期收益（token/latency/cache hit rate）
     - 实现难度（工作量估算）
     - 实验验证方法
     - 优先级排序（P0/P1/P2）

3. **推荐实施路线**
   - 哪些优化应该立即做
   - 哪些优化可以后续做
   - 哪些优化风险太高不建议做

### 第三部分：本地部署与测试策略

1. **GPU 资源评估**
   - 需要确认的硬件信息（提供检查命令）
   - 不同模型的资源需求对比表

2. **模型选择建议**
   - 推荐的主模型（型号 + 量化方案）
   - 备选方案（如果主模型不可行）
   - 模型质量验证方案（如何确保 >= API 质量）

3. **全局测试策略决策**
   - 选项 A/B/C 的详细对比
   - 推荐方案 + 理由
   - 实验公平性保证措施

4. **本地环境部署清单**
   - vLLM 版本和安装命令
   - 模型下载路径和启动命令
   - 配置文件修改清单
   - 验证步骤（smoke test）

### 第四部分：实验设计方案

1. **数据集选择**
   - 是否只用 kv_prefix_reuse_v1
   - 是否在 formal 数据集上补充 KV 对比
   - 数据集规模权衡

2. **对照组设计**
   - Baseline 和 Treatment 组定义
   - 每组的配置参数
   - 控制变量和自变量

3. **指标采集方案**
   - 必须采集的指标清单（KV 特有 + 通用质量/性能）
   - 指标来源（vLLM metrics / StateBus telemetry / benchmark report）
   - 采集脚本和自动化方案

4. **实验规模估算**
   - 预计运行轮次和时间
   - GPU 资源消耗估算
   - 磁盘空间需求

5. **Claim 边界定义**
   - 实验成功后可以 claim 什么
   - 不能 claim 什么（即使实验成功）
   - 答辩口径建议

### 第五部分：集成与落地计划

1. **代码集成方案**
   - 参数控制方式（环境变量 / CLI 参数 / 配置文件）
   - Benchmark suite 划分（kv_formal vs non_kv_formal）
   - Git 分支策略

2. **报告结构建议**
   - Non-KV 基础章节（已有内容）
   - KV 增量章节（新增内容）
   - 如何呈现 KV 作为 optional 增强

3. **风险隔离措施**
   - 如何确保 KV 代码不影响 non-KV baseline
   - 如何快速回退（如果 KV 实验失败）
   - 如何保持 v2-non-kv-baseline-20260710 tag 的稳定性

4. **详细执行步骤（时间线）**

**Phase 1: 环境准备与验证（1-2 天）**
- [ ] 确认 GPU 资源（显存/型号/驱动）
- [ ] 部署推荐模型 + vLLM
- [ ] Smoke test（确保本地 API 可用）
- [ ] 质量验证（跑 1-2 个 formal cases，对比 API 结果）
- **Go/No-go 判断**：如果模型质量不足或环境有问题 → 停止或调整

**Phase 2: 代码审查与增强（2-3 天）**
- [ ] 修复当前实现的技术债务
- [ ] 实施推荐的优化方向（P0 项）
- [ ] 补充缺失的文档和注释
- [ ] 单元测试覆盖（KV 模块）
- **Go/No-go 判断**：如果代码质量不过关 → 继续修复

**Phase 3: 实验执行（3-5 天）**
- [ ] 跑 kv_prefix_reuse_v1（cache-friendly vs cache-hostile）
- [ ] 采集 vLLM metrics（prefix_cache_hit_rate、ttft_ms）
- [ ] 质量验证（quality_floor_pass_rate）
- [ ] （可选）在 formal 数据集上补充 KV 对比
- [ ] 生成实验报告和可视化
- **Go/No-go 判断**：如果 KV 无增量收益 → 回退到 non-KV

**Phase 4: 报告集成与答辩准备（1-2 天）**
- [ ] 将 KV 实验结果写入增量章节
- [ ] 更新答辩口径（KV 作为创新加分项）
- [ ] 准备答辩 slides（KV 相关）
- [ ] 最终 review 和归档

**总预算**: 7-12 天（与决策文档一致）

### 第六部分：答辩准备

1. **KV 相关预期质疑 + 标准回答**
   - Q: "你的 KV cache 是怎么在 Agent 间传递的？"
   - Q: "你的 KV 优化相比 vLLM 自带的 APC 有什么区别？"
   - Q: "为什么不实现真正的跨模型 KV 共享？"
   - Q: "你的 evidence pruning 和 SnapKV 有什么区别？"

2. **技术亮点提炼**
   - 3-5 个一句话总结的技术亮点
   - 每个亮点的支撑数据

3. **可视化建议**
   - 推荐的图表类型（prefix layout 示意图、cache hit rate 对比、TTFT 对比）
   - 数据呈现方式

---

## 输出要求

1. **输出格式**：Markdown 文档，结构清晰，分节明确
2. **分析深度**：每个问题都要给出具体的技术方案，不要只说"需要分析"
3. **可执行性**：执行步骤要具体到命令/文件/参数，不要只说"部署模型"
4. **风险意识**：每个关键决策点都要有 go/no-go 判断和回退方案
5. **文档路径**：所有引用的文件都要给出完整路径
6. **数据支撑**：所有判断都要有数据或推理依据

---

## 特别注意

1. **不要写代码**：只需要分析和规划，不需要实际编写代码
2. **不要跑实验**：只需要设计实验方案，不需要实际执行
3. **保持诚实**：如果某个方向不可行或风险太高，明确说出来
4. **优先级清晰**：哪些是 P0（必须做）、P1（应该做）、P2（可选）要明确
5. **与 non-KV baseline 的关系**：始终记住 KV 是增量优化，non-KV 是保底方案

---

## 开始分析

请按照上述结构，完成详细的 KV 研究分析和落地计划。
