# StateBus v2 Adaptive Agent 与 LLM CodeAct 续作 Review/实施 Prompt

> 用途：将本文从“任务说明”开始的全部内容交给新的编码 Agent。
>
> 工作方式：先基于当前代码和现有产物做 review，给出详细实施计划；随后在同一轮继续实现、测试和收尾。除非遇到需要用户决定的真实阻塞，不要只交付方案而停止。
>
> 当前日期：2026-07-18。
>
> 重要口径：目标是提高四个 Agent 的真实决策权，并让 Executor 使用 LLM 生成的受限 CodeAct。目标不是 25/25，也不是为错误 case 写特化规则。系统/安全不变量必须严格，模型能力造成的合理错误可以保留并如实统计。

## 任务说明

你是一名多智能体 Runtime、LLM CodeAct、安全执行、结构化协议和实验评测工程师。请在当前 StateBus 仓库上继续完成 bounded adaptive runtime 的自然增强。

仓库路径：

```text
宿主机：/home/qcrs/statebus/project
容器内：/workspace/statebus/project
目标容器：statebus-dev-qcrs
```

本轮必须依次完成：

1. 阅读赛题要求、参考设计和当前代码；
2. review 当前实现，明确四个 Agent 实际拥有的决策权、CodeAct 是否确由 LLM 生成和执行、还有哪些不自然或过度限制；
3. 先给出详细、分阶段、可验证的实施计划；
4. 按计划继续修改代码，不要停在方案；
5. 在 Docker 容器中完成确定性回归、bwrap readiness 和必要的 live 验证；
6. 最终给出真实准确率、失败分类、Agent 自主性证据、CodeAct 证据和剩余风险。

## 一、先明确赛题到底要求什么

赛题原始要求见：

```text
docs/reference/题目.md
```

本项目要解决的核心不是普通工作流编排，而是多 Agent 协作基础设施：

- 至少三个 Agent 协同，当前系统为 Planner、Retriever、Executor、Summarizer 四角色；
- 使用结构化通信降低纯文本传递的 token、字符和控制面开销；
- 使用 embedding、语义状态或其他非文本中间状态，并证明它被下游实际消费；
- 建立可检索、可复用的共享记忆；
- 支持纯文本与结构化协议的公平对照；
- 覆盖多类任务和连续任务，并记录消息、token、状态传输、时延和记忆复用指标；
- 鼓励 CodeAct，即由 LLM 生成 Python，在轻量沙箱中安全执行并回传结果；
- 最终需要在 openEuler 24.03-LTS-SP3 路径上可运行和复现。

此前 StateBus 的协议、StateRef、非文本状态、共享记忆和 strict benchmark 已有基础。当前这轮改造专门补一个明显短板：四个 Agent 在旧路径中承担的真实语义工作太少，很多步骤由程序预先决定，LLM 更像在固定闭集里填字段或复核结果。

因此本轮提升的正确方向是：

```text
扩大“模型可以提出和决定什么”
保持“模型输出能直接造成什么副作用”严格受控
```

这不是放弃 schema、Policy、Grant、Artifact validator 或 sandbox，也不是把 Controller 改成 LLM。

## 二、参考文档的正确用法

开始前完整阅读：

```text
AGENTS.md
README.md
docs/constraints/current_host_and_migration.md
docs/constraints/current_feature_scope.md
docs/planning/implementation_plan.md
docs/reference/题目.md
docs/improvement/23_bounded_adaptive_agent_runtime_20260716/00_design_and_implementation_plan_zh.md
docs/improvement/23_bounded_adaptive_agent_runtime_20260716/01_implementation_prompt_zh.md
docs/improvement/24_adaptive_codeact_runtime_closure_20260717/00_detailed_optimization_and_implementation_plan_zh.md
```

三份 improvement 文档用于理解：

- 为什么要提升四角色自由度；
- Planner/Controller/Validator 的控制权边界；
- 为什么需要真实 Evidence -> Ref -> Executor -> Artifact -> Claim 因果链；
- 为什么 LLM CodeAct 必须进入正式 Runtime dispatcher；
- 测试、审计和实验应该证明什么。

它们不是当前代码完成度清单，也不是要求重新实现 P0-P8。文档写于不同时间，当前实现已经推进过多轮。文档与代码或最新产物不一致时，以当前代码和可复算 artifact 为准，并在 review 中说明差异。

