[JSON]
{
  "round": 8,
  "id": 9008,
  "answer": "@round[8] @feature_scope[post_run_upgrades_progression] @depends_on[1,2,3,4,5,6,7] @new_systems[upgrade_state,coin_costs,wind_control,storm_resistance] @deliverable[incremental_spec]\n\n新增局后升级系统，实现五类升级：体力上限、护盾上限、cargo_slots、风道掌控、雷暴抗性。新增UpgradeState记录已购买升级，金币消耗对应升级成本。升级前置条件为金币足够且未购买。风道掌控允许玩家选择是否接受wind_lane推动，修改resolve_tile_effect处理风道逻辑。雷暴抗性减少storm体力伤害-1但不低于1。确保旧关卡兼容，未购买升级时行为与第7轮一致。新增测试点验证升级逻辑、金币消耗、升级后属性变化。",
  "test_points": [
    "升级界面显示可购买的升级选项",
    "金币不足时无法购买升级",
    "已购买升级后属性值更新",
    "风道掌控允许玩家选择是否接受推动",
    "雷暴抗性减少storm体力伤害-1但不低于1",
    "升级后GameConfig或PlayerState初始值修改",
    "旧关卡未购买升级时行为与第7轮一致",
    "升级后属性值不超过合理上限",
    "升级后系统不影响现有订单交付逻辑"
  ]
}

[Final Answer]
[JSON]
{
  "round": 8,
  "id": 9008,
  "answer": "@round[8] @feature_scope[post_run_upgrades_progression] @depends_on[1,2,3,4,5,