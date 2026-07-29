# Intermediate Audit Single-LLM Full-Artifact Baseline

Mode: `single_llm_full_artifact`
Generated: 2026-07-10 00:30:47

| Time(s) | Token in | Token out | Parse OK | Verifier OK | Final answer |
|---:|---:|---:|---:|---:|---|
| 82.246 | 2513 | 1945 | True | False | `{"case_id": "C-117", "risk_score": 108, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident", "primary_control_gap": "token_binding_bypass"}` |

Expected:

`{"case_id": "C-117", "risk_score": 108, "tier": "CRITICAL", "action": "isolate_account_and_open_major_incident", "primary_control_gap": "token_binding_bypass"}`

Verifier errors:

- researcher_report too short: 443 chars < 900
- researcher_report missing required evidence E001
- researcher_report missing required evidence E018
- analyst_analysis too short: 246 chars < 900
- analyst_analysis missing required phrase: token_binding_bypass
- analyst_analysis missing required phrase: reader_writer_policy_split
- C-118.risk_score formula mismatch: row=76 computed=72
- C-118.risk_score expected 72 got 76
- C-120.risk_score formula mismatch: row=43 computed=17
- C-120.risk_score expected 17 got 43
- C-120.tier expected LOW got 'MEDIUM'
- C-120.action expected log_and_monitor got 'require_manager_reapproval'

Run config:

`{"suite_id": "intermediate_audit_artifact_1round_v1", "task_file": "/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/task/lantent/intermediate_audit_1round/intermediate_audit_task.json", "output_dir": "/data/mingwei/yzmxdzntxzddkxtxztcdygxjyjz/exp/latent_kv_exp/intermediate_audit_single_llm_20260710_002925", "mode": "single_llm_full_artifact", "base_url": "http://localhost:8101/v1", "model": "/data/models/Qwen3-8B", "max_tokens": 4096, "temperature": 0.0, "chat_disable_thinking": "1", "started_at": "2026-07-10 00:29:25"}`

Verifier check status:

`{"researcher_report": false, "analyst_analysis": false, "executor_matrix": false, "final_answer": true}`