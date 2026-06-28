[Researcher 3 answer]
### skyforge_courier_game.py
```python
import sys
import time
import random

# Game configuration
GAME_CONFIG = {
    "time_limit": 180,  # seconds
    "stamina": 10,
    "shield": 5,
    "cargo_slots": 2,
    "speed_level": 1,
    "reputation": 0,
    "coins": 0,
    "core_order_required": True
}

# Level data
LEVEL_DATA = {
    "level_id": "day_01",
    "width": 12,
    "height": 12,
    "tiles": [
        ["workshop", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"],
        ["air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air", "air"]
    ],
    "workshop": {"x": 0, "y": 0},
    "customers": [{"id": "c01", "x": 10, "y": 10}],
    "orders": [{"order_id": "o01", "customer_id": "c01", "priority": "core"}],
    "weather_script": []
}

def main():
    # Initialize game state
    player_state = {
        "x": LEVEL_DATA["workshop"]["x"],
        "y": LEVEL_DATA["workshop"]["y"],
        "time_left": GAME_CONFIG["time_limit"],
        "stamina": GAME_CONFIG["stamina"],
        "shield": GAME_CONFIG["shield"],
        "cargo_slots": GAME_CONFIG["cargo_slots"],
        "speed_level": GAME_CONFIG["speed_level"],
        "reputation":