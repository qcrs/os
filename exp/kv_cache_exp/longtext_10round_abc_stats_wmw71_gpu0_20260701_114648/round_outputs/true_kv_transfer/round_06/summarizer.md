[JSON]
{
  "round": 6,
  "id": 9006,
  "answer": "@round[6] @feature_scope[supply_items] @depends_on[1,2,3,4,5] @new_systems[supply,battery,shield_cell,parcel_wrap] @deliverable[incremental_spec]",
  "round_summary": "新增补给站（supply）和三个道具：battery（恢复体力）、shield_cell（恢复护盾）、parcel_wrap（保护脆弱包裹）。补给站触发方式为玩家移动至该tile时自动使用，不占货舱，库存上限为2。battery恢复体力但不超过上限，shield_cell恢复护盾但不超过上限，parcel_wrap保护一个脆弱包裹免受一次风暴伤害。道具使用时机为自动触发，无需手动选择。新增PlayerState字段：supplies（道具库存）、max_supplies（上限）。修改resolve_tile_effect处理supply触发，新增道具使用逻辑。更新deliver_orders函数检查包裹损坏状态。",
  "test_points": [
    "玩家移动至supply tile时自动触发补给效果",
    "补给站使用后道具库存减少1",
    "battery恢复体力但不超过上限",
    "shield_cell恢复护盾但不超过上限",
    "parcel_wrap保护一个脆弱包裹免受一次风暴伤害",
    "道具库存上限为2，无法携带超过2个道具",
    "道具不占货舱空间，不影响cargo_slots",
    "风暴中使用parcel_wrap保护包裹"
  ],
  "carried_state": [
    "PlayerState需新增supplies字段记录当前携带的道具，max_supplies字段记录库存上限",
    "resolve_tile_effect函数需新增处理supply tile的逻辑，自动使用道具",
    "battery道具效果：恢复5体力，但不超过stamina上限",
   