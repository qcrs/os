# 合成涉密数据访问审计长中间推理任务集 B/D Comparison

Suite: `classified_data_audit_latent_kv_10round_v1`
Generated: 2026-07-09 15:31:35

Task note: synthetic classified-data audit; no real sensitive data is included.
Current latent_kv topology: planner/researcher explicit structured packets, then analyst_latent -> executor_latent -> summarizer_latent through server-side KV handles.

## Summary

| Mode | Rounds | Avg time(s) | Token in | Token out | Latent steps | KV MB | Field accuracy | Full correct |
|------|-------:|------------:|---------:|----------:|-------------:|------:|---------------:|-------------:|
| B_structured | 10 | 109.1 | 11837 | 3072 | 0 | 0 | 40/40 | 10/10 |
| D_latent_kv | 10 | 93.5 | 12394 | 2560 | 80 | 2409 | 40/40 | 10/10 |

## Speed

- latent_kv vs structured: 14.3%

## Communication

| Mode | Msgs | Handoffs | Text chars | Text tok est | Non-text transfers | Non-text MB | Context chars orig/comp |
|------|-----:|---------:|-----------:|-------------:|-------------------:|------------:|------------------------:|
| B_structured | 7.0 | 4.0 | 66408 | 16602 | 3.0 | 0.01 | 90/253 |
| D_latent_kv | 4.0 | 4.0 | 64589 | 16148 | 6.0 | 2408.61 | 42/162 |

## Rounds

- B_structured R01 116.5s fields=4/4 answer={"case_id": "C-002", "risk_score": 67, "tier": "HIGH", "action": "freeze_export_and_start_review"} expected={"case_id": "C-002", "risk_score": 67, "tier": "HIGH", "action": "freeze_export_and_start_review"} msgs=7 text_chars=70014 latent=0 err=
- B_structured R02 106.9s fields=4/4 answer={"case_id": "C-014", "risk_score": 81, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-014", "risk_score": 81, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=7 text_chars=62525 latent=0 err=
- B_structured R03 119.7s fields=4/4 answer={"case_id": "C-032", "risk_score": 66, "tier": "HIGH", "action": "freeze_export_and_start_review"} expected={"case_id": "C-032", "risk_score": 66, "tier": "HIGH", "action": "freeze_export_and_start_review"} msgs=7 text_chars=71196 latent=0 err=
- B_structured R04 107.0s fields=4/4 answer={"case_id": "C-044", "risk_score": 83, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-044", "risk_score": 83, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=7 text_chars=72378 latent=0 err=
- B_structured R05 106.0s fields=4/4 answer={"case_id": "C-053", "risk_score": 66, "tier": "HIGH", "action": "freeze_export_and_start_review"} expected={"case_id": "C-053", "risk_score": 66, "tier": "HIGH", "action": "freeze_export_and_start_review"} msgs=7 text_chars=64780 latent=0 err=
- B_structured R06 106.7s fields=4/4 answer={"case_id": "C-061", "risk_score": 80, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-061", "risk_score": 80, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=7 text_chars=65580 latent=0 err=
- B_structured R07 107.3s fields=4/4 answer={"case_id": "C-073", "risk_score": 76, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-073", "risk_score": 76, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=7 text_chars=75682 latent=0 err=
- B_structured R08 107.6s fields=4/4 answer={"case_id": "C-083", "risk_score": 67, "tier": "HIGH", "action": "freeze_export_and_start_review"} expected={"case_id": "C-083", "risk_score": 67, "tier": "HIGH", "action": "freeze_export_and_start_review"} msgs=7 text_chars=52337 latent=0 err=
- B_structured R09 106.7s fields=4/4 answer={"case_id": "C-091", "risk_score": 85, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-091", "risk_score": 85, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=7 text_chars=51050 latent=0 err=
- B_structured R10 106.1s fields=4/4 answer={"case_id": "C-101", "risk_score": 81, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-101", "risk_score": 81, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=7 text_chars=78538 latent=0 err=
- D_latent_kv R01 91.9s fields=4/4 answer={"case_id": "C-002", "risk_score": 67, "tier": "HIGH", "action": "freeze_export_and_start_review"} expected={"case_id": "C-002", "risk_score": 67, "tier": "HIGH", "action": "freeze_export_and_start_review"} msgs=4 text_chars=63852 latent=80 err=
- D_latent_kv R02 90.6s fields=4/4 answer={"case_id": "C-014", "risk_score": 81, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-014", "risk_score": 81, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=4 text_chars=60331 latent=80 err=
- D_latent_kv R03 90.5s fields=4/4 answer={"case_id": "C-032", "risk_score": 66, "tier": "HIGH", "action": "freeze_export_and_start_review"} expected={"case_id": "C-032", "risk_score": 66, "tier": "HIGH", "action": "freeze_export_and_start_review"} msgs=4 text_chars=65059 latent=80 err=
- D_latent_kv R04 97.5s fields=4/4 answer={"case_id": "C-044", "risk_score": 83, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-044", "risk_score": 83, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=4 text_chars=65702 latent=80 err=
- D_latent_kv R05 92.7s fields=4/4 answer={"case_id": "C-053", "risk_score": 66, "tier": "HIGH", "action": "freeze_export_and_start_review"} expected={"case_id": "C-053", "risk_score": 66, "tier": "HIGH", "action": "freeze_export_and_start_review"} msgs=4 text_chars=66946 latent=80 err=
- D_latent_kv R06 90.6s fields=4/4 answer={"case_id": "C-061", "risk_score": 80, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-061", "risk_score": 80, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=4 text_chars=67243 latent=80 err=
- D_latent_kv R07 92.4s fields=4/4 answer={"case_id": "C-073", "risk_score": 76, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-073", "risk_score": 76, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=4 text_chars=50588 latent=80 err=
- D_latent_kv R08 92.7s fields=4/4 answer={"case_id": "C-083", "risk_score": 67, "tier": "HIGH", "action": "freeze_export_and_start_review"} expected={"case_id": "C-083", "risk_score": 67, "tier": "HIGH", "action": "freeze_export_and_start_review"} msgs=4 text_chars=69268 latent=80 err=
- D_latent_kv R09 96.2s fields=4/4 answer={"case_id": "C-091", "risk_score": 85, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-091", "risk_score": 85, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=4 text_chars=65157 latent=80 err=
- D_latent_kv R10 99.9s fields=4/4 answer={"case_id": "C-101", "risk_score": 81, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} expected={"case_id": "C-101", "risk_score": 81, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident"} msgs=4 text_chars=71746 latent=80 err=