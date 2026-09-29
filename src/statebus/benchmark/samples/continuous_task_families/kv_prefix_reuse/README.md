# Prefix reuse 探针样本

该目录提供显式机制样本，用于比较共同长 evidence 位于 prompt 开头和交错布局时的 engine-local prefix cache 观察值。

样本只控制 `corpus_prefix_hash`、prompt layout、evidence pruning 和任务顺序；模型内部 KV tensor 留在同一 vLLM engine，不通过 StateBus 在进程间传递。正式 28 位置 utility 的入口是 `src/statebus/benchmark/model_assist_utility/`，本目录是可复用 fixture，不是主链任务输入。

样本文件：

```text
orion_factory_ops_report_2026.md
nova_retail_ops_report_2026.md
manifest.json
```
