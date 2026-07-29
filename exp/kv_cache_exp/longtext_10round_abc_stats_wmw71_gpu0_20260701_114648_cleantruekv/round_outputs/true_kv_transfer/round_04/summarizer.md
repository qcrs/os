[JSON]
{
  "answer": "@round[4] @feature_scope[storm_shield_fragility] @depends_on[1,2,3] @new_systems[storm,shield,package_damage,risk_roll] @deliverable[incremental_spec]",
  "analysis": "在第3轮基础上新增雷暴（storm）、护盾（shield）和包裹损坏（package_damage）系统。实现风暴触发机制：进入storm格时先扣护盾，护盾为0再扣体力。脆弱包裹有30%概率损坏。风道推动至storm格仍触发风险。新增shield字段，package_fragility字段，damaged状态。处理交付奖励优先级：同时迟到和损坏时，仅给予最低奖励。设计可测试的随机损坏逻辑，允许注入随机种子或mock判定。新增测试点：风暴触发顺序、护盾消耗、体力扣除、包裹损坏概率、风道风暴交互、风险判定可测试性、损坏订单交付奖励、风暴格停留判定。",
  "carried_state": [
    "map",
    "player_position",
    "orders",
    "delivery_status",
    "time_left",
    "stamina",
    "wind_lane",
    "cloud_wall"
  ],
  "output_hash": "d4a2c8f1a3e6b7d9",
  "output_chars": 345
}
[JSON]
{
  "answer": "@round[4] @feature_scope[storm_shield_fragility] @depends_on[1,2,3] @new_systems[storm,shield,package_damage,risk_roll] @deliverable[incremental_spec]",
  "analysis": "在第3轮基础上新增雷暴（storm）、护盾（shield）和包裹损坏（package_damage）系统。实现风暴触发机制