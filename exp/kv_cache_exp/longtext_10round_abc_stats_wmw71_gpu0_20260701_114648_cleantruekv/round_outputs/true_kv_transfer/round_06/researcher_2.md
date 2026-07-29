[JSON]
{
  "researcher": "researcher_2",
  "findings": [
    "supply tile 触发机制设计为玩家移动至该 tile 时自动使用，恢复体力/护盾但不超过上限",
    "battery 道具需手动使用，每次恢复5体力，不占货舱格，最多携带2个",
    "shield_cell 道具需手动使用，每次恢复1护盾，不占货舱格，最多携带2个",
    "parcel_wrap 道具自动触发保护脆弱包裹免受一次 storm 损害，不占货舱格，最多携带2个",
    "道具库存限制为最多携带2个，不占 cargo_slots，需在出发前选择携带",
    "新增 supply tile 类型，与 wind_lane、cloud_wall 等 tile 共存",
    "订单交付逻辑需处理 parcel