# StateBus Benchmark Boundary、Dataset Generalization 与 Contract Refactor 深度设计

> 项目：`qcrs/os`（当前主展示仓库，`master`）  
> 历史参考：`qcrs/os1`  
> 日期：2026-09-02  
> 定位：Benchmark Boundary / Dataset Generalization / Contract Audit / External Evaluation Integration Baseline  
> 状态：设计分析稿；用于后续 B0/R0 级重构，不表示本文目标 contract 已实现。

## 0. 文档目标

本文承接前一份 Routing Architecture 深度审计，专门解决 StateBus 当前数据集、Benchmark 输入边界、外部有效性与 contract 泛化问题，并把设计进一步下沉到代码字段级。

本文回答：

1. 当前 `os/master` 到底有没有 benchmark leakage？
2. 当前 controlled 45 cases / E5 25 cases 分别能证明什么，不能证明什么？
3. 如何接 TeamBench / IDA-Bench / LongMemEval-V2 / AIDABench，而不重新制造 `task_family -> tool -> solution` hard-code？
4. `MinimalBenchmarkSample / CanonicalTaskSpec / AdaptiveTaskEnvelope / AdaptiveMainlineRequest / AdaptiveDispatchContext / MemoryQuery / MemoryCommit` 七个核心 contract 如何迁移？
5. 这部分如何与前一份 `PlanSelector / BindingResolver` Routing 设计合并？

核心原则：

```text
Controlled Benchmark Contract
    用于机制 A/B、确定性 oracle、稳定 correctness gate

External Public Task Contract
    只描述 benchmark 真正公开给被测系统的任务与资产

AdaptiveTaskEnvelope
    只描述 Runtime Authority

Private Evaluation Contract
    Gold / hidden tests / grader / reference impl
    永远位于 StateBus Runtime 边界之外
```

目标架构：

```text
Benchmark Harness
  ├─ Public View ──> ExternalBenchmarkAdapter
  │                    ├─ ExternalTaskEnvelope
  │                    ├─ InputAssetRef[]
  │                    └─ Visibility Manifest
  │                             │
  │                             ▼
  │                         StateBus
  │                             │
  │                      RouteContextBuilder
  │                             │
  │                         PlanSelector
  │                             │
  │                    AdaptiveTaskEnvelope
  │                             │
  │                          Planner
  │                             │
  │                     PlanPolicyValidator
  │                             │
  │                       Approved Plan
  │                             │
  │                      BindingResolver
  │                             │
  │                     CapabilityGrant
  │                             │
  │                         Dispatcher
  │                             │
  │                        ResultBundle
  │                             │
  └─ Private Evaluator <────────┘
       Gold / hidden tests / grader
```


## 1. 当前三类 Evaluation Lane

当前 StateBus 不应该再被描述成“一个 benchmark path”。

### 1.1 Controlled Mechanism Lane

典型入口：

```text
statebus/benchmark/minimal_runner.py
run_minimal_benchmark()
run_smoke()
```

服务：

```text
L0 pure text
L1 typed control
L2 semantic pruning/state
L3 replay/full stack
```

以及通信、Embedding、Memory、Logit、APC、KV 等机制 A/B。

这类实验需要：

```text
same task
same data
same model
same quality floor
```

所以固定输入、固定 gold、固定 workflow 本身没有问题。

### 1.2 Controlled Formal Adaptive Lane

当前 E5 主线：

```text
MinimalBenchmarkSample
 -> CanonicalTaskSpec
 -> adapt_formal_sample()
 -> FormalAdaptiveCase
 -> generic_adaptive_analysis_v2
 -> Planner
 -> PlanPolicy
 -> DSL / CodeAct
 -> deterministic runtime validation
 -> expected_facts_report()
```

当前 generic capability closure 已经收敛为：

```text
retrieve_semantic_evidence_v1
retrieve_table_evidence_v1
execute_analysis_dsl_v2
execute_bounded_python_v2
compose_claim_set_v2
compose_risk_memo_v1
```

所以“Runtime 仍然一个 benchmark operation 对应一个 capability”已经不是当前主事实。

### 1.3 External Benchmark Lane

当前尚未形成正式统一 contract。

本文建议新建，而不是继续扩 `TaskCompiler` enum。


## 2. 当前是否存在 Gold Leakage

结论：

**没有发现 `expected_facts` / Gold value 直接进入 Planner、Retriever、Executor prompt 的路径。**

当前 sample 中：

```json
"expected_facts": {
  "trend_direction": "increasing"
}
```

属于 evaluator Gold。

它在 Runtime 完成之后才由 `expected_facts_report()` 使用。当前 formal telemetry 也显式记录 `benchmark_oracle_visible_to_roles=False`。

因此当前 E5 不能被简单评价为“把答案喂给模型”。

但这不代表 evaluation boundary 已经充分 generic。

真正存在的是另外四类 scaffolding：

1. **Semantic / solution scaffolding**
2. **Input preprocessing scaffolding**
3. **Role topology scaffolding**
4. **Reference validator inside runtime**

这些不会直接暴露答案，却会明显降低 task understanding / algorithm selection / workflow selection 难度。


## 3. Semantic / Solution Scaffolding

当前 `adapt_formal_sample()` 会根据：

```text
task_family
intent_op
arguments
```

生成：

```text
operation
source_schema
output_schema
operation_semantics
expected_output_shape
```

`_operation_for_spec()` 是 closed operation registry，例如：

```text
compute_delta
compute_trend
groupby_aggregate
detect_outliers
materialize_clean_table
...
```

未知 operation 会直接 `formal_adaptive_operation_unsupported`。

所以当前 E5 更准确地是：

```text
Generic Capability Runtime
        ↑
Closed Formal Semantic Adapter
```

而不是：

