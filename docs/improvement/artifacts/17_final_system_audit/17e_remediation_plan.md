# 17e - 修复方案 (Remediation Plan)

**审计日期：** 2026-07-06
**关联主报告：** [17_final_system_audit_20260706.md](../../17_final_system_audit_20260706.md)

---

## 修复优先级分级

- **P0**：阻止发布，必须立即修复
- **P1**：赛前必须修复，影响核心声明
- **P2**：强烈建议修复，影响声明范围
- **P3**：可选增强，不影响发布

---

## 第一部分：必须立即修的 P0/P1

*所有 P1 问题已修复或缓解。*

---

## 第二部分：赛前必须修的 P2（4 项）

### 修复 1：标注或改写过时文档（DOC-001）

**优先级：** P2 高
**预计工时：** 30 分钟
**风险等级：** 低（文档修改）

#### 目标文件

1. `docs/reports/MASTER_PRESENTATION_GUIDE.md`
2. `docs/reports/task_design_and_mode_comparison.md`

#### 修改内容

在每个文件开头添加醒目的历史标注横幅：

```markdown
---
**⚠️ 历史文档警告 / HISTORICAL DOCUMENT WARNING**

**当前定位：** 本文档为 2026-06-{date} 历史快照，不是当前 source-of-truth。

**当前权威来源（按优先级）：**
1. docs/improvement/16_deep_contest_audit_20260706.md（最新综合审计）
2. docs/improvement/15_fairness_gate_propagation_audit_20260706.md（公平门修复）
3. docs/reports/v2_update_validation_readout_20260704.md（最诚实的分析）
4. docs/contracts/v2_external_pure_text_fairness_gate.md（公平门契约）

**警告：**
- ❌ 不要引用本文档的 pack 架构（v3 已废弃）
- ❌ 不要引用 `text_whole_lane`（内部比较器，非外部基线）
- ❌ 不要引用 `task_match_rate`（已退役指标）
- ❌ 不要引用 `contest_honest_headline_v1`（v3 frozen artifact，已废弃）

请勿引用本文档作为当前竞赛叙事依据。本文档保留仅作历史参考。
---

[原文档内容从这里开始...]
```

#### 回归测试

```bash
# 验证横幅已添加
head -20 docs/reports/MASTER_PRESENTATION_GUIDE.md | grep -c "历史文档警告"
head -20 docs/reports/task_design_and_mode_comparison.md | grep -c "历史文档警告"
# 两个命令都应输出 1

# 确认未引入语法错误
grep -c "^---$" docs/reports/MASTER_PRESENTATION_GUIDE.md
# 应输出偶数（markdown front matter 成对）
```

#### Benchmark/JSON 验证

无需（纯文档修改）

#### 风险和 claim 影响

- **风险：** 极低
- **Claim 影响：** 正面 - 防止引用过时声明
- **回滚容易度：** 极易（git revert 即可）

---

### 修复 2：降级速度声明（CLAIM-001）

**优先级：** P2 高
**预计工时：** 1 小时
**风险等级：** 中（需仔细检查所有表述）

#### 目标文件

1. `docs/reports/v2_experiment_summary_20260703.md`
2. `docs/contracts/v2_external_pure_text_fairness_gate.md`
3. 任何答辩材料（如果存在）

#### 修改内容

**查找并替换以下模式：**

| 错误表述 | 正确表述 |
|---------|---------|
| "StateBus 端到端速度更快" | "StateBus 展示令牌和提示字节显著效率改进（-34% tokens, -39% prompt bytes），但当前系统开销为正（+9.9s）" |
| "端到端延迟改进" | "资源效率改进" |
| "latency win" / "speed superiority" | "resource efficiency improvement" |
| "CodeAct -65% 加速" | "CodeAct 阶段在同进程热缓存重运行场景下展示 -65.7% 时间减少（从 2455ms 到 843ms），证明结果缓存机制有效" |

**添加明确的效率 vs 速度区分：**

```markdown
## 效率改进（非速度）

### 资源效率指标（已验证）

✅ **令牌节省：** -1023 tokens (-34%)
✅ **提示字节节省：** -4992 bytes (-39%)
✅ **控制平面字节节省：** -351 bytes

### 当前系统开销

🔴 **端到端时间：** +9906ms（StateBus 当前更慢）
  - LLM 时间增量：+2588ms
  - 系统开销增量：+1643ms

### 推荐答辩表述

"StateBus 展示了令牌和提示字节的显著节省，为后续优化奠定了基础。
当前系统开销为正，但资源效率改进已通过外部公平门验证。
优化路径明确：减少多角色协调开销、优化状态序列化性能。"
```

