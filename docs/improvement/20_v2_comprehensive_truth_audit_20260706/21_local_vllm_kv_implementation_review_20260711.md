# Local vLLM/KV Implementation Review - 2026-07-11

## 1. Executive Conclusion

The local vLLM path has one valid completed 32B formal evidence point: `sb32bcompact` completed 25/25 cases on L0, L1, L2, and L3 with the local Qwen3-32B service at `http://127.0.0.1:53334/v1`, `shared_memory` state pool mode, loopback transport, and context caps configured at 4096 tokens with a 64-token safety margin.

This is evidence for StateBus control-plane prefix scheduling, compact prompt construction, input-level pruning, and engine-local prefix reuse readiness. It is not evidence for true KV tensor transfer, hidden-state transfer, cross-engine KV reuse, or multi-GPU success.

The strongest machine-readable result is:

- Audit artifact: `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_vllm_kv_audit_20260711.json`
- Final pass run: `/home/qcrs/statebus/runs/sb32bcompact`
- Formal pass shape: L0-L3 all `case_count=25`, `quality_floor_pass_count=25`
- Token/control deltas: protocol L3 total tokens `64839` versus text L0 total tokens `122785`, total token delta `-57946`, prompt token delta `-51606`, control byte delta `-31581`
- Current regenerated vLLM health probe: `/health` returns `HTTP 200` on `127.0.0.1:53334`
- Current regenerated vLLM metrics probe: `/metrics` exposes prefix/cache/KV gauge lines, including `enable_prefix_caching="True"`, `gpu_memory_utilization="0.82"`, and `num_gpu_blocks="573"`

Important evidence limit: the scanned failed run artifacts mostly contain empty `formal_suite.stdout.json` files or missing summaries, not direct Traceback or BadRequest snippets. Failure attributions in the audit JSON are therefore marked as inferred unless direct snippets are present.

## 2. Source Map

Authoritative baseline sources for this review:

| Source | Role in this review |
| --- | --- |
| `AGENTS.md` | Repo operating constraints, branch posture, host/container boundary, v1/v2 terminology. |
| `README.md` | Current StateBus project framing and runnable entry points. |
| `docs/constraints/current_host_and_migration.md` | Confirms host development posture and the openEuler VM validation boundary. |
| `docs/constraints/current_feature_scope.md` | Confirms what is implemented versus planned. |
| `docs/planning/implementation_plan.md` | Confirms v1/v2 sequencing and scope. |
| `docs/reference/题目.md` | Contest/task reference source. |
| `docs/setup/local_vllm_qwen.md` | Local vLLM/Qwen setup and service expectations. |
| `docs/improvement/20_v2_comprehensive_truth_audit_20260706/20_kv_execution_prompt_20260710.md` | Immediate execution objective and required audit shape. |
| `docs/improvement/20_v2_comprehensive_truth_audit_20260706/20_kv_execution_progress_qwen3_8b_20260710.md` | Progress state before the 32B audit. |
| `docs/improvement/20_v2_comprehensive_truth_audit_20260706/19_kv_research_comprehensive_analysis_and_roadmap_20260710.md` | Primary research roadmap for local vLLM/KV readiness. |
| `docs/improvement/20_v2_comprehensive_truth_audit_20260706/19_kv_research_appendix_kv_tensor_feasibility.md` | Boundary on true KV tensor feasibility. |
| `docs/improvement/20_v2_comprehensive_truth_audit_20260706/16_phase_transition_decision_kv_readiness_20260710.md` | Phase transition decision and claim boundary. |
| `docs/improvement/20_v2_comprehensive_truth_audit_20260706/17_kv_transition_readiness_report_20260710.md` | Readiness report for local vLLM/KV next steps. |

Superseded or secondary sources:

| Source class | Treatment |
| --- | --- |
| `19_kv_research_part*.md` | Treated as draft shards superseded by the comprehensive roadmap unless they contain narrower implementation notes. |
| `19_kv_research_comprehensive_analysis_and_roadmap_20260710.md.backup` | Ignored for current claims because the non-backup file is the authoritative revision. |
| Local API non-KV reviews and artifact mining docs from July 8-9 | Used only for historical context. They are not local vLLM/KV evidence. |
| Existing artifact inventories under `artifacts/local_api_*` | Ignored for local vLLM/KV result claims because they target prior local API or non-KV runs. |

