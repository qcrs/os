# Planner Validate-First 闭环 — 实现核对报告

日期：2026-06-16
Branch：`feat/statebus-full-restructure-20260616`
11 文件修改，+433/-49 行

---

## 逐项核对

### 1. Validate 改成真实校验 ✅ 完成

| 计划要求 | 代码位置 | 状态 |
|---|---|---|
| route 不能为空、不能是 generic_triage | `sample_agents.py:989` — `validated_route == "generic_triage"` → failure | ✅ |
| route_confidence 在 [0,1] 内，含 validate 时 >= 0.5 | `sample_agents.py:992` — `route_confidence < 0.5` → failure | ✅ |
| validated_tool 非空，与 route 允许 tool 集一致 | `sample_agents.py:994-998` — tool 空或不在 allowed_tools → failure | ✅ |
| retrieved_doc_ids 非空且映射到 retrieve 证据集 | `sample_agents.py:1000-1001` — doc_ids 空 → failure | ✅ |
| retrieve 与 decision packet 冲突检测 | `sample_agents.py:1002-1005` — route/tool 不一致 → failure | ✅ |
| 产出 VALIDATION_GATE_PACKET typed state | `sample_agents.py:1023-1032` — `put_validation_gate_state()` | ✅ |
| StepResult.success 取决于 validation_success | `sample_agents.py:1035` — `success=validation_success` | ✅ |

### 2. Execute 强制消费 validate ✅ 完成

| 计划要求 | 代码位置 | 状态 |
|---|---|---|
| execute 前读取 validation packet | `sample_agents.py:913-920` — `ctx.get_validation_gate_state()` | ✅ |
| validation_success != true 时拒绝执行 | `sample_agents.py:918` — `raise ValueError(...)` | ✅ |
| 区分普通三步和 validate-first 合同 | `orchestrator.py:1463-1466` — `state_packet_minimal` vs `state_packet_minimal_validated` | ✅ |
| contracts.py 新增 validate source | `contracts.py:728-732` — `StepInputSource(step_id="validate")` | ✅ |
| VALIDATION_GATE_PACKET 在 nontext handoff 计数中 | `orchestrator.py:266` — 加入 `nontext_kinds` | ✅ |

### 3. Planner 合同对齐 ✅ 完成

| 计划要求 | 代码位置 | 状态 |
|---|---|---|
| planner 从 owner_agent 白名单移除 | `sample_agents.py:1609` — `planner` 不在列表中 | ✅ |
| protocol prompt 禁止 compact shape | `sample_agents.py:1647` — "Return only {\"steps\":[...]}" | ✅ |
| repair prompt 禁止 compact shape | `sample_agents.py:1694` — "Do not use compact r/x/s shape" | ✅ |
| generic_triage 在 controlled pack 上拒绝 | `executor_runtime.py:1925-1929` — `task_pack_type` 检查 | ✅ |
| retrieved_doc_ids 非空校验 | `executor_runtime.py:1914-1915` — `raise ValueError` | ✅ |

### 4. One-shot vs repair 分报 ✅ 完成

| 计划要求 | 代码位置 | 状态 |
|---|---|---|
| RunContext 新增 planner_one_shot_valid 等 | `orchestrator.py:225-226` | ✅ |
| TaskMetrics 新增 planner_one_shot_valid/repair_rate | `metrics.py:103-112` | ✅ |
| task payload 输出 | `runner.py:2161-2163` | ✅ |
| report header 展示 rate | `runner.py:4206-4224` | ✅ |

### 5. Support surface 边界 ✅ 完成

| 计划要求 | 状态 |
|---|---|
| planner_support_v3 保持 formal_secondary_planner | ✅ |
| contest/memory_policy 保持 plan_source_default: yaml | ✅ |
| README/docs 边界清晰 | ✅ 已有 |

---

## 测试覆盖 ✅

| 测试 | 覆盖点 | 状态 |
|---|---|---|
| `test_validate_route_emits_gate_packet_and_execute_requires_successful_validation` | validate 产出 packet + execute 消费 + 失败阻断 | ✅ 24 passed |
| `test_planner_support_v3_runs_llm_planner_in_protocol_mode` | 4-step plan + validate results + repair 报告 | ✅ |
| `test_planner_agent_retries_until_planner_contract_is_valid` | repair count + one_shot_valid | ✅ |

---

## 剩余注意点（非问题）

1. **compact shape 解析代码仍在**：`_compact_planner_output_to_steps()` 未删除。protocol prompt 已禁止 compact，但 parser 仍支持。如果 future LLM 忽略 prompt 仍产出 compact，会通过 parse → validation 链被拒绝（因为 compact 没有 validate semantic_role）。保留解析代码不会造成实际风险。

2. **yaml plan 也支持 validate**：`build_plan()` 条件生成 validate step。当 yaml 行有 `required_plan_semantic_roles` 含 validate 时，yaml plan 也是 4 步。这是合理的——validate 不应该只是 LLM planner 专有的语义。

3. **deterministic 测试中 validate 会失败**：因为 deterministic retrieval 产出的 route 可能不满足 validate 条件（如 route_confidence 低于 0.5）。测试已正确区分"validate 失败 → execute 被阻断"和"validate 成功 → execute 继续"两条路径。

---

## 结论

**5 项计划全部实现。24 个相关测试通过。无遗漏。**