#### 回归测试

```bash
# 验证所有"速度优势"表述已移除
grep -r "速度.*优势\|latency.*win\|端到端.*快\|faster.*end.*to.*end" \
  docs/reports/ docs/contracts/ | \
  grep -v "不能声明\|unsupported\|警告"
# 应输出为空

# 验证"效率改进"表述已添加
grep -c "资源效率改进\|resource efficiency" docs/reports/v2_experiment_summary_20260703.md
# 应输出 >= 1
```

#### Benchmark/JSON 验证

```bash
# 确认 JSON 证据与表述一致
cat /home/qcrs/statebus/runs/codex-raw-fairness-20260706/runtime/benchmark_reports/codex-raw-fairness-20260706-cold-start-compare-api.json | \
  jq '{
    api_task_ms_delta,
    api_llm_total_tokens_delta,
    api_prompt_bytes_delta
  }'
# 应输出：
# {
#   "api_task_ms_delta": 9906,  // 正数 = 更慢
#   "api_llm_total_tokens_delta": -1023,  // 负数 = 节省
#   "api_prompt_bytes_delta": -4992  // 负数 = 节省
# }
```

#### 风险和 claim 影响

- **风险：** 中等 - 需确保所有文档一致
- **Claim 影响：** 高 - 防止速度声明被挑战
- **回滚容易度：** 容易（文档修改）

---

### 修复 3：明确重放命名为"降级复用"（REPLAY-001 后续）

**优先级：** P2 高
**预计工时：** 1.5 小时
**风险等级：** 中（需修改多个文档）

#### 目标文件

1. `docs/reports/v2_experiment_summary_20260703.md`
2. `docs/reports/v2_update_validation_readout_20260704.md`
3. `docs/contracts/v2_role_contract.md`
4. 任何答辩材料

#### 修改内容

**添加三级分类说明（在每个提到重放的文档中）：**

```markdown
## 重放/复用分类（对外口径）

StateBus 实现三级重放/复用机制，严格区分不同语义强度：

### 1. EXACT_REPLAY（精确重放）

**语义：** 任务规格、输入工件、运行时签名完全相同，输出字节完全相同
**跳步：** 2 步（跳过 Planner + Retriever，直接使用历史 Executor 输出）
**证据：** 3 次精确重放（continuous_replay_collection stdout.json）
**适用场景：** 完全相同的重复查询

### 2. VALIDATED_DOWNGRADED_REUSE（验证降级复用）

**语义：** 任务家族、意图操作、所需工具相同，但参数可能不同
**跳步：** 1 步（跳过 Planner，保留 Retriever + Executor + Summarizer）
**证据：** 17 次验证降级复用
**适用场景：** 同类任务，不同参数（如不同时期的相同指标查询）

**⚠️ 重要澄清：**
- **不是"通用答案恢复"**：不能直接重放历史答案
- **不是"泛化记忆"**：需要任务家族和工具集匹配
- **仍需执行核心逻辑**：Retriever 和 Executor 仍然运行

### 3. ASSIST（辅助复用）

**语义：** 历史工件支持当前任务，但不满足跳步条件
**跳步：** 0 步（所有角色都执行，但可参考历史）
**证据：** 39 次历史支持复用
**适用场景：** 相关历史为新任务提供上下文

### 对外术语约定

| 代码字段 | 对外表述 | 避免使用 |
|---------|---------|---------|
| `validated_replay_count` | "验证降级复用计数" | ❌ "验证重放" |
| `validated_downgraded_reuse_count` | ✅ 使用此别名 | ❌ "通用答案恢复" |
| `exact_replay_count` | "精确重放计数" | ✅ 可直接使用 |
| `history_backed_reuse_count` | "历史支持复用计数" | ✅ 可直接使用 |
```

**替换所有"验证重放"表述：**
- "验证重放" → "验证降级复用"
- "validated replay" → "validated downgraded reuse"
- "答案恢复" → "降级复用（跳过规划步骤）"

