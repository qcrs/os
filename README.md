# StateBus Project

This directory is the host-side development repo for the StateBus implementation.

Current strategy:

- Develop on the current Linux host.
- Use the isolated conda env under `$HOME/statebus/conda-envs/statebus_host`.
- Keep models, caches, logs, runs, and state artifacts under `$HOME/statebus`.
- Finish `Phase 0` to `Phase 4` here.
- Use openEuler VM only for posterior validation and final delivery checks.

## Quick Start

```bash
cd /home/qcrs/statebus/project
source deploy/activate_statebus_host.sh
python -m pytest -q
```

## LLM API Config

`Planner` and `Summarizer` now use a shared OpenAI-compatible client abstraction.

- Main role/provider config: `deploy/statebus_llm.yaml.local`
- YAML template: `deploy/statebus_llm.yaml.example`
- Secret/override file: `deploy/statebus_llm.env.local`
- Env template: `deploy/statebus_llm.env.example`

Recommended split:

```bash
cp deploy/statebus_llm.yaml.example deploy/statebus_llm.yaml.local
cp deploy/statebus_llm.env.example deploy/statebus_llm.env.local
```

Then fill `STATEBUS_LLM_API_KEY` in `deploy/statebus_llm.env.local`.

Role behavior such as `provider`, `model`, `json_output`, `max_tokens`, and
vendor-specific `extra_body` now lives in the YAML file, so switching between
OpenAI-compatible models should not require Python changes.

## Model Paths

- Embedding: `/home/qcrs/statebus/models/Qwen3-Embedding-0.6B`
- Optional reranker: `/home/qcrs/statebus/models/Qwen3-Reranker-0.6B`

## Current Scope

Current implementation focus:

- `runtime`
- `protocol`
- `statepool`
- `memory`
- `agents`
- `eval`

Deferred until later:

- `nsjail`
- privileged container workflows
- openEuler-only validation
- final sandbox isolation path

## Current Engineering Scope

Current host-feasible implementation status:

- `protocol` mode uses checked-in `.proto + pb2` control frames
- `StateRef` supports `mmap` and Python `shared_memory`
- shared memory is a real benchmark option, not just a dormant backend
- `Executor` is now tool-registry-based with a lightweight subprocess fallback
- `Executor` can also run as an external multi-process UDS sample transport
- non-text state now includes `FEATURE_BUNDLE` in addition to `EMBEDDING`

Scope notes:

- the current subprocess executor is a host-side fallback, not `nsjail`
- the current UDS executor path is a real sample transport, not the final distributed runtime
- hidden-state / KV-style intermediate representations are still deferred
- Docker / openEuler / stronger sandboxing stay in the later validation phase

See [docs/constraints/current_feature_scope.md](docs/constraints/current_feature_scope.md) for the precise boundary between what is already host-feasible and what must be deferred.

## Benchmark Examples

Default `mmap` mainline:

```bash
source deploy/activate_statebus_host.sh
python -m eval.runner --repeat 1 --llm-mode deterministic --out /tmp/statebus_mmap_demo
```

Shared-memory benchmark route:

```bash
source deploy/activate_statebus_host.sh
python -m eval.runner \
  --repeat 1 \
  --llm-mode deterministic \
  --statepool-backend shared_memory \
  --embed-state-backend shared_memory \
  --out /tmp/statebus_shm_demo
```

External `UDS` executor sample transport:

```bash
source deploy/activate_statebus_host.sh
python -m eval.runner \
  --repeat 1 \
  --modes protocol \
  --llm-mode deterministic \
  --executor-transport uds \
  --out /tmp/statebus_uds_demo
```

Notes:

- `UDS` transport requires a real host environment that allows `AF_UNIX` sockets.
- some managed sandboxes may block Unix sockets; in that case this path should be verified directly on the host.
