# Batch 3 v2 Amendment Ledger

This file records the four amendments added before implementation freeze.

## A1 — Local + cross-process canonical access enforcement

StateAccessGrant semantics apply to every canonical consumer, including
in-process providers. Direct low-level `load/get/resolve_*` calls are not
business access authority.

## A2 — Constrained RUNTIME_INTERMEDIATE

Runtime-created intermediate State is constrained by active
Attempt/Binding/Grant and the already-authorized capability/output contract.

## A3 — Settlement revokes new authority only

Settlement prevents new witnesses/acquisitions/pins/publications but does not
require revoking an already-dispatched invocation's already-issued witness
mid-flight. Batch 2 stale-result fencing remains the semantic safety boundary.

## A4 — Artifact legacy fields are compatibility projections

`verification_state` / `replay_ready` cannot independently authorize
verification or replay. Runtime-owned decisions remain authoritative.
