# Contest Memory/State Mechanism Results

- Raw root: `/home/qcrs/statebus/os/runs/contest-mechanisms-20260927_171109-3234416`
- Planned / started / passed: 24 / 24 / 23
- Environment: `openEuler 24.03 LTS-SP3`, container `statebus-runtime`, source `/workspace/statebus/os`.
- Model/API: `qwen3-32b` on physical GPU 2 at `http://127.0.0.1:53334/v1`, context 8192.
- Embedding: `/statebus/models/Qwen3-Embedding-0.6B` on physical GPU 1 (container `cuda:0`).
- Runtime Python: `/home/qcrs/statebus/conda-envs/statebus_host/bin/python`
- Provider tokens are provider usage, not Agent communication tokens; no wire-byte estimate is made.

## Actual runner command

```bash
bash scripts/run_contest_mechanisms.sh \
  --mechanism all \
  --mode live \
  --output /home/qcrs/statebus/os/runs/contest-mechanisms-20260927_171109-3234416
```

## Memory matched tasks

| Task | Off status | On status | Off quality | On quality | Off ms | On ms | Off tokens | On tokens | Consumed | Replay | Source | Reason |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| F01 | success | success | yes | yes | 83185.316 | 72666.150 | 3402 | 3402 | no | no | - | no-match |
| F02 | success | success | yes | yes | 74098.079 | 44264.223 | 3411 | 1339 | yes | yes | F01 | validated_replay_consumed |
| F06 | success | success | yes | yes | 75534.148 | 74314.900 | 3427 | 3427 | no | no | - | incompatible |
| F07 | success | success | yes | yes | 99626.845 | 45489.626 | 6646 | 1359 | yes | yes | F06 | validated_replay_consumed |
| O01 | success | success | yes | yes | 51394.544 | 50274.937 | 2934 | 2934 | no | no | - | no-match |
| O02 | success | success | yes | yes | 51292.106 | 31329.558 | 2949 | 1083 | yes | yes | O01 | validated_replay_consumed |
| O06 | success | success | yes | yes | 52086.406 | 50515.633 | 2940 | 2940 | no | no | - | incompatible |
| O07 | success | success | yes | yes | 62962.997 | 32118.983 | 5757 | 1097 | yes | yes | O06 | validated_replay_consumed |

### Memory four-round totals

| Family | Variant | Started | Passed | Requests | Tokens | Task ms sum |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| finance | off | 4 | 4 | 9 | 16886 | 332444.389 |
| finance | on | 4 | 4 | 6 | 9527 | 236734.899 |
| service_ops | off | 4 | 4 | 9 | 14580 | 217736.053 |
| service_ops | on | 4 | 4 | 6 | 8054 | 164239.112 |

## State matched tasks

| Task | Off status | On status | Off quality | On quality | Off chars | On chars | Off tokens | On tokens | Consume | Cross-PID | Effect | On reason |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| semantic-holdout-s1 | success | quality_fail | yes | no | 1184 | 1184 | 7565 | 8538 | 2.000 | yes | no_effect | output_validation_failed |
| semantic-holdout-s5 | success | success | yes | yes | 304 | 304 | 7052 | 7043 | 3.000 | yes | no_effect | - |
| semantic-holdout-s4 | success | success | yes | yes | 568 | 568 | 15521 | 13793 | 2.000 | yes | no_effect | - |
| semantic-holdout-s8 | success | success | yes | yes | 292 | 292 | 11897 | 11923 | 3.000 | yes | no_effect | - |

### State variant totals

| Variant | Started | Passed | Requests | Tokens | Task ms sum |
| --- | ---: | ---: | ---: | ---: | ---: |
| off | 4 | 4 | 21 | 42035 | 614486.355 |
| on | 4 | 3 | 20 | 41297 | 582504.955 |

## Observed and not proven

- The bounded smoke observed real Memory replay on current input when recorded; unstarted formal slots prove nothing.
- State publication/transfer/consumption can be observed even when `behavioral_effect=no_effect` or business quality fails.
- Savings ratios are computed only for complete, quality-passing, non-zero matched pairs.
- Candidate hit, actual consumption, and validated replay are separate observations.
- `no_effect` is not a benefit claim, and provider tokens are not inter-agent communication tokens.
- This report describes the recorded raw batch; later implementation fixes are not retroactively claimed as live evidence.

## Collector command

```bash
bash scripts/run_contest_mechanisms.sh --collect-only --output /home/qcrs/statebus/os/runs/contest-mechanisms-20260927_171109-3234416 --collect-output <new-report-root>
```
