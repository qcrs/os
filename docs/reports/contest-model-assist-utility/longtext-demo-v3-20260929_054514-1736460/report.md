# Long-text model-assist utility demonstration

status: `failed`
standard_restored: `unchanged`

The 28 positions are counted as APC 8, Logit 12, and KV 8. Warmup and recovery evidence are separate.

## APC

observed=0 expected=8

## KV

observed=0 expected=8

## Logit

observed=0 expected=12

```json
{
  "schema_version": "statebus.model_assist_utility.summary.v1",
  "record_count": 0,
  "slot_counts": {
    "apc": 0,
    "logit": 0,
    "kv": 0
  },
  "attempt_counts": {
    "apc": 0,
    "logit": 0,
    "kv": 0
  },
  "warmup_counts": {
    "apc": 0,
    "logit": 0,
    "kv": 0
  },
  "expected_slot_counts": {
    "apc": 8,
    "logit": 12,
    "kv": 8
  },
  "not_started_positions": {
    "apc": 8,
    "logit": 12,
    "kv": 8
  },
  "position_outcomes": {
    "apc": {
      "completed": 0,
      "failed": 0,
      "refused": 0,
      "unavailable": 0
    },
    "logit": {
      "completed": 0,
      "failed": 0,
      "refused": 0,
      "unavailable": 0
    },
    "kv": {
      "completed": 0,
      "failed": 0,
      "refused": 0,
      "unavailable": 0
    }
  },
  "demo_completed": false,
  "business_quality_passed": false,
  "by_module": {
    "apc": {
      "completed": 0,
      "failed": 0,
      "refused": 0,
      "unavailable": 0,
      "passed": 0,
      "correct_abstention": 0
    },
    "logit": {
      "completed": 0,
      "failed": 0,
      "refused": 0,
      "unavailable": 0,
      "passed": 0,
      "correct_abstention": 0
    },
    "kv": {
      "completed": 0,
      "failed": 0,
      "refused": 0,
      "unavailable": 0,
      "passed": 0,
      "correct_abstention": 0
    }
  },
  "status": "failed",
  "standard_restored": "unchanged",
  "phase": "all",
  "error_type": "VllmTokenCodecError",
  "error": "tokenizer_api_failed"
}
```
