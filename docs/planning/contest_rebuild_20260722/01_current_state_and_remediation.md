# 01 当前状态、证据边界与整改登记册

> **事实来源**：[`statebus_v2_contest_readiness_audit_20260722.md`](../../reports/statebus_v2_contest_readiness_audit_20260722.md)、当前源码、canonical E0-E6 报告，以及 [`07`](07_auxiliary_verification_record.md) 的定向核对。
> **设计假设**：当前 dirty worktree 的 latent/alignment 改动属于用户，不回滚；未来 contest freeze 从明确 runtime/config/data hash 建立，正式 lane 一律 latent off。
> **待验证实验**：R0 current-version regression、R1 semantic accounting、R2 L0-L3、R4 memory counterfactual、R5-R10 Prefix/LogitState、R11/R12 数据与自然能力覆盖。

文档导航：[索引](README.md) | [00 决策与包装](00_executive_decision_and_packaging.md) | [01 现状与整改](01_current_state_and_remediation.md) | [02 Prefix](02_prefix_engine_local_reuse_design.md) | [03 LogitState](03_logitstate_core_chain_design.md) | [04 数据与任务](04_vertical_data_preprocess_and_task_design.md) | [05 实验](05_experiment_matrix_metrics_and_statistics.md) | [06 实施与验收](06_implementation_plan_and_acceptance.md) | [07 辅助核对](07_auxiliary_verification_record.md)

## 1. 证据身份

- 当前分支为 `feat/native-latent-alignment`，存在用户拥有的未提交 latent/alignment 变更；本轮没有触碰。
- canonical E0-E6 是 2026-07-20 历史 dirty snapshot，不等价于当前工作树。
- 本轮 33 项 focused tests 通过，只证明序列化/Ref/prefix control-plane/feedback 合同；不证明性能或质量。
- 当前最强非文本状态证据是 embedding `SemanticStateRef`，而不是 Prefix、LogitState 或 latent。
- 任何后续“当前已实现”都必须指当前代码路径；任何“已获益”都必须指新的 frozen artifact。

## 2. D0 决定登记册

状态枚举严格采用 Prompt 指定的六类。

