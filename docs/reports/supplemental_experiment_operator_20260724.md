# StateBus Supplemental Experiment Operator Guide

Date: 2026-07-24

## 1. Current Decision

The fixed baseline already proves the three mechanisms that matter to the
contest story:

1. E1 proves typed control and the whole-stack token/wire reduction.
2. E4 proves that a non-text embedding matrix is consumed numerically across
   PIDs through `SemanticStateRef`, changes selected evidence, and is released.
3. E3 proves compatibility-gated memory consumption, behavioral effects, one
   incompatible rejection with recomputation, and one skipped LLM call.

The supplemental run therefore does not repeat E0-E6. It answers only two
remaining presentation questions:

| Experiment | Run now | Exact question | Result boundary |
| --- | --- | --- | --- |
| P0-lite | Yes, if the PPT wants a latency statement | On the same ten causal-core tasks, what is the quality-gated L3-L0 task-time change under balanced order? | One AB/BA sanity cycle; descriptive rather than publication-grade significance. |
| P1-lite | Yes, if the PPT wants memory cost/value on a common runner | What changes between current L2 (memory replay OFF) and L3 (actual memory query/use ON)? | Current-stack attribution only; not a frozen-snapshot or gate-only isolation. |
| P2/T2 | No by default | Is the StateRef carrier itself faster than a same-selection text carrier? | Unneeded unless the PPT explicitly claims carrier speed. |

P2 is intentionally absent from `all`. The local T2 implementation already
exists as `run_continuous_text_semantic_selection_family` in
`statebus/benchmark/continuous_runner.py`, and later development artifacts also
exist. Canonical E4 is already enough for the mechanism innovation claim. A
new T2 run is justified only to promote the stronger statement "the carrier
itself is faster"; the current PPT does not need that statement.

## 2. Why P1 Is Deliberately Lite

The current baseline runner has these useful adjacent layers:

```text
L2 = typed control + semantic pruning + SemanticStateRef, replay/memory query OFF
L3 = the same stack + replay/memory query/compatibility/consumption ON
```

It does not expose a supported `gate-only but withhold injection` CLI switch,
nor does it restore an identical immutable memory snapshot before every lane.
Adding those features now would be a new implementation project, not a test
script. The practical run therefore uses L2/L3 and labels the result P1-lite.

The incompatible negative is not repeated. Canonical E3 already records:

- 6 queries, 16 candidates and 15 compatible/approved matches;
- 23 consumption records and 23 behavioral effects;
- 1 incompatible fixture rejected and recomputed;
- 1 skipped step and 1 skipped LLM call.

This preserves the useful split:

```text
E3 -> safety and truth of memory reuse
P1-lite -> fresh common-runner cost/value sanity
```

Do not rename the P1-lite result to a frozen-snapshot causal experiment. If a
strict net-value claim later becomes necessary, implement M0/M1/M2 snapshot
restore and gate-only control as a separate, explicit change.

## 3. Fixed Runtime Environment

The operator script uses the existing repository and container:

| Item | Fixed value |
| --- | --- |
| Host repository | `/home/qcrs/statebus/project` |
| Container | `statebus-dev-qcrs` |
| Container image target when creation is needed | `embed` |
| Role model service | existing `qwen3-32b` vLLM at `http://127.0.0.1:53334/v1` |
| vLLM policy | health-check and reuse only; never launch, stop, kill or restart |
| Embedding model | `/statebus/models/Qwen3-Embedding-0.6B` |
| Physical embedding GPU | host GPU 2 |
| Device seen by the experiment process | `cuda:0`, through `CUDA_VISIBLE_DEVICES=2` |
| Runtime | container, local vLLM roles, local GPU embedding, subprocess transport, shared memory |
| Task source | existing `causal_core`: five financial plus five operating cases |
| Persistence | `audit_full` |

The container uses host networking, so it can reuse the host vLLM service. The
script sources `deploy/statebus_llm.env.local` indirectly through the existing
container activation script; it neither prints nor copies the API key.

The preflight checks four things and then stops touching service state:

1. the container exists or can be started without rebuilding;
2. the embedding model directory exists;
3. physical GPU 2 maps to the single visible container device `cuda:0`;
4. the existing vLLM `/health` endpoint returns HTTP 200.

APC/Prefix state in the reused vLLM is shared service state. AB/BA order makes
the sanity result more reasonable, but it does not isolate APC. No result from
this script may be presented as a Prefix optimization result.

## 4. Exact Schedule

Warm-ups are excluded from the summary. Each warm-up uses one existing formal
financial case. Measured lanes use all ten causal-core cases and run serially.

### P0-lite

```text
excluded warm-up: L0, L3
AB block:         L0 -> L3
BA block:         L3 -> L0
```

The two blocks produce 20 paired task observations. This is enough for a PPT
sanity table and crossover diagnosis. It is not the four- or six-block formal
campaign described as the ideal design in the baseline compendium.

### P1-lite

```text
excluded warm-up: L2, L3
AB block:         L2 OFF -> L3 actual-use
BA block:         L3 actual-use -> L2 OFF
```

All rounds remain in the summary, including cold/no-use rounds. The script
does not filter the task set after seeing memory hits.

