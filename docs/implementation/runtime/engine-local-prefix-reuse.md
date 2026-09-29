# Engine-Local Prefix Reuse

APC 将 Executor、Summarizer 或其他获准角色共同可见的 evidence 编译到 prompt 的相同 token prefix，再由同一 vLLM engine 自动复用缓存 block。StateBus 负责 evidence 交集、稳定渲染、exact-token identity 和 counter delta；vLLM 负责 block 的驻留和淘汰。

## 调用路径

~~~mermaid
sequenceDiagram
    participant R as Runtime
    participant P as Prefix compiler
    participant V as vLLM
    R->>P: role-visible evidence
    P->>P: stable-key intersection + digest check
    P->>P: tokenizer / chat template / block alignment
    P->>V: full prompt with shared prefix
    V-->>R: response + metrics counters
    R->>R: compute task-local query/hit delta
~~~

共同前缀只有在参与角色集合、stable key 和 entry digest 都一致时才 eligible。compile_exact_token_prefix_identity() 以真实 tokenizer 和 chat template 计算最长公共 token prefix，并按 block size 对齐；公共范围不足时保持独立布局。

STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix 选择共同布局；STATEBUS_PREFIX_POLICY=observe|on 选择观测或启用策略。默认 independent + off。

## 观察字段

- prefix text hash、layout/normalizer/visibility policy version；
- participant roles、authorized common keys、entry digest；
- exact token identity、full block token count、eligibility reason；
- vLLM /metrics 的 query/hit counter delta；
- task wall、consumer TTFT 和服务 instance/cache epoch。

服务 counter 不可读、series 不一致或窗口不独占时，业务请求可以完成，观测标为 unavailable。该状态不能被当作 zero hit。

## 当前 utility 结果

当前精选 run 的 APC 分母为 8 个计分位置，见 tests/evidence/model-assist/summary.md：

- consumer TTFT 平均 2540.2 -> 264.3 ms，下降 89.59%；
- 观测命中 token 平均 48 -> 5168；
- 完整 task_wall_ms 平均下降 4.29%。

这些数来自独立 long-text utility suite；服务切换和清理成本不归因于某个 slot。APC 的局部 TTFT 结果不能改写为 48 项主链整体收益。

## 代码入口

| 文件 | 职责 |
| --- | --- |
| src/statebus/contracts/prefix.py | prefix contract 和 exact identity model |
| src/statebus/runtime/prefix_identity.py | common prefix intersection、token LCP、block alignment |
| src/statebus/runtime/prefix_feedback.py | predicted/observed counter delta feedback |
| src/statebus/benchmark/model_assist_utility/runner.py | APC utility phase 和记录聚合 |
| scripts/experiments/contest_model_assist/run_utility_suite.sh | utility launcher |
