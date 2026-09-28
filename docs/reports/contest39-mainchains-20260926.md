# Contest39：两条 12 轮 DSL 主链

合同：`mechanism_simple_v2`。入口：`scripts/run_contest_dsl_mainchains.sh`。

## 运行

在 `/home/qcrs/statebus/os` 下执行，两个配置请顺序运行：

```bash
SB_OUT="runs/contest39-sbfull-$(date +%Y%m%d_%H%M%S)-$$"
bash scripts/run_contest_dsl_mainchains.sh --variant SB-FULL --output "$SB_OUT"

TEXT_OUT="runs/contest39-ptext-$(date +%Y%m%d_%H%M%S)-$$"
bash scripts/run_contest_dsl_mainchains.sh --variant P-TEXT --output "$TEXT_OUT"
```

每条命令顺序执行 Finance 12 轮、Service Ops 12 轮，共 24 个计划槽。
每个 family 分别保存 Memory、历史、ledger、provider journal、scorer 和指标。
某链失败后，该链余下轮次为 `blocked_by_prior_failure`，另一 family 仍运行。
全部成功才返回 0；业务/机制失败返回非零。已存在的 output 拒绝覆盖，不自动重试或切换合同。
运行期间不要修改源码或任务合同。中断后保留证据，不拼接成完整连续成绩。

```bash
bash scripts/run_contest_dsl_mainchains.sh --help
bash scripts/run_contest_dsl_mainchains.sh --variant SB-FULL --dry-run
/home/qcrs/statebus/conda-envs/statebus_host/bin/python scripts/show_contest_dsl_results.py "$SB_OUT"
```

`--dry-run` 不调用 Docker/GPU/provider，不启动服务，也不创建运行目录。
诊断可显式添加 `--family finance` 或 `--family service_ops`，仍运行该 family 的完整 12 轮。
底层 CLI 保留旧 `default` 合同，只有显式 `--profile mechanism_simple_v2` 才选择新任务。
旧入口的三轮/offline 默认值未被暗改；新的 wrapper 固定传入 `--rounds 12 --mode live`。

## 环境与预算

- 复用 `statebus-runtime`，容器源码 `/workspace/statebus/os`。
- 解释器 `/home/qcrs/statebus/conda-envs/statebus_host/bin/python`。
- GPU2 上 `/data/models/Qwen3-32B`，served model `qwen3-32b`，`http://127.0.0.1:53334/v1`，8192 context。
- GPU1 映射为容器内 `cuda:0`，Embedding `/statebus/models/Qwen3-Embedding-0.6B`。
- Executor 2048、Summarizer 1536，一次 Executor repair；无动态预算、压缩或 CodeAct fallback。
- wrapper 只检查和复用服务；如需准备环境，另行使用现有 `scripts/start_statebus.sh qwen3-32b-gpu2-u050 --embedding-gpu 1 --container-name statebus-runtime`。
- `embedding-preflight.json` 为复用的单次 encode 探针，设备/维度用于环境证据；其中通用 profile 的 `budget` 不是 DSL 请求预算，真实请求配置以各 slot `manifest.json`/`provider.jsonl` 为准。

## 实现边界

- 两业务完整 R01–R12；聚合、差额、历史序列、预算/计划关联均在现有 Runtime DSL 执行。
- R03 消费前两轮验证结果；R04/R05 使用真实前轮 baseline 并保留当前期基础量。
- R10 仅汇集每个物理期间的一个 verified producer，分别覆盖六个月和八周；不重新计算原始数据，不注入 scorer 值。
- Service 计划表按 `SEED=20260924` 和公开规则冻结，O08/O09/O11 使用 `hourly + plan`，不再发布 latency samples。
- R08/R09/R11 的方法、输入 schema、输出合同相同；v1/v2 合同分开。R11 为同源重新计算审计，不称新数据实验。
- R12 使用现有 Executor → Memory → Summarizer 授权读取，核对结构化值并生成自己的报告；不复制 producer 自然语言报告。
- Planner 为确定性公开计划，Retriever 为真实注册检索，Executor 为模型生成 DSL 或经过 Runtime 兼容门的 replay，Summarizer 为模型生成的结构化事实报告；没有伪装所有角色都发 LLM 请求。
- 报告校验仍覆盖每个字段、数值、实体、来源及完整限定语。公开报告结构避免要求模型在 prose 里重复 `key=value`；确定性渲染只处理已经严格验证的模型输出。
- scorer 仍独立读取 raw CSV。schema 错误现在明确标出 missing/unexpected 字段，供原有一次 repair 使用。

