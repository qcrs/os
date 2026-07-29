[JSON]
{
  "round": 1,
  "id": 9001,
  "answer": "@round[1] @feature_scope[mvp_movement_delivery] @depends_on[none] @new_systems[map,movement,core_order,delivery] @deliverable[design_spec]\n\n### GameConfig\n- level_width: 12\n- level_height: 12\n- initial_time: 180\n- core_order_priority: 'core'\n\n### LevelState\n- tiles: 12x12 2D array of tile types\n- workshop: {x, y}\n- customers: list of {id, x, y}\n- orders: list of {order_id, customer_id, priority, package_type}\n\n### PlayerState\n- x, y: current position\n- time_left: remaining time\n- stamina: current stamina\n- cargo: list of delivered orders\n- current_order: None or order_id\n\n### OrderState\n- status: 'created' | 'delivered' | 'late'\n- deadline: time when order becomes late\n- package_type: type of package\n\n### Tile Behavior\n- workshop: spawn point and return to end day\n- air: passable\n- cloud_wall: impassable\n- customer: triggers delivery check\n\n### Core Order Flow\ncreated -> deliverable -> delivered (on arrival)\n\n### Test Cases\n1. Player cannot move through cloud_wall\n2. Order status changes to delivered on customer tile arrival\n3. Time decreases with each move\n4. Stamina decreases with each move\n5. Core order is marked delivered after correct delivery"
}
[JSON] 为了确保第1轮MVP的实现符合设计目标，以下是详细的设计规格：

### GameConfig
- level_width