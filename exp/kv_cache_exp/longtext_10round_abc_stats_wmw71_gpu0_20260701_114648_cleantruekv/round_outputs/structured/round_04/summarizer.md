[Round 4 Deliverable]
@round[4] @feature_scope[storm_shield_fragility] @depends_on[1,2,3] @new_systems[storm,shield,package_damage,risk_roll] @deliverable[incremental_spec]
```json
{
  "storm": {
    "trigger": "enter_tile",
    "effect": "risk_roll",
    "risk_roll": {
      "dice": 2,
      "threshold": 9,
      "consequences": {
        "shield": -1,
        "stamina": -1,
        "package_damage": 1
      }
    }
  },
  "shield": {
    "initial": 3,
    "max": 5,
    "recharge": 1,
    "recharge_cooldown": 2
  },
  "package_damage": {
    "state": "intact",
    "damage": 0,
    "max_damage": 1
  },
  "risk_roll": {
    "deterministic_seed": 42,
    "mockable": true
  },
  "test_cases": [
    "storm_without_shield",
    "shield_depletion_sequence",
    "package_damage_only",
    "storm_with_damage",
    "multiple_storm_encounters",
    "shield_recharge_test",
    "deterministic_seed_injection",
    "mock_risk_roll_test"
  ]
}
```
```markdown
# Storm, Shield, and Package Damage Implementation Notes

## System Integration
- Storm triggers on tile entry, not movement
- Wind lane pushes into storm tiles but still triggers risk roll
- Shield is separate from stamina, with explicit depletion tracking
- Package damage state is tracked independently of delivery status

## Risk Roll Mechanics
- Uses deterministic random seed (42) for testability
- Mock