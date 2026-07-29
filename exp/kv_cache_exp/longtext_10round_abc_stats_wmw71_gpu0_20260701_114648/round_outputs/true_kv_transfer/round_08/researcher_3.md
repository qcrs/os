[JSON]
{
  "researcher": "researcher_3",
  "findings": [
    "新增UpgradeState数据结构，记录已购买的升级，与PlayerState集成",
    "金币消耗对应升级成本，升级前置条件为金币足够且未购买",
    "风道掌控允许玩家选择是否接受wind_lane推动，修改resolve_tile_effect处理风道逻辑",
    "雷暴抗性减少storm体力伤害-1但不低于1，修改风暴伤害计算逻辑",
    "确保旧关卡兼容，未购买升级时行为与第7轮一致"
  ],
  "dependencies": [
    "PlayerState需扩展添加upgrade_state字段记录已购买升级",
    "GameConfig需添加upgrade_cost参数定义各升级成本",
    "resolve_tile_effect函数需处理风道掌控选择逻辑",
    "风暴伤害计算需考虑雷暴抗性属性",
    "RunSummary需新增upgrade