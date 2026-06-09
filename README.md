# StateBus Project

This directory is the host-side development repo for the StateBus implementation.

Current strategy:

- Develop on the current Linux host.
- Use the isolated conda env under `$HOME/statebus/conda-envs/statebus_host`.
- Keep models, caches, logs, runs, and state artifacts under `$HOME/statebus`.
- Finish `Phase 0` to `Phase 4` here.
- Use openEuler VM only for posterior validation and final delivery checks.

## Read First

Before making large code or claim-surface changes, read:

- `docs/constraints/current_host_and_migration.md`
- `docs/constraints/current_feature_scope.md`
- `docs/planning/implementation_plan.md`
- `docs/reference/题目.md`

For the current host-side evidence stack, also read:

- `runs/comprehensive_eval_20260607_131113/SUMMARY.md`
- `runs/comprehensive_eval_20260607_131113/NOTES.md`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/SUMMARY.md`
- `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/SUMMARY.md`

## Quick Start

```bash
cd /home/qcrs/statebus/project
source deploy/activate_statebus_host.sh
python -m pytest -q
python -m runtime.smoke
```

## LLM API Config

`Planner` and `Summarizer` now use a shared OpenAI-compatible client abstraction.

- Main role/provider config: `deploy/statebus_llm.yaml.local`
- YAML template: `deploy/statebus_llm.yaml.example`
- Secret/override file: `deploy/statebus_llm.env.local`
- Env template: `deploy/statebus_llm.env.example`

Recommended split:

```bash
cp deploy/statebus_llm.yaml.example deploy/statebus_llm.yaml.local
cp deploy/statebus_llm.env.example deploy/statebus_llm.env.local
```

Then fill `STATEBUS_LLM_API_KEY` in `deploy/statebus_llm.env.local`.

Role behavior such as `provider`, `model`, `json_output`, `max_tokens`, and
vendor-specific `extra_body` now lives in the YAML file, so switching between
OpenAI-compatible models should not require Python changes.

## Model Paths

- Embedding: `/home/qcrs/statebus/models/Qwen3-Embedding-0.6B`
- Optional reranker: `/home/qcrs/statebus/models/Qwen3-Reranker-0.6B`

## Branch Roles

Current branch roles after the realism/protocol hardening merge:

- `main`
  - active implementation mainline
  - this is the default branch for new work
  - currently includes both the host-side prototype baseline and the realism/protocol hardening work
- `feat/realism-protocol-hardening`
  - historical topic branch for the realism/protocol hardening push
  - currently points to the same head as `main`
  - keep it as a comparison/reference pointer unless the user explicitly wants to reopen that topic as a separate line
- `baseline/statebus-host-prototype-20260607`
  - historical snapshot of the contestized host-side prototype before realism hardening
  - use it for regression comparison, explanation, or archaeology
  - do not base new development on it unless the user explicitly asks

Short version:

- new work starts from `main`
- `feat/...` explains how the hardening happened
- `baseline/...` explains what existed before the hardening pass

## Current Scope

Current implementation focus:

- `runtime`
- `protocol`
- `statepool`
- `memory`
- `agents`
- `eval`

Deferred until later:

- `nsjail`
- privileged container workflows
- openEuler-only validation
- final sandbox isolation path

## Current Validation Snapshot

The latest checked host-side comprehensive evaluation package is still:

- `runs/comprehensive_eval_20260607_131113/`

The latest host-goal verification package for the newer `18`-task replay-aware
task set is:

- `runs/host_goal_eval_20260607_233858/`

The earlier deterministic repeat-10 stability package for that same replay-aware
task set is:

- `runs/host_goal_eval_20260608_002101/`

The earlier deterministic repeat-10 regression package for the newer
runtime-evidence exact-replay and corpus-metadata retrieval path is:

- `runs/host_goal_eval_20260608_021820_runtime_exact_replay_det_repeat10/`

The earlier serialized API repeat-10 package for the current runtime-evidence
exact-replay and corpus-metadata retrieval path is:

- `runs/host_goal_eval_20260608_022627_runtime_exact_replay_api_repeat10/`

The latest full current-worktree refresh bundle after the provenance-aware
route-gate cleanup and planner-contract parser fix is:

- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`

