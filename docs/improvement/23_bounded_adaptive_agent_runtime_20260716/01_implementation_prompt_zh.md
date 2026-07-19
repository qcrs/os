# StateBus v2 受限自适应 Agent Runtime 第一、第二阶段实施 Prompt

> 用途：将本文从“任务说明”开始的全部内容交给编码 Agent。编码 Agent 必须在当前仓库真实代码上完成第一阶段和第二阶段实现与轻量验证，不得只输出分析或再次撰写方案。
>
> 设计基线：`docs/improvement/23_bounded_adaptive_agent_runtime_20260716/00_design_and_implementation_plan_zh.md`
>
> 环境决定：第一、第二阶段的 Python 命令、测试、诊断和 smoke 全部在已重建的 root+bwrap Docker 容器中运行；源码通过 bind mount 共享，可以在宿主机工作区编辑。宿主机还负责 Docker 编排、vLLM 服务和只读健康检查。生成代码本身必须在 bwrap 内降权，不能因为外层容器是 root 就以 root 执行 LLM 代码。

## 任务说明

你是一名多智能体 Runtime、LLM 结构化协议、CodeAct 和安全执行工程师。请在 `/workspace/statebus/project` 的当前 StateBus v2 实现上，严格依据：

```text
docs/improvement/23_bounded_adaptive_agent_runtime_20260716/00_design_and_implementation_plan_zh.md
```

完成：

1. 第一阶段：受限自适应四角色协作；
2. 第二阶段：正式 Runtime 中的受限 LLM Python CodeAct；
3. 单元测试、确定性集成测试和一至两个轻量 local-vLLM smoke；
4. 不运行正式大实验、连续十轮实验或长时间 benchmark，只在最终报告中给出后续运行命令。

这不是自由 Agent 框架改造。目标是增加 LLM 对计划、检索和执行配方的真实贡献，同时让 Driver、Supervisor、Policy Validator 和 Artifact Validator 保持最终控制权。

必须连续完成两个阶段：第一阶段完成后先执行第一阶段轻量门禁，门禁通过后继续实现第二阶段，不得把“第一阶段完成”当作本轮终点，也不得在两个阶段之间启动正式大实验。

## 一、开始前必须执行

### 1. 读取仓库约束和设计基线

先完整阅读：

```text
AGENTS.md
README.md
docs/constraints/current_host_and_migration.md
docs/constraints/current_feature_scope.md
docs/planning/implementation_plan.md
docs/reference/题目.md
docs/improvement/23_bounded_adaptive_agent_runtime_20260716/00_design_and_implementation_plan_zh.md
docs/reports/statebus_v2_agent_task_flow_zh.md
docs/reports/statebus_v2_agent_controlplane_codeact_architecture_zh.md
```

然后阅读设计文档第 10、11、12、14、16、19 章对应的当前源码和测试。文档与代码不一致时，以当前源码为准，但必须记录差异及处理理由。

### 2. 所有 Python 执行和测试必须使用 Docker

本轮目标容器固定为：

```text
statebus-dev-qcrs
```

禁止在宿主机直接执行仓库的 `python3`、`pytest`、diagnostic、smoke 或 benchmark。宿主机允许执行：

- 使用 `apply_patch` 或等价受控方式编辑 bind-mounted 源码和文档；
- `git`、静态文本搜索和只读文件检查；
- `docker compose`、`docker exec`、`docker inspect`；
- vLLM 启停和 `curl` 健康检查；
- 不调用仓库 Python 的普通 shell 检查。

从宿主机运行每一条 Python 测试或诊断时，使用以下形式：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  python3 -m pytest -q TEST_PATH
'
```

如果编码 Agent 本身已经运行在 `statebus-dev-qcrs` 容器内，可以直接执行容器内命令，但必须先用 `test -f /.dockerenv` 和 `hostname` 确认环境，并在最终测试记录中注明测试发生在该容器；不得因此转到宿主机 Python。

无论以 root 还是 qcrs 进入容器，执行任何 Python、pytest 或脚本之前都必须先运行：

```bash
source /workspace/statebus/project/docker/activate_statebus_container.sh
```

确认当前目录为：

```text
/workspace/statebus/project
```

### 3. 检查工作区，保护用户文件

先运行 `git status --short`。当前工作区可能包含用户尚未提交或尚未跟踪的文件。必须遵守：

- 不运行 `git reset --hard`、`git checkout --`、`git clean` 或其他破坏性命令；
- 不删除、不覆盖用户已有报告；
- 特别保护：
  - `docs/reports/statebus_v2_agent_task_flow_zh.md`
  - `docs/reports/statebus_v2_agent_controlplane_codeact_architecture_zh.md`
- 不 rebase、不 commit，除非用户另行明确要求；
- 遇到同文件已有改动时，先理解并保留，再做最小范围编辑。

### 4. 2026-07-16 已验证的容器基线

当前 root+bwrap 容器已由用户重建并完成轻量预检。可以作为本轮实现和测试基线的事实包括：

| 项目 | 已验证结果 |
| --- | --- |
| 容器 | `statebus-dev-qcrs`，外层用户 `uid=0(root)` |
| 系统 | openEuler 24.03 LTS-SP3 |
| Python | 3.11.6 |
| PyTorch | 2.5.1+cu121 |
| CUDA | PyTorch CUDA 12.1，`torch.cuda.is_available() == True` |
| GPU 可见性 | 容器当前可见 3 张 A100 80GB；embedding 固定使用容器 `cuda:0` |
| vLLM | Qwen3-32B 使用宿主机物理 GPU 2，URL 为 `http://127.0.0.1:53334/v1` |
| local embedding | 模型目录存在，`sentence_transformers` 可导入；实际编码仍须在 live smoke 中验证 |
| StateBus 目录 | LLM config 可读，embedding 模型目录存在，`/statebus/work` 可写 |
| shared memory | `/dev/shm` 为 1.0 GiB |
| bwrap probe | `bwrap_smoke.ok == true` |
| 现有 CodeAct smoke | `actual_backend == bwrap`、exit code 0、无 fallback |