```text
Unknown External Task
        ↓
Generic Runtime
```

### 3.1 什么是合法 public semantics

如果用户原始 request 明确写：

```text
use 1.5 IQR
return JSON
preserve all rows
```

这些属于 Public Declared Constraint。

### 3.2 什么是 Adapter Semantic Derivation

如果 Adapter 进一步自动给出：

```text
inclusive quartile position = (n - 1) * p
linear interpolation
Q1 = .25
Q3 = .75
```

或者自动决定：

```text
this is detect_outlier
use CodeAct
final schema must be fields X/Y/Z
```

就属于 Adapter Semantic Derivation。

它不是 Gold，但 External lane 不应该把它送给 Runtime。


## 4. Input Preprocessing Scaffolding

当前 formal adapter 会用类似：

```text
_csv_source_rows()
_financial_source_rows()
_cross_period_source_rows()
_holdout_source_rows()
```

把原始数据提前转换成：

```python
tuple[dict[str, object], ...]
```

随后写成 controller-owned `source_rows.json` 并包装成 verified `ExecutionArtifactRef`。

对 controlled benchmark 这是合理的；对 external generalization 则有明显问题。

如果 IDA-Bench 原本给：

```text
CSV
XLSX
multiple files
messy schema
```

而 Adapter 提前：

```text
parse
normalize
type-clean
schema-discover
convert to rows
```

那么 StateBus 实际只证明了：

```text
clean normalized rows -> analysis
```

而不是：

```text
raw external asset -> inspect -> choose provider -> solve
```

因此 External lane 必须引入 `InputAssetRef`，原始资产与 Runtime 派生的 `ExecutionArtifactRef` 分开。


## 5. Role Topology Scaffolding

当前 adaptive formal 构造：

```python
role_cardinality={
    "retriever": (1, 1),
    "executor": (1, 2),
    "summarizer": (1, 1),
}
```

Planner prompt 也显式得到 required roles。

`PlanPolicyValidator` 正确地根据 envelope 检查 role cardinality，因此：

```text
Retriever=0
Summarizer=0
```

在当前 E5 formal lane 不合法。

这意味着：

**当前 E5 不能用于验证前一份 Routing 设计中的 Role / Workflow Routing。**

问题不在 `PlanPolicyValidator`，而在：

```text
谁生成 AdaptiveTaskEnvelope
```

未来应改为：

```text
ExternalTaskEnvelope
 -> RouteContextBuilder
 -> PlanSelector / Admission Policy
 -> AdaptiveTaskEnvelope.role_cardinality
 -> PlanPolicyValidator
```

Role cardinality 仍然保留作为 authority gate。


## 6. Reference Validator Inside Runtime

当前 formal quality validator 不读取 `expected_facts`，但会：

```text
recompute_formal_rows(operation, arguments, authorized_input_rows)
```

重新计算 reference output，再与 Executor 结果比对。

这是很强的 controlled correctness design，但意味着 Runtime 拥有当前 formal task 的 reference implementation。

同时 mismatch 后 repair 还能使用 task-specific `operation_semantics`。

因此 `25/25` 的最准确表述应是：

> 在 registered controlled task contracts 下，StateBus adaptive DSL/CodeAct execution 在 deterministic runtime validation 与 bounded repair 条件下完成 25/25。

而不是：

> 对未知数据分析任务 blind success 25/25。

External lane 中，Runtime validator 应只验证 generic invariant：

```text
artifact exists
hash valid
parseable
public schema satisfied
required public fields present
finite values
provenance valid
sandbox/path authorization valid
Grant valid
```

真正 task correctness 交给 benchmark native grader。


## 7. 问题严重度

| Claim | 当前 scaffolding 影响 |
|---|---:|
| typed communication token/bytes | 很低 |
| Embedding actual cross-PID consume | 很低 |
| Memory controlled reuse | 很低 |
| Prefix/KV real compute reuse | 很低 |
| DSL/CodeAct registered-contract capability | 中 |
| Plan/Role/Provider Router generalization | 高 |
| general adaptive runtime claim | 高 |
| direct Gold leakage | 当前未发现 |

总体：

```text
不是 correctness failure
不是全部 benchmark 无效
不是需要推翻 Runtime

而是：

Controlled harness 很强
External validity 不足
Boundary contract 需要正式拆分
```


## 8. Visibility Taxonomy

建议正式定义：

```text
PUBLIC_RAW
PUBLIC_DECLARED_CONSTRAINT
PUBLIC_MECHANICAL_DERIVATION
ADAPTER_SEMANTIC_DERIVATION
PRIVATE_GOLD
PRIVATE_GRADER
AUDIT_ONLY
```

### PUBLIC_RAW

被 benchmark 原生提供给被测系统：

```text
user message
spec / brief
dataset files
workspace
tool documentation
conversation history
```

### PUBLIC_DECLARED_CONSTRAINT

用户显式要求：

```text
output JSON
use IQR=1.5
must edit repository
network forbidden
```

### PUBLIC_MECHANICAL_DERIVATION

不涉及 task semantics 的确定性 derivation：

```text
file size
SHA256
MIME
CSV header
directory listing
Git commit identity
```

### ADAPTER_SEMANTIC_DERIVATION

例如：

```text
intent_op=detect_outliers
正确公式
应该调用 CodeAct
应该先 Retriever 再 Executor
自动构造 solution-specific output schema
```

External Runtime 不可见。

### PRIVATE_GOLD

```text
answer
expected_facts
label
target output
```

### PRIVATE_GRADER

```text
hidden tests
grade.sh internals
reference implementation
evaluator configuration
judge prompt
```

### AUDIT_ONLY

```text
benchmark name
case id
category
difficulty
split
leaderboard tag
```

不能进入 Router / Planner / Binder / MemoryQuery feature。


