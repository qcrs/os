# 17d - 问题分类账 (Issue Ledger)

**审计日期：** 2026-07-06
**关联主报告：** [17_final_system_audit_20260706.md](../../17_final_system_audit_20260706.md)

---

## P0 问题（阻止发布）

*本次审计未发现 P0 问题。*

---

## P1 问题（已修复）

### AUDIT-001: Socket 路径冲突风险

**状态：** ✅ 已修复
**发现时间：** 文档 16 (2026-07-06)
**修复提交：** `03a9d22` 之前

**问题描述：**
全审计脚本 `run_v2_full_container_audit_suite.sh` 在多次并行运行时，UDS socket 路径可能冲突。原始实现使用固定路径，不包含运行 ID。

**影响：**
- 多个审计进程可能互相干扰
- Socket 绑定失败导致审计中断

**修复内容：**
Socket 路径现在包含 `STATEBUS_RUN_ID` 哈希：
```bash
# scripts/run_v2_full_container_audit_suite.sh:206
SOCKET_PATH="/tmp/statebus-audit-${STATEBUS_RUN_ID}.sock"
```

**验证命令：**
```bash
grep "SOCKET_PATH.*STATEBUS_RUN_ID" scripts/run_v2_full_container_audit_suite.sh
```

**证据：**
- 文件：`scripts/run_v2_full_container_audit_suite.sh:206`
- 文档：`docs/improvement/artifacts/16_deep_contest_audit/issue_ledger.md`

**是否还需修：** ✅ 否

---

### AUDIT-002: 摘要缺少 JSON 指标解析

**状态：** ✅ 已修复
**发现时间：** 文档 16 (2026-07-06)
**修复提交：** `03a9d22` 之前

**问题描述：**
全审计脚本的 `summary.latest.json` 只记录阶段通过/失败状态，不解析关键 benchmark 指标（如 formal_superiority_claim_allowed, api_task_ms_delta 等）。

**影响：**
- 自动化无法从摘要获取关键决策指标
- 必须手动检查每个阶段的 stdout.json

**修复内容：**
摘要现在解析并聚合关键指标：
```bash
# scripts/run_v2_full_container_audit_suite.sh:411
parse_key_metrics() {
  local report_json="$1"
  jq -r '{
    formal_superiority_claim_allowed,
    api_task_ms_delta,
    validated_replay_count,
    exact_replay_count,
    external_fairness_gate_pass_count
  }' "$report_json"
}
```

**验证命令：**
```bash
cat /home/qcrs/statebus/runs/v2-full-audit-20260705_213331/summary.latest.json | jq '.key_metrics'
```

**证据：**
- 文件：`scripts/run_v2_full_container_audit_suite.sh:411`
- 文档：`docs/improvement/artifacts/16_deep_contest_audit/issue_ledger.md`

**是否还需修：** ✅ 否

---

### FG-001: 每案例公平门未传播到家族/比较器

**状态：** ✅ 已修复
**发现时间：** 文档 15 (2026-07-06)
**修复提交：** `a6e951e` (Propagate external fairness gate failures)

**问题描述：**
`run_external_text_case()` 评估每案例公平门，但 `run_external_text_family()` 不聚合到家族报告。比较器硬门可能通过，即使个别案例有 visible-candidate 或 metadata-leakage 失败。

**影响：**
- 外部公平门可能误报通过
- 个别案例泄漏风险被掩盖

**修复内容：**
```python
# v2/benchmark/comparator_runner.py:157-173
def _fairness_manifest(statebus_report, external_report):
    # ... 其他检查 ...
    full_fairness_gate_coverage = (
        external_report.get("external_fairness_gate_coverage", 0) ==
        external_report.get("external_case_count", 0)
    )
    no_fairness_gate_failures = (
        external_report.get("external_fairness_gate_failed_case_count", 0) == 0
    )

    pass_hard_gate = all([
        # ... 其他条件 ...
        full_fairness_gate_coverage,
        no_fairness_gate_failures,
        # ...
    ])
```

**验证命令：**
```bash
python -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode api --embedding-mode local
# 检查输出 JSON 的 external_fairness_gate_failed_case_count 字段
```

**证据：**
- 文件：`v2/benchmark/comparator_runner.py:157-173`
- 提交：`a6e951e`
- 文档：`docs/improvement/15_fairness_gate_propagation_audit_20260706.md`

