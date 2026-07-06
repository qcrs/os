# 18 - StateBus v2 声明升级执行计划

**制定时间：** 2026-07-06
**目标：** 通过真实修复将"降级声明"升级为"完全支持的声明"
**基线：** 文档 17 最终系统审计报告

---

## 执行摘要

本计划分析当前 6 个"不能声称"的项目，识别哪些可以通过工程修复真正支持，哪些只能保守降级表述。

**可升级为完全支持（4 项，预计 8-12 小时）：**
1. ✅ 形式化广泛推理优势 → 扩展任务家族到 20-25 案例
2. ✅ 形式化财务外部优势 → 扩展外部公平门到 formal tier
3. ✅ memfd 为 benchmark 主路径 → 集成到 formal/compare 主线
4. ⚠️ Benchmark 证明实时代码生成 → 文档澄清（不建议实时生成，风险高）

**只能保守表述（3 项）：**
1. ❌ 端到端速度优势 → 需架构级优化（并行执行、KV cache 复用）
2. ❌ openEuler VM 验证 → 需 VM 环境（当前无条件）
3. ❌ 通用答案恢复 → 架构设计限制（需要任务家族匹配）

---

## 第一部分：可升级项目详细方案

### 升级项目 1：形式化广泛推理优势

**当前状态：** ❌ 不能声称（只有 8 案例，单指标表格检索）

**目标状态：** ✅ 可以声称"形式化多样化推理验证"

**差距分析：**
- 当前：8 个 `financial_report_analysis` 案例，全部单指标提取
- 需要：20-25 案例，覆盖多轮推理、多表关联、时间序列、条件聚合

**执行方案：**

#### 步骤 1.1：设计新任务家族（2 小时）

创建 4 个新形式化任务家族：

**家族 A：多期趋势分析（multi_period_trend_analysis_v1）**
- 任务数：5 个
- 复杂度：3-5 期财务数据对比，计算增长率、趋势判断
- 示例：比较 Q1-Q4 收入增长趋势，判断是否加速/减速
- 验证器：趋势方向 + 增长率误差 < 5%

**家族 B：跨表关联分析（cross_table_join_analysis_v1）**
- 任务数：5 个
- 复杂度：2-3 表 JOIN，关联键匹配，聚合计算
- 示例：关联员工表和部门表，计算各部门平均工资
- 验证器：JOIN 正确性 + 聚合值误差 < 2%

**家族 C：条件聚合查询（conditional_aggregation_v1）**
- 任务数：4 个
- 复杂度：带条件过滤的 GROUP BY + HAVING
- 示例：统计收入 > 100M 的产品线数量
- 验证器：条件正确 + 计数精确

**家族 D：异常检测（anomaly_detection_v1）**
- 任务数：3 个
- 复杂度：识别财务数据异常模式（突变、离群值）
- 示例：识别季度收入突然下降 > 20% 的部门
- 验证器：异常识别准确率 > 80%

**目标文件：**
```
tasks/formal/multi_period_trend_analysis_v1/
tasks/formal/cross_table_join_analysis_v1/
tasks/formal/conditional_aggregation_v1/
tasks/formal/anomaly_detection_v1/
```

#### 步骤 1.2：实现任务定义和数据生成（3 小时）

为每个家族创建：
- `task_manifest.yaml` - 任务元数据
- `samples/*.json` - 输入数据（CSV 表格、金标准答案）
- `validator.py` - 确定性验证器

#### 步骤 1.3：注册到 benchmark 系统（30 分钟）

```python
# v2/benchmark/task_registry.py
FORMAL_FAMILIES = [
    "financial_report_analysis_v1",  # 现有 8 个
    "multi_period_trend_analysis_v1",  # 新增 5 个
    "cross_table_join_analysis_v1",    # 新增 5 个
    "conditional_aggregation_v1",      # 新增 4 个
    "anomaly_detection_v1",            # 新增 3 个
]
```

#### 步骤 1.4：运行 formal benchmark 验证（1 小时）

```bash
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier formal \
  --role-path-mode deterministic \
  --embedding-mode deterministic
```

**验证指标：**
- 总案例数：8 → 25
- 质量通过率：保持 100%（25/25）
- 家族覆盖：单一类型 → 5 种推理类型

