[JSON]
{
  "round": 1,
  "id": 9001,
  "answer": "@round[1] @feature_scope[mvp_movement_delivery] @depends_on[none] @new_systems[map,movement,core_order,delivery] @deliverable[design_spec]\n\n### GameConfig\n- level_width: 12\n- level_height: 12\n- initial_time: 180\n- core_order_priority: 'core'\n\n### LevelState\n- tiles: 12x12 2D array of tile types\n- workshop: {x, y}\n- customers: list of {id, x, y}\n- orders: list of {order_id, customer_id, priority, package_type}\n\n### PlayerState\n- x, y: current position\n- time_left: remaining time\n- stamina: current stamina\n- cargo: list of delivered orders\n- current_order: active order ID or null\n\n### OrderState\n- status: 'created' | 'delivered' | 'late'\n- deadline: time remaining\n- package_type: type of package\n- customer_id: target customer\n\n### Tile Behavior\n- workshop: spawn point and return to end day\n- air: passable\n- cloud_wall: impassable\n- customer: triggers delivery check\n\n### Core Order Flow\ncreated -> deliverable -> delivered (on arrival)\n\n### Test Points\n1. Player cannot move outside map boundaries\n2. Cloud wall blocks movement\n3. Order status changes to delivered on customer tile arrival\n4. Core order triggers delivery logic\n5. Time decreases with each move"
}
[JSON]
{
  "round": 1,
  "id": 9001,
  "answer": "@round[