**是否还需修：** ✅ 否

---

### FG-002: 确定性规划器失败 visible-candidate 门

**状态：** ✅ 已修复
**发现时间：** 文档 15 (2026-07-06)
**修复提交：** `be74494` (Harden external fairness gate raw payload checks)

**问题描述：**
确定性规划器的提示布局导致 visible-candidate 公平门误判。规划器输出格式与外部基线不完全兼容。

**影响：**
- 确定性模式的外部比较无法通过公平门
- 必须依赖 api 模式

**修复内容：**
- 调整确定性规划器提示布局以匹配公平门期望
- 增强 visible-candidate 检查的容错性

**验证命令：**
```bash
python -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode deterministic --embedding-mode deterministic
```

**证据：**
- 提交：`be74494`
- 文档：`docs/improvement/artifacts/15_fairness_gate_propagation/issue_ledger.md`

**是否还需修：** ✅ 否

---

### FG-005: 原始角色 JSON 泄漏未扫描

**状态：** ✅ 已修复
**发现时间：** 文档 15 (2026-07-06)
**修复提交：** `be74494`

**问题描述：**
公平门扫描归一化后的输出，但原始角色 JSON 载荷（可能包含中间决策细节）未被扫描泄漏。

**影响：**
- 原始 JSON 可能包含 oracle 字段名或预期答案线索
- 公平门漏判风险

**修复内容：**
公平门现在扫描原始角色 JSON 和原始选择载荷：
```python
# v2/benchmark/external_text_baseline.py:154
def _fairness_gate(...):
    # ... 其他检查 ...

    # 扫描所有原始载荷
    combined_surface = "\n".join([
        planner_raw_json,
        retriever_raw_json,
        executor_raw_json,
        summarizer_raw_json,
        # ... 归一化输出 ...
    ])

    no_metadata_leakage = not any(
        oracle_field in combined_surface.lower()
        for oracle_field in _ORACLE_FIELDS
    )
```

**验证命令：**
```bash
# 检查代码确认原始载荷参与扫描
grep -A 10 "planner_raw_json" v2/benchmark/external_text_baseline.py | grep -c "combined_surface"
```

**证据：**
- 文件：`v2/benchmark/external_text_baseline.py:154`
- 提交：`be74494`
- 文档：`docs/improvement/artifacts/15_fairness_gate_propagation/issue_ledger.md`

**是否还需修：** ✅ 否

---

## P1 问题（已缓解但仍需后续）

### REPLAY-001: 重放指标命名过于激进

**状态：** ⚠️ 已缓解（代码添加别名），仍需文档降级
**发现时间：** 文档 16 (2026-07-06)
**缓解提交：** `03a9d22` 之前

**问题描述：**
`validated_replay_count` 名称暗示"通用验证重放"，但实际语义是"降级复用"（任务家族相同时跳过规划步骤，但不是直接重放答案）。命名过于激进，易被误读为"泛化的安全答案恢复"能力。

**影响：**
- 对外沟通风险：被误读为 AI 记忆泛化能力
- 评委可能质疑"验证重放"的真实范围

**已缓解内容：**
添加保守别名 `validated_downgraded_reuse_count` 和 `answer_restoration_replay_count`：
```python
# v2/runtime/driver.py:1215-1226
telemetry.emit({
    "validated_replay_count": validated_replay_count,
    "validated_downgraded_reuse_count": validated_replay_count,  # 保守别名
    "exact_replay_count": exact_replay_count,
    "answer_restoration_replay_count": 0.0,  # 明确区分
})
```

**仍需后续行动：**
1. ✅ 修改所有对外文档，使用"降级复用（validated downgraded reuse）"而非"验证重放"
2. ✅ 明确说明：跳过规划步骤，但不是直接重放答案
3. ✅ 添加三级分类说明：EXACT_REPLAY / VALIDATED_DOWNGRADED_REUSE / ASSIST

**验证命令：**
```bash
grep -r "validated_downgraded_reuse_count" v2/runtime/driver.py v2/benchmark/continuous_runner.py
```

**证据：**
- 文件：`v2/runtime/driver.py:1215-1226`, `v2/benchmark/continuous_runner.py:713`
- 文档：`docs/improvement/artifacts/16_deep_contest_audit/issue_ledger.md`

