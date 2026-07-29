[JSON]
{
  "researcher": "researcher_2",
  "findings": [
    "订单选择需在出发前完成，基于priority、weight、deadline、reward_coins、reward_rep进行权衡",
    "cargo_slots容量限制影响可携带订单数量，weight占用1或2格",
    "到达客户点后自动交付匹配订单，同一客户优先交付即将超时的核心订单",
    "未携带订单不影响结算，但可能错过奖励；携带但未交付订单需在结算时处理",
    "迟到订单交付时金币减半，损坏订单仅获得最低奖励",
    "新增OrderState记录订单状态，PlayerState添加cargo_slots字段",
    "结算时区分未携带、携带未交付、迟到、损坏订单的差异"
  ],
  "dependencies": [
    "PlayerState需扩展添加cargo_slots字段",
    "OrderState需新增selected、delivered