这些结果只证明当前容器能够创建 bwrap namespace，并能运行仓库现有的确定性 CodeAct smoke。它们**不证明**第二阶段的安全目标已经完成。第二阶段仍必须新增并验证：

- LLM 代码在 bwrap 内的 UID/GID 非 0；
- LLM 路径不挂载整个 repo 和其他任务目录；
- 输入只读、输出定点可写、工作区外不可写；
- sandbox 内无网络且不接收 vLLM URL/API 环境；
- 正式 LLM CodeAct 在 bwrap 失败时不回退 `resource`/`none`；
- AST、输出 schema、质量验证和 ArtifactRef 签发全部通过。

## 二、不可改变的架构决定

### 1. 控制权

必须保持以下控制模型：

```text
LLM Planner 只提出 PlanProposal
        |
        v
PlanPolicyValidator 校验并生成 ApprovedPlan
        |
        v
Runtime Driver / Supervisor 签发 CapabilityGrant 并调度
        |
        v
Retriever / Executor / Summarizer 返回候选结果
        |
        v
程序 Verifier 决定结果是否成为已验证 Evidence / Artifact / Claim
```

禁止：

- Planner 直接调用其他角色；
- Planner 自己签发权限、注册工具、改变预算或终止策略；
- 任何角色把 LLM 输出直接当成已授权命令；
- 角色绕过 Driver/Supervisor 互相调用；
- Summarizer 修改已验证数值或把无证据内容变成事实。

### 2. strict 路径兼容

保留当前 `RuntimeDriver.run()` 和既有 strict benchmark 语义。新增自适应入口，例如 `run_adaptive()`，不得把历史固定路径原地改成动态路径。

支持并区分：

```text
strict_fixed
adaptive_shadow
adaptive_bounded
```

- 默认必须仍为 `strict_fixed`；
- `adaptive_shadow` 生成和验证计划，但不让计划改变实际执行；
- `adaptive_bounded` 才执行获批计划；
- 三种模式必须进入 runtime signature、审计和 telemetry；
- 新 adaptive 结果不得写入或冒充 2026-07-15 历史实验结果。

### 3. 两阶段边界

第一阶段：

- 允许 Planner 生成受限任务图；
- 允许 Retriever 提议多 query 和一次补检索；
- 允许 Executor 生成并运行 Transform DSL；
- 允许 Summarizer 生成带引用 ClaimSet；
- 只运行开发者注册的确定性 capability 和 DSL；
- 禁止执行 LLM 生成的 Python。

第二阶段：

- 增加 LLM Python 代码生成、提取、AST 校验、一次 repair、bwrap 执行和输出验收；
- 默认关闭；
- 仅对指定 domain pack/capability 启用；
- live LLM Python 只允许使用强制 bwrap 路径；
- bwrap 不 ready 时 fail-closed，不能回退到 `resource`、`none` 或普通宿主 subprocess。

## 三、现有代码事实和复用要求

实现前必须追踪并复用，而不是平行重造：

- `v2/runtime/smoke.py::run_smoke()`：当前四角色、检索和执行多发生在 Driver 之前；adaptive 要把真实调度移入 Runtime；
- `v2/runtime/driver.py`：保留 strict 入口，增加 adaptive ready-queue 调度；
- `v2/runtime/session.py::RuntimeWorkflowStep`、`RuntimeTaskSession`、`RuntimeReplanRecord`：承载步骤、依赖、状态和重规划记录；
- `v2/runtime/supervisor.py::RuntimeSupervisor`：保留 ACK、heartbeat、timeout、trap、cancel 生命周期；
- `v2/runtime/fallback.py::FallbackDag`：复用 retry、downgrade、skip 语义；
- `v2/runtime/role_path.py`：保留旧角色方法，新增 adaptive Prompt/解析入口；
- `v2/retrieval/pipeline.py`：扩展 multi-query 和稳定 fan-in，不另建一套证据系统；
- `v2/runtime/workspace.py`：复用 task/attempt workspace；
- `v2/refs/models.py::ExecutionArtifactRef`：执行结果继续使用独立 ArtifactRef，不与 StateRef 合并；
- `v2/runtime/codeact.py`、`v2/runtime/codeact_data_tasks.py`：保留确定性 CodeAct 作为 strict/失败回退；
- `v2/runtime/codeact_sandbox.py`：增强 readiness、fail-closed、挂载和降权，不复制新的散装 subprocess runner；
- `scripts/v2_diagnostics/bounded_llm_codeact_demo.py`：提取可复用的代码提取、AST policy 和 repair 逻辑到正式 Runtime；
- `scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py`：升级或复用为真实 namespace readiness 诊断。

## 四、第一阶段实施顺序

