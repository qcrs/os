# Qwen3-8B KV Execution Progress

日期：2026-07-10

## 本次执行范围

按 `20_kv_execution_prompt_20260710.md` 的当前修正版，先完成：

1. `Qwen3-8B` 外部 vLLM 启动
2. `statebus-dev-qcrs` root 容器内 `source /usr/local/bin/activate_statebus_container.sh`
3. `local_vllm` smoke 验证
4. `formal/dev` mini formal `max-cases=5` 验证

当前未执行：

- `Qwen3-32B` full formal
- 后续 KV treatment 组

原因：当前更大卡资源仍被占用，先完成 8B 链路与容器内验证。

## 实际命令

宿主机启动 vLLM：

```bash
STATEBUS_VLLM_CUDA_VISIBLE_DEVICES=1 \
STATEBUS_VLLM_PORT=53333 \
./scripts/start_vllm_qwen3_8b_prefix_cache.sh
```

容器内 smoke：

```bash
./scripts/run_v2_local_vllm_container_check.sh
```

容器内 mini formal 5 cases：

```bash
STATEBUS_LOCAL_VLLM_CHECK_RUN_ID=v2-local-vllm-check-20260710_mini5_final \
./scripts/run_v2_local_vllm_container_check.sh \
  /bin/bash -lc \
  '/usr/bin/python3 -m v2.benchmark.live_runner \
    --suite formal \
    --benchmark-tier dev \
    --role-path-mode local_vllm \
    --embedding-mode deterministic \
    --max-cases 5 \
    > /statebus/runs/v2-local-vllm-check-20260710_mini5_final/mini_formal_5.stdout.json'
```

## 环境事实

- vLLM env: `/home/qcrs/statebus/conda-envs/vllm-qwen-cu121`
- Python: `3.11`
- vLLM: `0.7.3`
- Torch: `2.5.1+cu121`
- 容器网络口径：`docker/compose.yaml` 当前使用 `network_mode: host`
- root 容器激活脚本：`/usr/local/bin/activate_statebus_container.sh`
- `Qwen3` 本地 OpenAI-compatible 配置已显式关闭 thinking：
  - `extra_body.chat_template_kwargs.enable_thinking=false`

补充事实：

- 当前 `vllm==0.7.3` 的 `/health` probe 可用，但 body 可能为空；以 `curl -sf .../health` exit code `0` 作为 ready 判据。

## 实际结果

### 1. Smoke

`local_vllm` smoke 已通过，关键输出：

```text
ok=true
role_path_mode=local_vllm
embedding_mode=deterministic
quality_floor_pass=True
```

### 2. Mini formal (5 cases)

artifact:

- run root:
  `/home/qcrs/statebus/runs/v2-local-vllm-check-20260710_mini5_final/`
- raw stdout json:
  `/home/qcrs/statebus/runs/v2-local-vllm-check-20260710_mini5_final/mini_formal_5.stdout.json`

核心结果：

- `selected_case_count = 5`
- `available_case_count = 25`
- `L3_case_count = 5`
- `L3_quality_pass_count = 5`

四层都通过：

- `L0 quality_floor_pass_count = 5`
- `L1 quality_floor_pass_count = 5`
- `L2 quality_floor_pass_count = 5`
- `L3 quality_floor_pass_count = 5`

`protocol L3` 相对 `text L0`：

- total tokens: `8710 vs 11231`，delta `-2521`
- prompt tokens: `5967 vs 7516`，delta `-1549`
- control bytes: `2285 vs 2357`，delta `-72`
- quality pass delta: `0`

这说明当前 `Qwen3-8B + local_vllm + root container` 路径下：

1. 结构化 lane 没有丢失 mini formal 质量；
2. token/prompt token/control bytes 都低于 text lane；
3. 该结果已经是容器内、root 激活、外部 vLLM 的真实运行结果。

### 3. Isolated mini formal (5 cases, self-contained bundle)