The latest deterministic repeat-10 executor candidate-tool refresh bundle is:

- `runs/host_goal_eval_20260608_120619_executor_candidate_tool_refresh/`

The latest deterministic repeat-10 exact-replay doc-preference refresh bundle is:

- `runs/host_goal_eval_20260608_122921_exact_replay_drop_doc_preference_refresh/`

The latest deterministic repeat-10 runtime-profile trim refresh bundle is:

- `runs/host_goal_eval_20260608_124900_runtime_profile_trim_refresh/`

The latest controlled serialized API repeat-10 claim-boundary package for the
current `26`-task fairness surface is:

- `runs/host_goal_eval_20260609_085938_text_brief_fidelity_api_repeat10_serial/`

Current benchmark-pack split in the repo:

- `tasks/sample_benchmark.yaml`
  - formal controlled pack
  - use this for `communication`, scoped `state_transfer`, and replay-scoped
    `memory` headline claims
- `tasks/open_validation_benchmark.yaml`
  - support-only open validation pack
  - use this for retrieval / executor / replay boundary checks, retain/revert
    decisions, and misfire explanation
  - do not promote this pack into formal contest headline claims without a
    separate controlled rerun

The earlier deterministic + smoke refresh bundle after the provenance-aware
route-gate cleanup is:

- `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/`

Headline status from the current host-side evidence stack:

- host env is valid and `AF_UNIX` socket bind works on the host
- full pytest now passes: `56 passed`
- `runtime.smoke` now has a real module entry and emits visible stdout; the
  latest archived smoke log is non-empty in
  `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
- `nsjail` is still missing on the host
- Docker CLI exists, but the current user still cannot access `/var/run/docker.sock`
- the latest controlled serialized API `repeat=10` lane package confirms:
  - `communication` claim: supported
  - `state_transfer` claim: supported with the explicit
    `text brief handoff` baseline scope, after the text-side brief was tightened
    into a more complete executor handoff
  - `memory` claim: supported for `replay_enabled / step-skipping`, but
    `assist_only` still does not beat `memory_off`

Historical comprehensive package interpretation from
`runs/comprehensive_eval_20260607_131113/`:

- deterministic repeat-10:
  - `protocol` lowers control bytes relative to `text`
  - but deterministic mode does not yet produce a meaningful latency win
- formal API repeat-10:
  - only `api_repeat10_serial/` should be treated as formal latency evidence
  - `protocol` lowers control bytes, live API tokens, and end-to-end wall-clock time relative to `text`
- shared-memory and `UDS`:
  - both are real host-feasible paths
  - in the current package they are capability checks, not the main performance headline
- memory reuse:
  - reuse lookup and validation are working
  - but current benchmark shape is still assist-only, not step-skipping

Host-goal verification interpretation from `runs/host_goal_eval_20260607_233858/`:

- deterministic repeat-1 on the current `18`-task set:
  - both modes finish with `failure_count = 0`
  - both modes now show non-zero replay gain:
    - `skipped_step_count = 9`
    - `reuse_gain = 0.17`
  - `protocol` still lowers control bytes relative to `text`
  - but this deterministic rerun is still not a formal latency headline
- serialized API repeat-1 on the same `18`-task set:
  - `protocol` lowers control bytes from `100615.00` to `85903.00`
  - `protocol` lowers live API tokens from `22850.00` to `16822.00`
  - `protocol` lowers end-to-end wall-clock time from `86594.07 ms` to `72173.55 ms`
  - both modes keep the same replay gain headline:
    - `skipped_step_count = 9`
    - `reuse_gain = 0.17`

Replay-aware repeat-10 interpretation from
`runs/host_goal_eval_20260608_002101/deterministic_repeat10/`:

- deterministic repeat-10 on the current `18`-task set:
  - both modes finish all `10` runs with `failure_count = 0`
  - both modes keep `expectation_match_rate = 1.00`
  - both modes keep the replay headline stable:
    - `skipped_step_count = 9`
    - `reuse_gain = 0.17`
  - `protocol` lowers total control bytes from `147701.00` to `133167.00`
  - this package also records explicit runtime gate counts and replay slices:
    - `allow_memory_assist = 12`
    - `allow_execute_prune = 3`
    - `allow_exact_replay = 3`
- this is still a deterministic stability package, not a new formal API timing package

Runtime-evidence exact-replay deterministic repeat-10 regression interpretation
from `runs/host_goal_eval_20260608_021820_runtime_exact_replay_det_repeat10/deterministic_repeat10/`:

- this package is for the current exact-replay cleanup plus the newer
  corpus-metadata retrieval path, not a new live API headline
- both modes still finish all `10` runs with:
  - `failure_count = 0`
  - `expectation_match_rate = 1.00`
  - `skipped_step_count = 9`
  - `reuse_gain = 0.17`
- `protocol` still lowers control bytes from `149086.00` to `134485.00`
- the exact-replay guarantee is now stronger:
  - all three `skip_retrieve_execute` benchmark tasks still skip correctly
  - their archived `replay_source_task_id` values are now empty/null
- use this package when you need the current deterministic regression evidence
  for the replay-semantics cleanup and retrieval-side de-specialization path

Current-worktree deterministic repeat-10 refresh interpretation from
`runs/host_goal_eval_20260608_084835_provenance_gate_refresh/deterministic_repeat10/`:

- this package reruns the deterministic stability pass after the
  provenance-aware replay gate cleanup on the current worktree
- both modes still finish all `10` runs with:
  - `failure_count = 0`
  - `expectation_match_rate = 1.00`
  - `skipped_step_count = 9`
  - `reuse_gain = 0.17`
  - `memory_hit_rate = 0.83`
- `protocol` still lowers total control bytes from `148142.00` to `133875.00`
- deterministic wall-clock also now trends slightly lower in `protocol`:
  - `6433.43 ms -> 6396.95 ms`
- the exact-replay payloads now archive provenance-aware route evidence rather
  than metadata-only route claims:
  - `feature_route_source = hint_consensus`
  - `feature_route_provenance = ["corpus_metadata", "lexical"]`
- the host regression gate is also stronger in this bundle because
  `runtime_smoke.txt` is no longer empty
- use this package when you need the freshest deterministic proof for the
  current dirty worktree after the provenance gate cleanup

Runtime-evidence exact-replay serialized API repeat-10 interpretation from
`runs/host_goal_eval_20260608_022627_runtime_exact_replay_api_repeat10/api_repeat10_serial/`:

- both modes finish all `10` runs with `failure_count = 0`
- both modes keep `expectation_match_rate = 1.00`
- both modes keep the replay headline stable:
  - `skipped_step_count = 9`
  - `reuse_gain = 0.17`
- memory lookup also stays aligned:
  - `memory_hit_rate = 0.83`
  - `memory_hit_task_count = 15`
- `protocol` lowers total control bytes from `103525.30` to `89380.80`
- `protocol` lowers live API total tokens from `24986.20` to `17995.00`
- `protocol` lowers end-to-end wall-clock time from `93830.97 ms` to `77792.77 ms`
- this package is the live API companion to the current exact-replay cleanup:
  - the three `skip_retrieve_execute` tasks still skip under live API reruns
  - archived exact-replay payloads keep `feature_route_source = corpus_metadata`
    in that earlier pre-provenance bundle

Current-worktree serialized API repeat-10 refresh interpretation from
`runs/host_goal_eval_20260608_093111_planner_contract_refresh/api_repeat10_serial/`:

- this package reruns the formal serialized API pass after the provenance-aware
  route-gate cleanup and the planner-contract parser tolerance fix
- both modes still finish all `10` runs with:
  - `failure_count = 0`
  - `expectation_match_rate = 1.00`
  - `skipped_step_count = 9`
  - `reuse_gain = 0.17`
  - `memory_hit_rate = 0.83`
- `protocol` lowers total control bytes from `103503.10` to `88789.80`
- `protocol` lowers live API total tokens from `24384.40` to `16625.90`
- `protocol` lowers end-to-end wall-clock time from `81184.06 ms` to
  `60776.34 ms`
- the exact-replay route remains intact after the fix:
  - the three `skip_retrieve_execute` tasks still skip under live API reruns
  - text mode no longer drops `sample-cache-006` on a planner numeric-step-id
    wobble
- this is now the latest formal live API timing bundle on the current
  provenance-aware worktree

Current `26`-task serialized API repeat-10 claim-boundary interpretation from
`runs/host_goal_eval_20260609_085938_text_brief_fidelity_api_repeat10_serial/`:

- this package refreshes the earlier `230711` formal lane bundle after the
  text-side `state_transfer` brief was tightened into a more complete executor
  handoff
- both modes finish all `10` runs with:
  - `failure_count = 0`
  - `expectation_match_rate = 1.00`
- aggregate still favors `protocol`:
  - control bytes: `150876.20 -> 128743.80`
  - live API total tokens: `29727.80 -> 19882.30`
  - end-to-end wall-clock: `127173.46 ms -> 100976.55 ms`
- the more important contest-claim reading comes from the lane tables:
  - `communication`
    - control bytes: `5838.25 -> 4944.60`
    - total tokens: `1140.25 -> 727.70`
    - task time: `5133.40 ms -> 3907.84 ms`
  - `state_transfer`
    - text-side baseline remains `text brief handoff to executor`
    - the text-side brief is now a more complete executor handoff, so the text
      baseline is more honest rather than cheaper
    - control bytes: `5148.30 -> 4603.23`
    - handoff textual bytes: `1725.00 -> 738.00`
    - handoff non-text bytes: `0.00 -> 1704.67`
    - total tokens: `1116.07 -> 698.53`
    - task time: `4840.01 -> 3804.30`
  - `memory`
    - `replay_enabled` still shows stable step-skipping gain
    - `assist_only` still does not beat `memory_off`
- use this package when the question is:
  - what the current host-mainline can honestly claim for the contest surface
  - what it still cannot claim without overstatement

Interpretation boundary:

- `runs/comprehensive_eval_20260607_131113/` remains the older assist-only comprehensive baseline and broader host-side capability package
- `runs/host_goal_eval_20260607_233858/` proves the replay-aware route first became real in both deterministic `repeat=1` and serialized API `repeat=1`
- `runs/host_goal_eval_20260608_002101/` upgrades that replay-aware route to deterministic `repeat=10` stability and adds explicit contract/axis reporting
- `runs/host_goal_eval_20260608_004449/` remains the earlier serialized API `repeat=10` replay-aware package before the current exact-replay cleanup
- `runs/host_goal_eval_20260608_022627_runtime_exact_replay_api_repeat10/` upgrades that same replay-aware route to the earlier formal serialized API `repeat=10` timing evidence after the runtime-evidence exact-replay cleanup
- `runs/host_goal_eval_20260608_032333_runtime_reuse_contract_refresh/` remains
  the earlier runtime-reuse-contract cleanup refresh bundle
- `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/` remains the
  first provenance-aware smoke + deterministic refresh, but its
  `api_repeat10_serial/` subdirectory is an incomplete diagnostic rerun
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/` is now the
  latest full current-worktree bundle with regression gate, deterministic
  repeat-10, and serialized API repeat-10