## 三、当前已经实现到哪一步

不要从“CodeAct 尚未接入”的旧结论重新开始。当前代码已经具备以下能力，必须先核对源码和测试，再决定是否需要调整。

### 1. Adaptive Runtime 已经是真实路径

当前已有：

- `RuntimeDriver.run()` 保留 strict 默认语义；
- `RuntimeDriver.run_adaptive()` 执行获批 bounded DAG；
- `PlanProposal` 与 `ApprovedPlan` 分离；
- `PlanPolicyValidator` 校验 DAG、角色、capability、合同、预算和 Python 权限；
- Runtime ready queue、CapabilityGrant、ACK、step 状态和 telemetry；
- `AdaptiveCapabilityDispatcher` 按 execution kind 调度 Retriever、DSL、LLM Python 和 Summarizer；
- verified Evidence/Artifact/Claim 的 Ref 和 hash lineage；
- strict 与 adaptive 结果分开记录。

重点 review：不要只看到类和合同存在。必须追踪一次实际调用链，确认模型决定是否真实改变 approved plan、query、program/source、Artifact 和 Claim。

### 2. 四个 Agent 的决策面已经扩大

当前目标和已有实现应当是：

| 角色 | 模型应真实决定的内容 | Controller 保留的内容 |
| --- | --- | --- |
| Planner | 检索策略、DSL/Python 选择、一个或多个 Executor 阶段、语义目标、报告类型 | Ref 绑定、合法依赖、预算、Grant、capability 是否注册 |
| Retriever | 受限 query、table/semantic evidence 偏好、排序与补检索建议 | corpus、实体、时间范围、最大 query/扩展预算 |
| Executor | DSL 程序或完整 Python source、算法、字段处理、聚合/比较/异常分析 | 固定输入路径、输出 schema、AST policy、bwrap、质量验证 |
| Summarizer | Claim 组织、claim 文本、numeric fields 和合法引用 | 只允许 verified Evidence/Artifact，Claim validator 决定是否接受 |

当前 formal adaptive 路径已切换到通用 capability surface，关键 ID 包括：

```text
retrieve_semantic_evidence_v1
retrieve_table_evidence_v1
execute_analysis_dsl_v2
execute_bounded_python_v2
compose_claim_set_v2
compose_risk_memo_v1
```

`v2/benchmark/adaptive_formal.py` 当前应把 formal Executor capability 映射为通用 `execute_bounded_python_v2`。不要恢复旧的 `formal_lookup_metric_python_v1`、`formal_compute_trend_python_v1` 等按 benchmark operation 预注册的执行能力。

Controller 可以把模型的语义角色图编译成稳定 step ID、typed Ref 和合法依赖。这是控制面职责，不是作弊。但必须满足：

- 保留模型选择的 Retriever/Executor/Summarizer capability；
- 保留一个或多个 Executor 阶段及其顺序；
- 保留每个阶段的语义 goal；
- 不依据 case ID、expected facts 或隐藏答案改变计划；
- raw proposal、编译字段和 approved plan 都进入 trace；
- 编译器只修控制面 wiring，不修业务答案和算法。

### 3. LLM CodeAct 已经接入正式 Runtime

当前不是外挂固定脚本。正式目标调用链已存在：

```text
Planner 选择 execute_bounded_python_v2
  -> PlanPolicyValidator
  -> ApprovedPlan
  -> CapabilityGrant
  -> AdaptiveCapabilityDispatcher
  -> CodeGenerationRequest
  -> Executor local-vLLM 生成完整 Python source
  -> AST policy / bounded repair
  -> bwrap 非 root 执行
  -> schema/provenance/quality gate
  -> verified ExecutionArtifactRef
  -> Summarizer ClaimSet
```

近期通用改进包括：

- 多 Executor 输入支持：`inputs/task.json`、`inputs/upstream-1.json` 等固定路径；
- 输入 Ref 的显式顺序、schema 和 provenance 保留；
- bwrap 非零退出后允许一次模型生成的 runtime repair，并在新 workspace 重新执行全部 policy/sandbox/quality gate；
- CodeExecutionRecord 保存 runtime error、repair kind、diagnostic 和 hash；
- Planner 获得 source schema、required final schema 和用户授权 task parameters，但不获得 expected facts；
- Executor 获得每个 authorized input schema、输出 schema、task semantics 和固定路径；
- 中间 Executor 输出可以被下游 Executor 消费；
- numeric text policy 可以描述通用源格式，例如“leading token + bracketed range”，但不得传源值或答案；
- Prompt 和 policy 已允许内存字符串清洗 `str.replace(",", "")`；
- `Path.replace()`、rename、任意路径和文件系统副作用仍被禁止。

