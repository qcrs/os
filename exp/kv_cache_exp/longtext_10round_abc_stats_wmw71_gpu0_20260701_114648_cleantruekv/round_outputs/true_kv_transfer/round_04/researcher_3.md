[JSON]
{
  "researcher": "researcher_3",
  "findings": [
    "新增storm字段，进入storm格时先扣shield，shield为0再扣stamina",
    "package_fragility字段用于判定脆弱包裹损坏概率",
    "damaged状态记录包裹是否损坏",
    "风险判定逻辑需可测试，支持注入随机种子或mock判定",
    "风暴格停留判定：若风道推动至storm格，仍触发一次storm风险",
    "交付奖励优先级：同时迟到和损坏时，仅给予最低安慰奖励",
    "风暴触发顺序：先扣shield，再扣stamina，最后判定包裹损坏",
    "风暴格停留判定需与风道逻辑交互，确保风险触发"
  ],
  "dependencies": [
    "map数据结构需包含storm类型tile",
    "player_state需包含shield字段",
    "order_state需