# Long-text model-assist utility demonstration

status: `blocked_preflight`
standard_restored: `not_changed`

The 28 positions are counted as APC 8, Logit 12, and KV 8. Warmup and recovery evidence are separate.

```json
{
  "schema_version": "statebus.model_assist_utility.summary.v1",
  "record_count": 0,
  "slot_counts": {
    "apc": 0,
    "logit": 0,
    "kv": 0
  },
  "expected_slot_counts": {
    "apc": 8,
    "logit": 12,
    "kv": 8
  },
  "demo_completed": false,
  "by_module": {},
  "status": "blocked_preflight",
  "standard_restored": "not_changed",
  "blocked_reasons": [
    "standard_gpu_has_non_workflow_compute_owner"
  ],
  "phase": "all"
}
```
