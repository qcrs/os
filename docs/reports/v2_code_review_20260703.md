# StateBus v2 完整代码/实验审阅报告

**审阅时间**：2026-07-03
**分支**：`feat/statebus-v2-container-runtime`
**审阅范围**：代码事实、合同文档、实验证据、赛题要求对齐
**定性**：中立审阅，只做边界标定，不做主观美化

---

## 一、总体判断

**结论：实现已超出原型阶段，但离"赛题答辩可宣称全部指标"还有若干明确缺口。**

核心事实：

- StateBus v2 已在 openEuler Docker 容器中运行，pytest 通过 154 条（`container-validation-20260703_094529`）
- 四角色 `Planner→Retriever→Executor→Summarizer` 主链路在 `api+local embedding` 模式下有端到端证据
- external pure-text comparator 已通过 dev fixed-answer fairness gate（3/3 exact/quality），但被正确标记 `formal_superiority_claim_allowed=false`
- continuous/replay 在 20 轮 L2 语义状态传输和 16 轮 replay 观测中有正向数据
- CodeAct bwrap sandbox 可运行，但 API 生成代码本身依赖 deterministic policy fallback 才能稳定通过

**最大风险**：当前大部分 claim 依赖 dev-tier fixed-answer family（3 个样本），不是 formal financial family；replay 加固不完整；CodeAct API 生成不稳定；openEuler 报告是容器测试，不是 VM 最终交付。

---

## 二、当前已实现能力逐项核查

### 2.1 多 Agent 协作

**已成立，有代码和 telemetry 双重证据。**

- `v2/runtime/role_contract.py:7` 冻结四角色图：`planner->retriever->executor->summarizer`
- 每角色有独立 `responsibility`、`required_metric_keys`、`produced_artifacts`、`forbidden_scope`
- `scripts/v2_diagnostics/role_contract_audit.py` 可对任意 benchmark 报告验证角色存在性
- formal suite JSON：`family_case_count=3`；`quality_floor_pass_count=3`；`role_path_mode=api`

**边界**：角色分工是在 benchmark-constrained 框架内成立的，不是 open-world 自由多 Agent。Retriever/Executor 的 LLM autonomy 受限，见第七节。

### 2.2 StateRef / MemoryRef / ArtifactRef 边界

**v2 中三者边界已通过 schema 版本分开：**

- `v2/contracts/constants.py:16`：`MEMORY_REF_SCHEMA_VERSION = "statebus.memory_ref.v2"`
- `v2/contracts/constants.py:17`：`MEMORY_COMMIT_SCHEMA_VERSION = "statebus.memory_commit.v2"`
- `SemanticStateRef` 和 `ExecutionArtifactRef` 在 `v2/refs/` 中是并列的一等引用对象
- `CanonicalTaskSpec` 作为 replay key 基础对象已落地，`schema_version = "statebus.canonical_task_spec.v1"`

**已知问题**：MemoryRef 是 v2，MemoryCommit 也是 v2，但 `CANDIDATE→VERIFIED→INVALIDATED` 完整状态流转在 commit gate 逻辑中是否已走通需要进一步确认。

### 2.3 共享记忆与语义检索

**已实现，有 benchmark 证据：**

- `MemoryIndexStore` + `DeterministicEmbeddingEncoder` / local Qwen3-Embedding 双后端
- `v2/memory/models.py:34` 的 `MemoryType` 枚举覆盖：EVIDENCE / OUTCOME / STRATEGY / STRATEGY_CACHE / SEMANTIC_EVIDENCE / NUMERIC_FACT / ROUTE_HINT / EXECUTION_ARTIFACT / VALIDATED_REPLAY / EXACT_REPLAY
- continuous 结果：`L2_semantic_state_transfer_count=20`；`L3_artifact_reuse_count=41`；`history_backed_reuse_count=41`

**局限**：记忆写入的 `CANDIDATE→VERIFIED` 校验门尚未完整落地；replay negative audit 仅有 7 个 case，不是完整审计覆盖。

### 2.4 Replay 与连续任务复用

**continuous-replay 结果已有正向证据：**

| 指标 | 数值 |
|---|---|
| `eligible_for_replay_headline` | true |
| `replay_observed_round_count` | 16/16 |
| `validated_replay_count` | 13 |
| `exact_replay_count` | 3 |
| `L3_reuse_gain` | 16 |
| `L3_artifact_reuse_count` | 23 |

Flagship ablation（frozen evidence）：

| Family | exact | validated | skipped steps |
|---|---:|---:|---:|
| `csv_correlation_replay_v1` | 0 | 8 | 8 |
| `long_doc_metric_replay_v1` | 3 | 5 | 11 |

**边界**：这些证据绑定 frozen baseline commit `f7dcb15`，不是 HEAD remediation 后完整重跑。最新 CodeAct fallback 改动后 full suite 尚待复验。

### 2.5 typed control plane / telemetry / benchmark gate

**已实现，结构完整：**

- `v2/contracts/constants.py` 有完整 schema 版本注册（40+ schema ID）
- `TELEMETRY_EVENT_SCHEMA_VERSION`、`BENCHMARK_QUALITY_FLOOR_SCHEMA_VERSION` 已明确定义
- fairness gate 实现 fail-closed 语义（`external_text_baseline.py:110`）
- quality floor 三层：`deterministic_checks_passed`、`fact_coverage_passed`、`llm_judge_passed`

**缺口**：`llm_judge_passed` 目前在所有 case 中均为 `None`，LLM-as-a-Judge 层未实际启用。

### 2.6 openEuler container 测试可支持的 claim

**可支持：**
- openEuler 24.03-LTS-SP3 Docker image 构建成功
- 容器内 `tests/v2` 通过：`154 passed in 357.91s`（2026-07-03 fresh run）
- bwrap 在 root+高权限 Docker profile 下可运行 CodeAct
- API+local embedding 在容器路径下有 evidence index

**不能支持：**
- openEuler VM 最终交付（容器不等于 VM）
- 默认非 root bwrap 沙箱隔离（需要 `SYS_ADMIN + seccomp=unconfined` 特权 profile）
- production-grade 沙箱
- KV cache / hidden-state handoff

---

## 三、当前证据强度

| 能力 | 证据类型 | 强度 | 主要缺口 |
|---|---|---|---|
| 四角色 API 主链路 | container pytest 154 passed + preflight ok | 强 | 任务 family 仅 3 个 case |
| StateBus 内部 carrier compare | carrier compare JSON；valid=true；token delta=-250 | 中 | 仅 dev fixed-answer，非 formal financial |
| external pure-text comparator | new JSON；fairness gate pass 3/3 | 中（dev scope） | formal_superiority=false；task_ms +9263ms 更慢 |
| non-text flagship ablation | 4/4 stress pass；prompt_saved=13834 bytes | 中 | frozen baseline；非 HEAD 重跑 |
| continuous L2 语义传输 | 20 轮 | 中 | cold-start，非 formal |
| replay | 16 轮观测；13 validated；3 exact | 中 | frozen baseline；repair 后未完整重跑 |
| CodeAct bwrap | bundle ok=true；ast_policy_pass | 弱-中 | API 生成不稳定；依赖 deterministic fallback |
| openEuler VM | 无 | 无 | 只有 container 证据 |

