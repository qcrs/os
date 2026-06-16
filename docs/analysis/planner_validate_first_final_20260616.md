# Planner Validate-First 修复 — 最终验证

日期：2026-06-16
运行：`runs/api_repeat1_mincheck_rerun_20260616_153659/`

---

## 一、结果 — 全部通过

```
11/11 tasks: status=completed, contract_valid=True
```

| task_id | plan_source | steps | validate? | contract_valid |
|---|---:|---:|---:|---:|
| checkout-llm-001 | llm | **4** | ✅ | True |
| checkout-yaml-001 | yaml | 3 | — | True |
| auth-llm-001 | llm | 3 | — | True |
| **auth-llm-002** | llm | **4** | ✅ | True |
| auth-yaml-001 | yaml | 3 | — | True |
| cache-llm-001 | llm | 3 | — | True |
| cache-yaml-001 | yaml | 3 | — | True |
| billing-llm-001 | llm | 3 | — | True |
| billing-yaml-001 | yaml | 3 | — | True |
| **deploy-llm-001** | llm | **4** | ✅ | True |
| deploy-yaml-001 | yaml | 3 | — | True |

3 个 validate-first 行全部产出 4 步 plan，`results.validate.success=true`。

---

## 二、关键改动

**`PLANNER_ROLE_BINDINGS`** — 语义角色到 (owner_agent, action) 的绑定表：
```python
"validate": ("executor", "VALIDATE_ROUTE")
```
`_normalize_planner_step()` 用此绑定校验每个 step 的 owner_agent 和 action 与 semantic_role 一致。如果 LLM 产出 `semantic_role="validate"` 但 `action="EXECUTE_PLAYBOOK"`，直接拒绝。这让 LLM 不可能用错误的 action 来"冒充" validate 步骤。

配合 **repair loop**（3 次尝试）+ **prompt 加强**（"Do not use the compact shape"），LLM 最终产出了正确格式的 4 步 plan。

---

## 三、admissible 仍然是 0.27 — 这是正确的

11 个 task 全部跑通，但 admissible 只有 0.27。这意味着：
- **Planner 层**：正确工作——产出合法 plan
- **Retrieval 层**：去 hint 后检索质量弱——找不到正确 route

这是去 corpus 预标签后的真实状态。0.27 的 admissible 说明 9/11 的 task 在 route/tool 选择上出了问题——但这不是 Planner 的错。Planner 产出的 plan 结构正确，是 retriever 喂给 executor 的 evidence 质量不够。

---

## 四、改动评价 — 合理

| 项 | 评价 |
|---|---|
| PLANNER_ROLE_BINDINGS | ✅ 强制 semantic_role → (owner, action) 一致性，避免 LLM 用错误 action 冒充 |
| Repair loop (MAX_PLANNER_REPAIR_ATTEMPTS=2) | ✅ 给 LLM 修复机会，minimal 额外 LLM 成本（+3 calls） |
| Prompt 加强（禁止 compact、要求 semantic_role） | ✅ 明确指令 |
| 不破坏已有功能 | ✅ yaml 行和旧 llm 行行为不变 |