| 对象 | 分类 | 当前代码/证据 | 当前可说 | 当前不可说 | 后续 gate / 依赖 |
| --- | --- | --- | --- | --- | --- |
| typed Protobuf/UDS control | `implemented and consumed` | `v2/control/statebus_v2.proto`、`messages.py`、`transport.py`；历史 E1 | 主路径使用 typed control；历史 bytes 结果可按 snapshot 引用 | Protobuf 必然省 token/latency；wire-level HELLO 已存在 | R0/R2；同 topology fresh run |
| Planner/Retriever/Executor/Summarizer | `implemented and consumed` | `v2/runtime/role_path.py`、runtime controller、E4/E5 role requests | 受控固定角色链；闭集 capability | 自治协商群体、动态 DAG、任意 CodeAct | R12 自然 route/tool coverage |
| embedding `SemanticStateRef` | `implemented and consumed` | `v2/state/semantic_state.py`、`smoke.py:2197+`、`pipeline.py:1645+` | `<f4` matrix 跨 PID 数值消费并改变 selected IDs/hydration；显式 release | hidden/KV、向量直接喂 LLM、外部泛化 | R1/R2 fresh producer/consumer/effect/release |
| role hydration accounting | `implemented and consumed`，但需收紧 | `smoke._build_role_hydrated_slices()`、driver telemetry | role-specific text/table/artifact bytes 已记账 | `target_role=executor` 等于 Executor LLM 读向量 | R1 拆 logical owner/physical consumer/downstream role |
| `RoleExecutionReceipt` | `implemented and consumed`（adaptive path） | `v2/contracts/adaptive.py`、`adaptive_dispatcher.py` | 当前实现可要求 consumed ID/hash/recipe receipt | 历史 E3 已自动修复或当前 formal 已证明 | R4 fresh run；legacy/adaptive 口径统一 |
| legacy smoke memory receipt | `implemented and consumed`，范围窄 | `smoke._continuous_memory_consumption_records()` 只记 approved replay | candidate 不再自动计 consumption | assist candidate 已被 role 使用 | R4 role callback + paired counterfactual |
| E3 `consumed=23` | `invalidated historical count` | 历史 artifact + comprehensive review | 可保留“历史记录值 23，后续审计判定不适合作 headline” | 23 次真实角色消费/effect | R4 重建，旧 artifact 不改写 |
| Memory store/query/compatibility | `implemented and consumed` | `v2/memory/`、runtime driver | 存储、检索、拒绝、replay 类型存在 | candidate/approved=hit；自然节省 LLM call | R4；receipt + counterfactual + nonzero effect |
| `NeuralPrefixIdentity` / hash | `implemented but unconsumed`（exact-token 意义） | `v2/runtime/neural_state.py` | 元数据 identity 用于调度/估算 | hash 绑定最终 token IDs | R5/P-A；canonical render + token hash |
| `compile_prefix_layout()` | `implemented and consumed`（flag path） | `v2/runtime/role_path.py` | helper 能把给定 shared text 放到 suffix 前并去重 | 当前角色一定共享相同前缀 | R5；current role slice counterfixture 已失败 |
| `EngineLocalPrefixRegistry.cache_hit` | `implemented but unconsumed`（engine 意义） | `v2/runtime/neural_state.py` | registry 见过相同兼容 key | GPU cache hit | 改名 `candidate_handle_seen`；P-B engine counter |
| Prefix saved-token/hit estimate | `telemetry only` | `estimate_engine_local_prefix_reuse()` 按 bytes/4、roles-1 | 调度估算 | observed token saving、TTFT、cache hit | P-B/P-C；estimate/observation 分表 |
| `/metrics` parser/delta | `implemented but unconsumed`（正式证据） | `vllm_metrics.py`；focused tests | 能解析候选 counter/gauge schema并拒绝 reset | 当前服务 schema/独占窗口已验证 | read-only probe；P-B per-request exclusive scrape |
| Prefix feedback/schedule | `implemented and consumed`（probe family） | `prefix_feedback.py`、`kv_prefix_schedule.py`、`continuous_runner.py` | `kv_prefix_reuse_v1` 可按 affinity 重排；指定 plans 静态 dependency-safe | 通用 scheduler 具备 DAG ready-set 证明；重排已增益 | P-A/P-B；ready-set scheduler contract |
| observed Prefix performance | `planned` | 无合格 canonical artifact | 无 | 命中提升、TTFT/总时延下降 | P-A/P-B/P-C |
| `serialize_logit_state_v2()` | `telemetry only` | `v2/runtime/logit_state.py`、`role_path.validate_execution_choice()` | 可从 Executor top-logprobs 形成 peak-position `<f4` 摘要 | 是正确候选分布、已跨进程传递、已改善决策 | L-A/B；专用闭集 decision position |
| `LogitStateRef` | `implemented but unconsumed` | `v2/refs/models.py`、RefKind/storage policy | Ref 类型和 registry entry 存在 | active ref 已在主路径 publish/resolve/release | L-B/L-D；扩展 contract + state module |
| `logit_state_transfer_count` / `<0.3` | `telemetry only` | `smoke.py:3552+` | bytes 存在时产生粗粒度计数 | transfer、calibrated gate、quality effect | 删除误名/迁移；L-A/C |
| Logit numeric consumer/effect | `planned` | 无 | 无 | LogitState 闭环完成 | L-A-D；[`03`](03_logitstate_core_chain_design.md) |
| ACME/BETA financial docs | `historical only`（formal headline） | repo-local markdown，source_basis 只有 design note | dev/task-contract fixture | 真实企业或外部泛化 | R11；公开企业披露替换 |
| disease/weather CSV | `historical only`（企业垂类） | repo-local Group 2 data | parser/CodeAct/table regression | 企业经营分析证据 | R11；仅保留 diagnostic |
| Orion/Nova prefix docs | `historical only`（业务 headline） | manifest 为 `demo_secondary`、mechanism-only | P-A/P-B dev mechanism fixture | 正式业务泛化 | R11 业务 holdout；P-B 可继续用 |
| latent/prompt_embeds/KV handoff | `historical only` 且正式关闭 | 用户分支代码/历史研究 | 可说明因质量/边界而关闭 | 正式能力、收益、依赖项 | formal config `latent_mode=off`；不进入 R0-R12 |

