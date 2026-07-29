[JSON]
{
  "analysis": "在第7轮天气预报和动态事件系统基础上，新增局后升级系统。升级类型包括体力上限、护盾上限、cargo_slots、风道掌控、雷暴抗性。新增UpgradeState记录已购买升级，金币消耗对应升级成本。风道掌控允许玩家选择是否接受wind_lane推动，雷暴抗性减少storm体力伤害-1但不低于1。确保旧关卡兼容，未购买升级时行为与第7轮一致。新增测试点验证升级逻辑、金币消耗、升级后属性变化。",
  "round_summary": "[JSON]\n{\n  \"round\": 8,\n  \"id\": 9008,\n  \"answer\": \"@round[8] @feature_scope[post_run_upgrades_progression] @depends_on[1,2,3,4,5,6,7] @new_systems[upgrade_state,coin_costs,wind_control,storm_resistance] @deliverable[incremental_spec]\n\n新增局后升级系统，实现五类升级：体力上限、护盾上限、cargo_slots、风道掌控、雷暴抗性。新增UpgradeState记录已购买升级，