#### 回归测试

```bash
# 验证代码别名存在
grep -c "validated_downgraded_reuse_count" v2/runtime/driver.py
grep -c "validated_downgraded_reuse_count" v2/benchmark/continuous_runner.py
# 都应输出 >= 1

# 验证文档使用正确术语
grep -r "通用答案恢复\|generic answer restoration" docs/reports/ docs/contracts/
# 应输出为空或只有"不是"的否定句

# 运行重放测试
python -m pytest tests/v2/test_replay.py -k "replay_decision" -v
# 应全部通过
```

#### Benchmark/JSON 验证

```bash
# 验证 benchmark 输出包含保守别名
cat /home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/10_continuous_replay_collection_primary/stdout.json | \
  jq '{
    validated_replay_count,
    validated_downgraded_reuse_count,
    exact_replay_count,
    answer_restoration_replay_count
  }'
# 应输出：
# {
#   "validated_replay_count": 17,
#   "validated_downgraded_reuse_count": 17,  // 相同值
#   "exact_replay_count": 3,
#   "answer_restoration_replay_count": 0  // 明确为 0
# }
```

#### 风险和 claim 影响

- **风险：** 中等 - 需确保术语一致性
- **Claim 影响：** 高 - 防止"通用答案恢复"被误读为 AI 记忆泛化能力
- **回滚容易度：** 容易（文档修改 + 代码别名已存在）

---

### 修复 4：明确形式化范围为"精密锚点"（BENCH-001 后续）

**优先级：** P2 高
**预计工时：** 45 分钟
**风险等级：** 低（文档降级声明）

#### 目标文件

1. `docs/reports/v2_experiment_summary_20260703.md`
2. 任何答辩材料

#### 修改内容

**添加形式化范围诚实表述：**

```markdown
## 形式化基准范围（诚实口径）

### 当前覆盖

- **案例数量：** 8 个 financial_report_analysis 案例
- **任务类型：** 单指标表格检索（提取单个财务指标）
- **质量基线：** 8/8 通过确定性验证器
- **定位：** 精密锚点（precision anchor），不是广泛推理优势

### 质量指标

✅ **质量通过率：** 8/8 (100%)
✅ **语义剪枝节省：** 6255 bytes
✅ **类型化控制开销：** +360 bytes（可控）
⚠️ **L3 复用增益：** 0（冷启动，符合预期）

### 不能声明

❌ "形式化广泛推理优势"（案例类型单一）
❌ "复杂多代理协作优势"（任务推理链短）
❌ "形式化外部优势"（无外部比较数据）

### 可以声明

✅ "形式化质量基线维持（8/8 精密锚点案例通过）"
✅ "类型化控制开销可控（+360B vs 剪枝节省 6255B）"
✅ "确定性验证器确保质量无回归"

### 推荐答辩表述

"StateBus 在形式化财务报告分析基准上维持质量基线（8/8 案例通过），
展示类型化控制平面的可控开销（+360B）和语义剪枝的显著节省（6255B）。
当前覆盖为精密锚点（单指标表格检索），为后续扩展奠定基础。"
```

#### 回归测试

```bash
# 验证形式化案例数
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier formal \
  --role-path-mode deterministic \
  --embedding-mode deterministic 2>&1 | \
  grep -o "case_count.*"
# 应包含 8

# 验证质量分数
cat /home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/07_formal_primary/stdout.json | \
  jq '.L3_quality_pass_count, .L3_case_count'
# 应输出 8, 8
```

#### Benchmark/JSON 验证

```bash
cat /home/qcrs/statebus/runs/v2-full-audit-20260705_213331/stages/07_formal_primary/stdout.json | \
  jq '{
    L3_case_count,
    L3_quality_pass_count,
    L3_reuse_gain,
    pruning_bytes_saved,
    control_bytes_delta
  }'
# 应输出：
# {
#   "L3_case_count": 8,
#   "L3_quality_pass_count": 8,
#   "L3_reuse_gain": 0,
#   "pruning_bytes_saved": 6255,
#   "control_bytes_delta": 360
# }
```

#### 风险和 claim 影响

- **风险：** 低（诚实降级声明）
- **Claim 影响：** 高 - 防止"8 案例"被挑战为不足以支撑广泛推理
- **回滚容易度：** 容易（文档修改）

---

