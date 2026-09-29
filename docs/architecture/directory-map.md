# 目录职责

以下路径是当前 `os` checkout 的入口。表中的“职责”描述实际内容，不表示待完成的迁移计划。

| 路径 | 职责 | 事实来源 |
| --- | --- | --- |
| `src/statebus/` | Python Runtime、contracts、control、state、memory、retrieval、benchmark、Studio backend | 当前 package 和 import |
| `src/statebus/contracts/` | Task、Plan、Capability、Artifact、State、KV、Logit 等合同 | contract modules |
| `src/statebus/control/` | Protobuf/UDS message、admission 和 subprocess transport | `statebus_control.proto`、`transport.py` |
| `src/statebus/runtime/` | compiler、dispatcher、mainline、attempt、gate、replay、telemetry | Runtime modules |
| `src/statebus/state/` | semantic、memory、logit state 和 store lifecycle | state modules |
| `src/statebus/memory/` | embedding、candidate index、compatibility 和 store | memory modules |
| `src/statebus/benchmark/` | 主链、机制实验、utility runner 和样本逻辑 | benchmark modules |
| `src/studio-ui/` | React/TypeScript Studio frontend | `package.json`、`src/` |
| `tasks/` | 任务 manifest、公开输入和 validator | task manifests |
| `tests/unit/` | 离线合同、Runtime、Memory、CodeAct、Logit/APC/KV 测试 | test files |
| `tests/integration/` | Runtime、固定主链和 Studio 组合测试 | test files |
| `tests/benchmarks/` | benchmark contract tests 和稳定 dispatcher | test files、`run_statebus.sh` |
| `tests/evidence/` | 三条精选结果链的 Markdown/JSON 汇总 | evidence files |
| `scripts/` | 服务检查、主链/机制/utility launcher、诊断和报告工具 | shell/Python scripts |
| `runs/` | raw run、服务日志和运行材料 | run directories |

`tasks/` 不是 Runtime 源码；`src/statebus/benchmark/samples/` 是可复用 fixture、gold 和 compiled input，不等于全部任务定义。
