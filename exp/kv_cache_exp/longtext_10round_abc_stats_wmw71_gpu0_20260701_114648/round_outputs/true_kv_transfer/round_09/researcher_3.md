[JSON]
{
  "researcher": "researcher_3",
  "findings": [
    "评分系统需计算核心订单、普通订单、奖励订单、准时倍率、路线效率、风险处理、迟到、损坏、事故扣分",
    "评价等级S/A/B/C/F需基于得分和交付表现",
    "RunSummary需包含score、grade、grade_reason、coin_delta、rep_delta、upgrade_suggestion",
    "route_efficiency通过实际步数与理论最短路径对比估算，若无路径算法则使用预计算shortest_path_steps",
    "测试点需覆盖评分逻辑、评价等级、结算报告字段、升级建议生成"
  ],
  "dependencies": [
    "PlayerState需包含delivered_orders、late_orders、damaged_orders、accident_count字段",
    "OrderState需记录deadline、delivery_time、damage_state字段",
    "LevelState需