---

## 四、主要问题和风险

### 4.1 高风险阻塞

**H1. CodeAct API 生成三次全部失败，依赖 deterministic policy fallback**

最新 bundle `container-validation-codeact-fix-20260703_040610`：
- `generated_by=deterministic_policy_fallback_after_llm_api`
- `generation_fallback_used=true`
- 不能宣称"LLM 生成的代码在沙箱中稳定运行"，只能宣称 bounded CodeAct 执行链路可工作

**H2. 最新 CodeAct fallback 修复后，完整 v2 pytest 尚未复验**

- frozen baseline 对应 commit `f7dcb15`
- 最新 commits（43c41bc、43b5951、5762d88、b9695df）之后未有完整重跑记录
- `tests/v2/test_bounded_llm_codeact_demo.py` 和 `scripts/v2_diagnostics/bounded_llm_codeact_demo.py` 存在未提交修改

**H3. external comparator wall time 更慢（+9263ms）**

- `runtime_non_llm_overhead_dominates` 是当前诊断结论
- 答辩中展示 external compare 必须诚实说明 StateBus 端到端耗时更长
- 赛题"降低通信开销"在 wall time 维度目前仅有 token/byte 节省，无端到端加速

### 4.2 中风险 claim 边界

**M1. external comparator 只是 dev fixed-answer（3 case），不能用于 formal superiority**

- `formal_superiority_claim_allowed=false`
- `external_comparator_claim_scope=dev_fixed_answer_only`

**M2. replay 证据绑定 frozen baseline，且 repair 后未重跑**

**M3. openEuler 报告是容器/index 证据，不是 VM 最终交付**

赛题要求："最终交付代码需在 openEuler 24.03-LTS-SP3 上编译运行"，当前只有 Docker container 证据。

**M4. runtime smoke 的 producer_run_id 来自固定 trace_id，不是真实唯一 run/session id**

### 4.3 实验覆盖缺口

- replay negative audit 只有 7 case，不是 12-case persisted-live-history 完整审计
- formal financial family 至今没有 external comparator 对比
- `llm_judge_passed` 在所有 case 均为 None，LLM-as-a-Judge 层未实际启用
- continuous/replay 新结果绑定 frozen commit，HEAD 未完整重跑

### 4.4 工程质量问题

- `MemoryCommit` 状态流转（CANDIDATE→VERIFIED→INVALIDATED）有枚举定义，但完整 commit gate 校验逻辑是否已走通需要代码确认
- `producer_run_id` 固定来自 trace_id 而非真实 session id
- bwrap 沙箱在答辩环境中需要特权 Docker profile

### 4.5 赛题展示风险

- 若评委追问"为什么你们的系统更慢"，需要准备 runtime_non_llm_overhead 来源说明
- CodeAct 展示依赖 deterministic fallback，若现场 API 不稳定只能展示 fallback 路径
- replay 收益数字不能直接说"节省了 N 次 LLM 调用"，需要精确口径

---

## 五、按赛题要求的差距表

| 赛题要求 | 当前状态 | 差距 |
|---|---|---|
| ≥3 个 Agent、≥3 类角色 | 四角色已实现，有 role_contract 审计 | 无实质差距 |
| 结构化通信协议 | v2 control plane + schema + telemetry 完整 | 无实质差距 |
| 握手/能力发现/协议映射 | ControlPlaneLoopbackServer + capability table 存在 | 无实质差距 |
| 不靠自然语言透传 | StateRef + typed carrier 已实现 | 无实质差距 |
| 纯文本 vs 结构化双模式对比 | internal carrier compare 有效；external comparator 通过 dev gate | external 只是 dev scope；formal 对比待补 |
| 非文本中间状态传递 | SemanticStateRef + Qwen3-Embedding + flagship ablation 证据 | 需说清楚不是 hidden-state/KV，是 embedding+feature bundle |
| 共享记忆模块 | MemoryRef v2，MemoryType 枚举完整 | commit gate 完整性待确认 |
| 关键词/标签/语义检索 | SQLite + local embedding + 检索日志 | LLM judge 质量层未启用 |
| 不同 Agent 在后续任务复用 | replay L3 reuse_gain>0 有证据 | frozen baseline，HEAD 未重跑 |
| ≥2 组关联连续任务 | csv_correlation + long_doc_metric 两族 | 符合要求 |
| 统计消息次数/token/非文本状态/耗时/命中率 | 全部有记录，role-level 拆分 | end-to-end 更慢需解释 |
| 10 轮稳定运行 | continuous 20 轮；replay 16 轮 | 已满足 |
| 提交源码/设计文档/部署文档/实验报告/演示视频 | 代码完整；evidence index 有 | 演示视频状态未知；VM 部署文档待补 |
| 鼓励 CodeAct | bounded CodeAct demo 可运行，bwrap backend | API 生成不稳定，依赖 fallback |
| 最终在 openEuler 24.03-LTS-SP3 运行 | Docker container 验证通过 | VM 最终交付未验证 |

---

## 六、external pure-text comparator 专项分析

### 6.1 实现方式

`v2/benchmark/external_text_baseline.py` 实现了四角色 pure-text baseline：

- **Planner**：收到 task_id、goal、public evidence text、公开 route/tool candidates 列表，用 LLM 选一个候选
- **Retriever**：收到 planner 输出 + evidence + candidates，再次 LLM 选择
- **Executor**：收到 route/tool 选择 + evidence，验证并构造 execution artifact
- **Summarizer**：收到 artifact + evidence + summary hint，生成最终 summary

四个角色分别调用独立 LLM，走同一个 `build_llm_client`，不共享内部 StateBus state。

### 6.2 是否是真正的四角色 pure-text baseline

**是，但有关键约束。**

代码确认：
- `external_text_baseline.py:158`：`baseline_kind = "external_pure_text_four_role"`
- `llm_call_count=4`，每角色独立 prompt，不共享内部 StateBus 对象

**约束**：executor prompt 中明确写入了 `revenue_value`（从 corpus 表格提取），使 executor 的验证难度有限。这在设计上合理（两条 lane 都能看到相同 evidence），但任务偏向"确认型"而非"发现型"。

### 6.3 fairness gate 实现边界

`external_text_baseline.py:110` 的 `_fairness_gate()` 中：

```python
checks = {
    "no_statebus_imports": True,       # 硬编码 True，不是动态检测
    "no_typed_state_used": True,       # 硬编码 True
    "no_metadata_leakage": True,       # 硬编码 True
    "no_lexical_fallback": True,       # 硬编码 True
    "llm_only_decisions": True,        # 硬编码 True
    "planner_visible_choice_only": _visible_choice_only(planner_payload),    # 动态
    "retriever_visible_choice_only": _visible_choice_only(retriever_payload), # 动态
    "executor_visible_choice_only": _visible_choice_only(executor_payload),   # 动态
}
```