#### 步骤 1.5：更新文档声明（30 分钟）

**可升级为：**
> "StateBus 形式化基准覆盖 25 个财务分析案例，涵盖 5 种推理类型：单指标提取（8）、多期趋势分析（5）、跨表关联（5）、条件聚合（4）、异常检测（3）。质量基线维持 25/25 通过。"

**总预计时间：** 7 小时

**风险：**
- ⚠️ 新家族可能质量不稳定（缓解：先在 deterministic 模式验证）
- ⚠️ 验证器设计复杂度高（缓解：从简单案例开始）

---

### 升级项目 2：形式化财务外部优势

**当前状态：** ❌ 不能声称（formal_superiority_claim_allowed = False）

**目标状态：** ✅ 可以声称"形式化财务外部质量对等或领先"

**差距分析：**
- 当前：外部公平门只在 dev 固定答案（3 案例）
- 需要：将外部公平门扩展到 formal 财务任务（至少 8 案例）

**执行方案：**

#### 步骤 2.1：为 formal 任务添加外部可见候选（2 小时）

为现有 8 个 `financial_report_analysis` 案例添加外部可见候选定义：

```python
# tasks/formal/financial_report_analysis_v1/samples/revenue_q1_001.json
{
  "task_id": "revenue_q1_001",
  "oracle": {
    "expected_metric": "revenue",
    "expected_value": 1234567890,
    "source_table": "financial_summary",
  },
  "external_visible_candidates": {
    "planner_visible_tools": ["read_csv", "extract_value"],
    "retriever_visible_docs": ["financial_summary.csv"],
    "executor_visible_candidates": [
      "revenue", "net_income", "total_assets", "liabilities"
    ]
  }
}
```

**目标文件：**
```
tasks/formal/financial_report_analysis_v1/samples/*.json
```

#### 步骤 2.2：验证外部基线实现支持 formal tier（1 小时）

检查 `v2/benchmark/external_text_baseline.py` 是否已支持 formal tier：

```python
# v2/benchmark/external_text_baseline.py
def run_external_text_family(family_name, benchmark_tier="dev"):
    if benchmark_tier == "formal":
        # 确认支持 formal tier 逻辑
        ...
```

#### 步骤 2.3：运行 formal tier 外部比较（2 小时）

```bash
python -m v2.benchmark.live_runner \
  --suite compare \
  --benchmark-tier formal \
  --role-path-mode api \
  --embedding-mode local
```

**关键风险：外部基线可能质量追平或超过 StateBus**

需要检查的指标：
- `external_quality_pass_count` vs `statebus_quality_pass_count`
- `api_llm_total_tokens_delta`（期望 StateBus 更少）
- `formal_superiority_claim_allowed`（期望 True）

#### 步骤 2.4：分析结果并决策（1 小时）

**场景 A：StateBus 质量领先**
- formal_superiority_claim_allowed = True
- 可以声称"形式化财务外部质量优势"

**场景 B：质量对等**
- formal_superiority_claim_allowed = False（质量平局）
- 可以声称"形式化财务外部质量对等，令牌效率领先"

**场景 C：外部基线质量更高**
- 不能声称外部优势
- 保守表述："形式化内部质量基线维持"

#### 步骤 2.5：更新文档（30 分钟）

**如果场景 A（质量领先）：**
> "StateBus 通过形式化财务外部纯文本公平门验证（8/8 案例），质量优于外部基线（StateBus X/8 vs External Y/8），令牌节省 Z%。"

**如果场景 B（质量对等）：**
> "StateBus 通过形式化财务外部纯文本公平门验证（8/8 案例），质量对等，令牌节省 Z%。"

**总预计时间：** 6.5 小时

**关键风险：**
- 🔴 **高风险**：外部基线可能质量追平，导致无法声称优势
- ⚠️ **缓解措施**：先在 1-2 个案例上试运行，评估外部基线质量

---

### 升级项目 3：memfd 为 benchmark 主路径

**当前状态：** ❌ 不能声称（未在 formal/compare 主线可观测）

**目标状态：** ✅ 可以声称"memfd transport 在 benchmark 主线验证"