## 结果文件

`$OUT/{finance,service_ops}/ledger.json` 各保留 12 行。
`metrics/{product,communication,state,memory,codeact}.{json,csv,md}` 为逐项表，`metrics/summary.json` 包含清晰分母及包含 producer/repair/consumer 的整链成本。
`slots/Fxx|Oxx/` 保存输入 lineage、program/hash、provider、rows、scorer、report、Runtime telemetry、Memory/state receipts。

通信指标来自真实 in-process text/typed receiver 边界；没有 wire 观测，wire bytes 保持 missing，不能据此宣称 wire 节省。
Embedding 为实际 mmap 非文本矩阵跨 PID 消费，非 hidden-state/KV transfer；`read_bytes` 和 `hydrate_bytes` 是同次读的别名，不相加。
普通轮 Memory 无命中或 state `no_effect` 不判业务失败；R11/R12 的实际 replay/消费单独 gate。
`business_quality` 与机制 gate 分开，hit rate 与 actual-use rate 分开；完整产品差异不归因于单一机制。

## 验证证据

证据根：`runs/contest39-validation-20260926/`。旧失败目录保留，不改写成新成功。

- `final-targeted-tests.log`：42 项通过，包含旧接线回归、新合同、scorer 错误诊断、报告反例、wrapper dry-run 和真实退出码传递的 mock 测试。
- 最终版源码于 16:47 更新后，`delivery-targeted-tests-20260926-1.log` 在受限 sandbox 中出现 2 项本地 socket 权限失败、40 项通过；同一组测试经授权在 sandbox 外重跑（`delivery-tests-20260926-2/`），42 项全部通过。此处不是业务/Runtime 算术失败。
- `final-tests/test_full_12_round_runtime_sim0/finance-SB-FULL`：12/12 offline。
- `final-tests/test_full_12_round_runtime_sim1/service_ops-SB-FULL`：12/12 offline。
- `final-tests/test_full_12_round_runtime_sim2/finance-P-TEXT`：12/12 offline。
- `final-tests/test_full_12_round_runtime_sim3/service_ops-P-TEXT`：12/12 offline。
- 上述 offline 无 provider 请求；不能作为连续 live 成绩。
- `live-finance-first4`：F01 schema 命名错误，一次 repair 未修正；保留成本。
- `live-finance-schema-fix`：F01 算术/schema 通过，报告因漏写实体/期间/完整前缀未通过；促成结构化报告合同修复，保留成本。
- `live-finance-jsonschema-20260926-1`：最新合同下的真实 F01 通过（scorer、结构化报告和机制 gate 均通过）；一次 Executor repair，3 次模型请求，5388 provider tokens，113041.65 ms E2E。12 个计划槽保留，只有 F01 为 success，F02–F12 为 not_started，不能算 12 轮 live 通过。
- 上述 live F01 观察到 5 条 in-process typed handoff、非文本 embedding matrix 20480 bytes 的 publish/跨 PID transfer/consume/release，实际 read_bytes=20480，downstream_effect=no_effect；wire bytes 未观测。Memory query=1、candidate=0、actual consumption=0，不能作为 Memory 复用收益证据。

历史关联、跨表关联、R11 live replay、R12 live 跨 Agent 消费仍待操作者运行连续主链验证。完整 24/48 slots live campaign 留给操作者启动；未跑完的轮次不宣称通过。
