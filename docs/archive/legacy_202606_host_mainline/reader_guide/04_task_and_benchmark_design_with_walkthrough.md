# 任务与 Benchmark 设计 + 真实 Walkthrough

本文档回答：

1. 任务是怎么设计的。
2. 为什么不是一堆散题。
3. 这些任务是在验证系统能力，还是只是在做局部优化测试。
4. 一个真实任务到底如何完整流过系统。

---

## 1. 任务设计总原则

### 1.1 为什么要做连续任务链

StateBus 要验证的三件事——低开销通信、非文本状态传递、共享记忆复用——都不是单个独立问答任务能检验的：

- **通信效率**需要通过"同一任务双模式对照"来证明：固定 task object、语料范围、summary/scoring contract 等主合同，再比较 `text` vs `protocol` 的 mode surface；这不应被误读成“所有角色内部实现完全不变”
- **状态传递**需要通过"非文本状态的生产→传递→消费"链路来证明：Retriever 产出 typed state → Executor 消费
- **记忆复用**需要通过"前后任务关联"来证明：第二轮任务遇到与第一轮相似的情况时，能否命中记忆并跳过重复步骤

因此，任务设计不是散题集合，而是**有结构的任务 pack（任务包）**：

- pack 内有任务族（family）
- 族内有独立任务（S1）和关联任务（S2）
- 同一个 task object（任务对象）在 text/protocol 两种模式下运行

### 1.2 这些任务不是普通问答集

传统 benchmark 常见"给定一个问题，输出一个回答"。StateBus 的任务是**系统诊断类任务**：给定一个运维场景（如"auth_rotation 服务验证失败"），Agent 需要经过多步推理（检索→校验→执行→总结）来完成。

每个 task 不是简单选答案，而是需要：
1. 从语料库（corpus）中检索相关文档
2. 从多候选 route（路由）中选择正确的诊断方向
3. 从多候选 tool（工具）中选择正确的排障工具
4. 面对 distractor（干扰项）和 ambiguous（歧义情况）时做正确的拒识或替代选择

---

## 2. task / family / chain / case 的关系

| 名称 | 含义 | 在代码/配置里怎么体现 | 为什么要这么分 |
|---|---|---|---|
| **task**（任务） | 单个完整任务定义，包含 query、expected route/tool、case contract | `SampleTask` dataclass，在 YAML 或 Python builder 中定义 | 最小评测单元 |
| **family**（任务族） | 同一领域的一组 task，共享相同的 corpus 和 domain（领域）知识 | `contest_family_spec.py` 中的 5 个族：`auth_rotation`、`billing_queue_backlog`、`checkout_regression`、`deployment_config_drift`、`inventory_rollout` | 同一族内的任务可以共享记忆和经验 |
| **chain**（任务链） | 同一 family 内有先后依赖关系的任务序列 | `reusable` complexity bucket（复杂度桶），携带 `prior_case_ids` 和 `prior_rejection` 合同 | 验证跨任务记忆复用：S1（前序）的执行经验能否被 S2（后继）复用 |
| **case**（用例） | 每个 task 的评估合同：`case_id`、`case_type`、`expected_family`、`primary_expected_route`、`primary_expected_tool`、`acceptable_routes`、`acceptable_tools`、`disallowed_families`、`abstention_allowed` 等 | YAML 中的 `eval_scope` 和 `expected_*` 字段 | 定义 scorer（评分器）如何判断正确性 |

---

## 3. 一个 pack 为什么不是散题

以历史 frozen formal headline / carrier-isolation object `contest_honest_headline_v1` 为例：

- **5 个 family**，每个 family 下 4 个 complexity bucket：`simple`（简单）、`distractor`（干扰项）、`ambiguous`（歧义）、`reusable`（可复用）
- **S1（独立任务）**：30 个 task，各自独立完成，不带 prior dependency
- **S2（关联任务）**：10 个 task，携带 prior dependency / prior rejection 合同，预期复用前序 S1 任务的经验
- 同一 task object 在 `text_whole_lane` 和 `state_packet_minimal` 两种模式下配对运行

这形成了一个清晰的成组对照矩阵：相同 family、相同 case contract、相同 task object，在两条 lane 下成对运行，再按 repeat 聚合。

注意：