## 9. External Visibility Hard Gate

External Runtime 可消费：

```text
PUBLIC_RAW
∪ PUBLIC_DECLARED_CONSTRAINT
∪ PUBLIC_MECHANICAL_DERIVATION
```

禁止：

```text
ADAPTER_SEMANTIC_DERIVATION
PRIVATE_GOLD
PRIVATE_GRADER
AUDIT_ONLY
```

进入：

```text
RouteContext
Planner prompt
BindingContext
retrieval request
CodeAct prompt
MemoryQuery
```

正式 external run 只要 private/adaptor-semantic/audit-only 信息进入这些 consumer，应直接标记 run invalid，而不是 warning。


## 10. 新 Contract：InputAssetRef

```python
@dataclass(frozen=True)
class InputAssetRef:
    asset_id: str
    asset_kind: AssetKind
    media_type: str
    locator: str
    access_mode: AssetAccessMode
    content_digest: str
    size_bytes: int
    role_visibility: tuple[str, ...]
    declared_schema_ref: str = ""
    provenance: dict[str, object] = field(default_factory=dict)
    schema_version: str = "statebus.input_asset_ref.v1"
```

推荐 AssetKind：

```text
FILE
DIRECTORY
REPOSITORY
DATABASE
API_ENDPOINT
CONVERSATION
```

不要注册：

```text
financial_csv
ida_dataset
weather_dataset
```

### InputAssetRef 与 ExecutionArtifactRef

```text
weather.csv
    = InputAssetRef

profile.json
cleaned.csv
analysis.json
    = Runtime-produced ExecutionArtifactRef
```

这是 Dataset Generalization 的关键边界。

`declared_schema_ref` 只能代表 benchmark/user 原本公开的 schema；Runtime 自己 inspect 得到的 schema 应作为新的 Runtime Artifact。


## 11. 新 Contract：ExternalTaskEnvelope

它描述“任务是什么”，不描述“Runtime 被允许做什么”。

```python
@dataclass(frozen=True)
class ExternalTaskEnvelope:
    task_id: str  # opaque runtime id
    natural_goal: str
    input_asset_refs: tuple[str, ...]
    conversation_ref_ids: tuple[str, ...] = ()
    public_constraints: PublicTaskConstraints = ...
    public_context_hash: str = ""
    visibility_manifest_hash: str = ""
    schema_version: str = "statebus.external_task_envelope.v1"
```

不要放：

```text
benchmark_name
benchmark_category
difficulty
intent_op
adapter-required-tools
gold
```

这些要么是 AUDIT_ONLY，要么是 PRIVATE。

PublicTaskConstraints 仅包括：

```text
output_format
required_artifact_kinds
explicitly_required_fields
explicit_tool_constraints
public_policy_refs
user_budget
```

`explicit_tool_constraints` 只有用户/benchmark 原始 task 真正公开要求 tool 时才有值。


## 12. 新 Contract：TaskContractIdentity

当前 `canonical_task_spec_hash` 已渗透 Runtime 与 Memory，因此不能粗暴删除 CanonicalTaskSpec。

建议增加：

```python
@dataclass(frozen=True)
class TaskContractIdentity:
    contract_kind: str
    contract_hash: str
    legacy_canonical_task_spec_hash: str = ""
    public_context_hash: str = ""
    schema_version: str = "statebus.task_contract_identity.v1"
```

contract_kind：

```text
controlled_canonical_v1
external_public_v1
interactive_public_v1
```

Controlled bridge：

```text
CanonicalTaskSpec.spec_hash
 -> TaskContractIdentity(
      kind=controlled_canonical_v1,
      contract_hash=spec_hash,
      legacy_canonical_task_spec_hash=spec_hash
    )
```

External：

```text
ExternalTaskEnvelope.public_context_hash
 -> TaskContractIdentity(
      kind=external_public_v1,
      contract_hash=public_context_hash
    )
```


## 13. 新 Contract：BenchmarkVisibilityAudit

建议：

```python
@dataclass(frozen=True)
class BenchmarkVisibilityRecord:
    field_path: str
    visibility_class: VisibilityClass
    producer: str
    consumers: tuple[str, ...]
    value_hash: str
    derivation_source_hashes: tuple[str, ...] = ()
```

```python
@dataclass(frozen=True)
class BenchmarkVisibilityAudit:
    run_id: str
    runtime_task_id: str
    records: tuple[BenchmarkVisibilityRecord, ...]
    private_to_runtime_count: int
    private_to_role_count: int
    adapter_semantic_to_runtime_count: int
    audit_metadata_to_router_count: int
    native_evaluator_outside_runtime: bool
    schema_version: str = "statebus.benchmark_visibility_audit.v1"
```

注意 Audit 只存 hash/classification，不复制 Gold 内容，避免 audit 文件本身成为泄露载体。


## 14. ExternalBenchmarkAdapter

推荐 Runtime-facing API：

```python
class ExternalBenchmarkAdapter(Protocol):
    def prepare_public_task(...) -> ExternalTaskEnvelope:
        ...

    def materialize_public_assets(...) -> tuple[InputAssetRef, ...]:
        ...

    def submit_result(
        runtime_task_id: str,
        result: ResultBundle,
    ) -> BenchmarkSubmissionHandle:
        ...
```

不向 Runtime 暴露：

```text
gold()
hidden_tests()
reference_solution()
evaluate_private()
```

native benchmark evaluator 位于 StateBus Runtime 边界之外。

如果 benchmark 的 public/private 文件在同一目录，正式实验最好把 StateBus 放进只挂载 public staging 的子进程/容器，而不是只靠“代码约定不读取”。


## 15. 与 Routing Architecture 的会合点

目标完整链：

