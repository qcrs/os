# Contest Memory/State Mechanism Results

- Raw root: `/home/qcrs/statebus/os/runs/contest-mechanisms-smoke-20260927_164855-3166537`
- Planned / started / passed: 24 / 6 / 5
- Provider tokens are provider usage, not Agent communication tokens; no wire-byte estimate is made.

## Memory matched tasks

| Task | Off quality | On quality | Off ms | On ms | Off tokens | On tokens | Consumed | Replay | Source | Reason |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| F01 | yes | yes | 84633.422 | 73195.240 | 3402 | 3402 | no | no | - | no-match |
| F02 | yes | yes | 74648.163 | 44254.951 | 3411 | 1339 | yes | yes | F01 | validated_replay_consumed |
| F06 | - | - | - | - | - | - | - | - | - | - |
| F07 | - | - | - | - | - | - | - | - | - | - |
| O01 | - | - | - | - | - | - | - | - | - | - |
| O02 | - | - | - | - | - | - | - | - | - | - |
| O06 | - | - | - | - | - | - | - | - | - | - |
| O07 | - | - | - | - | - | - | - | - | - | - |

### Memory four-round totals

| Family | Variant | Started | Passed | Requests | Tokens | Task ms sum |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| finance | off | 2 | 2 | - | - | - |
| finance | on | 2 | 2 | - | - | - |
| service_ops | off | 0 | 0 | - | - | - |
| service_ops | on | 0 | 0 | - | - | - |

## State matched tasks

| Task | Off quality | On quality | Off chars | On chars | Off tokens | On tokens | Consume | Cross-PID | Effect |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| semantic-holdout-s1 | yes | no | 1184 | 1184 | 7567 | 8538 | 2.000 | yes | no_effect |
| semantic-holdout-s5 | - | - | - | - | - | - | - | - | - |
| semantic-holdout-s4 | - | - | - | - | - | - | - | - | - |
| semantic-holdout-s8 | - | - | - | - | - | - | - | - | - |

## Interpretation boundary

- Savings ratios are computed only for complete, quality-passing, non-zero matched pairs.
- Candidate hit, actual consumption, and validated replay are separate observations.
- `no_effect` means the mechanism ran without an observed selection change; it is not a benefit claim.
