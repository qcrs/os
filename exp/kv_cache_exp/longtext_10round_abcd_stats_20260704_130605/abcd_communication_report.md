# ABCD Communication Mode Comparison Report

Generated: 2026-07-04 13:09:34
Experiment dir: `/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/kv_cache_exp/longtext_10round_abcd_stats_20260704_130605`

## Summary Table

| Mode | Name | Rounds | LLM Calls | Messages | Text Tokens | NonText Events | NonText Bytes | Avg Round Time | Total Time | Notes |
|------|------|--------|-----------|----------|------------|---------------|---------------|----------------|-----------|-------|
| A | `text` | 10 | 60 | 80 | 334183 | 0 | 0 | 78.6775s | 815.2352s |  |
| B | `structured` | 10 | 60 | 80 | 181106 | 80 | 12888 | 70.2694s | 713.1718s |  |
| C | `true_kv_transfer` | 10 | 60 | 80 | 165104 | 61 | 31770488340 | 85.2168s | 881.598s |  |
| D | `latent_kv` | 10 | 10 | 0 | 1535 | 10 | 146800640 | 20.6261s | 206.3504s | latent_steps=1120 |

## Mode Descriptions

- **A/text**: Full source prefix + textual state transfer each round
- **B/structured**: Compact structured packets + typed state messages
- **C/true_kv_transfer**: Source prefix prefetched as vLLM KV tensors; per-agent suffix counted as text
- **D/latent_kv**: Non-text latent steps; KV state transferred as handle IDs (zero-copy)

## Latent KV (D mode) Stats

- Total latent steps: 1120
- Total KV bytes added: 146,800,640
- Total avoided prefill tokens: 6,069
- Avg latent steps/round: 112.0
