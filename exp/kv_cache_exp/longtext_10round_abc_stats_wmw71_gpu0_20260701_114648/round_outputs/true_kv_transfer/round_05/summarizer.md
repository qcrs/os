[JSON]
{
  "round": 5,
  "id": 9005,
  "answer": "@round[5] @feature_scope[multi_order_cargo_selection] @depends_on[1,2,3,4] @new_systems[cargo_slots,order_selection,priority_delivery] @deliverable[incremental_spec]",
  "round_summary": "新增多订单系统，引入cargo_slots货舱容量限制。玩家需在出发前选择携带订单，每个订单占用1或2格货舱空间。订单字段priority、weight、deadline、reward_coins、reward_rep影响选择策略。到达客户点后自动交付匹配订单，同一客户优先交付即将超时的核心订单。新增OrderState记录订单状态，修改PlayerState添加cargo_slots字段。结算时区分未携带订单、携带但未交付、迟到、损坏订单的差异。",
  "carried_state": [
    "PlayerState需扩展添加cargo_slots字段",
    "OrderState需新增selected、delivered、damaged状态",
    "GameConfig需添加cargo_slots_initial参数",
    "新增order_selection界面在出发前选择订单",
    "deliver_orders函数需检查订单是否已选且未交付",
    "新增优先级交付逻辑：同一客户优先交付即将超时的核心订单",
    "结算时区分未携带订单、携带但未交付、迟到、损坏订单的差异",
    "测试点包括货舱容量限制、订单选择策略、交付优先级、未携带订单结算影响等"
  ],
  "test_points": [
    "玩家出发前选择订单时货舱容量不足无法选择部分订单",
    "订单weight为2时占用2格货舱空间",
    "核心订单优先于普通订单交付",
    "同一客户多个订单时优先交付即将超时的核心订单",
   