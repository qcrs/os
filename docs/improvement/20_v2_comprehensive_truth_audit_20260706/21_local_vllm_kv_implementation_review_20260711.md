# Local vLLM/KV Implementation Review - 2026-07-11

## 1. Executive Conclusion

The local vLLM path has one valid completed 32B formal evidence point: `sb32bcompact` completed 25/25 cases on L0, L1, L2, and L3 with the local Qwen3-32B service at `http://127.0.0.1:53334/v1`, `shared_memory` state pool mode, loopback transport, and context caps configured at 4096 tokens with a 64-token safety margin.

This is evidence for StateBus control-plane prefix scheduling, compact prompt construction, input-level pruning, and engine-local prefix reuse readiness. It is not evidence for true KV tensor transfer, hidden-state transfer, cross-engine KV reuse, or multi-GPU success.

The strongest machine-readable result is:

- Audit artifact: `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/local_vllm_kv_audit_20260711.json`
- Final pass run: `/home/qcrs/statebus/runs/sb32bcompact`
- Formal pass shape: L0-L3 all `case_count=25`, `quality_floor_pass_count=25`
- Token/control deltas: protocol L3 total tokens `64839` versus text L0 total tokens `122785`, total token delta `-57946`, prompt token delta `-51606`, control byte delta `-31581`
- Final regenerated vLLM health probe: `/health` refused connection on `127.0.0.1:53334`
- Final regenerated vLLM metrics probe: `/metrics` refused connection, so no current live prefix/cache metric value is claimed in the committed artifact

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
- Current evidence assumes service URL `http://127.0.0.1:53334/v1`, max model length 4096, and tensor parallelism 1.
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
| Generated UTC | `2026-07-11T05:16:39.322547+00:00` |
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
| `http://127.0.0.1:53334/health` | Connection refused |
| `http://127.0.0.1:53334/metrics` | Connection refused; no prefix/cache/KV metrics captured |

Raw parsed metric values at final audit time: `{}`.

This final probe does not invalidate the completed run artifacts. It does mean no current live prefix hit-rate, hit-count, or miss-count claim should be made from the committed audit JSON.

Post-audit validation readout:

| Check | Result |
| --- | --- |
| `docker ps -a` | Docker reachable; `statebus-dev-qcrs` is up. |
| Default `scripts/run_v2_local_vllm_container_check.sh` | Failed at host health probe for default 8B URL `http://127.0.0.1:53333/health`; connection refused. |
| `qwen3-32b` profile container check | Failed at host health probe for `http://127.0.0.1:53334/health`; connection refused before container health probe or smoke command. |
| Container activation wrapper | The script path still sources `/usr/local/bin/activate_statebus_container.sh` inside `docker exec`; this was inspected but not reached in the failed health-probe run. |
| `pgrep -af 'vllm|Qwen3|53334|53333'` | No vLLM server process was visible; one unrelated Qwen training/sampling process matched. |
| `nvidia-smi` | GPU 2, the documented 32B profile GPU, was already heavily occupied by existing Python workloads. No process was killed or restarted. |

## 6. Bugs, Risks, and Missing Work

1. True KV tensor transfer is not implemented.
   The current implementation performs prompt layout, schedule hints, engine-local prefix registry bookkeeping, and input-level pruning. It does not export vLLM KV tensors, import KV tensors, share KV between engines, or bypass prefill through a StateBus-owned KV object.

2. Prefix hit/miss claims remain limited.
   The final regenerated audit could not reach the metrics endpoint. Earlier local probes are not enough for a committed mechanism claim. A mechanism claim needs controlled before/after metrics around cache-friendly versus cache-hostile scheduling.

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

10. Container activation is centralized in the wrapper but was not reached in the failed final probe.
    `scripts/run_v2_local_vllm_container_check.sh` sources `/usr/local/bin/activate_statebus_container.sh` inside `docker exec`; the final run failed during the host health probe before container execution. This is a service-availability failure, not evidence that container activation is broken.

