# StateBus Repo Guidelines

## Working Mode

This repo is now the active implementation repo for StateBus.

Default branch posture:

- `main` is the active implementation mainline.
- `feat/realism-protocol-hardening` is now a historical topic branch pointer; it currently matches `main`.
- `baseline/statebus-host-prototype-20260607` is a pre-hardening snapshot for comparison only.
- `feat/statebus-v2-container-runtime` is the active `v2` clean-room planning branch rooted at the current contest-facing worktree, not at historical `main`.
- Start new `v1/mainline` work from `main`.
- Start new `v2` clean-room work from `feat/statebus-v2-container-runtime` unless the user explicitly asks to rebase or restart from another branch.

Read these files first before major code changes:

- `README.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`
- `docs/reference/题目.md`

## Environment Strategy

Do not reopen the `v1/mainline` decision unless the user explicitly asks:

- main development runs on the current Linux host;
- use the user-owned conda env and user-owned directories under `$HOME/statebus`;
- do not depend on the system Docker daemon;
- do not assume `nsjail` is installed or usable;
- first implementation of `StatePool` must prefer file-backed `mmap` and Python `shared_memory`;
- `Phase 0` to `Phase 4` are developed here;
- openEuler VM is for posterior validation, reproducibility, and final delivery checks.

Current host fact pattern to keep stable:

- host-side `AF_UNIX` / `UDS` is a valid path;
- `shared_memory` is a real benchmark option, not a dormant backend;
- Docker socket access is not available to the current user;
- `nsjail` is still absent on the host.

For `v2` clean-room work, use this explicit exception path:

- target environment is single-container `Docker + openEuler`;
- container development is allowed and intended for `v2`;
- the formal `v2` control plane is `UDS + typed Protobuf`, not `UDS + MessagePack` as the main wire contract;
- the formal `v2` data plane is tiered by object kind:
  - short-lived embedding / dense semantic state prefers `shared_memory`;
  - replay-ready state, manifests, and long-lived objects prefer `mmap` / CAS;
  - execution outputs use task workspaces plus artifact root plus CAS;
- `KV cache / hidden-state handoff` remains `Future Work` and must be described only as `Engine-Local Prefix Reuse`.

## Project Layout

Top-level implementation folders:

- `agents/`
- `runtime/`
- `protocol/`
- `statepool/`
- `memory/`
- `eval/`
- `tasks/`
- `tests/`
- `docs/`
- `deploy/`
- `scripts/`

## Development Priorities

Implement `v1/mainline` in this order:

1. host-side env and directory assumptions
2. `text` mode runnable path
3. `protocol` mode runnable path
4. `StateRef` and file-backed statepool
5. SQLite + FAISS memory flow
6. benchmark and telemetry

Do not start with:

- container orchestration
- openEuler VM packaging
- privileged shared-memory transport
- production sandboxing

For `v2`, implement in this order:

1. `v2/` clean-room package skeleton and `tests/v2/`
2. typed Protobuf control plane and runtime event semantics
3. `CanonicalTaskSpec`, `RuntimeCompatibilitySignature`, and ref registry
4. semantic provenance, hydration, and deterministic evidence fan-in
5. execution workspace and `ExecutionArtifactRef`
6. replay gate, telemetry, benchmark, and quality floor

## Commands

Activate env:

```bash
source deploy/activate_statebus_host.sh
```

Initial host setup:

```bash
bash scripts/setup_host_dev_env.sh
```

Smoke tests:

```bash
python -m pytest -q
python -m runtime.smoke
```

`v2` container bootstrap:

```bash
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=core
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d
docker exec -it statebus-dev-qcrs bash
```

## Code Rules

- Keep terminology aligned to `Planner`, `Retriever`, `Executor`, `Summarizer`, `StateRef`, `MemoryProxy`.
- Label planned features as planned if they are not implemented.
- Keep repo-local sample tasks as the default benchmark input.
- Avoid claiming openEuler compatibility unless it has been validated in the VM stage.
- Avoid claiming `nsjail`, Docker-based execution, hidden-state/KV transfer, or stronger sandbox isolation unless that path has been explicitly validated.
- For API latency claims, use serialized benchmark reruns only; do not treat concurrent API launches as formal timing evidence.
- Treat current memory reuse as assist-style unless a benchmark explicitly shows non-zero `reuse_gain` or `skipped_step_count`.
- For `v2`, keep `ExecutionArtifactRef` separate from `StateRef`; do not collapse them back into one vague ref type.
- For `v2`, formal benchmark task families should default to offline financial-report / operating-metric analysis, not freeform incident demos.