必须按 P1-A 至 P1-F 小步完成。每一步先完成合同和确定性单测，再接入下一步。不要一次性重写 `run_smoke()`、Driver 和四角色代码。

### P1-A：合同、Capability Registry 和 Domain Pack

实现设计文档第 5、6 章的合同，至少包括：

```text
WorkflowMode
AdaptiveTaskEnvelope
CapabilityDescriptor
PlanStepProposal
PlanProposal
ApprovedPlan
PlanPolicyReport
EvidenceRequest
EvidenceCoverageReport
TransformProgram / TransformStep
ClaimSet / Claim
StateConsumptionRecord
CapabilityGrant
```

要求：

- 使用仓库已有 dataclass/Protobuf/序列化风格；
- schema 带版本；
- 所有集合序列化顺序稳定；
- hash/digest 输入稳定；
- proposal 与 approved 对象必须分开，不能只靠一个 `approved: true` 字段；
- LLM 可见 capability 是紧凑的公开描述，不包含宿主命令、真实文件系统路径或实现对象；
- Controller 使用的执行 descriptor 不直接暴露给 LLM；
- capability ID、版本、输入 schema、输出 schema、权限、预算和 validator 必须可追踪；
- 先实现 `long_doc_analysis_v1` domain pack；
- 至少提供确定性能力：证据读取/检索、结构化筛选/聚合、引用报告；
- `intent_op` 可以作为兼容字段或 capability 内部实现细节，但不能继续承担全部任务类型和泛化边界。

至少增加：

- 合同 round-trip 测试；
- stable serialization/digest 测试；
- 非法 schema version 测试；
- 重复 step ID、未知 capability、非法依赖测试；
- registry public view 不泄漏执行细节测试。

完成 P1-A 后先运行对应新单测，不要立即运行完整套件。

### P1-B：Planner 提案、程序审批和 shadow 模式

为 Planner 增加独立 adaptive Prompt 构造和解析函数。Prompt 必须包含：

- 固定角色规则：只提出计划，不执行、不派工、不新增 capability；
- 动态任务：目标、允许输入 Ref 的摘要、输出要求；
- capability public view；
- 最多步骤数、最大依赖深度、补检索/重规划预算；
- 明确 JSON schema；
- 禁止输出 shell、Python、真实路径和未注册工具；
- completion criteria。

Planner 的原始输出只能成为 `PlanProposal`。实现 `PlanPolicyValidator`，按确定性顺序验证：

1. schema 和版本；
2. step ID 唯一性；
3. DAG 无环；
4. 依赖存在；
5. capability 已注册且属于当前 domain pack；
6. 输入来源只能是 task 输入或上游输出；
7. 输出类型能被下游消费；
8. 步骤数、深度、token、检索、重规划和执行预算；
9. 权限不超过任务 envelope；
10. completion criteria 能被程序检查。

实现一次格式 repair，但 repair 只修 JSON/schema，不允许偷偷扩大权限或替换未知 capability。repair 后仍失败则使用确定性 fallback plan，并记录原因。

接入 `adaptive_shadow`：

- 调用 Planner；
- 保存原始候选、解析结果、policy report 和 approved/fallback plan；
- 实际仍执行 strict 路径；
- 对比 proposed plan 与 fixed workflow，但不得改变 strict 输出；
- telemetry 区分 `proposal_valid`、`policy_rejected`、`repair_used`、`fallback_used`。

测试必须覆盖：循环 DAG、越权 capability、未知输入、超预算、伪造已验证 Ref、Prompt 注入和合法最小计划。

### P1-C：Retriever 请求、覆盖率校验和一次补检索

让 Retriever 在获批计划范围内生成 `EvidenceRequest`，而不是只从既有 `tc` 中选 route/tool。

Retriever Prompt 输入只应包括：

- 当前 approved step；
- task goal 和允许的数据源摘要；
- 可用 corpus/ref 的受控元数据；
- query 数量和长度预算；
- 所需 evidence type；
- 输出 schema。

Retriever 可以决定：

- 在预算内提出 query；
- query 优先级；
- 期望证据类型；
- 对已有候选重排。

Retriever 不可以：

- 新增数据源；
- 读任意文件；
- 联网；
- 伪造 locator、StateRef 或 EvidenceItem；
- 自己决定 coverage 已达标。

扩展 `RetrieverFanoutPipeline`：

- 支持多个获批 query；
- 复用已注册 adapter；
- fan-in 顺序稳定；
- 去重规则稳定；
- 每个 EvidenceItem 保留 source/ref/locator/provenance；
- 不把 LLM 声称的证据当成真实证据。

实现程序化 `EvidenceCoverageVerifier`。只允许 Controller 在 coverage 不足时批准一次补检索；用 query hash 去重，禁止无限循环。补检索前后 coverage、缺失类型、候选数量和决策必须进入 ledger/telemetry。

测试至少覆盖：合法 multi-query、重复 query、未知 corpus、伪造 locator、coverage 足够不重试、coverage 不足只重试一次、补检索仍不足后的确定性处理。

### P1-D：adaptive Driver 和 CapabilityGrant

新增 `RuntimeDriver.run_adaptive()`，将实际 adaptive 调度放入 Runtime，而不是继续在 `run_smoke()` 中预先算完再交给 Driver 记账。

要求：

