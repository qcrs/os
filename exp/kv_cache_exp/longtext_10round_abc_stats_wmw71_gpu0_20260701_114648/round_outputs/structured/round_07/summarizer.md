[Round 7 Deliverable]
@round[7] @feature_scope[weather_forecast_dynamic_events] @depends_on[1,2,3,4,5,6] @new_systems[weather_script,forecast,temporary_blocked,storm_intensity] @deliverable[incremental_spec]

### Weather Script Design
```python
weather_script = {
    "forecast": {
        "current": "clear",
        "next": ["breeze", "turbulence", "storm"]
    },
    "events": {
        "breeze": {"effect": "wind_lane_push +1", "duration": 1},
        "turbulence": {"effect": "air_to_blocked", "duration": 2},
        "storm": {"effect": "storm_intensity +1", "duration": 3}
    },
    "seed": 42
}
```

### Turn Processing Order
1. Forecast display
2. Weather event application
3. Movement resolution
4. Tile effect processing
5. Order delivery checks

### UI Forecast Field
```text
[Weather Forecast] Current: clear | Next: breeze, turbulence, storm
```

### Dynamic Blocked Tile Rules
- Temporary blocked tiles from turbulence last 2 turns
- Generated 1-2 tiles per turbulence event
- Disappear after duration completes

### Test Points
1. Weather forecast visibility
2. Breeze push effect verification
3. Turbulence blocked tile generation
4. Storm intensity progression
5. Forecast seed reproducibility
6. Event duration tracking
7. Movement during weather events
8. UI display accuracy
9. Deterministic replay capability
```


[Round 7 Deliverable]
@round[7] @feature_scope[weather_forecast_dynamic_events] @depends_on[1,2,3,4,5,6] @