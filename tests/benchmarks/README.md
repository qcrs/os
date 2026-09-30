# Benchmark 入口

`run_statebus.sh` 是 benchmark 的 keyword dispatcher。它检查参数并调用对应 runner，不启动 vLLM，也不替换已有容器。

## 目录导航

```text
tests/benchmarks/
├── README.md
├── mainline/
├── mechanisms/
└── utility/
```

目录入口：[`mainline/`](mainline/)、[`mechanisms/`](mechanisms/)、[`utility/`](utility/)。

```bash
tests/benchmarks/run_statebus.sh smoke --dry-run
tests/benchmarks/run_statebus.sh mainline-24 --dry-run
tests/benchmarks/run_statebus.sh mainline-mechanisms --dry-run
tests/benchmarks/run_statebus.sh apc --dry-run
tests/benchmarks/run_statebus.sh kv --dry-run
tests/benchmarks/run_statebus.sh logit --dry-run
tests/benchmarks/run_statebus.sh utility --dry-run
```

`mainline-24` 选择标准任务 launcher；`mainline-mechanisms` 选择 24 位置机制 runner；`apc`、`kv`、`logit` 和 `utility` 选择独立的 28 位置 utility runner。dispatcher 保持参数合同，模型服务由调用方管理。

## Live 执行

先从仓库根目录启动 Runtime profile，并确认 vLLM、`statebus-runtime` 和 smoke 正常：

```bash
scripts/start_statebus.sh qwen3-32b-gpu2-u050
tests/benchmarks/run_statebus.sh smoke
```

然后运行对应 benchmark。主实验和 Memory / State runner 默认使用 live 模式：

```bash
tests/benchmarks/run_statebus.sh mainline-24
tests/benchmarks/run_statebus.sh mainline-mechanisms
```

utility runner 需要显式确认执行：

```bash
tests/benchmarks/run_statebus.sh utility --execute --yes
```

`utility` 可替换为 `apc`、`kv` 或 `logit` 以运行单个 phase。上述命令不会启动或重启 vLLM 和容器；输出写入新的 `runs/` 目录。

正式结果入口：

| 路由 | 结果目录 | 分母 |
| --- | --- | ---: |
| `mainline-24` | `tests/evidence/mainline/` | 24 对、48 次执行 |
| `mainline-mechanisms` | `tests/evidence/mechanisms/` | 16 Memory + 8 State |
| `apc` / `kv` / `logit` / `utility` | `tests/evidence/model-assist/` | 8 APC + 8 KV + 12 Logit |

先运行 `--dry-run` 查看解析后的命令和输出目录，再执行 live runner。配置和服务启动见 [`../../docker/README.md`](../../docker/README.md)，详细结果见 [`../../docs/experiments/results.md`](../../docs/experiments/results.md)。
