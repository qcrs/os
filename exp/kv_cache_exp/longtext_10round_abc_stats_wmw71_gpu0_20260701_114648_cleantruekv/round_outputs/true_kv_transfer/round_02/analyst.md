{
  "analysis": "在第1轮MVP基础上新增时间与体力系统。时间从180秒开始，每回合减少1秒；体力从10开始，每回合减少1。时间归零且未完成核心订单则失败。结算字段包含delivered_core_count、elapsed_steps、remaining_stamina、success。新增字段默认值为time_left=180, stamina=10。更新顺序：先减少时间与体力，再处理移动效果。体力为0时无法移动。时间归零时立即检查核心订单状态。测试点包括时间减少、体力减少、时间归零失败、体力为0无法移动、核心订单成功判定，以及复用第1轮的移动和订单交付测试。",
  "round_summary": "本轮新增时间与体力系统，实现每回合资源消耗和结算逻辑。时间与体力在每回合开始时更新，先减少再处理移动效果。核心订单成功判定依赖delivered_core_count >= 1且time_left > 0。保留原有地图、移动和订单交付逻辑，新增字段默认值为time_left=180, stamina=10。",
  "carried_state": [
    "map",
   