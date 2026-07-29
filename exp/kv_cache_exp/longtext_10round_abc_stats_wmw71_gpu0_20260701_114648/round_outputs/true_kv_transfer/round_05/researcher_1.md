[JSON]
{
  "researcher": "researcher_1",
  "findings": [
    "PlayerState需新增cargo_slots字段，初始值为2，用于限制可携带订单数量",
    "OrderState需新增weight字段，表示占用货舱格数（1或2）",
    "订单选择界面需在出发前展示所有订单，按priority、weight、deadline排序",
    "交付逻辑需检查当前携带订单是否匹配客户点，并按priority和deadline排序交付",
    "未携带订单在结算时不会获得奖励，但不影响配送日成功判定",
    "携带但未交付订单在结算时按状态计算奖励（迟到或损坏）",
    "核心订单必须至少完成一个才能成功配送日",
    "新增OrderState字段：priority（core/normal/bonus）、weight（1/2）、deadline（回合数）、reward_coins、reward_rep、frag