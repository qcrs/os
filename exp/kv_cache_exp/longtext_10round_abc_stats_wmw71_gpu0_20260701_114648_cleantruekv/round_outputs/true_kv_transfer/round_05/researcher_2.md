[JSON]
{
  "researcher": "researcher_2",
  "findings": [
    "订单优先级排序需结合priority字段（core > normal > bonus）和deadline（越近越优先）",
    "cargo_slots容量限制需与订单weight字段交互，1格或2格占用",
    "未携带订单在结算时不会获得任何奖励",
    "携带但未交付的订单视为未完成，不计入结算统计",
    "迟到订单交付时金币减半，声望不增加",
    "损坏订单交付时仅获得最低安慰奖励",
    "订单选择界面需在出发前展示所有订单的priority、weight、deadline、reward_coins、reward_rep",
    "同一客户点的多个订单需按deadline排序，优先交付即将超时的核心订单"
  ],
  "dependencies": [
    "地图数据结构需包含所有订单信息",
    "玩家