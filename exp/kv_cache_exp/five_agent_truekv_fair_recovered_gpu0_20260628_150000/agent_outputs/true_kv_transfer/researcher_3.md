[Final answer]
### skyforge_courier_game.py
```python
import sys
import time
import random

# 游戏配置
GAME_CONFIG = {
    "time_limit": 180,  # 秒
    "stamina_max": 10,
    "shield_max": 3,
    "cargo_slots": 2,
    "speed_level": 1,
    "reputation": 0,
    "coins": 0,
    "weather_script": [
        {"turn": 20, "weather": "storm"},
        {"turn": 40, "weather": "calm"},
        {"turn": 60, "weather": "gust"}
    ]
}

# 地图数据
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
    "orders": [{"order_id": "o01", "customer_id": "c01", "priority": "core", "deadline": 120, "reward_coins": 50, "reward_rep": 10, "fragility": 1, "weight": 1}],
    "weather_script": [{"turn": 20, "weather": "storm"}