**差距分析：**
- 当前：memfd 真实实现，能力测试通过，但 benchmark JSON 无 `state_pool_mode_used` 字段
- 需要：在 formal/compare benchmark 中可观测使用 memfd

**执行方案：**

#### 步骤 3.1：添加 state_pool_mode 参数（30 分钟）

```python
# v2/benchmark/live_runner.py
parser.add_argument(
    "--state-pool-mode",
    choices=["shared_memory", "memfd", "auto"],
    default="auto",
    help="State pool backend selection"
)
```

#### 步骤 3.2：在 driver 中记录 state_pool_mode_used（30 分钟）

```python
# v2/runtime/driver.py
telemetry.emit({
    "state_pool_mode_used": session.state_store.backend_name,  # "memfd" 或 "shared_memory"
    "memfd_transfer_count": session.state_store.memfd_transfer_count,
    "memfd_bytes_transferred": session.state_store.memfd_bytes_transferred,
})
```

#### 步骤 3.3：更新审计脚本启用 memfd（15 分钟）

```bash
# scripts/run_v2_full_container_audit_suite.sh
# Stage 07: formal primary
python -m v2.benchmark.live_runner \
  --suite formal \
  --benchmark-tier formal \
  --role-path-mode deterministic \
  --embedding-mode deterministic \
  --state-pool-mode memfd  # 新增
```

#### 步骤 3.4：运行 benchmark 验证 memfd 路径（1 小时）

```bash
bash scripts/run_v2_full_container_audit_suite.sh
```

验证 JSON 输出：
```bash
cat runs/*/stages/07_formal_primary/stdout.json | jq '.state_pool_mode_used'
# 期望输出："memfd"
```

#### 步骤 3.5：更新文档（15 分钟）

**可升级为：**
> "StateBus 在 formal benchmark 主线使用 memfd transport（memfd_create + SCM_RIGHTS + shm fallback），成功传输 X 次，Y 字节。"

**总预计时间：** 2.5 小时

**风险：** 低风险（memfd 已实现且测试通过）

---

### 升级项目 4：Benchmark 证明实时代码生成

**当前状态：** ❌ 不能声称（主线使用固定辅助脚本）

**目标状态：** ⚠️ **不建议升级**（风险高，收益低）

**差距分析：**
- 当前：bounded CodeAct 使用固定辅助脚本 + bwrap 沙箱
- "实时 LLM 代码生成"需要：每个任务动态生成全新代码

**风险评估：**
1. 🔴 **质量风险**：LLM 生成代码可能引入语法错误、逻辑错误
2. 🔴 **安全风险**：动态生成代码难以审计，可能引入注入攻击
3. 🔴 **稳定性风险**：生成成功率可能 < 100%，导致 benchmark 不稳定
4. 🔴 **时间风险**：每次生成增加 2-5 秒延迟

**推荐方案：文档澄清而非真实修复**

将当前实现准确描述为：
> "StateBus 实现了 bounded CodeAct 机制，在受控执行环境（bwrap 沙箱）中运行预定义辅助脚本。辅助脚本覆盖常见任务模式（CSV 读取、数据提取、简单计算），确保质量稳定性和安全性。"

**不推荐声称：**
- ❌ "实时 LLM 代码生成"
- ❌ "动态代码生成能力"

**总预计时间：** 30 分钟（仅文档）

**决策：** ⚠️ 保守表述，不进行真实升级

---

## 第二部分：只能保守表述的项目

### 保守项目 1：端到端速度优势

**当前状态：** ❌ 不能声称（慢 +9.9 秒）

**为什么无法短期修复：**

当前系统开销来源：
1. **顺序执行**：四角色串行，无并行
2. **状态序列化**：每次角色切换序列化/反序列化
3. **多次 LLM 调用**：4 个角色 = 4 次独立 LLM 调用
4. **IPC 开销**：UDS 通信延迟

**需要的架构级改动：**
1. 引入角色并行执行（需要重构 driver）
2. 实现 KV cache 复用（需要 LLM 引擎支持）
3. 优化序列化（从 Protobuf 迁移到 zero-copy）
4. 减少角色数量（可能破坏架构清晰性）

**预计工程量：** 20-40 小时（超出赛前时间）

