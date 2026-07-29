[JSON]
{
  "plan": "在第5轮基础上新增补给站（supply）和三个道具：battery（恢复体力）、shield_cell（恢复护盾）、parcel_wrap（保护脆弱包裹）。补给站触发方式为玩家移动至supply tile时自动使用，每次恢复有限制（体力不超过上限，护盾不超过上限）。道具库存限制为最多携带2个，不占货舱格。battery手动使用，shield_cell手动使用，parcel_wrap自动触发保护。新增supply tile类型，修改订单交付逻辑以处理道具保护。测试点包括补给站触发、道具使用、库存限制、保护效果等。",
  "sub_queries": [
    "如何设计supply tile的触发机制和恢复上限？",
    "如何实现道具