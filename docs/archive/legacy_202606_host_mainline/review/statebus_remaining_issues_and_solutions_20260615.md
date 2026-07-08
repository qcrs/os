# StateBus 代码修改后遗留问题与解决方案任务书

日期：2026-06-15
前置文档：`docs/analysis/full_system_audit_20260615.md`、`docs/analysis/experimental_anomalies_20260615.md`
本次修改范围：16 文件，+552/-231 行，branch `feat/contest-audit-hardening-20260615`

---

## 一、已完成的修改概览（无需再动）

以下修改已落地并通过 smoke 测试验证（`python -m pytest -q tests/test_smoke.py` 5 passed），不需要重新讨论：

| 编号 | 修改内容 | 涉及文件 |
|---|---|---|
| D1 | planner_source/planner_step_count/planner_contract_valid 审计字段挂到 RunContext，并在 task payload 中输出 | `orchestrator.py`, `runner.py` |
| D2 | handoff_bytes 从主累计口径中移除，改为 handoff_payload_bytes/handoff_wire_bytes/handoff_textual_bytes/handoff_nontext_bytes | `orchestrator.py` |
| D3 | _aggregate_task_groups 按 (mode, task_group) 分组，解决跨 mode handoff 数据抄写 | `runner.py` |
| D4 | memory_hit_rate → assist_memory_hit_rate 全链路重命名，旧名保留 alias | `metrics.py`, `runner.py` |
| D5 | failure_count → run_failure_count，新增 expected_negative_task_failure_count / negative_control_trigger_rate | `runner.py` |
| D6 | public_surface 收敛为 formal_headline / formal_secondary_planner / formal_secondary_memory / audit_only 四类 + 8 个 alias 映射 | `sample_tasks.py`, 7 个 YAML |
| D7 | _plan_from_llm_output 解除固定 3 步合同，改为 3-5 步 + DAG 合法性 + semantic coverage 校验 | `sample_agents.py` |
| D8 | _feature_bundle_from_executor_decision_packet() 不再调用 build_feature_bundle()，直接从 packet 取值，新增 _validate_executor_decision_packet() 做 schema/hash 校验 | `executor_runtime.py` |
| D9 | Protocol summarizer 在非 audit 路径改用 compact JSON（_build_protocol_summary_input_packet + json.dumps），不展开成文本 | `sample_agents.py` |
| D10 | plan_source_default 支持 + formal pack 校验（非 audit pack 必须有显式 plan_source 或 plan_source_default） | `sample_tasks.py` |
| D11 | extract_corpus_eval_labels 新增，把 route_hint/tool_name 提取为 eval label，与 runtime hint 分离 | `local_corpus.py` |

---

## 二、当前遗留问题（需要分析和解决）

### 问题 1：Contest 包 Planner 仍然被绕过

**当前状态**：
- D7 解除了 `_plan_from_llm_output()` 的固定 3 步校验——LLM Planner 可以做 3-5 步的自由分解
- D10 增加了 `plan_source_default` 支持和 formal pack 校验
- 但 `contest_dual_mode_controlled_v3_benchmark.yaml:18` 写的是 `plan_source_default: yaml`
- 所以 contest 包上的 Planner 执行路径仍然是 `plan_source == "yaml" → build_plan(task)` → 硬编码 3 步

**矛盾点**：
- 赛题要求"覆盖规划角色"——但 formal headline 包上 Planner 从未被调用
- 如果改成 `plan_source_default: llm`，会引入第三个变化变量（Planner 的行为在 text 和 protocol 下不同——prompt 不同、输出格式不同），破坏 contest 包的"只改 mode + handoff_object" 的合同
- 如果保持 yaml，Planner 能力在最重要的包上完全没有展示

**需要解决的核心问题**：既要展示 Planner 能力（赛题要求），又要保持 contest 包的变量受控。怎么安排？

---

### 问题 2：Corpus 预标签（route_hint / tool_name）仍然影响运行时检索

**当前状态**：
- D11 新增了 `extract_corpus_eval_labels()` 把 hint 复制到 eval 层——但这不影响运行时
- `agents/sample_agents.py:304` 调用改为了 `_resolve_runtime_corpus_hints()`，替代原来的 `extract_corpus_feature_hints()`
- 但 `_resolve_runtime_corpus_hints()` 的具体实现路径需要确认：如果它仍然读 `CorpusDoc.route_hint` / `CorpusDoc.tool_name`，则预标签问题未解决
- `contest_release_regression_corpus.yaml` 中所有 32 个文档的 `route_hint` 和 `tool_name` 字段仍然存在

**影响**：
- 检索的 route/tool 决策 85% 来自文档预标签（hint_consensus），不是来自真实检索推理
- 协议模式下 EXECUTOR_DECISION_PACKET 的 route metadata 优势在预标签场景下是冗余的——text 侧也能从同一文档中读到同样的 hint
- 这就是为什么 contest 包的 `exact_match_rate=0.85` 在两模式下完全一样

**需要解决的核心问题**：如何让 protocol 的结构化检索精度在 benchmark 中有展示空间？

---

### 问题 3：Task 鉴别诊断难度不足