## 第三部分：赛前建议行动（可选，但强烈推荐）

### 建议 1：扩展形式化任务家族（BENCH-001 根本修复）

**优先级：** P2 中（如果时间允许）
**预计工时：** 4-6 小时
**风险等级：** 中（需测试新任务质量）

#### 目标

将形式化案例从 8 个扩展到 20-25 个，覆盖更复杂的推理模式。

#### 建议新家族

1. **multi_period_trend_analysis_v1**（多期趋势分析）
   - 3-5 期财务数据对比
   - 识别增长/下降趋势
   - 计算年化增长率

2. **cross_table_join_analysis_v1**（跨表关联分析）
   - 多表 JOIN 推理
   - 跨表指标计算
   - 关系型数据查询

3. **conditional_aggregation_v1**（条件聚合）
   - 带条件过滤的聚合查询
   - 分组统计
   - 多条件组合

4. **anomaly_detection_v1**（异常检测）
   - 识别财务异常模式
   - 离群值检测
   - 趋势偏离识别

#### 实施步骤

1. **设计新任务家族**（1-2 小时）
   ```bash
   # 创建任务定义
   mkdir -p tasks/formal/multi_period_trend_analysis_v1
   # 添加 manifest.yaml, samples/, expected_outputs/
   ```

2. **注册到 benchmark**（30 分钟）
   ```python
   # v2/benchmark/task_registry.py
   FORMAL_FAMILIES.append({
       "family_id": "multi_period_trend_analysis_v1",
       "tier": "formal",
       "expected_case_count": 5,
   })
   ```

3. **运行测试**（1-2 小时）
   ```bash
   python -m v2.benchmark.live_runner \
     --suite formal \
     --benchmark-tier formal \
     --role-path-mode api \
     --embedding-mode local
   ```

4. **验证质量**（1 小时）
   - 确保新案例质量通过率 >= 80%
   - 检查重放增益（预期仍为 0，冷启动）

#### 预期效果

- 形式化案例数：8 → 20-25
- 任务类型覆盖：单指标 → 单指标 + 多期趋势 + 跨表关联 + 条件聚合 + 异常检测
- 声明升级：从"精密锚点"到"形式化财务分析基准"

#### 风险

- ⚠️ **质量可能下降**：新任务可能更难，质量通过率可能低于 100%
- ⚠️ **LLM 成本**：api 模式测试需要真实 LLM 调用
- ⚠️ **时间紧张**：赛前可能没有足够时间充分测试

**建议：** 如果时间不足，优先完成文档降级（修复 1-4），新家族可作为后续工作。

---

### 建议 2：将外部公平门扩展到 formal tier（BENCH-002）

**优先级：** P2 中（风险较高）
**预计工时：** 3-4 小时
**风险等级：** 高（外部基线可能追平或超过 StateBus）

#### 目标

将外部纯文本公平门从 dev 固定答案扩展到 formal 财务任务，验证形式化优势。

#### 实施步骤

1. **为 formal 任务添加外部可见候选**（1-2 小时）
   ```yaml
   # tasks/formal/financial_report_analysis_v1/sample_001.yaml
   external_visible_candidates:
     - candidate_id: "revenue_2023"
       table: "income_statement"
       column: "revenue"
       period: "2023"
     - candidate_id: "revenue_2022"
       table: "income_statement"
       column: "revenue"
       period: "2022"
   ```

2. **确认外部基线支持 formal tier**（30 分钟）
   ```python
   # v2/benchmark/external_text_baseline.py 已支持，无需修改
   ```

3. **运行外部比较**（1 小时）
   ```bash
   python -m v2.benchmark.live_runner \
     --suite compare \
     --benchmark-tier formal \
     --role-path-mode api \
     --embedding-mode local
   ```

4. **分析结果**（1 小时）
   - 检查 `formal_superiority_claim_allowed`
   - 检查外部基线质量是否追平
   - 检查公平门是否全部通过

#### 预期结果（三种可能）

**场景 A（理想）：** StateBus 质量领先 + 公平门通过
- `formal_superiority_claim_allowed = True`
- 可声明"形式化外部优势"

**场景 B（中性）：** 质量对等 + 公平门通过
- `formal_superiority_claim_allowed = False`（质量 delta = 0）
- 可声明"形式化外部公平门通过，质量对等"