- 输入是 `AdaptiveTaskEnvelope + ApprovedPlan + Registry snapshot`；
- Driver 建立 ready queue；
- 只有全部依赖已验证通过的 step 才能 ready；
- 每次 dispatch 前由 Controller 签发一次性 `CapabilityGrant`；
- grant 至少绑定 task/session/step/attempt/capability/version/input refs/budget/expiry 或等效字段；
- Agent 返回值必须绑定 grant，防止跨 step/attempt 重放；
- Supervisor 仍负责生命周期、timeout、cancel 和 trap；
- Validator 决定 step 是 completed、retryable failed 还是 terminal failed；
- ready queue、dispatch、ACK、状态转换和最终状态都写入 ledger；
- 最大重规划次数为 1；
- 重规划只能修改尚未执行的子图，不能改写已验证结果；
- 未授权步骤、过期 grant、输入 Ref 不匹配必须在产生副作用前拒绝。

保留 `RuntimeDriver.run()`。不要通过大量 `if adaptive` 污染每一个 strict 分支；优先共享小型纯函数、状态转换和 validator。

集成测试使用 deterministic role stub 和 capability stub，证明：

- 一个合法计划实际执行了不同于固定四步的 DAG；
- 依赖未满足的步骤不会 dispatch；
- 越权 proposal 不会产生 grant；
- grant 不可跨 attempt 使用；
- 一次局部 replan 后仅未执行子图改变；
- strict 路径结果保持原样。

### P1-E：Transform DSL 和 Executor

实现设计文档中的小型声明式 DSL，不要设计成通用编程语言。第一版只允许有限操作，例如：

```text
select
filter_eq / filter_contains
sort
limit
group_by
aggregate
derive_safe
join_by_key
anomaly_check
```

实际 op 名称可按代码风格调整，但必须满足：

- op allowlist；
- 无 shell；
- 无任意函数调用；
- 无 Python 表达式/eval；
- 无任意文件路径；
- 输入只能是 grant 中的 Ref；
- 输出只能写当前 attempt workspace 的固定位置；
- 行数、列数、步骤数、join 规模和输出大小有上限；
- 类型和空值行为确定；
- 结果序列化稳定；
- 结果经过 schema 和质量校验后才生成 verified `ExecutionArtifactRef`。

Executor Prompt 只生成 `TransformProgram` 候选。它看到 approved step、输入 schema/摘要、允许 op 和输出 schema；不能看到宿主工具实现、任意路径或 shell。

至少把一个长文档/结构化证据动作迁移到 DSL，并保留 legacy deterministic fallback。测试比较 DSL 与确定性预期结果，不能只断言“程序没报错”。

恶意测试包括：未知 op、路径穿越、超大 limit/join、类型错误、输出 schema 不匹配、试图嵌入 Python、试图引用未授权 Ref。

### P1-F：ClaimSet、StateConsumptionRecord 和三模式集成

Summarizer 输出 `ClaimSet` 候选，每个事实性 claim 必须引用：

- 一个或多个 EvidenceItem locator；或
- 一个 verified `ExecutionArtifactRef` 中的字段/记录。

程序验证：

- 引用存在；
- 引用属于当前 task/session；
- 数值与 artifact 一致；
- 不允许 Summarizer 改写数值；
- 证据不足时输出明确的 insufficient-evidence 状态，而不是补写事实。

实现 `StateConsumptionRecord`，至少记录：

- consumer role/step；
- StateRef 或 memory ref；
- 实际读取字段；
- 消费时间；
- 读取后改变的选择、排序、跳过、预算或 fallback 决定；
- 无影响时也要明确记录 `no_effect`，不能把“Ref 可读”写成“复用产生收益”。

完成三模式轻量集成：

```text
strict_fixed
adaptive_shadow
adaptive_bounded
```

并做 StateRef `off / normal / perturbed` 的小型确定性测试。第一阶段完成标准不是 token 一定下降，而是：

- adaptive proposal 真实通过 policy；
- 获批计划真实改变至少一个执行选择或 DAG；
- 变化和输入 Ref 均可审计；
- 关闭或扰动状态时，下游决定变化可解释；
- strict 基线不回归。

## 五、第二阶段：正式受限 LLM Python CodeAct

第二阶段必须建立在第一阶段的 ApprovedPlan、CapabilityGrant、workspace、ArtifactRef 和 validator 上。不能把诊断脚本直接当正式执行器。

### P2-A：正式合同和代码生成入口

新增或实现等价合同：

```text
CodeGenerationRequest
CodeGenerationPolicy
GeneratedCodeCandidate
CodePolicyReport
CodeExecutionRequest
CodeExecutionRecord
CodeRepairRecord
```

合同必须绑定：

- approved plan/step；
- capability grant；
- 输入 Ref 和已解析的只读输入清单；
- 固定工作区相对路径；
- 唯一输出路径；
- 输出 JSON schema；
- 允许模块；
- AST policy 版本；
- sandbox policy 版本；
- timeout/CPU/RAM/file/nproc 限额；
- model/prompt/runtime signature；
- attempt ID。

只对 registry 中显式标记为 `llm_bounded_python` 的 capability 开放。默认 execution mode 仍是 legacy/DSL。

### P2-B：Prompt、提取、AST policy 和一次 repair

从 `scripts/v2_diagnostics/bounded_llm_codeact_demo.py` 提取通用逻辑到正式 runtime 模块，并保留诊断脚本调用兼容或做最小适配。

代码生成 Prompt 必须明确：