**当前状态**：
- 5 个 family 各只有一个正确答案（route + tool）
- "distractor" 和 "ambiguous" 复杂度等级的 task 期望答案不变——只是多给了一个 `-false` 文档
- 没有跨 family 证据组合推理任务
- query 文本中包含直接指向正确答案的关键词（如 "connection pool waits" → db_pool_saturation）
- 11 个 v3 pack 共用同一个 `contest_release_regression_corpus.yaml`

**影响**：
- protocol 模式的精确路由传递在"一个正确答案"的场景下没有正确率提升空间——text 的 baseline 也是 0.85
- 正确率的瓶颈不在于通信格式，在于 task 本身的难度天花板

**需要解决的核心问题**：如何设计任务让两种模式的正确率出现差异（至少让 protocol 有机会展示优势）？

---

### 问题 4：Contest 包的 memory/reuse 全部关闭

**当前状态**：
- `contest_dual_mode_controlled_v3_benchmark.yaml` 所有 40 行 `runtime_reuse_contract: reuse_disabled`
- `memory_policy_controlled_v3` 和 `memory_reuse_v3` 上有 replay proof，但它们是 protocol-only 的
- 没有跨 mode 的 memory reuse 对比

**影响**：
- 赛题要求"验证共享记忆复用在减少重复计算、降低协作开销和提升任务效率方面的实际效果"——这个验证在 contest 包（formal headline）上完全没有
- 如果评委只看 contest 包，会认为 memory 功能没有被测试

**需要解决的核心问题**：如何在不太幅增加变量缠绕的前提下，把 memory reuse 引入 contest 对比面？

---

### 问题 6：typed_state_mechanism_v3 被降级为 audit_only 后的 formal 空位

**当前状态**：
- `typed_state_mechanism_v3_benchmark.yaml` 的 `public_surface` 从 `formal_secondary_typed_state_mechanism` 改为 `audit_only`
- 同样 `typed_state_authenticity_v3_benchmark.yaml` 也被改为 `audit_only`
- D6 的 alias 映射中 `formal_secondary_typed_state_mechanism` → `audit_only`

**影响**：
- 原来 typed-state mechanism 有一条 formal-secondary claim line，现在这条线空了
- typed_state_mechanism_v3 的数据仍然可用（kind match = 1.00, executor_expected_kind_match_rate = 1.00），但 public_surface 声明为 audit_only 意味着它不能作为 formal claim 引用

**需要解决的核心问题**：typed-state mechanism 的 formal claim 应该谁来承担？是否需要一个新的 formal-secondary pack，还是恢复 mechanism_v3 的 formal 身份但收缩它的 claim 范围？

---

### 问题 7：Open surface 数据仍来自确定性 stub，不是真实 LLM

**当前状态**：
- `eval/open_runner.py:414` 直接使用 `task.primary_expected_route` / `task.primary_expected_tool`，不走真实检索
- `eval/open_runner.py:637` 使用 `_token_estimate()` 估计 token，不做真实 LLM 调用
- `eval/text_open_baseline.py:123` 是 lexical deterministic runtime
- 20260615 批次的 SUMMARY 写的是 `LLM config: reused-existing-results`

**影响**：
- open surface 的 task_ms=16ms 不可能来自真实 LLM
- 不同 runtime arm 的 reuse 指标完全相同到小数点后两位——统计上不可能
- 如果有人把 open surface 数据当作真实外部系统对比证据，会被评审直接驳回

**需要解决的核心问题**：open surface 的定位应该怎么声明？如果需要真实外部基线对比，应该在什么时候用什么方式跑？

---

## 三、需要你分析和解决的问题

请阅读以上 6 个遗留问题（问题 1-4、6-7。问题 5 保留编号占位），结合以下文件理解当前状态：

### 必须先读的文件

1. `docs/reference/题目.md` — 赛题原文
2. `docs/analysis/full_system_audit_20260615.md` — 全系统审计报告
3. `docs/analysis/experimental_anomalies_20260615.md` — 实验数据异常清单
4. 以下代码文件确认当前状态：
   - `tasks/sample_tasks.py` — plan_source 默认值、public_surface 定义、contract 校验
   - `tasks/contest_dual_mode_controlled_v3_benchmark.yaml` — contest 包的完整配置
   - `agents/sample_agents.py` — _plan_from_llm_output、_resolve_runtime_corpus_hints、summarizer 新路径
   - `runtime/orchestrator.py` — compile_task_plan、_plan_task
   - `runtime/executor_runtime.py` — _feature_bundle_from_executor_decision_packet、_validate_executor_decision_packet
   - `eval/runner.py` — 指标聚合、gate 函数
   - `tasks/local_corpus.py` — extract_corpus_eval_labels、_resolve_runtime_corpus_hints

```

### 约束

- 用中文
- 落到具体文件:行号
- 不要涉及 Docker/openEuler/nsjail/API repeat=10 执行步骤
- 方案的动机必须引用赛题原文的对应评分项
- 如果某个问题在当前分支上已经有解决的基础设施但没正确配置，明确指出"只需改 YAML 配置"而非"需要改代码"
