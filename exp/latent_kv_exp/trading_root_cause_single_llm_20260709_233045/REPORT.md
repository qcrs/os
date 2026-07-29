# Trading Root Cause Single-LLM Baseline

Suite: `trading_root_cause_latent_steps_1round_v1`
Generated: 2026-07-09 23:31:05

This baseline uses one direct OpenAI-compatible chat completion call. It does not use the multi-agent graph, latent KV handles, or executor tools.

| Mode | Time(s) | Token in | Token out | Msgs | Handoffs | Text chars | Non-text MB | Fields | Answer |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| single_llm | 20.081 | 5276 | 464 | 2 | 0 | 12369 | 0.00 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |

Expected:

`{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}`

Run config:

`{"suite_id": "trading_root_cause_latent_steps_1round_v1", "task_file": "/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/task/lantent/trading_root_cause_1round/trading_root_cause_task.json", "output_dir": "/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/trading_root_cause_single_llm_20260709_233045", "mode": "single_llm", "base_url": "http://localhost:8101/v1", "model": "/data/models/Qwen3-8B", "max_tokens": 1024, "temperature": 0.0, "chat_disable_thinking": "1", "started_at": "2026-07-09 23:30:45"}`