- 模型是受限数据转换代码生成器，不是系统管理员；
- 输入文件是固定的 workspace 相对路径；
- 只能读取请求列出的输入；
- 只能写唯一固定输出 JSON；
- 输出必须符合给定 schema；
- 只能使用 allowlist 标准库/已批准库；
- 禁止网络、subprocess、动态安装、环境变量探测、目录扫描和工作区外访问；
- 返回一个代码块或严格 JSON 包装，不得夹杂执行命令。

代码提取必须处理 markdown fence，但不能通过宽松字符串清洗绕过 AST 校验。

AST policy 至少拒绝：

- `subprocess`、`socket`、网络库；
- `eval`、`exec`、`compile`；
- 动态 import；
- `os.system` 和进程创建；
- 未批准模块；
- 任意绝对路径和 `..` 路径构造；
- 读取环境变量、用户目录或系统信息；
- 非必要的反射/字节码/序列化执行；
- 直接打开未签发路径。

AST 通过不是安全证明，只是第一道门。格式或 policy 失败最多允许一次 repair；repair Prompt 只提供必要错误，不扩大原权限。repair 后仍失败，退回 DSL 或确定性实现，并记录 fallback；绝不把未通过 policy 的代码送入执行器。

### P2-C：root+bwrap 外层能力和内层降权

#### 1. 不接受“只用 root”

重建前的事实是：基础容器即使以 `0:0` 运行，若未增加 namespace capability，bwrap 仍会报：

```text
bwrap: Creating new namespace failed: Operation not permitted
```

原因是 root 用户身份与 Docker capability/安全策略是两层权限。当前容器已经使用以下 Compose 叠加完成重建，并已通过现有 bwrap smoke；除非容器配置改变或被重建为基础 profile，不需要重复重建：

```bash
cd /home/qcrs/statebus/project
docker compose \
  -f docker/compose.yaml \
  -f docker/compose.root.yaml \
  -f docker/compose.bwrap.yaml \
  up -d --force-recreate statebus-dev
```

然后：

```bash
docker exec -it -u 0 statebus-dev-qcrs bash
source /workspace/statebus/project/docker/activate_statebus_container.sh
```

每次开始第二阶段安全验收前仍须执行 `docker inspect` 和真实 readiness probe，不能只依据“之前通过过”。不得在不具备 bwrap capability 的基础 core 容器中伪造 live 成功结果。

#### 2. 外层 root，内层非 root

root 只用于创建 mount/user/pid/network namespace 和准备 attempt workspace。LLM 生成代码必须在 bwrap 内以配置的非 root UID/GID 运行。

实现时：

- 增加显式 sandbox UID/GID 配置，默认选择容器内 qcrs 对应的非 root UID/GID或专用 sandbox UID/GID；
- 每个 attempt 使用独立 workspace；
- Runtime 只给该 UID/GID 当前 attempt 目录的必要读写权限；
- 输入只读，固定输出目录可写；
- 执行结束后由 root Runtime 读取、验证并规范化 artifact；
- 不能为了修复权限问题让生成代码保留 root 身份；
- 不对整个 `/statebus/work`、`/statebus/runs` 或 repo 提供可写挂载。

#### 3. bwrap 挂载和环境

为 LLM Python 单独使用最小挂载策略：

- `--unshare-pid`、`--unshare-ipc`、`--unshare-uts`、`--unshare-net`；
- 独立 user namespace，并设置非 root UID/GID；
- `--die-with-parent` 和 `--new-session`；
- 最小 `/proc`、`/dev`、`/tmp`；
- Python runtime 和确需的库只读；
- 当前 attempt workspace 按输入只读/输出可写的最小方式挂载；
- 不把整个项目仓库挂入 LLM code sandbox；
- 不挂载模型、缓存、日志、其他任务 workspace、Docker socket、SSH 或宿主敏感路径；
- 从空环境开始，只设置最小的 locale、Python 路径和固定输入/输出变量；
- 不把 vLLM URL、API key、代理和宿主环境传给生成代码。

如果现有确定性 CodeAct 因导入项目模块仍需要 repo 只读挂载，应将“deterministic trusted”与“LLM untrusted”挂载策略分开，不能为了兼容前者扩大后者。

#### 4. readiness 必须执行真实 probe

不能再用 `shutil.which("bwrap")` 作为可用性结论。增加可缓存的最小 readiness probe，至少实际验证：

- user/mount/pid/network namespace 能创建；
- `/proc` 可挂载；
- sandbox 内 UID/GID 非 0；
- sandbox 无网络；
- attempt workspace 权限符合预期；
- 工作区外写入失败。

readiness 结果记录 bwrap 版本、policy version、失败阶段和原因，但不得记录敏感环境。

#### 5. fail-closed

为正式 LLM CodeAct 增加明确的 `require_bwrap=True` 或等价强类型策略：

- bwrap 未安装：不执行；
- readiness 失败：不执行；
- bwrap 启动失败：不执行；
- 实际 backend 不是 bwrap：结果无效；
- sandbox 超时/资源限制：失败或受控 fallback；
- 只允许 fallback 到 Transform DSL 或开发者确定性 capability；
- 禁止 fallback 到 `resource`、`none` 或宿主 Python；
- 现有 `auto -> resource` 可保留给历史确定性/诊断路径，但正式 LLM CodeAct 绝不能使用它。

`sandbox_backend`、readiness、fallback reason 和 policy digest 必须进入 execution record、ledger 和 telemetry。

#### 6. 开发 profile 的边界