- 这一节是在解释 task pack 如何构造，以及为什么它不是散题。
- 它使用 `contest_honest_headline_v1` 作为历史 frozen headline 例子，是因为这个对象更适合展示完整 family/chain/case 设计。
- 它**不是**当前 active communication headline 的 authoritative source-of-truth。当前 active communication headline 是 `superiority_comm_v1`。

每个 complexity bucket 的作用：

| bucket | 作用 | 例子 |
|---|---|---|
| `simple` | 基准场景：route 直接匹配，tool 唯一确定 | `auth_rotation` 族中 `auth_session_drift` route 匹配 `tool.auth_session_repair` |
| `distractor` | 测试抗干扰：query 中有相似但不对的 route 线索 | `checkout_regression` 中同时出现 `db_pool_saturation` 和 `cache_invalidation` 的线索，需正确选择 |
| `ambiguous` | 测试边界处理：某些 case 没有确切匹配时，是否合理拒识 | 无法匹配任何已知 route 时走 abstention（拒识）路径 |
| `reusable` | 测试记忆复用：携带 `prior_case_ids` 依赖，预期命中 S1 记忆后跳过执行步骤 | S2 任务 reuse S1 的 route/tool/evidence，触发 skip_execute |

---

## 4. variable axes（变量轴）字典

| 变量 | 控制什么 | 改它会影响哪条结论 |
|---|---|---|
| `mode`（模式） | Agent 间通信格式：`text`（自然语言）vs `protocol`（结构化协议） | communication headline（通信开销对比）、state transfer（状态传递对比） |
| `transfer_strategy`（传递策略） | 状态传递方式：`text_whole_lane`（全通道文本）、`text_strict_pure_lane`（严格纯文本）、`state_packet_minimal`（最小状态包）、`natural_handoff_text`（自然交接文本）等 | typed-state 机制证据、handoff wire/payload bytes |
| `handoff_profile`（交接配置） | 交接时的信息密度：full evidence 内联 vs 精简 typed packet | communication 开销、executor 消费方式 |
| `runtime_reuse_contract`（运行时复用合同） | 记忆复用策略：`reuse_disabled` / `assist_allowed` / `validated_replay` / `exact_replay` | memory replay effect、skipped_step_count、reuse_gain |
| `plan_source`（计划来源） | Plan 的来源：`yaml`（固定脚本化 plan）vs `llm`（LLM 自主规划） | planner support 证据、系统开放规划能力 |
| `benchmark_lane`（评测通道） | 结论归属通道：`communication`、`state_transfer`、`memory`、`integrity` | claim lane 归因：每个指标该归到哪条赛题轴 |
| `variable_axes`（变量轴） | 该 pack 的 single-variable contract（单变量合同）标识：只改变哪个变量 | 证明 pack 确实是单变量对照，不是多变量混杂 |

---

## 5. 评分与正确性判定

### 5.1 指标定义

| 指标 | 含义 | 正式 headline 是否使用 |
|---|---|---|
| `route_exact_rate`（路由精确率） | Executor 选择的 route（诊断方向）与 expected route 完全一致的比例 | ✅ 是 |
| `tool_exact_rate`（工具精确率） | Executor 选择的 tool（排障工具）与 expected tool 完全一致的比例 | ✅ 是 |
| `exact_match_rate`（完全匹配率） | route 和 tool 同时完全匹配的比例 | ✅ 是 |
| `admissible_match_rate`（可接受匹配率） | route 和 tool 在 acceptable set（可接受集合）内的比例 | ✅ 是 |
| `abstention_rate`（拒识率） | Executor 正确识别为"无法确定"并走 abstention 路径的比例 | ✅ 是 |
| `wrong_family_rate`（错误族选择率） | 选中 disallowed family（禁止族）中的 route 的比例。**这必须为 0** | ✅ 是 |
| `task_match_rate` | 旧版宽松指标（只比较 route 族）。v3 已废弃，不再作为正式 headline 指标 | ❌ 否 |

### 5.2 scorer（评分器）在判断什么

当前 scorer 的核心逻辑是 case-level contract（用例级合同）：

- 每个 task 显式声明了可接受的 route 集合（`acceptable_routes`）和 tool 集合（`acceptable_tools`）
- 也声明了禁止的 family（`disallowed_families`）
- 对于 ambiguous case（歧义用例），scorer 允许 abstention（拒识）作为正确行为
- `route_exact_rate` 检查 primary route 是否匹配
- `admissible_match_rate` 检查结果是否在 acceptable set 内

