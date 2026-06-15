# 基于审计报告的验证与修复 Prompt

日期：2026-06-15

交给能读长上下文的新模型窗口。目标：先验证审计报告中每个问题是否合理，再给出详细解决方案。

```text
你现在在 `/home/qcrs/statebus/project` 工作。

你的任务分两步：第一步验证问题是否合理，第二步给出详细解决方案。

## 必须先读的文件（按顺序）

1. `docs/reference/题目.md` — 赛题原文，最高约束
2. `docs/analysis/full_system_audit_20260615.md` — 全系统审计报告（问题清单）
3. `docs/analysis/experimental_anomalies_20260615.md` — 实验数据异常清单
4. `docs/analysis/requirements_decomposition.md` — 赛题要求拆解

## 第一步：逐个验证问题是否合理

对审计报告中列出的每一个问题，逐一回答：

1. 在代码中找到对应的位置，确认问题描述是否准确
2. 如果问题描述不准确，说明实际代码行为是什么
3. 如果问题存在但严重性被高估，说明为什么影响有限
4. 如果问题确实严重，确认审计报告中的描述和定位是否正确
5. 如果发现了审计报告中没提到的新问题，补充进来

你需要重点验证的问题类别：
- Planner 是否真的在所有 benchmark 上被绕过
- Corpus 预标签对检索/路由的影响到底有多大
- `build_feature_bundle()` 的双重调用是否真的发生
- Protocol summarizer 的 token 膨胀机制
- Consumer sensitivity 的 negative control 为什么只有 3/15 触发
- memory_hit_rate 的实际度量口径
- Open surface 的数据是不是真实 LLM 跑出来的
- handoff_bytes 的跨模式抄写问题

对于每个问题，需要给出：
- 代码文件:行号 作为证据
- "问题成立" / "问题不成立" / "问题存在但严重性需调整" 的判断
- 如果调整严重性，说明原因

## 第二步：给出详细解决方案

只针对验证后确认成立的问题。方案必须：

1. **严格对齐赛题要求**：每个方案的动机必须引用 `题目.md` 中的原文要求或评分细则
2. **落到代码层面**：给出具体的文件路径和修改方向（不需要写出完整代码，但要说清楚改哪个函数、哪个逻辑分支）
3. **落到 benchmark 层面**：如果需要改 YAML、改 corpus、改 task 定义，具体说明改哪个 pack、哪个字段
4. **区分阶段**：
   - 必须做的（不做会影响赛题基本要求的满足）
   - 应该做的（做了能显著提升评分）
   - 可以做的（锦上添花）
5. **说明预期效果**：每个方案修完之后，benchmark 的哪个指标预期会怎么变

### 暂时不碰的领域

以下内容不要出现在方案中：
- Docker 部署
- openEuler VM 迁移
- nsjail 沙箱
- API repeat=10 真实验证（可以提"需要验证"但不要给具体执行步骤）
- 生产级性能优化

### 方案聚焦的领域

- `plan_source` 的默认值策略和 Planner 启用
- `_plan_from_llm_output()` 的合同校验逻辑
- Corpus 的预标签字段（`route_hint` / `tool_name`）和任务难度
- `contest_dual_mode_controlled_v3` 的 single_variable 声明和变量控制
- `build_feature_bundle()` 在 executor 侧的冗余调用
- Summarizer 的结构化→文本→LLM 往返
- `memory_hit_rate` 的度量口径和 naming
- Consumer sensitivity 的 negative control 失效
- handoff_bytes 的跨 mode 指标聚合
- Open surface 的数据来源（确认是 real LLM 还是 stub）
- Task 的鉴别诊断难度（多 route 候选、跨 family 推理）
- `runtime_reuse_contract` 在 contest 包上的设置

## 输出格式

### 第一部分：问题验证

对每个问题输出：

```
### 问题 [编号]: [标题]

**审计报告定位**: [文件:行号]

**实际代码验证**: 
- 确认/否认 审计报告的描述，引用具体代码行

**判断**: 成立 / 不成立 / 严重性需调整

**理由**: [如果调整，说明原因]
```

### 第二部分：解决方案

按 "必须做 → 应该做 → 可以做" 三段排列。每个方案输出：

```
### 方案 [编号]: [标题]

**对齐赛题要求**: [引用题目.md 原文 + 评分项]

**涉及文件**:
- `path/file.py:行号` — 改动描述

**改动说明**: [具体改什么，怎么改]

**预期效果**: [benchmark 哪个指标预期从 X 变成 Y]

**风险**: [可能的副作用]
```

## 约束

- 用中文
- 不要泛泛而谈"应该优化"，每一处都落到文件:行号
- 不要给出不基于审计报告发现的新问题（除非你在验证过程中真的发现了遗漏）
- 方案不要动 Docker/openEuler/nsjail
- 方案不要假设你能跑 API repeat=10（可以提"需要验证"但不给执行步骤）
```