现有 `docker/compose.bwrap.yaml` 使用较强容器 capability 和放宽的 security option。它可作为当前单容器开发/验收 profile，但不能宣称是完整生产隔离。

实现完成后应静态审查 `NET_ADMIN`、`seccomp=unconfined`、`apparmor=unconfined` 是否都为当前宿主所必需。只有通过单项移除后的 bwrap readiness 和恶意用例，才能缩减；不要凭猜测删除导致 profile 不可用，也不要把这些权限加入基础 `docker/compose.yaml`。

生产化后续方向是独立 sandbox worker/service：主 Runtime 保持非 root、无额外 capability，只将签发后的最小 CodeExecutionRequest 交给隔离 worker。本轮不要求拆服务，但新合同和 runner 不应阻碍后续拆分。

### P2-D：执行、输出验收和 ArtifactRef

执行前依次检查：

```text
ApprovedPlan
-> CapabilityGrant
-> CodeGenerationPolicy
-> AST policy
-> bwrap readiness
-> workspace manifest
```

执行后依次检查：

```text
exit code / timeout / resource status
-> 唯一输出文件存在
-> 无额外未授权输出
-> JSON 可解析
-> schema 合法
-> 数据质量/数值/行数检查
-> provenance 与 execution record 完整
-> verified ExecutionArtifactRef
```

进程退出码为 0 不代表成功。只有所有输出 validator 通过才能生成 verified ArtifactRef，下游 Summarizer 只能看到 verified artifact 的受控摘要、字段和引用。

执行记录至少包含：

- 原始生成响应的安全摘要/hash；
- 提取后代码 hash；
- AST policy version/report；
- repair/fallback；
- sandbox requested/actual backend；
- readiness digest；
- UID/GID policy；
- mount policy digest；
- 输入 Ref；
- 输出文件 hash/schema；
- exit/timeout/resource 数据；
- validator report；
- 最终 ArtifactRef。

### P2-E：缓存边界

只缓存“已通过 policy、bwrap 执行和输出验证”的结果。cache key 至少包含：

```text
task/capability semantic input digest
input content digests
generated source digest
model/prompt signature
AST policy version
sandbox policy version
runtime/dependency signature
output schema version
```

缓存命中也必须重新检查 task/session 授权和 ArtifactRef 可读性。不得因相同自然语言直接复用旧代码结果，不得跨不兼容 policy/runtime 重放。

## 六、测试要求

### 1. 测试原则

- 所有仓库 Python 测试、诊断和 smoke 必须在 `statebus-dev-qcrs` Docker 容器中运行；
- 每次从宿主机发起测试都使用 `docker exec -u 0 ... bash -lc`，并在同一 shell 内先 source 容器激活脚本；
- 禁止使用宿主机 Python 代跑“方便测试”，即使宿主机依赖看起来相同；
- 每个小步骤先跑直接相关测试；
- 使用 fake/stub LLM 覆盖绝大多数合同、解析、调度和失败测试；
- 不为了让测试通过而削弱 validator、沙箱或 strict 语义；
- 不把当前 bwrap probe 成功解释成第二阶段安全策略已经实现；
- 不要求每个单测真实加载 embedding 模型或调用 vLLM；
- live 测试单独标记，默认测试套件可离线运行；
- 最后才运行一至两个小型 live local-vLLM smoke。

### 2. 第一阶段最小测试矩阵

至少覆盖：

| 范围 | 必测内容 |
| --- | --- |
| contracts | round-trip、stable digest、schema version、非法字段 |
| registry | public/private view、未知 capability、版本和权限 |
| planner | 合法计划、循环、超预算、越权、一次 repair、fallback |
| retriever | multi-query、稳定 fan-in、去重、coverage、一次补检索 |
| driver | ready queue、依赖、grant、timeout、局部 replan、终止 |
| DSL | 正确结果、未知 op、路径、类型、规模、schema、未授权 Ref |
| summarizer | 引用存在、数值一致、证据不足、伪造引用 |
| state/memory | consumed/no_effect、off/normal/perturbed |
| modes | strict_fixed、adaptive_shadow、adaptive_bounded |

### 3. 第一阶段完成后的轻量门禁

完成 P1-A 至 P1-F 后，不要立刻运行完整 benchmark，也不要立即进入第二阶段的 live LLM Python。先按以下顺序执行一个小门禁。

#### 门禁 1：第一阶段精确单测

在 Docker 中运行第一阶段新增测试。开发过程中先按新增测试文件逐个运行，失败时就地修复，不要用全套测试掩盖问题；全部单文件通过后可使用以下命令做第一阶段汇总复核：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q \
    tests/v2/test_adaptive_contracts.py \
    tests/v2/test_adaptive_planner_policy.py \
    tests/v2/test_adaptive_retrieval.py \
    tests/v2/test_adaptive_driver.py \
    tests/v2/test_transform_dsl.py \
    tests/v2/test_adaptive_claims.py
