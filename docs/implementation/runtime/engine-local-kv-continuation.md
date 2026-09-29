# Engine-Local KV Continuation

显式 KV continuation 在 producer Executor 请求完成后捕获 parent KV，并把短生命周期 EngineLocalKVHandle 交给同一 vLLM Worker 的 consumer。consumer 仍按同一 logical prompt 生成结果，但物理 prefill 由 inherited parent 加 suffix 组成。

## 调用路径

~~~mermaid
sequenceDiagram
    participant E as Executor
    participant K as vLLM Worker registry
    participant C as CodeAct / Artifact
    participant S as Summarizer
    E->>K: capture parent KV
    K-->>E: READY handle
    E->>C: normal artifact and validation path
    C-->>S: verified artifact
    S->>K: load handle + suffix
    K-->>S: tokens + KVForwardProof
    S->>K: release in finally
~~~

handle 绑定 engine/model/tokenizer identity、task/attempt、parent token digest、block/layout、TTL 和实际 KV bytes。consumer 必须同时提供 scheduler proof 与 Worker forward proof；identity、token 账本或 proof 不一致时拒绝 continuation。capture、load、release 的计数和 registry 清理写入 suite record。

full_replay 与 continuation 必须保持相同 task、model、sampling、quality gate 和 APC 关闭条件。continuation 只在 utility profile 显式选择时运行；默认主链为 STATEBUS_ENGINE_LOCAL_KV_MODE=off。

## 当前 utility 结果

当前精选 run 的 KV 分母为 8 个计分位置，见 tests/evidence/model-assist/summary.md：

- consumer computed prefill 平均 5666.5 -> 545.5 tokens，下降 90.37%；
- consumer TTFT 平均 2570.6 -> 1005.7 ms，下降 60.88%；
- consumer request wall 平均下降 11.88%，完整 task_wall_ms 平均下降 3.58%；
- 这些数字包含 utility runner 记录的 capture/load/release 账本；服务切换成本不归因于某个 slot。

局部 prefill 和 TTFT 下降不等于主链整体收益，也不等于跨进程 hidden-state 传递。KV bytes、logical tokens 和 provider tokens 保持独立字段。

## 代码入口

| 文件 | 职责 |
| --- | --- |
| src/statebus/contracts/engine_local_kv.py | handle、proof 和兼容 identity contract |
| src/statebus/integrations/vllm_kv/ | client、connector、middleware、role client |
| src/statebus/runtime/kv_budget.py | budget、load/capture/release 约束 |
| src/statebus/benchmark/model_assist_utility/runner.py | KV utility phase 和记录聚合 |
| scripts/experiments/contest_model_assist/run_utility_suite.sh | utility launcher |
