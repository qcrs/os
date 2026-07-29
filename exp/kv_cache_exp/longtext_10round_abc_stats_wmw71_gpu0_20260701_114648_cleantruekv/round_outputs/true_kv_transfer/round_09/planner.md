[JSON]
{
  "plan": "在第8轮基础上实现评分系统，包含核心订单、普通订单、奖励订单、准时倍率、路线效率、风险处理、迟到、损坏、事故扣分。计算route_efficiency使用实际步数与理论最短路径的比值。RunSummary需包含score、grade、grade_reason、coin_delta、rep_delta、upgrade_suggestion。新增10个测试点，确保结算报告解释评分原因并给出升级建议。",
  "sub_queries": [
    "如何计算理论最短路径？",
    "如何实现风险处理加分？",
    "如何生成upgrade_suggestion？"
  ],
  "answer_tags": "@round[9] @feature_scope[scoring_grades_run_report] @