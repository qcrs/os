# KV Cache Experiment Notes

## Current recommended five-Agent script

Use `run_five_agent_truekv_fair_current.py` for the current five-Agent trueKV comparison. It is restored from `run_five_agent_truekv_fair_20260628_124500.py`, which produced the previously good trueKV run:

- result: `five_agent_truekv_fair_fixed_gpu1_20260628_125722/experiment_report.md`
- C/trueKV: `200.6168s`, `effective_total_tokens=16423`, final artifact score `82.0`, compile/q/WASD all passed.

Example container command:

```bash
docker exec -w /data/mingwei/SynapseX SynapseX-wmw-627 bash -lc '
  export CUDA_VISIBLE_DEVICES=1
  export PYTHONDONTWRITEBYTECODE=1
  export VLLM_GPU_MEMORY_UTILIZATION=0.55
  export VLLM_MAX_MODEL_LEN=8192
  export VLLM_MAX_NUM_SEQS=1
  export VLLM_MAX_NUM_BATCHED_TOKENS=4096
  python3 -u exp/kv_cache_exp/run_five_agent_truekv_fair_current.py \
    --output-dir exp/kv_cache_exp/five_agent_truekv_fair_current_$(date +%Y%m%d_%H%M%S) \
    --clean
'
```

## Strict experiment caveat

`run_five_agent_truekv_fair_strict_20260628_134200.py` was added to make A/text and C/trueKV use the exact same long-prefix + suffix prompt layout. That made the comparison stricter, but the run `five_agent_truekv_fair_strict_gpu0_20260628_134200` showed poor C/trueKV final output: the generated game file was only a placeholder (`...`). Treat it as a failed strict-prompt trial, not as the current best implementation.

Do not use the strict result to claim trueKV quality; it only demonstrates KV reuse/token reduction under that prompt layout.
