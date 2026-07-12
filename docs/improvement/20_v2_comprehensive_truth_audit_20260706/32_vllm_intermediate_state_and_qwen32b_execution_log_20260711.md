# vLLM Intermediate State And Qwen3-32B Execution Log - 2026-07-11

## Scope

- Probe the live GPU0 `qwen3-32b` vLLM OpenAI-compatible endpoint at `http://127.0.0.1:53334/v1` without restarting the service.
- Verify the actual capability boundary for:
  - hidden states
  - `logprobs` / `top_logprobs`
  - prefix-cache observability
- Only after that boundary check, run bounded local-vLLM correctness tests from short to longer:
  - local-vLLM smoke
  - 5-case mini formal
- Keep claims below:
  - hidden-state transfer
  - KV tensor export / transfer
  - cross-engine reuse

## Source Documents Read

- `README.md`
- `docs/reference/题目.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/29_local_vllm_kv_experiment_log_synthesis_20260711.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/30_independent_audit_report_20260711.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/31_comprehensive_gap_audit_20260711.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/19_kv_research_comprehensive_analysis_and_roadmap_20260710.md`
- `docs/improvement/20_v2_comprehensive_truth_audit_20260706/19_kv_research_appendix_kv_tensor_feasibility.md`

## Initial Git State

- Current worktree authority differs from the pasted prompt’s older branch note:
  - live branch observed here: `feat/statebus-gap-fix-and-logit-state`
  - the prompt file still referred to `feat/local-vllm-kv-prep`
- Initial `git status --short --branch` before this log update already showed a dirty worktree with ongoing local-vLLM/logit-state edits plus pre-existing untracked audit files.

## vLLM Capability Probe

- New artifact:
  - `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/vllm_intermediate_state_capability_20260711.json`
- Live service facts recorded in that artifact:
  - `/health`: HTTP `200`
  - `/v1/models`: `qwen3-32b`, `allow_logprobs=true`, `max_model_len=8192`
  - `/metrics` exposes:
    - `vllm:gpu_prefix_cache_hit_rate`
    - `vllm:cpu_prefix_cache_hit_rate`
    - `vllm:gpu_cache_usage_perc`
    - `vllm:cpu_cache_usage_perc`
    - `vllm:cache_config_info`
- Missing from `/metrics`:
  - no raw prefix hit counter
  - no raw prefix miss counter

| Capability | Available? | Evidence | Can Use In StateBus? | Boundary |
| --- | --- | --- | --- | --- |
| `hidden_states` | no | hidden-state probe requests returned HTTP `200` but no `hidden_states` payload | no | no hidden-state transfer unless a real tensor payload is returned |
| `logprobs` / `top_logprobs` | yes | `choices[0].logprobs.content[*].top_logprobs` in the probe artifact | yes, as a lightweight output-distribution proxy | output-distribution state only, not hidden-state / KV transfer |
| prefix cache metrics | yes | `/metrics` exposes `vllm:gpu_prefix_cache_hit_rate` and `vllm:cache_config_info` | yes | engine-local observability only; no raw per-request hit/miss counter |
| KV tensor export | no | current endpoint and `/metrics` expose no KV dump/export API | no | no KV transfer claim on the current service surface |

## Hidden-State Feasibility

- Probed request variants:
  - `return_hidden_states=true`
  - `output_hidden_states=true`
  - both again with `logprobs=true`
- Result:
  - all returned HTTP `200`
  - none returned any `hidden_states` field
  - response shape matched the ordinary chat-completions shape
- Extra control:
  - an unrelated unknown field also returned HTTP `200` with the same shape
- Judgment:
  - current OpenAI-compatible endpoint appears to silently ignore unknown hidden-state flags
  - hidden states are not obtainable from the current endpoint
  - this turn does not support any hidden-state-transfer claim

## Logprob / Confidence-State Feasibility

- `logprobs=true` and `top_logprobs=5` are supported on `/v1/chat/completions`.
- Returned structure is usable:
  - `choices[0].logprobs.content[*].token`
  - `choices[0].logprobs.content[*].logprob`
  - `choices[0].logprobs.content[*].top_logprobs`
