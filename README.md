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