最后一项是必须保留的通用修复。此前 AST policy 只按方法名封禁 `.replace()`，把安全的字符串清洗和文件系统 rename 混为一谈。这是过度限制，不是模型错误。当前应按接收对象和副作用区分：

```text
str.replace(...)   -> 允许，用于内存数据清洗
Path.replace(...)  -> 拒绝，属于文件系统变更
```

不要重新引入“禁止所有 `.replace`”的规则，也不要为某一个 disease/aggregation case 写专用解析器。

## 四、当前可引用的真实测试证据

### 1. 五任务 live adaptive 预跑

产物：

```text
/home/qcrs/statebus/runs/adaptive_five_case_prerun_20260717_final/
  adaptive_mode_matrix_20260717_20260717_133619/summary.json
```

该产物真实证明：

- 五个 live task 全部通过；
- 五个不同 approved plan hash；
- 三种 capability 组合；
- comparison 使用 LLM Python；
- 两个 aggregation 任务使用 DSL；
- 两个 anomaly 任务使用 LLM Python；
- `verified_codeact_count = 3`；
- `codeact_execution_record_count = 3`；
- bwrap backend 正确，sandbox UID/GID 为 `65534/65534`；
- 模型 fallback、Runtime fallback、sandbox fallback 均为 0。

这说明 Agent 决策权和 LLM CodeAct 不是空壳，也不是只调用固定 Python 包装脚本。

### 2. 第一轮 25-case formal adaptive

产物：

```text
/home/qcrs/statebus/runs/adaptive_formal_compare_20260718_104008/
  adaptive_formal_compare_20260718_024017/summary.json
```

必须准确解读：

- 25 个 case 都被尝试；
- 18 个产生完整 case summary；
- 16 次 CodeAct verified；
- fallback 为 0；
- 但最终质量通过只有 `9/25`；
- 其余包含 Planner dependency cycle/unknown dependency、Summarizer dependency 输入错误和业务质量失败；
- 因此不能声称这一轮“大部分 case 正确”；
- 该运行还早于当前 generic capability 改造，selected capability 中仍有旧的 `formal_*_python_v1`，不能作为当前最终准确率。

它能证明的是：LLM source 确实大量进入 Runtime、bwrap 和 Artifact 路径。它不能证明当前 generic adaptive 实现已经达到高准确率。

### 3. Generic capability 定向运行

产物：

```text
/home/qcrs/statebus/runs/adaptive_formal_targeted_fix_20260718/
/home/qcrs/statebus/runs/adaptive_formal_targeted_fix2_20260718/
/home/qcrs/statebus/runs/adaptive_formal_targeted_fix3_20260718/
```

这些运行证明：

- Planner 已选择通用 `execute_bounded_python_v2`，不再依赖 operation-specific Python capability；
- 四任务定向运行中四个执行产物 verified，两个端到端质量通过；
- multi-Executor anomaly DAG 已真实执行过两个不同 LLM source，并消费上游 Artifact；
- 最后的 `formal-anomaly-001` 精确得到 `10149.43` 和 `5949.08`，bwrap UID/GID 为 `65534/65534`，无 fallback；
- 最后的 `formal-agg-002` 失败原因是旧 policy 错误拒绝安全的 `str.replace`，不是业务代码必然错误；该通用 policy 问题现已修复；
- policy 修复后尚未做新的 live formal rerun，不能把旧失败直接改写成通过。

### 4. 当前最近的确定性回归

容器内已完成：

```text
42 passed
```

覆盖：

```text
tests/v2/test_llm_codeact_policy.py
tests/v2/test_adaptive_codeact_integration.py
tests/v2/test_adaptive_formal_compare.py
```

该回归确认：

- 安全 `str.replace` 可通过；
- 直接 `Path(...).replace(...)` 被拒绝；
- Path 变量 `.replace(...)` 被拒绝；
- multi-input、runtime repair、adaptive CodeAct 和 formal compare 接线未回归；
- 没有为具体 case 增加规则。

