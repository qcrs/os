[JSON]
{
  "plan": "在第5轮基础上新增补给站（supply）和三个道具：battery（恢复体力）、shield_cell（恢复护盾）、parcel_wrap（保护脆弱包裹）。补给站触发方式为玩家移动至该tile时自动使用，道具库存上限为2，不占货舱。battery恢复体力但不超过上限；shield_cell恢复护盾但不超过上限；parcel_wrap保护一个脆弱包裹免受一次风暴伤害。道具使用时机为自动触发，无需手动选择。新增PlayerState字段：supplies（道具库存）、max_supplies（上限）。修改resolve_tile_effect处理supply触发，新增道具使用逻辑。更新deliver_orders检查包裹损坏状态。测试点包括补给站触发、道具库存限制、道具