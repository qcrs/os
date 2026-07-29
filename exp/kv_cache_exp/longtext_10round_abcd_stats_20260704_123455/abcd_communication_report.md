# ABCD Communication Mode Comparison Report

Generated: 2026-07-04 12:38:06
Experiment dir: `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/kv_cache_exp/longtext_10round_abcd_stats_20260704_123455`

## Summary Table

| Mode | Name | Rounds | LLM Calls | Messages | Text Tokens | NonText Events | NonText Bytes | Avg Round Time | Total Time | Notes |
|------|------|--------|-----------|----------|------------|---------------|---------------|----------------|-----------|-------|
| A | `text` | 10 | 60 | 80 | 334183 | 0 | 0 | 78.6775s | 815.2352s |  |
| B | `structured` | 10 | 60 | 80 | 181106 | 80 | 12888 | 70.2694s | 713.1718s |  |
| C | `true_kv_transfer` | 10 | 60 | 80 | 165104 | 61 | 31770488340 | 85.2168s | 881.598s |  |
| D | `latent_kv` | 10 | 0 | 0 | 0 | 0 | 0 | 18.7742s | 187.8147s | latent_steps=0 |

## Mode Descriptions

- **A/text**: Full source prefix + textual state transfer each round
- **B/structured**: Compact structured packets + typed state messages
- **C/true_kv_transfer**: Source prefix prefetched as vLLM KV tensors; per-agent suffix counted as text
- **D/latent_kv**: Non-text latent steps; KV state transferred as handle IDs (zero-copy)

## Latent KV (D mode) Stats

- Total latent steps: 0
- Total KV bytes added: 0
- Total avoided prefill tokens: 0
- Avg latent steps/round: 0.0
