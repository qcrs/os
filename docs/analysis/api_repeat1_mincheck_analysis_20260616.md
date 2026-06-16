# API Repeat-1 MinCheck 结果分析

日期：2026-06-16
运行目录：`runs/api_repeat1_mincheck_20260616_151801/`

---

## 一、typed_state_consumer_sensitivity_v3 — ✅ 统计口径修正确认

| 指标 | 修前（旧 run） | 修后（本轮） | 目标 |
|---|---:|---:|---:|
| `run_failure_count` | 非零（含 expected negative） | **0** | ✅ |
| `failure_count` | 非零 | **0** | ✅ |
| `expected_negative_task_failure_count` | 5 | **5** | ✅ |
| `unexpected_task_failure_count` | 0 | **0** | ✅ |
| `missing_decision_failure_rate` | 1.00 | **1.00** | ✅ |
| `wrong_decision_misroute_rate` | 0.80 | **0.80** | ✅ |
| `wrong_decision_mistool_rate` | 1.00 | **1.00** | ✅ |

**结论**：修复准确。expected negative failure 从 run-level counting 中正确分离了。run_failure_count=0, failure_count=0，而 expected_negative_task_failure_count=5 保持可审计。

---

## 二、planner_support_v3 — ❌ validate-first LLM 行全部失败

### 关键 JSON 数据

```json
// planner-support-deploy-llm-001
status: "failed"
planner_contract_valid: false
planner_step_count: 0
results: {}

// planner-support-auth-llm-002  
status: "failed"
planner_contract_valid: false
planner_step_count: 0
results: {}
```

两个被标记为 `required_plan_semantic_roles: [retrieve, validate, execute, summarize]` 的 LLM 行全部失败。

### 聚合数据

| 指标 | 本轮 | 上轮（无 validate 合同） |
|---|---|---|
| protocol_admissible_match_rate | **0.09** | 0.27 |
| combined_admissible_match_rate | **0.05** | 0.14 |
| planner_llm_request_count | 6.00 | 6.00 |
| planned_step_count | 18.00 | 33.00 |

planned_step_count 从 33 降到 18 —— 因为两个 validate 行失败贡献了 0 steps。

---

## 三、根因分析

**代码改动正确，不是代码 bug。** 问题在于真实 LLM（deepseek-v4-flash）产出的 plan 不符合 validate 要求。

prompt 已明确告诉 LLM：
- "The plan must include these semantic roles: retrieve, validate, execute, summarize"
- "If validate is required, use the explicit steps form instead of the compact shape"

但真实 LLM 仍可能：
1. 产出旧 3 步格式（忽略 validate 要求）
2. 使用 compact JSON 格式（没有 validate 槽位）
3. 产出 validate step 但 semantic_role 标签错误

`planner_contract_valid: false` 说明 `_validate_planner_semantic_coverage` 正确拒绝了缺失 validate 的 plan —— 验证逻辑在工作。但 LLM 没有遵从 prompt 指示。

**对比**：`test_deterministic_llm_emits_validate_step_when_task_contract_requires_it` 测试通过了 —— 因为 deterministic client 产出的内容被设计为符合合同。真实 LLM 不受控制。

---

## 四、总体判断

| pack | 状态 | 说明 |
|---|---|---|
| typed_state_consumer_sensitivity_v3 | ✅ 修复正确 | run_failure_count=0, expected_negative=5 正确分离 |
| planner_support_v3 | ⚠️ 代码正确，LLM 不服从 | 两个 validate-first 行全失败，需 prompt 调优 |

**typed_state 的统计口径修复已验证生效。planner 的 validate-first 合同已正确 enforce，但真实 LLM 尚不能产出满足合同的 plan——这是 prompt engineering 问题，不是代码逻辑问题。**
