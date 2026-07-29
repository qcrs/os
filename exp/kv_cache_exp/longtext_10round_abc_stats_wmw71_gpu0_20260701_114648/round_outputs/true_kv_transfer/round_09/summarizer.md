[JSON]
{
  "round": 9,
  "id": 9009,
  "answer": "@round[9] @feature_scope[scoring_grades_run_report] @depends_on[1,2,3,4,5,6,7,8] @new_systems[score,grade,route_efficiency,upgrade_suggestion] @deliverable[incremental_spec]",
  "summary": "[JSON]\n{\n  \"round\": 9,\n  \"id\": 9009,\n  \"answer\": \"@round[9] @feature_scope[scoring_grades_run_report] @depends_on[1,2,3,4,5,6,7,8] @new_systems[score,grade,route_efficiency,upgrade_suggestion] @deliverable[incremental_spec]\\n\\n新增评分系统、评价等级和结算报告。实现评分逻辑，计算不同订单类型、准时倍率、路线效率、风险处理、迟到、损坏、事故扣分。生成评价等级S/A/B/C/F，包含结算报告字段和升级建议。测试点覆盖评分计算、评价等级判定、结算报告字段、升级建议生成。\\n\\n新增字段：\\n- RunSummary 包含 score、grade、grade_reason、coin_delta、rep_delta、upgrade_suggestion\\n- PlayerState 添加 delivered_orders、late_orders、damaged_orders、accident_count 字段\\n- OrderState 记录 deadline、delivery_time、damage_state 字段\\n- LevelState 预计算每个客户点的 shortest_path_steps\\n\\n评分计算公式：\\nscore = (core_orders * 100) + (normal_orders * 50) + (bonus_orders * 80) + (on_time