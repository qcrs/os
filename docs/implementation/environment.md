# Local Python and Docker Environment

The repository has two host-side Python environments and one application
container profile.

## StateBus host environment

This environment runs host-side tests and non-vLLM Python tools:

```bash
cd /home/qcrs/src/statebus/os
deploy/install_statebus_host.sh --dry-run
deploy/install_statebus_host.sh
source deploy/activate_statebus_host.sh
python -c 'import statebus; print(statebus.__file__)'
```

The default prefix is `~/src/statebus/conda-envs/statebus_host` and dependencies are
read from `requirements-host.txt` and `requirements-studio.txt`. The installer
installs this checkout in editable mode and does not start services.

## Host vLLM environment

vLLM is intentionally separate from the StateBus host environment:

```bash
cd /home/qcrs/src/statebus/os
deploy/install_vllm_env.sh --dry-run
deploy/install_vllm_env.sh
```

The default prefix is `~/src/statebus/conda-envs/vllm-qwen-cu121`; pinned packages
come from `requirements-vllm.txt`. Installation does not select a GPU or start
vLLM. Before a real start, inspect GPU ownership and the resolved profile with
the existing deployment runbook.

## Docker image

The existing `docker/Dockerfile` has `core` and `embed` targets. Configure
`docker/.env` from `docker/.env.example`, then inspect the build command:

```bash
cd /home/qcrs/src/statebus/os
deploy/build_statebus_image.sh --dry-run
deploy/build_statebus_image.sh
```

The build wrapper only invokes `docker compose build`; it never creates,
replaces, starts, or stops a container. The existing shared container remains
managed by its owning workflow. Use `docker/README.md` for runtime and model
service procedures.

## Verification without service startup

```bash
docker compose --env-file docker/.env.example -f docker/compose.yaml config
source deploy/activate_statebus_host.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q
```
