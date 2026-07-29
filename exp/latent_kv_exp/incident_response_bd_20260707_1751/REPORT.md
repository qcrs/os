# Incident Response A/B/D Comparison

Suite: `trading_incident_response_latentmas_10round_v1`
Generated: 2026-07-07 18:33:22

Current D implementation note: planner -> researcher use explicit structured packets, then analyst_latent -> executor_latent -> summarizer_latent pass Delta KV sequentially. No explicit reducer agent is used.

## Summary

| Mode | Rounds | Avg time(s) | Token in | Token out | Latent steps | KV MB | Field accuracy | Full correct |
|------|-------:|------------:|---------:|----------:|-------------:|------:|---------------:|-------------:|
| B_structured | 10 | 86.3 | 8531 | 1895 | 0 | 0 | 38/60 | 0/10 |
| D_latent_kv | 10 | 99.9 | 7411 | 2092 | 112 | 672 | 35/60 | 0/10 |
- D vs B: -15.7%

## Communication

| Mode | Msgs | Handoffs | Text chars | Text tok est | Non-text transfers | Non-text MB | Context chars orig/comp |
|------|-----:|---------:|-----------:|-------------:|-------------------:|------------:|------------------------:|
| B_structured | 7.0 | 4.0 | 30627 | 7657 | 3.0 | 0.01 | 13391/4517 |
| D_latent_kv | 4.0 | 4.0 | 25657 | 6415 | 6.0 | 672.30 | 6785/2288 |

## Rounds

- B_structured R01 104.3s fields=4/6 msgs=7 text_chars=29791 nontext=3/12KB latent=0 err=
- B_structured R02 94.5s fields=4/6 msgs=7 text_chars=32188 nontext=3/12KB latent=0 err=
- B_structured R03 78.4s fields=2/6 msgs=7 text_chars=31645 nontext=3/12KB latent=0 err=
- B_structured R04 84.8s fields=4/6 msgs=7 text_chars=29212 nontext=3/12KB latent=0 err=
- B_structured R05 86.3s fields=4/6 msgs=7 text_chars=30173 nontext=3/12KB latent=0 err=
- B_structured R06 83.8s fields=2/6 msgs=7 text_chars=30334 nontext=3/12KB latent=0 err=
- B_structured R07 96.2s fields=4/6 msgs=7 text_chars=31439 nontext=3/12KB latent=0 err=
- B_structured R08 75.9s fields=5/6 msgs=7 text_chars=30214 nontext=3/12KB latent=0 err=
- B_structured R09 77.4s fields=5/6 msgs=7 text_chars=30710 nontext=3/12KB latent=0 err=
- B_structured R10 81.6s fields=4/6 msgs=7 text_chars=30565 nontext=3/12KB latent=0 err=
- D_latent_kv R01 98.8s fields=2/6 msgs=4 text_chars=25162 nontext=6/690636KB latent=112 err=
- D_latent_kv R02 97.3s fields=4/6 msgs=4 text_chars=25700 nontext=6/679548KB latent=112 err=
- D_latent_kv R03 97.3s fields=0/6 msgs=4 text_chars=26119 nontext=6/717276KB latent=112 err=
- D_latent_kv R04 104.8s fields=4/6 msgs=4 text_chars=24593 nontext=6/698700KB latent=112 err=
- D_latent_kv R05 103.6s fields=4/6 msgs=4 text_chars=26267 nontext=6/704892KB latent=112 err=
- D_latent_kv R06 102.6s fields=5/6 msgs=4 text_chars=25388 nontext=6/677532KB latent=112 err=
- D_latent_kv R07 85.8s fields=4/6 msgs=4 text_chars=25315 nontext=6/680556KB latent=112 err=
- D_latent_kv R08 102.9s fields=4/6 msgs=4 text_chars=27900 nontext=6/707772KB latent=112 err=
- D_latent_kv R09 102.3s fields=4/6 msgs=4 text_chars=25658 nontext=6/686172KB latent=112 err=
- D_latent_kv R10 103.8s fields=4/6 msgs=4 text_chars=24470 nontext=6/641244KB latent=112 err=