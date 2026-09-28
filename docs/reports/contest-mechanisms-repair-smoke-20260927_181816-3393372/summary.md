# Contest Memory/State Mechanism Results

- Raw root: `/home/qcrs/statebus/os/runs/contest-mechanisms-repair-smoke-20260927_181816-3393372`
- Planned / started / passed: 24 / 2 / 2
- Environment: `openEuler 24.03 LTS-SP3`, container `statebus-runtime`, source `/workspace/statebus/os`.
- Model/API: `qwen3-32b` on physical GPU 2 at `http://127.0.0.1:53334/v1`, context 8192.
- Embedding: `/statebus/models/Qwen3-Embedding-0.6B` on physical GPU 1 (container `cuda:0`).
- Runtime Python: `/home/qcrs/statebus/conda-envs/statebus_host/bin/python`
- Provider tokens are provider usage, not Agent communication tokens; no wire-byte estimate is made.

## Actual runner command

```bash
bash scripts/run_contest_mechanisms.sh \
  --mechanism state \
  --mode live \
  --output /home/qcrs/statebus/os/runs/contest-mechanisms-repair-smoke-20260927_181816-3393372 \
  --case-id semantic-holdout-s1
```

## Memory matched tasks

| Task | Off status | On status | Off quality | On quality | Off ms | On ms | Off tokens | On tokens | Consumed | Replay | Source | Reason |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| F01 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |
| F02 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |
| F06 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |
| F07 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |
| O01 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |
| O02 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |
| O06 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |
| O07 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |

### Memory four-round totals

| Family | Variant | Started | Passed | Requests | Tokens | Task ms sum |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| finance | off | 0 | 0 | - | - | - |
| finance | on | 0 | 0 | - | - | - |
| service_ops | off | 0 | 0 | - | - | - |
| service_ops | on | 0 | 0 | - | - | - |

## State matched tasks

| Task | Off status | On status | Off quality | On quality | Off chars | On chars | Off tokens | On tokens | Consume | Cross-PID | Effect | On reason |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| semantic-holdout-s1 | success | success | yes | yes | 1184 | 1184 | 7616 | 9543 | 2.000 | yes | no_effect | - |
| semantic-holdout-s5 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |
| semantic-holdout-s4 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |
| semantic-holdout-s8 | not_started | not_started | - | - | - | - | - | - | - | - | - | - |

### State variant totals

| Variant | Started | Passed | Requests | Tokens | Task ms sum |
| --- | ---: | ---: | ---: | ---: | ---: |
| off | 1 | 1 | 4 | 7616 | 111866.190 |
| on | 1 | 1 | 5 | 9543 | 130956.651 |

## Observed and not proven

- The bounded smoke observed real Memory replay on current input when recorded; unstarted formal slots prove nothing.
- State publication/transfer/consumption can be observed even when `behavioral_effect=no_effect` or business quality fails.
- Savings ratios are computed only for complete, quality-passing, non-zero matched pairs.
- Candidate hit, actual consumption, and validated replay are separate observations.
- `no_effect` is not a benefit claim, and provider tokens are not inter-agent communication tokens.
- This report describes the recorded raw batch; later implementation fixes are not retroactively claimed as live evidence.

## Collector command

```bash
bash scripts/run_contest_mechanisms.sh --collect-only --output /home/qcrs/statebus/os/runs/contest-mechanisms-repair-smoke-20260927_181816-3393372 --collect-output <new-report-root>
```