- `runs/host_goal_eval_20260608_230711_26task_api_repeat10_serial/` remains the
  earlier formal `26`-task lane package before the text-side brief fidelity
  refresh; use it as the historical comparison point rather than the latest
  truth
- `runs/host_goal_eval_20260608_120619_executor_candidate_tool_refresh/`
  is the latest deterministic bundle for the executor candidate-tool boundary;
  it keeps `tool_candidates` in `FEATURE_BUNDLE` without echoing them into the
  execute payload
- `runs/host_goal_eval_20260608_122921_exact_replay_drop_doc_preference_refresh/`
  is the latest deterministic bundle for the exact-replay gate after dropping
  current-task `preferred_corpus_doc_ids` from the skip-retrieve-execute path
- `runs/host_goal_eval_20260608_124900_runtime_profile_trim_refresh/`
  is the latest deterministic bundle after moving corpus doc ids to task-level
  input and trimming them out of `RuntimeTaskProfile`
- `runs/host_goal_eval_20260608_130836_runtime_drop_reuse_tags_refresh/`
  is the latest deterministic bundle after dropping `reuse_tags` from live
  runtime memory-query prefilters
- for current live API timing claims on the replay-aware `18`-task host
  mainline, cite `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`
- for the current `26`-task fairness / contest-claim surface under serialized
  live API `repeat=10`, cite
  `runs/host_goal_eval_20260609_085938_text_brief_fidelity_api_repeat10_serial/`