还存在更早的 `tests/v2: 418 passed` 记录，但它早于最近若干通用修改。新的实现 Agent必须在相关修改完成后重新跑覆盖当前代码的回归，不能把旧 418 当作当前最终结果。

## 五、本轮真正要解决的问题

### 1. Review 自由度是否真实，而不是只看 Prompt

逐角色追踪至少一个 DSL task、一个单 Executor Python task 和一个 multi-Executor Python task：

- Planner raw proposal 选择了什么；
- Controller 只编译了哪些 wiring；
- approved plan 保留了哪些模型决定；
- Retriever query 是否由模型生成并改变 evidence；
- Executor program/source 是否由模型生成；
- source hash 是否进入 runtime session 和 Artifact lineage；
- Summarizer 是否生成 ClaimSet；
- 哪些 validator 最终接受或拒绝结果。

如果某个角色仍然只有唯一选择、模型结果不影响下游，或 Controller 预先计算了业务答案，必须指出并自然修复。

### 2. 清理残留的 benchmark 特化，而不是继续增加特化

重点搜索：

- case ID、sample 文件名、task family 特判；
- `formal_*_python_v1` 或 operation-specific Runtime capability；
- expected values、expected rows、expected facts 是否进入 Planner/Retriever/Executor/Summarizer Prompt；
- Controller 是否按 operation 选择算法或修改模型输出；
- validator 是否把 benchmark oracle 暴露给角色；
- task sample 是否为了模型输出被改写。

允许 benchmark 在 Runtime 完成后使用 expected facts 做外部评分。允许 Controller 提供用户请求本来就包含的 task parameters、源 schema、输出 schema 和非答案源格式 metadata。禁止把 oracle 或答案用于生成、repair、policy normalization 或 Runtime quality gate。

### 3. 自然处理 Planner 结构错误

Planner 输出 dependency cycle、未知 dependency 或把 schema 字段当 Ref ID，不应通过按 case 写 fallback plan 解决。

自然边界是：

- 模型决定语义角色、capability、Executor 阶段数量/顺序和 goal；
- Controller 绑定稳定 step IDs、verified source Ref、typed dependency outputs；
- 编译过程通用、确定性、可审计；
- 无法编译的角色图仍由 Policy 拒绝；
- 不根据 expected answer 修复计划；
- Planner schema/semantic repair 次数有界。

review 当前 controller compiler 是否满足该边界。若已经满足，不要为了把所有模型错误变成成功而继续扩张 compiler。

### 4. 只修通用能力问题

以下类型应该修：

- AST policy 错把无副作用操作当危险操作；
- 多个 verified upstream Artifact 被静默丢弃；
- Prompt 缺少输入 schema、输出 schema或用户原本给出的字段语义；
- runtime error 没有进入有界 repair；
- Ref 顺序、schema、provenance 丢失；
- generic parser/format contract 对一类常见数据表示不明确；
- Controller/角色合同不一致导致合法输出必然被拒绝；
- telemetry 无法证明模型决定是否生效。

以下类型通常不应继续修：

- 模型选错了统计方法，但 Prompt 和 task semantics 已清楚；
- 模型产生合理但数值不正确的代码；
- 模型一次生成了不合格 Plan，且 Policy 正确拒绝；
- Summarizer 在清晰合同下仍生成错误 claim；
- 个别 case 的舍入、字段选择或排序错误，除非暴露通用合同缺口。

模型错误可以保留为失败样本。不要为了 25/25 改任务、塞答案、扩大权限或添加 case-specific branch。

### 5. 调整评测口径，但不要吞掉错误

用户不要求 25/25。建议把门拆成两层：

1. 系统与安全门：必须 100% 满足；
2. 模型质量门：追求较高正确率，合理模型错误允许存在。

系统与安全门至少包括：

- bwrap readiness 通过；
- LLM code 实际 backend 为 bwrap；
- sandbox UID/GID 非 0；
- sandbox/resource/none fallback 为 0；
- expected facts 不可见于角色；
- 所有通过 case 的 Artifact 和 Claim 都 verified；
- 跨 task Ref、越权路径、未注册 validator 继续 fail-closed；
- strict 默认路径不回归。

模型质量应报告：

