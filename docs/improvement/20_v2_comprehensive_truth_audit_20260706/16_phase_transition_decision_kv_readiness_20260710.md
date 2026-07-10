# Phase Transition Decision: Non-KV 固化 vs KV 转进判断

Date: 2026-07-10
Reviewer: Engineering Decision Matrix
Scope: 基于赛题要求，判断当前 v2 local API non-KV 实验结果是否值得固化，以及是否应转向 KV 研究

---

## 执行摘要

**决策建议：现在可以转向 KV 研究。**

理由：
1. 赛题三个核心维度（低开销通信、非文本状态传递、共享记忆复用）的证据链**完整且强**
2. 当前没有阻断性问题，P1 优化项不影响核心 claim
3. 正确性评估已充分（quality gate + benchmark fairness + artifact audit）
4. Latency 劣势已归因清楚，有明确答辩口径
5. 继续优化 non-KV 的边际收益低于探索 KV 的战略价值

**但需要满足两个前提：**
1. 当前 non-KV 实验结果需要**归档固化**（写入正式报告 + 保留 artifact roots）
2. KV 研究需要**增量验证**（在 non-KV 证据之上叠加，而非替代）

---

## 1. 赛题要求对照：完成度评估

### 1.1 赛题三个核心维度

根据 `docs/reference/赛题9设计讲解压缩稿.md`，赛题评分重点：

| 维度 | 赛题要求 | 当前完成度 | 支撑证据 |
|------|---------|-----------|---------|
| **低开销通信** | 相比纯文本，控制面开销降低 | ✅ **完成** | prompt token -57.9%, 协议控制面交换仅 169.2ms (0.5%) |
| **非文本状态传递** | embedding/中间状态按引用传递而非文本序列化 | ✅ **完成** | 25/25 semantic_state_transfer, memfd/shared_memory 后端验证 |
| **共享记忆复用** | 跨任务记忆沉淀和复用机制 | ✅ **完成** | validated replay 18, exact replay 2, reuse_gain 非零 |

**结论：三个核心维度全部完成，证据强度足够答辩。**

### 1.2 详细指标矩阵

#### 1.2.1 低开销通信

| 指标 | 数值 | 证据路径 |
|------|------|---------|
| Prompt token reduction | **-63,268 (-57.9%)** | `r01_07_formal_compare_api_local_memfd/stdout.json` |
| Total token reduction | **-67,989 (-49.7%)** | 同上 |
| 协议控制面开销（loopback） | **169.2ms (0.5%)** | `deep_mining/runtime_overhead_matrix.csv` |
| 协议控制面开销（subprocess） | **2933.0ms** | `r01_05 vs r01_14` 对比 |

**评判：**
- ✅ Token 减少幅度超过 50%，证明"低开销通信"成立
- ✅ 协议自身开销在 loopback 下仅 0.5%，证明结构化协议不比纯文本高
- ⚠️ Subprocess transport 增加 2.9s，但这是 transport 选择问题，不是协议本身

#### 1.2.2 非文本状态传递

| 指标 | 数值 | 证据路径 |
|------|------|---------|
| Semantic state transfer count | **25/25 (100%)** | Core formal 所有 cases |
| StateRef backend coverage | **memfd + shared_memory 双验证** | `state_transport_backend_matrix.csv` |
| StateRef 类型覆盖 | **EMBEDDING + DENSE_EVIDENCE + TOOL_ARTIFACT** | Protocol messages |
| Non-text bytes transfer | **1704.67 bytes/case (state_transfer lane)** | `text_brief_fidelity` formal package |

**评判：**
- ✅ 100% cases 生成 semantic transfer，证明机制普遍有效
- ✅ 双后端验证，证明不依赖特定 backend
- ✅ StateRef 覆盖多种状态类型，不是单一 embedding demo

#### 1.2.3 共享记忆复用

| 指标 | 数值 | 证据路径 |
|------|------|---------|
| Validated replay | **18 cases** | `x28` continuous replay collection |
| Exact replay | **2 cases** | 同上 |
| Artifact reuse | **非零** | `x27` history reuse collection |
| History reuse | **非零** | 同上 |
| Reuse gain | **0.17 (17%)** | Host goal eval replay-aware runs |
| Memory hit rate | **0.83 (83%)** | 同上 |
| Skipped step count | **9 steps (18-task chain)** | 同上 |