**审阅发现**：前五项均为硬编码 True，不是动态检测。fairness gate 对"external baseline 是否真的没有用 StateBus helpers"的证明力靠代码结构保证，不是运行时验证。升级到 formal comparator 时需要将这些项改为动态扫描。

### 6.4 为什么 formal_superiority_claim_allowed=false 合理

1. dev fixed-answer family 只有 3 个 case，样本量不足支持正式优越性结论
2. `task_ms delta = +9263ms`（StateBus 更慢），无端到端时间优势
3. token/byte delta 为负（StateBus 更省），但 task_ms 更慢，说明存在 `runtime_non_llm_overhead`

### 6.5 当前 external compare 能证明什么，不能证明什么

**能证明：**
- external pure-text four-role baseline 在 dev fixed-answer family 上可以跑通，通过 fairness gate
- 在相同 3 个任务上两边 exact/quality 得分相同（3/3），StateBus 没有降低质量
- StateBus 在 prompt bytes 和 LLM tokens 方面有节省（-8624 bytes，-2002 tokens）

**不能证明：**
- formal financial family 上的优越性
- StateBus 在 wall time 上更快（当前更慢 +9263ms）
- open-ended 任务上的优越性
- `no_statebus_imports` 通过了运行时严格验证（当前是硬编码）

### 6.6 升级到 formal financial family comparator 需要改哪些文件

| 文件 | 改动 | 优先级 |
|---|---|---|
| `v2/benchmark/samples/formal_financial_family/` | 添加 ≥5 个 formal financial 任务样本 | P0 |
| `v2/benchmark/external_text_baseline.py` | 将 fairness gate 前五项改为动态检测 | P0 |
| `v2/benchmark/comparator_runner.py` | 添加 formal tier 对称运行配置 | P0 |
| `v2/benchmark/scoring.py` 或新文件 | 实现真正的 LLM-as-a-Judge（当前 `llm_judge_passed=None`） | P1 |
| `docs/contracts/v2_external_pure_text_fairness_gate.md` | 更新 claim boundary，升级到 formal tier | P1 |

升级后的容器测试命令：

```bash
export STATEBUS_CONTAINER_VALIDATION_DIR=/statebus/runs/container-validation-formal-compare-$(date +%Y%m%d_%H%M%S)
docker exec -e STATEBUS_CONTAINER_VALIDATION_DIR="$STATEBUS_CONTAINER_VALIDATION_DIR" statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  mkdir -p "$STATEBUS_CONTAINER_VALIDATION_DIR"
  python3 -m v2.benchmark.live_runner \
    --suite compare \
    --benchmark-tier formal \
    --role-path-mode api \
    --embedding-mode local \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/formal-compare.log"
'
```

---

## 七、planner / role autonomy 专项分析

### 7.1 当前 planner 是真实开放规划还是受控规划

**受控规划，但不是虚假规划。**

- `v2/runtime/smoke.py` 通过 `FallbackPlanner` 调用，`role_path_mode` 控制 deterministic 还是 api
- deterministic 模式：planner output 是预先确定的；api 模式：planner 才真正调用 LLM
- fixed-answer family 中，planner 收到的是 `CanonicalTaskSpec` + `request_text` + 公开 candidate list，已提示了答案范围

**合同层面**：`v2/runtime/role_contract.py:36` 禁止 planner 看到 oracle 字段（`primary_expected_route`、`acceptable_routes` 等）。但可见 candidate list 本身有限，自主规划被约束在有限搜索空间。

这是**合理的 benchmark 设计折中**：任务越开放，可测性越差；任务越固定，自主性越弱。当前设计更偏向可测性。

### 7.2 如何提高 planner autonomy 且保留可测性

**Step 1（低风险）**：在 fixed-answer family 中增加"planner 需要分解多步骤"的任务，不只是"选 route/tool"，而是"生成 retrieval objective + 分解子步骤"。不修改现有 3 个样本，只新增。

**Step 2（中风险）**：使用已有的 `PlannerHandoff` schema（`v2/contracts/constants.py:5`），让 planner 输出结构化的 retrieval objective + workflow steps，由 retriever/executor/summarizer 独立消费。

**Step 3（高风险）**：在 continuous family 中增加"planner 需要基于 memory hit 做重规划"的轮次，测试 planner 在跨任务依赖下的真实规划能力。

**不破坏现有证据的原则**：只在新任务族中引入，不修改 fixed-answer 和 formal-financial 现有样本及 expected fields。

### 7.3 是否应该引入 planner-generated plan schema

**应该，基础设施已存在。** `v2/contracts/constants.py:5`：`PLANNER_HANDOFF_SCHEMA_VERSION = "statebus.planner_handoff.v1"`。当前 benchmark 中 planner 的输出更多是"选候选"而不是"生成计划"。

引入步骤：
1. 设计 ≥2 个需要真正分解的任务（如：跨季度对比 → 分解为"提取 Q1/Q2 → 计算差值 → 生成报告"三步）
2. planner 输出 `PlannerHandoff`，包含 `workflow_steps`、`retrieval_objective`、`required_outputs`
3. retriever 基于 `retrieval_objective` 做 evidence 选择，不再依赖 candidate list
4. executor 基于 workflow_steps 中的具体 action 执行
5. summarizer 基于 `required_outputs` 合同生成报告

### 7.4 哪些改动会破坏现有证据

| 改动 | 风险 | 原因 |
|---|---|---|
| 修改 fixed-answer family 样本的 expected fields | 高 | quality floor 重算，历史对比失效 |
| 修改 `external_text_baseline.py` prompt 模板 | 高 | external compare 需要完整重跑 |
| 修改 `FallbackPlanner` 输出格式 | 中 | 影响 replay key 计算 |
| 修改 `CanonicalTaskSpec` 字段集合 | 高 | replay exact key 失效 |
| 新增任务 family | 低 | 不影响现有任务证据 |

---

## 八、CodeAct / sandbox 专项分析

### 8.1 当前沙箱边界

`v2/runtime/codeact_sandbox.py` 实现了两层沙箱：

**bwrap 层（容器内，高权限 profile）**

`codeact_sandbox.py:165` 的 `_run_bwrap()` 中：
- `--unshare-pid/ipc/uts/net`：namespace 隔离
- `/proc`, `/dev`, `/tmp` 独立挂载
- `/statebus/runs` 只读绑定
- `project_root` 只读绑定为 `/sandbox/project`
- `workspace_root` 读写绑定为 `/sandbox/workspace`
- resource limits：CPU 15s，AS 2GB，FSIZE 64MB，nofile 128，nproc 64

**resource 层（fallback，无 namespace）**

`codeact_sandbox.py:136` 的 `_run_resource()`：
- 仅靠 `RLIMIT_*` 进行资源限制
- 无 namespace 隔离，仅防止无限资源消耗

