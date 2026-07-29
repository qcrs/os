[JSON]
{
  "analysis": "在第4轮基础上新增多订单系统，引入cargo_slots货舱容量限制。玩家需在出发前选择携带订单，每个订单占用1或2格。订单字段priority、weight、deadline、reward_coins、reward_rep影响选择优先级。到达客户点后自动交付匹配订单，同一客户优先交付即将超时的核心订单。结算时区分未携带订单、携带但未交付、迟到、损坏订单的差异。新增cargo_slots字段，实现订单选择逻辑，调整交付判定和结算计算。",
  "round_summary": "第5轮新增多订单、货舱容量和出发前订单选择系统。玩家需在出发前筛选订单，根据priority、weight、deadline、reward_coins、reward_rep进行取舍。到达客户点后自动交付匹配订单，同一客户优先交付即将超时的核心订单。结算时区分未携带订单、携带但未交付、迟到、损坏订单的处理方式。新增cargo_slots字段，实现订单选择逻辑，调整交付判定和结算计算。",
  "carried_state": [
    "map",
    "player_position",
    "orders",
    "delivery_status",
    "time_left",
    "stamina