11. The 4096 context cap limits mechanism validation.
    It enabled the 32B formal quality path but constrains long-prefix experiments. E4 below is required before claiming an 8192-token mechanism result.

12. Qwen3-32B local evidence is single-GPU.
   No current audited result proves tensor parallel 2, multi-GPU launch stability, or multi-GPU prefix-cache behavior.

13. Current memory reuse is assist-style unless measured otherwise.
   Existing evidence should not be described as skipped execution or replay gain unless a benchmark shows non-zero `reuse_gain` or `skipped_step_count`.

14. Prefix cache metrics do not currently prove hit/miss behavior.
    The final audit could not reach `/metrics`, and previous gauge-only reads are not a controlled before/after experiment. Do not claim cache hits or misses without exposed counters or a defensible hit-rate delta captured around a specific probe.

15. Dynamic pruning is an estimate-driven input optimization.
    `STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED` controls evidence selection before prompting. It is not KV tensor pruning, vLLM cache eviction control, or hidden-state reuse.

16. Qwen3 fallback performance is not final vLLM-native performance.
    `docs/setup/local_vllm_qwen.md` states that cu121 + vLLM 0.7.3 can run Qwen3 through Transformers fallback, but its speed and prefix-cache behavior should not be treated as final native-vLLM evidence.

17. Docker/openEuler boundary is not a compatibility claim.
   The container check validates the current dev container path. openEuler compatibility must still be validated in the VM or final delivery environment.

18. `ExecutionArtifactRef` must remain separate from `StateRef`.
    Execution outputs should stay in workspaces/artifact root/CAS. Collapsing them into generic state refs would obscure replay semantics.

## 7. Next KV Test Plan