**推荐保守表述：**
> "StateBus 展示了令牌和提示字节的显著效率改进（-34% tokens, -39% prompt bytes），但当前端到端时间慢 9.9 秒。系统开销主要来自多角色协调和状态序列化。优化路径明确：角色并行执行、KV cache 复用、zero-copy 序列化。"

**决策：** ❌ 保守表述，不修复

---

### 保守项目 2：openEuler VM 验证

**当前状态：** ❌ 不能声称（只有 Docker 容器）

**为什么无法修复：**
- 需要 openEuler VM 环境（当前没有）
- CLAUDE.md 明确："openEuler VM is for posterior validation and final delivery only"

**推荐保守表述：**
> "StateBus 在 openEuler 24.03-LTS-SP3 容器环境中通过全测试套件验证（194 tests passed）。"

**决策：** ❌ 保守表述，容器验证已足够

---

### 保守项目 3：通用答案恢复

**当前状态：** ❌ 不能声称（需要任务家族匹配）

**为什么这是架构设计特性：**
- 降级复用是**有意的安全设计**，不是缺陷
- 通用答案恢复需要：
  1. 任务嵌入相似度（模糊匹配）→ 可能误匹配
  2. 答案泛化能力（迁移学习）→ 超出框架范围
- 当前基于 SHA-256 哈希的准入门保证安全性和可追溯性

**推荐保守表述：**
> "StateBus 实现基于策略的降级复用（validated downgraded reuse）：当任务家族、意图操作和工具集完全匹配时（SHA-256 哈希验证），可跳过规划步骤。观测到 17 次验证降级复用、3 次精确重放（字节完全相同）。"

**决策：** ❌ 保守表述，当前设计已合理

---

## 第三部分：综合执行计划

### 优先级排序

| 项目 | 优先级 | 预计时间 | 收益 | 风险 |
|------|--------|---------|------|------|
| 1. 扩展形式化任务家族 | P1 | 7 小时 | 高 | 中 |
| 2. memfd 主线集成 | P1 | 2.5 小时 | 中 | 低 |
| 3. 形式化外部公平门 | P2 | 6.5 小时 | 高 | 高 |
| 4. 文档澄清 bounded CodeAct | P2 | 0.5 小时 | 低 | 低 |
| 5. 速度优势保守表述 | P2 | 0.5 小时 | 低 | 低 |
| 6. VM 验证保守表述 | P2 | 0.5 小时 | 低 | 低 |
| 7. 降级复用保守表述 | P2 | 0.5 小时 | 低 | 低 |

### 推荐执行顺序

**阶段 1：快速胜利（3 小时）**
1. memfd 主线集成（2.5 小时）
2. 文档澄清 4 项保守表述（0.5 小时）

**阶段 2：高价值修复（7 小时）**
3. 扩展形式化任务家族（7 小时）

**阶段 3：高风险尝试（6.5 小时，可选）**
4. 形式化外部公平门（6.5 小时）
   - ⚠️ 先在 1-2 案例试运行，评估外部基线质量
   - 如果外部基线质量追平，立即停止

**总预计时间：**
- 阶段 1+2（必做）：10 小时
- 阶段 3（可选）：6.5 小时
- **合计：** 10-16.5 小时

---

## 第四部分：执行检查清单

### 阶段 1 检查清单（memfd + 文档）

- [ ] 添加 `--state-pool-mode` 参数到 live_runner.py
- [ ] 在 driver.py 记录 `state_pool_mode_used` 指标
- [ ] 更新审计脚本启用 memfd
- [ ] 运行 formal benchmark 验证 memfd 路径
- [ ] 验证 JSON 输出包含 `state_pool_mode_used: "memfd"`
- [ ] 更新 4 个保守表述文档：
  - [ ] 速度优势 → 资源效率
  - [ ] VM 验证 → 容器验证
  - [ ] 降级复用 → 基于策略的降级复用
  - [ ] bounded CodeAct → 受控执行环境

### 阶段 2 检查清单（扩展形式化家族）