Dirty worktree note:

- `git status --short --branch` showed a pre-existing untracked file named `tatus --short --branch`.
- This file was not read as evidence, not staged, and not modified.

## 3. Implementation Map

`runtime/llm.py`

- Adds the local context safety boundary through `_estimate_chat_prompt_tokens`, `_cap_max_tokens_for_context`, and `_context_window_adjusted_request`.
- The current code can reduce `max_tokens` before request submission and can retry after a maximum-context 400 response.
- Risk: the 400 retry path matches status/text broadly. It should stay documented as a local vLLM hardening behavior, not as proof that all providers share the same semantics.

`v2/runtime/role_path.py`

- Implements compact planner/summarizer JSON paths and compact evidence text.
- Supports shared evidence prefix alignment through `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix`.
- Uses the explicit claim boundary `prompt_prefix_layout_control_plane_only_no_kv_tensor_export`.
- This is the main implementation surface for input layout that can help vLLM's engine-local prefix cache. It does not export or import KV tensors.

`scripts/run_v2_local_vllm_container_check.sh`

- Runs the local vLLM check inside the dev container.
- Writes a temporary local vLLM config for the container path.
- Sources `/usr/local/bin/activate_statebus_container.sh` before running the command.
- Keeps the check rooted in the existing single-container v2 validation path.
- The default profile is the 8B development endpoint unless the caller first sources the 32B profile or exports the 32B URL/model variables.

`scripts/run_v2_local_vllm_formal_suite.sh`

- Wraps the container check to run the formal suite and emit `formal_suite.stdout.json` plus `formal_suite.summary.json`.
- This review adds an explicit AF_UNIX socket path byte-length guard before invoking the container check.
- The guard exits with code 2 and a clear message when `${STATEBUS_CONTAINER_RUNS_ROOT}/${RUN_ID}/control.sock` exceeds `STATEBUS_AF_UNIX_SOCKET_PATH_MAX_BYTES` or the default 107-byte limit.

`deploy/activate_statebus_local_vllm_profile.sh` and `scripts/start_vllm_qwen3_32b_prefix_cache.sh`

- Define the local vLLM service profile and the Qwen3-32B prefix-cache launch path.
- Completed formal evidence used service URL `http://127.0.0.1:53334/v1`, max model length 4096, and tensor parallelism 1.
- Current recovered service/profile defaults use GPU0, max model length 8192, `gpu_memory_utilization=0.82`, `num_gpu_blocks_override=573`, and tensor parallelism 1.
- Host-side commands that use the local profile should source `deploy/activate_statebus_local_vllm_profile.sh qwen3-32b`, which itself sources `deploy/activate_statebus_host.sh`.
- No current audited evidence proves two-GPU success.
- The setup doc explicitly warns that Qwen3 under current cu121 + vLLM 0.7.3 uses Transformers fallback, so API functionality and quality evidence should not be treated as final vLLM-native performance evidence.

`v2/runtime/neural_state.py`

- Provides `EngineLocalPrefixRegistry`, prefix-hash helpers, and prompt prefix layout compilation.
- Tracks engine-local handles and cache-affinity metadata.
- It is a control-plane registry, not a KV tensor store.

`v2/benchmark/kv_analysis.py`

- Computes theoretical prefix reuse and replay-class interpretation.
- Its claim boundary is theoretical unless backed by live vLLM metrics.
- It reports estimates such as engine-local prefix cache query/hit estimates from benchmark case metadata, not raw vLLM counters.

`v2/benchmark/kv_prefix_schedule.py`

- Builds corpus-prefix schedule hints and cache-friendly/cache-hostile task orderings.
- The claim boundary is `corpus_prefix_schedule_control_plane_only_no_kv_tensor_export`.

`v2/benchmark/kv_prefix_experiment.py`

- Runs a targeted local vLLM prefix-alignment probe using shared-prefix or chain prompt layouts.
- Uses `v2/runtime/vllm_metrics.py` for metrics collection.
- This should be the next mechanism test surface, but no new full formal run was started for this review.

`v2/runtime/vllm_metrics.py`

- Parses known vLLM prefix-cache query/hit/hit-rate metric names.
- Current service evidence exposed hit-rate and cache usage gauges, not explicit raw hit/miss counters.