| ID | Hypothesis | Command | Expected metrics | Pass/fail | Claim boundary | Est. runtime | Risk |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| E0 | The current local 32B service is observable before any mechanism probe. | `source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b && curl -sS http://127.0.0.1:53334/health && curl -sS http://127.0.0.1:53334/metrics | rg 'prefix|cache|kv'` | HTTP 200 health; raw prefix/cache/KV metric names and values if exposed. | Pass if health is 200 and metrics are either captured or explicitly absent; fail on connection refusal. | Service observability only. No reuse claim. | <1 min | Service is currently down; restarting requires safe GPU availability and explicit operator intent. |
| E1 | `kv_prefix_reuse_v1` cache-friendly ordering produces stronger engine-local prefix-cache evidence than cache-hostile ordering. | `source deploy/activate_statebus_local_vllm_profile.sh qwen3-32b && python -m v2.benchmark.kv_prefix_schedule --family-dir v2/benchmark/samples/continuous_task_families/kv_prefix_reuse --mode cache_friendly --output /home/qcrs/statebus/runs/kv-e1-friendly-plan.json` and the paired `--mode cache_hostile` plan, followed by the local_vllm live probe for both orders. | Task order, affinity run length, prompt tokens, TTFT if available, and before/after vLLM prefix/cache metrics. | Pass if friendly ordering improves exposed cache signal or TTFT versus hostile without quality regression; fail if no controlled delta is captured. | Engine-Local Prefix Reuse plus control-plane scheduling only. No KV tensor export. | 30-60 min | Metrics gauges can be polluted by prior traffic unless the service lifetime is controlled. |
| E2 | `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix` improves prefix-cache observability versus default layout. | Run the same small local_vLLM KV probe twice: once with `STATEBUS_PREFIX_ALIGNMENT_MODE=` and once with `STATEBUS_PREFIX_ALIGNMENT_MODE=shared_evidence_prefix`, preserving metric snapshots around each run. | Layout plan fields, shared prefix bytes, prompt tokens, raw vLLM prefix/cache metrics, quality pass count. | Pass if shared alignment improves exposed cache signal or TTFT and preserves quality; fail if no measurable delta or quality regresses. | Prompt prefix layout control plane only. No hidden-state handoff. | 30-60 min | Current 4096 context may limit shared-prefix length. |
| E3 | Dynamic pruning reduces prompt/KV pressure without lowering quality. | Run paired local_vLLM probes with `STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=0` and `STATEBUS_EVIDENCE_DYNAMIC_PRUNING_ENABLED=1`, using the same task subset and captured configs. | Selected evidence bytes, prompt tokens, pruning decision, quality pass count, and vLLM prefix/cache metrics if available. | Pass if pruning reduces prompt pressure while preserving quality floor; fail if answer quality drops or evidence selection is not auditable. | Input-level evidence pruning only. No KV tensor pruning or vLLM cache control. | 30-90 min | Over-pruning can hide required financial evidence. |
| E4 | 8192 context allows stronger mechanism probes than 4096, but only if 32B can restart safely. | After confirming no job disruption risk, compare the documented 4096 profile with an 8192 profile from `docs/setup/local_vllm_qwen.md`; then rerun E0 and a mini E1/E2 probe. | Startup logs, health, model max length, request context caps, prompt tokens, quality pass count, metrics. | Pass only if 8192 service starts cleanly and mini quality/mechanism probes complete; fail on OOM, startup instability, or quality regression. | Context feasibility and local service capacity only. | 1-3 hr | Do not kill other GPU jobs; current final audit saw GPU 2 heavily occupied. |
| E5 | Tensor parallel size 2 can run Qwen3-32B and preserve the local_vLLM quality path only if GPU0/GPU1 are actually free. | Use the `qwen3-32b-2gpu` profile only after `nvidia-smi` proves GPU0/GPU1 are free; then run E0 plus a mini formal subset. | Health, metrics, GPU allocation, summary JSON, L0-L3 pass counts. | Pass only with service health, metric capture, and mini formal pass; fail otherwise. | Multi-GPU service validation only. No 2-GPU claim until this passes. | 1-3 hr | Must not kill or preempt other users' GPU jobs. |
| E6 | Any mechanism change preserves the 25-case formal quality guard. | After E1-E5 identify a stable mechanism/profile change, run `STATEBUS_LOCAL_VLLM_FORMAL_RUN_ID=kv-e6-formal-guard scripts/run_v2_local_vllm_formal_suite.sh` only with explicit approval for a full run. | Complete summary JSON; L0-L3 25/25; token/control deltas; metric snapshots before/after. | Pass if all 25 cases pass all layers and summary is complete; fail on missing summary, quality regression, or opaque logs. | Formal quality guard. No true KV tensor claim. | Several hours | Full formal is expensive and was explicitly not restarted in this audit. |

Highest-priority next test: E0, then E1. The final audit probe could not reach the local vLLM service, so service observability must be restored before measuring prefix behavior.

## 8. Recommendations

1. Keep `sb32bcompact` as the current local vLLM/Qwen3-32B formal evidence point and cite the audit JSON with it.

2. Use the phrase `Engine-Local Prefix Reuse` for the KV-facing work unless and until true KV tensor export/import exists.

3. Keep the new AF_UNIX socket guard in the formal wrapper. It is cheap, deterministic, and prevents an avoidable container failure mode.

4. Do not start another full formal run until E0-E4 pass with fresh artifacts and metric snapshots.

5. Restore or relaunch the local vLLM service under the documented profile before E0/E1, but do not treat the relaunch itself as a new benchmark result.

6. Add a narrow follow-up to persist raw vLLM metric values in every prefix experiment artifact. The parser in `v2/runtime/vllm_metrics.py` is useful, but experiment outputs should preserve raw names and values even when only gauges are exposed.

7. Treat `runtime/llm.py` context retry behavior as local-vLLM hardening and add a future test that proves it does not mask unrelated provider 400 errors.

8. Keep benchmark claims serialized. Concurrent API launches should remain engineering smoke evidence, not formal API latency evidence.

9. Preserve the current untracked `tatus --short --branch` file as unrelated workspace state unless the user explicitly asks to remove it.

10. Do not pursue true KV tensor handoff or a vLLM fork next. The current evidence is not ready for that path; finish the engine-local prefix-cache mechanism probes first.
