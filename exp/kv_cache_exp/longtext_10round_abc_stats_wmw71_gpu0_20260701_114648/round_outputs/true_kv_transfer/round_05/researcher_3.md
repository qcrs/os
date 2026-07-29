[JSON]
{
  "researcher": "researcher_3",
  "findings": [
    "订单选择系统需要在游戏开始时提供界面，让玩家从所有订单中选择携带的订单",
    "cargo_slots字段需要添加到PlayerState，初始值为2，每个订单根据weight占用1或2格",
    "订单字段priority、weight、deadline、reward_coins、reward_rep将影响选择策略，例如优先选择高reward_core订单，避免携带高weight订单",
    "到达客户点后，自动交付当前携带且匹配的订单，同一客户点优先交付即将超时的核心订单",
    "未携带的订单在结算时不会获得任何奖励，但不会影响成功判定",
    "携带但未交付的订单在结算时根据状态（准时/迟到/损坏）获得相应奖励",
    "损坏订单只能获得最低安慰奖励，而迟到订单获得减