`v2/retrieval/pruning.py` and `v2/retrieval/pipeline.py`

- Implement dynamic evidence pruning based on estimated KV capacity.
- This is input-level pruning, not runtime KV eviction or tensor transport.

`StateRef` and `ExecutionArtifactRef`

- The reviewed v2 boundary keeps `ExecutionArtifactRef` separate from `StateRef`.
- Execution outputs remain task workspaces, artifact root, and CAS oriented. They are not collapsed into state-pool references.

## 4. Experiment Timeline

| Step | Evidence | Result | Attribution |
| --- | --- | --- | --- |
| Mini local vLLM formal run | `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-gpu0-mini5-20260710_2234` | Complete JSON; 5/25 selected; L0-L3 all 5/5 | Proved the container/local vLLM path could complete a small formal subset. |
| Full formal with 120s timeout | `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-gpu0-formal-20260710_2250` | Empty stdout, no summary, L0 report 25/25 exists | Inferred wrapper timeout from config `timeout_s=120` and missing suite summary. |
| Timeout increased to 900s | `/home/qcrs/statebus/runs/sb32bformal900` | Empty stdout, no summary, L0 report 25/25 exists | Partial formal run without suite summary. |
| Long run-id AF_UNIX risk | Objective timeline plus wrapper behavior | Current audited named run IDs are within the container socket limit; no direct path-too-long snippet was found | Historical failure class preserved, now guarded by `scripts/run_v2_local_vllm_formal_suite.sh`. |
| Executor `max_tokens=4096` without context cap | `/home/qcrs/statebus/runs/sb32bformalx4k` | Empty stdout, no summary | Inferred vLLM context-400 risk from config and missing summary; no direct BadRequest snippet found. |
| Executor `max_tokens=3072` without context cap | `/home/qcrs/statebus/runs/sb32bformal3k` | Empty stdout, no summary | The objective timeline treats this as a long-prompt context-400 class failure, but current scanned artifacts only prove an unattributed empty wrapper stdout. |
| Context cap introduced | `/home/qcrs/statebus/runs/sb32bcap3k` | Empty stdout, no summary, L0 report 25/25 exists | Context cap reduced executor risk, but summarizer JSON truncation risk remained inferred. |
| Compact planner/summarizer and larger summarizer budget | `/home/qcrs/statebus/runs/sb32bcompact` | Complete summary and stdout; L0-L3 all 25/25 | Final pass. |

Direct failure-snippet audit:

- The audit script scanned candidate JSON, log, stdout, stderr, text, and YAML files under each run root and sampled `/home/qcrs/statebus/logs`.
- For the named local vLLM runs, no direct Traceback, BadRequestError, maximum-context, timeout, AF_UNIX path-too-long, or JSON truncation snippets were found.
- Therefore the timeline above separates direct artifact facts from inferred attributions.

## 5. Python Audit Result

Generated command:

```bash
source deploy/activate_statebus_host.sh && python scripts/audit_local_vllm_kv_results.py
```

Generated artifact:

```text
docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_vllm_kv_audit_20260711.json
```

Audit schema and aggregate:

| Field | Value |
| --- | --- |
| Schema | `statebus.local_vllm_kv_audit.v1` |
| Generated UTC | `2026-07-11T06:18:13.649306+00:00` |
| Run count | 8 |
| Final pass runs | `sb32bcompact` |
| Claim boundary | Audit evidence only; no true KV tensor transfer claim. |

Run table:

| Run | Summary/stdout | Cases | Layers | Attribution |
| --- | --- | --- | --- | --- |
| `sb32bcompact` | summary JSON ok, stdout JSON ok | 25/25 | L0 25/25, L1 25/25, L2 25/25, L3 25/25 | final pass |
| `v2-local-vllm-qwen3-32b-gpu0-mini5-20260710_2234` | summary JSON ok, stdout JSON ok | 5/25 | L0 5/5, L1 5/5, L2 5/5, L3 5/5 | mini pass, no failure attribution |
| `sb32bformal900` | summary missing, stdout empty | unknown | L0 25/25 from benchmark report | partial formal run without suite summary |
| `sb32bformal3k` | summary missing, stdout empty | unknown | none extracted | unattributed empty wrapper stdout |
| `sb32bcap3k` | summary missing, stdout empty | unknown | L0 25/25 from benchmark report | partial run, executor risk reduced by context cap, summarizer JSON truncation risk |
| `sb32bformalx4k` | summary missing, stdout empty | unknown | none extracted | vLLM context 400 risk |
| `v2-local-vllm-qwen3-32b-gpu0-formal-20260710_2250` | summary missing, stdout empty | unknown | L0 25/25 from benchmark report | wrapper timeout 120s |
| `v2-local-vllm-qwen3-32b-gpu0-formal-timeout900-20260711_0015` | summary missing, stdout empty | unknown | none extracted | unattributed empty wrapper stdout |

