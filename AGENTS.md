# StateBus OS Workspace Instructions

## Scope and source of truth

- Active checkout: `/home/qcrs/statebus/os`.
- Make code, test, and deployment changes in this checkout unless the user
  explicitly asks to modify the sibling project checkout.
- The competition brief and design context live in
  `/home/qcrs/statebus/project/docs/reference/题目.md`.
- The sibling project's deployment material is useful reference only:
  `/home/qcrs/statebus/project/docker` and
  `/home/qcrs/statebus/project/deploy`.
- `/home/qcrs/statebus/project` is a separate worktree and may contain user
  changes. Do not edit it, reset it, or copy its dirty worktree back into this
  checkout without explicit approval.
- For commands against this checkout, prefer its `README.md`, `docker/README.md`,
  `deploy/`, and `scripts/` over stale historical notes in `docs/experiments/`.

## Intended runtime

- Application runtime: reuse the existing `statebus-dev-qcrs` openEuler 24.03
  LTS-SP3 Docker container created from `/home/qcrs/statebus/project/docker`.
  Do not create a second container or recreate this one from the current
  checkout unless the user explicitly asks for that change.
- Model serving: host-side vLLM, OpenAI-compatible API at
  `http://127.0.0.1:53334/v1`.
- The application container uses host networking and does not request a GPU;
  Embedding is intentionally configured for CPU so it does not compete with
  vLLM.
- Model: `/data/models/Qwen3-32B`, BF16, served name `qwen3-32b`.
- Default serving target: physical GPU `2`, single-GPU tensor parallelism.
  `CUDA_VISIBLE_DEVICES=2` exposes that physical card as logical device 0
  inside the vLLM process; do not confuse the two indices.

## Required reading before substantial work

Read these files before changing runtime behavior or benchmark semantics:

1. `README.md`
2. `docker/README.md`
3. `deploy/activate_statebus_host.sh`
4. `deploy/activate_statebus_local_vllm_profile.sh`
5. `scripts/vllm/start_qwen3_32b.sh`
6. `/home/qcrs/statebus/project/docs/reference/题目.md`

Keep claims bounded by actual validation. In particular, do not describe
embedding/state references as hidden-state or KV-cache tensor transfer. Native
vLLM prefix caching is an engine-local serving feature.

## Host activation

From this checkout:

```bash
cd /home/qcrs/statebus/os
source ./deploy/activate_statebus_host.sh
```

The script activates the user-owned environment at
`$HOME/statebus/conda-envs/statebus_host` and prepares the normal StateBus
directories. The equivalent script under
`/home/qcrs/statebus/project/deploy/` is for the sibling project checkout; do
not source it while running this checkout unless `STATEBUS_LLM_CONFIG_FILE` and
`PYTHONPATH` are intentionally overridden.

The existing vLLM environment is expected at
`$HOME/statebus/conda-envs/vllm-qwen-cu121`. The current known package baseline
is Python 3.11, vLLM 0.9.2, PyTorch 2.7.0+cu126, Transformers 4.52.4, and
Tokenizers 0.21.4. Verify rather than assuming a package is installed.

## Preflight checks

Do these checks before starting a model or container:

```bash
command -v conda docker nvidia-smi
nvidia-smi -L
nvidia-smi -i 2 --query-gpu=index,name,memory.total,memory.used,memory.free --format=csv
test -r /data/models/Qwen3-32B/config.json
test -x "$HOME/statebus/conda-envs/vllm-qwen-cu121/bin/vllm"
docker ps
```

If `nvidia-smi` cannot communicate with the driver, stop at preflight; do not
claim that vLLM is running. If `docker ps` reports a Docker socket permission
error, fix the host's Docker access or use an authorized operator session before
trying to build or start the openEuler container. Never work around this by
creating a second untracked container runtime.

## Safe first vLLM boot

The first boot is deliberately conservative: one request sequence, 4096-token
context, 4096 batched tokens, eager execution, and 0.82 GPU memory utilization.
This reduces KV-cache pressure while confirming that the 32B weights load on
GPU 2. The tracked defaults and `deploy/vllm.env.local` should agree.

Create local configuration once (these files are ignored by Git):

```bash
[[ -e deploy/vllm.env.local ]] || cp deploy/vllm.env.example deploy/vllm.env.local
[[ -e deploy/statebus_llm.yaml.local ]] || cp deploy/statebus_llm.local_vllm.example deploy/statebus_llm.yaml.local
```

The effective baseline is:

```bash
export STATEBUS_VLLM_ENV_PREFIX="$HOME/statebus/conda-envs/vllm-qwen-cu121"
export STATEBUS_VLLM_MODEL_PATH=/data/models/Qwen3-32B
export STATEBUS_VLLM_SERVED_MODEL_NAME=qwen3-32b
export STATEBUS_VLLM_HOST=127.0.0.1
export STATEBUS_VLLM_PORT=53334
export STATEBUS_VLLM_CUDA_VISIBLE_DEVICES=2
export STATEBUS_VLLM_TENSOR_PARALLEL_SIZE=1
export STATEBUS_VLLM_DTYPE=bfloat16
export STATEBUS_VLLM_MAX_MODEL_LEN=4096
export STATEBUS_VLLM_MAX_NUM_SEQS=1
export STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS=4096
export STATEBUS_VLLM_GPU_MEMORY_UTILIZATION=0.82
export STATEBUS_VLLM_ENFORCE_EAGER=1
export STATEBUS_VLLM_ENABLE_PREFIX_CACHING=1
```

When GPU 2 has an unrelated workload occupying memory, keep the tracked
defaults but add a local-only offload override before starting the service:

```bash
export STATEBUS_VLLM_CPU_OFFLOAD_GB=8
```

CPU offload trades throughput for headroom and is preferable to killing another
user's GPU process. Remove the override only after a clean load with enough
free memory has been observed.

Start and inspect the managed service:

```bash
scripts/vllm/manage_qwen3_32b.sh print-config
scripts/vllm/manage_qwen3_32b.sh start
scripts/vllm/manage_qwen3_32b.sh health
scripts/vllm/manage_qwen3_32b.sh status
```

The service can take several minutes to load the 17 weight shards (the manager
waits up to 900 seconds). Keep the log open in a second terminal when
diagnosing a failure:

```bash
scripts/vllm/manage_qwen3_32b.sh logs
```

Only after the 4096-token profile is healthy should a user try 8192. Increase
`STATEBUS_VLLM_MAX_MODEL_LEN` and
`STATEBUS_VLLM_MAX_NUM_BATCHED_TOKENS` together, then restart and re-check
memory. If loading still fails, first confirm GPU 2 is not occupied; then use a
small explicit `STATEBUS_VLLM_CPU_OFFLOAD_GB` value (for example `4`) rather
than raising the GPU memory limit. Do not kill unrelated GPU processes.

Stop only the process owned by the manager:

```bash
scripts/vllm/manage_qwen3_32b.sh stop
```

## Existing openEuler container

The canonical container is already managed by the sibling project checkout. It
mounts `/home/qcrs/statebus/project` at `/workspace/statebus/project`; it does
not mount this `/home/qcrs/statebus/os` checkout. Reuse it for the validated
openEuler runtime and project-side integration checks:

```bash
docker inspect statebus-dev-qcrs --format '{{.State.Status}} {{.Config.Image}} {{.HostConfig.NetworkMode}}'
docker exec -it statebus-dev-qcrs bash
```

Inside the container, load the project-side environment:

```bash
source /workspace/statebus/project/docker/activate_statebus_container.sh
cd /workspace/statebus/project
python3 -m v2.runtime.smoke --role-path-mode local_vllm
```

Do not run `docker compose up`, `--force-recreate`, or `build` from this
checkout as a routine step: the current checkout's Compose file uses the same
container name and could replace the sibling project's working container. If
the container is ever absent, recover it from the sibling project explicitly:

```bash
cd /home/qcrs/statebus/project
docker compose --env-file docker/.env -f docker/compose.yaml up -d --no-build
```

The container uses `network_mode: host`, so it reaches the host vLLM at
`127.0.0.1:53334`. A failed `/health` probe is an environment/service failure,
not evidence that the StateBus runtime is broken.

For code that is being changed in this `os` checkout, run host-side tests with
the current checkout's Conda activation. Only use the existing container after
the source checkout has been deliberately made visible to it.

## Tests and local-only checks

For tests that do not need a live model service:

```bash
source ./deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q
```

For the live service and container path:

```bash
scripts/run_local_vllm_container_check.sh
```

For longer formal runs, use `scripts/run_local_vllm_formal_suite.sh` only after
the short smoke passes. Keep run outputs under the configured `runs/` directory
and do not overwrite historical evidence.

## Current setup observation

On 2026-09-04, `/data/models/Qwen3-32B`, the host Conda environments, the
NVIDIA driver, and Docker were present. GPU 2 is an A100 80 GB with an unrelated
training process using about 7.7 GiB, and the existing `statebus-dev-qcrs`
container is running from the sibling `/home/qcrs/statebus/project` checkout.
The first managed vLLM attempt used the conservative 4096-token profile but
exited while loading shard 14/17; its log contained no Python traceback or OOM
message. Treat the service as unvalidated until a later start reaches
`/health` and `/v1/models`; do not kill the unrelated GPU process or recreate
the shared container.
