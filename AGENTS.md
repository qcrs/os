# StateBus Repo Guidelines

## Working Mode

This repo is now the active implementation repo for StateBus.

Read these files first before major code changes:

- `README.md`
- `docs/constraints/current_host_and_migration.md`
- `docs/planning/implementation_plan.md`
- `docs/reference/题目.md`

## Environment Strategy

Do not reopen this decision unless the user explicitly asks:

- main development runs on the current Linux host;
- use the user-owned conda env and user-owned directories under `$HOME/statebus`;
- do not depend on the system Docker daemon;
- do not assume `nsjail` is installed or usable;
- first implementation of `StatePool` must prefer file-backed `mmap` and Python `shared_memory`;
- `Phase 0` to `Phase 4` are developed here;
- openEuler VM is for posterior validation, reproducibility, and final delivery checks.

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

Implement in this order:

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

## Code Rules

- Keep terminology aligned to `Planner`, `Retriever`, `Executor`, `Summarizer`, `StateRef`, `MemoryProxy`.
- Label planned features as planned if they are not implemented.
- Keep repo-local sample tasks as the default benchmark input.
- Avoid claiming openEuler compatibility unless it has been validated in the VM stage.
