{
  "researcher": "researcher_3",
  "findings": [
    "新增 time_left 从 180 秒开始，每回合减少 1 秒。当 time_left <= 0 时判定配送日失败。",
    "新增 stamina 从 10 开始，每回合减少 1。体力为 0 时无法移动。",
    "新增 RunSummary 包含 delivered_core_count、elapsed_steps、remaining_stamina、success 四个字段。",
    "时间与体力在每回合开始时更新，先减少再处理移动效果。",
    "核心订单成功判定依赖 delivered_core_count >= 1，且 time_left > 0。",
    "保留原有地图、移动和订单交付逻辑，新增字段默认值为 time_left=180, stamina=10。"
  ],
  "dependencies": [
    "第1轮的 map、movement