Final `sb32bcompact` deltas:

| Metric | Text L0 | Protocol L3 | Delta |
| --- | ---: | ---: | ---: |
| Total tokens | 122785 | 64839 | -57946 |
| Prompt tokens | 101978 | 50372 | -51606 |
| Control bytes | 42926 | 11345 | -31581 |
| Quality pass count | 25 | 25 | 0 |

Final vLLM probe from regenerated audit artifact:

| Endpoint | Result |
| --- | --- |
| `http://127.0.0.1:53334/health` | `HTTP 200` |
| `http://127.0.0.1:53334/metrics` | Prefix/cache/KV gauge lines exposed |

Raw metric lines preserved by the final audit:

```text
vllm:gpu_cache_usage_perc{model_name="qwen3-32b"} 0.0
vllm:cpu_cache_usage_perc{model_name="qwen3-32b"} 0.0
vllm:cpu_prefix_cache_hit_rate{model_name="qwen3-32b"} 0.0
vllm:gpu_prefix_cache_hit_rate{model_name="qwen3-32b"} 0.0
vllm:cache_config_info{block_size="16",cache_dtype="auto",calculate_kv_scales="False",cpu_offload_gb="0",enable_prefix_caching="True",gpu_memory_utilization="0.82",is_attention_free="False",num_cpu_blocks="1024",num_gpu_blocks="573",num_gpu_blocks_override="573",sliding_window="None",swap_space_bytes="4294967296"} 1.0
```

This final probe restores live observability. It still does not prove a prefix-cache mechanism win: the current endpoint exposes idle hit-rate gauges, not raw hit/miss counters.

Post-audit validation readout:

| Check | Result |
| --- | --- |
| `docker ps -a` | Docker reachable; `statebus-dev-qcrs` is up. |
| Default `scripts/run_v2_local_vllm_container_check.sh` | Failed at host health probe for default 8B URL `http://127.0.0.1:53333/health`; connection refused. |
| `qwen3-32b` profile container check | Passed after service recovery with explicit 32B endpoint and GPU0 environment overrides. |
| Container activation wrapper | The script path still sources `/usr/local/bin/activate_statebus_container.sh` inside `docker exec`; the 32B profile container check passed after service recovery. |
| `pgrep -af 'vllm|Qwen3|53334|53333'` | Qwen3-32B vLLM service visible on `127.0.0.1:53334`; specific PIDs are service-lifetime facts, not benchmark evidence. |
| `nvidia-smi` | Qwen3-32B vLLM engine runs on GPU0. GPU1/GPU2 non-StateBus workloads were not killed or restarted. |

## 6. Mechanism Probes After E0 Recovery

After the GPU0/8192 service recovered, three small mechanism probes were run. These are not full formal guards.

| Probe | Artifact | Result |
| --- | --- | --- |
| E1 cache-friendly vs cache-hostile schedule | `artifacts/e1_kv_schedule_ablation_summary_20260711_134159.json` | Passed under repeat=4 / 573-block stress: friendly final GPU prefix hit-rate `0.788866` vs hostile `0.523494`; mean TTFT `657.55 ms` vs `1378.70 ms`. |
| E2 shared evidence prefix on/off | `artifacts/e2_prefix_alignment_ablation_summary_20260711_1359.json` | Passed: shared final GPU prefix hit-rate `0.780876` vs independent `0.0`; mean TTFT `951.61 ms` vs `3540.27 ms`. |
| E3 dynamic pruning on/off | `artifacts/e3_dynamic_pruning_ablation_20260711.json` | Passed at retrieval level: selected evidence bytes `333 -> 112`, estimated KV tokens saved `36 -> 92`, hard fact `fact-revenue-1` preserved. |

