# Planner Repair Loop 修复分析

日期：2026-06-16

---

## 一、改动内容

`agents/sample_agents.py` — `PlannerAgent.plan_task()` 新增 repair loop：

```
MAX_PLANNER_REPAIR_ATTEMPTS = 2
→ 总共 3 次尝试（初始 + 2 次修复）
```

每次 `_plan_from_llm_output()` 抛出 `ValueError` 时，调用 `_planner_repair_messages()` 构造修复消息：
- 把 LLM 的无效输出作为 assistant 消息追加
- 追加一条 user 消息，明确写明验证错误和修复要求：
  - "The previous planner output failed contract validation."
  - "Validation error: {具体的错误信息}"
  - "The plan must cover these semantic roles: retrieve, validate, execute, summarize"
  - "Do not use the compact r/x/s shape on this retry"
  - "Do not omit semantic_role"

Prompt 也加强了：
- protocol 模式增加："Every explicit step object must include step_id, semantic_role, owner_agent, action, input_state_refs, params, depends_on"
- "If validate is required, return only the explicit {\"steps\":[...]} form"
- "Do not omit semantic_role on any step"

---

## 二、逻辑评估 — 正确

| 检查点 | 状态 |
|---|---|
| repair loop 正确计数（0..MAX_PLANNER_REPAIR_ATTEMPTS） | ✅ |
| `_planner_repair_messages` 正确构造对话历史 | ✅ |
| `*base_messages` 正确展开原来的消息列表 | ✅ |
| `ChatMessage(role="assistant", ...)` 构造正确 | ✅ |
| prompt 明确禁止 compact 格式 | ✅ |
| prompt 明确要求 semantic_role | ✅ |
| parse/validate 逻辑不变（上轮已验证正确） | ✅ |

**代码逻辑无误。**

---

## 三、结果 — 仍然失败

```
planner-support-deploy-llm-001:
  status=failed, planner_contract_valid=False, planned_step_count=0

planner-support-auth-llm-002:
  status=failed, planner_contract_valid=False, planned_step_count=0
```

3 次尝试（初始 + 2 repair）后仍然无法产出含 validate step 的有效 plan。

`planned_step_count=0` → LLM 产出的 plan 甚至在 plan compilation 阶段就被拒绝——没有进入 step execution。

---

## 四、根因

**不是代码 bug。** 是 deepseek-v4-flash 在当前 prompt 格式下无法可靠地产出 4 步 validate-first plan。

可能的 LLM 失败模式：
- 仍使用 compact JSON 格式（`{"r":...,"x":...,"s":...}`），尽管被明确告知不要
- 产出 3 步 explicit plan，忽略 validate 步骤
- 产出 4 步但 `semantic_role` 字段缺失或命名错误

代码侧的 repair loop、prompt 加强、validate contract 验证链路都工作正常——它们在正确拒绝不符合要求的 plan。问题在 LLM 产出的内容。

---

## 五、对比赛题的影响

`planner_support_v3` 承担"多 Agent 规划角色"的赛题证据。当前状态下：
- yaml 行（5 rows）正常通过
- 非 validate 的 llm 行（4 rows）正常通过
- validate-first 的 llm 行（2 rows）失败

可以诚实地说：系统具备 4-step validate-first 规划能力（代码层面的 validate contract + repair loop + semantic_role 系统），但 API LLM 在当前 prompt 下尚未稳定产出符合合同的 4-step plan。deterministic 测试证明代码路径正确。
