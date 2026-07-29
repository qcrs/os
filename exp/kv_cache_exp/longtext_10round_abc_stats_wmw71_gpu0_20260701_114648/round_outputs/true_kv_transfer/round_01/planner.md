[JSON]
{
  "plan": "设计第1轮MVP，实现地图、玩家移动、核心订单和交付判定。首先定义GameConfig、LevelState、PlayerState、OrderState的最小字段。地图使用12x12二维数组表示，包含workshop、air、cloud_wall、customer四种tile。玩家移动时检查tile类型，不可穿越cloud_wall。核心订单状态从created到delivered需触发交付逻辑。测试点包括移动边界、tile碰撞、订单交付、状态变化和基础流程。",
  "sub_queries": [
    "如何定义GameConfig的最小字段以支持地图和订单？",
    "PlayerState需要哪些属性来跟踪移动和订单状态？",
    "OrderState如何表示核心订单从创建到