Mechanism-probe claim boundary:

- E1/E2 support engine-local prefix reuse through schedule/layout control.
- E3 supports input-level evidence pruning.
- None of E1/E2/E3 proves KV tensor export, hidden-state transfer, cross-engine KV reuse, or full formal quality on its own.

## 7. Bugs, Risks, and Missing Work

1. True KV tensor transfer is not implemented.
   The current implementation performs prompt layout, schedule hints, engine-local prefix registry bookkeeping, and input-level pruning. It does not export vLLM KV tensors, import KV tensors, share KV between engines, or bypass prefill through a StateBus-owned KV object.

2. Prefix hit/miss claims remain controlled-probe scoped.
   The recovered service exposes prefix/cache/KV metrics, and E1/E2 captured defensible hit-rate deltas plus TTFT deltas. vLLM still exposes gauges rather than raw hit/miss counters in this setup, so the claim should stay scoped to the documented E1/E2 probes.

3. Failure logs are weak for failed long runs.
   The failed run roots often contain zero-byte wrapper stdout and no top-level summary. The audit script records inferred attribution rather than fabricating direct Traceback or BadRequest evidence.

4. AF_UNIX path length is now guarded, but historical direct evidence is missing in scanned artifacts.
   The current named run IDs audit within the default 107-byte limit. The wrapper guard prevents recurrence and turns the failure into an immediate actionable exit.

5. Context cap handling is useful but broad.
   `runtime/llm.py` can cap `max_tokens` and retry on maximum-context 400 responses. The retry match should remain scoped in claims to local vLLM/Qwen until provider-specific behavior is tested.

6. Runtime token estimation is rough.
   `_estimate_chat_prompt_tokens` is a character-based approximation, not a tokenizer-accurate count. It is acceptable as a defensive guardrail, but a future local vLLM/Qwen hardening pass should prefer tokenizer-aware estimation when the tokenizer is cheaply available.

7. JSON truncation risk moved rather than disappeared.
   The compact pass indicates the final planner/summarizer/executor budgets can work for this corpus. It does not prove arbitrary financial reports or longer contexts are safe.

8. Compact summarizer JSON can reduce reusable-step detail.
   The compact summarizer fix helped `sb32bcompact` finish, but shorter JSON may suppress `reusable_steps` richness. That is acceptable for the current quality-path proof, but it should be checked before making stronger replay or reuse claims.

9. Formal wrapper run IDs now have an active UDS guard.
   The wrapper should continue to fail before container execution when the computed AF_UNIX socket path is too long. This avoids opaque UDS failures and keeps the failure mode auditable.

10. Container activation is centralized in the wrapper, but E1/E2/E3 are not formal container guards.
    `scripts/run_v2_local_vllm_container_check.sh` sources `/usr/local/bin/activate_statebus_container.sh` inside `docker exec`, and the recovered 32B profile check passed. The mechanism probes are narrower local-vLLM probes, not a replacement for the later formal guard.

11. The completed formal quality point and current mechanism point use different context baselines.
    `sb32bcompact` remains the 4096-token formal quality evidence. E1/E2/E3 ran against the recovered 8192-token service and support mechanism claims only within their probe scope. A longer-than-8192 capacity test is separate E4 work, not a prerequisite for citing the current 8192 E1/E2/E3 results.

12. Qwen3-32B local evidence is single-GPU.
   No current audited result proves tensor parallel 2, multi-GPU launch stability, or multi-GPU prefix-cache behavior.

13. Current memory reuse is assist-style unless measured otherwise.
   Existing evidence should not be described as skipped execution or replay gain unless a benchmark shows non-zero `reuse_gain` or `skipped_step_count`.

14. Prefix cache metrics do not prove general hit/miss behavior outside the captured probes.
    E1/E2 provide defensible hit-rate deltas around specific controlled prompts. Do not generalize those deltas to all workloads, and do not describe them as raw KV tensor handoff or cross-engine cache reuse.

15. Dynamic pruning is an estimate-driven input optimization.
    `STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED` controls evidence selection before prompting. It is not KV tensor pruning, vLLM cache eviction control, or hidden-state reuse.

