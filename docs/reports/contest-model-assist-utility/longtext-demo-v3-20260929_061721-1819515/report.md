# Long-text model-assist utility demonstration

status: `demo_completed`
standard_restored: `unchanged`

The 28 positions are counted as APC 8, Logit 12, and KV 8. Warmup and recovery evidence are separate.

## APC

observed=8 expected=8

## KV

observed=8 expected=8

## Logit

observed=12 expected=12

```json
{
  "schema_version": "statebus.model_assist_utility.summary.v1",
  "record_count": 93,
  "slot_counts": {
    "apc": 8,
    "logit": 12,
    "kv": 8
  },
  "attempt_counts": {
    "apc": 10,
    "logit": 37,
    "kv": 8
  },
  "warmup_counts": {
    "apc": 10,
    "logit": 2,
    "kv": 10
  },
  "expected_slot_counts": {
    "apc": 8,
    "logit": 12,
    "kv": 8
  },
  "not_started_positions": {
    "apc": 0,
    "logit": 0,
    "kv": 0
  },
  "position_outcomes": {
    "apc": {
      "completed": 8,
      "failed": 0,
      "refused": 0,
      "unavailable": 0
    },
    "logit": {
      "completed": 12,
      "failed": 0,
      "refused": 0,
      "unavailable": 0
    },
    "kv": {
      "completed": 8,
      "failed": 0,
      "refused": 0,
      "unavailable": 0
    }
  },
  "demo_completed": true,
  "business_quality_passed": false,
  "by_module": {
    "apc": {
      "completed": 8,
      "failed": 0,
      "refused": 0,
      "unavailable": 0,
      "passed": 8,
      "correct_abstention": 0
    },
    "logit": {
      "completed": 12,
      "failed": 0,
      "refused": 0,
      "unavailable": 0,
      "passed": 9,
      "correct_abstention": 3
    },
    "kv": {
      "completed": 8,
      "failed": 0,
      "refused": 0,
      "unavailable": 0,
      "passed": 0,
      "correct_abstention": 0
    }
  },
  "status": "demo_completed",
  "standard_restored": "unchanged",
  "phase": "logit",
  "live_summary": {
    "standard": [],
    "kv": [],
    "logit": [
      {
        "slot_id": "MU-LOGIT-UNRESOLVED-ORION-EXCEPTIONS:logit_selective",
        "quality": true,
        "status": "completed",
        "exact_available": true,
        "runtime_completed": false,
        "gate_ready": true,
        "expanded": true,
        "case_id": "MU-LOGIT-UNRESOLVED-ORION-EXCEPTIONS",
        "condition": "logit_selective"
      }
    ],
    "warmup": [],
    "rechecks": [],
    "status": "live_completed",
    "targeted_recheck": {
      "slot_id": "MU-LOGIT-UNRESOLVED-ORION-EXCEPTIONS:logit_selective",
      "gate_ready": true,
      "status": "completed"
    }
  }
}
```