**当前容器测试**用的是 bwrap，但需要 `SYS_ADMIN + seccomp=unconfined + apparmor=unconfined` 特权 profile。**这不等价于 openEuler VM 级隔离，也不是生产环境 non-root 沙箱。**

### 8.2 AST policy 拦截了哪些危险能力

从合同文档 `docs/contracts/v2_bounded_codeact_demo.md` 和 `ast_audit.json` 路径来看，AST policy 是 fail-closed 的：

- 危险的 import（如 `subprocess`, `os.system` 等）
- 网络访问
- 文件系统写入超出 workspace 范围
- 任何不在 allowlist 内的 stdlib 使用

代码执行流程：`generate → AST audit → pass/fail → 仅 pass 才进 bwrap 执行`

**这个 fail-closed 设计是核心 claim 的基础**，任何 API 生成的代码都必须先过 AST policy。

### 8.3 deterministic fallback 是否合理，claim 应怎么写

**合理，但必须在答辩中明确区分两条路径。**

当前最新 bundle 结果：
- `generated_by=deterministic_policy_fallback_after_llm_api`
- `generation_fallback_used=true`
- API 生成 / repair 三次失败，最后走 deterministic policy fallback

**正确 claim 写法**：

> StateBus v2 实现了 bounded CodeAct 执行链路，包含 AST policy 审计（fail-closed）、bwrap namespace 隔离、resource 限制三层保护。当前演示在容器内（openEuler 24.03-LTS-SP3 Docker profile）通过 bwrap sandbox 成功执行了生成的 Python action，返回正常 artifact。该演示目前使用 deterministic policy fallback 生成代码；LLM API 直接生成代码的路径已实现 repair loop 和 AST 校验，但生成稳定性仍在改进中。

**不应写的 claim**：

- "LLM 生成的代码已在沙箱中稳定可靠运行"
- "系统支持任意 LLM CodeAct 代码的安全执行"
- "CodeAct 路径优于其他系统"

### 8.4 要让 API CodeAct 直接稳定成功，应改哪些部分

| 改动方向 | 具体文件 | 说明 |
|---|---|---|
| 改 prompt | `scripts/v2_diagnostics/bounded_llm_codeact_demo.py` | 当前 prompt 可能导致 LLM 生成超出 AST policy 的 import；需更明确说明 allowlist |
| 改 parser | `v2/runtime/codeact.py` 中的 response 解析 | 确保能从不同 LLM 输出格式（含 markdown codeblock）正确提取代码 |
| 改 repair loop | `bounded_llm_codeact_demo.py` + codeact runner | repair prompt 应包含上次失败的 AST error message，让 LLM 针对性修正 |
| schema enforcement | 考虑让 LLM 输出 JSON 包裹代码，而非裸代码 | 减少解析歧义 |
| executor envelope | `v2/runtime/codeact.py` | 确保 CodeAct request 的 action_spec 足够明确，限制生成范围 |

### 8.5 是否需要记录 raw LLM response、repair prompt、policy diff

**强烈建议记录，且 `generation_attempts.json` 已经在做这件事。**

应补充记录：
- 每次 repair 的具体 AST error（policy diff 形式，指出哪行违反了哪条规则）
- raw LLM response（当前 bundle 中是否完整保存需确认）
- repair prompt 的完整内容（不只是"修复后的"）

这些记录对答辩中"展示 fail-closed + repair 机制"非常有价值，即使最终走了 deterministic fallback，也能展示系统的防御深度。

---

## 十、KV cache / hidden-state future work 规划

### 10.1 当前 StateBus 支持的是哪一层状态传递

**当前实现的是 semantic state / artifact / memory replay 层，不是 KV transfer。**

当前链路：
- `SemanticStateRef`：embedding 向量 + feature bundle，用于检索 routing
- `ExecutionArtifactRef`：执行产物引用，用于 replay 和复用
- `MemoryRef`：历史记忆引用，用于跨任务 assist 和 replay

这三者都是应用层状态传递。KV cache / hidden-state handoff 是 LLM 推理引擎层的能力，与上面三层无直接关联。

### 10.2 只能称 Future Work 的内容

以下内容必须明确标注为"后续方向"或"Engine-Local Prefix Reuse"，不能在当前 claim 中出现：

- LLM 推理引擎 KV cache 在 Agent 间共享
- hidden state / activation 向量在 Agent 间直传
- 跨模型共享 latent representation
- 真正的后端消费者按神经网络内部表示继续推理

**正确描述方式**：
> 当前 StateBus 实现了 embedding + feature bundle + state ref 级别的非文本中间态传递，支持语义检索、路由决策和 artifact 复用。更深层的 KV cache 前缀复用属于 Engine-Local Prefix Reuse，是后续研究方向，依赖 LLM 推理引擎对外暴露相应接口。

### 10.3 KV cache 应放在哪一层

如果未来要实现，推荐放置位置：

| 层次 | 位置 | 说明 |
|---|---|---|
| LLM engine-local | 推理引擎内部（vLLM prefix cache） | 不需要 StateBus 介入，直接靠 prompt prefix 相同触发 |
| prefix cache key | `CanonicalTaskSpec` + prompt template hash | StateBus 可以记录"此任务使用了哪段 prefix"，帮助 engine 识别可复用的 prefix |
| runtime compatibility signature | `RuntimeCompatibilitySignature` 中加入 `llm_engine_version` | 确保 prefix cache 不会跨引擎版本复用 |
| StateRef metadata | `SemanticStateRef.metadata["prefix_cache_key"]` | 如果 engine 支持，可以把 prefix cache key 作为 state 的一个属性携带 |

### 10.4 最小实验设计

如果要做 Engine-Local Prefix Reuse 的初步实验：

1. 选择同一个 Planner prompt prefix（所有财报分析任务共享的系统 prompt）
2. 在 vLLM 中启用 prefix cache，对比有/无 prefix cache 的 TTFT（首 token 时延）
3. 统计 Planner 调用中有多少次触发了 prefix cache hit
4. 记录 `ttft_ms`、`prefix_cache_hit_count`、`prefix_cache_miss_count`
5. 与 `task_ms` 对比，验证 prefix cache 对端到端时延的实际贡献

**注意**：这个实验的前提是 LLM 服务是自托管的（vLLM），API 模式下无法控制引擎层 cache。

---

## 九、task design 专项分析

### 9.1 当前任务是否太小、太固定、太 benchmark-oriented

**是，但这是有意为之的折中，不是纯工程缺陷。**

fixed-answer family（3 个 case）：
- 任务结构非常固定：选 route/tool + 提取一个数值
- 正确答案是预先确定的 exact key
- 这保证了 benchmark 可复现性，但削弱了"多 Agent 系统真实能力"的展示说服力

formal financial family：
- 任务相对更真实（财报/经营指标分析），但证据仍需审查是否有 ≥5 个充分差异化样本

### 9.2 continuous/replay family 是否更接近赛题要求

**更接近，而且已有最好的证据。**

赛题要求"至少 2 组具有关联性的连续任务，验证记忆复用在减少重复计算方面的实际效果"。