为避免继续复用共享 `v2-live` 运行目录，又执行了一次显式隔离 run：

```bash
./scripts/run_v2_local_vllm_mini_formal.sh
```

artifact:

- host-visible run root:
  `/home/qcrs/statebus/runs/v2-local-vllm-mini-formal-20260710_173349/`
- raw stdout json:
  `/home/qcrs/statebus/runs/v2-local-vllm-mini-formal-20260710_173349/mini_formal.stdout.json`
- summary json:
  `/home/qcrs/statebus/runs/v2-local-vllm-mini-formal-20260710_173349/mini_formal.summary.json`
- suite report:
  `/home/qcrs/statebus/runs/v2-local-vllm-mini-formal-20260710_173349/runtime/benchmark_reports/v2-local-vllm-mini-formal-20260710_173349-formal-suite.json`

按 `mini_formal.summary.json`：

- `selected_case_count = 5`
- `available_case_count = 25`
- `L0 quality_floor_pass_count = 5`
- `L1 quality_floor_pass_count = 5`
- `L2 quality_floor_pass_count = 5`
- `L3 quality_floor_pass_count = 5`

`protocol L3` 相对 `text L0`：

- total tokens: `8710 vs 11231`，delta `-2521`
- prompt tokens: `5967 vs 7516`，delta `-1549`
- control bytes: `2455 vs 2357`，delta `+98`

说明：

1. 这次 run 的 bundle 已完全落在单独 run root 下，不再依赖共享 `v2-live` 目录；
2. 质量结果与前一轮 5-case mini formal 一致，四层全部通过；
3. token 与 prompt token 仍低于 text lane；
4. `control bytes` 在隔离 run 中不再低于 text lane，而是高出 `98`，因此当前更稳妥的表述应是：
   - `Qwen3-8B + local_vllm + root container` 路径已验证可运行；
   - mini formal 下 protocol lane 保持质量且降低了 token / prompt token；
   - control bytes 优势在当前 8B 证据上并不稳定，后续应以 `32B` 与 KV treatment 组补充确认。

### 4. 后续直接切 32B 的准备已补齐

为避免后续再手改 `model/base_url/port` 组合，已补两个执行入口：

1. source 型 profile：

```bash
source deploy/activate_statebus_local_vllm_profile.sh qwen3-8b
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b
```

它会统一设置：

- `STATEBUS_VLLM_MODEL_PATH`
- `STATEBUS_VLLM_SERVED_MODEL_NAME`
- `STATEBUS_LOCAL_VLLM_MODEL`
- `STATEBUS_VLLM_PORT`
- `STATEBUS_LOCAL_VLLM_BASE_URL`
- `STATEBUS_LOCAL_VLLM_HEALTH_URL`
- `STATEBUS_VLLM_CUDA_VISIBLE_DEVICES`

2. 通用 formal wrapper：

```bash
scripts/run_v2_local_vllm_formal_suite.sh
```

因此后续切到 `32B` 的推荐命令形态是：

```bash
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b
scripts/start_vllm_qwen3_32b_prefix_cache.sh

STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID=v2-local-vllm-qwen3-32b-formal \
STATEBUS_LOCAL_VLLM_FORMAL_BENCHMARK_TIER=formal \
STATEBUS_LOCAL_VLLM_FORMAL_MAX_CASES= \
scripts/run_v2_local_vllm_formal_suite.sh
```

如果空闲卡不是 profile 默认值，再单独覆盖：

```bash
export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES=<free_gpu_index>
```

## 当前结论

`Qwen3-8B` 这条过渡执行路径已经打通，可作为：

1. Phase 1 的 container-root smoke 证据；
2. Phase 1 的 mini formal dev 证据；
3. 后续切换到 `Qwen3-32B` 之前的稳定 fallback 路径。

下一步应在更大卡空闲后执行：

1. `Qwen3-32B` single-card full formal
2. KV treatment 组
3. cache-friendly / cache-hostile 对照
