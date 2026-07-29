[JSON]
{
  "plan": "在第8轮局后升级系统基础上，新增评分系统、评价等级和结算报告。评分需计算核心订单、普通订单、奖励订单、准时倍率、路线效率、风险处理、迟到、损坏、事故扣分。路线效率通过实际步数与理论最短路径对比估算，若无路径算法则使用预计算shortest_path_steps。RunSummary需包含score、grade、grade_reason、coin_delta、rep_delta、upgrade_suggestion。新增至少10个测试点，确保评分逻辑正确，评价等级符合文档要求，并生成升级建议。",
  "sub_queries": [
    "如何计算路线效率？",
    "如何实现评分系统？",
    "如何生成评价等级？",
