[JSON]
{
  "researcher": "researcher_2",
  "findings": [
    "storm 触发时需优先扣除 shield，若 shield 为 0 再扣除 stamina",
    "脆弱包裹在 storm 中有 30% 概率损坏，损坏后奖励减半",
    "风道推动进入 storm 仍触发 storm 风险",
    "风险判定需支持 deterministic random seed 注入以方便测试",
    "damaged 状态需独立于订单状态，不影响交付判定但影响奖励",
    "storm 风险判定应与 wind_lane 推动逻辑解耦，确保风道不会规避风险",
    "订单 fragility 字段需与 package_damage 逻辑绑定",
    "风险判定函数需接受 mock 参数以支持单元测试"
  ],
  "dependencies": [
    "PlayerState 需扩展 shield 字段",
   