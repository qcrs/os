# API Repeat-1 全量 Smoke 结果

日期：2026-06-16 17:03
运行目录：`runs/api_repeat1_smoke_20260616_165207/`
6 pack，real LLM + real embedding，repeat=1

---

## 总览

| pack | 核心指标 | 状态 |
|---|---|---|
| contest_dual_mode_controlled_v3 | exact=0.05, adm=0.55, control **-15.6%** | withheld (repeat=1) |
| planner_support_v3 | one_shot=**1.00**, repair=**0**, adm=0.27 | ✅ clean |
| memory_policy_controlled_v3 | exact=**1.00**, replay gate **pass** | ✅ clean |
| typed_state_consumer_sensitivity_v3 | missing_fail=1.00, wrong_tool=1.00, expected_neg=5, unexpected=0 | ✅ clean |
| typed_state_mechanism_v3 | exact=0.00, adm=0.25, control **+160** | ✅ clean |
| memory_dual_mode_fairness_v3 | **object_parity=pass**, text_restore=pass | withheld (repeat=1) |

---

## 逐 pack

### contest_dual_mode_controlled_v3

| 指标 | text | protocol | delta |
|---|---:|---:|---:|
| control_bytes | 7728 | 6522 | **-1206 (-15.6%)** |
| task_ms | 5078 | 5095 | +17 (+0.3%) |
| exact_match | — | — | 0.05 |
| admissible | — | — | 0.55 |

通信节省稳定（15.6%），但 task_ms 持平——去 hint 后 retrieval 质量弱，50% task abstain。Planner 未调用（plan_source_default: yaml）。

### planner_support_v3 — 本轮亮点

| 指标 | 值 |
|---|---|
| planner_llm_request_count | 6.00 (6 个 llm 行全调用) |
| planned_step_count | 38.00 (含 4-step validate 行) |
| **planner one-shot valid rate** | **1.00** |
| **planner repair attempts** | **0** |
| admissible | 0.27 |

**所有 6 个 LLM 行全部 one-shot 通过，无需 repair。** validate-first 行产出正确 4-step plan。admissible 0.27 是 retrieval 瓶颈，不是 planner 问题。

### memory_policy_controlled_v3

| policy | tokens | skipped | reuse_gain | task_ms |
|---|---:|---:|---:|---:|
| memory_off | 408 | 0 | 0 | 3332 |
| exact_replay | 396 | 2 | 0.67 | **1756** |

replay gate pass，exact_match 1.00。最稳定的一条线。

### typed_state_consumer_sensitivity_v3

missing_decision_failure=1.00, wrong_decision_mistool=1.00, expected_neg=5, unexpected=0。统计口径干净。

### typed_state_mechanism_v3

exact=0.00, adm=0.25。去 hint 后 typed state 对比 natural handoff 在正确率上没有提升——两种 handoff 对象的正确率天花板都被 retrieval 质量限制了。

### memory_dual_mode_fairness_v3

**object_parity_gate: pass。** 这个之前被 withheld（object_parity_failed + hidden_field_leak）的包现在干净了。只 withheld for stability_gate（repeat=1 < 10）。

---

## 一句话

planner 修复完全生效（one-shot 1.00, repair 0），memory dual_mode fairness gate 通过，communication 优势稳定。唯一系统性问题：去 hint 后 retrieval 质量弱（exact 0.00-0.05），是所有 correctness 指标的瓶颈。