## 3. 当前真实主链

```text
CanonicalTaskSpec
  -> Planner: bounded retrieval objective
  -> Retriever: lexical/semantic/table candidates
  -> Qwen3-Embedding-0.6B: normalized query/candidate vectors
  -> [query; candidates] little-endian float32 matrix
  -> SemanticStateRef(shared_memory or mmap) + manifest/hash/lease
  -> subprocess selector: resolve -> cosine top-k -> byte budget
  -> selected IDs -> apply_semantic_state_selection()
  -> role-specific hydration
  -> Executor: closed candidate + bounded DSL/Python + validator
  -> verified ExecutionArtifactRef
  -> Summarizer: verified artifact/authorized evidence only
  -> MemoryRef commit/query/compatibility/replay
  -> state release
```

物理 selector 是系统组件；`target_role=executor` 是逻辑目标，不表示 Executor LLM 读取 float matrix。Controller、selector 和未来 ConfidenceGate 不计入 Agent 数。

## 4. 关键代码审计

### 4.1 Prefix

| 位置 | 当前行为 | 根因/风险 | 修复方向 |
| --- | --- | --- | --- |
| `neural_state.build_evidence_prefix_hash()` | hash EvidencePack/manifest/system version 元数据 | 不绑定 canonical rendered text、chat template 或 exact token IDs | hash 最终 common token window；元数据 hash 仅作 lineage |
| `role_path.compile_prefix_layout()` | 把调用者给的 `shared_prefix_text` 放到最前 | 不保证各 role 调用者提供相同 text | 单独构造授权交集的 `CanonicalSharedEvidencePrefix` |
| `smoke._build_role_hydrated_slices()` | Executor 主要是 table，Summarizer 可见 semantic+table | 当前两角色 `combined_text()` 常不同 | common prefix=visibility intersection；额外证据进 suffix |
| `EngineLocalPrefixRegistry.ensure_handle()` | 复见即 `cache_hit=True`、计数+1 | 错误命名易冒充 engine hit；key 兼容字段不足 | `candidate_handle_seen`；扩展 engine/template/epoch/adapter/config identity |
| `estimate_engine_local_prefix_reuse()` | bytes/4，假设首角色 miss、其余 hit | 只能估算；忽略 block 完整性/eviction/tokenizer | 保留为 planning estimate，永不进入 observed 字段 |
| `vllm_metrics.py` | counter 优先，gauge-only 拒绝，检查单调性 | 当前服务 schema未核对；单位可能是 tokens；label/其他流量可污染 | 固定 metric schema/labels/unit；per-request exclusive interval |
| `smoke.run_smoke()` | task 前后各抓一次，窗口覆盖所有角色 | 不能归因单请求/单 prefix；没有独占证明 | 请求级 event 和 scrape；污染时 invalidated |
| `kv_prefix_schedule.py` | explicit friendly/hostile plans | 该 manifest 安全，但通用排序没有 ready-set API | 只从 DAG ready set 选 affinity；完成后再解锁依赖 |
| `continuous_runner.py` feedback | 只在 local vLLM + probe family + input order 重排 | 基于整 task delta，仍可能受不可比 observation 影响 | 只消费 valid request observation；invalid 不触发策略 |

本轮 fixed fixture 进一步确认：给 Executor/Summarizer **同一** shared text 时，Qwen3-32B chat template 的 44-token common window hash 相同；模拟当前不同 role slice 时 shared hash 不同，full-message LCP 仅 11 tokens。详见 [`07`](07_auxiliary_verification_record.md)。

### 4.2 LogitState

