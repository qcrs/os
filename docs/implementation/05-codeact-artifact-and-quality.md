# Executor、CodeAct 与质量门导航

Executor 有两条主要执行表示：受限 Python CodeAct 与结构化 Transform DSL。两条路径最终
都产生 `ExecutionArtifactRef`，并经过输入、输出和业务质量检查。启用 Logit Retry Gate
时，闭集 route/tool 选择在代码生成或 DSL 执行之前经过数值授权门。候选选择、模型生成、
执行隔离和业务正确性分别留下记录。

| 文档 | 核心问题 |
|:--|:--|
| [Logit Retry Gate](runtime/logit-retry-gate.md) | Executor 候选是否足以进入实际执行，低 margin 后如何只重查一次 |
| [受限 Python CodeAct](execution/bounded-python-codeact.md) | 模型生成的 Python 如何经过静态策略与 bubblewrap 执行 |
| [Transform DSL](execution/transform-dsl.md) | 哪些表格操作可以用确定性结构化程序表达 |
| [Workspace、产物与质量门](execution/artifact-and-quality-gate.md) | 输入怎样物化、候选文件何时 verified、失败后如何 invalidated |

```text
CapabilityGrant
  -> 闭集 route/tool 选择
  -> 可选 LogitStateRef / GateReceipt
  -> Python 候选或 TransformProgram
  -> 策略校验
  -> 隔离且有预算的执行
  -> 输出 Schema 与能力 Validator
  -> ExecutionArtifactRef candidate/verified
  -> Runtime 提交门与结算
```

具体 benchmark 的 `executor-mode` 记录程序来自 LLM 生成、注册的确定性 recipe 还是 DSL。
实验汇总按真实 execution record 统计每一种路径。

显式 KV Continuation 的 handle 来源是 Executor 模型 prefill，并跨过 CodeAct 阶段留在同一
vLLM Worker，等待 Summarizer 消费。CodeAct 的业务结果形成 verified
`ExecutionArtifactRef`。两类对象分别验证 parent KV 继承和业务质量门。