```text
ExternalTaskEnvelope
      ↓
Visibility Gate
      ↓
RouteContextBuilder
      ↓
PlanSelector
      ↓
AdaptiveTaskEnvelope
      ↓
Planner
      ↓
PlanPolicyValidator
      ↓
Approved Logical Plan
      ↓
BindingResolver
      ↓
CapabilityGrant
      ↓
Dispatcher
```

RouteContext 可以看：

```text
natural goal
asset media types
asset sizes
public schema
Runtime-inspected schema artifact
public output constraints
available logical capabilities
resource/risk state
```

禁止看：

```text
benchmark origin
category
difficulty
expected facts
manual intent_op
manual required_tools
adapter reference formula
```

正确 Router 是 capability/contract-driven，而不是 benchmark-label-driven。


# 16. 外部 Benchmark 深度调研

## 16.1 TeamBench — P0

官方资料（2026）：

```text
851 templates
931 seeded instances
19 categories
5 ablation conditions
```

Planner / Executor / Verifier 通过 OS/Docker enforce role separation：

```text
Planner:
  full spec read
  no workspace write

Executor:
  workspace write
  no full spec

Verifier:
  spec + read-only workspace
  no modification
```

每个 task 有 deterministic grader。

官方仓库已提供 `TeamBenchFrameworkAdapter`：

```python
run_team(task_dir, run_dir, roles)
run_single(task_dir, run_dir, role_config)
```

返回 `FrameworkResult`，最后由 harness 自己调用 grader。

这非常适合 StateBus 作为 external MAS framework 接入，而不是手工转换成 CanonicalTaskSpec。

### 推荐接法

```text
TeamBench Harness
 -> StateBusTeamBenchAdapter
 -> sanitized role/public inputs
 -> StateBus
 -> FrameworkResult
 -> TeamBench native grade.sh
```

### 推荐 subset

开发：少量 smoke，不作为 headline。

正式项目 subset：从官方 TeamBench-90 预注册完整 category，例如：

```text
Data Engineering
Incident Response
Information Retrieval
```

对应当前官方 90-task list 中约 14 个 task。selection policy 必须在看结果前冻结。

如资源允许，再上 full TeamBench-90。

### 当前注意点

官方 README 当前说明 TeamBench-90 中 `GH120_redis-py_3863` 正在 re-curation，因此正式结果必须固定：

```text
benchmark commit
task-list hash
selection manifest
```


## 16.2 IDA-Bench — P0

IDA-Bench：

```text
25 publicly sourced Kaggle notebook tasks
interactive multi-round analysis
平均约 8.36 instructions/task
```

领域覆盖 manufacturing、business、psychology、weather 等。

官方 README 明确支持：

```text
Implement the AgentClass Protocol
```

接自定义 agent。

因此最佳接法：

```text
IDA Harness
 -> StateBusAgentClass
 -> StateBus
```

而不是：

```text
IDA case
 -> manual intent_op
 -> manual required_tools
 -> CanonicalTaskSpec
```

### 为什么非常适合 BindingResolver

简单任务：

```text
filter + group + aggregate
```

DSL 与 Python 都 feasible，Binder 选成本更低者。

复杂任务：

```text
custom parsing
pivot
imputation
multi-stage statistics
```

DSL infeasible，CodeAct feasible。

### 数量建议

```text
Dev: 5
Formal: 25 全跑
```

因为 benchmark 总量本身只有 25，正式只挑 5 个容易被质疑 selection bias。


## 16.3 LongMemEval-V2 — P1

官方 2026 benchmark：

```text
451 manually curated questions
5 memory abilities
up to 500 trajectories
up to 115M tokens
web + enterprise
small + medium public tiers
```

Memory interface：

```python
insert(trajectory)
query(query, query_image=None)
```

query backend 不接收：

```text
question id
question type
raw question record
gold answer
evaluator configuration
```

仓库还提供 `tests/test_query_privacy.py`，显式构造 secret ID / answer / evaluator 并断言 backend 只获得 opaque query invocation ID。

这应成为 StateBus `BenchmarkVisibilityAudit` 测试模式的直接参考。

### 推荐接法

实现：

```text
StateBusMemoryBackend
```

直接接官方 harness。

不要把 LongMemEval question 转成 CanonicalTaskSpec。

初期跑官方 Small tier，稳定后上 Medium。


## 16.4 AIDABench — P2

AIDABench 2026：

```text
600+ end-to-end data analytics tasks
QA
Visualization
File Generation
```

输入覆盖：

```text
spreadsheets
databases
financial reports
operational records
```

官方 protocol 是 task instruction + associated files + sandboxed arbitrary Python。

论文报告 best pass@1 约 59.43%。

它非常适合后续压力测试：

```text
InputAssetRef
multi-file
heterogeneous formats
artifact generation
```

但当前不宜作为第一 external benchmark，因为会同时引入文件、DB、visualization、LLM evaluator 等多个变量。


## 16.5 ToolSandbox — P2

ToolSandbox 重点：

```text
stateful tool execution
implicit state dependencies
on-policy conversation
intermediate/final milestone evaluation
```

适合后续 Capability Routing / state dependency / tool sequencing。

但 adapter 复杂度高于 TeamBench/IDA，暂不作为主线。


## 16.6 BFCL V4 — P3

BFCL V4 已从传统 function calling 扩展到：

```text
Agentic Web Search
Memory
Multi-turn
Live/non-live function calling
Hallucination
Latency
```

当前公开 Agentic 部分包含：

```text
Web Search 200
Memory 465
```

适合作为 tool/capability routing microbenchmark，但不替代 TeamBench 的 role-separated MAS 或 IDA 的 artifact-heavy data analysis。


## 16.7 OrchBench — Research Reference

OrchBench 2026 将 orchestration plan 与 worker execution 分离，用 deterministic simulator 测：

```text
quality
makespan
token cost
```

