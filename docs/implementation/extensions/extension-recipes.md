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

## 新增 Transform DSL 操作

同时更新 allowed op、参数校验、输出列推导、解释执行、稳定序列化和预算测试。涉及 join 或派生字段时，还要校验 Ref 授权与字段 collision。不要只修改 `_apply()`，否则 Validator 与真实执行面不一致。

## 新增数值状态类型或存储后端

新的数值状态需要明确 dtype、byte order、shape/layout、encoder/producer signature、manifest、blob hash、lease、消费算法和 receipt。随后在 RefKind/StorageKind、LayeredStoragePolicy、publish/resolve/release、Control RefHandle、Telemetry 与跨进程测试中接入。

新增后端不能静默改变对象语义。Store 应记录 preferred/selected/fallback，解析路径必须限制在受控 root，release 必须幂等。若对象无法跨进程解析，就不能作为 formal 非文本状态载体。

## 新增记忆类型或兼容字段

扩展 `MemoryType` 或 metadata 前，先判断该字段属于候选排序还是硬兼容。检索信号进入 MemoryQuery/RRF；会使旧结果失效的条件进入 CompatibilityDecision/Replay key。同步更新 canonical payload、持久化恢复、reason code、Telemetry 和 negative test。

## 新增 Studio recipe

在 [`recipes.py`](../../../statebus/studio/recipes.py) 增加公开描述，并在 `build_command()` 中返回固定 argv。浏览器参数不能直接拼入命令。若新 runner 产生不同 summary 布局，要扩 `task_flow.py` 的受限解析，而不是在 React 中直接扫描文件。

catalog 只暴露安全元数据。新增数据源时使用 project-root containment、checksum 与受限 preview，不暴露系统任意路径。长任务仍进入单 Worker 队列。

## 新增 Telemetry 指标

先定义事件分母和聚合方式。逐次计数加入 additive event，任务终态值放在 `TASK_SUMMARY_METRICS`；不要在两处同时累计同一指标。同步更新 Studio 白名单仅用于展示，正式汇总仍以完整 event contract 为准。

