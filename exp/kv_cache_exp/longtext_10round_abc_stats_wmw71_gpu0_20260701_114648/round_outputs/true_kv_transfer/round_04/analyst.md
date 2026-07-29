[JSON]
{
  "analysis": "在第3轮基础上新增雷暴（storm）、护盾（shield）和包裹损坏（package_damage）系统。雷暴触发时优先扣除护盾，护盾为0时扣体力。脆弱包裹有概率损坏。需处理风道推入雷暴时仍触发风险。新增shield字段到PlayerState，fragility字段到OrderState，damaged状态到PackageState。设计风险判定逻辑，允许注入随机种子或mock测试。测试点包括雷暴扣盾、护盾耗尽后体力扣减、脆弱包裹损坏、风道推入雷暴风险、风险判定可测试性等。",
  "round_summary": "新增风暴、护盾和包裹损坏系统。风暴触发时优先扣盾，护盾为0时扣体力。脆弱包裹有30%概率损坏。风道推动进入风暴仍触发风险。新增shield字段到PlayerState，fragility字段到OrderState，damaged状态到PackageState。设计mock风险判定函数以支持测试。测试点覆盖风暴扣盾、护盾耗尽后体力扣减、脆弱包裹损坏、风道推入风暴风险、风险判定可测试性等。",
  "car