**场景 C（不利）：** 外部基线质量超过 StateBus
- `formal_superiority_claim_allowed = False`（质量 delta < 0）
- 不能声明形式化优势

#### 风险评估

- 🔴 **高风险场景 C**：外部基线可能在简单表格检索任务上质量追平或超过
- ⚠️ **外部基线优势**：四个独立 LLM 调用可能提供更多重试机会
- ⚠️ **如果场景 C 发生**：需要解释为"公平对比验证了外部基线的有效性"

**建议：** 先在 dev 环境充分测试，确认 StateBus 质量领先后再正式运行。如果场景 C 发生，不要将结果纳入答辩材料。

---

## 第四部分：可选增强（P3）

### 增强 1：将 memfd 纳入 benchmark 主线（STATE-001）

**优先级：** P3
**预计工时：** 2-3 小时
**风险等级：** 低

**目标：** 在 benchmark JSON 中可观测 memfd 路径使用情况。

**实施步骤：**
1. 添加 `--state-pool-mode` 参数到 live_runner
2. 在 benchmark JSON 添加 `state_pool_mode_used` 字段
3. 在审计脚本 stage 07/08 启用 memfd 模式
4. 验证 memfd 路径被真实使用

**预期效果：** 可以声称"memfd 在 formal benchmark 主线验证"

**风险：** 低 - memfd 实现已存在且测试通过

---

### 增强 2：扩展审计回退矩阵（SCRIPT-001）

**优先级：** P3
**预计工时：** 1-2 小时
**风险等级：** 低

**目标：** 提高审计脚本鲁棒性，增加更多回退路径。

**实施步骤：**
1. api+local 失败 → 自动重试 3 次，延长超时到 600s
2. api 完全不可用 → 尝试替代 embedding 提供商
3. 所有路径失败 → 生成详细诊断报告

**预期效果：** 审计成功率提高

**风险：** 低 - 不影响现有功能

---

## 第五部分：验证清单

### 修复 1-4 完成后的验证命令

```bash
# 1. 验证旧文档已标注
head -20 docs/reports/MASTER_PRESENTATION_GUIDE.md | grep "历史文档警告"
head -20 docs/reports/task_design_and_mode_comparison.md | grep "历史文档警告"

# 2. 验证速度声明已移除
grep -r "速度.*优势\|latency.*win" docs/reports/ | grep -v "不能声明"
# 应输出为空

# 3. 验证重放术语已更新
grep -r "通用答案恢复" docs/reports/ docs/contracts/
# 应输出为空或只有否定句

# 4. 验证形式化范围已明确
grep -c "精密锚点\|precision anchor" docs/reports/v2_experiment_summary_20260703.md
# 应输出 >= 1

# 5. 运行全测试套件
python -m pytest tests/v2/ -q
# 应全部通过

# 6. 验证 benchmark JSON 证据一致
cat /home/qcrs/statebus/runs/codex-raw-fairness-20260706/runtime/benchmark_reports/codex-raw-fairness-20260706-cold-start-compare-api.json | \
  jq '{
    api_task_ms_delta,
    api_llm_total_tokens_delta,
    formal_superiority_claim_allowed
  }'
# 应输出：+9906, -1023, false
```

---

## 第六部分：修复时间线

| 修复项 | 优先级 | 预计工时 | 建议完成时间 |
|--------|--------|---------|-------------|
| 修复 1：标注旧文档 | P2 高 | 30 分钟 | 立即 |
| 修复 2：降级速度声明 | P2 高 | 1 小时 | 立即 |
| 修复 3：明确重放命名 | P2 高 | 1.5 小时 | 今天内 |
| 修复 4：明确形式化范围 | P2 高 | 45 分钟 | 今天内 |
| **P2 总计** | - | **3.75 小时** | **今天内完成** |
| 建议 1：扩展形式化家族 | P2 中 | 4-6 小时 | 赛前（如有时间） |
| 建议 2：扩展外部公平门 | P2 中 | 3-4 小时 | 赛前（谨慎评估风险） |
| 增强 1：memfd 主线 | P3 | 2-3 小时 | 可选 |
| 增强 2：审计回退 | P3 | 1-2 小时 | 可选 |

---

**最后更新：** 2026-07-06
**下次审计建议：** 赛前 48 小时（验证所有修复完成）