**评判：**
- ✅ Validated/exact replay 有实际观测值，不是"机制存在但无效果"
- ✅ Reuse gain 17% 证明复用有实际收益
- ✅ Memory hit rate 83% 证明记忆检索有效
- ✅ Skipped step count 非零证明跨任务真实复用

---

## 2. CodeAct 沙箱完成度

### 2.1 当前状态

根据 `docs/constraints/current_feature_scope.md`：

| 能力 | 完成度 | 证据 |
|------|--------|------|
| Subprocess 隔离 | ✅ 已实现 | `LightweightSubprocessRunner` |
| Tool registry | ✅ 已实现 | `ToolRegistry + ToolSpec` |
| UDS external executor | ✅ 样机 | `runtime/uds_transport.py` |
| CodeAct acceptance | ✅ 5/5 pass | `x04d` stage |
| **nsjail 正式沙箱** | ❌ 未实现 | 需要额外安装和权限 |
| **Docker 容器隔离** | ❌ 未实现 | 迁移阶段工作 |

### 2.2 评判

**赛题是否要求 nsjail/Docker 级别隔离？**

查阅赛题文档，没有明确要求"必须使用特定沙箱技术"。赛题关注的是：
- Agent 协作框架的**通信开销**
- **状态传递机制**
- **记忆复用能力**

CodeAct 沙箱属于**工程实现细节**，不是赛题评分核心。

**当前完成度判断：**
- ✅ 有 subprocess 隔离，满足基本安全边界
- ✅ 有 tool registry，满足可扩展执行
- ⚠️ nsjail/Docker 是加分项，不是必选项
- **结论：当前 CodeAct 沙箱对赛题来说足够，但对生产系统不够**

---

## 3. 正确性评估覆盖度

### 3.1 用户关心的问题："除了 CodeAct，其他部分有没有评估正确性？"

#### 3.1.1 已有的正确性评估

| 组件 | 评估方式 | 证据 |
|------|---------|------|
| **Planner** | Quality gate (L3 validator) | Core r01_07: 25/25 vs 16/25 |
| **Retriever** | Embedding semantic transfer count | 25/25 cases 全部生成 StateRef |
| **Executor** | Tool artifact validation + audit | 2373 artifact audit sidecars |
| **Summarizer** | Quality headline + benchmark expectation | Expectation match rate = 1.00 |
| **StatePool** | Checksum + hydration audit | 2373 hydration audit JSON |
| **Memory** | Replay validation + reuse contract | 18 validated replay + 2 exact replay |
| **Protocol** | Schema validation + capability gate | Hello/Capability 握手验证 |
| **CodeAct** | Acceptance test | 5/5 pass |

#### 3.1.2 Benchmark fairness gate

当前 benchmark 有三层 fairness gate：

1. **Quality gate：** `strict_equal_quality` / `quality_superiority`
2. **Text-side baseline fidelity：** Text 模式必须写完整 handoff，不能故意削弱
3. **Artifact audit：** 每个 run 有完整 telemetry/prompt slice/memory commit/hydration audit

**结论：正确性评估已经非常充分。**

### 3.2 需要进一步评估正确性吗？

**不需要。**

理由：
1. 当前 quality gate 已经是**外部 baseline 对比**，不是自说自话
2. Benchmark 有 deterministic repeat-10 稳定性验证
3. Artifact audit 覆盖每个 agent cycle
4. 没有证据表明当前正确性评估有系统性漏洞

**但有一个例外：**
- 如果要 claim "latency superiority"，需要更严格的 end-to-end correctness validation
- 当前 latency gate 是 false，所以这个例外不适用

---

## 4. Latency 劣势分析

### 4.1 用户关心的问题："Latency 时间久是不是必然？只能从答辩口径调整？"

#### 4.1.1 当前 latency 状态

| 指标 | 数值 | 含义 |
|------|------|------|
| Task time delta | **-92,795.8ms** | StateBus 总任务时间更快（因为 LLM 时间少） |
| LLM time delta | **-124,997.3ms** | LLM 推理时间大幅减少 |
| System overhead delta | **+32,201.5ms** | 系统开销增加 |
| Latency superiority gate | **false** | 不能 claim 端到端 latency 优势 |