论文报告 simulator score 与 Claude Code execution quality Pearson `r=0.816`，并显著减少 token/wall time。

它非常适合借鉴：

```text
PlanSelector evaluation
workflow oracle
Router Regret
```

但太新，不建议让项目 external credibility 依赖它。


## 17. 推荐 External Suite

```text
                    StateBus
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
    TeamBench       IDA-Bench    LongMemEval-V2
        │              │              │
        ▼              ▼              ▼
 Plan / Role       Execution        Memory
 Routing            Binding         Reuse
```

扩展：

```text
AIDABench
ToolSandbox
BFCL
```

Internal 45 cases 不删除，重新定位为 Controlled Mechanism Evidence。


# 18. Before → After Contract Audit

下面进入七个核心 dataclass 字段级重构。

原则：

```text
Controlled contract 不强行泛化
External contract 新建
Runtime identity/authority 逐步桥接
Memory 最后迁移
```


## 18.1 `MinimalBenchmarkSample`

### Before

```python
task_id
request_text
canonical_task_spec
expected_artifact_type
task_family
expected_facts
scenario_tags
```

### 字段决策

| 字段 | 分类 | After |
|---|---|---|
| `task_id` | controlled/audit | Controlled 保留 |
| `request_text` | PUBLIC | 保留 |
| `canonical_task_spec` | controlled semantic contract | Controlled 保留 |
| `expected_artifact_type` | controlled output contract | 保留 |
| `task_family` | benchmark metadata | Controlled 保留；External Router 禁止 |
| `expected_facts` | PRIVATE_GOLD | evaluator only |
| `scenario_tags` | AUDIT_ONLY | External Router 禁止 |

### After

**不做 in-place universalization。**

新增：

```text
ExternalTaskEnvelope
BenchmarkVisibilityAudit
InputAssetRef
```

`MinimalBenchmarkSample` 正式标记：

```text
evaluation_lane=controlled
```

### Compatibility

`from_path()` / `load_sample_family()` / current smoke runners 保持行为不变。

### touched functions

```text
statebus/benchmark/minimal_runner.py
  _canonical_task_spec_from_payload
  MinimalBenchmarkSample.from_path
  load_sample_family
  run_minimal_benchmark
  run_minimal_benchmark_family

adaptive_formal loaders
task registry
```


## 18.2 `CanonicalTaskSpec`

### Before

```python
task_family
intent_op
target_entities
time_scope
required_outputs
required_tools
arguments
schema_version
```

### 字段决策

| Before | Controlled | External |
|---|---|---|
| `task_family` | 保留 | 不用于 route |
| `intent_op` | 保留 | Adapter 不预标 |
| `target_entities` | 保留 | public-derived 可用 |
| `time_scope` | 保留 | public-derived 可用 |
| `required_outputs` | 保留 | 仅显式 public requirement |
| `required_tools` | 保留 | External 默认禁止推导 |
| `arguments` | 保留 | 必须 visibility split |
| `schema_version` | 保留 | legacy |

### After

不删除。

正式定位：

```text
ControlledTaskContractV1 / Legacy Contract
```

新增：

```text
TaskContractIdentity
ExternalTaskEnvelope
```

### Compatibility Bridge

```text
CanonicalTaskSpec.spec_hash
 -> TaskContractIdentity(controlled_canonical_v1)
```

### touched functions

```text
statebus/contracts/models.py
statebus/runtime/compiler.py
  compile
  _canonical_from_mapping
  _validate_precompiled_spec
  _heuristic_compile

statebus/benchmark/minimal_runner.py
statebus/benchmark/adaptive_formal.py
statebus/runtime/adaptive_mainline.py
statebus/runtime/adaptive_dispatcher.py
statebus/memory/models.py
statebus/memory/store.py
```


## 18.3 `AdaptiveTaskEnvelope`

### Before

```text
task_id
canonical_task_spec_hash
workflow_mode
domain_pack_id
allowed_capability_ids
allowed_output_contracts
allowed_memory_policies
role_cardinality
budgets
risk_class
allow_llm_python
policy_version
```

### After

| Before | After | 说明 |
|---|---|---|
| `task_id` | same | External 使用 opaque task ID |
| `canonical_task_spec_hash` | `task_contract_hash` | 泛化 identity |
| — | `task_contract_kind` | 新增 |
| `workflow_mode` | same | 保留 |
| `domain_pack_id` | same | authority pack；禁止由 benchmark label 直接 route |
| `allowed_capability_ids` | same / 后续 logical IDs | 先保留 |
| `allowed_output_contracts` | same | 保留 |
| `allowed_memory_policies` | same | 保留 |
| `role_cardinality` | same | 保留，改由 PlanSelector/Admission 生成 |
| — | `allowed_input_asset_ids` | 新增 |
| — | `visibility_manifest_hash` | 新增 audit linkage |
| budgets/risk | same | 保留 |

### 为什么 role_cardinality 不删除

它是 Policy authority，而不是硬编码本身。

真正要改：

```text
Formal Adapter 固定写 1/1/1
```

### Compatibility

过渡期同时支持：

```text
canonical_task_spec_hash
task_contract_hash
```

若新字段为空则 fallback legacy。

### touched functions

```text
statebus/contracts/adaptive.py
PlanPolicyValidator
formal envelope construction
RolePath planner payload
AdaptiveRuntimeRequest validation
AdaptiveMainline manifest/hash
tests
```


## 18.4 `AdaptiveMainlineRequest`

### Before 核心

```text
trace_id
task_id
canonical_task_spec_hash
canonical_task_spec
envelope
registry
runtime/workspace root
propose_plan
bindings
available_input_refs
normalize/repair/fallback
memory config
input lineage/schema/validator digest
```

### After 新增