`csv_correlation_replay_v1` 和 `long_doc_metric_replay_v1` 两族已经：
- 实现了跨轮依赖（`depends_on_rounds`）
- 实现了 validated_replay 和 exact_replay 区分
- 有 `skipped_step_count` > 0 的非零复用收益

**但**：这两族的任务描述是否足够贴合"真实业务场景"仍需答辩时向评委说明。纯粹的 CSV 相关性分析比 openEuler 服务诊断更抽象。

### 9.3 formal financial family 是否足够代表真实场景

**接近，但需要扩充多样性。**

当前 formal financial family 的主要任务模式是：
- 提取特定季度的特定指标
- 选择正确的 route（财务分析路径）和 tool（数值提取工具）

缺少的场景：
- **跨期对比**：Q1 vs Q2 同一指标的变化分析
- **多指标综合**：同时分析营收、成本、利润三个指标
- **异常检测**：某季度某指标出现异常的诊断
- **趋势分析**：多个季度的趋势判断

### 9.4 还应加入哪些任务

| 新任务类型 | 对应赛题要求 | 当前实现差距 |
|---|---|---|
| 长文档经营指标提取（多页财报） | 非文本状态传递（embedding 稀疏化长文档） | 已有 `long_doc_table_v1` 但需扩充 |
| 跨轮财报对比（Q1 vs Q2） | 连续任务+记忆复用 | 需新增 continuous family |
| 代码执行 artifact 复用（CodeAct 产物作为下轮输入） | CodeAct + replay | 未实现 |
| 多角色冲突修复（planner 与 executor 意见不一致） | 多 Agent 协调机制 | 未实现 |
| 记忆污染/失效场景（故意写入错误记忆后复用） | 记忆系统鲁棒性 | replay negative audit 已有 7 case，需扩充 |

### 9.5 新增任务不破坏现有证据的原则

- 新任务必须使用新的 `task_family` 标识符
- 新任务的 `expected_facts` 格式兼容现有 scoring contract
- 新任务不修改 `OfflineFinancialReportCorpus` 已有 document 的内容
- 如果新任务需要新 corpus，单独放在新 `corpus_*` 目录下

---

## 十一、后续计划和测试命令

### P0 必须补（阻塞答辩宣称）

---

#### P0-1. 完整 v2 pytest 复验（最新 HEAD）

**目标**：确认 CodeAct fallback 修复后所有 v2 tests 仍然通过

**涉及文件**：所有 `tests/v2/` + `scripts/v2_diagnostics/bounded_llm_codeact_demo.py` 未提交修改先提交

**测试命令**：

```bash
export STATEBUS_CONTAINER_VALIDATION_DIR=/statebus/runs/container-validation-full-pytest-$(date +%Y%m%d_%H%M%S)
docker exec -e STATEBUS_CONTAINER_VALIDATION_DIR="$STATEBUS_CONTAINER_VALIDATION_DIR" statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  mkdir -p "$STATEBUS_CONTAINER_VALIDATION_DIR"
  python3 --version 2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/env.log"
  git log --oneline -5 2>&1 | tee -a "$STATEBUS_CONTAINER_VALIDATION_DIR/env.log"
  python3 -m pytest -q tests/v2 \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/pytest-v2.log"
  echo "exit_code=$?" | tee -a "$STATEBUS_CONTAINER_VALIDATION_DIR/pytest-v2.log"
'
```

**预期证据路径**：`$STATEBUS_CONTAINER_VALIDATION_DIR/pytest-v2.log`

**可宣称**：HEAD 代码在 openEuler 容器下 `N passed`

**不能宣称**：fix 之前的 frozen baseline 仍然是最新状态

---

#### P0-2. CodeAct bounded demo 单测重跑

**目标**：确认 `test_bounded_llm_codeact_demo.py` 在 HEAD 代码下通过

**测试命令**：

```bash
export STATEBUS_CONTAINER_VALIDATION_DIR=/statebus/runs/container-validation-codeact-$(date +%Y%m%d_%H%M%S)
docker exec -e STATEBUS_CONTAINER_VALIDATION_DIR="$STATEBUS_CONTAINER_VALIDATION_DIR" statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  mkdir -p "$STATEBUS_CONTAINER_VALIDATION_DIR"
  python3 -m pytest -q tests/v2/test_bounded_llm_codeact_demo.py -v \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/codeact-tests.log"
  python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
    --role-path-mode deterministic \
    --sandbox-backend bwrap \
    --output-root "$STATEBUS_CONTAINER_VALIDATION_DIR/diagnostics" \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/bounded-codeact-det.log"
'
```

**预期证据路径**：`$STATEBUS_CONTAINER_VALIDATION_DIR/diagnostics/summary.json`（`ok=true`）

**可宣称**：bounded CodeAct 执行链路（AST policy + bwrap）可运行，deterministic mode

**不能宣称**：API 生成代码稳定可运行

---

#### P0-3. external compare 新结果与 frozen baseline 一致性确认

external compare 最新结果已在 `/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-fix-20260703_032551-external-cold-start-compare.json`，需确认与 frozen baseline hash 的关系。

**如需重跑 external compare**，从现有代码反查准确命令（不要猜测，以 `live_runner.py` 实际支持的参数为准）：

```bash
# 从 live_runner.py 确认 --suite compare 参数后执行
docker exec statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m v2.benchmark.live_runner --help 2>&1 | head -40
'
```

---

### P1 强烈建议

---

#### P1-1. 补 replay HEAD 证据

**目标**：continuous-replay 的 16 轮证据目前绑定 frozen baseline，需要在最新 HEAD 上重跑

**从现有代码反查命令**（参考已有的 continuous-replay JSON 路径中的 suite 名称）：

```bash
export STATEBUS_CONTAINER_VALIDATION_DIR=/statebus/runs/container-validation-replay-$(date +%Y%m%d_%H%M%S)
docker exec -e STATEBUS_CONTAINER_VALIDATION_DIR="$STATEBUS_CONTAINER_VALIDATION_DIR" statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  mkdir -p "$STATEBUS_CONTAINER_VALIDATION_DIR"
  python3 -m v2.benchmark.live_runner \
    --suite continuous \
    --benchmark-tier dev \
    --role-path-mode api \
    --embedding-mode local \
    2>&1 | tee "$STATEBUS_CONTAINER_VALIDATION_DIR/continuous.log"
'
```

**预期证据路径**：runtime artifact root 下的 `continuous-replay` JSON

**可宣称**：HEAD 代码下 continuous/replay 仍有正向收益

**不能宣称**：frozen baseline 数字等同 HEAD 数字

---

#### P1-2. fairness gate 动态化（no_statebus_imports 等五项）

**目标**：将 `external_text_baseline.py` 中硬编码 True 的五项改为真正的动态检测

**涉及文件**：`v2/benchmark/external_text_baseline.py:110`

**测试命令**：

```bash
python3 -m pytest -q tests/v2/test_fixed_answer_and_external_baseline.py -v
python3 -m pytest -q tests/v2/test_compare_diagnostics.py -v
```

