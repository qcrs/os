# Executor、CodeAct 与质量门导航

Executor 有两条主要执行表示：受限 Python CodeAct 与结构化 Transform DSL。两条路径最终都必须产生 `ExecutionArtifactRef`，并经过输入、输出和业务质量检查。若启用 Logit Retry Gate，闭集 route/tool 选择还会在代码生成或 DSL 执行之前经过一次数值授权门。为避免把候选选择、模型生成、安全隔离和业务正确性混在一起，这些机制分别说明。

| 文档 | 核心问题 |
|:--|:--|
| [Logit Retry Gate](runtime/logit-retry-gate.md) | Executor 候选是否足以进入实际执行，低 margin 后如何只重查一次 |
| [受限 Python CodeAct](execution/bounded-python-codeact.md) | 模型生成的 Python 如何经过静态策略与 bubblewrap 执行 |
| [Transform DSL](execution/transform-dsl.md) | 哪些表格操作可以用确定性结构化程序表达 |
| [Workspace、产物与质量门](execution/artifact-and-quality-gate.md) | 输入怎样物化、候选文件何时 verified、失败后如何 invalidated |

```text
CapabilityGrant
  -> closed-set route/tool choice
  -> optional LogitStateRef / GateReceipt
  -> Python candidate or TransformProgram
  -> policy validation
  -> isolated/bounded execution
  -> output schema + capability validator
  -> ExecutionArtifactRef candidate/verified
  -> Runtime Commit Gate and settlement
```

具体 benchmark 的 `executor-mode` 决定程序来自 LLM 生成、注册的确定性 recipe 还是 DSL。不能因为名称中出现 CodeAct 就假定每个实验都让 LLM 临场写 Python。