- for the first provenance-aware route-proof bundle before the planner fix,
  cite `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/`

Use these files for the authoritative current snapshot:

- `runs/comprehensive_eval_20260607_131113/SUMMARY.md`
- `runs/comprehensive_eval_20260607_131113/api_repeat10_serial/benchmark_report.md`
- `runs/comprehensive_eval_20260607_131113/deterministic_repeat10/benchmark_report.md`
- `runs/host_goal_eval_20260607_233858/SUMMARY.md`
- `runs/host_goal_eval_20260608_002101/SUMMARY.md`
- `runs/host_goal_eval_20260608_021820_runtime_exact_replay_det_repeat10/SUMMARY.md`
- `runs/host_goal_eval_20260608_022627_runtime_exact_replay_api_repeat10/SUMMARY.md`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/SUMMARY.md`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/deterministic_repeat10/benchmark_report.md`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/api_repeat10_serial/benchmark_report.md`
- `runs/host_goal_eval_20260608_120619_executor_candidate_tool_refresh/deterministic_repeat10/benchmark_report.md`
- `runs/host_goal_eval_20260608_122921_exact_replay_drop_doc_preference_refresh/deterministic_repeat10/benchmark_report.md`
- `runs/host_goal_eval_20260608_124900_runtime_profile_trim_refresh/deterministic_repeat10/benchmark_report.md`
- `runs/host_goal_eval_20260608_130836_runtime_drop_reuse_tags_refresh/deterministic_repeat10/benchmark_report.md`
- `runs/host_goal_eval_20260608_230711_26task_api_repeat10_serial/benchmark_report.md`
- `runs/host_goal_eval_20260608_230711_26task_api_repeat10_serial/benchmark_results.json`
- `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/SUMMARY.md`
- `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/deterministic_repeat10/benchmark_report.md`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/pytest_q.txt`
- `runs/host_goal_eval_20260608_093111_planner_contract_refresh/runtime_smoke.txt`
- `docs/progress/host_goal_26task_serialized_api_decision_20260608.md`

## Current Engineering Scope

Current host-feasible implementation status:

- `protocol` mode uses checked-in `.proto + pb2` control frames
- remote executor wire path is converged into protobuf rather than an ad hoc side channel
- `StateRef` supports `mmap` and Python `shared_memory`
- shared memory is a real benchmark option, not just a dormant backend
- `Executor` is now tool-registry-based with a lightweight subprocess fallback
- `Executor` now prefers a small ranked `tool_candidates` set from
  `FEATURE_BUNDLE`, while keeping that candidate list out of the execute payload
- exact replay no longer requires current-task `preferred_corpus_doc_ids`; the
  skip-retrieve-execute gate now keys off memory-archived query/route/evidence
  consistency instead
- corpus doc ids now travel as task-level corpus hints, not runtime profile side-band
- runtime memory lookup no longer uses benchmark `reuse_tags` as a live
  candidate prefilter; the runtime profile is now just the explicit
  `runtime_reuse_contract`
- `Executor` can also run as an external multi-process UDS sample transport
- non-text state now includes `FEATURE_BUNDLE` in addition to `EMBEDDING`
- retrieved corpus docs can now contribute route/tool hints, but the archived
  `FEATURE_BUNDLE` now records route provenance / confidence and allows lexical
  evidence to override conflicting metadata hints
- repo-local benchmark corpora and sample tasks now live under `tasks/`

Scope notes:

- the current subprocess executor is a host-side fallback, not `nsjail`
- the current UDS executor path is a real sample transport, not the final distributed runtime
- hidden-state / KV-style intermediate representations are still deferred
- Docker / openEuler / stronger sandboxing stay in the later validation phase

See [docs/constraints/current_feature_scope.md](docs/constraints/current_feature_scope.md) for the precise boundary between what is already host-feasible and what must be deferred.

## Measurement Discipline

When writing docs, reports, or future benchmark summaries, keep these boundaries explicit:

- For API latency claims, only serialized reruns count as formal evidence.
- In the current comprehensive eval package, `api_repeat1/` and `api_repeat10/` are diagnostic-only because they were first launched concurrently.
- The historical comprehensive package's formal API directories are:
  - `api_repeat1_serial/`
  - `api_repeat10_serial/`
- `shared_memory` and `UDS` are currently validated as host-feasible execution paths, but not yet the main formal comparison axis.
- A matched backend comparison route now exists via `scripts/run_statepool_backend_matrix.py`.
- Current backend evidence is split into:
  - deterministic preflight: `runs/statepool_backend_matrix_20260608_012235/`
  - serialized API repeat-3 verification: `runs/statepool_backend_matrix_20260608_013044_api_repeat3/`
- The current honest backend takeaway is mixed rather than headline-simple:
  - in protocol mode, `shared_memory` is faster
  - in text mode, `shared_memory` is slower
  - so `shared_memory` is still not a single-direction main performance headline
- For the older comprehensive package, memory reuse should still be described as assist-style reuse.
- For `runs/host_goal_eval_20260607_233858/`, step skipping first becomes real and measurable because `reuse_gain` and `skipped_step_count` are non-zero.
- For `runs/host_goal_eval_20260608_002101/`, that replay-aware route is now also stable across deterministic `repeat=10`, and the report explicitly splits `cold_start` / `reject_control` / `assist` / `validated_replay` / `exact_replay`.
- For `runs/host_goal_eval_20260608_004449/`, that same replay-aware route first gained serialized API `repeat=10` formal timing evidence.
- For `runs/host_goal_eval_20260608_022627_runtime_exact_replay_api_repeat10/`, the exact-replay cleanup and corpus-metadata retrieval path first gained serialized API `repeat=10` formal timing evidence before the current-worktree refresh.
- For `runs/host_goal_eval_20260608_093111_planner_contract_refresh/`, the
  current provenance-aware worktree has now been rerun end to end after the
  planner-contract parser fix, with fresh host regression, deterministic
  `repeat=10`, and serialized API `repeat=10` evidence.
- For `runs/host_goal_eval_20260608_084835_provenance_gate_refresh/`, the
  current worktree first fixed the empty smoke log issue and archived
  `hint_consensus` + lexical provenance in exact-replay payloads, but its
  `api_repeat10_serial/` directory should be treated as an incomplete
  diagnostic rerun rather than the formal live API reference.
- In the current code, runtime reuse gating is now fronted by a single `runtime_reuse_contract`; `expected_reuse_mode` remains the benchmark-validation label, and the reported `allow_*` counts are derived projections of that runtime contract.
- Do not collapse those evidence layers into one sentence; the historical comprehensive baseline, the replay-aware `repeat=1` proof, the replay-aware deterministic `repeat=10` stability package, and the replay-aware serialized API `repeat=10` package must stay separate.
- Do not claim `nsjail`, Docker-based execution, or openEuler compatibility unless they were validated in the proper later-stage environment.

## Benchmark Examples

Default `mmap` mainline:

```bash
source deploy/activate_statebus_host.sh
python -m eval.runner --repeat 1 --llm-mode deterministic --out /tmp/statebus_mmap_demo
```

Shared-memory benchmark route:

```bash
source deploy/activate_statebus_host.sh
python -m eval.runner \
  --repeat 1 \
  --llm-mode deterministic \
  --statepool-backend shared_memory \
  --embed-state-backend shared_memory \
  --out /tmp/statebus_shm_demo
```

Matched `mmap` vs `shared_memory` backend matrix:

```bash
source deploy/activate_statebus_host.sh
python scripts/run_statepool_backend_matrix.py \
  --repeat 3 \
  --llm-mode api \
  --out /tmp/statebus_backend_matrix
```

External `UDS` executor sample transport:

```bash
source deploy/activate_statebus_host.sh
python -m eval.runner \
  --repeat 1 \
  --modes protocol \
  --llm-mode deterministic \
  --executor-transport uds \
  --out /tmp/statebus_uds_demo
```

Notes:

- `UDS` transport requires a real host environment that allows `AF_UNIX` sockets.
- some managed sandboxes may block Unix sockets; in that case this path should be verified directly on the host.
