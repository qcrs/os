[JSON]
{
  "researcher": "researcher_2",
  "findings": [
    "评分系统需综合核心订单、普通订单、奖励订单、准时倍率、路线效率、风险处理、迟到、损坏、事故扣分",
    "评价等级S/A/B/C/F需根据得分和交付表现确定",
    "route_efficiency通过实际步数与预计算的shortest_path_steps对比估算",
    "RunSummary需包含score、grade、grade_reason、coin_delta、rep_delta、upgrade_suggestion",
    "升级建议需基于玩家表现和当前装备状态生成"
  ],
  "dependencies": [
    "PlayerState需包含delivered_orders、late_orders、damaged_orders、accident_count字段",
    "OrderState需记录deadline、delivery_time、damage_state字段",
    "LevelState需预计算每个客户点的shortest_path_steps",
    "resolve_tile