- 尝试 case 数；
- 完成 case 数；
- end-to-end quality pass 数和比例；
- Planner policy rejection；
- Retriever、Executor、Summarizer 各阶段失败；
- CodeAct generation/execution/verified/repair 数；
- DSL/Python 分布；
- 模型错误与基础设施错误分开。

如果需要修改 `run_adaptive_formal_compare.py` 的退出语义，保留原有“全对”严格字段作为额外证据，不要悄悄降低其含义。另增一个明确命名的 high-accuracy/development gate，并将阈值做成配置。默认可以先采用 `80%` 作为“较高正确率”开发门，但必须在计划中说明，报告实际分子/分母，不能只打印 PASS。

## 六、绝对禁止的“作弊式修复”

不得：

- 根据 task ID、case index、sample 文件名或 expected facts 分支；
- 为每种 benchmark operation 注册一个只会做该题的 Python capability；
- 在 Prompt 中提供 expected rows、expected values、完整答案代码或可直接复制的算法模板；
- 在 Controller 中重算答案后覆盖模型输出；
- 根据 oracle 自动 patch Python source、DSL program 或 ClaimSet；
- 修改 formal 样本问题、expected facts 或评分容差来迎合模型；
- 把失败 case 从分母删除；
- 用 deterministic fallback 冒充模型成功；
- 放宽 bwrap、路径、网络、Grant、Ref 或 validator 安全边界来提高通过率；
- 把旧 operation-specific 25-case 结果冒充为当前 generic 实现结果。

允许并鼓励：

- 通用 schema 和协议修复；
- 通用 planner wiring compiler；
- 通用数据格式 metadata；
- 通用 AST side-effect 分类；
- 有界、由 LLM 重新生成完整候选的 repair；
- 失败分类和可观察性增强；
- 改善不含答案的任务语义表达；
- 修复任何会让合法通用代码必然失败的 Runtime bug。

## 七、开始实施前必须先交付详细计划

读完代码、测试和现有 run artifact 后，先向用户输出详细计划。计划至少包含：

1. 当前实现审计结论；
2. 四个 Agent 当前真实决策权与仍被程序预决定的部分；
3. LLM CodeAct 从模型 source 到 bwrap Artifact 的实际调用链；
4. 残留特化或 oracle 泄漏检查结果；
5. 拟修改文件和每个修改的通用理由；
6. 明确不会修的模型 case 错误；
7. 测试层级、命令、预期门和停止条件；
8. 如何判定“高正确率”而非“全对”；
9. 风险、回滚与不允许扩大的权限。

计划给出后继续执行，不要等待用户再次说“开始”，除非：

- 需要更改用户数据或 expected facts；
- 需要重启/升级用户正在使用的 vLLM；
- 需要破坏性 git 操作；
- 需要明显扩大 sandbox 或网络权限；
- 当前 dirty worktree 与目标修改不可安全合并。

## 八、建议实施顺序

### P0：真实性与残留特化审计

- `git status --short`，保护全部用户改动；
- 从 generic formal adapter 追踪角色可见输入；
- 搜索 operation-specific capability、case ID、expected facts 泄漏；
- 核对 current source 是否仍保留 multi-input、runtime repair 和 safe `str.replace`；
- 核对旧 task sample 的本地修改，不要擅自回滚用户内容；
- 输出“保留/修改/不修改”清单。

### P1：Agent 决策权闭环

- 用确定性 stub 测试 Planner 选择 DSL、单 Python、多 Python 三种合法图；
- 确认 controller compiler 保留模型 capability/goal/stage count；
- 确认 Retriever query 进入 retrieval hash 和 evidence selection；
- 确认每个 Executor source/program hash 进入 Artifact lineage；
- 确认 Summarizer 只消费依赖输出和 verified evidence。

### P2：通用 CodeAct 可用性与安全边界

- 保留 `str.replace`/`Path.replace` 区分；
- 补充别名、Path 变量和嵌套表达式的通用 policy 测试，但不要扩大到任意动态类型推断；
- 核对一次 AST repair 和一次 runtime repair 的总预算是否清晰，禁止无限 repair；
- 确认 repaired code 在新 workspace 重跑 AST、bwrap、schema、quality；
- 确认多个 input Ref 全部读取且 provenance 顺序稳定。

### P3：错误分类与评测门