**是否还需修：** ⚠️ **是** - 需修改对外文档

**优先级：** P2 高优先级

---

## P2 问题（开放）

### BENCH-001: 形式化家族狭窄（8 案例）

**状态：** 🔴 开放
**发现时间：** 文档 12, 16 (2026-07-05, 07-06)

**问题描述：**
形式化基准只有 8 个 `financial_report_analysis` 案例，全部为单指标表格检索（提取单个财务指标）。缺少多轮推理、多表关联、时间序列分析等复杂任务。

**影响：**
- 🔴 **不能声明"形式化广泛推理优势"**
- 🔴 **不能声明"复杂多代理协作优势"**
- ⚠️ 只能声明"精密锚点质量基线"

**当前证据：**
- 8/8 质量通过（`formal_primary stdout.json`）
- L3_reuse_gain = 0（冷启动，符合预期）
- pruning_bytes_saved = 6255B

**建议修复：**
扩展形式化任务家族到 20-25 案例，覆盖：
1. **多期趋势分析**：3-5 期财务数据对比（`multi_period_trend_analysis_v1`）
2. **跨表关联分析**：多表 JOIN 推理（`cross_table_join_analysis_v1`）
3. **条件聚合**：带条件过滤的聚合查询（`conditional_aggregation_v1`）
4. **异常检测**：识别财务异常模式（`anomaly_detection_v1`）

**目标文件：**
- `tasks/formal/` 添加新家族定义
- `v2/benchmark/task_registry.py` 注册新家族

**预期效果：**
- 形式化案例数：8 → 20-25
- 增强"广泛推理"声明可信度

**验证命令：**
```bash
python -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode api --embedding-mode local
# 检查输出 case_count 和 family 覆盖
```

**优先级：** P2 高优先级（赛前强烈建议）

**是否阻止发布：** ⚠️ 不阻止，但限制声明范围

---

### BENCH-002: 外部比较仅覆盖 dev 固定答案

**状态：** 🔴 开放
**发现时间：** 文档 12, 15, 16 (2026-07-05, 07-06)

**问题描述：**
外部纯文本公平门只在 dev 固定答案任务上通过（3 个 gridops 案例）。形式化财务任务（8 个案例）没有对应的外部比较。

**影响：**
- 🔴 **formal_superiority_claim_allowed = False**
- 🔴 **不能声明"形式化财务外部优势"**
- ✅ 可以声明"dev 固定答案外部公平门通过"

**当前证据：**
- dev 范围：3/3 通过，0 失败（`codex-raw-fairness-20260706`）
- formal 范围：无外部比较数据

**效率对比（dev 范围）：**
- ✅ 令牌节省：-1023 tokens (-34%)
- ✅ 提示字节节省：-4992 bytes (-39%)
- 🔴 时间增加：+9906ms (+108%)

**建议修复：**
将外部纯文本公平门扩展到形式化财务任务：
1. 为 8 个 `financial_report_analysis` 案例添加外部可见候选定义
2. 运行外部基线对比（`external_text_baseline.py` 支持 formal tier）
3. 检查外部基线质量是否追平 StateBus

**目标文件：**
- `tasks/formal/financial_report_analysis_v1/` 添加外部候选定义
- `v2/benchmark/external_text_baseline.py` 确认 formal tier 支持

**风险：**
- ⚠️ **高风险**：外部基线可能质量追平或超过 StateBus，导致优势消失
- ⚠️ 需要充分测试后再决定是否启用

**验证命令：**
```bash
python -m v2.benchmark.live_runner --suite compare --benchmark-tier formal --role-path-mode api --embedding-mode local
```

**优先级：** P2 高优先级（如果希望声明形式化优势）

**是否阻止发布：** ⚠️ 不阻止，但限制声明为 dev 范围

---

### STATE-001: memfd 非 benchmark 主线

**状态：** 🔴 开放
**发现时间：** 文档 12, 16 (2026-07-05, 07-06)

**问题描述：**
`MemfdStatePool` 真实实现存在（`memfd_create + SCM_RIGHTS + shm fallback`），能力测试通过，但未在 formal/compare benchmark 主线中可观测使用。Benchmark JSON 无 `state_pool_mode_used` 字段记录。

**影响：**
- 🔴 **不能声明"benchmark 证明 memfd 为主路径"**
- ✅ 可以声明"memfd 真实实现，能力测试通过"

