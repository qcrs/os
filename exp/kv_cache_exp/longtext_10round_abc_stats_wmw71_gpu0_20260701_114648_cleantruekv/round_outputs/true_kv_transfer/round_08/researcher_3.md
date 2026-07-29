[JSON]
{
  "researcher": "researcher_3",
  "findings": [
    "新增UpgradeState数据结构，包含已购买升级列表，集成到PlayerState中",
    "金币消耗根据升级类型设定，如体力上限+2需50金币，护盾上限+1需30金币，cargo_slots+1需40金币，风道掌控需50金币，雷暴抗性需60金币",
    "升级前置条件为完成配送日且金币足够，未购买升级时行为与第7轮一致",
    "风道掌控允许玩家选择是否接受wind_lane推动，修改PlayerState的wind_control属性",
    "雷暴抗性减少storm体力伤害但不低于1，修改GameConfig的storm_damage属性",
    "升级不影响旧关卡，未购买升级时使用默认值",
    "新增9个测试点验证升级逻辑、金币