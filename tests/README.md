# 测试与证据

返回 [`../README.md`](../README.md) 查看真实启动、Demo 和 Studio；部署与服务检查见 [`../docker/README.md`](../docker/README.md)，实验口径与结果见 [`../docs/experiments/README.md`](../docs/experiments/README.md)。

```text
tests/unit/          离线合同、Runtime、Memory、CodeAct、Logit/APC/KV
tests/integration/   Runtime、固定主链和 Studio 组合测试
tests/benchmarks/    主链、机制和 utility contract tests 及 dispatcher
tests/evidence/      三条精选结果链的 Markdown/JSON 聚合
tests/measurement/   旧目录布局兼容入口；不承载默认测试
```

离线回归：

```bash
source deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/unit tests/integration tests/benchmarks
```

按目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/unit
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/integration
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/benchmarks
```

Benchmark 入口使用 [`benchmarks/run_statebus.sh`](benchmarks/run_statebus.sh)。精选结果目录只保存 `mainline`、`mechanisms` 和 `model-assist` 的聚合文件；完整运行树和服务日志保存在 `runs/`。

Live smoke 和 benchmark 需要已启动的 vLLM 与 `statebus-runtime`：

```bash
tests/benchmarks/run_statebus.sh smoke
tests/benchmarks/run_statebus.sh mainline-24
tests/benchmarks/run_statebus.sh mainline-mechanisms
tests/benchmarks/run_statebus.sh utility --execute --yes
```

各命令的前置条件、phase 参数和输出目录见 [`benchmarks/README.md`](benchmarks/README.md)。

Studio 的 API 组合测试位于 `tests/integration/studio/`，前端流程测试位于 `src/studio-ui/tests/`。

```bash
cd src/studio-ui
npm ci
npm run typecheck
npm run test:flow
```

## 目录导航

```text
tests/
├── README.md
├── benchmarks/
│   ├── mainline/
│   ├── mechanisms/
│   └── utility/
├── evidence/
│   ├── mainline/
│   ├── mechanisms/
│   └── model-assist/
├── integration/
│   ├── runtime/
│   └── studio/
├── measurement/
└── unit/
    ├── codeact/
    ├── contracts/
    ├── mechanisms/
    ├── memory/
    └── runtime/
```

目录入口：

| 目录 | 入口 |
| --- | --- |
| `benchmarks/` | [`benchmarks/README.md`](benchmarks/README.md) |
| `benchmarks/mainline/` | [`benchmarks/mainline/`](benchmarks/mainline/) |
| `benchmarks/mechanisms/` | [`benchmarks/mechanisms/`](benchmarks/mechanisms/) |
| `benchmarks/utility/` | [`benchmarks/utility/`](benchmarks/utility/) |
| `evidence/` | [`evidence/README.md`](evidence/README.md) |
| `evidence/mainline/` | [`evidence/mainline/`](evidence/mainline/) |
| `evidence/mechanisms/` | [`evidence/mechanisms/`](evidence/mechanisms/) |
| `evidence/model-assist/` | [`evidence/model-assist/`](evidence/model-assist/) |
| `integration/` | [`integration/README.md`](integration/README.md) |
| `integration/runtime/` | [`integration/runtime/`](integration/runtime/) |
| `integration/studio/` | [`integration/studio/`](integration/studio/) |
| `measurement/` | [`measurement/README.md`](measurement/README.md) |
| `unit/` | [`unit/README.md`](unit/README.md) |
| `unit/codeact/` | [`unit/codeact/`](unit/codeact/) |
| `unit/contracts/` | [`unit/contracts/`](unit/contracts/) |
| `unit/mechanisms/` | [`unit/mechanisms/`](unit/mechanisms/) |
| `unit/memory/` | [`unit/memory/`](unit/memory/) |
| `unit/runtime/` | [`unit/runtime/`](unit/runtime/) |
