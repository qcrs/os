```json
{
  "cargo": {
    "slots": 5,
    "items": [
      {
        "type": "standard",
        "weight": 1,
        "value": 10
      },
      {
        "type": "fragile",
        "weight": 2,
        "value": 20,
        "damage_chance": 0.2
      },
      {
        "type": "shield",
        "weight": 1,
        "value": 15,
        "protection": 1
      }
    ]
  },
  "supplies": {
    "stations": [
      {
        "type": "rest",
        "effect": {
          "stamina": 5
        }
      },
      {
        "type": "upgrade",
        "effect": {
          "cargo_slots": 1
        }
      }
    ]
  },
  "weather": {
    "scripts": [
      {
        "name": "calm",
        "effects": {
          "wind_speed": 0,
          "storm_chance": 0.05
        }
      },
      {
        "name": "gale",
        "effects": {
          "wind_speed": 2,
          "storm_chance": 0.15
        }
      },
      {
        "name": "storm",
        "effects": {
          "wind_speed": 3,
          "storm_chance": 0.3
        }
      }
    ]
  },
  "upgrades": {
    "available": [
      {
        "name": "cargo_expansion",
        "cost": 10,
        "effect": {
          "cargo_slots": 1
        }
      },
      {
        "name": "stamina_boost",
        "cost": 15,
        "effect": {
          "stamina": 5
        }
      }
    ]
  },
  "scoring": {
    "base": 100,
    "multipliers": {
      "orders_delivered": 1.5,
      "cargo_weight": 0.5,
      "stamina_remaining": 0.2
    },
    "grades": {
      "A": 90,
      "B": 75,
      "C": 60,
      "D": 45,
      "F": 0
    }
  },
  "balance": {
    "time_limit": 30,
    "stamina_start": 10,
    "wind_speed_range": [0, 3],
    "storm_damage": 2,
    "fragile_damage": 1,
    "upgrade_cost_range": [5, 20]
  },
  "test_matrix": {
    "test_cases": [
      {
        "name": "basic_delivery",
        "description": "Test basic movement and order delivery",
        "parameters": {
          "map": "simple",
          "weather": "calm",
          "orders": 1,
          "cargo_slots": 5
        },
        "expected": {
          "success": true,
          "score": 150
        }
      },
      {
        "name": "storm_damage",
        "description": "Test fragile item damage during storm",
        "parameters": {
          "map": "stormy",
          "weather": "storm",
          "orders": 1,
          "cargo_slots": 5
        },
        "expected": {
          "success": true,
          "score": 120
        }
      },
      {
        "name": "upgrade_test",
        "description": "Test cargo