[JSON]
{
  "researcher": "researcher_2",
  "findings": [
    "UpgradeState 需要存储已购买的升级列表，与 PlayerState 和 GameConfig 分离，确保旧关卡兼容",
    "金币消耗需根据升级类型设定，如体力上限+2需50金币，cargo_slots+1需30金币",
    "风道掌控和雷暴抗性属于可选升级，需在升级菜单中显示，且不影响原有行为",
    "升级后 GameConfig 或 PlayerState 的初始值需动态调整，例如增加 stamina_max 或 shield_max",
    "未购买升级时，风道推动和雷暴伤害应保持第7轮行为"
  ],
  "dependencies": [
    "PlayerState 需包含 upgrade_progress 字段",
    "GameConfig 需包含 upgrade_cost 字段",
    "LevelState 需