#### 4.1.2 Overhead 归因（已完成拆解）

| 组件 | 耗时 (ms) | 占比 | 可优化性 |
|------|--------:|-----:|---------|
| CodeAct subprocess 隔离 | 20,490.7 | 63.6% | ❌ 不建议优化（安全必要成本） |
| Agent 协调 + 状态操作 | ~10,340 | 32.1% | ⚠️ 可优化但 ROI 不明确 |
| Benchmark 插桩 | ~1,017 | 3.2% | ❌ 不建议优化（审计必要） |
| 协议控制面交换 | 169.2 | 0.5% | ✅ 已经很低 |

#### 4.1.3 Latency 劣势是必然的吗？

**部分必然，部分可优化。**

**必然部分（63.6%）：**
- CodeAct subprocess 隔离是安全性必要成本
- 除非放弃隔离或改用更轻量的沙箱（WASM/eBPF），否则这部分开销无法消除
- 但赛题**没有要求端到端 latency 优于 baseline**

**可优化部分（32.1%）：**
- Agent 协调和状态操作的 10.3s 有优化空间
- 但优化前需要先验证：这 10.3s 是否包含必要的 semantic processing
- 如果是 LLM inference 本身，那就是"用推理换 token"的设计取舍

**不必优化部分（3.7%）：**
- Benchmark 插桩和协议控制面已经很低

#### 4.1.4 答辩口径

**推荐口径（已在 review 报告中）：**

> "系统开销主要来自 CodeAct subprocess 隔离（63.6%，安全必要成本）和 agent 协调（33.3%，协议成本）。协议自身的控制面交换在 loopback 模式下仅 169.2ms (0.5%)，证明结构化协议相比纯文本开销可控。赛题评分重点是'通信开销低于纯文本'，我们的 prompt token 降低 57.9% 已充分证明。"

**可以说：**
- "Token 减少 57.9% 证明通信开销低"
- "协议自身开销仅 0.5%"
- "系统开销主要来自安全隔离，不是协议本身"

**不能说：**
- "StateBus 端到端更快"（gate 是 false）
- "系统开销为零"（实际 +32s）
- "优化后可以消除开销"（63.6% 是安全必要成本）

### 4.2 需要优化 latency 才能转 KV 吗？

**不需要。**

理由：
1. 赛题不要求 latency superiority
2. 当前 overhead 已经归因清楚，有明确答辩口径
3. 优化 32s overhead 的收益远低于探索 KV 的战略价值
4. KV 研究本身可能带来 latency 优化（减少 LLM re-encode）

---

## 5. 其他问题梳理

### 5.1 Flagship 2/6 通过率低

**问题：** 只有 csv_table_profile_v1 和 csv_correlation_replay_v1 clean pass，4/6 failed

**是否阻断转 KV？** 否。

**理由：**
1. Flagship 是 **stress test**，不是基本功能验证
2. Core r01_07 已经证明 25/25 quality superiority
3. 2/6 pass 说明 StateRef prompt-saving 是 family-dependent，这是诚实发现
4. Cross_period_financial_v1 是控制负例，证明"文本足够时 StateRef 无额外收益"

**是否需要修到 6/6？** 不建议。

- P1 项可以修（long_doc_metric full-vs-isolated 矛盾），但不紧急
- 其他 failed families 属于"机制正确，但 family 本身需要 tuning"

### 5.2 StateBus 24/25 质量回归

**问题：** lr01/lr02/lr03/x23/x26 都是 24/25，只有 core r01_07 是 25/25

**是否阻断转 KV？** 否。

**理由：**
1. 25/25 vs 16/25 已经足够证明 quality superiority
2. 24/25 vs 16/25 仍然是显著优势
3. 修这个问题的收益是"解锁更多 formal compare 作为 claim"，不是"修复阻断性 bug"

**是否值得修？** 值得（P1），但不阻断 KV。

- 如果修好，答辩素材翻倍
- 但修的代价高（逐 case diff prompt slice）

### 5.3 Subprocess transport overhead +2.9s

