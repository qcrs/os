# openEuler Container Validation Report

Date: 2026-07-03

Scope: StateBus v2 openEuler Docker validation boundary for
`feat/statebus-v2-container-runtime`.

This report turns the already-tested container path into a reproducible
validation index. It does not claim that a fresh Docker build, container rerun,
or openEuler VM validation was performed on 2026-07-03.

## 1. Container Profile

| Field | Value |
| --- | --- |
| Base image | `hub.oepkgs.net/openeuler/openeuler:24.03-lts-sp3` |
| Dockerfile | `docker/Dockerfile` |
| Compose file | `docker/compose.yaml` |
| Optional bwrap profile | `docker/compose.bwrap.yaml` |
| Default target | `core` |
| Heavy dependency target | `embed` |
| Image tag pattern | `statebus-dev-openeuler:24.03-lts-sp3-${STATEBUS_DOCKER_TARGET}` |
| Container name | `statebus-dev-qcrs` |
| Container repo mount | `/workspace/statebus/project` |
| Container state root | `/statebus` |
| Host state root | `/home/qcrs/statebus` |
| Default container user | `root` via `USER 0:0` |
| bwrap validation user/profile | `root + docker/compose.bwrap.yaml` |
| GPU setting | `runtime: ${STATEBUS_DOCKER_RUNTIME:-nvidia}` and `NVIDIA_VISIBLE_DEVICES=${STATEBUS_NVIDIA_VISIBLE_DEVICES:-all}` |

The bwrap profile intentionally adds `SYS_ADMIN`, `NET_ADMIN`, `seccomp=unconfined`,
and `apparmor=unconfined`. This validates a high-privilege root+bwrap Docker
profile only. It must not be reported as default non-root sandbox support or
production-grade isolation.

## 2. Reproducible Commands

Host-side bootstrap:

```bash
export STATEBUS_UID="$(id -u)"
export STATEBUS_GID="$(id -g)"
export STATEBUS_DOCKER_TARGET=core
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d
docker exec -it statebus-dev-qcrs bash
```

Container activation:

```bash
source /usr/local/bin/activate_statebus_container.sh
cd /workspace/statebus/project
```

Minimal container checks:

```bash
python3 --version
python3 -c "import numpy, pydantic, orjson, msgpack; import google.protobuf"
python3 -c "import langgraph; print('langgraph ok')"
python3 -m pytest -q tests/v2/test_preflight_and_live_runner.py tests/v2/test_fixed_answer_and_external_baseline.py tests/v2/test_minimal_benchmark.py
python3 -m pytest -q tests/v2/test_smoke.py
python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode deterministic --embedding-mode deterministic
python3 -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode deterministic --embedding-mode deterministic --statebus-mode cold-start
```

API/local embedding evidence commands represented by the existing evidence
package:

```bash
python3 -m pytest -q tests/v2
python3 -m v2.benchmark.live_runner --suite preflight --role-path-mode api --embedding-mode local
python3 -m v2.benchmark.live_runner --suite formal --benchmark-tier formal --role-path-mode api --embedding-mode local
python3 -m v2.benchmark.live_runner --suite compare --benchmark-tier dev --role-path-mode api --embedding-mode local
python3 -m v2.benchmark.flagship_ablation --role-path-mode api --embedding-mode local
python3 -m v2.benchmark.live_runner --suite replay-negative-audit --role-path-mode api --embedding-mode local
```

bwrap-specific launch profile:

```bash
docker compose -f docker/compose.yaml -f docker/compose.bwrap.yaml up -d --force-recreate
```

## 3. Evidence Package

| Field | Value |
| --- | --- |
| Host evidence root | `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352` |
| Container evidence root | `/statebus/runs/v2-api-evidence-20260702_145352` |
| Runtime artifact root | `/home/qcrs/statebus/runs/v2-live/runtime` |
| Final evidence index | `docs/reports/final_v2_evidence_index_20260703.md` |
| Claim boundary readout | `docs/reports/v2_api_evidence_readout_and_claim_boundary_20260702.md` |

Key evidence hashes are recorded in
`docs/reports/final_v2_evidence_index_20260703.md`. The most relevant container
profile facts are:

| Evidence | Result |
| --- | --- |
| `pytest-v2.log` | `152 passed in 358.04s` |
| `preflight-api.log` | `ok=true`, `role_path_mode=api`, `embedding_mode=local` |
| `local-embedding-stack.log` | `torch_version=2.5.1+cu121`, CUDA available, `STATEBUS_EMBED_DEVICE=cuda:0` |
| formal/carrier artifacts | `codeact_sandbox_bwrap_count > 0` and fallback count `0` under the recorded root+bwrap profile |

Key artifact hashes:

| Artifact | Host path | sha256 |
| --- | --- | --- |
| pytest log | `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/pytest-v2.log` | `07438af471f654c0641d231afa962e75f1d57d124621491c8e5102fdebaf2f97` |
| preflight log | `/home/qcrs/statebus/runs/v2-api-evidence-20260702_145352/preflight-api.log` | `ec16293de3d476083ae607156ab75c9890b1774f7507dbfd07e414f7d3cc605f` |
| formal suite JSON | `/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-formal-suite.json` | `8b83c60500455a42f9bf2696ba28631011500861be0a11003163ad92ec1c5cbc` |
| internal carrier compare JSON | `/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-carrier-compare.json` | `6c44b16d22407074255602fb2f84fb86bb05def46bbe0c94243ed90b87ca97b9` |
| external compare debug JSON | `/home/qcrs/statebus/runs/v2-live/runtime/benchmark_reports/statebus-v2-benchmark-cold-start-compare.json` | `00848b7af84263eb19e43935df1153331cc4b68ee83830b883b6aae0823bd061` |
| flagship ablation JSON | `/home/qcrs/statebus/runs/v2-live/runtime/flagship-ablation/benchmark_reports/statebus-v2-benchmark-non-text-flagship-ablation.json` | `66f0180b38cfcd4bb124053607096632138d54f61dab0882c8daf13952f7b5d5` |
| replay negative audit JSON | `/home/qcrs/statebus/runs/v2-live/runtime/replay-negative-audit/benchmark_reports/statebus-v2-benchmark-replay-negative-audit.json` | `4bb3af17999ec4d7956a8b13498d11882f70e6d8cf37072531f6f9e49dd855ec` |

## 4. Validation Boundary

Validated:

- openEuler Docker development profile based on `24.03-lts-sp3`.
- Root container execution path with mounted project and mounted state roots.
- API + local embedding v2 evidence package under the container path mapping.
- Controlled CodeAct-style execution with bwrap backend under `root + compose.bwrap.yaml`.

Not validated by this report:

- openEuler VM final delivery.
- Default non-root bwrap execution.
- Production-grade sandbox isolation.
- Docker-free target-machine delivery.
- External pure-text formal superiority.
- KV cache or hidden-state handoff.

If final review requires VM evidence, add a separate VM validation report with
the same fields: commit hash, OS image, user, Python/dependency versions,
commands, log paths, artifact hashes, and pass/fail summary.
