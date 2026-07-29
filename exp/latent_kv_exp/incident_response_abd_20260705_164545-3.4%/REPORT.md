# Incident Response A/B/D Comparison

Suite: `trading_incident_response_latentmas_10round_v1`
Generated: 2026-07-05 19:16:44

Current D implementation note: `build_latent_kv_graph()` starts latent transfer at analyst; researcher is still text.

## Summary

| Mode | Rounds | Avg time(s) | Token in | Token out | Latent steps | KV MB | Field accuracy | Full correct |
|------|-------:|------------:|---------:|----------:|-------------:|------:|---------------:|-------------:|
| A_text | 10 | 285.4 | 10039 | 3061 | 0 | 0 | 1/60 | 0/10 |
| B_structured | 10 | 303.6 | 10544 | 3052 | 0 | 0 | 2/60 | 0/10 |
| D_latent_kv | 10 | 275.5 | 9842 | 2804 | 112 | 764 | 40/60 | 0/10 |

## D Speed

- D vs A: 3.4%
- D vs B: 9.2%

## Rounds

- A_text R01 292.3s fields=0/6 latent=0 err=
- A_text R02 288.0s fields=0/6 latent=0 err=
- A_text R03 268.9s fields=0/6 latent=0 err=
- A_text R04 261.7s fields=1/6 latent=0 err=
- A_text R05 296.4s fields=0/6 latent=0 err=
- A_text R06 297.7s fields=0/6 latent=0 err=
- A_text R07 297.6s fields=0/6 latent=0 err=
- A_text R08 274.7s fields=0/6 latent=0 err=
- A_text R09 267.6s fields=0/6 latent=0 err=
- A_text R10 308.7s fields=0/6 latent=0 err=
- B_structured R01 316.2s fields=1/6 latent=0 err=
- B_structured R02 331.4s fields=0/6 latent=0 err=
- B_structured R03 297.3s fields=1/6 latent=0 err=
- B_structured R04 285.6s fields=0/6 latent=0 err=
- B_structured R05 315.2s fields=0/6 latent=0 err=
- B_structured R06 305.4s fields=0/6 latent=0 err=
- B_structured R07 302.1s fields=0/6 latent=0 err=
- B_structured R08 274.6s fields=0/6 latent=0 err=
- B_structured R09 286.3s fields=0/6 latent=0 err=
- B_structured R10 321.6s fields=0/6 latent=0 err=
- D_latent_kv R01 276.0s fields=4/6 latent=112 err=
- D_latent_kv R02 284.1s fields=4/6 latent=112 err=
- D_latent_kv R03 294.0s fields=2/6 latent=112 err=
- D_latent_kv R04 271.1s fields=4/6 latent=112 err=
- D_latent_kv R05 301.8s fields=4/6 latent=112 err=
- D_latent_kv R06 294.5s fields=4/6 latent=112 err=
- D_latent_kv R07 246.6s fields=4/6 latent=112 err=
- D_latent_kv R08 263.2s fields=5/6 latent=112 err=
- D_latent_kv R09 265.5s fields=5/6 latent=112 err=
- D_latent_kv R10 258.9s fields=4/6 latent=112 err=