- 区分 model quality failure、policy rejection、sandbox/infrastructure failure 和 Runtime bug；
- 继续逐 case 保存 raw proposal、source、policy report、execution record、quality report 和 summary；
- 保留严格全对 gate；
- 如需要，新增可配置 high-accuracy gate；
- 系统/安全错误不得被质量阈值掩盖。

### P4：容器回归和 live 验证

- 先定向单测；
- 再 `tests/v2` 相关回归；
- 再 bwrap readiness；
- vLLM health 正常后做少量 generic live case；
- 只有通用修复验证完成后，才运行 fresh 25-case；
- fresh run 独立目录，不覆盖旧证据；
- 长测试期间保持静默，只在完成或报错时更新用户。

## 九、Docker、root、qcrs 与 bwrap 配置

### 1. 当前容器事实

2026-07-18 检查到：

```text
container: statebus-dev-qcrs
running: true
outer container user: 0:0
privileged: false
network: host
cap_add: SYS_ADMIN, NET_ADMIN
security_opt: seccomp=unconfined, apparmor=unconfined
```

这与 root+bwrap profile 一致。不要因为宿主用户是 qcrs，就把容器内 Runtime 改为 qcrs。当前 nested bwrap 需要外层容器 root 和 namespace/mount capability；真正的 LLM 代码必须在 bwrap 内降权为 UID/GID `65534/65534`。

边界是：

```text
宿主用户 qcrs 调用 Docker
  -> 外层 statebus-dev-qcrs 以 root 运行 Runtime/bwrap setup
  -> 内层 bwrap 以 65534:65534 执行 LLM Python
```

这不是 privileged container，也不能宣传成生产级 sandbox。

### 2. 每次 Python/pytest 前必须激活容器环境

标准命令：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q TEST_PATHS
'
```

不要在宿主机 conda 环境直接跑仓库 Python 测试。源码由 bind mount 共享，宿主机可以编辑、搜索和执行 git 只读检查。

### 3. 只有 profile 不匹配或 readiness 失败时才重建

先检查：

```bash
docker inspect --format \
  'running={{.State.Running}} user={{json .Config.User}} privileged={{.HostConfig.Privileged}} security_opt={{json .HostConfig.SecurityOpt}} cap_add={{json .HostConfig.CapAdd}}' \
  statebus-dev-qcrs
```

如果容器不是 root+bwrap profile，或用户确认可以重建，再执行：

```bash
cd /home/qcrs/statebus/project
docker compose \
  -f docker/compose.yaml \
  -f docker/compose.root.yaml \
  -f docker/compose.bwrap.yaml \
  up -d --force-recreate statebus-dev
```

不要无理由 rebuild，也不要停止或替换用户的 vLLM 服务。

### 4. bwrap readiness 必须做真实 probe

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py
'
```

必须检查：

- `actual_backend == bwrap`；
- `ready == true`；
- sandbox UID/GID 为非 0，当前预期 `65534/65534`；
- 无 resource/none fallback；
- 无网络；
- 输入只读、输出定点、工作区外不可写。

### 5. local vLLM 和 embedding

固定服务：

```text
STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1
STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b
STATEBUS_EMBEDDING_MODE=local
STATEBUS_EMBED_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B
```

先只读检查：

```bash
curl -fsS http://127.0.0.1:53334/health
curl -fsS http://127.0.0.1:53334/v1/models | jq
```

GPU wrapper 语义：

```text
STATEBUS_CUDA_VISIBLE_DEVICES=1  # 宿主物理 GPU 1
STATEBUS_EMBED_DEVICE=cuda:0     # 映射后容器内逻辑 GPU 0
```

不要把宿主物理 GPU 1 写成容器 `cuda:1`。不要擅自升级、重启或杀死 vLLM；health 不通过时继续确定性测试，把 live 标记为外部依赖未就绪。

## 十、建议测试命令

### 1. 最近改动的定向回归

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q \
    tests/v2/test_llm_codeact_policy.py \
    tests/v2/test_adaptive_codeact_integration.py \
    tests/v2/test_adaptive_formal_compare.py