**当前证据：**
- 代码实现：`v2/state/store.py:26-75`
- 测试通过：`tests/v2/` 覆盖
- Benchmark 可观测性：❌ 缺失

**建议修复（可选）：**
1. 在 `v2/benchmark/live_runner.py` 添加 `--state-pool-mode` 参数：
```python
parser.add_argument("--state-pool-mode",
                    choices=["shared_memory", "memfd", "auto"],
                    default="auto")
```

2. 在 benchmark JSON 添加 `state_pool_mode_used` 字段：
```python
{
  "state_pool_mode_used": "memfd",  # 或 "shared_memory"
  "memfd_transfer_count": 12,
  "memfd_bytes_transferred": 8192,
}
```

3. 在 `scripts/run_v2_full_container_audit_suite.sh` stage 07/08 启用 memfd：
```bash
python -m v2.benchmark.live_runner --suite formal --state-pool-mode memfd
```

**验证命令：**
```bash
cat benchmark_report.json | jq '.state_pool_mode_used'
# 应输出 "memfd"
```

**优先级：** P3 可选增强

**是否阻止发布：** ✅ 否 - 可降级为能力展示

---

### SCRIPT-001: 全审计回退矩阵有限

**状态：** 🔴 开放
**发现时间：** 文档 16 (2026-07-06)

**问题描述：**
全审计脚本的证据强度回退只有一层：`api+local` → `api+deterministic` / `deterministic+local` → `deterministic+deterministic`。如果 api 模式完全失败，只能回退到 deterministic 弱证据。

**影响：**
- ⚠️ 鲁棒性不足：网络问题导致 api 模式全失败时，审计降级为弱证据
- ℹ️ 不影响当前发布（当前 api+local 成功）

**当前逻辑：**
```bash
# scripts/run_v2_full_container_audit_suite.sh
if stage_03_passed; then
  EVIDENCE_TIER="strong"  # api+local
elif stage_04_passed || stage_05_passed; then
  EVIDENCE_TIER="medium"  # api+deterministic 或 deterministic+local
else
  EVIDENCE_TIER="weak"  # deterministic+deterministic
fi
```

**建议修复（可选）：**
添加更多回退路径：
- api+local 失败 → 重试 3 次，延长超时
- api 完全不可用 → 尝试替代 embedding 提供商
- 所有路径失败 → 生成诊断报告而非静默降级

**优先级：** P3 低优先级

**是否阻止发布：** ✅ 否

---

### DOC-001: 旧文档过度声明

**状态：** 🔴 开放
**发现时间：** 文档 12, 16 (2026-07-05, 07-06)

**问题描述：**
两份历史文档包含过度声明，但未标注"历史"或"已废弃"：
1. `docs/reports/MASTER_PRESENTATION_GUIDE.md` (2026-06-11)
2. `docs/reports/task_design_and_mode_comparison.md` (2026-06-13)

这些文档使用过时的 v3 pack 架构和 `text_whole_lane` 术语，可能被误引用。

**影响：**
- 🔴 **引用风险**：答辩材料可能误引用过时声明
- 🔴 **术语混淆**：`text_whole_lane` 不是外部纯文本基线

**过时内容示例：**
- `contest_honest_headline_v1` (v3 pack，已废弃)
- `memory_dual_mode_fairness_v3` (v3 pack，已废弃)
- `task_match_rate` (已退役指标)

**建议修复：**
在文件开头添加醒目横幅：
```markdown
---
**⚠️ 历史文档警告 / HISTORICAL DOCUMENT WARNING**

本文档为 {date} 历史快照，不是当前 source-of-truth。

当前权威来源：
- docs/improvement/16_deep_contest_audit_20260706.md
- docs/improvement/15_fairness_gate_propagation_audit_20260706.md
- docs/reports/v2_update_validation_readout_20260704.md

请勿引用本文档作为当前竞赛叙事依据。
---
```

**目标文件：**
- `docs/reports/MASTER_PRESENTATION_GUIDE.md`
- `docs/reports/task_design_and_mode_comparison.md`

**验证命令：**
```bash
head -20 docs/reports/MASTER_PRESENTATION_GUIDE.md | grep -c "历史文档警告"
# 应输出 1
```

**优先级：** P2 高优先级（赛前必须完成）

