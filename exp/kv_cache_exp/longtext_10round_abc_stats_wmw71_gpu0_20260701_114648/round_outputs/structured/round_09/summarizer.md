[Round 9 Deliverable]
@round[9] @feature_scope[scoring_grades_run_report] @depends_on[1,2,3,4,5,6,7,8] @new_systems[score,grade,route_efficiency,upgrade_suggestion] @deliverable[incremental_spec]

### 核心评分系统实现
1. **得分计算**：
   - 准时倍率 = 1.2^（准时时间/总时间）
   - 路线效率 = (实际步数 / 理论最短步数) * 100%
   - 风险处理 = 100% - (事故次数 * 20%)
   - 损坏订单 = 每个损坏订单扣50分
   - 迟到订单 = 每个迟到订单扣100分
   - 事故扣分 = 每次事故扣30分

2. **等级评定**：
   - S: ≥ 950分
   - A: 850-949分
   - B: 750-849分
   - C: 600-749分
   - F: < 600分

3. **结算报告**：
   - 包含score、grade、grade_reason、coin_delta、rep_delta、upgrade_suggestion
   - 详细说明得分构成和升级建议

4. **测试点**：
   1. 多订单准时交付
   2. 路线效率计算
   3. 风险处理得分
   4. 损坏订单扣分
   5. 迟到订单扣分
   