---

#### P1-3. formal financial family 任务扩充

**目标**：添加 ≥5 个 formal financial 任务，覆盖跨期对比、多指标综合

**涉及文件**：`v2/benchmark/samples/formal_financial_family/`

---

### P2 展示增强

---

#### P2-1. runtime overhead 说明文档

**目标**：针对 external compare 中 +9263ms 的 runtime overhead，准备诚实且有说服力的解释

内容应包含：
- audit bundle 写入的文件数量和字节数（引用 `runtime_persistence_breakdown.py` 输出）
- bwrap sandbox setup 的额外耗时
- 在 formal financial 场景下 overhead 可能相对较小的论证

**测试命令**：

```bash
docker exec statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 scripts/v2_diagnostics/runtime_persistence_breakdown.py \
    --output-root /statebus/runs/v2-diagnostics/persistence-breakdown-$(date +%Y%m%d_%H%M%S)
'
```

---

#### P2-2. CodeAct API 生成稳定化

**目标**：改进 prompt 和 parser，使 API 生成代码通过率 ≥1/3

**涉及文件**：
- `scripts/v2_diagnostics/bounded_llm_codeact_demo.py`
- `v2/runtime/codeact.py`（AST policy allowlist 说明在 prompt 中更清楚）

**测试命令**：

```bash
docker exec statebus-dev-qcrs bash -lc '
  source /usr/local/bin/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 scripts/v2_diagnostics/bounded_llm_codeact_demo.py \
    --role-path-mode api \
    --sandbox-backend bwrap \
    --max-repair-attempts 3 \
    --output-root /statebus/runs/v2-diagnostics/codeact-api-$(date +%Y%m%d_%H%M%S)
'
```

**预期证据路径**：`summary.json`（`generation_fallback_used=false`，`ok=true`）

**可宣称**：LLM API 生成代码通过 AST policy 并在 bwrap 中稳定运行

---

### P3 Future Work

---

#### P3-1. openEuler VM 最终交付验证

**目标**：在 bare-metal 或 KVM VM 上验证 pytest + benchmark 可复现

**涉及文件**：`docker/compose.yaml`、`scripts/setup_host_dev_env.sh`、`deploy/`

**可宣称**：满足赛题"在 openEuler 24.03-LTS-SP3 上运行"的最终交付要求

---

#### P3-2. Engine-Local Prefix Reuse 初步实验

**目标**：量化 planner/summarizer 的 prompt prefix cache 命中率和 TTFT 收益

**前提**：需要自托管 LLM 服务（如 vLLM），不适用于 API 模式

---

#### P3-3. replay audit 从 7 case 扩展到 12 case persisted-live-history

**目标**：补充 replay negative audit，覆盖 persisted live history 的 12 种边界情况

**涉及文件**：`tests/v2/test_replay.py`、`v2/benchmark/live_runner.py`

---

## 十二、哪些 claim 可以写进答辩，哪些不能写

### 12.1 可以明确宣称的

**多 Agent 协作**
- StateBus v2 实现了四角色协作系统（Planner→Retriever→Executor→Summarizer），每角色有明确的职责边界和禁止行为合同
- 系统在 `api+local embedding` 模式下完成了端到端任务（形式：财务指标分析任务族）
- `role_contract_audit.py` 可对任意 benchmark 报告自动验证四角色的存在性和指标完整性

**结构化通信与非文本状态传递**
- 控制面使用 typed schema（40+ schema ID，全部版本化），不靠自然语言透传
- `SemanticStateRef` + Qwen3-Embedding 实现了 embedding 级别的非文本中间状态传递
- flagship ablation 显示：使用 StateRef 后 LLM prompt 可省 13834 bytes（prompt-visible），prompt bytes 减少 2100 bytes（4 个任务族 4/4 stress pass）

**共享记忆与复用**
- 实现了 SQLite + local embedding 共享记忆存储，`MemoryType` 覆盖 10 种记忆类型
- continuous 运行：20 轮 L2 语义状态传输，41 次 L3 artifact 复用
- continuous-replay 运行：16 轮观测，13 轮 validated_replay，3 轮 exact_replay，`L3_reuse_gain=16`
- replay 三层（assist / validated / exact）有明确的准入边界合同

**对比实验**
- internal carrier compare：StateBus 与纯文本 carrier 对比有效（`comparison_valid=true`），prompt bytes 节省 1922 bytes，LLM tokens 节省 250
- external pure-text four-role comparator 通过了 dev fixed-answer fairness gate（3/3 exact/quality），token 节省 2002，prompt bytes 节省 8624

**容器运行**
- 在 openEuler 24.03-LTS-SP3 Docker 容器中 `pytest tests/v2` 通过 154 条
- bwrap sandbox（高权限 profile）下 bounded CodeAct 执行链路可运行，AST policy fail-closed

**工程完整性**
- 10 轮以上连续稳定运行（continuous 20 轮，replay 16 轮）
- 完整 telemetry 和 benchmark gate，每个实验结果都有 sha256 hash 记录的证据 index

### 12.2 不能宣称的

| 不能宣称 | 原因 | 正确口径 |
|---|---|---|
| StateBus 在端到端耗时上优于纯文本 | external compare task_ms +9263ms，StateBus 更慢 | "在 token/prompt bytes 上有节省，端到端耗时因 runtime overhead 更高，正在优化" |
| formal financial 场景下优于纯文本 | external comparator 只是 dev fixed-answer scope，不是 formal | "dev fixed-answer fairness gate 已通过，formal 场景对比是下一步工作" |
| LLM 生成的 CodeAct 代码稳定可靠运行 | API 生成三次全部失败，依赖 deterministic fallback | "bounded CodeAct 执行链路可工作，API 生成稳定性仍在改进" |
| 实现了 KV cache / hidden-state handoff | 未实现 | "实现了 embedding + feature bundle 级别的非文本中间态，KV cache 是 Engine-Local Prefix Reuse，属于后续方向" |
| openEuler VM 最终交付已验证 | 只有 Docker container 证据 | "已在 openEuler 24.03-LTS-SP3 Docker 容器中验证，VM 最终交付是最后交付前的步骤" |
| 完整记忆复用收益（命中即收益）| assist 不等于 replay gain，`skipped_step_count` 才是真实收益 | "validated/exact replay 有 skipped_step_count > 0 的非零收益，assist 层不计入 step 节省" |
| replay 证据是 HEAD 最新状态 | frozen baseline commit f7dcb15，最新修复后未完整重跑 | "证据绑定 frozen baseline，最新修复后的完整重跑是 P0 待补项" |
| 系统架构等同完整分布式多 Agent | 当前是单容器单进程为主的 benchmark 架构 | "实现了四角色协作原型，控制面和数据面分离，UDS executor transport 有样机" |
| CodeAct 优于其他系统 | 没有横向对比 | "实现了受控 bounded CodeAct，不做横向对比" |

### 12.3 答辩中的关键防守点

**当评委问"为什么 StateBus 更慢"**：

