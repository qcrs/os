# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

StateBus is a host-side multi-agent collaboration framework that verifies whether communication overhead can decrease, intermediate state can pass as non-plain-text, and shared memory enables real reuse. The system orchestrates agents (Planner, Retriever, Executor, Summarizer) that share state via typed protocols rather than plain text.

## Branch Strategy

- `main`: Active v1 implementation mainline
- `feat/statebus-v2-container-runtime`: Active v2 clean-room branch (single-container Docker + openEuler)
- Start v1 work from `main`; start v2 work from `feat/statebus-v2-container-runtime`

## Commands

### Environment Setup

```bash
bash scripts/setup_host_dev_env.sh
source deploy/activate_statebus_host.sh
```

### Tests

```bash
# Full test suite
python -m pytest -q

# V2 tests only
python -m pytest -q tests/v2

# Single test file
python -m pytest -q tests/test_smoke.py

# Single test function
python -m pytest -q tests/test_protocol_messages.py::test_state_ref_canonical_hash

# Smoke check (deterministic mode)
python -m runtime.smoke
```

### V2 Benchmark Runner

```bash
python -m v2.benchmark.live_runner --suite preflight --role-path-mode deterministic --embedding-mode deterministic
python -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic
python -m v2.benchmark.live_runner --suite statebus --benchmark-tier dev --role-path-mode deterministic --embedding-mode deterministic
python -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode api --embedding-mode local
```

Notes: `role-path-mode=api` requires `STATEBUS_LLM_API_KEY`; `embedding-mode=local` requires local model at `$HOME/statebus/models/Qwen3-Embedding-0.6B`.

### V2 Container Bootstrap

```bash
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=core
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d
docker exec -it statebus-dev-qcrs bash
```

## Architecture

### Layers

- **agents/**: Planner, Retriever, Executor, Summarizer agent implementations
- **runtime/**: Orchestration engine, LLM integration, role contracts, remote execution
- **protocol/**: Message structures (`StateRef`, `Plan`, `PlanStep`, `StepResult`, `MemoryCommit`), Protobuf serialization, channels
- **statepool/**: Multi-backend state storage (CAS blob, mmap file, Python shared_memory)
- **memory/**: SQLite + FAISS vector retrieval for semantic search
- **eval/**: Benchmark runner, metrics computation, fairness gates
- **tasks/**: Task corpus, benchmark pack definitions
- **v2/**: Clean-room v2 implementation (runtime compiler, session, state store, benchmark)

### Data Plane (v2)

- Short-lived embedding/dense semantic state → `shared_memory`
- Replay-ready state, manifests, long-lived objects → `mmap` / CAS
- Execution outputs → task workspaces + artifact root + CAS

### Control Plane (v2)

UDS (Unix Domain Sockets) + typed Protobuf (not MessagePack).

### Key Entry Points

- `runtime/orchestrator.py`: Main orchestration engine with state management and fairness gates
- `protocol/messages.py`: Core data structures and serialization
- `statepool/store.py`: Multi-backend state storage
- `memory/store.py`: EmbeddingProvider and MemoryStore
- `v2/benchmark/live_runner.py`: V2 benchmark orchestrator
- `eval/runner.py`: V1 benchmark runner

## Environment Constraints

- Host-side development on Linux; no Docker socket access for current user (v1)
- `nsjail` is not installed; do not assume sandbox isolation
- `shared_memory` is a real benchmark option, not dormant
- openEuler VM is for posterior validation and final delivery only
- `KV cache / hidden-state handoff` is Future Work (describe only as "Engine-Local Prefix Reuse")

## Code Conventions

- Terminology: `Planner`, `Retriever`, `Executor`, `Summarizer`, `StateRef`, `MemoryProxy`
- Keep `ExecutionArtifactRef` separate from `StateRef` in v2
- Do not claim openEuler compatibility unless validated in VM
- Do not claim Docker-based execution, hidden-state/KV transfer, or stronger sandbox isolation unless validated
- Treat memory reuse as assist-style unless benchmark shows non-zero `reuse_gain` or `skipped_step_count`
- Formal benchmark tasks default to offline financial-report / operating-metric analysis
- `text_whole_lane` is an internal comparator, not an external pure-text baseline

## Configuration (Do Not Commit)

- `deploy/statebus_llm.yaml.local` — LLM provider/model/role config
- `deploy/statebus_llm.env.local` — API keys (`STATEBUS_LLM_API_KEY`)

## Tech Stack

Python ≥ 3.11, numpy, protobuf, pydantic ≥ 2, orjson, msgpack, openai, faiss-cpu, transformers, sentence-transformers, networkx, pyyaml, rich. Optional: langgraph. Testing: pytest.

## Reference Reading Order

1. `docs/constraints/current_host_and_migration.md`
2. `docs/constraints/current_feature_scope.md`
3. `docs/reports/statebus_system_method_task_and_results_explainer.md`
4. `docs/reader_guide/README.md`
5. `tasks/README.md`
