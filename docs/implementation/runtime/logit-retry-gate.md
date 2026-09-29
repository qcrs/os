# Logit Retry Gate

Logit Gate 位于 Executor 的闭集候选选择之后、业务 dispatch 之前。Executor 产生候选概率，独立 Gate PID 解析 LogitStateRef，返回 LogitGateReceipt；Runtime 决定接受、重查一次或 fail closed。

## 执行路径

~~~mermaid
sequenceDiagram
    participant E as Executor
    participant S as State store
    participant G as Gate worker
    participant R as Runtime
    E->>S: publish candidate probabilities
    S-->>E: LogitStateRef
    E->>G: typed request + RefHandle
    G->>S: resolve and validate state
    G-->>R: GateReceipt + transport audit
    R->>R: cross-check PID, candidate and state identity
    R->>S: release state and write tombstone
~~~

候选 surface 绑定 alias、candidate ID、route、tool 和 digest。只允许单字段 JSON 选择；Gate 不解析自由文本，也不读取完整词表 logits。概率提取失败、候选缺失、state/lease/hash/PID 不一致都形成明确的 unavailable/error receipt。

retry_once 首次 retry 后最多再取一次候选概率；第二次仍不满足 gate 时不发送 Worker dispatch。所有已发布 state 通过 finally release。

## 配置

~~~dotenv
STATEBUS_LOGIT_GATE_MODE=off
# telemetry 或 retry_once
~~~

- off：不发布 Logit state，沿原选择路径；
- telemetry：发布并记录 accept/retry/unavailable/error，不改变业务控制流；
- retry_once：首次 retry 重新选择，第二次 retry 或 state 错误时 fail closed。

## 当前 utility 结果

当前精选 run 的 Logit 分母为 12 个计分位置，见 tests/evidence/model-assist/summary.md：

- 9 个 resolved case 通过；
- 3 个 unresolved case 正确 abstention；
- 在 3 个 resolved case 上，compact/selective logical input 平均减少 75.21%；
- compact/selective provider request wall 方向性下降 17.18%/18.51%。

正确 abstention 是质量结果，不应从分母删除。request wall 和 logical input 是不同指标；小批量方向性结果不能外推为所有模型或任务。

## 代码入口

| 文件 | 职责 |
| --- | --- |
| src/statebus/contracts/logit.py | candidate surface、receipt 和概率语义 |
| src/statebus/runtime/logit_state.py | exact choice token 定位和概率提取 |
| src/statebus/runtime/logit_gate.py | subprocess Gate、cross-check 和 release |
| src/statebus/state/logit_state.py | State store 发布、消费、释放和 tombstone |
| src/statebus/benchmark/model_assist_utility/runner.py | Logit utility phase 和 records |