```python
task_contract_identity: TaskContractIdentity

external_task_envelope: ExternalTaskEnvelope | None

available_input_assets: dict[str, InputAssetRef]

visibility_audit: BenchmarkVisibilityAudit | None
```

保留：

```text
available_input_refs
```

因为 raw external asset 与 Runtime verified artifact 是两个层。

### Legacy

```text
canonical_task_spec
canonical_task_spec_hash
```

继续 Controlled compatibility，External 不填。

### touched functions

```text
AdaptiveMainlineRunner.run
task identity validation
input lineage
schema digest
AdaptiveDispatchContext assembly
AdaptiveRuntimeRequest assembly
manifest persistence
_commit_verified_memory
all formal/external callers
```


## 18.5 `AdaptiveDispatchContext`

### Before 核心

```text
registry
validator_registry
artifacts/evidence
retrieval factories
transform factories
code factories
codeact_contracts
quality_semantics_by_capability
output_schema_by_capability/by_step
state/memory/workspace
canonical_task_spec
input lineage
schema/validator/runtime digests
```

### 风险字段

External lane 最需要控制：

```text
codeact_contracts
quality_semantics_by_capability
output_schema_by_capability
output_schema_by_step
```

当前 formal lane 会通过这些字段把 `operation_semantics` 传给 DSL/CodeAct。

### After

新增：

```text
task_contract_identity
external_task_envelope
asset_registry
visibility_policy
public_constraint_context
```

Generic external path 逐步不依赖 `canonical_task_spec`。

### 强约束

Context 中不得出现：

```text
benchmark name/category/difficulty
gold
reference formula
grader path
hidden tests
```

### touched functions

```text
AdaptiveMainlineRunner.run
AdaptiveCapabilityDispatcher
  _dispatch_retrieval
  _dispatch_transform_dsl
  _dispatch_llm_python
memory query construction
quality validators
claim generation
formal bindings
```


## 18.6 `MemoryQuery`

### Before

```python
query_task_id
query_spec_hash
query_text
tags
query_embedding
limit
allowed_memory_types
allow_assist
allow_validated_replay
allow_exact_replay
compatibility_signature
output_contract_version
canonical_task_spec
input_lineage_hashes
input_schema_digest
validator_digest
```

### 当前 coupling

`MemoryIndexStore._compatibility_decision()` 当前会用：

```text
exact canonical spec hash
task_family
intent_op
required_outputs
```

判断 compatibility。

这对 controlled chain 有效，但 external benchmark 不具备这些 canonical labels。

### After

推荐：

```python
query_task_id
task_contract_identity

query_text
public_tags
query_embedding

allowed_memory_types
replay permissions

compatibility_signature
output_contract_version

input_lineage_hashes
input_schema_digest
validator_digest

task_compatibility_fingerprint
```

### `task_compatibility_fingerprint`

只能由 public/runtime facts 形成：

```text
logical capability family
input media/schema fingerprint
output contract
validator version
runtime signature
```

禁止：

```text
benchmark category
intent_op label
gold
```

### Exact vs Assist

EXACT_REPLAY：

```text
exact task contract
+ input lineage
+ output contract
+ validator digest
+ runtime signature
```

ASSIST：

允许更宽松 semantic retrieval。

### touched functions

```text
statebus/memory/models.py
statebus/memory/store.py
  lookup
  lookup_hybrid
  _compatibility_decision
AdaptiveCapabilityDispatcher memory query construction
memory persistence/reload tests
```


## 18.7 `MemoryCommit`

### Before

```python
memory_ref
canonical_task_spec
required_outputs
quality_floor_pass
created_from_artifact_hash
```

### 问题

当前 `AdaptiveMainlineRunner._commit_verified_memory()` 明确：

```text
canonical_task_spec is None
 -> canonical_task_spec_not_supplied
 -> no memory commit
```

所以 external path 不生成 CanonicalTaskSpec 时，Memory 直接失效。

### After

推荐：

```python
memory_ref

task_contract_identity
task_compatibility_fingerprint

output_contract_version
public_output_requirements_hash

input_lineage_hashes
validator_digest
runtime_compatibility_signature

quality_floor_pass
created_from_artifact_hash
```

Controlled legacy 可以继续保留 `required_outputs` / canonical spec payload。

### 关键规则

External native benchmark grade：

```text
PASS / FAIL
```

属于 private evaluator signal。

不能反向写入 StateBus MemoryCommit，再被下一个 benchmark case 使用。

External memory commit 只能依据：

```text
generic runtime validation
public contract
```

### touched functions

```text
statebus/memory/models.py
statebus/memory/store.py
AdaptiveMainlineRunner._commit_verified_memory
MemoryRef construction
replay tests
continuous task tests
```


## 19. 七个 Contract 的优先级

| Contract | Priority | 第一阶段 |
|---|---:|---:|
| MinimalBenchmarkSample | P3 | 只标 controlled lane |
| CanonicalTaskSpec | P2 | bridge，不重写 |
| AdaptiveTaskEnvelope | P0 | identity / asset authority |
| AdaptiveMainlineRequest | P0 | external public inputs |
| AdaptiveDispatchContext | P0 | visibility / assets |
| MemoryQuery | P1 | LongMemEval 前 |
| MemoryCommit | P1/P2 | Memory genericization 阶段 |

这避免“一次重写整个 Runtime”。


# 20. Routing 与 Benchmark Refactor 的联合迁移

Routing 计划：

```text
R0 Logical Capability / Provider contract split
R1 DSL/Python BindingResolver
R2 PlanSelector
R3 Routing receipts/telemetry
```

Benchmark 计划：

```text
B0 Visibility inventory
B1 Boundary contracts
B2 Controlled lane classification
B3 AssetRegistry
B4 TaskContractIdentity bridge
B5 External Router integration
B6 TeamBench
B7 IDA-Bench
B8 Memory genericization / LongMemEval
```

