# 演示入口

`demo/` 是评审和离线回放入口。它不复制 `src/studio-ui/`，也不拥有正式 benchmark 的结果分母。

```bash
demo/run_demo.sh --offline
demo/run_demo.sh --local-vllm
demo/run_smoke.sh --dry-run
```

正式主链、机制和 utility 结果使用 `tests/benchmarks/run_statebus.sh`；精选输出使用 `tests/evidence/`。