'
```

文件名可按最终代码布局调整，但覆盖范围不能减少。

#### 门禁 2：小型确定性 adaptive smoke

新增或复用一个 `tests/v2/test_adaptive_smoke.py` 等价测试，使用仓库本地小样本和 fake/stub LLM，禁止访问 vLLM。任务保持简单，例如：

```text
从一个小型财报/运营指标样本中找出本期收入和上期收入，计算变化，并给出来源引用。
```

该 smoke 只需要：

- 2 至 4 个获批步骤；
- 最多一次补检索；
- 一个小型 TransformProgram；
- 一个 verified ExecutionArtifactRef；
- 一个所有事实均有 locator/artifact 引用的 ClaimSet；
- 分别运行 `strict_fixed`、`adaptive_shadow`、`adaptive_bounded`；
- 证明 shadow 不改变 strict 结果；
- 证明 bounded 至少有一个真实获批决定不同于 fixed workflow；
- 全程不加载大模型、不跑长文档、不跑连续任务。

从宿主机执行：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q tests/v2/test_adaptive_smoke.py
'
```

#### 门禁 3：小型 strict 回归

只跑最直接的既有回归，先确认新增入口没有改变当前固定路径：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q \
    tests/v2/test_role_contract_audit.py \
    tests/v2/test_smoke.py
'
```

#### 门禁 4：最多一个第一阶段 live smoke

前三个门禁通过后，检查 vLLM health，再用同一个小任务做一次 local-vLLM + local-embedding smoke。优先复用已有最小运行入口；若现有入口无法单独运行 adaptive 小任务，可以新增 `scripts/v2_diagnostics/run_adaptive_agent_smoke.py`，但不得在脚本中复制 Runtime 逻辑。

该 live smoke 必须：

- 在 Docker 中运行；
- 使用 `http://127.0.0.1:53334/v1` 和 `qwen3-32b`；
- embedding 使用 `/statebus/models/Qwen3-Embedding-0.6B`、`cuda:0`；
- 只运行一个小任务；
- 输出 Planner proposal、policy report、approved plan、角色调用次数、ArtifactRef 和 ClaimSet 的审计摘要；
- 不报告性能收益，不运行十轮，不运行 formal benchmark。

示例执行形式如下，实际参数以最终脚本为准：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  export STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1
  export STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b
  export STATEBUS_EMBEDDING_MODE=local
  export STATEBUS_EMBED_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B
  export STATEBUS_EMBED_DEVICE=cuda:0
  python3 scripts/v2_diagnostics/run_adaptive_agent_smoke.py
'
```

若 vLLM health 不可用，记录 live smoke 未运行，但不能用 deterministic stub 冒充 live 结果。第一阶段前三个确定性门禁通过后继续第二阶段实现；本轮不能在第一阶段结束。

### 4. 第二阶段最小测试矩阵

至少覆盖：

| 范围 | 必测内容 |
| --- | --- |
| extraction | fenced code、严格包装、混杂文本、空代码 |
| AST policy | import、subprocess、socket、eval/exec、路径、反射 |
| repair | 只修一次、权限不扩大、二次失败走安全 fallback |
| readiness | missing bwrap、namespace denied、UID 仍为 0、成功 probe |
| fail-closed | 正式 LLM 路径绝不落到 resource/none |
| mounts | repo/其他 workspace 不可读写、输入只读、输出定点可写 |
| network | sandbox 内连接失败 |
| resources | timeout、CPU、内存、文件大小、进程数 |
| output | 缺失、额外文件、非法 JSON、schema 错、质量错 |
| artifact | 仅完整验证后签发、记录可追踪、跨 attempt 拒绝 |
| cache | signature 命中、policy/runtime 变化失效、未验证结果不缓存 |

### 5. 两阶段日常测试节奏

按实际新增文件选择精确命令，例如：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q tests/v2/test_adaptive_contracts.py
  python3 -m pytest -q tests/v2/test_adaptive_planner_policy.py
  python3 -m pytest -q tests/v2/test_adaptive_retrieval.py
  python3 -m pytest -q tests/v2/test_adaptive_driver.py
  python3 -m pytest -q tests/v2/test_transform_dsl.py
  python3 -m pytest -q tests/v2/test_adaptive_claims.py
  python3 -m pytest -q tests/v2/test_llm_codeact_policy.py
  python3 -m pytest -q tests/v2/test_llm_codeact_sandbox.py
'
```

文件名可按仓库习惯调整。完成一个阶段后运行相关既有回归：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q \
    tests/v2/test_role_contract_audit.py \
    tests/v2/test_runtime_and_benchmark.py \
    tests/v2/test_smoke.py \
    tests/v2/test_bounded_llm_codeact_demo.py \
    tests/v2/test_subprocess_executor.py
'
```

最后在时间合理时运行：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 -m pytest -q tests/v2
'
```

若完整 `tests/v2` 明显耗时，可停止在已覆盖改动面的测试，并在最终报告明确未运行项，不要擅自开始长实验。

### 6. bwrap 验收

在 root+bwrap profile 容器中先运行：

```bash
docker exec -u 0 statebus-dev-qcrs bash -lc '
  set -euo pipefail
  source /workspace/statebus/project/docker/activate_statebus_container.sh
  cd /workspace/statebus/project
  python3 scripts/v2_diagnostics/check_codeact_bwrap_sandbox.py
'
```

只有真实 probe 成功后才运行 LLM CodeAct live smoke。必须检查：

- `actual_backend == bwrap`；
- sandbox 内 UID 非 0；
- 无 fallback reason；
- 无工作区外副作用；
- 输出通过 validator；
- ArtifactRef 可追踪。

## 七、local embedding 与 vLLM 固定配置

### 1. embedding 必须是 local

容器内使用：

```bash
export STATEBUS_EMBEDDING_MODE=local
export STATEBUS_EMBED_MODEL_PATH=/statebus/models/Qwen3-Embedding-0.6B
export STATEBUS_EMBED_DEVICE=cuda:0
```

