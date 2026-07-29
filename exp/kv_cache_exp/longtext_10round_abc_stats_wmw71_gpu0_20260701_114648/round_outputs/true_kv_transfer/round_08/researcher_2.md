[JSON]
{
  "researcher": "researcher_2",
  "findings": [
    "UpgradeState 需包含已购买的升级类型，与 PlayerState 分离以保持旧关卡兼容",
    "金币消耗需对应升级成本，如体力上限+2需消耗50金币",
    "风道掌控允许玩家选择是否接受 wind_lane 推动，需修改 resolve_tile_effect 逻辑",
    "雷暴抗性减少 storm 体力伤害-1但不低于1，需在 resolve_tile_effect 中调整伤害计算",
    "升级系统需在配送日结算后触发，不影响当前配送日",
    "未购买升级时，所有系统行为与第7轮一致"
  ],
  "dependencies": [
    "PlayerState 需扩展添加 upgrade_state 字段",
    "GameConfig 需添加 upgrade_cost 字段定义各升级成本",
    "resolve