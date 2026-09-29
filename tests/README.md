# 测试与证据

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

benchmark 入口使用 [`benchmarks/run_statebus.sh`](benchmarks/run_statebus.sh)。`tests/evidence/` 不是通用测试目录；它保存 mainline、mechanisms 和 model-assist 的精选结果，raw run 和服务日志仍在 `runs/`。