| 位置 | 当前行为 | 根因/风险 | 修复方向 |
| --- | --- | --- | --- |
| `runtime/llm.py` | 仅 local_vllm Executor 请求 `logprobs=True, top_logprobs=20` | endpoint 能力未核对；其他 provider 不支持 | capability event；missing 时 fail closed to baseline |
| `role_path.validate_execution_choice()` | 对合并 completion 的 top-logprobs 调 serializer；异常全部吞掉 | 无 unavailable reason；retry 序列混合；无 Ref | 每次 request 独立 producer receipt；结构化错误事件 |
| `serialize_logit_state_v2()` | 选全 JSON 序列 peak entropy；候选用字符串前缀匹配 | 可能选 `{`、引号、字段名、格式 token；无法可靠绑定业务决定 | 专用单 token alias 字段，byte/token position mapping |
| serializer payload | peak 位置 top-k 重新归一化 `<f4` | 丢失 tail mass；不是冻结候选顺序 | candidate-ordered probabilities + `other_mass` |
| `LogitStateRef` | 少量 producer/consumer/length/hash 字段 | 缺 task/session/request/prompt/model/template/lease/PID/policy | 按 [`03`](03_logitstate_core_chain_design.md) 扩展 v2 contract |
| `LayeredStoragePolicy` | auto 模式 LOGIT_STATE 优先 memfd | 正式短命跨 PID链更适合命名 shared memory | contest profile 改 shared_memory -> mmap fallback |
| `smoke.py` | bytes>0 计 transfer；confidence<0.3 计 trigger | 无 publish/resolve/action/calibration | 分 publish/resolve/consume/release/action/effect；去掉硬阈值 |
| numeric consumer | 不存在 | telemetry 不能构成非文本交接 | 独立 `ConfidenceGate` subprocess |

### 4.3 Memory 与 semantic accounting

- `RoleExecutionReceipt` 和 narrow Summarizer view 是正确收紧方向，但尚无 fresh formal artifact。
- Summarizer 默认不能获得 recipe source；未来 receipt 必须拒绝“prepared input 等于 consumed”。
- 每条 memory consumption 必须绑定 `rendered_request_hash` 或 `executed_recipe_hash`，并有 before/after decision surface 与 outcome。
- Semantic 必须分别记录 `producer_role/PID`、`physical_consumer_component/PID`、`logical_target_role`、`downstream_hydration_roles`；PID 不得按角色求和后失真。

## 5. P0/P1/P2 整改清单

| ID | 严重性 | 问题/根因 | 未来 owner | 完成定义 | 前置依赖 |
| --- | --- | --- | --- | --- | --- |
| P0-1 | blocker | LogitState 无真实 consumer；现有 peak JSON entropy 无业务绑定 | Runtime/State owners | dedicated producer、active ref、cross-PID gate、bounded action、effect receipt、release、L-A-D | 闭集 candidate contract、top_logprobs capability |
| P0-2 | blocker | Prefix estimate/registry 与 engine observation 混淆 | Prompt/Runtime/Benchmark owners | canonical common tokens、expanded identity、ready-set、valid per-request counters、P-A-C | tokenizer/template freeze、独占实验窗口 |
| P0-3 | blocker | E3 memory consumption 含假阳性/宽归因 | Memory/Runtime owners | actual rendered/recipe receipts；off/disclosed/consumed paired run；旧 E3 保留纠错 | role callbacks、fresh freeze |
| P0-4 | blocker | formal 垂类仍依赖 synthetic/通用 CSV | Data/Benchmark owners | public source terms、raw/transform/gold ledger、issuer-disjoint holdout、2x10 | [`04`](04_vertical_data_preprocess_and_task_design.md) source gate |
| P0-5 | blocker | current worktree 与 E0-E6 identity 不同 | Release owner | source/config/data/runtime/image hashes；clean manifest；fresh full tests/artifacts | P0-1..4 合并后 |
| P1-1 | high | bytes/token/latency 因果叙事混用 | Benchmark owner | 指标字典、matched switches、ABBA/CI、quality equivalence | [`05`](05_experiment_matrix_metrics_and_statistics.md) |
| P1-2 | high | Agent 能力叙事过宽、semantic route 自然覆盖不足 | Runtime/Task owner | 权限表；R12 只报告自然 selected count；无覆盖就缩窄 claim | public formal tasks |
| P1-3 | high | semantic logical/physical/downstream 记账混淆 | Telemetry owner | 分字段 receipt，PID/ref/hash 对齐，release count 可审计 | R1 fixture + integration |
| P1-4 | medium-high | prefix probe 是专门 mechanism data | Benchmark owner | Orion/Nova 只做 P-A/B；业务 P-C 用公开数据 | R11 数据冻结 |
| P2-1 | medium | 无 wire HELLO | Protocol owner | 仅需求成立时实现 HELLO/ACK、版本/capability digest/failure test | 非提交 blocker；registry discovery 已够最低要求 |
| P2-2 | medium | sandbox 可能被包装成生产隔离 | Execution owner | 只称 contest validation profile；记录 bwrap/non-root/fallback | final packaging lint |

