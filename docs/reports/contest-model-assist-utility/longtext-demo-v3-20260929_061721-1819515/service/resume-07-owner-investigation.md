# Resume 07 GPU Owner Check

- Execution revision: `longtext-demo-v3-20260929_061721-1819515-resume-07`
- Selected slot: `MU-NOVA-4K-DELIVERY:apc_on_independent`
- Wall budget: 14,400 seconds
- Preflight result: blocked before any scored model request; see `resume-preflight-07.json`.
- Block reason: `standard_gpu_has_non_workflow_compute_owner`.

GPU 2 is not exclusive to the utility workflow. PID `2415216`, user `yz`, was running `python -m CE3_baselines.main --mode collaborative --strategy ours_al_v6 ... --cuda_id 2` and held 4,466 MiB. Related PIDs `2415214` and `2415215` for the same collaborative job occupied GPUs 0 and 1. These processes are outside the StateBus vLLM manager and were left untouched.

The manager-owned standard service remained healthy at PID `2379904` on port `53334`; the KV manager reported stopped. The preflight verified `/health`, `/v1/models`, the existing `statebus-runtime` container, and host/container imports from this checkout. No APC inference request was issued and no service switch occurred.
