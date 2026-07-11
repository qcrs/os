# E0 32B Observability Probe - 2026-07-11

## Conclusion

E0 is not passable in the current host state. The Qwen3-32B local vLLM endpoint is not listening on `127.0.0.1:53334`, so E1/E2/E3 mechanism ablations should not run yet.

This is a service-availability blocker, not a StateBus benchmark failure.

## Commands Run

```bash
git status --short --branch
git log -2 --oneline
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b && curl -sS -i http://127.0.0.1:53334/health
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b && curl -sS http://127.0.0.1:53334/metrics | rg 'prefix|cache|kv'
pgrep -af 'vllm|Qwen3|53334|53333'
nvidia-smi
ss -ltnp
ps -fp 2906243 3391328 3394943
source deploy/activate_statebus_host.sh && python scripts/audit_local_vllm_kv_results.py
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b && scripts/run_v2_local_vllm_container_check.sh
```

## Findings

| Check | Result |
| --- | --- |
| Git status | Only pre-existing unrelated `tatus --short --branch` remains untracked. |
| Latest commits | `148bd7d kv: tighten local vllm audit coverage`, `df6d35b kv: add local vllm audit and guardrails`. |
| 32B health | `curl: (7) Failed to connect to 127.0.0.1 port 53334: Connection refused`. |
| 32B metrics | `curl: (7) Failed to connect to 127.0.0.1 port 53334: Connection refused`; no prefix/cache/KV metrics exposed. |
| Port listening | `ss -ltnp` showed no listener on `53334` or `53333`. |
| vLLM process scan | No vLLM server process matched; one unrelated Qwen3.5 sampling command matched the model-name grep. |
| GPU2 state | GPU2 had about 65 GiB allocated by existing non-StateBus Python/LLaMA-Factory work. |
| Container check | `scripts/run_v2_local_vllm_container_check.sh` with the 32B profile failed at the host health probe before container execution. |
| Audit JSON | Refreshed `local_vllm_kv_audit_20260711.json`; it records health and metrics as connection refused. |

Observed GPU2 processes:

| PID | Owner | Summary |
| ---: | --- | --- |
| `2906243` | `double` | `python -m CE3_baselines.main ... --cuda_id 2` |
| `3391328` | `dev001` | `llamafactory-cli webui` |
| `3394943` | `dev001` | `llamafactory-cli train ... Qwen2.5-32B-Instruct ...` |

## Decision

Do not run E1/E2/E3 while E0 is failing. Their metrics would be absent or misleading because the local vLLM service is unavailable.

Do not start, kill, or restart GPU processes from this audit path. Starting Qwen3-32B on GPU2 is not safe while the current non-StateBus GPU workloads are present.

## Next Action

Wait for GPU2/service availability or get explicit operator approval for a safe service launch window. Once the 32B service is listening again, rerun E0:

```bash
source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b
curl -sS http://127.0.0.1:53334/health
curl -sS http://127.0.0.1:53334/metrics | rg 'prefix|cache|kv'
```

Only after E0 passes should E1 cache-friendly/cache-hostile, E2 shared-prefix on/off, and E3 dynamic-pruning on/off probes run.
