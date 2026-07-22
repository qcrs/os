# Contest Rebuild 环境准备

日期：`2026-07-22`

这套 profile 只完成正式实验前的环境准备。它不访问本地服务或外部网络，不发模型请求，不下载数据，也不执行 Docker、cache reset、服务重启或 openEuler 验证。

## 1. 激活与静态检查

在仓库根目录执行：

```bash
source deploy/activate_statebus_contest_rebuild.sh
python scripts/check_contest_rebuild_environment.py
```

激活脚本会先复用 `deploy/activate_statebus_host.sh` 激活 host Python 环境，再加载可选的 `deploy/statebus_contest_rebuild.env.local` 覆盖。无本机覆盖时，仓库默认值即可用于当前主机。

机器可读输出：

```bash
python scripts/check_contest_rebuild_environment.py --json
```

静态检查只读取环境变量和本地文件系统。报告中的 `offline_only=true` 和 `external_actions_performed=false` 是固定边界；所有 live 项单独列为 `deferred`。

## 2. 已固定的本机配置

| 对象 | 配置 |
| --- | --- |
| profile | `contest-rebuild-20260722` / version `1` / phase `prepare` |
| StateBus host env | `$HOME/statebus/conda-envs/statebus_host` |
| vLLM env | `$HOME/statebus/conda-envs/vllm-qwen-cu121` |
| vLLM version | `0.9.2` |
| model/tokenizer | `/data/models/Qwen3-32B` |
| physical GPU | `1` (`CUDA_VISIBLE_DEVICES=1`) |
| served model | `qwen3-32b` |
| API | `http://127.0.0.1:53334/v1` |
| health | `http://127.0.0.1:53334/health` |
| metrics | `http://127.0.0.1:53334/metrics` |
| StateBus LLM config | `deploy/statebus_llm.contest_rebuild.yaml` |
| Qwen request mode | four roles explicitly `enable_thinking=false` |
| persistent service | `statebus-vllm-qwen3-32b-allcap` |
| launcher | `scripts/start_vllm_qwen3_32b_latent.sh` |
| lifecycle | `scripts/manage_vllm_qwen3_32b_allcap.sh` |
| request discipline | serialized, concurrency `1` |
| container identity | activation-time `STATEBUS_UID` / `STATEBUS_GID` |

模型是只读输入，因此保留现有 `/data/models` 路径。cache、filing raw/canonical、private gold、logs、runs 和 openEuler validation 输出全部位于用户拥有的 `$HOME/statebus` 树内。

常驻服务固定使用 vLLM `0.9.2` 的 V0 engine，因为 latent worker extension 需要 direct V0 `collective_rpc`。服务同时打开 APC、prompt embeds、latent middleware、`max_logprobs=20`、request ID headers，并注入已审计支持 `0.7.3/0.9.2` 的 exact prefix query/hit counter exporter。`VLLM_NO_USAGE_STATS=1` 固定关闭与推理无关的匿名 usage telemetry。`/metrics` 由 vLLM 自动暴露；实际 endpoint 名、labels 和单位仍必须等后续 live 核对后才能冻结。

启动配置与某次实验的 treatment 是两层。常驻服务保留全部能力，但 prepare profile 仍令 Prefix、Logit 和 Latent treatment 默认关闭，因此不会因为服务能力全开而把未授权机制带进实验。

Thinking 同样属于请求合同，不是 vLLM 服务启动能力。正式 `Planner`、`Retriever`、`Executor`、`Summarizer` 请求必须同时满足：`json_output=true`、`temperature=0.0`、`extra_body.chat_template_kwargs.enable_thinking=false`，且不得用 `reasoning_effort` 或 `request_kwargs.extra_body` 覆盖。静态 preflight 会 fail closed 核对这四个角色。历史落盘 run 也使用 non-thinking 配置，因此开启 thinking 会形成新的实验 treatment，不能混入历史比较或正式 P/L/R 聚合。独立能力探针若直接调用 API，也必须在请求体中显式携带同一个 `enable_thinking=false`。

## 3. 常驻 vLLM 生命周期

固定服务名：`statebus-vllm-qwen3-32b-allcap`。

先做纯本地配置检查：

```bash
scripts/manage_vllm_qwen3_32b_allcap.sh check
```

需要替换当前 `Qwen3-32B:53334` 进程时，只执行一次：

```bash
scripts/manage_vllm_qwen3_32b_allcap.sh restart
```

