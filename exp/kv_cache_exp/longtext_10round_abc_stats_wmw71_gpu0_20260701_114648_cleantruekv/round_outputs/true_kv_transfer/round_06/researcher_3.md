[JSON]
{
  "researcher": "researcher_3",
  "findings": [
    "补给站（supply）触发方式为玩家移动至该tile时自动使用，每次恢复有限制（体力不超过上限，护盾不超过上限）。",
    "battery道具手动使用，恢复5体力，不占货舱格，最多携带2个。",
    "shield_cell道具手动使用，恢复1护盾，不占货舱格，最多携带2个。",
    "parcel_wrap道具自动触发，保护一个脆弱包裹免受一次storm伤害，不占货舱格，最多携带2个。",
    "道具库存限制为最多携带2个，不占货舱格，与订单选择系统分离。"
  ],
  "dependencies": [
    "地图系统（map）",
    "玩家状态（player_state）",
    "订单系统（orders）",
    "时间与体力