不得把 hash embedding 或远程 embedding 的结果当作本轮 local embedding 验收结果。普通单元测试可使用确定性 stub，但 live smoke 必须记录上述 local 配置。

### 2. vLLM 固定 URL 和模型

本轮 local-vLLM：

```text
base URL: http://127.0.0.1:53334/v1
health:   http://127.0.0.1:53334/health
metrics:  http://127.0.0.1:53334/metrics
model:    qwen3-32b
GPU:      宿主机物理 GPU 2
```

由用户在宿主机单独终端启动；编码 Agent 不得擅自杀死或替换已有模型服务：

```bash
cd /home/qcrs/statebus/project
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b
export CUDA_VISIBLE_DEVICES=2
export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES=2
export STATEBUS_VLLM_HOST=127.0.0.1
export STATEBUS_VLLM_PORT=53334
export STATEBUS_VLLM_GPU_MEMORY_UTILIZATION=0.82
export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE=1
unset STATEBUS_VLLM_NUM_GPU_BLOCKS_OVERRIDE
bash scripts/start_vllm_qwen3_32b_prefix_cache.sh
```

启动后检查：

```bash
curl -fsS http://127.0.0.1:53334/health
curl -fsS http://127.0.0.1:53334/v1/models | jq
```

如果 health 不通过，跳过 live LLM smoke 并报告外部依赖未就绪；不要修改测试来伪造成功。

容器使用 host network，所以容器内仍使用 `127.0.0.1:53334`。在容器内导出：

```bash
export STATEBUS_LOCAL_VLLM_BASE_URL=http://127.0.0.1:53334/v1
export STATEBUS_LOCAL_VLLM_MODEL=qwen3-32b
export STATEBUS_LLM_CONFIG_FILE=/workspace/statebus/project/deploy/statebus_llm.yaml.local
```

不要改成容器名 URL，不要在 Prompt 或生成代码 sandbox 中传入该 URL。只有 Runtime 的 LLM client 可以访问 vLLM；LLM 生成的 Python 在 `--unshare-net` 中运行。

## 八、允许的轻量 live 验证

所有 deterministic 测试通过后，最多做一至两个小任务：

1. 一个长文档证据任务：Planner 生成 2 至 4 步计划，Retriever 产生受限 query，Executor 使用 DSL，Summarizer 生成带引用 ClaimSet；
2. 一个小型 JSON/CSV 任务：在明确获批 capability 下生成受限 Python，经 AST+bwrap+schema validator 产生 ArtifactRef。

限制：

- 单任务；
- 小输入；
- 不连续十轮；
- 不跑 formal benchmark 全量；
- 不并发启动多个 API 实验；
- 不声称延迟、token 或复用收益，除非另有匹配实验；
- 输出放入新的 2026-07-16 之后的开发验证目录，与历史结果隔离。

## 九、验收标准

### 第一阶段

- strict 默认行为和既有测试不回归；
- shadow 计划不改变 strict 结果；
- bounded 模式至少执行一个非固定四步的获批 DAG；
- Planner proposal 未审批前不能 dispatch；
- 每次 dispatch 都有可验证 CapabilityGrant；
- Retriever coverage 由程序计算，最多补检索一次；
- Executor DSL 产生的 ArtifactRef 通过内容验证；
- Summarizer factual claim 均有证据/artifact 引用；
- StateRef/memory 的实际消费和影响有记录；
- 越权、循环、伪造 Ref 和超预算输入在副作用前被拒绝。

### 第二阶段

- 正式 LLM code path 默认关闭且只对注册 capability 开放；
- 代码必须通过提取、AST policy 和 bwrap readiness；
- LLM 代码实际以 sandbox 内非 root UID/GID 运行；
- 网络隔离；
- 不挂载整个 repo 或其他任务 workspace；
- bwrap 失败时 fail-closed；
- 正式 LLM 路径的 `resource`/`none` fallback 次数为 0；
- 所有恶意测试均未产生工作区外副作用；
- 只有输出 schema 和质量验证通过才创建 verified ArtifactRef；
- repair、fallback、sandbox、policy 和 artifact 均可审计。

## 十、工作方式和最终交付

保持持续实施，不要在输出计划后停止。遇到问题按以下优先级处理：

1. 先读真实代码和测试；
2. 做最小兼容改动；
3. 写失败测试；
4. 修复实现；
5. 跑局部测试；
6. 再进入下一步。

不要：

- 为追求“自治”移除 Controller 校验；
- 把结构化 schema 当作无意义限制；
- 用 Prompt 禁令代替程序 policy；
- 用 AST policy 代替 sandbox；
- 用 sandbox 代替输出 validator；
- 将 `ExecutionArtifactRef` 合并为 StateRef；
- 将 memory 命中等同于真实节省；
- 修改历史实验报告来匹配新实现；
- 在用户未授权时提交代码。

最终回复必须报告：

1. 实际修改文件；
2. 第一阶段每个子阶段的完成状态；
3. 第二阶段每个子阶段的完成状态；
4. 控制权和安全边界如何落到代码；
5. 所有测试命令及结果；
6. local-vLLM/embedding/bwrap live smoke 的真实配置和结果；
7. 未运行的正式大实验；
8. 仍存在的风险、未实现项和后续大实验命令。

任何未完成项必须明确写“未完成”，不得用“支持”“可用”或“已验证”模糊代替。
