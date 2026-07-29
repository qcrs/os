[JSON]
{
  "researcher": "researcher_3",
  "findings": [
    "storm 触发时优先扣盾，护盾为0时扣体力，需在 resolve_tile_effect 中实现",
    "fragile 包裹损坏概率需与 storm 交互，需在 deliver_orders 中处理",
    "风道推动进入 storm 仍触发风险，需在 wind_lane 推动后检查目标 tile",
    "风险判定需可测试，需设计 mock_risk_roll 函数",
    "damaged 状态需新增到 PackageState 并在交付时影响奖励",
    "需在 PlayerState 添加 shield 字段",
    "需在 OrderState 添加 fragility 字段",
    "需在 RunSummary 添加 damaged_packages_count 字段"
  ],
  "dependencies": [
    "PlayerState 需扩展 shield 字段",
    "OrderState 需