# Trading Root Cause structured vs kv_latent Step Ablation

Suite: `trading_root_cause_latent_steps_1round_v1`
Generated: 2026-07-09 22:28:25

Executor code/tools are disabled by prompt and by agent no-code path.

| Mode | Steps A/E/P/S | Time(s) | Token in | Token out | Latent steps | KV MB | Msgs | Text chars | Non-text MB | Fields | Answer |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| structured | - | 201.109 | 36000 | 3072 | 0 | 0.00 | 7 | 290811 | 0.01 | 0/3 | `{"root_cause": "True", "severity": "TRUE", "first_bad_component": "True"}` |
| kv_latent_0 | 0/0/0/0 | 203.028 | 30098 | 2560 | 0 | 2544.75 | 4 | 268508 | 2544.76 | 0/3 | `{"root_cause": "clearing_batch_backpressure", "severity": "P2", "first_bad_component": "AuditLogger"}` |
| kv_latent_16 | 8/8/0/0 | 203.959 | 30114 | 2560 | 16 | 2550.38 | 4 | 270450 | 2550.39 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |
| kv_latent_32 | 16/16/0/0 | 186.587 | 30130 | 2560 | 32 | 2556.00 | 4 | 270461 | 2556.01 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |
| kv_latent_56 | 32/16/8/0 | 188.647 | 30154 | 2560 | 56 | 2563.88 | 4 | 270439 | 2563.89 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |
| kv_latent_80 | 48/24/8/0 | 230.645 | 30178 | 2560 | 80 | 2572.88 | 4 | 270465 | 2572.89 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |
| kv_latent_120 | 64/32/16/8 | 191.852 | 30218 | 2560 | 120 | 3457.41 | 4 | 270443 | 3457.42 | 3/3 | `{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}` |

Expected:

`{"root_cause": "ordergateway_auth_cache_key_normalization", "severity": "P1", "first_bad_component": "OrderGateway"}`