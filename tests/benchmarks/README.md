# Benchmark 入口

`run_statebus.sh` 是稳定的 keyword dispatcher，正式 runner 仍是各自实现的 owner：

```bash
tests/benchmarks/run_statebus.sh smoke --dry-run
tests/benchmarks/run_statebus.sh mainline-24 --dry-run
tests/benchmarks/run_statebus.sh mainline-mechanisms --dry-run
tests/benchmarks/run_statebus.sh apc --dry-run
tests/benchmarks/run_statebus.sh kv --dry-run
tests/benchmarks/run_statebus.sh logit --dry-run
tests/benchmarks/run_statebus.sh utility --dry-run
```

`mainline-24` 选择主链 launcher；`mainline-mechanisms` 选择 24 位置机制 runner；`apc`、`kv`、`logit` 和 `utility` 选择独立的 28 位置 utility runner。dispatcher 不改变参数合同，也不隐式管理服务。
