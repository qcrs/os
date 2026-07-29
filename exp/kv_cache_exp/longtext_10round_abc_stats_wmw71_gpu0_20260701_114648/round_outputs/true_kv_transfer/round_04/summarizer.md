[JSON]
{
  "round": 4,
  "id": 9004,
  "answer": "@round[4] @feature_scope[storm_shield_fragility] @depends_on[1,2,3] @new_systems[storm,shield,package_damage,risk_roll] @deliverable[incremental_spec]",
  "round_summary": "新增风暴、护盾和包裹损坏系统。风暴触发时优先扣盾，护盾为0时扣体力。脆弱包裹有30%概率损坏。风道推动进入风暴仍触发风险。新增shield字段到PlayerState，fragility字段到OrderState，damaged状态到PackageState。设计mock风险判定函数以支持测试。测试点覆盖风暴扣盾、护盾耗尽后体力扣减、脆弱包裹损坏、风道推入风暴风险、风险判定可测试性等。",
  "carried_state": [
    "PlayerState需扩展添加shield字段",
    "OrderState需新增fragility字段",
    "PackageState需新增damaged状态",
    "GameConfig需添加shield_initial参数",
    "resolve_tile_effect函数需处理storm触发逻辑",
    "deliver_orders函数需检查包裹损坏状态",
    "新增mock_risk_roll函数支持测试"
  ],
  "test_points": [
    "玩家进入storm格时护盾减少1",
    "护盾为0时进入storm格扣减3体力",
    "脆弱包裹在storm格有30%概率损坏",
    "风道推动进入storm格仍触发风险",
    "风险判定函数可注入随机种子",
    "损坏包裹交付时获得最低奖励",
    "风暴扩大时检查玩家位置",
    "风暴结束时恢复部分护盾"
  ]
}
[JSON]
{
  "round": 4,
  "id