- For the minimal probe request, the final token had `5` alternatives and serialized into a `20`-byte float32 payload.
- Direct probe summary from the new artifact:
  - `logprobs_supported=true`
  - `logprobs_parseable=true`
  - `lightweight_logit_state_viable=true`
- Claim boundary fixed in the artifact:
  - `openai_compatible_logprobs_probe_only_no_hidden_state_tensor_no_kv_tensor_export`
- Practical judgment:
  - the current endpoint can provide a lightweight output-distribution state proxy
  - this is closer to “LLM output distribution intermediate state” than plain text
  - it is still not model-internal hidden-state / KV transfer

## Prefix Cache Metrics

- Live metrics confirm prefix-cache observability is present but limited.
- What is available:
  - `vllm:gpu_prefix_cache_hit_rate`
  - `vllm:cache_config_info`
- What is not available:
  - no raw `hits_total`
  - no raw `misses_total`
- Therefore current metric language must remain:
  - gauge-level cache observability
  - not exact per-request raw hit/miss accounting

## Code Changes

- Added `scripts/probe_vllm_intermediate_state_capability.py` to freeze the live endpoint probe into a standalone JSON artifact.
- Added low-risk audit clarifications from the gap log:
  - `v2/retrieval/pipeline.py`: annotated `estimated_kv_tokens_saved` as an input-side arithmetic estimate, not a measured GPU KV counter
  - `v2/runtime/neural_state.py`: annotated `neural_prefix_cache_hit_count_estimate` as a control-plane estimate, not a raw vLLM hit counter
  - `scripts/run_v2_local_vllm_container_check.sh`: added explicit `53333` / `53334` endpoint guidance to avoid `8B` / `32B` confusion
- Corrected local-vLLM executor logprob request wiring in `runtime/llm.py`:
  - use top-level `logprobs` / `top_logprobs` request fields
  - keep the behavior local-vLLM + executor only
- Corrected `v2/runtime/logit_state.py`:
  - consume the final token’s `top_logprobs` distribution
  - support both SDK object shape and JSON dict shape
  - avoid the earlier degenerate “single chosen-token logprob only” behavior
- Added targeted tests:
  - `tests/test_llm_runtime.py`
  - `tests/v2/test_contracts_and_refs.py`
  - `tests/v2/test_logit_state.py`

## no-KV API Correctness Tests

- Static checks completed cleanly:
  - `python -m py_compile v2/retrieval/pipeline.py v2/runtime/neural_state.py runtime/llm.py`
  - `bash -n scripts/run_v2_local_vllm_container_check.sh`
  - `git diff --check`
- Requested pytest files `tests/v2/test_refs.py` and `tests/v2/test_state_store.py` are not present in the current worktree, so they were recorded as missing and not fabricated.
- Existing minimal pytest gate completed cleanly:
  - `python -m pytest -q tests/v2/test_control_plane.py tests/v2/test_uds_loopback.py -x`
  - result: `7 passed`
  - note: protobuf-generated deprecation warnings were emitted from `protocol/statebus_pb2.py`, but the test run passed
- API + local-embedding preflight was attempted exactly as requested:
  - `python -m v2.benchmark.live_runner --suite preflight --role-path-mode api --embedding-mode local`
  - result: `ok=false`
  - blocking facts reported by the runner:
    - `provider default missing api key; set STATEBUS_LLM_API_KEY`
    - `missing python dependency: sentence_transformers`
  - non-blocking environment facts from the same preflight:
    - embedding model path present: `/home/qcrs/statebus/models/Qwen3-Embedding-0.6B`
    - embedding device available: `cuda:0`

- Smoke before serializer correction:
  - run id: `v2-local-vllm-qwen3-32b-capprobe-smoke-20260711`
  - result: `ok=true`
- Persisted smoke after the serializer correction:
  - run id: `v2-local-vllm-qwen3-32b-capprobe-smoke-fix-20260711`
  - result: `ok=true`
  - `quality_floor_pass=True`
  - persisted roots:
    - `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-capprobe-smoke-fix-20260711/workspaces`
    - `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-capprobe-smoke-fix-20260711/runtime`

## Qwen3-32B Short Tests

- Runner subset support was verified directly:
  - `python -m v2.benchmark.live_runner --help`
  - exposed bounded subset flag: `--max-cases`
