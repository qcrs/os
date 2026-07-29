[JSON]
{
  "researcher": "researcher_1",
  "findings": [
    "第3轮已实现风道和云墙，需在此基础上添加雷暴系统",
    "需新增shield字段用于护盾管理",
    "package_fragility字段需记录包裹易损状态",
    "damaged状态需在订单中跟踪",
    "风暴触发顺序为：先扣护盾，护盾为0再扣体力",
    "风道推动至风暴格仍触发风险判定",
    "交付奖励优先级：同时迟到和损坏时仅给予最低奖励",
    "需设计可测试的随机损坏逻辑，支持注入随机种子或mock判定"
  ],
  "dependencies": [
    "地图数据结构需包含storm tile类型",
    "玩家状态需包含shield字段",
    "订单数据需包含package_fragility和damaged字段",
    "风险判定逻辑