详细文件与验收顺序在 [`06`](06_implementation_plan_and_acceptance.md)。

## 6. 严格角色边界

| 角色/组件 | 输入与可见对象 | 输出 | 拒绝条件/不可声称 |
| --- | --- | --- | --- |
| Planner | request、CanonicalTaskSpec、历史 artifact 摘要（授权时） | bounded semantic retrieval objective | 不读 gold/全 corpus facts；不生成动态执行 DAG |
| Retriever | objective、closed capability surface、候选 corpus | query/candidates、EvidencePack、route selection | formal 必须自然覆盖；不能称开放搜索自治体 |
| semantic selector | binary SemanticStateRef、manifest、budget | selected IDs/scores receipt | 系统数值组件，不是 LLM Agent |
| Executor | authorized slice、closed route/tool、artifact inputs | bounded program/verified artifact | 不执行任意 shell；不能越 grant |
| Summarizer | verified artifact、authorized evidence、narrow memory hint | cited summary/claim set | 不是数值真相来源；不得接收 executable recipe |
| Controller | grants、Refs、policies、quality/replay/prefix/logit lifecycle | decisions/events/releases | 系统组件，不计 Agent |
| ConfidenceGate（future） | short-lived LogitStateRef + binding contract | 一个 bounded action | 不读 raw completion；不循环重试；不证明答案正确 |

## 7. 历史结果的可用读法

| 历史对象 | 可保留 | 必须附带的限制 |
| --- | --- | --- |
| E1 | 40/40；control/wire bytes 和 L1-L2 context 变化 | prompt token L0-L1 增加；单次固定顺序 latency；不是当前 worktree |
| E2 | 两 family 各 10/10；rejection/recompute 设计 | candidate/artifact reuse 不等于 actual consume/replay |
| E3 | commit/load/compatibility/rejection 路径 | `consumed=23` 不作为 headline；历史 artifact 不改写 |
| E4 | repo-local holdout 上跨 PID semantic consumer | 非第三方/开放域；current code 需 fresh rerun |
| E5 | 25/25、DSL 7、bounded Python 18 | Retriever 全部自然选 table；不能称 semantic 自适应广泛覆盖 |
| E6 | 历史 openEuler container `558 passed` | 不证明当前 branch/new data/new mechanisms |

## 8. 整改停止条件

- 若 exact token identity 无法在真实 role layout 成立，Prefix 停在 ineligible/negative result，不改任务迎合。
- 若引擎没有合法 counters，P-B 只能报告 unavailable；不得用 lifetime gauge 替代。
- 若 Logit features 在 dev 无预测力，停止 gated mode，保留 telemetry 或关闭。
- 若 gate 没有净质量价值，L-C 负结果保留，不进入 headline。
- 若公开数据 rights/source/gold 隔离未通过，formal 继续称 repo-local benchmark。
- 若 memory paired run 无 actual effect，Memory 只包装为 store/query/compatibility mechanism。
- 若任何 lane 质量不等价，不比较该 lane 的“更快”。