- Persisted short-run artifact:
  - run id: `v2-local-vllm-qwen3-32b-capprobe-mini5-20260711`
  - summary: `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-capprobe-mini5-20260711/mini_formal.summary.json`
- Result:
  - selected cases: `5 / 25`
  - `L0/L1/L2/L3` all `5/5` quality-floor pass
  - `role_path_mode=local_vllm`
  - `state_pool_mode_used=shared_memory`
- Short-run compare summary:
  - `protocol_L3_total_tokens=8387`
  - `text_L0_total_tokens=10730`
  - `protocol_vs_text_token_delta=-2343`
  - `protocol_L3_prompt_tokens=6263`
  - `text_L0_prompt_tokens=7681`
  - `protocol_vs_text_prompt_token_delta=-1418`
  - `protocol_L3_control_bytes=2485`
  - `text_L0_control_bytes=2357`
  - `protocol_vs_text_control_bytes_delta=128`
- Layer reports also show the new logit-state telemetry path is live:
  - `L0/L1/L2/L3` each recorded `telemetry_logit_state_transfer_count=5`
  - `telemetry_logit_confidence_gate_trigger_count=0`

## Qwen3-32B Longer Attempts

- Incremental scale-up completed:
  - run id: `v2-local-vllm-qwen3-32b-capprobe-mini10-20260712`
  - selected cases: `10 / 25`
  - `L0/L1/L2/L3` all `10/10` quality-floor pass
  - `role_path_mode=local_vllm`
  - `state_pool_mode_used=shared_memory`
- 10-case compare summary:
  - `protocol_L3_total_tokens=18137`
  - `text_L0_total_tokens=24991`
  - `protocol_vs_text_token_delta=-6854`
  - `protocol_L3_prompt_tokens=13701`
  - `text_L0_prompt_tokens=18608`
  - `protocol_vs_text_prompt_token_delta=-4907`
  - `protocol_L3_control_bytes=4960`
  - `text_L0_control_bytes=6658`
  - `protocol_vs_text_control_bytes_delta=-1698`
- Layer telemetry confirms the logit-state path remained live through the larger subset:
  - `L0/L1/L2/L3` each recorded `telemetry_logit_state_transfer_count=10`
- First full-25-case local-vLLM formal attempt was started:
  - run id: `v2-local-vllm-qwen3-32b-capprobe-formal25-20260712`
  - partial result:
    - `L0` completed with `25/25` quality-floor pass
    - `logit_state_transfer_count=25`
  - failure:
    - `L1/formal-anomaly-003` hit `openai.APITimeoutError`
    - the live `qwen3-32b` vLLM service still answered `/health` and continued exposing prefix-cache metrics after the failure
- A second full-25-case retry with increased client timeout was attempted:
  - run id: `v2-local-vllm-qwen3-32b-capprobe-formal25-timeout300-20260712`
  - request timeout override: `STATEBUS_LOCAL_VLLM_REQUEST_TIMEOUT_S=300`
  - failure:
    - immediate `AF_UNIX path too long`
    - root cause: the suite script validates only the root `control.sock` path, while per-case execution expands it to `control-<layer>-<task_id>.sock`
- A third retry completed successfully:
  - run id: `v2-q32b-f25-t300-0712`
  - request timeout override: `STATEBUS_LOCAL_VLLM_REQUEST_TIMEOUT_S=300`
  - reason for shorter run id:
    - keep the expanded per-case UDS path below the host `AF_UNIX` length ceiling while preserving the same formal workload
  - current verified progress:
    - `L0` completed with `25/25` quality-floor pass
    - `llm_total_tokens=122798`
    - `logit_state_transfer_count=25`
    - `logit_confidence_gate_trigger_count=0`
    - `L1` completed with `25/25` quality-floor pass
    - `L1 llm_total_tokens=130871`
    - `L1 logit_state_transfer_count=24`
    - `L1 logit_confidence_gate_trigger_count=0`
    - `L2` completed with `25/25` quality-floor pass
    - `L2 llm_total_tokens=64755`
    - `L2 logit_state_transfer_count=25`
    - `L2 logit_confidence_gate_trigger_count=0`
    - `L3` completed with `25/25` quality-floor pass
    - `L3 llm_total_tokens=64755`
    - `L3 logit_state_transfer_count=25`
    - `L3 logit_confidence_gate_trigger_count=0`
    - suite summary:
      - `selected cases=25 / 25`
      - `protocol_L3_total_tokens=64755`
      - `text_L0_total_tokens=122798`
      - `protocol_vs_text_token_delta=-58043`
      - `protocol_L3_prompt_tokens=50330`
      - `text_L0_prompt_tokens=101978`
      - `protocol_vs_text_prompt_token_delta=-51648`
      - `protocol_L3_control_bytes=11570`
      - `text_L0_control_bytes=42926`
      - `protocol_vs_text_control_bytes_delta=-31356`