该命令按当前用户、模型路径、端口和 `vllm serve` 参数精确定位旧进程，先发 `TERM`，超时才发 `KILL`，随后通过 `nohup` 启动 all-cap 服务。启动是异步的，不会自动请求 `/health`、`/metrics` 或模型 endpoint。

只读状态和日志：

```bash
scripts/manage_vllm_qwen3_32b_allcap.sh status
tail -F "$HOME/statebus/logs/statebus-vllm-qwen3-32b-allcap.log"
```

## 4. 默认关闭语义

环境准备阶段固定：

```text
STATEBUS_PREFIX_POLICY=off
STATEBUS_PREFIX_ALIGNMENT_MODE=independent
STATEBUS_LOGIT_POLICY=off
STATEBUS_LATENT_MODE=off
STATEBUS_LATENT_HANDOFF_MODE=off
STATEBUS_LATENT_PROMPT_EMBEDS_ENABLED=false
STATEBUS_PREFIX_FEEDBACK_ADAPTIVE=0
```

这里的 latent 三项是实验侧使用策略，不是服务启动 capability。它们由激活脚本强制覆盖为关闭，不能通过 local override 打开。Prefix/Logit 只有进入对应已注册 lane 后才可单独改变；prepare 静态检查会拒绝非 `off` 值。cache namespace/epoch 在准备阶段必须为空，避免沿用旧服务身份。

激活时还会清空旧 profile 可能遗留的 `STATEBUS_VLLM_NUM_GPU_BLOCKS_OVERRIDE`、`STATEBUS_VLLM_CPU_OFFLOAD_GB` 和 `STATEBUS_VLLM_KV_CACHE_DTYPE`，并默认固定物理 GPU 1（`CUDA_VISIBLE_DEVICES=1`）。需要这些压力阀或 GPU 本机覆盖时只能通过 `STATEBUS_CONTEST_VLLM_*` 重新声明，不能隐式继承另一个 profile。

## 5. 独立动作 gate

以下 gate 当前全部是 `0`：

| Gate | 尚未执行的动作 |
| --- | --- |
| `STATEBUS_CONTEST_ALLOW_METRICS_CHECK` | 读取并核对 `/metrics` schema |
| `STATEBUS_CONTEST_ALLOW_TOP_LOGPROBS_PROBE` | 一次固定闭集 `top_logprobs` 请求 |
| `STATEBUS_CONTEST_ALLOW_FILING_DOWNLOAD` | rights review 后下载和冻结公开 filing |
| `STATEBUS_CONTEST_ALLOW_FORMAL_EXPERIMENTS` | 正式 P/L/R 请求与聚合 |
| `STATEBUS_CONTEST_ALLOW_COLD_CACHE` | 建立 cold/independent engine epoch |
| `STATEBUS_CONTEST_ALLOW_SERVICE_RESTART` | 停止、替换或重启服务 |
| `STATEBUS_CONTEST_ALLOW_OPENEULER_VALIDATION` | 最终 openEuler build/run/validation |

一个 gate 的授权不传递给其他 gate。cold cache 若依赖重启，两个 gate 都必须显式开启。它们是 contest runner 的前置合同，不是 shell 级全局沙箱；直接调用旧诊断脚本仍可能执行其原有动作，因此未来 live 操作必须从受 gate 检查的新入口发起。

## 6. 已创建的持久目录

```text
$HOME/statebus/
├── caches/contest-rebuild/public-filings/raw/
├── logs/contest-rebuild-v1/
├── runs/contest-rebuild-v1/
│   └── openeuler-final/
└── work/contest-rebuild/
    ├── data/public-filings/canonical/
    └── gold-private/
```

下载 gate 关闭时 raw 目录保持空是正常状态；静态 preflight 只要求目录存在、可写且没有越出 `$HOME/statebus`。

## 7. 尚未形成的证据

激活 profile 和创建管理命令不会改变当前已经运行的 `53334` 进程；只有人工执行一次 `restart` 后，新 capability profile 才会生效。新进程实际暴露哪些 counters，仍必须以后通过只读服务核对确认。现在仍不能声称：

- 当前 `/metrics` counter schema 已验证；
- 当前服务支持正式闭集 `top_logprobs` contract；
- filings 已获取、许可或冻结；
- P/L/R、cold-cache 或 openEuler 验证已经运行；
- A0 已通过，或任何 Prefix/Logit 收益已经成立。

本次只结算“本地静态依赖和 fail-closed 配置已准备”。