### 5.3 negative control（负控）为什么重要

`typed_state_consumer_sensitivity_v3` 是最典型的 negative control（负控）设计：

- **Baseline（基线）**：正常的 `DENSE_EVIDENCE + EXECUTOR_DECISION_PACKET` → 预期成功
- **Negative 1：缺失 decision packet** → 预期 `failure`（`missing_decision_failure_rate = 1.00`）
- **Negative 2：错误 decision packet** → 预期 `tool misfire`（选错工具，`wrong_decision_mistool_rate = 1.00`）
- **Pack 范围边界**：当前 authoritative refresh 是 `40` 个 protocol tasks，跨 `5` 个 family，同时覆盖 full-rich helper visibility rows 和 minimal destructive-control rows；它不是一个只含 `8` 个 task 的窄包

只有正控和负控都按预期行为触发，才能证明 typed-state 是被真实消费的，不是"代码里有这个字段但 Executor 根本不看"。

---

## 6. 一个真实任务的完整 walkthrough

以历史 frozen headline `contest_honest_headline_v1` 中 `checkout_regression` 族的 `reusable`（S2）任务为例。

### 6.1 task 长什么样

```yaml
task_id: checkout-regression-reusable-1
query: "checkout regression after payment gateway deploy"
family: checkout_regression
complexity_bucket: reusable
case_type: exact_single_solution
primary_expected_route: db_pool_saturation
primary_expected_tool: tool.db_pool_triage
acceptable_routes: [db_pool_saturation]
acceptable_tools: [tool.db_pool_triage]
disallowed_families: [auth_rotation, inventory_rollout]
prior_case_ids: [checkout-regression-simple-1]  # 依赖前序 S1 任务
prior_rejections: [cache_invalidation]            # 前序已拒绝的 route
```

### 6.2 走 protocol 路径（state_packet_minimal）

**Step 1 — Planner 接收什么、输出什么**

Planner 接收：`query`、`capability_table`（能力表）、可选的 `MemoryHit`。输出 `Plan`：
```json
{
  "steps": [
    {"step_id": "s1", "semantic_role": "retrieve", "owner_agent": "retriever", "action": "RETRIEVE_EVIDENCE", ...},
    {"step_id": "s2", "semantic_role": "validate", "owner_agent": "executor", "action": "VALIDATE_ROUTE", ...},
    {"step_id": "s3", "semantic_role": "execute", "owner_agent": "executor", "action": "EXECUTE_PLAYBOOK", ...},
    {"step_id": "s4", "semantic_role": "summarize", "owner_agent": "summarizer", "action": "SUMMARIZE_AND_COMMIT", ...}
  ]
}
```

**Step 2 — Retriever 接收什么、输出什么**

Retriever 接收：
- `query`: "checkout regression after payment gateway deploy"
- `prior_case_ids`: ["checkout-regression-simple-1"] → 查询 MemoryStore

Retriever 执行：
1. corpus retrieval（语料检索）：检索到 `doc-42`（关于 `db_pool_saturation`）、`doc-101`（关于 `cache_invalidation`，前序已拒绝）
2. memory assist lookup：命中前序 S1 的记忆，route 为 `db_pool_saturation`，tool 为 `tool.db_pool_triage`
3. 构建 `FEATURE_BUNDLE`：提取 route=`db_pool_saturation`、signals=[`connection_timeout`, `pool_exhaustion`]、query_terms
4. 构建 `TOOL_CANDIDATE_SET`：让 `tool.db_pool_triage` 排在首位
5. 调用 retriever-role LLM contract 做 semantic selection，得到当前 route/tool 语义决策
6. 产出 `DENSE_EVIDENCE`、`REPLAY_ELIGIBILITY_BUNDLE`、`EXECUTOR_DECISION_PACKET`

**Step 3 — protocol 路径怎么传（handoff）**

在 protocol 路径（`state_packet_minimal`）下，Retriever 产出不内联在文本消息中。它们通过 `StateRef` 传递给 Executor：

```python
# 控制面消息中只有 StateRef 指针
PlanStep{
  step_id: "s3",
  semantic_role: "execute",
  input_state_refs: [
    "state://dense-evidence/doc-42",      # 50-80 bytes 指针
    "state://decision-packet/checkout-1", # 指针
    "state://validation-gate/checkout-1"  # 指针
  ],
  params: {}  # 不再内联大段 evidence 文本
}
```