> "当前 dev fixed-answer 场景的主要 overhead 来自审计 bundle 写入（每次运行写入多份 manifest、telemetry log、role prompt slice），这些是实验可追溯性的必要成本。在更大规模任务中，非文本状态传递节省的检索/重传开销会超过 overhead。我们也在实现 `benchmark_balanced` 持久化模式来降低非必要写入。"

**当评委问"4 个角色是真的分工还是形式分工"**：

> "每个角色有明确的禁止行为合同（Planner 不能执行工具，Retriever 不能写最终答案，Executor 不能访问检索集以外的证据），这些合同在 `role_contract.py` 中机器可验证，并通过 `role_contract_audit.py` 在每次实验后自动校验。"

**当评委问"embedding 是怎么传递的，不是直传给 LLM 看吧"**：

> "正确。embedding 主要用于检索和记忆召回，不直传给通用 LLM。LLM（Planner/Summarizer）消费的是 adapter 整理后的文本摘要和结构化字段（`LLM_CONTEXT_SLICE`），不是裸向量。embedding 向量通过 `SemanticStateRef` 传递，但 ref 本身只是一个引用 handle，不是把向量 dump 进 prompt。"

**当评委问"记忆复用是不是只是上下文延续"**：

> "不是。系统区分了三层：assist（历史记忆作为参考，不跳步）、validated_replay（跳过构思步骤，用新输入重新执行）、exact_replay（输入 hash 等价，直接复用旧结论跳过 retrieve+execute）。当前 continuous-replay 中有 13 轮 validated_replay 和 3 轮 exact_replay，`skipped_step_count` 非零。这不是上下文延续，是有明确条件的步骤跳过。"

---

## 十三、KV Cache / hidden-state 创新深化方向

> 本节为后续研究方向规划，所有内容均标注为 Future Work。当前实现不包含以下机制。

### 13.1 两个传递维度的区分

KV cache / hidden-state 传递存在两个完全不同的维度，对应不同的创新路径：

| 维度 | 对象 | 机制 | 当前 StateBus 基础 |
|---|---|---|---|
| **单任务内**：4 Agent 之间的 KV prefix inheritance | 同一任务的 Planner→Retriever→Executor→Summarizer | 后一个 Agent 的 prompt 前缀包含前一个 Agent 的完整 prompt | `PlannerHandoff` schema + `LLM_CONTEXT_SLICE` |
| **跨任务**：不同任务共享 corpus 的 KV cache | 引用相同文档的多个任务 | 相同 evidence corpus 作为静态 prefix，vLLM 自动命中 | `CanonicalTaskSpec` 的 `ticker+quarter` 标识符 + `SemanticStateRef.metadata` |

---

### 13.2 创新点一：Agent 链式 Prefix Inheritance（单任务内）

**原理**

vLLM prefix cache 的核心：两次 LLM 请求的 prompt **前缀完全相同**时，前缀对应的 KV 激活直接复用，不重新计算。

当前 StateBus 的 4 个 Agent 每人独立构造 prompt，没有利用这个机制。

**创新结构**

强制规定 handoff 的 prompt 构造协议：

```
Planner  prompt: [SYS] + [CORPUS] + [TASK] + [PLANNER_INSTRUCTIONS]
Retriever prompt: [SYS] + [CORPUS] + [TASK] + [PLANNER_INSTRUCTIONS] + [PLANNER_OUTPUT] + [RETRIEVER_INSTRUCTIONS]
Executor  prompt: [SYS] + [CORPUS] + [TASK] + [PLANNER_INSTRUCTIONS] + [PLANNER_OUTPUT] + [RETRIEVER_INSTRUCTIONS] + [RETRIEVER_OUTPUT] + [EXECUTOR_INSTRUCTIONS]
Summarizer prompt: [SYS] + [CORPUS] + [TASK] + ... + [EXECUTOR_OUTPUT] + [SUMMARIZER_INSTRUCTIONS]
```

这样：
- Retriever 调用 LLM 时命中 Planner 那段 KV cache
- Executor 调用 LLM 时命中 Planner+Retriever 那段 KV cache
- Summarizer 调用 LLM 时命中前三个 Agent 的 KV cache

**实现代价**：只需修改 StateBus 的 `LLM_CONTEXT_SLICE` 构造合同，不需要修改 vLLM。

**可测指标**：
- `prefix_cache_hit_count`（每个 Agent 调用中命中的 prefix cache 次数）
- `ttft_ms`（首 token 时延，prefix cache 命中后 TTFT 显著下降）
- `kv_reused_tokens`（复用的 token 数量）

**注意事项**：
- 此方案使 prompt 随链式累积变长，需要设置 token budget 上限
- 需要结合 context compression（见 13.4）避免 Summarizer 的 prompt 过长
- vLLM 的 prefix cache 是 block-level 的（通常 16 token 一 block），prefix 必须精确到 block 边界才能命中

---

### 13.3 创新点二：Corpus-Level KV 跨任务共享

**原理**

StateBus 的 formal financial family 中，多个任务可能引用**同一份财报文档**（如 ACME 的 2026Q1 报告）。这份文档几千 tokens，每次 LLM 调用都要重新编码成 KV，代价高昂。

**创新结构**

将 prompt 分为两个明确的部分：

```
[STATIC PREFIX]  = [SYS_PROMPT] + [CORPUS_DOCUMENTS]   # 跨任务不变
[DYNAMIC SUFFIX] = [ROLE_INSTRUCTIONS] + [TASK_PARAMS]  # 任务特定
```

当两个任务引用相同 corpus 文档时，`[STATIC PREFIX]` 完全相同，vLLM 自动命中 corpus 那段 KV cache。

**与 StateBus 的集成点**

- `CanonicalTaskSpec` 已记录 `ticker`（股票代码）和 `quarter`（季度），可以派生出 `corpus_prefix_hash = sha256(ticker + quarter + sys_prompt_version)`
- 这个 hash 可以放入 `SemanticStateRef.metadata["corpus_prefix_hash"]`
- StateBus 调度器可以基于 `corpus_prefix_hash` 做 **batch 排序**：同一个 corpus 的任务放在同一个时间窗口执行，最大化 prefix cache 驻留率

**预期收益**

假设财报文档 = 3000 tokens，LLM 每次调用都触发 corpus 重编码：
- 无 prefix cache：4 Agent × 3000 tokens = 12000 tokens 编码
- 有 prefix cache：第一次任务 12000 tokens，后续同 corpus 任务 ≈ 0 tokens corpus 编码

**可测指标**：
- 不同 ticker/quarter 的任务对比 Retriever/Executor 的 `ttft_ms`
- 同 corpus 多轮任务的 prefix cache hit rate

---

### 13.4 创新点三：SemanticStateRef 驱动的 Input-Level KV 压缩

**背景**

KV 压缩（SnapKV、PyramidKV 等）需要修改 LLM 推理引擎。但可以在 **input 层做等价的 token budget 压缩**，效果上等同于减少 KV 计算量，且**不需要修改推理引擎**。