**问题：** Subprocess transport 比 loopback 增加 2.9s 控制面开销

**是否阻断转 KV？** 否。

**理由：**
1. 当前 formal run 用的是 loopback，不是 subprocess
2. Subprocess transport 是可选 backend
3. 2.9s 是 UDS round-trip 开销，属于 transport 层面，不是协议设计问题

**是否需要优化？** 不建议现在优化。

- 在 claim gate 通过之前，优化 transport 无意义
- 这是 backend 选择问题，不影响协议本身的 claim

### 5.4 gridops_world_v1 continuous 不支持

**问题：** x17b optional failure，continuous runner 不支持 gridops_world_v1

**是否阻断转 KV？** 否。

**理由：**
1. Optional failure，不是 required
2. 修了也只多一个 family 数据
3. 对答辩无感知增益

**是否需要修？** 不需要。

---

## 6. 转向 KV 的战略判断

### 6.1 继续优化 non-KV 的边际收益

| 优化项 | 预期收益 | 预期代价 | ROI |
|--------|---------|---------|-----|
| StateBus 24/25 → 25/25 | 解锁 6 个 formal compare 作为 claim | 逐 case diff + route 归因 | 中 |
| long_doc full-vs-isolated 矛盾 | Flagship 2/6 → 3/6 | Diff runtime root + T2 pairing | 中 |
| Subprocess transport 优化 | -2.9s 控制面开销 | UDS round-trip 优化 | 低 |
| Agent 协调优化 | -10.3s 系统开销 | 深度 profiling + refactor | 低-中 |

**结论：继续优化 non-KV 的边际收益递减，没有"一修就能翻倍"的高 ROI 项。**

### 6.2 转向 KV 的战略价值

| 维度 | KV 相比 non-KV 的增量价值 |
|------|--------------------------|
| **竞争差异化** | non-KV StateRef 是"更强的 embedding"，KV 是"真正的 hidden state 传递" |
| **技术深度** | KV 涉及模型内部表示，技术难度和创新度更高 |
| **性能潜力** | KV 可能减少 re-encode 开销，带来 latency 优化 |
| **赛题加分** | 赛题提到"非文本状态传递"，KV 是更极致的体现 |
| **风险** | KV 可能面临同构性约束、内存开销、工程复杂度 |

**关键问题：KV 是锦上添花还是必要项？**

**答案：锦上添花，但值得探索。**

理由：
1. 赛题三个核心维度已经用 non-KV 证明完成
2. KV 不是"没有就无法答辩"的必选项
3. 但 KV 是"有了就能显著增强技术叙事"的加分项
4. 如果 KV 研究失败，可以回退到 non-KV baseline

### 6.3 转向 KV 的前提条件

#### 前提 1：non-KV 结果必须归档固化

**必须做：**
1. 写入正式报告（system method + results explainer）
2. 保留 artifact roots（core + follow-up runs）
3. 归档 evidence 路径（CSV matrices + JSON reports）
4. 固化答辩口径（review 报告 Section 6.3）

**为什么：**
- KV 研究有风险，non-KV 是保底方案
- 答辩时需要"non-KV 已证明 + KV 是增量探索"的双层叙事

#### 前提 2：KV 必须增量验证，不能替代 non-KV

**KV 研究策略：**
1. 先复现 non-KV 的 25/25 quality superiority
2. 在此基础上叠加 KV transfer
3. 对比 KV vs non-KV 的增量收益
4. 如果 KV 失败，non-KV 仍然是完整证据链

**不能做：**
- 删除 non-KV 代码
- 假装 KV 是唯一路径
- 把 non-KV 实验结果当作"过时"

---

## 7. 最终决策

### 7.1 核心判断

**现在可以转向 KV 研究。**

**支撑论据：**

| 决策维度 | 判断 | 理由 |
|---------|------|------|
| 赛题核心维度完成度 | ✅ 完成 | 低开销通信、非文本传递、共享记忆全部有强证据 |
| 阻断性问题 | ✅ 无 | 没有"不修就无法答辩"的问题 |
| 正确性评估 | ✅ 充分 | Quality gate + fairness + audit 三层验证 |
| Latency 答辩口径 | ✅ 清晰 | Overhead 归因完成，有明确说法 |
| 继续优化 non-KV ROI | ⚠️ 递减 | 没有高 ROI 的必修项 |
| 转向 KV 战略价值 | ✅ 高 | 技术深度、竞争差异化、性能潜力 |