## Artifacts / Run Paths

- Capability probe artifact:
  - `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/vllm_intermediate_state_capability_20260711.json`
- Persisted post-fix smoke:
  - `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-capprobe-smoke-fix-20260711/`
- Persisted short mini formal:
  - `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-capprobe-mini5-20260711/`
- Persisted 10-case mini formal:
  - `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-capprobe-mini10-20260712/`
  - `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-capprobe-mini10-20260712/runtime/benchmark_reports/v2-local-vllm-qwen3-32b-capprobe-mini10-20260712-formal-suite.json`
- First failed 25-case formal attempt:
  - `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-capprobe-formal25-20260712/`
- Second failed 25-case retry with long run id:
  - `/home/qcrs/statebus/runs/v2-local-vllm-qwen3-32b-capprobe-formal25-timeout300-20260712/`
- Successful short-id 25-case retry:
  - `/home/qcrs/statebus/runs/v2-q32b-f25-t300-0712/`
  - `/home/qcrs/statebus/runs/v2-q32b-f25-t300-0712/formal_suite.summary.json`
  - `/home/qcrs/statebus/runs/v2-q32b-f25-t300-0712/runtime/benchmark_reports/v2-q32b-f25-t300-0712-formal-suite.json`

## Failures And Limits

- Current endpoint does not expose hidden states through the OpenAI-compatible surface.
- Hidden-state flags are silently ignored, so they cannot be used as proof of support.
- Prefix-cache metrics remain gauge-only; no raw hit/miss counters are exposed.
- The simple logprob probe demonstrates observability and parseability, not calibrated uncertainty quality.
- The first full-25-case local-vLLM formal failed under the default `120s` client timeout even though the vLLM service remained healthy, so the initial long-run ceiling is “clean through `L0`, timeout encountered in `L1`”.
- A timeout-relaxed retry exposed an additional runner limitation:
  - longer run ids can still fail UDS bind/connect because per-case socket names append `-<layer>-<task_id>.sock` after the root path checked by `scripts/run_v2_local_vllm_formal_suite.sh`
- The short-id timeout-relaxed retry demonstrates the current workable recipe for full `25-case` local-vLLM formal on this host:
  - keep the live `qwen3-32b` service unchanged
  - use `STATEBUS_LOCAL_VLLM_REQUEST_TIMEOUT_S=300`
  - keep the run id short enough that expanded per-case UDS paths remain below the host `AF_UNIX` ceiling
- Current runtime work proves:
  - logprob capture
  - compact distribution serialization
  - telemetry counting
- Current runtime work does not yet prove:
  - a fully persisted `LogitStateRef` data-plane object being written and consumed end-to-end in the live path

## Final Git State

- Worktree remains dirty at end of turn.
- Relevant additions from this turn:
  - `scripts/probe_vllm_intermediate_state_capability.py`
  - `docs/improvement/20_v2_comprehensive_truth_audit_20260706/artifacts/vllm_intermediate_state_capability_20260711.json`
  - `docs/improvement/20_v2_comprehensive_truth_audit_20260706/32_vllm_intermediate_state_and_qwen32b_execution_log_20260711.md`
  - `tests/v2/test_logit_state.py`
- Relevant updated tracked files from this turn:
  - `runtime/llm.py`
  - `tests/test_llm_runtime.py`
  - `tests/v2/test_contracts_and_refs.py`
  - `v2/runtime/logit_state.py`
