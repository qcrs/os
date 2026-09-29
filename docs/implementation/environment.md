# 环境与配置

当前 checkout 的 host-side Python 环境入口：

~~~bash
cd /home/qcrs/statebus/os
source ./deploy/activate_statebus_host.sh
python -c 'import statebus; print(statebus.__file__)'
~~~

该环境用于 Runtime、Studio backend、offline tests 和 dispatcher；它不包含 vLLM。

vLLM 使用独立环境，由 scripts/vllm/manage_qwen3_32b.sh 管理。启动前必须检查 NVIDIA driver、空闲或获准的 GPU、模型路径和 /health、/v1/models；默认首轮 profile 以 os/AGENTS.md 为准，不能用旧报告中的 GPU 或 context 假设当前服务。

容器、模型服务和 host Runtime 的 ownership 分开：

| 层 | 位置 | 作用 |
| --- | --- | --- |
| host Runtime | statebus_host + src/statebus | tests、Studio backend、launcher |
| host vLLM | vllm-qwen-cu121 + /data/models/Qwen3-32B | OpenAI-compatible model service |
| openEuler container | 已有 statebus-dev-qcrs | sibling project 管理的运行参考；本 checkout 不例行替换 |

离线检查：

~~~bash
source deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/unit tests/integration tests/benchmarks
tests/benchmarks/run_statebus.sh mainline-24 --dry-run
~~~

Live runner 可能产生 runs、服务日志和模型请求；运行前阅读 AGENTS.md 的 GPU、容器、输出目录规则。