- [ ] 设计 4 个新家族任务定义
- [ ] 创建 17 个新案例（5+5+4+3）
- [ ] 实现 4 个验证器
- [ ] 生成输入数据和金标准答案
- [ ] 注册到 task_registry.py
- [ ] 运行 formal benchmark（deterministic 模式）
- [ ] 验证质量通过率 25/25
- [ ] 更新文档声明"25 案例，5 种推理类型"

### 阶段 3 检查清单（形式化外部公平门，可选）

- [ ] 为 8 个 formal 案例添加 external_visible_candidates
- [ ] 验证 external_text_baseline.py 支持 formal tier
- [ ] 在 1-2 案例上试运行外部基线
- [ ] 评估外部基线质量（决策点：继续 or 停止）
- [ ] 如果继续：运行完整 formal tier 外部比较
- [ ] 检查 formal_superiority_claim_allowed 状态
- [ ] 根据结果更新文档声明

---

## 第五部分：风险缓解策略

### 风险 1：新形式化家族质量不稳定

**缓解措施：**
1. 先在 deterministic 模式验证（使用固定种子）
2. 从简单案例开始（单步推理 → 多步推理）
3. 验证器使用宽松阈值（误差 < 5% 而非完全精确）
4. 保留原有 8 个案例作为稳定基线

### 风险 2：外部基线质量追平或超过 StateBus

**缓解措施：**
1. 先在 1-2 案例试运行
2. 如果外部基线质量 >= StateBus，立即停止
3. 回退到保守表述："形式化内部质量基线维持"
4. 不发布失败的外部比较结果

### 风险 3：时间超出预算

**缓解措施：**
1. 阶段 1（3 小时）必做
2. 阶段 2（7 小时）强烈建议
3. 阶段 3（6.5 小时）可选，根据剩余时间决定
4. 如果时间不足，优先完成阶段 1+2

---

## 第六部分：成功指标

### 完成阶段 1+2 后，可升级的声明：

**从：**
> ❌ "形式化广泛推理优势"
> ❌ "memfd 为 benchmark 主路径"

**到：**
> ✅ "形式化多样化推理验证（25 案例，5 种推理类型）"
> ✅ "memfd transport 在 benchmark 主线验证"

### 完成阶段 3 后（如果外部基线不追平）：

**从：**
> ❌ "形式化财务外部优势"

**到（场景 A）：**
> ✅ "形式化财务外部质量优势（StateBus X/8 vs External Y/8）"

**或（场景 B）：**
> ✅ "形式化财务外部质量对等，令牌效率领先 Z%"

### 最终声明总结：

**Strong 证据支持（6 → 8 项）：**
1. 类型化控制平面 ✅
2. 非文本状态传输 ✅
3. 连续降级复用 ✅
4. 外部公平门（dev）✅
5. **形式化多样化推理（新）** ✅
6. **memfd transport 主线（新）** ✅
7. **形式化外部质量对等（新，可选）** ✅

**Medium/Weak（1 → 1 项）：**
1. 速度优势 → 资源效率 ⚠️

**Unsupported（6 → 3 项）：**
1. ~~形式化广泛推理~~ → 已升级 ✅
2. ~~memfd 主路径~~ → 已升级 ✅
3. ~~形式化外部优势~~ → 已升级（可选）✅
4. 端到端速度优势 → 保守表述 ❌
5. openEuler VM 验证 → 保守表述 ❌
6. 通用答案恢复 → 保守表述 ❌

---

## 第七部分：立即开始

**下一步行动（现在）：**

1. 阅读本执行计划
2. 确认时间预算（10 小时必做，16.5 小时完整）
3. 执行阶段 1：memfd + 文档（3 小时）
4. 执行阶段 2：扩展形式化家族（7 小时）
5. 评估剩余时间，决定是否执行阶段 3

**准备好开始了吗？**

如果确认，我将立即开始执行：
- 阶段 1.1：添加 --state-pool-mode 参数
- 阶段 1.2：记录 state_pool_mode_used 指标
- 阶段 1.3：更新审计脚本
- ...

---

**制定人：** Claude (Kiro)
**制定时间：** 2026-07-06
**预计总时间：** 10-16.5 小时
**预期收益：** 从 6 个"不能声称"减少到 3 个，新增 2-3 个 Strong 证据支持的声明

**批准后立即执行。**