推荐交错：

```text
B0
 ↓
B1
 ↓
R0
 ↓
B3
 ↓
R1
 ↓
R2 + B4/B5
 ↓
B6 TeamBench
 ↓
B7 IDA
 ↓
B8 LongMemEval
```


## 21. B0 — Visibility Inventory

目标：

**不改变当前任何 benchmark execution behavior。**

只新增：

```text
EvaluationLane
VisibilityClass
Controlled visibility inventory
benchmark_visibility_report.json
```

例如：

```json
{
  "evaluation_lane": "controlled_formal",
  "public": ["request_text"],
  "public_mechanical": ["source file hash", "source schema"],
  "adapter_semantic": ["operation", "output_schema", "operation_semantics"],
  "private": ["expected_facts", "quality_checks"],
  "private_visible_to_roles": false,
  "controlled_reference_validator_enabled": true
}
```


## 22. B1 — Boundary Contracts

新增建议：

```text
statebus/contracts/benchmark_boundary.py
statebus/contracts/input_asset.py
statebus/benchmark/visibility.py
tests/benchmark_boundary/
```

实现：

```text
VisibilityClass
InputAssetRef
ExternalTaskEnvelope
PublicTaskConstraints
TaskContractIdentity
BenchmarkVisibilityRecord
BenchmarkVisibilityAudit
```

只要求：

```text
validation
canonical_payload
hash
round-trip
privacy/visibility tests
```

不接外部 benchmark。


## 23. B2 — Controlled Formal 正式分类

当前 adaptive formal manifest 增加：

```text
evaluation_lane=controlled_formal

gold_visible_to_runtime=false

adapter_semantic_scaffolding=enabled

reference_validator=enabled
```

这一步不要求去掉 operation semantics。

目的不是“洗白”，而是准确声明实验类型。


## 24. B3 — AssetRegistry

新增：

```text
AssetRegistry
```

只负责：

```text
register InputAssetRef
verify digest
enforce access mode
enforce role visibility
materialize authorized path
```

不要第一版就加入 PDF/XLSX/DB parser。

Parser/Inspector 是 capability/provider，不是 Asset Registry。


## 25. B4 — TaskContractIdentity Bridge

逐步将：

```text
canonical_task_spec_hash
```

泛化成：

```text
task_contract_hash
```

先改：

```text
AdaptiveTaskEnvelope
AdaptiveMainlineRequest
AdaptiveRuntimeRequest
manifest
```

Memory 暂时 legacy。

必须保持 controlled tests。


## 26. B5 — External + Router

此时才接：

```text
ExternalTaskEnvelope
 -> Visibility Gate
 -> RouteContextBuilder
 -> PlanSelector
 -> AdaptiveTaskEnvelope
 -> Planner
 -> PlanPolicy
 -> BindingResolver
```

role cardinality、capability availability 来自 public context + authority policy，而不是 benchmark label。


## 27. B6 — TeamBench Slice

第一版建议：

```text
memory off
logit off
explicit KV off
```

先验证：

```text
official harness
role isolation
typed state
PlanSelector
Artifact Ref
Grant
native deterministic grader
visibility audit
```

Acceptance：

```text
official grader post-runtime
StateBus process cannot read grader
no category/difficulty in RouteContext
role visibility matches TeamBench
visibility audit PASS
FrameworkResult valid
```


## 28. B7 — IDA-Bench Slice

重点：

```text
InputAsset
DSL vs CodeAct Binding
multi-round context
```

Acceptance：

```text
original instructions preserved
original dataset exposed as InputAssetRef
no manual intent_op
no manual required_tools
no ground truth in Route/CodeAct
official checkpoint/submission compatible
native evaluator outside Runtime
```


## 29. B8 — Memory Genericization

再改：

```text
MemoryQuery
MemoryCommit
MemoryIndexStore._compatibility_decision
```

引入：

```text
TaskContractIdentity
task_compatibility_fingerprint
```

然后实现 LongMemEval-V2 backend。


# 30. 必须新增的 Tests

```text
tests/benchmark_boundary/
  test_private_gold_not_runtime_visible.py
  test_private_grader_not_runtime_visible.py
  test_adapter_semantic_not_external_visible.py
  test_audit_metadata_not_route_visible.py
  test_public_mechanical_derivation_allowed.py
  test_input_asset_role_scope.py
  test_opaque_runtime_task_id.py
  test_task_contract_hash_excludes_private.py
  test_private_grade_not_memory_feedback.py
```

尤其建议仿 LongMemEval-V2 做 spy：

```text
secret-question-id
secret-answer
secret-evaluator
```

最后断言：

```text
none in RouteContext
none in Planner prompt
none in BindingContext
none in MemoryQuery
```


## 31. External Task ID

不要把：

```text
D6_data_reconcile
formal-anomaly-003
```

直接当 Planner-visible identity。

正式 external run 使用 opaque：

```text
runtime_task_id = UUID/random opaque id
```

Outside-runtime Audit 保存：

```text
benchmark case id <-> runtime task id
```

避免 task ID 自带 category signal。


## 32. Hash / Side-channel 规则

不要把 private Gold 纳入：

```text
task_contract_hash
public_context_hash
memory compatibility hash
```

否则即使 value 不可见，

不同 Gold 导致不同 hash 仍可能形成 side-channel / lookup key。

应分开：

```text
public_context_hash
task_contract_hash
visibility_manifest_hash
asset digest

private evaluation hash
  only outside Runtime
```


## 33. External Output Schema / Tool Constraint 规则

### Output Schema

若用户公开说：

```text
return fields A/B/C
```

属于 Public Declared Constraint。

若 Adapter 根据 benchmark label 自动知道：

```text
正确输出必然是 delta_value/delta_pct
```