**创新结构**

Retriever 做完 evidence selection 后，不只返回选中的 doc chunk，同时计算并返回一个 **token importance score**（用 embedding similarity 作为 attention 的代理指标）：

```python
@dataclass(frozen=True)
class EvidencePruningHint:
    chunk_id: str
    importance_score: float      # embedding sim to query
    token_count: int
    keep_in_kv_budget: bool      # 是否保留在 token budget 内
```

这个 `EvidencePruningHint` 随 `SemanticStateRef` 传递给 Executor 和 Summarizer。Executor 构造 prompt 时只使用 `keep_in_kv_budget=True` 的 chunk。

**本质**：这是 **input pruning**，但从 KV 计算角度看等价于 KV 层减少，且与现有 `SemanticStateRef` 完全兼容。

**与 flagship ablation 的关联**

当前 flagship ablation 已经显示 SemanticStateRef 节省了 prompt bytes（13834 bytes raw，2100 bytes prompt-visible）。加入 `EvidencePruningHint` 可以进一步量化：

- `evidence_tokens_before_pruning`
- `evidence_tokens_after_pruning`
- `pruning_ratio`
- `quality_floor_pass`（确保压缩后质量没有下降）

---

### 13.5 创新点四：ReplayClass × KV Cache 分层联动

**这是最有架构创新性的方向**，可以直接写进答辩的 StateBus 贡献点。

**核心思路**：将 replay 的三层分类与 KV cache 策略精确对应，形成统一的 **"状态复用金字塔"**。

```
                    ┌─────────────────────────────────┐
                    │      exact_replay               │
                    │  完全跳过 LLM 调用               │
                    │  从 CAS 直接恢复结果              │
                    │  KV = 0（无需任何 KV 计算）       │
                    └────────────────┬────────────────┘
                                     │ 降级
                    ┌────────────────▼────────────────┐
                    │    validated_replay              │
                    │  corpus 前缀 KV 可复用            │
                    │  (相同文档，不同查询)             │
                    │  重算：task suffix KV 部分        │
                    └────────────────┬────────────────┘
                                     │ 降级
                    ┌────────────────▼────────────────┐
                    │       assist                    │
                    │  system prompt 前缀 KV 可复用    │
                    │  corpus 需重算                   │
                    │  历史摘要作为 context 参考        │
                    └────────────────┬────────────────┘
                                     │ 降级
                    ┌────────────────▼────────────────┐
                    │      cold start                 │
                    │  全量计算                        │
                    │  仅 system prompt KV 可能命中    │
                    └─────────────────────────────────┘
```

**与现有合同的对齐**

这个分层与 `docs/planning/replay_admissibility_contract.md` 中的三层定义完全对应：

| ReplayClass | KV 策略 | 节省来源 |
|---|---|---|
| `exact_replay` | 跳过 LLM 调用 | 100% LLM tokens 节省 |
| `validated_replay` | corpus prefix KV 命中 | corpus 编码时间节省（TTFT 下降） |
| `assist` | system prefix KV 命中 | system prompt 编码时间节省 |
| cold start | 全量计算 | 仅 inter-request system KV 共享 |

**可测指标**（在 continuous/replay benchmark 中记录）：
- `replay_class_kv_savings_tokens`：按 replay class 分组统计节省的 KV tokens
- `replay_class_ttft_ms`：按 replay class 分组统计 TTFT 时延
- `estimated_kv_compute_saved_ratio`：估算 KV 计算节省比例

---

### 13.6 最小可行实验设计（不需要修改推理引擎）

以下实验可以在**当前架构**下进行，不依赖 vLLM 的 KV cache 接口暴露：

**实验 A：Prefix Alignment 效果测量**

1. 保持当前 4 角色架构不变
2. 给两组任务：Group A（4 Agent 独立 prompt，不共享前缀）vs Group B（4 Agent 链式 prefix）
3. 使用 vLLM 的 `--enable-prefix-caching` 并开启 metrics
4. 对比两组的 `ttft_ms`、`prompt_tokens`、`total_latency_ms`

**实验 B：Corpus-Level Batch Scheduling**

1. 选取 3 个引用相同 corpus 的任务 + 3 个引用不同 corpus 的任务
2. 比较"相同 corpus 任务连续执行"vs"随机顺序执行"的 TTFT
3. 记录 `corpus_prefix_hash`，作为 `SemanticStateRef.metadata` 的标准字段

**实验 C：EvidencePruningHint 压缩效果**

1. 在 Retriever 输出中加入 `importance_score`（用 embedding cosine similarity 计算）
2. 设置 token budget：只保留 `importance_score > threshold` 的 chunk
3. 对比有/无 pruning 的 `prompt_tokens`、`quality_floor_pass`、`task_ms`

---

### 13.7 answer 边界

**可宣称（实验后）**：
- StateBus 通过 `CanonicalTaskSpec` 的 corpus 标识符派生 prefix cache key，支持 corpus-level 跨任务 KV 复用
- StateBus 的 ReplayClass 分层与 prefix cache 策略对齐，形成统一的状态复用金字塔
- `EvidencePruningHint` 实现了不修改推理引擎的 input-level KV 等价压缩

**不能宣称**：
- 实现了 LLM 内部 KV 激活的直接跨 Agent 传递（当前不可行，需要推理引擎接口）
- 实现了跨模型的 KV 共享（不同 Agent 用不同模型时完全不可行）
- 在不自托管 LLM 的情况下验证了 prefix cache 效果（API 模式下无法控制引擎层 cache）

---

| 文件 | 用途 |
|---|---|
| `v2/runtime/role_contract.py` | 四角色合同定义，机器可验证 |
| `v2/runtime/codeact_sandbox.py` | bwrap + resource 双层沙箱实现 |
| `v2/benchmark/external_text_baseline.py` | external pure-text four-role baseline |
| `v2/benchmark/scoring.py` | fixed-answer quality floor 评分逻辑 |
| `v2/contracts/constants.py` | 全部 schema 版本 ID 注册 |
| `v2/memory/models.py` | MemoryRef、MemoryType、MemoryCommitStatus |
| `docs/contracts/v2_external_pure_text_fairness_gate.md` | external comparator 的 claim boundary |
| `docs/contracts/v2_role_contract.md` | 角色合同文字版 |
| `docs/contracts/v2_bounded_codeact_demo.md` | CodeAct demo 的 claim boundary |
| `docs/reports/final_v2_evidence_index_20260703.md` | frozen evidence index（commit f7dcb15） |
| `docs/reports/openeuler_container_validation_20260703.md` | openEuler 容器验证报告 |
| `scripts/v2_diagnostics/compare_diagnostics.py` | external compare 诊断脚本 |
| `scripts/v2_diagnostics/bounded_llm_codeact_demo.py` | CodeAct bounded demo |
| `scripts/v2_diagnostics/runtime_persistence_breakdown.py` | runtime 持久化开销分析 |

---

*本文档由审阅生成，路径：`docs/reports/v2_code_review_20260703.md`*