'
```

当前基线是 `42 passed`。修改后不得低于该覆盖面。

### 2. 扩展 adaptive 回归

按实际改动选择：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q \
    tests/v2/test_adaptive_contracts.py \
    tests/v2/test_adaptive_planner_policy.py \
    tests/v2/test_adaptive_dispatcher.py \
    tests/v2/test_adaptive_driver.py \
    tests/v2/test_adaptive_retrieval.py \
    tests/v2/test_evidence_projection.py \
    tests/v2/test_capability_validators.py \
    tests/v2/test_transform_dsl.py \
    tests/v2/test_adaptive_claims.py \
    tests/v2/test_adaptive_role_prompts.py \
    tests/v2/test_llm_codeact_policy.py \
    tests/v2/test_llm_codeact_sandbox.py \
    tests/v2/test_adaptive_codeact_integration.py \
    tests/v2/test_adaptive_formal_compare.py
'
```

### 3. Fresh formal adaptive 验证

只有定向回归、bwrap 和小型 live 验证通过后再运行。使用新目录：

```bash
cd /home/qcrs/statebus/project
STATEBUS_CUDA_VISIBLE_DEVICES=1 \
STATEBUS_EMBED_DEVICE=cuda:0 \
STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1 \
STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b \
bash scripts/v2_diagnostics/run_adaptive_formal_compare_gpu1.sh
```

该命令测试的是当前 generic bounded adaptive + LLM CodeAct，不是旧 strict 5-case/25-case efficiency 实验。不要并发运行多个 local-vLLM formal job。

长测试启动后保持静默等待，只在以下情况更新：

- 全部完成并有 summary；
- 命令报错；
- 超时；
- vLLM、CUDA、bwrap 或容器状态发生真实异常。

## 十一、验收口径

### 必须全部通过的系统门

- strict 默认路径和相关回归未被破坏；
- adaptive 由 `RuntimeDriver.run_adaptive()` 和正式 dispatcher 执行；
- 每一步有 ApprovedPlan 和 CapabilityGrant；
- Ref task/session/attempt、schema、hash 和 provenance 校验有效；
- LLM CodeAct source 由真实 local-vLLM 生成；
- source 经过 AST policy、bwrap、schema 和 quality gate；
- bwrap 内 UID/GID 非 0；
- sandbox fallback 为 0；
- expected facts 不可见于角色；
- 通过 case 的 Artifact/Claim 全部 verified；
- 无 case-specific 代码和答案注入。

### 不要求全部通过的模型质量门

- 不要求 25/25；
- 目标是较高、可复现的 end-to-end quality pass rate；
- 个别 Planner、Retriever、Executor 或 Summarizer 模型错误可以接受；
- 错误必须保留在分母和 failure artifact 中；
- 不因某个模型错误自动修改 task、oracle、容差或 Runtime 业务逻辑；
- 如果实际正确率仍明显偏低，先判断是否存在通用合同/Runtime 问题；没有通用问题时如实报告模型上限，不继续 case chasing。

### 必须证明 Agent 自由度真的提升

最终至少给出三个具体实例：

1. Planner 在不同任务选择不同 approved plan/capability/DAG；
2. Executor 由 LLM 生成不同 source，至少一个 multi-stage/upstream Artifact 实例；
3. Retriever query 或 Summarizer ClaimSet 的模型决定真实进入下游 hash/Artifact/报告。

同时给出 CodeAct 证据：

- model ID；
- source hash；
- ApprovedPlan/Grant hash；
- sandbox backend 和 UID/GID；
- output/quality report/artifact hash；
- fallback/repair 次数；
- 外部 expected-facts 评分。

## 十二、最终交付

最终回复必须包含：

1. review 发现；
2. 实际修改文件；
3. 哪些修改扩大了 Agent 的通用决策权；
4. 哪些修改改善了 LLM CodeAct 的通用可用性；
5. 哪些错误被有意保留为模型错误，没有特化修复；
6. 容器、激活脚本、GPU、vLLM、bwrap、外层 root/内层 UID/GID 配置；
7. 所有测试命令与结果；
8. fresh live/formal run 的 result bundle；
9. end-to-end 正确率分子/分母和阶段失败分类；
10. 能宣称和不能宣称的结论。

不得只写“测试通过”或“CodeAct 已支持”。必须用 raw proposal -> approved plan -> Grant -> source/program -> bwrap -> quality report -> Artifact -> Claim 的真实证据说明提升。

任何未运行项明确写“未运行”。任何模型错误明确写“模型错误/质量失败”。任何基础设施或 Runtime bug不得伪装成模型误差。

