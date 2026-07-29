[JSON]
{
  "plan": "在第7轮基础上新增局后升级系统，实现五类升级：体力上限、护盾上限、cargo_slots、风道掌控、雷暴抗性。新增UpgradeState记录已购买升级，金币消耗对应升级成本。升级前置条件为金币足够且未购买。风道掌控允许玩家选择是否接受wind_lane推动，修改resolve_tile_effect处理风道逻辑。雷暴抗性减少storm体力伤害-1但不低于1。确保旧关卡兼容，未购买升级时行为与第7轮一致。新增测试点验证升级逻辑、金币消耗、升级后属性变化。",
  "sub_queries": [
    "如何设计UpgradeState数据结构并集成到现有PlayerState中？",
    "