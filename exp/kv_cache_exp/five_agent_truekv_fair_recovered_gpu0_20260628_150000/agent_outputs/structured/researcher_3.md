```json
{
  "game_state": {
    "map": {
      "width": 12,
      "height": 12,
      "tiles": [
        {
          "type": "grass",
          "effects": []
        },
        {
          "type": "sand",
          "effects": [
            "speed_boost"
          ]
        },
        {
          "type": "water",
          "effects": [
            "stamina_loss"
          ]
        },
        {
          "type": "mountain",
          "effects": [
            "obstacle"
          ]
        },
        {
          "type": "wind_lane",
          "effects": [
            "wind_push"
          ]
        },
        {
          "type": "cloud_wall",
          "effects": [
            "collision_block"
          ]
        },
        {
          "type": "supply",
          "effects": [
            "restock"
          ]
        },
        {
          "type": "storm",
          "effects": [
            "storm_damage"
          ]
        }
      ]
    },
    "player": {
      "position": {
        "x": 0,
        "y": 0
      },
      "inventory": {
        "cargo_slots": 5,
        "cargo": [
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
        ],
        "supplies": 3,
        "upgrades": {
          "speed": 1,
          "stamina": 1,
          "cargo_slots": 5
        }
      },
      "time_left": 100,
      "stamina": 100,
      "weather": "clear",
      "orders": [
        {
          "id": "order_001",
          "type": "deliver",
          "destination": {
            "x": 11,
            "y": 11
          },
          "cargo_type": "standard",
          "quantity": 1
        },
        {
          "id": "order_002",
          "type": "collect",
          "source": {
            "x": 1,
            "y": 1
          },
          "cargo_type": "fragile",
          "quantity": 1
        }
      ]
    },
    "game": {
      "turn": 0,
      "status": "active",
      "summary": {
        "score": 0,
        "level": 1,
        "grade": "none"
      }
    }
  },
  "functions": {
    "render_map": "渲染地图并显示玩家位置和订单状态",
    "update_turn": "处理玩家移动、更新状态、检查订单完成",
    "resolve_tile_effect": "应用地形效果如速度提升、体力消耗等",
    "deliver_orders": "检查订单是否完成并更新评分",
    "calculate_summary": "计算最终得分和等级",
    "main": "游戏主循环，处理输入和游戏状态更新"
  },
  "tests": [
    {
      "name": "test_move_to_water_tile",
      "description": "测试移动到水地时体力减少",
      "input": {
        "player_position": {
          "x": 0,
          "y": 0