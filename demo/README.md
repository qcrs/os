# 演示入口

`demo/` 提供离线回放和本地 vLLM 演示。Studio API 由 `demo/run_demo.sh --local-vllm` 启动，UI 由 `scripts/run_statebus_studio_ui.sh` 启动；正式 benchmark 位于 [`../tests/benchmarks/README.md`](../tests/benchmarks/README.md)。

```bash
demo/run_demo.sh --offline
demo/run_demo.sh --local-vllm
demo/run_smoke.sh --dry-run
```

本地 vLLM Demo：

```bash
# 终端一
source deploy/activate_statebus_host.sh
demo/run_demo.sh --local-vllm

# 终端二
scripts/run_statebus_studio_ui.sh
```

浏览器打开 `http://127.0.0.1:50173`。`--offline` 只打印已保存的 utility 结果入口；`run_smoke.sh --dry-run` 只打印 smoke 命令。Live smoke 使用 [`../tests/benchmarks/run_statebus.sh smoke`](../tests/benchmarks/README.md)。

服务已由 `scripts/start_statebus.sh` 启动时，直接运行 live smoke：

```bash
demo/run_smoke.sh
```

正式主链、机制和 utility 结果使用 `tests/benchmarks/run_statebus.sh`；精选输出使用 `tests/evidence/`。
