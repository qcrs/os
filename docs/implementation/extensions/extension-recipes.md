# 常见扩展流程

## 新增正式任务或任务族

先定义可复现输入和 `CanonicalTaskSpec`，包括 task family、intent、required outputs/tools、结构化 arguments 和 quality checks。连续任务还要在 manifest 中写 depends-on rounds、produces/consumes 与 minimum reuse class。正式模式不依赖自由文本启发式编译。

随后确认现有 capability 是否覆盖该 intent。若覆盖，补 formal adapter 的 operation semantics、source rows/output schema 和 Validator；若不覆盖，再新增 capability。最后把任务加入 task registry 或 continuous family loader，并补质量、角色链和公平性测试。

```text
sample/manifest
  -> CanonicalTaskSpec
  -> formal adapter
  -> capability routing
  -> Validator / expected facts contract
  -> benchmark + tests
```

## 新增 capability

Capability descriptor 至少需要稳定 ID/version、owner role、execution kind、输入 Ref kind、输出 contract、Validator IDs、风险/预算。然后在 Dispatcher 中接入执行路径，在 PlanPolicy 中确认 owner/edge/contract 校验能够识别它，在 capability validator registry 中登记业务复算器。

若 capability 使用 LLM bounded Python，还要建立 `CodeGenerationPolicy`：允许 imports、固定 input/output paths、source/AST/loop/repair budgets 和 sandbox policy。若使用 DSL，应优先组合已有 op；只有无法表达时才扩 DSL。

## 接入 Transform DSL 操作

一次 DSL 操作接入同时更新 allowed op、参数校验、输出列推导、解释执行、稳定序列化和预算
测试。join 与派生字段操作同时校验 Ref 授权和字段 collision，使 Validator 与执行面保持一致。

## 新增数值状态类型或存储后端

新的数值状态需要明确 dtype、byte order、shape/layout、encoder/producer signature、manifest、blob hash、lease、消费算法和 receipt。随后在 RefKind/StorageKind、LayeredStoragePolicy、publish/resolve/release、Control RefHandle、Telemetry 与跨进程测试中接入。

Store 为新增后端记录 preferred/selected/fallback，解析路径限定在受控 root，release 采用幂等
实现。跨进程解析测试通过后，该后端进入 formal 非文本状态载体目录。

## 新增模型侧复用机制

模型侧机制分为正式 Ref 与 engine-local 优化。正式 Ref 接入 RefKind、Registry、typed Protobuf、
授权、lease 与 GC；engine-local 优化保留普通路径，并记录 engine/model/tokenizer identity、
启用范围、fallback、资源所有者和机制证明。Worker-local handle 由引擎 registry 管理。

```text
logical request contract
  -> deterministic identity/admission
  -> default-off runtime wiring
  -> engine integration
  -> mechanism proof + failure audit
  -> quality parity
  -> serialized A/B
```

Prefix 类机制记录 position-0 Token identity、完整 block 与 task-local counter delta；显式 KV
类机制记录 capture/load/release、logical Token accounting、scheduler/Worker 双证明、TTL/容量
与 fallback。两类机制使用独立命中指标。

## 新增记忆类型或兼容字段

扩展 `MemoryType` 或 metadata 前，先判断该字段属于候选排序还是硬兼容。检索信号进入 MemoryQuery/RRF；会使旧结果失效的条件进入 CompatibilityDecision/Replay key。同步更新 canonical payload、持久化恢复、reason code、Telemetry 和 negative test。

## 新增 Studio recipe

在 [`recipes.py`](../../../statebus/studio/recipes.py) 增加公开描述，并在 `build_command()` 中
返回固定 argv。浏览器提交 recipe ID，服务端完成命令映射；新 runner 的 summary 布局由
`task_flow.py` 适配后交给 React 展示。

catalog 暴露名称、摘要、checksum 和受限 preview。数据源使用 project-root containment，
长任务进入单 Worker 队列。

## 新增 Telemetry 指标

事件先定义分母与聚合方式。逐次计数进入 additive event，任务终态值进入
`TASK_SUMMARY_METRICS`，每个指标只选择一种累计位置。Studio 白名单负责界面展示，完整
event contract 负责运行汇总。
