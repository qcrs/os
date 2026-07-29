[JSON]
{
  "plan": "在第4轮基础上新增多订单系统，引入cargo_slots货舱容量限制。玩家需在出发前选择携带订单，每个订单占用1或2格货舱空间。订单字段priority、weight、deadline、reward_coins、reward_rep影响选择策略。到达客户点后自动交付匹配订单，同一客户优先交付即将超时的核心订单。新增OrderState记录订单状态，修改PlayerState添加cargo_slots字段。结算时区分未携带订单、携带但未交付、迟到、损坏订单的差异。测试点包括货舱容量限制、订单选择策略、交付优先级、未携带订单结算影响等。",
  "sub_queries": [
    "如何设计订单选择界面？",
    "如何实现