Executor 收到后，通过 `StatePool.read(state_ref)` 本地零拷贝读取实际数据。

**Step 4 — text 路径怎么传（对比）**

在 text 路径（`text_whole_lane`）下，Retriever 把 route/tool/evidence 内联在文本中：
```text
"Query: checkout regression after payment gateway deploy
 Retrieved docs: doc-42
 Visible candidates: db_pool_saturation::tool.db_pool_triage
 Visible evidence: [doc-42 的完整内容 ~2800 bytes]"
```
Executor 需要从这段自然语言文本中解析出 route 和 tool 信息。

**Step 5 — Executor 怎么消费（两种路径的差异）**

- protocol 路径：Executor 直接读取 `EXECUTOR_DECISION_PACKET`（route=`db_pool_saturation`、tool=`tool.db_pool_triage`、signals=[...]），优先消费结构化 decision；当前实现里它仍会再走一层 executor-role LLM semantic selection，然后进入真实工具执行
- text 路径：Executor 从文本中提取 `db_pool_saturation::tool.db_pool_triage`，再做匹配；当前实现里它同样会走 executor-role LLM semantic selection，但输入表面仍是文本恢复出来的 route/tool 信息

**Step 6 — replay gate（回放门控）检查**

由于这是 `reusable` 任务，在 retrieve 和 execute 之间，Orchestrator 会检查 replay gate：

1. 从 MemoryStore 查询前序 S1 的记忆 → 命中（route=`db_pool_saturation`、tool=`tool.db_pool_triage`）
2. 新鲜检索的 route 也是 `db_pool_saturation` → **fresh route == stored route** ✅
3. fresh route 的 provenance 满足 `required_prior_routes` → ✅
4. replay-compatible `TOOL_ARTIFACT` 存在 → ✅
5. **replay gate: pass → skip_execute = true**

于是 Executor 的 execute step 被跳过，直接进入 summarize。

**Step 7 — Summarizer 怎么总结**

Summarizer 收到：
- 检索结果：`DENSE_EVIDENCE`（通过 adapter 整理的摘要）
- 执行产物：已经有了（因为 skip_execute，使用前序 S1 的 artifact）
- 记忆命中：前序 S1 的 memory

Summarizer 产出：
- `summary`: "Checkout regression caused by db_pool_saturation. Applied tool.db_pool_triage..."
- `MemoryCommit`: 包含 summary、evidence_refs、replay episode 信息 → 写入 MemoryStore

**Step 8 — scorer 最后怎么判**

scorer 读取 task 的 case contract：
- `primary_expected_route`: `db_pool_saturation` → Executor 选的是 `db_pool_saturation` → `route_exact = true`
- `primary_expected_tool`: `tool.db_pool_triage` → Executor 选的是 `tool.db_pool_triage` → `tool_exact = true`
- `exact_match = true`
- `wrong_family = false`
- 由于 skip_execute 发生，`skipped_step_count += 1`，`reuse_gain += 0.25`

---

## 7. 这个任务在证明什么，不在证明什么

### 证明什么

1. **通信载体差异**：protocol 路径下，从 Retriever 到 Executor 的 handoff 不再依赖把主要执行语义内联成大段自然语言，而是通过结构化的 `EXECUTOR_DECISION_PACKET` 和相关 StateRef 传递。这是 communication compactness 变化的核心来源。
2. **typed-state 被真实消费**：Executor 在 protocol 路径下优先消费的是 `EXECUTOR_DECISION_PACKET`（结构化决策），而不是只靠自然语言恢复 route/tool。缺失/错误 packet 会导致 failure/tool misfire（由 `consumer_sensitivity_v3` 负控证明）。
3. **replay effect 真实发生**：前序 S1 的记忆被命中后，S2 任务的 execute step 被真实跳过（不是只标记"命中"）。

### 不在证明什么

1. **不等于 latency superiority closure**：虽然单个任务快了，但整体 latency superiority 尚未闭合（summarize_ms 仍有正残差）。
2. **不等于 overall superiority**：这是一个受控 paired contest object 下的行为证明，不是 open-world agent benchmark。
3. **不等于 LangGraph 是核心创新**：LangGraph 只是执行图外壳。
4. **这个 walkthrough 是帮助理解系统流**，不是单独证明 superiority。
