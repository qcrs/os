# Remaining Risks

## P1: Formal external superiority is still unsupported

No formal API compare JSON was produced. The full audit script still runs compare at dev tier. Any formal external superiority claim must remain blocked.

## P1: Deterministic evidence is not API evidence

The fresh 25/25 formal runs use `role_path_mode=deterministic`. They prove internal benchmark plumbing and deterministic quality, not current API behavior.

## P1: Container activation is broken

The required activation command fails in the running container because conda is absent. This is an engineering reproducibility issue, not just documentation friction.

## P1: CodeAct must stay bounded

The current defensible claim is bounded CodeAct / controlled execution. Realtime LLM code generation needs a fresh formal API artifact.

## P2: Family validators are not active primary validators

`tasks/formal/*/validator.py` should not be cited as benchmark quality enforcement until the runner imports and uses them.

## P2: Memfd negative fallback needs stronger evidence

Memfd positive path is verified. Memfd unavailable fallback needs a real negative environment or explicit capability-masked stage.

## P2: openEuler VM validation is absent

The container run does not equal openEuler VM validation. Compatibility claims remain unsupported.

## P2: Nested protobuf payloads still include JSON fields

Typed Protobuf envelope is real, but nested payloads still use JSON strings for several fields. Keep wording precise.

## P2: `jq` is absent in the container

The audit prompt's extraction command is not portable to the current image. Add `jq` or a repo-local Python extractor.

## P3: Benchmark artifact size and ownership

Fresh JSON artifacts are around 3 MB total and were copied from container `/tmp`. Ownership was normalized back to `qcrs:qcrs`, but future scripts should write artifacts directly with correct UID/GID.
