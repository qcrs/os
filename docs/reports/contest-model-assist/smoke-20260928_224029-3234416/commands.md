# Contest model-assist run commands

- run id: smoke-20260928_224029-3234416
- mode: smoke
- phase: both
- family: finance
- candidate root: /home/qcrs/statebus/os
- report root: /home/qcrs/statebus/os/docs/reports/contest-model-assist/smoke-20260928_224029-3234416

## Reproduce this run

```bash
cd /home/qcrs/statebus/os
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \
  --mode smoke --phase both --family finance --report-root /home/qcrs/statebus/os/docs/reports/contest-model-assist --run-id NEW_RUN_ID --yes
```

Use a new run ID; this report directory is immutable evidence.

## Summarize without rerunning

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="/home/qcrs/statebus/os" \
  /home/qcrs/statebus/conda-envs/statebus_host/bin/python scripts/experiments/contest_model_assist/run_minimal_probe.py \
  --summarize /home/qcrs/statebus/os/docs/reports/contest-model-assist/smoke-20260928_224029-3234416/standard-finance
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="/home/qcrs/statebus/os" \
  /home/qcrs/statebus/conda-envs/statebus_host/bin/python scripts/experiments/contest_model_assist/run_minimal_probe.py \
  --summarize /home/qcrs/statebus/os/docs/reports/contest-model-assist/smoke-20260928_224029-3234416/kv-finance
```

## Formal follow-up

Only after this smoke is reviewed and a separate maintenance window is approved:

```bash
cd /home/qcrs/statebus/os
scripts/experiments/contest_model_assist/run_smoke_and_formal.sh \
  --mode formal --phase both --family all --report-root /home/qcrs/statebus/os/docs/reports/contest-model-assist --run-id NEW_FORMAL_RUN_ID --yes
```

The orchestrator switches standard APC-on service to candidate APC-off KV service,
verifies the KV audit, and restores standard before returning. It does not run the
12-round mainline or full benchmark.