16. Qwen3 fallback performance is not final vLLM-native performance.
    `docs/setup/local_vllm_qwen.md` states that cu121 + vLLM 0.7.3 can run Qwen3 through Transformers fallback, but its speed and prefix-cache behavior should not be treated as final native-vLLM evidence.

17. Docker/openEuler boundary is not a compatibility claim.
   The container check validates the current dev container path. openEuler compatibility must still be validated in the VM or final delivery environment.

18. `ExecutionArtifactRef` must remain separate from `StateRef`.
    Execution outputs should stay in workspaces/artifact root/CAS. Collapsing them into generic state refs would obscure replay semantics.

## 7. Completed and Remaining KV Plan

| ID | Status | Evidence | Claim boundary |
| --- | --- | --- | --- |
| E0 | Complete | `22_e0_32b_observability_probe_20260711.md`; audit JSON records `/health` and raw prefix/cache/KV metric lines. | Service observability only. |
| E1 | Complete | `23_e1_kv_schedule_ablation_20260711.md`; friendly hit-rate and TTFT beat hostile under repeat=4 / 573-block stress. | Engine-local prefix reuse from schedule control only. |
| E2 | Complete | `24_e2_prefix_alignment_ablation_20260711.md`; shared evidence prefix beat independent layout on hit-rate and TTFT. | Prompt layout enabling engine-local prefix reuse only. |
| E3 | Complete | `25_e3_dynamic_pruning_ablation_20260711.md`; retrieval-level dynamic pruning reduced selected evidence pressure while preserving the hard fact proxy. | Input-level pruning only. |

Remaining work should stay narrow:

| ID | Next condition | Suggested action | Claim boundary | Risk |
| --- | --- | --- | --- | --- |
| Stability repeat | Before promoting E1/E2 numbers into a headline mechanism claim. | Rerun the small E1/E2 probes once against the same GPU0/8192 profile, preserving fresh metric snapshots. | Repeatability check only. | Metrics gauges can be affected by service lifetime and prior traffic. |
| E4 | Only if GPU capacity and service restart risk are acceptable. | Treat as a longer-than-8192 capacity smoke, for example 12288 before any 16384 attempt. | Context capacity only. | GPU0 has limited headroom; do not disturb unrelated GPU jobs. |
| E5 | Only if GPU0/GPU1 are proven free and the operator approves a restart. | Try `qwen3-32b-2gpu` and run E0 plus a mini formal subset. | Multi-GPU service validation only. | No two-GPU claim until health, metrics, and mini quality pass. |
| E6 | Only after the mechanism/profile choice is accepted and the user approves a long run. | Run the formal 25-case guard with captured metric snapshots. | Formal quality guard. No true KV tensor claim. | Several hours; not started in this audit. |

## 8. Recommendations

1. Keep `sb32bcompact` as the current local vLLM/Qwen3-32B formal evidence point and cite the audit JSON with it.

2. Use the phrase `Engine-Local Prefix Reuse` for the KV-facing work unless and until true KV tensor export/import exists.

3. Keep the new AF_UNIX socket guard in the formal wrapper. It is cheap, deterministic, and prevents an avoidable container failure mode.

4. Do not start another full formal run until the E1/E2 mechanism numbers are either repeated or explicitly accepted, and the user approves E6.

5. Keep the local vLLM service on the documented GPU0/8192 profile for comparable mechanism probes. Longer context attempts belong to E4 and should not overwrite the current baseline.

6. Add a narrow follow-up to persist raw vLLM metric values in every prefix experiment artifact. The parser in `v2/runtime/vllm_metrics.py` is useful, but experiment outputs should preserve raw names and values even when only gauges are exposed.

7. Treat `runtime/llm.py` context retry behavior as local-vLLM hardening and add a future test that proves it does not mask unrelated provider 400 errors.

8. Keep benchmark claims serialized. Concurrent API launches should remain engineering smoke evidence, not formal API latency evidence.

9. Preserve the current untracked `tatus --short --branch` file as unrelated workspace state unless the user explicitly asks to remove it.

10. Do not pursue true KV tensor handoff or a vLLM fork next. The current evidence supports engine-local prefix reuse and input pruning; the next decision is repeatability or formal guard, not KV tensor ownership.