属于 Adapter Semantic Derivation，External 禁止。

### Tool Constraint

若 task 明说：

```text
must use SQL
network forbidden
```

可以进入 Authority。

若 Adapter 认为：

```text
应该用 CodeAct
```

不能。

交给 BindingResolver。


## 34. Role Constraint 规则

TeamBench 的 Planner/Executor/Verifier 是 benchmark 原生 protocol，所以合法进入 public role authority。

IDA-Bench 并不要求 StateBus 的 Retriever/Executor/Summarizer topology，因此不能由 Adapter 固定完整三/四角色。

这正是 Role Router external validation。


## 35. Dataset Generalization 的成功标准

不是：

```text
“支持了 7 个 benchmark 名称”
```

而是：

> 接一个新 external benchmark 时，不需要修改 Runtime task-family switch、operation formula registry、capability IDs 或 provider selection rule。

理想情况下只新增：

```text
public adapter
asset mapping
submission wrapper
```

Runtime 不改。


# 36. Codex 第一阶段实施规格（B0/B1）

## Scope

只做：

```text
Visibility Contract
Boundary Contract
Controlled Visibility Audit
```

不做：

```text
TeamBench integration
IDA integration
Router behavior change
Memory genericization
TaskCompiler rewrite
```

## New files

建议：

```text
statebus/contracts/benchmark_boundary.py
statebus/contracts/input_asset.py
statebus/benchmark/visibility.py
tests/benchmark_boundary/
```

## Required objects

```text
VisibilityClass
InputAssetRef
ExternalTaskEnvelope
PublicTaskConstraints
TaskContractIdentity
BenchmarkVisibilityRecord
BenchmarkVisibilityAudit
```

## Controlled integration

当前 `adaptive_formal_mainline` 仅增加 visibility inventory / manifest。

不得改变：

```text
Planner prompt
Executor prompt
operation semantics
validator
expected facts
formal result
```

## Acceptance Gates

```text
existing tests PASS
formal 25 behavior unchanged

expected_facts -> PRIVATE_GOLD
operation_semantics -> ADAPTER_SEMANTIC_DERIVATION
scenario tags/category -> AUDIT_ONLY

private role visibility count = 0

new privacy tests PASS
canonical hashes stable where old contracts unchanged
```

这是最适合交给 Codex 的第一 implementation slice。


# 37. 最终结论

1. 当前没有发现直接 `expected_facts -> Agent` 的 answer leakage。
2. 当前 adaptive formal 明确存在 semantic procedure、input normalization、role topology、reference validation scaffolding。
3. 这些对 controlled mechanism experiment 不构成致命问题，但不足以证明 general external runtime。
4. 不应删除 Controlled Lane，而应新增 External Lane。
5. External lane 不应扩 `TaskCompiler` 的 task family / intent / tool enum。
6. `CanonicalTaskSpec` 先定位为 Controlled/Legacy contract，不做万能 v2。
7. 真正 P0 contract 热点是 `AdaptiveTaskEnvelope / AdaptiveMainlineRequest / AdaptiveDispatchContext`。
8. `InputAssetRef / ExternalTaskEnvelope / TaskContractIdentity / BenchmarkVisibilityAudit` 是 external boundary 的核心。
9. Router 必须只消费 public context；benchmark origin/category/difficulty 不得成为 routing feature。
10. TeamBench / IDA-Bench / LongMemEval-V2 分别对应 Plan/Role Routing、Execution Binding、Memory Reuse，是最合适的三条 external 主线。
11. Memory genericization应在 TeamBench/IDA bring-up 之后单独完成。
12. 第一 Codex Slice 应是 B0/B1 visibility + contract，不应直接开始“接 benchmark”。

---

# 38. 参考资料

## StateBus

- https://github.com/qcrs/os
- https://github.com/qcrs/os1
- https://github.com/qcrs/os/blob/master/statebus/benchmark/minimal_runner.py
- https://github.com/qcrs/os/blob/master/statebus/benchmark/adaptive_formal.py
- https://github.com/qcrs/os/blob/master/statebus/benchmark/adaptive_formal_mainline.py
- https://github.com/qcrs/os/blob/master/statebus/contracts/models.py
- https://github.com/qcrs/os/blob/master/statebus/contracts/adaptive.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/compiler.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_mainline.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/adaptive_dispatcher.py
- https://github.com/qcrs/os/blob/master/statebus/runtime/plan_policy.py
- https://github.com/qcrs/os/blob/master/statebus/memory/models.py
- https://github.com/qcrs/os/blob/master/statebus/memory/store.py

## TeamBench

- https://github.com/ybkim95/TeamBench
- https://github.com/ybkim95/TeamBench/blob/main/harness/framework_adapter.py
- https://arxiv.org/abs/2605.07073
- https://teambench.github.io/

## IDA-Bench

- https://github.com/lhydave/IDA-Bench
- https://arxiv.org/abs/2505.18223
- https://www.kaggle.com/datasets/lhydave/ida-bench

## LongMemEval-V2

- https://github.com/xiaowu0162/LongMemEval-V2
- https://github.com/xiaowu0162/LongMemEval-V2/blob/main/tests/test_query_privacy.py
- https://arxiv.org/abs/2605.12493
- https://xiaowu0162.github.io/longmemeval-v2/

## AIDABench

- https://github.com/MichaelYang-lyx/AIDABench
- https://arxiv.org/abs/2603.15636

## ToolSandbox

- https://github.com/apple/ToolSandbox
- https://arxiv.org/abs/2408.04682

## BFCL V4

- https://gorilla.cs.berkeley.edu/leaderboard
- https://gorilla.cs.berkeley.edu/blogs/15_bfcl_v4_web_search.html

## OrchBench

- https://arxiv.org/abs/2607.25656
