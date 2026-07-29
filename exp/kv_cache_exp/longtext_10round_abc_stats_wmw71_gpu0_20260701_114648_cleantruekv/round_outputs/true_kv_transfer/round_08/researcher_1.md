[JSON]
{
  "researcher": "researcher_1",
  "findings": [
    "UpgradeState 需要存储已购买的升级列表，与 PlayerState 和 GameConfig 分离，确保旧关卡兼容",
    "金币消耗需根据升级类型设定，如体力上限+2需50金币，cargo_slots+1需30金币",
    "风道掌控和雷暴抗性属于可选升级，需在 GameConfig 中定义默认值，未购买时保持原行为",
    "升级应修改 PlayerState 的初始值，如增加 stamina_max、shield_max、cargo_slots_max",
    "雷暴抗性需限制最低为1，避免护盾值异常"
  ],
  "dependencies": [
    "PlayerState 需包含 stamina_max, shield_max, cargo_slots_max 字段",
    "GameConfig 需定义 upgrade_cost 字典，