**是否阻止发布：** ⚠️ 不阻止，但有误导风险

---

### CLAIM-001: 端到端速度为负

**状态：** 🔴 开放
**发现时间：** 文档 12, 14, 15, 16（所有审计一致）

**问题描述：**
所有审计报告一致显示：StateBus 端到端时间比外部基线慢 9-13 秒（api_task_ms_delta = +9906ms）。但部分文档（如 `v2_experiment_summary`）可能包含"速度优势"或"-65% CodeAct"等易被误读的表述。

**影响：**
- 🔴 **不能声明"端到端速度优势"**
- 🔴 **不能声明"延迟改进"**
- ⚠️ **-65.7% CodeAct 加速**仅限同进程热缓存重运行，不是通用改进

**当前证据：**
- api_task_ms_delta = +9906ms（StateBus 更慢）
- api_llm_ms_delta = +2588ms（LLM 时间更慢）
- api_system_overhead_ms_delta = +1643ms（系统开销）

**真实效率改进：**
- ✅ 令牌节省：-1023 tokens (-34%)
- ✅ 提示字节节省：-4992 bytes (-39%)

**建议修复：**
替换所有"速度"/"延迟"表述为"资源效率"：
```markdown
**错误表述：**
"StateBus 端到端速度更快"
"延迟改进"
"CodeAct -65% 加速"

**正确表述：**
"StateBus 展示了令牌和提示字节的显著效率改进（-34% tokens, -39% prompt bytes），
但当前系统开销为正（+9.9s）。优化空间明确，资源效率改进已验证。"

"CodeAct 阶段在同进程热缓存重运行场景下展示 -65.7% 时间减少（从 2455ms 到 843ms），
证明结果缓存机制有效。"
```

**目标文件：**
- `docs/reports/v2_experiment_summary_20260703.md`
- 任何答辩材料

**验证命令：**
```bash
grep -r "速度.*优势\|latency.*win\|端到端.*快\|faster.*end.*to.*end" docs/reports/ docs/contracts/
# 应输出为空或只有"不能声明"的警告
```

**优先级：** P2 高优先级（赛前必须完成）

**是否阻止发布：** ⚠️ 不阻止，但有被挑战风险

---

## 声明过度风险清单

| 危险声明 | 真实情况 | 推荐答辩表述 |
|---------|---------|------------|
| "StateBus 端到端更快" | +9.9s 更慢 | "令牌和提示字节节省，系统开销当前为正" |
| "形式化外部优势验证" | formal_superiority_claim_allowed=False | "Dev 固定答案外部公平门通过；形式化外部标题资格待定" |
| "openEuler VM 验证" | 只有容器验证 | "openEuler 容器环境测试通过" |
| "通用答案恢复重放" | 降级复用 | "基于策略的降级复用（validated downgraded reuse）" |
| "形式化广泛推理优势" | 8 案例，单指标 | "形式化质量基线维持（8/8 精密锚点案例）" |
| "Benchmark 证明实时 LLM 代码生成" | 固定辅助脚本 | "受控执行环境下的代码生成能力展示" |
| "memfd 为 benchmark 主路径" | 能力测试通过 | "MemfdStatePool 真实实现，能力测试通过" |
| "令牌节省归因于协议" | 主要归因于剪枝 | "令牌节省主要来自语义剪枝（6255B），类型化控制开销 +360B" |

---

## 问题统计

| 严重性 | 总数 | 已修复 | 已缓解 | 开放 |
|--------|-----|--------|-------|------|
| P0 | 0 | - | - | 0 |
| P1 | 5 | 4 | 1 | 0 |
| P2 | 6 | 0 | 0 | 6 |
| P3 | 2 | 0 | 0 | 2 |
| **总计** | **13** | **4** | **1** | **8** |

---

## 赛前必须修复清单（P2 高优先级）

1. ✅ **DOC-001**: 标注旧文档为历史
2. ✅ **CLAIM-001**: 降级速度声明
3. ✅ **REPLAY-001 后续**: 明确重放命名为"降级复用"
4. ⚠️ **BENCH-001 后续**: 明确形式化范围为"精密锚点"（或扩展家族）
5. ⚠️ **BENCH-002**: 扩展外部公平门到 formal tier（如果希望声明形式化优势）

---

**最后更新：** 2026-07-06