## 5. Commands

Run from the original repository. The script starts the existing container if
it is stopped, or creates it from the already-built `embed` image if absent.
It never builds an image automatically.

```bash
cd /home/qcrs/statebus/project

# Only P0-lite.
scripts/experiments/run_supplemental_experiments_gpu2.sh latency

# Only P1-lite.
scripts/experiments/run_supplemental_experiments_gpu2.sh memory

# Both. T2 is not included.
scripts/experiments/run_supplemental_experiments_gpu2.sh all
```

An explicit fresh result directory can be supplied as the second argument. It
must be below `/home/qcrs/statebus/runs` and must not already exist:

```bash
scripts/experiments/run_supplemental_experiments_gpu2.sh all \
  /home/qcrs/statebus/runs/contest_recovery_supplemental_manual_01
```

The service is already warm in normal operation. To shorten a diagnostic run,
the excluded one-case warm-ups can be skipped explicitly:

```bash
STATEBUS_SUPPLEMENTAL_SKIP_WARMUP=1 \
  scripts/experiments/run_supplemental_experiments_gpu2.sh latency
```

Do not run `latency` and `memory` concurrently. The script holds a host lock
and exits if another supplemental campaign is active.

## 6. Silent Execution And Failure Behavior

Every runner invocation is a blocking `docker exec`. Its stdout and stderr are
redirected to the lane's `console.log`. There is no polling loop and no periodic
terminal output while a lane is running. The operator sees only:

1. preparation and preflight completion;
2. silence while the benchmark runs;
3. final result paths, or an error plus the last 80 log lines.

This is intentional. Do not wrap it in a frequent `docker logs`, `ps`, or file
polling loop. If an external monitor is required, five-minute intervals are
enough, but the script itself does not need them.

## 7. Metrics And Fair Interpretation

P0 uses `task_ms` as the primary task-level observation and also retains:

- process-level `operator_wall_ms`, including runner startup;
- `llm_wall_ms`;
- `runtime_non_llm_ms = task_ms - llm_wall_ms`;
- prompt/completion/total tokens and LLM-call count;
- control and total wire bytes;
- control-plane, CodeAct, runtime-driver, signature, persistence, workspace and
  telemetry spans;
- all per-case quality gates.

The stage spans are diagnostic parent/child timers. They must not be added to
manufacture a second end-to-end total. A fair slide shows the observed task
delta, the LLM-time delta, and selected safety/runtime spans side by side.

Interpret P0 as follows:

```text
quality fails
  -> no performance comparison

quality passes and L3 is faster
  -> descriptive full-stack latency reduction on these tasks

quality passes and L3 is equal/slower
  -> token/wire advantage remains; show the measured safety overhead and
     workload crossover instead of claiming universal speedup
```

P1 retains the full memory funnel:

- query, candidate, compatible and policy-approved counts;
- consumption and behavioral-effect counts;
- incompatible rejection, skipped-step and skipped-call counts;
- case-level compatible/use/effect/skipped-work rates;
- task, LLM, token and wire deltas between L2 and L3.

The generated report calls the rate a `query-case rate`: among cases that
issued a memory query, how many had at least one compatible match, actual
consumption, behavioral effect, or skipped work. It does not divide raw receipt
counts by query count and mislabel that ratio as a hit rate.

## 8. CodeAct And LLM Boundary

P0/P1 use:

```text
Planner     -> local vLLM
Retriever   -> local vLLM + local GPU embedding
Executor    -> deterministic_codeact
Summarizer  -> local vLLM
```

`deterministic_codeact` means the Executor does not ask the LLM to invent
Python. The runtime builds a fixed, bounded CodeAct plan from the task contract,
executes it in the configured sandbox and validates the artifact. This keeps
P0/P1 focused on the StateBus stack rather than code-generation variance.

E5 adaptive CodeAct is different. In that experiment the Executor LLM really
generates bounded Python for the selected capability, then policy checks,
sandbox execution and artifact validation run. That path is needed to prove
adaptive CodeAct coverage, and E5 already provides 18 bounded-Python plus 7 DSL
cases. It does not need to be repeated for P0/P1.

The following mechanisms do not inherently require LLM-written code:

- typed Protobuf/UDS control;
- StateRef publish, open, consume and release;
- embedding/cosine selection;
- memory retrieval, compatibility gating and receipt recording;
- a carrier-only T2b microbenchmark.

They may still coexist with LLM roles in an integrated task, but the mechanism
itself is deterministic runtime logic.

## 9. Result Layout

Each invocation creates a new root under `/home/qcrs/statebus/runs`:

```text
contest_recovery_supplemental_<mode>_<timestamp>/
  run_manifest.json
  preflight.log
  warmup/
  latency/AB|BA/<order-layer>/
  memory/AB|BA/<order-layer>/
    lane_manifest.json
    operator_timing.json
    console.log
    runtime/
    workspaces/
  supplemental_summary.json
  supplemental_summary.md
  summarizer.log
```

The Markdown report is the PPT reading surface. The JSON report retains each
case, paired deltas, lane totals, stage metrics and memory rates for later
audit. Raw runner artifacts remain under each lane and are not collapsed or
deleted.