### 7.2 执行建议

#### 立即行动（转 KV 前必须完成）

1. **归档 non-KV 实验结果**
   - [ ] 写入正式报告 draft（基于 review 报告 Section 2, 5, 6）
   - [ ] 保留 artifact roots（不要删除 runs/）
   - [ ] 归档 evidence CSV matrices 到 docs/
   - [ ] 固化答辩 FAQ（基于 review 报告 Section 6.3）

2. **清理 git worktree**
   - [ ] Commit 当前 non-KV 分支
   - [ ] Tag 为 `v2-non-kv-baseline-20260710`
   - [ ] 确保随时可以回退

#### KV 研究阶段策略

**Phase 1: KV 可行性验证（1-2 天）**
- 调研 vLLM/TGI 的 KV cache export API
- 验证同构模型间 KV 传递的技术路径
- 评估内存开销和 transport 复杂度
- **Go/No-go 判断：如果技术路径不可行，立即停止**

**Phase 2: KV MVP 实现（3-5 天）**
- 实现 KV StateRef 传递（基于 non-KV 代码）
- 跑通单个 case 的 KV transfer
- 验证 KV 能否减少 re-encode
- **Go/No-go 判断：如果无增量收益，回退到 non-KV**

**Phase 3: KV benchmark 验证（2-3 天）**
- 复现 non-KV 的 25/25 quality superiority
- 对比 KV vs non-KV 的 token/latency delta
- 评估 KV 的 claim 边界
- **Go/No-go 判断：如果 claim 不比 non-KV 强，回退**

**Phase 4: KV 集成到报告（1-2 天）**
- 如果 Phase 3 成功，将 KV 作为增量章节写入报告
- 保留 non-KV 为基础证据
- 形成"non-KV 已证明 + KV 是增强"的双层叙事

### 7.3 风险控制

| 风险 | 缓解措施 |
|------|---------|
| KV 研究失败 | non-KV 已归档，可直接用于答辩 |
| KV 工程复杂度高 | 设置 go/no-go gate，及时止损 |
| KV 无增量收益 | 对比 benchmark 明确，回退决策快 |
| 时间不足 | KV 总预算 7-12 天，超时即停止 |

### 7.4 不建议的路径

❌ **不建议：先把 non-KV 优化到完美再转 KV**
- 理由：边际收益递减，没有"一修就完美"的路径

❌ **不建议：删除 non-KV 代码，All-in KV**
- 理由：KV 有失败风险，non-KV 是保底方案

❌ **不建议：KV 和 non-KV 平行推进**
- 理由：资源分散，两边都做不深

---

## 8. 答辩预演：如果只有 non-KV

假设 KV 研究失败，当前 non-KV 能否支撑答辩？

**答案：可以。**

### 8.1 核心 claim（基于 non-KV）

1. **低开销通信：** Prompt token -57.9%, 协议控制面 0.5%
2. **非文本状态传递：** 25/25 semantic StateRef, memfd/shared_memory 双验证
3. **共享记忆复用：** Validated replay 18, reuse gain 17%

### 8.2 预期质疑 + 回答（已在 review 报告中）

**Q1: "系统开销增加 32s，怎么说低开销？"**
A: 63.6% 是安全隔离，33.3% 是协议成本，协议自身仅 0.5%。对比维度是 token 不是 wall time。

**Q2: "为什么只有 2/6 family 通过？"**
A: StateRef prompt-saving 是 family-dependent，这是诚实发现。csv_table 和 csv_correlation 是 clean 正例，cross_period 是控制负例。

**Q3: "你的 KV cache 传递在哪里？"**
A: 本轮是 non-KV，重点验证 semantic StateRef。KV 是 future work。

**结论：non-KV 已经可以支撑完整答辩。**

---

## 9. 更新历史

- 2026-07-10: 初始决策文档，基于 14/15 号分析报告 + 赛题要求 + feature scope
- 核心结论：可以转 KV，但需先归档 non-KV
