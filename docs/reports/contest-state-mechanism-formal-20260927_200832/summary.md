# Contest State Mechanism Results (Complete Matched Pairs)

这是 State 机制的质量完整 matched-pair 汇总，只包含 `semantic-holdout-s5`、`semantic-holdout-s4`、`semantic-holdout-s8` 的 6 个变体。原始运行目录未修改。

- Raw root: `/home/qcrs/statebus/os/runs/contest-state-executor-consumer-formal-20260927_200832`
- Report scope planned / started / passed: 6 / 6 / 6
- Environment: `openEuler 24.03 LTS-SP3`, container `statebus-runtime`, source `/workspace/statebus/os`.
- Model/API: `qwen3-32b` on physical GPU 2 at `http://127.0.0.1:53334/v1`, context 8192.
- Embedding: `/statebus/models/Qwen3-Embedding-0.6B` on physical GPU 1 (container `cuda:0`).
- Runtime Python: `/home/qcrs/statebus/conda-envs/statebus_host/bin/python`

## Aggregate comparison

| Metric | State off | State on | Change |
| --- | ---: | ---: | ---: |
| Selected evidence chars | 1164 | 867 | **-25.5%** |
| Provider requests | 17 | 15 | **-11.8%** |
| Provider tokens | 34749 | 30639 | **-11.8%** |
| Task e2e time | 516236.852 ms | 458391.989 ms | **-11.2%** |

## Matched tasks

| Task | Off status | On status | Off chars | On chars | Off tokens | On tokens | Consume | Cross-PID | Release |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| semantic-holdout-s5 | success | success | 304 | 145 | 7042 | 6899 | 3 | yes | yes |
| semantic-holdout-s4 | success | success | 568 | 568 | 15694 | 13894 | 2 | yes | yes |
| semantic-holdout-s8 | success | success | 292 | 154 | 12013 | 9846 | 3 | yes | yes |

## Mechanism observation

All three `State on` variants observed the complete mechanism path:

```text
State publish -> cross-process transfer -> Executor consume -> release/reclaim
```

The aggregate reduction is a matched-pair result; it does not imply every individual task must decrease. In particular, the mixed-input `s4` pair remained quality-complete and preserved evidence size while still exercising the State path.

## Actual runner command

```bash
bash scripts/run_contest_mechanisms.sh \
  --mechanism state \
  --mode live \
  --output /home/qcrs/statebus/os/runs/contest-state-executor-consumer-formal-20260927_200832
```

## Collector command

```bash
bash scripts/run_contest_mechanisms.sh \
  --collect-only \
  --output /home/qcrs/statebus/os/runs/contest-state-executor-consumer-formal-20260927_200832 \
  --collect-output <new-report-root>
```
